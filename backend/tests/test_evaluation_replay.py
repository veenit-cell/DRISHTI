# ruff: noqa: E501

from datetime import datetime

from app.evaluation_replay import REPLAY_AT, records, run_replay


def test_replay_is_deterministic_and_hides_future_records() -> None:
    first, second = run_replay(), run_replay()
    assert first["result_hash"] == second["result_hash"]
    assert first["record_count"] == 120
    assert first["future_records_excluded"] == 1
    assert all(datetime.fromisoformat(row["event_time"]) <= REPLAY_AT for row in records() if row["id"] != "future-001")


def test_replay_contains_required_signals_and_lifecycle() -> None:
    result = run_replay()
    assert result["synthetic"] is True
    assert result["dependency_inputs"]["influx"] == 180
    assert result["ablation"]["removed"] == ["dependency_reasoning", "verification_value"]
    assert result["lifecycle"][-1] == "audit_verified"
    assert result["dependency_aware"]["infeasible_assignments"] == 0
