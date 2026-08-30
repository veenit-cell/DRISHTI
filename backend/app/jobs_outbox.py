"""Transactional outbox/job primitives with a bounded single-process worker."""
# ruff: noqa: E501, E701, UP038

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

import psycopg

MAX_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 60
JobStatus = Literal["queued", "leased", "succeeded", "failed", "dead"]


class JobStore:
    def enqueue_atomic(self, domain_write: Callable[[dict[str, Any]], None], event: dict[str, Any], job_type: str, payload: dict[str, Any], now: datetime, handler_key: str, max_attempts: int = MAX_ATTEMPTS) -> dict[str, Any]:
        raise NotImplementedError


class InMemoryJobStore(JobStore):
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.domain: list[dict[str, Any]] = []
        self.handled: set[str] = set()
        self.lock = Lock()

    def enqueue_atomic(self, domain_write, event, job_type, payload, now, handler_key, max_attempts=MAX_ATTEMPTS):
        with self.lock:
            domain_before, events_before = copy.deepcopy(self.domain), copy.deepcopy(self.events)
            try:
                domain_write(self.domain)
                self.events.append(copy.deepcopy(event))
                job = {"id": f"job_{uuid4().hex}", "job_type": job_type, "payload": copy.deepcopy(payload), "status": "queued", "available_at": now, "lease_owner": None, "leased_until": None, "attempt_count": 0, "max_attempts": max_attempts, "last_error_code": None, "handler_key": handler_key, "created_at": now, "updated_at": now}
                self.jobs[job["id"]] = job
                return copy.deepcopy(job)
            except Exception:
                self.domain, self.events = domain_before, events_before
                raise

    def claim(self, worker_id: str, now: datetime, lease_seconds: int = 30) -> dict[str, Any] | None:
        with self.lock:
            candidates = [job for job in self.jobs.values() if job["status"] == "queued" and job["available_at"] <= now or job["status"] == "leased" and job["leased_until"] and job["leased_until"] <= now]
            job = min(candidates, key=lambda item: (item["available_at"], item["id"]), default=None)
            if job is None:
                return None
            job["status"], job["lease_owner"], job["leased_until"] = "leased", worker_id, now + timedelta(seconds=lease_seconds)
            job["attempt_count"] += 1
            job["updated_at"] = now
            return copy.deepcopy(job)

    def succeed(self, job_id: str, worker_id: str, now: datetime) -> dict[str, Any]:
        with self.lock:
            job = self.jobs[job_id]
            if job["lease_owner"] != worker_id: raise ValueError("lease owner mismatch")
            job.update(status="succeeded", leased_until=None, updated_at=now)
            return copy.deepcopy(job)

    def fail(self, job_id: str, worker_id: str, now: datetime, error_code: str, retryable: bool = True) -> dict[str, Any]:
        with self.lock:
            job = self.jobs[job_id]
            if job["lease_owner"] != worker_id: raise ValueError("lease owner mismatch")
            terminal = not retryable or job["attempt_count"] >= job["max_attempts"]
            delay = min(MAX_BACKOFF_SECONDS, 2 ** max(0, job["attempt_count"] - 1))
            job.update(status="dead" if terminal else "queued", leased_until=None, available_at=now if terminal else now + timedelta(seconds=delay), last_error_code=error_code, updated_at=now)
            return copy.deepcopy(job)

    def run_once(self, worker_id: str, now: datetime, handler: Callable[[dict[str, Any]], None]) -> dict[str, Any] | None:
        job = self.claim(worker_id, now)
        if not job: return None
        try:
            if job["handler_key"] in self.handled:
                return self.succeed(job["id"], worker_id, now)
            handler(job)
            self.handled.add(job["handler_key"])
            return self.succeed(job["id"], worker_id, now)
        except Exception as exc:
            return self.fail(job["id"], worker_id, now, type(exc).__name__, retryable=True)

    def backlog(self, now: datetime) -> list[dict[str, Any]]:
        with self.lock:
            return [{"id": j["id"], "status": j["status"], "age_seconds": max(0, int((now - j["created_at"]).total_seconds())), "attempt_count": j["attempt_count"], "last_error_code": j["last_error_code"]} for j in sorted(self.jobs.values(), key=lambda item: item["created_at"]) if j["status"] in {"queued", "leased", "failed", "dead"}]


class PostgreSQLJobStore(JobStore):
    """PostgreSQL adapter; callers supply a transaction-local domain write callback."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def enqueue_atomic(self, domain_write, event, job_type, payload, now, handler_key, max_attempts=MAX_ATTEMPTS):
        job_id = f"job_{uuid4().hex}"
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            domain_write(cursor)
            cursor.execute("INSERT INTO outbox_events (id, organization_id, workspace_id, event_type, aggregate_type, aggregate_id, aggregate_revision, envelope, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (event["id"], event["organization_id"], event["workspace_id"], event["event_type"], event.get("aggregate_type", "domain"), event.get("aggregate_id", event["id"]), event.get("aggregate_revision", 1), json.dumps(event), now))
            cursor.execute("INSERT INTO jobs (id, organization_id, workspace_id, job_type, payload, status, available_at, attempt_count, max_attempts, handler_key, created_at, updated_at) VALUES (%s,%s,%s,%s,%s,'queued',%s,0,%s,%s,%s,%s)", (job_id, event["organization_id"], event["workspace_id"], job_type, json.dumps(payload), now, max_attempts, handler_key, now, now))
        return {"id": job_id, "status": "queued", "handler_key": handler_key}

    def claim(self, tenant_id: str, workspace_id: str, worker_id: str, now: datetime, lease_seconds: int = 30) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, job_type, payload, attempt_count, max_attempts, handler_key FROM jobs WHERE organization_id=%s AND workspace_id=%s AND ((status='queued' AND available_at<=%s) OR (status='leased' AND leased_until<=%s)) ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1", (tenant_id, workspace_id, now, now))
            row = cursor.fetchone()
            if row is None: return None
            cursor.execute("UPDATE jobs SET status='leased', lease_owner=%s, leased_until=%s, attempt_count=attempt_count+1, updated_at=%s WHERE id=%s", (worker_id, now + timedelta(seconds=lease_seconds), now, row[0]))
            return {"id": str(row[0]), "job_type": row[1], "payload": row[2], "attempt_count": row[3] + 1, "max_attempts": row[4], "handler_key": row[5]}

    def finish(self, job_id: str, worker_id: str, now: datetime, error_code: str | None = None, retryable: bool = True) -> str:
        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT attempt_count,max_attempts,lease_owner FROM jobs WHERE id=%s FOR UPDATE", (job_id,))
            row = cursor.fetchone()
            if row is None or row[2] != worker_id: raise ValueError("lease owner mismatch")
            if error_code is None: status, available = "succeeded", now
            else:
                terminal = not retryable or row[0] >= row[1]
                status, available = ("dead", now) if terminal else ("queued", now + timedelta(seconds=min(MAX_BACKOFF_SECONDS, 2 ** max(0, row[0] - 1))))
            cursor.execute("UPDATE jobs SET status=%s,available_at=%s,leased_until=NULL,last_error_code=%s,updated_at=%s WHERE id=%s", (status, available, error_code, now, job_id))
            return status


def sitrep_handler(job: dict[str, Any]) -> str:
    """Useful bounded handler: deterministic synthetic SITREP export text."""
    return json.dumps({"job_id": job["id"], "type": "synthetic_sitrep", "payload": job["payload"]}, sort_keys=True)
