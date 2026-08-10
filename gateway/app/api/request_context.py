"""Per-request identifier, carried from the middleware to the error envelope.

Every response in this API — and every log line written while serving it —
reports the same `requestId`, so an operator handed a mobile screenshot can find
the one request that failed.

This is NOT `TaskModel.correlation_id`. That column is per *task*: it lives for
the whole lifetime of a task and is shared with the executor protocol. Filling
the envelope from it would make every failure on a given task report the same
identifier, which defeats the only reason the field exists, while the response
stayed perfectly schema-valid. The two identifiers are different things and the
contract names them differently on purpose.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Callable, Optional
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


# Renders an unhandled exception as a contract response, or returns None when
# the request is not on the contract surface. Injected rather than imported so
# this module stays free of any dependency on the error envelope.
UnhandledRenderer = Callable[[Request, BaseException], Optional[Response]]


REQUEST_ID_HEADER = "X-Request-Id"

# Same shape as `components.schemas.Id` in the contract. An inbound value that
# does not match is replaced rather than echoed: the header is written straight
# into response headers and into logs, so accepting arbitrary client bytes here
# is a header-injection and log-forging primitive.
# `fullmatch`, not `match`: with `re.match` the `$` anchor also matches just
# before a trailing newline, so "abc\n" passed this guard and was echoed
# verbatim into a response header — the one thing the guard exists to stop.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str:
    """The current request's identifier, or a fresh one outside a request.

    Never returns an empty string: the contract makes `requestId` required on
    every error, including the ones raised before any handler runs, so there is
    no code path allowed to report "unknown".
    """
    value = _request_id.get()
    if value:
        return value
    # Outside a request (a background task, a test calling directly) mint one
    # and keep it: returning a fresh uuid4() per call meant the log line and the
    # response body of the same failure reported two different identifiers.
    generated = str(uuid4())
    _request_id.set(generated)
    return generated


def set_request_id(value: str) -> None:
    _request_id.set(value)


def _accept_inbound(value: str | None) -> str:
    if value and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return str(uuid4())


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, expose it in the context, echo it in the response.

    A client-supplied `X-Request-Id` is honoured when it is well formed, so a
    mobile client can tie its own local log to the server's. Anything else gets
    a server-generated id.

    **Unhandled exceptions are rendered here, not by an `@app.exception_handler`.**
    Starlette's `ServerErrorMiddleware` — which invokes that handler — sits
    *outside* every user middleware, so by the time it runs, this middleware's
    `finally` has already reset the contextvar. A handler installed there
    produced a fresh UUID for the log line and a second, different one for the
    response body, and sent no `X-Request-Id` header at all: on exactly the
    500 an operator most needs to trace, the screenshot and the log disagreed.
    Rendering while the context is still set is what keeps them equal.
    """

    def __init__(self, app: ASGIApp, on_unhandled: UnhandledRenderer | None = None) -> None:
        super().__init__(app)
        self.on_unhandled = on_unhandled

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _accept_inbound(request.headers.get(REQUEST_ID_HEADER))
        token = _request_id.set(request_id)
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                rendered = self.on_unhandled(request, exc) if self.on_unhandled else None
                if rendered is None:
                    # Outside the contract surface there is no envelope to
                    # render: let ServerErrorMiddleware handle it exactly as it
                    # did before, so `POST /mcp` keeps its behaviour.
                    raise
                response = rendered
        finally:
            _request_id.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
