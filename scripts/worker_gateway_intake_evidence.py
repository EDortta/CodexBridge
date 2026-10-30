#!/usr/bin/env python3
"""One-shot Git SSH -> Worker -> Gateway intake, sanitized immutable evidence.

Run as developer. Reads local user service environment, never emits a token,
HTTP body or raw stderr. Does not start the daemon or execute any request.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import uuid

HOME=Path.home()
ROOT=Path(os.environ.get("XDG_STATE_HOME",str(HOME/".local/state")))/"codexbridge-worker"
CONFIG=Path(os.environ.get("XDG_CONFIG_HOME",str(HOME/".config")))/"codexbridge-worker"
WATCH=Path(os.environ.get("XDG_DATA_HOME",str(HOME/".local/share")))/"codexbridge-worker/scripts/worker_watch.py"
PUBLISHER=HOME/".local/state/development-evidences/repo/publisher.py"
ID="smoke-20261030-worker-intake"

def main():
    now=datetime.now(timezone.utc)
    runid=now.strftime("%H%M%S")+"-"+uuid.uuid4().hex[:8]
    checks={"user_context":os.geteuid()!=0,"watcher_installed":WATCH.is_file(),
            "request_observed":False,"gateway_admitted":False}
    env=os.environ.copy()
    if (CONFIG/"worker.env").is_file():
        for line in (CONFIG/"worker.env").read_text().splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                k,v=line.split("=",1)
                if k.startswith("CODEXBRIDGE_"):
                    env[k]=v.strip().strip('"')
    if checks["user_context"] and checks["watcher_installed"]:
        try:
            proc=subprocess.run(
                [sys.executable,str(WATCH),"--state-file",str(ROOT/"state.json"),
                 "--once","--forward-gateway"],
                env=env,capture_output=True,text=True,timeout=90)
            checks["worker_exit_ok"]=proc.returncode==0
            for line in proc.stdout.splitlines():
                try:
                    item=json.loads(line)
                except ValueError:
                    continue
                if item.get("project")!="codexbridge":
                    continue
                checks["request_observed"]=any(req.get("name")==ID+".json"
                                                 for req in item.get("requests",[]))
                checks["gateway_admitted"]=any(rec.get("requestId")==ID
                    and rec.get("state")=="admitted" for rec in item.get("gateway_admissions",[]))
            if proc.returncode!=0:
                # Only a classification; subprocess stderr is never published.
                checks["worker_failed"]=True
        except (OSError,subprocess.TimeoutExpired):
            checks["runner_error"]=True
    status="pass" if all((checks["user_context"],checks["request_observed"],
                          checks["gateway_admitted"])) else "attention"
    report={"schema":1,"project":"CodexBridge","feature":"worker-gateway-intake",
            "branch":"development","timestamp_utc":now.isoformat(),"run_id":runid,
            "status":status,"checks":checks,"secrets_included":False}
    print(json.dumps(report,indent=2))
    if not PUBLISHER.is_file():
        print("Publisher unavailable",file=sys.stderr)
        return 2
    envelope={"relative_path":f"CodexBridge/worker-gateway-intake/development/{now:%Y-%m-%d}/{runid}/manifest.json",
              "report":report}
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/"envelope.json"
        path.write_text(json.dumps(envelope))
        for args in (["enqueue","--file",str(path)],["flush"]):
            p=subprocess.run([sys.executable,str(PUBLISHER),*args],
                              capture_output=True,text=True,timeout=90)
            if p.returncode:
                print("Publisher failed on "+args[0],file=sys.stderr)
                return 2
    return 0 if status=="pass" else 1

if __name__=="__main__":
    raise SystemExit(main())
