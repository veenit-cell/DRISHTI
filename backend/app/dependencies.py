# ruff: noqa: E501

"""Bounded infrastructure dependency DAG and mission unlock valuation."""

from __future__ import annotations

import copy
import json
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import RequestContext

DEPENDENCY_VERSION = "dependency_dag_v1"
MAX_DEPTH = 6
NODE_TYPES = {"power", "water", "communications", "hospital", "shelter", "transport", "other"}
DEPENDENCY_TYPES = {"requires", "enhances", "degrades_without"}

# Adapter for the existing shelter evaluator.  The evaluator now consumes the
# same typed node/edge representation as the persisted infrastructure graph.
LEGACY_DEPENDENCY_NODES = [
    ("power", "other"),
    ("water_purification", "other"),
    ("medicine_cold_chain", "other"),
    ("safe_water_runway", "other"),
    ("unsafe_water", "other"),
    ("operational_disease_risk_pressure", "other"),
    ("population_pressure", "other"),
    ("medical_demand", "other"),
    ("medicine_diagnostic_pressure", "other"),
]
LEGACY_DEPENDENCY_EDGES = [
    ("power", "water_purification"),
    ("power", "medicine_cold_chain"),
    ("water_purification", "safe_water_runway"),
    ("unsafe_water", "operational_disease_risk_pressure"),
    ("population_pressure", "operational_disease_risk_pressure"),
    ("medical_demand", "medicine_diagnostic_pressure"),
]


def legacy_dependency_graph() -> dict[str, list[str]]:
    """Return the old cascade adjacency map from shared typed graph records."""
    nodes = {node_id for node_id, _ in LEGACY_DEPENDENCY_NODES}
    graph = {node_id: [] for node_id in nodes}
    for upstream, downstream in LEGACY_DEPENDENCY_EDGES:
        graph[upstream].append(downstream)
    return graph


class InfraNodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str | None = Field(
        default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$"
    )
    node_type: str = Field(
        pattern=r"^(power|water|communications|hospital|shelter|transport|other)$"
    )
    name: str = Field(min_length=1, max_length=160)
    location: dict[str, Any] | None = None
    state: str = Field(default="unknown", pattern=r"^(operational|degraded|failed|unknown)$")
    capacity: float | None = None
    evidence_ref: str | None = Field(default=None, max_length=160)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class InfraDependencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upstream_id: str
    downstream_id: str
    dependency_type: str = Field(
        default="requires", pattern=r"^(requires|enhances|degrades_without)$"
    )
    threshold: float | None = None


class InfraNode(BaseModel):
    node_id: str
    node_type: str
    name: str
    state: str
    capacity: float | None
    evidence_ref: str | None = None


class InfraDependency(BaseModel):
    upstream_id: str
    downstream_id: str
    dependency_type: str


class UnlockCandidate(BaseModel):
    action: str
    target_node_id: str
    restoration_cost: str
    downstream_nodes_unlocked: list[str]
    missions_unlocked: list[str]
    mission_unlock_value: float
    assumptions: list[str]
    evidence_refs: list[str]
    rank: int
    version: str


def validate_dag(nodes: list[InfraNode], edges: list[InfraDependency]) -> list[str]:
    """Return validation errors for unknown references, cycles, or depth overflow."""
    node_ids = {node.node_id for node in nodes}
    errors = [
        f"unknown upstream node: {edge.upstream_id}"
        for edge in edges
        if edge.upstream_id not in node_ids
    ]
    errors += [
        f"unknown downstream node: {edge.downstream_id}"
        for edge in edges
        if edge.downstream_id not in node_ids
    ]
    errors += [
        "self dependency is not allowed" for edge in edges if edge.upstream_id == edge.downstream_id
    ]
    if errors:
        return sorted(set(errors))
    graph: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        graph[edge.upstream_id].append(edge.downstream_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            errors.append(f"dependency path exceeds depth {MAX_DEPTH}")
            return
        if node_id in visiting:
            errors.append("dependency graph contains a cycle")
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in sorted(graph[node_id]):
            visit(child, depth + 1)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(node_ids):
        visit(node_id, 1)
    return sorted(set(errors))


def compute_downstream_impact(
    target_node_id: str, nodes: list[InfraNode], edges: list[InfraDependency]
) -> list[str]:
    """Return reachable downstream nodes, bounded to MAX_DEPTH and stably ordered."""
    node_ids = {node.node_id for node in nodes}
    if target_node_id not in node_ids:
        return []
    graph: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        if edge.upstream_id in node_ids and edge.downstream_id in node_ids:
            graph[edge.upstream_id].append(edge.downstream_id)
    found: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(target_node_id, 0)])
    while queue:
        current, depth = queue.popleft()
        if depth >= MAX_DEPTH:
            continue
        for child in sorted(graph[current]):
            if child not in found:
                found.add(child)
                queue.append((child, depth + 1))
    return sorted(found)


