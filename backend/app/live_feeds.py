import httpx
from datetime import datetime, UTC
from typing import Any, List, Dict
import asyncio
from app.evidence import ReportCreate, SourceInput, LocationInput

class RequiresAuthorizationError(Exception):
    """Raised when an adapter requires authorization that is not available."""
    pass

class NotPubliclyAvailableError(Exception):
    """Raised when a feed is not publicly accessible."""
    pass

class LiveFeedAdapter:
    """Base adapter for pulling live disaster feeds."""
    async def fetch_reports(self) -> List[ReportCreate]:
        raise NotImplementedError

class NDMAAdapter(LiveFeedAdapter):
    """Stub adapter for NDMA/SACHET."""
    async def fetch_reports(self) -> List[ReportCreate]:
        raise RequiresAuthorizationError("NDMA/SACHET feed requires authorization.")

class CWCAdapter(LiveFeedAdapter):
    """Stub adapter for CWC Flood data."""
    async def fetch_reports(self) -> List[ReportCreate]:
        raise RequiresAuthorizationError("CWC Flood data requires authorization.")

class USGSEarthquakeAdapter(LiveFeedAdapter):
    """Adapter for the public USGS Earthquake GeoJSON feed."""
    FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"

    async def fetch_reports(self) -> List[ReportCreate]:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.FEED_URL, timeout=10.0)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                # Fallback to empty if offline to gracefully degrade
                return []
        
        reports = []
        now = datetime.now(UTC)
        for feature in data.get("features", []):
            properties = feature.get("properties", {})
            geometry = feature.get("geometry", {})
            
            # Extract basic info
            mag = properties.get("mag")
            place = properties.get("place")
            time_ms = properties.get("time")
            
            if mag is None or time_ms is None or not geometry:
                continue
                
            observed_at = datetime.fromtimestamp(time_ms / 1000.0, tz=UTC)
            
            # Map severity
            severity = "minor"
            if mag >= 5.0:
                severity = "critical"
            elif mag >= 4.0:
                severity = "moderate"
                
            report = ReportCreate(
                contract_version=1,
                client_record_id=f"usgs_live_{feature.get('id', 'unknown')}",
                observed_at=observed_at,
                received_at=now,
                source=SourceInput(channel="usgs_api", source_class="authoritative_live"),
                location=LocationInput(
                    geometry=geometry,
                    uncertainty_m=5000,
                    place_text=place,
                ),
                report_type="earthquake",
                facts={
                    "magnitude": mag,
                    "severity": severity,
                    "url": properties.get("url")
                },
                privacy_class="internal"
            )
            reports.append(report)
        return reports

class LiveFeedManager:
    """Orchestrates pulling from all registered live feeds."""
    def __init__(self):
        self.adapters = [
            USGSEarthquakeAdapter(),
            NDMAAdapter(),
            CWCAdapter(),
        ]
        self.last_sync_time: datetime | None = None
        self.health_status: Dict[str, str] = {}
        
    async def sync_all(self) -> List[ReportCreate]:
        all_reports = []
        for adapter in self.adapters:
            adapter_name = adapter.__class__.__name__
            try:
                reports = await adapter.fetch_reports()
                all_reports.extend(reports)
                self.health_status[adapter_name] = "healthy"
            except RequiresAuthorizationError:
                self.health_status[adapter_name] = "NEEDS_AUTHORIZATION"
            except NotPubliclyAvailableError:
                self.health_status[adapter_name] = "NOT_PUBLICLY_AVAILABLE"
            except Exception as e:
                self.health_status[adapter_name] = "STALE_OR_UNAVAILABLE"
        
        self.last_sync_time = datetime.now(UTC)
        return all_reports
