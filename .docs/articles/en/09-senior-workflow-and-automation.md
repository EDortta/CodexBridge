# 09 - Senior Workflow and Automation

## Happy story: scalable consistency
Lia became team reference by standardizing this kit across repositories and introducing a repeatable CLI routine that any agent or programmer follows without thinking.

## Senior focus
- Cross-repo governance standards
- Automated quality gates with GovernanceKit CLI
- Reliable handoff culture that survives context resets

## The CLI daily loop

Three commands cover the full session lifecycle:

**`governancekit resume`** — run at the start of every session. Prints the active work_id, branch, status, and the exact next step from RESUME.md. Both agents and humans run this before touching code.

**`governancekit doctor`** — run before coding. Validates the scaffold: required files, readiness flags, active issue, resume next step, and tracked secret paths. Fix every `[FAIL]` before starting. `[HINT]` lines (like a stale code map) are advisory — address them when convenient.

**`governancekit map`** — run after significant changes and commit the result. Regenerates `docs/codemap.md`, the persistent code index that agents read at session start instead of scanning files.

```bash
# Start of session
governancekit resume

# Before touching code
governancekit doctor

# After a batch of changes
governancekit map
git add docs/codemap.md
git commit -m "refresh codemap"
```

## CI integration

Add `doctor` to your pipeline for machine-readable validation:

```bash
governancekit doctor --json | jq '.ok'
```

Exit code is 1 if any non-advisory check fails — use it as a merge gate.

## Scaling to a team

- Require `governancekit doctor` to pass in CI before any merge.
- Commit `docs/codemap.md` with the code — treat it as a first-class artifact, not a generated file to ignore.
- Run `resume` in your prompt starter: *"Run `governancekit resume` and use the output to orient yourself before planning."*
- Review `docs/napkin-lessons.md` in team retrospectives — it captures non-obvious decisions.
- One `docs/limits.md` per repo, reviewed quarterly by the team lead.

## Prompt starter for senior sessions
"Run `governancekit resume`. Then read AGENTS.md, software-overview.md, and limits.md. Report what you find and propose a focused plan before writing any code."

## Result
Agents arrive with context. Programmers spend no time re-explaining the project. The scaffold enforces discipline without extra effort from anyone.
