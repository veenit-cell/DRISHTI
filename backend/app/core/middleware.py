import json
import logging
import re
import time
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import Problem

_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp, max_length: int = 128) -> None:
        self.app = app
        self.max_length = max_length

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_value = headers.get(b"x-correlation-id")
        value = raw_value.decode("ascii", errors="ignore") if raw_value else uuid4().hex
        if (
            not value
            or len(value) > self.max_length
            or _CORRELATION_PATTERN.fullmatch(value) is None
        ):
            problem = Problem(
                type="https://ev2.local/problems/invalid-correlation-id",
                title="Invalid correlation identifier",
                status=400,
                code="INVALID_CORRELATION_ID",
                detail="X-Correlation-ID must be bounded printable identifier text.",
                correlation_id="rejected",
            )
            body = problem.model_dump_json().encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"x-correlation-id", b"rejected"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        scope.setdefault("state", {})["correlation_id"] = value

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable_headers = list(message.get("headers", []))
                mutable_headers.append((b"x-correlation-id", value.encode("ascii")))
                message["headers"] = mutable_headers
            await send(message)

        await self.app(scope, receive, send_with_correlation)


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int = 1_000_000) -> None:
        self.app, self.max_body_bytes = app, max_body_bytes
        self.logger = logging.getLogger("drishti.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        size = int(headers.get(b"content-length", b"0") or 0)
        if size > self.max_body_bytes:
            body = json.dumps(
                {
                    "code": "REQUEST_TOO_LARGE",
                    "detail": "Request body exceeds the development limit.",
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        started = time.perf_counter()
        await self.app(scope, receive, send)
        self.logger.info(
            "request_complete",
            extra={
                "method": scope.get("method"),
                "path": scope.get("path"),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
