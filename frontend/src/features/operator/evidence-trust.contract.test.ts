import type { EvidenceReport } from "./api";
import { evidenceClassification, evidenceFreshness, highDecisionImpact } from "./components/EvidenceTrustPanel";

const report = (overrides: Partial<EvidenceReport> = {}): EvidenceReport => ({
  id: "report-1",
  report_type: "life_safety",
  status: "accepted_for_review",
  source: { channel: "operator_report_desk", source_class: "authenticated_operator" },
  observed_at: "2026-09-04T08:00:00Z",
  received_at: "2026-09-04T08:05:00Z",
  recorded_at: "2026-09-04T08:05:00Z",
  location: { place_text: "North Sector" },
  warnings: [],
  revision: 1,
  ...overrides,
});

export function assertEvidenceTrustContract(): void {
  const contradictory = report({
    status: "reviewed",
    warnings: ["Conflicting field observations"],
  });
  if (evidenceClassification(contradictory) !== "contradictory") throw new Error("contradictory evidence must be filterable");

  const stale = report({ observed_at: "2026-09-03T00:00:00Z" });
  if (evidenceFreshness(stale, Date.parse("2026-09-04T08:00:00Z")) !== "stale") throw new Error("stale evidence must remain visible as stale");
  if (!highDecisionImpact(contradictory)) throw new Error("contradictory evidence must be marked high decision impact");
}
