#!/usr/bin/env python3
"""Align the live user's Agent project allowlist with the approved file-test root.

Only changes the codexbridge project's PATH in the already configured Agent
allowlist. Does not broaden allowed projects, modes, scopes or executable
profiles. Keeps a private backup; requires restarting the user Agent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> int:
    from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects
    pid = subprocess.check_output([
        "systemctl", "--user", "show", "-p", "MainPID", "--value",
        "codex-bridge-agent.service"], text=True).strip()
    if not pid.isdecimal() or int(pid) <= 0:
        print("STATUS=agent_not_running")
        return 2
    proc = Path("/proc") / pid
    try:
        cwd = Path(os.readlink(proc / "cwd"))
        entries = (proc / "environ").read_bytes().split(bytes([0]))
    except OSError:
        print("STATUS=agent_process_unreadable")
        return 2
    oldcwd = Path.cwd()
    original = {k: os.environ.get(k) for k in list(os.environ)
                if k.startswith("CODEX_BRIDGE_AGENT_")}
    try:
        for key in original:
            del os.environ[key]
        for entry in entries:
            if entry.startswith(b"CODEX_BRIDGE_AGENT_") and b"=" in entry:
                key, value = entry.split(b"=", 1)
                os.environ[key.decode()] = value.decode()
        os.chdir(cwd)
        settings = AgentSettings()
        conf = Path(settings.file_executor_config_file or "")
        allowlist = Path(settings.allowed_projects_file)
        if not conf.is_absolute():
            conf = cwd / conf
        if not allowlist.is_absolute():
            allowlist = cwd / allowlist
    finally:
        os.chdir(oldcwd)
        for key in list(os.environ):
            if key.startswith("CODEX_BRIDGE_AGENT_"):
                del os.environ[key]
        os.environ.update({k:v for k,v in original.items() if v is not None})
    if (not conf.is_file() or conf.is_symlink()
            or not allowlist.is_file() or allowlist.is_symlink()):
        print("STATUS=operator_file_unavailable")
        return 2
    config = json.loads(conf.read_text())
    if set(config) != {"project", "branch", "root", "profiles"}:
        print("STATUS=operator_config_invalid")
        return 2
    if config["project"] != "codexbridge" or config["branch"] != "feature/file-instruction-ws-bridge":
        print("STATUS=unexpected_project_branch")
        return 2
    target = Path(config["root"]).resolve(strict=True)
    if target != ROOT.resolve(strict=True):
        print("STATUS=target_not_current_worktree")
        return 2
    branch = subprocess.check_output(["git", "-C", str(target),
                                      "symbolic-ref", "--quiet", "--short", "HEAD"],
                                     text=True).strip()
    if branch != config["branch"]:
        print("STATUS=branch_mismatch")
        return 2
    if not all((target / p).is_file() for p in [
        "tests/unit/test_file_executor.py", "tests/unit/test_file_ws_adapter.py"
    ]):
        print("STATUS=tests_missing")
        return 2
    if allowlist.stat().st_mode & 0o022:
        print("STATUS=unsafe_allowlist_permissions")
        return 2
    data = json.loads(allowlist.read_text())
    projects = data.get("projects")
    if not isinstance(projects, list):
        print("STATUS=invalid_allowlist")
        return 2
    selected = [p for p in projects if isinstance(p,dict) and p.get("project_id")=="codexbridge"]
    if len(selected) != 1:
        print("STATUS=project_registration_ambiguous")
        return 2
    current = Path(selected[0]["path"]).resolve()
    if current == target:
        print("STATUS=aligned")
        print("CHANGED=false")
        return 0
    # Only an explicit already registered project changes. Refuse to replace
    # an authorized unrelated checkout: preserve the existing access boundary.
    if not current.is_dir() or not (current / ".git").exists():
        print("STATUS=current_workspace_not_verified")
        return 2
    if (subprocess.run(["git","-C",str(current),"rev-parse","--show-toplevel"],
                       capture_output=True).returncode != 0):
        print("STATUS=current_workspace_not_git")
        return 2
    selected[0]["path"] = str(target)
    backup = allowlist.with_name(allowlist.name + ".backup-file-mvp-" +
                                 datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.write_bytes(allowlist.read_bytes())
    backup.chmod(0o600)
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    temporary = allowlist.with_name("." + allowlist.name + "." + secrets.token_hex(6))
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, allowlist.stat().st_mode & 0o777)
        os.replace(temporary,allowlist)
    finally:
        temporary.unlink(missing_ok=True)
    print("STATUS=aligned")
    print("CHANGED=true")
    print("RESTART_AGENT_REQUIRED=true")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
