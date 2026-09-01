"""`Runner.probe()` and `RunnerPool.probe_all()` -- issue #73 Stage 2.

`capabilities()` is a compile-time claim ("this code can drive engine X");
`probe()` is a runtime measurement ("the binary is on THIS machine and
answered"). These tests prove the runtime side: a probe never raises (a node
whose probe raised would fail to connect at all -- see
`agent/codex_bridge_agent/runners/base.py:EngineProbe`'s own docstring), never
leaks a filesystem path into `detail`, and `RunnerPool.probe_all()` always
reports one entry per `KNOWN_ENGINES` key, implemented or not.
"""

from __future__ import annotations

import asyncio

import pytest

import agent.codex_bridge_agent.runners.claude as claude_module
import agent.codex_bridge_agent.runners.codex as codex_module
from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.base import EngineProbe
from agent.codex_bridge_agent.runners.claude import ClaudeRunner
from agent.codex_bridge_agent.runners.codex import CodexRunner
from agent.codex_bridge_agent.runners.pool import RunnerPool
from agent.codex_bridge_agent.runners.registry import KNOWN_ENGINES
from shared.protocol import EngineAvailability


class _FakeProcess:
    """Stands in for `asyncio.subprocess.Process` for `probe()`'s own

    `--version` call -- only `communicate()`/`kill()`/`wait()` are exercised,
    so nothing else needs faking.
    """

    def __init__(self, stdout: bytes = b"", hang: bool = False) -> None:
        self._stdout = stdout
        self._hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(3600)
        return (self._stdout, b"")

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        return 0


