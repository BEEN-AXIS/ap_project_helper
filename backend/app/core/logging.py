"""Structured JSON logs with a request id. Never logs passwords, tokens or code."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid

from starlette.types import ASGIApp, Receive, Scope, Send

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_REDACT = ("password", "token", "code", "secret", "authorization", "cookie", "ticket")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id.get(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            for k, v in extra.items():
                out[k] = "[redacted]" if any(r in k.lower() for r in _REDACT) else v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root.handlers = [h]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel("WARNING")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("algoarena.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = uuid.uuid4().hex[:12]
        token = request_id.set(rid)
        start = time.perf_counter()
        status = 0

        async def _send(message):  # type: ignore[no-untyped-def]
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            if scope.get("path", "").startswith("/api"):
                self.log.info(
                    "request",
                    extra={"fields": {"method": scope.get("method"), "path": scope.get("path"), "status": status,
                                      "ms": round((time.perf_counter() - start) * 1000, 1)}},
                )
            request_id.reset(token)
