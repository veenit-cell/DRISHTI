import type { ScenarioComparison, WhatIfResult } from "./api";
import { SCENARIO_LAB_LABELS } from "./components/ScenarioLab";

export function assertScenarioLabContract(result: WhatIfResult): void {
  if (Object.keys(SCENARIO_LAB_LABELS).length !== 6) throw new Error("scenario lab must expose all six supported scenario changes");
  const comparisons: ScenarioComparison[] = [result.baseline, result.do_nothing, result.intervention];
  if (comparisons.some((comparison) => !comparison.scenario_hash)) throw new Error("scenario comparisons require hashes");
  if (comparisons.some((comparison) => !comparison.projection.projections.length)) throw new Error("scenario comparisons require runway projections");
  if (comparisons.some((comparison) => !comparison.risk_level)) throw new Error("scenario comparisons require operational risk level");
  if (!result.intervention.uncertainty.length) throw new Error("simulations require explicit uncertainty");
}
