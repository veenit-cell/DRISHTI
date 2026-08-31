import type { CommandIncident } from "../api";

export function IncidentBar({ incident, busy, isSynthetic, workspaceMode, onPause, onMenuClick, menuOpen = false }: { incident: CommandIncident | null; busy: boolean; isSynthetic?: boolean; workspaceMode?: "live" | "synthetic" | "mixed"; onPause?: () => void; onMenuClick?: () => void; menuOpen?: boolean }) {
  const online = navigator.onLine;

  const modeText = workspaceMode === "live" ? "Live Mode" : workspaceMode === "mixed" ? "Mixed Mode" : isSynthetic ? "Training Mode" : (online ? "Live" : "Offline");

  return (
    <header className="app-header">
      <div className="app-header-left">
        {/* Mobile menu toggle */}
        {onMenuClick && (
          <button type="button" className="btn-ghost mobile-menu-button" onClick={onMenuClick} aria-label={menuOpen ? "Close main navigation" : "Open main navigation"} aria-expanded={menuOpen} aria-controls="main-navigation" style={{padding: "0.4rem"}}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
        )}

        {incident ? (
          <div style={{display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap"}}>
            <span className="app-header-title" style={{color: "var(--accent-cyan)"}}>{incident.name}</span>
            <span className="badge" aria-label={`Incident severity: ${incident.severity}`}>
              <span className={`badge-dot ${incident.severity === "critical" ? "critical" : "info"}`} aria-hidden="true" />
              Severity: {incident.severity.toUpperCase()}
            </span>
            <span style={{color: "var(--text-dim)", fontSize: "0.8rem"}}>{incident.operational_period}</span>
            <span style={{color: "var(--text-dim)", fontSize: "0.75rem"}}>·</span>
            <span style={{color: "var(--text-muted)", fontSize: "0.8rem", textTransform: "capitalize"}}>{incident.phase.replaceAll("_", " ")}</span>
            <span style={{color: "var(--text-dim)", fontSize: "0.75rem"}}>·</span>
            <span style={{color: "var(--text-dim)", fontSize: "0.8rem"}}>Commander: {incident.roles.incident_commander ?? "unassigned"}</span>
          </div>
        ) : (
          <span className="app-header-title" style={{color: "var(--text-muted)"}}>No active incident</span>
        )}
      </div>

      <div className="app-header-right">
        {/* Busy/sync indicator */}
        {busy && (
          <span className="badge" role="status" aria-live="polite" style={{borderColor: "rgba(245, 158, 11, 0.3)", color: "var(--status-warning)"}}>
            <span className="badge-dot warning" aria-hidden="true" />
            Synchronizing workspace data
          </span>
        )}

        {/* Pause button for live incidents */}
        {!isSynthetic && incident?.status === "active" && onPause ? (
          <button type="button" className="btn-ghost" disabled={busy} onClick={onPause} style={{fontSize: "0.8rem", color: "var(--text-muted)"}}>
            ⏸ Pause
          </button>
        ) : null}

        {/* Mode indicator */}
        <span className="badge" role="status" aria-label={`Data mode: ${modeText}`} style={{
          borderColor: isSynthetic ? "rgba(245, 158, 11, 0.3)" : (online ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"),
          color: isSynthetic ? "var(--status-warning)" : (online ? "var(--status-success)" : "var(--status-critical)"),
          background: isSynthetic ? "var(--status-warning-bg)" : (online ? "var(--status-success-bg)" : "var(--status-critical-bg)"),
        }}>
          <span className={`badge-dot ${isSynthetic ? "warning" : (online ? "" : "critical")}`} aria-hidden="true" />
          {modeText}
        </span>
      </div>
    </header>
  );
}
