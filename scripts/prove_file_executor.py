#!/usr/bin/env python3
"""End-to-end *local file executor* proof; intentionally no Gateway/WS claim."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix="codexbridge-file-proof-") as tmp:
        home = Path(tmp)
        root = home / "workspace"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "feature/proof"], check=True)
        inbox = home / "inbox"
        inbox.mkdir()
        config = home / "operator.json"
        config.write_text(json.dumps({
            "project": "proof", "branch": "feature/proof", "root": str(root),
            "profiles": {"verify": {
                "argv": [sys.executable, "-c", "print('CB_FILE_EXECUTION_OK')"],
                "timeout_seconds": 5,
            }},
        }), encoding="utf-8")
        (inbox / "proof-001.json").write_text(json.dumps({
            "schemaVersion": 1, "requestId": "proof-001",
            "project": "proof", "branch": "feature/proof", "profile": "verify",
        }), encoding="utf-8")
        command = [sys.executable, "-m", "agent.codex_bridge_agent.file_executor",
                   "--config", str(config), "--inbox", str(inbox)]
        first = subprocess.run(command, capture_output=True, text=True, check=True)
        second = subprocess.run(command, capture_output=True, text=True, check=True)
        receipt = json.loads((inbox / "results/proof-001.json").read_text())
        assert receipt["status"] == "success", receipt
        assert receipt["exitCode"] == 0, receipt
        assert "CB_FILE_EXECUTION_OK" in receipt["output"], receipt
        assert (inbox / "proof-001[DONE].json").is_file()
        assert json.loads(second.stdout) == [], second.stdout
        sanitized = {key: receipt[key] for key in (
            "requestId", "status", "exitCode", "instructionSha256",
            "startedAt", "finishedAt", "profile"
        )}
        sanitized["doneFileExists"] = True
        sanitized["replayedWithoutExecution"] = True
        sanitized["scope"] = "LOCAL_FILE_EXECUTOR_ONLY"
        destination = Path(os.environ.get("CODEXBRIDGE_FILE_PROOF_OUTPUT", str(home / "proof.json")))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(sanitized, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
