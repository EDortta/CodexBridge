"""The closed vocabulary an artifact row may use, and the one error it raises.

Same shape and the same reason as `issue_types.py` and `conversation_types.py`:
the values a mobile client branches on are enum members in
`docs/api/codex-bridge.openapi.yaml`, and adding a value to an enum other than
`ErrorCode` is a breaking change (`docs/api/README.md` §"What is a breaking
change"). Keeping them in one module means the store, the routes and the
contract read the same list rather than three spellings of it.

## Nothing in this build produces an artifact

There is no ingestion path: no executor message, no upload endpoint, no build
hook writes a row here. Every artifact this API can serve was created by a
direct call to `store.create_artifact`, which today means a test fixture or an
operator script. That is stated here rather than implied because
`docs/api/README.md` already refuses to publish a field whose value can only
ever be one thing — the same honesty issue #5 applied when it omitted an
always-zero `artifacts` count and issue #7 applied to `dependencies`.

The vocabulary below is therefore a **choice**, not a description of observed
data. It is deliberately small: a value that no producer ever writes is easier
to add later (additive, non-breaking for a *request* filter) than to remove.

## Why the patterns are strict

`name` reaches an HTTP `Content-Disposition` header and `storage_path` reaches
the filesystem. `security-standards.md` §9 requires a caller-supplied filename
to match `^[A-Za-z0-9._-]+$` or be replaced by a server-generated identifier,
and §2 forbids a response that lets a client infer a server path. The
validation lives here, next to the write, rather than at whichever caller
happens to exist — `design-standards.md` §3.
"""

from __future__ import annotations

import re


# What kind of thing the bytes are. `apk` is the one issue #11 names explicitly
# (it is what `GET /api/v1/builds/android` lists); the other three are the
# categories the rest of this gateway could plausibly retain, kept coarse so a
# producer does not have to negotiate a new enum value on day one.
ARTIFACT_TYPES: frozenset[str] = frozenset({"apk", "archive", "report", "log"})

# Where the bytes came from. Not the storage location — that is `storage_path`,
# which never leaves the server.
ARTIFACT_ORIGINS: frozenset[str] = frozenset({"executor", "ci", "manual"})

# Which deployment an APK is built for. Mirrors the three build flavours a
# mobile project normally carries; a client shows the badge from it.
ANDROID_ENVIRONMENTS: frozenset[str] = frozenset({"production", "staging", "development"})

DEFAULT_CONTENT_TYPE = "application/octet-stream"

MAX_NAME_LENGTH = 255
MAX_VERSION_LENGTH = 64
MAX_CHANGELOG_LENGTH = 20000

# A downloadable filename, per `security-standards.md` §9. No spaces, no quotes,
# no path separator, no leading dot: this value is interpolated into a
# `Content-Disposition` header, where a quote or a newline is a header-injection
# primitive and `..` is a traversal one.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")

VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

# RFC 9110 `token "/" token`, restricted to the characters a media type may
# use. Parameters (`; charset=…`) are refused rather than parsed: the value is
# written into a response header and nothing here needs them.
CONTENT_TYPE_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}/[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")

# An Android application id: at least two dot-separated segments, each starting
# with a letter. Rejecting a single segment is deliberate — `com` is not a
# package name and a client that shows it has been given nonsense.
PACKAGE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")

# The SHA-256 certificate fingerprint `apksigner verify --print-certs` and
# `keytool -list` print: 32 uppercase hex pairs joined by colons. A bare 64-char
# hex string is accepted on input and normalized to this form, so two spellings
# of one certificate do not read as two certificates.
FINGERPRINT_RE = re.compile(r"^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$")
BARE_FINGERPRINT_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


class ArtifactError(ValueError):
    """A rejected artifact field, carrying what the API must report.

    Same *shape* as `IssuePlanningError` and `ConversationPlanningError` — and
    deliberately not the same wiring, which is worth stating because the
    obvious assumption is wrong and a council round caught this docstring
    making it. Those two are converted to `400 validation_failed` by a
    `_planning_error` helper on their router, because those routers accept
    request bodies. **This one has no such conversion, because no endpoint
    accepts an artifact**: `store.create_artifact` is called by a test fixture
    or an operator script, and the single `except ArtifactError` on a route
    (`routes/artifacts.py`, the download path) answers `404` for a stored path
    that stopped resolving inside the root — the caller has no business
    learning that a path exists at all.

    `field` and `code` are populated anyway, and that is the point of putting
    them here: the ingestion endpoint a future issue adds inherits the pointer
    already decided next to the rule, instead of re-deciding it at the route.
    Whoever writes that endpoint owes it the `_planning_error`-shaped handler —
    it does not exist yet, and this docstring used to say it did.
    """

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message


def normalize_fingerprint(value: str) -> str:
    """Colon-separated uppercase form of a SHA-256 certificate fingerprint.

    Raises `ArtifactError` for anything that is not one. This is the field an
    operator compares against what their signing key actually is, so a value
    that merely *looks* like a fingerprint is worse than a rejection.
    """
    candidate = (value or "").strip().upper()
    if BARE_FINGERPRINT_RE.match(candidate):
        candidate = ":".join(candidate[index : index + 2] for index in range(0, 64, 2))
    if not FINGERPRINT_RE.match(candidate):
        raise ArtifactError(
            "/android/signingFingerprint",
            "invalid_fingerprint",
            "signingFingerprint must be a SHA-256 certificate fingerprint "
            "(32 colon-separated hex pairs, or 64 hex characters).",
        )
    return candidate
