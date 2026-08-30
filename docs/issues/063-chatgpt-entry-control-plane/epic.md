## Objective
Give CodexBridge a second operator-facing front door — ChatGPT itself, over the existing remote MCP transport — so an operator can say "resolve issue X of project Y" (or "remind me of Z") directly in a ChatGPT conversation, get the work dispatched here, and be told when it lands, without opening MOBO.

## Product invariant
Epic #40 states "MOBO is the operator interface. CodexBridge owns orchestration." This epic keeps that invariant intact and adds a second interface with the same authority: **ChatGPT is also an operator interface**, speaking to the same orchestration core through the MCP transport that already exists. No new orchestration concept is introduced; no aggregate other than `TaskModel` gains an identity.

## Relationship to the `[mobo-dev-orch]` batch (#40–#58)
This is a sibling epic, not a duplicate. Concretely:
- #41 (generic provider contract) is delivered here as **#41a**: a Runner abstraction with Codex and Claude Code as the two real implementations, satisfying #41's headline acceptance criterion ("orchestrator code does not invoke `codex exec` directly") for real rather than vacuously — see the child issue for why that criterion is already true today with zero work and would close #41 green without touching the actual coupling. The residual #41 scope (`tasks.session_id` rename, `TaskMode` as a declared capability, capability negotiation over the wire) is left as **#41b**, filed separately and not claimed here.
- #44 (issue-to-mission workflow "from MOBO") gets a sibling MCP-facing counterpart in this epic: the same "resolve issue X of project Y" flow, reachable from ChatGPT instead of the phone.
- #51 (delivery contract) already lists "push branch" as a delivery mode; this epic implements exactly that slice — commit + push, pre-authorized in the originating request, nothing else.
- #46 (scheduler) and #50 (decision gates) are both named in the council review as depending on out-of-band notification, which does not exist anywhere in this codebase. This epic explicitly claims and closes that gap (council finding **F27**) for the "task finished" case.
- #13 (mobile event stream) is unaffected; this epic does not touch the mobile contract directly, though two of its children open new CodexBridge-side issues (`POST /api/v1/missions`, `GET /api/v1/missions/{id}/delivery`) that unblock CodexBridgeMobile issues filed alongside this one.

## Scope
- A `Runner` abstraction on the executor with `codex` and `claude` (Claude Code) implementations, declaring capabilities explicitly instead of assuming symmetry (#41a).
- One new MCP tool, `start_development_task`, that resolves a project and (optionally) a local issue reference into a submitted task, with a computed ETA and an idempotent id-resolution contract — no path ever crosses from ChatGPT to the gateway.
- A pre-authorized delivery path: the operator names a branch and an explicit push flag in the same request; the executor commits by explicit path and pushes only inside that authorization, never to `main`/`master`, never with `--force`.
- An out-of-band completion notification (email) closing council finding F27 for the "task finished" case, plus the read-side fields a ChatGPT scheduled Task needs to poll for completion.
- Google Calendar-backed reminders (`create_reminder`, `cancel_reminder`) reachable the same way.
- Two CodexBridge-side HTTP surfaces (`POST /api/v1/missions`, `GET /api/v1/missions/{id}/delivery`) that give CodexBridgeMobile its own first path to launching work and reading delivery evidence — filed here because they are a prerequisite for the CodexBridgeMobile issues, not because MOBO is this epic's audience.

## Non-goals
- Renaming any published MCP tool, HTTP field, or `TaskState` value. The Codex-named tools (`submit_codex_task`, `continue_codex_session`, `cancel_codex_task`, `approve_codex_task`) keep answering exactly as they do today.
- Introducing a `mission`/`session`/`decision` aggregate distinct from `TaskModel`. Council finding **F01** is a critical, open finding that mission/session/decision are the same row today; this epic adds columns only, and states explicitly in each child issue which of those columns are "Attempt" properties (belong to the `tasks` row as it exists) versus "Mission" properties (belong to the aggregate #43 will eventually define), so #43 does not have to reverse-engineer the mapping.
- GitHub issue ingestion (`gh:N` issue references return a typed `issue_source_unsupported` — council finding **F18**, no owner today).
- Merge to `main` or any deploy action under any authorization. Push is scoped to `development`/`feature/*` only, always.
- A generic event/push infrastructure. The notification piece explicitly does not close F27 in general — only the one "task finished, email the requester" path.

## Acceptance criteria
From ChatGPT, an authorized operator can name a project and (optionally) an issue reference, choose or default an agent engine, pre-authorize a branch and push in the same request, receive a task id and a duration estimate immediately, and later receive an email when the task reaches a terminal state — while a scheduled ChatGPT Task can poll for the same information. Reminders can be created, and cancelled, on the operator's Google Calendar the same way. No existing MCP tool, HTTP contract field, or `TaskState` value changes meaning.
