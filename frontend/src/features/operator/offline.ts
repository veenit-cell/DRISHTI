export type OfflineCommandKind = "report" | "acknowledgement" | "en_route" | "on_scene" | "paused" | "completion" | "route_observation" | "outcome";
export type OfflineCommandStatus = "queued" | "syncing" | "accepted" | "replayed" | "rejected" | "conflict" | "blocked";

export type OfflineCommand = {
  command_id: string;
  aggregate_id: string;
  sequence: number;
  kind: OfflineCommandKind;
  client_timestamp: string;
  payload: Record<string, unknown>;
  tenant_id: string;
  workspace_id: string;
};

export type StoredOfflineCommand = OfflineCommand & {
  local_status: OfflineCommandStatus;
  attempts: number;
  last_error?: string;
  server_timestamp?: string;
  reconciled_at?: string;
};

export type ReconciliationResult = {
  command_id: string;
  aggregate_id: string;
  sequence: number;
  status: "accepted" | "replayed" | "rejected" | "conflict" | "blocked";
  client_timestamp: string | null;
  server_timestamp: string | null;
  reason: string | null;
  conflict_explanation: string | null;
  expected_sequence: number | null;
  retryable: boolean;
};

export type ReconciliationSummary = {
  accepted: number;
  replayed: number;
  rejected: number;
  blocked: number;
  conflicts: number;
  server_timestamp: string;
  expected_sequence_number: Record<string, number>;
  safe_to_retry: boolean;
  retryable_command_ids: string[];
};

export type OfflineSyncResponse = {
  accepted_at: string;
  results: ReconciliationResult[];
  reconciliation: ReconciliationSummary;
};

export type OfflineSummary = {
  last_successful_sync: string | null;
  last_known_state_timestamp: string | null;
};

const DB_NAME = "shelter-field-pwa";
const STORE = "outbox";
const META_STORE = "offline_meta";
const MAX_BATCH = 20;
const TERMINAL_STATUSES = new Set<OfflineCommandStatus>(["accepted", "replayed", "rejected"]);

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 2);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "command_id" });
      if (!db.objectStoreNames.contains(META_STORE)) db.createObjectStore(META_STORE, { keyPath: "key" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB unavailable"));
  });
}

function sortCommands(commands: StoredOfflineCommand[]): StoredOfflineCommand[] {
  return [...commands].sort((a, b) => a.aggregate_id.localeCompare(b.aggregate_id) || a.sequence - b.sequence || a.client_timestamp.localeCompare(b.client_timestamp) || a.command_id.localeCompare(b.command_id));
}

function isPendingStatus(status: OfflineCommandStatus): boolean {
  return !TERMINAL_STATUSES.has(status);
}

function offlineSyncIdempotencyKey(commands: StoredOfflineCommand[]): string {
  const identity = commands.map((command) => `${command.command_id}:${command.sequence}`).join("|");
  let hash = 2166136261;
  for (let index = 0; index < identity.length; index += 1) {
    hash ^= identity.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `ui-offline-sync-${(hash >>> 0).toString(16)}`;
}

export function isOfflineCommandPending(command: StoredOfflineCommand): boolean {
  return isPendingStatus(command.local_status);
}

export async function queueCommand(command: OfflineCommand): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction([STORE, META_STORE], "readwrite");
    tx.objectStore(STORE).put({ ...command, local_status: "queued", attempts: 0 });
    const sequenceKey = `sequence:${command.tenant_id}:${command.workspace_id}:${command.aggregate_id}`;
    const metaStore = tx.objectStore(META_STORE);
    const request = metaStore.get(sequenceKey);
    request.onsuccess = () => metaStore.put({ key: sequenceKey, value: Math.max(command.sequence, Number(request.result?.value ?? 0)) });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("Outbox write failed"));
  });
  await recordLastKnownStateTimestamp(command.client_timestamp);
}

