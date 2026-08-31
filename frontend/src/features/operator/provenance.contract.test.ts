import { formatProvenanceLabel } from "./components/CommandBrief";
import type { CommandSummary } from "./api";

export function assertProvenanceRenderingContract(): void {
  const summary: CommandSummary = {
    generated_at: "2026-09-04T10:00:00Z",
    source: "api",
    mode: "mixed",
    metrics: {
      ready_resources: 2,
      total_resources: 4,
      active_tasks: 1,
      response_queue: 1,
      verification_queue: 2,
      population_influx: null,
      water_runway_hours: 3.5,
      contamination: "unknown",
    },
    priorities: [],
    data_quality: { contamination: "unknown", synthetic: false },
    freshness: { state: "stale", as_of: "2026-09-04T09:55:00Z" },
    provenance: {
      source: "lorawan_gateway",
      source_class: "sensor",
      synthetic: false,
      affected_entity_type: "workspace",
      affected_entity_id: "current_workspace",
    },
  };
  const label = formatProvenanceLabel(summary, "Water runway");
  if (!label.includes("sensor") || !label.includes("stale") || !label.includes("lorawan_gateway")) {
    throw new Error("important metrics must expose source class, freshness, and source");
  }
}
