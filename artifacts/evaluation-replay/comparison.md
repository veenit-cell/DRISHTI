# Synthetic evaluation replay

This is a deterministic synthetic comparison, not real-world validation.

| Metric | Baseline / ablation | Dependency-aware |
|---|---:|---:|
| Critical failures identified before threshold | 2 | 3 |
| Infeasible assignments proposed | 1 | 0 |
| Unknown sectors surfaced | 0 | 2 |
| Explanation completeness | 0.35 | 1.0 |

Records: 120 visible, 1 future record excluded. Result hash: $(@{ablation=; baseline=; baseline_method=report_volume_plus_manual_asset_availability; dependency_aware=; dependency_inputs=; future_records_excluded=1; input_hash=d3214f761f6826a80b5201d94aee46d15fb59ef17e63a0a49995817ceaf48e58; lifecycle=System.Object[]; provenance=synthetic_evaluation_fixture; record_count=120; replay_at=2026-08-30T12:00:00+00:00; result_hash=1bccaf48fc3b74d40419a6c8aff3fcbd64f015e5c9be42d296fd1ae2f735af25; runtime_ms=1; scenario_signals=System.Object[]; synthetic=True; total_fixture_records=121; version=evaluation_replay_v1}.result_hash).
Lifecycle: commander approval â†’ acknowledgement â†’ en route â†’ completion â†’ outcome â†’ audit verification.
