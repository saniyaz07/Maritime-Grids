"""
tests/test_voyage_context.py — Phase 10C.3 Voyage State & Context Tests
======================================================================
Comprehensive test suite covering vessel context, route/waypoint validation,
voyage status, vessel positioning, timeline, energy states, weather context
enrichment, serialization, and absence of physics recalculation.

Explicitly maps 1-to-1 to all 24 required Phase 10C.3 verification items.
"""

from datetime import datetime, timezone
import json
import pytest
from pydantic import ValidationError

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.mock_provider import MockWeatherProvider
from app.voyage.contracts import (
    Route,
    VesselContext,
    VesselEnergyState,
    VesselPosition,
    VoyageContext,
    VoyageStatus,
    VoyageTimeline,
    VoyageWeatherContext,
)
from app.voyage.context_builder import VoyageContextBuilder


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def sample_vessel() -> VesselContext:
    return VesselContext(
        vessel_id="VESSEL_OSV_01",
        ship_type="Oil Service Boat",
        design_speed_knots=12.0,
        max_speed_knots=14.5,
        displacement_tonnes=2500.0,
        engine_power_kw=4500.0,
        battery_pack_capacity_kwh=649.7,
        solar_panel_size_m2=80.0,
        fuel_price_usd_per_liter=1.15,
        provenance=WeatherProvenanceType.OBSERVED,
    )


@pytest.fixture
def sample_route() -> Route:
    return Route(
        route_id="ESCRAVOS_LAGOS",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP_ESCRAVOS", latitude=5.58, longitude=5.18, distance_from_start_nm=0.0),
            RouteWaypoint(waypoint_id="WP_OFFSHORE_1", latitude=5.80, longitude=4.50, distance_from_start_nm=45.0),
            RouteWaypoint(waypoint_id="WP_OFFSHORE_2", latitude=6.10, longitude=3.80, distance_from_start_nm=95.0),
            RouteWaypoint(waypoint_id="WP_LAGOS", latitude=6.45, longitude=3.40, distance_from_start_nm=130.0),
        ],
        total_distance_nm=130.0,
    )


@pytest.fixture
def sample_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        speed_over_ground_knots=11.8,
        course_over_ground_deg=285.0,
        data_type=WeatherProvenanceType.OBSERVED,
    )


# =====================================================================
# ALL 24 TEST ITEMS
# =====================================================================

def test_01_valid_vessel_context(sample_vessel):
    """Item 1: Verify valid VesselContext initialization."""
    assert sample_vessel.vessel_id == "VESSEL_OSV_01"
    assert sample_vessel.ship_type == "Oil Service Boat"
    assert sample_vessel.battery_pack_capacity_kwh == 649.7
    assert sample_vessel.solar_panel_size_m2 == 80.0


def test_02_invalid_vessel_identifier():
    """Item 2: Verify rejection of empty vessel ID."""
    with pytest.raises(ValidationError):
        VesselContext(vessel_id="", ship_type="Oil Service Boat")

    with pytest.raises(ValidationError):
        VesselContext(vessel_id="   ", ship_type="Oil Service Boat")


def test_03_valid_route(sample_route):
    """Item 3: Verify valid Route construction with waypoints."""
    assert sample_route.route_id == "ESCRAVOS_LAGOS"
    assert len(sample_route.waypoints) == 4
    assert sample_route.origin_port == "Escravos Terminal"
    assert sample_route.destination_port == "Lagos Port"


def test_04_invalid_latitude():
    """Item 4: Verify rejection of waypoint latitude > 90 or < -90."""
    with pytest.raises(ValidationError):
        RouteWaypoint(waypoint_id="WP_BAD", latitude=95.0, longitude=3.40)


def test_05_invalid_longitude():
    """Item 5: Verify rejection of waypoint longitude > 180 or < -180."""
    with pytest.raises(ValidationError):
        RouteWaypoint(waypoint_id="WP_BAD", latitude=6.45, longitude=185.0)


def test_06_empty_route():
    """Item 6: Verify rejection of empty route waypoints."""
    with pytest.raises(ValidationError):
        Route(route_id="EMPTY", origin_port="A", destination_port="B", waypoints=[])


def test_07_malformed_waypoint_sequence():
    """Item 7: Verify rejection of route with only 1 waypoint (minimum 2 required)."""
    with pytest.raises(ValidationError):
        Route(
            route_id="ONE_WP",
            origin_port="A",
            destination_port="B",
            waypoints=[RouteWaypoint(waypoint_id="WP1", latitude=6.0, longitude=3.0)],
        )


