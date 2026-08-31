from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.context import RequestContext
from app.mutual_aid import ForecastRequest, PostgreSQLMutualAidStore
from app.persistence import database_ready

pytestmark = pytest.mark.skipif(
    not database_ready(Settings().database_url), reason="PostgreSQL is not available"
)


def test_postgres_mutual_aid_forecast_round_trip():
    now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    context = RequestContext(
        "operator", "operator", "org_pg_slice4", "evt_pg_slice4", frozenset(), "test"
    )
    store = PostgreSQLMutualAidStore(Settings().database_url)
    result = store.create_forecast(
        context,
        ForecastRequest(
            resource_type="potable_water",
            current_quantity=100,
            consumption_per_hour=12,
            reserve_floor=40,
            forecast_window_hours=8,
            lead_time_hours=4,
            location="North Sector",
        ),
        now,
    )
    assert result["forecast_id"]
    assert store.list_forecasts(context)[0]["resource_type"] == "potable_water"
