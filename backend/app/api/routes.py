# ruff: noqa: E501

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from app.cascade import CascadeRequest, evaluate_cascade
from app.command_summary import build_command_summary
from app.core.context import RequestContext, require_scopes
from app.core.errors import ApiProblem, Problem, problem_response
from app.coverage import (
    CoverageCellCreate,
    CoverageConflictError,
    CoverageNotFoundError,
    CoverageObservationCreate,
)
from app.decision_loop import DecisionNotFoundError, DecisionResponse, InteractionAuditRequest
from app.decision_policy import PolicyRequest, evaluate_policy
from app.decision_snapshot import SnapshotRequest, build_decision_snapshot
from app.dependencies import (
    DependencyConflictError,
    InfraDependencyCreate,
    InfraNodeCreate,
)
from app.evaluation_replay import run_replay
from app.evidence import (
    EvidenceReview,
    IncidentLink,
    IncidentNotFoundError,
    ReportConflictError,
    ReportCreate,
    ReportNotFoundError,
)
from app.import_export import ImportRequest, export_redacted_csv, export_sitrep, import_fixture
from app.idempotency import request_hash
from app.incident_command import (
    CommandRoleAssignment,
    IncidentConflictError,
    IncidentCreate,
    IncidentTransition,
    SectorCreate,
)
from app.incident_command import (
    IncidentNotFoundError as CommandIncidentNotFoundError,
)
from app.mutual_aid import (
    ForecastRequest,
    MutualAidApproval,
    MutualAidConflictError,
    MutualAidNotFoundError,
    MutualAidRequestCreate,
    compute_forecast,
    draft_mutual_aid_request,
)
from app.offline_sync import SyncBatch, SyncResponse
from app.operations import (
    IdempotencyConflictError,
    MissionCreate,
    QueueItemCreate,
    QueueItemNotFoundError,
    ResourceNotFoundError,
    ResourceReadinessUpdate,
    RouteObservationCreate,
    StructuredTaskOutcome,
    TaskApproval,
    TaskConflictError,
    TaskNotFoundError,
    TaskOutcome,
    TaskStatusUpdate,
)
from app.operational_snapshot import build_operational_snapshot
from app.persistence import database_ready
from app.pilot_readiness import (
    OfficialFeedEnvelope,
    PilotConfigCreate,
    PilotConflictError,
    retention_preview,
    run_tabletop_exercise,
)
from app.plans import CertificateCreate, PlanConflictError, PlanCreate, PlanNotFoundError
from app.runway import RunwayRequest, project_runway
from app.shelter_state import (
    ShelterConflictError,
    ShelterCreate,
    ShelterNotFoundError,
    ShelterObservationCreate,
)
from app.telemetry import build_telemetry_summary
from app.updates import UpdatePublish, entity_type_for_event, source_class_for
from app.what_if import WhatIfRequest, WhatIfResult, evaluate_what_if

router = APIRouter()

IdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=3, max_length=128),
]


def _execute_idempotent(
    request: Request,
    context: RequestContext,
    idempotency_key: str | None,
    payload: Any,
    action: Callable[[], Any],
) -> Any:
    try:
        effective_key = idempotency_key or f"legacy-{request_hash(payload)}"
        return request.app.state.idempotency.execute(
            context,
            effective_key[:128],
            payload,
            action,
            request.app.state.clock.now(),
        )
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used with different request data.",
        ) from None


def _safe_read(unavailable: list[str], name: str, reader: Any, default: Any) -> Any:
    """Return a bounded partial result when a read adapter is temporarily unavailable."""
    try:
        return reader()
    except Exception:
        unavailable.append(name)
        return default


def _summary_freshness(scenario: dict[str, Any], generated_at: datetime, unavailable: list[str]) -> str:
    if unavailable:
        return "degraded"
    if not scenario:
        return "unknown"
    replayed_at = scenario.get("replayed_at")
    if replayed_at:
        try:
            observed = datetime.fromisoformat(str(replayed_at))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=UTC)
            comparison_time = generated_at if generated_at.tzinfo else generated_at.replace(tzinfo=UTC)
            if comparison_time.astimezone(UTC) - observed.astimezone(UTC) > timedelta(hours=6):
                return "stale"
        except (TypeError, ValueError):
            return "unknown"
    return "fresh"


@router.get("/command/summary", tags=["command"], response_model=None)
async def get_command_summary(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    unavailable: list[str] = []
    operations = request.app.state.operations_store
    scenario = _safe_read(unavailable, "decision_store", lambda: request.app.state.decision_store.get_scenario(context), {})
    generated_at = request.app.state.clock.now()
    return build_command_summary(
        resources=_safe_read(unavailable, "operations.resources", lambda: operations.list_resources(context), []),
        response_queue=_safe_read(unavailable, "operations.response_queue", lambda: operations.list_queue(context, "response"), []),
        verification_queue=_safe_read(unavailable, "operations.verification_queue", lambda: operations.list_queue(context, "verification"), []),
        tasks=_safe_read(unavailable, "operations.tasks", lambda: operations.list_tasks(context), []),
        scenario=scenario,
        generated_at=generated_at,
        workspace_mode=request.app.state.workspace_mode,
        correlation_id=context.correlation_id,
        freshness_state=_summary_freshness(scenario, generated_at, unavailable),
        unavailable_stores=unavailable,
        source="api",
    )


@router.get("/telemetry/summary", tags=["telemetry"], response_model=None)
async def get_telemetry_summary(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    """Return a bounded, scoped telemetry-health projection without device keys."""
    adapter = request.app.state.telemetry_adapter
    return build_telemetry_summary(
        devices=adapter.list_devices(context),
        gateways=adapter.list_gateways(context),
        generated_at=request.app.state.clock.now(),
        workspace_mode=request.app.state.workspace_mode,
    )


@router.get("/command/operational-snapshot", tags=["command"], response_model=None)
async def get_operational_snapshot(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    unavailable: list[str] = []
    generated_at = request.app.state.clock.now()
    shelters = _safe_read(unavailable, "shelter_state_store.shelters", lambda: request.app.state.shelter_state_store.list_shelters(context), [])
    current_shelter = min(shelters, key=lambda item: str(item.get("id", "")), default=None)
    current_shelter_state = (
        _safe_read(unavailable, "shelter_state_store.state", lambda: request.app.state.shelter_state_store.get_state(context, current_shelter["id"]), None)
        if current_shelter
        else None
    )
    return build_operational_snapshot(
        active_incident=_safe_read(unavailable, "incident_store", lambda: request.app.state.incident_store.get_active_incident(context), None),
        resources=_safe_read(unavailable, "operations.resources", lambda: request.app.state.operations_store.list_resources(context), []),
        tasks=_safe_read(unavailable, "operations.tasks", lambda: request.app.state.operations_store.list_tasks(context), []),
        response_queue=_safe_read(unavailable, "operations.response_queue", lambda: request.app.state.operations_store.list_queue(context, "response"), []),
        verification_queue=_safe_read(unavailable, "operations.verification_queue", lambda: request.app.state.operations_store.list_queue(context, "verification"), []),
        route_conditions=_safe_read(unavailable, "operations.routes", lambda: request.app.state.operations_store.list_route_observations(context), []),
        shelter_state=current_shelter_state,
        pending_recommendations=_safe_read(unavailable, "decision_store.recommendations", lambda: request.app.state.decision_store.list_pending_recommendations(context), []),
        generated_at=generated_at,
        mode=request.app.state.workspace_mode,
        correlation_id=context.correlation_id,
        unavailable_stores=unavailable,
    )


@router.post("/command/incidents", tags=["command"], status_code=201, response_model=None)
async def create_command_incident(
    request: Request,
    incident: IncidentCreate,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "command_incident.create.v1", "incident": incident.model_dump(mode="json")},
            lambda: request.app.state.incident_store.create_incident(
                context, incident, request.app.state.clock.now()
            ),
        )
    except IncidentConflictError as exc:
        raise ApiProblem(
            status=409, code="INCIDENT_CONFLICT", title="Incident conflict", detail=str(exc)
        ) from None


@router.get("/command/incidents", tags=["command"], response_model=None)
async def list_command_incidents(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("decision:read"))]
) -> dict[str, Any]:
    return {"items": request.app.state.incident_store.list_incidents(context)}


