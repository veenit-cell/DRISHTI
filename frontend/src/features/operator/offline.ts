export type OfflineCommand = { command_id: string; aggregate_id: string; sequence: number; kind: "report" | "acknowledgement" | "en_route" | "on_scene" | "paused" | "completion" | "route_observation" | "outcome"; client_timestamp: string; payload: Record<string, unknown>; tenant_id: string; workspace_id: string };

const DB_NAME = "shelter-field-pwa";
const STORE = "outbox";
const MAX_BATCH = 20;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "command_id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB unavailable"));
  });
}

export async function queueCommand(command: OfflineCommand): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => { const tx = db.transaction(STORE, "readwrite"); tx.objectStore(STORE).put(command); tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error ?? new Error("Outbox write failed")); });
}

export async function queueTaskUpdate(taskId: string, status: "acknowledged" | "en_route" | "on_scene" | "paused" | "completed", payload: Record<string, unknown> = {}): Promise<void> {
  const pending = await readOutbox();
  const sequence = Math.max(0, ...pending.filter((command) => command.aggregate_id === taskId).map((command) => command.sequence)) + 1;
  const kind = status === "acknowledged" ? "acknowledgement" : status === "completed" ? "completion" : status;
  await queueCommand({ command_id: `offline-${taskId}-${sequence}-${Date.now()}`, aggregate_id: taskId, sequence, kind, client_timestamp: new Date().toISOString(), payload: { status, ...payload }, tenant_id: "org_demo", workspace_id: "evt_demo" });
}

export async function readOutbox(): Promise<OfflineCommand[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => { const request = db.transaction(STORE).objectStore(STORE).getAll(); request.onsuccess = () => resolve((request.result as OfflineCommand[]).sort((a, b) => a.client_timestamp.localeCompare(b.client_timestamp)).slice(0, MAX_BATCH)); request.onerror = () => reject(request.error ?? new Error("Outbox read failed")); });
}

export async function syncOutbox(): Promise<{ accepted: number; conflicts: number; rejected: number }> {
  const commands = await readOutbox();
  if (!commands.length) return { accepted: 0, conflicts: 0, rejected: 0 };
  const response = await fetch("/api/v1/offline-sync", { method: "POST", headers: { "Content-Type": "application/json", "X-Dev-Identity": "operator" }, body: JSON.stringify({ commands }) });
  if (!response.ok) throw new Error(`Sync failed (${response.status})`);
  const results = (await response.json()) as { results: Array<{ command_id: string; status: string }> };
  const removable = new Set(results.results.filter((item) => item.status === "accepted" || item.status === "replayed").map((item) => item.command_id));
  if (removable.size) { const db = await openDb(); await new Promise<void>((resolve, reject) => { const tx = db.transaction(STORE, "readwrite"); removable.forEach((id) => tx.objectStore(STORE).delete(id)); tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error); }); }
  return { accepted: results.results.filter((item) => item.status === "accepted" || item.status === "replayed").length, conflicts: results.results.filter((item) => item.status === "conflict").length, rejected: results.results.filter((item) => item.status === "rejected").length };
}

export function printTaskPacket(task: { id: string; resource: string; status: string }): void {
  const popup = window.open("", "task-packet", "width=700,height=700");
  if (!popup) return;
  popup.document.body.innerHTML = `<main><h1>Field task packet</h1><p><strong>Task:</strong> ${task.id}</p><p><strong>Resource:</strong> ${task.resource}</p><p><strong>Status:</strong> ${task.status}</p><hr><p>Paper/radio fallback: read task ID, destination, status, and time to the commander. Do not record personal data.</p></main>`;
  popup.print();
}
