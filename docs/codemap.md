# Code Map · codex-bridge

> Generated: 2026-09-02 · Root: `/home/esteban/Sync/Projects/AI/CodexBridge`
> Refresh: `governancekit --root /home/esteban/Sync/Projects/AI/CodexBridge map`

## Summary

- 170 file(s) · 1875 symbol(s) indexed
- Languages: config (2), python (166), shell (2)
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
- `.gitignore`: `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.coverage`, `codex_bridge.db`, `backups/`, `dist/`, `build/`, `*.egg-info/`, `.venv/`, `venv/`, `.governancekit-identity.json`, `AGENTS.md`, `.cursorrules`, `CLAUDE.md`, `.windsurfrules`, `GEMINI.md`, `.github/copilot-instructions.md`, `.amazonq/rules/ai-agents.md`, `handoff.md`, `new-tag.sh`, `scripts/install-agents-kit.sh`, `scripts/agent-worktree.sh`, `.docs-migration-bak/`, `.gk/operator.json`, `.gk/secrets.json`, `.gk/context-telemetry.jsonl`, `.gk/overwritten/`, `.gk/pre-upgrade/`, `.gk/pre-migrate/`, `.gk/remove-agents-backup/`, `.gk/remove-agents-plan.json`, `.gk/context-proposal/`, `*.kit-new`, `*.pre-draft`, `.env`, `.env.*`, `.envrc`, `.npmrc`, `.pypirc`, `.netrc`, `*.pem`, `*.key`, `.credentials/*`, `!.env.example`, `!.env.sample`, `!.env.template`, `!.env.dist`, `!.env-example`, `!.env.missing`, `!.credentials/.gitignore`, `!.credentials/.keep`, `!.credentials/README*`, `!.credentials/*.example`, `!.credentials/*.sample`, `!.credentials/*.template`, `!.credentials/*.dist`

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
    issue_materialize.py  — "Writes one epic's rendered markdown to disk -- issue #78, Commit 2c."
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
        artifacts.py  — "The artifact catalogue, Android build metadata, and the download flow — issue #11."
        auth.py  — "Sign-in, renewal, revocation, and what the actor may actually do."
        authorizations.py  — "The explicit operator grant: `POST .../authorize` and `.../revoke`."
        control_ui.py  — "CodexBridge Control — the first server-rendered screens (issue #73 Stage 5)."
        conversations.py  — "Conversations and contextual messaging — issue #10."
        decisions.py  — "Operational decisions: sensitive tasks held for a human to resolve — issue #6."
        discovery.py  — "Discovered resources: the panel's half of "the node proposes, the panel adopts"."
        enrollment.py  — "Node enrollment — issue #76's minimal cut."
        epics.py  — "Epics — issue #8."
        events.py  — "Near-real-time delivery of what changed, and the backlog behind it — issue #13."
        issues.py  — "Issues — issue #8."
        missions.py  — "Missions: the mission-control view of the same run Sessions exposes — issue #7."
        nodes.py  — "Bridge Nodes — the fleet visibility surface of issue #73, Stage 2."
        notifications.py  — "What this actor wants to be notified about — issue #13."
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
      artifact_storage.py  — "Where an artifact's bytes live, and which of them a request may read."
      artifact_types.py  — "The closed vocabulary an artifact row may use, and the one error it raises."
      audit.py
      conversation_types.py  — "Closed vocabulary for conversation context references, and their error."
      discovery_types.py  — "Closed vocabulary for adopting a `discovered_resources` row, and its error."
      email_templates.py  — "Branded HTML for every CodexBridge transactional email."
      event_types.py  — "Which audit rows become mobile events, and what those events may say — issue #13."
      google_calendar.py  — "A Google Calendar client for reminders, built to be tested without ever"
      issue_render.py  — "Pure markdown renderer for epic materialization -- issue #78, Commit 2a."
      issue_types.py  — "Closed vocabularies for epics and issues, and the error they fail with."
      metrics.py
      notify.py  — "Out-of-band completion notification by email."
      store.py
    version.py  — "The single statement of this application's version."
pyproject.toml
scripts/
  apply_migrations.py  — "Apply the SQL files in `migrations/`, once each, in filename order."
  check_contract_compatibility.py  — "Refuse a contract change that breaks the minimum API version mobile still supports."
  diagnose.sh
  discover_projects.py  — "Read-only scan of a directory tree for real git repositories."
  enroll_node.py  — "Redeem a node-enrollment invite and save the machine token locally."
  install.sh
  publish_contract.py  — "Publish the OpenAPI contract as a pinned, checksummed artifact."
  register_projects.py  — "Turn an operator-approved project list into a diff against the real"
shared/
  __init__.py  — "Shared contracts for the gateway and the agent."
  policy.py
  project_discovery.py  — "Read-only filesystem discovery of real git repositories."
  protocol.py
  security.py
tests/
  conftest.py
  contract/
    test_contract_compatibility.py  — "The gate that fails a pull request before it breaks the pinned mobile client."
    test_declared_examples_are_real.py  — "Response **bodies**, checked against the contract — the half the route gate skips."
    test_docs_match_the_runtime.py  — "Prose that states a runtime fact, checked against the runtime."
    test_openapi_document.py  — "Contract tests for the canonical OpenAPI document."
    test_proxy_routes.py  — "Every contracted path must be routed by the proxies in front of the gateway."
    test_published_contract_artifact.py  — "The pinned contract artifact `EDortta/CodexBridgeMobile` consumes."
  integration/
    test_agent_ack_handling.py  — "`task.ack` handling in the `/agent/ws` message loop — issue #16 council."
    test_agent_hub.py
    test_agent_ws_discovery.py  — "`AgentMessageType.DISCOVERY_REPORT` through the real `/agent/ws` receive loop."
    test_agent_ws_handshake.py  — "The `/agent/ws` handshake stops carrying the token in the URL — issue #15."
    test_agent_ws_identity.py  — "An envelope's `executor_id` is a claim; the handshake's is the fact."
    test_api_conventions.py  — "Representative-endpoint compliance for the cross-cutting API rules (issue #12)."
    test_artifacts.py  — "Artifacts, Android build metadata and the download flow — issue #11."
    test_auth.py  — "The mobile credential lifecycle — issue #4."
    test_authorization_routes.py  — "`POST .../authorize` and `.../revoke` -- issue #73 Stage 4."
    test_claude_runner_real_process.py  — "ClaudeRunner against a REAL `claude` subprocess — not the fakes used elsewhere."
    test_codex_runner_real_process.py  — "CodexRunner against a REAL `codex` subprocess — not the fake used everywhere else."
    test_control_ui.py  — "CodexBridge Control's server-rendered screens — issue #73 Stage 5."
    test_conversations.py  — "Conversations and contextual messaging — issue #10."
    test_decisions.py  — "Operational decisions — issue #6."
    test_discovery_routes.py  — "Discovered-resource adoption routes — issue #73 Stage 3 adoption half."
    test_dispatch_payload_engine_and_delivery.py  — "`AgentHub.dispatch_next` forwards engine/issue_ref/delivery to the executor."
    test_enrollment.py  — "`POST /api/v1/nodes/invite` / `enroll` / `{id}/revoke` — issue #76 (minimal"
    test_epics_issues.py  — "Epics and issues — issue #8."
    test_events.py  — "The mobile event stream, its polling fallback, and notification preferences — issue #13."
    test_issue_materialize_result.py  — "`issue.materialize_result` handling in the `/agent/ws` message loop --"
    test_mcp_epics_issues.py  — "The epics/issues MCP tools -- issue #78."
    test_mcp_reminders.py  — "The `create_reminder`/`cancel_reminder` MCP tools, at the `handle_mcp_call` layer."
    test_missions.py  — "Missions: the mission-control view of Sessions — issue #7."
    test_node_enrollment_ws.py  — "Enrolled/revoked nodes at the `/agent/ws` handshake — issue #76 (minimal"
    test_nodes.py  — "Bridge Node fleet visibility — issue #73 Stage 2."
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
    test_agent_announcement.py  — "The `hello` payload's real content -- issue #73 Stage 2."
    test_agent_auth.py  — "Credential resolution for the `/agent/ws` handshake — issue #15."
    test_agent_auto_project.py  — "`agent.codex_bridge_agent.config.resolve_auto_project` -- the opt-in"
    test_agent_discovery.py  — "`AgentService._scan_root`/`_discovery_loop` -- issue #73 Stage 3."
    test_agent_machine_token.py  — "`agent.codex_bridge_agent.config.resolve_machine_token` -- issue #76's"
    test_agent_service.py
    test_agent_service_materialize.py  — "`AgentService._handle_materialize` -- the `ISSUE_MATERIALIZE` handler on"
    test_apply_migrations.py  — "The migration runner, exercised against real throwaway databases."
    test_capability_vocabulary.py  — "The capability vocabulary issue #73's authorization plane is built on."
    test_claude_runner.py  — "ClaudeRunner's pure logic: command assembly, NDJSON extraction, sandbox mapping."
    test_codex_runner.py  — "CodexRunner's pause/resume/restart/cancel state machine — issue #16 council."
    test_config_settings.py  — "issue #17 council round 1, "the second caller": `cancel_replay_max_age_seconds`"
    test_discover_projects.py  — "`scripts/discover_projects.py` -- read-only repo discovery."
    test_discovery_store.py  — "`store.record_discovery_report` -- issue #73 Stage 3."
    test_effective_task_modes.py  — "`store.effective_task_modes` -- issue #73 Stage 4, WK-20260902-gh73-authorization-plane."
    test_email_templates.py  — "`gateway.app.services.email_templates` -- pure rendering, no I/O."
    test_enroll_node.py  — "`scripts/enroll_node.py` -- one HTTP call, one file write, issue #76."
    test_git_delivery.py  — "`git_delivery.deliver_changes` against real throwaway git repos."
    test_google_calendar.py  — "`gateway.app.services.google_calendar`, without ever touching Google."
    test_instructions.py  — "`resolve_issue_text` and `build_task_instruction`."
    test_issue_materialize.py  — "`materialize_epic` and the shared numbering scanner -- issue #78, Commit 2c."
    test_issue_render.py  — "`render_epic_markdown` -- issue #78, Commit 2a."
    test_main_import.py
    test_node_enrollment.py  — "`store.create_node_invite` / `store.enroll_node` / `store.revoke_node` —"
    test_node_store.py  — "`store.ensure_node_for_executor` / `upsert_registry` / `record_node_announcement`"
    test_notify.py  — "`gateway.app.services.notify` -- the task-finished completion email."
    test_policy.py
    test_rate_limiter_bounds.py  — "The limiter's key space must be bounded, or it becomes the resource exhausted."
    test_register_projects.py  — "`scripts/register_projects.py` -- diff-only, never applies anything."
    test_runner_probe.py  — "`Runner.probe()` and `RunnerPool.probe_all()` -- issue #73 Stage 2."
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
- `resolve_auto_project(project_id, root)` — "Fallback lookup for a `project_id` the static allowlist does not know."
- **`MachineTokenFileError`** *(class)* — "`machine_token_file` is set but unusable -- always an operator problem,"
- `resolve_machine_token(settings)` — "The machine token to present at the `/agent/ws` handshake."

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
- `list_used_issue_numbers(project_root)` — "Every `NNN` already in use under `docs/issues/`, across the three"
- `resolve_issue_text(project_root, issue_ref)` — "Returns the raw text of the issue `issue_ref` names, or raises"
- `build_task_instruction()` — "Assembles the final provider prompt, keeping the operator's own words"

### `agent/codex_bridge_agent/issue_materialize.py`

> Writes one epic's rendered markdown to disk -- issue #78, Commit 2c.

- **`MaterializeError`** *(class)* — "A typed reason a `MaterializeRequest` could not be written."
  - `__init__(self, code)` *(method)*
- **`MaterializeOutcome`** *(class)*
- `materialize_epic(project_root, request)` — "Writes `request.files` under `project_root/docs/issues/`, allocating"

### `agent/codex_bridge_agent/runners/base.py`

> The provider-neutral surface the executor dispatches a task through.

- **`RunningTask`** *(class)* — "A live subprocess plus the control flags `pause`/`cancel`/`restart`"
- **`EngineProbe`** *(class)* — "The runtime answer to "is this engine's binary actually here, right now"."
- **`RunnerCapabilities`** *(class)* — "What a provider can and cannot do, declared rather than assumed."
- **`Runner`** *(class)* — "One provider's implementation of "run this instruction, report back"."
  - `capabilities(self)` *(method)*
  - `probe(self)` *(async method)*
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
  - `probe(self)` *(async method)* — "Issue #73 Stage 2: is `self.settings.claude_bin` actually here, right now."
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
  - `probe(self)` *(async method)* — "Issue #73 Stage 2: is `self.settings.codex_bin` actually here, right now."
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
  - `probe_all(self)` *(async method)* — "Issue #73 Stage 2: one `EngineAvailability` for every `KNOWN_ENGINES`"

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
- `principal_for_token(session, token)` *(async function)* — "The principal a bearer token resolves to right now, or None."
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

### `gateway/app/api/routes/artifacts.py`

> The artifact catalogue, Android build metadata, and the download flow — issue #11.

- `list_artifacts(project, type, origin, cursor, limit, principal, session)` *(async function)* — "Artifacts the caller may see, newest first."
- `get_artifact(artifact_id, principal, session)` *(async function)*
- `mint_download_token(artifact_id, request, response, principal, session)` *(async function)* — "Mint a short-lived bearer credential for this artifact's bytes."
- `download_artifact(artifact_id, request, session)` *(async function)* — "Stream an artifact's bytes to the holder of a live download token."
- `list_android_builds(project, environment, package_name, cursor, limit, principal, session)` *(async function)* — "APK artifacts with their build metadata, newest first."
- `get_android_build(build_id, principal, session)` *(async function)* — "One Android build, addressed by the id of the artifact it is."

### `gateway/app/api/routes/auth.py`

> Sign-in, renewal, revocation, and what the actor may actually do.

