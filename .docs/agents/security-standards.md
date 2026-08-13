# Security Standards

Concrete, verifiable security rules for any code created or changed in a project
that uses this kit — agents and humans alike. This is the **minimum** bar, not a
project-specific checklist.

`./security.md` covers *how to review* (categories, classification, output).
This file covers *what must be true* in the delivered code. When a rule conflicts
with "make it work fast in dev", the rule wins. Every rule below was distilled
from real vulnerabilities found in production; see **Provenance** at the end.

If this file conflicts with `/AGENTS.md`, follow `/AGENTS.md`.

## 1. Secrets and credentials

- No secret (password, API key, token, private key) in code, docs, design docs,
  examples or git history. Secrets live **only** in `.credentials/` or `.env`,
  both gitignored from the first commit.
- **Fail-fast:** a service refuses to start without its required secrets
  (`JWT_SECRET`, cipher keys, allowed origins…). No embedded default "to run in
  dev" — dev also sets env.
- **No secret or personal identifier as a default in a tracked file.** Read it
  from env or `~/.config` and fail when unset; never
  `os.getenv("X") or "dev-secret"`. A fallback secret is a shipped secret.
- Key material (`*.pem *.key *.ppk *.pfx *.ovpn id_rsa id_ed25519 *.env* .credentials`)
  is gitignored **from the first commit** and written `chmod 600` (dirs `700`) —
  not fixed afterwards.
- No default user password. Provisioning generates a random per-user password
  with forced change on first access.
- Persisted credentials are encrypted at rest and **masked** in any screen, log
  or dump.
- Secret leaked into the repo: immediate containment (`git rm --cached` +
  `.gitignore`) and **rotation as an explicit operator task**. History rewrite
  only with human approval.
- **A database dump is credential material.** `pg_dump`/`mysqldump` output carries
  password/key hashes, tokens and audit rows — treat it exactly like a key file:
  gitignored **before** it is created, never after. The window between "I made a
  backup" and "I remembered to ignore it" is one `git add -A` wide, and that is
  how it gets committed.
- **`git add -A` is a weapon in a repo whose `.gitignore` does not yet cover the
  artifact you just produced.** Before committing, read `git status` — or add
  explicit paths. Generating an artifact and staging everything in the same breath
  is the mechanism, not the accident.

## 2. Logs and personal data (privacy)

- Never log a token, password, national ID, e-mail, phone or auth payload. Log
  opaque identifiers (user id, request id) — the log records *what* happened,
  not *who* the person is.
- **Redact before logging:** strip `Authorization`, tokens, passwords and PII
  (CPF, phone, e-mail) from any log line. Never log a full request URL or body
  that can carry credentials. Peer-supplied text is logged as structured fields,
  never echoed verbatim.
- **No secret or token in a URL or query string** — it leaks to access logs,
  proxies, browser history and referrers. Carry it in a header or POST body.
- **PII never committed and never stored plaintext in a synced directory**
  (`~/Sync`, cloud-backed folders). PII at rest is encrypted with a written
  retention policy before production. No PII in filenames.
- **Anti-reintroduction gate:** the distributed contract (`AGENTS.md`, shared
  docs) is scanned against a configured operator-name / PII regex, not just
  unfilled `{{…}}` slots (LGPD Art. 46). Wire it as a pre-commit / CI check.
- 500 errors never expose a stack trace or internal detail outside dev.
- Every personal-data field collected has a written purpose and retention policy
  before production. See `./privacy-compliance.md`.

## 3. Network and service exposure

- Services bind to **loopback by default**. External exposure is explicit and
  named opt-in (e.g. `allow_nonlocal_host`) — never `0.0.0.0` for convenience.
  Kit compose/worktree templates bind `127.0.0.1` and ship **no trivial default
  datastore/admin credentials** — generate a random per-project/per-worktree one.
- Flags that disable protections (e.g. `--no-sandbox`) are never the default;
  always explicit opt-in with a name that announces the risk.
- Before reusing an existing port/endpoint/process, **validate the owner**
  (protocol handshake + PID/cmdline). Do not assume the port is yours.
- Internal APIs and WebSockets: always authenticate (key in a **header**, never
  in the URL) and refuse unencrypted transport outside localhost. A localhost
  daemon also validates the `Host` header against an allowlist (defence against
  DNS rebinding) in addition to its bearer token.
- **Never disable certificate verification** (`verify=False`,
  `rejectUnauthorized:false`, `CURLOPT_SSL_VERIFYPEER=0`, `sslmode=disable`) on a
  channel carrying secrets, PII or an agent token; a dev exception is a named,
  non-default opt-in. SSH/SCP keep host-key verification — no
  `StrictHostKeyChecking=no`.

