# Git Delivery — branch, commit, PR, merge, deploy

Everything the agent does that reaches a forge, a remote, or a production host: how a
branch may be named, what a commit of record requires, how `development` relates to
`main`, and the one-way door in front of deploy.

`./session-close.md` covers *how to hand the work back*; this file covers *what the git
actions themselves are allowed to be*.

Load this file before creating a branch, an issue or PR, a commit, a merge to `main`, or
any action that reaches a remote or a production host.
If this file conflicts with `/AGENTS.md`, follow `/AGENTS.md`.

## 6. GitHub/Jira Guard

Prefer `jkctl.py` for issue/PR workflows when present.

Never create an issue or PR with empty or placeholder-only title/body.
Never run:
- `gh issue create` without `--body` or `--body-file`
- `gh pr create` without `--body` or `--body-file`

Issue bodies must include context, objective, scope, ARO, test plan, and DoD.
PR bodies must include summary, related issue, changed areas, tests, risks/rollback, security impact, and validation checklist.

---

## 7. Branch, Commit, Artifacts

Branch naming:
- Jira: `feature/<JIRA-KEY>/<short-description>`
- GitHub: `feature/gh-<issue-number>/<short-description>`
- undercover/local: `feature/uc-<NNN>/<short-description>`

#### Allowed characters (MANDATORY)

Branch names must use only plain ASCII in the class `[a-z0-9/_-]`
(uppercase permitted solely inside an issue/Jira key, e.g. `UBR-1027`).
The final name must match `^[a-zA-Z0-9/_-]+$`.

[PROHIBITED] in a branch name — they silently break tooling, prompts, and refs:
- quotes of any kind (`"` `'` `` ` ``), even from a shell-escaping mistake;
- whitespace (spaces, tabs);
- shell/glob metacharacters: `$ & * ? ! ; | < > ( ) { } [ ] \ ^ ~ : @ = + , #`
  and a leading `-`;
- accented or non-ASCII letters and any Unicode symbol, homoglyph, or
  invisible character;
- `..`, a trailing `/`, a trailing `.lock`, or a trailing `.` (invalid git refs).

[MANDATORY] When deriving a branch slug from an issue title/slug: transliterate
to ASCII, lowercase, replace every disallowed character with `-`, collapse
repeats, strip leading/trailing `-`. Verify the final name matches
`^[a-zA-Z0-9/_-]+$` **before** `git checkout -b` (or `git worktree add -b`).
Never pass an issue title verbatim to git branch/checkout. An invalid name →
stop and report; do not create the branch.

Rules:
- Obtain explicit human permission before creating a branch.
- Before creating or switching to a **second** concurrent branch/worktree, apply
  `/AGENTS.md` §1c: report what is already open and wait for the operator's
  authorization.
- Create/switch branch before first code change.
- Work only on that branch.
- Default PR base is `development` unless explicitly required otherwise.
- Commit only after applicable checks are green, unless impossible and documented.
- [MANDATORY] No **commit de entrega** — o que fecha o trabalho antes de devolver ao
  operador — se o diff toca contrato compartilhado, **acrescenta** `not validated:` ou varre
  muitos arquivos: rode e registre o council de `../agents/council.md` (depois do
  `../agents/reviewer.md`, nunca no lugar dele). `governancekit --root <projeto> council`; sem
  registro o `doctor` reprova, e o `pre-commit` também onde `install-hooks` rodou.
- Do not commit caches, local runtime data, backups, credentials, `.env*`, or token files.

#### `development` vs `main` (branch consolidation)

- `development` is the **working branch** — feature/fix branches land here and
  work accumulates across cycles. **`main` is the consolidated/stable branch.**
- **Stay on `development` most of the time.** Consolidating into `main` is a
  deliberate, cycle-end act — not something done on every change. Let several
  cycles close on `development` first.
- **On a push request, the agent asks whether to also merge to `main`.** Default
  is **no** (push `development`, keep `main` as-is). Merge to `main` only on an
  explicit "yes". Merging to `main` never implies deploy (deploy stays gated,
  §7b).

### 7b. Deploy autônomo é proibido [MANDATORY]

Nunca executar deploy, restart de serviço em host remoto, push para produção, ou
qualquer ação que afete um ambiente de produção **sem aprovação explícita do
operador (`{{OPERATOR_NAME}}`)**.

Inclui — sem se limitar a:
- scripts de deploy com `--yes`, `--force`, `--skip-confirm` ou equivalentes
- `ssh` para host de produção para reiniciar serviço
- `docker compose up` (ou equivalente) em host remoto
- `git push` forçado para branch de produção

O fluxo correto depois do commit é sempre: **parar, reportar, aguardar aprovação.**
"Implementar a issue" **nunca inclui deploy** — deploy é um passo separado e gateado
que exige um humano. Merge para `main` também não implica deploy (§7).

Esta regra existe por incidente real: um agente rodou `deploy.sh --yes`
automaticamente depois de um commit e empurrou para produção sem autorização.
