"""`gh_tool.run_gh`/`resolve_gh_token` against a fake `gh` subprocess.

WK-20260902-forge-github-module, issue #80/#79 (PR B2). No test here ever
spawns a real `gh` -- `asyncio.create_subprocess_exec` is monkeypatched to a
`_FakeProcess`, the same shape `tests/unit/test_codex_runner.py` already uses
for its own fake process (`_FakeTimeoutProcess`). Every negative case is
paired with a positive control in the same test or its neighbor, per
`docs/napkin-lessons.md`'s 2026-09-01 lesson: a refusal test that can never
actually reach the code it claims to guard proves nothing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent.codex_bridge_agent.forge.gh_tool import GH_ENV_ALLOWLIST, resolve_gh_token, run_gh


class _FakeProcess:
    """Stands in for `asyncio.subprocess.Process`. Records nothing itself --
    the test records the call to `create_subprocess_exec` that produced it.
    """

    def __init__(self, *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"", hang: bool = False) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(3600)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        return self.returncode


def _fake_create_subprocess_exec(process: _FakeProcess, calls: list[dict]):
    async def fake(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return process

    return fake


def _write_regular_credential(project_root: Path, relative_path: str, token: str = "regular-file-token") -> None:
    path = project_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")


def _write_symlink_credential_outside_repo(
    project_root: Path, relative_path: str, external_dir: Path, token: str = "symlinked-token"
) -> None:
    external_dir.mkdir(parents=True, exist_ok=True)
    target = external_dir / "github-token"
    target.write_text(token, encoding="utf-8")
    link = project_root / relative_path
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)


# --------------------------------------------------------------------------
# resolve_gh_token: the credential guard, in isolation
# --------------------------------------------------------------------------


def test_resolve_gh_token_refuses_a_regular_file_inside_the_repo(tmp_path: Path):
    _write_regular_credential(tmp_path, ".credentials/github-token")
    token, reason = resolve_gh_token(tmp_path, ".credentials/github-token")
    assert token is None
    assert reason == "forge_credential_must_be_symlink_outside_repo"


def test_resolve_gh_token_accepts_a_symlink_resolving_outside_the_repo(tmp_path: Path):
    """Positive control for the test above: same shape, but a symlink whose
    target actually resolves outside `project_root` is accepted."""
    external = tmp_path.parent / f"{tmp_path.name}-external"
    _write_symlink_credential_outside_repo(tmp_path, ".credentials/github-token", external, token="secret-abc")
    token, reason = resolve_gh_token(tmp_path, ".credentials/github-token")
    assert reason is None
    assert token == "secret-abc"


def test_resolve_gh_token_refuses_a_symlink_whose_target_is_still_inside_the_repo(tmp_path: Path):
    """A symlink alone is not the guard -- the resolved TARGET must be
    outside `project_root`. A symlink pointing at another file in the same
    tree must be refused exactly like a regular file."""
    real_file = tmp_path / "nested" / "token-file"
    real_file.parent.mkdir(parents=True, exist_ok=True)
    real_file.write_text("inside-repo-token", encoding="utf-8")
    link = tmp_path / ".credentials" / "github-token"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(real_file)

    token, reason = resolve_gh_token(tmp_path, ".credentials/github-token")
    assert token is None
    assert reason == "forge_credential_must_be_symlink_outside_repo"


def test_resolve_gh_token_refuses_a_missing_credential(tmp_path: Path):
    token, reason = resolve_gh_token(tmp_path, ".credentials/github-token")
    assert token is None
    assert reason == "forge_credential_missing"


def test_resolve_gh_token_refuses_a_broken_symlink(tmp_path: Path):
    link = tmp_path / ".credentials" / "github-token"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(tmp_path.parent / "nowhere" / "does-not-exist")
    token, reason = resolve_gh_token(tmp_path, ".credentials/github-token")
    assert token is None
    assert reason == "forge_credential_target_missing"


# --------------------------------------------------------------------------
# run_gh: the credential guard applied before any subprocess is spawned
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_gh_refuses_a_regular_file_credential_without_spawning_a_process(tmp_path: Path, monkeypatch):
    _write_regular_credential(tmp_path, ".credentials/github-token")
    calls: list[dict] = []
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec(_FakeProcess(), calls))

    result = await run_gh(
        tmp_path,
        "issue",
        "list",
        gh_bin="gh",
        credential_relative_path=".credentials/github-token",
        timeout_seconds=5,
    )

    assert result.refused_reason == "forge_credential_must_be_symlink_outside_repo"
    assert result.returncode is None
    assert calls == []  # the fake subprocess was never invoked


@pytest.mark.asyncio
async def test_run_gh_runs_the_process_when_the_credential_is_a_valid_symlink(tmp_path: Path, monkeypatch):
    """Positive control for the refusal above."""
    external = tmp_path.parent / f"{tmp_path.name}-external"
    _write_symlink_credential_outside_repo(tmp_path, ".credentials/github-token", external, token="tok-xyz")
    calls: list[dict] = []
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        _fake_create_subprocess_exec(_FakeProcess(returncode=0, stdout=b"ok"), calls),
    )

    result = await run_gh(
        tmp_path,
        "issue",
        "list",
        gh_bin="gh",
        credential_relative_path=".credentials/github-token",
        timeout_seconds=5,
    )

    assert result.refused_reason is None
    assert result.ok is True
    assert len(calls) == 1


# --------------------------------------------------------------------------
# Env custody: GH_TOKEN reaches the subprocess and nothing else does
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_gh_injects_gh_token_and_filters_everything_else(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-leak-to-gh")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-never-leak-to-gh-either")
    monkeypatch.setenv("CODEX_HOME", "/should/not/reach/gh")

    external = tmp_path.parent / f"{tmp_path.name}-external"
    _write_symlink_credential_outside_repo(tmp_path, ".credentials/github-token", external, token="the-gh-token")
    calls: list[dict] = []
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec(_FakeProcess(), calls))

    await run_gh(
        tmp_path,
        "issue",
        "list",
        gh_bin="gh",
        credential_relative_path=".credentials/github-token",
        timeout_seconds=5,
    )

    assert len(calls) == 1
    env = calls[0]["kwargs"]["env"]
    assert env["GH_TOKEN"] == "the-gh-token"
    assert set(env) <= GH_ENV_ALLOWLIST
    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "CODEX_HOME" not in env


def test_gh_env_allowlist_is_exactly_home_path_gh_token():
    assert GH_ENV_ALLOWLIST == frozenset({"HOME", "PATH", "GH_TOKEN"})


# --------------------------------------------------------------------------
# argv shape: no shell, list argv, cwd is project_root
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_gh_calls_create_subprocess_exec_with_a_list_argv_no_shell(tmp_path: Path, monkeypatch):
    external = tmp_path.parent / f"{tmp_path.name}-external"
    _write_symlink_credential_outside_repo(tmp_path, ".credentials/github-token", external)
    calls: list[dict] = []
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec(_FakeProcess(), calls))

    await run_gh(
        tmp_path,
        "issue",
        "close",
        "42",
        "--repo",
        "owner/repo",
        gh_bin="/usr/local/bin/gh",
        credential_relative_path=".credentials/github-token",
        timeout_seconds=5,
    )

    assert len(calls) == 1
    assert calls[0]["args"] == ("/usr/local/bin/gh", "issue", "close", "42", "--repo", "owner/repo")
    assert calls[0]["kwargs"]["cwd"] == str(tmp_path)
    assert calls[0]["kwargs"]["stdout"] is asyncio.subprocess.PIPE
    assert calls[0]["kwargs"]["stderr"] is asyncio.subprocess.PIPE


# --------------------------------------------------------------------------
# Timeout: always passed, and enforced
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_gh_always_passes_the_timeout_to_wait_for(tmp_path: Path, monkeypatch):
    external = tmp_path.parent / f"{tmp_path.name}-external"
    _write_symlink_credential_outside_repo(tmp_path, ".credentials/github-token", external)
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", _fake_create_subprocess_exec(_FakeProcess(), [])
    )

    real_wait_for = asyncio.wait_for
    seen_timeouts: list[float | None] = []

    async def recording_wait_for(awaitable, timeout=None):
        seen_timeouts.append(timeout)
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", recording_wait_for)

    await run_gh(
        tmp_path,
        "issue",
        "list",
        gh_bin="gh",
        credential_relative_path=".credentials/github-token",
        timeout_seconds=42.5,
    )

    assert seen_timeouts == [42.5]


@pytest.mark.asyncio
async def test_run_gh_times_out_and_kills_the_process(tmp_path: Path, monkeypatch):
    external = tmp_path.parent / f"{tmp_path.name}-external"
    _write_symlink_credential_outside_repo(tmp_path, ".credentials/github-token", external)
    hanging = _FakeProcess(hang=True)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create_subprocess_exec(hanging, []))

    result = await run_gh(
        tmp_path,
        "issue",
        "list",
        gh_bin="gh",
        credential_relative_path=".credentials/github-token",
        timeout_seconds=0.05,
    )

    assert result.returncode == 124
    assert hanging.killed is True
    assert hanging.waited is True
