"""Bounded worker command: ``python -m app.worker --once``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from app.core.config import get_settings
from app.jobs_outbox import PostgreSQLJobStore, sitrep_handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one leased outbox job")
    parser.add_argument("--once", action="store_true", help="claim at most one job")
    parser.add_argument("--tenant", default="org_demo")
    parser.add_argument("--workspace", default="evt_demo")
    args = parser.parse_args()
    if not args.once:
        parser.error("--once is required for the bounded demo worker")
    store = PostgreSQLJobStore(get_settings().database_url)
    now = datetime.now(UTC)
    job = store.claim(args.tenant, args.workspace, "worker-demo", now)
    if job is None:
        print("no queued jobs")
        return
    try:
        sitrep_handler(job)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(store.finish(job["id"], "worker-demo", now, type(exc).__name__))
        return
    print(store.finish(job["id"], "worker-demo", now))


if __name__ == "__main__":
    main()
