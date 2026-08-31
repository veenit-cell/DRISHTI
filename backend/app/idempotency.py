"""Scoped idempotency coordination for write endpoints without store-native replay."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from threading import RLock
from typing import Any, Awaitable, Callable

import psycopg
from psycopg.types.json import Jsonb

from app.core.context import RequestContext
from app.operations import IdempotencyConflictError


def request_hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyCoordinator:
    """Serialize and replay one logical write per tenant/workspace/key.

    PostgreSQL deployments use the existing durable idempotency_records table and
    a transaction advisory lock. The in-memory adapter uses the same contract
    with a process-local lock for deterministic tests and local development.
    """

    def __init__(self, database_url: str | None = None, ttl: timedelta = timedelta(days=1)) -> None:
        self.database_url = database_url
        self.ttl = ttl
        self._lock = RLock()
        self._records: dict[tuple[str, str, str], tuple[str, Any, datetime]] = {}

    def execute(
        self,
        context: RequestContext,
        key: str,
        payload: Any,
        action: Callable[[], Any],
        now: datetime,
    ) -> Any:
        if self.database_url:
            return self._execute_postgres(context, key, payload, action, now)
        return self._execute_memory(context, key, payload, action, now)

    async def execute_async(
        self,
        context: RequestContext,
        key: str,
        payload: Any,
        action: Callable[[], Awaitable[Any]],
        now: datetime,
    ) -> Any:
        """Async counterpart for writes whose adapter must be awaited."""
        if self.database_url:
            return await self._execute_postgres_async(context, key, payload, action, now)
        identity = (context.tenant_id, context.workspace_id, key)
        digest = request_hash(payload)
        with self._lock:
            existing = self._records.get(identity)
            if existing and existing[2] > now:
                if existing[0] != digest:
                    raise IdempotencyConflictError
                return copy.deepcopy(existing[1])
            if existing:
                self._records.pop(identity, None)
            result = await action()
            self._records[identity] = (digest, copy.deepcopy(result), now + self.ttl)
            return result

    def _execute_memory(
        self,
        context: RequestContext,
        key: str,
        payload: Any,
        action: Callable[[], Any],
        now: datetime,
    ) -> Any:
        identity = (context.tenant_id, context.workspace_id, key)
        digest = request_hash(payload)
        with self._lock:
            existing = self._records.get(identity)
            if existing and existing[2] > now:
                if existing[0] != digest:
                    raise IdempotencyConflictError
                return copy.deepcopy(existing[1])
            if existing:
                self._records.pop(identity, None)
            result = action()
            self._records[identity] = (digest, copy.deepcopy(result), now + self.ttl)
            return result

    def _execute_postgres(
        self,
        context: RequestContext,
        key: str,
        payload: Any,
        action: Callable[[], Any],
        now: datetime,
    ) -> Any:
        digest = request_hash(payload)
        lock_key = f"{context.tenant_id}:{context.workspace_id}:{key}"
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
            cursor.execute(
                "DELETE FROM idempotency_records WHERE organization_id=%s AND workspace_id=%s AND idempotency_key=%s AND expires_at <= %s",
                (context.tenant_id, context.workspace_id, key, now),
            )
            cursor.execute(
                "SELECT request_hash, response_body FROM idempotency_records WHERE organization_id=%s AND workspace_id=%s AND idempotency_key=%s",
                (context.tenant_id, context.workspace_id, key),
            )
            existing = cursor.fetchone()
            if existing:
                if existing[0] != digest:
                    raise IdempotencyConflictError
                return existing[1]
            result = action()
            cursor.execute(
                "INSERT INTO idempotency_records (organization_id, workspace_id, idempotency_key, request_hash, response_status, response_body, created_at, expires_at) VALUES (%s,%s,%s,%s,200,%s,%s,%s)",
                (
                    context.tenant_id,
                    context.workspace_id,
                    key,
                    digest,
                    Jsonb(result),
                    now,
                    now + self.ttl,
                ),
            )
            return result

    async def _execute_postgres_async(
        self,
        context: RequestContext,
        key: str,
        payload: Any,
        action: Callable[[], Awaitable[Any]],
        now: datetime,
    ) -> Any:
        digest = request_hash(payload)
        lock_key = f"{context.tenant_id}:{context.workspace_id}:{key}"
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (lock_key,))
            cursor.execute(
                "DELETE FROM idempotency_records WHERE organization_id=%s AND workspace_id=%s AND idempotency_key=%s AND expires_at <= %s",
                (context.tenant_id, context.workspace_id, key, now),
            )
            cursor.execute(
                "SELECT request_hash, response_body FROM idempotency_records WHERE organization_id=%s AND workspace_id=%s AND idempotency_key=%s",
                (context.tenant_id, context.workspace_id, key),
            )
            existing = cursor.fetchone()
            if existing:
                if existing[0] != digest:
                    raise IdempotencyConflictError
                return existing[1]
            result = await action()
            cursor.execute(
                "INSERT INTO idempotency_records (organization_id, workspace_id, idempotency_key, request_hash, response_status, response_body, created_at, expires_at) VALUES (%s,%s,%s,%s,200,%s,%s,%s)",
                (context.tenant_id, context.workspace_id, key, digest, Jsonb(result), now, now + self.ttl),
            )
            return result
