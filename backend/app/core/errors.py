"""One error envelope for every failure: {"error": {"code", "message", "details"}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_STATUS = {
    "unauthorized": 401,
    "forbidden": 403,
    "not_found": 404,
    "validation": 422,
    "rate_limited": 429,
    "busy": 409,
    "not_in_hand": 409,
    "match_not_live": 409,
    "cooldown": 429,
    "code_too_large": 413,
    "empty_code": 422,
    "no_charges": 409,
    "conflict": 409,
    "server_error": 500,
}


class AppError(Exception):
    def __init__(self, code: str, message: str = "", details: dict[str, Any] | None = None, status: int | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code.replace("_", " ")
        self.details = details or {}
        self.status = status or ERROR_STATUS.get(code, 400)


class RuleError(AppError):
    """A command the match actor rejected: no state change, nothing broadcast."""


def envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError) -> JSONResponse:
        headers = {}
        if "retry_after" in exc.details:
            headers["Retry-After"] = str(max(1, int(exc.details["retry_after"] + 0.999)))
        return JSONResponse(envelope(exc.code, exc.message, exc.details), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errs = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(envelope("validation", "Invalid request", {"errors": errs}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "not_found", 413: "code_too_large", 429: "rate_limited"}.get(
            exc.status_code, "server_error" if exc.status_code >= 500 else "validation"
        )
        return JSONResponse(envelope(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_req: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        import logging

        logging.getLogger("algoarena").exception("unhandled error", exc_info=exc)
        return JSONResponse(envelope("server_error", "Something went wrong"), status_code=500)
