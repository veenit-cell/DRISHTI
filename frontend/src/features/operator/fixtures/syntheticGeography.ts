import type { MapFeature } from "../api";

export const syntheticGeography: MapFeature[] = [
  {
    id: "syn_feat_1",
    geometry: { type: "Point", coordinates: [91.750, 26.190] }, // Longitude, Latitude (Guwahati/Brahmaputra)
    properties: {
      title: "Water Purification Unit",
      feature_kind: "Resource",
      status: "assigned",
      verification_state: "confirmed",
      synthetic: true,
      timestamp: new Date().toISOString(),
      source: "Command Fixture"
    }
  },
  {
    id: "syn_feat_2",
    geometry: { type: "Point", coordinates: [91.730, 26.180] },
    properties: {
      title: "North Sector Medical Need",
      feature_kind: "Need",
      status: "unmet",
      verification_state: "confirmed",
      synthetic: true,
      timestamp: new Date().toISOString(),
      source: "Field Report 8A"
    }
  },
  {
    id: "syn_feat_3",
    geometry: { type: "Point", coordinates: [91.740, 26.175] },
    properties: {
      title: "Evacuation Request",
      feature_kind: "Need",
      status: "unmet",
      verification_state: "probable",
      synthetic: true,
      timestamp: new Date().toISOString(),
      source: "Drone Analytics"
    }
  },
  {
    id: "syn_feat_4",
    geometry: { type: "Point", coordinates: [91.765, 26.185] },
    properties: {
      title: "NH-27 Corridor Blocked",
      feature_kind: "Route",
      status: "blocked",
      verification_state: "confirmed",
      synthetic: true,
      timestamp: new Date().toISOString(),
      source: "Satellite Uplink"
    }
  },
  {
    id: "syn_feat_5",
    geometry: { type: "Point", coordinates: [91.720, 26.195] },
    properties: {
      title: "West Bank Sector",
      feature_kind: "Sector",
      status: "silent",
      verification_state: "no-information",
      synthetic: true,
      timestamp: new Date().toISOString(),
      source: "System"
    }
  },
  {
    id: "syn_feat_6",
    geometry: { type: "Point", coordinates: [91.780, 26.170] },
    properties: {
      title: "South East District",
      feature_kind: "Area",
      status: "communications-dark",
      verification_state: "unassessed",
      synthetic: true,
      timestamp: new Date().toISOString(),
      source: "Network Monitor"
    }
  }
];
