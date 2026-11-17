# Issue #138 — OAuth/MCP session renewal

## Scope and security boundaries

The browser OAuth authorization-code + PKCE endpoint `/oauth/token` can now
issue and rotate refresh tokens **only** for clients present in both
`CODEX_BRIDGE_OAUTH_ALLOWED_CLIENT_IDS` and
`CODEX_BRIDGE_OAUTH_REFRESH_CLIENT_IDS`. The latter is a comma-separated
opt-in list, defaulting to `chatgpt-codexbridge`; set it to an empty value to
keep the former authorization-code-only behavior. The OAuth discovery advertises
`refresh_token` only when the feature is enabled.

Browser grant absolute lifetime: `CODEX_BRIDGE_OAUTH_BROWSER_REFRESH_TTL_SECONDS`
(default 604800 seconds, 7 days). This is **not** the mobile grant's 30-day
lifetime; renewal carries the original deadline and does not extend it.
The mobile `/api/v1/auth/refresh` accepts only the `codexbridge-mobile`
client; OAuth `/oauth/token` refresh requires the original registered client.
Both enforce single-use rotation using the existing conditional database
UPDATE and revoke a replayed grant. Existing `/api/v1/auth/revoke` supports
grant revocation; its API does not automatically perform ChatGPT logout.

Rotated scopes are the intersection of originally granted scopes, the current
user registry's scopes, and the deployment's current scope allowlist. A disabled
account cannot refresh. Token responses prohibit caching, and no raw tokens,
codes or passwords are logged.

## User interface

The authorization form immediately shows a submitting state, disables the
submit control, and announces progress to assistive technologies. A 15-second
warning reports unexpectedly long processing. Network failures that prevent
navigation remain subject to browser error display.

## Diagnosis

Run this read-only probe from any client host:

```sh
bash scripts/diagnose_issue_138_oauth.sh
```

The output separates DNS, connect, TLS, first-byte and total response times.
The server logs also record `oauth_authorize_timing` entries for
`password_verify` and `code_persist`, in milliseconds without credentials.
The browser redirect, external identity provider, ChatGPT token renewal logic,
and client-side network conditions are outside this server's instrumentation.

The previously observed 12-second login cannot be attributed to one component
until measurements from the actual host are captured. **No live timing
measurement has yet been recorded for this branch.**

## Acceptance gates before controlled deployment

1. Run `python3 -m pytest -q tests/integration/test_oauth_authorize.py tests/integration/test_auth.py tests/integration/test_mcp_transport.py`.
2. Run the wider test suite and review the concurrent rotation and revoke tests.
3. Measure the actual login stages, record sanitized evidence, and review that
   cached credentials never appear in logs.
4. Confirm ChatGPT's connector uses the returned refresh token after an access
   token expires; server-side support does not prove client-side behavior.
5. Deploy to frida with a rollback plan only after tests and explicit approval.

No production change is implied by this branch.


## Measured bottleneck and next production gate (2026-11-16)

