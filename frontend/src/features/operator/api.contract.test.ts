import { getCommandSummary, type CommandSummary } from "./api";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const apiSummary: CommandSummary = {
  generated_at: "2026-09-04T10:00:00Z",
  correlation_id: "api-contract",
  source: "api",
  freshness: { state: "fresh", as_of: "2026-09-04T10:00:00Z" },
  availability: { state: "available", unavailable_stores: [] },
  mode: "live",
  metrics: {
    ready_resources: 2,
    total_resources: 3,
    active_tasks: 1,
    response_queue: 1,
    verification_queue: 0,
    population_influx: 0,
    water_runway_hours: 12,
    contamination: "clear",
  },
  priorities: [],
  data_quality: { contamination: "clear", synthetic: false },
};

type FetchHandler = (...args: Parameters<typeof fetch>) => ReturnType<typeof fetch>;

async function withFetch(handler: FetchHandler, callback: () => Promise<void>): Promise<void> {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler as typeof fetch;
  try {
    await callback();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

export async function assertOperatorApiFallbackContracts(): Promise<void> {
  await withFetch(
    async () => new Response(JSON.stringify({ detail: "command backend unavailable" }), { status: 503, headers: { "content-type": "application/problem+json" } }),
    async () => {
      let rejected = false;
      try {
        await getCommandSummary({ allowSyntheticFallback: false });
      } catch (error) {
        rejected = error instanceof Error && error.message === "command backend unavailable";
      }
      assert(rejected, "live backend failures must reject instead of returning fabricated summary data");
    },
  );

  await withFetch(
    async () => new Response(JSON.stringify({ detail: "training backend unavailable" }), { status: 503, headers: { "content-type": "application/problem+json" } }),
    async () => {
      const summary = await getCommandSummary({ allowSyntheticFallback: true });
      assert(summary.source === "fallback", "synthetic fallback must be explicitly marked");
      assert(summary.mode === "synthetic", "synthetic fallback must remain synthetic mode");
    },
  );

  await withFetch(
    async () => new Response(JSON.stringify(apiSummary), { status: 200, headers: { "content-type": "application/json" } }),
    async () => {
      const summary = await getCommandSummary({ allowSyntheticFallback: false });
      assert(summary.source === "api", "successful responses must be marked as API data");
      assert(summary.metrics.ready_resources === 2, "successful API metrics must be preserved");
    },
  );
}
