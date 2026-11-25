"""Bounded, read-only projection of private local execution evidence.

Only sanitized manifest metadata is returned. Paths, logs and publisher
envelopes are not transferred across the WebSocket.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

FEATURE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
SHA = re.compile(r"^[a-f0-9]{40}$")
SAFE = re.compile(r"^[A-Za-z0-9._:/+-]{1,160}$")
FIELDS = ("schema", "feature", "phase", "branch", "commit", "timestamp_utc",
          "status", "exit_code", "duration_seconds", "error_category")
CHECKS = ("counts", "failed_test_ids", "local_log_sha256", "local_log_bytes", "raw_logs_local_only")
PUBLICATION = {"published", "queued", "unavailable", "enqueue_failed", "publisher_error"}


def _safe_string(value: object, max_chars: int = 160) -> str | None:
    if not isinstance(value, str) or len(value) > max_chars:
        return None
    if not SAFE.fullmatch(value):
        return None
    return value


def _read(path: Path) -> dict | None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_768:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_evidence(*, state_root: Path, project_id: str, feature: str,
                  limit: int = 5) -> dict:
    """No arbitrary paths or recursive user-controlled traversals."""
    if project_id != "codexbridge" or not FEATURE.fullmatch(feature) or not (1 <= limit <= 20):
        return {"status": "denied", "items": []}
    root = state_root / "codexbridge" / feature
    if root.is_symlink() or not root.is_dir():
        return {"status": "no_evidence", "items": []}
    if root.stat().st_mode & 0o002:
        return {"status": "unsafe_evidence_directory", "items": []}

    items = []
    # This schema writes one run per immediate child; no recursive globbing.
    # Bound directory enumeration to limit CPU on a compromised/huge directory.
    for directory in sorted(root.iterdir(), key=lambda p: p.name, reverse=True)[:200]:
        if not directory.is_dir() or directory.is_symlink():
            continue
        if not re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", directory.name):
            continue
        manifest = _read(directory / "manifest.json")
        if manifest is None or str(manifest.get("project", "")).casefold() != project_id:
            continue
        row = {}
        for field in FIELDS:
            val = manifest.get(field)
            if type(val) in (int, float, bool) and field in ("schema", "exit_code", "duration_seconds"):
                row[field] = val
            elif field in ("branch", "feature", "phase", "timestamp_utc", "status", "error_category"):
                safe = _safe_string(val)
                if safe is not None:
                    row[field] = safe
            elif field == "commit" and isinstance(val, str) and SHA.fullmatch(val):
                row[field] = val
        checks = manifest.get("checks")
        if isinstance(checks, dict):
            kept = {}
            counts = checks.get("counts")
            if isinstance(counts, dict):
                kept["counts"] = {k: v for k, v in counts.items()
                                  if k in ("passed", "failed", "skipped", "error", "errors", "warnings")
                                  and type(v) is int and 0 <= v <= 100_000}
            failed = checks.get("failed_test_ids")
            if isinstance(failed, list):
                kept["failed_test_ids"] = [x for x in failed[:20] if isinstance(x, str)
                                           and len(x) <= 180 and x.startswith("tests/")
                                           and all(ord(c) >= 32 for c in x)]
            digest = checks.get("local_log_sha256")
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
                kept["local_log_sha256"] = digest
            row["checks"] = kept
        publication = _read(directory / "publication.json")
        status = publication.get("status") if publication else "unknown"
        row["publication_status"] = status if status in PUBLICATION else "unknown"
        row["verified_remote"] = False  # Local claim, not GitHub independent verification.
        if row["publication_status"] == "published":
            rel = publication.get("relative_path")
            if (isinstance(rel, str) and len(rel) < 250
                    and rel.startswith("CodexBridge/")
                    and ".." not in rel and re.fullmatch(r"[A-Za-z0-9_./-]+", rel)):
                row["publication_url"] = (
                    "https://github.com/EDortta/development-evidences/blob/main/" + rel
                )
        items.append(row)
        if len(items) >= limit:
            break
    return {"status": "ok" if items else "no_evidence", "items": items,
            "source": "agent_local_manifest", "remote_verification": False}
