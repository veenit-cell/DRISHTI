import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SensorHealthPanel } from "./SensorHealthPanel";
import type { TelemetrySummary } from "../api";

const summary: TelemetrySummary = {
  generated_at: "2026-01-01T00:00:00Z",
  mode: "synthetic",
  source: "synthetic-fixture",
  freshness: "silent",
  counts: { fresh_sensors: 0, stale_sensors: 0, silent_sensors: 1, critical_readings: 0, gateway_count: 0 },
  devices: [],
  gateways: [],
  warning: "No telemetry does not mean safe conditions.",
};

describe("SensorHealthPanel", () => {
  it("renders an explicit synthetic and no-telemetry warning", () => {
    render(<SensorHealthPanel summary={summary} state="ready" />);
    expect(screen.getByRole("heading", { name: "Sensor Health" })).toBeInTheDocument();
    expect(screen.getByText("No telemetry does not mean safe conditions.")).toBeInTheDocument();
    expect(screen.getByText("Synthetic telemetry")).toBeInTheDocument();
    expect(screen.getByText("No telemetry is available in this tenant/workspace.")).toBeInTheDocument();
  });

  it("keeps loading and retry states accessible", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<SensorHealthPanel summary={null} state="loading" onRetry={onRetry} />);
    expect(screen.getByRole("status", { name: "Loading telemetry health" })).toBeInTheDocument();
    rerender(<SensorHealthPanel summary={null} state="error" error="Backend unavailable" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry telemetry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