- **`SignInRequest`** *(class)*
- **`RefreshRequest`** *(class)*
- **`RevokeRequest`** *(class)*
- `sign_in(body, response, session)` *(async function)* — "Exchange a username and password for an access/refresh pair."
- `refresh(body, response, session)` *(async function)* — "Rotate a refresh token into a new pair."
- `revoke(request, response, body, session)` *(async function)* — "Sign out: end the grant now rather than at expiry."
- `current_actor(response, principal)` *(async function)* — "Who is calling, and what this build will let them do."

### `gateway/app/api/routes/authorizations.py`

> The explicit operator grant: `POST .../authorize` and `.../revoke`.

- **`AuthorizeNodeProjectRequest`** *(class)*
- `authorize_node_project(node_id, project_id, payload, principal, session)` *(async function)* — "Grant `payload.capabilities` to `node_id` on `project_id`."
- `revoke_node_project(node_id, project_id, principal, session)` *(async function)* — "Revoke the active authorization for `node_id` on `project_id`."

### `gateway/app/api/routes/control_ui.py`

> CodexBridge Control — the first server-rendered screens (issue #73 Stage 5).

- `control_home(request, session)` *(async function)*
- `control_node_detail(node_id, request, cursor, state, session)` *(async function)*
- `control_invite(request)` *(async function)*

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

### `gateway/app/api/routes/discovery.py`

> Discovered resources: the panel's half of "the node proposes, the panel adopts".

- **`NewProjectSpec`** *(class)*
- **`AdoptDiscoveredResourceRequest`** *(class)*
- `list_discovered_resources(node_id, response, state, cursor, limit, principal, session)` *(async function)* — "One node's discovered candidates, cursor-paginated, newest-id last."
- `adopt_discovered_resource(resource_id, payload, response, idempotency_key, principal, session)` *(async function)* — "Bind a discovered candidate to a project (existing or new)."
- `deny_discovered_resource(resource_id, response, idempotency_key, principal, session)` *(async function)* — "Refuse a discovered candidate. "Ignore" is a UI filter over `DISCOVERED`/"

### `gateway/app/api/routes/enrollment.py`

> Node enrollment — issue #76's minimal cut.

- **`NodeInviteRequest`** *(class)*
- **`NodeEnrollRequest`** *(class)*
- `invite_node(body, principal, session)` *(async function)* — "Issue a one-time enrollment invite. The raw token is returned here and"
- `enroll_node(body, session)` *(async function)* — "Redeem an invite and create the Executor+Node it authorizes."
- `revoke_node(node_id, principal, session)` *(async function)* — "End `node_id`'s credential and close its live socket in this request."

### `gateway/app/api/routes/epics.py`

> Epics — issue #8.

- **`CreateEpicRequest`** *(class)*
- **`UpdateEpicRequest`** *(class)*
- `list_epics(project_id, response, status, cursor, limit, principal, session)` *(async function)* — "Epics in one project, newest first."
- `get_epic_detail(epic_id, response, principal, session)` *(async function)*
- `create_epic(payload, response, idempotency_key, principal, session)` *(async function)*
- `update_epic(epic_id, payload, response, if_match, principal, session)` *(async function)* — "Change title, description or status."
- `link_issue(epic_id, issue_id, response, if_match, idempotency_key, principal, session)` *(async function)* — "Attach an issue to an epic. Both must be in a project the caller may see."

### `gateway/app/api/routes/events.py`

> Near-real-time delivery of what changed, and the backlog behind it — issue #13.

- **`StreamSlot`** *(class)* — "One acquired slot, releasable exactly once, remembering whose it was."
  - `__init__(self, slots, owner)` *(method)*
  - `release(self)` *(method)*
- **`StreamSlots`** *(class)* — "How many event streams this process will hold open at once."
  - `__init__(self, limit, per_actor)` *(method)*
  - `active` *(property)*
  - `active_for(self, owner)` *(method)*
  - `acquire(self, owner)` *(method)*
  - `release(self, owner)` *(method)*
- `list_events(response, after, project, type, limit, principal, session)` *(async function)* — "Events the caller may see, oldest first, after `after`."
- `event_stream()` *(async function)* — "The SSE body: an async generator of frames."
- `stream_events(request, after, project, type, last_event_id, principal)` *(async function)* — "Open a live event stream for the caller's projects."

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

### `gateway/app/api/routes/nodes.py`

> Bridge Nodes — the fleet visibility surface of issue #73, Stage 2.

- `list_nodes_endpoint(principal, session)` *(async function)* — "Every Bridge Node in the fleet, ordered by id."
- `get_node_detail(node_id, principal, session)` *(async function)* — "One node's fleet status."

### `gateway/app/api/routes/notifications.py`

> What this actor wants to be notified about — issue #13.

- **`NotificationPreferencesRequest`** *(class)*
- `get_preferences(response, principal, session)` *(async function)* — "This actor's preferences, or the defaults when nothing was ever saved."
- `put_preferences(payload, response, principal, session)` *(async function)* — "Replace this actor's preferences."

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

- `resolve_executor_token()` — "Return the credential to verify, or `None` when none was presented."

### `gateway/app/core/config.py`

- **`Settings`** *(class)*
  - `effective_artifact_download_token_ttl_seconds(self)` *(method)*
  - `effective_event_stream_poll_interval(self)` *(method)*
  - `effective_event_stream_batch_limit(self)` *(method)*
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
- `generate_artifact_download_token()` — "A bearer credential for the bytes of one artifact (issue #11)."
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
- `load_user_registry(path)` — "The registry as a lookup dict, failing **closed** on any problem."
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
- `session_factory()` — "The sessionmaker, for code that outlives a request's dependencies."

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
- `handle_issue_materialize_result(session, envelope)` *(async function)* — "Handles one `issue.materialize_result` from the `/agent/ws` message loop."
- `agent_ws(websocket, executor_id, x_executor_token)` *(async function)*

### `gateway/app/mcp/server.py`

- `handle_mcp_call(body, session, hub, principal)` *(async function)*

### `gateway/app/mcp/tools.py`

- `tool_definitions()`

### `gateway/app/models/entities.py`

- **`ExecutorModel`** *(class)*
- **`NodeModel`** *(class)* — "A registered CodexBridge installation — issue #73's Bridge Node."
- **`WorkspaceBindingModel`** *(class)* — "A logical Project as it exists on one Node's disk (issue #73)."
- **`ScmAssociationModel`** *(class)* — "Project <-> source-control repository, as an association rather than an"
- **`ProjectAuthorizationModel`** *(class)* — "What a node may actually do to a project (issue #73's authorization plane)."
- **`DiscoveredResourceModel`** *(class)* — "Something a node can see that Control has not necessarily adopted."
- **`ProjectModel`** *(class)*
- **`TaskModel`** *(class)*
- **`EpicModel`** *(class)*
- **`IssueModel`** *(class)*
- **`ConversationModel`** *(class)* — "A contextual thread linked to at least one product entity — issue #10."
- **`ConversationMessageModel`** *(class)* — "One message in a conversation. Immutable once written — no update path."
- **`ConversationReadStateModel`** *(class)* — "How far one actor has read into one conversation."
- **`ArtifactModel`** *(class)* — "A retained file this gateway can hand to CodexBridgeMobile — issue #11."
- **`AndroidBuildModel`** *(class)* — "APK metadata for one artifact — issue #11's Android half."
- **`ArtifactDownloadTokenModel`** *(class)* — "A short-lived bearer credential for the bytes of exactly one artifact."
- **`TaskLogModel`** *(class)*
- **`AuditEventModel`** *(class)*
- **`NotificationPreferenceModel`** *(class)* — "Which events one actor wants to be notified about — issue #13."
- **`MessageReceiptModel`** *(class)*
- **`IdempotencyRecordModel`** *(class)* — "A completed write, keyed so an offline retry replays instead of repeating."
- **`OAuthAuthorizationCodeModel`** *(class)*
- **`OAuthAccessTokenModel`** *(class)*
- **`OAuthRefreshTokenModel`** *(class)* — "A single-use credential that mints access tokens for one grant."
- **`NodeInviteModel`** *(class)* — "A bearer credential that authorizes exactly one `POST /api/v1/nodes/enroll`."

### `gateway/app/services/agent_hub.py`

- **`AgentConnection`** *(class)*
- **`AgentHub`** *(class)*
  - `__init__(self, session_factory, cancel_replay_max_age_seconds, control_replay_max_age_seconds)` *(method)*
  - `is_connected(self, executor_id)` *(method)*
  - `register(self, executor_id, websocket)` *(async method)*
  - `unregister(self, executor_id)` *(async method)*
  - `force_close(self, executor_id)` *(async method)* — "Close `executor_id`'s live socket, if it has one. Issue #76."
  - `send(self, executor_id, envelope)` *(async method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `dispatch_available(self, executor_id)` *(async method)* — "Dispatches the next queued/waiting task to `executor_id`, if one is"
  - `mark_task_finished(self, executor_id, task_id)` *(async method)* — "Releases the slot `task_id` held and, if the executor is still"
- `hub_envelope(executor_id, message_type, payload)` — "Build a message for an executor."

### `gateway/app/services/artifact_storage.py`

> Where an artifact's bytes live, and which of them a request may read.

- **`UnsatisfiableRange`** *(class)* — "A well-formed `Range` whose first byte lies past the end of the file."
- **`ArtifactContentMissing`** *(class)* — "The row exists and its bytes do not."
- **`ByteRange`** *(class)* — "A resolved, satisfiable range: `[start, end]` inclusive, as HTTP means it."
  - `length` *(property)*
- `artifacts_root()` — "The one directory artifact bytes may live under."
- `validate_storage_path(storage_path)` — "The stored form of a relative artifact path, or `ArtifactError`."
- `resolve_artifact_file(storage_path)` — "The file `storage_path` names, proven to be inside the artifacts root."
- `parse_range_header(value, size)` — "The single byte range `value` asks for, or None to serve the whole file."
- `read_chunks(path, byte_range)` — "Yield the requested bytes of `path`, `chunk_size` at a time."

### `gateway/app/services/artifact_types.py`

> The closed vocabulary an artifact row may use, and the one error it raises.

- **`ArtifactError`** *(class)* — "A rejected artifact field, carrying what the API must report."
  - `__init__(self, field, code, message)` *(method)*
- `normalize_fingerprint(value)` — "Colon-separated uppercase form of a SHA-256 certificate fingerprint."

### `gateway/app/services/audit.py`

- `record_event(session, entity_type, entity_id, event_type, payload)` *(async function)*

### `gateway/app/services/conversation_types.py`

> Closed vocabulary for conversation context references, and their error.

- **`ConversationPlanningError`** *(class)* — "A create input that fails validation inside the store itself."
  - `__init__(self, field, code, message)` *(method)*

### `gateway/app/services/discovery_types.py`

> Closed vocabulary for adopting a `discovered_resources` row, and its error.

- **`DiscoveryAdoptionError`** *(class)* — "An adopt/deny input that fails validation inside the store itself."
  - `__init__(self, field, code, message)` *(method)*

### `gateway/app/services/email_templates.py`

> Branded HTML for every CodexBridge transactional email.

- **`EmailKind`** *(class)*
- `subject_prefix(kind)` — "The bracketed tag this ecosystem's other notifications already use."
- `render_email(kind)` — "Render one full HTML document for `kind`. Every text argument is"

### `gateway/app/services/event_types.py`

> Which audit rows become mobile events, and what those events may say — issue #13.

- **`MobileEvent`** *(class)* — "One translated event, in the shape the contract publishes."
  - `action` *(property)*
  - `as_dict(self)` *(method)*
- `classify(audit_event_type, payload)` — "`(mobile type, entity kind)` for one audit row, or None when it is internal."
- `summarize(mobile_type, payload, redact)` — "A short, human-readable line for one event. Never the raw payload."
- `actor_of(payload)`
- `state_of(payload)` — "The entity's state, or None when the row does not record a defined one."

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

### `gateway/app/services/issue_render.py`

> Pure markdown renderer for epic materialization -- issue #78, Commit 2a.

- `epic_directory_slug(epic)` — "The `<epic-slug>-[<status>]` component of the epic's directory name."
- `issue_relative_key(issue)` — "The `issues/<issue_id>/<task-slug>-[<status>].md` key for one issue."
- `render_epic_markdown(epic, issues)` — "Relative path -> content, for every file one epic materializes to."

### `gateway/app/services/issue_types.py`

> Closed vocabularies for epics and issues, and the error they fail with.

- **`IssuePlanningError`** *(class)* — "A create/update input that fails validation inside the store itself."
  - `__init__(self, field, code, message)` *(method)*

### `gateway/app/services/metrics.py`

- `render_metrics()`

### `gateway/app/services/notify.py`

> Out-of-band completion notification by email.

- **`NotifyConfigError`** *(class)* — "The gateway itself is not set up for notification email -- an operator"
- **`EmailCredentials`** *(class)*
- `notify_task_finished(session, task, settings)` *(async function)* — "Send exactly one completion email for `task` when configured, and"

### `gateway/app/services/store.py`

- `upsert_registry(session, executors, projects)` *(async function)* — "Seed executors and projects from `registry.json` — issue #76's contract"
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
- `effective_task_modes(session, executor, project)` *(async function)* — "The task modes `executor` may actually run on `project`, right now."
- `create_task(session, request, executor_online, continue_session_id, requested_by_user_id, requested_by_email, can_approve_push)` *(async function)*
- `mark_executor_connected(session, executor_id, connected)` *(async function)*
- `executor_is_live(executor)` — "Whether an executor should be presented as connected right now."
- `ensure_node_for_executor(session, executor)` *(async function)* — "The Bridge Node bound to `executor`, creating and binding one if needed."
- `record_node_announcement(session, executor, announcement)` *(async function)* — "Persist a HELLO's `NodeAnnouncement` onto the node bound to `executor`."
- `record_discovery_report(session, executor, report)` *(async function)* — "Persist one root's `DiscoveryReport` into `discovered_resources` -- and nothing else."
- `list_discovered_resources_page(session, node_id)` *(async function)* — "One node's discovered candidates, ordered by id, over-fetched by one."
- `get_discovered_resource(session, resource_id)` *(async function)*
- `grant_project_authorization(session)` *(async function)* — "Get-or-create the standing authorization row for `(node_id, project_id)`."
- `revoke_project_authorization(session)` *(async function)* — "Revoke the ACTIVE authorization row for `(node_id, project_id)`, if any."
- `adopt_discovered_resource(session, resource_id)` *(async function)* — "Adopt one discovered candidate: bind it to a project and, when either"
- `deny_discovered_resource(session, resource_id)` *(async function)* — "Refuse one discovered candidate. See `DECIDABLE_DISCOVERY_STATES` --"
- `list_nodes(session)` *(async function)* — "Every Bridge Node, ordered by id, paired with the executor bound to it."
- `get_node(session, node_id)` *(async function)* — "One Bridge Node and its bound executor, or None if the node does not exist."
- `create_node_invite(session)` *(async function)* — "Issue a bearer enrollment invite. Only `hash_token(token)` is stored."
- `enroll_node(session)` *(async function)* — "Redeem `invite_token`: create the Executor+Node it authorizes."
- `revoke_node(session, node_id)` *(async function)* — "Revoke `node_id`'s credential. Returns `None` if the node does not exist."
- `count_decidable_discovered_resources(session, node_id)` *(async function)* — "How many of `node_id`'s discovered resources are awaiting an operator"
- `list_active_authorizations_for_node(session, node_id)` *(async function)* — "Every non-revoked `project_authorizations` row for `node_id`."
- `get_project_names(session, project_ids)` *(async function)* — "`{project_id: name}` for the given ids, silently dropping unknown ones."
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
- `list_mobile_events_page(session)` *(async function)* — "Deliverable audit rows after `after`, oldest first, with their project."
- `audit_cursor_status(session, after)` *(async function)* — "Whether resuming from `after` can be done without a silent gap."
- `oldest_audit_event_id(session)` *(async function)* — "Lowest id still in **this caller's** feed, reported alongside a gap."
- `get_notification_preference(session, user_id)` *(async function)*
- `set_notification_preference(session)` *(async function)* — "Replace one actor's preferences wholesale, creating the row if absent."
- `create_epic(session)` *(async function)*
- `get_epic(session, epic_id)` *(async function)*
- `get_epic_for_projects(session, epic_id, project_ids)` *(async function)* — "An epic the caller may see, or None. Mirrors `get_task_for_projects`."
- `list_epics_page(session)` *(async function)* — "Epics in one project, newest first, over-fetched by one."
- `update_epic(session, epic_id)` *(async function)* — "Change title, description or status. Mirrors `update_issue` below --"
- `create_issue(session)` *(async function)*
- `get_issue(session, issue_id)` *(async function)*
- `get_issue_for_projects(session, issue_id, project_ids)` *(async function)*
- `list_issues_page(session)` *(async function)*
- `update_issue(session, issue_id)` *(async function)*
- `link_issue_to_epic(session)` *(async function)* — "Attach `issue_id` to `epic_id`. Both must already exist in one project."
- `apply_epic_materialization(session)` *(async function)* — "Records a successful `ISSUE_MATERIALIZE_RESULT` -- issue #78, Commit 2."
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
- `create_artifact(session)` *(async function)* — "Record an artifact and, for an APK, its build metadata."
- `artifact_is_retained(artifact, now)` — "Whether the artifact is still inside its retention window."
- `get_artifact_for_projects(session, artifact_id, project_ids)` *(async function)* — "An artifact the caller may see, or None. Mirrors `get_conversation_for_projects`."
- `list_artifacts_page(session)` *(async function)* — "Artifacts the caller may see, newest first, over-fetched by one."
- `android_builds_for(session, artifact_ids)` *(async function)* — "`{artifact_id: AndroidBuildModel}` for a whole page in one query."
- `get_android_build(session, artifact_id)` *(async function)*
- `list_android_builds_page(session)` *(async function)* — "APK artifacts with their build metadata, newest first, over-fetched by one."
- `create_artifact_download_token(session)` *(async function)* — "Store the hash of a freshly minted download token."
- `get_artifact_download_token(session, token)` *(async function)* — "The live token row for `token`, or None when it is unknown or expired."

### `scripts/apply_migrations.py`

> Apply the SQL files in `migrations/`, once each, in filename order.

- `main()`

### `scripts/check_contract_compatibility.py`

> Refuse a contract change that breaks the minimum API version mobile still supports.

- `facts(document)` — "Comparable facts for one OpenAPI document."
- `incompatibilities(baseline, candidate)` — "Every breaking change in `candidate` relative to `baseline`."
- `minimum_supported_version(document)`
- `baseline_path(document, published)`
- `main(argv)`

### `scripts/discover_projects.py`

> Read-only scan of a directory tree for real git repositories.

- **`Candidate`** *(class)*
- `discover(root)`
- `main(argv)`

### `scripts/enroll_node.py`

> Redeem a node-enrollment invite and save the machine token locally.

- `enroll(gateway_url, invite_token, display_name)` — "Call `POST /api/v1/nodes/enroll`. Returns the parsed JSON body."
- `write_machine_token(path, token)` — "Write `token` to `path` with `0600` permissions, creating parent dirs."
- `main(argv)`

### `scripts/publish_contract.py`

> Publish the OpenAPI contract as a pinned, checksummed artifact.

- `sha256_of(path)`
- `contract_version(source)` — "`info.version` of the document at `source`."
- `publish(source, output)` — "Write the version directory and refresh the index. Returns the version."
- `check(source, output)` — "Everything wrong with the published artifact, in messages an operator can act on."
- `main(argv)`

### `scripts/register_projects.py`

> Turn an operator-approved project list into a diff against the real

- **`ApprovedProject`** *(class)*
- `diff_registry_projects(approved, registry_file)` — "Additions to the gateway registry's top-level `projects` list."
- `diff_executor_allowed_projects(approved, registry_file, executor_id)` — "Additions to one executor's `allowed_projects` list inside the gateway registry."
- `diff_local_allowed_projects(approved, allowed_projects_file)`
- `diff_user_allowed_projects(approved, user_registry_file, user_id)`
- `main(argv)`

### `shared/policy.py`

- **`PolicyDecision`** *(class)*
- `policy_level_for_mode(mode)`
- `push_branch_is_allowed(delivery)` — "Whether `delivery.branch` is a branch a pre-authorized push may target."
- `push_is_preauthorized(request)` — "Whether this request's own `delivery` block authorizes a push."
- `evaluate_task_policy(request)`

### `shared/project_discovery.py`

> Read-only filesystem discovery of real git repositories.

- `is_excluded(dir_name)`
- `walk_for_git_repos(root, max_depth)` — "Depth-limited scan for directories containing `.git`."
- `suggest_project_id(path, taken)` — "A short, stable, unique-among-`taken` id for `path`'s own directory name."
- `build_project_id_index(root, max_depth)` — "Every real repo under `root`, keyed by its `suggest_project_id`."

### `shared/protocol.py`

- **`AgentEngine`** *(class)* — "Which development-agent CLI runs a task's instruction."
- **`TaskMode`** *(class)*
- **`Capability`** *(class)* — "What a node is authorized to do to a project, per issue #73."
- `capabilities_to_modes(capabilities)` — "The task modes a capability set permits. Unknown values are ignored."
- **`TaskState`** *(class)*
- **`PolicyLevel`** *(class)*
- **`TaskPriority`** *(class)*
- **`AgentMessageType`** *(class)*
- **`ApprovalDecision`** *(class)*
- **`DiscoveredState`** *(class)* — "Lifecycle of something a node can see, per issue #73."
- **`BindingState`** *(class)* — "Whether a Project-on-a-Node workspace is usable right now."
- **`NodeHealth`** *(class)* — "A Bridge Node's operational condition, derived at read time."
- **`DiscoveryRoot`** *(class)* — "One directory tree a node is configured to scan, and what that grants."
- **`EngineAvailability`** *(class)* — "Whether one `AgentEngine` can actually run on this node, right now."
- **`NodeAnnouncement`** *(class)* — "What a node reports about itself when it connects (`hello` payload)."
- **`DiscoveredCandidate`** *(class)* — "One directory a node's own scan found under one of its `discovery_roots`."
- **`DiscoveryReport`** *(class)* — "One node's scan of one `discovery_root`, sent as `AgentMessageType.DISCOVERY_REPORT`."
- `node_health()` — "Derive a node's health from facts, at read time, never from a column."
- **`ProjectRegistration`** *(class)*
- **`ExecutorRegistration`** *(class)*
- **`DeliveryRequest`** *(class)* — "What the requester authorized the executor to do with git, once a task"
- **`MaterializeRequest`** *(class)* — "What `ISSUE_MATERIALIZE` asks the executor to write to disk, for one"
- **`SubmitTaskRequest`** *(class)*
- **`ContinueSessionRequest`** *(class)*
- **`AgentEnvelope`** *(class)*
- **`ToolResponse`** *(class)*

### `shared/security.py`

- `secure_compare(left, right)`
- `hash_token(token)`
- `hash_resource_key(value)` — "A fixed-width (64 hex chars), indexable stand-in for an unbounded string."
- `sanitize_log_line(line)`
- `ensure_within_root(root, target)`
- `filtered_environment(allowed_keys)`

### `tests/contract/test_contract_compatibility.py`

> The gate that fails a pull request before it breaks the pinned mobile client.

- `run(*args)`
- `spec()`
- `baseline(spec)` — "The published copy of the minimum supported version."
- `test_the_document_declares_a_minimum_supported_version(spec)` — "Without it there is no floor, and this whole file has nothing to compare against."
- `test_the_minimum_supported_version_is_published(spec)` — "A floor naming an unpublished version is a floor over nothing."
- `test_the_minimum_supported_version_is_not_ahead_of_the_document(spec)` — "A floor above the ceiling means the build serves nothing it promises."
- `test_raising_the_floor_past_a_published_version_is_written_down(spec)` — "The one edit that silently disarms this whole file."
- `test_the_error_code_exemption_still_has_a_schema(spec)` — "The one enum allowed to grow must still be the one the reason applies to."
- `test_the_document_is_compatible_with_the_minimum_supported_version()` — "The acceptance criterion: a breaking change is caught before merge."
- `test_the_gate_names_the_incompatible_endpoint_in_its_output(tmp_path)` — ""CI output identifies the incompatible endpoint/schema" — asserted, not assumed."
- `test_the_gate_refuses_a_floor_that_is_not_published(tmp_path)` — "Pointing the floor at a version nobody can download is not a green run."
- `test_a_document_with_no_declared_floor_is_an_error(tmp_path)`
- `test_a_document_compared_with_itself_reports_nothing(baseline)` — "The precondition every other case rests on."
- `remove_an_endpoint(document)`
- `remove_an_operation(document)`
- `remove_a_response_status(document)`
- `remove_a_response_field(document)`
- `rename_a_response_field(document)`
- `remove_an_enum_value(document)`
- `add_a_value_to_another_enum(document)`
- `close_an_open_field_with_an_enum(document)` — "`type: string` -> `enum: [...]`: yesterday's valid value may be rejected today."
- `narrow_a_type(document)`
- `tighten_a_ceiling(document)`
- `add_a_pattern(document)`
- `make_a_field_required(document)`
- `change_a_reference(document)`
- `require_authentication_on_an_open_endpoint(document)`
- `stop_requiring_a_response_field(document)` — "A response field that becomes optional is a break, not a relaxation."
- `swap_the_credential_an_operation_accepts(document)` — "Collapsing `security` to "is it empty" hid every scheme and scope change."
- `add_a_branch_to_an_all_of(document)` — "`allOf` is an AND: a new branch narrows every value that validated before."
- `change_a_default(document)` — "A client that omits the field gets different behaviour and no error."
- `rename_a_server_variable(document)` — "`servers` was not walked at all; every generated client embeds it."
- `add_a_required_parameter_to_a_path_item(document)` — "Path-item parameters apply to every operation under the path."
- `demand_a_request_body_where_there_was_none(document)` — "An operation that starts requiring a body every existing caller omits."
- `point_an_operation_at_a_required_component_parameter(document)` — "A `$ref` to an already-required component parameter, added to an operation."
- `use_a_restriction_keyword_the_gate_does_not_model(document)` — "The tripwire: abstaining loudly beats abstaining silently."
- `test_a_breaking_change_is_caught_and_named(baseline, mutate)` — "Every rule in §"What is a breaking change" that a schema diff can see."
- `add_an_endpoint(document)`
- `add_a_realistic_endpoint(document)` — "An endpoint shaped like one someone would actually add."
- `add_a_component_schema(document)` — "A new schema arrives with its own `required` and constraints, and is referenced."
- `hoist_parameters_to_the_path_item(document)` — "A pure refactor: path-item parameters apply to every operation under it."
- `add_an_optional_response_field(document)`
- `add_a_value_to_error_code(document)`
- `relax_a_ceiling(document)`
- `drop_a_pattern(document)`
- `widen_a_type(document)`
- `rewrite_prose(document)`
- `test_a_compatible_change_is_left_alone(baseline, mutate)` — "§"What is not breaking", asserted as loudly as its opposite."

### `tests/contract/test_declared_examples_are_real.py`

> Response **bodies**, checked against the contract — the half the route gate skips.

- `client()`
- `test_the_document_declares_response_examples_at_all()` — "Anti-vacuity: the parametrized test below is empty if discovery breaks."
- `test_the_validator_rejects_what_the_schema_forbids(body, why)` — "Everything below is worthless if `_validator` accepts anything."
- `test_a_declared_example_satisfies_its_own_schema(label, schema, example)` — "An example that contradicts its schema misleads the reader who trusts it most."
- `test_at_least_one_operation_can_be_driven()` — "Anti-vacuity, again: `security: []` disappearing must not read as green."
- `test_the_undeclared_field_check_is_not_skipping_everything(client)` — "The third anti-vacuity guard, and the one that was missing."
- `test_the_gateway_returns_the_declared_shape(client, path, method, operation)` — "The success half of "representative examples are tested"."
- `test_the_gateway_returns_no_field_the_contract_omits(client, path, method, operation)` — "The body-level mirror of the undocumented-route check."
- `test_a_failure_response_is_the_declared_error_envelope(client, label, trigger)` — "`Error` is a promise about *every* non-2xx, so it is checked against the schema."

### `tests/contract/test_docs_match_the_runtime.py`

> Prose that states a runtime fact, checked against the runtime.

- `test_the_codemap_names_every_module_it_claims_to_index()` — "`.docs/agents/programmer.md` tells the next agent to read this instead of scanning."
- `test_the_api_readme_does_not_deny_the_limiter_that_ships(denial)` — "§"Rate limiting — vocabulary only, so far" outlived the wiring."
- `test_the_api_readme_does_not_deny_the_publication_machinery_that_ships(denial)` — "§"Getting the contract to the mobile repository" described its own absence."
- `test_the_testing_doc_counts_the_gates_that_exist()` — "`docs/api/testing.md` enumerates the gates; the enumeration must be true."
- `test_the_contract_docs_do_not_deny_what_ships(denial)` — "Sentences that were false when written, pinned so they cannot come back."
- `test_every_field_cited_as_never_shipping_is_actually_listed_there()` — "A pointer whose target does not contain the rule is worse than no pointer."
- `test_no_shipped_file_still_promises_a_boot_gate_for_a_table_only_migration()` — "`REQUIRED_TABLES` does not fail a boot, and five files used to say it does."
- `test_the_env_example_does_not_claim_the_artifacts_root_is_the_checkout()` — "The one file an operator copies must not describe a default it does not have."
- `test_the_installation_guide_names_every_setting_security_md_calls_mandatory()` — "`docs/security.md` says this one must be set at deploy; step 4 never named it."
- `test_no_document_names_a_capability_flag_the_probe_does_not_report()` — "A `false` flag a client can read is the point; a *missing* key is not one."
- `test_the_codemap_names_the_canonical_checkout_not_a_worktree()` — "`governancekit map` stamps the root it was run from, and agents run in worktrees."
- `test_the_audit_payload_writer_count_is_the_real_one()` — "Five files tell a reader how many writers can put a key in an audit payload."

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
- `test_every_declared_security_scheme_is_used(spec)` — "A scheme nothing references describes a credential nothing accepts."
- `test_the_artifact_download_does_not_claim_the_session_credential(spec)` — "The one operation that refuses the session token must not declare it."
- `test_every_declared_component_is_referenced_or_owned(spec)` — "A component nothing points at is a claim the API behaves that way."
- `test_no_pending_component_is_stale(spec)` — "An entry whose component is now wired must be removed."

### `tests/contract/test_proxy_routes.py`

> Every contracted path must be routed by the proxies in front of the gateway.

- `contract_paths()`
- `test_nginx_configs_exist()` — "If the configs move, this gate must fail loudly rather than pass empty."
- `test_every_contract_path_is_routed_by_every_terminating_vhost(contract_paths)`
- `test_every_proxied_location_reaches_an_upstream()` — "A location block with no `proxy_pass` silently drops its path."

### `tests/contract/test_published_contract_artifact.py`

> The pinned contract artifact `EDortta/CodexBridgeMobile` consumes.

- `run(*args)`
- `spec()`
- `test_the_publisher_exists_and_runs()` — "If the script moves, every other test here would pass vacuously."
- `test_the_published_artifact_matches_the_current_document()` — "A merged contract change that never reached `contract/` is drift."
- `test_the_current_version_is_published(spec)` — "`info.version` must name a directory a client can fetch."
- `test_the_index_names_the_current_version_as_latest(spec)` — "The pointer a consumer follows when it has not pinned yet."
- `test_a_published_version_is_byte_identical_to_the_document(spec)` — "Not "equivalent YAML" — identical bytes."
- `test_every_published_version_hashes_to_its_manifest()` — "The property that makes a pin worth pinning."
- `test_check_reports_a_document_that_moved_ahead_of_the_artifact(tmp_path)` — "Change the document, do not republish: the check must name the stale file."
- `test_check_reports_a_published_version_edited_after_the_fact(tmp_path)` — "Rewriting a pinned version is the failure the digest exists to catch."
- `test_check_reports_a_contract_that_was_never_published(tmp_path)`
- `test_publishing_a_new_version_leaves_the_old_one_untouched(tmp_path)` — "A pin survives the next release, or it was never a pin."
- `test_publishing_is_deterministic(tmp_path)` — "Two runs over one input produce identical bytes."

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
- `test_a_rejected_ack_from_a_runner_that_lost_the_task_triggers_notification(factory, monkeypatch)` *(async function)* — "issue #70: the "reconnect with no record" branch is the one path"
- `test_an_accepted_ack_does_not_trigger_notification(factory, monkeypatch)` *(async function)* — "A normal pause/resume/restart ack never lands a task in a terminal"

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

### `tests/integration/test_agent_ws_discovery.py`

> `AgentMessageType.DISCOVERY_REPORT` through the real `/agent/ws` receive loop.

- **`FakeSocket`** *(class)*
  - `__init__(self, incoming)` *(method)*
  - `accept(self)` *(async method)*
  - `close(self, code)` *(async method)*
  - `send_json(self, payload)` *(async method)*
  - `receive_json(self)` *(async method)*
- `wired(monkeypatch)` *(async function)*
- `test_a_discovery_report_is_recorded_for_the_authenticated_node(wired)` *(async function)*
- `test_the_receiving_branch_writes_only_discovered_resources(wired)` *(async function)* — "The structural guarantee, proven through the real handler this time:"
- `test_a_malformed_discovery_report_is_dropped_not_closed(wired)` *(async function)* — "Same tolerant-parse posture as a malformed HELLO: a broken payload"
- `test_a_forged_discovery_report_is_dropped_not_recorded_against_the_victim(wired)` *(async function)* — "The claimed-vs-authenticated `executor_id` guard at the top of the"

### `tests/integration/test_agent_ws_handshake.py`

> The `/agent/ws` handshake stops carrying the token in the URL — issue #15.

- `client(monkeypatch)` *(async function)* — "A real app, but wired to its own isolated in-memory database."
- `test_a_handshake_with_no_credential_is_refused(client)`
- `test_refusing_an_anonymous_handshake_touches_no_executor_record(client, monkeypatch)` — "4401 must be decided before the database, not after a lookup."
- `test_the_header_is_bound_and_reaches_the_registry_check(client)` — "An unknown executor authenticating by header gets 4404, not 4401."
- `test_the_query_parameter_no_longer_authenticates(client)` — "The removal #15 deferred by one release."
- `test_a_query_token_cannot_stand_in_for_a_blank_header(client)` — "No fall-through: an empty header is absent, and the URL is not a backup."

### `tests/integration/test_agent_ws_identity.py`

> An envelope's `executor_id` is a claim; the handshake's is the fact.

- **`FakeSocket`** *(class)* — "Just enough `WebSocket` for `agent_ws`: it accepts, sends, and runs dry."
  - `__init__(self, incoming)` *(method)*
  - `accept(self)` *(async method)*
  - `close(self, code)` *(async method)*
  - `send_json(self, payload)` *(async method)*
  - `receive_json(self)` *(async method)*
- `wired(monkeypatch)` *(async function)*
- `test_a_node_announcing_itself_is_recorded(wired)` *(async function)* — "The honest path, so every refusal below is not passing for want of wiring."
- `test_a_node_cannot_announce_on_another_nodes_behalf(wired)` *(async function)* — "The exploit: authenticate as one node, claim to be another."
- `test_the_forged_envelope_is_dropped_not_redirected(wired)` *(async function)* — "Rewriting the claimed id to the authenticated one would be worse."
- `test_a_forged_heartbeat_does_not_refresh_another_nodes_liveness(wired)` *(async function)* — "Liveness feeds `node_health`, so forging it forges the fleet's health."
- `test_the_connection_survives_a_forged_envelope(wired)` *(async function)* — "Dropping the message must not drop the socket."

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

### `tests/integration/test_artifacts.py`

> Artifacts, Android build metadata and the download flow — issue #11.

- `users_file(tmp_path)`
- `artifacts_root(tmp_path, monkeypatch)` — "The one directory artifact bytes may be read from, for this test run."
- `api(users_file, artifacts_root, monkeypatch)` *(async function)*
- `auth(token)`
- `android_metadata(**overrides)`
- `make_artifact(api)` *(async function)* — "Record one artifact and, unless told otherwise, write its bytes."
- `mint(api, artifact_id, token)`
- `download(api, artifact_id, download_token, **kwargs)`
- `test_the_list_carries_the_checksum_and_the_signing_metadata(api)` *(async function)* — "Issue #11's "checksums and signing metadata before download/install"."
- `test_detail_reports_the_same_shape_as_the_list(api)` *(async function)*
- `test_a_non_apk_artifact_carries_no_android_block(api)` *(async function)* — "`android` is absent, not null: an archive has no build metadata to show."
- `test_pagination_walks_every_artifact_exactly_once(api)` *(async function)* — "Stable ordering across a paged walk — the issue's pagination criterion."
- `test_an_artifact_in_another_project_is_absent_from_the_list(api)` *(async function)*
- `test_an_artifact_in_another_project_is_indistinguishable_from_a_missing_one(api)` *(async function)* — "The exact cross-project answer every other resource in this contract gives."
- `test_minting_a_token_for_a_hidden_artifact_gives_the_same_404(api)` *(async function)* — "The mint endpoint must not be the oracle the read endpoint refuses to be."
- `test_the_project_query_cannot_widen_what_the_caller_may_see(api)` *(async function)* — "`?project=p2` from a p1-only actor narrows to nothing, never widens."
- `test_an_admin_sees_every_project(api)` *(async function)*
- `test_a_download_token_cannot_reach_across_projects(api)` *(async function)* — "The bytes are behind the same project scope the metadata is."
- `test_mint_then_download_returns_the_bytes(api)` *(async function)*
- `test_the_minted_credential_never_travels_in_the_url(api)` *(async function)* — "`security-standards.md` §2: a credential in a query string reaches logs."
- `test_a_session_bearer_token_does_not_download(api)` *(async function)* — "The session credential is not what fetches the bytes."
- `test_a_download_with_no_credential_is_refused(api)` *(async function)*
- `test_an_expired_token_is_refused_with_the_typed_error(api)` *(async function)*
- `test_a_token_minted_for_one_artifact_is_refused_on_another(api)` *(async function)*
- `test_an_unknown_token_is_refused(api)` *(async function)*
- `test_every_download_refusal_is_the_same_refusal(api)` *(async function)* — "Absent, unknown, expired and wrong-artifact must be indistinguishable."
- `test_minting_for_an_unknown_artifact_is_a_typed_404(api)` *(async function)*
- `test_the_download_token_is_never_stored_in_the_clear(api)` *(async function)* — "The fourth narrowing, which the module docstring claimed was tested."
- `test_a_token_stops_at_the_projects_the_account_still_has(api)` *(async function)* — ""...or narrows" — the half of the re-read claim that had no test."
- `test_an_absurdly_long_range_is_not_a_five_hundred(api, header)` *(async function)* — "A `Range` of 4301+ digits was an unhandled `ValueError`."
- `test_a_zero_padded_range_is_still_a_range(api)` *(async function)* — "Leading zeros are legal and carry no meaning — RFC 9110 §14.1.1 is `1*DIGIT`."
- `test_the_missing_content_404_writes_a_log_line_the_request_id_finds(api, caplog)` *(async function)* — "The `requestId` has to resolve to something, or the refusal is a dead end."
- `test_a_token_survives_reuse_inside_its_lifetime(api)` *(async function)* — "Deliberately **not** single-use — the lifetime is the control."
- `test_issuing_a_download_authorization_is_audited(api)` *(async function)* — "A credential for bytes leaves a trail, like every other credential here."
- `test_the_default_artifacts_root_follows_the_working_directory()` — "The default is a development convenience, not a stable location."
- `test_a_token_whose_account_was_disabled_stops_working(api)` *(async function)* — "The account is re-read at download time, not trusted from minting time."
- `test_a_satisfiable_range_is_a_206_with_content_range(api)` *(async function)*
- `test_a_suffix_range_returns_the_tail(api)` *(async function)*
- `test_an_unsatisfiable_range_is_a_416_naming_the_size(api)` *(async function)*
- `test_a_range_this_endpoint_does_not_serve_falls_back_to_the_whole_file(api, header)` *(async function)* — "RFC 9110 §14.2 lets a server ignore a `Range` it will not honour."
- `test_parse_range_header_agrees_with_the_endpoint()` — "The unit-level statement of the same rule, over sizes the API cannot reach."
- `test_a_retired_artifact_is_still_listed_and_says_so(api)` *(async function)*
- `test_a_retired_artifact_mints_no_token_and_serves_no_bytes(api)` *(async function)*
- `test_no_response_body_carries_the_storage_path(api)` *(async function)* — "`storage_path` is this table's `ProjectModel.path`."
- `test_a_traversing_storage_path_cannot_be_stored_at_all(api)` *(async function)* — "The lexical half of the confinement rule, at the write."
- `test_a_symlink_inside_the_root_does_not_escape_it(api)` *(async function)* — "The half the string check cannot see."
- `test_a_row_whose_bytes_are_gone_is_a_typed_404_naming_no_path(api)` *(async function)*
- `test_resolve_refuses_before_it_reports_missing(artifacts_root)` — "A missing file and a rejected path are different exceptions, not one."
- `test_the_android_list_shows_only_apks(api)` *(async function)*
- `test_the_android_list_filters_on_metadata_the_catalogue_cannot(api)` *(async function)*
- `test_a_build_is_addressed_by_the_artifacts_own_id(api)` *(async function)*
- `test_an_artifact_that_is_not_a_build_is_not_a_build(api)` *(async function)* — "Same `404` as an id that does not exist: from this endpoint's vocabulary"
- `test_a_build_in_another_project_answers_the_same_404(api)` *(async function)*
- `test_the_android_list_is_project_scoped(api)` *(async function)*
- `test_an_apk_must_carry_build_metadata_and_nothing_else_may(api)` *(async function)*
- `test_a_fingerprint_has_one_spelling(api)` *(async function)* — "A bare 64-hex fingerprint and the colon-separated form are one certificate."
- `test_a_name_that_could_forge_a_header_is_refused(api)` *(async function)* — "`name` is interpolated into `Content-Disposition`."
- `test_an_artifact_needs_a_real_checksum(api)` *(async function)*
- `test_an_unknown_project_is_refused_at_the_write(api)` *(async function)*

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
- `test_signing_out_kills_a_download_token_minted_before_it(api)` *(async function)* — "Sign-out has to close every credential, not the two it was written for."
- `test_revoking_by_refresh_token_also_kills_the_download_tokens(api)` *(async function)* — "The other revocation door closes the same set."
- `test_a_replayed_dead_refresh_token_cannot_kill_a_live_grants_download(api)` *(async function)* — "Revocation stops at the grant it names — the round-1 fix reached past it."
- `test_a_grantless_sign_out_does_not_abort_the_phones_download(api)` *(async function)* — "Signing out of ChatGPT must not kill an APK transfer on the phone."
- `test_an_access_token_that_was_never_issued_signs_out_quietly(api)` *(async function)* — "Same rule, reached from the other side: incurious about the credential."
- `test_a_consumed_refresh_token_still_ends_its_own_grant(api)` *(async function)* — "Pinned on purpose — this behaviour is a decision, not an accident."
- `test_revoking_nothing_is_refused(api)` *(async function)*
- `test_revocation_is_recorded_against_the_actor(api)` *(async function)*
- `test_a_no_op_revoke_writes_no_audit_row(api)` *(async function)* — "A retry the endpoint blesses must not add a `0/0` audit row."
- `test_a_last_minute_rotation_does_not_outlive_the_grant_deadline(api)` *(async function)* — "A rotation near the grant's end must not mint an access token past it."
- `test_a_rotation_far_from_the_deadline_still_gets_the_full_access_ttl(api)` *(async function)* — "The deadline cap must not shorten a normal rotation — the fix's floor."
- `test_the_retention_sweep_keeps_a_refresh_reuse_record(api)` *(async function)* — "The spam sweep must not age out the record that a token was replayed."
- `test_me_requires_a_token(api)` *(async function)*
- `test_me_refuses_an_expired_token(api)` *(async function)*
- `test_every_401_on_this_surface_is_the_same_401(api)` *(async function)* — "Four places claimed this and it was not true."
- `test_a_disabled_account_is_asked_to_sign_in_again_not_told_it_may_not(api)` *(async function)* — "401, not 403 — and `/api/v1/auth/me` declares no 403 at all."
- `test_me_reports_the_actor_and_its_projects(api)` *(async function)*
- `test_me_marks_an_admin_as_seeing_every_project(api)` *(async function)*
- `test_me_separates_read_operational_and_administrative(api)` *(async function)* — "The three classes the issue asks for, reported per action."
- `test_epics_publish_is_exercised_over_mcp()` — "Not a real assertion -- a pointer so `COVERED_ELSEWHERE`'s own guard"
- `test_every_catalogued_action_is_exercised_below()` — "A new action must extend the table, or it ships unchecked."
- `test_each_exemption_names_a_test_that_exists()` — "An exemption pointing at nothing is an exemption with no coverage behind it."
- `test_the_guard_flags_a_new_administrative_action(monkeypatch)` — "The guard is only worth having if it fires — so fire it."
- `test_the_report_and_the_endpoints_agree(api, who)` *(async function)* — "The claim the whole endpoint exists for."
- `test_the_administrative_action_describes_what_the_list_endpoint_does(api)` *(async function)* — "`sessions.readAllProjects` is administrative because it crosses projects."
- `test_the_administrative_action_describes_what_the_missions_list_endpoint_does(api)` *(async function)* — "`missions.readAllProjects` mirrors `sessions.readAllProjects` — same widening."

### `tests/integration/test_authorization_routes.py`

> `POST .../authorize` and `.../revoke` -- issue #73 Stage 4.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)*
- `auth(token)`
- `test_authorize_requires_a_token(api)` *(async function)*
- `test_authorize_without_the_admin_scope_is_forbidden(api)` *(async function)*
- `test_authorize_read_with_the_admin_scope_is_allowed(api)` *(async function)* — "Positive control: the base scope alone is sufficient for `read`/`test`."
- `test_granting_modify_without_can_approve_sensitive_or_admin_role_is_refused(api)` *(async function)* — "The scope alone (`codexbridge.admin`, no real admin role, no"
- `test_granting_modify_with_can_approve_sensitive_is_allowed(api)` *(async function)* — "Positive control: the sensitive-approval flag alone is sufficient, no admin role needed."
- `test_granting_deliver_with_a_real_admin_role_is_allowed(api)` *(async function)* — "Positive control: a real `"admin"` role alone is sufficient, no `can_approve_sensitive` needed."
- `test_granting_read_and_modify_together_still_needs_the_second_gate(api)` *(async function)* — "Mixing a sensitive capability into an otherwise-plain request still trips the gate."
- `test_authorize_overwrites_rather_than_merges_capabilities(api)` *(async function)*
- `test_revoke_then_regrant_reuses_the_same_row_and_both_events_are_audited(api)` *(async function)*
- `test_revoking_a_pair_with_no_active_authorization_is_not_found(api)` *(async function)*
- `test_revoke_never_needs_the_sensitive_gate(api)` *(async function)* — "Positive control for the "no second gate on revoke" claim: the"
- `test_authorizing_an_unknown_node_is_not_found(api)` *(async function)*
- `test_authorizing_an_unknown_project_is_not_found(api)` *(async function)*

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

### `tests/integration/test_control_ui.py`

> CodexBridge Control's server-rendered screens — issue #73 Stage 5.

- `basic(username, password)`
- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)*
- `set_node_display_name(factory, node_id, display_name)` *(async function)*
- `seed_resource(factory)` *(async function)*
- `seed_project(factory)` *(async function)*
- `grant(factory)` *(async function)*
- `test_control_home_requires_a_credential(api)` *(async function)*
- `test_control_home_with_a_wrong_password_is_refused(api)` *(async function)*
- `test_control_home_without_the_admin_scope_is_forbidden(api)` *(async function)*
- `test_control_home_with_the_admin_scope_is_allowed(api)` *(async function)* — "Positive control for the previous three: the credential and scope alone are sufficient."
- `test_control_home_escapes_a_hostile_display_name(api)` *(async function)*
- `test_control_home_counts_pending_candidates(api)` *(async function)*
- `test_control_node_detail_requires_a_credential(api)` *(async function)*
- `test_control_node_detail_unknown_node_is_404(api)` *(async function)*
- `test_control_node_detail_renders_capabilities_for_an_admin(api)` *(async function)* — "Positive control for the previous two."
- `test_control_node_detail_escapes_a_hostile_resource_path_and_suggested_name(api)` *(async function)*
- `test_control_node_detail_shows_the_candidate_resource_path(api)` *(async function)* — "The one authorized surface `resourcePath` may appear on (docs/api/README.md)."
- `test_control_node_detail_paginates_discovered_candidates(api)` *(async function)*
- `test_control_node_detail_shows_a_grant_form_for_an_adopted_unauthorized_project(api)` *(async function)* — "`ADOPTED` with no capability grant yet has no `project_authorizations`"
- `test_control_node_detail_shows_active_capabilities_and_a_revoke_form(api)` *(async function)*
- `test_control_node_detail_warns_that_modify_and_deliver_need_more_than_admin_scope(api)` *(async function)*
- `test_control_node_detail_mints_no_audit_event(api)` *(async function)* — "Reading a page, and the token minted for its own fetch() calls, are not audited."
- `test_control_node_detail_embeds_a_real_bearer_token_for_its_own_fetch_calls(api)` *(async function)* — "The page-scoped token is an ordinary row in the same table `/api/v1/**` reads."
- `test_control_invite_requires_a_credential(api)` *(async function)*
- `test_control_invite_without_the_admin_scope_is_forbidden(api)` *(async function)*
- `test_control_invite_explains_the_gap_honestly(api)` *(async function)* — "Positive control for the previous two, and the point of this screen today:"

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

### `tests/integration/test_discovery_routes.py`

> Discovered-resource adoption routes — issue #73 Stage 3 adoption half.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)*
- `auth(token)`
- `seed_resource(factory)` *(async function)*
- `test_list_requires_a_token(api)` *(async function)*
- `test_list_without_the_admin_scope_is_forbidden(api)` *(async function)*
- `test_list_with_the_admin_scope_is_allowed(api)` *(async function)* — "Positive control for the previous two: the scope alone is sufficient."
- `test_a_principal_without_the_administrative_scope_cannot_adopt(api)` *(async function)*
- `test_a_principal_with_the_administrative_scope_can_adopt(api)` *(async function)* — "Positive control for the previous test."
- `test_adoption_cannot_grant_modify_without_the_sensitive_ladder(api)` *(async function)* — "The second door to `modify`/`deliver`, closed."
- `test_the_same_actor_may_adopt_when_it_asks_for_no_sensitive_capability(api)` *(async function)* — "Positive control: the ladder gates the capability, not the adoption."
- `test_a_token_with_no_scopes_cannot_deny(api)` *(async function)*
- `test_an_unknown_node_id_is_not_found(api)` *(async function)*
- `test_an_invalid_state_filter_is_rejected(api)` *(async function)*
- `test_the_state_filter_narrows_the_list(api)` *(async function)*
- `test_a_resource_from_a_different_node_is_not_listed(api)` *(async function)*
- `test_pagination_covers_more_candidates_than_one_page(api)` *(async function)* — "The real-world case this PR names: 247 candidates from one root."
- `test_the_dto_carries_the_sensitive_path_fields(api)` *(async function)* — "This IS the pre-registered exception (`docs/control-plane.md`,"
- `test_adopting_with_a_new_project_creates_project_binding_and_moves_state(api)` *(async function)*
- `test_adopting_without_a_remote_url_creates_no_scm_association(api)` *(async function)* — "Positive control for the previous test's association assertion."
- `test_adopting_into_an_existing_project_reuses_it(api)` *(async function)*
- `test_adopting_twice_does_not_duplicate_the_binding(api)` *(async function)*
- `test_adopt_requires_exactly_one_of_project_id_or_new_project(api)` *(async function)*
- `test_adopting_an_unknown_resource_is_not_found(api)` *(async function)*
- `test_a_matching_auto_authorize_root_grants_read_on_adoption(api)` *(async function)* — "`E1`'s registration grants `read` for exactly `/root` (see the `api` fixture)."
- `test_a_non_matching_root_grants_nothing(api)` *(async function)* — "Positive control: a candidate under a root E1 never registered grants nothing automatically."
- `test_operator_grant_capabilities_can_include_modify_and_deliver(api)` *(async function)*
- `test_root_config_and_operator_grants_coexist_in_one_call(api)` *(async function)* — "Both origins apply in the same adopt call -- `/root` auto-grants `read`,"
- `test_auto_authorize_can_never_grant_modify_or_deliver(api)` *(async function)* — "A malicious/misconfigured root cannot smuggle `modify`/`deliver` in --"
- `test_denying_moves_state_and_records_the_actor(api)` *(async function)*
- `test_denying_twice_is_a_conflict(api)` *(async function)*
- `test_a_denied_resource_is_not_touched_by_a_later_report(api)` *(async function)* — "The rule `docs/control-plane.md` names survives this PR: DENIED is"

### `tests/integration/test_dispatch_payload_engine_and_delivery.py`

> `AgentHub.dispatch_next` forwards engine/issue_ref/delivery to the executor.

- **`DummyWebSocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send_json(self, payload)` *(async method)*
- `factory()` *(async function)*
- `test_dispatch_omits_delivery_and_issue_ref_when_neither_was_requested(factory)` *(async function)*
- `test_dispatch_forwards_engine_issue_ref_and_delivery_when_requested(factory)` *(async function)*

### `tests/integration/test_enrollment.py`

> `POST /api/v1/nodes/invite` / `enroll` / `{id}/revoke` — issue #76 (minimal

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)*
- `auth(token)`
- `test_admin_can_issue_an_invite(api)`
- `test_a_read_only_caller_cannot_issue_an_invite(api)`
- `test_the_raw_invite_token_never_lands_in_audit_events(api)` *(async function)*
- `test_enroll_redeems_the_invite_and_the_node_connects_with_the_returned_token(api)`
- `test_enroll_needs_no_bearer_token_at_all(api)` — "Decision #2: the node has no credential yet -- the invite is the gate."
- `test_enroll_refuses_an_unknown_invite_token(api)`
- `test_enroll_refuses_a_consumed_invite_the_second_time(api)`
- `test_enroll_refuses_an_expired_invite(api)` *(async function)*
- `test_the_raw_machine_token_never_lands_in_audit_events(api)` *(async function)*
- `test_admin_can_revoke_an_enrolled_node(api)`
- `test_a_read_only_caller_cannot_revoke(api)`
- `test_revoking_an_unknown_node_answers_not_found(api)`

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
- `test_get_epic_returns_an_etag(api)` *(async function)*
- `test_update_epic_requires_if_match(api)` *(async function)*
- `test_update_epic_with_a_stale_etag_is_refused(api)` *(async function)*
- `test_update_epic_changes_only_the_mentioned_fields(api)` *(async function)* — "Positive control for the two If-Match negatives above."
- `test_update_epic_can_explicitly_clear_a_nullable_field(api)` *(async function)*
- `test_update_epic_rejects_an_unknown_status(api)` *(async function)*
- `test_a_reader_cannot_update_an_epic(api)` *(async function)*

