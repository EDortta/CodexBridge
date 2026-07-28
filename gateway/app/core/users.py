from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

from pydantic import BaseModel, Field


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


def load_user_registry(path: str) -> dict[str, GatewayUser]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    payload = UserRegistry.model_validate(json.loads(file_path.read_text(encoding="utf-8")))
    users: dict[str, GatewayUser] = {}
    for user in payload.users:
        users[user.user_id] = user
        users[user.email.lower()] = user
    return users


def lookup_user(path: str, username_or_email: str) -> GatewayUser | None:
    registry = load_user_registry(path)
    return registry.get(username_or_email.lower()) or registry.get(username_or_email)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    salt = _b64decode(salt_b64)
    expected = _b64decode(digest_b64)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(derived, expected)


def _b64decode(value: str) -> bytes:
    padding = "=" * ((4 - (len(value) % 4)) % 4)
    return base64.urlsafe_b64decode(value + padding)
