# RescueOps Judge Demo Script

**Target duration:** 3 minutes 30 seconds to 3 minutes 50 seconds
**Rule:** call the tabletop data synthetic; never call it live field data.

## 0:00–0:20 — Opening

> In the first 24 hours of a disaster, the problem is not report volume. It is deciding which incomplete reports require action, what remains unknown, and who owns the decision. RescueOps is human-supervised evidence-to-action software, not an autonomous dispatcher.

## 0:20–0:50 — Live authority

Click **Activate Incident**.

> The FastAPI backend creates the command incident and records its phase, severity, operational period, and commander in the incident bar. Commander authority is explicit.

Click **Pause incident**.

> Pause is not a cosmetic toggle. The server confirms the paused state before the screen changes. We return to a paused-session landing state, where **Resume incident** continues the same record and **Close incident** ends it. A paused incident is never presented as finished.

Click **Close incident**.

## 0:50–1:10 — Synthetic tabletop

Click **Start Synthetic Tabletop**, then **Begin command briefing**.

> From here, every signal is synthetic and visibly labelled. This flood replay includes water pressure, a blocked corridor, contradictory reports, and a communications-dark settlement.

## 1:10–1:40 — Command brief and map

Show Command, then click **Map**.

> The brief answers what the commander must decide next: up to three decisions on the left, the common operating picture in the centre, and command pulse on the right. The map separates confirmed, probable, blocked, and no-information states. A silent settlement is a verification need, never a safe area.

## 1:40–2:10 — Evidence

Click **Reports**. Use **Receive report**; then point to **Corroborate**, **Contradict**, and **Assign verification**.

> Reports retain source, time, location uncertainty, claims, and review state. Contradiction remains visible because it may change the decision. This is evidence before action, with an accountable review trail.

## 2:10–2:40 — Mission decision

Click **Missions**. Point to **Create mission**, ready-resource selection, then **Acknowledge**, **Mark en route**, **Arrived on scene**, **Pause**, and **Complete & record outcome**.

> RescueOps checks capability, readiness, and route constraints—not proximity alone. A commander approves the assignment, and completion preserves outcome evidence and residual need.

## 2:40–3:05 — Sustainment and handover

Click **Resources**, **Logistics**, and **Handover**.

> Resources show readiness and current task. Logistics shows runway, reserve floors, and mutual-aid drafts. Handover can **Generate SITREP**, **Run synthetic replay**, and **Run fault tabletop**. Offline commands are honestly marked queued for reconciliation; this MVP does not claim they have already changed task state.

## 3:05–3:35 — Architecture and value

> The frontend is React, TypeScript, Vite, and Leaflet. It uses scoped `/api/v1` requests to FastAPI modules for incident command, evidence, coverage, missions, decisions, mutual aid, and pilot exercises. PostgreSQL/PostGIS is the durable target; deterministic in-memory stores support local development and tests. Writes use idempotency keys, problem responses, and audit records.

> The value is not another dashboard. RescueOps keeps uncertainty visible, links evidence to constrained action, keeps human approval explicit, and preserves the rationale for the next shift.

## Button reference

- **Activate / Pause / Resume / Close incident:** create, preserve, resume, or end the commander-owned incident.
- **Start Synthetic Tabletop / Begin command briefing:** enter explicitly simulated replay.
- **Map, Reports, Missions, Resources, Logistics, Handover:** open connected workspaces.
- **Evidence and mission buttons:** review evidence, request verification, approve and progress missions, and record outcomes.
- **SITREP and tabletop buttons:** create bounded handover and exercise outputs.

**Do not claim:** live agency integration, autonomous dispatch, production authentication, measured field performance, or automatic application of queued offline task updates.