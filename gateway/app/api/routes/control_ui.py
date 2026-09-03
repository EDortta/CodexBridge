"""CodexBridge Control — the first server-rendered screens (issue #73 Stage 5).

Four routes, on purpose only four: `GET /control` (fleet), `GET
/control/nodes/{nodeId}` (node detail: capabilities/engines, discovered
candidates, authorizations), and `GET /control/invite` (see its own section
below — this one does not do what its name promises yet). Missions,
Decisions, Audit and Settings are Stage 6; the epic (#73) lists them as
non-goals for this cycle.

## HTML in the gateway's own process, not a second deployable

`gateway/app/main.py:oauth_authorize`/`oauth_authorize_submit` already answer
this question for this codebase: a form is an `HTMLResponse` built from an
f-string with `html.escape` at every interpolation, served from the same
FastAPI app, no template engine dependency. This module follows that
precedent exactly rather than introducing Jinja2 (a new dependency for one
screen) or a second deployable (a build step, a second set of secrets, a
second thing to keep in sync with the JSON contract). When the real Stage 5
SPA arrives, it replaces this shell against the *same* `/api/v1/**` surface —
that is why the shell stays this thin.

## Reads are server-rendered; writes are `fetch()` against the real API

Two different rules for two different things, and conflating them is the
mistake this module is written to avoid:

- **Reads** (the node list, one node's capabilities/engines, a page of
  discovered candidates, the active authorizations on a node) are rendered
  server-side by calling the *exact same* functions the JSON routes call —
  `gateway.app.api.routes.nodes._node_dto`,
  `gateway.app.api.routes.discovery._discovered_resource_dto`,
  `gateway.app.api.routes.authorizations._authorization_dto`, `store.
  list_nodes`/`get_node`/`list_discovered_resources_page`. Nothing here
  recomputes health, capability, or pagination logic — it imports the one
  definition and prints it as HTML instead of JSON. This is also why HTML
  escaping is directly testable with plain `pytest` + `TestClient`, no
  browser needed: the escaped text is in the response body the test already
  reads.
- **Writes** (Adopt, Deny, Grant, Revoke) are `fetch()` calls from inline
  `<script>` against `POST /api/v1/discovered-resources/{id}/adopt|deny` and
  `POST /api/v1/nodes/{nodeId}/projects/{projectId}/authorize|revoke` — the
  brief's own instruction ("as telas chamam os mesmos endpoints JSON que
  C1/C3/C4 já expõem"), and the only way a `403` on granting `modify`/
  `deliver` (`permissions.is_allowed`'s second gate, see
  `docs/control-plane.md` Stage 4) is the *real* one instead of a guess this
  module would have to keep in sync by hand. A write never touches `store.py`
  directly from here.

## Authentication: HTTP Basic, re-verified per request

`current_principal` (`gateway/app/api/auth.py`) reads `Authorization: Bearer
<token>` — and a plain browser navigation (typing the URL, clicking a link)
cannot attach a custom header. Gating `GET /control` on that exact dependency
the way `/api/v1/nodes` is gated would make the page unreachable by a normal
browser, which cannot be "the panel the operator opens on `frida`" — so this
had to be something else, and the brief allows exactly the honest fallback:
"se a única forma honesta hoje for exigir um token colado, diga isso em vez
de inventar sessão de cookie nova."

What is used instead is **HTTP Basic**, verified on *every* request by the
same `gateway.app.core.users.authenticate_async` that
`oauth_authorize_submit` and `POST /api/v1/auth/sign-in` already call — the
identical constant-cost, enumeration-safe password check, not a second one.
Basic is the one standard HTTP credential a browser resends automatically on
every subsequent request to this origin (plain link clicks, pagination,
reloads) without any server-side session state, any cookie, or any token
embedded in a URL or a hidden form field. It needs no CSRF defence — unlike a
cookie session, nothing rides along on a *forged* cross-origin request,
because the browser only ever attaches Basic credentials to requests to the
realm it cached them against, which this deployment's operator establishes by
typing a password into the browser's own native prompt (triggered by this
module's `401` + `WWW-Authenticate: Basic`), never into a form this module
renders. That is the whole reason a cookie session was rejected here: it
would have been a *second* credential mechanism, with its own expiry and its
own forgery surface, to keep correct forever next to the one the JSON surface
already has — the exact shape `docs/napkin-lessons.md` keeps warning about.

Every route in this module is therefore gated by `_control_principal`, which:

1. parses `Authorization: Basic base64(user:pass)`, challenging with `401` +
   `WWW-Authenticate` when it is absent or malformed — the browser's native
   dialog, no HTML form of this module's own;
2. calls `authenticate_async` against it — `401` again on a wrong password,
   with the same opaque message every failed credential gets elsewhere on
   this codebase;
3. derives an `AuthenticatedPrincipal` from the resulting `GatewayUser` —
   same shape `current_principal`/`oauth_authorize_submit` build, `auth_
   scheme="basic"` so it is distinguishable if it ever needs to be;
4. calls `permissions.is_allowed(principal, action)` — the *same* catalogue
   `require_action` enforces on `/api/v1/**` — and refuses with an explicit
   `403` naming the action, never a silent redirect or a blank page. This is
   what "uma tela que recusa na porta" means in practice here: the refusal
   happens before a single row of fleet data is read, not after a `fetch()`
   already reached the browser and failed.

Cost: `authenticate_async` is ~200-600ms of deliberate PBKDF2, and Basic
re-supplies it on *every* click, including "next page". That is the price of
"no server-side session state at all" and is judged acceptable for a
single-operator admin console; `gateway/app/main.py`'s rate limiter is
applied to this whole router in `gateway/app/main.py` (same bucket rule as
`POST /oauth/authorize`) precisely because that repeated derivation is also
the cheapest lever a guesser has against this surface.

**One thing Basic does *not* solve**: the write actions still need a
`Authorization: Bearer` token, because that is the only scheme `/api/v1/**`
accepts and this PR is not the place to teach it a second one (out of scope,
and the mobile/ChatGPT clients depend on Bearer meaning exactly what it means
today). So `GET /control/nodes/{nodeId}` — the one screen with buttons that
write — mints one ordinary, short-lived OAuth access token per render, via
the *same* `store.create_oauth_access_token` call `POST /api/v1/auth/sign-in`
uses, scoped the same way (`principal.scopes ∩ settings.oauth_scopes()`),
landing in the *same* `oauth_access_tokens` table `current_principal` reads.
It is embedded once, inline, in a `<script>` tag for this page's own
`fetch()` calls — never in a URL, a query string, a log line, or
`audit_events` (minting it calls no `record_event`, matching every other
*read* path in this codebase, which is audited by nothing; only the writes
this token goes on to make are audited, by the routes it calls). A fresh page
load mints a fresh token; nothing here reuses or persists one.

## `resourcePath`/`rootPath`: displayed, never leaked sideways

`docs/api/README.md` ("Fields that must never ship") and `docs/control-
plane.md` ("resource_key é dado sensível") name exactly one standing
exception for a server filesystem path: the administrative discovery surface
— `GET /api/v1/nodes/{nodeId}/discovered-resources` and the `adopt`/`deny`
responses. This module's node-detail screen is that same authorized surface,
rendered as HTML instead of JSON, so the path *may* appear in the escaped
table body an operator with `nodes.discoveries.read` is looking at. It must
not appear anywhere else this module writes: never in a `<title>`, never in a
query string (pagination here cursors on the resource's opaque `id`, exactly
like `routes/discovery.py`'s own cursor, never on the path), and this module
calls no logger at any level — there is nothing for it to leak into.

## `/control/invite`: what this screen cannot do yet, and why

The brief for this PR describes `GET /control/invite` calling `POST
/api/v1/nodes/invite` and printing a ready-to-copy `scripts/enroll_node.py`
command. Neither exists in this codebase: `gateway/app/api/routes/nodes.py`
serves only `GET /nodes` and `GET /nodes/{nodeId}`, no route registers a node
or mints it a `machine_token`; `scripts/` holds `discover_projects.py`,
`register_projects.py`, `apply_migrations.py`, `install.sh`, `diagnose.sh` —
no `enroll_node.py`. `docs/project-onboarding.md`'s own "Schema de executor"
section confirms this is by design so far: a node is registered today by
hand-editing `registry.json` (`machine_token` included) on both sides and
restarting the gateway, the same two-file, two-machine procedure that page
documents in full for projects.

Building the described screen would mean inventing, inside this UI PR, the
one thing the brief itself forbids inventing here: real backend business
logic (a token-minting endpoint with its own security posture — hashing at
rest, an audit trail, a revocation story — and a new script) with no existing
API to front. "Se uma tela precisa de um dado que a API não dá, a resposta
certa é parar e relatar, não calcular no template" — this is exactly that
case, at the level of an entire endpoint rather than one field. So this route
renders an honest explanation instead of a form that posts to nothing: it
names the missing endpoint and script by their exact expected names, and
points at `docs/project-onboarding.md`'s real, current procedure. See this
PR's own final report for the recommendation (a follow-up Stage 5 PR to
design and build the invite endpoint) rather than silently shipping a button
that 404s.
"""

