from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field, field_validator


EXECUTOR_TOKEN_HEADER = "X-Executor-Token"
"""Header carrying the executor machine token on the `/agent/ws` handshake.

The token used to travel as a query parameter, which put it verbatim in every
access log on the path — 37 lines in the gateway journal and 70 in nginx's,
counted on 2026-08-10 (#15). A WebSocket handshake is an HTTP request and
carries headers normally, so the credential does not belong in the URL.
"""


class AgentEngine(str, Enum):
    """Which development-agent CLI runs a task's instruction.

    WK-20260830-chatgpt-entry-provider-and-delivery / sibling of issue #41
    ("generic development-agent provider contract"), entered here as `#41a`.
    Named `engine`, deliberately not `agent`: that word already names four
    different things in this codebase (`/agent/ws`, `codex-bridge-agent`,
    `AgentEnvelope`, `AgentMessageType`).

    `CODEX` and `CLAUDE` are implemented by a real runner
    (`agent/codex_bridge_agent/runners/`). The rest are registered so a
    dispatch naming one fails with a typed `engine_not_implemented:<engine>`
    instead of an `AttributeError` or a silent fallback to Codex -- the seven
    CLIs installed on the executor are candidates, not commitments (57a
    surface inventory, 2026-08-24: "Codex stays the only provider for now,
    multi-provider is horizon" -- this migration is that horizon arriving,
    scoped to exactly two engines).
    """

    CODEX = "codex"
    CLAUDE = "claude"
    CURSOR_AGENT = "cursor-agent"
    GEMINI = "gemini"
    OPENCODE = "opencode"
    AIDER = "aider"


# Engines with a real `Runner` implementation as of this migration. Anything
# else in `AgentEngine` is a declared candidate with no code behind it yet --
# checked by the executor's `RunnerPool`, not by this module (the gateway
# accepts any `AgentEngine` value; only the executor knows what it can run).
IMPLEMENTED_ENGINES = frozenset({AgentEngine.CODEX.value, AgentEngine.CLAUDE.value})


class TaskMode(str, Enum):
    ANALYZE = "analyze"
    REVIEW = "review"
    EDIT = "edit"
    TEST = "test"
    IMPLEMENT = "implement"


class Capability(str, Enum):
    """What a node is authorized to do to a project, per issue #73.

    #73 requires the authorization model to be "capability-oriented rather
    than assuming blanket filesystem access", and says the vocabulary should
    be established "by the implementation issues and existing security
    contracts". So this is DERIVED from `TaskMode`, never parallel to it:
    `CAPABILITY_MODES` below is the whole mapping, and `allowed_modes` stays
    the single enforcement point it already is
    (`gateway/app/services/store.py:create_task`, and -- new in this work --
    the executor's own `_handle_dispatch`).

    Introducing a second, independent permission vocabulary is exactly the
    "parallel concepts" #73 warns against: it would need its own enforcement,
    its own tests, and its own drift.

    `DELIVER` is the one value with no `TaskMode` behind it, because delivery
    is not a mode -- it is `SubmitTaskRequest.delivery`
    (`shared.protocol.DeliveryRequest`), gated separately by
    `PUSHABLE_BRANCH_PATTERN` and the `codexbridge.task.approve` scope. It is
    named here so an authorization can withhold it, not to move that gate.
    """

    READ = "read"
    TEST = "test"
    MODIFY = "modify"
    DELIVER = "deliver"


# The only definition of which capability grants which task modes. Imported by
# the gateway (`services/store.py`) and by the executor
# (`agent/codex_bridge_agent/service.py`) so the two sides cannot drift on
# what a capability means -- the same "one definition, several importers"
# shape `STOPPABLE_TASK_STATES` and `PUSHABLE_BRANCH_PATTERN` already have.
#
# `DELIVER` maps to no mode on purpose (see `Capability.DELIVER`).
CAPABILITY_MODES: dict[Capability, frozenset[TaskMode]] = {
    Capability.READ: frozenset({TaskMode.ANALYZE, TaskMode.REVIEW}),
    Capability.TEST: frozenset({TaskMode.TEST}),
    Capability.MODIFY: frozenset({TaskMode.EDIT, TaskMode.IMPLEMENT}),
    Capability.DELIVER: frozenset(),
}


