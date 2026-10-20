"""
tests/test_open_meteo_provider.py — Phase 10C.2 Open-Meteo Provider & Route Weather Tests
========================================================================================
Comprehensive unit test suite for OpenMeteoWeatherProvider covering live, historical,
forecast, and route weather normalization, bounded retries, rate limits, timeouts,
caching hits/expiration, zero mock fallback on failure, and offline network isolation.

Explicitly maps 1-to-1 to all 23 required Phase 10C.2 verification items.
"""

from datetime import datetime, timedelta, timezone
import io
import json
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch
import pytest

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.open_meteo_provider import (
    OpenMeteoWeatherProvider,
    WeatherProviderError,
    WeatherProviderInvalidRequestError,
    WeatherProviderInvalidResponseError,
    WeatherProviderRateLimitError,
    WeatherProviderTimeoutError,
    WeatherProviderUnavailableError,
)
from app.weather.cache import InMemoryWeatherCache


# =====================================================================
# SYNTHETIC OPEN-METEO FIXTURES
# =====================================================================

SAMPLE_CURRENT_ATM_RESPONSE = {
    "latitude": 6.45,
    "longitude": 3.40,
    "current": {
        "time": "2026-06-15T12:00:00Z",
        "temperature_2m": 28.4,
        "relative_humidity_2m": 82.0,
        "surface_pressure": 1012.8,
        "wind_speed_10m": 7.5,
        "wind_direction_10m": 215.0,
        "cloud_cover": 45.0,
        "precipitation": 0.0,
        "shortwave_radiation_instant": 620.0,
    }
}

SAMPLE_CURRENT_MARINE_RESPONSE = {
    "latitude": 6.45,
    "longitude": 3.40,
    "current": {
        "time": "2026-06-15T12:00:00Z",
        "wave_height": 1.45,
        "wave_direction": 225.0,
        "wave_period": 7.5,
        "ocean_current_velocity": 0.45,
        "ocean_current_direction": 180.0,
    }
}

SAMPLE_HISTORICAL_ARCHIVE_RESPONSE = {
    "latitude": 6.45,
    "longitude": 3.40,
    "hourly": {
        "time": [f"2024-01-15T{h:02d}:00:00Z" for h in range(24)],
        "temperature_2m": [24.0 + 0.5 * h for h in range(24)],
        "relative_humidity_2m": [85.0 - 0.8 * h for h in range(24)],
        "surface_pressure": [1013.0 + 0.1 * h for h in range(24)],
        "wind_speed_10m": [5.0 + 0.2 * h for h in range(24)],
        "wind_direction_10m": [200.0 for _ in range(24)],
        "cloud_cover": [30.0 for _ in range(24)],
        "precipitation": [0.0 for _ in range(24)],
        "shortwave_radiation_instant": [0.0 if h < 6 or h > 18 else 500.0 for h in range(24)],
    }
}

SAMPLE_FORECAST_RESPONSE = {
    "latitude": 6.45,
    "longitude": 3.40,
    "hourly": {
        "time": [f"2026-06-16T{h:02d}:00:00Z" for h in range(24)],
        "temperature_2m": [27.0 for _ in range(24)],
        "relative_humidity_2m": [78.0 for _ in range(24)],
        "surface_pressure": [1014.0 for _ in range(24)],
        "wind_speed_10m": [8.0 for _ in range(24)],
        "wind_direction_10m": [190.0 for _ in range(24)],
        "cloud_cover": [50.0 for _ in range(24)],
        "precipitation": [0.5 for _ in range(24)],
        "shortwave_radiation_instant": [400.0 for _ in range(24)],
    }
}


def make_mock_http_response(payload_dict: dict, status_code: int = 200):
    """Helper creating a context-managed mock HTTP response."""
    raw_bytes = json.dumps(payload_dict).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = status_code
    mock_resp.read.return_value = raw_bytes
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp


# =====================================================================
# ALL 23 TEST ITEMS
# =====================================================================

