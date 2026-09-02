from __future__ import annotations

import base64
import hashlib
import json
import time

import pytest

from gateway.app.core.users import (
    PUBLISHED_EXAMPLE_HASHES,
    AuthenticatedPrincipal,
    authenticate,
    load_user_registry,
    lookup_user,
    verify_password,
)


# The credential shipped in `examples/users.json`. Its plaintext is committed in
# this repository, which is the whole reason `authenticate` refuses it.
PUBLISHED_HASH = "pbkdf2_sha256$600000$i5bjWyIkeqmiK7hOrL0g2Q$_sGD6Ia_tKwSQcCj8sLn4DvA5PbmGGCyilYzklVV4lo"
PUBLISHED_PLAINTEXT = "change-me-now"


def _hash(password: str, iterations: int) -> str:
    salt = b"codexbridge-test-salt"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")  # noqa: E731
    return "$".join(("pbkdf2_sha256", str(iterations), encode(salt), encode(digest)))


def _registry_file(tmp_path, *users) -> str:
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": list(users)}), encoding="utf-8")
    return str(path)


def _user(**overrides) -> dict:
    user = {
        "user_id": "alice",
        "email": "alice@example.com",
        "password_hash": _hash("s3cret", 1000),
        "roles": [],
        "allowed_projects": ["p1"],
        "scopes": ["codexbridge.read"],
        "enabled": True,
    }
    user.update(overrides)
    return user


def test_verify_password_accepts_known_hash() -> None:
    assert verify_password(PUBLISHED_PLAINTEXT, PUBLISHED_HASH)


def test_authenticate_returns_the_user_and_no_reason(tmp_path) -> None:
    path = _registry_file(tmp_path, _user())
    outcome = authenticate(path, "alice", "s3cret")
    assert outcome.ok
    assert outcome.user is not None and outcome.user.user_id == "alice"


@pytest.mark.parametrize(
    ("username", "password", "reason"),
    [
        ("nobody", "s3cret", "unknown_user"),
        ("alice", "wrong", "bad_password"),
    ],
)
def test_authenticate_names_why_it_refused(tmp_path, username, password, reason) -> None:
    """The reason reaches the audit trail; the caller is told nothing."""
    path = _registry_file(tmp_path, _user())
    outcome = authenticate(path, username, password)
    assert not outcome.ok and outcome.reason == reason


def test_authenticate_refuses_a_disabled_account(tmp_path) -> None:
    path = _registry_file(tmp_path, _user(enabled=False))
    assert authenticate(path, "alice", "s3cret").reason == "account_disabled"


def test_a_registry_still_carrying_the_published_example_password_cannot_sign_in(tmp_path) -> None:
    """`security-standards.md` §1: no default user password.

    `examples/users.json` ships one `admin` account whose plaintext is committed
    beside it. `POST /api/v1/auth/sign-in` made that credential reachable with a
    single unauthenticated JSON body, so an operator who copied the example and
    skipped the password change is publishing an admin account. The refusal is
    here rather than in a line of `docs/installation.md`, because the operator
    who skips the password change is the operator who skipped that line.
    """
    path = _registry_file(tmp_path, _user(password_hash=PUBLISHED_HASH))

    outcome = authenticate(path, "alice", PUBLISHED_PLAINTEXT)

    assert not outcome.ok
    assert outcome.reason == "published_example_credential"
    assert PUBLISHED_HASH in PUBLISHED_EXAMPLE_HASHES


def test_the_shipped_example_registry_is_covered_by_that_refusal() -> None:
    """The constant tracks the file, or the guard protects nothing.

    Editing `examples/users.json` to a fresh hash without adding it here would
    silently reopen the hole, and the example's plaintext would still be in the
    commit that introduced it.
    """
    from pathlib import Path

    example = json.loads(
        (Path(__file__).resolve().parents[2] / "examples" / "users.json").read_text(encoding="utf-8")
    )
    for user in example["users"]:
        assert user["password_hash"] in PUBLISHED_EXAMPLE_HASHES, (
            f"{user['user_id']} in examples/users.json can sign in: its hash is not "
            "listed in users.PUBLISHED_EXAMPLE_HASHES"
        )


