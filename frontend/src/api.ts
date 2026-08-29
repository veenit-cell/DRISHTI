export type ApiStatus = {
  status: "online" | "degraded";
  service: string;
  version: string;
  detail: string;
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
