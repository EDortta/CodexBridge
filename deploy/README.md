# What is deployed, and what only looks deployed

Verified against the running hosts on **2026-08-10**. This file exists because
`deploy/` was found to be stale relative to production in two ways at once — a
file name that did not match, and a port that did not match — and stale
deployment config is worse than none, because it reads as authority.

## Live

| path | host | notes |
|---|---|---|
| `nginx/frida-codex-bridge.conf` | `frida` | **Installed as `/etc/nginx/sites-available/codexbridge-https`.** The names differ: editing the file here does not touch the host, and vice versa. Verified byte-identical to the installed copy before the 2026-08-10 deploy. |
| `systemd/codex-bridge-gateway.service` | `frida` | The running unit binds `--port 18080`. This file used to say `8080`, which would have collided with `mosquitto` and crash-looped under `Restart=always`; it now reads the port from `CODEX_BRIDGE_BIND_PORT`. |
| `nginx/dom1-codexbridge.conf` — **only** the `/.well-known/acme-challenge/` block | `dom1` | Certificate renewal. This is the sole remaining CodexBridge-related job on dom1. |

The gateway listens on `127.0.0.1:18080`; nginx terminates TLS on **internal
443**, published **externally as 8443**. Nothing listens on 8443 on the host —
`https://codexbridge.inovacaosistemas.com.br:8443` reaches nginx's 443 through
the port publish, which is NAT and appends nothing to `X-Forwarded-For`.

## Retired — kept for reference, not in any request path

Confirmed by the operator on 2026-08-10: **dom1 no longer serves CodexBridge**;
it only helps renew the certificate.

| path | why it is here |
|---|---|
| `nginx/dom1-codexbridge.conf` — the `location /` block proxying to `127.0.0.1:18081` | the old dom1 ingress into the Incus edge proxy |
| `incus/codexbridge_edge_proxy.py` | the Incus edge proxy itself |
| `systemd/codexbridge-edge-proxy.service` | its unit |
| `nginx/codexbridge-container.conf` | the vhost inside the Incus container; **not installed on frida** |

They are kept rather than deleted because they document a topology that worked
and may be wanted again. **They are not neutral, though:** if any of them is put
back in front of the gateway, the chain grows two `X-Forwarded-For` entries and
their addresses must be added to `CODEX_BRIDGE_API_TRUSTED_PROXIES`, or every
anonymous caller collapses into one rate-limit bucket.

## Rules that cost something to learn

- **Publishing a route is two edits**: the router *and* the vhost. Both frida
  vhosts are location allowlists with no catch-all, so an unlisted route is a
  404 at the front door however well it works in the application. That is how
  `/health`, `/ready` and the whole `/api` surface shipped fully tested and
  entirely unreachable. `tests/contract/test_proxy_routes.py` now fails on it.
- **Migrations are not automatic, and a clean start does not mean they ran.**
  The gateway refuses to start when a migration adds a *column* it has not seen
  (`gateway/app/db/schema_guard.py`), and the unit restarts every 5s, so
  skipping the step can turn an upgrade into a crash loop. A migration that only
  adds *tables* — 0006, 0007 and 0008 — fails **silently**: `startup` runs
  `Base.metadata.create_all` before `check_schema`, so the gateway creates them
  itself and serves on a schema without the `.sql`'s indexes and defaults, with
  no `schema_migrations` row. Applying it stays an operator decision:
  `docs/installation.md`, step 9.
- **`EnvironmentFile` is not a shell script.** `. /etc/codex-bridge/env` fails in
  bash, because the format allows unquoted values with spaces. Read the one
  variable you need with `sed -n 's/^VAR=//p'`.
