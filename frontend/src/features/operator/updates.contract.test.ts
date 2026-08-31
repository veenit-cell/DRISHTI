import { OPERATIONAL_UPDATE_TYPES, type OperationalUpdate } from "./api";
import { affectedSectionsForUpdate } from "./OperatorWorkspace";

export function assertOperationalUpdateContract(): void {
  if (OPERATIONAL_UPDATE_TYPES.length !== 9) throw new Error("all operational update types are required");

  const event: OperationalUpdate = {
    event_type: "resource_readiness_changed",
    cursor: "42",
    occurred_at: "2026-09-03T10:00:00Z",
    source: "operations_api",
    source_class: "operator_report",
    correlation_id: "corr-test",
    affected_entity_type: "resource",
    affected_entity_id: "resource-1",
    payload: { status: "ready" },
  };
  if (!event.cursor || !event.occurred_at || !event.source || !event.source_class || !event.correlation_id || !event.affected_entity_id) {
    throw new Error("operational update envelope is incomplete");
  }
  if (!affectedSectionsForUpdate(event.event_type).includes("resources")) {
    throw new Error("resource updates must refresh the resources section");
  }
}
