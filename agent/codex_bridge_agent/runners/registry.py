"""Extensible engine registry for CodexBridge.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a. Every value in
`shared.protocol.AgentEngine` is a declared CANDIDATE -- the seven CLIs
installed on the executor host. Only the ones registered here as
`implemented=True` have code behind them; the rest exist so a dispatch naming
one fails with a typed `EngineNotImplementedError` instead of an
`AttributeError` or a silent fallback to Codex.

This module provides an extensible registry pattern that supports:
1. Core engines (Codex, Claude) with established implementations
2. Candidate engines (Cursor Agent, Gemini, OpenCode, Aider, Copilot, etc.)
3. Custom N+1 adapters without modifying existing engines
4. Dynamic engine discovery and availability tracking
5. Clear separation between known/registered, implemented, installed, available, and authenticated states
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.base import EngineProbe, Runner
from shared.protocol import AgentEngine


@runtime_checkable
class EngineAdapter(Protocol):
    """Protocol for engine adapters that can discover, probe, and instantiate engines."""

    def get_engine_name(self) -> str:
        """Return the canonical engine identifier."""
        ...

    def get_engine_display_name(self) -> str:
        """Return a human-readable name for the engine."""
        ...

    def is_binary_installed(self) -> bool:
        """Check if the engine binary is available on the system."""
        ...

    async def probe_availability(self) -> EngineProbe:
        """Check if the engine is fully available with authentication."""
        ...

    async def instantiate(self, settings: AgentSettings) -> Runner:
        """Create a runner instance for this engine."""
        ...


@dataclass(frozen=True)
class EngineRegistration:
    """Engine registration with implementation status and factory."""
    engine: str
    implemented: bool
    factory: Callable[[AgentSettings], Runner] | None = None
    adapter: EngineAdapter | None = None
    # Lifecycle states for better tracking
    installed: bool = False
    probe_available: bool = False
    authenticated: bool = False


# Core engines with established implementations
KNOWN_ENGINES: dict[str, EngineRegistration] = {
    AgentEngine.CODEX.value: EngineRegistration(
        engine=AgentEngine.CODEX.value,
        implemented=True,
        factory=lambda settings: __import__("agent.codex_bridge_agent.runners.codex", fromlist=["CodexRunner"]).CodexRunner(settings),
        installed=True, probe_available=True, authenticated=True,
    ),
    AgentEngine.CLAUDE.value: EngineRegistration(
        engine=AgentEngine.CLAUDE.value,
        implemented=True,
        factory=lambda settings: __import__("agent.codex_bridge_agent.runners.claude", fromlist=["ClaudeRunner"]).ClaudeRunner(settings),
        installed=True, probe_available=True, authenticated=True,
    ),
}

# Candidate engines - may have adapters but no implementation yet
CANDIDATE_ENGINES: dict[str, EngineRegistration] = {
    AgentEngine.CURSOR_AGENT.value: EngineRegistration(
        engine=AgentEngine.CURSOR_AGENT.value,
        implemented=False,
        adapter=None,  # To be implemented
        installed=False, probe_available=False, authenticated=False,
    ),
    AgentEngine.GEMINI.value: EngineRegistration(
        engine=AgentEngine.GEMINI.value,
        implemented=False,
        adapter=None,  # To be implemented
        installed=False, probe_available=False, authenticated=False,
    ),
    AgentEngine.OPENCODE.value: EngineRegistration(
        engine=AgentEngine.OPENCODE.value,
        implemented=False,
        adapter=None,  # To be implemented
        installed=False, probe_available=False, authenticated=False,
    ),
    AgentEngine.AIDER.value: EngineRegistration(
        engine=AgentEngine.AIDER.value,
        implemented=False,
        adapter=None,  # To be implemented
        installed=False, probe_available=False, authenticated=False,
    ),
    "copilot": EngineRegistration(
        engine="copilot",
        implemented=False,
        adapter=None,  # To be implemented
        installed=False, probe_available=False, authenticated=False,
    ),
}

# Dynamic registry for custom N+1 engines
CUSTOM_ENGINES: dict[str, EngineRegistration] = {}


def get_all_engines() -> dict[str, EngineRegistration]:
    """Get all engines including core, candidates, and custom."""
    return {**KNOWN_ENGINES, **CANDIDATE_ENGINES, **CUSTOM_ENGINES}


def register_custom_engine(
    engine_name: str,
    adapter: EngineAdapter | None = None,
    factory: Callable[[AgentSettings], Runner] | None = None,
    implemented: bool = False,
    installed: bool = False,
    probe_available: bool = False,
    authenticated: bool = False,
) -> None:
    """Register a custom engine adapter or implementation.

    Args:
        engine_name: Unique identifier for the engine
        adapter: Adapter for discovery and probing (optional for direct implementation)
        factory: Factory function for creating runner instances (optional if adapter provides instantiation)
        implemented: Whether this engine has a Runner implementation
        installed: Whether the binary/engine is installed on the system
        probe_available: Whether the engine passes availability probing
        authenticated: Whether the engine is authenticated/licensed
    """
    engine_reg = EngineRegistration(
        engine=engine_name,
        implemented=implemented,
        factory=factory,
        adapter=adapter,
        installed=installed,
        probe_available=probe_available,
        authenticated=authenticated,
    )
    CUSTOM_ENGINES[engine_name] = engine_reg


def discover_available_engines() -> dict[str, EngineRegistration]:
    """Discover and probe all available engines."""
    available = {}

    # Check core engines
    for name, reg in KNOWN_ENGINES.items():
        if reg.implemented and reg.factory:
            available[name] = reg

    # Check candidate engines via adapters
    for name, reg in CANDIDATE_ENGINES.items():
        if reg.adapter and reg.adapter.is_binary_installed():
            available[name] = reg

    # Check custom engines via adapters
    for name, reg in CUSTOM_ENGINES.items():
        if reg.adapter and reg.adapter.is_binary_installed():
            available[name] = reg

    return available


def get_engine_info(engine_name: str) -> EngineRegistration | None:
    """Get registration information for a specific engine."""
    return get_all_engines().get(engine_name)