# (runner class, the `AgentSettings` field that names its binary) -- every
# test below is parametrized across both real runners so a regression in
# either engine's `probe()` is caught, not just one.
_RUNNER_PARAMS = [
    pytest.param(CodexRunner, "codex_bin", id="codex"),
    pytest.param(ClaudeRunner, "claude_bin", id="claude"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_cls,bin_field", _RUNNER_PARAMS)
async def test_probe_reports_unavailable_when_binary_not_on_path(monkeypatch, runner_cls, bin_field) -> None:
    settings = AgentSettings(**{bin_field: "some-binary-name"})
    runner = runner_cls(settings)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    result = await runner.probe()

    assert isinstance(result, EngineProbe)
    assert result.available is False
    assert result.detail is not None
    assert "path" in result.detail.lower()
    assert result.version is None


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_cls,bin_field", _RUNNER_PARAMS)
async def test_probe_reports_available_and_the_parsed_version(monkeypatch, runner_cls, bin_field) -> None:
    settings = AgentSettings(**{bin_field: "some-binary-name"})
    runner = runner_cls(settings)
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/some-binary-name")

    async def fake_create_subprocess_exec(*_args: object, **_kwargs: object) -> _FakeProcess:
        return _FakeProcess(stdout=b"tool-version 9.9.9\nextra ignored line\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_create_subprocess_exec)

    result = await runner.probe()

    assert result.available is True
    assert result.version == "tool-version 9.9.9"


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_cls,bin_field", _RUNNER_PARAMS)
async def test_probe_survives_oserror_without_raising(monkeypatch, runner_cls, bin_field) -> None:
    settings = AgentSettings(**{bin_field: "some-binary-name"})
    runner = runner_cls(settings)
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/some-binary-name")

    async def raising(*_args: object, **_kwargs: object) -> _FakeProcess:
        raise OSError("no such file or directory")

    monkeypatch.setattr("asyncio.create_subprocess_exec", raising)

    result = await runner.probe()

    assert result.available is False
    assert result.detail is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_cls,bin_field,timeout_module", [
    pytest.param(CodexRunner, "codex_bin", codex_module, id="codex"),
    pytest.param(ClaudeRunner, "claude_bin", claude_module, id="claude"),
])
async def test_probe_survives_a_timeout_without_raising(monkeypatch, runner_cls, bin_field, timeout_module) -> None:
    settings = AgentSettings(**{bin_field: "some-binary-name"})
    runner = runner_cls(settings)
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/some-binary-name")
    # The real timeout is 5s; shrink it so this test doesn't spend 5 real
    # seconds waiting for a probe that is deliberately never going to answer.
    monkeypatch.setattr(timeout_module, "_PROBE_TIMEOUT_SECONDS", 0.05)

    async def hanging(*_args: object, **_kwargs: object) -> _FakeProcess:
        return _FakeProcess(hang=True)

    monkeypatch.setattr("asyncio.create_subprocess_exec", hanging)

    result = await runner.probe()

    assert result.available is False
    assert result.detail is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_cls,bin_field", _RUNNER_PARAMS)
async def test_probe_detail_never_carries_the_configured_binary_path(monkeypatch, runner_cls, bin_field) -> None:
    """`detail` is meant to explain a probe failure to an operator, never to

    leak where the binary lives on this machine -- `shared/protocol.py`'s own
    `EngineAvailability.detail` docstring makes this the whole point of the
    field. The resolved path from `shutil.which` (a plausible install
    location, not the literal configured name) is what would leak if
    `probe()` ever built its message from it.
    """
    settings = AgentSettings(**{bin_field: "some-binary-name"})
    runner = runner_cls(settings)
    secret_resolved_path = "/opt/very/secret/install/path/some-binary-name"
    monkeypatch.setattr("shutil.which", lambda _name: secret_resolved_path)

    async def raising(*_args: object, **_kwargs: object) -> _FakeProcess:
        raise OSError("boom")

    monkeypatch.setattr("asyncio.create_subprocess_exec", raising)

    result = await runner.probe()

    assert result.available is False
    detail = result.detail or ""
    assert secret_resolved_path not in detail
    assert getattr(settings, bin_field) not in detail


class _FakeProbeRunner:
    """A `Runner` stand-in that only `probe_all()` ever calls -- `probe()`.

    Follows `tests/unit/test_agent_service.py`'s idiom of injecting a fake
    directly into `pool._runners[...]` rather than building a new harness.
    """

    def __init__(self, result: EngineProbe | None = None, raise_exc: Exception | None = None) -> None:
        self._result = result
        self._raise = raise_exc

    async def probe(self) -> EngineProbe:
        if self._raise is not None:
            raise self._raise
        assert self._result is not None
        return self._result


@pytest.mark.asyncio
async def test_probe_all_returns_one_entry_per_known_engine() -> None:
    pool = RunnerPool(AgentSettings())
    pool._runners["codex"] = _FakeProbeRunner(EngineProbe(available=True, version="1.2.3"))
    pool._runners["claude"] = _FakeProbeRunner(EngineProbe(available=False, detail="not found on PATH"))

    result = await pool.probe_all()

    assert {entry.engine for entry in result} == set(KNOWN_ENGINES.keys())
    by_engine = {entry.engine: entry for entry in result}

    assert by_engine["codex"] == EngineAvailability(
        engine="codex", implemented=True, available=True, version="1.2.3", detail=None
    )
    assert by_engine["claude"] == EngineAvailability(
        engine="claude", implemented=True, available=False, version=None, detail="not found on PATH"
    )
    for name, registration in KNOWN_ENGINES.items():
        if registration.implemented:
            continue
        entry = by_engine[name]
        assert entry.implemented is False
        assert entry.available is False
        assert entry.detail == "no runner implemented"


@pytest.mark.asyncio
async def test_probe_all_survives_one_runner_raising() -> None:
    pool = RunnerPool(AgentSettings())
    pool._runners["codex"] = _FakeProbeRunner(raise_exc=RuntimeError("codex probe exploded"))
    pool._runners["claude"] = _FakeProbeRunner(EngineProbe(available=True, version="9.9.9"))

    result = await pool.probe_all()

    by_engine = {entry.engine: entry for entry in result}
    assert by_engine["codex"].implemented is True
    assert by_engine["codex"].available is False
    assert by_engine["codex"].detail == "probe failed"
    assert by_engine["claude"].available is True
    assert by_engine["claude"].version == "9.9.9"
    # Every other known engine is still present -- one bad runner did not
    # shrink the announcement's engine list.
    assert {entry.engine for entry in result} == set(KNOWN_ENGINES.keys())
