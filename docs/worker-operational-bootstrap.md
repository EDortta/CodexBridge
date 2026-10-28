# Worker operational bootstrap (Linux/systemd)

**Deploy only after Gateway has been updated and migrations 0020–0022 were applied.**

On the Gateway host, provision a Worker identity locally with
`python3 scripts/worker_identity.py --database-url "$DATABASE_URL" create devel3 --secret-file /secure/worker-token`.
This writes a fresh randomly generated credential to an owner-only file,
never stdout. Transfer it to `/etc/codexbridge-worker/worker-token` on devel3
through a secure administrator-controlled method, without committing it.
Use `revoke devel3` to invalidate it.

On devel3 run `sudo bash scripts/install-worker-systemd.sh` from the
CodexBridge checkout. It installs a disabled systemd service. Store a
read-only GitHub token at `/etc/codexbridge-worker/github-token`, configure
both secret files readable only by root and the Worker service group
(`chmod 0640`, `chown root:codexbridge-worker`).

Use `sudo -u codexbridge-worker python3 scripts/workerctl.py
--state-file /var/lib/codexbridge-worker/state.json register ...` (see
`python3 scripts/workerctl.py --help` for exact CLI syntax); then activate
the project locally and issue the corresponding eight-hour lease via the
Gateway's admin-only `POST /control/workers/{worker_id}/activate` endpoint.
The Gateway project must already have the approved `worker_repository`
binding in `ProjectModel.config_json`. Finally `systemctl enable --now
codexbridge-worker`.

**Important limitations:** This installs only the GitHub→Gateway *admission*
transport. It does **not** dispatch Executor tasks or write results back to
GitHub/ChatGPT. The planned end-to-end execution milestone still requires
Gateway-side commit/Node authorization, dispatch, and result projection.
Never start the service assuming a registered Worker credential is an
execution authorization.
