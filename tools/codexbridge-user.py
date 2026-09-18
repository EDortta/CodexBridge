#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

DEFAULT_REGISTRY = "/etc/codex-bridge/users.json"


def hash_password(password: str, iterations: int = 600_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return "$".join(("pbkdf2_sha256", str(iterations), encode(salt), encode(digest)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or update a CodexBridge user in the gateway registry."
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--user", required=True, dest="user_id")
    parser.add_argument("--email", required=True)
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()

    password = getpass.getpass("New CodexBridge password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("ERROR: passwords do not match")
    if len(password) < 12:
        raise SystemExit("ERROR: password must contain at least 12 characters")

    path = Path(args.registry)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        original_mode = path.stat().st_mode & 0o777
    else:
        data = {"users": []}
        original_mode = 0o600

    users = data.setdefault("users", [])
    matches = [
        user
        for user in users
        if str(user.get("user_id", "")).lower() == args.user_id.lower()
        or str(user.get("email", "")).lower() == args.email.lower()
    ]
    if len(matches) > 1:
        raise SystemExit("ERROR: ambiguous matching users in registry")

    if matches:
        user = matches[0]
        user["user_id"] = args.user_id
        user["email"] = args.email
        user["password_hash"] = hash_password(password)
        user.setdefault("enabled", True)
        action = "updated"
    else:
        if not args.create:
            raise SystemExit(
                "ERROR: user not found; re-run with --create if creation is intended"
            )

        if args.admin:
            roles = ["admin"]
            scopes = [
                "codexbridge.read",
                "codexbridge.task.submit",
                "codexbridge.task.cancel",
                "codexbridge.task.approve",
                "codexbridge.issues.write",
                "codexbridge.conversations.write",
                "codexbridge.reminders.write",
                "codexbridge.reminders.read",
                "codexbridge.notifications.manage",
                "codexbridge.admin",
            ]
            can_approve_sensitive = True
        else:
            roles = []
            scopes = ["codexbridge.read"]
            can_approve_sensitive = False

        users.append(
            {
                "user_id": args.user_id,
                "email": args.email,
                "password_hash": hash_password(password),
                "roles": roles,
                "allowed_projects": ["codexbridge"],
                "scopes": scopes,
                "enabled": True,
                "can_approve_sensitive": can_approve_sensitive,
            }
        )
        action = "created"

    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, original_mode or 0o600)
        json.loads(Path(tmp_name).read_text(encoding="utf-8"))
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    print(f"user_{action}=ok")
    print(f"user_id={args.user_id}")
    print(f"email={args.email}")
    print(f"registry={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
