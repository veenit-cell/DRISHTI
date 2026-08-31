import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, useMap } from "react-leaflet";
import { listMapFeatures, type MapFeature } from "../api";
import { syntheticGeography } from "../fixtures/syntheticGeography";
import L from "leaflet";

function MapBounds({ features }: { features: MapFeature[] }) {
  const map = useMap();

  useEffect(() => {
    const points = features
      .filter((f) => f.geometry.type === "Point")
      .map((f) => {
        const coords = f.geometry.coordinates as [number, number];
        return L.latLng(coords[1], coords[0]);
      });

    if (points.length > 0) {
      const bounds = L.latLngBounds(points);
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
    }
  }, [features, map]);

  return null;
}

const getMarkerIcon = (state: string, kind: string) => {
  let color = "var(--status-info)"; // blue (information)

  const s = state.toLowerCase();

  if (s === "confirmed" && kind.toLowerCase() === "need") {
    color = "var(--status-critical)"; // red
  } else if (s === "probable" || s === "blocked" || s === "stale") {
    color = "var(--status-warning)"; // amber
  } else if (s === "no-information" || s === "communications-dark" || s === "unassessed" || s === "silent") {
    color = "var(--text-muted)"; // grey
  }

  return L.divIcon({
    className: "custom-map-marker",
    html: `<div style="background-color: ${color}; width: 16px; height: 16px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10]
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

  if (features.length === 0) {
    return (
      <div className="map-container">
        <div className="empty-geography">
          <strong>NO OPERATIONAL GEOGRAPHY</strong>
          <span>Map features will appear when incident geography is available.</span>
        </div>
      </div>
    );
  }

  return (
    <div className="map-container">
      <MapContainer
        center={[26.184, 91.742]}
        zoom={13}
        style={{ height: "100%", width: "100%", zIndex: 1 }}
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

          return (
            <Marker key={feature.id} position={[lat, lng]} icon={getMarkerIcon(state, kind)}>
              <Popup>
                <div style={{fontFamily: "Inter, sans-serif"}}>
                  <strong style={{color: "var(--text-main)", display: "block", marginBottom: "4px"}}>{title}</strong>
                  <span style={{fontSize: "0.8rem", color: "var(--text-muted)"}}>
                    {kind} · <span style={{textTransform: "uppercase"}}>{state}</span>
                  </span>
                  {!!feature.properties.synthetic && (
                    <div style={{marginTop: "8px", fontSize: "0.7rem", color: "var(--status-warning)", fontWeight: 700}}>SYNTHETIC TABLETOP FIXTURE</div>
                  )}
                  {!!feature.properties.source && (
                    <div style={{marginTop: "4px", fontSize: "0.75rem", color: "var(--text-muted)"}}>Source: {String(feature.properties.source)}</div>
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
