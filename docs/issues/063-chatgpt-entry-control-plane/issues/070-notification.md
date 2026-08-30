Parent: #63
Related: #46, #50, #13 — this issue explicitly claims and closes council finding **F27** for one specific case: task-finished notification.

## Objective
Send an email when a task reaches a terminal state, and add the read-side fields a ChatGPT scheduled Task needs to poll "what finished since I last asked." Council finding F27 records that no out-of-band notification mechanism exists anywhere in this codebase, and that #46 and #50's own acceptance criteria depend on one existing. This issue does not close F27 in general — no device push, no per-principal subscription, no event-class preferences — only the one path: task finished → email the requester.

## Scope
- New `gateway/app/services/notify.py`.
- Called from `gateway/app/main.py`'s `TASK_RESULT` handling, **after** `store.store_result` and `hub.mark_task_finished` — the state is already committed before this runs, so a failure here cannot roll anything back.
- Additive fields on `get_task_status` / `list_recent_tasks` (`engine`, `issue_ref`, `delivery{branch, commit, pushed, outcome, reason}`, `eta_seconds`) plus an optional `states` filter on `list_recent_tasks`.
- `docs/chatgpt-registration.md` gains a short recipe for setting up a ChatGPT scheduled Task that polls this surface.

## Requirements
- Runs on the **gateway**, not the executor: only the gateway knows `requested_by_email`; it is the always-on side (able to report even `lost`, when the executor itself died); and the executor is the side that just ran an LLM over untrusted issue text (see #65) and should not also hold an SMTP credential (council finding **F08**, provider/secret custody).
- Credential by **reference only**, never inline: `CODEX_BRIDGE_NOTIFICATION_EMAIL_CONFIG_FILE` pointing at a file in the same `key=value` shape as this ecosystem's existing `~/.config/credentials/email/*.conf` files (`account`, `app_password`, `smtp_host`, `smtp_port`). Absent config → feature disabled, logged once at startup, never a hard failure. The module refuses to use a config file whose permission mode has any group/other bits set (`mode & 0o077`). Because the live gateway systemd unit sets `ProtectHome=true`, this file must live under `/etc/codex-bridge/`, not under any user's home directory.
- Uses `aiosmtplib`, not the stdlib `smtplib` — a blocking SMTP call inside an async handler stalls the event loop for every other request, the same trap this codebase already documented and fixed once for `users.authenticate` (ten concurrent unauthenticated attempts took `/health` from 0.8ms to 3.3s before `authenticate_async` existed).
- Email body includes: task id, project, engine, final state, issue reference, branch, commit sha, push outcome, refusal reason if any, duration, and a link to the session detail. **Never** includes diff content, log lines, repository file content, or filesystem paths — the resolved issue text is untrusted (see #65) and email is an exfiltration channel.
- **A notification failure must never fail the task.** Wrap the send in try/except; on failure, log and record a `task.notification_failed` audit event containing **only the exception type name**, never its message — SMTP error messages routinely echo the server banner and occasionally quote back the credential.

## ARO
- **F27**: partially addressed, explicitly scoped as above — this is one corner of the finding, not the whole finding. #46 and #50 should not treat this issue's completion as satisfying every notification-dependent acceptance criterion they carry; only the "mission finished" case is covered.
- **F08**: addressed by keeping the SMTP credential exclusively on the gateway host, never on the executor.
- **F12** (no scheduler exists, and a Raspberry Pi is not where to add one): respected — no scheduler is introduced by this issue. The ChatGPT scheduled Task is the clock; this issue only provides the surface it polls, plus the one push-style channel (email) that works while the app or chat session is closed.

## Test plan
- New `tests/unit/test_notify.py`: no config file → no-op, no exception; world-readable config file → refused with a logged reason; a sender that raises → the task stays `completed` and a `task.notification_failed` event is recorded with only the exception type; the composed email body contains none of {diff, log line, absolute path, credential-shaped string} for a range of fixture tasks.
- Extend `tests/integration/test_sessions.py` / relevant task-status tests for the additive fields and the `states` filter.
- `tests/contract/test_openapi_document.py` / `docs/protocol.md`: no HTTP route added by this issue's core (the send-on-completion path is a hook, not an endpoint); the additive MCP fields are documented.

## Definition of Done
- A task reaching any terminal state (`completed`, `failed`, `cancelled`, `expired`, `lost`) triggers exactly one notification attempt when configured, and zero when not.
- A raising SMTP client cannot change the task's own final state.
- The email never contains repository content.
