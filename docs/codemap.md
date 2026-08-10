# Code Map · codex-bridge

> Generated: 2026-08-10 · Root: `/home/esteban/Sync/Projects/AI/CodexBridge`
> Refresh: `governancekit --root /home/esteban/Sync/Projects/AI/CodexBridge map`

## Summary

- 43 file(s) · 161 symbol(s) indexed
- Languages: config (2), python (39), shell (2)
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
- `.gitignore`: `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.coverage`, `codex_bridge.db`, `dist/`, `build/`, `*.egg-info/`, `.venv/`, `venv/`, `AGENTS.md`, `.cursorrules`, `CLAUDE.md`, `.windsurfrules`, `GEMINI.md`, `.github/copilot-instructions.md`, `.amazonq/rules/ai-agents.md`, `.credentials`, `handoff.md`, `new-tag.sh`, `scripts/install-agents-kit.sh`, `scripts/agent-worktree.sh`, `.docs-migration-bak/`, `.gk/operator.json`, `.gk/secrets.json`, `.gk/context-telemetry.jsonl`, `.gk/overwritten/`

## Entry Points

- `agent/codex_bridge_agent/__main__.py` — `python -m agent.codex_bridge_agent`

## File Tree

```
agent/
  __init__.py  — "Agent package."
  codex_bridge_agent/
    __init__.py  — "codex-bridge-agent package."
    __main__.py
    codex_runner.py
    config.py
    git_tools.py
    service.py
deploy/
  incus/
    codexbridge_edge_proxy.py
gateway/
  Dockerfile
  __init__.py  — "Gateway package."
  app/
    __init__.py  — "Gateway app package."
    core/
      config.py
      logging.py
      oauth.py
      rate_limit.py
      registry.py
      users.py
    db/
      base.py
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
      metrics.py
      store.py
pyproject.toml
scripts/
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
    test_openapi_document.py  — "Contract tests for the canonical OpenAPI document."
  integration/
    test_store_and_mcp.py
  unit/
    test_agent_service.py
    test_main_import.py
    test_policy.py
    test_security.py
    test_users.py
```

## Symbol Index

### `agent/codex_bridge_agent/codex_runner.py`

- **`CodexRunner`** *(class)*
  - `__init__(self, settings)` *(method)*
  - `cancel(self, task_id)` *(async method)*
  - `run_task(self, task_id, project_root, instruction, timeout_seconds, continue_session_id, send_log)` *(async method)*

### `agent/codex_bridge_agent/config.py`

- **`AgentSettings`** *(class)*
- **`AgentProjectConfig`** *(class)*
- `load_agent_projects(path)`

### `agent/codex_bridge_agent/git_tools.py`

- `collect_git_snapshot(project_root, diff_max_chars)` *(async function)*

### `agent/codex_bridge_agent/service.py`

- **`AgentService`** *(class)*
  - `__init__(self, settings)` *(method)*
  - `run_forever(self)` *(async method)*
- `main()` *(async function)*

### `deploy/incus/codexbridge_edge_proxy.py`

- `proxy(path, request)` *(async function)*

### `gateway/app/core/config.py`

- **`Settings`** *(class)*
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
- `now_utc()`
- `expires_in(seconds)`
- `pkce_challenge(verifier)`
- `issuer_metadata()`
- `protected_resource_metadata()`
- `error_redirect(redirect_uri, error, state, description)`

### `gateway/app/core/rate_limit.py`

- **`MemoryRateLimiter`** *(class)*
  - `__init__(self, limit, window_seconds)` *(method)*
  - `allow(self, key)` *(async method)*

### `gateway/app/core/registry.py`

- **`Registry`** *(class)*
- `load_registry(path)`

### `gateway/app/core/users.py`

- **`GatewayUser`** *(class)*
- **`UserRegistry`** *(class)*
- **`AuthenticatedPrincipal`** *(class)*
  - `is_admin(self)` *(method)*
  - `has_scope(self, scope)` *(method)*
  - `can_access_project(self, project_id)` *(method)*
- `load_user_registry(path)`
- `lookup_user(path, username_or_email)`
- `verify_password(password, encoded_hash)`

### `gateway/app/db/base.py`

- **`Base`** *(class)*

### `gateway/app/db/session.py`

- `get_session()` *(async function)*

### `gateway/app/main.py`

- `oauth_www_authenticate_header()`
- `validate_oauth_client(client_id, redirect_uri)`
- `render_authorize_form()`
- `authenticate_mcp_request(session, body, authorization)` *(async function)*
- `startup()` *(async function)*
- `healthz()` *(async function)*
- `metrics_endpoint()` *(async function)*
- `oauth_metadata()` *(async function)*
- `oauth_protected_resource()` *(async function)*
- `oauth_authorize(response_type, client_id, redirect_uri, scope, state, code_challenge, code_challenge_method)` *(async function)*
- `oauth_authorize_submit(response_type, client_id, redirect_uri, scope, state, code_challenge, code_challenge_method, username, password, session)` *(async function)*
- `oauth_token(grant_type, code, redirect_uri, client_id, code_verifier, session)` *(async function)*
- `mcp_endpoint(request, authorization, session)` *(async function)*
- `agent_ws(websocket, executor_id, token)` *(async function)*

