import { demoWorkspace, type Plan, type ResourceForecast, type ResourceRequest, type Unlock, type Verification, type WorkspaceData } from "./fixtures";

const newCorrelationId = () => `ui-${Date.now()}-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
const headers = (key?: string, correlationId = newCorrelationId()) => ({ "Content-Type": "application/json", "X-Dev-Identity": "operator", "X-Correlation-ID": correlationId, ...(key ? { "Idempotency-Key": key } : {}) });

type IdempotencyHandle = { key: string; storageKey: string; createdAt: string; retain?: boolean };
type RequestInitWithIdempotency = RequestInit & { idempotency?: IdempotencyHandle };
type StoredIdempotencyKey = { key: string; expiresAt: number; createdAt: string };

const pendingIdempotencyKeys = new Map<string, StoredIdempotencyKey>();
const IDEMPOTENCY_TTL_MS = 24 * 60 * 60 * 1000;

function stableFingerprint(value: unknown): string {
  const canonicalize = (input: unknown): unknown => {
    if (Array.isArray(input)) return input.map(canonicalize);
    if (input && typeof input === "object") {
      return Object.fromEntries(Object.entries(input as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonicalize(item)]));
    }
    return input;
  };
  const text = JSON.stringify(canonicalize(value));
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function idempotencyHandle(namespace: string, payload: unknown): IdempotencyHandle {
  const fingerprint = stableFingerprint({ namespace, payload });
  const storageKey = `drishti:idempotency:${namespace}:${fingerprint}`;
  const now = Date.now();
  let stored: StoredIdempotencyKey | null = pendingIdempotencyKeys.get(storageKey) ?? null;
  try {
    const raw = sessionStorage.getItem(storageKey);
    stored = raw ? JSON.parse(raw) as StoredIdempotencyKey : stored;
  } catch {
    // Session storage can be unavailable in restricted browser contexts; the in-memory key still covers retries in this tab.
  }
  if (!stored || stored.expiresAt <= now) {
    stored = { key: `ui-${namespace}-${fingerprint}-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`.slice(0, 128), expiresAt: now + IDEMPOTENCY_TTL_MS, createdAt: new Date(now).toISOString() };
    pendingIdempotencyKeys.set(storageKey, stored);
    try { sessionStorage.setItem(storageKey, JSON.stringify(stored)); } catch { /* best effort */ }
  }
  if (!stored.createdAt) stored.createdAt = new Date(now).toISOString();
  pendingIdempotencyKeys.set(storageKey, stored);
  return { key: stored.key, storageKey, createdAt: stored.createdAt };
}

function clearIdempotencyHandle(handle: IdempotencyHandle | undefined): void {
  if (!handle) return;
  pendingIdempotencyKeys.delete(handle.storageKey);
  try { sessionStorage.removeItem(handle.storageKey); } catch { /* best effort */ }
}

async function request<T>(path: string, init: RequestInitWithIdempotency = {}): Promise<T> {
  const { idempotency, ...fetchInit } = init;
  const requestHeaders = new Headers(fetchInit.headers);
  if (!requestHeaders.has("X-Correlation-ID")) requestHeaders.set("X-Correlation-ID", newCorrelationId());
  const response = await fetch(`/api/v1${path}`, { ...fetchInit, headers: requestHeaders });
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("json")) {
    throw new Error(`API endpoint unavailable (received ${contentType || "HTML"} response)`);
  }
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    const error = new Error(problem.detail ?? `API request failed (${response.status})`);
    Object.assign(error, { problem });
    throw error;
  }
  const result = await response.json() as T;
  if (!idempotency?.retain) clearIdempotencyHandle(idempotency);
  return result;
}

type Candidate = { action: string; rank: number; confidence: string; expected_operational_effect: string; resource_cost: Record<string, string | number>; excluded_resources: Record<string, string>; priority_reason?: string; evidence_available?: string; important_unknowns?: string; resource_availability?: string; route_accessibility?: string; decision_model?: Record<string, string> };
type Recommendation = { id: string; status: string; action?: string; sector?: string; reasons?: string[]; input_snapshot?: Record<string, unknown>; candidates: Candidate[]; compatible_resources: Array<{ id: string; name: string }>; queue_item_id?: string | null; selected_resource_id?: string | null; selected_action?: string | null; auto_dispatched: boolean; expected_effect?: string; created_at?: string; decided_at?: string | null };
type Scenario = { replayed_at: string; signals: { water_runway_hours: number; contamination: string; population_influx: number } };
export type CommandIncident = { incident_id: string; name: string; hazard_type: string; severity: string; operational_period: string; summary: string; event_time: string; status: string; phase: string; roles: Record<string, string> };
export type IncidentSector = { sector_id: string; incident_id: string; name: string; owner_actor_id: string; assessment_state: string };
export type EvidenceReport = { id: string; client_record_id?: string; report_type: string; status: string; source: { channel: string; source_class: string }; observed_at: string | null; received_at: string | null; recorded_at: string; location: { place_text: string | null; uncertainty_m?: number | null } | null; warnings: string[]; revision: number; duplicate_candidates?: EvidenceDuplicate[] };
export type EvidenceClaim = { id: string; claim_type: string; value: unknown; verification_state: string };
export type EvidenceLink = { report_id?: string; incident_id: string; linked_by: string; linked_at: string };
export type EvidenceDuplicate = { candidate_report_id: string; reason: string };
export type EvidenceReportDetail = EvidenceReport & { reviewed_by?: string; reviewed_at?: string | null; review_note?: string | null; claims: EvidenceClaim[]; duplicate_candidates: EvidenceDuplicate[]; command_incident_links: EvidenceLink[]; affected_recommendations?: Array<{ recommendation_id: string; action: string; status: string }> };
export type MapFeature = { id: string; geometry: { type: string; coordinates: unknown }; properties: Record<string, unknown> };
export type Mission = { mission_id: string; id: string; title: string; status: string; destination: string | null; required_capability: string | null; source_report_id: string; task: { id: string; status: string } | null };
type Item = Record<string, unknown>;
export type GoldenFlow = { data: WorkspaceData; recommendation: Recommendation; audit: Item[]; activeIncident?: CommandIncident | null; source?: DataOrigin; source_detail?: string };
export type LiveQueueItem = { id: string; title: string; priority?: string; destination?: string | null; required_capability?: string | null; source_recommendation_id?: string | null; status: string; created_at?: string };
export type DataOrigin = "api" | "synthetic-fixture" | "cache" | "fallback" | "unavailable";
export type CommandSummary = {
  generated_at: string;
  correlation_id?: string | null;
  source?: DataOrigin;
  source_detail?: string;
  freshness?: { state: "fresh" | "stale" | "unknown" | "degraded"; as_of: string };
  availability?: { state: "available" | "degraded"; unavailable_stores: string[] };
  provenance?: { source: string; source_class: string; synthetic: boolean; affected_entity_type?: string; affected_entity_id?: string };
  mode: "live" | "mixed" | "synthetic" | "operational";
  metrics: { ready_resources: number; total_resources: number; active_tasks: number; response_queue: number; verification_queue: number; population_influx: number | null; water_runway_hours: number | null; contamination: string | null };
  priorities: Array<{ key: string; label: string; reason: string; severity: string }>;
  data_quality: { contamination: string | null; scenario_replayed_at?: string; synthetic: boolean };
};
export type CascadeFinding = {
  affected_capability: string;
  severity: string;
  estimated_time_window_hours: number | null;
  causal_path: string[];
  supporting_input_refs: string[];
  unknown_contributors: string[];
  confidence: string;
  rule_version: string;
};
export type OperationalSnapshot = {
  snapshot_version: string;
  generated_at: string;
  audit_timestamp: string;
  correlation_id?: string | null;
  source?: DataOrigin;
  source_detail?: string;
  availability?: { state: "available" | "degraded"; unavailable_stores: string[] };
  mode: "live" | "synthetic" | "mixed";
  cascade_findings: CascadeFinding[];
  data_freshness: { overall: "fresh" | "stale" | "unknown"; as_of: string; [key: string]: string };
};
export type TelemetryFreshness = "fresh" | "stale" | "silent" | "unknown";
export type TelemetryLink = { link_type: "runway" | "cascade_finding" | "recommendation"; entity_id: string; label: string };
export type TelemetrySourceProvenance = { source: string; source_class: string; synthetic: boolean };
export type TelemetryMeasurement = { name: string; value: number | string | boolean | null; unit: string; observed_at: string | null; status: "normal" | "critical" | "unknown"; links: TelemetryLink[] };
export type TelemetryDeviceSummary = {
  device_id: string;
  sensor_type: string;
  shelter: string;
  last_seen: string | null;
  battery: number | null;
  signal_quality: number | null;
  freshness: TelemetryFreshness;
  communication_gap: boolean;
  communication_gap_minutes: number | null;
  latest_measurements: TelemetryMeasurement[];
  source_provenance: TelemetrySourceProvenance;
};
export type TelemetryGatewaySummary = {
  gateway_id: string;
  shelter: string;
  last_seen: string | null;
  status: "healthy" | "degraded" | "offline" | "unknown";
  freshness: TelemetryFreshness;
  communication_gap: boolean;
  connected_devices: number;
  source_provenance: TelemetrySourceProvenance;
};
export type TelemetrySummary = {
  generated_at: string;
  mode: "live" | "synthetic" | "mixed";
  source?: DataOrigin;
  source_detail?: string;
  freshness: TelemetryFreshness;
  counts: { fresh_sensors: number; stale_sensors: number; silent_sensors: number; critical_readings: number; gateway_count: number };
  devices: TelemetryDeviceSummary[];
  gateways: TelemetryGatewaySummary[];
  warning: string;
};
export type RunwaySnapshotInput = {
  observed_at: string | null;
  freshness_state: "fresh" | "stale" | "unknown";
  field_freshness: Record<string, "fresh" | "stale" | "unknown">;
  values: Record<string, number | null>;
  units: Record<string, string>;
  thresholds: Record<string, number | null>;
};
export type WhatIfKind = "population_influx" | "water_contamination" | "battery_reduction" | "purification_unavailable" | "route_blockage" | "resource_transfer";
export type WhatIfIntervention = {
  kind: WhatIfKind;
  amount?: number;
  unit?: string;
  enabled?: boolean;
  resource_type?: "potable_water" | "medicine";
  source_resource?: string;
};
export type ScenarioProjection = {
  resource: string;
  state: string;
  time_to_critical_hours: number | null;
  threshold: number | null;
  unit: string;
  freshness_state: string;
  confidence: string;
  within_horizon: boolean | null;
  contributors: string[];
};
export type ScenarioComparison = {
  label: "baseline" | "do_nothing" | "intervention";
  changed_inputs: Record<string, number | string | boolean | null>;
  projection: { formula_version: string; observed_at: string | null; horizon_hours: number; projections: ScenarioProjection[] };
  resource_consumption: Record<string, number | null>;
  risk_level: "low" | "medium" | "high" | "critical" | "unknown";
  tradeoffs: string[];
  uncertainty: string[];
  scenario_hash: string;
};
export type WhatIfResult = {
  scenario_version: string;
  input_hash: string;
  baseline: ScenarioComparison;
  do_nothing: ScenarioComparison;
  intervention: ScenarioComparison;
};
export const OPERATIONAL_UPDATE_TYPES = [
  "shelter_state_changed",
  "route_condition_changed",
  "incident_phase_changed",
  "recommendation_changed",
  "resource_readiness_changed",
  "task_status_changed",
  "verification_priority_changed",
  "communication_gap_detected",
  "communication_gap_recovered",
] as const;
export type OperationalUpdateType = typeof OPERATIONAL_UPDATE_TYPES[number];
export type OperationalUpdate = {
  event_type: OperationalUpdateType;
  cursor: string;
  occurred_at: string;
  source: string;
  source_class: string;
  correlation_id: string;
  affected_entity_type: string;
  affected_entity_id: string;
  payload: Record<string, string | number | boolean | null>;
};
export type OperationalUpdatePage = {
  items: OperationalUpdate[];
  next_cursor: string;
  correlation_id?: string | null;
  generated_at?: string;
  freshness?: { state: "fresh" | "stale" | "unknown" | "degraded"; as_of: string };
  availability?: { state: "available" | "degraded"; unavailable_stores: string[] };
};

export const fallbackGoldenFlow: GoldenFlow = {
  source: "fallback",
  source_detail: "Synthetic fixture used only for explicit training mode",
  data: demoWorkspace,
  recommendation: {
    id: "rec_live_view",
    status: "pending_approval",
    auto_dispatched: false,
    candidates: [
      {
        action: "deliver_or_treat_water",
        rank: 1,
        confidence: "medium",
        expected_operational_effect: "Adds or treats potable water before 3.5h runway expires.",
        resource_cost: { "water_team": 1.0, "power_kw": 4.0 },
        excluded_resources: {},
        priority_reason: "North Sector safe-water runway is below 3.5h critical threshold with incoming evacuees.",
        evidence_available: "Field sensor telemetry + drone reconnaissance (rpt_demo_01, rpt_demo_02).",
        important_unknowns: "INFORMATION GAP: Dharapur Village silent (0 reports, pop: 4,200).",
        resource_availability: "FEASIBLE: Synthetic Water Team Alpha & Rescue Boat 1 ready on scene.",
        route_accessibility: "NH-27 Highway Open; West Bank River Corridor Degraded / Blocked.",
        decision_model: { need: "Critical", confidence: "Medium", feasibility: "Feasible" }
      } as any,
      {
        action: "request_medicine_cold_chain_support",
        rank: 2,
        confidence: "low",
        expected_operational_effect: "Protects medicine and cold-chain reserve.",
        resource_cost: { "medical_support": 1.0 },
        excluded_resources: {},
        priority_reason: "Restores mission capability and access for downstream critical sectors.",
        evidence_available: "Infrastructure node dependency telemetry.",
        important_unknowns: "Structural damage extent pending ground reconnaissance.",
        resource_availability: "CONSTRAINED: Heavy excavator awaiting transport.",
        route_accessibility: "Route degraded by mud and debris.",
        decision_model: { need: "Medium", confidence: "Medium", feasibility: "Constrained" }
      } as any,
      {
        action: "shift_non_critical_power",
        rank: 3,
        confidence: "high",
        expected_operational_effect: "Preserves critical loads without dispatching resources.",
        resource_cost: { "operator": 1.0, "shift_kw": 2.0 },
        excluded_resources: {},
        priority_reason: "Protects cold chain and water purification pumps from cascading outage.",
        evidence_available: "Central Shelter load reports and infrastructure dependency model.",
        important_unknowns: "Fuel reserve delivery status unknown for East corridor.",
        resource_availability: "FEASIBLE: Generator Unit ready at Central Shelter.",
        route_accessibility: "Central road network Open.",
        decision_model: { need: "High", confidence: "High", feasibility: "Feasible" }
      } as any
    ],
    compatible_resources: [{ id: "res_348a10f74f374c47af445be276f0f3b8", name: "Synthetic Water Team Alpha" }]
  },
  audit: [{ event: "Active Operational Session Initialized" }]
};

function mapWorkspace(scenario: Scenario, recommendation: Recommendation, resources: Item[], queue: Item[], verification: Verification[], unlocks: Unlock[], plans: Plan[], forecasts: ResourceForecast[], resourceRequests: ResourceRequest[], tasks: Item[]): WorkspaceData {
  return {
    projections: [
      { resource: "Potable water", time: `${scenario.signals.water_runway_hours} h`, state: "critical next", freshness: "Live replay · runway_v1" },
      { resource: "Water contamination", time: scenario.signals.contamination, state: "operational pressure", freshness: "Synthetic replay signal" },
      { resource: "Population influx", time: `+${scenario.signals.population_influx}`, state: "expected", freshness: "Contradictory · verify" }
    ],
    candidates: recommendation.candidates.map((item) => ({
      action: item.action.replaceAll("_", " "),
      actionId: item.action,
      rank: item.rank,
      confidence: item.confidence,
      effect: item.expected_operational_effect,
      cost: Object.entries(item.resource_cost).map(([key, value]) => `${key}: ${value}`).join(" · "),
      excluded: Object.entries(item.excluded_resources).map(([id, reason]) => `${id}: ${reason}`).join("; ") || "None",
      priorityReason: (item as any).priority_reason || "North Sector safe-water runway is below 6.0h critical threshold with incoming evacuees.",
      evidenceAvailable: (item as any).evidence_available || "Corroborated sensor telemetry + drone reconnaissance (rpt_demo_01, rpt_demo_02).",
      importantUnknowns: (item as any).important_unknowns || "INFORMATION GAP: Dharapur Village silent (0 reports, pop: 4,200); West corridor bridge unassessed.",
      resourceAvailability: (item as any).resource_availability || "FEASIBLE: Synthetic Water Team Alpha & Rescue Boat 1 ready on scene.",
      routeAccessibility: (item as any).route_accessibility || "NH-27 Highway Open; West Bank River Corridor Degraded / Blocked.",
      decisionModel: (item as any).decision_model || { need: "Critical", confidence: "Medium", feasibility: "Feasible" },
    })),
    evidence: [
      { id: "scenario_fixed_north_sector_v1", claim: "North Sector water supply contaminated by flood breach (Severe)", state: "corroborated", classification: "Confirmed", source: `Backend · ${scenario.replayed_at}`, severity: "critical" },
      { id: "scenario_influx_conflict", claim: "Population influx +180 arriving at relief camp", state: "contradicted", classification: "Contradictory", source: "Citizen intake vs Aerial drone count (60)", severity: "moderate" },
      { id: "scenario_silent_dharapur", claim: "Dharapur Village — zero field reports received in 6h (Information Gap)", state: "unknown", classification: "Unknown / Needs Verification", source: "DEOC Silent Area Watchdog", severity: "high" },
      { id: "scenario_bridge_washout", claim: "NH-27 Highway Bridge washed out near Km 18", state: "corroborated", classification: "Confirmed", source: "Satellite SAR + PWD Field Notice", severity: "critical" },
    ],
    resources: resources.map((item) => ({
      id: String(item.id),
      name: String(item.name),
      readiness: String(item.readiness).toUpperCase(),
      feasibility: (item.feasibility as any) || (String(item.readiness).toLowerCase() === "ready" ? "feasible" : "infeasible"),
      category: (item.resource_type as any) || "other",
      route: item.readiness_expires_at ? `Fresh until ${String(item.readiness_expires_at)}` : "Freshness unknown",
      task: tasks.some((task) => task.resource_id === item.id && task.status !== "completed") ? "Active task" : "Unassigned"
    })),
    queue: queue.map((item) => ({ id: String(item.id), title: String(item.title), status: String(item.status ?? item.queue_type), source_recommendation_id: item.source_recommendation_id ? String(item.source_recommendation_id) : null })),
    tasks: tasks.map((item) => ({ id: String(item.id), resource: String(item.resource_id), status: String(item.status), outcome: String(item.outcome_summary ?? "Outcome pending") })),
    places: [
      { id: "north-sector", label: "North Sector · water contamination (Severe)", state: "synthetic replay", coordinates: "91.742, 26.184", routeFeasibility: "open", decisionModel: { need: "Critical", confidence: "High", feasibility: "Feasible" } },
      { id: "dharapur-village", label: "Dharapur Village · Silent Settlement (0 reports)", state: "silent", isSilent: true, informationGap: true, coordinates: "91.710, 26.190", routeFeasibility: "unknown", decisionModel: { need: "High", confidence: "Low", feasibility: "Unknown" } },
      { id: "nh27-bridge", label: "NH-27 Highway Bridge · Washout", state: "blocked", coordinates: "91.765, 26.185", routeFeasibility: "blocked", decisionModel: { need: "Critical", confidence: "High", feasibility: "Infeasible" } },
      { id: "west-sector", label: "West Sector · access blocked", state: "degraded", coordinates: "91.728, 26.176", routeFeasibility: "degraded", decisionModel: { need: "Medium", confidence: "Medium", feasibility: "Constrained" } },
    ],
    verification,
    unlocks,
    plans,
    forecasts,
    resourceRequests,
  };
}

async function reads(scenario: Scenario, recommendation: Recommendation, fallbackOnError = false): Promise<GoldenFlow> {
  try {
    const [resources, queue, verificationQueue, tasks, audit, coverage, infrastructure, plans, forecasts, resourceRequests] = await Promise.all([
      request<{ items: Item[] }>("/resources", { headers: headers() }),
      request<{ items: Item[] }>("/response-queue", { headers: headers() }),
      request<{ items: Item[] }>("/verification-queue", { headers: headers() }),
      request<{ items: Item[] }>("/tasks", { headers: headers() }),
      request<{ items: Item[] }>("/decision-loop/audit", { headers: headers() }),
      request<{ items: Verification[] }>("/coverage/verification-ranking", { headers: headers() }),
      request<{ items: Unlock[] }>("/infrastructure/unlock-ranking", { headers: headers() }),
      request<{ items: Plan[] }>("/plans", { headers: headers() }),
      request<{ items: ResourceForecast[] }>("/resource-forecasts", { headers: headers() }),
      request<{ items: ResourceRequest[] }>("/resource-requests", { headers: headers() })
    ]);
    return { data: mapWorkspace(scenario, recommendation, resources.items, [...queue.items, ...verificationQueue.items], coverage.items, infrastructure.items, plans.items, forecasts.items, resourceRequests.items, tasks.items), recommendation, audit: audit.items, source: "api" };
  } catch (reason) {
    if (!fallbackOnError) throw reason;
    return fallbackGoldenFlow;
  }
}

export async function getLiveDecisionFlow(): Promise<GoldenFlow | null> {
  const [scenario, result] = await Promise.all([
    request<Scenario>("/decision-loop/scenario", { headers: headers() }),
    request<{ recommendation: Recommendation | null }>("/decision-loop/recommendations/current", { headers: headers() }),
  ]);
  if (!result.recommendation) return null;
  const input = result.recommendation.input_snapshot || {};
  const normalizedScenario: Scenario = scenario?.signals
    ? scenario
    : {
        replayed_at: result.recommendation.created_at || new Date().toISOString(),
        signals: {
          water_runway_hours: Number(input.water_runway_hours ?? 0),
          contamination: String(input.contamination ?? "unknown"),
          population_influx: Number(input.population_influx ?? 0),
        },
      };
  return reads(normalizedScenario, result.recommendation, false);
}

export async function resetGoldenFlow(allowSyntheticFallback = false): Promise<GoldenFlow> {
  const replayOperation: IdempotencyHandle = { ...idempotencyHandle("golden-flow-replay", { flow: "golden" }), retain: true };
  const recommendationOperation: IdempotencyHandle = { ...idempotencyHandle("golden-flow-recommendation", { flow: "golden" }), retain: true };
  try {
    const scenario = await request<Scenario>("/decision-loop/demo/replay", { method: "POST", headers: headers(replayOperation.key), idempotency: replayOperation });
    const recommendation = await request<Recommendation>("/decision-loop/recommendations", { method: "POST", headers: headers(recommendationOperation.key), idempotency: recommendationOperation });
    const result = await reads(scenario, recommendation, allowSyntheticFallback);
    clearIdempotencyHandle(replayOperation);
    clearIdempotencyHandle(recommendationOperation);
    return result;
  } catch (reason) {
    if (!allowSyntheticFallback) throw reason;
    return fallbackGoldenFlow;
  }
}

export async function getActiveIncident(): Promise<CommandIncident | null> {
  const result = await request<{ incident: CommandIncident | null }>("/command/incidents/active", { headers: headers() });
  return result.incident;
}

export async function listIncidentSectors(incidentId: string): Promise<IncidentSector[]> {
  const result = await request<{ items: IncidentSector[] }>(`/command/incidents/${incidentId}/sectors`, { headers: headers() });
  return result.items;
}

export async function createIncidentSector(incidentId: string, input: { name: string; owner_actor_id: string }): Promise<IncidentSector> {
  const idempotency = idempotencyHandle("incident-sector", { incidentId, input });
  return request<IncidentSector>(`/command/incidents/${incidentId}/sectors`, { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(input) });
}

export async function listEvidenceReports(): Promise<EvidenceReport[]> {
  return (await request<{ items: EvidenceReport[] }>("/reports", { headers: headers() })).items;
}

export async function getEvidenceReport(reportId: string): Promise<EvidenceReportDetail> {
  return request<EvidenceReportDetail>(`/reports/${reportId}`, { headers: headers() });
}

export async function createEvidenceReport(input: { report_type: string; place_text: string; people_affected: number | null; longitude?: number; latitude?: number }): Promise<{ report_id: string }> {
  const idempotency = idempotencyHandle("evidence-report", input);
  const clientRecordId = idempotency.key;
  const observedAt = idempotency.createdAt;
  return request("/reports", { method: "POST", headers: headers(clientRecordId), idempotency, body: JSON.stringify({ contract_version: 1, client_record_id: clientRecordId, observed_at: observedAt, received_at: observedAt, source: { channel: "operator_report_desk", source_class: "authenticated_operator" }, location: { geometry: { type: "Point", coordinates: [input.longitude ?? 91.742, input.latitude ?? 26.184] }, uncertainty_m: 250, place_text: input.place_text || null }, report_type: input.report_type, facts: { people_affected: input.people_affected, access_state: "unknown" }, privacy_class: "restricted_operational" }) });
}

export async function reviewEvidenceReport(reportId: string, claimUpdates: Record<string, string>): Promise<EvidenceReportDetail> {
  const payload = { claim_updates: claimUpdates, note: "Commander review from report desk" };
  const idempotency = idempotencyHandle("evidence-review", { reportId, payload });
  return request(`/reports/${reportId}/review`, { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function linkEvidenceToCommandIncident(reportId: string, incidentId: string): Promise<void> {
  const payload = { incident_id: incidentId };
  const idempotency = idempotencyHandle("evidence-command-link", { reportId, payload });
  await request(`/reports/${reportId}/command-incident-links`, { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function assignVerification(report: EvidenceReportDetail, incidentId: string | undefined): Promise<void> {
  const payload = { title: `Verify ${report.report_type.replaceAll("_", " ")}`, priority: "high", destination: report.location?.place_text ?? null, notes: "Human verification requested from report desk", owner_actor_id: "operator", source_report_id: report.id, source_incident_id: incidentId ?? null };
  const idempotency = idempotencyHandle("verification-queue", payload);
  await request("/verification-queue", { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function listMapFeatures(): Promise<MapFeature[]> {
  return (await request<{ features: MapFeature[] }>("/map/features?limit=100", { headers: headers() })).features;
}

export async function listMissions(): Promise<Mission[]> {
  return (await request<{ items: Mission[] }>("/missions", { headers: headers() })).items;
}

export async function createMission(input: { source_report_id: string; source_incident_id: string; objective: string; destination: string; required_capability: string }): Promise<Mission> {
  const payload = { ...input, priority: "high", owner_actor_id: "operator" };
  const idempotency = idempotencyHandle("mission-create", payload);
  return request("/missions", { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function listResources(): Promise<Array<{ id: string; name: string; readiness: string }>> {
  return (await request<{ items: Array<{ id: string; name: string; readiness: string }> }>("/resources", { headers: headers() })).items;
}

export async function listResourceForecasts(): Promise<ResourceForecast[]> {
  return (await request<{ items: ResourceForecast[] }>("/resource-forecasts", { headers: headers() })).items;
}

export async function listResourceRequests(): Promise<ResourceRequest[]> {
  return (await request<{ items: ResourceRequest[] }>("/resource-requests", { headers: headers() })).items;
}

export async function approveMission(missionId: string, resourceId: string): Promise<void> {
  const payload = { resource_id: resourceId, approved: true, approval_note: "Commander approved mission assignment" };
  const idempotency = idempotencyHandle("mission-approval", { missionId, payload });
  await request(`/response-queue/${missionId}/approve`, { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function advanceLiveTask(taskId: string, status: "acknowledged" | "en_route" | "on_scene" | "paused"): Promise<void> {
  const payload = { status };
  const idempotency = idempotencyHandle("task-status", { taskId, payload });
  await request(`/tasks/${taskId}`, { method: "PATCH", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function completeLiveTask(taskId: string, actionTypeEvidence: string): Promise<void> {
  const action = idempotencyHandle("task-complete", { taskId, actionTypeEvidence });
  const completedAt = action.createdAt;
  const statusHandle: IdempotencyHandle = { ...action, key: `${action.key}-status`.slice(0, 128), retain: true };
  const outcomeHandle: IdempotencyHandle = { ...action, key: `${action.key}-outcome`.slice(0, 128), retain: true };
  await request(`/tasks/${taskId}`, { method: "PATCH", headers: headers(statusHandle.key), idempotency: statusHandle, body: JSON.stringify({ status: "completed" }) });
  const payload = { action_type_evidence: actionTypeEvidence, completion_quantities: {}, completed_at: completedAt, residual_need: null, verified_by: "operator" };
  await request(`/tasks/${taskId}/structured-outcome`, { method: "POST", headers: headers(outcomeHandle.key), idempotency: outcomeHandle, body: JSON.stringify(payload) });
  clearIdempotencyHandle(action);
}

export async function createSitrep(reports: EvidenceReport[]): Promise<{ reports: number; by_type: Record<string, number>; summary_hash: string }> {
  const idempotency = idempotencyHandle("sitrep-export", reports.map((report) => report.id));
  const payload = { tenant_id: "org_demo", workspace_id: "evt_demo", replay_at: idempotency.createdAt, rows: reports.map((report) => ({ event_time: report.observed_at ?? report.recorded_at, report_type: report.report_type, status: report.status, location: report.location?.place_text ?? "unknown" })) };
  return request("/exports/sitrep", { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function runExerciseReplay(allowSyntheticFallback = false): Promise<{ record_count: number; future_records_excluded: number; scenario_signals: string[]; result_hash: string; synthetic: boolean }> {
  try {
    return await request("/evaluation/replay", { headers: headers() });
  } catch (reason) {
    if (!allowSyntheticFallback) throw reason;
    return { record_count: 12, future_records_excluded: 0, scenario_signals: ["water_runway_hours: 3.5", "contamination: elevated"], result_hash: "eval_hash_demo", synthetic: true };
  }
}

export type PilotStatus = { configuration: { agency_name: string; district_name: string; country_code: string; approved_feed_ids: string[]; retention_days_operational: number; retention_days_restricted: number } | null; official_feed_events: number; identity_mode: string; retention_enforcement: string };
export type TabletopExercise = { synthetic: boolean; faults: string[]; metrics: { verification_time_minutes: number; wrong_dispatches: number; duplicate_missions_prevented: number; coverage_gaps_surfaced: number; sync_delay_minutes: number; operator_actions: number }; result_hash: string; limitations: string[] };

export async function getPilotStatus(): Promise<PilotStatus> {
  return request("/pilot/status", { headers: headers() });
}

export async function configurePilot(input: { agency_name: string; district_name: string; country_code: string; approved_feed_ids: string[] }): Promise<PilotStatus["configuration"]> {
  const payload = { ...input, retention_days_operational: 90, retention_days_restricted: 30, hazard_playbooks: { flood: "flood_v1", earthquake: "earthquake_v1", landslide: "landslide_v1" } };
  const idempotency = idempotencyHandle("pilot-configuration", payload);
  return request("/pilot/configuration", { method: "PUT", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function runPilotTabletop(allowSyntheticFallback = false): Promise<TabletopExercise> {
  try {
    const idempotency = idempotencyHandle("pilot-tabletop", { exercise: "tabletop" });
    return await request("/pilot/exercises/tabletop", { method: "POST", headers: headers(idempotency.key), idempotency });
  } catch (reason) {
    if (!allowSyntheticFallback) throw reason;
    return { synthetic: true, faults: ["delayed_telemetry_5m", "silent_village_dharapur"], metrics: { verification_time_minutes: 4.2, wrong_dispatches: 0, duplicate_missions_prevented: 3, coverage_gaps_surfaced: 2, sync_delay_minutes: 0.8, operator_actions: 5 }, result_hash: "tabletop_pass_hash", limitations: ["Tabletop replay mode active. Real-world dispatch disabled."] };
  }
}

export async function activateIncident(input: { name: string; hazard_type: string; severity: string; summary: string; event_time: string }): Promise<CommandIncident> {
  const createOperation = idempotencyHandle("incident-create", input);
  const created = await request<CommandIncident>("/command/incidents", { method: "POST", headers: headers(createOperation.key), idempotency: createOperation, body: JSON.stringify(input) });
  const rolePayload = { role: "incident_commander", actor_id: "operator" };
  const roleOperation = idempotencyHandle("incident-role", { incidentId: created.incident_id, rolePayload });
  await request(`/command/incidents/${created.incident_id}/roles`, { method: "POST", headers: headers(roleOperation.key), idempotency: roleOperation, body: JSON.stringify(rolePayload) });
  const transitionPayload = { status: "active", phase: "activation", note: "Incident activated from command room" };
  const transitionOperation = idempotencyHandle("incident-activate", { incidentId: created.incident_id, transitionPayload });
  return request<CommandIncident>(`/command/incidents/${created.incident_id}`, { method: "PATCH", headers: headers(transitionOperation.key), idempotency: transitionOperation, body: JSON.stringify(transitionPayload) });
}

export async function pauseIncident(incidentId: string): Promise<CommandIncident> {
  const payload = { status: "paused", phase: "handover", note: "Paused by commander from command bar" };
  const idempotency = idempotencyHandle("incident-pause", { incidentId, payload });
  return request<CommandIncident>(`/command/incidents/${incidentId}`, { method: "PATCH", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function resumeIncident(incidentId: string): Promise<CommandIncident> {
  const payload = { status: "active", phase: "size_up", note: "Resumed by commander from paused-session landing" };
  const idempotency = idempotencyHandle("incident-resume", { incidentId, payload });
  return request<CommandIncident>(`/command/incidents/${incidentId}`, { method: "PATCH", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function closeIncident(incidentId: string): Promise<CommandIncident> {
  const payload = { status: "closed", phase: "handover", note: "Closed by commander from paused-session landing" };
  const idempotency = idempotencyHandle("incident-close", { incidentId, payload });
  return request<CommandIncident>(`/command/incidents/${incidentId}`, { method: "PATCH", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
}

export async function decide(flow: GoldenFlow, decision: "approve" | "reject" | "modify", selectedAction?: string, note?: string): Promise<GoldenFlow> {
  const payload = { decision, selected_action: selectedAction, note: note || (decision === "modify" ? "Commander modified option before approval" : "Commander decision from operator workspace") };
  const idempotency = idempotencyHandle("recommendation-decision", { recommendationId: flow.recommendation.id, payload });
  const recommendation = await request<Recommendation>(`/decision-loop/recommendations/${flow.recommendation.id}/decision`, { method: "POST", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
  try {
    const scenario = await request<Scenario>("/decision-loop/scenario", { headers: headers() });
    return await reads(scenario, recommendation);
  } catch {
    // The mutation has already returned successfully; keep its authoritative status
    // visible even if the follow-up read is temporarily unavailable.
    return { ...flow, recommendation: { ...flow.recommendation, ...recommendation } };
  }
}

export async function approveMutualAid(flow: GoldenFlow, requestId: string): Promise<GoldenFlow> {
  const payload = { approved: true, approval_note: "Commander approved synthetic mutual-aid request" };
  const idempotency = idempotencyHandle("mutual-aid-approval", { requestId, payload });
  await request(`/resource-requests/${requestId}/approve`, { method: "PATCH", headers: headers(idempotency.key), idempotency, body: JSON.stringify(payload) });
  const scenario = await request<Scenario>("/decision-loop/scenario", { headers: headers() });
  return await reads(scenario, flow.recommendation, false);
}

export async function assignApproved(flow: GoldenFlow): Promise<GoldenFlow> {
  const queueId = flow.recommendation.queue_item_id;
  const resourceId = flow.recommendation.selected_resource_id || flow.recommendation.compatible_resources[0]?.id;
  if (!queueId || !resourceId) throw new Error("No approved queue item or compatible resource");
  const confirmationAt = flow.recommendation.decided_at || new Date().toISOString();
  const expiry = new Date(new Date(confirmationAt).getTime() + 3600000).toISOString();
  const routePayload = { destination: flow.recommendation.sector || "North Sector", state: "passable", observed_at: confirmationAt, expires_at: expiry, source: "commander_route_confirmation" };
  const routeOperation = idempotencyHandle("route-confirmation", { recommendationId: flow.recommendation.id, routePayload });
  await request("/route-observations", { method: "POST", headers: headers(routeOperation.key), idempotency: routeOperation, body: JSON.stringify(routePayload) });
  const approvalPayload = { resource_id: resourceId, approved: true, approval_note: "Commander confirmed route and manual assignment" };
  const approvalOperation = idempotencyHandle("recommendation-assignment", { queueId, resourceId, approvalPayload });
  await request(`/response-queue/${queueId}/approve`, { method: "POST", headers: headers(approvalOperation.key), idempotency: approvalOperation, body: JSON.stringify(approvalPayload) });
  const scenario = await request<Scenario>("/decision-loop/scenario", { headers: headers() });
  return await reads(scenario, flow.recommendation, false);
}

export async function advanceTask(flow: GoldenFlow, status: "acknowledged" | "en_route" | "on_scene" | "paused" | "completed"): Promise<GoldenFlow> {
  const task = flow.data.tasks.find((item) => item.status !== "completed");
  if (!task) throw new Error("No active task");
  const action = status === "completed" ? idempotencyHandle("task-complete", { taskId: task.id, source: "golden-flow" }) : null;
  const statusOperation = action || idempotencyHandle("task-status", { taskId: task.id, status });
  const statusPayload = { status };
  await request(`/tasks/${task.id}`, { method: "PATCH", headers: headers(statusOperation.key), idempotency: { ...statusOperation, key: `${statusOperation.key}-status`.slice(0, 128), retain: Boolean(action) }, body: JSON.stringify(statusPayload) });
  if (status === "completed") {
    const outcomePayload = { action_type_evidence: "Operational task completion recorded", completion_quantities: {}, completed_at: action?.createdAt || new Date().toISOString(), residual_need: "Continue monitoring next shift", verified_by: "operator" };
    await request(`/tasks/${task.id}/structured-outcome`, { method: "POST", headers: headers(`${statusOperation.key}-outcome`.slice(0, 128)), idempotency: { ...statusOperation, key: `${statusOperation.key}-outcome`.slice(0, 128), retain: true }, body: JSON.stringify(outcomePayload) });
    clearIdempotencyHandle(action || undefined);
  }
  const scenario = await request<Scenario>("/decision-loop/scenario", { headers: headers() });
  return await reads(scenario, flow.recommendation, false);
}

export async function syncLiveFeeds(): Promise<{ synced_count: number; created_count: number; health_status: Record<string, string>; last_sync_time: string | null }> {
  const idempotency = idempotencyHandle("feed-sync", { hour: new Date().toISOString().slice(0, 13) });
  return request("/feeds/sync", { method: "POST", headers: headers(idempotency.key), idempotency });
}

export async function getWorkspaceMode(): Promise<{ mode: string; health_status: Record<string, string>; last_sync_time: string | null }> {
  return request("/workspace/mode", { headers: headers() });
}

export async function getCommandSummary(options: { allowSyntheticFallback?: boolean } = {}): Promise<CommandSummary> {
  try {
    const result = await request<CommandSummary>("/command/summary", { headers: headers() });
    return { ...result, source: result.source ?? "api" };
  } catch (error) {
    if (options.allowSyntheticFallback !== true) throw error;
    return {
      generated_at: new Date().toISOString(),
      correlation_id: null,
      source: "fallback",
      source_detail: "Backend unavailable; synthetic fixture selected explicitly for this workspace",
      freshness: { state: "unknown", as_of: new Date().toISOString() },
      availability: { state: "degraded", unavailable_stores: ["command_summary"] },
      mode: "synthetic",
      metrics: { ready_resources: 2, total_resources: 7, active_tasks: 1, response_queue: 1, verification_queue: 1, population_influx: 180, water_runway_hours: 3.5, contamination: "elevated" },
      priorities: [
        { key: "water-runway", label: "Protect potable-water continuity", reason: "Water runway is below the emergency threshold.", severity: "critical" },
        { key: "contamination", label: "Verify contamination signal", reason: "Contamination pressure is elevated.", severity: "high" },
        { key: "verification", label: "Resolve information gaps", reason: "An unknown area may change the response plan.", severity: "unknown" },
      ],
      data_quality: { contamination: "elevated", synthetic: true },
    };
  }
}

export async function getOperationalSnapshot(options: { allowSyntheticFallback?: boolean } = {}): Promise<OperationalSnapshot> {
  try {
    const result = await request<OperationalSnapshot>("/command/operational-snapshot", { headers: headers(), cache: "no-store" });
    return { ...result, source: result.source ?? "api" };
  } catch (error) {
    if (options.allowSyntheticFallback !== true) throw error;
    const generatedAt = new Date().toISOString();
    return {
      snapshot_version: "operational_snapshot_v1",
      source: "fallback",
      source_detail: "Backend unavailable; synthetic fixture selected explicitly for this workspace",
      generated_at: generatedAt,
      audit_timestamp: generatedAt,
      correlation_id: null,
      mode: "synthetic",
      cascade_findings: [],
      data_freshness: { overall: "unknown", as_of: generatedAt },
    };
  }
}

export async function getTelemetrySummary(options: { allowSyntheticFallback?: boolean } = {}): Promise<TelemetrySummary> {
  try {
    const result = await request<TelemetrySummary>("/telemetry/summary", { headers: headers(), cache: "no-store" });
    return { ...result, source: result.source ?? "api" };
  } catch (error) {
    if (options.allowSyntheticFallback !== true) throw error;
    const now = new Date().toISOString();
    const source = { source: "lorawan_demo_fixture", source_class: "synthetic_telemetry", synthetic: true } as const;
    return {
      generated_at: now,
      source: "fallback",
      source_detail: "Backend unavailable; synthetic fixture selected explicitly for this workspace",
      mode: "synthetic",
      freshness: "silent",
      counts: { fresh_sensors: 1, stale_sensors: 1, silent_sensors: 1, critical_readings: 1, gateway_count: 2 },
      devices: [
        { device_id: "sensor-synthetic-water-01", sensor_type: "water_quality", shelter: "Synthetic North Shelter", last_seen: now, battery: 84, signal_quality: 91, freshness: "fresh", communication_gap: false, communication_gap_minutes: 0, latest_measurements: [{ name: "turbidity", value: 12.4, unit: "NTU", observed_at: now, status: "critical", links: [{ link_type: "runway", entity_id: "potable_water", label: "Potable-water runway" }, { link_type: "cascade_finding", entity_id: "safe_water_runway", label: "Safe-water cascade" }, { link_type: "recommendation", entity_id: "pending_water_action", label: "Pending water action" }] }], source_provenance: source },
        { device_id: "sensor-synthetic-power-02", sensor_type: "battery_health", shelter: "Synthetic North Shelter", last_seen: now, battery: 62, signal_quality: 64, freshness: "stale", communication_gap: true, communication_gap_minutes: 30, latest_measurements: [{ name: "reserve", value: 31, unit: "%", observed_at: now, status: "normal", links: [{ link_type: "runway", entity_id: "battery_reserve", label: "Battery runway" }] }], source_provenance: source },
        { device_id: "sensor-synthetic-silent-03", sensor_type: "shelter_environment", shelter: "Synthetic East Shelter", last_seen: null, battery: null, signal_quality: null, freshness: "silent", communication_gap: true, communication_gap_minutes: null, latest_measurements: [], source_provenance: source },
      ],
      gateways: [
        { gateway_id: "gateway-synthetic-north", shelter: "Synthetic North Shelter", last_seen: now, status: "healthy", freshness: "fresh", communication_gap: false, connected_devices: 2, source_provenance: source },
        { gateway_id: "gateway-synthetic-east", shelter: "Synthetic East Shelter", last_seen: null, status: "offline", freshness: "silent", communication_gap: true, connected_devices: 1, source_provenance: source },
      ],
      warning: "No telemetry does not mean safe conditions.",
    };
  }
}

export async function evaluateWhatIf(snapshot: RunwaySnapshotInput, intervention: WhatIfIntervention, horizonHours = 48): Promise<WhatIfResult> {
  return request<WhatIfResult>("/what-if/evaluate", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ snapshot, intervention, horizon_hours: horizonHours }),
  });
}

export async function pollOperationalUpdates(cursor: string | null, limit = 50): Promise<OperationalUpdatePage> {
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor) query.set("cursor", cursor);
  return request<OperationalUpdatePage>(`/updates?${query.toString()}`, {
    cache: "no-store",
    headers: { ...headers(), "Cache-Control": "no-cache" },
  });
}

export type AuditInteractionEvent = "recommendation_viewed" | "evidence_opened" | "scenario_evaluated";
export async function recordAuditInteraction(
  event: AuditInteractionEvent,
  subjectType: "recommendation" | "evidence" | "scenario",
  subjectId: string,
): Promise<{ recorded_at: string; correlation_id?: string | null; replayed: boolean }> {
  const stableKey = `ui-audit-${event}-${subjectType}-${subjectId}`.slice(0, 128);
  return request(`/decision-loop/audit/interactions`, {
    method: "POST",
    headers: headers(stableKey),
    body: JSON.stringify({ event, subject_type: subjectType, subject_id: subjectId }),
  });
}

export async function setWorkspaceMode(mode: "live" | "synthetic" | "mixed"): Promise<{ mode: string }> {
  const idempotency = idempotencyHandle("workspace-mode", { mode });
  return request(`/workspace/mode?mode=${mode}`, { method: "POST", headers: headers(idempotency.key), idempotency });
}
