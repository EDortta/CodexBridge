# Parallel agents with git worktrees

> One worktree per `work_id`, so two agents never step on each other.

## Why

The kit coordinates agents **sequentially by convention** — `handoff.md`,
per-epic `RESUME.md`, `work_id`, and one branch per issue. That keeps *history*
clean but gives **no physical isolation**: if two agents (claude-code, Codex,
Cursor) work the same checkout, their files, branch, builds and service ports
collide.

`git worktree` fixes this at the git level: it creates a **second working
directory** linked to the same `.git`, each with its own branch and files. Run
`awt new WK-… ` and an agent gets its own folder, branch, ports, `.venv`, and
(optionally) container.

## The three questions, answered

1. **Does it work in Codex / Cursor too?** Yes. `git worktree` is native to git
   — it does not depend on any agent. Each tool simply **opens the worktree
   folder** and works normally; the isolation comes from git. Point Codex at
   `../repo--WK-x` and Cursor at `../repo--WK-y` and they never collide. The only
   difference between tools is which folder you open. (Note: Cursor ignores
   chain-loaded rule files, so `.cursorrules` must be self-contained — see
   `docs/napkin-lessons.md`.)
2. **Do we emulate it via the kit?** There is nothing to emulate in code —
   worktree is native. The kit's job is the **convention layer**: one worktree
   per `work_id`, tied to the existing branch-per-issue + `work_id` + `handoff.md`
   discipline, with `agent-status.json` as the registry of who holds which
   worktree/branch/ports.
3. **How does it apply professionally here?** Real parallelism without collision:
   each agent/issue in its own worktree with isolated `.venv`, `.env`, ports and
   container. This is the same pattern the house already trusts for automation —
   `jkctl auto-review-prs` runs each PR in a `git worktree add -B …` (see
   `README-jkctl/07-autofix-pr.md`) — generalized to interactive agents.

## The tool: `awt` (`scripts/agent-worktree.sh`)

`awt` **is** `scripts/agent-worktree.sh` — the short name is a symlink on your
PATH. Install it once (the script self-installs; no copy of secrets, no build):

```bash
./scripts/agent-worktree.sh install        # symlink → ~/.local/bin/awt
# override target dir with --bin <dir> or AWT_BIN_DIR; awt uninstall removes it
```

If you installed the **AI-GovernanceKit**, it runs this for you. Installing only
the AI-Agents kit standalone? Run the line above yourself. Until then, call the
script by path: `./scripts/agent-worktree.sh new <work_id> …`.

Once installed:

```bash
awt new <work_id> [--branch <b>] [--base <ref>] [--docker]   # create + isolate
awt list                                                     # worktrees + holders
awt ports <work_id>                                          # allocated ports
awt rm <work_id> [--force]                                   # tear down (keeps branch)
```

- Worktree path: `../<repo>--<work_id>`; default branch `feature/<work_id>`,
  base `development` (falls back to `main`).
- **Deterministic ports** from the `work_id` (offset `100…890`) written into the
  worktree `.env` (`GATEWAY_PORT`, `DB_PORT`), so two worktrees never clash and a
  reconnecting agent gets the same ports.
- **Credentials**: symlinks the central store (`~/.config/credentials/personal`)
  into `.credentials/store` — never copies secrets.
- **`.venv`**: a private virtualenv per Python worktree.
- Refuses protected branches and existing worktrees; `rm` keeps the
  `feature/<work_id>` branch for its PR.

## Isolation matrix

| Concern | Per worktree? | How |
|---|---|---|
| Files / branch | ✅ | native `git worktree` |
| Service ports (8000/5432/…) | ✅ | deterministic offset → `.env` |
| `.venv` / deps | ✅ | private virtualenv (or the dev container) |
| `.env` / credentials | ✅ | generated `.env` + symlinked central store |
| Docker dev container | ✅ | bind-mount, project name `awt-<id>` |
| Singleton daemons (AI-hub `:9400`) | ❌ shared | all worktrees point at the one instance |

## Docker per worktree — no source `COPY`

The container image (`templates/Dockerfile.dev`) is built **once** and bakes only
dependencies — it never `COPY`s source. At runtime
(`templates/docker-compose.worktree.yml`) the worktree directory is **bind-mounted**
at `/app`. Day-to-day cycle:

1. Implement the issue (edit files in the worktree).
2. Transpile/build **inside the running container** (`docker exec` / compose run).
3. `docker compose -p awt-<id> restart` — the change is live. **No image rebuild.**

Rebuild the image only when *dependencies* change.

## Convention (ties into the rest of the kit)

- One worktree ⇔ one `work_id` ⇔ one `feature/<work_id>` branch.
- Record it in `agent-status.json` (`worktree`, `branch`, `ports` fields) so other
  agents see who holds what.
- Use `handoff.md` / per-epic `RESUME.md` and `session-close.md` as usual — the
  worktree adds physical isolation; the markdown state still carries intent.
- When the issue merges, `awt rm <work_id>` cleans the worktree; the branch lives
  on in its PR.
