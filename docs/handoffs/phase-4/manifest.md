# Phase 4 Handoff — Deterministic Decision Loop

Implemented a fixed synthetic replay scenario and one explainable recommendation rule (`water_attention_v1`). The rule triggers on short potable-water runway, elevated contamination, and incoming population; it returns reasons and only ready `water_team` resources.

APIs: `POST /api/v1/decision-loop/demo/replay` resets/replays the fixed scenario and operations state; `GET /api/v1/decision-loop/scenario` reads it; `POST /api/v1/decision-loop/recommendations` evaluates the rule; `POST /api/v1/decision-loop/recommendations/{id}/decision` records commander `approve` or `reject`.

Approval is explicit and never auto-dispatches or creates a task. The complete demo-path test proves replay, explainability, compatible-resource filtering, approval, and no automatic task creation. ML, solver optimization, WebSockets, and full offline synchronization remain deferred.
