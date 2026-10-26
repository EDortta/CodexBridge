import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import worker_watch


def test_observe_only_counts_json_files():
    listing = [
        {"name": "abc.json", "type": "file", "sha": "a"*40, "size": 10},
        {"name": "README.txt", "type": "file", "sha": "b"*40, "size": 10},
        {"name": "nested", "type": "dir"},
    ]
    with patch.object(worker_watch, "github_json", return_value=listing) as get:
        result = worker_watch.observe("codexbridge", "EDortta/CodexBridge", "codexbridge-control", None)
    assert result["request_count"] == 1
    assert result["requests"] == [{"name": "abc.json", "sha": "a"*40}]
    assert "ref=codexbridge-control" in get.call_args.args[0]


@pytest.mark.parametrize("branch", ["main", "master", "development"])
def test_reject_code_branches(branch):
    with pytest.raises(ValueError):
        worker_watch.observe("p", "owner/repo", branch, None)


def test_reject_oversized_request():
    with patch.object(worker_watch, "github_json", return_value=[
        {"name": "bad.json", "type": "file", "sha": "a"*40, "size": 65537}
    ]):
        with pytest.raises(ValueError):
            worker_watch.observe("p", "owner/repo", "codexbridge-control", None)


def test_only_activated_projects(tmp_path):
    from workerctl import _write_state, _empty_state
    from datetime import datetime, timedelta, timezone
    state = _empty_state()
    state["projects"]["active"] = {"repository": "o/active", "control_branch": "codexbridge-control"}
    state["projects"]["inactive"] = {"repository": "o/inactive", "control_branch": "codexbridge-control"}
    now = datetime.now(timezone.utc)
    state["activations"]["active"] = {
        "enabled_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=7, minutes=59)).isoformat(),
    }
    path = tmp_path / "state.json"
    _write_state(path, state)
    assert worker_watch.active_projects(path) == [("active", "o/active", "codexbridge-control")]
