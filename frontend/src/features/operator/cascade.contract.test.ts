import type { CascadeFinding } from "./api";
import { findingFreshness } from "./components/CascadePanel";

const finding = (overrides: Partial<CascadeFinding> = {}): CascadeFinding => ({
  affected_capability: "safe_water_runway",
  severity: "high",
  estimated_time_window_hours: 3.5,
  causal_path: ["power", "water_purification", "safe_water_runway"],
  supporting_input_refs: ["fixture:power"],
  unknown_contributors: [],
  confidence: "high",
  rule_version: "cascade_v1",
  ...overrides,
});

export function assertCascadePanelContract(): void {
  if (findingFreshness(finding()) !== "fresh") throw new Error("complete cascade path should be fresh");
  if (findingFreshness(finding({ unknown_contributors: ["stale:water_runway_hours"] })) !== "stale") {
    throw new Error("stale cascade input should remain visible");
  }
  if (findingFreshness(finding({ unknown_contributors: ["contradictory:power_available"] })) !== "uncertain") {
    throw new Error("contradictory cascade input should remain uncertain");
  }
  if (findingFreshness(finding({ unknown_contributors: ["unknown:purification_available"] })) !== "uncertain") {
    throw new Error("unknown cascade input should remain uncertain");
  }
}
