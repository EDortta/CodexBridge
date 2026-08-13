# Shared Contract References

This file is an index of shared rules to avoid duplication across role files.

Canonical source: `/AGENTS.md`

Specialized roles and precedence (when agents disagree):

- [governance-precedence.md](./governance-precedence.md) — compliance, security, and delivery conflict handling
- [privacy-compliance.md](./privacy-compliance.md) — GDPR/LGPD-oriented privacy requirements and review checklist

Low-token load rule:
- Start with `/AGENTS.md`, `docs/software-overview.md`, and `docs/limits.md`.
- Load role and workflow files only when relevant to the task.
- Do not load issue history, handoff, or lessons unless resuming active work.

Core files:
- [programmer.md](./programmer.md) — implementation workflow, branch rules, tests, contracts
- [reviewer.md](./reviewer.md) — PR/code review workflow
- [issue-automation.md](./issue-automation.md) — Jira/GitHub/local issue creation
- [security.md](./security.md) — runtime security review
- [privacy-compliance.md](./privacy-compliance.md) — personal data requirements
- [communication.md](./communication.md) — applying user profile preferences (load only when `~/.config/USER.md` is present)
- [../workflows/session-restore.md](../workflows/session-restore.md) — active work resume
- [../workflows/session-close.md](../workflows/session-close.md) — handoff/resume closeout
- [../workflows/typescript-audit.md](../workflows/typescript-audit.md) — on-demand TypeScript quality audit (whole-codebase, not PR-level)

If any role file conflicts with `AGENTS.md`, follow `AGENTS.md`.
