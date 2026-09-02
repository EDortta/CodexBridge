from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

from gateway.app.core.config import settings


def generate_authorization_code() -> str:
    return secrets.token_urlsafe(32)


def generate_access_token() -> str:
    return secrets.token_urlsafe(48)


def generate_refresh_token() -> str:
    """A refresh token is longer-lived than an access token, so it is longer."""
    return secrets.token_urlsafe(64)


def generate_artifact_download_token() -> str:
    """A bearer credential for the bytes of one artifact (issue #11).

    Minted here rather than at the route so that every credential this gateway
    issues comes from one module and one CSPRNG (`security-standards.md` §11).
    It is stored hashed and lives for minutes, but it is still a credential: the
    generator is `secrets`, never `random`, and the length matches the access
    token's rather than being "short because the lifetime is short".
    """
    return secrets.token_urlsafe(48)


def generate_grant_id() -> str:
    """Identifier of one sign-in and every rotation descended from it.

    Not derived from a token: it is written to audit records and returned
    nowhere, so it must stay useless to anyone who reads it.
    """
    return str(uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def expires_in(seconds: int) -> datetime:
    return now_utc() + timedelta(seconds=seconds)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def issuer_metadata() -> dict:
    issuer = settings.effective_oauth_issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "scopes_supported": sorted(settings.oauth_scopes()),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
    }


def protected_resource_metadata() -> dict:
    issuer = settings.effective_oauth_issuer()
    return {
        "resource": f"{issuer}/mcp",
        "authorization_servers": [issuer],
        "bearer_methods_supported": ["header"],
        "scopes_supported": sorted(settings.oauth_scopes()),
    }


def error_redirect(redirect_uri: str, error: str, state: str | None = None, description: str | None = None) -> str:
    params = {"error": error}
    if state:
        params["state"] = state
    if description:
        params["error_description"] = description
    return f"{redirect_uri}?{urlencode(params)}"
