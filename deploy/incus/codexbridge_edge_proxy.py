"""RETIRED 2026-08-10 — the Incus edge proxy on the dom1 path.

dom1 no longer serves CodexBridge; it only renews the certificate.
Kept for reference. Reinstating it grows the X-Forwarded-For chain —
see deploy/README.md before doing so.
"""

from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request, Response


UPSTREAM_BASE = os.environ.get("CODEXBRIDGE_EDGE_UPSTREAM", "https://codexbridge.inovacaosistemas.com.br:8443").rstrip("/")
UPSTREAM_HOST = os.environ.get("CODEXBRIDGE_EDGE_HOST", "codexbridge.inovacaosistemas.com.br")
TIMEOUT = httpx.Timeout(60.0, connect=10.0)

app = FastAPI(title="CodexBridge Edge Proxy", docs_url=None, redoc_url=None, openapi_url=None)
client = httpx.AsyncClient(verify=True, timeout=TIMEOUT, follow_redirects=False)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy(path: str, request: Request) -> Response:
    upstream_url = httpx.URL(f"{UPSTREAM_BASE}/{path}").copy_with(query=request.url.query.encode("utf-8"))
    body = await request.body()
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "accept-encoding", "connection"}
    }
    headers["host"] = UPSTREAM_HOST
    headers["x-forwarded-proto"] = "https"
    if request.client:
        forwarded = headers.get("x-forwarded-for")
        headers["x-forwarded-for"] = f"{forwarded}, {request.client.host}" if forwarded else request.client.host
    upstream = await client.request(
        request.method,
        upstream_url,
        content=body,
        headers=headers,
    )
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in {"content-encoding", "transfer-encoding", "connection"}
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)
