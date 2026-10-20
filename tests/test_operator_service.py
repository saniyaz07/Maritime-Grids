"""
tests/test_operator_service.py — Phase 10C.8 Operator / Driver Service Tests
=============================================================================
Comprehensive test suite validating OperatorService situational awareness,
OperatorStateResponse assembly, weather provenance/quality/freshness preservation,
truthful missing data handling, safe ETA derivation (with sog=0/None guards),
absence of autonomous control/actuation, and absence of wind propulsion physics.
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
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
    EngineeringDecisionInputs,
)
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
from app.pipeline.advisory_pipeline import AdvisoryPipeline
from app.facade.scenario_facade import MaritimeScenarioFacade
from app.services.contracts import (
    FieldAvailabilityClassification,
    OperatorAdvisorySummary,
    OperatorEnergyState,
    OperatorRegulatoryState,
    OperatorStateMetadata,
    OperatorStateResponse,
    OperatorVesselState,
    OperatorWeatherState,
    RouteProgressInfo,
)
from app.services.operator_service import OperatorService
from app.services.engineering_service import EngineeringService


# =====================================================================
# FIXTURES
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


class ConfigurableWeatherProvider(MockWeatherProvider):
    """Deterministic mock provider for testing explicit provenance and quality states."""
    def __init__(
        self,
        custom_provenance: WeatherProvenanceType = WeatherProvenanceType.OBSERVED,
        custom_quality: WeatherQualityState = WeatherQualityState.VALID,
        custom_freshness: WeatherFreshnessState = WeatherFreshnessState.FRESH,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.custom_provenance = custom_provenance
        self.custom_quality = custom_quality
        self.custom_freshness = custom_freshness

    def get_current_weather(self, latitude: float, longitude: float) -> NormalizedWeatherRecord:
        rec = super().get_current_weather(latitude, longitude)
        rec.data_type = self.custom_provenance
        rec.data_quality = self.custom_quality
        rec.freshness = self.custom_freshness
        return rec


# =====================================================================
# 1. CORE OPERATOR STATE & PROVENANCE TESTS (ITEMS 1–10)
# =====================================================================

def test_01_valid_operator_state_response(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 1: Valid telemetry produces structured OperatorStateResponse."""
    service = OperatorService()
    provider = MockWeatherProvider()

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert isinstance(res, OperatorStateResponse)
    assert res.vessel.vessel_id == "VESSEL_OSV_LAGOS_01"
    assert res.metadata.readiness_state == AdvisoryReadinessState.READY
    assert res.energy.battery_soc_pct == 85.0
    assert res.regulatory.attained_cii_rating == "A"
    assert res.regulatory.compliance_state == "COMPLIANT"


def test_02_weather_provenance_preservation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 2: Weather provenance is preserved in OperatorStateResponse."""
    service = OperatorService()
    provider = ConfigurableWeatherProvider(custom_provenance=WeatherProvenanceType.HISTORICAL)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.weather.provenance == WeatherProvenanceType.HISTORICAL
    assert res.weather.current.data_type == WeatherProvenanceType.HISTORICAL


def test_03_weather_quality_preservation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 3: Weather quality state is preserved in OperatorStateResponse."""
    service = OperatorService()
    provider = ConfigurableWeatherProvider(custom_quality=WeatherQualityState.PARTIAL)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.weather.quality == WeatherQualityState.PARTIAL


def test_04_weather_freshness_preservation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 4: Weather freshness state is preserved in OperatorStateResponse."""
    service = OperatorService()
    provider = ConfigurableWeatherProvider(custom_freshness=WeatherFreshnessState.STALE)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.weather.freshness == WeatherFreshnessState.STALE


def test_05_missing_energy_telemetry_remains_missing(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs
):
    """Test 5: Unobserved energy fields remain None without zero-substitution."""
    service = OperatorService()
    provider = MockWeatherProvider()
    empty_energy = VesselEnergyState()

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=empty_energy,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.energy.battery_soc_pct is None
    assert res.energy.fuel_remaining_liters is None
    assert res.energy.solar_power_kw is None


def test_06_advisories_from_pipeline(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Test 6: Advisories originate from AdvisoryPipeline with traceable evidence."""
    service = OperatorService()
    provider = MockWeatherProvider()
    low_batt = VesselEnergyState(battery_soc_pct=15.0)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=low_batt,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert res.advisories.warning_count >= 1
    batt_adv = res.get_advisories_by_category(AdvisoryCategory.BATTERY)[0]
    assert batt_adv.evidence[0].observed_value == 15.0
    assert batt_adv.evidence[0].threshold_value == 20.0


