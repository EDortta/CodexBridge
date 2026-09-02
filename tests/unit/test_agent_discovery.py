"""`AgentService._scan_root`/`_discovery_loop` -- issue #73 Stage 3.

The node-side half of discovery: turning `AgentSettings.discovery_roots`
into `DiscoveredCandidate` rows, one `DiscoveryReport` envelope per root.
Every repo here is a REAL, throwaway `git init` under pytest's own
`tmp_path` (the same posture `tests/unit/test_git_delivery.py` and
`tests/unit/test_agent_auto_project.py` already take) -- never a real
project.

Reuses `shared.project_discovery.walk_for_git_repos`/`suggest_project_id`
under the hood (via `build_project_id_index`), so the walking guarantees
already proven in `tests/unit/test_agent_auto_project.py` (never follows a
symlink, ignores a directory with no `.git`) are exercised again here
end-to-end through `_scan_root`, not re-proven from scratch.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService
from shared.protocol import AgentMessageType, DiscoveryReport


GIT_ENV = {
    "GIT_AUTHOR_NAME": "codexbridge-test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "codexbridge-test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env={**os.environ, **GIT_ENV})


def _init_repo(root: Path, *, remote: str | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "development"], root)
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "README.md"], root)
    _run(["git", "commit", "-q", "-m", "initial commit"], root)
    if remote:
        _run(["git", "remote", "add", "origin", remote], root)


class DummyWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, payload: str) -> None:
        self.messages.append(payload)


async def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_poll(), timeout=timeout)


# --------------------------------------------------------------------------
# AgentSettings.discovery_roots
# --------------------------------------------------------------------------


def test_discovery_roots_defaults_to_empty() -> None:
    """The shipped default: no discovery task work at all (`_discovery_loop`'s

    own no-op check) unless an operator opts in.
    """
    assert AgentSettings(_env_file=None).discovery_roots == []


def test_discovery_roots_parses_a_comma_separated_env_var(monkeypatch) -> None:
    """Same convention every other list-shaped setting in this codebase uses

    (`Settings.mcp_bearer_tokens`, `.oauth_allowed_client_ids`) -- plain
    comma-separated values in `.env`, not JSON.
    """
    monkeypatch.setenv("CODEX_BRIDGE_AGENT_DISCOVERY_ROOTS", "/srv/projects/a, /srv/projects/b ,/srv/projects/c")
    settings = AgentSettings(_env_file=None)
    assert settings.discovery_roots == ["/srv/projects/a", "/srv/projects/b", "/srv/projects/c"]


def test_discovery_roots_accepts_a_real_list_when_constructed_directly() -> None:
    """Tests throughout this file build `AgentSettings(discovery_roots=[...])`

    directly -- the comma-split validator must be a no-op for an actual
    `list[str]`, not just for a string.
    """
    settings = AgentSettings(discovery_roots=["/a", "/b"], _env_file=None)
    assert settings.discovery_roots == ["/a", "/b"]


# --------------------------------------------------------------------------
# _scan_root
# --------------------------------------------------------------------------


async def test_scan_root_finds_real_repos_with_remote_head_and_dirty(tmp_path: Path) -> None:
    repo = tmp_path / "hub"
    _init_repo(repo, remote="git@example.invalid:org/hub.git")

    service = AgentService(AgentSettings())
    report = await service._scan_root(str(tmp_path))

    assert report is not None
    assert report.root_path == str(tmp_path)
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.resource_key == str(repo.resolve())
    assert candidate.suggested_project_id == "hub"
    assert candidate.suggested_name == "hub"
    assert candidate.remote_url == "git@example.invalid:org/hub.git"
    assert candidate.head is not None
    assert candidate.dirty is False


async def test_scan_root_reports_no_remote_as_none_not_an_error(tmp_path: Path) -> None:
    """`git remote get-url origin` exits non-zero with no `origin` configured

    -- `DiscoveredCandidate.remote_url`'s own contract: that is not evidence
    of anything wrong with the candidate.
    """
    repo = tmp_path / "no-remote"
    _init_repo(repo)

    service = AgentService(AgentSettings())
    report = await service._scan_root(str(tmp_path))

    assert report is not None
    assert len(report.candidates) == 1
    assert report.candidates[0].remote_url is None


async def test_scan_root_marks_a_repo_with_uncommitted_changes_dirty(tmp_path: Path) -> None:
    repo = tmp_path / "dirty-repo"
    _init_repo(repo)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")

    service = AgentService(AgentSettings())
    report = await service._scan_root(str(tmp_path))

    assert report is not None
    assert report.candidates[0].dirty is True


async def test_scan_root_ignores_a_directory_with_no_git(tmp_path: Path) -> None:
    (tmp_path / "not-a-repo").mkdir()

    service = AgentService(AgentSettings())
    report = await service._scan_root(str(tmp_path))

    assert report is not None
    assert report.candidates == []


async def test_scan_root_never_follows_a_symlink_out_of_root(tmp_path: Path) -> None:
    """Same guarantee `test_agent_auto_project.py` proves for

    `resolve_auto_project` -- exercised here through `_scan_root` because it
    is inherited from `walk_for_git_repos`, not reopened by a second walk.
    """
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    _init_repo(outside)
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape-hatch").symlink_to(outside, target_is_directory=True)

    service = AgentService(AgentSettings())
    report = await service._scan_root(str(root))

    assert report is not None
    assert report.candidates == []


async def test_scan_root_finds_a_nested_submodule_as_its_own_candidate(tmp_path: Path) -> None:
    """CLAUDE.md's own project-scope rule: monorepo submodules are separate

    candidates, not swallowed by the parent repo -- same reasoning
    `walk_for_git_repos`'s own docstring gives.
    """
    _init_repo(tmp_path / "monorepo")
    _init_repo(tmp_path / "monorepo" / "packages" / "web")

    service = AgentService(AgentSettings())
    report = await service._scan_root(str(tmp_path))

    assert report is not None
    assert {c.suggested_name for c in report.candidates} == {"monorepo", "web"}


async def test_scan_root_returns_none_when_the_walk_itself_fails(tmp_path: Path, monkeypatch) -> None:
    """A scan failure (e.g. a permission error surfacing as an exception

    despite `walk_for_git_repos`'s own best-effort handling) must not raise
    out of `_scan_root` -- `_discovery_loop` depends on `None` meaning "skip
    this root", not on catching an exception itself.
    """
    from agent.codex_bridge_agent import service as service_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(service_module, "build_project_id_index", _boom)

    service = AgentService(AgentSettings())
    report = await service._scan_root(str(tmp_path))
    assert report is None


# --------------------------------------------------------------------------
# _discovery_loop
# --------------------------------------------------------------------------


async def test_discovery_loop_is_a_noop_when_no_roots_are_configured() -> None:
    """The shipped default (`discovery_roots=[]`) preserves today's

    behaviour exactly: no task work, no scan, no message.
    """
    service = AgentService(AgentSettings())
    socket = DummyWebSocket()

    # Returns on its own -- no task/cancel dance needed, unlike the other
    # tests below, precisely because this is the no-op path.
    await asyncio.wait_for(service._discovery_loop(socket), timeout=2.0)
    assert socket.messages == []


async def test_discovery_loop_sends_one_envelope_per_root(tmp_path: Path) -> None:
    """Protects against a single giant payload for every root: a slow or

    huge root must not delay the report for any other root
    (`DiscoveryReport`'s own docstring).
    """
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    _init_repo(root_a / "repo-a")
    _init_repo(root_b / "repo-b")

    service = AgentService(
        AgentSettings(discovery_roots=[str(root_a), str(root_b)], discovery_scan_interval_seconds=3600)
    )
    socket = DummyWebSocket()
    task = asyncio.create_task(service._discovery_loop(socket))
    try:
        await _wait_until(lambda: len(socket.messages) >= 2)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(socket.messages) == 2
    reports = []
    for raw in socket.messages:
        from shared.protocol import AgentEnvelope

        envelope = AgentEnvelope.model_validate_json(raw)
        assert envelope.type == AgentMessageType.DISCOVERY_REPORT
        reports.append(DiscoveryReport.model_validate(envelope.payload))

    reported_roots = {report.root_path for report in reports}
    assert reported_roots == {str(root_a), str(root_b)}
    for report in reports:
        assert len(report.candidates) == 1


async def test_discovery_loop_skips_a_root_that_fails_but_still_reports_the_others(
    tmp_path: Path, monkeypatch
) -> None:
    """A root whose scan raises must not stop the others from being reported.

    `build_project_id_index` itself never raises on an ordinary missing or
    unreadable directory (`walk_for_git_repos` swallows `OSError` and
    reports zero candidates instead) -- so the failure this test proves
    `_scan_root` survives has to be forced, the same way
    `test_scan_root_returns_none_when_the_walk_itself_fails` forces it.
    """
    from agent.codex_bridge_agent import service as service_module
    from shared.project_discovery import build_project_id_index as real_build_project_id_index

    good_root = tmp_path / "good"
    _init_repo(good_root / "repo")
    bad_root = tmp_path / "bad"

    def _flaky(root_path: Path, max_depth: int):
        if Path(root_path) == bad_root:
            raise RuntimeError("boom")
        return real_build_project_id_index(root_path, max_depth)

    monkeypatch.setattr(service_module, "build_project_id_index", _flaky)

    service = AgentService(
        AgentSettings(discovery_roots=[str(bad_root), str(good_root)], discovery_scan_interval_seconds=3600)
    )
    socket = DummyWebSocket()
    task = asyncio.create_task(service._discovery_loop(socket))
    try:
        await _wait_until(lambda: len(socket.messages) >= 1)
        # Give the (already-failed) bad root a moment too, to prove it never
        # sends a second envelope rather than just winning a race.
        await asyncio.sleep(0.05)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(socket.messages) == 1
    from shared.protocol import AgentEnvelope

    envelope = AgentEnvelope.model_validate_json(socket.messages[0])
    report = DiscoveryReport.model_validate(envelope.payload)
    assert report.root_path == str(good_root)
