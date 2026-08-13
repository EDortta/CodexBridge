from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import (
    AuditEventModel,
    ExecutorModel,
    MessageReceiptModel,
    OAuthAccessTokenModel,
    OAuthAuthorizationCodeModel,
    OAuthRefreshTokenModel,
    ProjectModel,
    TaskLogModel,
    TaskModel,
)
from gateway.app.services.audit import record_event
from shared.policy import evaluate_task_policy
from shared.protocol import (
    ApprovalDecision,
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskState,
)
from shared.security import hash_token


# `entity_type` of every row the credential lifecycle writes, and the only rows
# `purge_expired_audit_events` is allowed to remove. A literal at each call site
# would have made the retention window's scope a coincidence of spelling.
AUTH_ENTITY_TYPE = "auth"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def upsert_registry(
    session: AsyncSession,
    executors: list[ExecutorRegistration],
    projects: list[ProjectRegistration],
) -> None:
    for executor in executors:
        current = await session.get(ExecutorModel, executor.executor_id)
        metadata_json = json.dumps(executor.model_dump(mode="json"), ensure_ascii=True)
        if current is None:
            session.add(
                ExecutorModel(
                    id=executor.executor_id,
                    display_name=executor.display_name,
                    enabled=executor.enabled,
                    connected=False,
                    metadata_json=metadata_json,
                )
            )
        else:
            current.display_name = executor.display_name
            current.enabled = executor.enabled
            current.metadata_json = metadata_json
    for project in projects:
        current = await session.get(ProjectModel, project.project_id)
        config_json = json.dumps(project.model_dump(mode="json"), ensure_ascii=True)
        if current is None:
            session.add(
                ProjectModel(
                    id=project.project_id,
                    name=project.name,
                    path=project.path,
                    enabled=project.enabled,
                    config_json=config_json,
                )
            )
        else:
            current.name = project.name
            current.path = project.path
            current.enabled = project.enabled
            current.config_json = config_json
    await session.commit()


async def list_executors(session: AsyncSession) -> list[ExecutorModel]:
    result = await session.execute(select(ExecutorModel).order_by(ExecutorModel.id))
    return list(result.scalars())


async def list_projects(session: AsyncSession) -> list[ProjectModel]:
    result = await session.execute(select(ProjectModel).order_by(ProjectModel.id))
    return list(result.scalars())


async def list_projects_for_executor(session: AsyncSession, executor_id: str) -> list[ProjectModel]:
    executor = await session.get(ExecutorModel, executor_id)
    if executor is None:
        raise ValueError("unknown_executor")
    metadata = json.loads(executor.metadata_json)
    allowed = metadata.get("allowed_projects", [])
    if not allowed:
        return []
    result = await session.execute(select(ProjectModel).where(ProjectModel.id.in_(allowed)).order_by(ProjectModel.id))
    return list(result.scalars())


async def get_task(session: AsyncSession, task_id: str) -> TaskModel | None:
    return await session.get(TaskModel, task_id)


async def list_recent_tasks(session: AsyncSession, limit: int = 20) -> list[TaskModel]:
    result = await session.execute(select(TaskModel).order_by(TaskModel.created_at.desc()).limit(limit))
    return list(result.scalars())


