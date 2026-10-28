#!/usr/bin/env python3
"""Provision/revoke Worker identity on the Gateway; run locally as Gateway operator.

No public enrollment endpoint and no privilege derived from a GitHub token.
The machine secret is generated once and saved mode 0600; stdout is never a
credential channel. Worker enrollment is a Gateway-local administrative step.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import sys

# Allow direct execution from scripts/ without pip-installing the checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from gateway.app.models.entities import WorkerIdentityModel
from shared.security import hash_token

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def write_secret(path: Path, secret: str) -> None:
    """Create once, fail if it exists (never overwrite a deployed credential)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def provision(database_url: str, worker_id: str, secret_file: Path) -> None:
    if not ID.fullmatch(worker_id):
        raise ValueError("invalid Worker ID")
    if not secret_file.is_absolute():
        raise ValueError("secret-file must be an absolute path")
    engine = create_async_engine(database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            if await session.get(WorkerIdentityModel, worker_id) is not None:
                raise ValueError("Worker ID already registered")
            token = secrets.token_urlsafe(48)
            # Save before commit; remove on DB error. Never display the token.
            write_secret(secret_file, token)
            try:
                session.add(WorkerIdentityModel(
                    id=worker_id, token_hash=hash_token(token),
                    enabled=True, created_at=datetime.now(timezone.utc),
                    revoked_at=None,
                ))
                await session.commit()
            except BaseException:
                secret_file.unlink(missing_ok=True)
                raise
    finally:
        await engine.dispose()


async def revoke(database_url: str, worker_id: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            identity = await session.get(WorkerIdentityModel, worker_id)
            if identity is None:
                return False
            identity.enabled = False
            identity.revoked_at = datetime.now(timezone.utc)
            await session.commit()
            return True
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("worker_id")
    create.add_argument("--secret-file", required=True, type=Path)
    rev = sub.add_parser("revoke")
    rev.add_argument("worker_id")
    args = parser.parse_args()
    try:
        if args.command == "create":
            asyncio.run(provision(args.database_url, args.worker_id, args.secret_file))
            print(f"Worker {args.worker_id} registered; credential saved to {args.secret_file}")
        elif args.command == "revoke":
            found = asyncio.run(revoke(args.database_url, args.worker_id))
            print("Worker revoked" if found else "Worker not found")
            if not found:
                return 1
        return 0
    except (ValueError, OSError) as exc:
        print(f"Cannot complete Worker provisioning: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
