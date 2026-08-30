"""Which `AgentEngine` values have a real `Runner` behind them.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a. Every value in
`shared.protocol.AgentEngine` is a declared CANDIDATE -- the seven CLIs
installed on the executor host. Only the ones registered here as
`implemented=True` have code behind them; the rest exist so a dispatch naming
one fails with a typed `EngineNotImplementedError` instead of an
`AttributeError` or a silent fallback to Codex.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.base import Runner
from agent.codex_bridge_agent.runners.claude import ClaudeRunner
from agent.codex_bridge_agent.runners.codex import CodexRunner
from shared.protocol import AgentEngine


@dataclass(frozen=True)
class EngineRegistration:
    engine: str
    implemented: bool
    factory: Callable[[AgentSettings], Runner] | None = None


# `factory` is `None` for a candidate with no `Runner` yet -- deliberately
# listed rather than absent, so `KNOWN_ENGINES` is the one place that answers
# "what could this executor ever run" as well as "what can it run today".
KNOWN_ENGINES: dict[str, EngineRegistration] = {
    AgentEngine.CODEX.value: EngineRegistration(AgentEngine.CODEX.value, implemented=True, factory=CodexRunner),
    AgentEngine.CLAUDE.value: EngineRegistration(AgentEngine.CLAUDE.value, implemented=True, factory=ClaudeRunner),
    AgentEngine.CURSOR_AGENT.value: EngineRegistration(AgentEngine.CURSOR_AGENT.value, implemented=False),
    AgentEngine.GEMINI.value: EngineRegistration(AgentEngine.GEMINI.value, implemented=False),
    AgentEngine.OPENCODE.value: EngineRegistration(AgentEngine.OPENCODE.value, implemented=False),
    AgentEngine.AIDER.value: EngineRegistration(AgentEngine.AIDER.value, implemented=False),
}
