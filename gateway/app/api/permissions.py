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
believed them got a 404. `codexbridge.task.submit` and
`codexbridge.task.approve` are therefore absent: they exist in the MCP transport
and in `users.json`, and no HTTP endpoint of this contract offers them yet.

## The three classes

`read` sees state. `operational` changes what an executor is doing.
`administrative` reaches beyond the actor's own projects. The distinction is the
issue's, and it is worth keeping mechanical: a reviewer adding an endpoint has
to choose a class, and choosing `read` for something that cancels a run is a
visible mistake rather than an invisible one.
"""

from __future__ import annotations

from dataclasses import dataclass


READ_SCOPE = "codexbridge.read"
SUBMIT_SCOPE = "codexbridge.task.submit"
CANCEL_SCOPE = "codexbridge.task.cancel"
ADMIN_SCOPE = "codexbridge.admin"

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

# Order is the reported order. Grouped by class, read first, so a client that
# renders the list without sorting produces something sensible.
CATALOGUE: tuple[Action, ...] = (
    SESSIONS_READ,
    SESSIONS_READ_LOGS,
    SESSIONS_EXPLAIN_ERROR,
    PROJECTS_READ,
    SESSIONS_STOP,
    SESSIONS_PAUSE,
    SESSIONS_RESUME,
    SESSIONS_RESTART,
    SESSIONS_READ_ALL_PROJECTS,
)


def is_allowed(principal, action: Action) -> bool:
    """Whether `principal` may perform `action`.

    Delegates to `AuthenticatedPrincipal.has_scope`, which is also what the
    endpoint guard calls. Re-deriving the answer here — even correctly — would
    create a second rule that can drift from the one being enforced, and this
    one is the one the client is told about.
    """
    return principal.has_scope(action.scope)


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
