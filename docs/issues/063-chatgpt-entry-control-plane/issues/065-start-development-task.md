Parent: #63
Related: #44 (this is the MCP-facing sibling of #44's MOBO-facing flow), #64 (#41a, provides `engine`)

## Objective
Add one new MCP tool, `start_development_task`, that lets an operator say "resolve issue X of project Y" from ChatGPT and have it resolve into a submitted task — without ChatGPT ever inventing an `expires_at` timestamp or a project path, and without the gateway ever reading a file.

## Scope
- New tool in `gateway/app/mcp/tools.py` / `gateway/app/mcp/server.py`.
- `get_task_status` and `list_recent_tasks` gain **additive-only** `structuredContent` fields (`engine`, `issue_ref`, `delivery`, `eta_seconds`); no existing tool is renamed, honoring the coexistence rule recorded in `mobo-dev-orch/57a-surface-inventory.md` that a surface with no inventory row may not change meaning.
- New `store.resolve_project_reference(session, text, principal)` and `store.estimate_task_duration_seconds(session, *, project_id, mode, engine)`.
- New `agent/codex_bridge_agent/instructions.py` on the executor side, resolving `issue_ref` into an issue snapshot.

## Requirements
- `inputSchema`: only `project` is required. Defaults: `engine="claude"`, `mode="implement"`, `allow_push=false`, `run_when_available=true`, `timeout_seconds=3600`. **No `expires_at` field** — computed server-side as `now + max(2h, 2 × timeout_seconds)`, removing the single most error-prone field for an LLM caller. `branch` is required when `allow_push` is true, enforced in the handler as a typed `branch_required_for_push` error (JSON Schema `dependentRequired` is not reliably honored by MCP clients).
- Project resolution: exact `project_id` match, then case-insensitive exact `name` match, then unique case-insensitive prefix. Zero matches → 404 `unknown_project`. **More than one match → 409 `ambiguous_project` with the candidates listed in `structuredContent`**, so ChatGPT can ask the operator rather than guessing.
- If the project resolves in the gateway registry but is absent from the executor's allowlist, return a typed **`project_not_onboarded`** naming both files that must agree (`/etc/codex-bridge/registry.json` on the gateway host, `~/.config/codex-bridge-agent/allowed-projects.json` on the executor host) and the restart requirement — rather than letting the task be queued and fail later with a bare `unknown_project`, which `docs/project-onboarding.md` already calls "the most likely operational failure of this system." Today only `codexbridge` and `scripts` are onboarded on this deployment; any other project needs that maintenance window first, which is an operator action, not something this tool performs.
- Issue reference resolution: `ISSUE_REF_PATTERN = ^(local:[A-Za-z0-9-]{1,128}|docs:\d{1,6}|gh:\d{1,9}|\d{1,6})$` — no `/` and no `.`, so no path-traversal component can ever reach a filesystem `Path()`. `local:<id>` resolves against an `IssueModel` row **on the gateway**. `docs:NNN` or a bare number resolves **on the executor**, via glob over `docs/issues/` tolerant of both the `-[status]`-suffixed layout `.docs/agents/issue-automation.md` specifies and the plain-number layout this repository's own `docs/issues/` directory actually uses. Zero or multiple matches → typed `issue_not_found` / `issue_ambiguous`, never a guess. `gh:N` returns a typed **`issue_source_unsupported`** — GitHub issue ingestion has no owner in this codebase (council finding **F18**) and this tool must say so rather than improvising a second id space. After resolving a path, `ensure_within_root(project.path, resolved)` is applied before any read.
- **Provenance separation, the most important property of this tool.** The resolved issue file's content is untrusted third-party text. `SubmitTaskRequest.instruction` carries **only** the operator's own request text (plus a one-line generated objective when only an issue reference was given, e.g. "Resolve issue 046 in project zeecred."). The issue snapshot is read on the executor and injected into the provider prompt inside a clearly delimited, explicitly untrusted-labeled block, placed after the existing `BASE_PROMPT`. **The snapshot never reaches `evaluate_task_policy`, and no policy decision anywhere is made by matching against it.** Without this separation, anyone who can write a file under `docs/issues/` in a target repository can drive the sensitivity classifier — either denial of service (stuffing "deploy" into an issue body to force every resolution into `awaiting_approval`) or evasion (avoiding the ten sensitive keywords entirely).
- ETA: `store.estimate_task_duration_seconds` computes the **median** (not mean — a single 3600s timeout would dominate a mean) of `completed_at - started_at`, read from those columns directly rather than parsing `result_json`, over the last 50 completed tasks in the last 90 days matching `project_id + mode + engine`. Fewer than 5 samples widens the match — drop `engine`, then `project_id`, then `mode` — and `eta_basis` reports which level was used, with `eta_sample_size` reporting how many. **Zero samples returns `eta_seconds: null`, never an invented number** — an estimate with no declared basis is exactly the "best available evidence" failure council finding **F29** identifies.
- Response shape: `{task_id, state, engine, project_id, executor_id, issue_ref, branch, allow_push, expires_at, eta_seconds, estimated_completion_at, eta_basis, eta_sample_size}`.

## ARO
- **F16** (untrusted issue content): directly addressed by the provenance-separation requirement above. If dropped for convenience in implementation, the sensitivity classifier becomes attacker-controlled by anyone who can write to `docs/issues/` in the target repo.
- **F18** (GitHub ingestion has no owner): `gh:N` is explicitly out of scope, returning a typed error rather than an improvised second id space.
- **F29** (infalsifiable cost/ETA claims): addressed by the null-when-unknown rule and the reported sample basis.
- Operational risk, not a council finding: only two projects are onboarded on the live deployment today. `project_not_onboarded` turns a silent failure mode into an actionable one but does not remove the onboarding step itself, which requires editing two files on two hosts and remains an explicit operator action.

## Test plan
- `tests/integration/test_store_and_mcp.py`: `start_development_task` happy path; `ambiguous_project` 409 with candidates; `project_not_onboarded`; ETA fields present with correct `eta_basis` at each sample-size tier, and `eta_seconds: null` at zero samples.
- Unit test for `ISSUE_REF_PATTERN` covering every accepted and rejected shape, including traversal attempts (`../`, absolute paths, embedded `.`).
- Unit test proving the issue snapshot text is never passed to `evaluate_task_policy` and never appears in the audited `instruction` field.
- `tests/contract/test_docs_match_the_runtime.py` and `test_openapi_document.py` stay green (no HTTP route added — `/mcp` is excluded from the OpenAPI contract and already has an nginx location).

## Definition of Done
- A ChatGPT conversation can say "resolve issue 42 of project codexbridge" and receive a task id plus a non-fabricated ETA (or an honest `null`) in the same turn.
- Ambiguous project names produce a listable disambiguation, never a guess.
- No code path allows issue-file content to influence policy evaluation.
