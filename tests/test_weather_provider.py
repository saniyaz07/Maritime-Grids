"""
tests/test_weather_provider.py — Phase 10C.1 Weather Abstraction & Contract Tests
================================================================================
Comprehensive test suite for Phase 10C.1 covering normalized contracts, geographic
validation, data provenance, freshness rules, mock provider determinism, route
weather profiling, caching TTL, and the wind propulsion physical capability gap.

Covers all 20 required Phase 10C.1 verification items.
"""

from datetime import datetime, timedelta, timezone
import pytest
from pydantic import ValidationError

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
    DriverDashboardWeatherSummary,
)
from app.weather.provider import WeatherProvider
from app.weather.mock_provider import MockWeatherProvider
from app.weather.cache import InMemoryWeatherCache, WeatherCacheEntry


# =====================================================================
# 1. CONTRACT & VALIDATION TESTS (Items 1-10, 16-18)
# =====================================================================

def test_01_valid_weather_record():
    """Item 1: Verify creation of a completely valid NormalizedWeatherRecord."""
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="OPEN_METEO_TEST",
        data_type=WeatherProvenanceType.OBSERVED,
        wind_speed_ms=8.5,
        wind_direction_deg=220.0,
        temperature_c=28.5,
        relative_humidity_pct=82.0,
        surface_pressure_hpa=1012.5,
        solar_irradiance_w_per_m2=650.0,
        daily_ghi_kwh_per_m2=5.8,
        wave_height_m=1.4,
        wave_period_s=7.2,
    )
    assert rec.latitude == 6.45
    assert rec.longitude == 3.40
    assert rec.timestamp_utc == "2026-06-15T12:00:00+00:00"
    assert rec.wind_speed_knots is not None
    assert round(rec.wind_speed_knots, 1) == 16.5
    assert rec.evaluate_quality() == WeatherQualityState.VALID


def test_02_invalid_latitude():
    """Item 2 & 16: Verify rejection of latitude outside [-90.0, 90.0]."""
    with pytest.raises(ValidationError) as exc_info:
        NormalizedWeatherRecord(
            latitude=95.0,  # Invalid
            longitude=3.40,
            timestamp_utc="2026-06-15T12:00:00Z",
            data_source="TEST",
            data_type=WeatherProvenanceType.OBSERVED,
        )
    assert "latitude" in str(exc_info.value)


def test_03_invalid_longitude():
    """Item 3 & 16: Verify rejection of longitude outside [-180.0, 180.0]."""
    with pytest.raises(ValidationError) as exc_info:
        NormalizedWeatherRecord(
            latitude=6.45,
            longitude=-185.0,  # Invalid
            timestamp_utc="2026-06-15T12:00:00Z",
            data_source="TEST",
            data_type=WeatherProvenanceType.OBSERVED,
        )
    assert "longitude" in str(exc_info.value)


def test_04_invalid_humidity():
    """Item 4: Verify rejection of relative humidity > 100% or < 0%."""
    with pytest.raises(ValidationError) as exc_info:
        NormalizedWeatherRecord(
            latitude=6.45,
            longitude=3.40,
            timestamp_utc="2026-06-15T12:00:00Z",
            data_source="TEST",
            data_type=WeatherProvenanceType.OBSERVED,
            relative_humidity_pct=105.0,  # Invalid
        )
    assert "relative_humidity_pct" in str(exc_info.value)


def test_05_negative_wind_speed():
    """Item 5: Verify rejection of negative wind speed."""
    with pytest.raises(ValidationError) as exc_info:
        NormalizedWeatherRecord(
            latitude=6.45,
            longitude=3.40,
            timestamp_utc="2026-06-15T12:00:00Z",
            data_source="TEST",
            data_type=WeatherProvenanceType.OBSERVED,
            wind_speed_ms=-3.0,  # Invalid
        )
    assert "wind_speed_ms" in str(exc_info.value)


def test_06_missing_optional_fields():
    """Item 6: Verify record functions cleanly when optional fields are omitted."""
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
    )
    assert rec.wind_speed_ms is None
    assert rec.wave_height_m is None
    assert rec.solar_irradiance_w_per_m2 is None
    assert rec.is_available("wave_height_m") is False


def test_07_explicit_unavailable_field_is_not_zero():
    """
    Item 7: CRITICAL RULE — Verify missing fields remain None (UNAVAILABLE)
    and are NOT silently replaced by 0.0.
    """
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
        wave_height_m=None,
        wind_speed_ms=None,
    )
    assert rec.wave_height_m is not 0.0
    assert rec.wave_height_m is None
    assert rec.wind_speed_ms is not 0.0
    assert rec.wind_speed_ms is None


