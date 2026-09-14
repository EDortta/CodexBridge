"""The runner abstraction itself: capability declarations and the pool's

engine routing. WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a.
"""

from __future__ import annotations

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.forge.gh_tool import GH_ENV_ALLOWLIST
from agent.codex_bridge_agent.runners.base import (
    EngineNotImplementedError,
    Runner,
)
from agent.codex_bridge_agent.runners.codex import CodexRunner
from agent.codex_bridge_agent.runners.pool import RunnerPool
from agent.codex_bridge_agent.runners.registry import (
    EngineRegistration,
    KNOWN_ENGINES,
    CANDIDATE_ENGINES,
    CUSTOM_ENGINES,
    get_all_engines,
    register_custom_engine,
    discover_available_engines,
)
from shared.protocol import AgentEngine
from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.claude import ClaudeRunner


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

    WK-20260902-forge-github-module (issue #80/#79, PR B2) extends this to a
    THIRD allowlist that is not a `Runner` at all:
    `forge/gh_tool.GH_ENV_ALLOWLIST`, which is where `GH_TOKEN` -- the forge
    credential -- may legally appear. This is one of the most important
    tests in that PR: if `GH_TOKEN` (or any future forge-only variable) ever
    showed up in a runner's `env_allowlist`, it would reach a coding agent's
    own sandboxed subprocess, defeating the entire point of keeping the
    forge credential out of that sandbox (`gh_tool.py`'s own module
    docstring). This test fails the moment that happens.
    """
    allowlists = {
        name: registration.factory(AgentSettings()).capabilities().env_allowlist
        for name, registration in KNOWN_ENGINES.items()
        if registration.implemented and registration.factory is not None
    }
    allowlists["forge-github"] = GH_ENV_ALLOWLIST
    engine_specific = {
        name: allowlist - {"HOME", "PATH", "LANG", "LC_ALL"}
        for name, allowlist in allowlists.items()
    }
    names = list(engine_specific)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            overlap = engine_specific[left] & engine_specific[right]
            assert not overlap, f"{left} and {right} share engine-specific env vars: {overlap}"


def test_gh_token_is_on_the_forge_allowlist_and_nowhere_else():
    """Positive control, spelled out by name rather than left implicit in the

    set-overlap loop above: `GH_TOKEN` belongs on `GH_ENV_ALLOWLIST`, and no
    implemented runner's `env_allowlist` may contain it.
    """
    assert "GH_TOKEN" in GH_ENV_ALLOWLIST
    for name, registration in KNOWN_ENGINES.items():
        if not registration.implemented or registration.factory is None:
            continue
        runner_allowlist = registration.factory(AgentSettings()).capabilities().env_allowlist
        assert "GH_TOKEN" not in runner_allowlist, name


def test_unimplemented_engines_are_declared_not_absent():
    """Every `AgentEngine` value is a registered candidate, whether or not it

    has a `Runner` behind it yet -- so `RunnerPool.for_engine` can fail with a
    typed error naming the engine, never an `AttributeError` from a missing
    dict key.
    """
    all_engines = get_all_engines()
    for engine in AgentEngine:
        assert engine.value in all_engines, engine.value
    # Verify that all core engines are present and implemented
    implemented = {name for name, reg in all_engines.items() if reg.implemented}
    # Both Codex and Claude should be implemented in the extensible registry
    assert implemented == {AgentEngine.CODEX.value, AgentEngine.CLAUDE.value}


def test_custom_engine_registration():
    """Test that custom engines can be registered and discovered."""
    # Start with baseline count
    initial_count = len(get_all_engines())

    # Register a custom engine with an adapter
    class MockAdapter:
        def get_engine_name(self) -> str:
            return "custom-test-engine"

        def get_engine_display_name(self) -> str:
            return "Custom Test Engine"

        def is_binary_installed(self) -> bool:
            return True

        async def probe_availability(self):
            from agent.codex_bridge_agent.runners.base import EngineProbe
            return EngineProbe(available=True, detail="Test")

        async def instantiate(self, settings: AgentSettings):
            # Return a simple mock runner
            class MockRunner(Runner):
                def __init__(self):
                    pass
                async def run_task(self, **kwargs):
                    return {"status": "mock"}
            return MockRunner()

    adapter = MockAdapter()
    register_custom_engine(
        engine_name="custom-test-engine",
        adapter=adapter,
        factory=None,
        implemented=True,
        installed=True,
        probe_available=True,
        authenticated=True,
    )

    # Verify the custom engine was registered
    all_engines = get_all_engines()
    assert "custom-test-engine" in all_engines
    assert all_engines["custom-test-engine"].implemented is True
    assert all_engines["custom-test-engine"].adapter is not None
    assert all_engines["custom-test-engine"].installed is True

    # Verify it can be discovered as available
    available = discover_available_engines()
    assert "custom-test-engine" in available
    assert available["custom-test-engine"].implemented is True

    # Clean up - remove the custom engine to avoid polluting other tests
    # In a real scenario, you'd want better cleanup mechanisms
    from agent.codex_bridge_agent.runners.registry import CUSTOM_ENGINES
    CUSTOM_ENGINES.pop("custom-test-engine", None)
    # Note: This is a simple cleanup - in production you'd want more robust mechanisms


def test_pool_defaults_to_codex_and_rejects_unknown_engines():
    pool = RunnerPool(AgentSettings())
    assert isinstance(pool.for_engine("codex"), CodexRunner)
    from agent.codex_bridge_agent.runners.claude import ClaudeRunner

    assert isinstance(pool.for_engine("claude"), ClaudeRunner)
    with pytest.raises(EngineNotImplementedError) as raised:
        pool.for_engine("cursor-agent")
    assert str(raised.value) == "engine_not_implemented:cursor-agent"
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
