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
