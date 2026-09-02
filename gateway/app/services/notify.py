"""Out-of-band completion notification by email.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #70 / council finding
F27 (one corner of it: task finished -> email the requester).

## Why the gateway, not the executor

Only the gateway is always-on -- able to report even a `lost` task, when the
executor itself died -- and only the gateway should hold an SMTP credential:
the executor is the side that just ran an LLM over untrusted issue text (see
`agent/codex_bridge_agent/instructions.py`) and adding a mail credential to
that surface would be exactly the provider/secret custody council finding
F08 already flags.

## Why aiosmtplib, not the stdlib `smtplib`

A blocking SMTP call inside this async handler would stall the event loop
for every other request -- the same trap this codebase already hit and fixed
once for `users.authenticate` (`docs/napkin-lessons.md`: ten concurrent
unauthenticated attempts took `/health` from 0.8ms to 3.3s before
`authenticate_async` existed).

## Why a failure here can never fail the task

`notify_task_finished` is called *after* `store.store_result` and
`hub.mark_task_finished` have already committed the task's real outcome --
this module cannot undo that, and must not try. Every failure mode (missing
config, an unreadable or world-readable credential file, a malformed config,
an SMTP error) is caught in one place and turned into a `task.notification_failed`
audit event carrying **only the exception type name** -- never its message,
since SMTP error text routinely echoes the server banner and sometimes
quotes the credential back.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api.routes.sessions import redact
from gateway.app.core.config import Settings
from gateway.app.models.entities import ProjectModel, TaskModel
from gateway.app.services.audit import record_event
from gateway.app.services.email_templates import EmailKind, render_email, subject_prefix

logger = logging.getLogger(__name__)

# Mirrors `gateway/app/services/store.py`'s own terminal-state set
# (`restart_finished_task`) -- kept as a local literal rather than importing
# `TaskState` for the comparison, since this module only ever needs the
# string values already sitting on `task.state`.
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "expired", "lost"})

_REQUIRED_KEYS = ("account", "app_password", "smtp_host", "smtp_port")

_STATE_LABELS = {
    "completed": "concluída",
    "failed": "falhou",
    "cancelled": "cancelada",
    "expired": "expirou",
    "lost": "perdida (executor desconectado)",
}

class NotifyConfigError(RuntimeError):
    """The gateway itself is not set up for notification email -- an operator

    problem, never the task's fault. Always actionable.
    """


@dataclass(frozen=True)
class EmailCredentials:
    account: str
    app_password: str
    smtp_host: str
    smtp_port: int


def _load_email_credentials(path: str) -> EmailCredentials:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise NotifyConfigError(
            f"the notification email config file at {path!r} does not exist or is not readable."
        )
    mode = file_path.stat().st_mode
    if mode & 0o077:
        raise NotifyConfigError(
            f"the notification email config file at {path!r} is readable or writable by "
            f"group/other (mode {oct(mode & 0o777)}); refusing to use it. Fix with `chmod 600`."
        )
    values: dict[str, str] = {}
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        # Whitespace-tolerant on purpose: this ecosystem's own
        # `~/.config/credentials/email/*.conf` files are inconsistent —
        # most are `key=value`, at least one is `key = value`.
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    missing = [key for key in _REQUIRED_KEYS if key not in values or not values[key]]
    if missing:
        raise NotifyConfigError(
            f"the notification email config file at {path!r} is missing required field(s): "
            f"{', '.join(missing)}."
        )
    try:
        port = int(values["smtp_port"])
    except ValueError as exc:
        raise NotifyConfigError(
            f"the notification email config file at {path!r} has a non-numeric smtp_port."
        ) from exc
    return EmailCredentials(
        account=values["account"],
        app_password=values["app_password"],
        smtp_host=values["smtp_host"],
        smtp_port=port,
    )


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    if minutes:
        return f"{minutes}min {secs}s"
    return f"{secs}s"


def _compose(task: TaskModel, project_label: str) -> tuple[EmailKind, str, str, list[tuple[str, str]]]:
    kind = EmailKind.TASK_COMPLETED if task.state == "completed" else EmailKind.TASK_FAILED
    state_label = _STATE_LABELS.get(task.state, task.state)
    title = f"Tarefa {state_label} — {project_label}"
    lede = f'A tarefa {task.id} no projeto "{project_label}" terminou com o estado "{task.state}".'

    rows: list[tuple[str, str]] = [
        ("Tarefa", task.id),
        ("Projeto", project_label),
        ("Engine", task.engine),
        ("Estado final", task.state),
    ]
    if task.issue_ref:
        rows.append(("Issue", task.issue_ref))

    delivery = None
    if task.delivery_result_json:
        try:
            delivery = json.loads(task.delivery_result_json)
        except (json.JSONDecodeError, TypeError):
            delivery = None
    if delivery:
        if delivery.get("branch"):
            rows.append(("Branch", str(delivery["branch"])))
        if delivery.get("commit"):
            rows.append(("Commit", str(delivery["commit"])))
        rows.append(("Push", "sim" if delivery.get("pushed") else "não"))
        if delivery.get("reason"):
            rows.append(("Motivo (delivery)", redact(str(delivery["reason"])) or ""))

    if task.started_at and task.completed_at:
        duration = (task.completed_at - task.started_at).total_seconds()
        rows.append(("Duração", _format_duration(duration)))

    return kind, title, lede, rows


async def notify_task_finished(
    session: AsyncSession,
    task: TaskModel,
    settings: Settings,
) -> None:
    """Send exactly one completion email for `task` when configured, and

    never raise: any failure is caught, logged, and recorded as
    `task.notification_failed` with only the exception type name. A
    misconfigured or absent setup is a silent no-op, not an error — this is
    called from the hot path right after the task's own result is committed.
    """
    if task.state not in TERMINAL_STATES:
        return
    if not settings.notification_email_config_file or not settings.notification_to:
        return
    try:
        credentials = _load_email_credentials(settings.notification_email_config_file)

        project = await session.get(ProjectModel, task.project_id)
        project_label = project.name if project is not None else task.project_id

        kind, title, lede, rows = _compose(task, project_label)
        html_body = render_email(
            kind,
            preheader=f"{title} — {lede}",
            title=title,
            lede=lede,
            rows=rows,
            sign_line1="Notificação automática de",
            sign_line2="CodexBridge · executor " + task.executor_id,
        )

        message = EmailMessage()
        message["From"] = credentials.account
        message["To"] = settings.notification_to
        message["Subject"] = f"{subject_prefix(kind)} — {project_label}"
        message.set_content("Este e-mail requer um cliente compatível com HTML para ser exibido corretamente.")
        message.add_alternative(html_body, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=credentials.smtp_host,
            port=credentials.smtp_port,
            username=credentials.account,
            password=credentials.app_password,
            use_tls=credentials.smtp_port == 465,
            start_tls=credentials.smtp_port != 465,
        )
    except Exception as exc:  # noqa: BLE001 — every failure mode collapses to the same audit trail, by design.
        logger.warning("notification email failed for task %s: %s", task.id, type(exc).__name__)
        await record_event(
            session,
            "task",
            task.id,
            "task.notification_failed",
            {"exception_type": type(exc).__name__},
        )
        await session.commit()
