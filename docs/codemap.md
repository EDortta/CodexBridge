# Code Map · codex-bridge

> Generated: 2026-08-10 · Root: `/home/esteban/Sync/Projects/AI/CodexBridge`
> Refresh: `governancekit --root /home/esteban/Sync/Projects/AI/CodexBridge map`

## Summary

- 63 file(s) · 310 symbol(s) indexed
- Languages: config (2), python (59), shell (2)
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
    api/
      __init__.py  — "Cross-cutting HTTP behaviour for the mobile API (issue #12)."
      concurrency.py  — "Optimistic concurrency: two operators, two devices, one decision."
      errors.py  — "The one error envelope every contract endpoint returns."
      idempotency.py  — "Replay-safe writes for a client that goes offline mid-request."
      pagination.py  — "Cursor pagination for collections, and the offset scheme logs keep."
      rate_limit.py  — "Rate limiting for the contract surface."
      request_context.py  — "Per-request identifier, carried from the middleware to the error envelope."
      routes/
        __init__.py  — "HTTP routers for the mobile contract surface."
        probes.py  — "Liveness, readiness and version — what a client asks before anything else."
      scope.py  — "Which requests the API's cross-cutting rules apply to."
      setup.py  — "One call that installs every cross-cutting API behaviour."
    core/
      config.py
      logging.py
      oauth.py
      rate_limit.py
      registry.py
      users.py
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
    test_openapi_document.py  — "Contract tests for the canonical OpenAPI document."
    test_proxy_routes.py  — "Every contracted path must be routed by the proxies in front of the gateway."
  integration/
    test_api_conventions.py  — "Representative-endpoint compliance for the cross-cutting API rules (issue #12)."
    test_probes.py  — "Health, readiness and version — issue #3."
    test_store_and_mcp.py
  unit/
    test_agent_service.py
    test_apply_migrations.py  — "The migration runner, exercised against real throwaway databases."
    test_main_import.py
    test_policy.py
    test_schema_guard.py  — "The guard that refuses to serve a database the code has outgrown."
    test_security.py
    test_users.py
    test_version_is_single_sourced.py  — "Every statement of the application version must be the same statement."
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
- `lookup(session)` *(async function)* — "Read-only: the stored response for this key, or None. Does not reserve."
- `reserve(session)` *(async function)* — "Claim this key before doing the work."
- `complete(session)` *(async function)* — "Attach the finished response to a reservation this caller won."
- `release(session)` *(async function)* — "Drop a reservation whose write failed, so the client may try again."
- `remember(session)` *(async function)* — "Reserve and complete in one step. For a write already known to be done."
- `purge_expired(session)` *(async function)* — "Drop records past their TTL. Returns how many were removed."

### `gateway/app/api/pagination.py`

> Cursor pagination for collections, and the offset scheme logs keep.

- `scope_digest(endpoint, filters)` — "Identity of "this endpoint under these filters", for cursor binding."
- `encode_cursor(scope, position)`
- `decode_cursor(scope, cursor, expect)` — "Decode a cursor this server issued for `scope`, or fail with a typed error."
- `parse_limit(value)`
- `page_info()` — "Build `PageInfo`, keeping its one invariant true by construction."
- `paginate(items)` — "Trim an over-fetched list to `limit` and describe the page."

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

### `gateway/app/api/routes/probes.py`

> Liveness, readiness and version — what a client asks before anything else.

- `database_reachable(now)` *(async function)* — "Cached, single-flight readiness of the database."
- `reset_database_cache()` — "Drop the cached result. For tests and for a deliberate re-probe."
- `health()` *(async function)* — "Liveness. Deliberately touches nothing — see the module docstring."
- `ready(response)` *(async function)* — "Readiness, with the reason when it is not ready."
- `api_version()` *(async function)* — "What this server speaks, so a client can refuse before it starts."

### `gateway/app/api/scope.py`

> Which requests the API's cross-cutting rules apply to.

- `is_contract_path(path)` — "Whether `path` is governed by docs/api/codex-bridge.openapi.yaml."

### `gateway/app/api/setup.py`

> One call that installs every cross-cutting API behaviour.

- `install_api_conventions(app)` — "Install the error envelope, the request id, and their shared plumbing."

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
- **`IdempotencyRecordModel`** *(class)* — "A completed write, keyed so an offline retry replays instead of repeating."
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

### `scripts/apply_migrations.py`

> Apply the SQL files in `migrations/`, once each, in filename order.

- `main()`

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
- `test_reported_contract_version_matches_the_document(spec)` — "`GET /api/version` must not claim a contract version the file disagrees with."
- `test_every_declared_component_is_referenced_or_owned(spec)` — "A component nothing points at is a claim the API behaves that way."
- `test_no_pending_component_is_stale(spec)` — "An entry whose component is now wired must be removed."

