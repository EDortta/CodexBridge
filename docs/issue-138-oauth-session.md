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
