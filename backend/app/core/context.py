"""Identity and scope resolution."""
# ruff: noqa: E501

import time
from dataclasses import dataclass
from typing import Annotated, Protocol

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


class OIDCVerifier(Protocol):
    def verify(self, token: str) -> dict[str, object]: ...


class LocalOIDCVerifier:
    """Deterministic test provider; never use this verifier in production."""

    def verify(self, token: str) -> dict[str, object]:
        parts = token.split(":")
        if len(parts) not in {2, 3} or parts[0] != "local" or parts[1] not in _DEVELOPMENT_IDENTITIES:
            raise ValueError("invalid local identity token")
        if len(parts) == 3 and (not parts[2].isdigit() or int(parts[2]) <= time.time()):
            raise ValueError("expired local identity token")
        return _DEVELOPMENT_IDENTITIES[parts[1]]


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
                "decision:read",
                "decision:write",
                "state:read",
                "state:write",
            }
        ),
    },
    "viewer": {
        "actor_id": "usr_demo_viewer",
        "role": "viewer",
        "tenant_id": "org_demo",
        "workspace_id": "evt_demo",
        "scopes": frozenset(
            {
                "system:read",
                "evidence:read",
                "map:read",
                "operations:read",
                "decision:read",
                "state:read",
            }
        ),
    },
}


def require_scopes(*required_scopes: str):
    async def dependency(
        request: Request,
        identity_name: Annotated[str | None, Header(alias="X-Dev-Identity")] = None,
    ) -> RequestContext:
        settings = request.app.state.settings
        bearer = request.headers.get("authorization", "")
        if bearer.startswith("Bearer "):
            try:
                fixture = LocalOIDCVerifier().verify(bearer[7:])
            except ValueError:
                raise ApiProblem(status=401, code="AUTHENTICATION_REQUIRED", title="Authentication required", detail="The identity token is invalid or expired.") from None
        elif settings.app_environment == "production" or not settings.dev_identity_enabled:
            raise ApiProblem(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="No production identity adapter is configured for this checkpoint.",
            )
        else:
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
