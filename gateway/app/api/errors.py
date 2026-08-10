"""The one error envelope every contract endpoint returns.

`docs/api/codex-bridge.openapi.yaml` states that an endpoint returning anything
other than `Error` on a non-2xx response is a contract violation, not a variant.
This module is what makes that true for the failures no handler writes by hand:
request validation, unhandled exceptions, and the `HTTPException`s raised deep
inside dependencies.

Handlers are installed application-wide because FastAPI has no per-router
exception handling, but each one checks `is_contract_path` first and re-delegates
anything else to the framework default. That keeps `POST /mcp` speaking JSON-RPC.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exception_handlers import (
    http_exception_handler as default_http_exception_handler,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as default_validation_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway.app.api.request_context import current_request_id
from gateway.app.api.scope import is_contract_path


logger = logging.getLogger(__name__)


# `code` values in components.schemas.ErrorCode. Kept as constants so a typo is
# an ImportError rather than a response that validates against nothing.
VALIDATION_FAILED = "validation_failed"
UNAUTHENTICATED = "unauthenticated"
TOKEN_EXPIRED = "token_expired"
PERMISSION_DENIED = "permission_denied"
NOT_FOUND = "not_found"
CONFLICT = "conflict"
STALE_WRITE = "stale_write"
RATE_LIMITED = "rate_limited"
DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
INTERNAL_ERROR = "internal_error"

# Whether repeating the identical request may succeed without the caller
# changing anything. This is a property of the failure, so it belongs in one
# table rather than at each raise site where it would drift.
RETRYABLE_CODES = frozenset({RATE_LIMITED, DEPENDENCY_UNAVAILABLE, INTERNAL_ERROR})

_STATUS_TO_CODE = {
    400: VALIDATION_FAILED,
    401: UNAUTHENTICATED,
    403: PERMISSION_DENIED,
    404: NOT_FOUND,
    405: VALIDATION_FAILED,
    409: CONFLICT,
    412: STALE_WRITE,
    422: VALIDATION_FAILED,
    429: RATE_LIMITED,
    503: DEPENDENCY_UNAVAILABLE,
}


def code_for_status(status_code: int) -> str:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    return INTERNAL_ERROR if status_code >= 500 else VALIDATION_FAILED


class ApiError(Exception):
    """A failure that already knows its contract representation.

    Raise this instead of `HTTPException` inside `/api` handlers: it carries the
    `code` the client branches on, which an HTTP status alone cannot express
    (404 is `not_found`, but 409 could be `conflict` or `stale_write`).
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: list[dict] | None = None,
        retryable: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.retryable = code in RETRYABLE_CODES if retryable is None else retryable
        self.headers = headers or {}


def error_body(
    *,
    code: str,
    message: str,
    details: list[dict] | None = None,
    retryable: bool | None = None,
) -> dict:
    """Build the `Error` envelope. The single place its shape is decided."""
    body: dict = {
        "code": code,
        "message": message,
        "requestId": current_request_id(),
        "retryable": code in RETRYABLE_CODES if retryable is None else retryable,
    }
    if details:
        body["details"] = details
    return body


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict] | None = None,
    retryable: bool | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_body(code=code, message=message, details=details, retryable=retryable),
        headers=headers or {},
    )


def _validation_details(exc: RequestValidationError) -> list[dict]:
    details = []
    for error in exc.errors():
        location = error.get("loc") or ()
        # Skip the leading "body"/"query" marker so the pointer reads like the
        # JSON Pointer the contract documents.
        parts = [str(part) for part in location[1:]] or [str(part) for part in location]
        details.append(
            {
                "field": "/" + "/".join(parts) if parts else None,
                "code": str(error.get("type") or "invalid"),
                "message": str(error.get("msg") or "invalid value"),
            }
        )
    return [{k: v for k, v in detail.items() if v is not None} for detail in details]


def render_unhandled(request: Request, exc: BaseException) -> Response | None:
    """Log an unhandled exception and render it as `internal_error`.

    Returns None for a request outside the contract surface, which tells the
    caller to let the framework handle it — that is what keeps `POST /mcp`
    behaving as it does today.

    Called by `RequestContextMiddleware`, not by an `@app.exception_handler`,
    because Starlette invokes those from `ServerErrorMiddleware` — outside every
    user middleware, and therefore after the request-id context is gone.
    """
    if not is_contract_path(request.url.path):
        # Nothing is logged here on purpose. Re-raising hands the exception back
        # to Starlette's ServerErrorMiddleware, which logs its own traceback —
        # logging first produced two full tracebacks for one failure, doubling
        # the noise on the transport where volume is highest.
        return None
    # The traceback goes to the log, never to the client: raw driver errors leak
    # schema, filesystem paths and sometimes credentials. The client gets the
    # requestId, and it is the *same* id as this log line's.
    logger.error(
        "unhandled_exception",
        exc_info=exc,
        extra={"correlation_id": current_request_id(), "task_id": None, "executor_id": None},
    )
    return error_response(
        status_code=500,
        code=INTERNAL_ERROR,
        message="Unexpected server error. Report the requestId to the operator.",
    )


def install_error_handlers(app: FastAPI) -> None:
    """Route contract-path failures through the envelope, leave the rest alone.

    `_validation_error`, `_http_error` and `_unhandled` each check
    `is_contract_path` and re-delegate anything else to the framework default.
    `_api_error` does not, and does not need to: `ApiError` is defined by this
    package and is only ever raised by contract-path code, so an `ApiError`
    outside `/api` is a bug in the raiser, not a request to reshape.
    """

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> Response:
        return error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            retryable=exc.retryable,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        if not is_contract_path(request.url.path):
            return await default_validation_handler(request, exc)
        return error_response(
            status_code=422,
            code=VALIDATION_FAILED,
            message="Request failed validation.",
            details=_validation_details(exc),
        )

    # Registered against Starlette's class, not FastAPI's subclass. Starlette
    # looks handlers up by walking the raised exception's MRO, so a handler keyed
    # on the subclass never catches the parent — and the parent is what the
    # router itself raises for an unmatched path (404) or a wrong method (405).
    # Keyed on `fastapi.HTTPException`, every mistyped `/api/...` URL returned
    # `{"detail": "Not Found"}`: the envelope covered hand-raised failures and
    # silently missed the most common client mistake there is.
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if not is_contract_path(request.url.path):
            return await default_http_exception_handler(request, exc)
        return error_response(
            status_code=exc.status_code,
            code=code_for_status(exc.status_code),
            message=str(exc.detail),
            headers=dict(exc.headers or {}),
        )

    # No `@app.exception_handler(Exception)` is installed, deliberately.
    # Unhandled exceptions are rendered by `RequestContextMiddleware`, which runs
    # inside `ServerErrorMiddleware` and therefore still has the request id in
    # context. A handler here would also break the non-contract path: re-raising
    # from inside `ServerErrorMiddleware`'s own handler call leaves it past the
    # `response_started` check, so `POST /mcp` answered 500 with an empty body
    # instead of the framework default.
