# Session-Close Workflow

Run this at the end of each implementation stage/session.

## Required steps

1. Confirm active `work_id` and date.
2. Update `handoff.md` with status, next steps, blockers, changed files, and checks/tests.
3. Add at least one short lesson to `docs/napkin-lessons.md`.
4. Update active `docs/issues/<epic>/RESUME.md`.
5. Ensure `RESUME.md` contains exactly one `Next Step (DO THIS FIRST)`.
6. Ensure planning docs and commit plan use the same `work_id`.
7. **State what stays open for the next day** (`AGENTS.md` §1c). Run
   `governancekit --root <project> concurrency --closing` and record, in `handoff.md`,
   one line per branch/worktree that survives this session saying **what it holds**.
   A front left open without that line is a front nobody can pick up tomorrow.
   Worktrees reported as holding nothing unmerged should be removed now, not carried.
8. If automation exists (for example `session-close` in dev-workflow), execute it.

## Resume Requirements

`RESUME.md` must be short and operational:
- max roughly 50 lines
- no historical narrative
- no duplicated issue description
- only current state, changed files, checks, and next action

## Optional automation

If your repository has a `dev-workflow` command layer, see:
- `.docs/workflows/dev-workflow-integration.md`

## Output quality bar

- Handoff must be enough for another programmer to continue without chat history.
- Lessons must be specific, not generic motivation.
- Work identifier linkage must be explicit and traceable.
