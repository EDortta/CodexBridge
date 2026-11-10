"""Fail-closed candidate normalization for future Worker-request dispatch.

A candidate is *never* an authorization. Nothing in this module sends an
agent message, opens a worktree, or changes a database row.
"""
from __future__ import annotations

from dataclasses import dataclass

from scripts.worker_request import validate_envelope
from shared.protocol import TaskMode

# Only modes with an existing, read-only/test-only TaskMode mapping are eligible.
# "verify" and "build" are transport vocabulary, not execution permissions.
_SAFE_OPERATIONS = {"analyze": TaskMode.ANALYZE, "test": TaskMode.TEST}


class WorkerDispatchCandidateDenied(ValueError):
    """Rejected before any executor or authorization lookup."""


@dataclass(frozen=True)
class WorkerDispatchCandidate:
    project_id: str
    request_id: str
    node_id: str
    source_branch: str
    source_commit: str
    mode: TaskMode
    require_active_binding: bool = True
    delivery_allowed: bool = False


def make_dispatch_candidate(envelope: object, *, activated_project: str) -> WorkerDispatchCandidate:
    """Validate immutable transport data without treating it as authorization.

    A later Gateway stage MUST additionally check: admitted ledger identity
    and digest, source SHA against the approved forge, enabled Node and
    connected Executor, active workspace binding and capability, operator
    execution grant, and idempotent Task/Mission creation. The agent must
    independently enforce the capability. No operation may infer approval
    from this returned object.
    """
    try:
        req = validate_envelope(envelope, activated_project=activated_project)
    except (TypeError, ValueError, KeyError) as exc:
        raise WorkerDispatchCandidateDenied("invalid transport envelope") from exc

    mode = _SAFE_OPERATIONS.get(req["operation"])
    if mode is None:
        raise WorkerDispatchCandidateDenied("operation not enabled for dispatch")

    targets = req["targets"]
    if targets["mode"] != "selected" or len(targets["nodes"]) != 1:
        raise WorkerDispatchCandidateDenied("dispatch requires exactly one explicitly selected node")

    return WorkerDispatchCandidate(
        project_id=req["project"],
        request_id=req["requestId"],
        node_id=targets["nodes"][0],
        source_branch=req["source"]["branch"],
        source_commit=req["source"]["commit"].lower(),
        mode=mode,
    )
