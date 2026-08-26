"""Where an artifact's bytes live, and which of them a request may read.

One reason to change: *which bytes of which file*. The route
(`gateway/app/api/routes/artifacts.py`) owns *who may ask* and how a refusal is
shaped; this module owns the filesystem and the byte range, and knows nothing
about principals, tokens or HTTP status codes.

## The confinement rule, and why it is here rather than at the caller

`ArtifactModel.storage_path` is a path relative to `settings.artifacts_root`,
and it never leaves the server (`docs/api/README.md` §"Fields that must never
ship"). A path is dangerous in two independent ways, so it is checked twice:

- **lexically, at write time** — `validate_storage_path` refuses an absolute
  path, a backslash, a `..` segment, and any character outside
  `security-standards.md` §9's allowlist. `store.create_artifact` calls it, so a
  traversing path cannot be stored in the first place;
- **after resolution, at read time** — `resolve_artifact_file` resolves the
  candidate *and the root* and refuses anything that is not under the root.
  `Path.resolve` follows symlinks, so this is what catches a symlink planted
  inside the root pointing at `/etc/shadow` — which no amount of string
  checking can see.

Both live inside this module rather than at the endpoints that happen to exist
today, because `design-standards.md` §3 is explicit that a guard next to the
caller is a guard the next caller forgets. There is no way to open an artifact's
bytes in this codebase except through `resolve_artifact_file`.

## Range requests

`parse_range_header` implements the subset of RFC 9110 §14 this API supports: a
single `bytes=` range. Anything else — an unknown unit, a malformed value, more
than one range — returns `None`, which the route serves as a plain `200` with
the whole representation. RFC 9110 explicitly allows a server to ignore a
`Range` it does not want to honour, and answering `416` for a syntactically odd
header would break clients that send one speculatively. A range that *is* well
formed and cannot be satisfied is a different thing and raises
`UnsatisfiableRange`, which the route reports as `416`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from gateway.app.core.config import settings
from gateway.app.services.artifact_types import ArtifactError


# One path segment. Same allowlist as `artifact_types.NAME_RE`, which is what
# makes a stored path expressible as a URL-safe name if a future issue ever
# needs to: no spaces, no separators other than the `/` between segments, and
# no leading dot (which rules out `..` and hidden files in one rule).
SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

MAX_STORAGE_PATH_LENGTH = 512

# How much is read from disk per iteration while streaming. Bounded so a large
# artifact does not become a large allocation: the response is streamed, and the
# process holds one chunk at a time regardless of the file's size.
CHUNK_SIZE = 64 * 1024


class UnsatisfiableRange(Exception):
    """A well-formed `Range` whose first byte lies past the end of the file."""


class ArtifactContentMissing(Exception):
    """The row exists and its bytes do not.

    Distinct from a rejected path: this is a stored artifact whose file was
    removed, never written, or is not a regular file. The route answers it with
    a typed `404` naming the artifact, never the path.
    """


@dataclass(frozen=True)
class ByteRange:
    """A resolved, satisfiable range: `[start, end]` inclusive, as HTTP means it."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def artifacts_root() -> Path:
    """The one directory artifact bytes may live under.

    Read from settings at call time rather than captured at import, so a test
    (and an operator changing the deployment) does not have to reload this
    module — `design-standards.md` §2's "storage arrives through a parameter,
    not an import buried in a method", in the shape this codebase already uses
    for `settings.user_registry_file`.
    """
    return Path(settings.artifacts_root).resolve()


def validate_storage_path(storage_path: str) -> str:
    """The stored form of a relative artifact path, or `ArtifactError`.

    Lexical only. It refuses what can be refused by reading the string, and
    `resolve_artifact_file` refuses what cannot — see the module docstring for
    why both exist.
    """
    candidate = (storage_path or "").strip()
    if not candidate:
        raise ArtifactError("/storagePath", "required", "An artifact needs a storage path.")
    if len(candidate) > MAX_STORAGE_PATH_LENGTH:
        raise ArtifactError(
            "/storagePath", "too_long", f"A storage path may be at most {MAX_STORAGE_PATH_LENGTH} characters."
        )
    if candidate.startswith("/") or "\\" in candidate or ":" in candidate:
        raise ArtifactError(
            "/storagePath",
            "not_relative",
            "A storage path is relative to the artifacts root and may not be absolute.",
        )
    segments = candidate.split("/")
    for segment in segments:
        if not SEGMENT_RE.match(segment):
            raise ArtifactError(
                "/storagePath",
                "invalid_segment",
                "Each path segment must match [A-Za-z0-9][A-Za-z0-9._-]* — this "
                "rules out '.', '..' and empty segments.",
            )
    return "/".join(segments)


