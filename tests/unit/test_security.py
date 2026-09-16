import pytest

from shared.security import ensure_within_root, redact_sensitive_text, sanitize_log_line


def test_ensure_within_root_blocks_escape(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ValueError):
        ensure_within_root(str(root), str(tmp_path / ".."))


def test_log_redaction():
    line = "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz012345"
    assert "[REDACTED]" in sanitize_log_line(line)


@pytest.mark.parametrize(
    "text",
    [
        "workspace=/home/esteban/Sync/Projects/AI/CodexBridge",
        "registered at /srv/projects/CodexBridge",
        "config: /etc/codex-bridge/env",
        "artifact in /tmp/codexbridge/result.json",
        r"workspace=C:\\Users\\esteban\\Projects\\CodexBridge",
        "relative ./private/worktree and ../sibling/repo",
        "markdown `/home/esteban/Sync/Projects/AI/CodexBridge`",
    ],
)
def test_public_text_redaction_hides_filesystem_paths(text):
    redacted = redact_sensitive_text(text)
    assert "[PATH]" in redacted
    assert "/home/" not in redacted
    assert "/srv/" not in redacted
    assert "/etc/" not in redacted
    assert "/tmp/" not in redacted
    assert "C:\\" not in redacted
    assert "./private" not in redacted
    assert "../sibling" not in redacted


def test_public_text_redaction_keeps_logical_project_and_node_names():
    text = "Project CodexBridge is active on node devel3."
    assert redact_sensitive_text(text) == text