@router.get("/command/incidents/active", tags=["command"], response_model=None)
async def get_active_command_incident(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("decision:read"))]
) -> dict[str, Any]:
    return {"incident": request.app.state.incident_store.get_active_incident(context)}


@router.patch("/command/incidents/{incident_id}", tags=["command"], response_model=None)
async def transition_command_incident(
    request: Request,
    incident_id: str,
    update: IncidentTransition,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        def action() -> dict[str, Any]:
            result = request.app.state.incident_store.transition(
                context, incident_id, update, request.app.state.clock.now()
            )
            _publish_operational_update(
                request,
                context,
                "incident_phase_changed",
                incident_id,
                {"status": update.status, "state": result.get("phase", "unknown")},
                source="incident_command_api",
                source_class="operator_report",
                idempotency_key=idempotency_key,
            )
            return result

        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "command_incident.transition.v1", "incident_id": incident_id, "update": update.model_dump(mode="json")},
            action,
        )
    except CommandIncidentNotFoundError:
        raise ApiProblem(
            status=404,
            code="INCIDENT_NOT_FOUND",
            title="Incident not found",
            detail="The incident is outside the current scope.",
        ) from None
    except IncidentConflictError as exc:
        raise ApiProblem(
            status=409,
            code="INCIDENT_CONFLICT",
            title="Incident transition conflict",
            detail=str(exc),
        ) from None


@router.post("/command/incidents/{incident_id}/roles", tags=["command"], response_model=None)
async def assign_command_role(
    request: Request,
    incident_id: str,
    assignment: CommandRoleAssignment,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "command_incident.role.v1", "incident_id": incident_id, "assignment": assignment.model_dump(mode="json")},
            lambda: request.app.state.incident_store.assign_role(
                context, incident_id, assignment, request.app.state.clock.now()
            ),
        )
    except CommandIncidentNotFoundError:
        raise ApiProblem(
            status=404,
            code="INCIDENT_NOT_FOUND",
            title="Incident not found",
            detail="The incident is outside the current scope.",
        ) from None


@router.post(
    "/command/incidents/{incident_id}/sectors",
    tags=["command"],
    status_code=201,
    response_model=None,
)
async def create_incident_sector(
    request: Request,
    incident_id: str,
    sector: SectorCreate,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "command_incident.sector.v1", "incident_id": incident_id, "sector": sector.model_dump(mode="json")},
            lambda: request.app.state.incident_store.create_sector(
                context, incident_id, sector, request.app.state.clock.now()
            ),
        )
    except CommandIncidentNotFoundError:
        raise ApiProblem(
            status=404,
            code="INCIDENT_NOT_FOUND",
            title="Incident not found",
            detail="The incident is outside the current scope.",
        ) from None
    except IncidentConflictError as exc:
        raise ApiProblem(
            status=409, code="SECTOR_CONFLICT", title="Sector conflict", detail=str(exc)
        ) from None


