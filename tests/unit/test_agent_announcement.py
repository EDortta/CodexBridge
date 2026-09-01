"""The `hello` payload's real content -- issue #73 Stage 2.

Before this work `_run_once` sent `{"version": "0.1.0"}` and nothing else.
These tests drive the real `_run_once`/`_build_announcement` code (the same
`_FakeAgentSocket`/`_FakeConnect` idiom `tests/unit/test_agent_service.py`
already uses for its own `_run_once` tests), not a hand-built envelope, so a
mutation that guts `_build_announcement` fails these tests directly instead
of a copy of the expected payload staying green next to broken production
code.
"""

from __future__ import annotations

import platform

import pytest

from agent.codex_bridge_agent import service as service_module
from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AGENT_VERSION, AgentService
from shared.protocol import AgentEnvelope, AgentMessageType, Capability, NodeAnnouncement


class _FakeAgentSocket:
    """Async-iterable stand-in for the real websocket -- copied from

    `tests/unit/test_agent_service.py`'s own harness of the same name, not
    reinvented. An empty `incoming` list (every test here passes one) means
    `_run_once` sends `hello`, then the socket's `__anext__` raises
    `StopAsyncIteration` immediately, ending the loop cleanly with exactly
    one sent message to inspect.
    """

    def __init__(self, incoming: list[str]) -> None:
        self._incoming = list(incoming)
        self.sent: list[str] = []

    async def __aenter__(self) -> "_FakeAgentSocket":
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    def __aiter__(self) -> "_FakeAgentSocket":
        return self

    async def __anext__(self) -> str:
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


class _FakeConnect:
    def __init__(self, socket: _FakeAgentSocket) -> None:
        self._socket = socket

    def __call__(self, url: str, **kwargs: object) -> "_FakeConnect":
        return self

    async def __aenter__(self) -> _FakeAgentSocket:
        return self._socket

    async def __aexit__(self, *_: object) -> bool:
        return False


async def _hello_payload(service: AgentService, monkeypatch) -> dict:
    """Drives `_run_once` against a fake socket with nothing incoming and

    returns the parsed `hello` envelope's payload -- the first (and only)
    message the service sends before the loop ends.
    """
    incoming: list[str] = []
    socket = _FakeAgentSocket(incoming)
    monkeypatch.setattr(service_module.websockets, "connect", _FakeConnect(socket))
    await service._run_once()
    assert len(socket.sent) >= 1
    hello_envelope = AgentEnvelope.model_validate_json(socket.sent[0])
    assert hello_envelope.type == AgentMessageType.HELLO
    return hello_envelope.payload, socket.sent[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "allow_workspace_write,allow_git_delivery,expected_present,expected_absent",
    [
        pytest.param(False, False, set(), {"modify", "deliver"}, id="neither"),
        pytest.param(True, False, {"modify"}, {"deliver"}, id="modify-only"),
        pytest.param(True, True, {"modify", "deliver"}, set(), id="both"),
    ],
)
async def test_hello_envelope_validates_as_node_announcement_with_derived_capabilities(
    monkeypatch, allow_workspace_write, allow_git_delivery, expected_present, expected_absent
) -> None:
    settings = AgentSettings(allow_workspace_write=allow_workspace_write, allow_git_delivery=allow_git_delivery)
    service = AgentService(settings)

    async def fake_probe_all() -> list:
        return []

    monkeypatch.setattr(service.runners, "probe_all", fake_probe_all)

    payload, _raw = await _hello_payload(service, monkeypatch)

    # Validates as the real, strict DTO -- not just "has some keys".
    announcement = NodeAnnouncement.model_validate(payload)
    caps = {c.value for c in announcement.capabilities}

    # READ and TEST are unconditional -- see `AgentService._build_announcement`.
    assert Capability.READ.value in caps
    assert Capability.TEST.value in caps
    for cap in expected_present:
        assert cap in caps, f"expected {cap!r} present for allow_workspace_write={allow_workspace_write}, allow_git_delivery={allow_git_delivery}"
    for cap in expected_absent:
        assert cap not in caps, f"expected {cap!r} absent for allow_workspace_write={allow_workspace_write}, allow_git_delivery={allow_git_delivery}"


@pytest.mark.asyncio
async def test_hello_envelope_carries_os_and_arch_but_never_the_hostname(monkeypatch) -> None:
    """Issue #73: node identity must not be inferred from mutable hostname --

    and the fleet questions this announcement answers never needed it.
    `platform.system()`/`platform.machine()` are fine (coarse platform facts,
    the same on every node of the same kind); `platform.node()` (the
    hostname) must never appear anywhere in the serialised payload.
    """
    service = AgentService(AgentSettings())

    async def fake_probe_all() -> list:
        return []

    monkeypatch.setattr(service.runners, "probe_all", fake_probe_all)

    payload, raw_json = await _hello_payload(service, monkeypatch)

    announcement = NodeAnnouncement.model_validate(payload)
    assert announcement.os == platform.system()
    assert announcement.arch == platform.machine()

    hostname = platform.node()
    if hostname:
        assert hostname not in raw_json


@pytest.mark.asyncio
async def test_build_announcement_falls_back_to_minimal_payload_when_probing_raises(monkeypatch) -> None:
    """`_build_announcement` must never cost the connection. If anything

    inside it raises (here, `RunnerPool.probe_all` itself), `_run_once` still
    gets a valid, minimal `NodeAnnouncement` to send rather than an
    exception that would abort the whole connection attempt.
    """
    service = AgentService(AgentSettings())

    async def raising_probe_all() -> list:
        raise RuntimeError("boom: engine probing exploded")

    monkeypatch.setattr(service.runners, "probe_all", raising_probe_all)

    # Direct call: must not raise.
    announcement = await service._build_announcement()
    assert announcement.agent_version == AGENT_VERSION
    assert announcement.engines == []
    assert announcement.capabilities == []

    # End-to-end: `_run_once` still connects and sends a valid `hello`.
    payload, _raw = await _hello_payload(service, monkeypatch)
    fallback = NodeAnnouncement.model_validate(payload)
    assert fallback.agent_version == AGENT_VERSION
