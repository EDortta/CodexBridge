"""What an actor may do, in one table the API and the client both read.

The mobile client has to decide whether to *show* a control before the operator
touches it. Deciding that from a scope string means the client re-implements the
server's authorization rules, and the two drift the first time a scope is split
or renamed — with the client's copy winning, because it decides what the
operator sees.

So the rules live here, once. `GET /api/v1/auth/me` reports this catalogue
evaluated for the caller, and every guarded endpoint is guarded by an entry from
it (`gateway/app/api/auth.py:require_action`). A button the client shows and an
endpoint that answers `403` cannot disagree, because both read this file.

## Only actions this build serves

An entry here is a promise that a served endpoint honours it — the same rule
`probes.CAPABILITIES` follows, and for the same reason: the first cut of the
capability flags advertised machinery no endpoint used, so a client that
believed them got a 404. `codexbridge.task.submit` is therefore still absent:
it exists in the MCP transport and in `users.json`, and no HTTP endpoint of
this contract offers it yet. `codexbridge.task.approve` used to be absent for
the same reason; issue #6's `POST /api/v1/decisions/{id}/approve|reject|
request-revision` is its first HTTP exposure, so it is now `DECISIONS_DECIDE`'s
scope below.

## The three classes

`read` sees state. `operational` changes what an executor is doing.
`administrative` reaches beyond the actor's own projects. The distinction is the
issue's, and it is worth keeping mechanical: a reviewer adding an endpoint has
to choose a class, and choosing `read` for something that cancels a run is a
visible mistake rather than an invisible one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from shared.protocol import Capability


READ_SCOPE = "codexbridge.read"
SUBMIT_SCOPE = "codexbridge.task.submit"
CANCEL_SCOPE = "codexbridge.task.cancel"
APPROVE_SCOPE = "codexbridge.task.approve"
ADMIN_SCOPE = "codexbridge.admin"
# Creating or changing planning entities (epics, issues, epic-issue links).
# Distinct from CANCEL_SCOPE: stopping a session and writing a project plan are
# different capabilities an operator may grant separately.
ISSUES_WRITE_SCOPE = "codexbridge.issues.write"
# Creating a conversation or posting a message to one (issue #10). Distinct
# from ISSUES_WRITE_SCOPE for the same reason that scope is distinct from
# CANCEL_SCOPE: writing a project plan and starting a discussion about it are
# different capabilities an operator may grant separately.
CONVERSATIONS_WRITE_SCOPE = "codexbridge.conversations.write"

READ = "read"
OPERATIONAL = "operational"
ADMINISTRATIVE = "administrative"

CATEGORIES = (READ, OPERATIONAL, ADMINISTRATIVE)


@dataclass(frozen=True)
class Action:
    """One thing an actor may attempt, and what it takes to be allowed to.

    `name` is contract surface: it is returned by `GET /api/v1/auth/me` and a
    client branches on it, so renaming one is a breaking change.
    """

    name: str
    category: str
    scope: str
    summary: str


SESSIONS_READ = Action(
    name="sessions.read",
    category=READ,
    scope=READ_SCOPE,
    summary="List sessions and read one, within the actor's projects.",
)

SESSIONS_READ_LOGS = Action(
    name="sessions.readLogs",
    category=READ,
    scope=READ_SCOPE,
    summary="Read the log stream of a session, redacted.",
)

SESSIONS_EXPLAIN_ERROR = Action(
    name="sessions.explainError",
    category=READ,
    scope=READ_SCOPE,
    summary="Read the recorded evidence for why a session failed.",
)

PROJECTS_READ = Action(
    name="projects.read",
    category=READ,
    scope=READ_SCOPE,
    summary="List projects and read a project's operational summary, within the actor's projects.",
)

SESSIONS_STOP = Action(
    name="sessions.stop",
    category=OPERATIONAL,
    scope=CANCEL_SCOPE,
    summary="Cancel a queued or running session.",
)

SESSIONS_PAUSE = Action(
    name="sessions.pause",
    category=OPERATIONAL,
    scope=CANCEL_SCOPE,
    summary="Pause a running session on a connected executor.",
)

SESSIONS_RESUME = Action(
    name="sessions.resume",
    category=OPERATIONAL,
    scope=CANCEL_SCOPE,
    summary="Resume a paused session on a connected executor.",
)

SESSIONS_RESTART = Action(
    name="sessions.restart",
    category=OPERATIONAL,
    scope=CANCEL_SCOPE,
    summary="Restart a running or paused session on a connected executor.",
)

SESSIONS_READ_ALL_PROJECTS = Action(
    name="sessions.readAllProjects",
    category=ADMINISTRATIVE,
    scope=ADMIN_SCOPE,
    summary="See sessions in every project, not only the actor's own.",
)

DECISIONS_READ = Action(
    name="decisions.read",
    category=READ,
    scope=READ_SCOPE,
    summary="List decisions and read one, within the actor's projects.",
)

# One action for approve/reject/request-revision, matching the MCP transport's
# `approve_codex_task` tool: all three are the same authority to resolve a
# decision, not three separate ones. `codexbridge.task.approve` is the scope
# that tool already requires (`gateway/app/mcp/server.py`), so a token minted
# before this API existed is not silently narrower on it than it was.
DECISIONS_DECIDE = Action(
    name="decisions.decide",
    category=OPERATIONAL,
    scope=APPROVE_SCOPE,
    summary="Approve, reject, or request revision of a pending decision.",
)

MISSIONS_READ = Action(
    name="missions.read",
    category=READ,
    scope=READ_SCOPE,
    summary="List missions and read one, within the actor's projects.",
)

MISSIONS_READ_TIMELINE = Action(
    name="missions.readTimeline",
    category=READ,
    scope=READ_SCOPE,
    summary="Read the recorded timeline of a mission.",
)

MISSIONS_EXPLAIN = Action(
    name="missions.explain",
    category=READ,
    scope=READ_SCOPE,
    summary="Read the recorded evidence for a mission's current state.",
)

MISSIONS_CANCEL = Action(
    name="missions.cancel",
    category=OPERATIONAL,
    scope=CANCEL_SCOPE,
    summary="Cancel a queued or running mission.",
)

MISSIONS_READ_ALL_PROJECTS = Action(
    name="missions.readAllProjects",
    category=ADMINISTRATIVE,
    scope=ADMIN_SCOPE,
    summary="See missions in every project, not only the actor's own.",
)

# Issue #73 Stage 2: Bridge Nodes are fleet-wide, not scoped to a project --
# there is no per-node visible-projects filter the way `PROJECTS_READ` has, so
# this follows `SESSIONS_READ_ALL_PROJECTS`/`MISSIONS_READ_ALL_PROJECTS` and is
# administrative rather than a new scope of its own.
NODES_READ = Action(
    name="nodes.read",
    category=ADMINISTRATIVE,
    scope=ADMIN_SCOPE,
    summary="List Bridge Nodes and read one, across the whole fleet.",
)

# Issue #73 Stage 3 adoption half (WK-20260902-gh73-discovery-adoption).
# Same reasoning as `NODES_READ`: a discovered candidate belongs to a node,
# not to a project the caller may or may not see, so this follows the
# administrative/fleet-wide precedent rather than `visible_projects` scoping.
NODES_DISCOVERIES_READ = Action(
    name="nodes.discoveries.read",
    category=ADMINISTRATIVE,
    scope=ADMIN_SCOPE,
    summary="List the candidates one Bridge Node has discovered.",
)

# Deciding a candidate (`adopt`/`deny`) can create a project, a workspace
# binding, an SCM association and -- when a discovery root or the request
# grants capability -- a `project_authorizations` row. Separate action from
# `NODES_DISCOVERIES_READ` for the same reason `DECISIONS_READ`/
# `DECISIONS_DECIDE` are separate: seeing the queue and deciding it are
# different capabilities an operator may grant independently. Administrative,
# not operational, for the same reason `NODES_READ` is: a discovered
# candidate is not scoped to any project the caller already sees -- often
# there is no project yet -- so this reaches beyond `visible_projects` by
# definition, which is the axis this classification tracks
# (`DECISIONS_DECIDE` stays operational because the task it resolves IS
# already inside the actor's own projects).
NODES_DISCOVERIES_DECIDE = Action(
    name="nodes.discoveries.decide",
    category=ADMINISTRATIVE,
    scope=ADMIN_SCOPE,
    summary="Adopt or deny a discovered candidate.",
)

# Issue #73 Stage 4 (WK-20260902-gh73-authorization-plane): the explicit
# operator grant/revoke of `project_authorizations`, behind `POST
# .../authorize` and `.../revoke`. Administrative and fleet-wide, same
# posture as `NODES_READ`/`NODES_DISCOVERIES_DECIDE`: a `(node, project)`
# authorization pair is not scoped to any project the caller already sees by
# `visible_projects` -- it is a fleet-level decision about what a NODE may do,
# not a project-level one about what a session may do.
#
# `is_allowed` below carries this action's own second gate, the same shape
# `DECISIONS_DECIDE` already has: granting `modify` or `deliver` additionally
# requires `can_approve_sensitive` or `is_admin()`. Unlike `DECISIONS_DECIDE`'s
# gate, this one depends on the REQUEST body (which capabilities are being
# granted), which `require_action`'s dependency cannot see before the body is
# parsed -- so the route calls `is_allowed` a second time, with `capabilities=
# payload.capabilities`, after parsing it. Both calls still funnel through
# this one function; nothing about the rule lives in the route.
NODES_AUTHORIZATIONS_MANAGE = Action(
    name="nodes.authorizations.manage",
    category=ADMINISTRATIVE,
    scope=ADMIN_SCOPE,
    summary="Grant or revoke a Bridge Node's capabilities on a project.",
)

# `Capability` values whose grant requires the same second gate
# `DECISIONS_DECIDE` already applies before a sensitive task can be approved
# -- granting a node the power to write (`modify`) or push (`deliver`) is the
# same class of decision, just aimed at a node instead of a task.
_SENSITIVE_CAPABILITIES = frozenset({Capability.MODIFY, Capability.DELIVER})

EPICS_READ = Action(
    name="epics.read",
    category=READ,
    scope=READ_SCOPE,
    summary="List epics and read one, within the actor's projects.",
)

ISSUES_READ = Action(
    name="issues.read",
    category=READ,
    scope=READ_SCOPE,
    summary="List issues and read one, within the actor's projects.",
)

EPICS_CREATE = Action(
    name="epics.create",
    category=OPERATIONAL,
    scope=ISSUES_WRITE_SCOPE,
    summary="Create an epic in one of the actor's projects.",
)

ISSUES_CREATE = Action(
    name="issues.create",
    category=OPERATIONAL,
    scope=ISSUES_WRITE_SCOPE,
    summary="Create an issue in one of the actor's projects.",
)

ISSUES_UPDATE = Action(
    name="issues.update",
    category=OPERATIONAL,
    scope=ISSUES_WRITE_SCOPE,
    summary="Change status, priority, labels, assignee or dependencies of an issue.",
)

EPICS_LINK_ISSUE = Action(
    name="epics.linkIssue",
    category=OPERATIONAL,
    scope=ISSUES_WRITE_SCOPE,
    summary="Attach an issue to an epic.",
)

CONVERSATIONS_READ = Action(
    name="conversations.read",
    category=READ,
    scope=READ_SCOPE,
    summary="List conversations and read one, within the actor's projects.",
)

CONVERSATIONS_CREATE = Action(
    name="conversations.create",
    category=OPERATIONAL,
    scope=CONVERSATIONS_WRITE_SCOPE,
    summary="Start a conversation linked to at least one product entity.",
)

CONVERSATIONS_POST_MESSAGE = Action(
    name="conversations.postMessage",
    category=OPERATIONAL,
    scope=CONVERSATIONS_WRITE_SCOPE,
    summary="Post a message to a conversation.",
)

# Order is the reported order. Grouped by class, read first, so a client that
# renders the list without sorting produces something sensible.
CATALOGUE: tuple[Action, ...] = (
    SESSIONS_READ,
    SESSIONS_READ_LOGS,
    SESSIONS_EXPLAIN_ERROR,
    PROJECTS_READ,
    MISSIONS_READ,
    MISSIONS_READ_TIMELINE,
    MISSIONS_EXPLAIN,
    EPICS_READ,
    ISSUES_READ,
    CONVERSATIONS_READ,
    SESSIONS_STOP,
    SESSIONS_PAUSE,
    SESSIONS_RESUME,
    SESSIONS_RESTART,
    MISSIONS_CANCEL,
    EPICS_CREATE,
    ISSUES_CREATE,
    ISSUES_UPDATE,
    EPICS_LINK_ISSUE,
    CONVERSATIONS_CREATE,
    CONVERSATIONS_POST_MESSAGE,
    SESSIONS_READ_ALL_PROJECTS,
    DECISIONS_READ,
    DECISIONS_DECIDE,
    MISSIONS_READ_ALL_PROJECTS,
    NODES_READ,
    NODES_DISCOVERIES_READ,
    NODES_DISCOVERIES_DECIDE,
    NODES_AUTHORIZATIONS_MANAGE,
)


def is_allowed(
    principal,
    action: Action,
    *,
    capabilities: Iterable[Capability | str] | None = None,
) -> bool:
    """Whether `principal` may perform `action`.

    Delegates to `AuthenticatedPrincipal.has_scope`, which is also what the
    endpoint guard calls. Re-deriving the answer here — even correctly — would
    create a second rule that can drift from the one being enforced, and this
    one is the one the client is told about.

    `decisions.decide` carries one extra condition on top of the scope:
    `can_approve_sensitive` (or admin), the same gate
    `gateway/app/mcp/server.py:approve_codex_task` already applies before this
    API existed. It is a property of the account, not of the scope grant — a
    token can carry `codexbridge.task.approve` for a user the operator never
    trusted with a sensitive call — and it belongs here rather than as a second
    check inside the route: `GET /api/v1/auth/me` reports this same function, so
    a route that checked it separately would tell the client "you may" while the
    endpoint answered 403.

    `nodes.authorizations.manage` carries the same-SHAPED second gate, but
    only when `capabilities` names `modify` or `deliver` — granting a node
    `read`/`test` needs only the base administrative scope, the same as
    adoption's own `autoAuthorize` ceiling (`shared.protocol.
    AUTO_AUTHORIZABLE_CAPABILITIES`). `capabilities=None` (the default, and
    what `GET /api/v1/auth/me`'s `report_for` below always passes) skips this
    half of the check: whether a given request's capability list crosses
    into sensitive territory is a fact about that request, not about the
    actor in the abstract, so the catalogue reports only the baseline "may
    this actor ever manage authorizations at all" — the route re-calls this
    function with the real `capabilities` once the request body is parsed,
    for the answer that actually gates the write.

    That second gate reads `"admin" in principal.roles` here, NOT
    `principal.is_admin()` the way `decisions.decide` above reads it — a
    deliberate, load-bearing difference, not a typo. `is_admin()` is
    `"admin" in principal.roles or "codexbridge.admin" in principal.scopes`.
    `decisions.decide`'s own scope is `codexbridge.task.approve`, disjoint
    from `codexbridge.admin`, so for THAT action `is_admin()` genuinely adds
    something `has_scope` did not already establish. `nodes.authorizations.
    manage`'s own base scope IS `codexbridge.admin` (`ADMIN_SCOPE` — the
    same administrative class `nodes.read`/`nodes.discoveries.decide` use,
    per this PR's own brief). For an action whose scope already equals
    `codexbridge.admin`, `principal.has_scope(action.scope)` and
    `principal.is_admin()` are THE SAME PREDICATE (`has_scope` computes
    `is_admin() or scope in scopes`, and here `scope IS "codexbridge.admin"`
    — the `or` clause folds into the first). Gating on `is_admin()` a second
    time after `allowed` already required it would make the whole condition
    tautological: every principal who clears the base scope check would
    automatically clear this one too, and `can_approve_sensitive` would
    never once be the deciding factor — the exact escalation this gate
    exists to close. Checking the ROLE directly keeps the two properties
    `docs/control-plane.md`'s Stage 4 section names distinct: a principal's
    token may carry `codexbridge.admin` for fleet-visibility reasons
    (`nodes.read`, `nodes.discoveries.read`) without that principal being
    trusted for `modify`/`deliver` — the same distinction `can_approve_
    sensitive` already draws for `decisions.decide`.
    """
    allowed = principal.has_scope(action.scope)
    if action is DECISIONS_DECIDE:
        allowed = allowed and (principal.can_approve_sensitive or principal.is_admin())
    if action is NODES_AUTHORIZATIONS_MANAGE and capabilities is not None:
        requested = set()
        for capability in capabilities:
            try:
                requested.add(capability if isinstance(capability, Capability) else Capability(capability))
            except ValueError:
                continue
        if requested & _SENSITIVE_CAPABILITIES:
            allowed = allowed and (principal.can_approve_sensitive or "admin" in principal.roles)
    return allowed


def report_for(principal) -> list[dict]:
    """The catalogue evaluated for one actor, in contract shape."""
    return [
        {
            "action": action.name,
            "category": action.category,
            "requiredScope": action.scope,
            "allowed": is_allowed(principal, action),
        }
        for action in CATALOGUE
    ]
