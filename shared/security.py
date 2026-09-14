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

# Response-boundary redaction for executor-, Engine-, and operator-controlled
# free text. Order matters: URL credentials must be removed before host/address
# patterns can hide the delimiter that identifies them.
PUBLIC_TEXT_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]*(?::[^\s/@]*)?@"), r"\1[CREDENTIAL]@"),
    (re.compile(r"(?i)([?&](?:token|access_token|refresh_token|api_key|apikey|secret|password|passwd|pwd|sig|signature)=)[^\s&\"']+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)([\"']?\b(?:token|access_token|refresh_token|api[_-]?key|secret|password|passwd|pwd)\b[\"']?\s*[:=]\s*)[\"']?[^\s,;}\"']{4,}[\"']?"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(authorization\s*:\s*)\S+\s+\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(x-api-key\s*:\s*)\S+"), r"\1[REDACTED]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "[REDACTED]"),
    (re.compile(r"(?<![\w.])/(?:home|opt|etc|var|root|srv|usr|tmp|mnt|media)/[^\s\"']*"), "[PATH]"),
    (re.compile(r"\b[A-Za-z]:\\[^\s\"']*"), "[PATH]"),
    (re.compile(r"(?<![\w])\.{1,2}/[^\s\"']*"), "[PATH]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b"), "[ADDR]"),
    (re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|127\.0)\.\d{1,3}\.\d{1,3}\b"), "[ADDR]"),
    (re.compile(r"(?i)\b[a-z0-9][a-z0-9.-]*\.(?:internal|local|lan|intranet|corp)\b"), "[HOST]"),
    (re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"), ""),
    (re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]"), ""),
)


def secure_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_resource_key(value: str) -> str:
    """A fixed-width (64 hex chars), indexable stand-in for an unbounded string.

    WK-20260902-gh73-discovery-adoption. `DiscoveredResourceModel.resource_key`
    was written, since issue #73 Stage 3, as the candidate's absolute path on
    the node -- up to `DiscoveredCandidate.resource_key`'s own `max_length`
    2048 -- into a column declared `varchar(255)`. SQLite never enforces that
    width (type affinity, not a constraint), so the defect was silent there;
    `aiomysql` is a declared dependency, and MySQL does enforce it, so the
    same write is a `Data too long for column` error on that target.

    Widening the column is not the fix: it sits inside the composite unique
    index `(node_id, kind, resource_key)`, and MySQL's InnoDB index key limit
    (3072 bytes; ~767 characters at 4 bytes/char for `utf8mb4`) is almost
    certainly what the original 255 was sized against, before issue #73 Stage
    3 repurposed the column to hold a full path instead of a short suggested
    id. Widening it to fit 2048 characters would trade one silent failure for
    a different one on the same target.

    Same shape as `hash_token` (sha256, hex) and deliberately a second
    function rather than a shared call site: the two hash unrelated kinds of
    string for unrelated reasons (secrecy at rest vs. a fixed-width index
    key), and `docs/napkin-lessons.md`'s guidance against parallel concepts
    is about vocabulary that means the same thing twice, not about two
    one-line hashes that happen to use the same primitive.

    The candidate's real path never disappears: `DiscoveredResourceModel.
    resource_path` (added by `migrations/0014_discovery_resource_key_hash.
    sql`) carries it, unindexed, at the same 2048-character width the
    protocol already allows. `resource_key` is purely a lookup key from here
    on -- see `gateway/app/services/store.py:record_discovery_report` for how
    the two columns divide the work.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sanitize_log_line(line: str) -> str:
    redacted = line
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_sensitive_text(value: str | None) -> str | None:
    """Sanitize free text immediately before it crosses a public boundary."""
    if value is None:
        return None
    redacted = sanitize_log_line(value)
    for pattern, replacement in PUBLIC_TEXT_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
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

