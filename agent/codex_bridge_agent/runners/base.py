"""The provider-neutral surface the executor dispatches a task through.

WK-20260830-chatgpt-entry-provider-and-delivery, delivered as issue #41a
(sibling of #41 "generic development-agent provider contract" -- see that
issue's body for why the residue, not this slice, keeps the #41 number).

This `Runner` protocol extracts exactly the surface `AgentService`
(`agent/codex_bridge_agent/service.py`) already calls on the one runner it
used to hold directly -- nothing invented, nothing added "for symmetry".
`CodexRunner` (`runners/codex.py`) is that surface, moved literally; it is
the reference a new runner (`runners/claude.py`, issue #66) has to match.

`is_known` is LOAD-BEARING, not incidental: the gateway's ghost-task branch
(`gateway/app/main.py:handle_task_ack`, issue #17) tells "already resolved on
a live process" apart from "this runner never heard of it" by the `known`
flag a runner's `is_known()` produces. Its contract does not change here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol, runtime_checkable


LogSender = Callable[[str, str], Awaitable[None]]


@dataclass
class RunningTask:
    """A live subprocess plus the control flags `pause`/`cancel`/`restart`

    set from outside its own run loop. Provider-neutral: SIGSTOP/SIGCONT and
    `terminate()`/`kill()` work the same on any subprocess regardless of
    which CLI it runs, so both `runners/codex.py` and `runners/claude.py`
    share this shape rather than each declaring their own.
    """

    process: asyncio.subprocess.Process
    paused: bool = False
    cancel_requested: bool = False
    restart_requested: bool = False
    continue_session_id: str | None = None
    raw_events: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class RunnerCapabilities:
    """What a provider can and cannot do, declared rather than assumed.

    `sandbox_enforced_by` is the honest field: Codex's `-s read-only` is an
    OS-level sandbox the CLI itself enforces (`"os-sandbox"`); Claude Code has
    no equivalent flag and is contained only by a `--disallowedTools`
    denylist the EXECUTOR builds (`"provider-flags"`). Pretending the two are
    equivalent is exactly the "runtime surprise" issue #41 exists to prevent
    (council finding F29 makes the same point about `cost_class`: report what
    is true, not what would be convenient).

    `resume_token_kind` documents what kind of value `run_task`'s returned
    `provider_run_ref` actually is for this engine ("codex-thread-id",
    "claude-session-id", or "none" when `supports_resume` is False) -- purely
    descriptive, never interpreted by the pool.
    """

    engine: str
    supports_resume: bool
    resume_token_kind: str
    supports_sandbox: bool
    sandbox_modes: frozenset[str]
    sandbox_enforced_by: str
    supports_pause: bool
    supports_restart: bool
    streams_events: bool
    reports_cost: bool
    cost_class: str
    env_allowlist: frozenset[str]


@runtime_checkable
class Runner(Protocol):
    """One provider's implementation of "run this instruction, report back".

    Every method here mirrors a call site `agent/codex_bridge_agent/service.py`
    already makes against `CodexRunner` before this abstraction existed --
    see that file's `_run_once` (the four control branches) and
    `_handle_dispatch` (`run_task`).
    """

    def capabilities(self) -> RunnerCapabilities: ...

    def is_known(self, task_id: str) -> bool: ...

    def mark_dispatched(self, task_id: str) -> None: ...

    def forget(self, task_id: str) -> None: ...

    async def cancel(self, task_id: str) -> bool: ...

    async def pause(self, task_id: str) -> bool: ...

    async def resume(self, task_id: str) -> bool: ...

    async def restart(self, task_id: str) -> bool: ...

    async def run_task(
        self,
        task_id: str,
        project_root: Path,
        instruction: str,
        timeout_seconds: int,
        continue_session_id: str | None,
        send_log: LogSender,
        sandbox: str,
    ) -> dict: ...


class EngineNotImplementedError(RuntimeError):
    """A dispatch named an `AgentEngine` value with no real `Runner` behind it.

    Never an `AttributeError`, never a silent fallback to Codex -- the seven
    CLIs installed on the executor host are candidates
    (`shared.protocol.AgentEngine`), not commitments. `str(error)` is exactly
    `f"engine_not_implemented:{engine}"`, which is what `_handle_dispatch`
    reports back as the task's `error` field.
    """

    def __init__(self, engine: str) -> None:
        super().__init__(f"engine_not_implemented:{engine}")
        self.engine = engine
