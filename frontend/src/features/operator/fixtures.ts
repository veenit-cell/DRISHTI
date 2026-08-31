export type Projection = { resource: string; time: string; state: string; freshness: string };

export type DecisionModel = {
  need: "Low" | "Medium" | "High" | "Critical";
  confidence: "Low" | "Medium" | "High";
  feasibility: "Feasible" | "Constrained" | "Infeasible" | "Unknown";
};

export type Candidate = {
  action: string;
  actionId?: string;
  rank: number;
  confidence: string;
  effect: string;
  cost: string;
  excluded: string;
  priorityReason?: string;
  evidenceAvailable?: string;
  importantUnknowns?: string;
  resourceAvailability?: string;
  routeAccessibility?: string;
  decisionModel?: DecisionModel;
};

export type Verification = {
  cell_id: string;
  fact_type: string;
  population: number;
  debt_score: number;
  debt_band: string;
  reporting_impaired: boolean;
  decision_impact_score: number;
  plan_ids_affected: string[];
  what_answer_changes: string;
  rank: number;
};

export type Unlock = {
  action: string;
  target_node_id: string;
  downstream_nodes_unlocked: string[];
  missions_unlocked: string[];
  mission_unlock_value: number;
  rank: number;
};

export type Plan = {
  plan_id: string;
  status: string;
  objective_summary: string;
  fragility: number;
  assumptions: {
    assumption_id: string;
    subject_type: string;
    subject_id: string;
    expected_state: string;
    sensitivity: string;
    valid_until?: string | null;
  }[];
};

export type ResourceForecast = {
  forecast_id: string;
  resource_type: string;
  current_quantity: number;
  projected_quantity: number;
  reserve_floor: number;
  hours_to_reserve: number | null;
  request_recommended: boolean;
  location: string;
};

export type ResourceRequest = {
  request_id: string;
  resource_type: string;
  quantity: number;
  reserve_floor: number;
  location: string;
  need_by: string;
  status: string;
  source_reality: string;
};

export type ResourceItem = {
  id: string;
  name: string;
  readiness: string;
  route: string;
  task: string;
  category?: "boat" | "medical_team" | "excavator" | "sar_team" | "water_team" | "power_unit" | "other";
  feasibility?: "feasible" | "constrained" | "infeasible" | "unknown";
};

export type PlaceItem = {
  id: string;
  label: string;
  state: string;
  coordinates: string;
  isSilent?: boolean;
  informationGap?: boolean;
  routeFeasibility?: "open" | "blocked" | "degraded" | "unknown" | "high_risk";
  decisionModel?: DecisionModel;
};

export type EvidenceItem = {
  id: string;
  claim: string;
  state: "corroborated" | "proposed" | "contradicted" | "unknown" | string;
  source: string;
  severity?: "critical" | "high" | "moderate" | "low";
  classification?: "Confirmed" | "Unverified" | "Contradictory" | "Unknown / Needs Verification";
};

export type WorkspaceData = {
  projections: Projection[];
  candidates: Candidate[];
  evidence: EvidenceItem[];
  resources: ResourceItem[];
  queue: { id: string; title: string; status: string; source_recommendation_id?: string | null }[];
  tasks: { id: string; resource: string; status: string; outcome: string }[];
  places: PlaceItem[];
  verification: Verification[];
  unlocks: Unlock[];
  plans: Plan[];
  forecasts: ResourceForecast[];
  resourceRequests: ResourceRequest[];
};

