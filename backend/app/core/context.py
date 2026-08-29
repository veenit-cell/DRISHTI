from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, Request

from app.core.errors import ApiProblem


@dataclass(frozen=True)
class RequestContext:
    actor_id: str
    role: str
    tenant_id: str
    workspace_id: str
    scopes: frozenset[str]
    correlation_id: str


_DEVELOPMENT_IDENTITIES = {
    "operator": {
        "actor_id": "usr_demo_operator",
        "role": "operator",
        "tenant_id": "org_demo",
        "workspace_id": "evt_demo",
        "scopes": frozenset(
            {
                "context:read",
                "system:read",
                "evidence:read",
                "evidence:write",
                "map:read",
                "operations:read",
                "operations:write",
            }
        ),
    },
    "viewer": {
        "actor_id": "usr_demo_viewer",
        "role": "viewer",
        "tenant_id": "org_demo",
        "workspace_id": "evt_demo",
        "scopes": frozenset({"system:read", "evidence:read", "map:read", "operations:read"}),
    },
}


def require_scopes(*required_scopes: str):
    async def dependency(
        request: Request,
        identity_name: Annotated[str | None, Header(alias="X-Dev-Identity")] = None,
    ) -> RequestContext:
        settings = request.app.state.settings
        if settings.app_environment == "production" or not settings.dev_identity_enabled:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="No production identity adapter is configured for this checkpoint.",
            )
        fixture = _DEVELOPMENT_IDENTITIES.get(identity_name or "")
        if fixture is None:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="Select a known non-production identity fixture.",
            )
        missing_scopes = set(required_scopes) - fixture["scopes"]
        if missing_scopes:
            raise ApiProblem(
                status=403,
                code="SCOPE_DENIED",
                title="Required scope denied",
                detail="The current identity is not authorized for this operation.",
            )
        return RequestContext(
            actor_id=fixture["actor_id"],
            role=fixture["role"],
            tenant_id=fixture["tenant_id"],
            workspace_id=fixture["workspace_id"],
            scopes=fixture["scopes"],
            correlation_id=request.state.correlation_id,
        )

    return dependency
