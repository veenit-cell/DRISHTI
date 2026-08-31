from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import install_problem_handlers
from app.core.middleware import (
    CorrelationIdMiddleware,
    IdentityRateLimitMiddleware,
    RequestGuardMiddleware,
)
from app.coverage import CoverageStore, InMemoryCoverageStore, PostgreSQLCoverageStore
from app.decision_loop import InMemoryDecisionStore, PostgreSQLDecisionStore
from app.dependencies import DependencyStore, InMemoryDependencyStore, PostgreSQLDependencyStore
from app.evidence import EvidenceStore, InMemoryEvidenceStore, PostgreSQLEvidenceStore
from app.incident_command import IncidentStore, InMemoryIncidentStore, PostgreSQLIncidentStore
from app.mutual_aid import InMemoryMutualAidStore, MutualAidStore, PostgreSQLMutualAidStore
from app.offline_sync import OfflineSyncStore
from app.operations import InMemoryOperationsStore, OperationsStore, PostgreSQLOperationsStore
from app.persistence import database_ready
from app.pilot_readiness import InMemoryPilotStore, PilotStore, PostgreSQLPilotStore
from app.plans import InMemoryPlanStore, PlanStore, PostgreSQLPlanStore
from app.shelter_state import (
    InMemoryShelterStateStore,
    PostgreSQLShelterStateStore,
    ShelterStateStore,
)
from app.updates import Telemetry, UpdateFeed


def create_app(
    settings: Settings | None = None,
    evidence_store: EvidenceStore | None = None,
    operations_store: OperationsStore | None = None,
    coverage_store: CoverageStore | None = None,
    dependency_store: DependencyStore | None = None,
    plan_store: PlanStore | None = None,
    mutual_aid_store: MutualAidStore | None = None,
    incident_store: IncidentStore | None = None,
    pilot_store: PilotStore | None = None,
    shelter_state_store: ShelterStateStore | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url="/docs" if resolved_settings.app_environment != "production" else None,
        redoc_url=None,
    )
    app.state.settings = resolved_settings
    app.state.clock = clock or SystemClock()
    app.state.offline_sync_store = OfflineSyncStore()
    app.state.update_feed = UpdateFeed()
    app.state.telemetry = Telemetry()
    use_in_memory = (
        operations_store is None
        and resolved_settings.app_environment != "production"
        and not database_ready(resolved_settings.database_url)
    )
    resolved_operations_store = operations_store or (
        InMemoryOperationsStore()
        if use_in_memory
        else PostgreSQLOperationsStore(resolved_settings.database_url)
    )
    app.state.operations_store = resolved_operations_store
    app.state.coverage_store = coverage_store or (
        InMemoryCoverageStore()
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLCoverageStore(resolved_settings.database_url)
    )
    app.state.dependency_store = dependency_store or (
        InMemoryDependencyStore()
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLDependencyStore(resolved_settings.database_url)
    )
    app.state.plan_store = plan_store or (
        InMemoryPlanStore()
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLPlanStore(resolved_settings.database_url)
    )
    app.state.mutual_aid_store = mutual_aid_store or (
        InMemoryMutualAidStore()
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLMutualAidStore(resolved_settings.database_url)
    )
    app.state.incident_store = incident_store or (
        InMemoryIncidentStore()
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLIncidentStore(resolved_settings.database_url)
    )
    app.state.pilot_store = pilot_store or (
        InMemoryPilotStore()
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLPilotStore(resolved_settings.database_url)
    )
    app.state.evidence_store = evidence_store or (
        InMemoryEvidenceStore(app.state.plan_store)
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLEvidenceStore(resolved_settings.database_url, app.state.plan_store)
    )
    app.state.shelter_state_store = shelter_state_store or (
        InMemoryShelterStateStore()
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLShelterStateStore(resolved_settings.database_url)
    )
    app.state.decision_store = (
        InMemoryDecisionStore(
            resolved_operations_store, app.state.dependency_store, app.state.plan_store
        )
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLDecisionStore(
            resolved_settings.database_url,
            resolved_operations_store,
            app.state.dependency_store,
            app.state.plan_store,
        )
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in resolved_settings.allowed_origins],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=[
            "Content-Type",
            "Idempotency-Key",
            "X-Correlation-ID",
            "X-Dev-Identity",
        ],
    )
    app.add_middleware(
        IdentityRateLimitMiddleware,
        limit=60,
        window_seconds=60,
    )
    app.add_middleware(
        RequestGuardMiddleware,
        max_body_bytes=1_000_000,
    )
    app.add_middleware(
        CorrelationIdMiddleware,
        max_length=resolved_settings.max_correlation_id_length,
    )
    install_problem_handlers(app)
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
