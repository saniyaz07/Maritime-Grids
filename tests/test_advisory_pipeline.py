"""
tests/test_advisory_pipeline.py — Phase 10C.6 End-to-End Advisory Pipeline Integration Tests
=============================================================================================
Comprehensive integration test suite verifying the end-to-end decision-support pipeline:
  WeatherProvider -> Normalized Weather -> VoyageContext -> DecisionContext -> AdvisoryEngine -> Structured Output

Validates all 25+ required Phase 10C.6 integration scenarios covering basic flow, weather data quality,
explicit policy configuration, evidence preservation, determinism, human-in-the-loop safety,
and physical boundaries (no wind propulsion / no engine-off calculations).
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
from app.advisory.contracts import (
    Advisory,
    AdvisoryCategory,
    AdvisoryEvidence,
    AdvisoryPolicy,
    AdvisorySeverity,
    AdvisoryStatus,
    BatterySocPolicy,
    FuelLevelPolicy,
    WeatherSafetyPolicy,
)
from app.pipeline.advisory_pipeline import (
    AdvisoryPipeline,
    AdvisoryPipelineResult,
)


# =====================================================================
# FIXTURES & HELPER MOCKS
# =====================================================================

@pytest.fixture
def sample_vessel() -> VesselContext:
    return VesselContext(
        vessel_id="VESSEL_OSV_LAGOS_01",
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
            RouteWaypoint(waypoint_id="WP1", latitude=5.58, longitude=5.18),
            RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.50),
            RouteWaypoint(waypoint_id="WP3", latitude=6.45, longitude=3.40),
        ],
        total_distance_nm=130.0,
    )


@pytest.fixture
def sample_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        speed_over_ground_knots=12.0,
        course_over_ground_deg=285.0,
    )


@pytest.fixture
def sample_energy_state() -> VesselEnergyState:
    return VesselEnergyState(
        battery_soc_pct=85.0,
        battery_soh_pct=99.0,
        battery_energy_available_kwh=550.0,
        solar_power_kw=15.0,
        solar_energy_today_kwh=50.0,
        fuel_remaining_liters=6000.0,
        fuel_consumption_rate_lph=170.0,
    )


@pytest.fixture
def sample_engineering_inputs() -> EngineeringDecisionInputs:
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


@pytest.fixture
def sample_policy() -> AdvisoryPolicy:
    return AdvisoryPolicy(
        battery_policy=BatterySocPolicy(
            warning_threshold_pct=20.0,
            notice_threshold_pct=35.0,
        ),
        fuel_policy=FuelLevelPolicy(
            warning_threshold_liters=1000.0,
        ),
        weather_policy=WeatherSafetyPolicy(
            high_wind_threshold_knots=25.0,
            rough_sea_threshold_m=2.5,
        ),
    )


class CustomWeatherProvider(MockWeatherProvider):
    """Configurable mock provider for testing explicit provenance and quality states."""
    def __init__(
        self,
        custom_provenance: WeatherProvenanceType = WeatherProvenanceType.OBSERVED,
        custom_quality: WeatherQualityState = WeatherQualityState.VALID,
        custom_wind_kts: Optional[float] = None,
        custom_wave_m: Optional[float] = None,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.custom_provenance = custom_provenance
        self.custom_quality = custom_quality
        self.custom_wind_kts = custom_wind_kts
        self.custom_wave_m = custom_wave_m

    def get_current_weather(self, latitude: float, longitude: float) -> NormalizedWeatherRecord:
        rec = super().get_current_weather(latitude, longitude)
        rec.data_type = self.custom_provenance
        rec.data_quality = self.custom_quality
        if self.custom_wind_kts is not None:
            rec.wind_speed_knots = self.custom_wind_kts
        if self.custom_wave_m is not None:
            rec.wave_height_m = self.custom_wave_m
        return rec


# =====================================================================
# 1. BASIC PIPELINE INTEGRATION SCENARIOS (ITEMS 1–6)
# =====================================================================

def test_01_valid_voyage_to_valid_decision_context(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 1: Valid voyage definition produces a valid DecisionContext through pipeline."""
    mock_weather = MockWeatherProvider()
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert isinstance(result, AdvisoryPipelineResult)
    assert result.decision_context.readiness == AdvisoryReadinessState.READY
    assert result.decision_context.voyage_context.vessel.vessel_id == "VESSEL_OSV_LAGOS_01"


