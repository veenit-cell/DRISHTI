import { useState } from "react";
import { evaluateWhatIf, type ScenarioComparison, type WhatIfIntervention, type WhatIfKind, type WhatIfResult, type RunwaySnapshotInput } from "../api";

type ScenarioLabProps = {
  mode?: "live" | "synthetic" | "mixed";
  onApplyRecommendation?: (comparison: ScenarioComparison) => void;
  onScenarioEvaluated?: (comparison: ScenarioComparison) => void;
};

const DEFAULT_RUNWAY_SNAPSHOT: RunwaySnapshotInput = {
  observed_at: new Date().toISOString(),
  freshness_state: "unknown",
  field_freshness: {},
  values: {
    population: 1800,
    population_influx_per_hour: 180,
    potable_water_liters: 4200,
    water_consumption_liters_per_hour: 420,
    replenishment_liters_per_hour: 0,
    battery_percent: 31,
    battery_capacity_kwh: 100,
    power_consumption_kw: 18,
    battery_replenishment_kw: 0,
    medicine_units: 240,
    medicine_consumption_per_hour: 20,
    cold_chain_hours: 8,
    cold_chain_depletion_hours_per_hour: 1,
  },
  units: {
    population: "people",
    population_influx_per_hour: "people/hour",
    potable_water_liters: "liters",
    water_consumption_liters_per_hour: "liters/hour",
    replenishment_liters_per_hour: "liters/hour",
    battery_percent: "percent",
    battery_capacity_kwh: "kilowatt-hours",
    power_consumption_kw: "kilowatts",
    battery_replenishment_kw: "kilowatts",
    medicine_units: "units",
    medicine_consumption_per_hour: "units/hour",
    cold_chain_hours: "hours",
    cold_chain_depletion_hours_per_hour: "hours/hour",
  },
  thresholds: { potable_water_liters: 1000, battery_percent: 20, medicine_units: 40, cold_chain_hours: 2 },
};

export const SCENARIO_LAB_LABELS: Record<WhatIfKind, string> = {
  population_influx: "Population influx",
  water_contamination: "Water contamination",
  battery_reduction: "Battery reduction",
  purification_unavailable: "Purification unavailable",
  route_blockage: "Route blockage",
  resource_transfer: "Resource transfer",
};

function minimumTime(comparison: ScenarioComparison): string {
  const times = comparison.projection.projections.map((item) => item.time_to_critical_hours).filter((item): item is number => item != null);
  return times.length ? `${Math.min(...times)} h` : "Unknown";
}

function overallConfidence(comparison: ScenarioComparison): string {
  if (comparison.projection.projections.some((item) => item.confidence === "low")) return "Low";
  if (comparison.projection.projections.some((item) => item.confidence === "medium")) return "Medium";
  return "Unknown";
}

function consumptionSummary(comparison: ScenarioComparison): string {
  const consumption = comparison.resource_consumption;
  return `${consumption.water_liters_per_hour ?? "?"} L/h water · ${consumption.power_kilowatts ?? "?"} kW power · ${consumption.medicine_units_per_hour ?? "?"} units/h medicine`;
}

function interventionFor(kind: WhatIfKind, influx: number, contamination: number, batteryReduction: number, purificationUnavailable: boolean, routeBlocked: boolean, transferType: "potable_water" | "medicine", transferAmount: number): WhatIfIntervention {
  if (kind === "population_influx") return { kind, amount: influx, unit: "people/hour" };
  if (kind === "water_contamination") return { kind, amount: contamination, unit: "percent" };
  if (kind === "battery_reduction") return { kind, amount: batteryReduction, unit: "percent" };
  if (kind === "purification_unavailable") return { kind, enabled: purificationUnavailable };
  if (kind === "route_blockage") return { kind, enabled: routeBlocked };
  return { kind, amount: transferAmount, unit: transferType === "potable_water" ? "liters" : "units", resource_type: transferType, source_resource: "Scenario transfer source" };
}

