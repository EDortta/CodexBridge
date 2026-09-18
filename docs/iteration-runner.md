# Iteration Runner

`tools/iteration_runner.py` is a one-shot runner intended for cron. It turns a
repository manifest into at-most-once test rounds without keeping a daemon alive.

## Why it is cron-based

The machine may reboot. Cron restarts with the OS, while a long-lived monitor
needs its own service lifecycle. Each invocation is short and acquires a
non-blocking repository lock. If another invocation or automated test owns the
lock, the new invocation exits cleanly.

A reboot in the middle of a test releases the kernel lock automatically. No
round result is written until the child process finishes. Therefore the next
cron invocation retries the same round. Tests used by this mechanism MUST be
idempotent.

## Manifest

The controller writes `.codexbridge/iteration.json`.

- `enabled`: global switch.
- `run_id`: stable identity for the whole investigation/task.
- `project`: logical project name.
- `round`: 1-based round number. The controller MUST increment it before a
  new implementation/test round.
- `max_rounds`: hard stop.
- `deadline`: ISO-8601 timestamp with timezone; hard stop across reboots.
- `branch`: branch the checkout must already be on.
- `script`: repository-relative script; paths outside the checkout are refused.
- `args`: optional argument list.
- `timeout_seconds`: hard timeout for the test.
- `status`: one of `ready`, `paused`, `done`, `failed`, `needs_human`.
- `ready_revision`: optional commit that must be an ancestor of current HEAD.

Only `enabled=true` plus `status=ready` executes.

## Idempotency and uniqueness

The unique execution identity is `(run_id, round)`. The canonical machine
result is:

`iteration-results/<run_id>/round-NNN.json`

and the human log is the adjacent `.log` file. Once the JSON is tracked, that
round never executes again. The local `flock` at
`.git/codexbridge-project-execution.lock` prevents overlapping automated
rounds in the same checkout.

The result is written atomically, committed, and pushed. A failed test is still
a successful runner operation: its JSON says `status=failed` and carries the
exit code. This lets a controller react without relying on cron exit status.

## Resilience

Before execution the runner requires a clean tracked worktree and performs
`git fetch` plus `git pull --ff-only`. It never resets, cleans, autostashes,
or weakens GovernanceKit. Unrelated untracked files are left alone.

A test timeout is recorded with exit code 124. Pushes retry up to three times;
if the remote moved, only the clean result commit is rebased.

If `round > max_rounds` or the deadline has passed, a single
`terminal.json` is committed instead of running another test.

## Cron

Run every minute; overlapping invocations are harmless:

```cron
* * * * * cd /home/esteban/Sync/Projects/AI/CodexBridge && /usr/bin/python3 tools/iteration_runner.py >> ~/.local/state/codexbridge-iteration-runner/cron.log 2>&1
```

Ensure the parent state directory exists once:

```bash
mkdir -p ~/.local/state/codexbridge-iteration-runner
```

The 23:30 reboot does not need special handling. After boot, cron invokes the
runner again; the repository result files decide whether a round is complete.

## Controller/webhook handoff

Every round produces structured JSON suitable for a GitHub/GitLab webhook or an
external iteration controller. The controller should:

1. react only to `iteration-results/**/*.json`;
2. deduplicate by `run_id + round`;
3. inspect the result and diagnostics;
4. implement/fix the next change;
5. increment `round`, update `ready_revision` if desired, set
   `status=ready`, and push;
6. stop by setting `done`, `needs_human`, or by the hard max/deadline.

Do not trigger on every repository push. That creates feedback loops.
