"""Negative MVP contract: no unauthorized command, project or replay executes.

All cases use an isolated temporary Git checkout and private operator config.
Nothing touches the live Gateway, devel3 allowlist, or production inbox.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from agent.codex_bridge_agent.file_executor import process_once
from agent.codex_bridge_agent.file_ws_adapter import (
    FileDispatchDenied, execute_file_dispatch,
)


@pytest.fixture
def harness(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "feature/test"], check=True)
    marker = tmp_path / "executions"
    config = tmp_path / "operator.json"
    config.write_text(json.dumps({
        "project": "demo", "branch": "feature/test", "root": str(root),
        "profiles": {
            "verify": {
                "argv": [sys.executable, "-c",
                    "from pathlib import Path; "
                    + "p=Path(" + repr(str(marker)) + "); "
                    + "p.open('a').write('executed\\n')"],
                "timeout_seconds": 10,
            }
        },
    }))
    config.chmod(0o600)
    inbox = tmp_path / "inbox"
    inbox.mkdir(mode=0o700)
    return {"root": root, "config": config, "inbox": inbox, "marker": marker}


def payload(*, ident="negative-001", project="demo", branch="feature/test",
            profile="verify", mode="test", **fields):
    instruction = {
        "schemaVersion": 1, "requestId": ident,
        "project": project, "branch": branch, "profile": profile,
    }
    instruction.update(fields.pop("instruction_fields", {}))
    result = {
        "project_id": project, "engine": "file", "mode": mode,
        "instruction": json.dumps(instruction, sort_keys=True),
        "issue_ref": None, "continue_session_id": None,
    }
    result.update(fields)
    return result


def dispatch(h, request, *, root=None):
    return execute_file_dispatch(
        request, config_path=str(h["config"]), inbox_path=str(h["inbox"]),
        approved_project_root=str(root or h["root"]),
    )


@pytest.mark.parametrize(("change", "expected"), [
    ({"mode": "implement"}, "file_engine_requires_test"),
    ({"mode": "edit"}, "file_engine_requires_test"),
    ({"engine": "codex"}, "file_engine_requires_test"),
    ({"delivery": {"branch": "main"}}, "file_engine_excludes_delivery_and_sessions"),
    ({"issue_ref": "gh:1"}, "file_engine_excludes_delivery_and_sessions"),
    ({"continue_session_id": "forbidden"}, "file_engine_excludes_delivery_and_sessions"),
    ({"project_id": "other"}, "project_mismatch"),
    ({"instruction_fields": {"profile": "arbitrary"}}, "profile_not_allowed"),
    ({"instruction_fields": {"branch": "other"}}, "project_or_branch_mismatch"),
    ({"instruction_fields": {"extra": "do-anything"}}, "ValueError"),
    ({"instruction_fields": {"schemaVersion": 2}}, "ValueError"),
])
def test_denied_requests_never_execute_or_create_inbox(harness, change, expected):
    request = payload()
    if "instruction_fields" in change:
        data = json.loads(request["instruction"])
        data.update(change["instruction_fields"])
        request["instruction"] = json.dumps(data)
    else:
        request.update(change)
    with pytest.raises((FileDispatchDenied, ValueError)) as exc:
        dispatch(harness, request)
    assert str(exc.value) == expected or (
        expected == "ValueError" and type(exc.value) is ValueError
    )
    assert not harness["marker"].exists()
    assert not list(harness["inbox"].glob("*.json"))


def test_other_workspace_and_unsafe_config_are_denied(harness, tmp_path):
    another = tmp_path / "unapproved"
    another.mkdir()
    with pytest.raises(FileDispatchDenied, match="workspace_mismatch"):
        dispatch(harness, payload(), root=another)
    harness["config"].chmod(0o666)
    with pytest.raises(FileDispatchDenied, match="unsafe_operator_config"):
        dispatch(harness, payload())
    assert not harness["marker"].exists()


def test_private_inbox_is_required(harness):
    harness["inbox"].chmod(0o755)
    with pytest.raises(FileDispatchDenied, match="unsafe_inbox_permissions"):
        dispatch(harness, payload())
    assert not harness["marker"].exists()


def test_identical_replay_returns_same_receipt_without_rerun(harness):
    request = payload(ident="replay-ok")
    first = dispatch(harness, request)
    second = dispatch(harness, request)
    assert first["status"] == second["status"] == "success"
    assert first == second
    assert harness["marker"].read_text().splitlines() == ["executed"]


def test_reused_request_id_with_modified_instruction_fails_closed(harness):
    request = payload(ident="replay-altered")
    result = dispatch(harness, request)
    changed = payload(ident="replay-altered", instruction_fields={"profile": "verify"})
    # Same semantic data with different serialized bytes must not take over an old receipt.
    assert changed["instruction"] == request["instruction"]
    changed["instruction"] = json.dumps(
        json.loads(changed["instruction"]), separators=(",", ":")
    )
    assert hashlib.sha256(changed["instruction"].encode()).hexdigest() != result["instructionSha256"]
    with pytest.raises(FileDispatchDenied, match="request_id_collision"):
        dispatch(harness, changed)
    assert harness["marker"].read_text().splitlines() == ["executed"]


def test_interrupted_running_request_is_not_reexecuted(harness):
    request = payload(ident="interrupted-001")
    (harness["inbox"] / "interrupted-001.running").write_text(request["instruction"])
    config = json.loads(harness["config"].read_text())
    result, = process_once(harness["inbox"], config)
    assert result["status"] == "failed"
    assert result["reason"] == "interrupted"
    assert not harness["marker"].exists()
    # A retry cannot restart an interrupted run.
    with pytest.raises(FileDispatchDenied, match="request_id_collision"):
        dispatch(harness, request)
    assert not harness["marker"].exists()