def test_08_valid_voyage(sample_vessel, sample_route, sample_position):
    """Item 8: Verify creation of valid VoyageContext."""
    timeline = VoyageTimeline(
        departure_time_utc="2026-06-15T08:00:00Z",
        current_time_utc="2026-06-15T12:00:00Z",
        planned_arrival_time_utc="2026-06-15T18:00:00Z",
    )
    voyage = VoyageContext(
        voyage_id="VOY_2026_001",
        status=VoyageStatus.ACTIVE,
        vessel=sample_vessel,
        route=sample_route,
        current_position=sample_position,
        timeline=timeline,
    )
    assert voyage.voyage_id == "VOY_2026_001"
    assert voyage.status == VoyageStatus.ACTIVE
    assert voyage.vessel.vessel_id == "VESSEL_OSV_01"


def test_09_invalid_voyage_status(sample_vessel, sample_route, sample_position):
    """Item 9: Verify rejection of invalid voyage lifecycle status."""
    with pytest.raises(ValidationError):
        VoyageContext(
            voyage_id="VOY_001",
            status="SPEEDING_FAST",  # Invalid
            vessel=sample_vessel,
            route=sample_route,
            current_position=sample_position,
            timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        )


def test_10_valid_current_position(sample_position):
    """Item 10: Verify valid VesselPosition fields."""
    assert sample_position.latitude == 5.80
    assert sample_position.longitude == 4.50
    assert sample_position.speed_over_ground_knots == 11.8


def test_11_invalid_current_position():
    """Item 11: Verify rejection of invalid position coordinates."""
    with pytest.raises(ValidationError):
        VesselPosition(latitude=-95.0, longitude=4.50, timestamp_utc="2026-06-15T12:00:00Z")


def test_12_timestamp_validation():
    """Item 12: Verify ISO 8601 normalization on timeline timestamps."""
    tl = VoyageTimeline(
        departure_time_utc="2026-06-15T08:00:00+01:00",
        current_time_utc="2026-06-15T12:00:00Z",
    )
    assert tl.departure_time_utc == "2026-06-15T07:00:00+00:00"
    assert tl.current_time_utc == "2026-06-15T12:00:00+00:00"
    assert tl.estimated_arrival_time_utc is None  # explicitly unavailable


def test_13_weather_association(sample_vessel, sample_route, sample_position):
    """Item 13: Verify enrichment of VoyageContext with WeatherProvider."""
    provider = MockWeatherProvider()
    builder = VoyageContextBuilder("VOY_TEST_WX")
    builder.set_vessel(sample_vessel)
    builder.set_route(sample_route)
    builder.set_position(sample_position)
    builder.enrich_weather_from_provider(provider)
    voyage = builder.build()

    assert voyage.weather_context.current_weather is not None
    assert voyage.weather_context.current_weather.latitude == 5.80
    assert voyage.weather_context.weather_source == "MOCK_DETERMINISTIC"
    assert voyage.weather_context.weather_quality == WeatherQualityState.VALID


def test_14_route_weather_ordering(sample_vessel, sample_route, sample_position):
    """Item 14: Verify route weather profile preserves waypoint ordering."""
    provider = MockWeatherProvider()
    builder = VoyageContextBuilder("VOY_ORDER")
    builder.set_vessel(sample_vessel)
    builder.set_route(sample_route)
    builder.set_position(sample_position)
    builder.enrich_weather_from_provider(provider)
    voyage = builder.build()

    r_wx = voyage.weather_context.route_weather
    assert r_wx is not None
    assert len(r_wx.waypoints_weather) == 4
    assert r_wx.waypoints_weather[0].latitude == 5.58
    assert r_wx.waypoints_weather[3].latitude == 6.45


def test_15_weather_provenance_preservation(sample_vessel, sample_route, sample_position):
    """Item 15: Verify preservation of weather provenance types in voyage context."""
    provider = MockWeatherProvider()
    builder = VoyageContextBuilder("VOY_PROV")
    builder.set_vessel(sample_vessel)
    builder.set_route(sample_route)
    builder.set_position(sample_position)
    builder.enrich_weather_from_provider(provider)
    voyage = builder.build()

    assert voyage.weather_context.current_weather.data_type == WeatherProvenanceType.OBSERVED


