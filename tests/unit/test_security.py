import pytest

from shared.security import ensure_within_root, sanitize_log_line


def test_ensure_within_root_blocks_escape(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ValueError):
        ensure_within_root(str(root), str(tmp_path / ".."))


def test_log_redaction():
    line = "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz012345"
    assert "[REDACTED]" in sanitize_log_line(line)