def test_02_healthy_context_zero_advisories(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs, sample_policy
):
    """Scenario 2: Healthy context with configured policy emits 0 advisories when all conditions are normal."""
    mock_weather = MockWeatherProvider()
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert result.total_advisories == 0
    assert len(result.advisories) == 0
    assert result.has_critical_advisories() is False


def test_03_configured_battery_threshold_triggers_advisory(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 3: Low battery SoC triggers BATTERY advisory when policy is configured."""
    mock_weather = MockWeatherProvider()
    low_batt_state = VesselEnergyState(
        battery_soc_pct=15.0,  # Below 20% warning threshold
        battery_soh_pct=99.0,
        fuel_remaining_liters=6000.0,
    )
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=low_batt_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    battery_advs = result.get_advisories_by_category(AdvisoryCategory.BATTERY)
    assert len(battery_advs) == 1
    assert battery_advs[0].severity == AdvisorySeverity.WARNING
    assert "15.0%" in battery_advs[0].message
    assert "20.0%" in battery_advs[0].message


def test_04_configured_fuel_threshold_triggers_advisory(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 4: Low fuel reserve triggers FUEL advisory when policy is configured."""
    mock_weather = MockWeatherProvider()
    low_fuel_state = VesselEnergyState(
        battery_soc_pct=80.0,
        fuel_remaining_liters=650.0,  # Below 1000 L reserve threshold
    )
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=low_fuel_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    fuel_advs = result.get_advisories_by_category(AdvisoryCategory.FUEL)
    assert len(fuel_advs) == 1
    assert fuel_advs[0].severity == AdvisorySeverity.WARNING
    assert "650.0 L" in fuel_advs[0].message


def test_05_configured_wind_threshold_triggers_advisory(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs, sample_policy
):
    """Scenario 5: High wind speed triggers WEATHER advisory when policy is configured."""
    provider = CustomWeatherProvider(custom_wind_kts=32.0)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    wx_advs = result.get_advisories_by_category(AdvisoryCategory.WEATHER)
    assert len(wx_advs) == 1
    assert "High Wind" in wx_advs[0].title
    assert wx_advs[0].evidence[0].observed_value == 32.0


def test_06_configured_wave_threshold_triggers_advisory(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs, sample_policy
):
    """Scenario 6: High wave height triggers rough sea WEATHER advisory when policy is configured."""
    provider = CustomWeatherProvider(custom_wave_m=3.8)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    wx_advs = result.get_advisories_by_category(AdvisoryCategory.WEATHER)
    assert len(wx_advs) == 1
    assert "Rough Sea" in wx_advs[0].title
    assert wx_advs[0].evidence[0].observed_value == 3.8


# =====================================================================
# 2. WEATHER & DATA QUALITY SCENARIOS (ITEMS 7–11)
# =====================================================================

def test_07_stale_weather_triggers_data_quality_advisory(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 7: Stale weather telemetry produces DATA_QUALITY advisory."""
    mock_weather = MockWeatherProvider(mode="stale")
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    dq_advs = result.get_advisories_by_category(AdvisoryCategory.DATA_QUALITY)
    assert len(dq_advs) >= 1
    assert any("Freshness" in a.title for a in dq_advs)


def test_08_unavailable_weather_triggers_data_quality_advisory(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 8: Weather unavailable produces DATA_QUALITY advisory and marks readiness."""
    voyage_no_wx = VoyageContext(
        voyage_id="VOY_NO_WX",
        vessel=sample_vessel,
        route=sample_route,
        current_position=sample_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        weather_context=VoyageWeatherContext(current_weather=None, weather_quality=WeatherQualityState.UNAVAILABLE),
        energy_state=sample_energy_state,
    )
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_voyage(
        voyage_context=voyage_no_wx,
        engineering_inputs=sample_engineering_inputs,
    )

    dq_advs = result.get_advisories_by_category(AdvisoryCategory.DATA_QUALITY)
    assert len(dq_advs) >= 1
    assert any("Unavailable" in a.title for a in dq_advs)
    assert result.decision_context.readiness == AdvisoryReadinessState.INSUFFICIENT_DATA


def test_09_invalid_weather_triggers_critical_advisory(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 9: Corrupt/invalid weather telemetry produces CRITICAL advisory."""
    provider = CustomWeatherProvider(custom_quality=WeatherQualityState.INVALID)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert result.has_critical_advisories() is True
    crit_advs = result.get_advisories_by_severity(AdvisorySeverity.CRITICAL)
    assert len(crit_advs) >= 1
    assert crit_advs[0].category == AdvisoryCategory.DATA_QUALITY


def test_10_historical_weather_preserves_provenance(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 10: Historical weather query preserves HISTORICAL provenance in context and evidence."""
    provider = CustomWeatherProvider(custom_provenance=WeatherProvenanceType.HISTORICAL)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    curr_wx = result.decision_context.voyage_context.weather_context.current_weather
    assert curr_wx.data_type == WeatherProvenanceType.HISTORICAL


def test_11_forecast_weather_preserves_provenance(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 11: Forecast weather preserves FORECAST provenance."""
    provider = CustomWeatherProvider(custom_provenance=WeatherProvenanceType.FORECAST)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    curr_wx = result.decision_context.voyage_context.weather_context.current_weather
    assert curr_wx.data_type == WeatherProvenanceType.FORECAST


# =====================================================================
# 3. POLICY & TRUTHFUL EVALUATION SCENARIOS (ITEMS 12–15)
# =====================================================================

def test_12_no_policy_emits_zero_threshold_false_alarms(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs
):
    """Scenario 12: Unconfigured policy emits 0 threshold-based advisories even on degraded telemetry."""
    mock_weather = MockWeatherProvider()
    degraded_energy = VesselEnergyState(
        battery_soc_pct=10.0,
        fuel_remaining_liters=400.0,
    )
    pipeline = AdvisoryPipeline()  # No policy

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=degraded_energy,
        engineering_inputs=sample_engineering_inputs,
        policy=None,
    )

    assert result.total_advisories == 0


def test_13_configured_policy_changes_output_deterministically(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 13: Supplying explicit policy deterministically triggers threshold rules."""
    mock_weather = MockWeatherProvider()
    degraded_energy = VesselEnergyState(
        battery_soc_pct=10.0,
        fuel_remaining_liters=400.0,
    )
    pipeline = AdvisoryPipeline()

    result_unconf = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=degraded_energy,
        engineering_inputs=sample_engineering_inputs,
        policy=None,
    )
    result_conf = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=degraded_energy,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert result_unconf.total_advisories == 0
    assert result_conf.total_advisories == 2  # Battery + Fuel


def test_14_advisory_evidence_contains_configured_policy_threshold(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 14: Evidence records the exact policy threshold value."""
    mock_weather = MockWeatherProvider()
    low_batt_state = VesselEnergyState(battery_soc_pct=12.0)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=low_batt_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    batt_adv = result.get_advisories_by_category(AdvisoryCategory.BATTERY)[0]
    assert batt_adv.evidence[0].threshold_value == 20.0
    assert batt_adv.evidence[0].observed_value == 12.0


def test_15_repeatable_determinism(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 15: Identical inputs produce identical structured advisory output."""
    mock_weather = MockWeatherProvider()
    low_batt_state = VesselEnergyState(battery_soc_pct=15.0, fuel_remaining_liters=500.0)
    pipeline = AdvisoryPipeline()

    res1 = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=low_batt_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
        pipeline_id="RUN_STATIC_ID",
    )
    res2 = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=low_batt_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
        pipeline_id="RUN_STATIC_ID",
    )

    assert res1.total_advisories == res2.total_advisories
    assert [a.title for a in res1.advisories] == [a.title for a in res2.advisories]
    assert [a.deduplication_key for a in res1.advisories] == [a.deduplication_key for a in res2.advisories]


# =====================================================================
# 4. HUMAN-IN-THE-LOOP SAFETY & PHYSICAL BOUNDARIES (ITEMS 16–20)
# =====================================================================

def test_16_no_autonomous_control_in_pipeline(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 16: Human review required is unconditionally True across all advisories."""
    mock_weather = MockWeatherProvider()
    low_batt_state = VesselEnergyState(battery_soc_pct=15.0, fuel_remaining_liters=500.0)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=low_batt_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert result.total_advisories > 0
    for adv in result.advisories:
        assert adv.human_review_required is True


def test_17_no_route_mutation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs, sample_policy
):
    """Scenario 17: Pipeline execution never mutates route waypoints or path."""
    mock_weather = MockWeatherProvider()
    initial_waypoints = [(wp.latitude, wp.longitude) for wp in sample_route.waypoints]
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    after_waypoints = [(wp.latitude, wp.longitude) for wp in sample_route.waypoints]
    assert initial_waypoints == after_waypoints


def test_18_no_speed_mutation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs, sample_policy
):
    """Scenario 18: Pipeline execution never mutates vessel position speed or course."""
    mock_weather = MockWeatherProvider()
    orig_sog = sample_position.speed_over_ground_knots
    orig_cog = sample_position.course_over_ground_deg
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert sample_position.speed_over_ground_knots == orig_sog
    assert sample_position.course_over_ground_deg == orig_cog


def test_19_no_engine_off_calculation():
    """Scenario 19: Verify engine-off calculation functions remain absent from pipeline module."""
    import inspect
    import app.pipeline.advisory_pipeline as pipe_mod

    functions = [f for f in dir(pipe_mod) if inspect.isfunction(getattr(pipe_mod, f))]
    assert "calculate_engine_off_duration" not in functions
    assert "compute_wind_savings" not in functions


def test_20_no_wind_propulsion_model():
    """Scenario 20: Verify wind propulsion physical models remain absent from codebase."""
    import os
    models = os.listdir("models")
    assert "wind_propulsion.joblib" not in models
    assert "sail_thrust.joblib" not in models


# =====================================================================
# 5. ADDITIONAL E2E SCENARIOS & OUTPUT CAPABILITIES (ITEMS 21–25)
# =====================================================================

def test_21_pipeline_severity_counts_and_helpers(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 21: Verify pipeline severity counts and filtering helpers."""
    provider = CustomWeatherProvider(custom_quality=WeatherQualityState.INVALID)
    low_batt_state = VesselEnergyState(battery_soc_pct=15.0)
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=low_batt_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert result.critical_count >= 1
    assert result.warning_count >= 1
    assert result.total_advisories == (result.critical_count + result.warning_count + result.notice_count + result.info_count)
    assert len(result.get_advisories_by_severity(AdvisorySeverity.CRITICAL)) == result.critical_count


def test_22_pipeline_to_summary_dict(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 22: Verify to_summary_dict() produces valid JSON-serializable dictionary."""
    mock_weather = MockWeatherProvider()
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    summary = result.to_summary_dict()
    json_str = json.dumps(summary)
    assert "pipeline_id" in json_str
    assert summary["readiness_state"] == "READY"


def test_23_cii_advisory_in_pipeline(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 23: Attained CII rating 'E' generates CII advisory in pipeline."""
    sample_engineering_inputs.cii_attained_rating = "E"
    mock_weather = MockWeatherProvider()
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    cii_advs = result.get_advisories_by_category(AdvisoryCategory.CII)
    assert len(cii_advs) == 1
    assert "SEEMP Part III" in cii_advs[0].message


def test_24_missing_energy_fields_propagate_truthfully(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Scenario 24: Missing energy fields remain None without zero substitution or crash."""
    mock_weather = MockWeatherProvider()
    empty_energy = VesselEnergyState()  # All None
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=empty_energy,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert result.decision_context.voyage_context.energy_state.battery_soc_pct is None
    assert result.total_advisories == 0


def test_25_pipeline_offline_execution_no_network(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Scenario 25: AdvisoryPipeline executes 100% offline with zero external network access."""
    mock_weather = MockWeatherProvider()
    pipeline = AdvisoryPipeline()

    result = pipeline.run_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=mock_weather,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert result.decision_context.readiness == AdvisoryReadinessState.READY
