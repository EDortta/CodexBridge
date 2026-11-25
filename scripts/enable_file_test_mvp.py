#!/usr/bin/env python3
"""Pre-MVP: grant only TEST for codexbridge/devel3 on the live Gateway.

Executed from devel3; requires operator sudo on frida for maintenance only.
Never changes the Agent's Unix user. Publishes sanitized authorization evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
from datetime import datetime, timezone

REMOTE = r'''
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from gateway.app.models.entities import (ExecutorModel, ProjectModel,
    WorkspaceBindingModel, ProjectAuthorizationModel)
from gateway.app.services import store
from shared.protocol import Capability, TaskMode

pid = subprocess.check_output(
    ["systemctl", "show", "--value", "-p", "MainPID",
     "codex-bridge-gateway.service"], text=True).strip()
if not pid.isdecimal() or int(pid) < 1:
    print(json.dumps({"status": "gateway_not_running"})); raise SystemExit(2)
proc = Path("/proc") / pid
for entry in (proc / "environ").read_bytes().split(bytes([0])):
    if entry.startswith(b"CODEX_BRIDGE_") and b"=" in entry:
        key, value = entry.split(b"=", 1)
        os.environ[key.decode()] = value.decode()
os.chdir(os.readlink(proc / "cwd"))
from gateway.app.core.config import settings
from gateway.app.db.session import SessionLocal

async def pair(db):
    return (await db.get(ExecutorModel, "devel3"),
            await db.get(ProjectModel, "codexbridge"))

async def find_session():
    async with SessionLocal() as db:
        executor, project = await pair(db)
        if executor is not None and project is not None:
            return SessionLocal, None
    # When a deployed service gets the DB URL from a wrapper or hidden config,
    # inspect ONLY its actually open SQLite descriptors (no directory scan).
    paths = set()
    for fd in (proc / "fd").iterdir():
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.endswith((".db", ".sqlite", ".sqlite3")):
            paths.add(target)
        elif target.endswith((".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm")):
            paths.add(target.rsplit("-", 1)[0])
    matching = []
    for target in sorted(paths):
        try:
            conn = sqlite3.connect("file:" + target + "?mode=ro", uri=True)
            try:
                ok = (conn.execute("select 1 from executors where id='devel3'").fetchone()
                      and conn.execute("select 1 from projects where id='codexbridge'").fetchone())
            finally:
                conn.close()
            if ok:
                matching.append(target)
        except (sqlite3.Error, OSError):
            continue
    if len(matching) != 1:
        return None, "active_db_not_unique_or_found"
    from sqlalchemy.ext.asyncio import AsyncSession
    url = "sqlite+aiosqlite:///" + matching[0]
    engine = create_async_engine(url, connect_args={"timeout": 30})
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory, engine

async def main():
    factory, engine = await find_session()
    if factory is None:
        return {"status":"blocked","reason":engine}
    try:
        async with factory() as db:
            executor, project = await pair(db)
            if not executor or not project or not executor.enabled or not project.enabled:
                return {"status":"blocked","reason":"registration_disabled"}
            config = json.loads(project.config_json)
            allowed = config.get("allowed_modes", [])
            if not isinstance(allowed, list):
                return {"status":"blocked","reason":"invalid_modes"}
            binding = (await db.execute(select(WorkspaceBindingModel).where(
                WorkspaceBindingModel.node_id == executor.node_id,
                WorkspaceBindingModel.project_id == project.id))).scalars().first()
            authorization = None
            capabilities = []
            if binding is not None:
                authorization = (await db.execute(select(ProjectAuthorizationModel).where(
                    ProjectAuthorizationModel.node_id == executor.node_id,
                    ProjectAuthorizationModel.project_id == project.id))).scalars().first()
                if authorization is not None and authorization.revoked_at is not None:
                    return {"status":"blocked","reason":"explicitly_revoked"}
                if authorization is not None:
                    capabilities = json.loads(authorization.capabilities_json or "[]")
                    if any(c not in {v.value for v in Capability} for c in capabilities):
                        return {"status":"blocked","reason":"unknown_capability"}
            changed_base = False
            if TaskMode.TEST.value not in allowed:
                config["allowed_modes"] = allowed + [TaskMode.TEST.value]
                project.config_json = json.dumps(config)
                changed_base = True
                from gateway.app.services.audit import record_event
                await record_event(db, "project", project.id,
                    "project.test_mode_enabled",
                    {"executor_id":"devel3","mode":"test","origin":"operator_mvp"})
                await db.commit()
            changed_grant = False
            if binding is not None and Capability.TEST.value not in capabilities:
                await store.grant_project_authorization(
                    db, node_id=executor.node_id, project_id=project.id,
                    capabilities=[Capability(c) for c in capabilities] + [Capability.TEST],
                    granted_by="operator:mvp-file-test",
                )
                changed_grant = True
            effective = await store.effective_task_modes(db, executor, project)
            return {"status":"authorized" if TaskMode.TEST in effective else "blocked",
                    "test_allowed":TaskMode.TEST in effective,
                    "base_changed":changed_base,"grant_changed":changed_grant,
                    "has_binding":binding is not None}
    finally:
        if engine is not None:
            await engine.dispose()

print(json.dumps(asyncio.run(main()), sort_keys=True))
'''

def main():
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
               "-p", "2200", "esteban@frida.inovacaosistemas.com.br",
               "cd /opt/codex-bridge && sudo -n /opt/codex-bridge/.venv/bin/python -c "
               + shlex.quote(REMOTE)]
    try:
        run = subprocess.run(command, capture_output=True, text=True, timeout=70)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("STATUS=transport_failed", type(exc).__name__)
        return 2
    if run.returncode:
        print("STATUS=remote_failed", "EXIT_CODE=" + str(run.returncode))
        return 2
    try:
        data = json.loads(run.stdout.splitlines()[-1])
    except (ValueError, IndexError):
        print("STATUS=invalid_response")
        return 2
    safe = {key:data[key] for key in ("status","reason","test_allowed",
        "base_changed","grant_changed","has_binding") if key in data}
    print("GATEWAY_AUTH=" + json.dumps(safe, sort_keys=True))
    now = datetime.now(timezone.utc)
    relative = "CodexBridge/file-submit-authorization/" + now.strftime(
        "%Y-%m-%d/%Y%m%dT%H%M%SZ-") + secrets.token_hex(4) + "/manifest.json"
    publisher = Path.home() / ".local/state/development-evidences/repo/publisher.py"
    if not publisher.is_file():
        print("EVIDENCE_PUBLICATION=unavailable")
        return 3
    envelope = {"relative_path":relative,"report":{
        "schema":1,"project":"CodexBridge","feature":"file-submit-authorization",
        "timestamp_utc":now.isoformat(),"diagnostic":safe,
        "status":"success" if safe.get("status") == "authorized" else "failed"}}
    state = Path.home() / ".local/state/codexbridge"
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp = state / ("auth-" + secrets.token_hex(8) + ".json")
    temp.write_text(json.dumps(envelope) + "\n")
    temp.chmod(0o600)
    try:
        put = subprocess.run([sys.executable,str(publisher),"enqueue",
            "--file",str(temp)],capture_output=True,timeout=30)
        if put.returncode:
            print("EVIDENCE_PUBLICATION=enqueue_failed")
            return 3
        flush = subprocess.run([sys.executable,str(publisher),"flush"],
            capture_output=True,timeout=120)
        published = flush.returncode == 0 and (
            "published=" + relative).encode() in flush.stdout.splitlines()
        print("EVIDENCE_PUBLICATION=" + ("published" if published else "failed"))
        if published:
            print("EVIDENCE_URL=https://github.com/EDortta/development-evidences/blob/main/" + relative)
        return 0 if published and safe.get("status") == "authorized" else 3
    finally:
        temp.unlink(missing_ok=True)

if __name__ == "__main__":
    sys.exit(main())
