from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import ExecutorModel, IssueModel, MissionIssueSnapshotModel, MissionModel, TaskModel
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub
from gateway.app.services.mission_types import MissionState, MissionTransitionError
from shared.protocol import AgentEngine, DeliveryRequest, SubmitTaskRequest, TaskMode, TaskPriority


@dataclass(frozen=True)
class IssueSnapshot:
    issue: IssueModel
    canonical: dict
    canonical_hash: str


@dataclass(frozen=True)
class ResolvedIssueMission:
    mission: MissionModel
    task: TaskModel | None
    snapshot: IssueSnapshot
    stored_snapshot: MissionIssueSnapshotModel | None
    reused: bool
    drift_detected: bool


def _json_list(raw: str | None) -> list:
    try:
        parsed = json.loads(raw or "[]")
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def build_issue_snapshot(issue: IssueModel) -> IssueSnapshot:
    canonical = {
        "provider": issue.provider,
        "issue_id": issue.id,
        "external_id": issue.external_id,
        "revision": issue.revision,
        "title": issue.title,
        "description": issue.description or "",
        "comments": [],
        "labels": sorted(str(item) for item in _json_list(issue.labels_json)),
        "dependencies": sorted(str(item) for item in _json_list(issue.dependencies_json)),
        "status": issue.status,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return IssueSnapshot(issue=issue, canonical=canonical, canonical_hash=hashlib.sha256(encoded).hexdigest())


async def resolve_issue_reference(session: AsyncSession, project_id: str, issue_ref: str) -> IssueModel:
    text = issue_ref.strip()
    if text.startswith("local:"):
        text = text.split(":", 1)[1]
    elif text.startswith("gh:"):
        number = text.split(":", 1)[1]
        result = await session.execute(
            select(IssueModel)
            .where(IssueModel.project_id == project_id)
            .where(IssueModel.provider == "github")
            .where(IssueModel.external_id == number)
        )
        issue = result.scalar_one_or_none()
        if issue is None:
            raise ValueError("unknown_issue")
        return issue

    issue = await session.get(IssueModel, text)
    if issue is not None and issue.project_id == project_id:
        return issue

    result = await session.execute(
        select(IssueModel)
        .where(IssueModel.project_id == project_id)
        .where(or_(IssueModel.external_id == text, IssueModel.id == text))
        .order_by(IssueModel.created_at.desc(), IssueModel.id.desc())
    )
    issue = result.scalars().first()
    if issue is None:
        raise ValueError("unknown_issue")
    return issue


def default_objective(snapshot: IssueSnapshot) -> str:
    issue = snapshot.issue
    parts = [
        f"Resolve issue {issue.provider}:{issue.external_id or issue.id}: {issue.title}",
        "",
        "Use the immutable issue snapshot as the planning basis. Do not close or update the source issue merely because the agent process succeeds.",
    ]
    description = issue.description or ""
    if description:
        parts.extend(["", "Issue description:", description])
    dependencies = snapshot.canonical.get("dependencies") or []
    if dependencies:
        parts.extend(["", "Dependencies:", ", ".join(str(item) for item in dependencies)])
    return "\n".join(parts)


def _intent_fingerprint(
    *,
    project_id: str,
    issue: IssueModel,
    objective: str,
    mode: TaskMode,
    priority: TaskPriority,
    engine: AgentEngine,
    delivery: DeliveryRequest | None,
) -> str:
    payload = {
        "project_id": project_id,
        "provider": issue.provider,
        "issue_id": issue.id,
        "external_id": issue.external_id,
        "objective": objective,
        "mode": mode.value,
        "priority": priority.value,
        "engine": engine.value,
        "delivery": delivery.model_dump(mode="json") if delivery else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mission_matches_intent(
    mission: MissionModel,
    *,
    objective: str | None,
    mode: TaskMode,
    priority: TaskPriority,
    engine: AgentEngine,
    delivery: DeliveryRequest | None,
) -> bool:
    delivery_json = delivery.model_dump_json() if delivery is not None else None
    return (
        (objective is None or mission.objective == objective)
        and mission.requested_mode == mode.value
        and mission.priority == priority.value
        and (mission.selected_engine or engine.value) == engine.value
        and mission.delivery_json == delivery_json
    )


async def _record_drift(
    session: AsyncSession,
    mission: MissionModel,
    *,
    stored_snapshot: MissionIssueSnapshotModel,
    current_snapshot: IssueSnapshot,
    actor_id: str | None,
) -> None:
    mission.last_error = "Source issue changed since this mission was planned; operator replan decision required."
    try:
        await store.transition_mission_state(
            session,
            mission,
            MissionState.WAITING_HUMAN.value,
            actor_id=actor_id,
            event_type="mission.issue_drift_detected",
            payload={
                "snapshot_id": stored_snapshot.id,
                "planned_hash": stored_snapshot.canonical_hash,
                "current_hash": current_snapshot.canonical_hash,
                "planned_revision": stored_snapshot.issue_revision,
                "current_revision": current_snapshot.issue.revision,
            },
        )
    except MissionTransitionError:
        await store.append_mission_event(
            session,
            mission.id,
            "mission.issue_drift_detected",
            state=mission.state,
            actor_id=actor_id,
            payload={
                "snapshot_id": stored_snapshot.id,
                "planned_hash": stored_snapshot.canonical_hash,
                "current_hash": current_snapshot.canonical_hash,
                "planned_revision": stored_snapshot.issue_revision,
                "current_revision": current_snapshot.issue.revision,
                "condition": "waiting_human_unavailable_from_current_state",
            },
        )
        mission.updated_at = datetime.now(timezone.utc)
        mission.revision += 1
    await session.commit()
    await session.refresh(mission)


async def resolve_issue_as_mission(
    session: AsyncSession,
    *,
    hub: AgentHub,
    project_id: str,
    issue_ref: str,
    executor: ExecutorModel,
    objective: str | None,
    mode: TaskMode = TaskMode.IMPLEMENT,
    priority: TaskPriority = TaskPriority.NORMAL,
    engine: AgentEngine = AgentEngine.CODEX,
    timeout_seconds: int = 3600,
    run_when_available: bool = True,
    delivery: DeliveryRequest | None = None,
    force_new: bool = False,
    requested_by_user_id: str | None = None,
    requested_by_email: str | None = None,
    can_approve_push: bool = False,
) -> ResolvedIssueMission:
    issue = await resolve_issue_reference(session, project_id, issue_ref)
    snapshot = build_issue_snapshot(issue)
    mission_objective = objective or default_objective(snapshot)

    if not force_new:
        fingerprint = _intent_fingerprint(
            project_id=project_id,
            issue=issue,
            objective=mission_objective,
            mode=mode,
            priority=priority,
            engine=engine,
            delivery=delivery,
        )
        for stored_snapshot, mission in await store.find_active_issue_mission_snapshots(
            session, project_id=project_id, issue_id=issue.id, provider=issue.provider
        ):
            if not _mission_matches_intent(
                mission, objective=objective, mode=mode, priority=priority, engine=engine, delivery=delivery
            ):
                continue
            task = await store.get_mission_active_task(session, mission)
            if stored_snapshot.canonical_hash != snapshot.canonical_hash:
                await _record_drift(
                    session,
                    mission,
                    stored_snapshot=stored_snapshot,
                    current_snapshot=snapshot,
                    actor_id=requested_by_user_id,
                )
                await store.append_mission_event(
                    session,
                    mission.id,
                    "mission.issue_resolution_reused_with_drift",
                    state=mission.state,
                    task_id=task.id if task else None,
                    actor_id=requested_by_user_id,
                    payload={"intent_hash": fingerprint},
                )
                await session.commit()
                return ResolvedIssueMission(mission, task, snapshot, stored_snapshot, True, True)
            await store.append_mission_event(
                session,
                mission.id,
                "mission.issue_resolution_reused",
                state=mission.state,
                task_id=task.id if task else None,
                actor_id=requested_by_user_id,
                payload={"intent_hash": fingerprint},
            )
            await session.commit()
            return ResolvedIssueMission(mission, task, snapshot, stored_snapshot, True, False)

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(7200, 2 * timeout_seconds))
    source_ref = f"local:{issue.id}"
    if issue.provider == "github" and issue.external_id:
        source_ref = f"gh:{issue.external_id}"
    task = await store.create_task(
        session,
        SubmitTaskRequest(
            executor_id=executor.id,
            project_id=project_id,
            instruction=mission_objective,
            mode=mode,
            timeout_seconds=timeout_seconds,
            priority=priority,
            run_when_available=run_when_available,
            expires_at=expires_at,
            engine=engine,
            issue_ref=source_ref,
            delivery=delivery,
        ),
        executor_online=hub.is_connected(executor.id),
        requested_by_user_id=requested_by_user_id,
        requested_by_email=requested_by_email,
        can_approve_push=can_approve_push,
    )
    mission = await store.get_mission_for_projects(session, task.mission_id or task.id, None)
    if mission is None:
        raise RuntimeError("mission_not_created")
    stored = MissionIssueSnapshotModel(
        id=str(uuid4()),
        mission_id=mission.id,
        project_id=project_id,
        issue_id=issue.id,
        provider=issue.provider,
        external_id=issue.external_id,
        issue_revision=issue.revision,
        canonical_hash=snapshot.canonical_hash,
        title=issue.title,
        description=issue.description,
        status=issue.status,
        labels_json=json.dumps(snapshot.canonical["labels"], ensure_ascii=True),
        dependencies_json=json.dumps(snapshot.canonical["dependencies"], ensure_ascii=True),
        snapshot_json=json.dumps(snapshot.canonical, sort_keys=True, ensure_ascii=True),
        created_at=datetime.now(timezone.utc),
    )
    session.add(stored)
    await store.append_mission_event(
        session,
        mission.id,
        "mission.issue_snapshot_captured",
        state=mission.state,
        task_id=task.id,
        actor_id=requested_by_user_id,
        payload={
            "snapshot_id": stored.id,
            "issue_id": issue.id,
            "provider": issue.provider,
            "external_id": issue.external_id,
            "canonical_hash": snapshot.canonical_hash,
            "issue_revision": issue.revision,
        },
    )
    await session.commit()
    if hasattr(hub, "dispatch_available"):
        await hub.dispatch_available(task.executor_id)
    else:
        dispatch_payload = await hub.dispatch_next(task.executor_id)
        if dispatch_payload is not None:
            from gateway.app.services.agent_hub import hub_envelope

            await hub.send(task.executor_id, hub_envelope(task.executor_id, "task.dispatch", dispatch_payload))
    await session.refresh(task)
    await session.refresh(mission)
    return ResolvedIssueMission(mission, task, snapshot, stored, False, False)
