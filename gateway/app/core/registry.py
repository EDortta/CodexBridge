from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from shared.protocol import ExecutorRegistration, ProjectRegistration


class Registry(BaseModel):
    executors: list[ExecutorRegistration] = Field(default_factory=list)
    projects: list[ProjectRegistration] = Field(default_factory=list)


def load_registry(path: str) -> Registry:
    file_path = Path(path)
    if not file_path.exists():
        return Registry()
    return Registry.model_validate(json.loads(file_path.read_text(encoding="utf-8")))

