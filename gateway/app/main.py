from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.config import settings
from gateway.app.core.logging import configure_logging
from gateway.app.core.registry import load_registry
from gateway.app.db.base import Base
from gateway.app.db.session import SessionLocal, engine, get_session
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import metrics, store
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import AgentEnvelope, AgentMessageType, TaskState
from shared.security import sanitize_log_line, secure_compare


configure_logging()
app = FastAPI(title="CodexBridge Gateway", version="0.1.0")
hub = AgentHub(SessionLocal)


async def require_mcp_auth(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization.removeprefix("Bearer ").strip()
    if not secure_compare(token, settings.mcp_bearer_token):
        raise HTTPException(status_code=403, detail="invalid_bearer_token")


@app.on_event("startup")
async def startup() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    registry = load_registry(settings.registry_file)
    async with SessionLocal() as session:
        await store.upsert_registry(session, registry.executors, registry.projects)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    return Response(metrics.render_metrics(), media_type="text/plain; version=0.0.4")


@app.post("/mcp", dependencies=[Depends(require_mcp_auth)])
async def mcp_endpoint(request: Request, session: AsyncSession = Depends(get_session)) -> Response:
    body = await request.json()
    payload = await handle_mcp_call(body, session, hub)
    return Response(content=json.dumps(payload), media_type="application/json")


@app.websocket("/agent/ws")
async def agent_ws(
    websocket: WebSocket,
    executor_id: str,
    token: str,
) -> None:
    async with SessionLocal() as session:
        executor = await session.get(store.ExecutorModel, executor_id)
        if executor is None:
            await websocket.close(code=4404)
            return
        metadata = json.loads(executor.metadata_json)
        if not secure_compare(token, metadata["machine_token"]):
            await websocket.close(code=4403)
            return

    await websocket.accept()
    await hub.register(executor_id, websocket)
    await websocket.send_json(
        AgentEnvelope(
            message_id="hello-ack",
            executor_id=executor_id,
            sent_at=datetime.now(timezone.utc),
            type=AgentMessageType.HELLO_ACK,
            payload={"accepted": True},
        ).model_dump(mode="json")
    )
    dispatch_payload = await hub.dispatch_next(executor_id)
    if dispatch_payload is not None:
        await hub.send(
            executor_id,
            AgentEnvelope(
                message_id=f"dispatch-{dispatch_payload['task_id']}",
                executor_id=executor_id,
                sent_at=datetime.now(timezone.utc),
                type=AgentMessageType.TASK_DISPATCH,
                payload=dispatch_payload,
            ),
        )
    try:
        while True:
            raw = await websocket.receive_json()
            envelope = AgentEnvelope.model_validate(raw)
            async with SessionLocal() as session:
                is_new = await store.store_message_receipt(session, envelope.message_id, envelope.executor_id, envelope.type.value)
                if not is_new:
                    continue
                if envelope.type == AgentMessageType.HEARTBEAT:
                    await store.mark_executor_connected(session, envelope.executor_id, True)
                elif envelope.type == AgentMessageType.TASK_LOG:
                    await store.append_log(
                        session,
                        envelope.payload["task_id"],
                        int(envelope.payload["offset"]),
                        envelope.payload["stream"],
                        sanitize_log_line(envelope.payload["line"]),
                    )
                elif envelope.type == AgentMessageType.TASK_RESULT:
                    final_state = TaskState(envelope.payload["final_state"])
                    await store.store_result(session, envelope.payload["task_id"], envelope.payload, final_state)
                    await hub.mark_task_finished(envelope.executor_id, envelope.payload["task_id"])
                    next_payload = await hub.dispatch_next(envelope.executor_id)
                    if next_payload is not None:
                        await hub.send(
                            executor_id,
                            AgentEnvelope(
                                message_id=f"dispatch-{next_payload['task_id']}",
                                executor_id=executor_id,
                                sent_at=datetime.now(timezone.utc),
                                type=AgentMessageType.TASK_DISPATCH,
                                payload=next_payload,
                            ),
                        )
                elif envelope.type == AgentMessageType.TASK_CANCELLED:
                    await store.update_task_state(session, envelope.payload["task_id"], TaskState.CANCELLED)
                    await hub.mark_task_finished(envelope.executor_id, envelope.payload["task_id"])
    except WebSocketDisconnect:
        await hub.unregister(executor_id)

