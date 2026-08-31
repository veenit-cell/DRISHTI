"""Modular external integration adapters for RescueOps/DRISHTI.

Preserves clean boundaries for GIS, satellite observation rasters, weather alerts,
and government state/district emergency operation feeds without redesigning the system.
"""

from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Any, Protocol


class GISFeatureAdapter(Protocol):
    """Adapter interface for GIS systems (e.g. ArcGIS, QGIS, GeoServer, OpenStreetMap)."""

    @abstractmethod
    def fetch_features(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        layer: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch GeoJSON features within the bounding box."""
        ...

    @abstractmethod
    def export_features(self, features: list[dict[str, Any]]) -> dict[str, Any]:
        """Export standardized feature collection to external GIS layer."""
        ...


class SatelliteObservationAdapter(Protocol):
    """Adapter interface for satellite imagery & earth observation feeds (e.g. ISRO, Sentinel, NASA)."""

    @abstractmethod
    def query_pass(
        self,
        sensor: str,
        area_of_interest: dict[str, Any],
        since: datetime,
    ) -> list[dict[str, Any]]:
        """Query available satellite passes and inundation/extent maps."""
        ...

    @abstractmethod
    def extract_flood_extent(
        self, observation_id: str
    ) -> dict[str, Any]:
        """Extract vector flood polygons and severed route corridors."""
        ...


class WeatherAlertAdapter(Protocol):
    """Adapter interface for meteorological alerts and forecasts (e.g. IMD, CWC, NOAA)."""

    @abstractmethod
    def get_active_alerts(
        self, district_id: str
    ) -> list[dict[str, Any]]:
        """Fetch active meteorological warnings (rainfall intensity, river discharge, cyclone)."""
        ...

    @abstractmethod
    def get_river_surge_forecast(
        self, river_basin: str, horizon_hours: int = 24
    ) -> dict[str, Any]:
        """Fetch projected water levels against danger and evacuation marks."""
        ...


class GovernmentFeedAdapter(Protocol):
    """Adapter interface for state/national disaster management authorities (e.g. NDMA, SDMA, DEOC)."""

    @abstractmethod
    def pull_official_bulletin(
        self, agency_code: str, incident_code: str
    ) -> list[dict[str, Any]]:
        """Pull verified administrative incident bulletins and state directives."""
        ...

    @abstractmethod
    def push_sitrep(
        self, sitrep_payload: dict[str, Any], destination_agency: str
    ) -> dict[str, Any]:
        """Transmit verified shift SITREP package to authoritative command feeds."""
        ...