def capabilities_to_modes(capabilities: Iterable[Capability | str]) -> frozenset[TaskMode]:
    """The task modes a capability set permits. Unknown values are ignored.

    Ignoring rather than raising is deliberate and safe in this direction: an
    unknown capability grants nothing, so a newer gateway announcing a
    capability an older executor has never heard of narrows the executor's
    behaviour instead of crashing its dispatch loop. The reverse direction
    (an unknown value WIDENING access) cannot happen here, because a value
    absent from `CAPABILITY_MODES` contributes no modes.
    """
    modes: set[TaskMode] = set()
    for capability in capabilities:
        try:
            key = Capability(capability)
        except ValueError:
            continue
        modes |= CAPABILITY_MODES[key]
    return frozenset(modes)


# What a discovery root grants automatically, when it grants anything at all
# (`DiscoveryRoot.auto_authorize`). Never more than this by announcement:
# `MODIFY` and `DELIVER` require an explicit, audited operator grant, because
# #73 is unambiguous that "a node cannot grant itself project authorization
# merely by reporting a discovery".
AUTO_AUTHORIZABLE_CAPABILITIES = frozenset({Capability.READ, Capability.TEST})


class TaskState(str, Enum):
    QUEUED = "queued"
    WAITING_EXECUTOR = "waiting_executor"
    AWAITING_APPROVAL = "awaiting_approval"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    RESTARTING = "restarting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    LOST = "lost"


# States from which a cancel is meaningful, shared by the HTTP `/stop` route
# and the MCP `cancel_codex_task` tool. A single definition so the two
# surfaces cannot drift the way they did before issue #17's review caught
# `cancel_codex_task` silently no-op'ing on `paused`/`pausing`/`resuming`/
# `restarting` while `/stop` already covered them.
STOPPABLE_TASK_STATES = frozenset(
    {
        TaskState.QUEUED.value,
        TaskState.WAITING_EXECUTOR.value,
        TaskState.PAUSING.value,
        TaskState.PAUSED.value,
        TaskState.RESUMING.value,
        TaskState.RESTARTING.value,
        TaskState.RUNNING.value,
        TaskState.AWAITING_APPROVAL.value,
    }
)

# Default window (seconds) a cancelled-but-unacknowledged task stays worth
# resending `task.cancel` for on executor reconnect. One literal, referenced
# by `Settings.cancel_replay_max_age_seconds`, `AgentHub.__init__` and
# `store.list_tasks_requiring_cancel_replay` so the three cannot drift apart.
DEFAULT_CANCEL_REPLAY_MAX_AGE_SECONDS = 86400

# Same idea, for tasks stuck in PAUSING/RESUMING/RESTARTING with no `task.ack`
# (issue #17 council, "the sweep skeptic"): `list_tasks_requiring_control_replay`
# used to have no bound at all, unlike its cancel sibling above, so a
# year-old pending control was replayed on every reconnect forever.
DEFAULT_CONTROL_REPLAY_MAX_AGE_SECONDS = 86400

# Upper bound accepted for either replay window. `datetime.now(tz) -
# timedelta(seconds=...)` raises `OverflowError` well before this — the cap
# exists so a misconfigured operator gets a rejected setting at startup
# instead of every `AgentHub.register()` crashing after `websocket.accept()`,
# which left a dead connection in `hub.connections` with no way to close it
# (issue #17 council, "the second caller"). 10 years is generous against any
# realistic "replay indefinitely" intent without going anywhere near the
# `timedelta` ceiling (~2.7e11 seconds).
MAX_REPLAY_MAX_AGE_SECONDS = 315360000


class PolicyLevel(str, Enum):
    READ = "read"
    CONTROLLED_WRITE = "controlled_write"
    SENSITIVE = "sensitive"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class AgentMessageType(str, Enum):
    HELLO = "hello"
    HELLO_ACK = "hello_ack"
    HEARTBEAT = "heartbeat"
    TASK_DISPATCH = "task.dispatch"
    TASK_ACK = "task.ack"
    TASK_LOG = "task.log"
    TASK_RESULT = "task.result"
    TASK_CANCEL = "task.cancel"
    TASK_PAUSE = "task.pause"
    TASK_RESUME = "task.resume"
    TASK_RESTART = "task.restart"
    TASK_CANCELLED = "task.cancelled"
    ERROR = "error"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    # Distinct from REJECTED so a Decision DTO can tell an operator "send this
    # back for changes" apart from "this will not run" (issue #6). Both still
    # cancel the task: there is no protocol capability to hold it open for a
    # resubmission, so pretending otherwise would be the same failure
    # `routes/sessions.py` names for pause/resume/restart — a control that
    # reports success and changes nothing.
    REVISION_REQUESTED = "revision_requested"