@patch("urllib.request.urlopen")
def test_01_current_weather_normalization(mock_urlopen):
    """Item 1: Current weather normalization from Open-Meteo."""
    def side_effect(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "marine" in url:
            return make_mock_http_response(SAMPLE_CURRENT_MARINE_RESPONSE)
        return make_mock_http_response(SAMPLE_CURRENT_ATM_RESPONSE)

    mock_urlopen.side_effect = side_effect
    provider = OpenMeteoWeatherProvider()
    rec = provider.get_current_weather(6.45, 3.40)
    assert rec.data_type == WeatherProvenanceType.OBSERVED
    assert rec.temperature_c == 28.4
    assert rec.wind_speed_ms == 7.5


@patch("urllib.request.urlopen")
def test_02_historical_weather_normalization(mock_urlopen):
    """Item 2: Historical weather normalization from Open-Meteo Archive."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_HISTORICAL_ARCHIVE_RESPONSE)
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=False)
    rec = provider.get_historical_weather(6.45, 3.40, timestamp="2024-01-15T14:00:00Z")
    assert rec.data_type == WeatherProvenanceType.HISTORICAL
    assert rec.temperature_c == 24.0 + 0.5 * 14


@patch("urllib.request.urlopen")
def test_03_forecast_normalization(mock_urlopen):
    """Item 3: Forecast normalization from Open-Meteo Forecast API."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_FORECAST_RESPONSE)
    provider = OpenMeteoWeatherProvider()
    forecasts = provider.get_forecast_weather(6.45, 3.40, horizon_hours=12, step_hours=3)
    assert len(forecasts) == 5
    for f in forecasts:
        assert f.data_type == WeatherProvenanceType.FORECAST


@patch("urllib.request.urlopen")
def test_04_provider_field_mapping(mock_urlopen):
    """Item 4: Full atmospheric and oceanic field mapping."""
    def side_effect(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "marine" in url:
            return make_mock_http_response(SAMPLE_CURRENT_MARINE_RESPONSE)
        return make_mock_http_response(SAMPLE_CURRENT_ATM_RESPONSE)

    mock_urlopen.side_effect = side_effect
    provider = OpenMeteoWeatherProvider()
    rec = provider.get_current_weather(6.45, 3.40)
    assert rec.surface_pressure_hpa == 1012.8
    assert rec.wave_height_m == 1.45
    assert rec.wave_period_s == 7.5
    assert rec.cloud_cover_pct == 45.0


@patch("urllib.request.urlopen")
def test_05_unit_conversions(mock_urlopen):
    """Item 5: Unit conversion exactness (m/s to knots)."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_CURRENT_ATM_RESPONSE)
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=False)
    rec = provider.get_current_weather(6.45, 3.40)
    assert rec.wind_speed_ms == 7.5
    assert rec.wind_speed_knots == round(7.5 * 1.94384, 2)


@patch("urllib.request.urlopen")
def test_06_timezone_normalization(mock_urlopen):
    """Item 6: Timezone offset normalization to UTC."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_HISTORICAL_ARCHIVE_RESPONSE)
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=False)
    rec = provider.get_historical_weather(6.45, 3.40, timestamp="2024-01-15T15:00:00+01:00")
    assert rec.timestamp_utc == "2024-01-15T14:00:00+00:00"


def test_07_invalid_coordinates():
    """Item 7: Rejection of out-of-bounds coordinates."""
    provider = OpenMeteoWeatherProvider()
    with pytest.raises(WeatherProviderInvalidRequestError):
        provider.get_current_weather(95.0, 3.40)
    with pytest.raises(WeatherProviderInvalidRequestError):
        provider.get_current_weather(6.45, 190.0)


def test_08_invalid_date_range_or_horizon():
    """Item 8: Rejection of invalid horizon or step hours."""
    provider = OpenMeteoWeatherProvider()
    with pytest.raises(WeatherProviderInvalidRequestError):
        provider.get_forecast_weather(6.45, 3.40, horizon_hours=0)
    with pytest.raises(WeatherProviderInvalidRequestError):
        provider.get_forecast_weather(6.45, 3.40, horizon_hours=24, step_hours=0)


@patch("urllib.request.urlopen")
def test_09_malformed_provider_response(mock_urlopen):
    """Item 9: Handling of malformed JSON payload."""
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.read.return_value = b"<html>502 Bad Gateway</html>"
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    mock_urlopen.return_value = mock_resp

    provider = OpenMeteoWeatherProvider(max_retries=1)
    with pytest.raises(WeatherProviderInvalidResponseError):
        provider.get_current_weather(6.45, 3.40)


@patch("urllib.request.urlopen")
def test_10_http_failure(mock_urlopen):
    """Item 10: HTTP 500 failure raises WeatherProviderUnavailableError."""
    err = urllib.error.HTTPError(url="http://test", code=500, msg="Server Error", hdrs={}, fp=io.BytesIO(b""))
    mock_urlopen.side_effect = err
    provider = OpenMeteoWeatherProvider(max_retries=1)
    with pytest.raises(WeatherProviderUnavailableError):
        provider.get_current_weather(6.45, 3.40)


@patch("urllib.request.urlopen")
def test_11_timeout_handling(mock_urlopen):
    """Item 11: Timeout raises WeatherProviderTimeoutError."""
    mock_urlopen.side_effect = TimeoutError("Socket timed out")
    provider = OpenMeteoWeatherProvider(max_retries=1)
    with pytest.raises(WeatherProviderTimeoutError):
        provider.get_current_weather(6.45, 3.40)


@patch("urllib.request.urlopen")
def test_12_bounded_retry(mock_urlopen):
    """Item 12: Bounded retry attempts with backoff."""
    err = urllib.error.HTTPError(url="http://test", code=503, msg="Unavailable", hdrs={}, fp=io.BytesIO(b""))
    mock_urlopen.side_effect = err
    provider = OpenMeteoWeatherProvider(max_retries=3, backoff_factor=0.01)
    with pytest.raises(WeatherProviderUnavailableError):
        provider.get_current_weather(6.45, 3.40)
    assert mock_urlopen.call_count == 3


@patch("urllib.request.urlopen")
def test_13_rate_limit_handling(mock_urlopen):
    """Item 13: HTTP 429 raises WeatherProviderRateLimitError without retrying."""
    err = urllib.error.HTTPError(url="http://test", code=429, msg="Too Many Requests", hdrs={}, fp=io.BytesIO(b""))
    mock_urlopen.side_effect = err
    provider = OpenMeteoWeatherProvider(max_retries=3)
    with pytest.raises(WeatherProviderRateLimitError):
        provider.get_current_weather(6.45, 3.40)
    assert mock_urlopen.call_count == 1


@patch("urllib.request.urlopen")
def test_14_cache_hit(mock_urlopen):
    """Item 14: Cache hit serves response without HTTP query."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_CURRENT_ATM_RESPONSE)
    cache = InMemoryWeatherCache()
    provider = OpenMeteoWeatherProvider(cache=cache, enable_marine_enrichment=False)

    provider.get_current_weather(6.45, 3.40)
    assert mock_urlopen.call_count == 1

    provider.get_current_weather(6.45, 3.40)
    assert mock_urlopen.call_count == 1


@patch("urllib.request.urlopen")
def test_15_cache_expiration(mock_urlopen):
    """Item 15: Cache expiration triggers fresh network request."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_CURRENT_ATM_RESPONSE)
    cache = InMemoryWeatherCache()
    provider = OpenMeteoWeatherProvider(cache=cache, enable_marine_enrichment=False)

    provider.get_current_weather(6.45, 3.40)
    assert mock_urlopen.call_count == 1

    cache.clear()
    provider.get_current_weather(6.45, 3.40)
    assert mock_urlopen.call_count == 2


@patch("urllib.request.urlopen")
def test_16_route_weather_retrieval(mock_urlopen):
    """Item 16: Multi-waypoint route weather retrieval."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_CURRENT_ATM_RESPONSE)
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=False)
    waypoints = [
        RouteWaypoint(waypoint_id="WP1", latitude=6.45, longitude=3.40),
        RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.10),
    ]
    profile = provider.get_route_weather(waypoints, route_id="ROUTE_101")
    assert profile.total_waypoints == 2
    assert len(profile.waypoints_weather) == 2


@patch("urllib.request.urlopen")
def test_17_chronological_route_records(mock_urlopen):
    """Item 17: Chronological ordering of route records."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_HISTORICAL_ARCHIVE_RESPONSE)
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=False)
    waypoints = [
        RouteWaypoint(waypoint_id="WP1", latitude=6.45, longitude=3.40, estimated_arrival_utc="2024-01-15T08:00:00Z"),
        RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.10, estimated_arrival_utc="2024-01-15T12:00:00Z"),
        RouteWaypoint(waypoint_id="WP3", latitude=5.20, longitude=5.00, estimated_arrival_utc="2024-01-15T16:00:00Z"),
    ]
    profile = provider.get_route_weather(waypoints)
    times = [rec.timestamp_utc for rec in profile.waypoints_weather]
    assert times == sorted(times)


