# 12 - Online Issue Flow (Jira + GitHub)

## Happy story: end-to-end traceability
When corporate traceability is required, Lia uses Jira + GitHub together. Every task is traceable from planning to commit.

## What is yours (programmer)
- Confirm target Jira project and GitHub repo.
- Confirm online/public mode.
- Review and approve issue content before creation.

## What is the agent's
- Build complete issue bodies (no empty fields).
- Create/link Jira and GitHub issues when requested.
- Respect `AGENTS.md` content guard rules.

## Step by step
1. Confirm target systems.
2. Generate local docs in `docs/issues/`.
3. Create Jira issue.
4. Create GitHub issue.
5. Cross-link Jira ↔ GitHub.
6. Propagate `work_id` to docs, handoff, and commits.

## Operational tip
If target repo has `jkctl.py`, prefer it for issue/PR workflow operations.