def resolve_artifact_file(storage_path: str) -> Path:
    """The file `storage_path` names, proven to be inside the artifacts root.

    Raises `ArtifactError` when the path is not confined — including the symlink
    case, which the lexical check cannot see — and `ArtifactContentMissing` when
    it is confined but there is no regular file there.
    """
    relative = validate_storage_path(storage_path)
    root = artifacts_root()
    candidate = (root / relative).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        # Reached only through a symlink or a root that moved under us: the
        # lexical check already refused every traversing spelling. Reported as
        # the same rejection so no caller has to tell the two apart.
        raise ArtifactError(
            "/storagePath",
            "escapes_root",
            "A storage path must resolve inside the artifacts root.",
        )
    if not candidate.is_file():
        raise ArtifactContentMissing(relative)
    return candidate


# Bounded, because `int()` on a decimal string of more than
# `sys.int_info.str_digits_check_threshold` digits (4300, CPython's
# CVE-2020-10735 mitigation) raises `ValueError`: an unbounded `\d*` turned
# `Range: bytes=<4301 nines>-` into an unhandled exception and a
# `500 internal_error` with `retryable: true` — inviting the client to send it
# again — plus a stack trace per request. Found by a council round's
# adversarial-user lens. An over-long digit run is a malformed range, and this
# function already answers that with `None`: the guard belongs in the pattern,
# not in a `try/except` at the call site.
#
# 255, not 19. The first cut bounded it at 19 on the reasoning that 2**63-1 is
# 19 digits and no file is that large — but the bound is on **digit count**,
# and RFC 9110 §14.1.1 is `1*DIGIT`, so leading zeros are legal and carry no
# meaning. `bytes=00000000000000000001-2` is a twenty-digit spelling of a
# perfectly ordinary range, and dropping it re-sent the whole file with `200`
# where a `206` was asked for — silently, because an ignored `Range` is by
# design indistinguishable from an unsupported one. The second round of the
# same council caught it. 255 is comfortably under the threshold that causes
# the crash and comfortably over any padding a client could sanely emit; the
# magnitude is then checked against the real file size below, which is where a
# magnitude check belongs.
_RANGE_RE = re.compile(r"^bytes=(\d{0,255})-(\d{0,255})$")


def parse_range_header(value: str | None, size: int) -> ByteRange | None:
    """The single byte range `value` asks for, or None to serve the whole file.

    Returns None for an absent, unknown-unit, malformed or multi-range header —
    all of which RFC 9110 §14.2 permits a server to ignore. Raises
    `UnsatisfiableRange` for a syntactically valid range that starts past the
    end, which is the one case the RFC requires `416` for.
    """
    if not value:
        return None
    match = _RANGE_RE.match(value.strip())
    if not match:
        return None
    first, last = match.group(1), match.group(2)
    if not first and not last:
        return None

    if not first:
        # `bytes=-N`: the final N bytes. N == 0 asks for nothing, which is not a
        # range; ignore it rather than inventing an empty 206.
        suffix = int(last)
        if suffix == 0:
            return None
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(first)
        end = size - 1 if not last else min(int(last), size - 1)

    if size == 0 or start >= size:
        raise UnsatisfiableRange(start)
    if end < start:
        # `bytes=5-2` is well formed and meaningless. Ignored rather than
        # refused, same reasoning as the malformed case above.
        return None
    return ByteRange(start=start, end=end)


def read_chunks(path: Path, byte_range: ByteRange | None, *, chunk_size: int = CHUNK_SIZE) -> Iterator[bytes]:
    """Yield the requested bytes of `path`, `chunk_size` at a time.

    A generator rather than a `read()`: an APK is tens of megabytes and this
    process serves other requests while it is being downloaded.
    """
    remaining = None if byte_range is None else byte_range.length
    with path.open("rb") as handle:
        if byte_range is not None:
            handle.seek(byte_range.start)
        while True:
            want = chunk_size if remaining is None else min(chunk_size, remaining)
            if want <= 0:
                return
            chunk = handle.read(want)
            if not chunk:
                return
            if remaining is not None:
                remaining -= len(chunk)
            yield chunk
