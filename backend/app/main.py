from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import install_problem_handlers
from app.core.middleware import CorrelationIdMiddleware, RequestGuardMiddleware
from app.decision_loop import InMemoryDecisionStore, PostgreSQLDecisionStore
from app.evidence import EvidenceStore, PostgreSQLEvidenceStore
from app.offline_sync import OfflineSyncStore
from app.operations import InMemoryOperationsStore, OperationsStore, PostgreSQLOperationsStore
from app.shelter_state import PostgreSQLShelterStateStore, ShelterStateStore


def create_app(
    settings: Settings | None = None,
    evidence_store: EvidenceStore | None = None,
    operations_store: OperationsStore | None = None,
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
    app.state.evidence_store = evidence_store or PostgreSQLEvidenceStore(
        resolved_settings.database_url
    )
    resolved_operations_store = operations_store or PostgreSQLOperationsStore(
        resolved_settings.database_url
    )
    app.state.operations_store = resolved_operations_store
    app.state.shelter_state_store = shelter_state_store or PostgreSQLShelterStateStore(
        resolved_settings.database_url
    )
    app.state.decision_store = (
        InMemoryDecisionStore(resolved_operations_store)
        if isinstance(resolved_operations_store, InMemoryOperationsStore)
        else PostgreSQLDecisionStore(resolved_settings.database_url, resolved_operations_store)
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
