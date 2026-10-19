# Worker activation CLI (stage 1)

Status: implemented in `scripts/workerctl.py`, without a Worker service,
GitHub polling, Gateway integration or deployment.

This is **local configuration only**, not authority to execute anything.
The Bridge Gateway remains the authority for Project/Node permissions.
The conceptual contract and later Worker service stages are recorded in
[the design contract](https://github.com/EDortta/CodexBridge/blob/feature/worker-control-branch-contract-20261016/docs/worker-control-branch-contract.md)
and [implementation plan](https://github.com/EDortta/CodexBridge/blob/feature/worker-control-branch-contract-20261016/docs/worker-implementation-plan.md)
on the separate documentation branch. These files have not yet been merged
into `development`.

Requires Python 3.10 or newer; no additional Python packages.

## Register projects, then activate monitoring windows

Run commands from the CodexBridge repository checkout:

```console
python3 scripts/workerctl.py register --project codexbridge --repository EDortta/CodexBridge
python3 scripts/workerctl.py register --project project-b --repository my-account/project-b
python3 scripts/workerctl.py register --project project-c --repository my-account/project-c

python3 scripts/workerctl.py enable --project codexbridge
python3 scripts/workerctl.py enable --project project-b
python3 scripts/workerctl.py enable --project project-c

python3 scripts/workerctl.py list
python3 scripts/workerctl.py list --json
python3 scripts/workerctl.py disable --project project-b
```

The `register` command stores the association **locally**. The default branch
name for each association is `codexbridge-control`; override with
`register --branch <branch-name>` if the agreed control branch differs.
No branch is created or checked remotely by this script.

`enable` admits at most **three distinct projects at a time**, each for
**exactly eight elapsed hours**. Repeating `enable` while active is
idempotent: it does **not** extend the expiry. Once expired or disabled, an
explicit `enable` starts a fresh eight-hour window. `disable` frees a
slot without deleting the registration. `list` reports `inactive`,
`active`, `expired`, `disabled`, or `clock_error`, plus expiry in UTC.
Nothing is enabled automatically at startup.

## State file, concurrency, and safety

The state is local JSON, outside the checkout by default:

- Linux: `$XDG_STATE_HOME/codexbridge/workerctl.json` or
  `~/.local/state/codexbridge/workerctl.json`
- macOS: `~/Library/Application Support/CodexBridge/workerctl.json`
- Windows: `%LOCALAPPDATA%\CodexBridge\workerctl.json`

Override with `--state-file PATH` **before** the subcommand, or use
`CODEXBRIDGE_WORKERCTL_STATE` to set the default path. Keep this file out of
Git and avoid sharing its directory with untrusted local users.

The CLI uses an adjacent lock file plus an atomic JSON replacement, so
concurrent local invocations cannot independently approve a fourth project.
On Unix systems the state file is written with 0600 permissions. The
activation status is computed from UTC timestamps, so expiration does not
require a cron or background service. A clock observed earlier than the
activation start fails closed, but **a local wall clock is not a trusted
time source**. The future Worker and Gateway must enforce independent
authoritative checks on each received order.

**Current limitation:** the three-project cap applies to **one local state
file**, not to multiple Worker installations. A global cap requires
Gateway-managed leases/activation grants; do not deploy independent Workers
under the assumption that this CLI enforces a fleet-wide limit.

The script does not access other repositories, edit GitHub branches, fetch
source code, execute tasks, change Gateway configuration, or install a
Windows/macOS/Linux service. Those belong to subsequent stages and require
separate authorization. In particular, running `enable` today does
**not** start monitoring.

## Tests

```console
python3 -m pytest -q tests/unit/test_workerctl.py
```

Coverage includes eight-hour expiry, third/fourth-project boundary,
repeated activation, disabling, UTC/timezone handling, invalid/unsafe
project metadata, malformed state, symlink defense, and concurrent
processes using the same state file. Windows/macOS runtime behavior
must still be validated on those operating systems during the
multiplatform service stage.
