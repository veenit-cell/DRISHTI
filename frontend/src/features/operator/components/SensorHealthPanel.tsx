import type { TelemetryDeviceSummary, TelemetrySummary } from "../api";

type SensorHealthPanelProps = {
  summary: TelemetrySummary | null;
  state: "loading" | "ready" | "error";
  error?: string;
  onRetry?: () => void;
};

function formatTime(value: string | null): string {
  if (!value) return "No timestamp";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Invalid timestamp" : parsed.toLocaleString();
}

function measurementValue(value: TelemetryDeviceSummary["latest_measurements"][number]["value"], unit: string): string {
  if (value === null || value === undefined) return "Unknown";
  return `${String(value)}${unit ? ` ${unit}` : ""}`;
}

function freshnessLabel(freshness: TelemetryDeviceSummary["freshness"]): string {
  return freshness === "silent" ? "Silent / no recent signal" : `${freshness} data`;
}

export function SensorHealthPanel({ summary, state, error, onRetry }: SensorHealthPanelProps) {
  const containsSynthetic = summary?.devices.some((device) => device.source_provenance.synthetic) || summary?.gateways.some((gateway) => gateway.source_provenance.synthetic) || false;
  const modeLabel = summary?.mode === "synthetic" ? "Synthetic telemetry" : summary?.mode === "mixed" ? "Mixed telemetry" : "Live telemetry";

  return (
    <section className="sensor-health-panel" aria-labelledby="sensor-health-heading">
      <div className="sensor-health-heading">
        <div>
          <p className="eyebrow">Telemetry Health</p>
          <h2 id="sensor-health-heading">Sensor Health</h2>
          <p className="sensor-health-note">Backend-projected LoRaWAN health. The frontend never connects directly to MQTT or receives device keys.</p>
        </div>
        {summary && <div className="sensor-health-status"><span className="semantic-status status-info">{modeLabel}</span><span className="data-source-label">Source: {summary.source === "api" ? "API" : summary.source === "fallback" ? "Synthetic fixture fallback" : summary.source === "cache" ? "Cache" : "Not reported"}</span></div>}
      </div>

      {state === "loading" && <div className="sensor-health-state" role="status" aria-live="polite" aria-label="Loading telemetry health">
        <span className="sr-only">Loading telemetry health</span>
        <div className="section-skeleton" aria-hidden="true">
          <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
          <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
          <div className="skeleton-block"><span className="skeleton-line skeleton-line-short" /><span className="skeleton-line" /><span className="skeleton-line skeleton-line-muted" /></div>
        </div>
      </div>}
      {state === "error" && <div className="sensor-health-state sensor-health-state-error" role="alert"><span>{error || "Telemetry health unavailable"}. Stale or missing telemetry is not treated as current.</span>{onRetry && <button type="button" className="btn-secondary" onClick={onRetry}>Retry telemetry</button>}</div>}
      {summary && <>
        <div className="sensor-health-warning" role="note"><strong>Attention:</strong> {summary.warning}</div>
        {containsSynthetic && <div className="sensor-health-synthetic" role="status">Synthetic telemetry is included for training/replay and must not be treated as live field evidence.</div>}

        <div className="sensor-health-counts" role="group" aria-label="Sensor health counts">
          <div><strong>{summary.counts.fresh_sensors}</strong><span>Fresh sensors</span></div>
          <div><strong>{summary.counts.stale_sensors}</strong><span>Stale sensors</span></div>
          <div><strong>{summary.counts.silent_sensors}</strong><span>Silent sensors</span></div>
          <div><strong>{summary.counts.critical_readings}</strong><span>Critical readings</span></div>
          <div><strong>{summary.counts.gateway_count}</strong><span>Gateways</span></div>
        </div>

        <div className="sensor-health-grid">
          <div className="sensor-health-column">
            <div className="sensor-health-section-heading"><h3>Sensor signals</h3><span>{summary.devices.length} shown</span></div>
            {summary.devices.length ? summary.devices.map((device) => (
              <article className={`sensor-card sensor-card-${device.freshness}`} key={device.device_id}>
                <div className="sensor-card-heading">
                  <div><strong>{device.sensor_type.replaceAll("_", " ")}</strong><span>{device.device_id}</span></div>
                  <span className="sensor-state-label">{freshnessLabel(device.freshness)}</span>
                </div>
                <dl className="sensor-facts">
                  <div><dt>Shelter</dt><dd>{device.shelter}</dd></div>
                  <div><dt>Last seen</dt><dd>{formatTime(device.last_seen)}</dd></div>
                  <div><dt>Battery</dt><dd>{device.battery === null ? "Unknown" : `${device.battery}%`}</dd></div>
                  <div><dt>Signal quality</dt><dd>{device.signal_quality === null ? "Unknown" : `${device.signal_quality}%`}</dd></div>
                  <div><dt>Communication gap</dt><dd>{device.communication_gap ? `${device.communication_gap_minutes ?? "Unknown"} minutes` : "None detected"}</dd></div>
                  <div><dt>Provenance</dt><dd>{device.source_provenance.source_class}</dd></div>
                </dl>
                <div className="sensor-measurements"><strong>Latest measurements</strong>{device.latest_measurements.length ? <ul>{device.latest_measurements.map((measurement) => <li key={`${measurement.name}:${measurement.observed_at ?? "unknown"}`}><span className={measurement.status === "critical" ? "sensor-critical-reading" : ""}>{measurement.name.replaceAll("_", " ")}: {measurementValue(measurement.value, measurement.unit)} ({measurement.status})</span>{measurement.links.length > 0 && <small>Links: {measurement.links.map((link) => `${link.label} [${link.link_type.replaceAll("_", " ")}]`).join("; ")}</small>}</li>)}</ul> : <p>No current measurement available.</p>}</div>
              </article>
            )) : <div className="empty-state">No telemetry is available in this tenant/workspace.</div>}
          </div>

          <div className="sensor-health-column">
            <div className="sensor-health-section-heading"><h3>Gateway health</h3><span>{summary.gateways.length} shown</span></div>
            {summary.gateways.length ? summary.gateways.map((gateway) => <article className={`gateway-card gateway-card-${gateway.status}`} key={gateway.gateway_id}>
              <div className="sensor-card-heading"><div><strong>{gateway.gateway_id}</strong><span>{gateway.shelter}</span></div><span className="sensor-state-label">{gateway.status} / {gateway.freshness}</span></div>
              <dl className="sensor-facts"><div><dt>Last seen</dt><dd>{formatTime(gateway.last_seen)}</dd></div><div><dt>Connected devices</dt><dd>{gateway.connected_devices}</dd></div><div><dt>Communication gap</dt><dd>{gateway.communication_gap ? "Detected" : "None detected"}</dd></div><div><dt>Provenance</dt><dd>{gateway.source_provenance.source_class}</dd></div></dl>
            </article>) : <div className="empty-state">No gateway health is available.</div>}
            <p className="sensor-health-footnote">Telemetry links are contextual references to runway changes, cascade findings, and recommendations. They do not dispatch resources or change operational state.</p>
          </div>
        </div>
      </>}
    </section>
  );
}
