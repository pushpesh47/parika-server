"""
PARIKA API - Error Handling

Implements the single, centralized error-mapping table: every Core
exception (raised, unmodified, by an existing Core component) is
translated into a uniform JSON error envelope and an appropriate HTTP
status code, without any per-endpoint try/except boilerplate and
without changing a single Core exception's definition, message, or
hierarchy.

Classification deliberately uses the exception's *class name*, not an
explicit `isinstance()` import list against every Core exception
module -- this keeps the API layer decoupled from the exact import
path of every Core component's `exceptions.py`, while still
implementing the documented mapping table. Adding a new Core
component's `*NotFoundError` (for example) therefore requires zero
changes here.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from parika.core.router.exceptions import DispatchError

_NAME_SUFFIX_STATUS: tuple[tuple[str, int], ...] = (
    ("NotFoundError", status.HTTP_404_NOT_FOUND),
    ("AlreadyRegisteredError", status.HTTP_409_CONFLICT),
    ("AlreadyLoadedError", status.HTTP_409_CONFLICT),
    ("AlreadyExistsError", status.HTTP_409_CONFLICT),
    ("PermissionError", status.HTTP_403_FORBIDDEN),
    ("PermissionDeniedError", status.HTTP_403_FORBIDDEN),
    ("InvalidCredentialsError", status.HTTP_401_UNAUTHORIZED),
    ("ExpiredTokenError", status.HTTP_401_UNAUTHORIZED),
    ("MissingCredentialsError", status.HTTP_401_UNAUTHORIZED),
    ("UnauthorizedError", status.HTTP_401_UNAUTHORIZED),
    ("DisabledError", status.HTTP_409_CONFLICT),
    ("NotLoadedError", status.HTTP_409_CONFLICT),
    ("InvalidError", status.HTTP_400_BAD_REQUEST),
    ("InvalidRequestError", status.HTTP_400_BAD_REQUEST),
    # Additive entry for Expense Management's match-based update/
    # delete (see `parika/tools/expense/exceptions.py`
    # ExpenseAmbiguousMatchError): more than one record matched a
    # description-based request and nothing was changed/removed - a
    # conflict the caller must resolve, not a server failure.
    ("AmbiguousMatchError", status.HTTP_409_CONFLICT),
)


def _status_for_exception(exc: BaseException) -> int:
    """
    Classify an exception into an HTTP status code using the
    documented suffix-matching table.

    `NotImplementedError` (e.g. `WorkflowEngine.execute()`, a
    pre-existing, tracked, out-of-scope gap -- see the design's gap
    G10) always maps to 501, regardless of class name.

    Falls back to 500 for anything unrecognized.
    """

    if isinstance(exc, NotImplementedError):
        return status.HTTP_501_NOT_IMPLEMENTED

    exception_name = type(exc).__name__

    for suffix, http_status in _NAME_SUFFIX_STATUS:
        if exception_name.endswith(suffix):
            return http_status

    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _unwrap(exc: BaseException) -> BaseException:
    """
    Unwrap a `DispatchError` (raised by `Router.dispatch()` around
    every handler exception, per its own documented contract) to
    recover the *original* exception's type for classification,
    without ever changing `Router`'s own behavior.

    `Router.dispatch()` always sets `__cause__` via `raise ... from
    ex` (see `parika/core/router/router.py`), so the original
    exception is never lost -- only wrapped for `Router`'s own
    generic dispatch-failure reporting.
    """

    if isinstance(exc, DispatchError) and exc.__cause__ is not None:
        return exc.__cause__

    return exc


def build_error_envelope(exc: BaseException, *, request_id: str | None = None) -> dict[str, Any]:
    """
    Build the uniform JSON error envelope described in
    `register_exception_handlers()`'s handlers, below.
    """

    original = _unwrap(exc)

    return {
        "error": {
            "type": type(original).__name__,
            "message": str(original) or HTTPStatus(_status_for_exception(original)).phrase,
            "request_id": request_id or uuid4().hex,
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register the centralized exception handlers on `app`.

    This is the *only* place error-to-HTTP-status mapping happens;
    individual routers/handlers never need their own try/except
    blocks for Core exceptions.
    """

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "type": "RequestValidationError",
                    "message": str(exc),
                    "request_id": uuid4().hex,
                }
            },
        )

    @app.exception_handler(Exception)
    async def _handle_generic_exception(request: Request, exc: Exception) -> JSONResponse:
        original = _unwrap(exc)
        http_status = _status_for_exception(original)

        return JSONResponse(
            status_code=http_status,
            content=build_error_envelope(exc),
        )
