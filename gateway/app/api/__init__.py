"""Cross-cutting HTTP behaviour for the mobile API (issue #12).

Everything under `/api` shares one error envelope, one pagination convention,
one idempotency rule and one concurrency rule, so that a mobile client can
handle failures, retries and stale writes the same way at every endpoint
instead of learning each one.

Scope matters here: these behaviours apply to the contract surface only. The
MCP transport at `POST /mcp` has its own error shape, fixed by JSON-RPC and by
what ChatGPT's client expects, and must not be reshaped by this package.
`gateway/app/api/scope.py` is the single place that decides which requests are
in scope.
"""
