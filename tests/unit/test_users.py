from __future__ import annotations

import json

from gateway.app.core.users import AuthenticatedPrincipal, load_user_registry, verify_password


def test_verify_password_accepts_known_hash() -> None:
    assert verify_password(
        "change-me-now",
        "pbkdf2_sha256$600000$i5bjWyIkeqmiK7hOrL0g2Q$_sGD6Ia_tKwSQcCj8sLn4DvA5PbmGGCyilYzklVV4lo",
    )


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
