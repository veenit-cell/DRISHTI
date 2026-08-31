import type { Page } from "@playwright/test";

const now = "2026-01-01T00:00:00.000Z";

export async function installSyntheticApi(page: Page, degraded = false, delayMs = 0, offline = false): Promise<void> {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (offline) {
      await route.abort("failed");
      return;
    }
    if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
    if (degraded && (path.endsWith("/command/summary") || path.endsWith("/telemetry/summary"))) {
      await route.fulfill({ status: 503, contentType: "application/problem+json", body: JSON.stringify({ title: "Service unavailable", detail: "Synthetic degraded fixture" }) });
      return;
    }
    if (path.endsWith("/workspace/mode")) {
      await route.fulfill({ json: { mode: degraded ? "live" : "synthetic", health_status: {}, last_sync_time: null } });
      return;
    }
    if (path.endsWith("/command/incidents/active")) {
      await route.fulfill({ json: { incident: null } });
      return;
    }
    if (path.endsWith("/updates")) {
      await route.fulfill({ json: { items: [], next_cursor: "", correlation_id: "e2e-synthetic", generated_at: now, freshness: { state: "fresh", as_of: now }, availability: { state: "available", unavailable_stores: [] } } });
      return;
    }
    if (path.endsWith("/command/summary")) {
      await route.fulfill({ json: { generated_at: now, correlation_id: "e2e-summary", source: "api", mode: "synthetic", freshness: { state: "fresh", as_of: now }, availability: { state: "available", unavailable_stores: [] }, metrics: { ready_resources: 2, total_resources: 3, active_tasks: 1, response_queue: 1, verification_queue: 1, population_influx: 100, water_runway_hours: 3.5, contamination: "elevated" }, priorities: [{ key: "water", label: "Protect potable-water continuity", reason: "Synthetic fixture", severity: "critical" }], data_quality: { contamination: "elevated", synthetic: true } } });
      return;
    }
    if (path.endsWith("/command/operational-snapshot")) {
      await route.fulfill({ json: { snapshot_version: "operational_snapshot_v1", generated_at: now, audit_timestamp: now, correlation_id: "e2e-snapshot", source: "api", mode: "synthetic", cascade_findings: [], data_freshness: { overall: "fresh", as_of: now } } });
      return;
    }
    if (path.endsWith("/telemetry/summary")) {
      await route.fulfill({ json: { generated_at: now, mode: "synthetic", source: "api", freshness: "silent", counts: { fresh_sensors: 0, stale_sensors: 0, silent_sensors: 1, critical_readings: 0, gateway_count: 0 }, devices: [], gateways: [], warning: "No telemetry does not mean safe conditions." } });
      return;
    }
    if (request.method() === "GET") {
      await route.fulfill({ json: path.includes("/scenario") ? { replayed_at: now, signals: { water_runway_hours: 3.5, contamination: "elevated", population_influx: 100 } } : [] });
      return;
    }
    await route.fulfill({ json: { ok: true, recorded_at: now, replayed: false } });
  });
}