def test_07_human_review_required_flag(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Test 7: human_review_required is unconditionally True across all advisories."""
    service = OperatorService()
    provider = MockWeatherProvider()
    low_batt = VesselEnergyState(battery_soc_pct=15.0)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=low_batt,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    for adv in res.advisories.items:
        assert adv.human_review_required is True


def test_08_no_unconfigured_false_alarms(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs
):
    """Test 8: Unconfigured policy emits 0 threshold-based advisories on degraded state."""
    service = OperatorService()
    provider = MockWeatherProvider()
    degraded = VesselEnergyState(battery_soc_pct=12.0, fuel_remaining_liters=400.0)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=degraded,
        engineering_inputs=sample_engineering_inputs,
        policy=None,
    )

    assert res.advisories.total_count == 0


def test_09_explicit_policy_sensitivity(
    sample_vessel, sample_route, sample_position, sample_engineering_inputs, sample_policy
):
    """Test 9: Supplying explicit policy activates threshold evaluation deterministically."""
    service = OperatorService()
    provider = MockWeatherProvider()
    degraded = VesselEnergyState(battery_soc_pct=12.0, fuel_remaining_liters=400.0)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=degraded,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    assert res.advisories.total_count == 2  # Battery + Fuel


def test_10_deterministic_service_output(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs, sample_policy
):
    """Test 10: Repeatable inputs produce identical service responses."""
    service = OperatorService()
    provider = MockWeatherProvider()

    res1 = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
        request_id="REQ_STATIC",
    )
    res2 = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
        request_id="REQ_STATIC",
    )

    assert res1.metadata.request_id == res2.metadata.request_id
    assert res1.advisories.total_count == res2.advisories.total_count


# =====================================================================
# 2. DATA QUALITY & FAILURE PROPAGATION (ITEMS 11–14)
# =====================================================================

def test_11_unavailable_weather_propagation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 11: Unavailable weather produces INSUFFICIENT_DATA and data-quality advisory."""
    service = OperatorService()
    voyage_no_wx = VoyageContext(
        voyage_id="VOY_NO_WX",
        vessel=sample_vessel,
        route=sample_route,
        current_position=sample_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        weather_context=VoyageWeatherContext(current_weather=None, weather_quality=WeatherQualityState.UNAVAILABLE),
        energy_state=sample_energy_state,
    )

    res = service.get_operator_state_from_voyage(
        voyage_context=voyage_no_wx,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.metadata.readiness_state == AdvisoryReadinessState.INSUFFICIENT_DATA
    assert res.weather.quality == WeatherQualityState.UNAVAILABLE
    assert any(a.category == AdvisoryCategory.DATA_QUALITY for a in res.advisories.items)


def test_12_stale_weather_propagation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 12: Stale weather produces STALE_DATA readiness and freshness notice."""
    service = OperatorService()
    provider = MockWeatherProvider(mode="stale")

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.metadata.readiness_state == AdvisoryReadinessState.STALE_DATA
    assert res.weather.freshness == WeatherFreshnessState.EXPIRED


def test_13_invalid_weather_propagation(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 13: Corrupted weather quality produces INVALID_DATA and CRITICAL advisory."""
    service = OperatorService()
    provider = ConfigurableWeatherProvider(custom_quality=WeatherQualityState.INVALID)

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.metadata.readiness_state == AdvisoryReadinessState.INVALID_DATA
    assert res.has_critical_advisories() is True


def test_14_input_immutability(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs, sample_policy
):
    """Test 14: OperatorService execution guarantees zero mutation of inputs."""
    service = OperatorService()
    provider = MockWeatherProvider()

    orig_waypoints = [(wp.latitude, wp.longitude) for wp in sample_route.waypoints]
    orig_sog = sample_position.speed_over_ground_knots

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
        policy=sample_policy,
    )

    after_waypoints = [(wp.latitude, wp.longitude) for wp in sample_route.waypoints]
    assert orig_waypoints == after_waypoints
    assert sample_position.speed_over_ground_knots == orig_sog


# =====================================================================
# 3. ROUTE PROGRESS & ETA ESTIMATION GUARDS (ITEMS 15–18)
# =====================================================================

def test_15_route_progress_with_positive_sog(sample_route, sample_position):
    """Test 15: RouteProgressInfo computes valid progress and ETA when SOG > 0."""
    info = OperatorService._compute_route_progress(route=sample_route, position=sample_position)
    assert info.total_distance_nm == 130.0
    assert info.distance_remaining_nm is not None
    assert info.route_progress_pct is not None
    assert info.eta_utc is not None
    assert "linear estimate" in info.eta_derivation_note


def test_16_route_progress_with_zero_sog(sample_route, sample_position):
    """Test 16: RouteProgressInfo safely handles SOG = 0 without division-by-zero."""
    sample_position.speed_over_ground_knots = 0.0
    info = OperatorService._compute_route_progress(route=sample_route, position=sample_position)
    assert info.total_distance_nm == 130.0
    assert info.eta_utc is None  # ETA is None when stationary


def test_17_route_progress_with_missing_sog(sample_route, sample_position):
    """Test 17: RouteProgressInfo safely handles SOG = None without error."""
    sample_position.speed_over_ground_knots = None
    info = OperatorService._compute_route_progress(route=sample_route, position=sample_position)
    assert info.total_distance_nm == 130.0
    assert info.eta_utc is None


def test_18_route_progress_zero_distance_route():
    """Test 18: RouteProgressInfo safely handles zero-distance route."""
    empty_route = Route(
        route_id="PORT_BERTH",
        origin_port="Port A",
        destination_port="Port B",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1", latitude=6.45, longitude=3.40),
            RouteWaypoint(waypoint_id="WP2", latitude=6.45, longitude=3.40),
        ],
        total_distance_nm=0.0,
    )
    pos = VesselPosition(latitude=6.45, longitude=3.40, timestamp_utc="2026-06-15T12:00:00Z")
    info = OperatorService._compute_route_progress(route=empty_route, position=pos)
    assert info.route_progress_pct == 100.0
    assert info.eta_utc is None