def test_08_timestamp_normalization():
    """Item 8: Verify timestamps with Z and local offsets normalize to UTC."""
    rec_z = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
    )
    assert rec_z.timestamp_utc == "2026-06-15T12:00:00+00:00"

    rec_offset = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T14:00:00+02:00",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
    )
    assert rec_offset.timestamp_utc == "2026-06-15T12:00:00+00:00"


def test_09_stale_and_freshness_calculation():
    """Item 9 & 17: Verify freshness calculation correctly identifies FRESH, STALE, EXPIRED."""
    ref_time = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Fresh (30 minutes old)
    rec_fresh = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T11:30:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
    )
    freshness_1 = rec_fresh.evaluate_freshness(current_time_utc=ref_time)
    assert freshness_1 == WeatherFreshnessState.FRESH
    assert rec_fresh.freshness_age_seconds == 1800.0

    # 2. Stale (5 hours old)
    rec_stale = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T07:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
    )
    freshness_2 = rec_stale.evaluate_freshness(current_time_utc=ref_time)
    assert freshness_2 == WeatherFreshnessState.STALE
    assert rec_stale.freshness_age_seconds == 18000.0

    # 3. Expired (48 hours old)
    rec_exp = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-13T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.HISTORICAL,
    )
    freshness_3 = rec_exp.evaluate_freshness(current_time_utc=ref_time)
    assert freshness_3 == WeatherFreshnessState.EXPIRED
    assert rec_exp.freshness_age_seconds == 172800.0


def test_10_data_quality_classification():
    """Item 10 & 18: Verify data quality states (VALID, PARTIAL, UNAVAILABLE)."""
    # 1. UNAVAILABLE (no variables)
    rec_unavail = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.UNAVAILABLE,
    )
    assert rec_unavail.evaluate_quality() == WeatherQualityState.UNAVAILABLE

    # 2. PARTIAL (only 2 variables)
    rec_part = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
        temperature_c=25.0,
        relative_humidity_pct=70.0,
    )
    assert rec_part.evaluate_quality() == WeatherQualityState.PARTIAL

    # 3. VALID (full set)
    rec_valid = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
        temperature_c=25.0,
        relative_humidity_pct=70.0,
        wind_speed_ms=6.0,
        surface_pressure_hpa=1013.0,
        solar_irradiance_w_per_m2=400.0,
        wave_height_m=1.2,
    )
    assert rec_valid.evaluate_quality() == WeatherQualityState.VALID


# =====================================================================
# 2. MOCK PROVIDER TESTS (Items 11-15)
# =====================================================================

def test_11_deterministic_mock_provider():
    """Item 11: Verify MockWeatherProvider produces 100% deterministic output."""
    provider1 = MockWeatherProvider()
    provider2 = MockWeatherProvider()

    rec1 = provider1.get_current_weather(6.45, 3.40)
    rec2 = provider2.get_current_weather(6.45, 3.40)

    assert rec1.wind_speed_ms == rec2.wind_speed_ms
    assert rec1.temperature_c == rec2.temperature_c
    assert rec1.wave_height_m == rec2.wave_height_m
    assert rec1.solar_irradiance_w_per_m2 == rec2.solar_irradiance_w_per_m2


def test_12_current_weather_retrieval():
    """Item 12: Verify get_current_weather on MockWeatherProvider."""
    provider = MockWeatherProvider()
    rec = provider.get_current_weather(6.0, 4.0)

    assert rec.data_type == WeatherProvenanceType.OBSERVED
    assert rec.latitude == 6.0
    assert rec.longitude == 4.0
    assert rec.wind_speed_ms is not None
    assert rec.wave_height_m is not None
    assert rec.freshness == WeatherFreshnessState.FRESH


def test_13_historical_weather_retrieval():
    """Item 13: Verify get_historical_weather on MockWeatherProvider."""
    provider = MockWeatherProvider()
    past_iso = "2024-01-15T08:00:00Z"
    rec = provider.get_historical_weather(6.0, 4.0, past_iso)

    assert rec.data_type == WeatherProvenanceType.HISTORICAL
    assert rec.timestamp_utc == "2024-01-15T08:00:00+00:00"
    assert rec.temperature_c is not None


def test_14_forecast_weather_retrieval():
    """Item 14: Verify get_forecast_weather produces correct sequence."""
    provider = MockWeatherProvider()
    forecasts = provider.get_forecast_weather(6.0, 4.0, horizon_hours=12, step_hours=3)

    assert len(forecasts) == 5  # 0, 3, 6, 9, 12 hours
    for f in forecasts:
        assert f.data_type == WeatherProvenanceType.FORECAST
        assert f.latitude == 6.0


