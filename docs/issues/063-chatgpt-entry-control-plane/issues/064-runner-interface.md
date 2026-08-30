Parent: #63
Related: #41 (this issue delivers as **#41a**; residual #41 scope becomes #41b — see below)

## Objective
Introduce a `Runner` abstraction in the executor process (`agent/codex_bridge_agent/`) with two real implementations — Codex CLI and Claude Code — so a dispatched task can name an `engine` instead of the executor being hardwired to `codex exec`.

## Why this is #41a, not #41 itself
`grep -rn codex gateway/ --include=*.py` returns no CLI invocation today: the orchestrator already never invokes `codex exec` directly, because that invocation lives entirely in the executor process. #41's headline acceptance criterion is already true with zero work. Closing #41 with only this change would leave it green without touching the actual coupling: `tasks.session_id` is Codex-flavored, `continue_session_id` assumes one resume shape, and `TaskMode` is a closed five-value enum treated as if every provider supports the same five operations. Shipping this as a **sibling** (`#41a`) keeps this slice mergeable now — additive columns only, no rename, no published surface touched — while leaving `tasks.session_id`'s rename, `TaskMode` as a declared capability, and wire-level capability negotiation for **#41b**, which is not started by this issue.

## Scope
- New package `agent/codex_bridge_agent/runners/`: `base.py` (the `Runner` protocol + `RunnerCapabilities`), `codex.py` (today's `CodexRunner`, moved without behavior change), `claude.py` (new), `registry.py`, `pool.py`.
- `agent/codex_bridge_agent/codex_runner.py` stays as a re-export shim so existing imports (`tests/unit/test_codex_runner.py`, `tests/integration/test_codex_runner_real_process.py`) do not change.
- `shared/protocol.py` gains an `AgentEngine` enum (`codex`, `claude`, plus `cursor-agent`/`gemini`/`opencode`/`aider` registered as known-but-`implemented=False`). Field name is **`engine`**, not `agent` — "agent" already names four different things in this codebase (`/agent/ws`, `codex-bridge-agent`, `AgentEnvelope`, `AgentMessageType`).
- `SubmitTaskRequest.engine: AgentEngine = AgentEngine.CODEX` — default preserves current behavior for every existing caller.

## Requirements
- `RunnerCapabilities` declares, per provider: `supports_resume`, `resume_token_kind`, `supports_sandbox`, `sandbox_modes`, **`sandbox_enforced_by`** (`"os-sandbox"` for Codex, `"provider-flags"` for Claude Code — these are not equivalent and must not be presented as if they were), `supports_pause`, `supports_restart`, `streams_events`, `reports_cost`, `cost_class`, `env_allowlist`.
- `is_known(task_id)` keeps its exact current contract — the ghost-task branch in `gateway/app/main.py:handle_task_ack` (issue #17) depends on it, and this issue does not change that semantics, only relocates the implementation behind the pool.
- `ClaudeRunner`: fresh run is `claude -p --output-format stream-json --verbose --permission-mode <mode>` (NOT `--output-format json`, which returns one blob at the end and gives no incremental log — the existing `pump()` loop needs the NDJSON-per-event shape `stream-json` provides, same as `codex exec --json`). Resume uses `--resume <id>`; `--session-id <uuid>` lets the runner assign the id up front instead of scraping it from output events after the fact (the way Codex's `_find_session_id` must). Confirm session-id extraction against the installed CLI before merging — issues #32/#33 exist because an equivalent assumption about Codex was made once without that confirmation.
- Sandbox mapping for Claude Code: `read-only` → `--permission-mode plan` plus `--disallowedTools "Edit,Write,NotebookEdit,Bash"`; `workspace-write` → `--permission-mode acceptEdits`. The full-access mode is absent from the allowed set by construction, mirroring `_ALLOWED_SANDBOX_MODES` in the Codex runner.
- Environment custody: each runner declares its own `env_allowlist` (Claude Code: `HOME, PATH, LANG, LC_ALL, CLAUDE_CONFIG_DIR, ANTHROPIC_API_KEY`; Codex keeps its existing set) and `filtered_environment` is called with the runner's own allowlist, never a shared module constant. No engine's process ever receives another engine's credential variable.
- `agent/codex_bridge_agent/service.py`'s four control branches (cancel/pause/resume/restart) route through a `RunnerPool` that dispatches to whichever runner owns a given `task_id`; the branches themselves stay textually unchanged.
- An unknown or unimplemented engine returns a typed `engine_not_implemented:<engine>` result — never an `AttributeError`, never a silent fallback to Codex.
- Deploy note: Claude Code needs `~/.claude` writable. `deploy/systemd/codex-bridge-agent.service` currently sets `ProtectHome=read-only` with `ReadWritePaths` scoped to `~/.codex` only — this relaxation must be named explicitly in the PR body, not buried in a feature change (a hardening control silently loosened is how controls get lost). Note this machine's live agent unit already runs as `esteban` without `ProtectHome`; only the `deploy/systemd/` template for `frida` needs the change.

## ARO
- **F07** (already true acceptance criterion): addressed directly — see "Why this is #41a" above.
- **F29** (cost accounting circularity): `cost_class` is declared on `RunnerCapabilities` from day one, per the council's recommendation to move it out of #54 and into the provider descriptor.
- **F08** (provider secret custody): addressed by per-runner `env_allowlist`, tested explicitly (no engine's allowlist contains another engine's variable).
- Risk accepted: Claude Code has no OS-level sandbox equivalent to Codex's `-s read-only`; containment is a deny-tools list, which is more fragile. This is exactly why `sandbox_enforced_by` exists as an honest field rather than a fiction of parity.
- Open question: whether `--session-id` assignment behaves as documented on the installed CLI version — must be verified live before merge, not assumed.

## Test plan
- Extend `tests/unit/test_codex_runner.py`: `CodexRunner` satisfies the `Runner` protocol; declares `sandbox_enforced_by="os-sandbox"`.
- Extend `tests/unit/test_agent_service.py`: engine routing dispatches correctly; unknown engine returns the typed error; the `known`/ghost-task semantics from issue #17 still hold with two runners registered in the pool.
- New `tests/unit/test_runner_registry.py`: every registered engine declares complete capabilities; no engine's `env_allowlist` contains another engine's variable; the full-access sandbox mode appears in no built command for any engine.
- New `tests/unit/test_claude_runner.py`: `_build_command` for fresh vs. resume; NDJSON `stream-json` parsing extracts session id and final result; the read-only mapping emits the deny-tools flags; a fake stream drives `send_log` correctly.
- `python3 -m pytest tests/unit tests/integration -q` must stay green with the shim in place (no import changes required in existing tests).

## Definition of Done
- `codex` behavior is unchanged (verified by the existing Codex test suite passing unmodified through the shim).
- `claude` engine runs a real task end-to-end against a throwaway repository, producing valid `task.log`/`task.result` frames.
- `docs/protocol.md` and `docs/codemap.md` updated (`governancekit map` re-run).
- The systemd hardening relaxation is called out explicitly in the PR description.