### `tests/integration/test_events.py`

> The mobile event stream, its polling fallback, and notification preferences — issue #13.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)*
- `auth(token)`
- `make_task(factory, project_id)` *(async function)*
- `emit(factory, entity_type, entity_id, event_type, payload)` *(async function)* — "Write one audit row directly and return its id."
- `newest_audit_id(factory)` *(async function)*
- **`FakeClock`** *(class)* — "A monotonic clock the test moves on purpose."
  - `__init__(self)` *(method)*
  - `__call__(self)` *(method)*
- `stepping_sleep(clock, step, on_poll)` — "An `asyncio.sleep` replacement that advances the fake clock instead."
- `parse_frames(chunks)` — "SSE text as a list of `{id?, event?, data?, comment?}` dicts."
- `run_stream(factory)` *(async function)* — "Drive `event_stream` for exactly `polls` iterations and return its frames."
- `redact_for_test(value)` — "The real redactor, imported through the route module the code injects."
- `entity_frames(frames)` — "Only the frames that carry an event — control frames and heartbeats out."
- `test_the_backlog_returns_translated_events_oldest_first(api)` *(async function)*
- `test_the_page_reports_more_and_a_position_to_continue_from(api)` *(async function)*
- `test_a_type_filter_narrows_without_making_the_position_stall(api)` *(async function)* — "`nextAfter` is the last id *loaded*, not the last id returned."
- `test_an_unknown_type_filter_is_a_validation_error(api)` *(async function)*
- `test_a_declared_but_unemitted_type_filters_to_nothing_rather_than_failing(api)` *(async function)* — "`artifact.*` is in the vocabulary and produced by nothing in this build."
- `test_the_project_filter_only_ever_narrows(api)` *(async function)*
- `test_a_restricted_principal_sees_only_its_own_projects_events(api)` *(async function)*
- `test_authentication_events_never_appear_on_any_principals_feed(api)` *(async function)* — "Sign-in activity is not a product event, and streaming it is a disclosure."
- `test_a_preference_change_is_not_a_project_event(api)` *(async function)* — "`notification` rows are excluded the same way `auth` rows are."
- `test_an_event_whose_project_cannot_be_derived_reaches_nobody(api)` *(async function)* — "Fail closed, administrators included."
- `test_reading_events_requires_the_read_scope(api)` *(async function)*
- `test_no_stored_payload_key_is_passed_through_to_a_client(api)` *(async function)* — "The audit payload is written by thirty-five call sites and is not a response."
- `test_free_text_in_a_summary_is_redacted_and_bounded(api)` *(async function)* — "`redact` is applied to executor free text, and the line has a ceiling."
- `test_an_executors_control_and_state_strings_cannot_reach_a_notification_line(api)` *(async function)* — "Council round 1, the adversarial user — the whitelist's premise was false."
- `test_every_echoed_payload_value_comes_from_a_closed_vocabulary()` — "The guard behind the test above, asserted directly."
- `test_the_gap_signal_cannot_report_on_events_the_caller_may_not_see(api)` *(async function)* — "Council round 1 — the `gap` block was a one-bit oracle over the whole log."
- `test_the_oldest_available_id_is_the_callers_own_oldest(api)` *(async function)* — "`oldestAvailableId` returned the global minimum audit id to any reader."
- `test_a_resume_position_beyond_the_id_range_is_refused_not_a_500(api)` *(async function)* — "Council round 1 — `?after=2**63+1` was an authenticated 500."
- `test_an_out_of_range_last_event_id_is_clamped_not_replayed(api)` *(async function)* — "The same overflow on the stream, where a 500 is not even available."
- `test_every_emitted_event_type_has_a_summary_builder()` — "A type with no builder falls back to a bland sentence — silently."
- `test_every_audited_domain_event_type_is_translated()` — "A new audit event under a deliverable entity must be classified on purpose."
- `test_the_non_deliverable_entity_constants_stay_non_deliverable()` — "The exclusion of auth and preference rows is by construction; pin it."
- `test_the_declared_but_unemitted_types_are_not_produced_by_this_build()` — "`artifact.*` and `androidBuild.*` are contract, not behaviour."
- `test_the_stream_opens_with_an_acknowledgement_carrying_no_position(api)` *(async function)* — "`stream.open` must not carry `id:`."
- `test_events_recorded_while_the_stream_runs_are_delivered(api)` *(async function)*
- `test_reconnecting_from_the_last_id_loses_nothing_and_repeats_nothing(api)` *(async function)* — "The acceptance criterion, end to end."
- `test_the_same_position_replayed_twice_delivers_the_same_events(api)` *(async function)* — "Resume is a pure function of the position, so a duplicated reconnect is safe."
- `test_a_position_the_log_has_moved_past_is_announced_before_anything_is_delivered(api)` *(async function)* — "A gap is signalled, never papered over — and signalled *first*."
- `test_a_position_ahead_of_the_log_is_a_gap_too(api)` *(async function)* — "The mirror case: a cursor from another deployment, or a restored backup."
- `test_a_continuous_position_produces_no_gap_frame(api)` *(async function)* — "The signal is only worth having if it stays quiet when nothing was lost."
- `test_the_polling_fallback_reports_the_same_gap(api)` *(async function)* — ""No silent loss" is a property of the events, not of one transport."
- `test_a_revoked_token_stops_the_stream_it_had_already_opened(api)` *(async function)* — "Authorization is re-checked on every poll, not once at `GET`."
- `test_an_expired_token_stops_the_stream(api)` *(async function)* — "Expiry is the same failure as revocation and must end the stream too."
- `test_a_project_removed_from_the_actor_stops_reaching_them(api, users_file)` *(async function)* — "`allowed_projects` is re-read per poll, not captured when the stream opened."
- `test_a_disconnected_client_ends_the_stream_without_a_closing_frame(api)` *(async function)* — "Nothing is listening, so there is nothing to tell."
- `test_an_idle_stream_sends_a_comment_not_an_event(api)` *(async function)* — "A heartbeat keeps a proxy from timing out an idle connection."
- `test_a_newline_in_stored_text_cannot_split_one_frame_into_two(api)` *(async function)* — "SSE is a line protocol: a raw newline inside `data:` ends the frame early."
- `test_a_stream_type_filter_narrows_delivery_without_stalling_the_cursor(api)` *(async function)*
- `test_the_slot_ceiling_refuses_rather_than_degrading_the_shared_pool(api)` *(async function)* — "The rate limiter bounds requests per window, not connections held open."
- `test_a_finished_stream_gives_its_slot_back(api)` *(async function)* — "A slot that is not returned is gone for good, and the ceiling ratchets down."
- `test_a_connection_that_dies_before_the_body_starts_still_returns_its_slot(api)` *(async function)* — "The release path the generator's `finally` cannot reach — council round 1."
- `test_one_account_cannot_take_every_stream_slot(api)` *(async function)* — "A global ceiling is not a share — council round 1, the adversarial user."
- `test_the_per_actor_ceiling_can_never_exceed_the_process_ceiling()` — "A per-actor ceiling above the global one reads as a share and is not one."
- `test_the_module_level_slots_carry_the_configured_per_actor_ceiling()` — "The ceiling the deployment actually uses is wired from settings."
- `test_the_stream_ceiling_fits_inside_the_connection_pool()` — "32 streams against a 15-connection pool is the incident `probes.py` records."
- `test_the_stream_is_served_as_an_event_stream_that_a_proxy_will_not_buffer(api, monkeypatch)` *(async function)*
- `test_last_event_id_resumes_and_beats_the_query_parameter(api, monkeypatch)` *(async function)* — "The header is what a reconnecting `EventSource` sends by itself."
- `test_a_malformed_last_event_id_is_ignored_rather_than_refused(api)` *(async function)* — "The user agent sets that header, not the application."
- `test_a_bad_type_filter_fails_before_the_body_starts(api, monkeypatch)` *(async function)* — "Once an event-stream body has started there is no status code left to change."
- `test_preferences_round_trip(api)` *(async function)*
- `test_a_put_replaces_the_document_rather_than_merging_into_it(api)` *(async function)* — "`PUT`, not `PATCH`: an absent field takes its default."
- `test_preferences_are_per_actor_and_never_another_accounts(api)` *(async function)*
- `test_an_unknown_event_type_is_refused_with_the_field_named(api)` *(async function)*
- `test_writing_preferences_needs_a_scope_reading_them_does_not(api)` *(async function)* — "Two actions, because an operator may grant one without the other."
- `test_the_manage_scope_is_one_a_signed_in_client_can_actually_be_granted()` — "A scope outside `oauth_default_scopes` can never be granted to anyone."
- `test_the_env_template_can_grant_every_scope_the_catalogue_needs()` — "The allowlist has two sources, and production reads the one nobody edits."
- `test_a_rejected_subscription_list_cannot_amplify_the_response(api)` *(async function)* — "Council round 1 — the count was bounded, the bytes were not."
- `test_a_rejected_type_filter_cannot_amplify_the_response(api)` *(async function)* — "The same reflection on the query side, where the URL is the only limit."
- `test_a_stored_type_that_no_longer_exists_is_dropped_on_the_way_out(api)` *(async function)* — "A stored preference can outlive the type it names."
- `test_preferences_do_not_filter_the_stream(api)` *(async function)* — "A documented decision, not an omission — so it is pinned as behaviour."
- `test_an_empty_project_list_matches_nothing_and_is_not_no_restriction(api)` *(async function)* — "The one-character mistake: `if project_ids:` instead of `is not None`."
- `test_task_created_forks_on_the_state_it_was_created_in(api)` *(async function)* — "One audit row, two mobile meanings, resolved from the payload."
- `test_epics_issues_and_conversations_all_resolve_to_their_project(api)` *(async function)* — "Every deliverable entity type must have a working project derivation."
- `test_the_audit_index_exists_on_a_fresh_install_as_well_as_an_upgraded_one()` — "An index declared only in SQL is missing on every new database."
- `test_the_poll_interval_is_floored_rather_than_honoured()` — "A zero interval is a busy loop against the pool every endpoint shares."

