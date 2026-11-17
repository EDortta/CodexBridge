# File instruction executor MVP (experimental)

This increment is a deterministic, **local** execution layer. It does not call
Codex, Copilot, any LLM, or require ChatGPT write capabilities.

## Boundaries

The ChatGPT/MCP/Gateway/WS stack already exists. This increment does **not**
yet bridge WebSocket delivery to the filesystem inbox; do not represent it as
an end-to-end deployment. The existing Worker Git control branch intake only
admits requests and does not authorize execution. A subsequent adapter must
translate an independently approved Gateway operation into this schema, then
write it atomically to the agent inbox. Never feed arbitrary unapproved Git
requests directly into this executor.

The agent operator provisions a private config file containing exactly:
`project`, `branch`, `root`, `profiles`. Neither ChatGPT nor the instruction
file can choose a path or executable. A profile has an argv array
(no shell interpolation) and `timeout_seconds` (1..600). Treat operator
profiles as privileged configuration and never allow modification from the
untrusted inbox. Use read-only profiles for tests/verification until an
operator explicitly authorizes a mutating profile. Keep the inbox private to
the agent OS user.

Example operator configuration (not supplied by ChatGPT):

```json
{
  "project": "codexbridge",
  "branch": "feature/file-instruction-executor-mvp",
  "root": "/path/to/operator-approved/worktree",
  "profiles": {
    "unit-tests": {
      "argv": ["python3", "-m", "pytest", "-q", "tests/unit"],
      "timeout_seconds": 120
    }
  }
}
```

An instruction file named `verify-001.json`:

```json
{
  "schemaVersion": 1,
  "requestId": "verify-001",
  "project": "codexbridge",
  "branch": "feature/file-instruction-executor-mvp",
  "profile": "unit-tests"
}
```

After an authorized upstream transport atomically delivers that file to the
inbox, invoke:

```bash
python3 -m agent.codex_bridge_agent.file_executor \
  --config /path/to/private/operator-config.json \
  --inbox /path/to/private/inbox
```

A completed instruction is renamed `verify-001[DONE].json`; its outcome is
`results/verify-001.json`. **DONE means terminal, not successful.**
The outcome records `status`, `exitCode`, start/finish timestamps,
profile, SHA-256 of instruction, bounded output and timeout/truncation fields.

Atomic rename claims pending files. A process-level flock prevents two
executor instances sharing an inbox from executing simultaneously. Restart
after an interrupted command records `failed/interrupted` without replay:
side effects cannot reliably be rolled back, so this favors at-most-once
rather than claiming exactly-once execution. Repeated request IDs with a
persisted result do not reexecute. Different inboxes must not refer to the
same worktree without a higher-level project/branch lock.

## Proof and limitations

```bash
python3 -m pytest -q tests/unit/test_file_executor.py
```

The standalone runner uses real subprocesses in temporary Git repositories.
The targeted CI workflow exercises this test file on GitHub Actions. This
does **not** establish a live Gateway -> WS -> Agent -> inbox proof; that
integration and deployment to devel3 are separate acceptance gates.

This MVP does not yet publish to the shared development-evidences repository.
The result JSON is the local evidence format; no hardcoded remote evidence URL
is introduced here. Also not yet implemented: trusted WebSocket adapter,
project-wide lock across multiple inboxes, OS sandbox/cgroup, durable event
receipt on Gateway, and shared evidence publication. Those are blockers for
a production claim.
