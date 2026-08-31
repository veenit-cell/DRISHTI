# Phase 1 Development Roles and Scopes

The production identity provider and partner-approved role mapping are unresolved. Phase 1 therefore exposes only deterministic non-production fixtures and rejects them in production configuration.

| Fixture | Role | Tenant | Workspace | Scopes |
|---|---|---|---|---|
| `operator` | operator | `org_demo` | `evt_demo` | `context:read`, `system:read`, `evidence:read`, `evidence:write`, `map:read`, `operations:read`, `operations:write`, `decision:read`, `decision:write`, `state:read`, `state:write` |
| `viewer` | viewer | `org_demo` | `evt_demo` | `system:read`, `evidence:read`, `map:read`, `operations:read`, `decision:read`, `state:read` |

Rules:

- No fixture is selected when `X-Dev-Identity` is absent or unknown.
- Scope checks are server-side and deny by default.
- The fixture owns its tenant and workspace; callers cannot choose arbitrary scope identifiers.
- The fixture is a development mechanism, not an authentication claim or production credential.
- Pilot configuration uses existing `decision:write`; feed intake uses `evidence:write`. These are convenience scopes for the MVP, not a production role design.