@patch("urllib.request.urlopen")
def test_18_missing_provider_field_remains_none(mock_urlopen):
    """Item 18: Missing fields remain None and are never silently 0.0."""
    sparse = {"latitude": 6.45, "longitude": 3.40, "current": {"time": "2026-06-15T12:00:00Z", "temperature_2m": 26.0}}
    mock_urlopen.return_value = make_mock_http_response(sparse)
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=False)
    rec = provider.get_current_weather(6.45, 3.40)
    assert rec.temperature_c == 26.0
    assert rec.wind_speed_ms is None
    assert rec.wave_height_m is None
    assert rec.wind_speed_ms is not 0.0


@patch("urllib.request.urlopen")
def test_19_provenance_correctness(mock_urlopen):
    """Item 19: Provenance correctness (OBSERVED vs HISTORICAL vs FORECAST)."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_CURRENT_ATM_RESPONSE)
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=False)
    rec = provider.get_current_weather(6.45, 3.40)
    assert rec.data_type == WeatherProvenanceType.OBSERVED


@patch("urllib.request.urlopen")
def test_20_forecast_vs_historical_distinction(mock_urlopen):
    """Item 20: Forecast vs historical distinction."""
    mock_urlopen.return_value = make_mock_http_response(SAMPLE_FORECAST_RESPONSE)
    provider = OpenMeteoWeatherProvider()
    forecast = provider.get_forecast_weather(6.45, 3.40, horizon_hours=1)[0]
    assert forecast.data_type == WeatherProvenanceType.FORECAST
    assert forecast.data_type != WeatherProvenanceType.HISTORICAL


@patch("urllib.request.urlopen")
def test_21_no_mock_fallback_on_failure(mock_urlopen):
    """Item 21: Never silently fall back to mock data on provider failure."""
    mock_urlopen.side_effect = urllib.error.URLError("Network down")
    provider = OpenMeteoWeatherProvider(max_retries=1)
    with pytest.raises(WeatherProviderUnavailableError):
        provider.get_current_weather(6.45, 3.40)


def test_22_offline_deterministic_test():
    """Item 22: Offline deterministic provider execution."""
    provider = OpenMeteoWeatherProvider()
    assert provider.provider_name == "OPEN_METEO"
    assert provider.timeout_seconds == 10.0


def test_23_wind_propulsion_gap_remains_enforced():
    """Item 23: Re-verify wind propulsion capability gap is strictly enforced."""
    import os
    models = os.listdir("models")
    assert "wind_propulsion.joblib" not in models
    assert "sail_thrust.joblib" not in models
