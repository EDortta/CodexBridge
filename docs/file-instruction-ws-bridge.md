# Gateway → WebSocket → file instruction (feature slice)

Branch: `feature/file-instruction-ws-bridge`, based on
`feature/file-instruction-executor-mvp` (PR #142).
This change deliberately does not touch `development`, the `frida`
deployment, or the existing Codex/Claude runners.

## Contract and authorization

ChatGPT calls `submit_file_instruction` with four fields:
`executor_id`, `project_id`, `instruction` (a JSON string),
`timeout_seconds`. The Gateway uses the **existing** TaskModel,
authorization for `TaskMode.TEST`, queue, `task.dispatch` and
`task.result` on the authenticated reverse WebSocket. It never requests
`edit` or `implement`; no Codex/Claude subprocess is started.

Only strict instruction schema v1 is accepted, for example:

```json
{"schemaVersion":1,"requestId":"ws-test-001","project":"codexbridge","branch":"feature/file-instruction-ws-bridge","profile":"unit-tests"}
```

The local `AgentSettings` opt-in environment variables are:
`CODEX_BRIDGE_AGENT_FILE_EXECUTOR_CONFIG_FILE` and
`CODEX_BRIDGE_AGENT_FILE_EXECUTOR_INBOX`. The file config is *operator
owned*, not delivered by ChatGPT, and must name the **same** worktree
as the Agent's approved project binding; mode bits must prevent
group/other writes. Inbox must be private (0700).

Local private config example (edit worktree root before use):

```json
{
  "project": "codexbridge",
  "branch": "feature/file-instruction-ws-bridge",
  "root": "/home/esteban/Sync/Projects/AI/CodexBridge-agent",
  "profiles": {
    "unit-tests": {
      "argv": ["python3", "-m", "pytest", "-q", "tests/unit/test_file_executor.py", "tests/unit/test_file_ws_adapter.py"],
      "timeout_seconds": 180
    }
  }
}
```

The adapter verifies that the dispatched task is `test` only and carries
no issue, session or delivery fields. It verifies the approved project,
operator config, current branch, and local allowlisted profile, then
writes the instruction into the private inbox. Execution generates
`[DONE]` and JSON receipt. Gateway persists completion via the existing
`task.result` handler; repeated request IDs return the prior receipt.
A failed file run still ends with `[DONE]`, but sends `failed`.

## Verification gates

The targeted CI runs real local subprocesses, including the
`AgentService._handle_dispatch` WS-envelope handling (captured socket)
and confirms atomic local results. This is a **protocol-handler test**,
not a live authenticated Gateway/Agent network test. It does not prove
that a plugin reload has exposed the new MCP tool, or that the devel3
systemd agent has reloaded the new code.

A live acceptance run still requires:
1. Install this branch on devel3 with an unmodified local worktree
   and the operator-owned private config, without altering frida.
2. Upgrade Gateway in a controlled stage, reload MCP tool publication,
   verify the tool can submit a TEST-mode request.
3. Observe Gateway task IDs and actual WS ACK/result as well as local
   `[DONE]` and SHA-256 receipt.
4. Confirm retry, negative policy case and the existing centralized
   development-evidences publication. The shared collector is *not*
   wired to the new receipt in this slice.

This is an opt-in pilot. A task in `test` mode can still trigger the
operator-configured `argv`; keep profiles read-only or test-only and
ensure profile files are never writable by the untrusted request source.

## Existing agent worktree

**Run only after checking clean status.** The original
`feature/mvp-agent-communication` branch stays intact:

```bash
cd /home/esteban/Sync/Projects/AI/CodexBridge-agent
git status --short
git fetch origin
git switch --track origin/feature/file-instruction-ws-bridge
git status --short --branch
python3 -m pytest -q tests/unit/test_file_executor.py tests/unit/test_file_ws_adapter.py
```

If `git status --short` is not empty, do **not** switch until those changes
have been preserved in their original branch. No force, reset, or clean.

## Mandatory evidence for every verification command

Do not invoke `pytest` or a verification script bare. Wrap it with
`scripts/run_file_ws_evidence.py`, which ALWAYS records a local execution
log and sanitized JSON manifest, even when the command exits nonzero, times
out or cannot be spawned. It uses the already configured
`development-evidences/publisher.py` enqueue/flush interface. The command
exit code is preserved; a successful check with unsuccessful publication
returns nonzero to avoid false acceptance.

```bash
cd /home/esteban/Sync/Projects/AI/CodexBridge-agent
git pull --ff-only
python3 scripts/run_file_ws_evidence.py --timeout 300 -- \
  python3 -m pytest -q tests/unit/test_file_executor.py \
  tests/unit/test_file_ws_adapter.py tests/unit/test_file_ws_evidence.py
```

Output shows `STATUS`, `EXIT_CODE`, `EVIDENCE_DIR`,
`EVIDENCE_PUBLICATION` and `EVIDENCE_URL` only when actual publication
is confirmed. Raw `execution.log` stays private, with `0600` permissions.
A failed run gets `status=failed`, not a missing record.

GitHub Actions sets `--no-publish` because it has no authorized evidence
publisher credentials. Its `always()` artifact step uploads sanitized
manifest and publication status on both success and failure; never raw logs.
That CI-specific opt-out is not the command to run on devel3. It is not
proof that the shared Git repository was updated by the CI runner.

## MCP read-only execution evidence

New tool: `list_execution_evidence(executor_id, project_id, feature, limit=5)`.
Requires OAuth `codexbridge.read`, project-level access and the
project enabled on the executor. It sends a bounded `evidence.query` over
the existing authenticated reverse WebSocket, and returns a correlated
`evidence.result` (12-second timeout). This tool does **not** submit an
execution, start a coding CLI, read arbitrary files, or share raw logs.

For the initial version the local reader only supports project ID
`codexbridge` with runs produced by `run_file_ws_evidence.py` under
`<state-root>/codexbridge/<feature>/<run-id>/manifest.json`. The private
evidence root is configured on the Agent through
`CODEX_BRIDGE_AGENT_EVIDENCE_STATE_ROOT`, defaulting to the Agent's own
`~/.local/state`. When tests run as a different Unix user from the
systemd agent, provision an explicitly shared **read-only** evidence
directory or run the publisher under the agent user; do not grant
arbitrary broad filesystem visibility to the gateway.

The result is intentionally sanitised: feature, branch, commit, status,
exit code, timestamps, test counts, failed test IDs, log SHA256,
publication status and a GitHub evidence URL only when the **local**
publisher reported `published`. `verified_remote: false` is always
returned, because that is not an independent GitHub lookup. Missing
evidence, disconnected executor and timeout are distinct statuses.
A successful local file read is **not** proof of deployed gateway code.

Example MCP arguments (after Gateway and Agent are deployed):

```json
{"executor_id":"devel3","project_id":"codexbridge","feature":"file-instruction-ws-bridge","limit":5}
```

**Rollout gate:** Both ends must be updated, and the new MCP schema must
be reloaded by the connected plugin. No production restart or deployment
was performed by this branch commit. CI exercises a captured WebSocket
and reader but cannot prove the live frida/devel3 network roundtrip.

## Interruption during a deterministic file run (reconnect recovery)

A live devel3 test on 25 November 2026 interrupted the user Agent while
`unit-tests` was active. The observer confirmed a systemd restart but found
the instruction stuck at `<requestId>.running` without a receipt, while the
Gateway persisted the task as `running`. The original build failed recovery.

The recovery contract is **fail-closed**, not transparent rerun:

1. On reconnect, the Gateway resends only outstanding `engine=file`,
   `mode=test`, `state=running` envelopes, preserving the task ID.
2. If the Agent has the original completed receipt, it sends that receipt
   again (success or failure) without executing.
3. If the Agent instead finds an orphaned `.running` instruction, it
   atomically finalizes an `interrupted` failure receipt, retaining the
   original instruction hash, and reports the failure to the Gateway.
4. A different instruction with the same request ID is rejected.
5. No untrusted instruction can command a rerun. A human may submit a *new*
   request ID after investigating the interrupted result.

A test interrupted during execution is **not** considered passed. Acceptance
requires the Gateway task to leave `running`, the Agent to reconnect, and
the same original request ID to have only one execution attempt.
Other engines and terminal task states are not replayed.

This change needs coordinated Agent and Gateway deployment and a new live
systemd-interruption acceptance test. Unit/integration tests alone do not
prove the live deployment or that the original stuck task was reconciled.