### `tests/contract/test_proxy_routes.py`

> Every contracted path must be routed by the proxies in front of the gateway.

- `contract_paths()`
- `test_nginx_configs_exist()` — "If the configs move, this gate must fail loudly rather than pass empty."
- `test_every_contract_path_is_routed_by_every_terminating_vhost(contract_paths)`
- `test_every_proxied_location_reaches_an_upstream()` — "A location block with no `proxy_pass` silently drops its path."

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
- `test_api_version_omits_build_revision_when_the_deployment_injected_none(client)` — "Absence means "not reported", never "no build" — so no empty string."
- `test_api_version_reports_build_revision_when_set(client, monkeypatch)`
- `test_probe_responses_carry_no_infrastructure_detail(client)` — "The acceptance criterion "no sensitive infrastructure details", asserted."
- `test_api_version_is_rate_limited_with_the_contract_shape(monkeypatch)` — "The contract documents 429 + Retry-After; before this it documented only."
- `test_health_and_ready_are_never_rate_limited(monkeypatch)` — "Monitoring polls these on a timer."
- `test_bucket_is_the_caller_not_the_nearest_proxy(monkeypatch)` — "The deployed chain has more than one appending hop."
- `test_client_cannot_forge_a_hop_to_escape_its_bucket(monkeypatch)` — "Prepending entries must not move the caller off its bucket."
- `test_unparseable_forwarded_for_falls_back_to_one_shared_bucket(header, monkeypatch)` — "A trailing comma produced the literal bucket `"ip:"` — keyed on nothing."
- `test_missing_forwarded_for_behind_a_proxy_is_not_trusted(monkeypatch)` — "No header while configured for proxies means the request bypassed them."
- `test_ready_is_cached_so_a_flood_cannot_drain_the_connection_pool(monkeypatch)` — "`/ready` is unauthenticated and unlimited, and shares the API's pool."
- `test_readiness_cache_expires(monkeypatch)` *(async function)* — "Cached, not frozen: a recovered database must be noticed."
- `test_a_failed_probe_is_cached_only_briefly(monkeypatch)` *(async function)* — "A blip must not pin the gateway out of rotation for the whole TTL."
- `test_a_concurrent_burst_issues_one_probe(monkeypatch)` *(async function)* — "The cache alone does not help while the first probe is still running."
- `test_zero_cache_seconds_is_floored(monkeypatch)` — "A TTL of 0 would restore the uncached DoS, so it is not honoured."
- `test_every_served_api_route_carries_the_rate_limiter()` — "`main.py` claimed every future /api route inherits the limiter. It does not."

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

### `tests/unit/test_apply_migrations.py`

> The migration runner, exercised against real throwaway databases.

- `run(db, *args)`
- `legacy_db(tmp_path)` — "A database as `create_all` would have left it before issue #12."
- `columns(db, table)`
- `tables(db)`
- `test_adopting_then_upgrading_adds_the_column_to_existing_rows(legacy_db)`
- `test_reapplying_is_a_no_op(legacy_db)`
- `test_failure_names_the_way_forward(legacy_db)` — "The operator arrives here from a startup message naming this command."
- `test_dry_run_changes_nothing(legacy_db)`
- `test_unknown_migration_name_is_refused(legacy_db)`

### `tests/unit/test_main_import.py`

- `test_main_app_imports()`

### `tests/unit/test_policy.py`

- `test_policy_level_for_mode()`
- `test_sensitive_instruction_requires_approval()`

### `tests/unit/test_schema_guard.py`

> The guard that refuses to serve a database the code has outgrown.

- `test_fresh_database_passes(tmp_path)`
- `test_missing_column_is_named_with_its_migration(tmp_path)` — "The message has to be actionable: what is missing, and what adds it."
- `test_create_all_does_not_repair_an_existing_table(tmp_path)` — "The premise of the guard, asserted rather than assumed."

### `tests/unit/test_security.py`

- `test_ensure_within_root_blocks_escape(tmp_path)`
- `test_log_redaction()`

### `tests/unit/test_users.py`

- `test_verify_password_accepts_known_hash()`
- `test_load_user_registry_indexes_by_user_id_and_email(tmp_path)`
- `test_authenticated_principal_checks_scopes_and_projects()`

### `tests/unit/test_version_is_single_sourced.py`

> Every statement of the application version must be the same statement.

- `test_pyproject_and_code_agree()`
- `test_settings_reports_the_single_source()`
- `test_fastapi_application_reports_the_single_source()`
- `test_mcp_server_info_reports_the_single_source()` — "The MCP client sees this one; it drifted independently of the HTTP API."
- `test_no_stray_version_literals_in_the_gateway()` — "A new hardcoded copy is how the previous four accumulated."