### `tests/integration/test_issue_materialize_result.py`

> `issue.materialize_result` handling in the `/agent/ws` message loop --

- `factory()` *(async function)*
- `test_a_successful_result_records_materialized_path_on_epic_and_issue(factory)` *(async function)* — "Positive control for the failure/unknown-epic tests below."
- `test_a_failed_result_does_not_touch_materialized_path(factory)` *(async function)*
- `test_a_result_for_an_unknown_epic_does_not_raise(factory)` *(async function)*
- `test_a_result_with_no_epic_id_is_ignored_not_raised(factory)` *(async function)*
- `test_apply_epic_materialization_ignores_non_issue_keys_and_unknown_issue_ids(factory)` *(async function)* — "Positive control: the real issue id updates; two adversarial-ish"

### `tests/integration/test_mcp_epics_issues.py`

> The epics/issues MCP tools -- issue #78.

- **`DummyHub`** *(class)*
  - `is_connected(self, executor_id)` *(method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
- **`RecordingHub`** *(class)* — "A hub with a caller-controlled set of connected executors, recording"
  - `__init__(self, connected)` *(method)*
  - `is_connected(self, executor_id)` *(method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
- `users_file(tmp_path)`
- `env(users_file, monkeypatch)` *(async function)* — "One database, two doors onto it: `handle_mcp_call` directly, and a REST"
- `test_create_epic_two_issues_and_list_them(env)` *(async function)*
- `test_retried_create_epic_with_same_key_returns_the_same_epic(env)` *(async function)*
- `test_same_idempotency_key_with_a_different_body_is_a_conflict(env)` *(async function)*
- `test_principal_without_project_access_gets_a_typed_error_not_an_empty_list(env)` *(async function)*
- `test_principal_without_write_scope_gets_missing_scope(env)` *(async function)*
- `test_create_issue_returns_an_issue_ref_matching_the_shared_pattern(env)` *(async function)*
- `test_unknown_status_or_priority_is_a_typed_validation_error(env)` *(async function)*
- `test_an_epic_id_from_another_project_is_unknown_epic(env)` *(async function)*
- `test_rows_created_via_mcp_appear_unchanged_via_rest(env)` *(async function)*
- `test_update_issue_changes_only_the_mentioned_fields(env)` *(async function)* — "Positive control for the two expected_revision negatives below."
- `test_update_issue_accepts_the_bare_id_or_the_local_prefixed_ref(env)` *(async function)*
- `test_update_issue_without_expected_revision_is_refused(env)` *(async function)*
- `test_update_issue_with_a_stale_expected_revision_is_refused(env)` *(async function)*
- `test_update_issue_with_an_unknown_status_is_a_typed_validation_error(env)` *(async function)*
- `test_update_issue_on_another_projects_issue_is_unknown_issue(env)` *(async function)*
- `test_update_epic_changes_only_the_mentioned_fields(env)` *(async function)* — "Positive control for the two expected_revision negatives below."
- `test_update_epic_without_expected_revision_is_refused(env)` *(async function)*
- `test_update_epic_with_a_stale_expected_revision_is_refused(env)` *(async function)*
- `test_update_epic_with_an_unknown_status_is_a_typed_validation_error(env)` *(async function)*
- `test_move_issue_to_epic_changes_the_issues_epic(env)` *(async function)* — "Positive control for the two expected_revision negatives below."
- `test_move_issue_to_epic_without_expected_revision_is_refused(env)` *(async function)*
- `test_move_issue_to_epic_with_a_stale_expected_revision_is_refused(env)` *(async function)*
- `test_move_issue_to_epic_from_a_foreign_project_is_unknown_epic(env)` *(async function)*
- `test_a_retried_move_does_not_move_the_issue_twice(env)` *(async function)*
- `test_publish_epic_to_repo_dispatches_to_a_connected_executor(env)` *(async function)* — "Positive control for the two `_not_connected`/`_not_onboarded` tests below."
- `test_publish_epic_to_repo_with_no_connected_executor_is_a_typed_error(env)` *(async function)*
- `test_publish_epic_to_repo_for_a_project_no_executor_allows_is_project_not_onboarded(env)` *(async function)*
- `test_publish_epic_to_repo_unknown_epic_is_404(env)` *(async function)*
- `test_publish_epic_to_repo_republish_carries_existing_path(env)` *(async function)*
- `test_publish_epic_to_repo_requires_write_scope(env)` *(async function)*

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

### `tests/integration/test_node_enrollment_ws.py`

> Enrolled/revoked nodes at the `/agent/ws` handshake — issue #76 (minimal

- **`FakeSocket`** *(class)* — "Just enough `WebSocket` for `agent_ws`: it accepts, sends, and runs dry."
  - `__init__(self, incoming)` *(method)*
  - `accept(self)` *(async method)*
  - `close(self, code)` *(async method)*
  - `send_json(self, payload)` *(async method)*
  - `receive_json(self)` *(async method)*
- `wired(monkeypatch)` *(async function)*
- `test_a_freshly_enrolled_node_connects_with_the_token_enroll_returned(wired)` *(async function)*
- `test_a_freshly_enrolled_node_is_refused_with_the_wrong_token(wired)` *(async function)*
- `test_revoke_closes_the_live_socket(wired)` *(async function)* — "`force_close` against a connection that is genuinely still registered."
- `test_force_close_on_a_node_with_no_live_connection_reports_nothing_closed(wired)` *(async function)*
- `test_a_revoked_node_is_refused_on_its_next_handshake(wired)` *(async function)*

### `tests/integration/test_nodes.py`

> Bridge Node fleet visibility — issue #73 Stage 2.

- `users_file(tmp_path)`
- `api(users_file, monkeypatch)` *(async function)* — "A real app over a real database, seeded with one executor -> one node."
- `mark_live(factory, executor_id)` *(async function)*
- `set_last_seen(factory, executor_id, when)` *(async function)*
- `set_node_enabled(factory, node_id, enabled)` *(async function)*
- `set_capabilities_observed_at(factory, node_id, when)` *(async function)*
- `announce(factory, executor_id, **overrides)` *(async function)*
- `auth(token)`
- `test_nodes_require_a_token(api)` *(async function)*
- `test_an_expired_token_is_refused(api)` *(async function)*
- `test_a_token_without_the_admin_scope_is_forbidden(api)` *(async function)*
- `test_a_token_with_no_scopes_at_all_is_forbidden(api)` *(async function)*
- `test_an_unknown_node_id_is_not_found(api)` *(async function)*
- `test_list_returns_the_seeded_node(api)` *(async function)*
- `test_detail_returns_the_seeded_node(api)` *(async function)*
- `test_health_is_unknown_when_the_node_has_never_been_seen(api)` *(async function)*
- `test_health_is_offline_when_last_seen_is_older_than_the_reconnect_grace(api)` *(async function)*
- `test_health_is_degraded_when_live_but_disabled(api)` *(async function)*
- `test_health_is_ok_when_live_and_enabled(api)` *(async function)*
- `test_inventory_is_stale_before_any_announcement(api)` *(async function)*
- `test_inventory_is_not_stale_right_after_an_announcement(api)` *(async function)*
- `test_a_stale_capabilities_observed_at_is_reported_stale(api)` *(async function)*
- `test_no_absolute_path_leaks_after_an_announcement(api)` *(async function)* — "`docs/api/README.md` "fields that must never ship" excludes absolute"

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
- `test_every_served_api_route_is_guarded_or_listed_with_a_reason()` — "A route with no authorization guard ships only on purpose, in writing."
- `test_no_exemption_outlives_its_route()` — "A stale entry pre-authorizes whatever later claims that path."
- `test_every_exemption_is_load_bearing()` — "An entry the gate would pass without is an exemption that documents nothing."

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
- `test_handle_task_cancelled_triggers_notification(factory, monkeypatch)` *(async function)* — "issue #70: `handle_task_cancelled` lands a task in CANCELLED -- a"

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
- `test_an_unimplemented_engine_is_refused_before_dispatch(db_session)` *(async function)* — "Council round 1, "the second caller": the tool's own JSON Schema"
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
- `test_mcp_continue_codex_session_carries_the_parents_engine_forward(mcp_hub_factory)` *(async function)* — "Council round 1, "the sweep skeptic": before this fix, every"
- `test_mcp_continue_codex_session_succeeds_without_datetime_crash(mcp_hub_factory)` *(async function)* — "Issue #23: `continue_codex_session` forwards `parent.expires_at` —"
- `test_mcp_continue_codex_session_dispatches_to_a_connected_idle_executor(mcp_hub_factory)` *(async function)* — "Issue #24: unlike its sibling `submit_codex_task` (same file), this"
- `test_mcp_continue_codex_session_leaves_task_queued_when_the_executor_is_offline(mcp_hub_factory)` *(async function)* — "No regression on the pre-existing (disconnected) case: an offline"
- `test_mcp_continue_codex_session_at_capacity_does_not_dispatch(mcp_hub_factory)` *(async function)* — "A connected executor already at its concurrency limit must not be sent"

### `tests/unit/test_agent_announcement.py`

> The `hello` payload's real content -- issue #73 Stage 2.

- `test_hello_envelope_validates_as_node_announcement_with_derived_capabilities(monkeypatch, allow_workspace_write, allow_git_delivery, expected_present, expected_absent)` *(async function)*
- `test_hello_envelope_carries_os_and_arch_but_never_the_hostname(monkeypatch)` *(async function)* — "Issue #73: node identity must not be inferred from mutable hostname --"
- `test_discovery_root_count_reflects_the_nodes_own_scan_roots(monkeypatch)` *(async function)* — "Issue #73 Stage 3: `discovery_root_count` counts `AgentSettings."
- `test_discovery_root_count_is_zero_with_only_auto_project_root_set(monkeypatch)` *(async function)* — "The negative half of the pair above: `auto_project_root` alone never"
- `test_build_announcement_falls_back_to_minimal_payload_when_probing_raises(monkeypatch)` *(async function)* — "`_build_announcement` must never cost the connection. If anything"

### `tests/unit/test_agent_auth.py`

> Credential resolution for the `/agent/ws` handshake — issue #15.

- `test_the_header_is_the_credential()`
- `test_surrounding_whitespace_is_not_part_of_the_credential()`
- `test_nothing_presented_is_absent()`
- `test_blank_values_do_not_count_as_a_credential(blank)` — "A blank `X-Executor-Token:` is not a presented credential."

### `tests/unit/test_agent_auto_project.py`

> `agent.codex_bridge_agent.config.resolve_auto_project` -- the opt-in

- `test_resolves_a_real_repo_by_its_suggested_id(tmp_path)`
- `test_resolves_a_nested_submodule(tmp_path)` — "The same reasoning `discover_projects.py` bakes in: monorepo"
- `test_no_match_returns_none(tmp_path)`
- `test_a_root_that_is_not_a_directory_returns_none(tmp_path)`
- `test_a_directory_without_git_is_never_matched(tmp_path)`
- `test_a_symlinked_directory_outside_root_is_never_followed(tmp_path)` — "`walk_for_git_repos` never follows a symlink -- this proves the"
- `test_the_resolved_id_matches_what_discover_projects_would_suggest(tmp_path)` — "Consistency property this module's own docstring promises: an id a"

### `tests/unit/test_agent_discovery.py`

> `AgentService._scan_root`/`_discovery_loop` -- issue #73 Stage 3.

- **`DummyWebSocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send(self, payload)` *(async method)*
- `test_discovery_roots_defaults_to_empty()` — "The shipped default: no discovery task work at all (`_discovery_loop`'s"
- `test_discovery_roots_parses_a_comma_separated_env_var(monkeypatch)` — "Same convention every other list-shaped setting in this codebase uses"
- `test_discovery_roots_accepts_a_real_list_when_constructed_directly()` — "Tests throughout this file build `AgentSettings(discovery_roots=[...])`"
- `test_scan_root_finds_real_repos_with_remote_head_and_dirty(tmp_path)` *(async function)*
- `test_scan_root_reports_no_remote_as_none_not_an_error(tmp_path)` *(async function)* — "`git remote get-url origin` exits non-zero with no `origin` configured"
- `test_scan_root_marks_a_repo_with_uncommitted_changes_dirty(tmp_path)` *(async function)*
- `test_scan_root_ignores_a_directory_with_no_git(tmp_path)` *(async function)*
- `test_scan_root_never_follows_a_symlink_out_of_root(tmp_path)` *(async function)* — "Same guarantee `test_agent_auto_project.py` proves for"
- `test_scan_root_finds_a_nested_submodule_as_its_own_candidate(tmp_path)` *(async function)* — "CLAUDE.md's own project-scope rule: monorepo submodules are separate"
- `test_scan_root_returns_none_when_the_walk_itself_fails(tmp_path, monkeypatch)` *(async function)* — "A scan failure (e.g. a permission error surfacing as an exception"
- `test_discovery_loop_is_a_noop_when_no_roots_are_configured()` *(async function)* — "The shipped default (`discovery_roots=[]`) preserves today's"
- `test_discovery_loop_sends_one_envelope_per_root(tmp_path)` *(async function)* — "Protects against a single giant payload for every root: a slow or"
- `test_discovery_loop_skips_a_root_that_fails_but_still_reports_the_others(tmp_path, monkeypatch)` *(async function)* — "A root whose scan raises must not stop the others from being reported."

### `tests/unit/test_agent_machine_token.py`

> `agent.codex_bridge_agent.config.resolve_machine_token` -- issue #76's

- `test_falls_back_to_the_static_field_when_no_file_is_configured()`
- `test_prefers_the_file_over_the_static_field_when_both_are_set(tmp_path)`
- `test_strips_surrounding_whitespace_from_the_file_content(tmp_path)`
- `test_raises_when_the_configured_file_does_not_exist(tmp_path)`
- `test_raises_when_the_file_is_readable_by_group(tmp_path)`
- `test_raises_when_the_file_is_empty(tmp_path)`
- `test_a_correctly_permissioned_file_actually_works(tmp_path)` — "The positive control sitting next to every refusal above: `0600` is"

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
- `test_an_unregistered_project_is_still_refused_when_auto_project_root_is_unset(tmp_path)` *(async function)* — "Default behavior, unchanged by the new opt-in setting existing at"
- `test_auto_project_root_resolves_a_project_the_static_allowlist_does_not_know(tmp_path)` *(async function)* — "WK-20260830-chatgpt-entry-provider-and-delivery: with the opt-in root"
- `test_machine_token_travels_in_a_header_not_the_url(monkeypatch)` *(async function)* — "The token in the query string was logged verbatim 107 times (#15)."
- `test_connect_kwargs_are_accepted_by_the_real_installed_websockets_library()` *(async function)* — "Drives the REAL `websockets.connect`, not a fake -- every other test in"
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
- `test_handle_dispatch_refuses_a_write_mode_when_workspace_write_is_off(tmp_path)` *(async function)* — "WK-20260902-gh73-authorization-plane, issue #73 Stage 4."
- `test_handle_dispatch_allows_a_write_mode_when_workspace_write_is_on(tmp_path)` *(async function)* — "Positive control for the refusal above, in the same file (napkin-lessons"

### `tests/unit/test_agent_service_materialize.py`

> `AgentService._handle_materialize` -- the `ISSUE_MATERIALIZE` handler on

- **`DummyWebSocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send(self, payload)` *(async method)*
- `test_materialize_writes_files_and_reports_success(tmp_path)` *(async function)* — "Positive control for the three failure-mode tests below."
- `test_materialize_for_an_unknown_project_reports_a_typed_error(tmp_path)` *(async function)*
- `test_materialize_with_a_malformed_payload_reports_a_typed_error(tmp_path)` *(async function)*
- `test_materialize_republish_with_a_missing_existing_path_reports_a_typed_error(tmp_path)` *(async function)*

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
- `test_control_plane_seeds_one_node_per_existing_executor(legacy_db)` — "0009: an existing deployment must come up with its fleet already"
- `test_control_plane_grants_nothing_by_existing_alone(legacy_db)` — "0009 must create the authorization plane EMPTY."
- `test_control_plane_refuses_a_database_without_executors_before_touching_it(tmp_path)` — "A wrong database must be left untouched, not half-migrated."

### `tests/unit/test_capability_vocabulary.py`

> The capability vocabulary issue #73's authorization plane is built on.

- `test_every_task_mode_is_reachable_through_some_capability()` — "A mode no capability grants is a mode no authorization can ever permit."
- `test_read_grants_no_mode_that_can_modify_a_file()` — "The load-bearing claim of the whole read-only tier."
- `test_deliver_grants_no_mode()` — "Delivery is not a mode, and must not become one by accident."
- `test_an_unknown_capability_grants_nothing()` — "Forward compatibility must narrow, never widen."
- `test_a_discovery_root_cannot_grant_write_capabilities()` — "#73: "A node cannot grant itself project authorization merely by"
- `test_auto_authorizable_capabilities_never_reach_a_file()` — "Guards the constant itself, not just the validator that reads it."
- `test_a_root_grants_nothing_unless_it_says_so()` — "Scanning a tree and authorizing it are different acts."
- `test_the_five_discovered_states_are_all_distinct_values()` — "#73: "Do not collapse these into a single `enabled` boolean.""

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

### `tests/unit/test_discover_projects.py`

> `scripts/discover_projects.py` -- read-only repo discovery.

- `test_finds_a_top_level_repo(tmp_path)`
- `test_descends_past_a_repo_root_to_find_a_submodule(tmp_path)` — "CLAUDE.md: "Vale monorepo e submódulos (web, api, etc.)" -- a nested"
- `test_never_descends_into_excluded_directory_names(tmp_path)`
- `test_max_depth_stops_descent(tmp_path)`
- `test_suggested_project_ids_are_unique_on_a_name_collision(tmp_path)` — "The first `api` seen keeps the plain name; only the later collision"
- `test_flags_a_candidate_already_in_the_local_allowlist(tmp_path)`
- `test_a_malformed_local_allowlist_is_treated_as_empty_not_a_crash(tmp_path)`
- `test_cli_writes_json_to_the_requested_output_file(tmp_path)`
- `test_cli_never_writes_anywhere_but_the_requested_output_file(tmp_path)` — "Read-only by contract: the script's own docstring promises this."
- `test_cli_rejects_a_root_that_is_not_a_directory(tmp_path)`

### `tests/unit/test_discovery_store.py`

> `store.record_discovery_report` -- issue #73 Stage 3.

- `db_session()` *(async function)*
- `test_a_new_candidate_is_inserted_as_discovered(db_session)` *(async function)*
- `test_existing_candidate_refreshes_evidence_without_regressing_state(db_session)` *(async function)*
- `test_a_row_missing_from_the_report_becomes_stale(db_session)` *(async function)*
- `test_reconciliation_is_scoped_to_the_reports_own_root_path(db_session)` *(async function)* — "A row for a DIFFERENT root on the same node must not go STALE just"
- `test_denied_row_is_not_touched_even_when_reported_again(db_session)` *(async function)*
- `test_denied_row_does_not_regress_to_stale_when_absent(db_session)` *(async function)* — "The exact bug named in `docs/control-plane.md`: a refused candidate"
- `test_stale_row_reappearing_with_no_project_reverts_to_discovered(db_session)` *(async function)*
- `test_stale_row_reappearing_with_active_authorization_reverts_to_authorized(db_session)` *(async function)*
- `test_stale_row_reappearing_with_only_a_revoked_authorization_reverts_to_adopted(db_session)` *(async function)* — "The negative half of the pair above: a REVOKED authorization must not"
- `test_record_discovery_report_never_writes_authorization_or_projects(db_session)` *(async function)* — "The property that makes "the node proposes, the panel adopts" true by"
- `test_a_matching_auto_authorize_root_grants_nothing_from_a_report_alone(db_session)` *(async function)* — "The invariant this PR must not break: a node cannot authorize itself."
- `test_resource_key_is_a_fixed_width_hash_and_resource_path_carries_the_real_path(db_session)` *(async function)* — "The defect this PR fixes: a MySQL `varchar(255)` cannot hold every"
- `test_a_pre_migration_row_self_heals_its_resource_key_on_next_report(db_session)` *(async function)* — "A row written before 0013 has `resource_key` = the raw path (the"
- `test_a_large_report_does_not_cost_one_round_trip_per_candidate(db_session)` *(async function)* — "247 candidates -- the real root that motivated this work, rounded up"

### `tests/unit/test_effective_task_modes.py`

> `store.effective_task_modes` -- issue #73 Stage 4, WK-20260902-gh73-authorization-plane.

- `db_session()` *(async function)*
- `test_no_binding_returns_the_project_base_unchanged(db_session)` *(async function)* — "Non-regression: a pair that never went through discovery adoption is"
- `test_a_binding_with_no_authorization_permits_nothing(db_session)` *(async function)*
- `test_a_binding_with_read_and_test_permits_exactly_those_modes(db_session)` *(async function)*
- `test_a_revoked_authorization_permits_nothing(db_session)` *(async function)* — "Positive control for the "no authorization" case: an authorization row"
- `test_authorization_never_widens_past_the_projects_own_allowed_modes(db_session)` *(async function)* — "A capability grant intersects with `allowed_modes`, it never adds to it:"
- `test_create_task_for_an_unbound_pair_behaves_exactly_as_before_this_pr(db_session)` *(async function)* — "This is the test that would have passed before `effective_task_modes`"
- `test_create_task_for_a_bound_but_unauthorized_pair_refuses_every_mode(db_session)` *(async function)*
- `test_create_task_for_a_bound_and_partially_authorized_pair_allows_only_the_granted_modes(db_session)` *(async function)*
- `test_granting_a_new_pair_creates_one_row(db_session)` *(async function)*
- `test_granting_twice_overwrites_rather_than_merges(db_session)` *(async function)* — "Unlike adoption's own `_grant_project_authorization` (merge-only), this"
- `test_revoke_then_regrant_reuses_the_same_row(db_session)` *(async function)*
- `test_revoking_a_pair_with_no_active_authorization_returns_none(db_session)` *(async function)* — "Positive control for the revoke/regrant test: revoking nothing is a"

### `tests/unit/test_email_templates.py`

> `gateway.app.services.email_templates` -- pure rendering, no I/O.

- `test_every_kind_renders_a_complete_html_document()`
- `test_every_kind_has_a_distinct_accent_color_and_badge_label()` — "Approved on the design canvas: no two kinds should read as the same"
- `test_subject_prefix_is_bracketed_and_kind_specific()`
- `test_every_text_field_is_html_escaped(value)` — "Every argument is caller-controlled text -- some of it, per `render_email`'s"
- `test_a_cta_link_escapes_its_href_and_label()`
- `test_no_style_block_and_no_class_attribute()` — "Email clients strip <style> blocks and class selectors unpredictably"
- `test_no_inline_svg_shipped_in_a_real_email()` — "Outlook's desktop renderer does not support <svg> -- a broken icon in"
- `test_no_rows_and_no_cta_omits_the_highlight_card()`

### `tests/unit/test_enroll_node.py`

> `scripts/enroll_node.py` -- one HTTP call, one file write, issue #76.

- `test_write_machine_token_creates_the_file_with_0600(tmp_path)`
- `test_write_machine_token_overwrites_an_existing_file(tmp_path)`
- `test_main_enrolls_and_writes_the_token(tmp_path, monkeypatch)`
- `test_main_reports_a_refused_invite_and_writes_nothing(tmp_path, monkeypatch)`
- `test_main_strips_a_trailing_slash_from_the_gateway_url(monkeypatch, tmp_path)`

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

### `tests/unit/test_issue_materialize.py`

> `materialize_epic` and the shared numbering scanner -- issue #78, Commit 2c.

- `test_list_used_issue_numbers_covers_all_three_layouts(tmp_path)`
- `test_list_used_issue_numbers_empty_when_docs_issues_missing(tmp_path)`
- `test_materialize_epic_allocates_the_next_free_number(tmp_path)`
- `test_allocate_dir_retries_past_a_real_collision(tmp_path)` — "Direct test of the atomic-creation retry loop itself -- the exact"
- `test_allocate_file_retries_past_a_real_collision(tmp_path)` — "Same mechanism, for an issue file -- `os.open(..., O_CREAT|O_EXCL)`"
- `test_materialize_epic_survives_a_numbering_race_end_to_end(tmp_path, monkeypatch)` — "`materialize_epic` wired end-to-end against a numbering scan that"
- `test_materialize_epic_refuses_a_traversing_existing_path(tmp_path)`
- `test_materialize_epic_refuses_a_missing_existing_path(tmp_path)`
- `test_materialize_epic_republish_updates_in_place_and_adds_new_issues(tmp_path)`

### `tests/unit/test_issue_render.py`

> `render_epic_markdown` -- issue #78, Commit 2a.

- `test_epic_directory_slug_bakes_title_and_status_suffix_together()`
- `test_issue_relative_key_embeds_the_issue_id_as_a_correlation_segment()`
- `test_render_epic_markdown_exact_bytes_for_epic_and_two_issues()`
- `test_render_epic_markdown_with_no_issues_and_no_description()`
- `test_render_epic_markdown_is_deterministic_regardless_of_input_order()`

### `tests/unit/test_main_import.py`

- `test_main_app_imports()`

### `tests/unit/test_node_enrollment.py`

> `store.create_node_invite` / `store.enroll_node` / `store.revoke_node` —

- `db_session()` *(async function)*
- `test_create_node_invite_stores_only_the_hash(db_session)` *(async function)*
- `test_create_node_invite_never_writes_the_raw_token_to_audit_events(db_session)` *(async function)*
- `test_enroll_node_creates_executor_and_node_and_consumes_the_invite(db_session)` *(async function)*
- `test_enroll_node_refuses_an_unknown_token(db_session)` *(async function)*
- `test_enroll_node_refuses_a_consumed_invite_the_second_time(db_session)` *(async function)*
- `test_claiming_an_invite_is_conditional_so_only_one_racer_wins(db_session)` *(async function)* — "The `WHERE consumed_at IS NULL` `enroll_node` relies on."
- `test_enroll_node_refuses_an_expired_invite(db_session)` *(async function)*
- `test_enroll_node_generates_an_id_rather_than_trusting_the_caller(db_session)` *(async function)* — "No `executor_id`/`node_id` field on the request at all -- this is what"
- `test_revoke_node_disables_both_the_node_and_its_executor(db_session)` *(async function)*
- `test_revoke_node_refuses_an_unknown_node(db_session)` *(async function)*

### `tests/unit/test_node_store.py`

> `store.ensure_node_for_executor` / `upsert_registry` / `record_node_announcement`

- `db_session()` *(async function)*
- `test_ensure_node_for_executor_creates_and_binds_when_node_id_is_null(db_session)` *(async function)*
- `test_ensure_node_for_executor_is_idempotent(db_session)` *(async function)*
- `test_upsert_registry_produces_a_node_for_a_newly_added_executor(db_session)` *(async function)*
- `test_upsert_registry_never_overwrites_an_existing_executor_or_project_row(db_session)` *(async function)* — "The correction issue #76 item 4 makes: a revoked node stays revoked"
- `test_upsert_registry_hashes_the_machine_token_of_a_new_executor(db_session)` *(async function)*
- `test_upsert_registry_backfills_an_empty_machine_token_hash(db_session)` *(async function)* — "Issue #76's compatibility rule: a pre-#76 executor row, whose only"
- `test_upsert_registry_does_not_overwrite_an_already_backfilled_hash(db_session)` *(async function)* — "The other half of the same rule: once the hash column is populated,"
- `test_record_node_announcement_writes_observation_fields(db_session)` *(async function)*
- `test_record_node_announcement_leaves_enabled_health_reason_and_authorizations_untouched(db_session)` *(async function)* — "An announcement is an observation, never a grant (issue #73)."

### `tests/unit/test_notify.py`

> `gateway.app.services.notify` -- the task-finished completion email.

- `session()` *(async function)*
- `test_no_config_is_a_silent_no_op(session, monkeypatch)` *(async function)*
- `test_a_non_terminal_state_is_a_no_op(session, tmp_path, monkeypatch)` *(async function)*
- `test_a_world_readable_config_file_is_refused(session, tmp_path, monkeypatch)` *(async function)*
- `test_a_missing_config_file_is_refused(session, tmp_path, monkeypatch)` *(async function)*
- `test_a_sender_that_raises_never_fails_the_task_and_records_only_the_exception_type(session, tmp_path, monkeypatch)` *(async function)*
- `test_a_config_file_with_spaces_around_equals_parses_correctly(session, tmp_path, monkeypatch)` *(async function)* — "This ecosystem's own credential files are inconsistent: most are"
- `test_task_last_error_is_never_included_in_the_email(session, tmp_path, monkeypatch)` *(async function)* — "Issue #70 enumerates exactly what the body may carry -- task id,"
- `test_a_delivery_refusal_reason_is_redacted(session, tmp_path, monkeypatch, delivery_reason)` *(async function)* — "`reason` is the one delivery field allowed to carry free text (issue"
- `test_a_successful_send_writes_no_audit_event(session, tmp_path, monkeypatch)` *(async function)*

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

### `tests/unit/test_register_projects.py`

> `scripts/register_projects.py` -- diff-only, never applies anything.

- `test_registry_diff_adds_only_the_missing_projects(tmp_path)`
- `test_registry_diff_flags_a_path_collision_instead_of_silently_skipping(tmp_path)`
- `test_registry_diff_treats_a_missing_file_as_an_empty_registry(tmp_path)`
- `test_executor_diff_adds_only_ids_not_already_allowed(tmp_path)`
- `test_executor_diff_notes_an_unknown_executor_id(tmp_path)`
- `test_local_allowed_projects_diff_matches_registry_diff_shape(tmp_path)`
- `test_user_diff_adds_only_ids_not_already_allowed(tmp_path)`
- `test_user_diff_matches_by_email_case_insensitively(tmp_path)`
- `test_duplicate_project_id_in_the_approved_list_is_rejected(tmp_path)`
- `test_cli_never_writes_to_any_file_it_reads(tmp_path)`
- `test_cli_writes_only_the_report_when_out_is_given(tmp_path)`
- `test_cli_requires_at_least_one_target_file(tmp_path)`
- `test_cli_rejects_user_id_without_user_registry_file(tmp_path)`

### `tests/unit/test_runner_probe.py`

> `Runner.probe()` and `RunnerPool.probe_all()` -- issue #73 Stage 2.

- `test_probe_reports_unavailable_when_binary_not_on_path(monkeypatch, runner_cls, bin_field)` *(async function)*
- `test_probe_reports_available_and_the_parsed_version(monkeypatch, runner_cls, bin_field)` *(async function)*
- `test_probe_survives_oserror_without_raising(monkeypatch, runner_cls, bin_field)` *(async function)*
- `test_probe_survives_a_timeout_without_raising(monkeypatch, runner_cls, bin_field, timeout_module)` *(async function)*
- `test_probe_detail_never_carries_the_configured_binary_path(monkeypatch, runner_cls, bin_field)` *(async function)* — "`detail` is meant to explain a probe failure to an operator, never to"
- `test_probe_all_returns_one_entry_per_known_engine()` *(async function)*
- `test_probe_all_survives_one_runner_raising()` *(async function)*

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
- `test_required_tables_cannot_fire_at_boot_today()` — "`REQUIRED_TABLES` is documentation, not a boot gate — pinned, not fixed."

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
- `test_a_malformed_registry_fails_closed_instead_of_raising(tmp_path)` — "A hand-edit that leaves invalid JSON must refuse every credential, not raise."
- `test_a_shape_pydantic_refuses_fails_closed(tmp_path)` — "A structurally-valid JSON whose entries lack required fields also fails closed."
- `test_a_duplicate_user_id_refuses_the_whole_registry(tmp_path)` — "Last-write-wins on a colliding key silently rebinds a live token's privileges."
- `test_a_user_id_colliding_with_another_email_refuses_the_registry(tmp_path)` — "A `user_id` equal to another account's e-mail is the same collision."
- `test_a_case_variant_collision_is_refused(tmp_path)` — "The collision is case-insensitive, because resolution is."
- `test_a_non_pbkdf2_hash_does_not_set_the_derivation_cost(tmp_path)` — "An argon2/scrypt string in the registry must not dictate the PBKDF2 target."
- `test_an_over_ceiling_pbkdf2_hash_is_unusable_and_uncosted(tmp_path)` — "A typo'd pbkdf2 round count cannot turn one line into an authentication DoS."

### `tests/unit/test_version_is_single_sourced.py`

> Every statement of the application version must be the same statement.

- `test_pyproject_and_code_agree()`
- `test_settings_reports_the_single_source()`
- `test_fastapi_application_reports_the_single_source()`
- `test_mcp_server_info_reports_the_single_source()` — "The MCP client sees this one; it drifted independently of the HTTP API."
- `test_no_stray_version_literals_in_the_gateway()` — "A new hardcoded copy is how the previous four accumulated."

