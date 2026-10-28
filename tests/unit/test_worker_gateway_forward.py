"""Worker forwarding is opt-in and remains strictly Gateway-bound."""
import json
from unittest.mock import patch
import pytest
from test_worker_watch import worker_watch


def observation():
    return {"project": "codexbridge", "repository": "EDortta/CodexBridge",
            "branch": "codexbridge-control"}


def envelope():
    return {"requestId": "req-1", "project": "codexbridge"}


def test_gateway_request_uses_https_and_separate_machine_token():
    class FakeResponse:
        status = 202
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, n):
            return json.dumps({"requestId": "req-1", "projectId": "codexbridge",
                               "state": "admitted", "created": True}).encode()

    with patch.object(worker_watch, "urlopen", return_value=FakeResponse()) as open_request:
        result = worker_watch.gateway_intake("https://gateway.example", "z" * 48,
                                             observation(), envelope())
    req = open_request.call_args.args[0]
    assert req.full_url == "https://gateway.example/control/worker-intake/requests"
    assert req.get_method() == "POST"
    assert req.get_header("X-worker-token") == "z" * 48
    assert json.loads(req.data)["envelope"] == envelope()
    assert result == {"requestId": "req-1", "state": "admitted", "created": True}


@pytest.mark.parametrize("url", ["http://gateway.example", "https://u:p@gateway.example",
                               "https://gateway.example/other", "https://gateway.example?secret=1"])
def test_refuses_unsafe_gateway_url(url):
    with pytest.raises(ValueError):
        worker_watch.gateway_intake(url, "z" * 48, observation(), envelope())


def test_rejects_unexpected_gateway_ack():
    class FakeResponse:
        status = 202
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, n):
            return b'{"requestId":"wrong","projectId":"codexbridge","state":"admitted","created":true}'

    with patch.object(worker_watch, "urlopen", return_value=FakeResponse()):
        with pytest.raises(ValueError, match="acknowledgement"):
            worker_watch.gateway_intake("https://gateway.example", "z" * 48,
                                        observation(), envelope())
