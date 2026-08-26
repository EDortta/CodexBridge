"""The user registry, and the one operation that turns a password into a user.

`authenticate` is the only supported way to check a password. It exists as one
function rather than as `lookup_user` + `verify_password` at each call site
because every property this module owes — constant cost for an unknown
username, refusal of the credential published in `examples/users.json` — is a
guard that has to run on *every* sign-in path, and `design-standards.md` §3 is
explicit that such a guard lives inside the dangerous operation and not at the
caller. There were two callers (the mobile sign-in and the browser OAuth form)
and only one of them had the guard; that is the shape the rule names.

`verify_password` stays public because a stored hash still has to be checked
somewhere, but it is the primitive, not the entry point: it knows nothing about
who the hash belongs to and cannot be constant-cost, because it has nothing to
be constant against.

`authenticate` is **synchronous and expensive by design** — a few hundred
milliseconds of PBKDF2. An `async def` handler that calls it directly blocks the
event loop for that whole time, which stalls every other request in the process
including `/health`. `authenticate_async` is the entry point every request
handler must use; `tests/integration/test_oauth_authorize.py::test_no_request_handler_derives_a_key_on_the_event_loop`
is what keeps the next one from reaching for the synchronous name.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import anyio.to_thread
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class GatewayUser(BaseModel):
    user_id: str
    email: str
    password_hash: str
    roles: list[str] = Field(default_factory=list)
    allowed_projects: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    enabled: bool = True
    can_approve_sensitive: bool = False


class UserRegistry(BaseModel):
    users: list[GatewayUser] = Field(default_factory=list)


class AuthenticatedPrincipal(BaseModel):
    user_id: str
    email: str
    roles: list[str] = Field(default_factory=list)
    allowed_projects: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    can_approve_sensitive: bool = False
    auth_scheme: str = "oauth"

    def is_admin(self) -> bool:
        return "admin" in self.roles or "codexbridge.admin" in self.scopes

    def has_scope(self, scope: str) -> bool:
        return self.is_admin() or scope in self.scopes

    def can_access_project(self, project_id: str) -> bool:
        return self.is_admin() or project_id in self.allowed_projects


def _read_user_registry(path: str) -> dict[str, GatewayUser]:
    """Parse the registry, or raise. The strict form behind `load_user_registry`.

    Raises on malformed JSON, a shape pydantic refuses, or a **key collision**:
    two different accounts that resolve to the same lookup key — a duplicate
    `user_id`, a duplicate e-mail, or a `user_id` that equals another account's
    e-mail. Last-write-wins there silently rebinds an already-issued token to
    whichever entry loaded last, because `current_principal` re-resolves the
    token's `user_id` against this registry on every request; a copy-pasted
    entry with the e-mail changed and the `user_id` left alone is enough to hand
    one account another's roles. Refusing the whole registry is the fail-closed
    reading (`design-standards.md` §6): a registry the loader cannot make
    unambiguous grants nobody anything until the operator disambiguates it, and
    `unusable_registry_reason` names the collision.
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}
    payload = UserRegistry.model_validate(json.loads(file_path.read_text(encoding="utf-8")))
    users: dict[str, GatewayUser] = {}
    for user in payload.users:
        # Keys are case-folded, and the collision check is on the folded key.
        # `lookup_user` and `authenticate` resolve `.lower()` first, so a
        # collision detected on the raw `user_id` would miss the case that
        # actually escalates: a `user_id` of `"OPS@EXAMPLE.COM"` never byte-
        # matches another account's `email` of `"ops@example.com"`, yet resolves
        # to it at lookup. Folding both sides makes detection and resolution use
        # the same key. The `GatewayUser` keeps its original-case fields — only
        # the index is folded.
        for key in (user.user_id.lower(), user.email.lower()):
            existing = users.get(key)
            if existing is not None and existing is not user:
                raise ValueError(
                    f"duplicate registry key {key!r}: it resolves both "
                    f"{existing.user_id!r} and {user.user_id!r}. A user_id and an "
                    "e-mail must each identify exactly one account, case-insensitively."
                )
            users[key] = user
    return users


