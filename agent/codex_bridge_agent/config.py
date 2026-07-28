from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.protocol import ProjectRegistration


class AgentSettings(BaseSettings):
    gateway_ws_url: str = "ws://127.0.0.1:8080/agent/ws"
    executor_id: str = "T610"
    machine_token: str = "replace-with-long-random-token"
    allowed_projects_file: str = str(Path("examples/agent-projects.json").resolve())
    codex_bin: str = "codex"
    heartbeat_interval_seconds: int = 15
    reconnect_min_seconds: int = 2
    reconnect_max_seconds: int = 30
    max_concurrent_tasks: int = 1
    max_prompt_chars: int = 12000
    max_diff_chars: int = 120000
    max_result_chars: int = 200000

    model_config = SettingsConfigDict(env_prefix="CODEX_BRIDGE_AGENT_", env_file=".env")


class AgentProjectConfig(BaseModel):
    projects: list[ProjectRegistration] = Field(default_factory=list)


def load_agent_projects(path: str) -> dict[str, ProjectRegistration]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    payload = AgentProjectConfig.model_validate(json.loads(file_path.read_text(encoding="utf-8")))
    return {project.project_id: project for project in payload.projects}

