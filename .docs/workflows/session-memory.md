# Session Memory — artefatos que atravessam a sessão

Which files carry state between sessions, what each one owes, and the cross-project
activity registry that says who is alive on this machine.

`./session-restore.md` and `./session-close.md` are the *procedure* — what to do when a
session opens and closes. This file is the *artifact contract*: what those files must
contain for the procedure to mean anything.

Load this file when opening or closing a session, or when writing to `handoff.md`,
`RESUME.md` or `docs/napkin-lessons.md`.
If this file conflicts with `/AGENTS.md`, follow `/AGENTS.md`.

## 8. Session Memory

Use session memory only for active work:
- `docs/issues/<epic>/RESUME.md`
- `handoff.md`
- current issue/task file
- `docs/napkin-lessons.md`

`RESUME.md` is the source of truth for the immediate next action and must contain exactly one clear `Next Step (DO THIS FIRST)`.

At session close, update:
- `handoff.md`
- active `RESUME.md`
- `docs/napkin-lessons.md`

Planning/development docs must include:
- `work_id: WK-YYYYMMDD-<short-slug>`
- `date: YYYY-MM-DD`

### 8a. Activity monitor (cross-project, opt-in by presence)

Cross-project session tracking, in the XDG state directory:

```
${XDG_STATE_HOME:-$HOME/.local/state}/ai-agents/agent-status.json   # live sessions
${XDG_STATE_HOME:-$HOME/.local/state}/ai-agents/agent-log.md        # session log
```

**Only applies when `agent-status.json` already exists.** If it does not, skip this
section entirely and do not create it — the feature is opt-in by the presence of the
file, so a machine without the monitor is never blocked by it and no path has to be
configured anywhere. Never invent a different location: an agent writing its status
where the monitor does not look is worse than not writing it at all.

**On session start** — read the file, merge your entry, write it back:

```json
{"sessions": [
  {"agent": "<claude-code|codex|cursor>", "project": "<short, stable project path>",
   "task": "<one sentence: what you are doing right now>",
   "started": "<ISO-8601 UTC>", "heartbeat": "<ISO-8601 UTC>"}
]}
```

- `agent` is exactly `claude-code`, `codex` or `cursor`.
- Read first, merge, then write — **never overwrite another agent's entry**.
- Update `task` and `heartbeat` when your focus changes significantly.
- Working in a git worktree: add `worktree`, `branch` and `ports` so other agents
  see who holds which worktree, branch and ports. Omit them in a main checkout.

**On session end** — remove your entry from `agent-status.json` (a stale entry
misleads the monitor), then append one block to `agent-log.md` beside it when the
session did meaningful work:

```
## YYYY-MM-DD HH:MM · <agent> · <project>
<what was done — 1 to 3 lines>

**Next:** <one concrete next step, or —>

---
```

Append at the **bottom**; never edit an existing entry. The `**Next:**` line is
required (use `—` when nothing is pending). This log complements the per-project
session-close (`handoff.md`, `docs/napkin-lessons.md`); it does not replace it.