async def create_task(
    session: AsyncSession,
    request: SubmitTaskRequest,
    executor_online: bool,
    continue_session_id: str | None = None,
    requested_by_user_id: str | None = None,
    requested_by_email: str | None = None,
) -> TaskModel:
    executor = await session.get(ExecutorModel, request.executor_id)
    if executor is None or not executor.enabled:
        raise ValueError("unknown_or_disabled_executor")
    project = await session.get(ProjectModel, request.project_id)
    if project is None or not project.enabled:
        raise ValueError("unknown_or_disabled_project")
    executor_metadata = json.loads(executor.metadata_json)
    if request.project_id not in executor_metadata.get("allowed_projects", []):
        raise ValueError("project_not_allowed_for_executor")
    project_config = json.loads(project.config_json)
    if request.mode.value not in project_config.get("allowed_modes", []):
        raise ValueError("mode_not_allowed_for_project")
    if request.timeout_seconds > int(project_config.get("max_timeout_seconds", request.timeout_seconds)):
        raise ValueError("timeout_exceeds_project_limit")
    policy = evaluate_task_policy(request)
    state = TaskState.QUEUED if executor_online else TaskState.WAITING_EXECUTOR
    if not executor_online and not request.run_when_available:
        raise ValueError("executor_offline")
    if request.expires_at <= datetime.now(timezone.utc):
        raise ValueError("task_already_expired")
    if not policy.approved:
        state = TaskState.AWAITING_APPROVAL
    task = TaskModel(
        id=str(uuid4()),
        executor_id=request.executor_id,
        project_id=request.project_id,
        instruction=request.instruction,
        mode=request.mode.value,
        state=state.value,
        priority=request.priority.value,
        run_when_available=request.run_when_available,
        expires_at=request.expires_at,
        timeout_seconds=request.timeout_seconds,
        created_at=datetime.now(timezone.utc),
        requested_by_user_id=requested_by_user_id,
        requested_by_email=requested_by_email,
        correlation_id=str(uuid4()),
        session_id=continue_session_id,
        approval_state=policy.level.value if state == TaskState.AWAITING_APPROVAL else None,
    )
    session.add(task)
    await record_event(
        session,
        "task",
        task.id,
        "task.created",
        {
            "state": task.state,
            "policy_level": policy.level.value,
            "requested_by_user_id": requested_by_user_id,
            "requested_by_email": requested_by_email,
        },
    )
    await session.commit()
    await session.refresh(task)
    return task


async def mark_executor_connected(session: AsyncSession, executor_id: str, connected: bool) -> None:
    executor = await session.get(ExecutorModel, executor_id)
    if executor is None:
        raise ValueError("unknown_executor")
    executor.connected = connected
    executor.last_seen_at = datetime.now(timezone.utc)
    await session.commit()


async def next_dispatchable_task(session: AsyncSession, executor_id: str) -> TaskModel | None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(TaskModel)
        .where(TaskModel.executor_id == executor_id)
        .where(TaskModel.state.in_([TaskState.QUEUED.value, TaskState.WAITING_EXECUTOR.value]))
        .where(TaskModel.expires_at > now)
        .order_by(TaskModel.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_task_state(session: AsyncSession, task_id: str, state: TaskState, error: str | None = None) -> TaskModel:
    task = await session.get(TaskModel, task_id)
    if task is None:
        raise ValueError("unknown_task")
    task.state = state.value
    if state == TaskState.RUNNING:
        task.started_at = datetime.now(timezone.utc)
    if state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED, TaskState.LOST}:
        task.completed_at = datetime.now(timezone.utc)
    if error:
        task.last_error = error
    task.revision += 1
    await record_event(session, "task", task.id, "task.state_changed", {"state": task.state, "error": error})
    await session.commit()
    await session.refresh(task)
    return task


