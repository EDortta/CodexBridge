# Worker transport probe (stage 2, read-only)

The service transport probe in `scripts/worker_watch.py` reads **only**
`.codexbridge/requests/*.json` metadata from the dedicated control branch
of locally active projects. It never reads the JSON body, dispatches commands,
contacts the Gateway, writes results, or claims remote execution. This is an
incremental observer, **not an operational remote executor**.

Run in the CodexBridge checkout (after activating the project with workerctl):

```sh
python3 scripts/workerctl.py register --project codexbridge --repository EDortta/CodexBridge
python3 scripts/workerctl.py enable --project codexbridge
python3 scripts/worker_watch.py --once
python3 scripts/worker_watch.py --interval 60
```

For GitHub private repositories a least-privilege read credential can be provided
in `CODEXBRIDGE_GITHUB_TOKEN` through the host's protected secret store. Never
commit it or put it in arguments/logs. The control branch and
`.codexbridge/requests/` must exist; a missing directory is a visible poll
error and is **not** treated as a successful empty scan.

This stage intentionally performs no execution. Before dispatching:
validate request envelopes and immutable SHAs, introduce a persistent
checkpoint/lease and Gateway-verified authorization, authenticate Worker to
Gateway, add text-result publishing with redaction and bounded output, and
test restarts, offline handling, expiry and duplicate deliveries. No install,
restart or deployment is implied by merging this branch.