async function reserveNextSequence(tenantId: string, workspaceId: string, aggregateId: string): Promise<number> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction([META_STORE, STORE], "readwrite");
    const store = tx.objectStore(META_STORE);
    const key = `sequence:${tenantId}:${workspaceId}:${aggregateId}`;
    let next = 1;
    let metaValue = 0;
    let existingCommands: Array<{ aggregate_id?: string; sequence?: number }> = [];
    let readsComplete = 0;
    const finishReads = () => {
      readsComplete += 1;
      if (readsComplete !== 2) return;
      const existingSequence = Math.max(0, ...existingCommands.filter((command) => command.aggregate_id === aggregateId).map((command) => Number(command.sequence ?? 0)));
      next = Math.max(metaValue, existingSequence) + 1;
      store.put({ key, value: next });
    };
    const metaRequest = store.get(key);
    metaRequest.onsuccess = () => { metaValue = Number(metaRequest.result?.value ?? 0); finishReads(); };
    const outboxRequest = tx.objectStore(STORE).getAll();
    outboxRequest.onsuccess = () => { existingCommands = outboxRequest.result as Array<{ aggregate_id?: string; sequence?: number }>; finishReads(); };
    tx.oncomplete = () => resolve(next);
    tx.onerror = () => reject(tx.error ?? new Error("Offline sequence reservation failed"));
  });
}

export async function queueTaskUpdate(taskId: string, status: "acknowledged" | "en_route" | "on_scene" | "paused" | "completed", payload: Record<string, unknown> = {}): Promise<void> {
  const sequence = await reserveNextSequence("org_demo", "evt_demo", taskId);
  const kind = status === "acknowledged" ? "acknowledgement" : status === "completed" ? "completion" : status;
  await queueCommand({ command_id: `offline-${taskId}-${sequence}-${Date.now()}`, aggregate_id: taskId, sequence, kind, client_timestamp: new Date().toISOString(), payload: { status, ...payload }, tenant_id: "org_demo", workspace_id: "evt_demo" });
}

export async function readOutbox(): Promise<StoredOfflineCommand[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE).objectStore(STORE).getAll();
    request.onsuccess = () => {
      const records = request.result as Array<Partial<StoredOfflineCommand>>;
      resolve(sortCommands(records.map((command) => ({ ...command, local_status: command.local_status ?? "queued", attempts: command.attempts ?? 0 }) as StoredOfflineCommand)));
    };
    request.onerror = () => reject(request.error ?? new Error("Outbox read failed"));
  });
}

export async function getOfflineSummary(): Promise<OfflineSummary> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction(META_STORE).objectStore(META_STORE).getAll();
    request.onsuccess = () => {
      const values = new Map((request.result as Array<{ key: string; value: string }>).map((item) => [item.key, item.value]));
      resolve({ last_successful_sync: values.get("last_successful_sync") ?? null, last_known_state_timestamp: values.get("last_known_state_timestamp") ?? null });
    };
    request.onerror = () => reject(request.error ?? new Error("Offline metadata read failed"));
  });
}

async function recordLastKnownStateTimestamp(timestamp: string): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readwrite");
    tx.objectStore(META_STORE).put({ key: "last_known_state_timestamp", value: timestamp });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("Offline metadata write failed"));
  });
}

async function updateStoredCommands(updates: Array<{ command_id: string; local_status: OfflineCommandStatus; result?: ReconciliationResult; attempts?: number }>): Promise<void> {
  if (!updates.length) return;
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    updates.forEach((update) => {
      const request = store.get(update.command_id);
      request.onsuccess = () => {
        const command = request.result as StoredOfflineCommand | undefined;
        if (!command) return;
        const result = update.result;
        store.put({ ...command, local_status: update.local_status, attempts: update.attempts ?? command.attempts, last_error: result?.conflict_explanation ?? result?.reason ?? undefined, server_timestamp: result?.server_timestamp ?? undefined, reconciled_at: result ? new Date().toISOString() : command.reconciled_at });
      };
    });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("Outbox status update failed"));
  });
}

export async function retryOutbox(): Promise<void> {
  const commands = await readOutbox();
  await updateStoredCommands(commands.filter((command) => command.local_status === "conflict" || command.local_status === "blocked").map((command) => ({ command_id: command.command_id, local_status: "queued" })));
}

