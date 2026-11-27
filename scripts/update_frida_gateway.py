#!/usr/bin/env python3
"""Idempotent Gateway code updater: package -> transfer -> check -> apply -> verify -> publish.

LEGACY OAuth-138 updater, retained for historical compatibility.
Canonical operator entrypoint for new releases:
    python3 scripts/deploy_gateway.py

The remote interpreter only uses Python stdlib; no Git on frida. On the first
rollout this updater has a narrow, explicit scope (four OAuth files), while
the mechanism is reusable for future Gateway profiles. Database schema,
environment, SQLite files, virtualenv, and system configuration are untouched.
The immutable development-evidences manifest is part of the acceptance gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

FILES = (
    "gateway/app/main.py",
    "gateway/app/api/routes/auth.py",
    "gateway/app/core/config.py",
    "gateway/app/core/oauth.py",
    "gateway/app/services/agent_hub.py",
)
# Recorded by the read-only frida baseline evidence 141902-d9e5a470.
HISTORICAL_MAIN = "196de250b9dc323f0cd7a1047b22aabed36ffc37"
HISTORICAL_MAIN_SHA = "9bc3f8a693c14ed77badc0d4b360b7cdd8f55ea0881657996acbe4cd52578086"
DEFAULT_HOST = "esteban@frida.inovacaosistemas.com.br"
DEFAULT_PORT = "2200"
ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
PUBLISHER = Path(os.environ.get(
    "DEVELOPMENT_EVIDENCES_ROOT", str(STATE / "development-evidences/repo")
)) / "publisher.py"
EVIDENCE_REPO = "https://github.com/EDortta/development-evidences"
HEX64 = re.compile(r"^[a-f0-9]{64}$")
HEX40 = re.compile(r"^[a-f0-9]{40}$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, stderr=subprocess.DEVNULL, text=True
    ).strip()


def git_file(revision: str, filename: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{revision}:{filename}"],
        cwd=ROOT, stderr=subprocess.DEVNULL,
    )


def create_package(directory: Path, *, source_commit: str) -> dict:
    # The baseline is per-file: frida currently has an older, verified main.py
    # and development versions of three other OAuth modules.
    items = []
    package = directory / "package.tar.gz"
    with tarfile.open(package, "w:gz") as archive:
        for name in FILES:
            content = git_file(source_commit, name)
            target_hash = sha(content)
            baseline_ref = (
                HISTORICAL_MAIN if name in {
                    "gateway/app/main.py", "gateway/app/services/agent_hub.py"
                } else "origin/development"
            )
            baseline_hash = sha(git_file(baseline_ref, name))
            if name == "gateway/app/main.py" and baseline_hash != HISTORICAL_MAIN_SHA:
                raise ValueError("historical_baseline_mismatch")
            # An already-applied #138 release is a valid predecessor for
            # a new OAuth policy. Never overwrite unrelated unknown bytes.
            previous_release = sha(git_file(
                "6aa91e84e03776901f7557f026c47bfd34de4233", name
            ))
            items.append({
                "path": name,
                "expected_sha256": baseline_hash,
                "allowed_previous_sha256": [previous_release],
                "target_sha256": target_hash,
            })
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))
    manifest = {
        "schema": 1,
        "profile": "oauth-138",
        "source_commit": source_commit,
        "archive_sha256": sha(package.read_bytes()),
        "files": items,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=ROOT, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def publish(relative_path: str, report: dict) -> bool:
    with tempfile.TemporaryDirectory(prefix="codexbridge-update-proof-") as temp:
        envelope = Path(temp) / "envelope.json"
        envelope.write_text(
            json.dumps({"relative_path": relative_path, "report": report},
                       sort_keys=True, indent=2) + "\n"
        )
        for args in (["enqueue", "--file", str(envelope)], ["flush"]):
            response = run([sys.executable, str(PUBLISHER), *args], timeout=120)
            if response.returncode:
                return False
            if args[0] == "flush" and f"published={relative_path}" not in response.stdout.splitlines():
                return False
    return True


def classify_installed(items: list[dict], hashes: dict[str, str]) -> list[str]:
    """Fail closed on unrecognized remote bytes; return only files needing update."""
    changes = []
    for item in items:
        name = item["path"]
        current = hashes.get(name, "")
        allowed = {item["expected_sha256"], item["target_sha256"]}
        allowed.update(item.get("allowed_previous_sha256", []))
        if current not in allowed:
            raise ValueError("unknown_installed_baseline:" + name)
        if current != item["target_sha256"]:
            changes.append(name)
    return changes


def operate_remote(stage: Path, *, check_only: bool = False) -> dict:
    """Runs under sudo on frida. Strict allowlist; never reads private env."""
    import pwd
    import urllib.request

    def health() -> bool:
        try:
            with urllib.request.urlopen("http://127.0.0.1:18080/health", timeout=4) as res:
                return res.status == 200
        except Exception:
            return False

    def active() -> bool:
        return subprocess.run(
            ["systemctl", "is-active", "--quiet", "codex-bridge-gateway"],
            check=False,
        ).returncode == 0

    if os.geteuid() != 0 or not os.environ.get("SUDO_USER"):
        raise ValueError("remote_requires_sudo_from_operator")
    home = Path(pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir)
    stage = stage.resolve(strict=True)
    allowed_root = (home / "codexbridge-staging").resolve(strict=True)
    if allowed_root not in stage.parents or not re.fullmatch(r"auto138-[a-f0-9]{12}", stage.name):
        raise ValueError("invalid_staging_location")
    manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("profile") != "oauth-138":
        raise ValueError("invalid_manifest_schema")
    items = manifest.get("files")
    if not isinstance(items, list) or [item.get("path") for item in items] != list(FILES):
        raise ValueError("unexpected_update_scope")
    if not HEX40.fullmatch(manifest.get("source_commit", "")):
        raise ValueError("invalid_source_commit")
    archive = stage / "package.tar.gz"
    if sha(archive.read_bytes()) != manifest.get("archive_sha256"):
        raise ValueError("package_checksum_mismatch")
    desired: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        if len(members) != len(FILES) or [m.name for m in members] != list(FILES):
            raise ValueError("unexpected_archive_members")
        for item, member in zip(items, members):
            name = item["path"]
            if not member.isfile() or member.size > 1000000:
                raise ValueError("unsupported_member")
            raw = package.extractfile(member).read()
            if not HEX64.fullmatch(item.get("expected_sha256", "")) or not HEX64.fullmatch(item.get("target_sha256", "")):
                raise ValueError("invalid_file_digest")
            predecessors = item.get("allowed_previous_sha256", [])
            if (not isinstance(predecessors, list) or len(predecessors) > 4 or
                any(not isinstance(value, str) or not HEX64.fullmatch(value) for value in predecessors)):
                raise ValueError("invalid_predecessor_digest")
            if sha(raw) != item["target_sha256"]:
                raise ValueError("candidate_digest_mismatch")
            desired[name] = raw

    target = Path("/opt/codex-bridge")
    if not active() or not health():
        raise ValueError("gateway_not_healthy_before_update")
    existing = {}
    current_hashes = {}
    for item in items:
        name = item["path"]
        current = target / name
        if not current.is_file() or current.is_symlink():
            raise ValueError("missing_or_symlinked_target:" + name)
        current_bytes = current.read_bytes()
        current_hashes[name] = sha(current_bytes)
        existing[name] = (current_bytes, current.stat())
    changes = classify_installed(items, current_hashes)
    if not changes:
        return {"status": "already_current", "changed_count": 0,
                "service_active": True, "health_ok": True}
    if check_only:
        return {"status": "ready", "changed_count": len(changes),
                "service_active": True, "health_ok": True}

    release_id = stage.name
    backup = Path("/var/backups/codexbridge") / release_id
    if backup.exists():
        raise ValueError("backup_already_exists")
    backup.mkdir(parents=True, mode=0o700)
    for name in FILES:
        dest = backup / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(existing[name][0])
        dest.chmod(0o600)
    # Syntax validation is performed on all candidate files before the stop.
    for name in FILES:
        compile(desired[name], name, "exec")

    modified = False
    try:
        stopped = subprocess.run(["systemctl", "stop", "codex-bridge-gateway"], check=False)
        modified = True  # Even an unsuccessful stop may have changed service state.
        if stopped.returncode:
            raise RuntimeError("service_stop_failed")
        for name in changes:
            current = target / name
            stat = existing[name][1]
            temp_path = current.with_name(current.name + ".issue138-new")
            with temp_path.open("wb") as handle:
                handle.write(desired[name])
                handle.flush()
                os.fsync(handle.fileno())
            os.chown(temp_path, stat.st_uid, stat.st_gid)
            os.chmod(temp_path, stat.st_mode & 0o777)
            os.replace(temp_path, current)
        if subprocess.run(["systemctl", "start", "codex-bridge-gateway"], check=False).returncode:
            raise RuntimeError("service_start_failed")
        for _ in range(30):
            if active() and health():
                break
            time.sleep(2)
        else:
            raise RuntimeError("post_update_health_failed")
        # A healthy app that does not expose the refresh grant is not an
        # acceptable OAuth patch.
        import urllib.request
        with urllib.request.urlopen(
            "http://127.0.0.1:18080/.well-known/oauth-authorization-server", timeout=6
        ) as res:
            metadata = json.load(res)
        if "refresh_token" not in metadata.get("grant_types_supported", []):
            raise RuntimeError("oauth_refresh_not_advertised")
    except Exception:
        rollback_ok = False
        if modified:
            try:
                for name in changes:
                    current = target / name
                    original, stat = existing[name]
                    temp_path = current.with_name(current.name + ".issue138-rollback")
                    temp_path.write_bytes(original)
                    os.chown(temp_path, stat.st_uid, stat.st_gid)
                    os.chmod(temp_path, stat.st_mode & 0o777)
                    os.replace(temp_path, current)
                subprocess.run(["systemctl", "restart", "codex-bridge-gateway"], check=False)
                for _ in range(30):
                    if active() and health():
                        rollback_ok = True
                        break
                    time.sleep(2)
            except Exception:
                pass
        return {
            "status": "failed",
            "failure_class": "apply_or_acceptance",
            "rollback_attempted": modified,
            "rollback_healthy": rollback_ok,
            "service_active": active(),
            "health_ok": health(),
            "changed_count": len(changes),
        }
    return {
        "status": "updated", "changed_count": len(changes),
        "service_active": active(), "health_ok": health(),
        "oauth_refresh_discovery": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote-apply", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--check", action="store_true", help="Inspect and stage only")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT)
    args = parser.parse_args()
    if args.remote_apply:
        # Remote mode prints ONLY sanitized JSON, never tokens or raw logs.
        try:
            result = operate_remote(args.remote_apply, check_only=args.check)
        except Exception as exc:
            reason = str(exc).split(":", 1)[0][:64]
            result = {"status": "failed", "failure_class": reason}
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in ("updated", "already_current", "ready") else 1

    if not args.port.isdigit() or not re.fullmatch(r"[A-Za-z0-9@._-]+", args.host):
        parser.error("invalid remote connection details")
    try:
        branch = git("symbolic-ref", "--short", "HEAD")
        commit = git("rev-parse", "HEAD")
        evidence_branch = subprocess.check_output(
            ["git", "symbolic-ref", "--short", "HEAD"], cwd=PUBLISHER.parent,
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if not HEX40.fullmatch(commit) or evidence_branch != "main" or not PUBLISHER.is_file():
            raise ValueError("publisher_guard_failed")
        if git("status", "--porcelain", "--untracked-files=no"):
            raise ValueError("uncommitted_changes")
    except (OSError, subprocess.CalledProcessError, ValueError):
        print("BLOCKED: source checkout or evidence publisher unavailable", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    stage_id = "auto138-" + uuid.uuid4().hex[:12]
    work = STATE / "codexbridge/updates" / run_id
    work.mkdir(parents=True, exist_ok=False, mode=0o700)
    result: dict = {"status": "failed", "failure_class": "not_started"}
    started = time.monotonic()
    local_tests_rc = None
    failed_tests: list[str] = []
    try:
        # A failed local gate prevents ANY remote mutation. The raw pytest
        # output remains mode 0600 on devel3, never in the shared manifest.
        test_log = work / "pytest.log"
        with test_log.open("wb") as output:
            os.chmod(test_log, 0o600)
            try:
                tests = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q",
                     "tests/integration/test_oauth_authorize.py",
                     "tests/unit/test_issue_138_diagnostics.py",
                     "tests/unit/test_update_frida_gateway.py"],
                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                    stderr=subprocess.STDOUT, timeout=180, check=False,
                )
                local_tests_rc = tests.returncode
            except (OSError, subprocess.TimeoutExpired):
                local_tests_rc = 125
        if local_tests_rc:
            # Only pytest node IDs are exported: no traceback, parameters,
            # credentials, stdout, or environment details. Filter to the
            # statically known test modules and bounded safe characters.
            raw_log = test_log.read_text(encoding="utf-8", errors="replace")
            for line in raw_log.splitlines():
                match = re.match(
                    r"^FAILED (tests/(?:integration/test_oauth_authorize|"
                    r"unit/test_issue_138_diagnostics|unit/test_update_frida_gateway)"
                    r"\.py::[A-Za-z0-9_]+)",
                    line,
                )
                if match and match.group(1) not in failed_tests:
                    failed_tests.append(match.group(1))
                if len(failed_tests) >= 20:
                    break
            raise RuntimeError("local_tests_failed")
        create_package(work, source_commit=commit)
        # Remote first-party staging directory is private to the SSH user.
        remote_stage = f"codexbridge-staging/{stage_id}"
        mkdir = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                     "-p", args.port, args.host,
                     f"umask 077; mkdir -p ~/codexbridge-staging/{stage_id}"], timeout=25)
        if mkdir.returncode:
            raise RuntimeError("ssh_staging_failed")
        upload = run(["scp", "-q", "-P", args.port, str(work / "manifest.json"),
                      str(work / "package.tar.gz"), str(Path(__file__).resolve()),
                      args.host + ":" + remote_stage + "/"], timeout=60)
        if upload.returncode:
            raise RuntimeError("scp_upload_failed")
        remote_cmd = (
            f"sudo -n python3 ~/codexbridge-staging/{stage_id}/update_frida_gateway.py "
            f"--remote-apply ~/codexbridge-staging/{stage_id}"
            + (" --check" if args.check else "")
        )
        applied = run(["ssh", "-o", "BatchMode=yes", "-p", args.port, args.host,
                       remote_cmd], timeout=150)
        try:
            result = json.loads(applied.stdout.strip())
            if not isinstance(result, dict) or result.get("status") not in {
                "updated", "already_current", "ready", "failed"
            }:
                raise ValueError("invalid_remote_result")
        except (ValueError, json.JSONDecodeError):
            result = {"status": "failed", "failure_class": "remote_result_invalid"}
        if applied.returncode and result.get("status") != "failed":
            result = {"status": "failed", "failure_class": "remote_process_failed"}
    except (OSError, subprocess.TimeoutExpired, ValueError, RuntimeError) as exc:
        result = {"status": "failed", "failure_class": str(exc).split(":", 1)[0][:64]}

    # Only allowlisted properties leave the operator's machine.
    outcome = result.get("status", "failed")
    published_result = {
        "status": outcome,
        "failure_class": re.sub(r"[^A-Za-z0-9_-]", "", str(result.get("failure_class", "")))[:64],
        "changed_count": result.get("changed_count"),
        "service_active": result.get("service_active"),
        "health_ok": result.get("health_ok"),
        "rollback_attempted": result.get("rollback_attempted"),
        "rollback_healthy": result.get("rollback_healthy"),
        "oauth_refresh_discovery": result.get("oauth_refresh_discovery"),
    }
    report = {
        "schema": 1,
        "project": "CodexBridge",
        "feature": "gateway-update",
        "branch": branch,
        "commit": commit,
        "target": "frida",
        "phase": "deploy-test" if args.check else "release-validation",
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": round(time.monotonic() - started, 3),
        "status": "pass" if outcome in ("updated", "already_current", "ready") else "fail",
        "exit_code": 0 if outcome in ("updated", "already_current", "ready") else 1,
        "error_category": "none" if outcome in ("updated", "already_current", "ready") else "deployment",
        "checks": {
            "profile": "oauth-138",
            "stage_id": stage_id,
            "read_only": args.check,
            "local_tests_exit_code": local_tests_rc,
            "failed_tests": failed_tests,
            "outcome": published_result,
            "remote_publication_required": True,
        },
        "detail": "Sanitized result of idempotent Gateway update; no credentials, logs or environment uploaded",
    }
    relative = (
        f"CodexBridge/gateway-update/{re.sub(r'[^A-Za-z0-9_.-]', '-', branch)}/"
        f"{now:%Y-%m-%d}/{run_id}/manifest.json"
    )
    try:
        published = publish(relative, report)
    except (OSError, subprocess.TimeoutExpired):
        published = False
    print("UPDATE_RESULT=" + json.dumps(published_result, sort_keys=True))
    if not published:
        print("EVIDENCE_NOT_CONFIRMED", file=sys.stderr)
        return 2
    print(f"EVIDENCE_URL={EVIDENCE_REPO}/blob/main/{relative}")
    return 0 if report["exit_code"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
