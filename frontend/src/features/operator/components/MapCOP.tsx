import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import { listMapFeatures, type MapFeature } from "../api";
import { syntheticGeography } from "../fixtures/syntheticGeography";
import L from "leaflet";

function MapBounds({ features }: { features: MapFeature[] }) {
  const map = useMap();

  useEffect(() => {
    // Invalidate map size so Leaflet renders tiles properly inside flex and tab containers
    map.invalidateSize();
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 250);
    return () => clearTimeout(timer);
  }, [map]);

  useEffect(() => {
    const points = features
      .filter((f) => f.geometry && f.geometry.type === "Point" && Array.isArray(f.geometry.coordinates))
      .map((f) => {
        const coords = f.geometry.coordinates as [number, number];
        return L.latLng(coords[1], coords[0]);
      });

    if (points.length > 0) {
      const bounds = L.latLngBounds(points);
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
    }
  }, [features, map]);

  return null;
}

const getMarkerIcon = (state: string, kind: string, isInformationGap?: boolean, routeFeasibility?: string) => {
  let color = "#3b82f6"; // blue default
  let border = "#ffffff";
  let pulseClass = "";

  const s = state.toLowerCase();
  const k = kind.toLowerCase();

  if (isInformationGap || s === "silent" || s === "communications-dark" || s === "no-information") {
    color = "#8b5cf6"; // violet for information gap
    border = "#f59e0b"; // amber border
    pulseClass = "pulse-information-gap";
  } else if (routeFeasibility === "blocked" || s === "blocked") {
    color = "#ef4444"; // red for blocked route
    border = "#7f1d1d";
  } else if (s === "contradictory" || s === "contradicted") {
    color = "#f97316"; // orange
  } else if (s === "confirmed" && k === "need") {
    color = "#ef4444"; // red
  } else if (k === "resource") {
    color = "#06b6d4"; // cyan
  } else if (s === "probable" || s === "stale") {
    color = "#f59e0b"; // amber
  }

  return L.divIcon({
    className: `custom-map-marker ${pulseClass}`,
    html: `<div style="background-color: ${color}; width: 18px; height: 18px; border-radius: 50%; border: 2px solid ${border}; box-shadow: 0 2px 6px rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; color: white; font-size: 10px; font-weight: bold;">${isInformationGap ? '?' : ''}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11]
  });
};

export function MapCOP({ setError, isSynthetic = false, refreshToken = 0 }: { setError: (value: string) => void; isSynthetic?: boolean; refreshToken?: number }) {
  const [features, setFeatures] = useState<MapFeature[]>(isSynthetic ? syntheticGeography : []);

  useEffect(() => {
    const baseline = isSynthetic ? syntheticGeography : [];
    void listMapFeatures()
      .then((liveFeatures) => setFeatures([...baseline, ...liveFeatures.filter((feature) => !baseline.some((seed) => seed.id === feature.id))]))
      .catch((reason) => {
        setFeatures(baseline);
        if (!isSynthetic) setError(reason instanceof Error ? reason.message : "Map unavailable");
      });
  }, [setError, isSynthetic, refreshToken]);

  return (
    <div className="map-container" style={{ width: "100%", height: "100%", minHeight: "450px", position: "relative" }}>
      {features.length === 0 && (
        <div style={{
          position: "absolute",
          top: 12,
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 1000,
          background: "rgba(15, 23, 42, 0.85)",
          color: "#f8fafc",
          padding: "6px 14px",
          borderRadius: "20px",
          fontSize: "0.75rem",
          fontWeight: 600,
          backdropFilter: "blur(4px)",
          boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
          pointerEvents: "none",
          display: "flex",
          alignItems: "center",
          gap: "6px"
        }}>
          <span style={{width: 8, height: 8, borderRadius: "50%", background: "var(--accent-cyan, #06b6d4)", display: "inline-block"}}></span>
          Operational Area Base Map · 0 active incident markers
        </div>
      )}
      <MapContainer
        center={[26.184, 91.742]}
        zoom={13}
        style={{ height: "100%", width: "100%", minHeight: "450px", zIndex: 1 }}
      >
        <MapBounds features={features} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {features.map((feature) => {
          if (feature.geometry.type !== "Point") return null;
          const coords = feature.geometry.coordinates as [number, number];
          const lat = coords[1];
          const lng = coords[0];

          const title = String(feature.properties.title ?? feature.properties.name ?? feature.properties.report_type ?? "Unnamed feature");
          const kind = String(feature.properties.feature_kind ?? "Feature");
          const state = String(feature.properties.verification_state ?? feature.properties.status ?? feature.properties.assessment_state ?? "unassessed");
          const isGap = !!feature.properties.information_gap || state.toLowerCase() === "silent";
          const routeFeas = String(feature.properties.route_feasibility ?? "");
          const need = feature.properties.need ? String(feature.properties.need) : null;
          const confidence = feature.properties.confidence ? String(feature.properties.confidence) : null;
          const feasibility = feature.properties.feasibility ? String(feature.properties.feasibility) : null;

          return (
            <Marker key={feature.id} position={[lat, lng]} icon={getMarkerIcon(state, kind, isGap, routeFeas)}>
              <Popup>
                <div style={{fontFamily: "Inter, sans-serif", minWidth: 200}}>
                  <strong style={{color: "#0f172a", display: "block", fontSize: "0.9rem", marginBottom: "4px"}}>{title}</strong>
                  <div style={{fontSize: "0.75rem", color: "#64748b", marginBottom: "6px"}}>
                    {kind} · <span style={{textTransform: "uppercase", fontWeight: 600}}>{state}</span>
                  </div>

                  {isGap && (
                    <div style={{background: "rgba(139, 92, 246, 0.15)", border: "1px solid #8b5cf6", borderRadius: "4px", padding: "6px", marginBottom: "6px", fontSize: "0.7rem", color: "#6d28d9", fontWeight: 600}}>
                      ⚠️ INFORMATION GAP — VERIFICATION REQUIRED
                      <div style={{fontWeight: 400, fontSize: "0.65rem", marginTop: "2px", color: "#475569"}}>Zero reports received in 6h. Silence is operational uncertainty, not safety.</div>
                    </div>
                  )}

                  {routeFeas && (
                    <div style={{fontSize: "0.75rem", marginBottom: "4px", color: routeFeas === "blocked" ? "#ef4444" : "#10b981", fontWeight: 600}}>
                      Route Status: {routeFeas.toUpperCase()}
                    </div>
                  )}

                  {need && (
                    <div style={{display: "flex", gap: "4px", flexWrap: "wrap", margin: "6px 0", fontSize: "0.65rem"}}>
                      <span style={{background: "#fee2e2", color: "#b91c1c", padding: "2px 5px", borderRadius: "3px", fontWeight: 700}}>NEED: {need.toUpperCase()}</span>
                      {confidence && <span style={{background: "#e0e7ff", color: "#3730a3", padding: "2px 5px", borderRadius: "3px", fontWeight: 700}}>CONFIDENCE: {confidence.toUpperCase()}</span>}
                      {feasibility && <span style={{background: "#dcfce7", color: "#15803d", padding: "2px 5px", borderRadius: "3px", fontWeight: 700}}>FEASIBILITY: {feasibility.toUpperCase()}</span>}
                    </div>
                  )}

                  {!!feature.properties.synthetic && (
                    <div style={{marginTop: "6px", fontSize: "0.65rem", color: "#d97706", fontWeight: 700, textTransform: "uppercase"}}>
                      ✦ Synthetic Tabletop Data
                    </div>
                  )}

                  {!!feature.properties.source && (
                    <div style={{marginTop: "4px", fontSize: "0.7rem", color: "#64748b"}}>Source: {String(feature.properties.source)}</div>
                  )}
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
    </div>
  );
}
