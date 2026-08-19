"""CodexRunner's pause/resume/restart/cancel state machine — issue #16 council.

Round 1 shipped these behaviours with zero test coverage anywhere in the repo
(`grep -rln codex_runner tests/` returned nothing); round 2 proved it by
mutation — reverting the SIGCONT-before-terminate fix, or the restart-then-cancel
fix below, left the full 302-test suite green. These tests close that gap.
"""

from __future__ import annotations

import asyncio
import signal

import pytest

from agent.codex_bridge_agent.codex_runner import CodexRunner, RunningTask
from agent.codex_bridge_agent.config import AgentSettings


class _FakeProcess:
    """Stands in for `asyncio.subprocess.Process`: records signals and the
    terminate() call without spawning anything, for the pure state-machine
    tests that don't need a real process."""

    def __init__(self) -> None:
        self.signals_sent: list[int] = []
        self.terminated = False

    def send_signal(self, sig: int) -> None:
        self.signals_sent.append(sig)

    def terminate(self) -> None:
        self.terminated = True


def _runner_with_task(task_id: str = "t1", *, paused: bool = False):
    runner = CodexRunner(AgentSettings())
    process = _FakeProcess()
    item = RunningTask(process=process, paused=paused)
    runner.running[task_id] = item
    return runner, item, process


@pytest.mark.asyncio
async def test_pause_signals_sigstop_and_marks_paused() -> None:
    runner, item, process = _runner_with_task()
    assert await runner.pause("t1") is True
    assert item.paused is True
    assert process.signals_sent == [signal.SIGSTOP]


@pytest.mark.asyncio
async def test_pause_refuses_when_already_paused() -> None:
    runner, item, process = _runner_with_task(paused=True)
    assert await runner.pause("t1") is False
    assert process.signals_sent == []


@pytest.mark.asyncio
async def test_pause_refuses_an_unknown_task() -> None:
    runner = CodexRunner(AgentSettings())
    assert await runner.pause("missing") is False


@pytest.mark.asyncio
async def test_resume_signals_sigcont_and_clears_paused() -> None:
    runner, item, process = _runner_with_task(paused=True)
    assert await runner.resume("t1") is True
    assert item.paused is False
    assert process.signals_sent == [signal.SIGCONT]


@pytest.mark.asyncio
async def test_resume_refuses_when_not_paused() -> None:
    runner, item, process = _runner_with_task(paused=False)
    assert await runner.resume("t1") is False
    assert process.signals_sent == []


@pytest.mark.asyncio
async def test_restart_resumes_a_paused_process_before_terminating_it() -> None:
    runner, item, process = _runner_with_task(paused=True)
    assert await runner.restart("t1") is True
    assert process.signals_sent == [signal.SIGCONT]
    assert process.terminated is True
    assert item.paused is False
    assert item.restart_requested is True
    assert item.cancel_requested is False


@pytest.mark.asyncio
async def test_cancel_refuses_an_unknown_task() -> None:
    """The gateway replays `task.cancel` on reconnect for a task the executor
    may no longer be running at all (issue #17) — it must not raise, just
    report there was nothing to cancel."""
    runner = CodexRunner(AgentSettings())
    assert await runner.cancel("missing") is False


def test_is_known_reflects_mark_dispatched_not_the_running_process_dict() -> None:
    """council round 2 on #17, "the second caller": `is_known` used to check
    membership in `self.running`, which only holds a task while its process
    is alive — empty before `run_task` spawns one and after it exits. A task
    marked dispatched is known even with no process ever having existed for
    it, and stays known until explicitly forgotten."""
    runner = CodexRunner(AgentSettings())
    runner.mark_dispatched("t1")

    assert runner.is_known("t1") is True
    assert "t1" not in runner.running

    runner.forget("t1")

    assert runner.is_known("t1") is False


@pytest.mark.asyncio
async def test_cancel_resumes_a_paused_process_before_terminating_it() -> None:
    runner, item, process = _runner_with_task(paused=True)
    assert await runner.cancel("t1") is True
    assert process.signals_sent == [signal.SIGCONT]
    assert process.terminated is True
    assert item.paused is False
    assert item.cancel_requested is True


@pytest.mark.asyncio
async def test_cancel_after_restart_clears_the_pending_restart() -> None:
    """council 2026-08-18, "the second caller", reproduced live: restart()
    sets restart_requested; run_task's loop checks restart_requested before
    cancel_requested, so a cancel() landing right after used to leave the
    pending restart in place and the process was relaunched instead of ended
    — reported CANCELLED (slot freed) on the gateway while the executor kept
    running it, unmanaged."""
    runner, item, process = _runner_with_task()
    assert await runner.restart("t1") is True
    assert item.restart_requested is True
    assert await runner.cancel("t1") is True
    assert item.restart_requested is False
    assert item.cancel_requested is True


class _FakeTimeoutProcess:
    """A controllable stand-in for the real subprocess in
    `_terminate_gracefully` tests. `terminates_on_sigterm=False` models a
    process that does not end just because `terminate()` was called (whether
    because it is still stopped, or ignoring the signal for some other
    reason) — `wait()` never resolves on its own, which is what should drive
    the `kill()` fallback."""

    def __init__(self, *, terminates_on_sigterm: bool = True) -> None:
        self.events: list[str] = []
        self._terminated = False
        self._terminates_on_sigterm = terminates_on_sigterm
        self.killed = False

    def send_signal(self, sig: int) -> None:
        self.events.append("SIGCONT" if sig == signal.SIGCONT else f"signal-{sig}")

    def terminate(self) -> None:
        self.events.append("terminate")
        if self._terminates_on_sigterm:
            self._terminated = True

    def kill(self) -> None:
        self.killed = True
        self.events.append("kill")
        self._terminated = True

    async def wait(self) -> int:
        if self._terminated:
            self.events.append("wait_ok")
            return -15
        # A process that never actually terminates would hang `wait()`
        # forever on a real OS; sleeping past any sane test timeout
        # reproduces that without actually hanging the test suite.
        await asyncio.sleep(3600)
        return -9  # pragma: no cover


@pytest.mark.asyncio
async def test_terminate_gracefully_resumes_a_paused_process_before_terminating() -> None:
    runner, item, _ = _runner_with_task(paused=True)
    process = _FakeTimeoutProcess()

    await runner._terminate_gracefully(item, process)  # noqa: SLF001

    assert process.events == ["SIGCONT", "terminate", "wait_ok"]
    assert item.paused is False
    assert process.killed is False


@pytest.mark.asyncio
async def test_terminate_gracefully_does_not_signal_cont_when_not_paused() -> None:
    runner, item, _ = _runner_with_task(paused=False)
    process = _FakeTimeoutProcess()

    await runner._terminate_gracefully(item, process)  # noqa: SLF001

    assert process.events == ["terminate", "wait_ok"]
    assert process.killed is False


@pytest.mark.asyncio
async def test_terminate_gracefully_falls_back_to_kill_if_still_stuck() -> None:
    """The safety net behind the SIGCONT fix: a process that does not end
    from `terminate()` alone (still stopped, or otherwise unresponsive) is
    not left running forever — the 5s `wait()` timeout falls back to
    `kill()`."""
    runner, item, _ = _runner_with_task(paused=True)
    process = _FakeTimeoutProcess(terminates_on_sigterm=False)

    await asyncio.wait_for(
        runner._terminate_gracefully(item, process),  # noqa: SLF001
        timeout=10,
    )

    assert process.killed is True
    assert process.events == ["SIGCONT", "terminate", "kill", "wait_ok"]