### `gateway/app/mcp/server.py`

- `handle_mcp_call(body, session, hub, principal)` *(async function)*
- `hub_envelope(executor_id, message_type, payload)`

### `gateway/app/mcp/tools.py`

- `tool_definitions()`

### `gateway/app/models/entities.py`

- **`ExecutorModel`** *(class)*
- **`ProjectModel`** *(class)*
- **`TaskModel`** *(class)*
- **`TaskLogModel`** *(class)*
- **`AuditEventModel`** *(class)*
- **`MessageReceiptModel`** *(class)*
- **`OAuthAuthorizationCodeModel`** *(class)*
- **`OAuthAccessTokenModel`** *(class)*

### `gateway/app/services/agent_hub.py`

- **`AgentConnection`** *(class)*
- **`AgentHub`** *(class)*
  - `__init__(self, session_factory)` *(method)*
  - `is_connected(self, executor_id)` *(method)*
  - `register(self, executor_id, websocket)` *(async method)*
  - `unregister(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `mark_task_finished(self, executor_id, task_id)` *(async method)*

### `gateway/app/services/audit.py`

- `record_event(session, entity_type, entity_id, event_type, payload)` *(async function)*

### `gateway/app/services/metrics.py`

- `render_metrics()`

### `gateway/app/services/store.py`

- `upsert_registry(session, executors, projects)` *(async function)*
- `list_executors(session)` *(async function)*
- `list_projects(session)` *(async function)*
- `list_projects_for_executor(session, executor_id)` *(async function)*
- `get_task(session, task_id)` *(async function)*
- `list_recent_tasks(session, limit)` *(async function)*
- `create_task(session, request, executor_online, continue_session_id, requested_by_user_id, requested_by_email)` *(async function)*
- `mark_executor_connected(session, executor_id, connected)` *(async function)*
- `next_dispatchable_task(session, executor_id)` *(async function)*
- `update_task_state(session, task_id, state, error)` *(async function)*
- `append_log(session, task_id, offset, stream, line)` *(async function)*
- `decide_task_approval(session, task_id, decision, reason)` *(async function)*
- `recover_tasks_after_startup(session)` *(async function)*
- `get_logs(session, task_id, offset, limit)` *(async function)*
- `store_result(session, task_id, result, final_state)` *(async function)*
- `create_oauth_authorization_code(session)` *(async function)*
- `consume_oauth_authorization_code(session, code)` *(async function)*
- `create_oauth_access_token(session)` *(async function)*
- `get_oauth_access_token(session, token)` *(async function)*
- `store_message_receipt(session, message_id, executor_id, message_type)` *(async function)*

### `shared/policy.py`

- **`PolicyDecision`** *(class)*
- `policy_level_for_mode(mode)`
- `evaluate_task_policy(request)`

### `shared/protocol.py`

- **`TaskMode`** *(class)*
- **`TaskState`** *(class)*
- **`PolicyLevel`** *(class)*
- **`TaskPriority`** *(class)*
- **`AgentMessageType`** *(class)*
- **`ApprovalDecision`** *(class)*
- **`ProjectRegistration`** *(class)*
- **`ExecutorRegistration`** *(class)*
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

### `tests/integration/test_store_and_mcp.py`

- **`DummyHub`** *(class)*
  - `__init__(self)` *(method)*
  - `is_connected(self, executor_id)` *(method)*
  - `dispatch_next(self, executor_id)` *(async method)*
  - `send(self, executor_id, envelope)` *(async method)*
- `db_session()` *(async function)*
- `test_offline_task_rejected_without_queue(db_session)` *(async function)*
- `test_offline_task_queued_when_allowed(db_session)` *(async function)*
- `test_project_allowlist_enforced(db_session)` *(async function)*
- `test_mcp_list_projects_filters_by_executor(db_session)` *(async function)*
- `test_mcp_submit_task_rejects_project_outside_user_scope(db_session)` *(async function)*
- `test_task_logs_and_status_are_limited_to_task_owner(db_session)` *(async function)*
- `test_approval_moves_task_back_to_queue(db_session)` *(async function)*
- `test_startup_recovery_marks_running_as_lost(db_session)` *(async function)*

### `tests/unit/test_agent_service.py`

- **`DummyWebSocket`** *(class)*
  - `__init__(self)` *(method)*
  - `send(self, payload)` *(async method)*
- **`FailingRunner`** *(class)*
  - `run_task(self, **_)` *(async method)*
- `test_dispatch_failure_returns_task_result(tmp_path)` *(async function)*

### `tests/unit/test_main_import.py`

- `test_main_app_imports()`

### `tests/unit/test_policy.py`

- `test_policy_level_for_mode()`
- `test_sensitive_instruction_requires_approval()`

### `tests/unit/test_security.py`

- `test_ensure_within_root_blocks_escape(tmp_path)`
- `test_log_redaction()`

### `tests/unit/test_users.py`

- `test_verify_password_accepts_known_hash()`
- `test_load_user_registry_indexes_by_user_id_and_email(tmp_path)`
- `test_authenticated_principal_checks_scopes_and_projects()`

