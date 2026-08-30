# ruff: noqa: E501

from datetime import UTC, datetime, timedelta

import pytest

from app.jobs_outbox import InMemoryJobStore

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def enqueue(store, key="sitrep-1", fail=False):
    def write(domain):
        domain.append({"id": "domain-1"})
        if fail:
            raise RuntimeError("rollback")
    return store.enqueue_atomic(write, {"type": "domain.changed"}, "sitrep", {"shelter": "demo"}, NOW, key)


def test_atomic_rollback_and_worker_idempotency():
    store = InMemoryJobStore()
    with pytest.raises(RuntimeError):
        enqueue(store, "bad", True)
    assert not store.domain and not store.events and not store.jobs
    enqueue(store)
    calls = []
    first = store.run_once("w1", NOW, lambda job: calls.append(job["id"]))
    assert first["status"] == "succeeded" and len(calls) == 1
    enqueue(store, "sitrep-2")
    second = store.run_once("w1", NOW, lambda job: calls.append(job["id"]))
    assert second["status"] == "succeeded"


def test_lease_reclaim_retry_limit_and_terminal_visibility():
    store = InMemoryJobStore()
    enqueue(store)
    store.claim("dead-worker", NOW)
    assert store.claim("other", NOW) is None
    reclaimed = store.claim("other", NOW + timedelta(seconds=31))
    assert reclaimed and reclaimed["attempt_count"] == 2
    store.fail(reclaimed["id"], "other", NOW, "temporary")
    retry = store.claim("other", NOW + timedelta(seconds=2))
    terminal = store.fail(retry["id"], "other", NOW + timedelta(seconds=2), "permanent", retryable=False)
    assert terminal["status"] == "dead" and store.backlog(NOW)[0]["age_seconds"] >= 0
