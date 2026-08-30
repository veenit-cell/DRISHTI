from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from app.cascade import CascadeRequest, evaluate_cascade
from app.core.context import RequestContext, require_scopes
from app.core.errors import ApiProblem, Problem, problem_response
from app.decision_loop import DecisionNotFoundError, DecisionResponse
from app.decision_policy import PolicyRequest, evaluate_policy
from app.decision_snapshot import SnapshotRequest, build_decision_snapshot
from app.evidence import (
    EvidenceReview,
    IncidentLink,
    IncidentNotFoundError,
    ReportConflictError,
    ReportCreate,
    ReportNotFoundError,
)
from app.offline_sync import SyncBatch
from app.operations import (
    IdempotencyConflictError,
    QueueItemCreate,
    QueueItemNotFoundError,
    ResourceNotFoundError,
    ResourceReadinessUpdate,
    RouteObservationCreate,
    TaskApproval,
    TaskConflictError,
    TaskNotFoundError,
    TaskOutcome,
    TaskStatusUpdate,
)
from app.persistence import database_ready
from app.runway import RunwayRequest, project_runway
from app.shelter_state import (
    ShelterConflictError,
    ShelterCreate,
    ShelterNotFoundError,
    ShelterObservationCreate,
)
from app.what_if import WhatIfRequest, evaluate_what_if

router = APIRouter()


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
            raise ApiProblem(
                status=404,
                code="QUEUE_SOURCE_INCIDENT_NOT_FOUND",
                title="Queue source incident not found",
                detail=(
                    "The source incident is not available in the current tenant/workspace scope."
                ),
            )


@router.get("/health/live", tags=["system"])
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", tags=["system"], response_model=None)
async def health_ready(request: Request) -> JSONResponse | dict[str, str]:
    settings = request.app.state.settings
    if database_ready(settings.database_url):
        return {"status": "ready", "database": "available"}
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
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
) -> dict[str, Any]:
    try:
        return request.app.state.evidence_store.review_report(
            context, report_id, review, request.app.state.clock.now()
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
) -> dict[str, Any]:
    try:
        return request.app.state.evidence_store.link_incident(
            context, report_id, link, request.app.state.clock.now()
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


@router.post("/demo/seed", tags=["evidence"], response_model=None)
async def seed_demo(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("evidence:write"))],
) -> dict[str, Any]:
    created = request.app.state.evidence_store.seed_demo(context, request.app.state.clock.now())
    return {"synthetic": True, "created": created, "workspace_id": context.workspace_id}


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
) -> dict[str, Any]:
    try:
        return request.app.state.shelter_state_store.create_shelter(
            context, shelter, request.app.state.clock.now()
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
) -> dict[str, Any]:
    try:
        return request.app.state.shelter_state_store.create_observation(
            context, shelter_id, observation, request.app.state.clock.now(), idempotency_key
        )
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
    request: Request, context: Annotated[RequestContext, Depends(require_scopes("state:write"))]
) -> dict[str, Any]:
    return request.app.state.shelter_state_store.seed_demo(context, request.app.state.clock.now())


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


@router.post("/what-if/evaluate", tags=["decision-loop"], response_model=None)
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


@router.post("/offline-sync", tags=["operations"], response_model=None)
async def reconcile_offline_commands(
    batch: SyncBatch,
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("operations:write"))],
) -> dict[str, Any]:
    return request.app.state.offline_sync_store.reconcile(
        batch, context.tenant_id, context.workspace_id, request.app.state.clock.now()
    )


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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
):
    try:
        return request.app.state.operations_store.update_readiness(
            context, resource_id, update, request.app.state.clock.now(), idempotency_key
        )
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
):
    _validate_queue_sources(request, context, item)
    try:
        return request.app.state.operations_store.create_queue(
            context,
            item.model_copy(update={"queue_type": "verification"}),
            request.app.state.clock.now(),
            idempotency_key,
        )
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
):
    try:
        return request.app.state.operations_store.create_route_observation(
            context, observation, request.app.state.clock.now(), idempotency_key
        )
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
) -> dict[str, Any]:
    try:
        return request.app.state.operations_store.approve_task(
            context, queue_id, approval, request.app.state.clock.now(), idempotency_key
        )
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
) -> dict[str, Any]:
    try:
        return request.app.state.operations_store.update_task(
            context, task_id, update.status, request.app.state.clock.now(), idempotency_key
        )
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
) -> dict[str, Any]:
    try:
        return request.app.state.operations_store.record_task_outcome(
            context, task_id, outcome, request.app.state.clock.now(), idempotency_key
        )
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
) -> dict[str, Any]:
    try:
        return request.app.state.decision_store.recommend(
            context, request.app.state.clock.now(), idempotency_key
        )
    except IdempotencyConflictError:
        raise ApiProblem(
            status=409,
            code="IDEMPOTENCY_CONFLICT",
            title="Idempotency conflict",
            detail="This key was already used for a different command.",
        ) from None


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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=3, max_length=128)],
) -> dict[str, Any]:
    try:
        return request.app.state.decision_store.decide(
            context, recommendation_id, response, request.app.state.clock.now(), idempotency_key
        )
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


@router.get("/decision-loop/audit", tags=["decision-loop"], response_model=None)
async def decision_audit(
    request: Request,
    context: Annotated[RequestContext, Depends(require_scopes("decision:read"))],
    after: str | None = Query(default=None, max_length=64),
) -> dict[str, Any]:
    items = request.app.state.decision_store.audit(context)
    return {
        "items": [item for item in items if not after or item.get("at", "") > after],
        "next_after": items[-1].get("at") if items else after,
    }
