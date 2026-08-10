from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from gateway.app.version import APP_VERSION


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
    user_registry_file: str = str(Path("examples/users.json").resolve())
    public_base_url: str = "https://codexbridge.inovacaosistemas.com.br:8443"
    mcp_auth_mode: str = "bearer"
    mcp_bearer_token: str = Field(default="change-me")
    mcp_bearer_tokens: str | None = None
    oauth_issuer_url: str | None = None
    oauth_allowed_client_ids: str = "chatgpt-codexbridge"
    oauth_allowed_redirect_uri_prefixes: str = "https://chatgpt.com,https://chat.openai.com,https://auth.openai.com"
    oauth_default_scopes: str = "codexbridge.read codexbridge.task.submit codexbridge.task.cancel"
    oauth_access_token_ttl_seconds: int = 3600
    oauth_authorization_code_ttl_seconds: int = 600
    oauth_allow_unauthenticated_discovery: bool = True
    metrics_enabled: bool = True
    max_log_chunk_chars: int = 4000
    max_result_chars: int = 200000
    diff_max_chars: int = 120000
    reconnect_grace_seconds: int = 120
    rate_limit_window_seconds: int = 60
    rate_limit_requests_per_window: int = 120
    # Signs mobile-API pagination cursors. Unset means a random per-process
    # secret: cursors then stop working across a restart or a second replica,
    # which fails safe (the client restarts pagination) instead of trusting a
    # cursor this process never issued. Set it when running more than one.
    api_cursor_secret: str | None = None
    # Entries appended to X-Forwarded-For AFTER the one naming the client.
    # Do NOT derive it by counting proxies — the first proxy records the client
    # rather than adding a hop beyond it, and which vhosts are in the path
    # depends on what is installed. Read one real header as this process
    # receives it: hops = (number of entries) - 1. 0 means the gateway is
    # reached directly. Unset means "not determined": every anonymous caller
    # then shares one bucket and a warning is logged, which is degraded but
    # never wrong. See gateway/app/api/rate_limit.py.
    api_trusted_proxy_hops: int | None = None
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
