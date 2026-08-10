"""One call that installs every cross-cutting API behaviour.

The middleware and the exception handlers are not independent: the middleware
must be given `render_unhandled`, or unhandled exceptions fall through to
Starlette's `ServerErrorMiddleware` — outside the request-id context — and the
500 that results reports an identifier matching neither the log nor any header.

Wiring them at two call sites means the next application that mounts this API
(a test harness, a second entrypoint) can get one and not the other, and the gap
shows up only on the 500 path, which is the path nobody exercises by hand. So
there is one function, and it is the only supported way to install this.
"""

from __future__ import annotations

from fastapi import FastAPI

from gateway.app.api.errors import install_error_handlers, render_unhandled
from gateway.app.api.request_context import RequestContextMiddleware


def install_api_conventions(app: FastAPI) -> None:
    """Install the error envelope, the request id, and their shared plumbing.

    Both pieces are application-wide because Starlette and FastAPI offer no
    per-router hook. Scope is decided at request time by
    `gateway/app/api/scope.py`: the error handlers re-delegate anything outside
    `/api` to the framework default, so `POST /mcp` keeps the JSON-RPC error
    shape ChatGPT's client expects.

    The middleware itself does not scope — it stamps `X-Request-Id` on every
    response it returns, including `/mcp`, `/metrics` and `/oauth/*`, because a
    request id is worth having whatever the request was. The one exception is an
    unhandled exception on a non-contract path: there the middleware re-raises
    rather than building a response, so Starlette answers and no header is set.

    **Call this last.** `add_middleware` inserts at index 0, so whatever is added
    afterwards wraps this one — and a failure inside that outer middleware
    bypasses the envelope entirely, answering a contract path with plain text and
    no request id. If this application ever needs another middleware, it must be
    registered *before* this call.
    """
    app.add_middleware(RequestContextMiddleware, on_unhandled=render_unhandled)
    install_error_handlers(app)
