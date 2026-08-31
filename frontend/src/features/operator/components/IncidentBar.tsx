import type { CommandIncident } from "../api";

export function IncidentBar({ incident, busy, isSynthetic, onPause }: { incident: CommandIncident | null; busy: boolean; isSynthetic?: boolean; onPause?: () => void }) {
  const online = navigator.onLine;

  if (!incident) {
    return (
      <div className="state-banner" role="status">
        <div><strong>NO ACTIVE INCIDENT</strong> // SYSTEM IN STANDBY</div>
        {!online && <span style={{color: "var(--status-critical)"}}>OFFLINE</span>}
      </div>
    );
  }

  return (
    <div className="state-banner" role="status">
      <div>
        <strong style={{color: "var(--accent-cyan)", marginRight: "12px"}}>{incident.name}</strong>
        <span style={{marginRight: "12px"}}>|</span>
        <span style={{marginRight: "12px"}}>{incident.operational_period}</span>
        <span style={{marginRight: "12px"}}>|</span>
        <span style={{marginRight: "12px", textTransform: "uppercase"}}>{incident.phase.replaceAll("_", " ")}</span>
        <span style={{marginRight: "12px"}}>|</span>
        <span style={{color: "var(--status-critical)", marginRight: "12px"}}>{incident.severity.toUpperCase()}</span>
        <span style={{marginRight: "12px"}}>|</span>
        <span>Commander: {incident.roles.incident_commander ?? "unassigned"}</span>
      </div>
      <div>
        {busy ? (
          <span style={{color: "var(--status-warning)", marginRight: "12px"}}>SYNCING...</span>
        ) : (
          <span style={{color: "var(--text-muted)", marginRight: "12px"}}>UPLINK SECURE</span>
        )}
                {!isSynthetic && incident.status === "active" && onPause ? <button type="button" className="btn-secondary" disabled={busy} onClick={onPause} style={{ marginRight: "12px", padding: "0.35rem 0.65rem" }}>Pause incident</button> : null}
        <strong style={{
          color: isSynthetic ? "var(--status-warning)" : (online ? "var(--status-success)" : "var(--status-critical)"),
          backgroundColor: isSynthetic ? "#fffbeb" : "transparent",
          padding: isSynthetic ? "2px 6px" : "0",
          borderRadius: "2px",
          border: isSynthetic ? "1px solid var(--status-warning)" : "none"
        }}>
          {isSynthetic ? "SYNTHETIC TABLETOP" : (online ? "LIVE INCIDENT" : "OFFLINE")}
        </strong>
      </div>
    </div>
  );
}