def test_15_provider_abstraction_and_custom_subclass():
    """Item 15: Verify WeatherProvider interface extensibility."""
    class CustomConstantWeatherProvider(WeatherProvider):
        @property
        def provider_name(self) -> str:
            return "CUSTOM_CONSTANT"

        def get_current_weather(self, latitude: float, longitude: float) -> NormalizedWeatherRecord:
            return NormalizedWeatherRecord(
                latitude=latitude,
                longitude=longitude,
                timestamp_utc="2026-06-15T12:00:00Z",
                data_source=self.provider_name,
                data_type=WeatherProvenanceType.OBSERVED,
                wind_speed_ms=10.0,
            )

        def get_historical_weather(self, latitude: float, longitude: float, timestamp) -> NormalizedWeatherRecord:
            return self.get_current_weather(latitude, longitude)

        def get_forecast_weather(self, latitude: float, longitude: float, horizon_hours=24, step_hours=1):
            return [self.get_current_weather(latitude, longitude)]

    custom = CustomConstantWeatherProvider()
    res = custom.get_current_weather(10.0, 20.0)
    assert res.data_source == "CUSTOM_CONSTANT"
    assert res.wind_speed_ms == 10.0


# =====================================================================
# 3. ADVANCED CAPABILITY & SECURITY TESTS (Items 19-20, Cache, Route)
# =====================================================================

def test_19_no_secret_configuration():
    """Item 19: Verify initialization requires zero API keys or secrets."""
    provider = MockWeatherProvider()
    assert hasattr(provider, "api_key") is False
    assert provider.provider_name == "MOCK_DETERMINISTIC"


def test_20_physical_model_gap_detection():
    """
    Item 20: CRITICAL PHYSICAL MODEL AUDIT — Verify that no wind propulsion
    or sail force model is erroneously registered as part of the core engine.
    """
    # Inspect models/ directory: exactly 13 frozen ML models exist
    # Verify no 'wind_propulsion' or 'sail_force' model exists
    import os, joblib
    models_dir = "models"
    model_files = os.listdir(models_dir)
    assert "wind_propulsion.joblib" not in model_files
    assert "sail_thrust.joblib" not in model_files
    assert "flettner_rotor.joblib" not in model_files


def test_21_route_weather_profiling():
    """Verify route waypoint weather collection."""
    provider = MockWeatherProvider()
    wps = [
        RouteWaypoint(waypoint_id="WP1", latitude=6.45, longitude=3.40, distance_from_start_nm=0.0),
        RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.10, distance_from_start_nm=55.0),
        RouteWaypoint(waypoint_id="WP3", latitude=5.20, longitude=5.00, distance_from_start_nm=120.0),
    ]
    profile = provider.get_route_weather(wps, route_id="ESCRAVOS_LAGOS")
    assert profile.total_waypoints == 3
    assert len(profile.waypoints_weather) == 3
    assert profile.overall_quality == WeatherQualityState.VALID


def test_22_weather_cache_operations():
    """Verify in-memory weather caching, key generation, and TTL expiration."""
    cache = InMemoryWeatherCache(default_ttl_seconds=300.0)
    provider = MockWeatherProvider()
    rec = provider.get_current_weather(6.45, 3.40)

    key = cache.set(rec, ttl_seconds=60.0)
    assert cache.size() == 1

    # Lookup before expiry
    hit = cache.get(key)
    assert hit is not None
    assert hit.latitude == 6.45

    # Expiry test
    future_time = datetime.now(timezone.utc) + timedelta(seconds=120)
    miss = cache.get(key, current_time=future_time)
    assert miss is None
    assert cache.size() == 0


def test_23_driver_dashboard_summary_generation():
    """Verify driver dashboard telemetry projection."""
    provider = MockWeatherProvider()
    rec = provider.get_current_weather(6.45, 3.40)
    
    summary = DriverDashboardWeatherSummary(
        location_lat=rec.latitude,
        location_lon=rec.longitude,
        weather_timestamp_utc=rec.timestamp_utc,
        data_source=rec.data_source,
        provenance_type=rec.data_type,
        freshness_state=rec.freshness,
        quality_state=rec.data_quality,
        wind_speed_knots=rec.wind_speed_knots,
        wind_direction_deg=rec.wind_direction_deg,
        temperature_c=rec.temperature_c,
        humidity_pct=rec.relative_humidity_pct,
        solar_ghi_kwh_per_m2=rec.daily_ghi_kwh_per_m2,
        wave_height_m=rec.wave_height_m,
        ocean_current_speed_knots=rec.ocean_current_speed_knots,
        high_wind_warning=(rec.wind_speed_knots or 0.0) > 25.0,
        rough_sea_warning=(rec.wave_height_m or 0.0) > 2.5,
    )
    assert summary.location_lat == 6.45
    assert summary.provenance_type == WeatherProvenanceType.OBSERVED
    assert summary.freshness_state == WeatherFreshnessState.FRESH
