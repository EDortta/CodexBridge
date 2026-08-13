# Agent Operational Limits

## Metadata
- work_id: WK-20260504-low-token-contract-v2
- date: 2026-05-04
- owner: <maintainer>
- limits_ready: no

This file defines hard boundaries for agent execution.

## Install-Time Role

In this source kit, this file defines default reusable boundaries.
When copied into a target project, the programmer must replace or extend these limits with project-specific boundaries and set `limits_ready: yes` only after they are accurate.

If this file is missing or not ready in a target project, agents must stop implementation and ask the programmer to fill it.

## Allowed
- Implement work explicitly requested by the user.
- Perform necessary supporting refactors required for safe implementation/testing.
- Update tests, docs, and issue artifacts directly related to requested work.
- Use official migration workflows when persistence models change.

## Not Allowed
- Unrelated refactors or speculative improvements.
- Architecture expansion not required by the requested outcome.
- Silent contract changes (API/schema/interface) without explicit declaration.
- Creating empty or low-content Jira/GitHub Issue/PR artifacts.
- Marking issues as solved/finished without objective implementation evidence.

## Branch and Workflow Constraints
- Never start implementation on `main`/`master`.
- Create/switch branch only with explicit user permission.
- Prefer `jkctl.py` for issue/PR automation when available.
- At each stage end, run session-close workflow (`.docs/workflows/session-close.md`), update `handoff.md`, and record lessons in `docs/napkin-lessons.md`.

## Security and Secrets
- Never expose secrets/tokens/credentials in logs, code, or issue bodies.
- Never commit `.credentials`, `.env*`, token files, or equivalent secrets.

## Scope Authority
- Any request outside these boundaries must be explicitly flagged.
- Execution outside these boundaries requires explicit human approval first.
- Edits to this source kit's governance gates/templates require explicit human approval as a boundary update.
