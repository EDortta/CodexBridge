# Epic #63 — ChatGPT-facing conversational control plane

Sibling epic to #40 `[mobo-dev-orch]`. Where #40 makes CodexBridgeMobile the
orchestration client, this epic makes ChatGPT (over the existing remote MCP
transport) a second, equally-authorized operator interface — same
`TaskModel`, same policy gates, no new aggregate.

Filed 2026-08-30 (work_id `WK-20260830-chatgpt-entry-provider-and-delivery`).

## Issues

| # | Title | Slice of |
|---|---|---|
| [#64](https://github.com/EDortta/CodexBridge/issues/64) | Runner interface in the agent process, with Codex and Claude Code | #41a |
| [#65](https://github.com/EDortta/CodexBridge/issues/65) | `start_development_task`: resolve an issue of a project from ChatGPT | sibling of #44 |
| [#66](https://github.com/EDortta/CodexBridge/issues/66) | Delivery with pre-authorized commit and push | slice of #51 |
| [#67](https://github.com/EDortta/CodexBridge/issues/67) | Duration estimate (ETA) on task submission | — |
| [#68](https://github.com/EDortta/CodexBridge/issues/68) | `POST /api/v1/missions`: create a mission from an issue | unblocks CodexBridgeMobile |
| [#69](https://github.com/EDortta/CodexBridge/issues/69) | `GET /api/v1/missions/{id}/delivery`: delivery evidence | unblocks CodexBridgeMobile |
| [#70](https://github.com/EDortta/CodexBridge/issues/70) | Out-of-band completion notification by email | claims F27 |
| [#71](https://github.com/EDortta/CodexBridge/issues/71) | Reminders on Google Calendar (MCP) | — |
| [#72](https://github.com/EDortta/CodexBridge/issues/72) | REST surface for reminders | reuses #71 |

## Cross-repo

CodexBridgeMobile issues filed alongside this epic depend on #68, #69, #70,
#72 (and, unrelated to this epic, on the still-open #13 for a true event
stream). See `EDortta/CodexBridgeMobile` issues #54–#60.

## Status

Issues opened on GitHub 2026-08-30. Implementation of the PR sequence
(protocol/schema → runner abstraction → Claude Code runner → git delivery →
MCP tool → reminders) is tracked per-issue; see each issue's own body for its
test plan and Definition of Done. No council review has run yet — required
before any delivery commit per `.docs/agents/council.md`.