class DiscoveredState(str, Enum):
    """Lifecycle of something a node can see, per issue #73.

    #73 is explicit: "Do not collapse these into a single `enabled` boolean."
    The point of five values rather than two is that they answer different
    operator questions, and merging any pair loses one of them:

    * `DISCOVERED` -- the node reported it; Control has done nothing. This is
      NOT permission to operate it ("Discovery is not authorization").
    * `ADOPTED` -- the operator accepted it as a known project and bound it to
      a node, but granted no capability yet ("Adoption does not automatically
      grant every operational capability").
    * `AUTHORIZED` -- at least one capability is granted for this node.
    * `DENIED` -- the operator refused it. Distinct from `DISCOVERED` so a
      re-announcement does not resurrect it into the adoption queue every
      time the node reconnects.
    * `STALE` -- last seen in an earlier inventory, absent from the current
      one. Distinct from `DENIED` (nobody decided anything) and from
      absence (the row and its history survive; #73: "Offline/stale
      information must be visibly distinguished from current observations").
    """

    DISCOVERED = "discovered"
    ADOPTED = "adopted"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    STALE = "stale"


class BindingState(str, Enum):
    """Whether a Project-on-a-Node workspace is usable right now.

    Separate from `DiscoveredState`, which tracks the operator's decision.
    This tracks the observed world: a binding the operator authorized months
    ago is `UNAVAILABLE` the moment the directory stops being a readable git
    repository, without any decision changing.
    """

    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class NodeHealth(str, Enum):
    """A Bridge Node's operational condition, derived at read time.

    Mirrors the shape `ProjectHealth` already has in
    `docs/api/codex-bridge.openapi.yaml` — derived, never stored, so a
    gateway restart cannot leave a node asserting health nobody re-measured.
    """

    OK = "ok"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class DiscoveryRoot(BaseModel):
    """One directory tree a node is configured to scan, and what that grants.

    Issue #73: "No recursive whole-machine discovery by default. Discovery
    roots must themselves be explicitly configured." There is no default
    root; a node with no configured roots discovers nothing.

    `auto_authorize` is the operator's standing, auditable grant for
    everything under this one tree — the decision is made once per tree
    instead of once per project, which is the friction this work removes. It
    is capped at `AUTO_AUTHORIZABLE_CAPABILITIES` by the validator below:
    `MODIFY` and `DELIVER` are never obtainable by announcement, only by an
    explicit per-project grant that names an operator. Empty (the default)
    means the tree is scanned and its candidates queue for adoption, granting
    nothing at all.

    `path` is compared as a STRING against what the node announces, never
    resolved — the gateway runs on a different host and cannot see the node's
    disk, so it has no path to canonicalize. Canonicalization and ancestry
    are enforced where they can be: on the node
    (`agent/codex_bridge_agent/config.py:resolve_auto_project`, and
    `shared/project_discovery.py`, which never follows a symlink and never
    ascends).
    """

    path: str = Field(min_length=1, max_length=2048)
    auto_authorize: list[Capability] = Field(default_factory=list)

    @field_validator("auto_authorize")
    @classmethod
    def _refuse_non_auto_authorizable(cls, value: list[Capability]) -> list[Capability]:
        forbidden = [c for c in value if c not in AUTO_AUTHORIZABLE_CAPABILITIES]
        if forbidden:
            raise ValueError(
                "auto_authorize may only grant "
                f"{sorted(c.value for c in AUTO_AUTHORIZABLE_CAPABILITIES)}; "
                f"{sorted(c.value for c in forbidden)} require an explicit per-project grant "
                "(issue #73: a node cannot grant itself project authorization by reporting a discovery)"
            )
        return value