export function ScenarioLab({ mode = "synthetic", onApplyRecommendation, onScenarioEvaluated }: ScenarioLabProps) {
  const [kind, setKind] = useState<WhatIfKind>("population_influx");
  const [influx, setInflux] = useState(360);
  const [contamination, setContamination] = useState(60);
  const [batteryReduction, setBatteryReduction] = useState(20);
  const [purificationUnavailable, setPurificationUnavailable] = useState(true);
  const [routeBlocked, setRouteBlocked] = useState(true);
  const [transferType, setTransferType] = useState<"potable_water" | "medicine">("potable_water");
  const [transferAmount, setTransferAmount] = useState(500);
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [commanderConfirmed, setCommanderConfirmed] = useState(false);
  const [applied, setApplied] = useState(false);

  async function runSimulation() {
    setState("loading");
    setApplied(false);
    try {
      const intervention = interventionFor(kind, influx, contamination, batteryReduction, purificationUnavailable, routeBlocked, transferType, transferAmount);
      const nextResult = await evaluateWhatIf(DEFAULT_RUNWAY_SNAPSHOT, intervention);
      setResult(nextResult);
      onScenarioEvaluated?.(nextResult.intervention);
      setState("ready");
    } catch {
      setResult(null);
      setState("error");
    }
  }

  function applyAsRecommendation() {
    if (!result || !commanderConfirmed) return;
    onApplyRecommendation?.(result.intervention);
    setApplied(true);
  }

  const comparisons = result ? [result.baseline, result.do_nothing, result.intervention] : [];
  return (
    <section className="scenario-lab" aria-labelledby="scenario-lab-heading">
      <div className="scenario-lab-heading">
        <div>
          <p className="eyebrow">Scenario Lab</p>
          <h2 id="scenario-lab-heading">Simulate a change before acting</h2>
          <p className="scenario-lab-note">Simulation only. This panel evaluates explicit inputs against a bounded demonstration snapshot and never changes operational state.</p>
        </div>
        <span className="semantic-status status-warning">{mode === "synthetic" ? "Synthetic simulation" : "Simulation only · no live mutation"}</span>
      </div>

      <div className="scenario-controls">
        <label className="scenario-control scenario-control-wide">Scenario change
          <select value={kind} onChange={(event) => { setKind(event.target.value as WhatIfKind); setCommanderConfirmed(false); }}>
            {(Object.keys(SCENARIO_LAB_LABELS) as WhatIfKind[]).map((option) => <option key={option} value={option}>{SCENARIO_LAB_LABELS[option]}</option>)}
          </select>
        </label>

        <label className="scenario-control">Population influx: <output>{influx} people/hour</output>
          <input type="range" min="0" max="600" step="20" value={influx} onChange={(event) => setInflux(Number(event.target.value))} />
        </label>
        <label className="scenario-control">Water contamination: <output>{contamination}%</output>
          <input type="range" min="0" max="100" step="5" value={contamination} onChange={(event) => setContamination(Number(event.target.value))} />
        </label>
        <label className="scenario-control">Battery reduction: <output>{batteryReduction} percentage points</output>
          <input type="range" min="1" max="80" step="1" value={batteryReduction} onChange={(event) => setBatteryReduction(Number(event.target.value))} />
        </label>
        <label className="scenario-toggle"><input type="checkbox" checked={purificationUnavailable} onChange={(event) => setPurificationUnavailable(event.target.checked)} /> Purification unavailable</label>
        <label className="scenario-toggle"><input type="checkbox" checked={routeBlocked} onChange={(event) => setRouteBlocked(event.target.checked)} /> Route blocked</label>
        <label className="scenario-control">Transfer type
          <select value={transferType} onChange={(event) => setTransferType(event.target.value as "potable_water" | "medicine")}>
            <option value="potable_water">Potable water</option>
            <option value="medicine">Medicine</option>
          </select>
        </label>
        <label className="scenario-control">Transfer amount: <output>{transferAmount} {transferType === "potable_water" ? "liters" : "units"}</output>
          <input type="range" min="50" max="1000" step="50" value={transferAmount} onChange={(event) => setTransferAmount(Number(event.target.value))} />
        </label>
      </div>

      <div className="scenario-actions">
        <button type="button" className="btn-primary" onClick={() => void runSimulation()} disabled={state === "loading"}>
          {state === "loading" ? "Evaluating simulation…" : "Run simulation"}
        </button>
        <span className="scenario-state" role={state === "error" ? "alert" : "status"}>
          {state === "error" ? "Simulation unavailable. Check the decision service and retry." : state === "ready" ? `Scenario hash: ${result?.intervention.scenario_hash}` : "No simulation run yet."}
        </span>
      </div>

      {state === "ready" && result && (
        <>
        <div className="scenario-comparison" role="region" aria-label="Scenario comparison">
            <table>
              <caption>Simulation comparison</caption>
              <thead><tr><th scope="col">Metric</th>{comparisons.map((comparison) => <th scope="col" key={comparison.label}>{comparison.label.replace("_", " ")}</th>)}</tr></thead>
              <tbody>
                <tr><th scope="row">Time to critical state</th>{comparisons.map((comparison) => <td key={`${comparison.label}-time`}>{minimumTime(comparison)}</td>)}</tr>
                <tr><th scope="row">Resource consumption</th>{comparisons.map((comparison) => <td key={`${comparison.label}-consumption`}>{consumptionSummary(comparison)}</td>)}</tr>
                <tr><th scope="row">Operational risk level</th>{comparisons.map((comparison) => <td key={`${comparison.label}-risk`}>{comparison.risk_level}</td>)}</tr>
                <tr><th scope="row">Confidence</th>{comparisons.map((comparison) => <td key={`${comparison.label}-confidence`}>{overallConfidence(comparison)}</td>)}</tr>
              </tbody>
            </table>
          </div>
          <div className="scenario-explanation">
            <div><strong>Changed inputs</strong><p>{Object.entries(result.intervention.changed_inputs).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`).join(" · ") || "None"}</p></div>
            <div><strong>Tradeoffs</strong><ul>{result.intervention.tradeoffs.map((item) => <li key={item}>{item}</li>)}</ul></div>
            <div><strong>Uncertainty</strong><ul>{result.intervention.uncertainty.map((item) => <li key={item}>{item}</li>)}</ul></div>
          </div>
          <div className="scenario-approval">
            <label><input type="checkbox" checked={commanderConfirmed} onChange={(event) => setCommanderConfirmed(event.target.checked)} /> I understand this remains a recommendation and requires commander approval.</label>
            <button type="button" className="btn-secondary" disabled={!commanderConfirmed || applied} onClick={applyAsRecommendation}>{applied ? "Recommendation draft prepared" : "Apply as recommendation draft"}</button>
            {applied && <span role="status">Prepared for the existing approval workflow; no dispatch or operational mutation occurred.</span>}
          </div>
        </>
      )}
    </section>
  );
}