def compute_unlock_value(
    target_node_id: str,
    nodes: list[InfraNode],
    edges: list[InfraDependency],
    pending_missions: list[dict[str, Any]],
) -> UnlockCandidate:
    """Value restoration by weighted missions that become feasible afterward."""
    by_id = {node.node_id: node for node in nodes}
    downstream = compute_downstream_impact(target_node_id, nodes, edges)
    restored = {target_node_id, *downstream}
    unlocked: list[tuple[str, float]] = []
    for mission in pending_missions:
        mission_id = str(mission.get("mission_id", mission.get("id", "unknown")))
        required = [str(item) for item in mission.get("required_infrastructure", [])]
        if not required or not (set(required) & restored):
            continue
        was_feasible = all(
            by_id.get(node_id) and by_id[node_id].state == "operational" for node_id in required
        )
        after = all(
            node_id in restored or (by_id.get(node_id) and by_id[node_id].state == "operational")
            for node_id in required
        )
        if not was_feasible and after:
            unlocked.append((mission_id, float(mission.get("urgency_weight", 1.0))))
    return UnlockCandidate(
        action=f"restore_{target_node_id}",
        target_node_id=target_node_id,
        restoration_cost=str(
            by_id[target_node_id].capacity
            if target_node_id in by_id and by_id[target_node_id].capacity is not None
            else "commander assessment required"
        ),
        downstream_nodes_unlocked=downstream,
        missions_unlocked=sorted(item[0] for item in unlocked),
        mission_unlock_value=round(sum(item[1] for item in unlocked), 6),
        assumptions=sorted(node_id for node_id in restored if node_id != target_node_id),
        evidence_refs=sorted(
            {
                by_id[node_id].evidence_ref
                for node_id in restored
                if node_id in by_id and by_id[node_id].evidence_ref
            }
        ),
        rank=0,
        version=DEPENDENCY_VERSION,
    )