class EngineAvailability(BaseModel):
    """Whether one `AgentEngine` can actually run on this node, right now.

    Issue #73 Stage 2 asks a node for its "available execution engines". Three
    different facts get confused under that word, so all three are carried
    separately:

    * `implemented` — a `Runner` exists in this codebase for the engine. A
      compile-time claim, the same on every node running the same version.
    * `available` — the binary answered on this machine when probed. A runtime
      fact, and the only one that predicts whether a dispatch will start.
    * `version` — what the binary reported, when it reported anything.

    Collapsing them loses the two cases the operator most needs to see: an
    engine this build supports but this machine lacks (`implemented` and not
    `available` — install it), and an engine present on the machine that no
    runner can drive (`available` and not `implemented` — a code gap, not an
    ops one). `detail` carries the reason a probe failed, never a stack trace
    and never a path.
    """

    engine: str = Field(min_length=1, max_length=64)
    implemented: bool = False
    available: bool = False
    version: str | None = Field(default=None, max_length=200)
    detail: str | None = Field(default=None, max_length=400)


class NodeAnnouncement(BaseModel):
    """What a node reports about itself when it connects (`hello` payload).

    Issue #73 Stage 2. Deliberately carries **no identity**: the node is the
    one the authenticated `executor_id` already maps to. "Node identity must
    survive reconnects and must not be inferred from mutable hostname/IP
    alone" — accepting a self-declared id would also let a node claim another
    node's row, which is the announcement-as-authorization failure #73 names.

    Nothing here is a permission. `capabilities` is what the node's own
    configuration would *permit* it to do; what it may actually do to a given
    project still lives in `project_authorizations`, written by the operator.
    The gateway stores this as an observation with a timestamp, so a stale
    inventory is visibly stale rather than silently believed.

    `discovery_root_count` is a count, not the paths. Absolute paths are
    sensitive operational data (`docs/api/README.md`); the fleet surface needs
    to answer "is this node configured to discover anything at all", which a
    count answers without putting a filesystem layout in every client.
    """

    agent_version: str | None = Field(default=None, max_length=64)
    os: str | None = Field(default=None, max_length=120)
    arch: str | None = Field(default=None, max_length=60)
    engines: list[EngineAvailability] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    max_concurrent_tasks: int = Field(default=1, ge=0, le=1000)
    discovery_root_count: int = Field(default=0, ge=0)

    @field_validator("engines")
    @classmethod
    def _refuse_duplicate_engines(cls, value: list[EngineAvailability]) -> list[EngineAvailability]:
        seen = [engine.engine for engine in value]
        duplicated = sorted({name for name in seen if seen.count(name) > 1})
        if duplicated:
            raise ValueError(f"engine reported more than once: {duplicated}")
        return value


def node_health(
    *,
    live: bool,
    enabled: bool,
    ever_seen: bool,
    health_reason: str | None = None,
) -> "NodeHealth":
    """Derive a node's health from facts, at read time, never from a column.

    The order matters and is not arbitrary. A node nobody has ever heard from
    is `UNKNOWN`, not `OFFLINE`: "never connected" and "was here and went
    away" are different problems with different fixes, and #73 requires that
    "offline/stale information must be visibly distinguished from current
    observations". A disabled node reads `OFFLINE` while it is not live —
    saying `DEGRADED` about a machine that is simply switched off invents an
    incident. `DEGRADED` is reserved for a node that is answering but that
    the operator or the node itself has flagged.
    """

    if not ever_seen:
        return NodeHealth.UNKNOWN
    if not live:
        return NodeHealth.OFFLINE
    if not enabled or health_reason:
        return NodeHealth.DEGRADED
    return NodeHealth.OK


class ProjectRegistration(BaseModel):
    project_id: str
    name: str
    path: str
    allowed_modes: list[TaskMode] = Field(default_factory=lambda: list(TaskMode))
    max_timeout_seconds: int = 3600
    sensitive_patterns: list[str] = Field(default_factory=list)
    enabled: bool = True


class ExecutorRegistration(BaseModel):
    executor_id: str
    display_name: str
    machine_token: str
    max_concurrent_tasks: int = 1
    allowed_projects: list[str]
    enabled: bool = True
    expected_timezone: str = "America/Sao_Paulo"
    expected_online_windows: list[str] = Field(default_factory=list)
    # WK-20260901-control-plane-nodes-and-engines, issue #73 Stage 2. The
    # directory trees this node may scan, and what each tree grants standing.
    # Empty (the default) preserves today's behaviour exactly: no discovery,
    # no announcement, only the hand-registered `allowed_projects` above.
    #
    # Deliberately on the executor's registration rather than a global
    # setting: #73 requires the model to support a fleet, and two nodes of the
    # same fleet legitimately hold different trees at different paths.
    discovery_roots: list[DiscoveryRoot] = Field(default_factory=list)