from __future__ import annotations

import base64
import binascii
import html
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import pagination, permissions
from gateway.app.api.errors import ApiError
from gateway.app.api.permissions import Action
from gateway.app.api.routes.authorizations import _authorization_dto
from gateway.app.api.routes.discovery import _discovered_resource_dto
from gateway.app.api.routes.nodes import _node_dto
from gateway.app.core.config import settings
from gateway.app.core.oauth import expires_in, generate_access_token
from gateway.app.core.users import AuthenticatedPrincipal, authenticate_async
from gateway.app.db.session import get_session
from gateway.app.services import store
from shared.protocol import Capability


router = APIRouter(prefix="/control")

# The client label recorded on a token this module mints — mirrors `routes/
# auth.py`'s `MOBILE_CLIENT_ID`. Fixed, never taken from the request, for the
# same reason: this is a first-party surface, and a caller-supplied label
# would let a forged Basic credential (already rejected before this point,
# but defence in depth costs nothing here) mislabel its own audit trail.
CONTROL_CLIENT_ID = "codexbridge-control"

# Rows per HTML page of discovered candidates. Smaller than `pagination.
# DEFAULT_LIMIT` (50) on purpose -- an operator reading a table, not a client
# paging through JSON, and `docs/control-plane.md` cites 247 real candidates
# from one scan, so this list is worth keeping short per screen.
CANDIDATES_PAGE_SIZE = 20


