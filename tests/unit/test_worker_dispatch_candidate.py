"""Worker control requests cannot authorize themselves to execute."""
from __future__ import annotations

from copy import deepcopy

import pytest

from gateway.app.services.worker_dispatch_candidate import (
    WorkerDispatchCandidateDenied,
    make_dispatch_candidate,
)
from shared.protocol import TaskMode


def envelope():
    return {
        "schemaVersion": 1,
        "requestId": "smoke-1",
        "project": "codexbridge",
        "operation": "analyze",
        "source": {"branch": "development", "commit": "a" * 40},
        "targets": {"mode": "selected", "nodes": ["devel3"]},
        "parameters": {},
    }


def test_exactly_one_selected_node_produces_non_authorizing_candidate():
    candidate = make_dispatch_candidate(envelope(), activated_project="codexbridge")
    assert candidate.project_id == "codexbridge"
    assert candidate.node_id == "devel3"
    assert candidate.mode == TaskMode.ANALYZE
    assert candidate.source_commit == "a" * 40
    assert candidate.require_active_binding is True
    assert candidate.delivery_allowed is False


def test_test_maps_to_existing_task_mode():
    request = envelope()
    request["operation"] = "test"
    assert make_dispatch_candidate(request, activated_project="codexbridge").mode == TaskMode.TEST


@pytest.mark.parametrize("operation", ["build", "verify", "implement", "edit", "review"])
def test_unsupported_operation_never_becomes_execution_permission(operation):
    request = envelope()
    request["operation"] = operation
    with pytest.raises(WorkerDispatchCandidateDenied):
        make_dispatch_candidate(request, activated_project="codexbridge")


@pytest.mark.parametrize("targets", [
    {"mode": "all", "nodes": []},
    {"mode": "selected", "nodes": ["devel3", "frida"]},
    {"mode": "selected", "nodes": []},
])
def test_ambiguous_node_selection_denied(targets):
    request = envelope()
    request["targets"] = targets
    with pytest.raises(WorkerDispatchCandidateDenied):
        make_dispatch_candidate(request, activated_project="codexbridge")


def test_payload_cannot_smuggle_execution_command():
    request = envelope()
    request["parameters"] = {"shell": "echo unsafe"}
    with pytest.raises(WorkerDispatchCandidateDenied):
        make_dispatch_candidate(request, activated_project="codexbridge")


def test_project_mismatch_denied():
    with pytest.raises(WorkerDispatchCandidateDenied):
        make_dispatch_candidate(envelope(), activated_project="another-project")


def test_source_commit_must_be_immutable_full_sha():
    request = envelope()
    request["source"]["commit"] = "HEAD"
    with pytest.raises(WorkerDispatchCandidateDenied):
        make_dispatch_candidate(request, activated_project="codexbridge")


def test_candidate_is_immutable():
    from dataclasses import FrozenInstanceError
    candidate = make_dispatch_candidate(envelope(), activated_project="codexbridge")
    with pytest.raises(FrozenInstanceError):
        candidate.node_id = "other"