## 4. Authentication and authorization

- Every command interface (bot, C&C, admin panel, webhook) requires
  **authorization per action**, not just authentication of the caller.
- **Every state-mutating or data-reading route declares an auth guard** — a
  missing guard fails review, it is not default-allow. Mock/demo auth is gated to
  DEV and excluded from production bundles.
- **Inbound webhooks verify the provider signature / HMAC before any write** —
  unsigned → 401.
- **No self-mutable authorization fields:** `PATCH /users/me` never accepts
  `role`, `permissions` or `isAdmin` from the request body.
- Approval flows are **fail-closed**: without explicit, verifiable operator
  confirmation the answer is NO — and an empty policy or a failed config-load
  also fails closed, never open.
- Sensitive operations (financial data, payment keys, profile changes) are
  validated and authorized **on the backend**; the client is never the last line.
- **All auth-sensitive endpoints** (login, forgot/reset-password, token verify)
  have rate limiting and progressive lockout with state shared across instances
  (e.g. Redis) — not local memory. Responses and timing are **uniform** for
  existing vs non-existing accounts (no user enumeration).
- A minimum password policy (documented length/complexity) is enforced — no
  trivial minimums (e.g. 6 chars) for personal or financial accounts.
- Captcha/Turnstile on public forms. Disabling "temporarily" requires an open
  issue with a deadline — otherwise it is a regression.

## 5. Web hardening

- **CORS fail-closed:** allowed origins come from env; env absent → deny all, do
  not allow all.
- Required headers at the proxy/server: restrictive CSP,
  `X-Content-Type-Options: nosniff`, `frame-ancestors`, HSTS.
- No preview/dev-backdoor endpoint in code that reaches production. Admin seed
  and bootstrap routes gated by explicit env.
- Passwords and invite tokens never echoed in a response, URL or query string.

## 6. Runtime and filesystem

- Lockfiles and service state live **outside `/tmp`** (predictable, shared); use
  the service's own directory with restrictive permissions.
- A file with sensitive data is created with a restrictive `chmod` — not fixed
  afterwards.

## 7. Supply chain and release

- Installers **pin an immutable tag or commit and verify a published SHA-256**
  before running — never install from a mutable branch (`@main`). The docs never
  advertise `curl … | bash` of a mutable ref.
- Archive extraction is **slip-protected**: `tarfile.extractall(filter="data")`
  (or validate members) — no member writes outside the target via `../` or an
  absolute path.
- Running a downloaded script is **opt-in**, not an automatic side effect of
  fetching it.
- Third-party dependencies are pinned; a CDN `<script>` carries an SRI hash.
- The release/tag script is **gated by tests**: a broken suite does not tag and
  does not publish.

## 8. Rules specific to AI agents

