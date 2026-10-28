# Worker → Gateway intake forwarding

The Worker observer remains read-only by default. With explicit `--forward-gateway`, it fetches JSON by immutable Git blob SHA, validates the envelope, verifies `requestId` matches the filename, then submits that envelope via HTTPS `POST /control/worker-intake/requests`. The Gateway independently checks the Worker credential and active operator-issued activation lease; its response is admission metadata only, **not execution**.

Environment variables: `CODEXBRIDGE_GITHUB_TOKEN` (GitHub read token), `CODEXBRIDGE_GATEWAY_URL` (bare HTTPS origin), and `CODEXBRIDGE_WORKER_TOKEN` (separately provisioned Gateway Worker credential). They must never be printed or committed. Example: `python3 scripts/worker_watch.py --once --forward-gateway`. Running this without a fully provisioned Worker and deployed Gateway endpoint will fail; it never creates credentials or leases.

Requests repeat at polling intervals; the Gateway project/request ID ledger is the deduplication authority. **No local checkout, shell, Executor dispatch, result publishing, or deployment** is included. A Gateway authorization step must still bind the exact source commit and Node permissions before any real work.