export const demoWorkspace: WorkspaceData = {
  projections: [
    { resource: "Potable water", time: "3.5 h", state: "critical next", freshness: "Fresh · runway_v1" },
    { resource: "Battery / power", time: "5.1 h", state: "projected", freshness: "Fresh · runway_v1" },
    { resource: "Medicine cold chain", time: "8.0 h", state: "projected", freshness: "Stale · verify" },
  ],
  candidates: [
    {
      action: "Deliver / treat water",
      rank: 1,
      confidence: "Medium",
      effect: "+4 h safe-water runway (synthetic)",
      cost: "Water team · 4 kW",
      excluded: "med-van: missing water_delivery",
      priorityReason: "North Sector potable water runway (3.5h) is below the 6.0h critical threshold with 180 incoming evacuees.",
      evidenceAvailable: "Corroborated sensor telemetry + drone reconnaissance (rpt_demo_01, rpt_demo_02).",
      importantUnknowns: "INFORMATION GAP: Dharapur Village silent (0 reports, pop: 4,200); West corridor bridge unassessed.",
      resourceAvailability: "FEASIBLE: Synthetic Water Team Alpha & Rescue Boat 1 ready on scene.",
      routeAccessibility: "NH-27 Highway Open; West Bank River Corridor Degraded / Blocked.",
      decisionModel: { need: "Critical", confidence: "Medium", feasibility: "Feasible" },
    },
    {
      action: "Shift non-critical power",
      rank: 2,
      confidence: "High",
      effect: "Protects purification and cold chain",
      cost: "Operator · 2 kW shifted",
      excluded: "water-team: missing power_management",
      priorityReason: "Protects cold chain and water purification pumps from cascading electric grid outage.",
      evidenceAvailable: "Central Shelter load reports and infrastructure dependency model.",
      importantUnknowns: "Fuel reserve delivery status unknown for East corridor.",
      resourceAvailability: "FEASIBLE: Generator Unit ready at Central Shelter.",
      routeAccessibility: "Central road network Open.",
      decisionModel: { need: "High", confidence: "High", feasibility: "Feasible" },
    },
    {
      action: "Request medicine / cold-chain support",
      rank: 3,
      confidence: "Low · stale input",
      effect: "Requests reserve replenishment",
      cost: "Medical support · route unknown",
      excluded: "med-van: route not confirmed",
      priorityReason: "Replenishes depleted insulin and anti-venom supplies before nightfall.",
      evidenceAvailable: "Stale clinic inventory report from 10:00Z.",
      importantUnknowns: "Road passability past milestone 14 unverified.",
      resourceAvailability: "CONSTRAINED: Medical Team ready but transport constrained.",
      routeAccessibility: "Route degraded by mud and debris.",
      decisionModel: { need: "High", confidence: "Low", feasibility: "Constrained" },
    },
  ],
  evidence: [
    {
      id: "rpt_demo_01",
      claim: "North Sector water supply contaminated by flood breach (Severe)",
      state: "corroborated",
      classification: "Confirmed",
      source: "synthetic_demo_seed · rev 2 · 10:30Z",
      severity: "critical",
    },
    {
      id: "rpt_demo_02",
      claim: "Population influx +180 arriving at relief camp",
      state: "contradicted",
      classification: "Contradictory",
      source: "field report · rev 1 · 10:18Z (Contradicts drone count of 60)",
      severity: "moderate",
    },
    {
      id: "rpt_demo_03",
      claim: "Dharapur Village — zero communications received (Information Gap)",
      state: "unknown",
      classification: "Unknown / Needs Verification",
      source: "Automated network watchdog · 0 reports in 6h",
      severity: "high",
    },
    {
      id: "rpt_demo_04",
      claim: "NH-27 Highway Bridge washed out near Km 18",
      state: "corroborated",
      classification: "Confirmed",
      source: "Public Works Department + Drone Survey",
      severity: "critical",
    },
  ],
  resources: [
    { id: "water-1", name: "Synthetic Water Team Alpha", readiness: "READY", route: "Passable (Open)", task: "Unassigned", category: "water_team", feasibility: "feasible" },
    { id: "boat-1", name: "Synthetic Rescue Boat 1", readiness: "READY", route: "Waterway Navigable (Open)", task: "Unassigned", category: "boat", feasibility: "feasible" },
    { id: "med-team-1", name: "Synthetic Medical Team Beta", readiness: "READY", route: "Passable with delay (Degraded)", task: "Unassigned", category: "medical_team", feasibility: "constrained" },
    { id: "excavator-1", name: "Synthetic Heavy Excavator Unit", readiness: "NOT READY", route: "Awaiting lowbed (Infeasible)", task: "Maintenance", category: "excavator", feasibility: "infeasible" },
    { id: "sar-1", name: "Synthetic SAR Team Charlie", readiness: "READY", route: "Passable (Open)", task: "Unassigned", category: "sar_team", feasibility: "feasible" },
    { id: "power-1", name: "Synthetic Generator Unit", readiness: "READY", route: "Passable (Open)", task: "Active task · excluded", category: "power_unit", feasibility: "feasible" },
    { id: "med-1", name: "Synthetic Medical Van", readiness: "NOT READY", route: "Unknown", task: "Unassigned", category: "other", feasibility: "infeasible" },
  ],
  queue: [
    { id: "q-101", title: "Protect North Sector water continuity", status: "Queued" },
    { id: "q-102", title: "Verify Dharapur silent village (Reconnaissance)", status: "Verification" },
  ],
  tasks: [
    { id: "task-7", resource: "Synthetic Generator Unit", status: "en_route", outcome: "Outcome pending" },
  ],
  places: [
    {
      id: "inc_demo_north",
      label: "North Sector · water contamination (Severe)",
      state: "confirmed",
      coordinates: "91.742, 26.184",
      routeFeasibility: "open",
      decisionModel: { need: "Critical", confidence: "High", feasibility: "Feasible" },
    },
    {
      id: "inc_demo_dharapur",
      label: "Dharapur Village · Silent Settlement (0 reports)",
      state: "silent",
      coordinates: "91.710, 26.190",
      isSilent: true,
      informationGap: true,
      routeFeasibility: "unknown",
      decisionModel: { need: "High", confidence: "Low", feasibility: "Unknown" },
    },
    {
      id: "inc_demo_bridge",
      label: "NH-27 Highway Bridge · Washout",
      state: "blocked",
      coordinates: "91.765, 26.185",
      routeFeasibility: "blocked",
      decisionModel: { need: "Critical", confidence: "High", feasibility: "Infeasible" },
    },
    {
      id: "inc_demo_west",
      label: "West Sector · access blocked",
      state: "degraded",
      coordinates: "91.728, 26.176",
      routeFeasibility: "degraded",
      decisionModel: { need: "Medium", confidence: "Medium", feasibility: "Constrained" },
    },
  ],
  verification: [],
  unlocks: [],
  plans: [],
  forecasts: [],
  resourceRequests: [],
};
