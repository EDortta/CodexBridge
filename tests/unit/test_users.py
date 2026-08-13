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
