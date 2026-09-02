"""`agent.codex_bridge_agent.config.resolve_machine_token` -- issue #76's
"never paste a token into `.env` by hand" path.

Every test builds its own throwaway file under `tmp_path`; nothing here
touches a real credential.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings, MachineTokenFileError, resolve_machine_token


def test_falls_back_to_the_static_field_when_no_file_is_configured() -> None:
    settings = AgentSettings(machine_token="s3cr3t")
    assert resolve_machine_token(settings) == "s3cr3t"


def test_prefers_the_file_over_the_static_field_when_both_are_set(tmp_path: Path) -> None:
    token_file = tmp_path / "machine-token"
    token_file.write_text("from-the-file", encoding="utf-8")
    token_file.chmod(0o600)

    settings = AgentSettings(machine_token="static-placeholder", machine_token_file=str(token_file))

    assert resolve_machine_token(settings) == "from-the-file"


def test_strips_surrounding_whitespace_from_the_file_content(tmp_path: Path) -> None:
    token_file = tmp_path / "machine-token"
    token_file.write_text("token-with-trailing-newline\n", encoding="utf-8")
    token_file.chmod(0o600)

    settings = AgentSettings(machine_token_file=str(token_file))

    assert resolve_machine_token(settings) == "token-with-trailing-newline"


def test_raises_when_the_configured_file_does_not_exist(tmp_path: Path) -> None:
    settings = AgentSettings(machine_token_file=str(tmp_path / "does-not-exist"))
    with pytest.raises(MachineTokenFileError):
        resolve_machine_token(settings)


def test_raises_when_the_file_is_readable_by_group(tmp_path: Path) -> None:
    token_file = tmp_path / "machine-token"
    token_file.write_text("t", encoding="utf-8")
    token_file.chmod(0o640)

    settings = AgentSettings(machine_token_file=str(token_file))

    with pytest.raises(MachineTokenFileError, match="group/other"):
        resolve_machine_token(settings)


def test_raises_when_the_file_is_empty(tmp_path: Path) -> None:
    token_file = tmp_path / "machine-token"
    token_file.write_text("", encoding="utf-8")
    token_file.chmod(0o600)

    settings = AgentSettings(machine_token_file=str(token_file))

    with pytest.raises(MachineTokenFileError, match="empty"):
        resolve_machine_token(settings)


def test_a_correctly_permissioned_file_actually_works(tmp_path: Path) -> None:
    """The positive control sitting next to every refusal above: `0600` is
    accepted, so the refusals above are proven to be about the *bits set*,
    not about this function refusing every file unconditionally."""
    token_file = tmp_path / "machine-token"
    token_file.write_text("good-token", encoding="utf-8")
    token_file.chmod(0o600)
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    settings = AgentSettings(machine_token_file=str(token_file))

    assert resolve_machine_token(settings) == "good-token"