The centralized [run 203129-2ee7d7e7](https://github.com/EDortta/development-evidences/blob/main/CodexBridge/issue-138-oauth-session/fix-issue-138-oauth-session-ux/2026-11-16/203129-2ee7d7e7/manifest.json)
records 11.092 seconds for `POST /api/v1/auth/sign-in` versus 0.296
seconds for `GET /api/v1/auth/me`. The ~12-second problem is in the
sign-in request, not discovery or /me. The current production gateway
does not expose the internal password-versus-persistence timing.

This branch now adds successful sign-in `Server-Timing` values for
`password_verify` and `grant_persist` (milliseconds), and the
credential-safe collector reads only these numeric values. They are
**not available until this branch is deployed**.

A controlled deploy to frida, with previous version available for
rollback, is needed to establish whether the delay is the cost of the
password KDF or database commit/lock contention. Do not weaken the
constant-time account-enumeration protection or reduce KDF iterations
based on network-only measurements.

Fast validation after checkout (no deployment):

```sh
python3 -m pytest -q tests/unit/test_issue_138_diagnostics.py tests/integration/test_auth.py
```

After an approved deployment, use:

```sh
python3 scripts/run_issue_138_evidence.py --diagnostics-only
```

The published manifest will include numeric `sign_in.server_timing` if
the deployed gateway contains the instrumentation; absence of that field
means no server phase attribution yet.


## Frida: limited patch procedure, no migrations

The dedicated scripts stage and apply only:
`gateway/app/main.py`, `gateway/app/api/routes/auth.py`,
`gateway/app/core/config.py`, `gateway/app/core/oauth.py`.
They do not deploy the whole repository, perform migrations, restore a database
or require Git on frida. Frida's live hashes **must exactly match**
`origin/development` at staging time; otherwise `--check` and `--apply`
refuse to modify the service. A mismatch requires inspecting the actual frida
version, not bypassing the guard.

After obtaining a successful central evidence manifest, stage from devel3:

```bash
cd /home/esteban/Sync/Projects/AI/CodexBridge-oauth-138
git fetch origin
git pull --ff-only origin fix/issue-138-oauth-session-ux
bash -n scripts/stage-frida-issue-138.sh scripts/apply-frida-issue-138.sh
bash scripts/stage-frida-issue-138.sh
```

Save the printed `STAGED_ONLY=issue138-YYYYMMDDTHHMMSSZ`, then use
that ID **on frida** for read-only preflight:

```bash
cd "$HOME/codexbridge-staging/issue138-YYYYMMDDTHHMMSSZ"
sudo bash ./apply-frida-issue-138.sh --check issue138-YYYYMMDDTHHMMSSZ
```

Only after `CHECK=ok` and operator review, apply separately:

```bash
cd "$HOME/codexbridge-staging/issue138-YYYYMMDDTHHMMSSZ"
sudo bash ./apply-frida-issue-138.sh --apply issue138-YYYYMMDDTHHMMSSZ
```

The applicator creates a backup under
`/var/backups/codexbridge/<release-id>/old`, validates individual SHA-256
hashes and Python syntax, restarts the Gateway, and checks local HTTP health
and OAuth discovery. Failure after modification automatically restores old
files and restarts. No DB rollback: this procedure never migrates the DB.
Rollback applies to the four code files only, not OAuth grants subsequently
issued or browser sessions.

After application, run central diagnostics again. `Server-Timing` should
report `password_verify` and `grant_persist` for the administrative
`/api/v1/auth/sign-in` endpoint. Independently test real ChatGPT OAuth
refresh with client-side behavior; a healthy Gateway does not prove the
external connector renewed credentials automatically.

## One-command idempotent Gateway updater (supersedes manual stage/apply)

The legacy issue-specific staging and remote apply steps remain for audit history,
but **the supported operator entrypoint for this patch is now one command**:

```bash
cd /home/esteban/Sync/Projects/AI/CodexBridge-oauth-138
git pull --ff-only origin fix/issue-138-oauth-session-ux
python3 scripts/update_frida_gateway.py
```

For a no-mutation rehearsal use `python3 scripts/update_frida_gateway.py --check`.
Both modes publish an immutable sanitized GitHub manifest using the shared
`development-evidences` publisher, with an explicit publication ACK; the command
returns 2 if publication cannot be confirmed. The updater performs, in order:
local deterministic tests, exactly scoped Git packaging, transfer to frida,
baseline hash verification, idempotency check, backup of the four existing code
files, syntax verification, service restart, HTTP health check, OAuth discovery
check, and automatic code rollback if update or acceptance fails.

A second run on the same code returns `already_current` without restarting the
service. A partially updated instance can be completed when every file matches
either the verified baseline or desired content. Unknown file hashes stop the
update rather than overwrite unrecognized changes.

The current update profile is explicitly `oauth-138` (four Python modules).
The entrypoint and mechanism are permanent, but other Gateway file groups and
schema migrations need their own reviewed profile; this command does **not**
silently perform migrations or update the whole repository. An all-code release
must not pretend it is safe merely because the OAuth-only profile passed.

The previous failed `issue138-20261117T143058Z` deploy left the service healthy
and all four bytes unchanged, as confirmed by the published post-failure read-only
manifest. The failed deploy's original cause remained unclassified and must
not be reported as resolved merely because another updater succeeds.

## Twelve-month browser session policy (2026-11-17)

Operator-approved policy for the ChatGPT OAuth client:
`oauth_browser_refresh_ttl_seconds=31536000` (365 days absolute),
`oauth_access_token_ttl_seconds=3600` (1 hour), and single-use refresh
rotation with reuse revocation unchanged. Mobile first-party refresh grants
retain their independent 30-day lifetime. The longer deadline applies to
**new** authorization-code exchanges; it cannot extend existing persisted
grants retroactively. Browser reconnection is still dependent on the client
retaining and using the refresh token; OAuth discovery by itself is not proof.

The idempotent `scripts/update_frida_gateway.py` recognizes the hashes of
the previously deployed 6aa91e8 four-file patch as safe predecessors, so
updating only the config does not require reverting the deployed release.
A deployment-level environment variable `CODEX_BRIDGE_OAUTH_BROWSER_REFRESH_TTL_SECONDS`
may override the code default; the updater does not edit `/etc/codex-bridge/env`.
Actual runtime policy must be verified without revealing environment secrets.

Security cost: a stolen refresh token can potentially renew an account's
authorization for up to one year until revoked, despite single-use rotation.
No additional scope or access-token lifetime is granted; user revocation and
replay detection must remain active. Confirm whether ChatGPT preserves
refresh tokens across reconnects before claiming the login UX is solved.

## Gateway/AgentHub compatibility fix (2026-11-17)

A code-only OAuth deployment exposed a cross-module mismatch during a planned
Gateway restart: `main.py` called `AgentHub.unregister(executor_id, websocket)`,
but the installed `agent_hub.py` still implemented
`unregister(executor_id)`. When Uvicorn closed live agent sockets with WebSocket
code `1012` (service restart), cleanup raised `TypeError`. The newly
restarted Gateway recovered and accepted the agent's WebSocket connections.

The idempotent updater's versioned OAuth profile now includes
`gateway/app/services/agent_hub.py` as its fifth, explicitly protected file.
It recognizes the byte-identical historical AgentHub baseline from commit
`196de250`, validates candidate hashes, and deploys the newer method with
socket identity protection. The test
`tests/unit/test_update_frida_gateway.py::test_websocket_gateway_and_agent_hub_contract_are_deployed_together`
prevents another release that updates the caller without the callee.

Note: the 365-day browser refresh policy was deployed successfully with one
changed file (published evidence run 152033-dbdcbc47). That health check did
not exercise a live agent WebSocket shutdown; we must not equate health 200
with end-to-end WS contract coverage.
