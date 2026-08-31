import { describe, expect, it } from "vitest";
import { assertCascadePanelContract } from "./cascade.contract.test";
import { assertEvidenceTrustContract } from "./evidence-trust.contract.test";
import { assertOfflineReconciliationContract } from "./offline.contract.test";
import { assertOperatorApiFallbackContracts } from "./api.contract.test";
import { assertOperatorWorkspaceContract } from "./OperatorWorkspace.contract.test";
import { assertProvenanceRenderingContract } from "./provenance.contract.test";
import { assertScenarioLabContract } from "./scenario.contract.test";
import { assertTelemetrySummaryContract } from "./telemetry.contract.test";
import { assertOperationalUpdateContract } from "./updates.contract.test";
import type { TelemetrySummary, WhatIfResult } from "./api";

const projection = (label: "baseline" | "do_nothing" | "intervention") => ({
  label,
  changed_inputs: {},
  projection: {
    formula_version: "test",
    observed_at: null,
    horizon_hours: 48,
    projections: [{
      resource: "water",
      state: "critical",
      time_to_critical_hours: 3,
      threshold: null,
      unit: "hours",
      freshness_state: "fresh",
      confidence: "medium",
      within_horizon: true,
      contributors: ["synthetic fixture"],
    }],
  },
  resource_consumption: {},
  risk_level: "medium" as const,
  tradeoffs: ["synthetic test tradeoff"],
  uncertainty: ["synthetic test uncertainty"],
  scenario_hash: `${label}-hash`,
});

describe("operator contract harness", () => {
  it("runs the update, provenance, cascade, evidence, and workspace contracts", () => {
    expect(() => assertCascadePanelContract()).not.toThrow();
    expect(() => assertEvidenceTrustContract()).not.toThrow();
    expect(() => assertProvenanceRenderingContract()).not.toThrow();
    expect(() => assertOperatorWorkspaceContract()).not.toThrow();
    expect(() => assertOperationalUpdateContract()).not.toThrow();
  });

  it("runs the scenario and telemetry contracts with synthetic fixtures", () => {
    const scenario = {
      scenario_version: "test",
      input_hash: "test",
      baseline: projection("baseline"),
      do_nothing: projection("do_nothing"),
      intervention: projection("intervention"),
    } satisfies WhatIfResult;
    expect(() => assertScenarioLabContract(scenario)).not.toThrow();

    const telemetry = {
      generated_at: new Date(0).toISOString(),
      mode: "synthetic",
      source: "synthetic-fixture",
      freshness: "silent",
      counts: { fresh_sensors: 0, stale_sensors: 0, silent_sensors: 1, critical_readings: 0, gateway_count: 0 },
      devices: [],
      gateways: [],
      warning: "No telemetry does not mean safe conditions.",
    } satisfies TelemetrySummary;
    expect(() => assertTelemetrySummaryContract(telemetry)).not.toThrow();
  });

  it("runs the offline reconciliation contract without asserting local success", () => {
    expect(() => assertOfflineReconciliationContract({
      accepted_at: new Date(0).toISOString(),
      results: [{ command_id: "cmd-1", aggregate_id: "task-1", sequence: 1, status: "accepted", client_timestamp: new Date(0).toISOString(), server_timestamp: new Date(0).toISOString(), reason: "reconciled", conflict_explanation: null, expected_sequence: 1, retryable: false }],
      reconciliation: { accepted: 1, replayed: 0, rejected: 0, blocked: 0, conflicts: 0, server_timestamp: new Date(0).toISOString(), expected_sequence_number: { "task-1": 1 }, safe_to_retry: false, retryable_command_ids: [] },
    }, [{ command_id: "cmd-1", aggregate_id: "task-1", sequence: 1, kind: "acknowledgement", client_timestamp: new Date(0).toISOString(), payload: {}, tenant_id: "tenant-1", workspace_id: "workspace-1", local_status: "accepted", attempts: 1 }])).not.toThrow();
  });

  it("covers live API failure and explicit synthetic fallback behavior", async () => {
    await expect(assertOperatorApiFallbackContracts()).resolves.toBeUndefined();
  });
});