def load_user_registry(path: str) -> dict[str, GatewayUser]:
    """The registry as a lookup dict, failing **closed** on any problem.

    A registry that cannot be read — malformed mid-edit, a shape pydantic
    refuses, a key collision — returns `{}` here, so every credential path
    answers the uniform `401` rather than raising out of the request handler.
    An earlier cut let the parse raise straight through `authenticate` and
    `lookup_user`: a hand-edited `users.json` then turned `POST /auth/sign-in`
    and `GET /auth/me` into an unauthenticated `500 internal_error` with
    `retryable: true`, a new distinguishing channel that also told a conforming
    client to keep hammering a gateway that could not recover. The diagnostic
    survives in the log (a WARNING here) and in `unusable_registry_reason`, which
    `main.py` reports at startup and the MCP path surfaces as
    `user_registry_unavailable`.

    Failing closed covers an I/O fault (`OSError`: a volume unmounted, a
    permission flipped) the same as a parse error — a transient one becomes a
    fleet-wide forced sign-out rather than a `500`. That is the fail-closed
    trade, accepted deliberately: a registry the process cannot read grants
    nobody anything, and the deployment-level fault is still named at startup and
    on `/mcp`. Recorded as an accepted risk in the issue-#4 review.
    """
    try:
        return _read_user_registry(path)
    except Exception as error:  # malformed JSON, a shape pydantic refuses, a collision
        logger.warning(
            "user registry %r is unusable (%s: %s); failing closed — no account can "
            "sign in until it is fixed.",
            path,
            error.__class__.__name__,
            error,
        )
        return {}


def lookup_user(path: str, username_or_email: str) -> GatewayUser | None:
    registry = load_user_registry(path)
    return registry.get(username_or_email.lower()) or registry.get(username_or_email)


def unusable_registry_reason(path: str) -> str | None:
    """Why no account can sign in against `path`, or None when some can.

    A registry that is absent, empty or unreadable fails closed — every
    credential path refuses everything — and it does so *silently*, which is the
    half that is not safe. The gateway starts clean, `/health` says ok, `/ready`
    says ready because it checks the database, and every sign-in answers the
    deliberately opaque `Sign-in failed.` that an attacker gets. An already-issued
    OAuth token is refused by `/mcp` as an unknown-or-disabled *user*, which
    names the account when the problem is the file. Nothing anywhere says the
    cause, and `load_user_registry` returns `{}` for a missing path without a
    branch to report it.

    The shape that produces it is an upgrade: the default used to resolve to a
    bundled file, so a deployment that never set
    `CODEX_BRIDGE_USER_REGISTRY_FILE` worked. It now points at
    `/etc/codex-bridge/users.json` — deliberately, because the bundled file is a
    published credential — and the upgrade inherits nothing.

    Returns the message rather than logging it: the decision is testable without
    a log handler, and the caller owns where it goes (`design-standards.md` §2).
    """
    if not Path(path).exists():
        return (
            f"the user registry {path!r} does not exist. No account can sign in: "
            "POST /api/v1/auth/sign-in, POST /api/v1/auth/refresh and "
            "POST /oauth/authorize refuse every credential, and tokens already "
            "issued are refused by POST /mcp. Point "
            "CODEX_BRIDGE_USER_REGISTRY_FILE at this deployment's accounts file "
            "(docs/installation.md)."
        )
    try:
        registry = _read_user_registry(path)
    except Exception as error:  # malformed JSON, a shape pydantic refuses, a key collision
        return (
            f"the user registry {path!r} cannot be read ({error.__class__.__name__}: "
            f"{error}). No account can sign in until it parses."
        )
    if not registry:
        return (
            f"the user registry {path!r} lists no accounts. No account can sign in."
        )
    return None


# Why an authentication attempt failed. These strings reach the audit trail and
# never the caller: every one of them is answered with the same 401.
UNKNOWN_USER = "unknown_user"
BAD_PASSWORD = "bad_password"
ACCOUNT_DISABLED = "account_disabled"
PUBLISHED_CREDENTIAL = "published_example_credential"

# The password hashes shipped in this repository's `examples/`. Their plaintext
# is committed beside them (`change-me-now`), so a registry still carrying one
# is a public credential however the deployment is configured, and
# `security-standards.md` §1 has no exception for "it is only the example".
#
# Refused here rather than by a warning in `docs/installation.md`, because the
# operator who skips the password change is precisely the operator who did not
# read that line. The refusal is a sign-in failure with the same 401 as any
# other, and the reason lands in the audit trail so it is diagnosable.
PUBLISHED_EXAMPLE_HASHES = frozenset(
    {
        "pbkdf2_sha256$600000$i5bjWyIkeqmiK7hOrL0g2Q$_sGD6Ia_tKwSQcCj8sLn4DvA5PbmGGCyilYzklVV4lo",
    }
)


@dataclass(frozen=True)
class AuthenticationResult:
    """Whether the credential was accepted, and — for the audit trail — why not.

    `user` is populated whenever the username resolved, including on failure:
    the audit row is recorded against the account that was attacked, and an
    attempt against a disabled account is worth more to whoever reads that trail
    than an attempt against nobody.
    """

    user: GatewayUser | None
    reason: str | None

    @property
    def ok(self) -> bool:
        return self.reason is None


