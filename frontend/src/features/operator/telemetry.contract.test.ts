import type { TelemetrySummary } from "./api";

export function assertTelemetrySummaryContract(summary: TelemetrySummary): void {
  if (!summary.warning.toLowerCase().includes("does not mean safe")) throw new Error("telemetry warning must reject silent-is-safe interpretation");
  if (summary.devices.some((device) => "device_key" in device || "join_key" in device)) throw new Error("telemetry summary must not expose device keys");
  if (summary.devices.some((device) => device.freshness === "fresh" && device.communication_gap)) throw new Error("fresh telemetry cannot be marked as a communication gap");
  if (summary.devices.some((device) => device.latest_measurements.some((measurement) => measurement.status === "critical" && !measurement.links))) throw new Error("critical telemetry readings require operational links");
}