@router.get("/command/incidents/{incident_id}/sectors", tags=["command"], response_model=None)
async def list_incident_sectors(
    request: Request,
    incident_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    try:
        return {"items": request.app.state.incident_store.list_sectors(context, incident_id)}
    except CommandIncidentNotFoundError:
        raise ApiProblem(
            status=404,
            code="INCIDENT_NOT_FOUND",
            title="Incident not found",
            detail="The incident is outside the current scope.",
        ) from None
    except IncidentConflictError as exc:
        raise ApiProblem(
            status=409, code="INCIDENT_CONFLICT", title="Incident command conflict", detail=str(exc)
        ) from None


@router.post("/resource-forecasts", tags=["mutual-aid"], response_model=None)
async def create_resource_forecast(
    request: Request,
    forecast_request: ForecastRequest,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    def action() -> dict[str, Any]:
        created = request.app.state.mutual_aid_store.create_forecast(
            context, forecast_request, request.app.state.clock.now()
        )
        forecast = compute_forecast(forecast_request)
        draft = draft_mutual_aid_request(forecast, forecast_request, request.app.state.clock.now())
        if draft:
            created["draft_request"] = request.app.state.mutual_aid_store.create_request(
                context, MutualAidRequestCreate(**draft), request.app.state.clock.now()
            )
        return created

    return _execute_idempotent(
        request,
        context,
        idempotency_key,
        {"operation": "resource_forecast.create.v1", "forecast": forecast_request.model_dump(mode="json")},
        action,
    )


@router.get("/resource-forecasts", tags=["mutual-aid"], response_model=None)
async def list_resource_forecasts(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    return {"items": request.app.state.mutual_aid_store.list_forecasts(context)}


@router.get("/resource-requests", tags=["mutual-aid"], response_model=None)
async def list_resource_requests(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    return {"items": request.app.state.mutual_aid_store.list_requests(context)}


@router.patch("/resource-requests/{request_id}/approve", tags=["mutual-aid"], response_model=None)
async def approve_resource_request(
    request: Request,
    request_id: str,
    approval: MutualAidApproval,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "resource_request.approve.v1", "request_id": request_id, "approval": approval.model_dump(mode="json")},
            lambda: request.app.state.mutual_aid_store.approve_request(
                context, request_id, approval, request.app.state.clock.now()
            ),
        )
    except MutualAidNotFoundError:
        raise ApiProblem(
            status=404,
            code="RESOURCE_REQUEST_NOT_FOUND",
            title="Resource request not found",
            detail="The request is outside the current scope.",
        ) from None
    except MutualAidConflictError as exc:
        raise ApiProblem(
            status=409,
            code="RESOURCE_REQUEST_CONFLICT",
            title="Resource request conflict",
            detail=str(exc),
        ) from None


@router.post("/plans", tags=["plans"], status_code=201, response_model=None)
async def create_plan(
    request: Request,
    plan: PlanCreate,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    return _execute_idempotent(
        request,
        context,
        idempotency_key,
        {"operation": "plan.create.v1", "plan": plan.model_dump(mode="json")},
        lambda: request.app.state.plan_store.create_plan(context, plan, request.app.state.clock.now()),
    )


@router.get("/plans", tags=["plans"], response_model=None)
async def list_plans(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
    status: str | None = Query(default=None, max_length=32),
) -> dict[str, Any]:
    return {"items": request.app.state.plan_store.list_plans(context, status)}


@router.get("/plans/{plan_id}", tags=["plans"], response_model=None)
async def get_plan(
    request: Request,
    plan_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    try:
        return request.app.state.plan_store.get_plan(context, plan_id)
    except PlanNotFoundError:
        raise ApiProblem(
            status=404,
            code="PLAN_NOT_FOUND",
            title="Plan not found",
            detail="The plan is not available in the current scope.",
        ) from None


@router.post("/plans/{plan_id}/check-assumptions", tags=["plans"], response_model=None)
async def check_plan_assumptions(
    request: Request,
    plan_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "plan.check_assumptions.v1", "plan_id": plan_id},
            lambda: {"items": request.app.state.plan_store.check_assumptions(
                context, plan_id, request.app.state.clock.now()
            )},
        )
    except PlanNotFoundError:
        raise ApiProblem(
            status=404,
            code="PLAN_NOT_FOUND",
            title="Plan not found",
            detail="The plan is not available in the current scope.",
        ) from None


@router.post("/plans/{plan_id}/invalidate", tags=["plans"], response_model=None)
async def invalidate_plan(
    request: Request,
    plan_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    trigger_type: str = Query(
        default="manual", pattern=r"^(claim_revision|route_expiry|readiness_expiry|manual)$"
    ),
    trigger_ref: str = Query(..., min_length=1, max_length=160),
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "plan.invalidate.v1", "plan_id": plan_id, "trigger_type": trigger_type, "trigger_ref": trigger_ref},
            lambda: request.app.state.plan_store.invalidate_plan(
                context, plan_id, trigger_type, trigger_ref, request.app.state.clock.now()
            ),
        )
    except PlanNotFoundError:
        raise ApiProblem(
            status=404,
            code="PLAN_NOT_FOUND",
            title="Plan not found",
            detail="The plan is not available in the current scope.",
        ) from None
    except PlanConflictError:
        raise ApiProblem(
            status=409,
            code="PLAN_INVALIDATION_CONFLICT",
            title="Plan invalidation conflict",
            detail="The trigger does not match a named plan assumption.",
        ) from None


@router.post("/decision-certificates", tags=["plans"], status_code=201, response_model=None)
async def create_decision_certificate(
    request: Request,
    certificate: CertificateCreate,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "decision_certificate.create.v1", "certificate": certificate.model_dump(mode="json")},
            lambda: request.app.state.plan_store.create_certificate(
                context, certificate, request.app.state.clock.now()
            ),
        )
    except PlanNotFoundError:
        raise ApiProblem(
            status=404,
            code="PLAN_NOT_FOUND",
            title="Plan not found",
            detail="The selected plan is not available in the current scope.",
        ) from None
    except PlanConflictError:
        raise ApiProblem(
            status=409,
            code="CERTIFICATE_CONFLICT",
            title="Certificate conflict",
            detail="The selected plan is not approvable.",
        ) from None


@router.get("/decision-certificates/{certificate_id}", tags=["plans"], response_model=None)
async def get_decision_certificate(
    request: Request,
    certificate_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    try:
        return request.app.state.plan_store.get_certificate(context, certificate_id)
    except PlanNotFoundError:
        raise ApiProblem(
            status=404,
            code="CERTIFICATE_NOT_FOUND",
            title="Certificate not found",
            detail="The certificate is not available in the current scope.",
        ) from None


@router.post("/infrastructure/nodes", tags=["infrastructure"], status_code=201, response_model=None)
async def create_infrastructure_node(
    request: Request,
    node: InfraNodeCreate,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "infrastructure.node.create.v1", "node": node.model_dump(mode="json")},
            lambda: request.app.state.dependency_store.create_node(
                context, node, request.app.state.clock.now()
            ),
        )
    except DependencyConflictError:
        raise ApiProblem(
            status=409,
            code="INFRASTRUCTURE_NODE_CONFLICT",
            title="Infrastructure node conflict",
            detail="The node already exists with different immutable data.",
        ) from None


@router.get("/infrastructure/nodes", tags=["infrastructure"], response_model=None)
async def list_infrastructure_nodes(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    return {"items": request.app.state.dependency_store.list_nodes(context)}


@router.post(
    "/infrastructure/dependencies", tags=["infrastructure"], status_code=201, response_model=None
)
async def create_infrastructure_dependency(
    request: Request,
    dependency: InfraDependencyCreate,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "infrastructure.dependency.create.v1", "dependency": dependency.model_dump(mode="json")},
            lambda: request.app.state.dependency_store.create_dependency(
                context, dependency, request.app.state.clock.now()
            ),
        )
    except DependencyConflictError:
        raise ApiProblem(
            status=409,
            code="INVALID_DEPENDENCY",
            title="Invalid infrastructure dependency",
            detail="The edge references an unknown node or would violate the bounded DAG.",
        ) from None


@router.get("/infrastructure/dependencies", tags=["infrastructure"], response_model=None)
async def list_infrastructure_dependencies(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    return {"items": request.app.state.dependency_store.list_dependencies(context)}


@router.get("/infrastructure/unlock-ranking", tags=["infrastructure"], response_model=None)
async def infrastructure_unlock_ranking(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    return {
        "items": request.app.state.dependency_store.unlock_ranking(context),
        "version": "dependency_dag_v1",
    }


@router.post("/coverage/cells", tags=["coverage"], status_code=201, response_model=None)
async def create_coverage_cell(
    request: Request,
    cell: CoverageCellCreate,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "coverage.cell.create.v1", "cell": cell.model_dump(mode="json")},
            lambda: request.app.state.coverage_store.create_cell(
                context, cell, request.app.state.clock.now()
            ),
        )
    except CoverageConflictError:
        raise ApiProblem(
            status=409,
            code="COVERAGE_CELL_CONFLICT",
            title="Coverage cell conflict",
            detail="The cell ID already exists with different immutable data.",
        ) from None


@router.get("/coverage/cells", tags=["coverage"], response_model=None)
async def list_coverage_cells(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, Any]:
    return {
        "items": request.app.state.coverage_store.list_cells(context, request.app.state.clock.now())
    }


@router.get("/coverage/cells/{cell_id}", tags=["coverage"], response_model=None)
async def get_coverage_cell(
    request: Request,
    cell_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, Any]:
    try:
        return request.app.state.coverage_store.get_cell(
            context, cell_id, request.app.state.clock.now()
        )
    except CoverageNotFoundError:
        raise ApiProblem(
            status=404,
            code="COVERAGE_CELL_NOT_FOUND",
            title="Coverage cell not found",
            detail="The coverage cell is not available in the current scope.",
        ) from None


@router.post(
    "/coverage/cells/{cell_id}/observations",
    tags=["coverage"],
    status_code=201,
    response_model=None,
)
async def create_coverage_observation(
    request: Request,
    cell_id: str,
    observation: CoverageObservationCreate,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return request.app.state.coverage_store.create_observation(
            context, cell_id, observation, request.app.state.clock.now(), idempotency_key
        )
    except CoverageNotFoundError:
        raise ApiProblem(
            status=404,
            code="COVERAGE_CELL_NOT_FOUND",
            title="Coverage cell not found",
            detail="The coverage cell is not available in the current scope.",
        ) from None
    except CoverageConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different observation.",
        ) from None


@router.get("/coverage/cells/{cell_id}/observations", tags=["coverage"], response_model=None)
async def list_coverage_observations(
    request: Request,
    cell_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, Any]:
    try:
        return {"items": request.app.state.coverage_store.list_observations(context, cell_id)}
    except CoverageNotFoundError:
        raise ApiProblem(
            status=404,
            code="COVERAGE_CELL_NOT_FOUND",
            title="Coverage cell not found",
            detail="The coverage cell is not available in the current scope.",
        ) from None


@router.get("/coverage/verification-ranking", tags=["coverage"], response_model=None)
async def coverage_verification_ranking(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, Any]:
    return {
        "items": request.app.state.coverage_store.verification_ranking(
            context, request.app.state.clock.now()
        ),
        "version": "decision_impact_v1",
    }


@router.get("/updates", tags=["operations"], response_model=None)
async def poll_updates(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
    cursor: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    try:
        page = request.app.state.update_feed.poll(
            context.tenant_id, context.workspace_id, cursor, limit
        )
        generated_at = request.app.state.clock.now().isoformat()
        return {
            **page,
            "correlation_id": context.correlation_id,
            "generated_at": generated_at,
            "freshness": {"state": "fresh", "as_of": generated_at},
        }
    except ValueError:
        raise ApiProblem(
            status=422,
            code="INVALID_UPDATE_CURSOR",
            title="Invalid update cursor",
            detail="The update cursor is malformed.",
        ) from None
    except Exception:
        request.app.state.telemetry.increment("stale_feed_reads")
        generated_at = request.app.state.clock.now().isoformat()
        return {
            "items": [],
            "next_cursor": cursor or "",
            "correlation_id": context.correlation_id,
            "generated_at": generated_at,
            "freshness": {"state": "degraded", "as_of": generated_at},
            "availability": {"state": "degraded", "unavailable_stores": ["update_feed"]},
        }


@router.get("/metrics", tags=["system"], response_model=None)
async def metrics(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("system:read"))]
) -> dict[str, Any]:
    unavailable: list[str] = []
    response_depth = _safe_read(
        unavailable,
        "operations.response_queue",
        lambda: len(request.app.state.operations_store.list_queue(context, "response")),
        0,
    )
    verification_depth = _safe_read(
        unavailable,
        "operations.verification_queue",
        lambda: len(request.app.state.operations_store.list_queue(context, "verification")),
        0,
    )
    snapshot = request.app.state.telemetry.snapshot(
        queue_depth=response_depth + verification_depth,
    )
    return {
        **snapshot,
        "generated_at": request.app.state.clock.now().isoformat(),
        "correlation_id": context.correlation_id,
        "availability": {"state": "degraded" if unavailable else "available", "unavailable_stores": unavailable},
    }


@router.get("/evaluation/replay", tags=["exercise"], response_model=None)
async def evaluation_replay(
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    del context
    return run_replay()


@router.put("/pilot/configuration", tags=["pilot"], response_model=None)
async def configure_pilot(
    request: Request,
    configuration: PilotConfigCreate,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    return _execute_idempotent(
        request,
        context,
        idempotency_key,
        {"operation": "pilot.configuration.update.v1", "configuration": configuration.model_dump(mode="json")},
        lambda: request.app.state.pilot_store.configure(
            context, configuration, request.app.state.clock.now()
        ),
    )


@router.get("/pilot/status", tags=["pilot"], response_model=None)
async def pilot_status(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    configuration = request.app.state.pilot_store.get_config(context)
    events = request.app.state.pilot_store.list_feed_events(context)
    return {
        "configuration": configuration,
        "official_feed_events": len(events),
        "identity_mode": "development_fixture"
        if request.app.state.settings.dev_identity_enabled
        else "external_identity_required",
        "retention_enforcement": "review_required_no_automatic_deletion",
    }


@router.post("/pilot/official-feeds/events", tags=["pilot"], status_code=201, response_model=None)
async def ingest_official_feed_event(
    request: Request,
    envelope: OfficialFeedEnvelope,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        def action() -> dict[str, Any]:
            event, replayed = request.app.state.pilot_store.ingest_feed(
                context, envelope, request.app.state.clock.now()
            )
            return {"event": event, "replayed": replayed}

        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "pilot.official_feed_event.create.v1", "envelope": envelope.model_dump(mode="json")},
            action,
        )
    except PilotConflictError as exc:
        raise ApiProblem(
            status=409,
            code="OFFICIAL_FEED_REJECTED",
            title="Official feed event rejected",
            detail=str(exc),
        ) from None


@router.get("/pilot/retention-preview", tags=["pilot"], response_model=None)
async def pilot_retention_preview(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
    record_class: str = Query(
        default="operational", pattern="^(operational|restricted_operational)$"
    ),
    created_at: datetime | None = None,
) -> dict[str, Any]:
    configuration = request.app.state.pilot_store.get_config(context)
    if configuration is None:
        raise ApiProblem(
            status=404,
            code="PILOT_NOT_CONFIGURED",
            title="Pilot configuration required",
            detail="Configure the agency and district before evaluating retention.",
        )
    return retention_preview(
        configuration,
        record_class,  # type: ignore[arg-type]
        created_at or request.app.state.clock.now(),
        request.app.state.clock.now(),
    ).model_dump(mode="json")


@router.post("/pilot/exercises/tabletop", tags=["pilot"], response_model=None)
async def pilot_tabletop_exercise(
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    del context
    return run_tabletop_exercise()


@router.post("/updates", tags=["operations"], status_code=201, response_model=None)
async def publish_update(
    request: Request,
    update: UpdatePublish,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    """Packet-local adapter for committed operational changes in the demo."""
    payload = {"aggregate_id": update.aggregate_id}
    if update.status is not None:
        payload["status"] = update.status
    try:
        occurred_at = request.app.state.clock.now().isoformat()
        cursor = request.app.state.update_feed.publish(
            context.tenant_id,
            context.workspace_id,
            update.event_type,
            payload,
            occurred_at,
            source="operator_api",
            source_class="operator_report",
            correlation_id=context.correlation_id,
            affected_entity_type=entity_type_for_event(update.event_type),
            affected_entity_id=update.aggregate_id,
            idempotency_key=idempotency_key,
        )
        return {"cursor": cursor, "correlation_id": context.correlation_id, "occurred_at": occurred_at}
    except ValueError as exc:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail=str(exc),
        ) from None


def _publish_operational_update(
    request: Request,
    context: RequestContext,
    event_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
    source: str = "operational_api",
    source_class: str | None = None,
    idempotency_key: str | None = None,
) -> None:
    """Publish a bounded envelope after a scoped, committed mutation."""
    request.app.state.update_feed.publish(
        context.tenant_id,
        context.workspace_id,
        event_type,
        {"id": entity_id, **(payload or {})},
        request.app.state.clock.now().isoformat(),
        source=source,
        source_class=source_class or source_class_for(source),
        correlation_id=context.correlation_id,
        affected_entity_type=entity_type_for_event(event_type),
        affected_entity_id=entity_id,
        idempotency_key=idempotency_key,
    )


def _validate_queue_sources(
    request: Request, context: RequestContext, item: QueueItemCreate
) -> None:
    """Require queue provenance to resolve inside the caller's current scope."""
    if item.source_report_id:
        try:
            request.app.state.evidence_store.get_report(context, item.source_report_id)
        except ReportNotFoundError:
            raise ApiProblem(
                status=404,
                code="QUEUE_SOURCE_REPORT_NOT_FOUND",
                title="Queue source report not found",
                detail="The source report is not available in the current tenant/workspace scope.",
            ) from None
    if item.source_incident_id:
        incident_ids = {
            incident["id"] for incident in request.app.state.evidence_store.list_incidents(context)
        }
        if item.source_incident_id not in incident_ids:
            try:
                request.app.state.incident_store.get_incident(context, item.source_incident_id)
            except CommandIncidentNotFoundError:
                raise ApiProblem(
                    status=404,
                    code="QUEUE_SOURCE_INCIDENT_NOT_FOUND",
                    title="Queue source incident not found",
                    detail=(
                        "The source incident is not available in the current tenant/workspace scope."
                    ),
                ) from None


@router.post("/missions", tags=["missions"], response_model=None, status_code=201)
async def create_mission(
    request: Request,
    mission: MissionCreate,
    context: Annotated[
        RequestContext,
        Depends(require_scopes("operations:write", "evidence:read", "decision:read")),
    ],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        report = request.app.state.evidence_store.get_report(context, mission.source_report_id)
        command_incident = request.app.state.incident_store.get_incident(
            context, mission.source_incident_id
        )
    except ReportNotFoundError:
        raise ApiProblem(
            status=404,
            code="REPORT_NOT_FOUND",
            title="Report not found",
            detail="The source report is outside the current scope.",
        ) from None
    except CommandIncidentNotFoundError:
        raise ApiProblem(
            status=404,
            code="INCIDENT_NOT_FOUND",
            title="Incident not found",
            detail="The command incident is outside the current scope.",
        ) from None
    if command_incident["status"] != "active":
        raise ApiProblem(
            status=409,
            code="INCIDENT_NOT_ACTIVE",
            title="Incident is not active",
            detail="Missions can only be created for an active command incident.",
        )
    if not any(claim["verification_state"] == "corroborated" for claim in report["claims"]):
        raise ApiProblem(
            status=409,
            code="REPORT_NOT_VERIFIED",
            title="Report is not verified",
            detail="A commander must corroborate at least one source claim before mission creation.",
        )
    queue_item = QueueItemCreate(
        title=mission.objective,
        priority=mission.priority,
        destination=mission.destination,
        notes="Created from a corroborated report.",
        queue_type="response",
        required_capability=mission.required_capability,
        owner_actor_id=mission.owner_actor_id,
        source_report_id=mission.source_report_id,
        source_incident_id=mission.source_incident_id,
    )
    try:
        created = request.app.state.operations_store.create_queue(
            context, queue_item, request.app.state.clock.now(), idempotency_key
        )
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different mission.",
        ) from None
    return {"mission_id": created["id"], **created}


@router.get("/missions", tags=["missions"], response_model=None)
async def list_missions(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    tasks = {
        task["queue_item_id"]: task
        for task in request.app.state.operations_store.list_tasks(context)
    }
    return {
        "items": [
            {"mission_id": item["id"], **item, "task": tasks.get(item["id"])}
            for item in request.app.state.operations_store.list_queue(context, "response")
            if item.get("source_report_id")
        ]
    }


@router.get("/health/live", tags=["system"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", tags=["system"], response_model=None)
async def health_ready(request: Request) -> JSONResponse | dict[str, Any]:
    settings = request.app.state.settings
    database_status = "available" if database_ready(settings.database_url) else "unavailable"
    telemetry_adapter = request.app.state.telemetry_adapter
    adapter_health = getattr(telemetry_adapter, "health_check", None)
    if callable(adapter_health):
        try:
            telemetry_status = str(adapter_health())
        except Exception:
            telemetry_status = "unavailable"
    else:
        telemetry_status = "unknown"
    feed_statuses = request.app.state.live_feed_manager.health_status
    external_status = (
        "not_checked"
        if not feed_statuses
        else "healthy" if all(value == "healthy" for value in feed_statuses.values()) else "degraded"
    )
    checks = {
        "database": database_status,
        "update_feed": "available" if getattr(request.app.state, "update_feed", None) is not None else "unavailable",
        "telemetry_adapter": telemetry_status,
        "external_integrations": external_status,
    }
    if database_status == "available":
        return {
            "status": "ready",
            "checks": checks,
            "correlation_id": request.state.correlation_id,
        }
    problem = Problem(
        type="https://ev2.local/problems/dependency-unavailable",
        title="Required dependency unavailable",
        status=503,
        code="DEPENDENCY_UNAVAILABLE",
        detail="The PostgreSQL/PostGIS database is not ready.",
        correlation_id=request.state.correlation_id,
        retryable=True,
    )
    return problem_response(problem)


@router.get("/version", tags=["system"])
async def version(request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    return {
        "service": "ev2-backend",
        "version": settings.app_version,
        "api_version": "v1",
    }


@router.get("/dev/context", tags=["development"])
async def development_context(
    context: Annotated[RequestContext, Depends(require_scopes("context:read"))],
) -> dict[str, str | list[str]]:
    return {
        "actor_id": context.actor_id,
        "role": context.role,
        "tenant_id": context.tenant_id,
        "workspace_id": context.workspace_id,
        "scopes": sorted(context.scopes),
        "correlation_id": context.correlation_id,
        "identity_source": "development-fixture",
    }


@router.post("/reports", tags=["evidence"], status_code=201, response_model=None)
async def create_report(
    request: Request,
    report: ReportCreate,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    """Accept one immutable report; retries reuse the client record identity."""
    if idempotency_key != report.client_record_id:
        raise ApiProblem(
            status=422,
            code="IDEMPOTENCY_KEY_MISMATCH",
            title="Idempotency key mismatch",
            detail="Idempotency-Key must equal client_record_id for this report contract.",
        )
    try:
        record, replayed = request.app.state.evidence_store.create_report(
            context,
            report,
            request.app.state.clock.now(),
        )
    except ReportConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="The client record ID was already used for a different report payload.",
        ) from None
    return {
        "report_id": record["id"],
        "accepted_at": record["recorded_at"],
        "status": record["status"],
        "deduplicated_replay": replayed,
        "warnings": record["warnings"],
        "revision": record["revision"],
    }


@router.get("/reports", tags=["evidence"], response_model=None)
async def list_reports(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    try:
        items, next_cursor = request.app.state.evidence_store.list_reports(context, limit, cursor)
    except ValueError:
        raise ApiProblem(
            status=422,
            code="INVALID_CURSOR",
            title="Invalid report cursor",
            detail="The report cursor is malformed or expired.",
        ) from None
    return {"items": items, "next_cursor": next_cursor}


@router.get("/reports/{report_id}", tags=["evidence"], response_model=None)
async def get_report(
    request: Request,
    report_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, Any]:
    try:
        return request.app.state.evidence_store.get_report(context, report_id)
    except ReportNotFoundError:
        raise ApiProblem(
            status=404,
            code="REPORT_NOT_FOUND",
            title="Report not found",
            detail="The report is not available in the current tenant/workspace scope.",
        ) from None


@router.post("/reports/{report_id}/review", tags=["evidence"], response_model=None)
async def review_report(
    request: Request,
    report_id: str,
    review: EvidenceReview,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "evidence.review.v1", "report_id": report_id, "review": review.model_dump(mode="json")},
            lambda: request.app.state.evidence_store.review_report(
                context, report_id, review, request.app.state.clock.now()
            ),
        )
    except ReportNotFoundError:
        raise ApiProblem(
            status=404,
            code="REPORT_OR_CLAIM_NOT_FOUND",
            title="Report or claim not found",
            detail="The report or one of its claims is outside the current scope.",
        ) from None


@router.post("/reports/{report_id}/incident-links", tags=["evidence"], response_model=None)
async def link_report_incident(
    request: Request,
    report_id: str,
    link: IncidentLink,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "evidence.incident_link.v1", "report_id": report_id, "link": link.model_dump(mode="json")},
            lambda: request.app.state.evidence_store.link_incident(
                context, report_id, link, request.app.state.clock.now()
            ),
        )
    except ReportNotFoundError:
        raise ApiProblem(
            status=404,
            code="REPORT_NOT_FOUND",
            title="Report not found",
            detail="The report is outside the current tenant/workspace scope.",
        ) from None
    except IncidentNotFoundError:
        raise ApiProblem(
            status=404,
            code="INCIDENT_NOT_FOUND",
            title="Incident not found",
            detail="The incident is outside the current tenant/workspace scope.",
        ) from None


@router.post("/reports/{report_id}/command-incident-links", tags=["evidence"], response_model=None)
async def link_report_command_incident(
    request: Request,
    report_id: str,
    link: IncidentLink,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write", "decision:read"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        def action() -> dict[str, Any]:
            request.app.state.incident_store.get_incident(context, link.incident_id)
            return request.app.state.evidence_store.link_command_incident(
                context, report_id, link.incident_id, request.app.state.clock.now()
            )

        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "evidence.command_incident_link.v1", "report_id": report_id, "link": link.model_dump(mode="json")},
            action,
        )
    except CommandIncidentNotFoundError:
        raise ApiProblem(
            status=404,
            code="INCIDENT_NOT_FOUND",
            title="Incident not found",
            detail="The command incident is outside the current scope.",
        ) from None
    except ReportNotFoundError:
        raise ApiProblem(
            status=404,
            code="REPORT_NOT_FOUND",
            title="Report not found",
            detail="The report is outside the current scope.",
        ) from None


@router.post("/demo/seed", tags=["evidence"], response_model=None)
async def seed_demo(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    request_idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    return _execute_idempotent(
        request,
        context,
        request_idempotency_key,
        {"operation": "evidence.demo_seed.v1"},
        lambda: {"synthetic": True, "created": request.app.state.evidence_store.seed_demo(context, request.app.state.clock.now()), "workspace_id": context.workspace_id},
    )


@router.get("/incidents", tags=["evidence"], response_model=None)
async def list_incidents(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, Any]:
    return {"items": request.app.state.evidence_store.list_incidents(context)}


@router.post("/shelters", tags=["shelter-state"], status_code=201, response_model=None)
async def create_shelter(
    request: Request,
    shelter: ShelterCreate,
    context: Annotated[RequestContext, Depends(require_scopes("state:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return _execute_idempotent(
            request,
            context,
            idempotency_key,
            {"operation": "shelter.create.v1", "shelter": shelter.model_dump(mode="json")},
            lambda: request.app.state.shelter_state_store.create_shelter(
                context, shelter, request.app.state.clock.now()
            ),
        )
    except ShelterConflictError:
        raise ApiProblem(
            status=409,
            code="SHELTER_CONFLICT",
            title="Shelter identity conflict",
            detail="The shelter ID already exists with different immutable metadata.",
        ) from None


@router.get("/shelters", tags=["shelter-state"], response_model=None)
async def list_shelters(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("state:read"))]
) -> dict[str, Any]:
    return {"items": request.app.state.shelter_state_store.list_shelters(context)}


@router.post(
    "/shelters/{shelter_id}/observations",
    tags=["shelter-state"],
    status_code=201,
    response_model=None,
)
async def create_shelter_observation(
    request: Request,
    shelter_id: str,
    observation: ShelterObservationCreate,
    context: Annotated[RequestContext, Depends(require_scopes("state:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        result = request.app.state.shelter_state_store.create_observation(
            context, shelter_id, observation, request.app.state.clock.now(), idempotency_key
        )
        if not result.get("replayed", False):
            _publish_operational_update(
                request,
                context,
                "shelter_state_changed",
                shelter_id,
                {"freshness_state": observation.freshness_state},
                source="shelter_state_api",
                source_class=source_class_for(observation.source),
                idempotency_key=idempotency_key,
            )
        return result
    except ShelterNotFoundError:
        raise ApiProblem(
            status=404,
            code="SHELTER_NOT_FOUND",
            title="Shelter not found",
            detail="The shelter is outside the current tenant/workspace scope.",
        ) from None
    except ShelterConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different observation payload.",
        ) from None


@router.get("/shelters/{shelter_id}/observations", tags=["shelter-state"], response_model=None)
async def list_shelter_observations(
    request: Request,
    shelter_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("state:read"))],
) -> dict[str, Any]:
    try:
        return {
            "items": request.app.state.shelter_state_store.list_observations(context, shelter_id)
        }
    except ShelterNotFoundError:
        raise ApiProblem(
            status=404,
            code="SHELTER_NOT_FOUND",
            title="Shelter not found",
            detail="The shelter is outside the current tenant/workspace scope.",
        ) from None


@router.get("/shelters/{shelter_id}/state", tags=["shelter-state"], response_model=None)
async def get_shelter_state(
    request: Request,
    shelter_id: str,
    context: Annotated[RequestContext, Depends(require_scopes("state:read"))],
) -> dict[str, Any]:
    try:
        return request.app.state.shelter_state_store.get_state(context, shelter_id)
    except ShelterNotFoundError:
        raise ApiProblem(
            status=404,
            code="SHELTER_NOT_FOUND",
            title="Shelter not found",
            detail="The shelter is outside the current tenant/workspace scope.",
        ) from None


@router.post("/shelter-state/demo/seed", tags=["shelter-state"], response_model=None)
async def seed_shelter_state_demo(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("state:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    return _execute_idempotent(
        request,
        context,
        idempotency_key,
        {"operation": "shelter.demo_seed.v1"},
        lambda: request.app.state.shelter_state_store.seed_demo(context, request.app.state.clock.now()),
    )


@router.post("/runway/projections", tags=["shelter-state"], response_model=None)
async def project_resource_runway(
    request: RunwayRequest,
    context: Annotated[RequestContext, Depends(require_scopes("state:read"))],
) -> dict[str, Any]:
    del context
    return project_runway(request).model_dump(mode="json")


@router.post("/cascade/evaluate", tags=["decision-loop"], response_model=None)
async def evaluate_cascade_path(
    request: CascadeRequest,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    del context
    return evaluate_cascade(request).model_dump(mode="json")


@router.post("/what-if/evaluate", tags=["decision-loop"], response_model=WhatIfResult)
async def evaluate_what_if_path(
    request: WhatIfRequest,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    del context
    return evaluate_what_if(request).model_dump(mode="json")


@router.post("/decision-policy/evaluate", tags=["decision-loop"], response_model=None)
async def evaluate_decision_policy(
    request: PolicyRequest,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    del context
    return evaluate_policy(request).model_dump(mode="json")


@router.post("/decision-snapshot/build", tags=["decision-loop"], response_model=None)
async def build_decision_snapshot_path(
    request: SnapshotRequest,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    if request.tenant_id != context.tenant_id or request.workspace_id != context.workspace_id:
        raise ApiProblem(
            status=403,
            code="SCOPE_DENIED",
            title="Snapshot scope denied",
            detail="Snapshot sources must match the caller scope.",
        )
    return build_decision_snapshot(request).model_dump(mode="json")


@router.post("/offline-sync", tags=["operations"], response_model=SyncResponse)
async def reconcile_offline_commands(
    batch: SyncBatch,
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    def reconcile() -> dict[str, Any]:
        result = request.app.state.offline_sync_store.reconcile(
            batch, context.tenant_id, context.workspace_id, request.app.state.clock.now()
        )
        reconciliation = result.get("reconciliation", {})
        if reconciliation.get("rejected", 0) or reconciliation.get("conflicts", 0):
            request.app.state.telemetry.increment("offline_reconciliation_failures")
            if reconciliation.get("conflicts", 0):
                request.app.state.telemetry.increment("sync_conflicts", "conflict")
        return result

    return _execute_idempotent(
        request,
        context,
        idempotency_key,
        {"operation": "offline_sync.reconcile.v1", "batch": batch.model_dump(mode="json")},
        reconcile,
    )


@router.post("/imports/fixture", tags=["evidence"], response_model=None)
async def import_fixture_path(
    request: ImportRequest,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    if request.tenant_id != context.tenant_id or request.workspace_id != context.workspace_id:
        raise ApiProblem(
            status=403,
            code="SCOPE_DENIED",
            title="Import scope denied",
            detail="Import scope must match the caller.",
        )
    return _execute_idempotent(
        request,
        context,
        idempotency_key,
        {"operation": "fixture.import.v1", "request": request.model_dump(mode="json")},
        lambda: import_fixture(request).model_dump(mode="json"),
    )


@router.post("/exports/sitrep", tags=["evidence"], response_model=None)
async def export_sitrep_path(
    body: dict[str, Any],
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, Any]:
    if (
        body.get("tenant_id") != context.tenant_id
        or body.get("workspace_id") != context.workspace_id
    ):
        raise ApiProblem(
            status=403,
            code="SCOPE_DENIED",
            title="Export scope denied",
            detail="Export scope must match the caller.",
        )
    return export_sitrep(
        body.get("rows", []), datetime.fromisoformat(body["replay_at"].replace("Z", "+00:00"))
    )


@router.post("/exports/csv", tags=["evidence"], response_model=None)
async def export_csv_path(
    body: dict[str, Any],
    context: Annotated[RequestContext, Depends(require_scopes("evidence:read"))],
) -> dict[str, str]:
    if (
        body.get("tenant_id") != context.tenant_id
        or body.get("workspace_id") != context.workspace_id
    ):
        raise ApiProblem(
            status=403,
            code="SCOPE_DENIED",
            title="Export scope denied",
            detail="Export scope must match the caller.",
        )
    return {
        "content_type": "text/csv",
        "content": export_redacted_csv(
            body.get("rows", []), context.tenant_id, context.workspace_id
        ),
    }


@router.get("/sectors", tags=["geospatial"], response_model=None)
async def list_sectors(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("map:read"))],
) -> dict[str, Any]:
    return {"items": request.app.state.evidence_store.list_sectors(context)}


def _parse_bbox(raw_bbox: str | None) -> tuple[float, float, float, float] | None:
    if raw_bbox is None:
        return None
    try:
        values = tuple(float(part.strip()) for part in raw_bbox.split(","))
    except ValueError:
        raise ValueError from None
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError
    if (
        not -180 <= values[0] <= 180
        or not -180 <= values[2] <= 180
        or not -90 <= values[1] <= 90
        or not -90 <= values[3] <= 90
    ):
        raise ValueError
    return values  # type: ignore[return-value]


@router.get("/map/features", tags=["geospatial"], response_model=None)
async def map_features(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("map:read"))],
    limit: int = Query(default=100, ge=1, le=100),
    bbox: str | None = Query(default=None, max_length=128),
) -> dict[str, Any]:
    try:
        parsed_bbox = _parse_bbox(bbox)
    except ValueError:
        raise ApiProblem(
            status=422,
            code="INVALID_BBOX",
            title="Invalid map bounds",
            detail="bbox must be min_longitude,min_latitude,max_longitude,max_latitude in WGS84.",
        ) from None
    return request.app.state.evidence_store.map_features(context, limit, parsed_bbox)


@router.post("/operations/demo/seed", tags=["operations"], response_model=None)
async def seed_operations(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return {
            "synthetic": True,
            **request.app.state.operations_store.seed_demo(
                context, request.app.state.clock.now(), idempotency_key
            ),
        }
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.get("/resources", tags=["operations"], response_model=None)
async def list_resources(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("operations:read"))]
) -> dict[str, Any]:
    return {"items": request.app.state.operations_store.list_resources(context)}


@router.patch("/resources/{resource_id}/readiness", tags=["operations"], response_model=None)
async def update_readiness(
    request: Request,
    resource_id: str,
    update: ResourceReadinessUpdate,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
):
    try:
        result = request.app.state.operations_store.update_readiness(
            context, resource_id, update, request.app.state.clock.now(), idempotency_key
        )
        if result:
            _publish_operational_update(
                request,
                context,
                "resource_readiness_changed",
                resource_id,
                {"status": update.readiness},
                source="resource_readiness_api",
                source_class="operator_report",
                idempotency_key=idempotency_key,
            )
        return result
    except ResourceNotFoundError:
        raise ApiProblem(
            status=404,
            code="RESOURCE_NOT_FOUND",
            title="Resource not found",
            detail="The resource is outside the current scope.",
        ) from None


@router.post("/response-queue", tags=["operations"], response_model=None, status_code=201)
async def create_response_queue(
    request: Request,
    item: QueueItemCreate,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    _validate_queue_sources(request, context, item)
    try:
        return request.app.state.operations_store.create_queue(
            context, item, request.app.state.clock.now(), idempotency_key
        )
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.get("/response-queue", tags=["operations"], response_model=None)
async def list_response_queue(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("operations:read"))]
) -> dict[str, Any]:
    return {"items": request.app.state.operations_store.list_queue(context, "response")}


@router.post("/verification-queue", tags=["operations"], response_model=None, status_code=201)
async def create_verification_queue(
    request: Request,
    item: QueueItemCreate,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
):
    _validate_queue_sources(request, context, item)
    try:
        result = request.app.state.operations_store.create_queue(
            context,
            item.model_copy(update={"queue_type": "verification"}),
            request.app.state.clock.now(),
            idempotency_key,
        )
        if result:
            _publish_operational_update(
                request,
                context,
                "verification_priority_changed",
                str(result["id"]),
                {"priority": item.priority},
                source="verification_queue_api",
                source_class="operator_report",
                idempotency_key=idempotency_key,
            )
        return result
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.get("/verification-queue", tags=["operations"], response_model=None)
async def list_verification_queue(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("operations:read"))]
):
    return {"items": request.app.state.operations_store.list_queue(context, "verification")}


@router.post("/route-observations", tags=["operations"], response_model=None, status_code=201)
async def create_route_observation(
    request: Request,
    observation: RouteObservationCreate,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
):
    try:
        result = request.app.state.operations_store.create_route_observation(
            context, observation, request.app.state.clock.now(), idempotency_key
        )
        _publish_operational_update(
            request,
            context,
            "route_condition_changed",
            observation.destination,
            {"state": observation.state, "freshness_state": "fresh"},
            source="route_observation_api",
            source_class=source_class_for(observation.source),
            idempotency_key=idempotency_key,
        )
        return result
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.get("/route-observations", tags=["operations"], response_model=None)
async def list_route_observations(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("operations:read"))]
):
    return {"items": request.app.state.operations_store.list_route_observations(context)}


@router.post("/response-queue/{queue_id}/approve", tags=["operations"], response_model=None)
async def approve_task(
    request: Request,
    queue_id: str,
    approval: TaskApproval,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        result = request.app.state.operations_store.approve_task(
            context, queue_id, approval, request.app.state.clock.now(), idempotency_key
        )
        if result:
            _publish_operational_update(
                request,
                context,
                "task_status_changed",
                str(result["id"]),
                {"status": result.get("status"), "queue_item_id": queue_id},
                source="task_assignment_api",
                source_class="operator_report",
                idempotency_key=idempotency_key,
            )
        return result
    except QueueItemNotFoundError:
        raise ApiProblem(
            status=404,
            code="QUEUE_ITEM_NOT_FOUND",
            title="Queue item not found",
            detail="The queue item is outside the current scope.",
        ) from None
    except ResourceNotFoundError:
        raise ApiProblem(
            status=404,
            code="RESOURCE_NOT_FOUND",
            title="Resource not found",
            detail="The resource is outside the current scope.",
        ) from None
    except TaskConflictError as exc:
        raise ApiProblem(
            status=409, code="TASK_CONFLICT", title="Task cannot be approved", detail=str(exc)
        ) from None
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.get("/tasks", tags=["operations"], response_model=None)
async def list_tasks(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("operations:read"))]
) -> dict[str, Any]:
    return {"items": request.app.state.operations_store.list_tasks(context)}


@router.get("/jobs", tags=["operations"], response_model=None)
async def list_jobs(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("operations:read"))]
) -> dict[str, Any]:
    return {"items": request.app.state.operations_store.list_jobs(context)}


@router.get("/audit/integrity", tags=["operations"], response_model=None)
async def verify_audit_integrity(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("operations:read"))]
) -> dict[str, Any]:
    return request.app.state.operations_store.verify_audit_chain(context)


@router.patch("/tasks/{task_id}", tags=["operations"], response_model=None)
async def update_task(
    request: Request,
    task_id: str,
    update: TaskStatusUpdate,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        result = request.app.state.operations_store.update_task(
            context, task_id, update.status, request.app.state.clock.now(), idempotency_key
        )
        if result:
            _publish_operational_update(
                request,
                context,
                "task_status_changed",
                task_id,
                {"status": update.status},
                source="task_status_api",
                source_class="operator_report",
                idempotency_key=idempotency_key,
            )
        return result
    except TaskNotFoundError:
        raise ApiProblem(
            status=404,
            code="TASK_NOT_FOUND",
            title="Task not found",
            detail="The task is outside the current scope.",
        ) from None
    except TaskConflictError as exc:
        raise ApiProblem(
            status=409, code="TASK_CONFLICT", title="Task state conflict", detail=str(exc)
        ) from None
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.post("/tasks/{task_id}/outcome", tags=["operations"], response_model=None)
async def record_task_outcome(
    request: Request,
    task_id: str,
    outcome: TaskOutcome,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        result = request.app.state.operations_store.record_task_outcome(
            context, task_id, outcome, request.app.state.clock.now(), idempotency_key
        )
        if result:
            _publish_operational_update(request, context, "task_status_changed", task_id, source="task_outcome_api", source_class="operator_report", idempotency_key=idempotency_key)
        return result
    except TaskNotFoundError:
        raise ApiProblem(
            status=404,
            code="TASK_NOT_FOUND",
            title="Task not found",
            detail="The task is outside the current scope.",
        ) from None
    except TaskConflictError as exc:
        raise ApiProblem(
            status=409, code="TASK_CONFLICT", title="Task outcome conflict", detail=str(exc)
        ) from None
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.post("/tasks/{task_id}/structured-outcome", tags=["operations"], response_model=None)
async def record_structured_task_outcome(
    request: Request,
    task_id: str,
    outcome: StructuredTaskOutcome,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        result = request.app.state.operations_store.record_structured_outcome(
            context, task_id, outcome, request.app.state.clock.now(), idempotency_key
        )
        if result:
            _publish_operational_update(request, context, "task_status_changed", task_id, source="task_outcome_api", source_class="operator_report", idempotency_key=idempotency_key)
        return result
    except TaskNotFoundError:
        raise ApiProblem(
            status=404,
            code="TASK_NOT_FOUND",
            title="Task not found",
            detail="The task is outside the current scope.",
        ) from None
    except TaskConflictError as exc:
        raise ApiProblem(
            status=409, code="TASK_CONFLICT", title="Task outcome conflict", detail=str(exc)
        ) from None
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.post("/decision-loop/demo/replay", tags=["decision-loop"], response_model=None)
async def replay_decision_demo(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        return request.app.state.decision_store.replay(
            context, request.app.state.clock.now(), idempotency_key
        )
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.get("/decision-loop/scenario", tags=["decision-loop"], response_model=None)
async def get_decision_scenario(
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("decision:read"))]
) -> dict[str, Any]:
    return request.app.state.decision_store.get_scenario(context)


@router.post("/decision-loop/recommendations", tags=["decision-loop"], response_model=None)
async def create_recommendation(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        result = request.app.state.decision_store.recommend(
            context, request.app.state.clock.now(), idempotency_key
        )
        if result:
            _publish_operational_update(
                request,
                context,
                "recommendation_changed",
                str(result["id"]),
                {"status": result.get("status")},
                source="decision_loop_api",
                idempotency_key=idempotency_key,
            )
        return result
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.get("/decision-loop/recommendations/current", tags=["decision-loop"], response_model=None)
async def get_current_recommendation(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
) -> dict[str, Any]:
    return {
        "recommendation": request.app.state.decision_store.get_current_recommendation(context),
        "correlation_id": context.correlation_id,
        "generated_at": request.app.state.clock.now().isoformat(),
    }


@router.post(
    "/decision-loop/recommendations/{recommendation_id}/decision",
    tags=["decision-loop"],
    response_model=None,
)
async def decide_recommendation(
    request: Request,
    recommendation_id: str,
    response: DecisionResponse,
    context: Annotated[RequestContext, Depends(require_scopes("decision:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    try:
        result = request.app.state.decision_store.decide(
            context, recommendation_id, response, request.app.state.clock.now(), idempotency_key
        )
        if result:
            _publish_operational_update(
                request,
                context,
                "recommendation_changed",
                recommendation_id,
                {"status": result.get("status")},
                source="decision_loop_api",
                idempotency_key=idempotency_key,
            )
        return result
    except DecisionNotFoundError:
        raise ApiProblem(
            status=404,
            code="RECOMMENDATION_NOT_FOUND",
            title="Recommendation not found",
            detail="The recommendation is outside the current scope.",
        ) from None
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


@router.post("/decision-loop/audit/interactions", tags=["decision-loop"], response_model=None)
async def record_decision_interaction(
    request: Request,
    interaction: InteractionAuditRequest,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    expected_type = {
        "recommendation_viewed": "recommendation",
        "evidence_opened": "evidence",
        "scenario_evaluated": "scenario",
    }[interaction.event]
    if interaction.subject_type != expected_type:
        raise ApiProblem(
            status=422,
            code="INVALID_AUDIT_SUBJECT",
            title="Invalid audit subject",
            detail="The interaction event and subject type must refer to the same scoped entity.",
        )
    if interaction.event == "evidence_opened" and "evidence:read" not in context.scopes:
        raise ApiProblem(
            status=403,
            code="SCOPE_DENIED",
            title="Required scope denied",
            detail="Evidence interactions require evidence read scope.",
        )
    try:
        result = request.app.state.decision_store.record_interaction(
            context, interaction, request.app.state.clock.now(), idempotency_key
        )
        return {**result, "correlation_id": context.correlation_id}
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different audit interaction.",
        ) from None


@router.get("/decision-loop/audit", tags=["decision-loop"], response_model=None)
async def decision_audit(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
    after: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    items = request.app.state.decision_store.audit(context, after, limit)
    return {
        "items": items,
        "next_after": items[-1].get("at") if items else after,
        "correlation_id": context.correlation_id,
        "generated_at": request.app.state.clock.now().isoformat(),
    }
@router.post("/feeds/sync", tags=["feeds"], response_model=None)
async def sync_live_feeds(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    manager = request.app.state.live_feed_manager

    async def action() -> dict[str, Any]:
        reports = await manager.sync_all()
        if any(status != "healthy" for status in manager.health_status.values()):
            request.app.state.telemetry.increment("external_integration_failures")
        created_reports = []
        for rpt in reports:
            try:
                record, exists = request.app.state.evidence_store.create_report(
                    context, rpt, request.app.state.clock.now()
                )
                if not exists:
                    created_reports.append(record)
            except Exception:
                continue
        return {
            "synced_count": len(reports),
            "created_count": len(created_reports),
            "health_status": manager.health_status,
            "last_sync_time": manager.last_sync_time.isoformat() if manager.last_sync_time else None,
        }

    return await request.app.state.idempotency.execute_async(
        context,
        idempotency_key or f"legacy-feed-sync-{request.app.state.clock.now().strftime('%Y%m%d%H')}",
        {"operation": "feeds.sync.v1"},
        action,
        request.app.state.clock.now(),
    )

@router.get("/workspace/mode", tags=["workspace"], response_model=None)
async def get_workspace_mode(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:read"))],
) -> dict[str, Any]:
    manager = request.app.state.live_feed_manager
    return {
        "mode": request.app.state.workspace_mode,
        "health_status": manager.health_status,
        "last_sync_time": manager.last_sync_time.isoformat() if manager.last_sync_time else None,
    }

@router.post("/workspace/mode", tags=["workspace"], response_model=None)
async def set_workspace_mode(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
    mode: str = Query(..., pattern="^(live|synthetic|mixed)$"),
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    return _execute_idempotent(
        request,
        context,
        idempotency_key,
        {"operation": "workspace.mode.update.v1", "mode": mode},
        lambda: _set_workspace_mode(request, mode),
    )


def _set_workspace_mode(request: Request, mode: str) -> dict[str, Any]:
    request.app.state.workspace_mode = mode
    return {"mode": mode}

@router.post("/lorawan/webhook", tags=["lorawan"], response_model=None)
async def lorawan_webhook(
    request: Request,
    body: dict[str, Any],
    event: str = Query(..., description="ChirpStack event type (up, status, join, etc.)"),
) -> dict:
    """Receive ChirpStack HTTP integration webhooks."""
    settings = request.app.state.settings
    
    # Very basic validation: in production use proper signature verification
    token = request.headers.get("X-Chirpstack-Token", "")
    expected_token = getattr(settings, "lorawan_webhook_secret", "")
    
    if expected_token and token != expected_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    adapter = getattr(request.app.state, "telemetry_adapter", None)
    if hasattr(adapter, "ingest_event"):
        adapter.ingest_event(event, body)
        
    return {"accepted": True}