def test_an_absent_user_costs_what_this_registry_costs(tmp_path) -> None:
    """Otherwise `POST /api/v1/auth/sign-in` is a user-enumeration oracle.

    The cost charged to an unknown username used to be a hardcoded 600 000
    iterations — the count `examples/users.json` happens to use. Nothing bound
    that constant to how an operator's own `users.json` was generated, and
    `docs/installation.md` ships no generator and no recipe. A registry written
    at 200 000 answered a real account in ~100 ms and an invented one in
    ~300 ms: the oracle inverted, not closed, with the code commenting that the
    two matched by construction.

    The bound is a ratio rather than two equal timings, because equal timings
    are not something shared CI hardware can promise. Before the fix the ratio
    was 3; it is now ~1.
    """
    iterations = 200000
    path = _registry_file(tmp_path, _user(password_hash=_hash("s3cret", iterations)))

    authenticate(path, "nobody", "warm the cached decoy")

    started = time.monotonic()
    assert authenticate(path, "alice", "s3cret").ok
    real_cost = time.monotonic() - started

    started = time.monotonic()
    assert not authenticate(path, "nobody", "s3cret").ok
    decoy_cost = time.monotonic() - started

    ratio = decoy_cost / real_cost
    assert 0.4 <= ratio <= 2.5, (
        "an unknown username is charged a different derivation cost than a real "
        f"one, which identifies real accounts: {decoy_cost:.4f}s vs "
        f"{real_cost:.4f}s (ratio {ratio:.2f})"
    )


def test_the_cheapest_account_in_a_mixed_registry_is_not_identifiable(tmp_path) -> None:
    """A registry written at two costs made the older accounts enumerable.

    An operator who generated `users.json` before this delivery (210 000) and
    added a colleague with the recipe `docs/installation.md` now ships (600 000)
    has exactly this file. The decoy charges an unknown username the **highest**
    count present, so every account below that maximum answered *faster* than an
    invented one — 105 ms against 301 ms, a 2.86x split that identifies which
    accounts exist. That is the same oracle the decoy exists to close, pointing
    the other way, and the single-account registry in the test above cannot see
    it: there is only one cost in it.

    The fix is padding, so what is asserted is that the *cheap* account costs
    what an invented username costs. Ratios rather than equal timings, for the
    same reason as everywhere else in this file.
    """
    cheap, expensive = 100000, 300000
    path = _registry_file(
        tmp_path,
        _user(
            user_id="old",
            email="old@example.com",
            password_hash=_hash("s3cret", cheap),
        ),
        _user(
            user_id="new",
            email="new@example.com",
            password_hash=_hash("s3cret", expensive),
        ),
    )

    authenticate(path, "nobody", "warm the cached decoy")

    def cost(username: str) -> float:
        # The best of three: scheduling noise only ever adds time, so the
        # minimum is the closest this can get to the work actually done.
        return min(_timed(authenticate, path, username, "not-the-password") for _ in range(3))

    old_cost = cost("old")
    new_cost = cost("new")
    invented_cost = cost("no-such-user")

    for name, real_cost in (("old", old_cost), ("new", new_cost)):
        ratio = real_cost / invented_cost
        assert 0.6 <= ratio <= 1.7, (
            f"account {name!r} is answered at a different cost than an invented "
            f"username, which says it exists: {real_cost:.4f}s vs "
            f"{invented_cost:.4f}s (ratio {ratio:.2f})"
        )


def _timed(function, *args) -> float:
    started = time.monotonic()
    function(*args)
    return time.monotonic() - started


def test_an_empty_registry_still_costs_something(tmp_path) -> None:
    """A missing `users.json` must not make probing cheap.

    The default registry path points at a file a fresh deployment does not have,
    so this is the shape an unconfigured gateway is actually in.
    """
    path = str(tmp_path / "absent.json")
    authenticate(path, "nobody", "warm the cached decoy")

    started = time.monotonic()
    assert not authenticate(path, "nobody", "anything").ok
    cost = time.monotonic() - started

    assert cost > 0.02, f"an unknown username was answered in {cost:.4f}s, without deriving anything"


def test_load_user_registry_indexes_by_user_id_and_email(tmp_path) -> None:
    registry_path = tmp_path / "users.json"
    registry_path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "alice",
                        "email": "alice@example.com",
                        "password_hash": "pbkdf2_sha256$1$YQ$YQ",
                        "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    users = load_user_registry(str(registry_path))
    assert users["alice"].email == "alice@example.com"
    assert users["alice@example.com"].user_id == "alice"


def test_authenticated_principal_checks_scopes_and_projects() -> None:
    principal = AuthenticatedPrincipal(
        user_id="alice",
        email="alice@example.com",
        allowed_projects=["p1"],
        scopes=["codexbridge.read"],
    )
    assert principal.has_scope("codexbridge.read")
    assert not principal.has_scope("codexbridge.task.submit")
    assert principal.can_access_project("p1")
    assert not principal.can_access_project("p2")


# --------------------------------------------------------------------------
# Adversarial review (issue #4 council): the registry loader fails closed
# --------------------------------------------------------------------------


def test_a_malformed_registry_fails_closed_instead_of_raising(tmp_path) -> None:
    """A hand-edit that leaves invalid JSON must refuse every credential, not raise.

    The request path (`authenticate`, `lookup_user`) reaches `load_user_registry`;
    an unhandled `json.JSONDecodeError` there surfaces as an unauthenticated
    `500 internal_error retryable:true` on `/auth/sign-in` and `/auth/me` — a new
    distinguishing channel and a "keep hammering" signal. `load_user_registry`
    must swallow it and return `{}` (fail closed), so `authenticate` answers the
    uniform unknown-user refusal at the registry's fallback cost.
    """
    path = tmp_path / "users.json"
    path.write_text('{"users": [ truncated mid-edit', encoding="utf-8")

    assert load_user_registry(str(path)) == {}
    outcome = authenticate(str(path), "alice", "s3cret")
    assert not outcome.ok and outcome.user is None


