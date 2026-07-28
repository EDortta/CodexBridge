from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path


SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{20,})"),
    re.compile(r"(ghp_[A-Za-z0-9]{20,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9._-]{16,})", re.IGNORECASE),
]


def secure_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sanitize_log_line(line: str) -> str:
    redacted = line
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def ensure_within_root(root: str, target: str) -> Path:
    root_path = Path(root).resolve()
    target_path = Path(target).resolve()
    target_path.relative_to(root_path)
    return target_path


def filtered_environment(allowed_keys: set[str]) -> dict[str, str]:
    env = {}
    for key, value in os.environ.items():
        if key in allowed_keys:
            env[key] = value
    return env

