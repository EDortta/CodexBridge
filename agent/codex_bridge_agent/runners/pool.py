"""The facade `AgentService` talks to instead of a single hardcoded runner.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a. Before this, the
executor's control branches (`_run_once`'s pause/resume/restart/cancel) and
`_handle_dispatch` all called `self.runner.<method>` on one `CodexRunner`
instance directly. `RunnerPool` keeps that call shape (each method's
signature is unchanged) while routing to the correct engine's `Runner`
instance underneath.

The routing key is `_task_engine`, populated by `mark_dispatched(task_id,
engine)` at the moment a dispatch is accepted and cleared by `forget`. This
is deliberately NOT derived by asking every runner "do you know this task" --
that would silently paper over a task the pool itself never dispatched.
`is_known` is `task_id in self._task_engine`, which is the same load-bearing
contract `CodexRunner.is_known` always had (see `runners/base.py`), just
centralized across more than one instance.
"""

from __future__ import annotations

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.base import EngineNotImplementedError, Runner
from agent.codex_bridge_agent.runners.registry import KNOWN_ENGINES


class RunnerPool:
    def __init__(self, settings: AgentSettings):
        self._settings = settings
        self._runners: dict[str, Runner] = {
            name: registration.factory(settings)
            for name, registration in KNOWN_ENGINES.items()
            if registration.implemented and registration.factory is not None
        }
        self._task_engine: dict[str, str] = {}

    def for_engine(self, engine: str) -> Runner:
        runner = self._runners.get(engine)
        if runner is None:
            raise EngineNotImplementedError(engine)
        return runner

    def is_known(self, task_id: str) -> bool:
        return task_id in self._task_engine

    def mark_dispatched(self, task_id: str, engine: str) -> None:
        self._task_engine[task_id] = engine
        self._runners[engine].mark_dispatched(task_id)

    def forget(self, task_id: str) -> None:
        engine = self._task_engine.pop(task_id, None)
        if engine is not None:
            self._runners[engine].forget(task_id)

    async def cancel(self, task_id: str) -> bool:
        engine = self._task_engine.get(task_id)
        if engine is None:
            return False
        return await self._runners[engine].cancel(task_id)

    async def pause(self, task_id: str) -> bool:
        engine = self._task_engine.get(task_id)
        if engine is None:
            return False
        return await self._runners[engine].pause(task_id)

    async def resume(self, task_id: str) -> bool:
        engine = self._task_engine.get(task_id)
        if engine is None:
            return False
        return await self._runners[engine].resume(task_id)

    async def restart(self, task_id: str) -> bool:
        engine = self._task_engine.get(task_id)
        if engine is None:
            return False
        return await self._runners[engine].restart(task_id)
