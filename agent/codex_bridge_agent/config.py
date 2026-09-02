from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from shared.project_discovery import build_project_id_index
from shared.protocol import ProjectRegistration


class AgentSettings(BaseSettings):
    gateway_ws_url: str = "ws://127.0.0.1:8080/agent/ws"
    executor_id: str = "T610"
    machine_token: str = "replace-with-long-random-token"
    # Issue #76 (minimal cut). When set, `resolve_machine_token` below prefers
    # this over the static `machine_token` field: `scripts/enroll_node.py`
    # writes the value `POST /api/v1/nodes/enroll` returns straight into this
    # file with `0600` permissions, so an operator adopting a new machine
    # never has to copy a secret into `.env` by hand -- the exact habit issue
    # #76 exists to end. `machine_token` stays the default for an operator
    # still on the `registry.json` + static-token flow this build shipped
    # with before; nothing about that flow changes.
    machine_token_file: str | None = None
    allowed_projects_file: str = str(Path("examples/agent-projects.json").resolve())
    # WK-20260830-chatgpt-entry-provider-and-delivery. Opt-in, unset by
    # default: when set, a `project_id` not found in `allowed_projects_file`
    # is looked up as a real git repository somewhere under this root
    # (`shared.project_discovery`, the same walk `scripts/discover_projects.py`
    # runs) instead of being refused outright.
    #
    # This relaxes -- for whoever sets it -- one specific layer of the
    # defense-in-depth chain `docs/project-onboarding.md` documents (layer 7,
    # "existência do project_id na allowlist do agente", the one that still
    # holds even if the gateway itself is compromised): the boundary moves
    # from "this exact project_id was registered by hand" to "this project_id
    # names a real repo somewhere under this one directory tree". It does
    # NOT reach the gateway's own, separate `resolve_project_reference` gate
    # (`gateway/app/services/store.py`) -- a project still has to be
    # registered in the gateway's `registry.json` before ChatGPT can name it
    # at all; this setting only removes the SECOND, executor-local
    # registration step for anything already inside the root.
    #
    # Deliberately per-operator, not the shipped default: an operator who
    # wants CodexBridge to reach any current or future project under one
    # directory sets this once; an operator who wants a short, curated,
    # explicit list leaves it unset and keeps using `allowed_projects_file`
    # alone, exactly as before this setting existed.
    auto_project_root: str | None = None
    # WK-20260902-gh73-discovery-report, issue #73 Stage 3. The directory
    # trees THIS node scans for git repositories to propose as discovery
    # candidates -- empty by default, so an operator who never sets it keeps
    # today's behaviour exactly: no scan loop starts at all
    # (`AgentService._discovery_loop`).
    #
    # NOT `shared.protocol.ExecutorRegistration.discovery_roots`, even though
    # the names and the `path` strings must line up for the two to cooperate.
    # That one is the OPERATOR's registry entry (on the gateway) saying what a
    # tree grants automatically once something is reported under it. This one
    # is the NODE's own decision about which parts of ITS filesystem it is
    # willing to walk at all -- only the node can make that call, because only
    # the node has the filesystem. A discovery report never grants anything by
    # itself either way (`gateway/app/services/store.py:record_discovery_report`);
    # this setting only controls what gets PROPOSED, never what gets AUTHORIZED.
    #
    # A plain comma-separated string in the environment, like every other
    # list-shaped setting in this codebase (`Settings.mcp_bearer_tokens`,
    # `.oauth_allowed_client_ids`, ...) -- pydantic-settings would otherwise
    # require JSON-encoding a `list[str]` env var, which nothing else here
    # does. See `_split_comma_separated` below.
    discovery_roots: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Own interval, deliberately not derived from or coupled to
    # `heartbeat_interval_seconds`: a filesystem walk over a real operator
    # root (247 repositories, in the root that motivated this work) is not
    # something to repeat every 15 seconds, and `_discovery_loop` runs as its
    # own task precisely so a slow scan can never delay a heartbeat or a
    # dispatch. One scan right after HELLO, then one every this-many seconds.
    discovery_scan_interval_seconds: int = 3600
    codex_bin: str = "codex"
    # WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a.
    claude_bin: str = "claude"
    heartbeat_interval_seconds: int = 15
    reconnect_min_seconds: int = 2
    reconnect_max_seconds: int = 30
    max_concurrent_tasks: int = 1
    max_prompt_chars: int = 12000
    max_diff_chars: int = 120000
    max_result_chars: int = 200000
    # Issue #34: a write-intending task's mode (edit/implement) is the normal
    # way to opt into `-s workspace-write` (see `service.py:_handle_dispatch`).
    # This is the machine-level kill switch beneath that: an operator who wants
    # one specific executor to never write, regardless of what any task asks
    # for, sets `CODEX_BRIDGE_AGENT_ALLOW_WORKSPACE_WRITE=false` and every
    # dispatch on that host runs `-s read-only` no matter its policy level —
    # the same "last barrier on this machine" role `allowed_projects_file`
    # already plays for project scope (`docs/software-overview.md`).
    allow_workspace_write: bool = True
    # WK-20260830-chatgpt-entry-provider-and-delivery, slice of #51. Same
    # "last barrier on this machine" shape as `allow_workspace_write` above:
    # an operator who wants one specific executor to never commit/push,
    # regardless of what any pre-authorized request asks for, sets
    # `CODEX_BRIDGE_AGENT_ALLOW_GIT_DELIVERY=false`. Defaults to False --
    # unlike `allow_workspace_write`, this is a NEW capability with no
    # existing behavior to preserve, so the safe default is "off until an
    # operator turns it on", not "on until an operator turns it off".
    allow_git_delivery: bool = False
    git_author_name: str = "CodexBridge"
    git_author_email: str = "codexbridge@invalid"
    git_push_timeout_seconds: float = 120
    # WK-20260902-forge-protocol-and-policy, issue #80/#79. Same "last
    # barrier on this machine" shape as `allow_git_delivery` above, and the
    # same reasoning: a new capability with no existing behavior to
    # preserve, so the safe default is off until an operator turns it on.
    # This flag alone is table stakes, not a bypass -- even with it True,
    # every forge WRITE still stops at the human approval gate
    # (`shared.policy.forge_operation_policy_level`: there is no
    # pre-authorization for a forge write, structurally, on purpose). Turning
    # this on lets an executor run forge operations at all; it cannot let one
    # skip approval.
    allow_forge_operations: bool = False
    # The `gh` CLI binary this executor invokes for forge operations -- the
    # same "operator can point at a shim or a pinned path" role `codex_bin`
    # and `claude_bin` already play above. Not called anywhere yet: this PR
    # is protocol and policy only.
    forge_gh_bin: str = "gh"
    # Upper bound on a single forge operation (issue open/comment/close/list).
    # Short on purpose: a forge operation is one bounded API call through
    # `gh`, not a coding-agent session -- `git_push_timeout_seconds` above
    # sets the analogous bound for git delivery.
    forge_operation_timeout_seconds: float = 60
    # WK-20260902-forge-binding, issue #79/#80 (PR B4). Upper bound on
    # `git remote get-url <remote>` -- the live check `run_forge_operation`
    # runs before EVERY operation (write or read) to confirm the gateway's
    # declared `repo_identity` still matches this workspace's real remote
    # (`docs/control-plane.md`'s "the gateway guards the declared, the
    # executor confirms the real"). Short and separate from
    # `forge_operation_timeout_seconds`: this is a local, no-network `git`
    # read, not a `gh` call to a real API, so it should never take anywhere
    # near as long, and a caller reading logs should be able to tell which
    # of the two stalled.
    forge_remote_check_timeout_seconds: float = 10
    # WK-20260902-forge-github-module, issue #80/#79. Where `gh_tool.run_gh`
    # looks, under `project_root`, for the GitHub token to inject as
    # `GH_TOKEN`. The house convention this repo already practices
    # (`.credentials/store` in this very tree; `.gitignore:46` ignores
    # `.credentials/*`) is that this path is a SYMLINK to the real secret
    # kept outside the project tree -- `run_gh` refuses outright if it
    # resolves to a regular file inside the repo, because the coding agent
    # that runs in this same tree can read whatever the working copy holds.
    # An operator who keeps the token under a different name points this at
    # it without touching code.
    forge_credential_relative_path: str = ".credentials/github-token"

    model_config = SettingsConfigDict(env_prefix="CODEX_BRIDGE_AGENT_", env_file=".env")

    @field_validator("discovery_roots", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        """Accept `CODEX_BRIDGE_AGENT_DISCOVERY_ROOTS=/a,/b` from the environment.

        pydantic-settings parses a `list[str]` field from the environment as
        JSON by default, which is not how any other list-shaped setting in
        this codebase is written (`.env.example` uses plain comma-separated
        values throughout). Runs only when the raw value is a string --
        constructing `AgentSettings(discovery_roots=[...])` directly, as the
        tests do, is untouched.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


class AgentProjectConfig(BaseModel):
    projects: list[ProjectRegistration] = Field(default_factory=list)


def load_agent_projects(path: str) -> dict[str, ProjectRegistration]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    payload = AgentProjectConfig.model_validate(json.loads(file_path.read_text(encoding="utf-8")))
    return {project.project_id: project for project in payload.projects}


def resolve_auto_project(project_id: str, root: str, *, max_depth: int = 6) -> ProjectRegistration | None:
    """Fallback lookup for a `project_id` the static allowlist does not know.

    Only ever consulted when `AgentSettings.auto_project_root` is set (see
    its own docstring for the security tradeoff this makes). Reuses
    `shared.project_discovery`'s own id-assignment, so the id this resolves
    always matches what `scripts/discover_projects.py` would have suggested
    for the same directory -- an operator who ran that script and read
    "hub" gets the same directory back when they later just say "hub".

    Returns `None` on no match, a root that is not a real directory, or a
    match that -- despite `walk_for_git_repos` never following a symlink or
    ascending -- somehow resolves outside `root`; the last check is
    defense in depth on the one line that actually hands a path back to a
    caller that is about to run a coding agent against it.
    """
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        return None
    resolved_root = root_path.resolve()
    index = build_project_id_index(root_path, max_depth)
    match = index.get(project_id)
    if match is None:
        return None
    resolved_match = match.resolve()
    if resolved_match != resolved_root and resolved_root not in resolved_match.parents:
        return None
    return ProjectRegistration(project_id=project_id, name=match.name, path=str(match))


class MachineTokenFileError(RuntimeError):
    """`machine_token_file` is set but unusable -- always an operator problem,
    never something to fall back silently past."""


def resolve_machine_token(settings: AgentSettings) -> str:
    """The machine token to present at the `/agent/ws` handshake.

    Prefers `settings.machine_token_file` over the static `machine_token`
    field when set -- see that field's own docstring for why. A configured
    file that cannot actually be used raises rather than silently falling
    back to `machine_token`: an operator who set the file path did so because
    the static field is the placeholder, not a real credential, and a silent
    fallback would connect (or, more likely, fail the handshake with a
    confusing `4403`) using a token nobody meant to use.

    Same permission discipline `gateway/app/services/notify.py` already
    applies to its own credential file: refuses one readable or writable by
    group/other rather than trusting whatever `chmod` it was left at.
    """
    if not settings.machine_token_file:
        return settings.machine_token
    file_path = Path(settings.machine_token_file).expanduser()
    if not file_path.is_file():
        raise MachineTokenFileError(
            f"machine_token_file is set to {settings.machine_token_file!r} but that file "
            "does not exist or is not readable."
        )
    mode = file_path.stat().st_mode
    if mode & 0o077:
        raise MachineTokenFileError(
            f"machine_token_file at {settings.machine_token_file!r} is readable or "
            f"writable by group/other (mode {oct(mode & 0o777)}); refusing to use it. "
            "Fix with `chmod 600`."
        )
    token = file_path.read_text(encoding="utf-8").strip()
    if not token:
        raise MachineTokenFileError(f"machine_token_file at {settings.machine_token_file!r} is empty.")
    return token