# ---------------------------------------------------------------------------
# Authentication and authorization -- see the module docstring for the design
# ---------------------------------------------------------------------------


def _basic_challenge(message: str = "Sign in with a CodexBridge account.") -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=message,
        headers={"WWW-Authenticate": 'Basic realm="codexbridge-control"'},
    )


def _parse_basic_credentials(request: Request) -> tuple[str, str] | None:
    """`(username, password)` from a well-formed `Authorization: Basic` header, else None.

    Never raises: a malformed header is indistinguishable from an absent one
    to the caller of this function, which always turns None into the same
    `401` challenge `_control_principal` raises for "no credential at all".
    """
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header.removeprefix("Basic ").strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if ":" not in decoded:
        return None
    username, _, password = decoded.partition(":")
    return username, password


async def _control_principal(request: Request, action: Action) -> AuthenticatedPrincipal:
    """Resolve, verify and authorize the operator for one `/control` request.

    Raises the `401`/`403` this module's docstring describes; never returns a
    principal that has not cleared `permissions.is_allowed(principal,
    action)`.
    """
    credentials = _parse_basic_credentials(request)
    if credentials is None:
        raise _basic_challenge()
    username, password = credentials
    outcome = await authenticate_async(settings.user_registry_file, username, password)
    if not outcome.ok or outcome.user is None:
        raise _basic_challenge("Invalid username or password.")
    user = outcome.user
    principal = AuthenticatedPrincipal(
        user_id=user.user_id,
        email=user.email,
        roles=user.roles,
        allowed_projects=user.allowed_projects,
        scopes=user.scopes,
        can_approve_sensitive=user.can_approve_sensitive,
        auth_scheme="basic",
    )
    if not permissions.is_allowed(principal, action):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Signed in as {user.user_id!r}, but this screen requires the "
                f"{action.name!r} permission (scope {action.scope}). "
                "GET /api/v1/auth/me reports what this account may do."
            ),
        )
    return principal


async def _mint_page_token(session: AsyncSession, principal: AuthenticatedPrincipal) -> str:
    """A fresh, ordinary Bearer token for one render's own `fetch()` calls.

    See the module docstring, "Authentication" -- same table, same scope cap,
    as `POST /api/v1/auth/sign-in`. Commits: the token must be visible to the
    very next request (this page's own `fetch()`, milliseconds later), and
    this module holds no other reason to defer the commit.
    """
    token = generate_access_token()
    scopes = sorted(set(principal.scopes) & settings.oauth_scopes())
    await store.create_oauth_access_token(
        session,
        token=token,
        client_id=CONTROL_CLIENT_ID,
        user_id=principal.user_id,
        scopes=scopes,
        expires_at=expires_in(settings.oauth_access_token_ttl_seconds),
    )
    await session.commit()
    return token


