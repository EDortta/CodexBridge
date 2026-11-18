"""WebSocket task.dispatch -> durable file inbox -> deterministic execution.

This adapter never processes a command from the envelope. It only accepts
test-mode, no-delivery JSON referencing a locally provisioned profile.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile

from agent.codex_bridge_agent.file_executor import _read_instruction, process_once


class FileDispatchDenied(ValueError):
    pass


def _write_if_absent(path: Path, text: str):
    """Refuse changed re-delivery; atomic write and no replacement."""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != text:
            raise FileDispatchDenied("request_id_collision")
        return
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != text:
                raise FileDispatchDenied("request_id_collision")
    finally:
        os.unlink(temporary)


def execute_file_dispatch(payload: dict, *, config_path: str | None,
                          inbox_path: str | None, approved_project_root: str | None) -> dict:
    if not config_path or not inbox_path or not approved_project_root:
        raise FileDispatchDenied("file_executor_not_configured")
    if payload.get("mode") != "test" or payload.get("engine") != "file":
        raise FileDispatchDenied("file_engine_requires_test")
    if payload.get("delivery") or payload.get("issue_ref") or payload.get("continue_session_id"):
        raise FileDispatchDenied("file_engine_excludes_delivery_and_sessions")
    raw = payload.get("instruction")
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
        raise FileDispatchDenied("invalid_file_instruction")
    conf = Path(config_path)
    if conf.is_symlink() or not conf.is_file() or conf.stat().st_mode & 0o022:
        raise FileDispatchDenied("unsafe_operator_config")
    config = json.loads(conf.read_text(encoding="utf-8"))
    if set(config) != {"project", "branch", "root", "profiles"}:
        raise FileDispatchDenied("bad_operator_config")
    if config["project"] != payload.get("project_id"):
        raise FileDispatchDenied("project_mismatch")
    if Path(config["root"]).resolve(strict=True) != Path(approved_project_root).resolve(strict=True):
        raise FileDispatchDenied("workspace_mismatch")
    inbox = Path(inbox_path)
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    if inbox.is_symlink() or inbox.stat().st_mode & 0o077:
        raise FileDispatchDenied("unsafe_inbox_permissions")
    # Validate before writing. No paths, commands, or argv accepted in task.
    candidate = json.loads(raw)
    if not isinstance(candidate, dict):
        raise FileDispatchDenied("invalid_instruction_type")
    request_id = candidate.get("requestId")
    if not isinstance(request_id, str):
        raise FileDispatchDenied("missing_request_id")
    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp) / "candidate.json"
        temporary.write_text(raw, encoding="utf-8")
        validated, _digest = _read_instruction(temporary)
    if validated["project"] != config["project"] or validated["branch"] != config["branch"]:
        raise FileDispatchDenied("project_or_branch_mismatch")
    if validated["profile"] not in config["profiles"]:
        raise FileDispatchDenied("profile_not_allowed")
    target = inbox / (request_id + ".json")
    completed = inbox / "results" / (request_id + ".json")
    if completed.exists():
        # The original result is immutable, including its failure status.
        return json.loads(completed.read_text(encoding="utf-8"))
    done = inbox / (request_id + "[DONE].json")
    if done.exists():
        raise FileDispatchDenied("completed_without_receipt")
    _write_if_absent(target, raw)
    outcomes = process_once(inbox, config, only_id=request_id)
    if outcomes:
        return outcomes[0]
    if completed.is_file():
        return json.loads(completed.read_text(encoding="utf-8"))
    raise FileDispatchDenied("execution_not_recorded")


async def dispatch_file_task(payload: dict, *, config_path: str | None,
                             inbox_path: str | None, approved_project_root: str | None) -> dict:
    return await asyncio.to_thread(
        execute_file_dispatch, payload, config_path=config_path,
        inbox_path=inbox_path, approved_project_root=approved_project_root
    )
