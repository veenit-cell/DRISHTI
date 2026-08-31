from app.dependencies import (
    InfraDependency,
    InfraNode,
    compute_downstream_impact,
    compute_unlock_value,
    validate_dag,
)


def nodes(*states):
    return [
        InfraNode(node_id=node_id, node_type=node_type, name=node_id, state=state, capacity=None)
        for node_id, node_type, state in states
    ]


def edge(upstream, downstream):
    return InfraDependency(
        upstream_id=upstream, downstream_id=downstream, dependency_type="requires"
    )


def test_dag_rejects_cycles():
    errors = validate_dag(
        nodes(("a", "power", "failed"), ("b", "water", "failed"), ("c", "hospital", "failed")),
        [edge("a", "b"), edge("b", "c"), edge("c", "a")],
    )
    assert "dependency graph contains a cycle" in errors


def test_downstream_impact_counts_correctly():
    result = compute_downstream_impact(
        "power",
        nodes(
            ("power", "power", "failed"),
            ("hospital", "hospital", "degraded"),
            ("med", "other", "failed"),
        ),
        [edge("power", "hospital"), edge("hospital", "med")],
    )
    assert result == ["hospital", "med"]


def test_unlock_value_requires_dependency_edge():
    infra = nodes(("generator", "power", "failed"), ("hospital", "hospital", "degraded"))
    mission = [
        {"mission_id": "medical-team", "required_infrastructure": ["hospital"], "urgency_weight": 2}
    ]
    without_edge = compute_unlock_value("generator", infra, [], mission)
    with_edge = compute_unlock_value("generator", infra, [edge("generator", "hospital")], mission)
    assert without_edge.missions_unlocked == []
    assert with_edge.missions_unlocked == ["medical-team"]
    assert with_edge.mission_unlock_value == 2


def test_unlock_value_changes_ranking_signal():
    infra = nodes(
        ("generator", "power", "failed"),
        ("hospital", "hospital", "degraded"),
        ("water", "water", "degraded"),
    )
    missions = [
        {
            "mission_id": "medical-team",
            "required_infrastructure": ["hospital"],
            "urgency_weight": 3,
        },
        {"mission_id": "water-team", "required_infrastructure": ["water"], "urgency_weight": 1},
    ]
    generator = compute_unlock_value("generator", infra, [edge("generator", "hospital")], missions)
    water = compute_unlock_value("water", infra, [], missions)
    assert generator.mission_unlock_value > water.mission_unlock_value


def test_dag_rejects_unknown_node_reference():
    errors = validate_dag(
        nodes(("power", "power", "failed")),
        [edge("power", "missing")],
    )
    assert errors == ["unknown downstream node: missing"]
