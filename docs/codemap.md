# Code Map · codex-bridge

> Generated: 2026-08-30 · Root: `/home/esteban/Sync/Projects/AI/CodexBridge`
> Refresh: `governancekit --root /home/esteban/Sync/Projects/AI/CodexBridge map`

## Summary

- 115 file(s) · 1083 symbol(s) indexed
- Languages: config (2), python (111), shell (2)
- Top-level areas: `.`, `agent`, `deploy`, `gateway`, `scripts`, `shared`, `tests`

## Governance

- `AGENTS.md`
- `docs/required-reading.md`
- `docs/project-rules.md`
- `docs/software-overview.md`
- `docs/limits.md`
- `.docs/governancekit-integration.json`

## Ignored Paths

- Built-in: `.docs-migration-bak`, `.git`, `.idea`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.tox`, `.venv`, `.vscode`, `__pycache__`, `build`, `dist`, `env`, `node_modules`, `venv`
- `.gitignore`: `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.coverage`, `codex_bridge.db`, `dist/`, `build/`, `*.egg-info/`, `.venv/`, `venv/`, `.governancekit-identity.json`, `AGENTS.md`, `.cursorrules`, `CLAUDE.md`, `.windsurfrules`, `GEMINI.md`, `.github/copilot-instructions.md`, `.amazonq/rules/ai-agents.md`, `handoff.md`, `new-tag.sh`, `scripts/install-agents-kit.sh`, `scripts/agent-worktree.sh`, `.docs-migration-bak/`, `.gk/operator.json`, `.gk/secrets.json`, `.gk/context-telemetry.jsonl`, `.gk/overwritten/`, `.gk/pre-upgrade/`, `.gk/pre-migrate/`, `.gk/remove-agents-backup/`, `.gk/remove-agents-plan.json`, `.gk/context-proposal/`, `*.kit-new`, `*.pre-draft`, `.env`, `.env.*`, `.envrc`, `.npmrc`, `.pypirc`, `.netrc`, `*.pem`, `*.key`, `.credentials/*`, `!.env.example`, `!.env.sample`, `!.env.template`, `!.env.dist`, `!.env-example`, `!.env.missing`, `!.credentials/.gitignore`, `!.credentials/.keep`, `!.credentials/README*`, `!.credentials/*.example`, `!.credentials/*.sample`, `!.credentials/*.template`, `!.credentials/*.dist`

## Entry Points

- `agent/codex_bridge_agent/__main__.py` — `python -m agent.codex_bridge_agent`

## File Tree

```
agent/
  __init__.py  — "Agent package."
  codex_bridge_agent/
    __init__.py  — "codex-bridge-agent package."
    __main__.py
    codex_runner.py  — "Re-export shim."
    config.py
    git_delivery.py  — "The commit/push step a completed task's own `delivery` block authorizes."
    git_tools.py
    instructions.py  — "Resolves `issue_ref` to file content, and builds the provider prompt with"
    runners/
      __init__.py
      base.py  — "The provider-neutral surface the executor dispatches a task through."
      claude.py  — "Claude Code as a second `Runner`, issue #41a."
      codex.py
      pool.py  — "The facade `AgentService` talks to instead of a single hardcoded runner."
      registry.py  — "Which `AgentEngine` values have a real `Runner` behind them."
    service.py
deploy/
  incus/
    codexbridge_edge_proxy.py  — "RETIRED 2026-08-10 — the Incus edge proxy on the dom1 path."
gateway/
  Dockerfile
  __init__.py  — "Gateway package."
  app/
    __init__.py  — "Gateway app package."
    api/
      __init__.py  — "Cross-cutting HTTP behaviour for the mobile API (issue #12)."
      auth.py  — "Authentication and authorization for the contract surface."
      concurrency.py  — "Optimistic concurrency: two operators, two devices, one decision."
      errors.py  — "The one error envelope every contract endpoint returns."
      idempotency.py  — "Replay-safe writes for a client that goes offline mid-request."
      pagination.py  — "Cursor pagination for collections, and the offset scheme logs keep."
      permissions.py  — "What an actor may do, in one table the API and the client both read."
      rate_limit.py  — "Rate limiting for the contract surface."
      request_context.py  — "Per-request identifier, carried from the middleware to the error envelope."
      routes/
        __init__.py  — "HTTP routers for the mobile contract surface."
        auth.py  — "Sign-in, renewal, revocation, and what the actor may actually do."
        conversations.py  — "Conversations and contextual messaging — issue #10."
        decisions.py  — "Operational decisions: sensitive tasks held for a human to resolve — issue #6."
        epics.py  — "Epics — issue #8."
        issues.py  — "Issues — issue #8."
        missions.py  — "Missions: the mission-control view of the same run Sessions exposes — issue #7."
        probes.py  — "Liveness, readiness and version — what a client asks before anything else."
        projects.py  — "Projects and the project operational dashboard — issue #5."
        sessions.py  — "Agent sessions, their logs, and lifecycle control."
      scope.py  — "Which requests the API's cross-cutting rules apply to."
      setup.py  — "One call that installs every cross-cutting API behaviour."
      timestamps.py  — "RFC 3339 in UTC, spelled one way."
    core/
      agent_auth.py  — "Credential resolution for the `/agent/ws` handshake — issue #15."
      config.py
      logging.py
      oauth.py
      rate_limit.py
      registry.py
      users.py  — "The user registry, and the one operation that turns a password into a user."
    db/
      base.py
      schema_guard.py  — "Refuse to start on a database that is behind the code."
      session.py
    main.py
    mcp/
      server.py
      tools.py
    models/
      entities.py
    services/
      __init__.py
      agent_hub.py
      audit.py
      conversation_types.py  — "Closed vocabulary for conversation context references, and their error."
      google_calendar.py  — "A Google Calendar client for reminders, built to be tested without ever"
      issue_types.py  — "Closed vocabularies for epics and issues, and the error they fail with."
      metrics.py
      store.py
    version.py  — "The single statement of this application's version."
pyproject.toml
scripts/
  apply_migrations.py  — "Apply the SQL files in `migrations/`, once each, in filename order."
  diagnose.sh
  install.sh
shared/
  __init__.py  — "Shared contracts for the gateway and the agent."
  policy.py
  protocol.py
  security.py
tests/
  conftest.py
  contract/
    test_docs_match_the_runtime.py  — "Prose that states a runtime fact, checked against the runtime."
    test_openapi_document.py  — "Contract tests for the canonical OpenAPI document."
    test_proxy_routes.py  — "Every contracted path must be routed by the proxies in front of the gateway."
  integration/
    test_agent_ack_handling.py  — "`task.ack` handling in the `/agent/ws` message loop — issue #16 council."
    test_agent_hub.py
    test_agent_ws_handshake.py  — "The `/agent/ws` handshake stops carrying the token in the URL — issue #15."
    test_api_conventions.py  — "Representative-endpoint compliance for the cross-cutting API rules (issue #12)."
    test_auth.py  — "The mobile credential lifecycle — issue #4."
    test_claude_runner_real_process.py  — "ClaudeRunner against a REAL `claude` subprocess — not the fakes used elsewhere."
    test_codex_runner_real_process.py  — "CodexRunner against a REAL `codex` subprocess — not the fake used everywhere else."
    test_conversations.py  — "Conversations and contextual messaging — issue #10."
    test_decisions.py  — "Operational decisions — issue #6."
    test_dispatch_payload_engine_and_delivery.py  — "`AgentHub.dispatch_next` forwards engine/issue_ref/delivery to the executor."
    test_epics_issues.py  — "Epics and issues — issue #8."
    test_mcp_reminders.py  — "The `create_reminder`/`cancel_reminder` MCP tools, at the `handle_mcp_call` layer."
    test_missions.py  — "Missions: the mission-control view of Sessions — issue #7."
    test_oauth_authorize.py  — "The browser OAuth form — the *other* caller of the password check."
    test_probes.py  — "Health, readiness and version — issue #3."
    test_project_and_eta_resolution.py  — "`resolve_project_reference` and `estimate_task_duration_seconds`."
    test_projects.py  — "Projects and the project operational dashboard — issue #5."
    test_push_preauthorization.py  — "Push pre-authorization is resolved as a recorded approval, never a bypass."
    test_reconnect_replay_resolves.py  — "Issue #17 council round 1 — the headline scenario named by findings 1, 4"
    test_sessions.py  — "Agent sessions, logs and control — issue #9."
    test_start_development_task.py  — "The `start_development_task` MCP tool -- the conversational entry point."
    test_store_and_mcp.py
  unit/
    test_agent_auth.py  — "Credential resolution for the `/agent/ws` handshake — issue #15."
    test_agent_service.py
    test_apply_migrations.py  — "The migration runner, exercised against real throwaway databases."
    test_claude_runner.py  — "ClaudeRunner's pure logic: command assembly, NDJSON extraction, sandbox mapping."
    test_codex_runner.py  — "CodexRunner's pause/resume/restart/cancel state machine — issue #16 council."
    test_config_settings.py  — "issue #17 council round 1, "the second caller": `cancel_replay_max_age_seconds`"
    test_git_delivery.py  — "`git_delivery.deliver_changes` against real throwaway git repos."
    test_google_calendar.py  — "`gateway.app.services.google_calendar`, without ever touching Google."
    test_instructions.py  — "`resolve_issue_text` and `build_task_instruction`."
    test_main_import.py
    test_policy.py
    test_rate_limiter_bounds.py  — "The limiter's key space must be bounded, or it becomes the resource exhausted."
    test_runner_registry.py  — "The runner abstraction itself: capability declarations and the pool's"
    test_schema_guard.py  — "The guard that refuses to serve a database the code has outgrown."
    test_security.py
    test_users.py
    test_version_is_single_sourced.py  — "Every statement of the application version must be the same statement."
```

## Symbol Index

### `agent/codex_bridge_agent/config.py`

- **`AgentSettings`** *(class)*
- **`AgentProjectConfig`** *(class)*
- `load_agent_projects(path)`

### `agent/codex_bridge_agent/git_delivery.py`

> The commit/push step a completed task's own `delivery` block authorizes.

- **`DeliveryOutcome`** *(class)*
  - `to_dict(self)` *(method)*
- `deliver_changes()` *(async function)* — "Commits (and, if authorized, pushes) whatever a completed task changed."

### `agent/codex_bridge_agent/git_tools.py`

- `run_git(project_root, *args)` *(async function)* — "Runs one `git` subcommand in `project_root`, capturing stdout/stderr."
- `collect_git_snapshot(project_root, diff_max_chars)` *(async function)*

### `agent/codex_bridge_agent/instructions.py`

> Resolves `issue_ref` to file content, and builds the provider prompt with

- **`IssueResolutionError`** *(class)* — "A typed reason `issue_ref` could not be turned into file content."
  - `__init__(self, code)` *(method)*
- `resolve_issue_text(project_root, issue_ref)` — "Returns the raw text of the issue `issue_ref` names, or raises"
- `build_task_instruction()` — "Assembles the final provider prompt, keeping the operator's own words"

### `agent/codex_bridge_agent/runners/base.py`

> The provider-neutral surface the executor dispatches a task through.

- **`RunningTask`** *(class)* — "A live subprocess plus the control flags `pause`/`cancel`/`restart`"
- **`RunnerCapabilities`** *(class)* — "What a provider can and cannot do, declared rather than assumed."
- **`Runner`** *(class)* — "One provider's implementation of "run this instruction, report back"."
  - `capabilities(self)` *(method)*
  - `is_known(self, task_id)` *(method)*
  - `mark_dispatched(self, task_id)` *(method)*
  - `forget(self, task_id)` *(method)*
  - `cancel(self, task_id)` *(async method)*
  - `pause(self, task_id)` *(async method)*
  - `resume(self, task_id)` *(async method)*
  - `restart(self, task_id)` *(async method)*
  - `run_task(self, task_id, project_root, instruction, timeout_seconds, continue_session_id, send_log, sandbox)` *(async method)*
- **`EngineNotImplementedError`** *(class)* — "A dispatch named an `AgentEngine` value with no real `Runner` behind it."
  - `__init__(self, engine)` *(method)*

### `agent/codex_bridge_agent/runners/claude.py`

> Claude Code as a second `Runner`, issue #41a.

- **`ClaudeRunner`** *(class)* — "Mirrors `runners.codex.CodexRunner`'s public surface method for method"
  - `__init__(self, settings)` *(method)*
  - `capabilities(self)` *(method)*
  - `is_known(self, task_id)` *(method)*
  - `mark_dispatched(self, task_id)` *(method)*
  - `forget(self, task_id)` *(method)*
  - `cancel(self, task_id)` *(async method)*
  - `pause(self, task_id)` *(async method)*
  - `resume(self, task_id)` *(async method)*
  - `restart(self, task_id)` *(async method)*
  - `run_task(self, task_id, project_root, instruction, timeout_seconds, continue_session_id, send_log, sandbox)` *(async method)*

### `agent/codex_bridge_agent/runners/codex.py`

- **`CodexRunner`** *(class)*
  - `__init__(self, settings)` *(method)*
  - `capabilities(self)` *(method)*
  - `is_known(self, task_id)` *(method)* — "Whether this runner has any record of the task at all."
  - `mark_dispatched(self, task_id)` *(method)*
  - `forget(self, task_id)` *(method)*
  - `cancel(self, task_id)` *(async method)*
  - `pause(self, task_id)` *(async method)*
  - `resume(self, task_id)` *(async method)*
  - `restart(self, task_id)` *(async method)*
  - `run_task(self, task_id, project_root, instruction, timeout_seconds, continue_session_id, send_log, sandbox)` *(async method)* — "Issue #34: `sandbox` is now always explicit, never implicit."

### `agent/codex_bridge_agent/runners/pool.py`

> The facade `AgentService` talks to instead of a single hardcoded runner.

- **`RunnerPool`** *(class)*
  - `__init__(self, settings)` *(method)*
  - `for_engine(self, engine)` *(method)*
  - `is_known(self, task_id)` *(method)*
  - `mark_dispatched(self, task_id, engine)` *(method)*
  - `forget(self, task_id)` *(method)*
  - `cancel(self, task_id)` *(async method)*
  - `pause(self, task_id)` *(async method)*
  - `resume(self, task_id)` *(async method)*
  - `restart(self, task_id)` *(async method)*

### `agent/codex_bridge_agent/runners/registry.py`

> Which `AgentEngine` values have a real `Runner` behind them.

- **`EngineRegistration`** *(class)*

### `agent/codex_bridge_agent/service.py`

- **`AgentService`** *(class)*
  - `__init__(self, settings)` *(method)*
  - `run_forever(self)` *(async method)*
- `main()` *(async function)*

### `deploy/incus/codexbridge_edge_proxy.py`

> RETIRED 2026-08-10 — the Incus edge proxy on the dom1 path.

- `proxy(path, request)` *(async function)*

### `gateway/app/api/auth.py`

> Authentication and authorization for the contract surface.

- `unauthenticated(message)` — "The one shape of a 401 on this surface."
- `current_principal(request, session)` *(async function)* — "Resolve the bearer token to a principal, or refuse the request."
- `bearer_token(request)` — "The presented bearer token, or None when the header is absent or not one."
- `require_action(action)` — "Dependency factory refusing a principal that may not perform `action`."
- `visible_projects(principal)` — "Project ids the principal may see, or None meaning "no restriction"."

### `gateway/app/api/concurrency.py`

> Optimistic concurrency: two operators, two devices, one decision.

- `etag_for(revision)` — "The entity tag for a given revision, quoted as RFC 9110 requires."
- `require_if_match(header, revision)` — "Reject a write whose `If-Match` does not name the current revision."

### `gateway/app/api/errors.py`

> The one error envelope every contract endpoint returns.

- `code_for_status(status_code)`
- **`ApiError`** *(class)* — "A failure that already knows its contract representation."
  - `__init__(self)` *(method)*
- `error_body()` — "Build the `Error` envelope. The single place its shape is decided."
- `error_response()`
- `render_unhandled(request, exc)` — "Log an unhandled exception and render it as `internal_error`."
- `install_error_handlers(app)` — "Route contract-path failures through the envelope, leave the rest alone."

### `gateway/app/api/idempotency.py`

> Replay-safe writes for a client that goes offline mid-request.

- `fingerprint(body)`
- **`ReplayedResponse`** *(class)* — "A stored response being returned again, never re-executed."
  - `__init__(self, status_code, body)` *(method)*
- **`Claim`** *(class)* — "Proof that this caller, and not a later one, owns the reservation."
  - `__init__(self, token)` *(method)*
- `lookup(session)` *(async function)* — "Read-only: the stored response for this key, or None. Does not reserve."
- `reserve(session)` *(async function)* — "Claim this key before doing the work."
- `complete(session)` *(async function)* — "Attach the finished response to a reservation this caller still owns."
- `release(session)` *(async function)* — "Drop a reservation whose write failed, so the client may try again."
- `remember(session)` *(async function)* — "Reserve and complete in one step, for a write already known to be done."
- `purge_expired(session)` *(async function)* — "Drop records past their TTL. Returns how many were removed."

### `gateway/app/api/pagination.py`

> Cursor pagination for collections, and the offset scheme logs keep.

- `scope_digest(endpoint, filters)` — "Identity of "this endpoint under these filters", for cursor binding."
- `encode_cursor(scope, position)`
- `decode_cursor(scope, cursor, expect)` — "Decode a cursor this server issued for `scope`, or fail with a typed error."
- `cursor_time(value)` — "Cursor form of a timestamp: ISO 8601, always carrying microseconds."
- `parse_limit(value)`
- `page_info()` — "Build `PageInfo`, keeping its one invariant true by construction."
- `paginate(items)` — "Trim an over-fetched list to `limit` and describe the page."

### `gateway/app/api/permissions.py`

> What an actor may do, in one table the API and the client both read.

- **`Action`** *(class)* — "One thing an actor may attempt, and what it takes to be allowed to."
- `is_allowed(principal, action)` — "Whether `principal` may perform `action`."
- `report_for(principal)` — "The catalogue evaluated for one actor, in contract shape."

### `gateway/app/api/rate_limit.py`

> Rate limiting for the contract surface.

- `client_key(request)` — "Bucket identity for a request."
- **`RateLimitDependency`** *(class)* — "Refuse a request that exceeds the window, in the contract's own shape."
  - `__init__(self, limiter)` *(method)*
  - `__call__(self, request)` *(async method)*

### `gateway/app/api/request_context.py`

> Per-request identifier, carried from the middleware to the error envelope.

- `current_request_id()` — "The current request's identifier, or a fresh one outside a request."
- `set_request_id(value)`
- **`RequestContextMiddleware`** *(class)* — "Assign a request id, expose it in the context, echo it in the response."
  - `__init__(self, app, on_unhandled)` *(method)*
  - `dispatch(self, request, call_next)` *(async method)*

### `gateway/app/api/routes/auth.py`

> Sign-in, renewal, revocation, and what the actor may actually do.

- **`SignInRequest`** *(class)*
- **`RefreshRequest`** *(class)*
- **`RevokeRequest`** *(class)*
- `sign_in(body, response, session)` *(async function)* — "Exchange a username and password for an access/refresh pair."
- `refresh(body, response, session)` *(async function)* — "Rotate a refresh token into a new pair."
- `revoke(request, response, body, session)` *(async function)* — "Sign out: end the grant now rather than at expiry."
- `current_actor(response, principal)` *(async function)* — "Who is calling, and what this build will let them do."

### `gateway/app/api/routes/conversations.py`

> Conversations and contextual messaging — issue #10.

- **`ContextReference`** *(class)*
- **`CreateConversationRequest`** *(class)*
- **`CreateMessageRequest`** *(class)*
- `list_conversations(response, project_id, cursor, limit, principal, session)` *(async function)* — "Conversations the caller may see, newest-created first."
- `get_conversation(conversation_id, response, principal, session)` *(async function)*
- `list_messages(conversation_id, response, cursor, limit, principal, session)` *(async function)* — "A conversation's messages, oldest first."
- `create_conversation(payload, response, idempotency_key, principal, session)` *(async function)* — "Start a conversation. Every context reference is resolved and checked here."
- `post_message(conversation_id, payload, response, idempotency_key, principal, session)` *(async function)* — "Post a message. `Idempotency-Key` is what makes an offline retry safe."

### `gateway/app/api/routes/decisions.py`

> Operational decisions: sensitive tasks held for a human to resolve — issue #6.

- **`DecisionApproveRequest`** *(class)*
- **`DecisionRejectRequest`** *(class)*
- **`DecisionRevisionRequest`** *(class)*
- `list_decisions(response, project, state, urgency, risk, deadline_before, deadline_after, cursor, limit, principal, session)` *(async function)* — "Decisions the caller may see, newest first."
- `get_decision(decision_id, response, principal, session)` *(async function)*
- `approve_decision(decision_id, body, response, if_match, idempotency_key, principal, session)` *(async function)*
- `reject_decision(decision_id, body, response, if_match, idempotency_key, principal, session)` *(async function)*
- `request_decision_revision(decision_id, body, response, if_match, idempotency_key, principal, session)` *(async function)*

### `gateway/app/api/routes/epics.py`

> Epics — issue #8.

- **`CreateEpicRequest`** *(class)*
- `list_epics(project_id, response, status, cursor, limit, principal, session)` *(async function)* — "Epics in one project, newest first."
- `create_epic(payload, response, idempotency_key, principal, session)` *(async function)*
- `link_issue(epic_id, issue_id, response, if_match, idempotency_key, principal, session)` *(async function)* — "Attach an issue to an epic. Both must be in a project the caller may see."

### `gateway/app/api/routes/issues.py`

> Issues — issue #8.

- **`CreateIssueRequest`** *(class)*
- **`UpdateIssueRequest`** *(class)*
- `list_issues(project_id, response, status, priority, epic_id, assignee_user_id, cursor, limit, principal, session)` *(async function)* — "Issues in one project, newest first, optionally filtered."
- `get_issue_detail(issue_id, response, principal, session)` *(async function)*
- `create_issue(payload, response, idempotency_key, principal, session)` *(async function)*
- `update_issue(issue_id, payload, response, if_match, principal, session)` *(async function)* — "Change status, priority, labels, assignee, dependencies or blocked reason."

### `gateway/app/api/routes/missions.py`

> Missions: the mission-control view of the same run Sessions exposes — issue #7.

- **`MissionCancelRequest`** *(class)* — "Issue #36: an operator-typed reason has nowhere to go without this."
- `list_missions(response, project_id, stage, state, risk, blocked, cursor, limit, principal, session)` *(async function)* — "Missions the caller may see, newest first."
- `get_mission(mission_id, response, principal, session)` *(async function)*
- `get_mission_timeline(mission_id, response, cursor, limit, principal, session)` *(async function)* — "The mission's recorded events, oldest first — the order a narrative reads in."
- `cancel_mission(mission_id, response, if_match, idempotency_key, body, principal, session)` *(async function)* — "Cancel a mission that is queued, waiting, running or awaiting approval."
- `explain_mission(mission_id, principal, session)` *(async function)* — "A structured account of a mission's current state, assembled server-side."

### `gateway/app/api/routes/probes.py`

> Liveness, readiness and version — what a client asks before anything else.

- `database_reachable(now)` *(async function)* — "Cached, single-flight readiness of the database."
- `reset_database_cache()` — "Drop the cached result. For tests and for a deliberate re-probe."
- `health()` *(async function)* — "Liveness. Deliberately touches nothing — see the module docstring."
- `ready(response)` *(async function)* — "Readiness, with the reason when it is not ready."
- `api_version()` *(async function)* — "What this server speaks, so a client can refuse before it starts."

### `gateway/app/api/routes/projects.py`

> Projects and the project operational dashboard — issue #5.

- `list_projects_endpoint(response, q, status, attention, cursor, limit, principal, session)` *(async function)* — "Projects the caller may see, ordered by id, optimized for the mobile dashboard."
- `get_project_detail(project_id, principal, session)` *(async function)*
- `get_project_summary(project_id, principal, session)` *(async function)* — "The full dashboard payload for one project: status plus the executor breakdown."

### `gateway/app/api/routes/sessions.py`

> Agent sessions, their logs, and lifecycle control.

- `redact(value)` — "Strip from any executor-influenced text what a response must never carry."
- `list_sessions(response, state, cursor, limit, principal, session)` *(async function)* — "Sessions the caller may see, newest first."
- `get_session_detail(session_id, response, principal, session)` *(async function)*
- `get_session_logs(session_id, response, offset, limit, principal, session)` *(async function)* — "Log lines from `offset`, the append-only scheme the store already uses."
- `stop_session(session_id, response, if_match, idempotency_key, principal, session)` *(async function)* — "Cancel a running or queued session."
- `pause_session(session_id, response, if_match, idempotency_key, principal, session)` *(async function)*
- `resume_session(session_id, response, if_match, idempotency_key, principal, session)` *(async function)*
- `restart_session(session_id, response, if_match, idempotency_key, principal, session)` *(async function)*
- `explain_session_error(session_id, principal, session)` *(async function)* — "A structured account of why a session failed, assembled server-side."

### `gateway/app/api/scope.py`

> Which requests the API's cross-cutting rules apply to.

- `is_contract_path(path)` — "Whether `path` is governed by docs/api/codex-bridge.openapi.yaml."

### `gateway/app/api/setup.py`

> One call that installs every cross-cutting API behaviour.

- `install_api_conventions(app)` — "Install the error envelope, the request id, and their shared plumbing."

### `gateway/app/api/timestamps.py`

> RFC 3339 in UTC, spelled one way.

- `utc_z(value)` — "`value` as an RFC 3339 UTC instant ending in `Z`, or None."
- `now_z()` — "The current instant, in the same form."
- `cursor_z(value)` — "Cursor form of a timestamp: ISO 8601, always carrying microseconds."

### `gateway/app/core/agent_auth.py`

> Credential resolution for the `/agent/ws` handshake — issue #15.

- **`TokenSource`** *(class)* — "How the executor presented its machine token."
- `resolve_executor_token()` — "Pick the credential to verify and report where it came from."

### `gateway/app/core/config.py`

- **`Settings`** *(class)*
  - `effective_ready_cache_seconds(self)` *(method)*
  - `accepted_mcp_tokens(self)` *(method)*
  - `oauth_client_ids(self)` *(method)*
  - `oauth_scopes(self)` *(method)*
  - `oauth_redirect_uri_prefixes(self)` *(method)*
  - `effective_oauth_issuer(self)` *(method)*

### `gateway/app/core/logging.py`

- `configure_logging()`

### `gateway/app/core/oauth.py`

- `generate_authorization_code()`
- `generate_access_token()`
- `generate_refresh_token()` — "A refresh token is longer-lived than an access token, so it is longer."
- `generate_grant_id()` — "Identifier of one sign-in and every rotation descended from it."
- `now_utc()`
- `expires_in(seconds)`
- `pkce_challenge(verifier)`
- `issuer_metadata()`
- `protected_resource_metadata()`
- `error_redirect(redirect_uri, error, state, description)`

### `gateway/app/core/rate_limit.py`

- **`MemoryRateLimiter`** *(class)* — "Sliding-window limiter with a bounded key space."
  - `__init__(self, limit, window_seconds, max_keys)` *(method)*
  - `allow(self, key)` *(async method)*
  - `tracked_keys(self)` *(method)* — "Bucket count, for tests and diagnostics."

### `gateway/app/core/registry.py`

- **`Registry`** *(class)*
- `load_registry(path)`

### `gateway/app/core/users.py`

> The user registry, and the one operation that turns a password into a user.

- **`GatewayUser`** *(class)*
- **`UserRegistry`** *(class)*
- **`AuthenticatedPrincipal`** *(class)*
  - `is_admin(self)` *(method)*
  - `has_scope(self, scope)` *(method)*
  - `can_access_project(self, project_id)` *(method)*
- `load_user_registry(path)`
- `lookup_user(path, username_or_email)`
- `unusable_registry_reason(path)` — "Why no account can sign in against `path`, or None when some can."
- **`AuthenticationResult`** *(class)* — "Whether the credential was accepted, and — for the audit trail — why not."
  - `ok` *(property)*
- `authenticate(path, username_or_email, password)` — "Resolve a username and check its password, at a cost that does not vary."
- `authenticate_async(path, username_or_email, password)` *(async function)* — "`authenticate`, moved off the event loop."
- `verify_password(password, encoded_hash)`

### `gateway/app/db/base.py`

- **`Base`** *(class)*

### `gateway/app/db/schema_guard.py`

> Refuse to start on a database that is behind the code.

- **`SchemaOutOfDate`** *(class)* — "The database is missing something a migration was supposed to add."
- `check_schema(connection)`

### `gateway/app/db/session.py`

- `get_session()` *(async function)*

### `gateway/app/main.py`

- `oauth_www_authenticate_header()`
- `validate_oauth_client(client_id, redirect_uri)`
- `render_authorize_form()`
- `authenticate_mcp_request(session, body, authorization)` *(async function)*
- `report_user_registry_state()` — "Log, once at startup, when no account can sign in."
- `startup()` *(async function)*
- `healthz()` *(async function)*
- `metrics_endpoint()` *(async function)*
- `oauth_metadata()` *(async function)*
- `oauth_protected_resource()` *(async function)*
- `oauth_authorize(response_type, client_id, redirect_uri, scope, state, code_challenge, code_challenge_method)` *(async function)*
- `oauth_authorize_submit(response_type, client_id, redirect_uri, scope, state, code_challenge, code_challenge_method, username, password, session)` *(async function)*
- `oauth_token(grant_type, code, redirect_uri, client_id, code_verifier, session)` *(async function)*
- `mcp_endpoint(request, authorization, session)` *(async function)*
- `handle_task_ack(session, envelope)` *(async function)* — "Handles one `task.ack` from the `/agent/ws` message loop."
- `handle_task_cancelled(session, envelope)` *(async function)* — "Handles one `task.cancelled` ack from the `/agent/ws` message loop."
- `agent_ws(websocket, executor_id, token, x_executor_token)` *(async function)*

### `gateway/app/mcp/server.py`

- `handle_mcp_call(body, session, hub, principal)` *(async function)*

### `gateway/app/mcp/tools.py`

- `tool_definitions()`

### `gateway/app/models/entities.py`

- **`ExecutorModel`** *(class)*
- **`ProjectModel`** *(class)*
- **`TaskModel`** *(class)*
- **`EpicModel`** *(class)*
- **`IssueModel`** *(class)*
- **`ConversationModel`** *(class)* — "A contextual thread linked to at least one product entity — issue #10."
- **`ConversationMessageModel`** *(class)* — "One message in a conversation. Immutable once written — no update path."
- **`ConversationReadStateModel`** *(class)* — "How far one actor has read into one conversation."
- **`TaskLogModel`** *(class)*
- **`AuditEventModel`** *(class)*
- **`MessageReceiptModel`** *(class)*
- **`IdempotencyRecordModel`** *(class)* — "A completed write, keyed so an offline retry replays instead of repeating."
- **`OAuthAuthorizationCodeModel`** *(class)*
- **`OAuthAccessTokenModel`** *(class)*
- **`OAuthRefreshTokenModel`** *(class)* — "A single-use credential that mints access tokens for one grant."

### `gateway/app/services/agent_hub.py`

- **`AgentConnection`** *(class)*
- **`AgentHub`** *(class)*
  - `__init__(self, session_factory, cancel_replay_max_age_seconds, control_replay_max_age_seconds)` *(method)*
  - `is_connected(self, executor_id)` *(method)*
  - `register(self, executor_id, websocket)` *(async method)*
  - `unregister(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `dispatch_available(self, executor_id)` *(async method)* — "Dispatches the next queued/waiting task to `executor_id`, if one is"
  - `mark_task_finished(self, executor_id, task_id)` *(async method)* — "Releases the slot `task_id` held and, if the executor is still"
- `hub_envelope(executor_id, message_type, payload)` — "Build a message for an executor."

### `gateway/app/services/audit.py`

- `record_event(session, entity_type, entity_id, event_type, payload)` *(async function)*

### `gateway/app/services/conversation_types.py`

> Closed vocabulary for conversation context references, and their error.

- **`ConversationPlanningError`** *(class)* — "A create input that fails validation inside the store itself."
  - `__init__(self, field, code, message)` *(method)*

### `gateway/app/services/google_calendar.py`

> A Google Calendar client for reminders, built to be tested without ever

- **`CalendarConfigError`** *(class)* — "The gateway itself is not set up for reminders -- an operator problem,"
- **`CalendarAccessError`** *(class)* — "Google refused the request, or it could not be reached in time."
- **`CalendarConfig`** *(class)*
- `openssl_sign_rs256(signing_input, private_key_pem)` *(async function)* — "The default `Signer`: shells out to `openssl dgst -sha256 -sign`."
- `parse_when(when)` — "Parses `when` as ISO 8601. A caller with no offset is assumed to mean"
- `create_reminder()` *(async function)*
- `cancel_reminder()` *(async function)*
- `check_access(config)` *(async function)* — "Confirms the configured credential can actually read the configured"

### `gateway/app/services/issue_types.py`

> Closed vocabularies for epics and issues, and the error they fail with.

- **`IssuePlanningError`** *(class)* — "A create/update input that fails validation inside the store itself."
  - `__init__(self, field, code, message)` *(method)*

### `gateway/app/services/metrics.py`

- `render_metrics()`

### `gateway/app/services/store.py`

- `upsert_registry(session, executors, projects)` *(async function)*
- `list_executors(session)` *(async function)*
- `list_projects(session)` *(async function)*
- `list_projects_for_executor(session, executor_id)` *(async function)*
- `list_projects_page(session)` *(async function)* — "Projects the caller may see, ordered by id, over-fetched by one."
- `list_projects_filtered(session)` *(async function)* — "Every matching project, ordered by id, with no page limit."
- `get_project_for_caller(session, project_id, project_ids)` *(async function)* — "A project the caller may see, or None."
- `executors_by_project(session, project_ids)` *(async function)* — "`{project_id: [executors allowed to run it]}`, ordered by executor id."
- `executors_allowing_project(session, project_id)` *(async function)* — "Executors whose allowlist names this one project. See `executors_by_project`."
- `project_task_counts(session, project_ids)` *(async function)* — "Per-project task counts, in one grouped query rather than one query per row."
- `latest_project_activity_at(session, project_id)` *(async function)* — "The most recent task creation time for a project, or None if it has none."
- `get_task(session, task_id)` *(async function)*
- `list_recent_tasks(session, limit, states)` *(async function)* — "`states` narrows to a caller-given set of `TaskState` values."
- `create_task(session, request, executor_online, continue_session_id, requested_by_user_id, requested_by_email, can_approve_push)` *(async function)*
- `mark_executor_connected(session, executor_id, connected)` *(async function)*
- `executor_is_live(executor)` — "Whether an executor should be presented as connected right now."
- `next_dispatchable_task(session, executor_id)` *(async function)*
- `update_task_state(session, task_id, state, error)` *(async function)*
- `append_log(session, task_id, offset, stream, line)` *(async function)*
- `decide_task_approval(session, task_id, decision, reason)` *(async function)*
- `recover_tasks_after_startup(session)` *(async function)*
- `get_logs(session, task_id, offset, limit)` *(async function)*
- `store_result(session, task_id, result, final_state)` *(async function)*
- `restart_finished_task(session, task_id)` *(async function)*
- `create_oauth_authorization_code(session)` *(async function)*
- `consume_oauth_authorization_code(session, code)` *(async function)*
- `create_oauth_access_token(session)` *(async function)*
- `get_oauth_access_token(session, token)` *(async function)* — "The token row, or None when the token may not be used."
- `inspect_refresh_token(session, token)` *(async function)* — "Classify a presented refresh token without deciding what to do about it."
- `issue_auth_grant(session)` *(async function)* — "Write one sign-in (or one rotation) and its audit record, in one commit."
- `revoke_auth_grant(session)` *(async function)* — "Revoke every credential issued under one grant."
- `revoke_access_token(session)` *(async function)* — "Revoke one access token that belongs to no grant."
- `record_auth_event(session)` *(async function)* — "Persist one authentication event on its own."
- `purge_expired_audit_events(session)` *(async function)* — "Drop **authentication** audit rows older than the window. Returns how many."
- `store_message_receipt(session, message_id, executor_id, message_type)` *(async function)*
- `list_tasks_page(session)` *(async function)* — "Tasks the caller may see, newest first, over-fetched by one."
- `get_task_for_projects(session, task_id, project_ids)` *(async function)* — "A task the caller may see, or None."
- `get_recent_logs(session, task_id)` *(async function)* — "The most recent log lines, oldest-first within the slice."
- `list_tasks_requiring_cancel_replay(session, executor_id)` *(async function)* — "Cancelled tasks whose executor has not yet acknowledged the cancellation."
- `list_tasks_requiring_control_replay(session, executor_id)` *(async function)* — "Tasks stuck in a pending pause/resume/restart, waiting for a `task.ack`"
- `list_decisions_page(session)` *(async function)* — "Decisions the caller may see, newest first, over-fetched by one (issue #6)."
- `get_decision_for_projects(session, decision_id, project_ids)` *(async function)* — "A decision the caller may see, or None — "not a decision" included (issue #6)."
- `mission_risk(task)` — "The mission-control risk level for one task (issue #7). See `_risk_filter_clause`."
- `mission_stage(task)`
- `list_missions_page(session)` *(async function)* — "Missions (tasks, in mission-control framing) the caller may see, newest"
- `list_task_events_page(session, task_id)` *(async function)* — "A mission's timeline, oldest first — the order a narrative reads in (issue #7)."
- `create_epic(session)` *(async function)*
- `get_epic(session, epic_id)` *(async function)*
- `get_epic_for_projects(session, epic_id, project_ids)` *(async function)* — "An epic the caller may see, or None. Mirrors `get_task_for_projects`."
- `list_epics_page(session)` *(async function)* — "Epics in one project, newest first, over-fetched by one."
- `create_issue(session)` *(async function)*
- `get_issue(session, issue_id)` *(async function)*
- `get_issue_for_projects(session, issue_id, project_ids)` *(async function)*
- `list_issues_page(session)` *(async function)*
- `update_issue(session, issue_id)` *(async function)*
- `link_issue_to_epic(session)` *(async function)* — "Attach `issue_id` to `epic_id`. Both must already exist in one project."
- `create_conversation(session)` *(async function)* — "Create a conversation from an already-resolved, already-authorized context."
- `get_conversation(session, conversation_id)` *(async function)*
- `get_conversation_for_projects(session, conversation_id, project_ids)` *(async function)* — "A conversation the caller may see, or None. Mirrors `get_epic_for_projects`."
- `list_conversations_page(session)` *(async function)* — "Conversations the caller may see, newest-created first, over-fetched by one."
- `conversation_read_states(session)` *(async function)* — "`{conversation_id: last_read_at}` for one actor, over the given ids."
- `conversation_unread()` — "Whether an actor has unseen activity in a conversation."
- `mark_conversation_read(session)` *(async function)* — "Advance (never retreat) one actor's read cursor on one conversation."
- `create_conversation_message(session)` *(async function)* — "Append a message. Immutable once written — there is no update path."
- `list_conversation_messages_page(session)` *(async function)* — "A conversation's messages, oldest first — the order a thread reads in."
- **`AmbiguousProjectReference`** *(class)* — "More than one project matched a `start_development_task` reference."
  - `__init__(self, candidates)` *(method)*
- `resolve_project_reference(session, text)` *(async function)* — "Resolves "project Y" to exactly one registered project."
- `estimate_task_duration_seconds(session)` *(async function)* — "A duration estimate for `start_development_task`'s `eta_seconds`."

### `scripts/apply_migrations.py`

> Apply the SQL files in `migrations/`, once each, in filename order.

- `main()`

### `shared/policy.py`

- **`PolicyDecision`** *(class)*
- `policy_level_for_mode(mode)`
- `push_branch_is_allowed(delivery)` — "Whether `delivery.branch` is a branch a pre-authorized push may target."
- `push_is_preauthorized(request)` — "Whether this request's own `delivery` block authorizes a push."
- `evaluate_task_policy(request)`

### `shared/protocol.py`

- **`AgentEngine`** *(class)* — "Which development-agent CLI runs a task's instruction."
- **`TaskMode`** *(class)*
- **`TaskState`** *(class)*
- **`PolicyLevel`** *(class)*
- **`TaskPriority`** *(class)*
- **`AgentMessageType`** *(class)*
- **`ApprovalDecision`** *(class)*
- **`ProjectRegistration`** *(class)*
- **`ExecutorRegistration`** *(class)*
- **`DeliveryRequest`** *(class)* — "What the requester authorized the executor to do with git, once a task"
- **`SubmitTaskRequest`** *(class)*
- **`ContinueSessionRequest`** *(class)*
- **`AgentEnvelope`** *(class)*
- **`ToolResponse`** *(class)*

### `shared/security.py`

- `secure_compare(left, right)`
- `hash_token(token)`
- `sanitize_log_line(line)`
- `ensure_within_root(root, target)`
- `filtered_environment(allowed_keys)`

### `tests/contract/test_docs_match_the_runtime.py`

> Prose that states a runtime fact, checked against the runtime.

- `test_the_codemap_names_every_module_it_claims_to_index()` — "`.docs/agents/programmer.md` tells the next agent to read this instead of scanning."
- `test_the_api_readme_does_not_deny_the_limiter_that_ships(denial)` — "§"Rate limiting — vocabulary only, so far" outlived the wiring."

### `tests/contract/test_openapi_document.py`

> Contract tests for the canonical OpenAPI document.

- `spec()`
- `test_specification_is_valid_openapi()`
- `test_every_exclusion_is_well_formed(spec)` — "An exclusion with no reason is a silent escape; §"Contract scope" forbids it."
- `test_gate_sees_every_route_the_app_exposes()` — "No route class may be invisible to the inventory."
- `test_generated_openapi_is_not_served()` — "The canonical document is the only description of this gateway."
- `test_no_public_route_is_missing_from_the_contract(spec)`
- `test_no_contract_path_is_unimplemented(spec)`
- `test_no_exclusion_outlives_its_route(spec)` — "A stale exclusion pre-authorizes whatever later claims that path."
- `test_contract_and_exclusions_do_not_overlap(spec)` — "A route cannot be both public API and deliberately out of scope."
- `test_served_api_routes_are_versioned_and_contracted(spec)` — "`/api/**` is the public namespace and cannot be excluded out of the contract."
- `test_contract_declares_no_unversioned_api_path(spec)` — "The same namespace rule, applied to what the document promises."
- `test_route_paths_are_well_formed(spec)` — "An unbalanced brace is a typo the router accepts and serves literally."
- `test_normalize_matches_names_but_not_converters(served, documented, equivalent)` — "snake_case vs camelCase is not drift; a converter difference is."
- `test_reported_contract_version_matches_the_document(spec)` — "`GET /api/version` must not claim a contract version the file disagrees with."
- `test_every_declared_component_is_referenced_or_owned(spec)` — "A component nothing points at is a claim the API behaves that way."
- `test_no_pending_component_is_stale(spec)` — "An entry whose component is now wired must be removed."

### `tests/contract/test_proxy_routes.py`

> Every contracted path must be routed by the proxies in front of the gateway.

- `contract_paths()`
- `test_nginx_configs_exist()` — "If the configs move, this gate must fail loudly rather than pass empty."
- `test_every_contract_path_is_routed_by_every_terminating_vhost(contract_paths)`
- `test_every_proxied_location_reaches_an_upstream()` — "A location block with no `proxy_pass` silently drops its path."

### `tests/integration/test_agent_ack_handling.py`

> `task.ack` handling in the `/agent/ws` message loop — issue #16 council.

- `factory()` *(async function)*
- `test_an_executor_cannot_ack_a_task_it_does_not_own(factory)` *(async function)*
- `test_an_ack_with_no_task_id_is_logged_not_raised(factory)` *(async function)* — "council 2026-08-18, round 2, "the adversarial user": the same class of"
- `test_an_ack_with_an_unknown_state_is_refused_not_raised(factory)` *(async function)*
- `test_a_rejected_pause_or_resume_reverts_to_the_state_it_assumed(factory, pending, control, expected_state)` *(async function)*
- `test_a_rejected_restart_is_reported_as_failed_not_left_pending(factory)` *(async function)*
- `test_an_accepted_ack_updates_state_and_is_recorded(factory)` *(async function)*
- `test_a_rejected_ack_from_a_runner_that_lost_the_task_releases_the_slot(factory, monkeypatch, control)` *(async function)* — "issue #17 council round 1, "the sweep skeptic": before `known`"
- `test_a_rejected_ack_from_a_runner_that_lost_the_task_is_not_replayed_again(factory, monkeypatch, control)` *(async function)* — "finding 11 (council round 2 on #17, "the claim auditor"): the branch"
- `test_a_rejected_ack_from_a_runner_that_lost_the_task_dispatches_the_queue(factory, monkeypatch)` *(async function)* — "finding 10 (council round 2 on #17, "the sweep skeptic"): freeing the"
- `test_an_older_agent_with_no_known_field_keeps_the_pre_existing_fallback(factory, monkeypatch)` *(async function)* — "Additive per design-standards.md §4: an agent build that predates the"

### `tests/integration/test_agent_hub.py`

- **`DummyWebSocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send_json(self, payload)` *(async method)*
- `factory()` *(async function)*
- `test_register_replays_pending_cancel_before_dispatch(factory)` *(async function)*
- `test_register_replays_a_pending_pause_that_never_got_an_ack(factory)` *(async function)* — "council 2026-08-18, "the sweep skeptic" / "the second caller": a task"
- `test_register_replays_pending_resume_and_restart_too(factory)` *(async function)*
- `test_acknowledged_cancel_is_not_replayed_and_allows_dispatch(factory)` *(async function)*
- `test_cancel_replay_expires_after_max_age(factory)` *(async function)* — "A cancellation issued long ago is not chased on reconnect (issue #17):"
- `test_cancel_replay_still_happens_within_max_age(factory)` *(async function)*
- `test_control_replay_expires_after_max_age(factory)` *(async function)* — "issue #17 council round 1, "the sweep skeptic": unlike cancel replay,"
- `test_control_replay_still_happens_within_max_age(factory)` *(async function)*

### `tests/integration/test_agent_ws_handshake.py`

> The `/agent/ws` handshake stops carrying the token in the URL — issue #15.

- `client(monkeypatch)` *(async function)* — "A real app, but wired to its own isolated in-memory database."
- `test_a_handshake_with_no_credential_is_refused(client)`
- `test_refusing_an_anonymous_handshake_touches_no_executor_record(client, monkeypatch)` — "4401 must be decided before the database, not after a lookup."
- `test_the_header_is_bound_and_reaches_the_registry_check(client)` — "An unknown executor authenticating by header gets 4404, not 4401."
- `test_the_query_parameter_still_works_and_warns(client, caplog)`
- `test_the_deprecation_warning_does_not_print_the_token(client, caplog)` — "A warning about a leaked credential must not leak it again."
- `test_the_header_path_logs_no_deprecation_warning(client, caplog)`

### `tests/integration/test_api_conventions.py`

> Representative-endpoint compliance for the cross-cutting API rules (issue #12).

- **`ApproveBody`** *(class)*
- `build_app()`
- `client()`
- `db_session()` *(async function)*
- `test_request_id_is_generated_and_echoed(client)`
- `test_client_request_id_is_honoured(client)`
- `test_hostile_request_id_is_replaced_not_echoed(client)` — "The header is written into response headers and log lines."
- `test_request_ids_differ_between_requests(client)`
- `test_validation_failure_uses_the_envelope(client)`
- `test_http_exception_inside_contract_path_uses_the_envelope(client)`
- `test_unhandled_exception_returns_envelope_without_leaking_detail(client)` — "A raw driver error names hosts, ports and schema. It stays in the log."
- `test_rate_limited_carries_retry_after(client)`
- `test_non_contract_path_keeps_framework_error_shape(client)` — "`POST /mcp` speaks JSON-RPC; reshaping it would break the live client."
- `test_real_gateway_leaves_mcp_error_shape_untouched()`
- `test_pagination_walks_every_item_exactly_once(client)`
- `test_next_cursor_is_null_exactly_when_there_is_no_more(client)`
- `test_cursor_from_another_scope_is_rejected(client)` — "A cursor is single-purpose; reinterpreting one pages through wrong rows."
- `test_malformed_cursor_is_rejected(client, cursor, expected)` — "Every rejection collapses to one message on purpose."
- `test_limit_above_maximum_is_clamped_not_rejected()`
- `test_limit_below_one_is_rejected()`
- `test_page_info_never_advertises_a_cursor_without_more()` — "The contract binds these two fields; building them apart lets them drift."
- `test_write_without_if_match_is_refused(client)`
- `test_write_with_stale_if_match_reports_stale_write(client)`
- `test_second_of_two_concurrent_approvals_loses(client)` — "The scenario the feature exists for: two operators, two devices."
- `test_if_match_star_is_accepted(client)`
- `test_strong_validator_matches_and_wrong_revision_does_not()`
- `test_weak_validator_never_matches()` — "RFC 9110 requires strong comparison for If-Match."
- `test_if_match_list_matches_when_any_member_is_current()`
- `test_task_revision_advances_on_every_mutation(db_session)` *(async function)* — "Every mutator, not a sample of them."
- `test_first_request_has_nothing_to_replay(db_session)` *(async function)*
- `test_retry_replays_the_stored_response(db_session)` *(async function)*
- `test_same_key_different_body_is_a_conflict(db_session)` *(async function)* — "Answering with the earlier response would silently drop the second write."
- `test_same_key_from_another_actor_is_a_different_operation(db_session)` *(async function)* — "Otherwise one client's retry could be answered with another's response."
- `test_same_key_at_another_endpoint_is_a_different_operation(db_session)` *(async function)*
- `test_expired_record_does_not_replay(db_session)` *(async function)*
- `test_purge_expired_removes_only_expired(db_session)` *(async function)*
- `test_fingerprint_distinguishes_bodies()`
- `test_five_hundred_reports_the_same_id_in_body_and_header(client)` — "The screenshot and the log must name the same request."
- `test_generated_request_id_also_agrees_between_header_and_body(client)` — "Same equality when the server mints the id, which is the common case."
- `test_unmatched_api_path_returns_the_envelope(client)` — "A typo'd URL is the commonest client mistake, and it missed the envelope."
- `test_non_contract_unhandled_error_keeps_a_body(client)` — "Re-raising from inside the exception handler produced a bodyless 500."
- `test_control_characters_never_reach_the_response_header(hostile)` — "`re.match` with `$` also matches before a trailing newline."
- `test_forged_cursor_is_rejected_not_executed(client)` — "The scope digest is computed from public inputs, so it authenticates nothing."
- `test_signed_cursor_with_a_wrong_position_is_a_400_not_a_500(client, position)` — "Even a genuine cursor must not hand unchecked JSON to the caller."
- `test_oversized_cursor_is_rejected_before_decoding(client)`
- `test_quoted_asterisk_is_an_entity_tag_not_the_wildcard()` — "`"*"` is a legitimate tag value; only the bare token `*` is the wildcard."
- `test_concurrent_retries_do_not_both_execute(db_session)` *(async function)* — "The window between "no record" and "record written" was a double approval."
- `test_release_lets_a_failed_write_be_retried(db_session)` *(async function)* — "Otherwise one transient failure locks the key for its whole TTL."
- `test_release_does_not_discard_a_completed_response(db_session)` *(async function)*
- `test_abandoned_reservation_does_not_lock_the_key_for_a_day(db_session)` *(async function)* — "A worker killed between reserve and complete must not strand the client."
- `test_completing_a_lost_reservation_still_records_the_write(db_session)` *(async function)* — "Otherwise the next identical request executes the side effect again."
- `test_a_completed_record_is_final(db_session)` *(async function)* — "Replacing a recorded 200 with a later 500 defeats the whole mechanism."
- `test_non_contract_unhandled_error_is_logged_once(client, caplog)` — "Two full tracebacks for one failure, on the highest-volume transport."

### `tests/integration/test_auth.py`

> The mobile credential lifecycle — issue #4.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)* — "The auth and sessions routers over a real database."
- `sign_in(api, username, password)`
- `auth(token)`
- `make_task(factory, project_id)` *(async function)*
- `audit_events(factory, event_type)` *(async function)*
- `test_sign_in_returns_a_pair_that_works(api)` *(async function)*
- `test_a_token_response_is_never_cached(api)` *(async function)* — "It carries credentials. RFC 6749 §5.1."
- `test_every_sign_in_failure_answers_the_same(api, username, password)` *(async function)* — "Anything finer turns the sign-in form into a user directory."
- `test_a_failed_sign_in_is_attributed_without_storing_what_was_typed(api)` *(async function)* — "The reason is worth keeping. The input is not: it is unvalidated, and an"
- `test_an_unconfigured_gateway_has_no_account_to_sign_in_as(api, monkeypatch)` *(async function)* — "`security-standards.md` §1: no default user password; fail-fast on missing config."
- `test_an_unconfigured_gateway_says_so_instead_of_failing_in_silence(tmp_path, monkeypatch, caplog)` *(async function)* — "Fail-closed is only half of it; the other half is saying why."
- `test_the_published_example_credential_is_refused_even_when_configured(api, monkeypatch)` *(async function)* — "Defence in depth: the operator who copies the example and forgets."
- `test_sign_in_cannot_mint_a_scope_the_server_allowlist_withholds(api, monkeypatch)` *(async function)* — "Two issuers, one token table, and only one of them had a ceiling."
- `test_rotation_cannot_restore_a_scope_the_allowlist_has_since_dropped(api, monkeypatch)` *(async function)* — "A 30-day grant must not outlive a narrowing of the allowlist."
- `test_the_audit_trail_names_the_actor_by_id_and_never_by_email(api)` *(async function)* — "`security-standards.md` §2 lists e-mail among the fields never logged."
- `test_a_credential_row_names_the_actor_by_id_and_never_by_email(api)` *(async function)* — "The scope of the test above was the defect, not its assertion."
- `test_audit_rows_past_the_retention_window_are_swept(api)` *(async function)* — "Rejected sign-ins are the first unauthenticated write into `audit_events`."
- `test_the_retention_sweep_does_not_age_out_the_approval_record(api)` *(async function)* — "The window bounds sign-in spam. It must not decide anything else."
- `test_retention_of_zero_keeps_everything(api)` *(async function)* — "An operator who exports the table elsewhere opts out explicitly."
- `test_a_sensitive_action_is_tied_to_the_actor_that_signed_in(api)` *(async function)*
- `test_no_credential_is_stored_in_the_clear(api)` *(async function)*
- `test_refresh_returns_a_new_pair(api)` *(async function)*
- `test_rotation_does_not_extend_the_grant(api)` *(async function)* — "A refresh token that renewed its own deadline would never expire, which"
- `test_replaying_a_spent_refresh_token_kills_the_whole_grant(api)` *(async function)* — "Replay and theft are indistinguishable here, so it is read as theft."
- `test_only_one_rotation_of_a_refresh_token_can_win(api)` *(async function)* — "Single use has to survive two requests arriving together."
- `test_an_expired_refresh_token_is_refused(api)` *(async function)*
- `test_an_unknown_refresh_token_is_refused(api)` *(async function)*
- `test_refresh_narrows_to_what_the_registry_says_now(api)` *(async function)* — "A 30-day refresh token must not keep minting yesterday's permissions."
- `test_refresh_ends_the_grant_when_the_account_is_disabled(api)` *(async function)* — "Otherwise disabling an account takes as long as the refresh TTL."
- `test_revoking_stops_the_access_token_immediately(api)` *(async function)*
- `test_revocation_reaches_the_credential_store_the_mcp_transport_reads(api)` *(async function)* — "One store, or a revocation honoured by one surface and not the other."
- `test_a_refresh_token_alone_can_sign_out(api)` *(async function)* — "The usual moment to sign out is after the access token has expired."
- `test_revocation_is_idempotent_and_says_nothing_about_the_token(api)` *(async function)*
- `test_signing_out_twice_with_only_an_access_token_is_still_a_sign_out(api)` *(async function)* — "The second call is the one a flaky mobile connection actually makes."
- `test_an_access_token_that_was_never_issued_signs_out_quietly(api)` *(async function)* — "Same rule, reached from the other side: incurious about the credential."
- `test_a_consumed_refresh_token_still_ends_its_own_grant(api)` *(async function)* — "Pinned on purpose — this behaviour is a decision, not an accident."
- `test_revoking_nothing_is_refused(api)` *(async function)*
- `test_revocation_is_recorded_against_the_actor(api)` *(async function)*
- `test_me_requires_a_token(api)` *(async function)*
- `test_me_refuses_an_expired_token(api)` *(async function)*
- `test_every_401_on_this_surface_is_the_same_401(api)` *(async function)* — "Four places claimed this and it was not true."
- `test_a_disabled_account_is_asked_to_sign_in_again_not_told_it_may_not(api)` *(async function)* — "401, not 403 — and `/api/v1/auth/me` declares no 403 at all."
- `test_me_reports_the_actor_and_its_projects(api)` *(async function)*
- `test_me_marks_an_admin_as_seeing_every_project(api)` *(async function)*
- `test_me_separates_read_operational_and_administrative(api)` *(async function)* — "The three classes the issue asks for, reported per action."
- `test_every_catalogued_action_is_exercised_below()` — "A new action must extend the table, or it ships unchecked."
- `test_each_exemption_names_a_test_that_exists()` — "An exemption pointing at nothing is an exemption with no coverage behind it."
- `test_the_guard_flags_a_new_administrative_action(monkeypatch)` — "The guard is only worth having if it fires — so fire it."
- `test_the_report_and_the_endpoints_agree(api, who)` *(async function)* — "The claim the whole endpoint exists for."
- `test_the_administrative_action_describes_what_the_list_endpoint_does(api)` *(async function)* — "`sessions.readAllProjects` is administrative because it crosses projects."
- `test_the_administrative_action_describes_what_the_missions_list_endpoint_does(api)` *(async function)* — "`missions.readAllProjects` mirrors `sessions.readAllProjects` — same widening."

### `tests/integration/test_claude_runner_real_process.py`

> ClaudeRunner against a REAL `claude` subprocess — not the fakes used elsewhere.

- `test_run_task_drives_a_real_claude_process_end_to_end(tmp_path)` *(async function)*
- `test_run_task_read_only_blocks_a_real_write_attempt(tmp_path)` *(async function)* — "Finding 2's real-world consequence, proven rather than assumed: the"
- `test_run_task_actually_writes_when_dispatched_with_workspace_write_sandbox(tmp_path)` *(async function)*
- `test_run_task_resume_actually_continues_the_real_session(tmp_path)` *(async function)*

### `tests/integration/test_codex_runner_real_process.py`

> CodexRunner against a REAL `codex` subprocess — not the fake used everywhere else.

- `test_run_task_drives_a_real_codex_process_end_to_end(tmp_path)` *(async function)* — "A real `codex exec --json -C <dir> -o <file> <instruction>` subprocess,"
- `test_run_task_actually_writes_when_dispatched_with_workspace_write_sandbox(tmp_path)` *(async function)* — "The override side of finding (3): the same scratch repo, still not"
- `test_run_task_resume_actually_resumes_the_real_session(tmp_path)` *(async function)* — "Finding (2), now fixed, driven through `run_task` itself end to end:"

### `tests/integration/test_conversations.py`

> Conversations and contextual messaging — issue #10.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)*
- `auth(token)`
- `make_task(factory, project_id)` *(async function)*
- `make_issue(factory, project_id, **kwargs)` *(async function)*
- `make_conversation(factory)` *(async function)*
- `create_payload(context, title)`
- `test_conversations_require_a_token(api)` *(async function)*
- `test_reader_cannot_create_a_conversation_or_post_a_message(api)` *(async function)*
- `test_reader_can_still_list_get_and_read_messages(api)` *(async function)*
- `test_a_conversation_in_an_invisible_project_is_not_found(api)` *(async function)* — "404, never 403 — confirming existence is what probing is for."
- `test_create_requires_at_least_one_context_reference(api)` *(async function)*
- `test_create_rejects_an_unknown_context_type(api)` *(async function)*
- `test_create_with_a_context_reference_in_a_hidden_project_is_not_found(api)` *(async function)* — "Unauthorized entity references are rejected without disclosing hidden resources."
- `test_create_with_an_unknown_context_id_is_not_found(api)` *(async function)* — "A reference to something that does not exist answers exactly like a hidden one."
- `test_create_rejects_context_references_spanning_two_projects(api)` *(async function)*
- `test_create_accepts_a_session_decision_or_mission_reference_to_the_same_task(api)` *(async function)* — "session/decision/mission all name the same TaskModel row."
- `test_create_derives_project_id_from_the_context_and_deduplicates(api)` *(async function)*
- `test_a_project_outside_the_caller_visibility_is_not_found_when_used_as_context(api)` *(async function)*
- `test_a_retried_conversation_create_does_not_create_a_second_conversation(api)` *(async function)*
- `test_post_message_stores_markdown_and_attachments_verbatim(api)` *(async function)*
- `test_post_message_rejects_an_empty_body(api)` *(async function)*
- `test_post_message_rejects_an_oversized_attachment_id(api)` *(async function)* — "`MAX_ATTACHMENT_ID_LENGTH` (255) must be enforced, same as its three"
- `test_a_retried_message_post_does_not_create_a_second_message(api)` *(async function)* — "Message creation is idempotent for offline retries — the acceptance criterion."
- `test_the_same_key_with_a_different_body_is_a_conflict(api)` *(async function)* — "Reusing a key for a different payload is a client bug, not a silent replay."
- `test_a_message_without_an_idempotency_key_is_never_deduplicated(api)` *(async function)* — "No key means no replay protection — each call is a genuinely new message."
- `test_a_new_message_makes_the_conversation_unread_for_others(api)` *(async function)*
- `test_fetching_messages_marks_the_conversation_read(api)` *(async function)*
- `test_an_early_page_of_messages_does_not_mark_later_ones_read(api)` *(async function)* — "Fetching the oldest page must not silently mark newer, unfetched messages seen."
- `test_an_empty_conversation_is_never_unread(api)` *(async function)*
- `test_the_conversation_list_cursor_walks_every_conversation_once(api)` *(async function)*
- `test_the_message_list_cursor_walks_every_message_once_oldest_first(api)` *(async function)*
- `test_a_conversation_cursor_from_a_different_project_is_rejected(api)` *(async function)*
- `test_list_conversations_filters_by_project(api)` *(async function)*

### `tests/integration/test_decisions.py`

> Operational decisions — issue #6.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)* — "A real app over a real database, seeded with two projects."
- `make_decision(factory, project_id, instruction, requested_by_user_id, requested_by_email)` *(async function)*
- `make_plain_task(factory, project_id)` *(async function)* — "A task nobody was ever asked to decide on — not a decision."
- `auth(token)`
- `audit_events(factory, event_type)` *(async function)*
- `test_decisions_require_a_token(api)` *(async function)*
- `test_an_expired_token_is_refused(api)` *(async function)*
- `test_a_decision_in_an_invisible_project_is_not_found_not_forbidden(api)` *(async function)*
- `test_a_plain_task_is_not_a_decision(api)` *(async function)* — "A session id that exists but never needed approval is not found here."
- `test_the_list_is_filtered_before_it_is_paged(api)` *(async function)*
- `test_the_cursor_walks_every_decision_once(api)` *(async function)* — "`list_decisions_page` reuses `pagination.paginate`'s over-fetch-by-one"
- `test_the_project_filter_only_narrows_never_widens(api)` *(async function)*
- `test_the_decision_body_never_carries_the_project_path(api)` *(async function)*
- `test_the_request_field_is_redacted(api)` *(async function)*
- `test_state_filter_separates_pending_from_resolved(api)` *(async function)*
- `test_risk_and_urgency_filters(api)` *(async function)*
- `test_deadline_filters(api)` *(async function)*
- `test_reading_needs_no_approval_scope(api)` *(async function)*
- `test_deciding_needs_the_approve_scope(api)` *(async function)*
- `test_the_scope_alone_is_not_enough_for_a_sensitive_decision(api)` *(async function)* — "`can_approve_sensitive` is checked on top of `codexbridge.task.approve`."
- `test_auth_me_agrees_with_the_untrusted_approver_gate(api)` *(async function)* — "`GET /auth/me` is not mounted in this fixture; assert the function it calls."
- `test_approve_requires_if_match(api)` *(async function)*
- `test_approve_with_a_stale_etag_is_refused(api)` *(async function)*
- `test_approving_a_critical_decision_without_confirm_is_refused(api)` *(async function)*
- `test_approving_with_confirm_resolves_the_decision(api)` *(async function)*
- `test_approving_an_already_resolved_decision_is_a_conflict(api)` *(async function)*
- `test_a_retried_approve_replays_instead_of_acting_twice(api)` *(async function)*
- `test_approve_records_the_deciding_actor(api)` *(async function)*
- `test_approving_dispatches_to_a_connected_idle_executor(api)` *(async function)*
- `test_approve_response_revision_matches_the_post_dispatch_task_after_same_request_dispatch(api)` *(async function)* — "Council round-1 finding on this issue: `_resolve` fetches `updated`"
- `test_approving_leaves_the_task_waiting_when_the_executor_is_offline(api)` *(async function)* — "No regression on the pre-existing (disconnected) case: `api.hub` has"
- `test_approving_when_the_executor_is_at_capacity_does_not_bypass_the_concurrency_gate(api)` *(async function)*
- `test_reject_never_dispatches(api)` *(async function)*
- `test_request_revision_never_dispatches(api)` *(async function)*
- `test_reject_requires_a_non_empty_reason(api)` *(async function)*
- `test_reject_with_no_body_is_refused(api)` *(async function)*
- `test_rejecting_cancels_the_underlying_session(api)` *(async function)*
- `test_rejecting_an_already_resolved_decision_is_a_conflict(api)` *(async function)*
- `test_request_revision_requires_a_non_empty_reason(api)` *(async function)*
- `test_request_revision_is_a_distinct_outcome_from_reject(api)` *(async function)*
- `test_request_revision_on_a_resolved_decision_is_a_conflict(api)` *(async function)*

### `tests/integration/test_dispatch_payload_engine_and_delivery.py`

> `AgentHub.dispatch_next` forwards engine/issue_ref/delivery to the executor.

- **`DummyWebSocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send_json(self, payload)` *(async method)*
- `factory()` *(async function)*
- `test_dispatch_omits_delivery_and_issue_ref_when_neither_was_requested(factory)` *(async function)*
- `test_dispatch_forwards_engine_issue_ref_and_delivery_when_requested(factory)` *(async function)*

### `tests/integration/test_epics_issues.py`

> Epics and issues — issue #8.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)*
- `auth(token)`
- `make_epic(factory, project_id, title)` *(async function)*
- `make_issue(factory, project_id, **kwargs)` *(async function)*
- `test_epics_and_issues_require_a_token(api)` *(async function)*
- `test_reader_cannot_create_epics_or_issues(api)` *(async function)*
- `test_reader_can_still_list_and_read(api)` *(async function)*
- `test_a_project_outside_the_caller_visibility_is_not_found(api)` *(async function)* — "404, never 403 — confirming existence is what probing is for."
- `test_an_epic_or_issue_in_an_invisible_project_is_not_found(api)` *(async function)*
- `test_create_epic(api)` *(async function)*
- `test_create_epic_rejects_an_empty_title(api)` *(async function)*
- `test_create_epic_rejects_an_unknown_status(api)` *(async function)*
- `test_a_retried_epic_create_does_not_create_a_second_epic(api)` *(async function)*
- `test_create_issue_defaults_status_and_priority(api)` *(async function)*
- `test_create_issue_normalizes_and_dedupes_labels(api)` *(async function)*
- `test_create_issue_rejects_an_unknown_priority(api)` *(async function)*
- `test_create_issue_with_an_epic_from_another_project_is_rejected(api)` *(async function)*
- `test_create_issue_with_an_unknown_dependency_is_rejected(api)` *(async function)*
- `test_create_issue_with_a_dependency_in_another_project_is_rejected(api)` *(async function)*
- `test_create_issue_records_valid_dependencies(api)` *(async function)*
- `test_get_issue_returns_an_etag(api)` *(async function)*
- `test_the_issue_body_never_carries_the_project_path(api)` *(async function)*
- `test_list_issues_filters_by_status_priority_epic_and_assignee(api)` *(async function)*
- `test_the_issue_list_cursor_walks_every_issue_once(api)` *(async function)*
- `test_an_issue_cursor_from_a_different_project_is_rejected(api)` *(async function)*
- `test_update_requires_if_match(api)` *(async function)*
- `test_update_with_a_stale_etag_is_refused(api)` *(async function)*
- `test_update_changes_only_the_mentioned_fields(api)` *(async function)*
- `test_update_can_explicitly_clear_a_nullable_field(api)` *(async function)*
- `test_update_rejects_an_unknown_status(api)` *(async function)*
- `test_update_rejects_a_self_dependency(api)` *(async function)*
- `test_update_does_not_accept_an_epic_id(api)` *(async function)* — "epicId is deliberately absent from the update body — see the link endpoint."
- `test_link_issue_to_epic(api)` *(async function)*
- `test_link_requires_if_match(api)` *(async function)*
- `test_link_rejects_an_epic_from_a_different_project(api)` *(async function)*
- `test_a_reader_cannot_link(api)` *(async function)*
- `test_a_retried_link_does_not_relink_twice(api)` *(async function)*
- `test_a_failed_link_does_not_keep_the_key_claimed(api)` *(async function)*
- `test_the_epic_list_cursor_walks_every_epic_once(api)` *(async function)*
- `test_list_epics_filters_by_status(api)` *(async function)*

### `tests/integration/test_mcp_reminders.py`

> The `create_reminder`/`cancel_reminder` MCP tools, at the `handle_mcp_call` layer.

- **`DummyHub`** *(class)*
  - `is_connected(self, executor_id)` *(method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
- `db_session()` *(async function)*
- `test_tools_list_includes_both_reminder_tools(db_session)` *(async function)*
- `test_missing_scope_is_refused(db_session)` *(async function)*
- `test_happy_path_returns_the_fake_calendars_structured_content(db_session, monkeypatch)` *(async function)*
- `test_second_call_with_the_same_idempotency_key_reports_created_false(db_session, monkeypatch)` *(async function)*
- `test_calendar_error_is_reported_as_a_client_error_not_a_500(db_session, monkeypatch)` *(async function)*
- `test_cancel_reminder_happy_path(db_session, monkeypatch)` *(async function)*
- `test_an_unconfigured_gateway_still_serves_submit_codex_task_normally(db_session, monkeypatch)` *(async function)* — "The most important test in this file: reminders being unconfigured,"

### `tests/integration/test_missions.py`

> Missions: the mission-control view of Sessions — issue #7.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)* — "A real app over a real database, seeded with two projects."
- `make_task(factory, project_id, instruction, mode, state)` *(async function)*
- `auth(token)`
- `test_missions_require_a_token(api)` *(async function)*
- `test_an_expired_token_is_refused(api)` *(async function)*
- `test_a_mission_in_an_invisible_project_is_not_found_not_forbidden(api)` *(async function)*
- `test_the_list_is_filtered_before_it_is_paged(api)` *(async function)*
- `test_the_mission_body_never_carries_the_project_path(api)` *(async function)*
- `test_objective_and_assigned_agent_are_the_instruction_and_the_executor(api)` *(async function)*
- `test_stage_groups_state_into_three_phases(api, state, stage)` *(async function)*
- `test_risk_is_derived_from_mode(api, mode, risk)` *(async function)*
- `test_a_sensitive_instruction_overrides_risk_to_sensitive(api)` *(async function)* — "The keyword-escalation path recorded on `approval_state` at creation."
- `test_a_mission_awaiting_approval_is_blocked_with_a_reason(api)` *(async function)*
- `test_a_running_mission_is_not_blocked(api)` *(async function)*
- `test_stage_filter_restricts_the_list(api)` *(async function)*
- `test_state_and_stage_together_intersect(api)` *(async function)*
- `test_risk_filter_restricts_the_list(api)` *(async function)*
- `test_blocked_filter_restricts_the_list(api)` *(async function)*
- `test_project_filter_is_intersected_with_visibility(api)` *(async function)*
- `test_the_cursor_walks_every_mission_once(api)` *(async function)*
- `test_timeline_of_an_invisible_mission_is_not_found(api)` *(async function)*
- `test_timeline_reports_creation_and_state_changes_oldest_first(api)` *(async function)*
- `test_timeline_pages_by_cursor(api)` *(async function)*
- `test_a_mission_timeline_cursor_is_not_valid_for_another_mission(api)` *(async function)*
- `test_timeline_entries_are_redacted(api)` *(async function)*
- `test_a_token_without_the_scope_cannot_cancel(api)` *(async function)*
- `test_cancel_requires_if_match(api)` *(async function)*
- `test_cancel_with_a_stale_etag_is_refused(api)` *(async function)*
- `test_cancel_transitions_a_running_mission_and_notifies_the_executor(api)` *(async function)*
- `test_cancelling_a_finished_mission_is_a_conflict(api)` *(async function)* — "State-transition validation — issue #7's acceptance criterion."
- `test_cancel_an_already_cancelled_mission_is_also_a_conflict(api)` *(async function)*
- `test_a_disconnected_executor_does_not_block_cancel(api)` *(async function)*
- `test_a_retried_cancel_replays_instead_of_acting_twice(api)` *(async function)*
- `test_cancel_is_audited_with_the_actor(api)` *(async function)* — "Destructive commands require authenticated actor context and are audited."
- `test_cancel_accepts_no_body_exactly_as_before(api)` *(async function)* — "Issue #36 is additive: a client that sends no body at all must still work."
- `test_cancel_records_an_operator_typed_reason(api)` *(async function)* — "Issue #36: the reason has somewhere to go, on the same audit event."
- `test_cancel_with_no_reason_records_none(api)` *(async function)* — "No `reason` is sent — the field must not silently default to something else."
- `test_the_cancel_reason_appears_on_the_timeline(api)` *(async function)*
- `test_a_reused_idempotency_key_with_a_different_reason_is_a_conflict(api)` *(async function)* — "Same shape as `routes/decisions.py`'s reason-in-fingerprint: a reused key"
- `test_cancel_releases_the_executor_slot(api)` *(async function)*
- `test_explain_reports_mission_control_fields_alongside_evidence(api)` *(async function)*
- `test_explain_on_a_blocked_mission_reports_it(api)` *(async function)*
- `test_explain_of_an_invisible_mission_is_not_found(api)` *(async function)*

### `tests/integration/test_oauth_authorize.py`

> The browser OAuth form — the *other* caller of the password check.

- `browser(tmp_path, monkeypatch)` *(async function)*
- `concurrent_browser(tmp_path, monkeypatch)` *(async function)* — "The same app, driven by a client that can have requests in flight at once."
- `test_a_wrong_password_costs_the_same_for_a_real_and_an_invented_account(browser)` *(async function)* — "Otherwise `/oauth/authorize` enumerates every account in the registry."
- `test_a_disabled_account_cannot_complete_the_browser_flow(browser)` *(async function)* — "The short-circuit this replaced also enforced `enabled`; keep it enforced."
- `test_a_flood_of_bad_logins_does_not_stall_the_liveness_probe(concurrent_browser)` *(async function)* — "A key derivation on the event loop takes the whole process down with it."
- `test_the_browser_login_form_has_an_attempt_ceiling(browser, monkeypatch)` — "`/oauth/authorize` was the one auth endpoint with no limiter at all."
- `test_no_request_handler_derives_a_key_on_the_event_loop()` — "The threadpool hop has to be unforgettable, not merely present."
- `test_no_module_outside_the_registry_verifies_a_password_itself()` — "The guard has to be unforgettable, not merely present."

### `tests/integration/test_probes.py`

> Health, readiness and version — issue #3.

- `client()`
- `test_health_is_ok_and_carries_a_request_id(client)`
- `test_health_needs_no_authentication(client)` — "A probe that needs a credential cannot be used before authenticating."
- `test_health_touches_no_dependency(client, monkeypatch)` — "Liveness must not depend on a dependency."
- `test_ready_does_not_disclose_executor_presence_by_default(client)` — "The boolean charts when the operator's machines are online."
- `response_text(client, path)`
- `test_ready_reports_degraded_when_executor_state_is_exposed(client, monkeypatch)` — "With the setting on, degraded is still 200: reads work, traffic flows."
- `test_ready_is_ready_when_an_executor_is_connected(client, monkeypatch)`
- `test_ready_is_503_when_the_database_is_unavailable(client, monkeypatch)`
- `test_probe_database_swallows_the_driver_error(monkeypatch)` *(async function)* — "The branch that must never leak, driven for real."
- `test_unavailable_ready_body_contains_no_driver_text(client, monkeypatch)` — "And the response built from that `False` carries none of it."
- `test_api_version_reports_every_namespace_it_serves(client)` — "It sits outside /api/v1 precisely so it can answer for all namespaces."
- `test_capability_flags_match_what_the_served_routes_accept(client)` — "A `true` flag a client acts on must not produce a 404 or be ignored."
- `test_error_envelope_capability_is_demonstrated_not_asserted(client)` — "`errorEnvelope: true` is the one flag with no request signature."
- `test_api_version_omits_build_revision_when_the_deployment_injected_none(client)` — "Absence means "not reported", never "no build" — so no empty string."
- `test_api_version_reports_build_revision_when_set(client, monkeypatch)`
- `test_probe_responses_carry_no_infrastructure_detail(client)` — "The acceptance criterion "no sensitive infrastructure details", asserted."
- `test_api_version_is_rate_limited_with_the_contract_shape(monkeypatch)` — "The contract documents 429 + Retry-After; before this it documented only."
- `test_health_and_ready_are_never_rate_limited(monkeypatch)` — "Monitoring polls these on a timer."
- `test_the_caller_is_found_on_both_ingress_paths(monkeypatch)` — "A fixed hop count cannot be right for both, so the rule is "which are ours"."
- `test_two_clients_do_not_share_a_bucket(monkeypatch)` — "The round-1 defect: one abuser exhausting the window for everybody."
- `test_a_client_cannot_forge_an_extra_hop(monkeypatch)` — "Prepending junk must not move the caller off its own bucket."
- `test_header_from_an_untrusted_peer_is_ignored(monkeypatch)` — "The gateway binds 0.0.0.0, so anything on the LAN can reach it directly."
- `test_unconfigured_trusted_proxies_ignores_the_header(monkeypatch)` — "A wrong value is worse than none, so none must be safe rather than a guess."
- `test_unresolvable_forwarded_for_falls_back_to_one_shared_bucket(header, monkeypatch)` — "A trailing comma once produced the literal bucket `"ip:"` — keyed on nothing."
- `test_no_forwarded_header_keys_on_the_peer(monkeypatch)` — "Direct access, no proxy in the path: the peer IS the client."
- `test_no_header_from_a_trusted_proxy_is_not_keyed_on_the_proxy(monkeypatch)` — "Otherwise everyone arriving through that proxy shares its address."
- `test_addresses_are_normalized_so_spellings_do_not_split_buckets(monkeypatch)` — "A bucket that splits on spelling is a bucket an attacker can multiply."
- `test_ready_is_cached_so_a_flood_cannot_drain_the_connection_pool(monkeypatch)` — "`/ready` is unauthenticated and unlimited, and shares the API's pool."
- `test_readiness_cache_expires(monkeypatch)` *(async function)* — "Cached, not frozen: a recovered database must be noticed."
- `test_a_failed_probe_is_cached_only_briefly(monkeypatch)` *(async function)* — "A blip must not pin the gateway out of rotation for the whole TTL."
- `test_a_concurrent_burst_issues_one_probe(monkeypatch)` *(async function)* — "The cache alone does not help while the first probe is still running."
- `test_zero_cache_seconds_is_floored(monkeypatch)` — "A TTL of 0 would restore the uncached DoS, so it is not honoured."
- `test_every_served_api_route_carries_the_rate_limiter()` — "`main.py` claimed every future /api route inherits the limiter. It does not."

### `tests/integration/test_project_and_eta_resolution.py`

> `resolve_project_reference` and `estimate_task_duration_seconds`.

- `db_session()` *(async function)*
- `test_resolves_exact_project_id(db_session)` *(async function)*
- `test_resolves_exact_name_case_insensitively(db_session)` *(async function)*
- `test_resolves_a_unique_prefix(db_session)` *(async function)*
- `test_ambiguous_prefix_names_every_candidate_and_never_guesses(db_session)` *(async function)*
- `test_unknown_reference_raises_unknown_project(db_session)` *(async function)*
- `test_empty_reference_raises_unknown_project(db_session)` *(async function)*
- `test_a_percent_or_underscore_in_the_reference_is_not_a_wildcard(db_session)` *(async function)* — "`_like_escape` must neutralize SQL LIKE metacharacters in"
- `test_reports_no_estimate_with_zero_samples(db_session)` *(async function)*
- `test_uses_the_narrowest_basis_once_it_has_enough_samples(db_session)` *(async function)*
- `test_widens_to_project_and_mode_when_the_engine_specific_sample_is_too_thin(db_session)` *(async function)*
- `test_widens_to_global_mode_and_finally_to_none(db_session)` *(async function)*
- `test_median_not_mean_so_one_outlier_does_not_dominate(db_session)` *(async function)*

### `tests/integration/test_projects.py`

> Projects and the project operational dashboard — issue #5.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)* — "A real app over a real database, seeded with two projects and one executor."
- `make_task(factory, project_id, instruction, state)` *(async function)*
- `mark_live(factory, executor_id)` *(async function)*
- `set_last_seen(factory, executor_id, when)` *(async function)* — "Force a specific `last_seen_at` without going through a heartbeat."
- `add_project(factory, project_id)` *(async function)*
- `auth(token)`
- `test_projects_require_a_token(api)` *(async function)*
- `test_an_expired_token_is_refused(api)` *(async function)*
- `test_a_token_without_the_read_scope_is_forbidden(api)` *(async function)*
- `test_a_project_outside_the_callers_scope_is_not_found_not_forbidden(api)` *(async function)* — "404 confirms the identifier exists, which is what probing is for."
- `test_the_same_scope_rule_applies_to_summary(api)` *(async function)*
- `test_the_list_is_filtered_before_it_is_paged(api)` *(async function)*
- `test_a_user_with_no_projects_sees_nothing(api, users_file, monkeypatch)` *(async function)*
- `test_the_project_body_never_carries_the_filesystem_path(api)` *(async function)*
- `test_health_is_unknown_when_no_executor_names_the_project(api)` *(async function)*
- `test_health_is_degraded_when_the_assigned_executor_is_not_live(api)` *(async function)*
- `test_health_is_ok_when_the_assigned_executor_is_live(api)` *(async function)*
- `test_a_stale_heartbeat_reads_as_not_live_even_though_the_column_says_connected(api)` *(async function)* — "The bug `store.executor_is_live` exists to close."
- `test_health_is_disabled_for_a_disabled_project_regardless_of_executors(api)` *(async function)*
- `test_counts_reflect_task_state(api)` *(async function)*
- `test_a_project_with_no_sessions_reports_zero_not_a_missing_field(api)` *(async function)*
- `test_last_activity_reflects_the_newest_session(api)` *(async function)*
- `test_the_list_carries_the_same_counts_as_the_detail_read(api)` *(async function)* — "The list must not be a lighter lie than the detail endpoint."
- `test_issues_and_artifacts_are_not_invented(api)` *(async function)* — "No `IssueModel`/`ArtifactModel` exists yet; an always-zero field would"
- `test_summary_reports_the_executor_breakdown(api)` *(async function)*
- `test_summary_never_reports_a_host_or_port(api)` *(async function)* — "`docs/api/README.md` "Fields that must never ship" — no hostname, no port."
- `test_search_matches_id_or_name_case_insensitively(api)` *(async function)*
- `test_status_filters_by_enabled(api)` *(async function)*
- `test_an_invalid_status_value_is_rejected(api)` *(async function)*
- `test_attention_surfaces_projects_needing_a_decision_or_unhealthy(api)` *(async function)*
- `test_attention_does_not_flag_a_disabled_project(api)` *(async function)* — "A disabled project was turned off on purpose; that is not a surprise."
- `test_the_cursor_walks_every_project_once(api)` *(async function)*
- `test_the_cursor_walks_every_project_once_under_attention(api)` *(async function)* — "The in-memory-paginated path (`attention` set) must not repeat or skip either."
- `test_a_cursor_from_another_filter_is_rejected(api)` *(async function)*
- `test_a_cursor_is_not_valid_for_another_caller(api)` *(async function)* — "The caller's scope is bound into the cursor, same rule as sessions."

### `tests/integration/test_push_preauthorization.py`

> Push pre-authorization is resolved as a recorded approval, never a bypass.

- `db_session()` *(async function)*
- `test_preauthorized_push_resolves_automatically_when_caller_may_approve(db_session)` *(async function)*
- `test_preauthorized_push_waits_for_a_human_without_approval_authority(db_session)` *(async function)*
- `test_push_to_main_is_never_created_pending_or_otherwise(db_session)` *(async function)* — "`main` fails `PUSHABLE_BRANCH_PATTERN`, so this is an ordinary"
- `test_restart_clears_delivery_result_but_not_the_request(db_session)` *(async function)*

### `tests/integration/test_reconnect_replay_resolves.py`

> Issue #17 council round 1 — the headline scenario named by findings 1, 4

- **`DummyGatewaySocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send_json(self, payload)` *(async method)*
- `factory()` *(async function)*
- `test_issue_17_headline_scenario_no_longer_stalls_the_queue(factory, monkeypatch)` *(async function)*
- `test_rejected_approval_of_a_never_dispatched_task_does_not_pin_the_slot(factory, monkeypatch)` *(async function)* — "The second scenario in finding 1: a task that was never dispatched at"
- `test_cancel_ack_immediately_dispatches_the_next_queued_task(factory, monkeypatch)` *(async function)* — "finding 10 (council round 2 on #17, "the sweep skeptic"): the two tests"

### `tests/integration/test_sessions.py`

> Agent sessions, logs and control — issue #9.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)* — "A real app over a real database, seeded with two projects."
- `make_task(factory, project_id, instruction, state)` *(async function)*
- `auth(token)`
- `test_sessions_require_a_token(api)` *(async function)* — "These endpoints carry the operator's instructions and logs."
- `test_an_expired_token_is_refused(api)` *(async function)*
- `test_a_token_without_the_scope_cannot_stop(api)` *(async function)*
- `test_a_session_in_an_invisible_project_is_not_found_not_forbidden(api)` *(async function)* — "403 confirms the identifier exists, which is what probing is for."
- `test_the_list_is_filtered_before_it_is_paged(api)` *(async function)* — "Filtering after loading makes hasMore describe rows the caller cannot see."
- `test_a_user_with_no_projects_sees_nothing(api, users_file, monkeypatch)` *(async function)* — "An empty allowlist must not be mistaken for "unrestricted"."
- `test_the_session_body_never_carries_the_project_path(api)` *(async function)* — "`ProjectModel.path` is the canonical trap named by the contract."
- `test_the_cursor_walks_every_session_once(api)` *(async function)*
- `test_a_cursor_from_another_filter_is_rejected(api)` *(async function)*
- `test_logs_page_by_offset_and_resume(api)` *(async function)*
- `test_log_lines_are_redacted_on_the_way_out(api, stored, must_not_contain)` *(async function)* — "Stored log text is not safe: the gateway's own log carried a token (#15)."
- `test_logs_of_an_invisible_session_are_not_found(api)` *(async function)*
- `test_stop_requires_if_match(api)` *(async function)*
- `test_stop_with_a_stale_etag_is_refused(api)` *(async function)*
- `test_stop_cancels_and_tells_the_executor(api)` *(async function)*
- `test_stopping_a_finished_session_is_a_conflict(api)` *(async function)*
- `test_a_disconnected_executor_does_not_block_the_stop(api)` *(async function)* — "Refusing here strands the operator exactly when they most want to stop."
- `test_a_retried_stop_replays_instead_of_acting_twice(api)` *(async function)*
- `test_a_failed_stop_does_not_keep_the_key_claimed(api)` *(async function)* — "One transient refusal must not lock the key for its whole TTL."
- `test_pause_marks_the_session_pausing_and_tells_the_executor(api)` *(async function)*
- `test_pause_requires_a_connected_executor(api)` *(async function)*
- `test_resume_marks_the_session_resuming_and_tells_the_executor(api)` *(async function)*
- `test_restart_marks_the_session_restarting_and_tells_the_executor(api)` *(async function)*
- `test_restart_of_a_finished_session_re_queues_it(api)` *(async function)* — "A completed session is in FINISHED_RESTARTABLE, so restart succeeds and"
- `test_restart_of_a_rejected_session_is_a_conflict(api)` *(async function)*
- `test_restart_of_a_finished_session_needs_a_connected_executor(api)` *(async function)*
- `test_explain_error_reports_the_recorded_evidence(api)` *(async function)*
- `test_explain_error_on_a_healthy_session_says_so(api)` *(async function)*
- `test_explain_error_of_an_invisible_session_is_not_found(api)` *(async function)*
- `test_stop_releases_the_executor_slot(api)` *(async function)* — "A cancelled RUNNING task must not pin the executor's concurrency slot."
- `test_stop_reports_whether_the_executor_was_told(api)` *(async function)*
- `test_a_cursor_on_a_whole_second_timestamp_does_not_truncate(api)` *(async function)* — "`str(datetime)` drops ".000000" on a whole second."
- `test_a_cursor_is_not_valid_for_another_caller(api)` *(async function)* — "A cursor issued to one principal must not position another's pagination."
- `test_the_replayed_stop_carries_an_etag(api)` *(async function)* — "The contract declares ETag on this 200, and a retrying client needs one."
- `test_explain_error_reports_the_newest_stderr(api)` *(async function)* — "Reading the first 1000 lines and slicing the end returns the OLDEST."
- `test_more_secret_shapes_are_redacted(api, stored, must_not_contain)` *(async function)* — "Each of these reached the client verbatim before an adversarial pass."
- `test_terminal_escapes_are_stripped(api)` *(async function)* — "`]0;title` retitles a CLI consumer's window."
- `test_the_instruction_is_redacted_like_everything_else(api)` *(async function)* — "It sat raw beside a redacted lastError; it is free text a human writes."

### `tests/integration/test_start_development_task.py`

> The `start_development_task` MCP tool -- the conversational entry point.

- **`DummyHub`** *(class)*
  - `__init__(self)` *(method)*
  - `is_connected(self, executor_id)` *(method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
- `db_session()` *(async function)*
- `test_happy_path_resolves_project_and_returns_eta_fields(db_session)` *(async function)*
- `test_resolves_project_by_unique_prefix(db_session)` *(async function)* — ""unclai" resolves uniquely to "unclaimed" -- proven by getting past"
- `test_ambiguous_project_reference_is_409_naming_every_candidate(db_session)` *(async function)*
- `test_unknown_project_reference_is_404(db_session)` *(async function)*
- `test_project_not_onboarded_names_both_allowlist_files(db_session)` *(async function)*
- `test_allow_push_without_approval_authority_is_refused(db_session)` *(async function)*
- `test_allow_push_without_a_branch_is_refused(db_session)` *(async function)*
- `test_allow_push_to_an_unpushable_branch_is_refused(db_session)` *(async function)*
- `test_allow_push_on_a_valid_branch_creates_a_preauthorized_task(db_session)` *(async function)*
- `test_issue_ref_invalid_shape_is_refused(db_session)` *(async function)*
- `test_github_issue_reference_is_explicitly_unsupported(db_session)` *(async function)*
- `test_neither_request_nor_issue_is_refused(db_session)` *(async function)*
- `test_local_issue_reference_builds_a_default_request_from_its_title(db_session)` *(async function)*
- `test_local_issue_reference_in_another_project_is_unknown(db_session)` *(async function)*
- `test_bare_issue_number_with_no_request_builds_a_generic_objective(db_session)` *(async function)* — ""docs:NNN"/bare NNN forms are resolved on the EXECUTOR, not the"
- `test_eta_reflects_real_task_history(db_session)` *(async function)*

### `tests/integration/test_store_and_mcp.py`

- **`DummyHub`** *(class)*
  - `__init__(self)` *(method)*
  - `is_connected(self, executor_id)` *(method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
  - `mark_task_finished(self, executor_id, task_id)` *(async method)*
- `db_session()` *(async function)*
- `test_offline_task_rejected_without_queue(db_session)` *(async function)*
- `test_offline_task_queued_when_allowed(db_session)` *(async function)*
- `test_project_allowlist_enforced(db_session)` *(async function)*
- `test_mcp_list_projects_filters_by_executor(db_session)` *(async function)*
- `test_mcp_submit_task_rejects_project_outside_user_scope(db_session)` *(async function)*
- `test_task_logs_and_status_are_limited_to_task_owner(db_session)` *(async function)*
- `test_approval_moves_task_back_to_queue(db_session)` *(async function)*
- `test_mcp_cancel_of_a_disconnected_running_task_writes_cancelled(db_session)` *(async function)* — "Issue #17's own context claims the HTTP `/stop` endpoint and the MCP"
- `test_mcp_cancel_of_a_connected_running_task_sends_and_writes_cancelled(db_session)` *(async function)*
- `test_mcp_cancel_of_a_pending_control_state_writes_cancelled(db_session, pending_state)` *(async function)* — "Review of #17's own delivery: `cancel_codex_task` matched only RUNNING,"
- `test_mcp_cancel_records_who_cancelled_it(db_session, initial_state, connect_executor, slot_was_held)` *(async function)* — "issue #17 council round 1, "the second caller": HTTP `/stop` records"
- `test_startup_recovery_marks_running_as_lost(db_session)` *(async function)*
- `test_startup_recovery_marks_pending_control_states_as_lost(db_session, pending_state)` *(async function)* — "council 2026-08-18, round 2, "the second caller": issue #16 added these"
- `mcp_hub_factory()` *(async function)* — "A session factory over a fresh database, seeded like `db_session` but"
- `test_mcp_approve_dispatches_to_a_connected_idle_executor(mcp_hub_factory)` *(async function)* — "Issue #20 asks this of the REST path specifically because the MCP"
- `test_mcp_approve_records_the_deciding_actor(mcp_hub_factory)` *(async function)* — "Issue #19: only the generic `task.approval_decision` (written inside"
- `test_mcp_reject_and_request_revision_do_not_dispatch(mcp_hub_factory)` *(async function)*
- `test_mcp_continue_codex_session_succeeds_without_datetime_crash(mcp_hub_factory)` *(async function)* — "Issue #23: `continue_codex_session` forwards `parent.expires_at` —"
- `test_mcp_continue_codex_session_dispatches_to_a_connected_idle_executor(mcp_hub_factory)` *(async function)* — "Issue #24: unlike its sibling `submit_codex_task` (same file), this"
- `test_mcp_continue_codex_session_leaves_task_queued_when_the_executor_is_offline(mcp_hub_factory)` *(async function)* — "No regression on the pre-existing (disconnected) case: an offline"
- `test_mcp_continue_codex_session_at_capacity_does_not_dispatch(mcp_hub_factory)` *(async function)* — "A connected executor already at its concurrency limit must not be sent"

### `tests/unit/test_agent_auth.py`

> Credential resolution for the `/agent/ws` handshake — issue #15.

- `test_header_is_the_new_path()`
- `test_query_still_authenticates_during_the_transition()` — "Gateway and agent deploy independently, so the old form must keep working."
- `test_header_wins_when_both_are_present()` — "An agent already on the header must not be downgraded by a stale query."
- `test_nothing_presented_is_absent_not_empty_string()`
- `test_blank_values_do_not_count_as_a_credential(blank)` — "`?token=` is not a presented credential."
- `test_a_blank_header_falls_through_to_the_query()` — "Proxies that inject empty headers must not break the transition path."

### `tests/unit/test_agent_service.py`

- **`DummyWebSocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send(self, payload)` *(async method)*
- **`FailingRunner`** *(class)*
  - `mark_dispatched(self, _)` *(method)*
  - `forget(self, _)` *(method)*
  - `run_task(self, **_)` *(async method)*
- **`ControlRunner`** *(class)*
  - `__init__(self)` *(method)*
  - `is_known(self, _)` *(method)*
  - `pause(self, _)` *(async method)*
  - `resume(self, _)` *(async method)*
  - `restart(self, _)` *(async method)*
- `test_dispatch_failure_returns_task_result(tmp_path)` *(async function)*
- `test_machine_token_travels_in_a_header_not_the_url(monkeypatch)` *(async function)* — "The token in the query string was logged verbatim 107 times (#15)."
- `test_pause_resume_and_restart_controls_acknowledge_over_the_socket(monkeypatch)` *(async function)* — "Drives the real `_run_once` dispatch loop, not a copy of it."
- `test_cancel_of_an_unknown_task_still_acks_over_the_socket(monkeypatch)` *(async function)* — "issue #17 council round 1, "the claim auditor" / "the second caller":"
- `test_pause_of_an_unknown_task_reports_known_false(monkeypatch)` *(async function)* — "The control-message sibling of the cancel case above (issue #17"
- `test_handle_dispatch_forgets_the_task_only_after_the_result_is_sent(tmp_path)` *(async function)* — "finding 14 (council round 2, "the second caller"): before this fix,"
- `test_handle_dispatch_runs_delivery_when_the_payload_carries_one(tmp_path, monkeypatch)` *(async function)*
- `test_handle_dispatch_never_runs_delivery_without_a_delivery_payload(tmp_path, monkeypatch)` *(async function)* — "No `delivery` key at all -- today's only real shape, since no gateway"
- `test_handle_dispatch_never_runs_delivery_after_a_failed_task(tmp_path, monkeypatch)` *(async function)*
- `test_sandbox_for_is_read_only_for_the_read_policy_level()`
- `test_sandbox_for_is_workspace_write_for_controlled_write_and_sensitive()`
- `test_sandbox_for_machine_override_forces_read_only_even_for_write_levels()` — "`AgentSettings.allow_workspace_write=False` is the executor's own kill"
- `test_handle_dispatch_sends_read_only_for_a_read_mode_task(tmp_path)` *(async function)*
- `test_handle_dispatch_sends_workspace_write_for_a_write_mode_task(tmp_path)` *(async function)*
- `test_handle_dispatch_honours_the_machine_level_read_only_override(tmp_path)` *(async function)* — "A write-mode task still only gets `read-only` when this executor's own"

### `tests/unit/test_apply_migrations.py`

> The migration runner, exercised against real throwaway databases.

- `run(db, *args)`
- `legacy_db(tmp_path)` — "A database as `create_all` would have left it before issue #12."
- `columns(db, table)`
- `tables(db)`
- `test_adopting_then_upgrading_adds_the_column_to_existing_rows(legacy_db)`
- `test_the_auth_migration_leaves_existing_tokens_usable(legacy_db)` — "0003 adds revocation without revoking the installed base."
- `test_the_operators_email_is_gone_from_every_credential_table(legacy_db)` — "`security-standards.md` §2 names e-mail, and the default database is in `~/Sync`."
- `test_reapplying_is_a_no_op(legacy_db)`
- `test_failure_names_the_way_forward(legacy_db)` — "The operator arrives here from a startup message naming this command."
- `run_script(script, db, *args)`
- `test_a_semicolon_in_a_comment_is_not_a_statement(tmp_path)` — "The failure `migrations/0003_mobile_auth.sql` hit the day it was written."
- `test_a_half_applied_migration_is_not_reported_as_untouched(tmp_path)` — "The runner must not tell the operator the database is clean when it is not."
- `test_dry_run_changes_nothing(legacy_db)`
- `test_unknown_migration_name_is_refused(legacy_db)`
- `test_engine_and_delivery_columns_default_existing_rows_to_codex(legacy_db)` — "0008: an existing row must read back as what it always was -- a plain"

### `tests/unit/test_claude_runner.py`

> ClaudeRunner's pure logic: command assembly, NDJSON extraction, sandbox mapping.

- `test_claude_runner_satisfies_the_runner_protocol()`
- `test_capabilities_declare_provider_flags_not_os_sandbox()`
- `test_build_command_never_puts_the_instruction_in_argv()` — "The instruction travels over stdin (`run_task` writes it after spawning)."
- `test_build_command_assigns_a_session_id_for_a_fresh_run()`
- `test_build_command_resumes_an_existing_session_instead_of_assigning()`
- `test_read_only_denies_every_write_tool_and_all_of_bash()`
- `test_workspace_write_allows_edits_but_still_denies_push_and_commit()` — "Commit and push are never the agent's own initiative -- that is a"
- `test_find_session_id_reads_the_session_id_key()`
- `test_find_session_id_returns_none_when_absent()`
- `test_find_result_text_reads_the_last_result_events_result_field()`
- `test_find_result_text_is_empty_string_when_no_result_event()`
- `test_find_cost_reads_total_cost_usd_from_the_result_event()`
- `test_find_cost_is_none_when_no_result_event()`

### `tests/unit/test_codex_runner.py`

> CodexRunner's pause/resume/restart/cancel state machine — issue #16 council.

- `test_pause_signals_sigstop_and_marks_paused()` *(async function)*
- `test_pause_refuses_when_already_paused()` *(async function)*
- `test_pause_refuses_an_unknown_task()` *(async function)*
- `test_resume_signals_sigcont_and_clears_paused()` *(async function)*
- `test_resume_refuses_when_not_paused()` *(async function)*
- `test_restart_resumes_a_paused_process_before_terminating_it()` *(async function)*
- `test_cancel_refuses_an_unknown_task()` *(async function)* — "The gateway replays `task.cancel` on reconnect for a task the executor"
- `test_is_known_reflects_mark_dispatched_not_the_running_process_dict()` — "council round 2 on #17, "the second caller": `is_known` used to check"
- `test_cancel_resumes_a_paused_process_before_terminating_it()` *(async function)*
- `test_cancel_after_restart_clears_the_pending_restart()` *(async function)* — "council 2026-08-18, "the second caller", reproduced live: restart()"
- `test_terminate_gracefully_resumes_a_paused_process_before_terminating()` *(async function)*
- `test_terminate_gracefully_does_not_signal_cont_when_not_paused()` *(async function)*
- `test_terminate_gracefully_falls_back_to_kill_if_still_stuck()` *(async function)* — "The safety net behind the SIGCONT fix: a process that does not end"
- `test_build_command_passes_the_sandbox_flag_on_a_fresh_run()`
- `test_build_command_workspace_write_is_also_passed_through()`
- `test_build_command_resume_branch_never_gets_a_sandbox_flag()` — "`codex exec resume --help` lists no `-s`/`--sandbox` option (confirmed"
- `test_run_task_refuses_a_sandbox_value_this_codebase_never_passes()` *(async function)* — "`danger-full-access` is a real, accepted `codex exec -s` value — exactly"

### `tests/unit/test_config_settings.py`

> issue #17 council round 1, "the second caller": `cancel_replay_max_age_seconds`

- `test_a_replay_window_far_past_the_overflow_point_is_rejected_at_startup(field)`
- `test_a_replay_window_at_the_documented_ceiling_is_accepted(field)`
- `test_a_negative_replay_window_is_rejected(field)`

### `tests/unit/test_git_delivery.py`

> `git_delivery.deliver_changes` against real throwaway git repos.

- `test_parse_porcelain_z_handles_a_real_rename_record()` — "Confirmed against real `git status --porcelain=v1 -z` output for a"
- `test_parse_porcelain_z_empty_output_is_no_paths()`
- `test_parse_shortstat_reads_all_three_counters()`
- `test_parse_shortstat_missing_fields_default_to_zero()`
- `test_forbidden_paths_are_named_by_reason(path, expected_reason)`
- `test_ordinary_source_paths_are_not_forbidden()`
- `test_refuses_main_regardless_of_the_kill_switch(tmp_path)` *(async function)*
- `test_refuses_a_branch_that_fails_the_pushable_pattern(tmp_path)` *(async function)* — "Defense in depth: even though `DeliveryRequest` itself accepts any"
- `test_refuses_when_the_executor_kill_switch_is_off(tmp_path)` *(async function)*
- `test_refuses_an_invalid_remote_name_that_could_be_parsed_as_a_flag(tmp_path)` *(async function)* — "`DeliveryRequest.remote` has no shape constraint of its own; a value"
- `test_refuses_push_when_the_named_remote_does_not_exist(tmp_path)` *(async function)*
- `test_skips_cleanly_when_there_is_nothing_to_commit(tmp_path)` *(async function)*
- `test_refuses_a_credentials_file_even_among_other_real_changes(tmp_path)` *(async function)*
- `test_refuses_a_change_too_large_to_have_been_authorized(tmp_path)` *(async function)*
- `test_commits_on_a_new_branch_without_pushing(tmp_path)` *(async function)*
- `test_staging_never_uses_add_all_or_a_bare_dot(tmp_path, monkeypatch)` *(async function)* — "The shared working-tree gate: staging is always by explicit path."
- `test_no_command_ever_carries_a_force_flag(tmp_path, monkeypatch)` *(async function)*
- `test_head_moving_between_status_and_commit_is_refused_not_forced(tmp_path, monkeypatch)` *(async function)* — "Simulates another process writing to the branch in the gap between"

### `tests/unit/test_google_calendar.py`

> `gateway.app.services.google_calendar`, without ever touching Google.

- `test_jwt_assembly_carries_the_right_claims(tmp_path)` *(async function)*
- `test_access_token_is_cached_across_calls(tmp_path)` *(async function)*
- `test_event_id_is_deterministic_for_the_same_seed()`
- `test_event_id_differs_for_a_different_user()`
- `test_event_id_without_a_key_normalizes_text_case_and_whitespace()`
- `test_event_id_alphabet_is_base32hex_lowercase()`
- `test_naive_input_gets_the_default_timezone()`
- `test_offset_aware_input_keeps_its_own_offset()`
- `test_trailing_z_suffix_parses()`
- `test_malformed_datetime_is_a_calendar_access_error()`
- `test_unconfigured_gateway_refuses_before_touching_the_network(tmp_path)` *(async function)*
- `test_a_time_in_the_past_is_refused(tmp_path)` *(async function)*
- `test_more_than_two_years_out_is_refused(tmp_path)` *(async function)*
- `test_the_event_body_matches_the_documented_shape_and_never_has_attendees(tmp_path)` *(async function)*
- `test_a_lead_time_that_would_already_have_passed_is_clamped_to_zero(tmp_path)` *(async function)*
- `test_idempotent_replay_returns_created_false_with_the_same_id(tmp_path)` *(async function)*
- `test_replaying_a_deleted_reminder_id_is_refused(tmp_path)` *(async function)*
- `test_permission_or_not_found_names_the_client_email_and_share_instruction(tmp_path, status)` *(async function)*
- `test_invalid_grant_mentions_the_clock_as_a_possible_cause(tmp_path)` *(async function)*
- `test_no_fixture_private_key_value_ever_appears_in_any_raised_message(tmp_path)` *(async function)* — "A blanket check across every error path this module can raise --"
- `test_missing_credential_file_is_actionable(tmp_path)` *(async function)*
- `test_credential_file_missing_a_required_field_is_actionable(tmp_path)` *(async function)*
- `test_cancel_reminder_succeeds(tmp_path)` *(async function)*
- `test_cancel_reminder_already_gone_is_success(tmp_path)` *(async function)*
- `test_check_access_reports_calendar_summary_and_timezone(tmp_path)` *(async function)*
- `test_openssl_sign_rs256_produces_a_verifiable_signature(tmp_path)` *(async function)*

### `tests/unit/test_instructions.py`

> `resolve_issue_text` and `build_task_instruction`.

- `test_resolves_zero_padded_issue_under_an_epic_folder(tmp_path)`
- `test_resolves_a_bare_numbered_file_directly_under_docs_issues(tmp_path)`
- `test_resolves_an_epic_numbered_folder_via_its_readme(tmp_path)` — "This repo's own older convention (`docs/issues/001-mobile-api-foundation/`)"
- `test_unknown_issue_number_is_not_found(tmp_path)`
- `test_missing_docs_issues_directory_is_not_found(tmp_path)`
- `test_ambiguous_number_across_two_epics_is_reported_not_guessed(tmp_path)`
- `test_gh_reference_is_explicitly_unsupported(tmp_path)` — "GitHub issue ingestion has no owner in this codebase (council finding"
- `test_local_reference_is_rejected_here_as_a_defensive_backstop(tmp_path)` — "`local:<id>` is meant to be resolved by the GATEWAY (an `IssueModel`"
- `test_malformed_reference_is_invalid_not_a_traceback(tmp_path)`
- `test_a_prefix_of_a_longer_number_is_not_matched(tmp_path)` — "Globbing "65-*" must not accidentally match a "650-..." folder."
- `test_build_task_instruction_without_an_issue_has_no_untrusted_block()`
- `test_build_task_instruction_separates_operator_words_from_issue_content()`

### `tests/unit/test_main_import.py`

- `test_main_app_imports()`

### `tests/unit/test_policy.py`

- `test_policy_level_for_mode()`
- `test_sensitive_instruction_requires_approval()`
- `test_keyword_only_is_sensitive_and_unapproved()`
- `test_allow_push_without_keyword_is_sensitive_but_preauthorized()`
- `test_allow_push_to_main_is_refused_not_preauthorized()`
- `test_keyword_and_preauthorized_push_is_one_decision_not_two()` — "A "push " hit plus a matching `delivery` must not stack into two"
- `test_no_other_sensitive_keyword_is_ever_preauthorized()`

### `tests/unit/test_rate_limiter_bounds.py`

> The limiter's key space must be bounded, or it becomes the resource exhausted.

- `test_a_fresh_key_per_request_does_not_grow_without_bound()` *(async function)*
- `test_idle_buckets_are_dropped()` *(async function)* — "A window that emptied leaves an entry behind unless something removes it."
- `test_an_honest_caller_is_still_limited_while_the_table_churns()` *(async function)* — "Eviction must not become a way to escape the limit."
- `test_the_limit_still_fires_for_a_single_key()` *(async function)*

### `tests/unit/test_runner_registry.py`

> The runner abstraction itself: capability declarations and the pool's

- `test_codex_satisfies_the_runner_protocol()`
- `test_codex_declares_an_os_enforced_sandbox()` — "The honest field from `RunnerCapabilities`: Codex's `-s read-only` is a"
- `test_no_registered_engines_env_allowlist_overlaps_another()` — "Env custody must never be unioned across providers (council finding"
- `test_unimplemented_engines_are_declared_not_absent()` — "Every `AgentEngine` value is a registered candidate, whether or not it"
- `test_pool_defaults_to_codex_and_rejects_unknown_engines()`
- `test_pool_routes_control_messages_only_to_dispatched_tasks()` *(async function)*

### `tests/unit/test_schema_guard.py`

> The guard that refuses to serve a database the code has outgrown.

- `test_fresh_database_passes(tmp_path)`
- `test_missing_column_is_named_with_its_migration(tmp_path)` — "The message has to be actionable: what is missing, and what adds it."
- `test_a_database_that_cannot_express_revocation_refuses_to_serve(tmp_path)` — "`revoked_at` is what makes a revoked token stop working."
- `test_create_all_does_not_repair_an_existing_table(tmp_path)` — "The premise of the guard, asserted rather than assumed."
- `test_engine_and_delivery_columns_are_required(tmp_path)` — "Migration 0008: engine/issue_ref/delivery_json/delivery_result_json."

### `tests/unit/test_security.py`

- `test_ensure_within_root_blocks_escape(tmp_path)`
- `test_log_redaction()`

### `tests/unit/test_users.py`

- `test_verify_password_accepts_known_hash()`
- `test_authenticate_returns_the_user_and_no_reason(tmp_path)`
- `test_authenticate_names_why_it_refused(tmp_path, username, password, reason)` — "The reason reaches the audit trail; the caller is told nothing."
- `test_authenticate_refuses_a_disabled_account(tmp_path)`
- `test_a_registry_still_carrying_the_published_example_password_cannot_sign_in(tmp_path)` — "`security-standards.md` §1: no default user password."
- `test_the_shipped_example_registry_is_covered_by_that_refusal()` — "The constant tracks the file, or the guard protects nothing."
- `test_an_absent_user_costs_what_this_registry_costs(tmp_path)` — "Otherwise `POST /api/v1/auth/sign-in` is a user-enumeration oracle."
- `test_the_cheapest_account_in_a_mixed_registry_is_not_identifiable(tmp_path)` — "A registry written at two costs made the older accounts enumerable."
- `test_an_empty_registry_still_costs_something(tmp_path)` — "A missing `users.json` must not make probing cheap."
- `test_load_user_registry_indexes_by_user_id_and_email(tmp_path)`
- `test_authenticated_principal_checks_scopes_and_projects()`

### `tests/unit/test_version_is_single_sourced.py`

> Every statement of the application version must be the same statement.

- `test_pyproject_and_code_agree()`
- `test_settings_reports_the_single_source()`
- `test_fastapi_application_reports_the_single_source()`
- `test_mcp_server_info_reports_the_single_source()` — "The MCP client sees this one; it drifted independently of the HTTP API."
- `test_no_stray_version_literals_in_the_gateway()` — "A new hardcoded copy is how the previous four accumulated."