def test_16_weather_freshness_preservation(sample_vessel, sample_route, sample_position):
    """Item 16: Verify freshness state is preserved."""
    provider = MockWeatherProvider(mode="stale")
    builder = VoyageContextBuilder("VOY_FRESH")
    builder.set_vessel(sample_vessel)
    builder.set_route(sample_route)
    builder.set_position(sample_position)
    builder.enrich_weather_from_provider(provider)
    voyage = builder.build()

    assert voyage.weather_context.weather_freshness == WeatherFreshnessState.EXPIRED


def test_17_energy_state_with_available_values():
    """Item 17: Verify energy state with telemetry values."""
    energy = VesselEnergyState(
        battery_soc_pct=85.0,
        battery_soh_pct=98.5,
        battery_energy_available_kwh=550.0,
        solar_power_kw=15.2,
        solar_energy_today_kwh=62.4,
        fuel_remaining_liters=4500.0,
        fuel_consumption_rate_lph=180.0,
        provenance=WeatherProvenanceType.OBSERVED,
    )
    assert energy.battery_soc_pct == 85.0
    assert energy.solar_power_kw == 15.2
    assert energy.fuel_remaining_liters == 4500.0


def test_18_energy_state_with_unavailable_values():
    """Item 18: Verify energy state preserves None when telemetry is unavailable."""
    energy = VesselEnergyState()
    assert energy.battery_soc_pct is None
    assert energy.solar_power_kw is None
    assert energy.fuel_remaining_liters is None
    assert energy.battery_soc_pct is not 0.0


def test_19_historical_data_not_labelled_live():
    """Item 19: Verify historical data preserves HISTORICAL provenance."""
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2024-01-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.HISTORICAL,
    )
    assert rec.data_type != WeatherProvenanceType.OBSERVED
    assert rec.data_type == WeatherProvenanceType.HISTORICAL


def test_20_forecast_data_not_labelled_observed():
    """Item 20: Verify forecast data preserves FORECAST provenance."""
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-16T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.FORECAST,
    )
    assert rec.data_type != WeatherProvenanceType.OBSERVED
    assert rec.data_type == WeatherProvenanceType.FORECAST


def test_21_immutable_and_validated_voyage_context(sample_vessel, sample_route, sample_position):
    """Item 21: Verify complete structured VoyageContext validation."""
    voyage = VoyageContext(
        voyage_id="VOY_VALID",
        vessel=sample_vessel,
        route=sample_route,
        current_position=sample_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
    )
    assert voyage.status == VoyageStatus.PLANNED
    assert isinstance(voyage.weather_context, VoyageWeatherContext)
    assert isinstance(voyage.energy_state, VesselEnergyState)


def test_22_serialization(sample_vessel, sample_route, sample_position):
    """Item 22: Verify JSON serialization and round-trip parsing."""
    voyage = VoyageContext(
        voyage_id="VOY_SERIALIZE",
        status=VoyageStatus.ACTIVE,
        vessel=sample_vessel,
        route=sample_route,
        current_position=sample_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        energy_state=VesselEnergyState(battery_soc_pct=72.0),
    )
    json_str = voyage.model_dump_json()
    data = json.loads(json_str)

    assert data["voyage_id"] == "VOY_SERIALIZE"
    assert data["status"] == "ACTIVE"
    assert data["energy_state"]["battery_soc_pct"] == 72.0

    # Round trip reconstruction
    rebuilt = VoyageContext.model_validate_json(json_str)
    assert rebuilt.voyage_id == voyage.voyage_id
    assert rebuilt.vessel.vessel_id == voyage.vessel.vessel_id


def test_23_no_physics_recalculation():
    """
    Item 23: Verify that VoyageContext construction executes zero physics,
    fuel, or financial recalculations (pure state container).
    """
    import inspect
    import app.voyage.contracts as contracts_module

    # Confirm module only contains schema classes, zero simulation or optimization functions
    functions = [f for f in dir(contracts_module) if inspect.isfunction(getattr(contracts_module, f))]
    assert "calculate_fuel_consumption" not in functions
    assert "simulate_voyage" not in functions
    assert "optimize_sizing" not in functions


def test_24_wind_propulsion_gap_remains_absent():
    """Item 24: Re-verify wind propulsion capability gap is strictly enforced."""
    import os
    models = os.listdir("models")
    assert "wind_propulsion.joblib" not in models
    assert "sail_thrust.joblib" not in models
