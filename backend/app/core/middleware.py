"""Request safety middleware."""
# ruff: noqa: E501

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
            problem = Problem(
                type="https://ev2.local/problems/request-too-large",
                title="Request body too large",
                status=413,
                code="REQUEST_TOO_LARGE",
                detail="Request body exceeds the development limit.",
                correlation_id=scope.get("state", {}).get("correlation_id", "unavailable"),
            )
            body = problem.model_dump_json().encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        started = time.perf_counter()
        status = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message.get("status", 500))
            await send(message)

        await self.app(scope, receive, send_with_status)
        app = scope.get("app")
        telemetry = getattr(getattr(app, "state", None), "telemetry", None)
        if telemetry is not None:
            telemetry.request("http", status, started)
            if scope.get("method") not in {"GET", "HEAD", "OPTIONS"} and status >= 400:
                telemetry.increment("failed_writes")
            if status == 409 and b"idempotency-key" in headers:
                telemetry.increment("duplicate_retries")
        correlation_id = scope.get("state", {}).get("correlation_id", "unavailable")
        self.logger.info(
            "request_complete",
            extra={
                "event": "request_complete",
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "correlation_id": correlation_id,
            },
        )


class SecurityHeadersMiddleware:
    """Add conservative browser security headers without changing API payloads."""

    def __init__(self, app: ASGIApp, production: bool = False) -> None:
        self.app, self.production = app, production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {key.lower() for key, _value in message.get("headers", [])}
                security_headers = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(), geolocation=(), microphone=()"),
                ]
                if self.production:
                    security_headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                message["headers"] = list(message.get("headers", [])) + [
                    item for item in security_headers if item[0] not in existing
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)


class IdentityRateLimitMiddleware:
    """Small one-process fixed-window limiter; identity values are never logged."""

    def __init__(self, app: ASGIApp, limit: int = 60, window_seconds: int = 60) -> None:
        self.app, self.limit, self.window_seconds = app, limit, window_seconds
        self._counters: dict[tuple[str, int], int] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        identity = headers.get(b"x-dev-identity", b"bearer").decode("ascii", errors="ignore") or "anonymous"
        bucket = int(time.time() // self.window_seconds)
        key = (identity, bucket)
        self._counters[key] = self._counters.get(key, 0) + 1
        if self._counters[key] > self.limit:
            problem = Problem(
                type="https://ev2.local/problems/rate-limited",
                title="Request rate limited",
                status=429,
                code="RATE_LIMITED",
                detail="Request limit exceeded; retry shortly.",
                correlation_id=scope.get("state", {}).get("correlation_id", "unavailable"),
                retryable=True,
            )
            body = problem.model_dump_json().encode()
            await send({"type": "http.response.start", "status": 429, "headers": [(b"content-type", b"application/problem+json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
