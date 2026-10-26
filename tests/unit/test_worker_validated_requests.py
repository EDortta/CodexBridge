import base64
from unittest.mock import patch
import pytest

from test_worker_watch import worker_watch


def envelope(request_id="req-1"):
    return {
        "schemaVersion": 1, "requestId": request_id, "project": "codexbridge",
        "operation": "analyze", "source": {"branch": "feature/example", "commit": "a" * 40},
        "targets": {"mode": "selected", "nodes": ["devel3"]}, "parameters": {},
    }


def observation(name="req-1.json"):
    return {"project": "codexbridge", "repository": "EDortta/CodexBridge",
            "requests": [{"name": name, "sha": "b" * 40}]}


def test_immutable_blob_is_validated():
    import json
    payload = base64.b64encode(json.dumps(envelope()).encode()).decode()
    with patch.object(worker_watch, "github_json",
                      return_value={"encoding": "base64", "content": payload}) as read:
        assert worker_watch.read_validated_requests(observation(), None) == [
            {"requestId": "req-1", "blobSha": "b" * 40}
        ]
    assert "/git/blobs/" + "b" * 40 in read.call_args.args[0]
    assert "?ref=" not in read.call_args.args[0]


def test_filename_mismatch_is_rejected():
    import json
    payload = base64.b64encode(json.dumps(envelope()).encode()).decode()
    with patch.object(worker_watch, "github_json",
                      return_value={"encoding": "base64", "content": payload}):
        with pytest.raises(ValueError):
            worker_watch.read_validated_requests(observation("wrong.json"), None)


def test_shell_command_is_rejected():
    import json
    item = envelope()
    item["command"] = "sh -c whoami"
    payload = base64.b64encode(json.dumps(item).encode()).decode()
    with patch.object(worker_watch, "github_json",
                      return_value={"encoding": "base64", "content": payload}):
        with pytest.raises(ValueError):
            worker_watch.read_validated_requests(observation(), None)
