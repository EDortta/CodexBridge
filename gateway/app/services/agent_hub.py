from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import async_sessionmaker

from gateway.app.models.entities import ExecutorModel
from gateway.app.services import store
from shared.protocol import (
    AgentEnvelope,
    AgentMessageType,
    DEFAULT_CANCEL_REPLAY_MAX_AGE_SECONDS,
    DEFAULT_CONTROL_REPLAY_MAX_AGE_SECONDS,
    TaskState,
)


# Which control message to resend on reconnect for each pending state a task
# can be stuck in. Kept next to list_tasks_requiring_control_replay's states
# in store.py — both name the same three transitional states on purpose.
_CONTROL_REPLAY_MESSAGE: dict[TaskState, AgentMessageType] = {
    TaskState.PAUSING: AgentMessageType.TASK_PAUSE,
    TaskState.RESUMING: AgentMessageType.TASK_RESUME,
    TaskState.RESTARTING: AgentMessageType.TASK_RESTART,
}


@dataclass
class AgentConnection:
    executor_id: str
    websocket: WebSocket
    connected_at: datetime


class AgentHub:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        cancel_replay_max_age_seconds: int = DEFAULT_CANCEL_REPLAY_MAX_AGE_SECONDS,
        control_replay_max_age_seconds: int = DEFAULT_CONTROL_REPLAY_MAX_AGE_SECONDS,
    ):
        self.session_factory = session_factory
        self.cancel_replay_max_age_seconds = cancel_replay_max_age_seconds
        self.control_replay_max_age_seconds = control_replay_max_age_seconds
        self.connections: dict[str, AgentConnection] = {}
        self.running_tasks: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connections

    async def register(self, executor_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self.connections[executor_id] = AgentConnection(
                executor_id=executor_id,
                websocket=websocket,
                connected_at=datetime.now(timezone.utc),
            )
            self.running_tasks.setdefault(executor_id, set())
        async with self.session_factory() as session:
            await store.mark_executor_connected(session, executor_id, True)
            replay = await store.list_tasks_requiring_cancel_replay(
                session, executor_id, max_age_seconds=self.cancel_replay_max_age_seconds
            )
            control_replay = await store.list_tasks_requiring_control_replay(
                session, executor_id, max_age_seconds=self.control_replay_max_age_seconds
            )
        if replay:
            self.running_tasks.setdefault(executor_id, set()).update(task.id for task in replay)
            for task in replay:
                await self.send(
                    executor_id,
                    hub_envelope(executor_id, AgentMessageType.TASK_CANCEL.value, {"task_id": task.id}),
                )
        if control_replay:
            self.running_tasks.setdefault(executor_id, set()).update(task.id for task in control_replay)
            for task in control_replay:
                message_type = _CONTROL_REPLAY_MESSAGE[TaskState(task.state)]
                await self.send(
                    executor_id,
                    hub_envelope(executor_id, message_type.value, {"task_id": task.id}),
                )

    async def unregister(self, executor_id: str) -> None:
        async with self._lock:
            self.connections.pop(executor_id, None)
        async with self.session_factory() as session:
            try:
                await store.mark_executor_connected(session, executor_id, False)
            except ValueError:
                return

    async def force_close(self, executor_id: str) -> bool:
        """Close `executor_id`'s live socket, if it has one. Issue #76.

        This is what makes `POST /api/v1/nodes/{id}/revoke` actually revoke
        something instead of only refusing the *next* handshake
        (`store.revoke_node` already does that part). Without this call, a
        socket that was open when the operator revoked stays open — every
        message it sends keeps being processed, and it keeps receiving
        dispatched work — until it happens to disconnect on its own. Decision
        #4 of issue #76 names this in writing: "revogar fecha o socket... sem
        isso, revogar é teatro".

        `4403` is the same code the handshake itself uses for "token não
        confere com o registro" (`docs/protocol.md`) — this cut adds no new
        close code for revocation; the meaning ("this credential is no longer
        honoured") is the same one either way, and `4404`/`4401` would be
        actively wrong here (the executor id and its previous credential were
        both real).

        Returns whether a connection was actually closed, so the caller can
        tell "revoked and dropped a live socket" from "revoked, nothing was
        connected" without inspecting `is_connected` separately in a way that
        could race against `register`/`unregister`.

        Removes from `self.connections` directly rather than calling
        `unregister`: `unregister` also flips `ExecutorModel.connected` to
        `False` via `store.mark_executor_connected`, which is redundant here
        (`revoke_node` already set `enabled=False` and the row will read as
        offline once `last_seen_at` ages out) and would open a second,
        unnecessary database round trip on the hot path of closing a socket
        the caller is about to also revoke in the same request.
        """
        async with self._lock:
            connection = self.connections.pop(executor_id, None)
        if connection is None:
            return False
        try:
            await connection.websocket.close(code=4403)
        except Exception:
            # The socket may already be in the process of closing on its own
            # (a race with a client disconnect). Either way it is out of
            # `self.connections` now, which is the property that matters: the
            # next envelope this connection tries to send has nowhere to go.
            pass
        return True

    async def send(self, executor_id: str, envelope: AgentEnvelope) -> None:
        connection = self.connections[executor_id]
        await connection.websocket.send_json(envelope.model_dump(mode="json"))

    async def dispatch_next(self, executor_id: str) -> dict[str, Any] | None:
        if executor_id not in self.connections:
            return None
        async with self.session_factory() as session:
            executor = await session.get(ExecutorModel, executor_id)
            if executor is None:
                return None
            metadata = json.loads(executor.metadata_json)
            if len(self.running_tasks.setdefault(executor_id, set())) >= int(metadata.get("max_concurrent_tasks", 1)):
                return None
            task = await store.next_dispatchable_task(session, executor_id)
            if task is None:
                return None
            await store.update_task_state(session, task.id, TaskState.RUNNING)
            self.running_tasks.setdefault(executor_id, set()).add(task.id)
            payload: dict[str, Any] = {
                "task_id": task.id,
                "project_id": task.project_id,
                "instruction": task.instruction,
                "mode": task.mode,
                "timeout_seconds": task.timeout_seconds,
                "continue_session_id": task.session_id,
                # WK-20260830-chatgpt-entry-provider-and-delivery. `engine`
                # always present (column default "codex") so an executor that
                # reads `payload.get("engine", "codex")` behaves identically
                # whether or not this key is here at all -- included anyway
                # for an executor that wants to see it explicitly, and
                # because `issue_ref`/`delivery` being present without
                # `engine` would be a stranger payload shape than either
                # being absent together.
                "engine": task.engine,
                "issue_ref": task.issue_ref,
            }
            if task.delivery_json:
                payload["delivery"] = json.loads(task.delivery_json)
            return payload

    async def dispatch_available(self, executor_id: str) -> None:
        """Dispatches the next queued/waiting task to `executor_id`, if one is
        ready, and sends it right now.

        Shared entry point for every caller that moves a task into a
        dispatchable state (`QUEUED`/`WAITING_EXECUTOR`) and needs the queue
        nudged in the same turn, rather than left for an unrelated event to
        discover it later. `dispatch_next` already gates on the executor being
        connected (`executor_id not in self.connections`) and on its
        concurrency slot, so callers don't repeat either check themselves —
        that hand-rolled `is_connected` + `dispatch_next` + `send` sequence is
        exactly what issues #18/#20 found duplicated (correctly, in the MCP
        transport's `approve_codex_task`) and missing (in the REST
        `POST /api/v1/decisions/{id}/approve`, `gateway/app/api/routes/
        decisions.py`). Both callers now share this method instead of a third
        caller re-implementing the sequence by hand.
        """
        dispatch_payload = await self.dispatch_next(executor_id)
        if dispatch_payload is not None:
            await self.send(
                executor_id,
                hub_envelope(executor_id, AgentMessageType.TASK_DISPATCH.value, dispatch_payload),
            )

    async def mark_task_finished(self, executor_id: str, task_id: str) -> None:
        """Releases the slot `task_id` held and, if the executor is still
        connected, immediately dispatches whatever is next in its queue.

        The dispatch used to be hand-rolled at each caller that frees a slot;
        only the `TASK_RESULT` branch in `gateway/app/main.py` remembered to
        do it. `task.cancelled`'s ack, the `known=False` control-ack ghost
        resolution, HTTP `/stop` and MCP `cancel_codex_task` all free a slot
        through this same method and none of them re-dispatched — a
        connected, idle executor sat on queued work until an unrelated event
        (a later reconnect, a new submit) nudged the queue, the exact
        starvation issue #17 itself is about (issue #17 council round 2, "the
        sweep skeptic" / "the second caller"). Putting the dispatch here means
        every caller gets it, including ones not yet written.
        """
        self.running_tasks.setdefault(executor_id, set()).discard(task_id)
        await self.dispatch_available(executor_id)


def hub_envelope(executor_id: str, message_type: str, payload: dict) -> AgentEnvelope:
    """Build a message for an executor.

    Lives here rather than in the MCP server because the envelope is a property
    of the agent channel, not of the transport that happens to ask for it. The
    HTTP sessions API sends `task.cancel` too, and a second hand-rolled
    constructor there was already one field short — `AgentEnvelope` requires
    `message_id`, `executor_id` and `sent_at`, and omitting them fails at
    validation time rather than at review time.
    """
    return AgentEnvelope(
        message_id=str(uuid4()),
        executor_id=executor_id,
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType(message_type),
        payload=payload,
    )