async def append_log(session: AsyncSession, task_id: str, offset: int, stream: str, line: str) -> None:
    session.add(
        TaskLogModel(
            task_id=task_id,
            offset=offset,
            stream=stream,
            line=line,
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


async def decide_task_approval(
    session: AsyncSession,
    task_id: str,
    decision: ApprovalDecision,
    reason: str | None = None,
) -> TaskModel:
    task = await session.get(TaskModel, task_id)
    if task is None:
        raise ValueError("unknown_task")
    if task.state != TaskState.AWAITING_APPROVAL.value:
        raise ValueError("task_not_awaiting_approval")
    task.approval_state = decision.value
    task.approval_reason = reason
    if decision == ApprovalDecision.APPROVED:
        task.state = TaskState.WAITING_EXECUTOR.value
    else:
        task.state = TaskState.CANCELLED.value
        task.completed_at = datetime.now(timezone.utc)
    task.revision += 1
    await record_event(
        session,
        "task",
        task.id,
        "task.approval_decision",
        {"decision": decision.value, "reason": reason, "state": task.state},
    )
    await session.commit()
    await session.refresh(task)
    return task


async def recover_tasks_after_startup(session: AsyncSession) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    recovered = {"expired": 0, "lost": 0}
    result = await session.execute(select(TaskModel))
    for task in result.scalars():
        if task.state in {TaskState.COMPLETED.value, TaskState.FAILED.value, TaskState.CANCELLED.value, TaskState.EXPIRED.value}:
            continue
        if _as_utc(task.expires_at) <= now:
            task.state = TaskState.EXPIRED.value
            task.completed_at = now
            task.revision += 1
            await record_event(session, "task", task.id, "task.recovered", {"state": task.state})
            recovered["expired"] += 1
        elif task.state == TaskState.RUNNING.value:
            task.state = TaskState.LOST.value
            task.completed_at = now
            task.revision += 1
            await record_event(session, "task", task.id, "task.recovered", {"state": task.state})
            recovered["lost"] += 1
    await session.commit()
    return recovered


async def get_logs(session: AsyncSession, task_id: str, offset: int = 0, limit: int = 500) -> list[TaskLogModel]:
    result = await session.execute(
        select(TaskLogModel)
        .where(TaskLogModel.task_id == task_id)
        .where(TaskLogModel.offset >= offset)
        .order_by(TaskLogModel.offset.asc())
        .limit(limit)
    )
    return list(result.scalars())


async def store_result(session: AsyncSession, task_id: str, result: dict, final_state: TaskState) -> TaskModel:
    task = await session.get(TaskModel, task_id)
    if task is None:
        raise ValueError("unknown_task")
    task.result_json = json.dumps(result, ensure_ascii=True)
    task.command_json = json.dumps(result.get("command", []), ensure_ascii=True)
    task.session_id = result.get("codex_session_id")
    task.state = final_state.value
    task.completed_at = datetime.now(timezone.utc)
    task.revision += 1
    await record_event(session, "task", task.id, "task.result", {"state": task.state})
    await session.commit()
    await session.refresh(task)
    return task


async def create_oauth_authorization_code(
    session: AsyncSession,
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    user_id: str,
    scopes: list[str],
    code_challenge: str,
    code_challenge_method: str,
    expires_at: datetime,
) -> None:
    session.add(
        OAuthAuthorizationCodeModel(
            code_hash=hash_token(code),
            client_id=client_id,
            redirect_uri=redirect_uri,
            user_id=user_id,
            scopes_json=json.dumps(scopes, ensure_ascii=True),
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


async def consume_oauth_authorization_code(session: AsyncSession, code: str) -> OAuthAuthorizationCodeModel | None:
    item = await session.get(OAuthAuthorizationCodeModel, hash_token(code))
    if item is None:
        return None
    if item.consumed_at is not None:
        return None
    if _as_utc(item.expires_at) <= datetime.now(timezone.utc):
        return None
    item.consumed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(item)
    return item


async def create_oauth_access_token(
    session: AsyncSession,
    *,
    token: str,
    client_id: str,
    user_id: str,
    scopes: list[str],
    expires_at: datetime,
    grant_id: str | None = None,
) -> None:
    session.add(
        OAuthAccessTokenModel(
            token_hash=hash_token(token),
            client_id=client_id,
            user_id=user_id,
            scopes_json=json.dumps(scopes, ensure_ascii=True),
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
            grant_id=grant_id,
        )
    )
    await session.commit()


async def get_oauth_access_token(session: AsyncSession, token: str) -> OAuthAccessTokenModel | None:
    """The token row, or None when the token may not be used.

    Expiry and revocation are both refused **here**, inside the lookup every
    caller already makes, rather than at the call sites. There are two of them —
    the MCP transport and the mobile API — and a revocation honoured by one and
    not the other is a revocation that did not happen.
    """
    item = await session.get(OAuthAccessTokenModel, hash_token(token))
    if item is None:
        return None
    if item.revoked_at is not None:
        return None
    if _as_utc(item.expires_at) <= datetime.now(timezone.utc):
        return None
    return item


# Why a refresh token was refused. Only `reused` reaches the caller as anything
# other than a flat 401: the client is told nothing, but the *server* has to
# tell replay apart from theft, because theft revokes the grant.
REFRESH_UNKNOWN = "unknown"
REFRESH_REVOKED = "revoked"
REFRESH_REUSED = "reused"
REFRESH_EXPIRED = "expired"
REFRESH_VALID = "valid"


async def inspect_refresh_token(
    session: AsyncSession, token: str
) -> tuple[str, OAuthRefreshTokenModel | None]:
    """Classify a presented refresh token without deciding what to do about it.

    The verdict lives here, next to the timestamps it is computed from, so the
    route does not re-implement expiry comparison against a column that may come
    back naive from SQLite and aware from Postgres.
    """
    item = await session.get(OAuthRefreshTokenModel, hash_token(token))
    if item is None:
        return REFRESH_UNKNOWN, None
    if item.revoked_at is not None:
        return REFRESH_REVOKED, item
    if item.consumed_at is not None:
        # Single use. A second presentation is a replay or a stolen copy, and
        # the two are indistinguishable from here — so it is treated as theft.
        return REFRESH_REUSED, item
    if _as_utc(item.expires_at) <= datetime.now(timezone.utc):
        return REFRESH_EXPIRED, item
    return REFRESH_VALID, item


async def issue_auth_grant(
    session: AsyncSession,
    *,
    grant_id: str,
    access_token: str,
    refresh_token: str,
    client_id: str,
    user_id: str,
    scopes: list[str],
    access_expires_at: datetime,
    refresh_expires_at: datetime,
    event_type: str,
    rotated_from_hash: str | None = None,
) -> bool:
    """Write one sign-in (or one rotation) and its audit record, in one commit.

    Returns False when a rotation lost a race — see below — having written
    nothing. A sign-in always returns True.

    Rotation consumes the previous refresh token in the same transaction that
    issues the replacement: committing them separately leaves a window in which
    both are usable, which is exactly the state `inspect_refresh_token` treats
    as theft.

    The consumption is a conditional UPDATE and its row count is checked, rather
    than a read-then-write. Two refreshes arriving together both read an
    unconsumed token and both would mint a pair, so single use would hold only
    when nobody tested it. Whoever the database lets consume the row proceeds;
    the loser is told nothing was written and answers like any other rejected
    credential.

    **Nothing this function writes carries a personal identifier** — not the
    audit payload, and not the two token rows either. The actor is `user_id`
    everywhere: in `entity_id` on the audit row and in the `user_id` column on
    both tokens. `security-standards.md` §2 names e-mail explicitly and adds
    that PII is never stored plaintext in a synced directory, and the default
    `database_url` is a SQLite file inside this checkout, which sits under
    `~/Sync`.

    The scope of that sentence is the point of it. An earlier cut made the same
    §2 argument in this docstring while writing `user_email` into
    `oauth_access_tokens` and `oauth_refresh_tokens` twenty and thirty lines
    below, and the test behind it asserted on `audit_events` alone — so the
    reasoning retired the risk for the next reader while the field was still
    there. `migrations/0004_drop_user_email.sql` removes the columns; the
    registry lookup that used to fall back to the stored e-mail now resolves by
    `user_id`, which is the same registry key and was always tried first.

    A token row is a credential record: it needs to say *which account* the
    credential belongs to, and the opaque id says that. Whose e-mail address
    that is belongs in `users.json` and nowhere else.
    """
    now = datetime.now(timezone.utc)
    if rotated_from_hash is not None:
        consumed = await session.execute(
            update(OAuthRefreshTokenModel)
            .where(OAuthRefreshTokenModel.token_hash == rotated_from_hash)
            .where(OAuthRefreshTokenModel.consumed_at.is_(None))
            .where(OAuthRefreshTokenModel.revoked_at.is_(None))
            .values(consumed_at=now)
        )
        if consumed.rowcount != 1:
            await session.rollback()
            return False
    session.add(
        OAuthAccessTokenModel(
            token_hash=hash_token(access_token),
            client_id=client_id,
            user_id=user_id,
            scopes_json=json.dumps(scopes, ensure_ascii=True),
            expires_at=access_expires_at,
            created_at=now,
            grant_id=grant_id,
        )
    )
    session.add(
        OAuthRefreshTokenModel(
            token_hash=hash_token(refresh_token),
            grant_id=grant_id,
            client_id=client_id,
            user_id=user_id,
            scopes_json=json.dumps(scopes, ensure_ascii=True),
            expires_at=refresh_expires_at,
            created_at=now,
        )
    )
    await record_event(
        session,
        AUTH_ENTITY_TYPE,
        user_id,
        event_type,
        {
            "grant_id": grant_id,
            "client_id": client_id,
            "scopes": scopes,
            "rotated": rotated_from_hash is not None,
        },
    )
    await session.commit()
    return True


async def revoke_auth_grant(
    session: AsyncSession, *, grant_id: str, user_id: str, reason: str
) -> dict[str, int]:
    """Revoke every credential issued under one grant.

    Both tables, one commit: leaving the access tokens behind would mean a
    sign-out that keeps working for the rest of the access-token TTL, which is
    the failure the endpoint exists to prevent.
    """
    now = datetime.now(timezone.utc)
    access = await session.execute(
        update(OAuthAccessTokenModel)
        .where(OAuthAccessTokenModel.grant_id == grant_id)
        .where(OAuthAccessTokenModel.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    refresh = await session.execute(
        update(OAuthRefreshTokenModel)
        .where(OAuthRefreshTokenModel.grant_id == grant_id)
        .where(OAuthRefreshTokenModel.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    revoked = {"access_tokens": max(access.rowcount, 0), "refresh_tokens": max(refresh.rowcount, 0)}
    await record_event(
        session,
        AUTH_ENTITY_TYPE,
        user_id,
        "auth.credentials_revoked",
        {"grant_id": grant_id, "reason": reason, **revoked},
    )
    await session.commit()
    return revoked


async def revoke_access_token(
    session: AsyncSession, *, token: str, user_id: str, reason: str
) -> dict[str, int]:
    """Revoke one access token that belongs to no grant.

    The browser OAuth flow issues those: there is no refresh chain to revoke,
    so revocation stops at the token presented.
    """
    item = await session.get(OAuthAccessTokenModel, hash_token(token))
    revoked = {"access_tokens": 0, "refresh_tokens": 0}
    if item is not None and item.revoked_at is None:
        item.revoked_at = datetime.now(timezone.utc)
        revoked["access_tokens"] = 1
    await record_event(
        session,
        AUTH_ENTITY_TYPE,
        user_id,
        "auth.credentials_revoked",
        {"grant_id": None, "reason": reason, **revoked},
    )
    await session.commit()
    return revoked


async def record_auth_event(
    session: AsyncSession, *, user_id: str, event_type: str, payload: dict
) -> None:
    """Persist one authentication event on its own.

    Failed sign-ins are recorded here. The payload carries a reason and never
    the credential, nor the string the caller typed as a username: an audit
    table that stores unvalidated input is a log-forging surface and, when the
    caller typed a password into the wrong field, a credential store.
    """
    await record_event(session, AUTH_ENTITY_TYPE, user_id, event_type, payload)
    await session.commit()


async def purge_expired_audit_events(
    session: AsyncSession, *, retention_days: int, now: datetime | None = None
) -> int:
    """Drop **authentication** audit rows older than the window. Returns how many.

    `POST /api/v1/auth/sign-in` is the first unauthenticated write path into
    this table: a wrong password commits a row, and the rate limiter bounds the
    write *rate*, not the total. Before this, nothing removed an audit row at
    all — the startup sweep collected `idempotency_records` only — so a caller
    that never authenticated could grow the operator's database indefinitely.

    Scoped to `entity_type == "auth"`, and that scope is the point. The window
    is chosen to bound sign-in spam; applying it to the whole table would delete
    `task.approved` — the record of who authorized a sensitive task — plus
    `task.stopped_by_actor`, `task.state_changed` and `task.result`, on a table
    that had kept everything forever. Whether an approval record may be aged out
    at 90 days is an operator's decision about their own compliance, and it is
    not one to make by inheritance from a spam control. Eleven `record_event`
    call sites write here; two of them are auth, and those two are the ones an
    unauthenticated caller can drive.

    A non-positive window means "keep everything", for a deployment that exports
    the table elsewhere. It is an explicit opt-in to unbounded growth.

    Deletes by timestamp in one statement rather than loading the rows: the
    whole point is the case where there are a great many of them.
    """
    if retention_days <= 0:
        return 0
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    result = await session.execute(
        delete(AuditEventModel)
        .where(AuditEventModel.entity_type == AUTH_ENTITY_TYPE)
        .where(AuditEventModel.created_at < cutoff),
        # The delete happens in the database, not by evaluating the predicate
        # against whatever this session happens to have loaded. Letting
        # SQLAlchemy synchronize means comparing an aware cutoff against rows
        # SQLite hands back naive, and the sweep of a large table is exactly the
        # case where loading them is what must not happen.
        execution_options={"synchronize_session": False},
    )
    await session.commit()
    return max(result.rowcount, 0)


async def store_message_receipt(session: AsyncSession, message_id: str, executor_id: str, message_type: str) -> bool:
    current = await session.get(MessageReceiptModel, message_id)
    if current is not None:
        return False
    session.add(
        MessageReceiptModel(
            message_id=message_id,
            executor_id=executor_id,
            message_type=message_type,
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    return True

async def list_tasks_page(
    session: AsyncSession,
    *,
    project_ids: list[str] | None,
    states: list[str] | None = None,
    after: tuple[str, str] | None = None,
    limit: int = 50,
) -> list[TaskModel]:
    """Tasks the caller may see, newest first, over-fetched by one.

    `project_ids` of None means unrestricted (admin); an empty list means the
    caller sees nothing, which is a different thing and must not be collapsed
    into the former. The visibility filter is applied to the QUERY: filtering
    after loading is how a page count ends up describing rows the caller may not
    see.

    Returns `limit + 1` rows when more exist, which is what lets the caller
    report `hasMore` authoritatively without a second COUNT — the contract
    forbids inferring the end of a list from a short page, precisely because
    authorization can shorten one.

    Ordering is `(created_at DESC, id DESC)` and the cursor carries both. Time
    alone is not unique: two tasks created in the same instant would make a
    cursor skip one or repeat it forever.
    """
    statement = select(TaskModel)
    if project_ids is not None:
        if not project_ids:
            return []
        statement = statement.where(TaskModel.project_id.in_(project_ids))
    if states:
        statement = statement.where(TaskModel.state.in_(states))
    if after is not None:
        created_at, task_id = after
        # A real datetime, never a string. SQLAlchemy demotes a string bind to
        # a text comparison against the DateTime column: on SQLite that happens
        # to sort correctly *except* when `str(datetime)` omits the fractional
        # part on a whole second, which silently truncated the list; on Postgres
        # a text bind against timestamptz is wrong far more often than not.
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        statement = statement.where(
            or_(
                TaskModel.created_at < created_at,
                and_(TaskModel.created_at == created_at, TaskModel.id < task_id),
            )
        )
    statement = statement.order_by(TaskModel.created_at.desc(), TaskModel.id.desc()).limit(limit + 1)
    result = await session.execute(statement)
    return list(result.scalars())


async def get_task_for_projects(
    session: AsyncSession, task_id: str, project_ids: list[str] | None
) -> TaskModel | None:
    """A task the caller may see, or None.

    None covers "does not exist" and "not yours" alike. The caller turns both
    into `not_found`, because distinguishing them confirms an identifier exists
    to someone who was not given it.
    """
    task = await session.get(TaskModel, task_id)
    if task is None:
        return None
    if project_ids is not None and task.project_id not in project_ids:
        return None
    return task



async def get_recent_logs(
    session: AsyncSession, task_id: str, *, stream: str | None = None, limit: int = 20
) -> list[TaskLogModel]:
    """The most recent log lines, oldest-first within the slice.

    `get_logs` reads forward from an offset, which is right for a client
    resuming a stream and wrong for "what happened just before it failed":
    reading the first N and slicing the end of that window returns the oldest
    lines on any long session.
    """
    statement = select(TaskLogModel).where(TaskLogModel.task_id == task_id)
    if stream:
        statement = statement.where(TaskLogModel.stream == stream)
    statement = statement.order_by(TaskLogModel.offset.desc()).limit(limit)
    result = await session.execute(statement)
    return list(reversed(list(result.scalars())))
