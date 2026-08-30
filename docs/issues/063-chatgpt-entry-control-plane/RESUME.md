# RESUME — WK-20260830-chatgpt-entry-provider-and-delivery (epic #63)

- work_id: WK-20260830-chatgpt-entry-provider-and-delivery
- data: 2026-08-30
- branch: `development` (pushed, `650e37b`; nothing on `main` yet)

## Next Step (DO THIS FIRST)

Ask the operator whether they want to close the remaining gap on their "any
project, no registration" request: the gateway's own `resolve_project_reference`
(`gateway/app/services/store.py`) still requires a project to exist in its
`registry.json`-backed DB before ChatGPT can name it at all — the executor's
new `auto_project_root` (this session) only removed the SECOND, executor-side
registration step, not this first one. Closing it for real needs a new
gateway<->executor protocol message (ask the connected executor "do you know
this project?"), a distinct, bigger change on a live remote host (`frida`),
not yet scoped or approved. See `docs/threat-model.md`'s "Raiz de
auto-descoberta do executor" section and `docs/napkin-lessons.md`'s
2026-08-30 "dois portões, não um" entry.

## Current state

- Etapa 1 (conversational entry + delivery) and Etapa 3 (Google Calendar
  reminders): delivered, pushed, merged to `main` earlier this session.
- Etapa 2 (email notification, issue #70): implemented, pushed, operator
  confirmed the smoke-test email arrived correctly. NOT yet merged to `main`.
- Fase C (project-access discovery/registration tools): delivered, pushed.
  `scripts/discover_projects.py` + `scripts/register_projects.py`, diff-only,
  never applies. NOT yet run for real against `frida`/`devel3`'s live files.
- `auto_project_root` (this session, devel3-side only): delivered, pushed.
  `CODEX_BRIDGE_AGENT_AUTO_PROJECT_ROOT`, opt-in, unset by default. Lets the
  executor accept any real git repo under a configured root without a
  per-project entry in `allowed_projects_file` — but does NOT by itself
  deliver "mention any project, it just works" from ChatGPT (see Next Step).
- 746 tests passing (`pytest tests/unit tests/integration tests/contract -q`;
  one known machine-load-sensitive timing flake in `test_oauth_authorize.py`,
  confirmed unrelated, passes in isolation).

## Watch for

A background fork mid-session went outside its assigned scope and edited
several project files autonomously before being stopped — see
`docs/napkin-lessons.md`'s 2026-08-30 entry "a background fork given a
narrow read-only task instead resumed the entire session plan" before
spawning more forks in a session with a large pending plan already in
context.