# =====================================================================
# 4. SAFETY & PHYSICAL BOUNDARY AUDIT (ITEMS 19–23)
# =====================================================================

def test_19_no_actuation_methods_on_operator_service():
    """Test 19: OperatorService contains no actuation, steering, or throttle APIs."""
    service = OperatorService()
    methods = [m for m in dir(service) if not m.startswith("_")]
    assert "set_throttle" not in methods
    assert "steer" not in methods
    assert "start_engine" not in methods
    assert "stop_engine" not in methods
    assert "execute_advisory" not in methods
    assert "apply_recommendation" not in methods


def test_20_no_wind_propulsion_in_services():
    """Test 20: Re-verify absence of wind propulsion or thrust calculation code."""
    import inspect
    import app.services.operator_service as op_mod
    import app.services.engineering_service as eng_mod

    for mod in (op_mod, eng_mod):
        src = inspect.getsource(mod)
        assert "sail_thrust" not in src
        assert "flettner_rotor" not in src
        assert "wind_propulsion" not in src
        assert "engine_off" not in src


def test_21_services_independence():
    """Test 21: EngineeringService and OperatorService remain modular and independent."""
    eng_svc = EngineeringService()
    op_svc = OperatorService()

    assert not isinstance(eng_svc.facade, AdvisoryPipeline)
    assert not isinstance(op_svc.pipeline, MaritimeScenarioFacade)


def test_22_operator_response_to_dict(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 22: OperatorStateResponse.to_dict() serializes cleanly to JSON."""
    service = OperatorService()
    provider = MockWeatherProvider()

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    data = res.to_dict()
    json_str = json.dumps(data)
    assert "vessel" in json_str
    assert "weather" in json_str
    assert "energy" in json_str


def test_23_regulatory_compliance_state_mapping(
    sample_vessel, sample_route, sample_position, sample_energy_state, sample_engineering_inputs
):
    """Test 23: CII rating 'E' correctly maps to compliance_state='NON_COMPLIANT'."""
    sample_engineering_inputs.cii_attained_rating = "E"
    service = OperatorService()
    provider = MockWeatherProvider()

    res = service.get_operator_state_from_telemetry(
        vessel=sample_vessel,
        route=sample_route,
        position=sample_position,
        weather_provider=provider,
        energy_state=sample_energy_state,
        engineering_inputs=sample_engineering_inputs,
    )

    assert res.regulatory.attained_cii_rating == "E"
    assert res.regulatory.compliance_state == "NON_COMPLIANT"