# A branch a pre-authorized push may target. `development` by name, or any
# `feature/...` branch -- never `main`/`master` (excluded by not matching, not
# by a separate denylist: this is the ONLY definition of "pushable", imported
# by both gateway (`shared/policy.py`) and executor
# (`agent/codex_bridge_agent/service.py`), the same "one definition, two
# importers" shape `STOPPABLE_TASK_STATES` already uses to keep two surfaces
# from drifting apart. ASCII only, matching the branch-naming rule in
# `.docs/workflows/git-delivery.md`.
PUSHABLE_BRANCH_PATTERN = re.compile(r"^(development|feature/[a-zA-Z0-9][a-zA-Z0-9/_-]{0,120})$")

# An `issue_ref` naming the source of a `start_development_task` request.
# Deliberately excludes `/` and `.` in every form but the fixed `docs:`/`gh:`
# prefixes, so no value that reaches this pattern can ever traverse out of a
# project root once the executor turns it into a `Path()` (see
# `agent/codex_bridge_agent/instructions.py`). Forms:
#   - `local:<id>`   -- an `IssueModel` row, resolved by the gateway.
#   - `docs:NNN`/`NNN` -- a file under the target repo's `docs/issues/`,
#     resolved by the EXECUTOR (the gateway never learns a project's real
#     path -- `docs/architecture.md`).
#   - `gh:N`         -- accepted syntactically, always rejected with
#     `issue_source_unsupported`: GitHub issue ingestion has no owner in this
#     codebase yet (council review, finding F18). Better to say so than to
#     improvise a second id space.
ISSUE_REF_PATTERN = re.compile(r"^(local:[A-Za-z0-9-]{1,128}|docs:\d{1,6}|gh:\d{1,9}|\d{1,6})$")


class DeliveryRequest(BaseModel):
    """What the requester authorized the executor to do with git, once a task

    finishes successfully. WK-20260830-chatgpt-entry-provider-and-delivery,
    slice of issue #51 ("delivery contract").

    Naming a branch here, together with `allow_push=True`, IS the human
    permission `.docs/workflows/git-delivery.md` requires before a branch is
    created or a push is made -- it is recorded (see
    `shared.policy.evaluate_task_policy` and `store.create_task`), not
    inferred. `main`/`master` are refused twice: `PUSHABLE_BRANCH_PATTERN`
    will not match them here, and the executor re-checks independently in
    `agent/codex_bridge_agent/git_delivery.py` -- a compromised gateway must
    not be able to grant `main` on its own say-so.
    """

    branch: str
    allow_push: bool = False
    base_branch: str = "development"
    remote: str = "origin"
    commit_subject: str | None = Field(default=None, max_length=200)


class SubmitTaskRequest(BaseModel):
    executor_id: str
    project_id: str
    instruction: str = Field(min_length=1, max_length=12000)
    mode: TaskMode
    timeout_seconds: int = Field(ge=30, le=86400)
    priority: TaskPriority = TaskPriority.NORMAL
    run_when_available: bool = False
    expires_at: datetime
    require_destructive_approval: bool = True
    # Everything below is new in WK-20260830-chatgpt-entry-provider-and-delivery
    # and defaults such that a payload built against the pre-existing schema
    # (`submit_codex_task`'s JSON Schema in `gateway/app/mcp/tools.py`, which
    # still lists none of these) still validates byte for byte.
    engine: AgentEngine = AgentEngine.CODEX
    issue_ref: str | None = Field(default=None, max_length=512)
    delivery: DeliveryRequest | None = None


class ContinueSessionRequest(BaseModel):
    task_id: str
    instruction: str = Field(min_length=1, max_length=12000)
    timeout_seconds: int = Field(ge=30, le=86400)


class AgentEnvelope(BaseModel):
    message_id: str
    executor_id: str
    sent_at: datetime
    type: AgentMessageType
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    ok: bool = True
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