def authenticate(path: str, username_or_email: str, password: str) -> AuthenticationResult:
    """Resolve a username and check its password, at a cost that does not vary.

    Skipping the key derivation when the username is unknown answers in
    microseconds what a known username answers in a quarter of a second. That
    difference is a user-enumeration oracle and it survives every measure taken
    to make the two response bodies identical, so **every** attempt — real
    account, disabled account, invented username — is charged the same
    derivation cost, read from **this registry** rather than from a constant
    that has to be kept in step with however `users.json` was generated. A
    hardcoded 600 000 against a registry written at 210 000 answers a real
    account three times faster than an invented one, which is the oracle
    inverted rather than closed; so does a registry whose accounts were written
    at two different costs, and `_verify_at_constant_cost` pads for that one.

    Synchronous, and expensive on purpose. Request handlers call
    `authenticate_async`, which is the same work off the event loop.
    """
    registry = load_user_registry(path)
    user = registry.get(username_or_email.lower()) or registry.get(username_or_email)

    password_ok = _verify_at_constant_cost(
        password,
        user.password_hash if user else None,
        target_iterations=_registry_iterations(registry),
    )

    if user is None:
        return AuthenticationResult(None, UNKNOWN_USER)
    if not password_ok:
        return AuthenticationResult(user, BAD_PASSWORD)
    if user.password_hash in PUBLISHED_EXAMPLE_HASHES:
        return AuthenticationResult(user, PUBLISHED_CREDENTIAL)
    if not user.enabled:
        return AuthenticationResult(user, ACCOUNT_DISABLED)
    return AuthenticationResult(user, None)


async def authenticate_async(
    path: str, username_or_email: str, password: str
) -> AuthenticationResult:
    """`authenticate`, moved off the event loop.

    The derivation is a few hundred milliseconds of CPU with no `await` in it,
    so calling `authenticate` from an `async def` handler stops the whole
    process for its duration: measured against the synchronous call, ten
    concurrent unauthenticated sign-in attempts pushed `GET /health` from 0.8 ms
    to 3.3 s, and a liveness probe that times out restarts a gateway that is
    merely being probed for accounts. The cost per attempt is the price of
    closing the enumeration oracle; making every *other* request wait for it is
    not, and this is where that is separated out.

    Every request handler calls this one. `authenticate` stays synchronous for
    the tests and scripts that have no loop to hand.
    """
    return await anyio.to_thread.run_sync(authenticate, path, username_or_email, password)


def _verify_at_constant_cost(
    password: str, encoded_hash: str | None, *, target_iterations: int
) -> bool:
    """Verify a password, spending the same work whoever the username names.

    Two branches, one cost:

    - no such user — derive against a decoy hash built at `target_iterations`;
    - a real user hashed at fewer iterations than `target_iterations` — verify
      at the account's own cost, then pad by the difference. PBKDF2 is linear in
      its iteration count, so the two add up to the same work.

    The padding is what a registry with *mixed* costs needs. Without it, every
    account below the registry's maximum answers faster than an invented
    username — 105 ms against 301 ms for a two-account registry written at
    210 000 and 600 000 — which identifies exactly those accounts. That is the
    same oracle the decoy exists to close, pointing the other way.

    The result of the decoy and of the padding is discarded: `False` here never
    depends on comparing anything.
    """
    if encoded_hash is None:
        verify_password(password, _decoy_hash(target_iterations))
        return False
    result = verify_password(password, encoded_hash)
    _pad_derivation(target_iterations - _iterations_of(encoded_hash))
    return result


def _iterations_of(encoded_hash: str) -> int:
    """The cost this stored hash was written at, or 0 when it cannot be read.

    Zero on an unparseable hash is deliberate: `verify_password` rejects it
    immediately, having spent nothing, so the padding below has to cover the
    whole target rather than the remainder of it.

    The algorithm field is checked, not just skipped over. `verify_password`
    only ever derives `pbkdf2_sha256`, so an `argon2id$...` or `scrypt$...`
    string is never actually verified — reading its second field as a PBKDF2
    round count is meaningless, and an `argon2id$99000000$...` line (a plausible
    artefact of a hash migration) would otherwise set the padding target for
    *every* unauthenticated attempt in the deployment to 99 million rounds. A
    hash this function cannot honestly cost is worth 0, exactly like one it
    cannot parse.

    A round count above `_MAX_ITERATIONS` is also worth 0: `verify_password`
    refuses such a hash (the account is unusable), so it must not set the
    derivation target either. Returning 0 keeps the two consistent — the decoy
    and the padding both cost the registry's real ceiling, not the absurd one —
    and `_verify_at_constant_cost` then pads the unusable account up to that same
    target, so it is not identifiable by timing.
    """
    try:
        algorithm, iterations, _, _ = encoded_hash.split("$", 3)
    except (ValueError, AttributeError):
        return 0
    if algorithm != "pbkdf2_sha256":
        return 0
    try:
        count = int(iterations)
    except ValueError:
        return 0
    if count <= 0 or count > _MAX_ITERATIONS:
        return 0
    return count


