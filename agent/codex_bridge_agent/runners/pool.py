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

import asyncio

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.base import EngineNotImplementedError, Runner
from agent.codex_bridge_agent.runners.registry import KNOWN_ENGINES
from shared.protocol import EngineAvailability


class RunnerPool:
    def __init__(self, settings: AgentSettings):
        self._settings = settings
        self._runners: dict[str, Runner] = {
            name: registration.factory(settings)
            for name, registration in KNOWN_ENGINES.items()
            if registration.implemented and registration.factory is not None
        }
        self._task_engine: dict[str, str] = {}
        # Issue #66 ARO finding F34. A durable flag, independent of any
        # runner's own `running` dict: `CodexRunner.cancel` (and its
        # siblings) only ever touch a task while its process is alive, and
        # the process has already exited -- successfully -- by the time
        # `AgentService._handle_dispatch` runs the git delivery step
        # (`deliver_changes`, outside any runner's sandbox and outside
        # `self.running` entirely). Without a flag that survives the
        # process exiting, a TASK_CANCEL landing during delivery had no
        # record anywhere: `cancel()` below would look up a `self.running`
        # entry that is already gone and report `False`, and the git step
        # had no way to learn a cancel had been requested at all -- see
        # `deliver_changes`'s own docstring for what it does with this.
        # Bracketed by `mark_dispatched`/`forget` the same way `_task_engine`
        # itself is, so it cannot outlive the task it was requested for.
        self._cancel_requested: set[str] = set()

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
        self._cancel_requested.discard(task_id)

    def mark_cancel_requested(self, task_id: str) -> None:
        """Records that a `task.cancel` arrived for `task_id`, regardless of

        whether a live process was found to terminate. Called unconditionally
        from `AgentService`'s `TASK_CANCEL` handler, the same "record the
        request even if nothing was running" posture that handler's own
        unconditional `task.cancelled` ack already takes (issue #17) -- see
        that handler's comment for why an unconditional ack is correct even
        when `cancel()` itself returns `False`. `is_cancel_requested` is what
        `deliver_changes` polls; this is a plain set, not itself a signal to
        tear anything down.
        """
        self._cancel_requested.add(task_id)

    def is_cancel_requested(self, task_id: str) -> bool:
        return task_id in self._cancel_requested

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

    async def probe_all(self) -> list[EngineAvailability]:
        """Issue #73 Stage 2: one `EngineAvailability` for every `KNOWN_ENGINES`

        entry, not just the ones this pool instantiated a `Runner` for. A
        candidate engine with `implemented=False` (no `Runner` exists in this
        codebase) is reported unavailable with a reason rather than omitted
        entirely -- the fleet surface needs to answer "what could this build
        ever run" as well as "what can it run today"
        (`runners/registry.py`'s own docstring makes the same point about
        `KNOWN_ENGINES` itself).

        The implemented engines are probed concurrently
        (`asyncio.gather(..., return_exceptions=True)`) so one runner's probe
        raising cannot take down the whole announcement -- an exception here
        becomes `available=False, detail="probe failed"` rather than
        propagating, mirroring the same "never let one bad part break the
        rest" posture `Runner.probe()` itself takes toward its own
        subprocess.
        """
        implemented_names = [name for name, runner in self._runners.items()]
        results = await asyncio.gather(
            *(self._runners[name].probe() for name in implemented_names),
            return_exceptions=True,
        )
        probes: dict[str, EngineAvailability] = {}
        for name, outcome in zip(implemented_names, results):
            if isinstance(outcome, BaseException):
                probes[name] = EngineAvailability(
                    engine=name,
                    implemented=True,
                    available=False,
                    detail="probe failed",
                )
            else:
                probes[name] = EngineAvailability(
                    engine=name,
                    implemented=True,
                    available=outcome.available,
                    version=outcome.version,
                    detail=outcome.detail,
                )
        availabilities: list[EngineAvailability] = []
        for name, registration in KNOWN_ENGINES.items():
            if name in probes:
                availabilities.append(probes[name])
            else:
                availabilities.append(
                    EngineAvailability(
                        engine=name,
                        implemented=False,
                        available=False,
                        detail="no runner implemented",
                    )
                )
        return availabilities
