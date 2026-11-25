#!/usr/bin/env python3
"""Provision an isolated Python test runner and bind the local approved profile.

Operator-owned settings only. Never edits task instructions, gateway policy,
systemd service, repository source, or broadens capability permissions.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> int:
    from agent.codex_bridge_agent.config import AgentSettings
    systemd = subprocess.run(
        ["systemctl", "--user", "show", "codex-bridge-agent.service",
         "--property=Environment", "--value"],
        check=True, capture_output=True, text=True,
    ).stdout
    for token in shlex.split(systemd):
        if token.startswith("CODEX_BRIDGE_AGENT_") and "=" in token:
            key, value = token.split("=", 1)
            os.environ[key] = value
    settings = AgentSettings()
    path = Path(settings.file_executor_config_file)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o022:
        print("STATUS=unsafe_operator_config")
        return 2
    config = json.loads(path.read_text(encoding="utf-8"))
    if set(config) != {"project", "branch", "root", "profiles"}:
        print("STATUS=invalid_config")
        return 2
    if config["project"] != "codexbridge" or config["branch"] != "feature/file-instruction-ws-bridge":
        print("STATUS=wrong_project_or_branch")
        return 2
    root = Path(config["root"]).resolve(strict=True)
    if root != ROOT or not root.is_dir():
        print("STATUS=wrong_worktree")
        return 2
    profile = config["profiles"].get("unit-tests")
    if not isinstance(profile, dict) or not isinstance(profile.get("argv"), list):
        print("STATUS=profile_missing")
        return 2
    argv = profile["argv"]
    expected = ["-m", "pytest", "-q", "tests/unit/test_file_executor.py",
                "tests/unit/test_file_ws_adapter.py"]
    if len(argv) != len(expected) + 1 or argv[1:] != expected:
        print("STATUS=unexpected_profile_command")
        return 2

    # Exercise the same environment the executor's _execute() gives its child.
    isolated = {"PATH": os.defpath, "HOME": str(root), "LANG": "C", "LC_ALL": "C"}
    candidates = [
        Path.home() / ".local/share/codex-bridge/.venv/bin/python",
        root / ".venv/bin/python",
        Path(sys.executable).resolve(),
    ]
    def works(candidate: Path) -> bool:
        if not candidate.is_file():
            return False
        try:
            trial = subprocess.run([str(candidate), "-c",
                "import pytest, fastapi, sqlalchemy; print('ready')"],
                cwd=root, env=isolated, capture_output=True, timeout=20)
            return trial.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    interpreter = next((p for p in candidates if works(p)), None)
    installed = False
    if interpreter is None:
        interpreter = Path.home() / ".local/share/codex-bridge/pytest-venv/bin/python"
        venv = interpreter.parent.parent
        if not interpreter.is_file():
            created = subprocess.run([sys.executable, "-m", "venv", str(venv)],
                cwd=root, capture_output=True, timeout=90)
            if created.returncode:
                print("STATUS=venv_creation_failed")
                return 2
        pip = subprocess.run([str(interpreter), "-m", "pip", "install", "-e", ".[test]"],
            cwd=root, capture_output=True, timeout=220)
        if pip.returncode or not works(interpreter):
            print("STATUS=pytest_dependency_install_failed")
            return 2
        installed = True
    if argv[0] != str(interpreter):
        config["profiles"]["unit-tests"]["argv"][0] = str(interpreter)
        # Atomic replacement; strictly preserve original private file mode.
        fd, temporary = tempfile.mkstemp(prefix=".file-executor-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                os.fchmod(out.fileno(), path.stat().st_mode & 0o777)
                json.dump(config, out, sort_keys=True, indent=2)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print("STATUS=ready")
    print("ISOLATED_INTERPRETER_VERIFIED=true")
    print("PROFILE_CHANGED=" + str(argv[0] != str(interpreter)).lower())
    print("TEST_ENV_CREATED=" + str(installed).lower())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