class DependencyStore(Protocol):
    def create_node(
        self, context: RequestContext, node: InfraNodeCreate, now: datetime
    ) -> dict[str, Any]: ...
    def list_nodes(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def create_dependency(
        self, context: RequestContext, dependency: InfraDependencyCreate, now: datetime
    ) -> dict[str, Any]: ...
    def list_dependencies(self, context: RequestContext) -> list[dict[str, Any]]: ...
    def unlock_ranking(self, context: RequestContext) -> list[dict[str, Any]]: ...


class DependencyConflictError(Exception):
    pass


def _node_model(record: dict[str, Any]) -> InfraNode:
    return InfraNode(
        node_id=record["node_id"],
        node_type=record["node_type"],
        name=record["name"],
        state=record["state"],
        capacity=record.get("capacity"),
        evidence_ref=record.get("evidence_ref"),
    )


class InMemoryDependencyStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.nodes: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.pending_missions: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def create_node(self, context, node, now):
        node_id = node.node_id or f"node_{uuid4().hex}"
        key = (context.tenant_id, context.workspace_id, node_id)
        record = {
            "node_id": node_id,
            **node.model_dump(exclude={"node_id"}),
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "created_at": now.isoformat(),
        }
        with self._lock:
            existing = self.nodes.get(key)
            if existing and existing != record:
                raise DependencyConflictError
            self.nodes[key] = existing or record
            return copy.deepcopy(self.nodes[key])

    def list_nodes(self, context):
        return [
            copy.deepcopy(item)
            for item in self.nodes.values()
            if item.get("tenant_id", context.tenant_id) == context.tenant_id
            and item.get("workspace_id", context.workspace_id) == context.workspace_id
        ]

    def create_dependency(self, context, dependency, now):
        nodes = self.list_nodes(context)
        if dependency.upstream_id not in {
            node["node_id"] for node in nodes
        } or dependency.downstream_id not in {node["node_id"] for node in nodes}:
            raise DependencyConflictError("dependency references unknown node")
        candidate = InfraDependency(**dependency.model_dump())
        edges = [InfraDependency(**edge) for edge in self.list_dependencies(context)] + [candidate]
        if validate_dag([_node_model(node) for node in nodes], edges):
            raise DependencyConflictError("dependency would invalidate DAG")
        key = (
            context.tenant_id,
            context.workspace_id,
            f"{dependency.upstream_id}:{dependency.downstream_id}",
        )
        record = {
            **dependency.model_dump(),
            "dependency_id": f"dep_{uuid4().hex}",
            "tenant_id": context.tenant_id,
            "workspace_id": context.workspace_id,
            "created_at": now.isoformat(),
        }
        with self._lock:
            self.edges[key] = record
        return copy.deepcopy(record)

    def list_dependencies(self, context):
        return [
            copy.deepcopy(item)
            for item in self.edges.values()
            if item["tenant_id"] == context.tenant_id
            and item["workspace_id"] == context.workspace_id
        ]

    def unlock_ranking(self, context):
        nodes = [_node_model(node) for node in self.list_nodes(context)]
        edges = [InfraDependency(**edge) for edge in self.list_dependencies(context)]
        candidates = [
            compute_unlock_value(
                node.node_id,
                nodes,
                edges,
                self.pending_missions.get((context.tenant_id, context.workspace_id), []),
            )
            for node in nodes
            if node.state != "operational"
        ]
        candidates.sort(key=lambda item: (-item.mission_unlock_value, item.target_node_id))
        return [
            item.model_copy(update={"rank": index}).model_dump(mode="json")
            for index, item in enumerate(candidates, 1)
        ]


class PostgreSQLDependencyStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connection(self):
        return psycopg.connect(self.database_url)

    @staticmethod
    def _ensure_context(cursor, context, now):
        cursor.execute(
            "INSERT INTO organizations (id, name, created_at) VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.tenant_id, "Development demo organization", now),
        )
        cursor.execute(
            "INSERT INTO event_workspaces (id, organization_id, name, mode, status, event_time, created_at) VALUES (%s,%s,%s,'replay','active',%s,%s) ON CONFLICT (id) DO NOTHING",
            (context.workspace_id, context.tenant_id, "Development demo event", now, now),
        )
        cursor.execute(
            "INSERT INTO memberships (organization_id, actor_id, role, created_at) VALUES (%s,%s,%s,%s) ON CONFLICT (organization_id, actor_id) DO NOTHING",
            (context.tenant_id, context.actor_id, context.role, now),
        )

    def create_node(self, context, node, now):
        node_id = node.node_id or f"node_{uuid4().hex}"
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            cursor.execute(
                "INSERT INTO infrastructure_nodes (node_id, organization_id, workspace_id, node_type, name, location, state, capacity, evidence_ref, valid_from, valid_until, created_at) VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s,%s,%s,%s,%s,%s) ON CONFLICT (node_id) DO NOTHING",
                (
                    node_id,
                    context.tenant_id,
                    context.workspace_id,
                    node.node_type,
                    node.name,
                    json.dumps(node.location) if node.location else None,
                    node.state,
                    node.capacity,
                    node.evidence_ref,
                    node.valid_from,
                    node.valid_until,
                    now,
                ),
            )
            return {"node_id": node_id, **node.model_dump(exclude={"node_id"})}

    def list_nodes(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT node_id, node_type, name, state, capacity, evidence_ref FROM infrastructure_nodes WHERE organization_id=%s AND workspace_id=%s ORDER BY node_id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "node_id": row[0],
                    "node_type": row[1],
                    "name": row[2],
                    "state": row[3],
                    "capacity": row[4],
                    "evidence_ref": row[5],
                }
                for row in cursor.fetchall()
            ]

    def create_dependency(self, context, dependency, now):
        nodes = [_node_model(node) for node in self.list_nodes(context)]
        edges = [InfraDependency(**edge) for edge in self.list_dependencies(context)] + [
            InfraDependency(**dependency.model_dump())
        ]
        if validate_dag(nodes, edges):
            raise DependencyConflictError("dependency would invalidate DAG")
        with self._connection() as connection, connection.cursor() as cursor:
            self._ensure_context(cursor, context, now)
            dependency_id = f"dep_{uuid4().hex}"
            cursor.execute(
                "INSERT INTO infrastructure_dependencies (dependency_id, upstream_id, downstream_id, dependency_type, threshold, policy_version, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING dependency_id, upstream_id, downstream_id, dependency_type",
                (
                    dependency_id,
                    dependency.upstream_id,
                    dependency.downstream_id,
                    dependency.dependency_type,
                    dependency.threshold,
                    DEPENDENCY_VERSION,
                    now,
                ),
            )
            row = cursor.fetchone()
            return {
                "dependency_id": row[0],
                "upstream_id": row[1],
                "downstream_id": row[2],
                "dependency_type": row[3],
            }

    def list_dependencies(self, context):
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT dependency_id, upstream_id, downstream_id, dependency_type FROM infrastructure_dependencies d JOIN infrastructure_nodes n ON n.node_id=d.upstream_id WHERE n.organization_id=%s AND n.workspace_id=%s ORDER BY dependency_id",
                (context.tenant_id, context.workspace_id),
            )
            return [
                {
                    "dependency_id": row[0],
                    "upstream_id": row[1],
                    "downstream_id": row[2],
                    "dependency_type": row[3],
                }
                for row in cursor.fetchall()
            ]

    def unlock_ranking(self, context):
        nodes = [_node_model(node) for node in self.list_nodes(context)]
        edges = [InfraDependency(**edge) for edge in self.list_dependencies(context)]
        return [
            item.model_dump(mode="json")
            for item in sorted(
                (
                    compute_unlock_value(node.node_id, nodes, edges, [])
                    for node in nodes
                    if node.state != "operational"
                ),
                key=lambda item: (-item.mission_unlock_value, item.target_node_id),
            )
        ]