- User input is **untrusted by definition**: flows feeding an LLM have
  prompt-injection defense — untrusted content is **delimited** ("treat as data,
  not instructions"), the model's output is **validated against a strict
  schema/enum** (out-of-schema output is discarded, never acted on), and any
  externally-effecting auto-action (promote a lead, send a DM, spend money,
  change state) sits behind human confirmation or a deterministic policy — never
  fired on model output alone. Test these flows with adversarial inputs.
- An autonomous agent is **commit-only**: `git push`, deploy, remote-host
  restart and key rotation are always human-operator tasks. No exception, even
  if "the issue asks for it". This is backed by a **versioned `PreToolUse`
  deny-hook** that exits non-zero for `docker compose up`, service restart,
  `deploy.sh`, `git push`, and `--yes`/`--force`/`--skip-confirm` on production
  paths — and it runs even under `--dangerously-skip-permissions`.
- **No autonomous credential transmission:** code that transmits a credential,
  rotates a key or deploys is opt-in, default off, and needs human confirmation.
  Private-key bytes are never transmitted — use a fingerprint/reference plus an
  audit-log entry.
- What the agent cannot resolve alone (rotations, firewall, production env)
  becomes an explicit `needs_operator` item in the report — never silently
  omitted.
- The agent reports faithfully: a failed test, a skipped step and residual risk
  appear in the delivery summary.

## 9. Path and URL inputs

- A filesystem path built from request input is **resolved and confined**:
  `resolved.is_relative_to(base)` against a server-fixed base. Reject absolute
  paths, `..`, and symlinks that escape the base. A caller-supplied filename
  matches `^[A-Za-z0-9._-]+$` or is replaced by a server-generated UUID.
- **SSRF:** fetching a caller-supplied URL requires auth and a domain allowlist,
  and rejects private, loopback and link-local targets — **validate after DNS
  resolution** (the resolved IP, not just the hostname).

## 10. Injection (SQL, shell, filename)

- SQL uses **parameter binding / ORM** — never concatenate or f-string request
  input into a query. A dynamic identifier (table/column) comes from a fixed
  server-side allowlist, not from input.
- Shell out with `subprocess.run([...], shell=False)` (argument vector) — never
  `os.system` or `shell=True` with interpolated input. Values that must reach a
  command are whitelisted (`^[A-Za-z0-9._-]+$`).
- These rules apply to **every** untrusted string, including commit messages,
  filenames and **LLM output** used to build a command or query.

## 11. Cryptography and tokens

- Passwords are hashed with a **slow, salted KDF** (argon2id, scrypt or bcrypt).
  Never a fast/plain hash (md5, sha1, sha256) or a home-grown scheme.
- Secrets, tokens and unguessable IDs come from a **CSPRNG** (`secrets`,
  `crypto.randomBytes`) — never `Math.random()` / `rand()`.
- Tokens **expire and are revocable** with server-side revocation state. No
  non-expiring JWT, no `algorithm:'none'`, no weak or fallback signing secret.

---

## PR self-check

Before opening or approving a PR that touches runtime, confirm — or mark `n/a`:

- [ ] No secret added to code, docs, examples or history (`.credentials/`/`.env` only)
- [ ] Service still fail-fast on missing required env; no secret/PII default in a tracked file
- [ ] Key material gitignored + `chmod 600` from the first commit
- [ ] DB dumps / runtime artifacts gitignored **before** being created; `git status` read before commit
- [ ] No token/password/personal ID/auth payload logged; `Authorization`/PII redacted
- [ ] No secret or token in a URL or query string
- [ ] No PII committed or stored plaintext in a synced dir; operator-name/PII gate runs
- [ ] New service/port binds loopback unless external exposure is explicit opt-in
- [ ] Certificate verification never disabled on a secret/PII/token channel
- [ ] CORS/allowed origins stay fail-closed (env absent → deny)
- [ ] Every mutating/data route has an auth guard; webhooks verify signatures; no self-escalation
- [ ] Auth endpoints rate-limited + non-enumerable; password policy enforced
- [ ] Request-derived paths confined (`is_relative_to`); caller URLs allowlisted + post-DNS checked
- [ ] SQL parameter-bound; no `shell=True`/`os.system` on untrusted input (incl. LLM output)
- [ ] Passwords via argon2/scrypt/bcrypt; secrets from CSPRNG; tokens expire + revocable
- [ ] Installer pins tag/commit + checksum (no `@main`, no `curl|bash`); extraction slip-protected
- [ ] LLM output schema-validated; auto-actions gated by human confirm; deny-hook present
- [ ] `needs_operator` items (rotation, deploy, firewall) listed, not omitted

---

## Provenance

Distilled from ~300 real vulnerabilities remediated across production
repositories (secrets in code and design docs, mass-provisioned default
passwords, tokens and personal IDs logged at login, a debug service exposed off
loopback, CORS opened when env was absent, path traversal and SSRF in file/URL
handlers, SQL and shell injection, disabled TLS verification, weak password
hashing and non-expiring tokens, a supply-chain install from a mutable branch,
and an unauthorized autonomous deploy → the commit-only rule). Client and repo
identifiers are intentionally omitted: this kit is shared, so the *rule* travels,
not the incident.

2026-07-17 additions came from an agent (this one) committing a `pg_dump` into a
repo: the backup was created and the next `git add -A` swept it in, because
`data/` was not yet ignored. Caught before any push. The rule that would have
prevented it — *gitignore the artifact before creating it* — did not exist here
until the mistake did.

**Enforcement status:** §1 (tracked-secret paths, key-material) and §7 (installer
checksum) are enforced by `governancekit doctor` and the installer. `doctor` also
runs **advisory** scans for the automatable rules in §1–§4 and §7–§11 (disabled
TLS verification, secrets/PII in URLs, `shell=True`/`os.system`, `Math.random`
for secrets, weak password hashing, `0.0.0.0` binds and trivial creds in
templates, `@main`/`curl|bash` installers, unfiltered `extractall`) — a warning,
not a gate, so a consumer project's `doctor` stays PASS while surfacing the risk.
§5, §6 and the review-only rules (rate-limiting/password policy, prompt-injection
auto-action gating) remain review-gated here and in `./security.md`.