def _pad_derivation(iterations: int) -> None:
    """Spend `iterations` rounds of the same primitive, against nothing."""
    if iterations <= 0:
        return
    hashlib.pbkdf2_hmac("sha256", _PADDING_SECRET, _PADDING_SALT, iterations)


# Not a credential: input to a derivation whose output is discarded. Random per
# process so it is not a constant an attacker can precompute against, and cheap
# to produce — reading bytes, not deriving a key.
_PADDING_SECRET = secrets.token_bytes(32)
_PADDING_SALT = secrets.token_bytes(16)


def _registry_iterations(registry: dict[str, GatewayUser]) -> int:
    """The derivation cost **every** attempt against this registry is charged.

    The **highest** count present, not the mean or the first: a registry whose
    accounts were hashed at different costs cannot be matched by any single
    decoy, and a cheap real account is only indistinguishable from an invented
    one if the cheap one is padded up — which is what `_verify_at_constant_cost`
    does with this number. Erring high therefore costs the gateway a little work
    and tells a prober nothing; erring low would leave the expensive accounts
    identifiable and could not be padded away.

    A registry that is empty or whose hashes are unparseable falls back to the
    production cost — the file being absent must not make sign-in fast enough to
    probe.

    The ceiling is enforced in `_iterations_of`, which returns 0 for a count
    above `_MAX_ITERATIONS` (the same hash `verify_password` refuses). So one
    account written at an absurd round count — a typo, or a migrated hash whose
    count is in different units — contributes 0 here rather than dictating
    seconds of CPU per sign-in across the deployment, and every value this `max`
    sees is already within the ceiling.
    """
    counts = set()
    for user in registry.values():
        iterations = _iterations_of(user.password_hash)
        if iterations > 0:
            counts.add(iterations)
    return max(counts) if counts else _FALLBACK_ITERATIONS


@lru_cache(maxsize=8)
def _decoy_hash(iterations: int) -> str:
    """A hash of a random secret nobody holds, derived once per iteration count.

    Built at first use rather than at import: deriving it costs the same as one
    real verification, and paying that on every import — including every test
    collection — for a branch that may never run is a poor trade.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secrets.token_bytes(32), salt, iterations)
    return "$".join(
        (
            "pbkdf2_sha256",
            str(iterations),
            base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
            base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
        )
    )


# Used only when the registry says nothing — no file, no users, no parseable
# hash. It is the cost `docs/installation.md` tells an operator to generate at,
# so the fallback is expensive rather than cheap.
_FALLBACK_ITERATIONS = 600000

# The most PBKDF2 rounds any single registry entry may impose on every
# unauthenticated sign-in attempt. Well above any honestly-generated cost —
# ~16x the production 600 000 in `docs/installation.md`, so an operator who
# hardens has ample headroom and does not lock themselves out — while still
# refusing an absurd typo or a mis-unit migrated count (`…$99000000$…`) that
# would turn one line of `users.json` into an authentication DoS. A hash above
# this is unusable (`verify_password` refuses it, `_iterations_of` is 0); see the
# accepted risk in `docs/security.md`. See `_registry_iterations`.
_MAX_ITERATIONS = 10_000_000


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        rounds = int(iterations)
    except ValueError:
        return False
    # A round count above the ceiling makes the account unusable rather than
    # letting an attempt that names it spend that many rounds. `_registry_iterations`
    # caps the decoy/padding target, but the derivation here is what an attacker
    # who knows the account would actually trigger; refusing it closes the other
    # half of that authentication-DoS. `_iterations_of` returns 0 for the same
    # hash, so the constant-cost padding still covers it.
    if rounds <= 0 or rounds > _MAX_ITERATIONS:
        return False
    salt = _b64decode(salt_b64)
    expected = _b64decode(digest_b64)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(derived, expected)


def _b64decode(value: str) -> bytes:
    padding = "=" * ((4 - (len(value) % 4)) % 4)
    return base64.urlsafe_b64decode(value + padding)
