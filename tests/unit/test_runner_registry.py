"""The runner abstraction itself: capability declarations and the pool's

engine routing. WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a.
"""

from __future__ import annotations

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.base import EngineNotImplementedError, Runner
from agent.codex_bridge_agent.runners.codex import CodexRunner
from agent.codex_bridge_agent.runners.pool import RunnerPool
from agent.codex_bridge_agent.runners.registry import KNOWN_ENGINES
from shared.protocol import AgentEngine


def test_codex_satisfies_the_runner_protocol():
    runner = CodexRunner(AgentSettings())
    assert isinstance(runner, Runner)


def test_codex_declares_an_os_enforced_sandbox():
    """The honest field from `RunnerCapabilities`: Codex's `-s read-only` is a

    real OS-level sandbox, not a denylist the executor assembles. A future
    runner (Claude Code) that only has `--disallowedTools` must declare
    `"provider-flags"` here instead -- conflating the two is exactly the
    "runtime surprise" issue #41 exists to prevent.
    """
    caps = CodexRunner(AgentSettings()).capabilities()
    assert caps.engine == AgentEngine.CODEX.value
    assert caps.sandbox_enforced_by == "os-sandbox"
    assert caps.supports_resume is True
    assert caps.sandbox_modes == frozenset({"read-only", "workspace-write"})


def test_no_registered_engines_env_allowlist_overlaps_another():
    """Env custody must never be unioned across providers (council finding

    F08): a Codex-only credential (`OPENAI_API_KEY`) must never reach a
    different engine's subprocess, and vice versa. Only implemented engines
    have a real allowlist to check.
    """
    allowlists = {
        name: registration.factory(AgentSettings()).capabilities().env_allowlist
        for name, registration in KNOWN_ENGINES.items()
        if registration.implemented and registration.factory is not None
    }
    engine_specific = {
        name: allowlist - {"HOME", "PATH", "LANG", "LC_ALL"}
        for name, allowlist in allowlists.items()
    }
    names = list(engine_specific)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            overlap = engine_specific[left] & engine_specific[right]
            assert not overlap, f"{left} and {right} share engine-specific env vars: {overlap}"


def test_unimplemented_engines_are_declared_not_absent():
    """Every `AgentEngine` value is a registered candidate, whether or not it

    has a `Runner` behind it yet -- so `RunnerPool.for_engine` can fail with a
    typed error naming the engine, never an `AttributeError` from a missing
    dict key.
    """
    for engine in AgentEngine:
        assert engine.value in KNOWN_ENGINES, engine.value
    implemented = {name for name, reg in KNOWN_ENGINES.items() if reg.implemented}
    assert implemented == {AgentEngine.CODEX.value}


def test_pool_defaults_to_codex_and_rejects_unknown_engines():
    pool = RunnerPool(AgentSettings())
    assert isinstance(pool.for_engine("codex"), CodexRunner)
    with pytest.raises(EngineNotImplementedError) as raised:
        pool.for_engine("claude")
    assert str(raised.value) == "engine_not_implemented:claude"
    with pytest.raises(EngineNotImplementedError):
        pool.for_engine("not-a-real-engine")


@pytest.mark.asyncio
async def test_pool_routes_control_messages_only_to_dispatched_tasks():
    pool = RunnerPool(AgentSettings())
    assert pool.is_known("never-dispatched") is False
    assert await pool.cancel("never-dispatched") is False
    assert await pool.pause("never-dispatched") is False

    pool.mark_dispatched("task-1", "codex")
    assert pool.is_known("task-1") is True
    # The underlying CodexRunner has no live process for "task-1" (nothing
    # ever called `run_task`), so cancel/pause correctly report False -- the
    # pool's routing found the right runner, and that runner has its own
    # honest answer.
    assert await pool.cancel("task-1") is False

    pool.forget("task-1")
    assert pool.is_known("task-1") is False
