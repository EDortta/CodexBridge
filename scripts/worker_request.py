"""Strict transport-envelope validation before any Gateway admission.

This does not authorize execution. Gateway MUST authenticate the Worker/operator,
validate activation, commit, Node, capabilities and catalog operation again.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
FULL_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")
NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
OPERATIONS = frozenset({"analyze", "test", "verify", "build"})


class InvalidControlRequest(ValueError):
    pass


def validate_envelope(value: object, *, activated_project: str) -> dict:
    """Return sanitized, structurally checked request. Never run it locally."""
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "requestId", "project", "operation", "source", "targets", "parameters"
    }:
        raise InvalidControlRequest("unexpected request fields")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise InvalidControlRequest("unsupported schema")
    project, request_id = value["project"], value["requestId"]
    if not isinstance(project, str) or not PROJECT_ID.fullmatch(project) or project != activated_project:
        raise InvalidControlRequest("project mismatch")
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise InvalidControlRequest("invalid request id")
    if value["operation"] not in OPERATIONS:
        raise InvalidControlRequest("operation outside transport vocabulary")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != {"branch", "commit"}:
        raise InvalidControlRequest("invalid source")
    branch, commit = source["branch"], source["commit"]
    if not isinstance(branch, str) or not BRANCH.fullmatch(branch) or (
        ".." in branch or "//" in branch or branch.endswith(("/", ".", ".lock"))
        or any(part.startswith(".") for part in branch.split("/"))
    ) or branch == "codexbridge-control":
        raise InvalidControlRequest("unsafe code branch")
    if not isinstance(commit, str) or not FULL_SHA.fullmatch(commit):
        raise InvalidControlRequest("full immutable commit SHA required")
    targets = value["targets"]
    if not isinstance(targets, dict) or set(targets) != {"mode", "nodes"}:
        raise InvalidControlRequest("invalid targets")
    mode, nodes = targets["mode"], targets["nodes"]
    if mode not in {"all", "selected"} or not isinstance(nodes, list):
        raise InvalidControlRequest("invalid selection")
    if mode == "all" and nodes:
        raise InvalidControlRequest("all mode must not include explicit nodes")
    if mode == "selected" and not 1 <= len(nodes) <= 20:
        raise InvalidControlRequest("selected mode requires 1-20 nodes")
    if any(not isinstance(n, str) or not NODE_ID.fullmatch(n) for n in nodes):
        raise InvalidControlRequest("invalid node identifier")
    if len(set(nodes)) != len(nodes):
        raise InvalidControlRequest("duplicate nodes")
    if not isinstance(value["parameters"], dict) or value["parameters"]:
        raise InvalidControlRequest("parameters are not enabled in this increment")
    return value.copy()
