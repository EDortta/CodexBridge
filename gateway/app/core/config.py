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
    mcp_bearer_token: str = Field(default="change-me")
    metrics_enabled: bool = True
    max_log_chunk_chars: int = 4000
    max_result_chars: int = 200000
    diff_max_chars: int = 120000
    reconnect_grace_seconds: int = 120

    model_config = SettingsConfigDict(env_prefix="CODEX_BRIDGE_", env_file=".env")


settings = Settings()