export async function syncOutbox(): Promise<{ accepted: number; replayed: number; conflicts: number; blocked: number; rejected: number; results: ReconciliationResult[]; reconciliation: ReconciliationSummary | null }> {
  const commands = sortCommands((await readOutbox()).filter((command) => isPendingStatus(command.local_status))).slice(0, MAX_BATCH);
  if (!commands.length) return { accepted: 0, replayed: 0, conflicts: 0, blocked: 0, rejected: 0, results: [], reconciliation: null };
  if (typeof navigator !== "undefined" && !navigator.onLine) throw new Error("Cannot reconcile commands while offline");

  await updateStoredCommands(commands.map((command) => ({ command_id: command.command_id, local_status: "syncing", attempts: command.attempts + 1 })));
  const requestCommands = commands.map(({ local_status: _localStatus, attempts: _attempts, last_error: _lastError, server_timestamp: _serverTimestamp, reconciled_at: _reconciledAt, ...command }) => command);
  let response: Response;
  try {
    response = await fetch("/api/v1/offline-sync", { method: "POST", headers: { "Content-Type": "application/json", "X-Dev-Identity": "operator", "Idempotency-Key": offlineSyncIdempotencyKey(commands) }, body: JSON.stringify({ commands: requestCommands }) });
  } catch (reason) {
    await updateStoredCommands(commands.map((command) => ({ command_id: command.command_id, local_status: "queued", result: { command_id: command.command_id, aggregate_id: command.aggregate_id, sequence: command.sequence, status: "rejected", client_timestamp: command.client_timestamp, server_timestamp: null, reason: reason instanceof Error ? reason.message : "Network unavailable", conflict_explanation: null, expected_sequence: null, retryable: true } })));
    throw reason;
  }
  if (!response.ok) {
    await updateStoredCommands(commands.map((command) => ({ command_id: command.command_id, local_status: "queued" })));
    throw new Error(`Sync failed (${response.status})`);
  }
  const payload = (await response.json()) as OfflineSyncResponse;
  await updateStoredCommands(payload.results.map((result) => ({ command_id: result.command_id, local_status: result.status, result })));
  const serverTimestamp = payload.reconciliation?.server_timestamp ?? payload.accepted_at;
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(META_STORE, "readwrite");
    tx.objectStore(META_STORE).put({ key: "last_successful_sync", value: serverTimestamp });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("Offline metadata write failed"));
  });
  return { accepted: payload.reconciliation?.accepted ?? payload.results.filter((item) => item.status === "accepted").length, replayed: payload.reconciliation?.replayed ?? payload.results.filter((item) => item.status === "replayed").length, conflicts: payload.reconciliation?.conflicts ?? payload.results.filter((item) => item.status === "conflict" || item.status === "blocked").length, blocked: payload.reconciliation?.blocked ?? payload.results.filter((item) => item.status === "conflict" || item.status === "blocked").length, rejected: payload.reconciliation?.rejected ?? payload.results.filter((item) => item.status === "rejected").length, results: payload.results, reconciliation: payload.reconciliation ?? null };
}

export function printTaskPacket(task: { id: string; resource: string; status: string }): void {
  const popup = window.open("", "task-packet", "width=700,height=700");
  if (!popup) return;
  const main = popup.document.createElement("main");
  const title = popup.document.createElement("h1");
  title.textContent = "Field mission packet";
  main.appendChild(title);
  [["Task", task.id], ["Resource", task.resource], ["Status", task.status], ["Data state", "Last-known local state; server reconciliation required"]].forEach(([label, value]) => {
    const p = popup.document.createElement("p");
    const strong = popup.document.createElement("strong");
    strong.textContent = `${label}: `;
    p.append(strong, value);
    main.appendChild(p);
  });
  const note = popup.document.createElement("p");
  note.textContent = "Paper/radio fallback: read the task ID, destination, status, and time to the commander. Do not record personal data.";
  main.appendChild(note);
  popup.document.body.replaceChildren(main);
  popup.print();
}
