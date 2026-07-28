from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "codex-bridge-gateway"
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
