from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.context import RequestContext, require_scopes
from app.core.errors import Problem, problem_response
from app.persistence import database_ready

router = APIRouter()


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
