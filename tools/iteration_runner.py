#!/usr/bin/env python3
"""One-shot, reboot-safe iteration runner for CodexBridge projects.

Designed for cron. Each invocation:
1. acquires a per-checkout non-blocking lock;
2. fast-forwards the configured branch;
3. reads .codexbridge/iteration.json;
4. runs exactly one ready round, at most once;
5. writes machine + human results;
6. commits and pushes only those result files.

Round identity is (run_id, round). A completed round is never executed again.
If the machine reboots mid-run, no completed result exists, so the same
idempotent round is retried on the next cron invocation.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

MANIFEST_REL = Path(".codexbridge/iteration.json")
RESULTS_REL = Path("iteration-results")
STATE_DIR = Path.home() / ".local/state/codexbridge-iteration-runner"
VALID_STATUSES = {"ready", "paused", "done", "failed", "needs_human"}


class RunnerError(RuntimeError):
    pass


class ProjectBusy(RuntimeError):
    """The checkout is in use or locally modified; cron should retry later."""

    pass


@dataclasses.dataclass(frozen=True)
class Manifest:
    enabled: bool
    run_id: str
    project: str
    round: int
    max_rounds: int
    deadline: dt.datetime
    branch: str
    script: str
    args: tuple[str, ...]
    timeout_seconds: int
    status: str
    ready_revision: str | None = None

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        raw = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "enabled",
            "run_id",
            "project",
            "round",
            "max_rounds",
            "deadline",
            "branch",
            "script",
            "timeout_seconds",
            "status",
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise RunnerError(f"manifest missing fields: {', '.join(missing)}")

        status = str(raw["status"])
        if status not in VALID_STATUSES:
            raise RunnerError(f"invalid status {status!r}")

        deadline = parse_time(str(raw["deadline"]))
        result = cls(
            enabled=bool(raw["enabled"]),
            run_id=validate_token(str(raw["run_id"]), "run_id"),
            project=validate_token(str(raw["project"]), "project"),
            round=int(raw["round"]),
            max_rounds=int(raw["max_rounds"]),
            deadline=deadline,
            branch=validate_token(str(raw["branch"]), "branch", allow_slash=True),
            script=str(raw["script"]),
            args=tuple(str(x) for x in raw.get("args", [])),
            timeout_seconds=int(raw["timeout_seconds"]),
            status=status,
            ready_revision=(str(raw["ready_revision"]) if raw.get("ready_revision") else None),
        )
        if result.round < 1 or result.max_rounds < 1:
            raise RunnerError("round and max_rounds must be >= 1")
        if result.timeout_seconds < 1 or result.timeout_seconds > 86_400:
            raise RunnerError("timeout_seconds must be between 1 and 86400")
        return result


def parse_time(value: str) -> dt.datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise RunnerError("deadline must include timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_token(value: str, name: str, *, allow_slash: bool = False) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if allow_slash:
        allowed.add("/")
    if not value or any(ch not in allowed for ch in value):
        raise RunnerError(f"{name} contains unsafe characters")
    return value


def run(cmd: list[str], *, cwd: Path, timeout: int = 30, check: bool = True,
        stdout: Any = subprocess.PIPE, stderr: Any = subprocess.STDOUT,
        text: bool = True) -> subprocess.CompletedProcess:
    try:
        cp = subprocess.run(
            cmd,
            cwd=cwd,
            timeout=timeout,
            check=False,
            stdout=stdout,
            stderr=stderr,
            text=text,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(f"command timed out after {timeout}s: {cmd[0]}") from exc
    if check and cp.returncode != 0:
        output = (cp.stdout or "")[-3000:] if isinstance(cp.stdout, str) else ""
        raise RunnerError(f"command failed rc={cp.returncode}: {' '.join(cmd)}\n{output}")
    return cp


def git(repo: Path, *args: str, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=repo, timeout=timeout, check=check)


def repo_root() -> Path:
    cp = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=10,
    )
    if cp.returncode != 0:
        raise RunnerError("not inside a git checkout")
    return Path(cp.stdout.strip()).resolve()


def acquire_lock(repo: Path):
    git_dir = git(repo, "rev-parse", "--git-dir").stdout.strip()
    lock_path = (repo / git_dir / "codexbridge-project-execution.lock").resolve()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} host={socket.gethostname()} started={utc_now()}\n")
    handle.flush()
    return handle


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def tracked_dirty(repo: Path) -> bool:
    return (
        git(repo, "diff", "--quiet", check=False).returncode != 0
        or git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0
    )


def pull_current_branch(repo: Path) -> str:
    current = git(repo, "branch", "--show-current").stdout.strip()
    if not current:
        raise RunnerError("detached HEAD is not supported")
    if tracked_dirty(repo):
        raise ProjectBusy("tracked working tree is dirty")
    git(repo, "fetch", "--prune", "origin", current, timeout=60)
    git(repo, "pull", "--ff-only", "origin", current, timeout=60)
    return current


def safe_script(repo: Path, rel: str) -> Path:
    candidate = (repo / rel).resolve()
    try:
        candidate.relative_to(repo)
    except ValueError as exc:
        raise RunnerError("script escapes repository root") from exc
    if not candidate.is_file():
        raise RunnerError(f"script does not exist: {rel}")
    return candidate


def command_for(script: Path, args: tuple[str, ...]) -> list[str]:
    if script.suffix == ".py":
        return ["python3", str(script), *args]
    if script.suffix == ".sh":
        return ["bash", str(script), *args]
    return [str(script), *args]


def round_dir(repo: Path, manifest: Manifest) -> Path:
    return repo / RESULTS_REL / manifest.run_id


def result_json_path(repo: Path, manifest: Manifest) -> Path:
    return round_dir(repo, manifest) / f"round-{manifest.round:03d}.json"


def result_log_path(repo: Path, manifest: Manifest) -> Path:
    return round_dir(repo, manifest) / f"round-{manifest.round:03d}.log"


def is_completed(repo: Path, manifest: Manifest) -> bool:
    path = result_json_path(repo, manifest)
    if not path.exists():
        return False
    cp = git(repo, "ls-files", "--error-unmatch", str(path.relative_to(repo)), check=False)
    return cp.returncode == 0


def verify_ready_revision(repo: Path, revision: str | None) -> None:
    if not revision:
        return
    cp = git(repo, "merge-base", "--is-ancestor", revision, "HEAD", check=False)
    if cp.returncode != 0:
        raise RunnerError(f"ready_revision {revision!r} is not contained in current HEAD")


def execute_round(repo: Path, manifest: Manifest) -> dict[str, Any]:
    script = safe_script(repo, manifest.script)
    command = command_for(script, manifest.args)
    started = utc_now()
    head_before = git(repo, "rev-parse", "HEAD").stdout.strip()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f"{manifest.run_id}-r{manifest.round:03d}-",
        suffix=".log",
        dir=STATE_DIR,
        delete=False,
    ) as raw:
        temp_log = Path(raw.name)

    timed_out = False
    exit_code = 255
    with temp_log.open("w", encoding="utf-8", errors="replace") as out:
        out.write(f"run_id={manifest.run_id}\nround={manifest.round}\n")
        out.write(f"started_at={started}\ncommand_script={manifest.script}\n\n")
        out.flush()
        proc = subprocess.Popen(
            command,
            cwd=repo,
            stdout=out,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            exit_code = proc.wait(timeout=manifest.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
            out.write(f"\nITERATION_RUNNER_TIMEOUT after {manifest.timeout_seconds}s\n")
            out.flush()
            # Kill the whole process group, not only the shell/python parent.
            # A timed-out test must not leave ssh/curl/pytest grandchildren
            # running behind the project lock after cron moves on.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass

    finished = utc_now()
    head_after = git(repo, "rev-parse", "HEAD").stdout.strip()
    status = "timeout" if timed_out else ("success" if exit_code == 0 else "failed")

    return {
        "schema_version": 1,
        "run_id": manifest.run_id,
        "project": manifest.project,
        "round": manifest.round,
        "max_rounds": manifest.max_rounds,
        "status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "started_at": started,
        "finished_at": finished,
        "host": socket.gethostname(),
        "script": manifest.script,
        "args": list(manifest.args),
        "timeout_seconds": manifest.timeout_seconds,
        "branch": manifest.branch,
        "ready_revision": manifest.ready_revision,
        "head_before": head_before,
        "head_after": head_after,
        "deadline": manifest.deadline.isoformat().replace("+00:00", "Z"),
        "_temp_log": str(temp_log),
    }


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def publish_result(repo: Path, manifest: Manifest, result: dict[str, Any]) -> None:
    jpath = result_json_path(repo, manifest)
    lpath = result_log_path(repo, manifest)
    jpath.parent.mkdir(parents=True, exist_ok=True)

    temp_log = Path(result.pop("_temp_log"))
    shutil.copyfile(temp_log, lpath)
    temp_log.unlink(missing_ok=True)
    atomic_write_json(jpath, result)

    rel_json = str(jpath.relative_to(repo))
    rel_log = str(lpath.relative_to(repo))
    git(repo, "add", "--", rel_json, rel_log)
    git(
        repo,
        "commit",
        "-m",
        f"[iteration:{manifest.run_id}:{manifest.round}] {result['status']}",
        "--",
        rel_json,
        rel_log,
        timeout=30,
    )

    # Another actor may push between pull and our result. Rebase only our clean
    # result commit; never autostash or touch unrelated local changes.
    for attempt in range(1, 4):
        cp = git(repo, "push", "origin", manifest.branch, timeout=60, check=False)
        if cp.returncode == 0:
            return
        if tracked_dirty(repo):
            raise RunnerError("result committed locally but push failed and tree became dirty")
        pull = git(repo, "pull", "--rebase", "origin", manifest.branch, timeout=60, check=False)
        if pull.returncode != 0:
            raise RunnerError("result committed locally; rebase before push failed")
        time.sleep(attempt)
    raise RunnerError("result committed locally but push failed after 3 attempts")


def terminal_result(repo: Path, manifest: Manifest, reason: str) -> None:
    path = round_dir(repo, manifest) / "terminal.json"
    if path.exists():
        return
    payload = {
        "schema_version": 1,
        "run_id": manifest.run_id,
        "project": manifest.project,
        "round": manifest.round,
        "max_rounds": manifest.max_rounds,
        "status": "terminal",
        "reason": reason,
        "at": utc_now(),
        "host": socket.gethostname(),
    }
    atomic_write_json(path, payload)
    rel = str(path.relative_to(repo))
    git(repo, "add", "--", rel)
    git(repo, "commit", "-m", f"[iteration:{manifest.run_id}] terminal: {reason}", "--", rel)
    git(repo, "push", "origin", manifest.branch, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one CodexBridge iteration round if ready.")
    parser.add_argument("--manifest", default=str(MANIFEST_REL))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = repo_root()
    lock = acquire_lock(repo)
    if lock is None:
        print("iteration_runner=busy")
        return 0

    try:
        # Pull first. A controller may create the manifest remotely while this
        # checkout still has no manifest or has a stale paused copy.
        current_branch = pull_current_branch(repo)

        manifest_path = (repo / args.manifest).resolve()
        try:
            manifest_path.relative_to(repo)
        except ValueError as exc:
            raise RunnerError("manifest path escapes repository root") from exc
        if not manifest_path.exists():
            print("iteration_runner=no_manifest")
            return 0

        manifest = Manifest.load(manifest_path)
        if manifest.branch != current_branch:
            raise RunnerError(
                f"checkout is on {current_branch!r}, manifest requires {manifest.branch!r}"
            )

        if not manifest.enabled or manifest.status != "ready":
            print(f"iteration_runner=idle status={manifest.status} enabled={manifest.enabled}")
            return 0

        now = dt.datetime.now(dt.timezone.utc)
        if manifest.round > manifest.max_rounds:
            if not args.dry_run:
                terminal_result(repo, manifest, "max_rounds_exceeded")
            print("iteration_runner=terminal reason=max_rounds_exceeded")
            return 0
        if now >= manifest.deadline:
            if not args.dry_run:
                terminal_result(repo, manifest, "deadline_exceeded")
            print("iteration_runner=terminal reason=deadline_exceeded")
            return 0

        verify_ready_revision(repo, manifest.ready_revision)

        if is_completed(repo, manifest):
            print(f"iteration_runner=already_completed run_id={manifest.run_id} round={manifest.round}")
            return 0

        if args.dry_run:
            print(f"iteration_runner=would_run run_id={manifest.run_id} round={manifest.round} script={manifest.script}")
            return 0

        result = execute_round(repo, manifest)
        publish_result(repo, manifest, result)
        print(
            f"iteration_runner=completed run_id={manifest.run_id} "
            f"round={manifest.round} status={result['status']} exit_code={result['exit_code']}"
        )
        # The test outcome is data, not runner failure. Returning 0 keeps cron
        # quiet; the committed JSON drives the next controller round.
        return 0

    except ProjectBusy as exc:
        print(f"iteration_runner=busy reason={exc}")
        return 0
    except RunnerError as exc:
        print(f"iteration_runner=error error={exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"iteration_runner=unexpected_error type={type(exc).__name__} error={exc}", file=sys.stderr)
        return 3
    finally:
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
