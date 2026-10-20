"""
tests/test_decision_context.py — Phase 10C.4 Decision Context & Advisory Input Tests
====================================================================================
Comprehensive test suite covering DecisionContext assembly, readiness state
classification (READY, PARTIAL, INSUFFICIENT_DATA, STALE_DATA, INVALID_DATA),
engineering inputs, data provenance, serialization, and absence of wind propulsion.

Explicitly maps 1-to-1 to all 25 required Phase 10C.4 verification items.
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
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
    EngineeringDecisionInputs,
)
from app.decision.context_builder import DecisionContextBuilder


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def base_vessel() -> VesselContext:
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
def base_route() -> Route:
    return Route(
        route_id="ESCRAVOS_LAGOS",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1", latitude=5.58, longitude=5.18),
            RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.50),
            RouteWaypoint(waypoint_id="WP3", latitude=6.45, longitude=3.40),
        ],
        total_distance_nm=130.0,
    )


@pytest.fixture
def base_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        speed_over_ground_knots=12.0,
        course_over_ground_deg=285.0,
    )


@pytest.fixture
def base_voyage(base_vessel, base_route, base_position) -> VoyageContext:
    provider = MockWeatherProvider()
    builder = VoyageContextBuilder("VOY_TEST_DECISION")
    builder.set_vessel(base_vessel)
    builder.set_route(base_route)
    builder.set_position(base_position)
    builder.set_energy_state(
        VesselEnergyState(
            battery_soc_pct=80.0,
            battery_soh_pct=99.0,
            battery_energy_available_kwh=520.0,
            solar_power_kw=14.0,
            solar_energy_today_kwh=48.0,
            fuel_remaining_liters=5000.0,
            fuel_consumption_rate_lph=175.0,
        )
    )
    builder.enrich_weather_from_provider(provider)
    return builder.build()


@pytest.fixture
def full_engineering_inputs() -> EngineeringDecisionInputs:
    return EngineeringDecisionInputs(
        baseline_fuel_consumption_liters=3259.7,
        estimated_solar_energy_kwh=68.5,
        estimated_battery_displacement_kwh=120.0,
        total_clean_energy_kwh=188.5,
        co2_emissions_kg=8628.2,
        cii_attained_rating="A",
        optimal_transit_speed_knots=11.5,
        net_present_value_usd=145000.0,
        payback_period_years=4.2,
    )


# =====================================================================
# ALL 25 TEST ITEMS
# =====================================================================

def test_01_valid_decision_context(base_voyage, full_engineering_inputs):
    """Item 1: Verify creation of complete valid DecisionContext."""
    dc = DecisionContext(
        decision_context_id="DC_001",
        created_at_utc="2026-06-15T12:05:00Z",
        voyage_context=base_voyage,
        engineering_inputs=full_engineering_inputs,
    )
    assert dc.decision_context_id == "DC_001"
    assert dc.voyage_id == "VOY_TEST_DECISION"
    assert dc.vessel_id == "VESSEL_OSV_01"
    assert dc.readiness == AdvisoryReadinessState.READY
    assert dc.is_advisory_ready is True


def test_02_missing_vessel_data(base_route, base_position):
    """Item 2: Verify failure when building context without vessel."""
    with pytest.raises(ValueError):
        VoyageContextBuilder("VOY_NO_VESSEL").set_route(base_route).set_position(base_position).build()


def test_03_missing_route_data(base_vessel, base_position):
    """Item 3: Verify failure when building context without route."""
    with pytest.raises(ValueError):
        VoyageContextBuilder("VOY_NO_ROUTE").set_vessel(base_vessel).set_position(base_position).build()


def test_04_missing_position(base_vessel, base_route):
    """Item 4: Verify failure when building context without position."""
    with pytest.raises(ValueError):
        VoyageContextBuilder("VOY_NO_POS").set_vessel(base_vessel).set_route(base_route).build()


def test_05_missing_eta(base_voyage):
    """Item 5: Verify missing ETA remains explicitly None."""
    assert base_voyage.timeline.estimated_arrival_time_utc is None
    dc = DecisionContext(
        decision_context_id="DC_ETA",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=base_voyage,
    )
    assert dc.voyage_context.timeline.estimated_arrival_time_utc is None


def test_06_valid_current_weather(base_voyage):
    """Item 6: Verify current weather is accessible from DecisionContext."""
    dc = DecisionContext(
        decision_context_id="DC_WX",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=base_voyage,
    )
    assert dc.current_weather is not None
    assert dc.current_weather.latitude == 5.80
    assert dc.current_weather.wind_speed_ms is not None


def test_07_missing_weather(base_vessel, base_route, base_position):
    """Item 7: Verify missing weather produces INSUFFICIENT_DATA readiness."""
    voyage_no_wx = VoyageContext(
        voyage_id="VOY_NO_WX",
        vessel=base_vessel,
        route=base_route,
        current_position=base_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
    )
    dc = DecisionContext(
        decision_context_id="DC_NO_WX",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=voyage_no_wx,
    )
    assert dc.readiness == AdvisoryReadinessState.INSUFFICIENT_DATA
    assert "Current weather observation is unavailable" in dc.readiness_reasons[0]


def test_08_stale_weather(base_vessel, base_route, base_position):
    """Item 8: Verify expired weather produces STALE_DATA readiness."""
    provider = MockWeatherProvider(mode="stale")
    builder = VoyageContextBuilder("VOY_STALE")
    builder.set_vessel(base_vessel).set_route(base_route).set_position(base_position)
    builder.enrich_weather_from_provider(provider)
    stale_voyage = builder.build()

    dc = DecisionContext(
        decision_context_id="DC_STALE",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=stale_voyage,
    )
    assert dc.readiness == AdvisoryReadinessState.STALE_DATA


def test_09_invalid_weather(base_vessel, base_route, base_position):
    """Item 9: Verify corrupted/invalid weather quality produces INVALID_DATA readiness."""
    rec = NormalizedWeatherRecord(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="MOCK",
        data_type=WeatherProvenanceType.OBSERVED,
        data_quality=WeatherQualityState.INVALID,
    )
    voyage_inv = VoyageContext(
        voyage_id="VOY_INV",
        vessel=base_vessel,
        route=base_route,
        current_position=base_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        weather_context=VoyageWeatherContext(current_weather=rec, weather_quality=WeatherQualityState.INVALID),
    )
    dc = DecisionContext(
        decision_context_id="DC_INV",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=voyage_inv,
    )
    assert dc.readiness == AdvisoryReadinessState.INVALID_DATA


def test_10_historical_weather_provenance():
    """Item 10: Verify historical weather provenance preservation."""
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2024-01-15T12:00:00Z",
        data_source="HIST",
        data_type=WeatherProvenanceType.HISTORICAL,
    )
    assert rec.data_type == WeatherProvenanceType.HISTORICAL


def test_11_forecast_weather_provenance():
    """Item 11: Verify forecast weather provenance preservation."""
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-16T12:00:00Z",
        data_source="FCST",
        data_type=WeatherProvenanceType.FORECAST,
    )
    assert rec.data_type == WeatherProvenanceType.FORECAST


def test_12_observed_weather_provenance():
    """Item 12: Verify observed weather provenance preservation."""
    rec = NormalizedWeatherRecord(
        latitude=6.45,
        longitude=3.40,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="OBS",
        data_type=WeatherProvenanceType.OBSERVED,
    )
    assert rec.data_type == WeatherProvenanceType.OBSERVED


def test_13_valid_energy_state(base_voyage):
    """Item 13: Verify valid energy state telemetry."""
    energy = base_voyage.energy_state
    assert energy.battery_soc_pct == 80.0
    assert energy.fuel_remaining_liters == 5000.0


def test_14_missing_energy_state(base_vessel, base_route, base_position):
    """Item 14: Verify missing energy state fields default to None."""
    energy = VesselEnergyState()
    assert energy.battery_soc_pct is None
    assert energy.fuel_remaining_liters is None


def test_15_missing_battery_values():
    """Item 15: Verify missing battery values remain None and never 0."""
    energy = VesselEnergyState()
    assert energy.battery_soc_pct is not 0.0
    assert energy.battery_soc_pct is None


def test_16_missing_fuel_values():
    """Item 16: Verify missing fuel values remain None and never 0."""
    energy = VesselEnergyState()
    assert energy.fuel_remaining_liters is not 0.0
    assert energy.fuel_remaining_liters is None


def test_17_engineering_result_present(full_engineering_inputs):
    """Item 17: Verify engineering decision inputs structure."""
    assert full_engineering_inputs.baseline_fuel_consumption_liters == 3259.7
    assert full_engineering_inputs.cii_attained_rating == "A"


def test_18_engineering_result_unavailable(base_voyage):
    """Item 18: Verify DecisionContext handles missing engineering inputs."""
    dc = DecisionContext(
        decision_context_id="DC_NO_ENG",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=base_voyage,
        engineering_inputs=None,
    )
    assert dc.engineering_inputs is None
    assert dc.readiness == AdvisoryReadinessState.PARTIAL


def test_19_readiness_calculation_ready(base_voyage, full_engineering_inputs):
    """Item 19: Verify READY classification when all inputs are present and fresh."""
    dc = DecisionContext(
        decision_context_id="DC_READY",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=base_voyage,
        engineering_inputs=full_engineering_inputs,
    )
    assert dc.readiness == AdvisoryReadinessState.READY


def test_20_partial_readiness(base_voyage):
    """Item 20: Verify PARTIAL classification when engineering inputs are omitted."""
    dc = DecisionContext(
        decision_context_id="DC_PARTIAL",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=base_voyage,
    )
    assert dc.readiness == AdvisoryReadinessState.PARTIAL
    assert len(dc.readiness_reasons) > 0


def test_21_insufficient_data_readiness(base_vessel, base_route, base_position):
    """Item 21: Verify INSUFFICIENT_DATA classification when weather is unavailable."""
    voyage = VoyageContext(
        voyage_id="VOY_MINIMAL",
        vessel=base_vessel,
        route=base_route,
        current_position=base_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
    )
    dc = DecisionContext(
        decision_context_id="DC_INSUF",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=voyage,
    )
    assert dc.readiness == AdvisoryReadinessState.INSUFFICIENT_DATA


def test_22_invalid_data_readiness(base_vessel, base_route, base_position):
    """Item 22: Verify INVALID_DATA classification upon corrupt weather."""
    rec = NormalizedWeatherRecord(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="MOCK",
        data_type=WeatherProvenanceType.OBSERVED,
        data_quality=WeatherQualityState.INVALID,
    )
    voyage = VoyageContext(
        voyage_id="VOY_CORRUPT",
        vessel=base_vessel,
        route=base_route,
        current_position=base_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        weather_context=VoyageWeatherContext(current_weather=rec, weather_quality=WeatherQualityState.INVALID),
    )
    dc = DecisionContext(
        decision_context_id="DC_CORRUPT",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=voyage,
    )
    assert dc.readiness == AdvisoryReadinessState.INVALID_DATA


def test_23_serialization(base_voyage, full_engineering_inputs):
    """Item 23: Verify JSON serialization and round-trip parsing."""
    dc = DecisionContext(
        decision_context_id="DC_JSON",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=base_voyage,
        engineering_inputs=full_engineering_inputs,
    )
    json_str = dc.model_dump_json()
    data = json.loads(json_str)

    assert data["decision_context_id"] == "DC_JSON"
    assert data["readiness"] == "READY"
    assert data["engineering_inputs"]["baseline_fuel_consumption_liters"] == 3259.7

    # Round trip reconstruction
    rebuilt = DecisionContext.model_validate_json(json_str)
    assert rebuilt.decision_context_id == dc.decision_context_id
    assert rebuilt.voyage_context.voyage_id == dc.voyage_context.voyage_id


def test_24_immutability_and_validation(base_voyage):
    """Item 24: Verify ID validation on DecisionContext."""
    with pytest.raises(ValidationError):
        DecisionContext(
            decision_context_id="",  # Empty
            created_at_utc="2026-06-15T12:00:00Z",
            voyage_context=base_voyage,
        )


def test_25_wind_propulsion_capability_remains_absent():
    """Item 25: Re-verify that wind propulsion physical models remain absent."""
    import os
    models = os.listdir("models")
    assert "wind_propulsion.joblib" not in models
    assert "sail_thrust.joblib" not in models
    assert "flettner_rotor.joblib" not in models
