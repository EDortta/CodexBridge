# Dev-Workflow Integration (Session-Close Hook)

Use this pattern when your project has a `dev-workflow` command runner.

## Goal

Automatically trigger session-close at the end of each stage so context is never lost.

## Recommended behavior

At each stage end, run steps equivalent to:
1. update `handoff.md`
2. update `docs/napkin-lessons.md`
3. validate `work_id` linkage across planning docs and commit message

## Example command sequence

```bash
# Example only; adapt to your tooling
./dev-workflow stage-finish --work-id "WK-20260420-auth-reset"
./dev-workflow session-close --work-id "WK-20260420-auth-reset"
```

## Minimum acceptance for automation

- Fails if `handoff.md` has no new entry for the active `work_id`
- Fails if no lesson was added to `docs/napkin-lessons.md`
- Warns if commit message does not include active `work_id`

## Running agents in parallel

When more than one agent works the same project at once, give each its own git
worktree (one per `work_id`) so files, branches, builds and ports never collide.
See [parallel-worktrees.md](parallel-worktrees.md) and the `awt` helper
(`scripts/agent-worktree.sh`).

## Backing up a project that has no remote

A project whose history lives on one disk has no versioned backup — Syncthing
replicating `.git/` replicates corruption too. When a third-party host is not the
right answer (sensitive data, personal project) and you already run a server, a
bare repo there closes the gap. See [git-bare-remote.md](git-bare-remote.md) and
the `gbr` helper (`scripts/git-bare-remote.sh`).

`gbr status` and `gbr scan` are local and read-only — an agent may run them.
`gbr init` touches a remote server and is **operator-only**; the script itself
refuses to run without a terminal.
