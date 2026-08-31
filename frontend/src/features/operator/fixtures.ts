export type Projection = { resource: string; time: string; state: string; freshness: string };
export type Candidate = { action: string; actionId?: string; rank: number; confidence: string; effect: string; cost: string; excluded: string };
export type Verification = { cell_id: string; fact_type: string; population: number; debt_score: number; debt_band: string; reporting_impaired: boolean; decision_impact_score: number; plan_ids_affected: string[]; what_answer_changes: string; rank: number };
export type Unlock = { action: string; target_node_id: string; downstream_nodes_unlocked: string[]; missions_unlocked: string[]; mission_unlock_value: number; rank: number };
export type Plan = { plan_id: string; status: string; objective_summary: string; fragility: number; assumptions: { assumption_id: string; subject_type: string; subject_id: string; expected_state: string; sensitivity: string; valid_until?: string | null }[] };
export type ResourceForecast = { forecast_id: string; resource_type: string; current_quantity: number; projected_quantity: number; reserve_floor: number; hours_to_reserve: number | null; request_recommended: boolean; location: string };
export type ResourceRequest = { request_id: string; resource_type: string; quantity: number; reserve_floor: number; location: string; need_by: string; status: string; source_reality: string };
export type WorkspaceData = { projections: Projection[]; candidates: Candidate[]; evidence: { id: string; claim: string; state: string; source: string }[]; resources: { id: string; name: string; readiness: string; route: string; task: string }[]; queue: { id: string; title: string; status: string }[]; tasks: { id: string; resource: string; status: string; outcome: string }[]; places: { id: string; label: string; state: string; coordinates: string }[]; verification: Verification[]; unlocks: Unlock[]; plans: Plan[]; forecasts: ResourceForecast[]; resourceRequests: ResourceRequest[] };

export const demoWorkspace: WorkspaceData = {
  projections: [{ resource: "Potable water", time: "3.5 h", state: "critical next", freshness: "Fresh · runway_v1" }, { resource: "Battery / power", time: "5.1 h", state: "projected", freshness: "Fresh · runway_v1" }, { resource: "Medicine cold chain", time: "8.0 h", state: "projected", freshness: "Stale · verify" }],
  candidates: [{ action: "Deliver / treat water", rank: 1, confidence: "Medium", effect: "+4 h safe-water runway (synthetic)", cost: "Water team · 4 kW", excluded: "med-van: missing water_delivery" }, { action: "Shift non-critical power", rank: 2, confidence: "High", effect: "Protects purification and cold chain", cost: "Operator · 2 kW shifted", excluded: "water-team: missing power_management" }, { action: "Request medicine / cold-chain support", rank: 3, confidence: "Low · stale input", effect: "Requests reserve replenishment", cost: "Medical support · route unknown", excluded: "med-van: route not confirmed" }],
  evidence: [{ id: "rpt_demo_01", claim: "North Sector water contamination", state: "corroborated", source: "synthetic_demo_seed · rev 2 · 10:30Z" }, { id: "rpt_demo_02", claim: "Population influx +180", state: "contradicted / visible", source: "field report · rev 1 · 10:18Z" }],
  resources: [{ id: "water-1", name: "Water Team Alpha", readiness: "READY", route: "Passable · expires 14:00Z", task: "Unassigned" }, { id: "power-1", name: "Generator Unit", readiness: "READY", route: "Passable · expires 16:00Z", task: "Active task · excluded" }, { id: "med-1", name: "Medical Van", readiness: "NOT READY", route: "Unknown", task: "Unassigned" }],
  queue: [{ id: "q-101", title: "Protect North Sector water", status: "Queued" }, { id: "q-102", title: "Verify influx report", status: "Verification" }],
  tasks: [{ id: "task-7", resource: "Generator Unit", status: "en_route", outcome: "Outcome pending" }],
  places: [{ id: "inc_demo_north", label: "North Sector · water contamination", state: "suspected", coordinates: "91.742, 26.184" }, { id: "inc_demo_east", label: "East Sector · medical access", state: "unassessed", coordinates: "91.756, 26.191" }, { id: "inc_demo_west", label: "West Sector · access blocked", state: "confirmed", coordinates: "91.728, 26.176" }],
  verification: [],
  unlocks: [],
  plans: [],
  forecasts: [],
  resourceRequests: [],
};
