export type ApiStatus = {
  status: "online" | "degraded";
  service: string;
  version: string;
  detail: string;
};

export type ReportSummary = {
  id: string;
  client_record_id: string;
  report_type: string;
  status: string;
  source: { channel: string; source_class: string };
  observed_at: string | null;
  received_at: string | null;
  recorded_at: string;
  location: {
    geometry: { type: "Point"; coordinates: [number, number] };
    uncertainty_m: number | null;
    place_text: string | null;
  } | null;
  warnings: string[];
  revision: number;
};

export type ReportDetail = ReportSummary & {
  tenant_id: string;
  workspace_id: string;
  privacy_class: string;
  original_payload: Record<string, unknown>;
  original_sha256: string;
  normalization: {
    id: string;
    mapping_version: string;
    taxonomy_version: string;
    status: string;
    warnings: string[];
  } | null;
  claims: Array<{
    id: string;
    claim_type: string;
    value: unknown;
    verification_state: string;
    normalization_run_id: string;
  }>;
};

export type GeoFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id: string;
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: Record<string, unknown>;
  }>;
};

type VersionResponse = {
  service: string;
  version: string;
  api_version: string;
};

export async function readApiStatus(signal?: AbortSignal): Promise<ApiStatus> {
  const [liveResponse, versionResponse] = await Promise.all([
    fetch("/api/v1/health/live", { signal }),
    fetch("/api/v1/version", { signal }),
  ]);

  if (!liveResponse.ok || !versionResponse.ok) {
    throw new Error("The API boundary did not pass its liveness checks.");
  }

  const version = (await versionResponse.json()) as VersionResponse;
  return {
    status: "online",
    service: version.service,
    version: version.version,
    detail: `API ${version.api_version} is responding`,
  };
}

const operatorHeaders = { "X-Dev-Identity": "operator" };

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: { ...operatorHeaders, ...init?.headers },
  });
  if (!response.ok) {
    const problem = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(problem?.detail ?? `Request failed with status ${response.status}.`);
  }
  return (await response.json()) as T;
}

export async function readReports(signal?: AbortSignal): Promise<ReportSummary[]> {
  const response = await requestJson<{ items: ReportSummary[] }>("/api/v1/reports", { signal });
  return response.items;
}

export async function readReport(reportId: string, signal?: AbortSignal): Promise<ReportDetail> {
  return requestJson<ReportDetail>(`/api/v1/reports/${encodeURIComponent(reportId)}`, { signal });
}

export async function seedDemo(): Promise<{ created: number; synthetic: boolean }> {
  return requestJson<{ created: number; synthetic: boolean }>("/api/v1/demo/seed", { method: "POST" });
}

export async function createReport(reportType: string, placeText: string): Promise<{ report_id: string }> {
  const clientRecordId = `rpt_ui_${crypto.randomUUID()}`;
  const now = new Date().toISOString();
  return requestJson<{ report_id: string }>("/api/v1/reports", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": clientRecordId,
    },
    body: JSON.stringify({
      contract_version: 1,
      client_record_id: clientRecordId,
      observed_at: now,
      received_at: now,
      source: { channel: "evidence_workbench", source_class: "authenticated_operator" },
      location: {
        geometry: { type: "Point", coordinates: [91.742, 26.184] },
        uncertainty_m: 250,
        place_text: placeText || null,
      },
      report_type: reportType,
      facts: { people_affected: null, access_state: "unknown" },
      privacy_class: "restricted_operational",
    }),
  });
}

export async function readMapFeatures(signal?: AbortSignal): Promise<GeoFeatureCollection> {
  return requestJson<GeoFeatureCollection>("/api/v1/map/features?limit=100", { signal });
}
