from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, Field, field_validator, model_validator


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
    # WK-20260902-forge-protocol-and-policy, issue #80/#79. A forge operation
    # travels as its own envelope pair, deliberately not folded into
    # `TASK_DISPATCH`/`TASK_RESULT`: a task dispatch is a coding-agent session
    # that runs inside the provider's sandbox, and a forge operation is the
    # opposite of that on every axis that matters here -- it runs outside the
    # sandbox, on the executor process itself, and it is `SENSITIVE` by
    # construction rather than by what an instruction happens to say (see
    # `shared.policy.forge_operation_policy_level`). Nothing dispatches or
    # wires these yet -- this PR is only the vocabulary the wiring will use.
    FORGE_OPERATION = "forge.operation"
    FORGE_OPERATION_RESULT = "forge.operation_result"
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


class ForgeOperationKind(str, Enum):
    """The only things a forge operation may do, per issue #80/#79.

    Deliberately closed and enumerable -- there is no "run `gh` with
    arbitrary argv" kind, and no member of this enum, present or future,
    deletes an issue in any form. That is not an oversight to fill in later;
    a forge write already happens outside the agent's sandbox, on
    infrastructure this codebase does not control, in the operator's name --
    so the surface it can reach is enumerated by hand, once, here, rather
    than passed through from whatever a caller asks for. A new kind is a
    deliberate, reviewed addition to this class, never something a caller can
    request by naming a string this enum does not already have.

    `shared.policy.forge_operation_policy_level` is the other half of this
    decision: every member here except `ISSUE_LIST` is `SENSITIVE`, and there
    is no field anywhere that lets a caller change that.
    """

    ISSUE_OPEN = "issue_open"
    ISSUE_COMMENT = "issue_comment"
    ISSUE_LIST = "issue_list"
    ISSUE_CLOSE = "issue_close"


# `owner/repo`, and nothing else -- no leading `-` or `.` on either side (a
# leading `-` is how a value smuggles itself into flag position in an argv
# list; see `_REMOTE_NAME_PATTERN`'s own docstring,
# `agent/codex_bridge_agent/git_delivery.py:47`, for the same reasoning
# applied to a git remote name), no doubled slash, no `..` anywhere. This
# plays exactly that role for `ForgeOperationRequest.repo_identity`: the
# executor's forge module (not written in this PR) will eventually place this
# string as a positional argument to `gh`, and a value this pattern rejects
# can never reach that call, because it is validated here, at parse time, on
# both the gateway and the executor -- the same "one definition, two
# importers" shape `PUSHABLE_BRANCH_PATTERN` already uses.
REPO_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ForgeOperationRequest(BaseModel):
    """One forge operation a `FORGE_OPERATION` envelope may carry.

    WK-20260902-forge-protocol-and-policy, issue #80/#79. This model is shape
    and coherence validation ONLY -- it decides nothing about whether an
    operation may run without a human decision. That question belongs to
    `shared.policy.forge_operation_policy_level`, and its answer for every
    kind but `ISSUE_LIST` is unconditionally `SENSITIVE`: no combination of
    the fields below can change that answer. Refusing an incoherent request
    here, at parse time (a comment/close with no `issue_number`, an open with
    no `title`), is better than letting it reach the executor and fail there
    -- the same reasoning `DeliveryRequest` and `PUSHABLE_BRANCH_PATTERN`
    already apply to push.
    """

    kind: ForgeOperationKind
    repo_identity: str = Field(min_length=3, max_length=200)
    title: str | None = Field(default=None, max_length=256)
    body: str | None = Field(default=None, max_length=65536)
    issue_number: int | None = Field(default=None, gt=0)
    # Only meaningful for `ISSUE_LIST`; validated against a closed set below
    # regardless of `kind`, since a value outside it is never a real forge
    # issue state no matter which operation carries it.
    state: str | None = None

    @field_validator("repo_identity")
    @classmethod
    def _validate_repo_identity(cls, value: str) -> str:
        if not REPO_IDENTITY_PATTERN.match(value):
            raise ValueError(
                f"repo_identity {value!r} must look like 'owner/repo' "
                "(no leading '-'/'.', no doubled slash, no '..')"
            )
        return value

    @field_validator("state")
    @classmethod
    def _validate_state(cls, value: str | None) -> str | None:
        allowed = {"open", "closed", "all"}
        if value is not None and value not in allowed:
            raise ValueError(f"state must be one of {sorted(allowed)}, got {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_kind_requires_its_fields(self) -> "ForgeOperationRequest":
        """Recusa no parse é melhor que erro no executor.

        `issue_comment`/`issue_close` name an existing issue; without
        `issue_number` there is nothing to comment on or close.
        `issue_open` creates one; without `title` there is nothing to open.
        """
        if self.kind in (ForgeOperationKind.ISSUE_COMMENT, ForgeOperationKind.ISSUE_CLOSE):
            if self.issue_number is None:
                raise ValueError(f"{self.kind.value} requires issue_number")
        if self.kind is ForgeOperationKind.ISSUE_OPEN:
            if not self.title:
                raise ValueError("issue_open requires title")
        return self


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