def test_a_shape_pydantic_refuses_fails_closed(tmp_path) -> None:
    """A structurally-valid JSON whose entries lack required fields also fails closed."""
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": [{"user_id": "alice"}]}), encoding="utf-8")

    assert load_user_registry(str(path)) == {}
    assert not authenticate(str(path), "alice", "s3cret").ok


def test_a_duplicate_user_id_refuses_the_whole_registry(tmp_path) -> None:
    """Last-write-wins on a colliding key silently rebinds a live token's privileges.

    `current_principal` re-resolves a token's `user_id` against the registry on
    every request, so a second `alice` entry — say one carrying `roles:["admin"]`
    — would inherit the first alice's already-issued tokens. The loader refuses a
    registry it cannot make unambiguous rather than pick the last entry.
    """
    first = _user(user_id="alice", email="alice@example.com", roles=[])
    second = _user(
        user_id="alice", email="other@example.com", roles=["admin"], scopes=["codexbridge.admin"]
    )
    path = _registry_file(tmp_path, first, second)

    assert load_user_registry(path) == {}, "a duplicate user_id must refuse the registry"
    assert not authenticate(path, "alice", "s3cret").ok


def test_a_user_id_colliding_with_another_email_refuses_the_registry(tmp_path) -> None:
    """A `user_id` equal to another account's e-mail is the same collision."""
    victim = _user(user_id="ops", email="ops@example.com")
    attacker = _user(user_id="ops@example.com", email="mallory@example.com", roles=["admin"])
    path = _registry_file(tmp_path, victim, attacker)

    assert load_user_registry(path) == {}


def test_a_case_variant_collision_is_refused(tmp_path) -> None:
    """The collision is case-insensitive, because resolution is.

    `lookup_user` folds the input with `.lower()` first, so an attacker whose
    `user_id` is `"OPS@EXAMPLE.COM"` resolves to the victim's `ops@example.com`
    e-mail even though the two never byte-match. Detecting the collision on the
    raw key would miss exactly this, and leave the escalation open.
    """
    victim = _user(user_id="Ops", email="ops@example.com", roles=["admin"])
    attacker = _user(user_id="OPS@EXAMPLE.COM", email="mallory@example.com", roles=[])
    path = _registry_file(tmp_path, victim, attacker)

    assert load_user_registry(path) == {}
    assert lookup_user(path, "OPS@EXAMPLE.COM") is None


def test_a_non_pbkdf2_hash_does_not_set_the_derivation_cost(tmp_path) -> None:
    """An argon2/scrypt string in the registry must not dictate the PBKDF2 target.

    `verify_password` only ever derives `pbkdf2_sha256`, so an `argon2id$N$...`
    entry is never actually verified — reading its second field as a PBKDF2 round
    count let one migrated hash impose `N` rounds on every unauthenticated
    attempt. `argon2id$99000000$...` is worth 0, like an unparseable hash, so the
    registry falls back to its cost rather than to 99 million rounds.
    """
    from gateway.app.core.users import _iterations_of, _registry_iterations

    assert _iterations_of("argon2id$99000000$c2FsdA$ZGln") == 0
    registry = load_user_registry(
        _registry_file(tmp_path, _user(password_hash="argon2id$99000000$c2FsdA$ZGln"))
    )
    # No parseable pbkdf2 cost present -> fallback, not the argon2 number.
    assert _registry_iterations(registry) == 600000


def test_an_over_ceiling_pbkdf2_hash_is_unusable_and_uncosted(tmp_path) -> None:
    """A typo'd pbkdf2 round count cannot turn one line into an authentication DoS.

    Above `_MAX_ITERATIONS` the hash is refused by `verify_password` (the account
    cannot sign in) and worth 0 to `_iterations_of` (it does not set the
    derivation target either) — so an attempt that names the account does not
    spend the absurd count, and the decoy/padding cost falls back to the
    registry's real ceiling rather than the absurd one. The hash is hand-built
    with a dummy digest so the test never itself derives 99 million rounds.
    """
    from gateway.app.core.users import _iterations_of, _registry_iterations, verify_password

    absurd = "pbkdf2_sha256$99000000$c2FsdA$ZGln"
    assert _iterations_of(absurd) == 0
    assert verify_password("anything", absurd) is False

    registry = load_user_registry(_registry_file(tmp_path, _user(password_hash=absurd)))
    # No usable pbkdf2 cost present -> fallback, not 99 million and not the ceiling.
    assert _registry_iterations(registry) == 600000
