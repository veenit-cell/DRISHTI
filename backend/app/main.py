from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import install_problem_handlers
from app.core.middleware import CorrelationIdMiddleware
from app.decision_loop import InMemoryDecisionStore
from app.evidence import EvidenceStore, PostgreSQLEvidenceStore
from app.operations import InMemoryOperationsStore


def create_app(
    settings: Settings | None = None,
    evidence_store: EvidenceStore | None = None,
    operations_store: InMemoryOperationsStore | None = None,
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
    app.state.evidence_store = evidence_store or PostgreSQLEvidenceStore(
        resolved_settings.database_url
    )
    app.state.operations_store = operations_store or InMemoryOperationsStore()
    app.state.decision_store = InMemoryDecisionStore(app.state.operations_store)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in resolved_settings.allowed_origins],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Content-Type", "X-Correlation-ID", "X-Dev-Identity"],
    )
    app.add_middleware(
        CorrelationIdMiddleware,
        max_length=resolved_settings.max_correlation_id_length,
    )
    install_problem_handlers(app)
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
