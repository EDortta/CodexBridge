Parent: #63
Related: #71 (reuses its calendar service module)

## Objective
Give the phone a REST surface for reminders. The mobile client speaks REST against `/api/v1/*` and cannot call `/mcp` — different transport, different auth model — so #71's MCP tools alone do not reach CodexBridgeMobile.

## Scope
- `POST /api/v1/reminders`, `GET /api/v1/reminders`, `DELETE /api/v1/reminders/{id}` in a new `gateway/app/api/routes/reminders.py`.
- Reuses `gateway/app/services/google_calendar.py` from #71 unchanged — this issue adds a second transport in front of the same service, not a second implementation.
- New `Action`s in `permissions.py` mapping to the `codexbridge.reminders.write` scope introduced in #71, plus `codexbridge.reminders.read` for the list endpoint (the read scope is new here — #71 deliberately has no MCP list tool, but the phone's whole reason to exist for this feature is browsing existing reminders, so the REST surface does need one).

## Requirements
- `GET /api/v1/reminders` filters by `extendedProperties.private.source = "codexbridge"` (and, once #71's multi-user note is acted on, by the caller's own `requested_by`) — this endpoint must not become a way to enumerate the operator's entire personal calendar.
- Response and request bodies mirror #71's tool schemas field-for-field (`text`, `when`, `notes`, `lead_minutes`, `idempotency_key`) so the two transports stay a single mental model, not two independent contracts that can drift.
- Honors the standard `Idempotency-Key` header via the existing `gateway/app/api/idempotency.py` middleware — unlike `/mcp`, `/api/v1/` is inside it, so this issue does not need to reinvent the deterministic-event-id trick #71 uses; it may reuse it internally regardless for consistency with the MCP path.
- Same error-mapping requirement as #71: an unconfigured or misconfigured calendar produces the same actionable, `client_email`-naming message text on this transport as on MCP — not a paraphrase, the same string, so a support conversation about "reminders aren't working" gets one consistent explanation regardless of which client the operator used.

## ARO
- Depends entirely on #71 landing first; this issue adds no new calendar logic, only a second entry point.
- Same egress and credential-custody considerations as #71 apply unchanged — no new risk is introduced by adding a transport in front of an existing service.

## Test plan
- New `tests/integration/test_reminders_api.py`: create/list/cancel round trip; scope enforcement for both `.write` and `.read`; idempotency-key replay via the standard middleware; response body matches #71's MCP tool output shape field-for-field for the same logical request.
- `tests/contract/test_openapi_document.py`: the three new paths documented; `tests/contract/test_proxy_routes.py`: routes present in the nginx `/api/` allowlist.

## Definition of Done
- A reminder created via REST is indistinguishable, in the underlying Calendar event, from one created via MCP — same event shape, same idempotency behavior, same error messages.