# ---------------------------------------------------------------------------
# Rendering — plain f-strings + html.escape, exactly `oauth_authorize`'s idiom
# ---------------------------------------------------------------------------


def _e(value: object) -> str:
    """`html.escape`, tolerant of None -- the one interpolation function this

    module uses for every value that did not originate as a literal in this
    file. A `display_name`, a `resourcePath`, a `health_reason` are all text
    someone else wrote (an operator, a node's own hostname probe); none of
    them may become markup.
    """
    if value is None:
        return ""
    return html.escape(str(value))


_BASE_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 64rem;
       margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
h1 { font-size: 1.5rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
table { border-collapse: collapse; width: 100%; margin: .75rem 0; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #eee; font-size: .92rem; }
th { color: #555; font-weight: 600; }
code { background: #f3f3f3; padding: .1rem .3rem; border-radius: 3px; font-size: .88rem; }
.tag { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .8rem; }
.tag-ok { background: #dcfce7; color: #166534; }
.tag-degraded { background: #fef9c3; color: #854d0e; }
.tag-offline { background: #fee2e2; color: #991b1b; }
.tag-unknown { background: #e5e7eb; color: #374151; }
.hint { color: #555; font-size: .92rem; }
.error { color: #b91c1c; font-size: .9rem; margin: .25rem 0; }
.notice { background: #eff6ff; border: 1px solid #bfdbfe; padding: .75rem 1rem; border-radius: 6px; }
.warn { background: #fffbeb; border: 1px solid #fde68a; padding: .5rem .75rem; border-radius: 6px; font-size: .88rem; }
form.inline { display: inline; }
fieldset { border: 1px solid #ddd; border-radius: 6px; margin: .5rem 0; }
nav a { margin-right: 1rem; }
""".strip()

# The node-detail page's write behaviour: Adopt/Deny/Grant/Revoke, each a
# `fetch()` POST against the real `/api/v1/**` routes C1/C3/C4 already ship
# (see the module docstring, "Reads are server-rendered; writes are
# fetch()"). A plain string, never an f-string: every dynamic value it needs
# (`CB_TOKEN`, `CB_NODE_ID`) is declared as a `const` by the two lines the
# caller prepends via `json.dumps` (JS-literal-safe, unlike Python's `!r` —
# see `_candidate_row`'s docstring on why operator-supplied text is never
# spliced into a JS-call string), and every other dynamic value
# (`resourceId`, `projectId`) is read back from a form's `dataset` — set via
# HTML-escaped `data-*` attributes, never through inline `onsubmit=`.
_CONTROL_JS = """
function reportError(id, err) {
  const el = document.getElementById(id);
  if (el) { el.textContent = err; }
}
async function callApi(path, body) {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + CB_TOKEN },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await resp.json().catch(function () { return {}; });
  if (!resp.ok) {
    throw new Error((data && data.message) || (resp.status + " " + resp.statusText));
  }
  return data;
}
document.querySelectorAll(".control-adopt").forEach(function (form) {
  form.addEventListener("submit", async function (evt) {
    evt.preventDefault();
    const resourceId = form.dataset.resourceId;
    const caps = Array.from(form.querySelectorAll("input[name=cap]:checked")).map(function (el) { return el.value; });
    const projectId = form.projectId.value.trim();
    const newId = form.newProjectId.value.trim();
    const newName = form.newProjectName.value.trim();
    const body = { grantCapabilities: caps };
    if (projectId) { body.projectId = projectId; }
    else if (newId && newName) { body.newProject = { projectId: newId, name: newName }; }
    else {
      reportError("err-" + resourceId, "Provide an existing projectId or a new project id+name.");
      return;
    }
    try {
      await callApi("/api/v1/discovered-resources/" + encodeURIComponent(resourceId) + "/adopt", body);
      location.reload();
    } catch (e) { reportError("err-" + resourceId, e.message); }
  });
});
document.querySelectorAll(".control-deny").forEach(function (form) {
  form.addEventListener("submit", async function (evt) {
    evt.preventDefault();
    const resourceId = form.dataset.resourceId;
    try {
      await callApi("/api/v1/discovered-resources/" + encodeURIComponent(resourceId) + "/deny", undefined);
      location.reload();
    } catch (e) { reportError("err-" + resourceId, e.message); }
  });
});
document.querySelectorAll(".control-grant").forEach(function (form) {
  form.addEventListener("submit", async function (evt) {
    evt.preventDefault();
    const projectId = form.dataset.projectId;
    const caps = Array.from(form.querySelectorAll("input[name=cap]:checked")).map(function (el) { return el.value; });
    try {
      await callApi(
        "/api/v1/nodes/" + encodeURIComponent(CB_NODE_ID) + "/projects/" + encodeURIComponent(projectId) + "/authorize",
        { capabilities: caps }
      );
      location.reload();
    } catch (e) { reportError("err-auth-" + projectId, e.message); }
  });
});
document.querySelectorAll(".control-revoke").forEach(function (form) {
  form.addEventListener("submit", async function (evt) {
    evt.preventDefault();
    const projectId = form.dataset.projectId;
    try {
      await callApi(
        "/api/v1/nodes/" + encodeURIComponent(CB_NODE_ID) + "/projects/" + encodeURIComponent(projectId) + "/revoke",
        undefined
      );
      location.reload();
    } catch (e) { reportError("err-auth-" + projectId, e.message); }
  });
});
""".strip()


def _health_tag(health: str) -> str:
    return f'<span class="tag tag-{_e(health)}">{_e(health)}</span>'


def _capability_checkboxes(*, checked: frozenset[Capability] = frozenset()) -> str:
    """One `<label><input type=checkbox name=cap value=...>...` per `Capability`.

    Reads the vocabulary from `shared.protocol.Capability` — the same
    derived-from-`TaskMode` enum `CAPABILITY_MODES`/`AUTO_AUTHORIZABLE_
    CAPABILITIES` already use — rather than four literal strings copy-pasted
    at each call site, so a fifth capability (should one ever exist) shows up
    here without a second place to remember to edit. Nothing here is
    `disabled`: an operator may always uncheck a suggested default (e.g.
    adopting with no grant at all, leaving a candidate `ADOPTED` but not yet
    `AUTHORIZED` — see `docs/control-plane.md`, "Adoption does not
    automatically grant every operational capability").
    """
    boxes = []
    for capability in Capability:
        attr = " checked" if capability in checked else ""
        boxes.append(
            f'<label><input type="checkbox" name="cap" value="{capability.value}"{attr} /> {capability.value}</label>'
        )
    return "\n      ".join(boxes)


def _page(title: str, body: str) -> HTMLResponse:
    """The one page skeleton every `/control` route renders through.

    `title` must never carry `resourcePath`/`rootPath` -- see the module
    docstring's "resourcePath/rootPath" section. Every caller in this module
    passes a title built from static strings and, at most, a node's
    `displayName`/id, which are not in that sensitive category.
    """
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{_e(title)}</title>
    <style>{_BASE_CSS}</style>
  </head>
  <body>
    <nav><a href="/control">Fleet</a><a href="/control/invite">Invite a node</a></nav>
    {body}
  </body>
</html>"""
    )


# ---------------------------------------------------------------------------
# GET /control — fleet list
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def control_home(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    principal = await _control_principal(request, permissions.NODES_READ)
    rows = await store.list_nodes(session)

    body_rows = []
    for node, executor in rows:
        dto = _node_dto(node, executor)
        pending = await store.count_decidable_discovered_resources(session, node.id)
        admission = "enabled" if dto["enabled"] else "disabled"
        stale_note = ' <span class="hint">(stale)</span>' if dto["inventoryStale"] else ""
        body_rows.append(
            f"""<tr>
  <td><a href="/control/nodes/{_e(node.id)}">{_e(dto['displayName'])}</a></td>
  <td>{_health_tag(dto['health'])}{stale_note}</td>
  <td>{_e(admission)}</td>
  <td>{pending if pending else '&mdash;'}</td>
  <td>{_e(dto['agentVersion']) or '&mdash;'}</td>
</tr>"""
        )

    table = (
        "<table><thead><tr><th>Node</th><th>Health</th><th>Admission</th>"
        "<th>Pending candidates</th><th>Executor version</th></tr></thead>"
        f"<tbody>{''.join(body_rows) or '<tr><td colspan=5>No Bridge Nodes registered.</td></tr>'}</tbody></table>"
    )

    body = f"""
    <h1>CodexBridge Control &middot; Fleet</h1>
    <p class="hint">Signed in as {_e(principal.user_id)}. {len(rows)} node(s).</p>
    {table}
    """
    return _page("CodexBridge Control", body)


# ---------------------------------------------------------------------------
# GET /control/nodes/{node_id} — node detail
# ---------------------------------------------------------------------------


def _capabilities_section(dto: dict) -> str:
    caps = ", ".join(_e(c) for c in dto.get("capabilities") or []) or "&mdash;"
    engine_rows = []
    for engine in dto.get("engines") or []:
        engine_rows.append(
            f"""<tr>
  <td>{_e(engine.get('engine'))}</td>
  <td>{'yes' if engine.get('implemented') else 'no'}</td>
  <td>{'yes' if engine.get('available') else 'no'}</td>
  <td>{_e(engine.get('version')) or '&mdash;'}</td>
  <td>{_e(engine.get('detail')) or '&mdash;'}</td>
</tr>"""
        )
    engines_table = (
        "<table><thead><tr><th>Engine</th><th>Implemented</th><th>Available</th>"
        "<th>Version</th><th>Detail</th></tr></thead>"
        f"<tbody>{''.join(engine_rows) or '<tr><td colspan=5>No engines reported.</td></tr>'}</tbody></table>"
    )
    return f"""
    <h2>Capabilities &amp; engines</h2>
    <p>Announced capabilities: {caps}</p>
    <p class="hint">OS: {_e(dto.get('os')) or '&mdash;'} &middot; Arch: {_e(dto.get('arch')) or '&mdash;'}
       &middot; Max concurrent tasks: {_e(dto.get('maxConcurrentTasks')) or '&mdash;'}
       &middot; Discovery roots configured: {_e(dto.get('discoveryRootCount')) if dto.get('discoveryRootCount') is not None else '&mdash;'}</p>
    {engines_table}
    """


def _candidate_row(node_id: str, dto: dict, *, decidable: bool) -> str:
    """One `<tr>` for the candidates table.

    Every dynamic value a form needs to submit later (`resourceId`) travels as
    an `data-*` attribute, HTML-escaped through `_e` like everything else on
    this row -- never spliced into an inline `onsubmit="...(...)"` JS-call
    string. `project_id`/`resourceId` are both operator- or node-supplied text
    with no character allowlist enforced upstream (`shared.protocol.
    NewProjectSpec.project_id` is a bare length-bounded `str`), so building a
    JS argument list by Python string interpolation would be exactly the
    injection `_e` exists to close for HTML text -- `data-*` plus a delegated
    listener (`_CONTROL_JS` below) reads the value back through `dataset`, which
    never re-parses it as code.
    """
    actions = ""
    if decidable:
        actions = f"""
    <form class="control-adopt" data-resource-id="{_e(dto['id'])}">
      <input type="text" name="projectId" placeholder="existing projectId (optional)" size="16" />
      <input type="text" name="newProjectId" placeholder="new projectId" size="14" />
      <input type="text" name="newProjectName" placeholder="new project name" size="16" />
      {_capability_checkboxes(checked=frozenset({Capability.READ, Capability.TEST}))}
      <button type="submit">Adopt</button>
    </form>
    <form class="control-deny" data-resource-id="{_e(dto['id'])}">
      <button type="submit">Deny</button>
    </form>
    <div class="error" id="err-{_e(dto['id'])}"></div>
    """
    return f"""<tr>
  <td><code>{_e(dto['id'])}</code></td>
  <td>{_e(dto['state'])}</td>
  <td>{_e(dto['suggestedName']) or '&mdash;'}</td>
  <td><code>{_e(dto['resourcePath'])}</code></td>
  <td><code>{_e(dto['rootPath'])}</code></td>
  <td>{_e(dto['remoteUrl']) or '&mdash;'}</td>
  <td>{actions}</td>
</tr>"""


def _authorization_section(
    node_id: str,
    *,
    project_ids: list[str],
    active: dict[str, dict],
    names: dict[str, str],
    can_manage: bool,
) -> str:
    """The authorization table for one node.

    `project_ids` is every project this node has an adoption or an active
    authorization for -- not just `active.keys()`. An `ADOPTED` project with
    no capability grant yet has no `project_authorizations` row at all
    (`docs/control-plane.md`, "Adoption does not automatically grant every
    operational capability"), and that is exactly the project an operator
    most needs a Grant form for; showing only rows that already have one
    would hide the one action this section exists to offer.

    Injection note: see `_candidate_row`'s docstring -- `project_id` is
    operator-chosen text with no character allowlist, so it travels as an
    escaped `data-project-id` attribute, never spliced into an inline
    `onsubmit="...(...)"` call.
    """
    if not project_ids:
        rows = "<tr><td colspan=4>No project has been adopted or authorized on this node yet.</td></tr>"
    else:
        rendered = []
        for project_id in project_ids:
            row = active.get(project_id)
            caps = ", ".join(_e(c) for c in (row or {}).get("capabilities") or []) or "&mdash;"
            granted_by = _e((row or {}).get("grantedBy")) or "&mdash;"
            manage_controls = ""
            if can_manage:
                revoke_button = (
                    f'<form class="control-revoke" data-project-id="{_e(project_id)}">'
                    '<button type="submit">Revoke</button></form>'
                    if row is not None
                    else ""
                )
                manage_controls = f"""
        <form class="control-grant" data-project-id="{_e(project_id)}">
          {_capability_checkboxes()}
          <button type="submit">Grant</button>
        </form>
        {revoke_button}
        <div class="error" id="err-auth-{_e(project_id)}"></div>
        """
            rendered.append(
                f"""<tr>
  <td>{_e(names.get(project_id, project_id))} <span class="hint">({_e(project_id)})</span></td>
  <td>{caps}</td>
  <td>{granted_by}</td>
  <td>{manage_controls}</td>
</tr>"""
            )
        rows = "".join(rendered)

    note = ""
    if not can_manage:
        note = (
            '<p class="warn">This account can view authorizations but lacks '
            "<code>nodes.authorizations.manage</code> — Grant/Revoke controls are hidden.</p>"
        )
    warn = (
        '<p class="warn">Granting <code>modify</code> or <code>deliver</code> additionally requires '
        "<code>can_approve_sensitive</code> or the <code>admin</code> role — a request without either "
        "gets a real <code>403</code> from the server below, shown as reported, never a generic error.</p>"
    )
    return f"""
    <h2>Authorizations</h2>
    {note}
    {warn}
    <table><thead><tr><th>Project</th><th>Active capabilities</th><th>Granted by</th><th>Actions</th></tr></thead>
    <tbody>{rows}</tbody></table>
    """


@router.get("/nodes/{node_id}", response_class=HTMLResponse)
async def control_node_detail(
    node_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    state: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    principal = await _control_principal(request, permissions.NODES_READ)
    row = await store.get_node(session, node_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such node.")
    node, executor = row
    dto = _node_dto(node, executor)

    can_view_candidates = permissions.is_allowed(principal, permissions.NODES_DISCOVERIES_READ)
    can_decide = permissions.is_allowed(principal, permissions.NODES_DISCOVERIES_DECIDE)
    can_manage_auth = permissions.is_allowed(principal, permissions.NODES_AUTHORIZATIONS_MANAGE)

    token = ""
    if can_decide or can_manage_auth:
        token = await _mint_page_token(session, principal)

    candidates_section = ""
    if can_view_candidates:
        scope = pagination.scope_digest(f"/control/nodes/{node_id}/discovered-resources", {"state": state})
        after_id = None
        if cursor:
            try:
                after_id = pagination.decode_cursor(scope, cursor, expect={"id": str})["id"]
            except ApiError as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc
        candidate_rows = await store.list_discovered_resources_page(
            session, node_id, state=state, after=after_id, limit=CANDIDATES_PAGE_SIZE
        )
        page, info = pagination.paginate(
            candidate_rows, limit=CANDIDATES_PAGE_SIZE, scope=scope, position_of=lambda r: {"id": r.id}
        )
        dtos = [_discovered_resource_dto(r) for r in page]
        table_rows = "".join(
            _candidate_row(node_id, d, decidable=can_decide and d["state"] in {"discovered", "stale"})
            for d in dtos
        )
        next_link = ""
        if info["hasMore"] and info["nextCursor"]:
            state_qs = f"&state={_e(state)}" if state else ""
            next_link = (
                f'<p><a href="/control/nodes/{_e(node_id)}?cursor={_e(info["nextCursor"])}{state_qs}">'
                "Next page &rarr;</a></p>"
            )
        candidates_section = f"""
        <h2>Discovered candidates</h2>
        <table><thead><tr><th>Id</th><th>State</th><th>Suggested name</th><th>Resource path</th>
        <th>Root path</th><th>Remote</th><th>Actions</th></tr></thead>
        <tbody>{table_rows or '<tr><td colspan=7>No discovered candidates.</td></tr>'}</tbody></table>
        {next_link}
        """
        if not can_decide:
            candidates_section += (
                '<p class="warn">This account can view candidates but lacks '
                "<code>nodes.discoveries.decide</code> — Adopt/Deny controls are hidden.</p>"
            )
    else:
        candidates_section = (
            '<h2>Discovered candidates</h2><p class="warn">This account lacks '
            "<code>nodes.discoveries.read</code> — candidates are hidden.</p>"
        )

    authorization_section = ""
    if can_view_candidates:
        # Every project this node has an adoption or an active authorization
        # for: the candidates just fetched contribute adopted-but-maybe-not-
        # yet-authorized project ids (an `ADOPTED` row with no capability
        # grant has no `project_authorizations` row at all -- see
        # `_authorization_section`'s own docstring), and `list_active_
        # authorizations_for_node` contributes the source of truth for what
        # is actually granted. Neither alone is the full set an operator
        # needs to see.
        adopted_ids = {d["projectId"] for d in dtos if d.get("projectId")}
        active_rows = await store.list_active_authorizations_for_node(session, node_id)
        active = {row.project_id: _authorization_dto(row) for row in active_rows}
        project_ids = sorted(adopted_ids | set(active.keys()))
        names = await store.get_project_names(session, project_ids)
        authorization_section = _authorization_section(
            node_id, project_ids=project_ids, active=active, names=names, can_manage=can_manage_auth
        )
    else:
        authorization_section = (
            '<h2>Authorizations</h2><p class="warn">This account lacks '
            "<code>nodes.discoveries.read</code> — authorizations are hidden.</p>"
        )

    script = ""
    if token:
        # `json.dumps`, not Python's `!r`: `token` is server-generated and
        # already URL-safe, but `node_id` is operator-chosen text with no
        # character allowlist (see `_candidate_row`'s docstring) -- `json.
        # dumps` is the one function here guaranteed to produce a valid,
        # correctly-escaped JS string literal for either.
        script = (
            "<script>\n"
            f"const CB_TOKEN = {json.dumps(token)};\n"
            f"const CB_NODE_ID = {json.dumps(node_id)};\n"
            f"{_CONTROL_JS}\n"
            "</script>"
        )

    body = f"""
    <h1>Node: {_e(dto['displayName'])}</h1>
    <p class="hint">{_health_tag(dto['health'])} &middot; id <code>{_e(node.id)}</code>
    {' &middot; ' + _e(dto['healthReason']) if dto['healthReason'] else ''}</p>
    {_capabilities_section(dto)}
    {candidates_section}
    {authorization_section}
    {script}
    """
    return _page(f"CodexBridge Control · {dto['displayName']}", body)


# ---------------------------------------------------------------------------
# GET /control/invite — see module docstring, "/control/invite"
# ---------------------------------------------------------------------------


@router.get("/invite", response_class=HTMLResponse)
async def control_invite(
    request: Request,
) -> HTMLResponse:
    await _control_principal(request, permissions.NODES_READ)
    body = """
    <h1>Invite a node</h1>
    <div class="notice">
      <p><strong>Not available yet on this build.</strong> This screen would
      call <code>POST /api/v1/nodes/invite</code> and hand you a one-time
      token plus a ready <code>scripts/enroll_node.py</code> command. Both
      exist — they are issue #76's minimal cut — but they are not in this
      build: they live on a branch this one was not cut from, so the endpoint
      this page needs is genuinely absent from the process serving it.</p>
      <p>This screen lights up once that work merges. Nothing here needs to be
      designed or built again; the gap is which commits this build contains,
      not a missing capability.</p>
      <p>Until then, registering a Bridge Node is the manual, two-machine
      procedure it has always been: add the node's <code>machine_token</code>
      and <code>allowed_projects</code> to <code>registry.json</code> on the
      gateway host, add the matching project entries to the executor's own
      allowlist, and restart both processes —
      <code>docs/project-onboarding.md</code>, "Schema de executor".</p>
    </div>
    """
    return _page("CodexBridge Control · Invite a node", body)
