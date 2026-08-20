from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from gateway.app.version import APP_VERSION
from shared.protocol import (
    DEFAULT_CANCEL_REPLAY_MAX_AGE_SECONDS,
    DEFAULT_CONTROL_REPLAY_MAX_AGE_SECONDS,
    MAX_REPLAY_MAX_AGE_SECONDS,
)


class Settings(BaseSettings):
    app_name: str = "codex-bridge-gateway"
    app_version: str = APP_VERSION
    # Build or commit identifier, reported by GET /api/version when set. Left
    # unset in development; the deploy pipeline is expected to inject it.
    # Never put anything secret here: this endpoint is unauthenticated.
    build_revision: str | None = None
    environment: str = "development"
    bind_host: str = "0.0.0.0"
    bind_port: int = 8080
    database_url: str = "sqlite+aiosqlite:///./codex_bridge.db"
    registry_file: str = str(Path("examples/registry.json").resolve())
    # Where the accounts that may sign in are read from. Deliberately NOT
    # `examples/users.json`: that file ships one `admin` account whose plaintext
    # is committed in this repository, and `POST /api/v1/auth/sign-in` (issue #4)
    # made it reachable with one unauthenticated JSON body — no client
    # registration, no redirect allowlist, no PKCE. A default that resolves to a
    # published credential is a shipped secret (`security-standards.md` §1).
    #
    # An unconfigured deployment therefore has no registry at all: the file is
    # absent, `load_user_registry` returns empty, and every sign-in is refused at
    # the same cost as any other. Fail-closed, per `design-standards.md` §6.
    # Development sets `CODEX_BRIDGE_USER_REGISTRY_FILE` like production does.
    user_registry_file: str = "/etc/codex-bridge/users.json"
    public_base_url: str = "https://codexbridge.inovacaosistemas.com.br:8443"
    mcp_auth_mode: str = "bearer"
    mcp_bearer_token: str = Field(default="change-me")
    mcp_bearer_tokens: str | None = None
    oauth_issuer_url: str | None = None
    oauth_allowed_client_ids: str = "chatgpt-codexbridge"
    oauth_allowed_redirect_uri_prefixes: str = "https://chatgpt.com,https://chat.openai.com,https://auth.openai.com"
    oauth_default_scopes: str = (
        "codexbridge.read codexbridge.task.submit codexbridge.task.cancel codexbridge.issues.write"
    )
    oauth_access_token_ttl_seconds: int = 3600
    oauth_authorization_code_ttl_seconds: int = 600
    # Absolute lifetime of a mobile sign-in (issue #4). Rotation carries this
    # expiry forward unchanged rather than extending it, so a stolen refresh
    # token cannot be turned into an unbounded session: 30 days after signing
    # in, the operator signs in again.
    oauth_refresh_token_ttl_seconds: int = 2592000
    oauth_allow_unauthenticated_discovery: bool = True
    # How long an audit row is kept. `POST /api/v1/auth/sign-in` is the first
    # unauthenticated write path into `audit_events` — every other `record_event`
    # call site sits behind authentication — so a rejected attempt commits a row,
    # and the rate limiter's ceiling of 120/minute/bucket is a ceiling on the
    # write rate, not on the table. Nothing else ever removed one.
    #
    # Zero or negative disables the sweep, for an operator who exports the table
    # elsewhere and wants it kept whole. That is an explicit opt-in to unbounded
    # growth, not the default.
    audit_event_retention_days: int = 90
    metrics_enabled: bool = True
    max_log_chunk_chars: int = 4000
    max_result_chars: int = 200000
    diff_max_chars: int = 120000
    reconnect_grace_seconds: int = 120
    # How long a cancelled-but-unacknowledged task stays worth resending
    # `task.cancel` for on executor reconnect (issue #17). Bounded rather than
    # indefinite: an executor that reappears long after a cancellation was
    # issued has almost certainly already finished or been redeployed. The
    # default here (24h) is not, on its own, generous against every possible
    # deployment — `ProjectRegistration.max_timeout_seconds` has no enforced
    # upper bound and the schema accepts up to 86400s
    # (`shared/protocol.py`), so a project registered at the ceiling can have
    # a run still legitimately in flight when this window closes. What makes
    # the window safe either way is that the executor now resolves an unknown
    # cancel on its own: `CodexRunner.cancel` returning `False` still gets an
    # unconditional `task.cancelled` back (issue #17 council, "the claim
    # auditor" / "the second caller") because "not running here" satisfies a
    # cancel's postcondition regardless of whether a live process was
    # actually killed — so a replay that fires is never left waiting on an
    # ack that can't arrive. Past the window, the task is left CANCELLED with
    # no further replay — trimming stale noise, not correctness.
    #
    # Zero disables replay for practically every task (the cutoff lands at
    # "now", which no past cancellation can satisfy) — unlike
    # `audit_event_retention_days`, this is not a documented opt-in shape,
    # just what the comparison does at the boundary. It fails toward the safe
    # direction (no replay, not "replay everything"). Negative values are
    # rejected at startup (`ge=0`) rather than treated as "disable further" —
    # a negative window is nonsensical, and a prior version of this comment
    # claimed negative values disabled replay too, which stopped being true
    # the moment `ge=0` shipped (issue #17 council round 2, "the claim
    # auditor"). Capped at `MAX_REPLAY_MAX_AGE_SECONDS`:
    # `datetime.now(tz) - timedelta(seconds=...)` raises `OverflowError` for
    # values anywhere near a `timedelta`'s actual ceiling, and that raise
    # happens inside `AgentHub.register()` after `websocket.accept()` — every
    # executor would fail to ever finish registering (issue #17 council, "the
    # second caller").
    cancel_replay_max_age_seconds: int = Field(
        default=DEFAULT_CANCEL_REPLAY_MAX_AGE_SECONDS, ge=0, le=MAX_REPLAY_MAX_AGE_SECONDS
    )
    # Same bound, for tasks stuck in PAUSING/RESUMING/RESTARTING with no
    # `task.ack` (issue #17 council, "the sweep skeptic": this replay had no
    # bound at all before, unlike its cancel sibling above). A separate
    # setting rather than reusing `cancel_replay_max_age_seconds` — the two
    # already shipped as independent, differently-named env vars once cancel
    # replay's TTL existed alone, and renaming a shipped knob to widen its
    # scope is a silent breaking change for whoever already set it.
    control_replay_max_age_seconds: int = Field(
        default=DEFAULT_CONTROL_REPLAY_MAX_AGE_SECONDS, ge=0, le=MAX_REPLAY_MAX_AGE_SECONDS
    )
    rate_limit_window_seconds: int = 60
    rate_limit_requests_per_window: int = 120
    # Signs mobile-API pagination cursors. Unset means a random per-process
    # secret: cursors then stop working across a restart or a second replica,
    # which fails safe (the client restarts pagination) instead of trusting a
    # cursor this process never issued. Set it when running more than one.
    api_cursor_secret: str | None = None
    # Addresses or CIDRs of the proxies in front of this process, comma
    # separated (e.g. "127.0.0.1,192.168.71.0/24"). The client is the rightmost
    # X-Forwarded-For entry that is NOT one of these.
    #
    # Not a hop COUNT, because this deployment has two ingress paths of
    # different lengths — direct (8443 published to nginx's internal 443, one
    # entry) and via dom1 (dom1 nginx -> edge proxy -> frida nginx, three) — so
    # any fixed number is wrong for one of them.
    #
    # Defaults to the loopback reverse proxy, which is what this deployment
    # actually has: measured on frida, nginx is the only hop that appends and
    # the gateway's peer is 127.0.0.1. Leaving it unset shipped every anonymous
    # caller into one shared bucket — the defect the rewrite exists to remove,
    # reintroduced as a default. Set to "" to disable header trust entirely.
    #
    # A gateway with no proxy in front is unaffected: no X-Forwarded-For arrives,
    # so the setting is never consulted, and a forged header from a direct client
    # is ignored because that peer is not in this list.
    api_trusted_proxies: str | None = "127.0.0.1"
    # Whether GET /ready reports executor connectivity. Off by default: the
    # endpoint is unauthenticated, and the boolean is a presence signal about the
    # operator's machines — pollable from outside to chart when they are online.
    # /metrics is already restricted to localhost at the proxy for the same
    # reason. Turn on only if that exposure is acceptable.
    ready_expose_executor_state: bool = False
    # How long a readiness probe result is reused. /ready must stay cheap under
    # unauthenticated load: without this, each anonymous request took a
    # connection from the same pool that serves the API, and enough of them made
    # the gateway report itself database-down and ask to be pulled from rotation.
    ready_cache_seconds: float = 5.0

    def effective_ready_cache_seconds(self) -> float:
        # A zero or negative TTL disables caching and restores the DoS the cache
        # exists to prevent, so it is floored rather than honoured.
        return max(0.5, float(self.ready_cache_seconds))

    def accepted_mcp_tokens(self) -> set[str]:
        tokens = {self.mcp_bearer_token}
        if self.mcp_bearer_tokens:
            tokens.update(token.strip() for token in self.mcp_bearer_tokens.split(",") if token.strip())
        return tokens

    def oauth_client_ids(self) -> set[str]:
        return {item.strip() for item in self.oauth_allowed_client_ids.split(",") if item.strip()}

    def oauth_scopes(self) -> set[str]:
        return {item.strip() for item in self.oauth_default_scopes.split() if item.strip()}

    def oauth_redirect_uri_prefixes(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.oauth_allowed_redirect_uri_prefixes.split(",") if item.strip())

    def effective_oauth_issuer(self) -> str:
        return (self.oauth_issuer_url or self.public_base_url).rstrip("/")

    model_config = SettingsConfigDict(env_prefix="CODEX_BRIDGE_", env_file=".env")


settings = Settings()
