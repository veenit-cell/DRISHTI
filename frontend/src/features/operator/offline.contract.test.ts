import type { OfflineSyncResponse, StoredOfflineCommand } from "./offline";

export function assertOfflineReconciliationContract(response: OfflineSyncResponse, commands: StoredOfflineCommand[]): void {
  if (!response.accepted_at || !response.reconciliation.server_timestamp) throw new Error("offline reconciliation timestamps are required");
  if (response.results.some((result) => !result.command_id || !result.client_timestamp || result.expected_sequence === undefined)) throw new Error("offline command result is incomplete");
  if (response.results.some((result) => result.status === "rejected" && result.retryable)) throw new Error("rejected commands must not be marked safe to retry");
  if (commands.some((command) => command.local_status === "queued" && command.last_error?.includes("applied"))) throw new Error("queued local commands must not be presented as applied");
}
