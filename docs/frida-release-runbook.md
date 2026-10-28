# Frida deployment without Git

Deployment runs from the devel3 source checkout. Frida has **no Git**.

1. Prepare tested `development` on devel3.
2. From devel3, run `bash scripts/stage-frida-release.sh`. This creates a
   `git archive` on devel3 (only tracked files), verifies its SHA-256 on Frida,
   and stages it under the SSH user's private `~/codexbridge-staging`.
   **No service or live files are modified.**
3. Before applying a stage, the operator reviews the release, maintenance
   window, available space, pending migrations and the existing SQLite lock
   symptoms. The target must be a healthy live Gateway installation.
4. The operator copies `scripts/apply-frida-staged-release.sh` separately to
   Frida staging (e.g. `scp -P 2200 scripts/apply-frida-staged-release.sh
   esteban@frida.inovacaosistemas.com.br:~/codexbridge-staging/`).
   From an SSH terminal **on Frida**, run
   `sudo bash ~/codexbridge-staging/apply-frida-staged-release.sh --apply RELEASE_ID`.

The apply step is explicit. It refuses non-absolute SQLite paths and missing
config. It verifies the archive, makes an online `sqlite3.Connection.backup`
copy and integrity-checks the backup, copies old application files to
`/var/backups/codexbridge/RELEASE_ID/old-code`, stops the service, overlays
new tracked files without touching `.venv` or local database files, runs the
existing migration runner against the configured database, and starts the
Gateway only when migration succeeds. A failed migration leaves the service
stopped and reports the backup location for intervention; do not blindly
restore an older SQLite database without evaluating writes made after backup.
It validates local `/health` after restart.

**Known risk:** Frida reported intermittent `sqlite3.OperationalError:
database is locked` on heartbeats on 2026-10-28. Inspect concurrent SQLite
writers and pending schema migration ledger BEFORE the apply step. The
scripts do not claim to resolve the lock by upgrading or to automate
rollback. The first deployment should be scheduled when interrupting Gateway
briefly is acceptable. Do not execute any migrations during an unknown lock
incident.

**Remaining outside this deployment:** Worker credentials, local activation,
operator-issued lease, Executor dispatch and result projection. Staging a
Gateway release by itself does not make remote tasks operational.
