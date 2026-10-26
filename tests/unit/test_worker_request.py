import sys
from pathlib import Path
from copy import deepcopy
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from worker_request import InvalidControlRequest, validate_envelope


def valid():
    return {
        "schemaVersion": 1, "requestId": "r-001", "project": "codexbridge",
        "operation": "analyze", "source": {"branch": "feature/x", "commit": "a" * 40},
        "targets": {"mode": "selected", "nodes": ["devel3"]}, "parameters": {},
    }


def test_accepts_declared_shape():
    assert validate_envelope(valid(), activated_project="codexbridge") == valid()


@pytest.mark.parametrize("change", [
    lambda x: x.update(command="rm -rf /"),
    lambda x: x.update(project="other"),
    lambda x: x.update(schemaVersion=True),
    lambda x: x.update(operation="shell"),
    lambda x: x.update(operation=[]),
    lambda x: x["source"].update(commit="latest"),
    lambda x: x["source"].update(branch="codexbridge-control"),
    lambda x: x["source"].update(branch="../unsafe"),
    lambda x: x["targets"].update(mode="all"),
    lambda x: x["targets"].update(nodes=["devel3", "devel3"]),
    lambda x: x.update(parameters={"command": "whoami"}),
])
def test_rejects_unsafe(change):
    obj = deepcopy(valid())
    change(obj)
    with pytest.raises(InvalidControlRequest):
        validate_envelope(obj, activated_project="codexbridge")


def test_all_mode_requires_empty_nodes():
    obj = valid()
    obj["targets"] = {"mode": "all", "nodes": []}
    assert validate_envelope(obj, activated_project="codexbridge") == obj
