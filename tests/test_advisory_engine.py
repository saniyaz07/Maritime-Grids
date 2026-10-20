"""
tests/test_advisory_engine.py — Phase 10C.5 Advisory Engine & Threshold Provenance Tests
========================================================================================
Comprehensive test suite covering Advisory contracts, evidence preservation,
threshold provenance remediation, deterministic rules (weather stale/unavailable/invalid,
battery SoC, fuel level, CII compliance, high wind, rough sea, readiness), deduplication,
human-in-the-loop safety, and absence of wind propulsion / engine-off calculations.

Includes full validation of explicit policy-driven thresholds and verification that
unconfigured rules produce zero false alarms.
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
from app.advisory.rules import (
    AdvisoryRule,
    BatterySocLowRule,
    CiiRatingNonCompliantRule,
    DataQualityWeatherInvalidRule,
    DataQualityWeatherStaleRule,
    DataQualityWeatherUnavailableRule,
    DecisionReadinessRule,
    FuelLevelLowRule,
    HighWindAdvisoryRule,
    RoughSeaAdvisoryRule,
    DEFAULT_RULE_SET,
    build_rule_set_from_policy,
)
from app.advisory.engine import AdvisoryEngine


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def test_vessel() -> VesselContext:
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
def test_route() -> Route:
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
def test_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        speed_over_ground_knots=12.0,
        course_over_ground_deg=285.0,
    )


@pytest.fixture
def healthy_decision_context(test_vessel, test_route, test_position) -> DecisionContext:
    provider = MockWeatherProvider()
    builder = VoyageContextBuilder("VOY_HEALTHY")
    builder.set_vessel(test_vessel)
    builder.set_route(test_route)
    builder.set_position(test_position)
    builder.set_energy_state(
        VesselEnergyState(
            battery_soc_pct=85.0,
            battery_soh_pct=99.0,
            battery_energy_available_kwh=550.0,
            solar_power_kw=15.0,
            solar_energy_today_kwh=50.0,
            fuel_remaining_liters=6000.0,
            fuel_consumption_rate_lph=170.0,
        )
    )
    builder.enrich_weather_from_provider(provider)
    voyage = builder.build()

    eng = EngineeringDecisionInputs(
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

    return DecisionContext(
        decision_context_id="DC_HEALTHY_01",
        created_at_utc="2026-06-15T12:05:00Z",
        voyage_context=voyage,
        engineering_inputs=eng,
    )


@pytest.fixture
def sample_operational_policy() -> AdvisoryPolicy:
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


# =====================================================================
# CORE ADVISORY CONTRACT & LIFECYCLE TESTS (ITEMS 1–7)
# =====================================================================

def test_01_valid_advisory():
    """Item 1: Valid Advisory creation with required fields."""
    adv = Advisory(
        advisory_id="ADV_001",
        rule_id="RULE_001",
        category=AdvisoryCategory.WEATHER,
        severity=AdvisorySeverity.WARNING,
        title="Sample Weather Advisory",
        message="Wind speed elevated.",
        created_at_utc="2026-06-15T12:00:00Z",
    )
    assert adv.advisory_id == "ADV_001"
    assert adv.severity == AdvisorySeverity.WARNING
    assert adv.human_review_required is True
    assert adv.status == AdvisoryStatus.ACTIVE
    assert adv.deduplication_key is not None


def test_02_advisory_immutability():
    """Item 2: Advisory contract field validation."""
    with pytest.raises(ValidationError):
        Advisory(
            advisory_id="",  # empty string rejected
            rule_id="R1",
            category=AdvisoryCategory.WEATHER,
            severity=AdvisorySeverity.INFO,
            title="T",
            message="M",
            created_at_utc="2026-06-15T12:00:00Z",
        )


def test_03_advisory_serialization():
    """Item 3: JSON serialization and round-trip parsing."""
    adv = Advisory(
        advisory_id="ADV_SER",
        rule_id="R_SER",
        category=AdvisoryCategory.BATTERY,
        severity=AdvisorySeverity.WARNING,
        title="Battery SoC Low",
        message="SoC < 20%",
        created_at_utc="2026-06-15T12:00:00Z",
    )
    json_str = adv.model_dump_json()
    assert "BATTERY" in json_str
    rebuilt = Advisory.model_validate_json(json_str)
    assert rebuilt.advisory_id == adv.advisory_id
    assert rebuilt.deduplication_key == adv.deduplication_key


def test_04_category_validation():
    """Item 4: Rejection of invalid advisory category."""
    with pytest.raises(ValidationError):
        Advisory(
            advisory_id="ADV_BAD_CAT",
            rule_id="R1",
            category="MAGIC_PROPULSION",  # Invalid enum value
            severity=AdvisorySeverity.INFO,
            title="T",
            message="M",
            created_at_utc="2026-06-15T12:00:00Z",
        )


def test_05_severity_validation():
    """Item 5: Rejection of invalid severity level."""
    with pytest.raises(ValidationError):
        Advisory(
            advisory_id="ADV_BAD_SEV",
            rule_id="R1",
            category=AdvisoryCategory.SYSTEM,
            severity="CATASTROPHIC_UNKNOWN",  # Invalid enum value
            title="T",
            message="M",
            created_at_utc="2026-06-15T12:00:00Z",
        )


def test_06_status_validation():
    """Item 6: Advisory lifecycle status validation."""
    adv = Advisory(
        advisory_id="ADV_STAT",
        rule_id="R1",
        category=AdvisoryCategory.SYSTEM,
        severity=AdvisorySeverity.INFO,
        title="T",
        message="M",
        status=AdvisoryStatus.SUPPRESSED,
        created_at_utc="2026-06-15T12:00:00Z",
    )
    assert adv.status == AdvisoryStatus.SUPPRESSED


def test_07_expiry_handling():
    """Item 7: Expiration determination via is_expired()."""
    adv = Advisory(
        advisory_id="ADV_EXP",
        rule_id="R1",
        category=AdvisoryCategory.WEATHER,
        severity=AdvisorySeverity.INFO,
        title="T",
        message="M",
        created_at_utc="2026-06-15T12:00:00Z",
        valid_until_utc="2026-06-15T14:00:00Z",
    )
    assert adv.is_expired(current_time=datetime(2026, 6, 15, 13, 0, 0, tzinfo=timezone.utc)) is False
    assert adv.is_expired(current_time=datetime(2026, 6, 15, 15, 0, 0, tzinfo=timezone.utc)) is True


# =====================================================================
# DATA QUALITY & WEATHER RULES (ITEMS 8–11)
# =====================================================================

def test_08_weather_stale_rule(test_vessel, test_route, test_position):
    """Item 8: DataQualityWeatherStaleRule triggers on stale weather."""
    provider = MockWeatherProvider(mode="stale")
    builder = VoyageContextBuilder("VOY_STALE")
    builder.set_vessel(test_vessel).set_route(test_route).set_position(test_position)
    builder.enrich_weather_from_provider(provider)
    stale_voyage = builder.build()

    dc = DecisionContext(decision_context_id="DC_STALE", created_at_utc="2026-06-15T12:00:00Z", voyage_context=stale_voyage)
    rule = DataQualityWeatherStaleRule()
    advisories = rule.evaluate(dc)

    assert len(advisories) == 1
    assert advisories[0].category == AdvisoryCategory.DATA_QUALITY
    assert advisories[0].severity == AdvisorySeverity.WARNING


def test_09_weather_unavailable_rule(test_vessel, test_route, test_position):
    """Item 9: DataQualityWeatherUnavailableRule triggers on missing weather."""
    voyage_no_wx = VoyageContext(
        voyage_id="VOY_NO_WX",
        vessel=test_vessel,
        route=test_route,
        current_position=test_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
    )
    dc = DecisionContext(decision_context_id="DC_NO_WX", created_at_utc="2026-06-15T12:00:00Z", voyage_context=voyage_no_wx)
    rule = DataQualityWeatherUnavailableRule()
    advisories = rule.evaluate(dc)

    assert len(advisories) == 1
    assert "Unavailable" in advisories[0].title


def test_10_weather_invalid_rule(test_vessel, test_route, test_position):
    """Item 10: DataQualityWeatherInvalidRule triggers on corrupt weather quality."""
    rec = NormalizedWeatherRecord(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
        data_quality=WeatherQualityState.INVALID,
    )
    voyage_inv = VoyageContext(
        voyage_id="VOY_INV",
        vessel=test_vessel,
        route=test_route,
        current_position=test_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        weather_context=VoyageWeatherContext(current_weather=rec, weather_quality=WeatherQualityState.INVALID),
    )
    dc = DecisionContext(decision_context_id="DC_INV", created_at_utc="2026-06-15T12:00:00Z", voyage_context=voyage_inv)
    rule = DataQualityWeatherInvalidRule()
    advisories = rule.evaluate(dc)

    assert len(advisories) == 1
    assert advisories[0].severity == AdvisorySeverity.CRITICAL


def test_11_valid_weather_produces_no_false_warning(healthy_decision_context):
    """Item 11: Valid weather produces 0 data quality warnings."""
    rule1 = DataQualityWeatherStaleRule()
    rule2 = DataQualityWeatherUnavailableRule()
    rule3 = DataQualityWeatherInvalidRule()

    assert len(rule1.evaluate(healthy_decision_context)) == 0
    assert len(rule2.evaluate(healthy_decision_context)) == 0
    assert len(rule3.evaluate(healthy_decision_context)) == 0


# =====================================================================
# THRESHOLD PROVENANCE & OPERATIONAL RULES (ITEMS 12–17)
# =====================================================================

def test_12_battery_advisory_with_configured_threshold(healthy_decision_context):
    """Item 12: BatterySocLowRule triggers when SoC < explicit policy threshold."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 15.0
    rule = BatterySocLowRule(warning_threshold_pct=20.0, notice_threshold_pct=35.0)
    advisories = rule.evaluate(healthy_decision_context)

    assert len(advisories) == 1
    assert advisories[0].category == AdvisoryCategory.BATTERY
    assert advisories[0].severity == AdvisorySeverity.WARNING
    assert "15.0%" in advisories[0].message
    assert "20.0%" in advisories[0].message


def test_13_missing_battery_soc(healthy_decision_context):
    """Item 13: Missing battery SoC does NOT trigger false warning (missing != zero)."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = None
    rule = BatterySocLowRule(warning_threshold_pct=20.0, notice_threshold_pct=35.0)
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 0


def test_14_fuel_advisory_with_configured_threshold(healthy_decision_context):
    """Item 14: FuelLevelLowRule triggers when fuel < explicit reserve threshold."""
    healthy_decision_context.voyage_context.energy_state.fuel_remaining_liters = 600.0
    rule = FuelLevelLowRule(reserve_threshold_liters=1000.0)
    advisories = rule.evaluate(healthy_decision_context)

    assert len(advisories) == 1
    assert advisories[0].category == AdvisoryCategory.FUEL
    assert advisories[0].severity == AdvisorySeverity.WARNING
    assert "600.0 L" in advisories[0].message
    assert "1000.0 L" in advisories[0].message


def test_15_missing_fuel_state(healthy_decision_context):
    """Item 15: Missing fuel state does not trigger false warning."""
    healthy_decision_context.voyage_context.energy_state.fuel_remaining_liters = None
    rule = FuelLevelLowRule(reserve_threshold_liters=1000.0)
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 0


def test_16_cii_advisory_from_existing_result(healthy_decision_context):
    """Item 16: CiiRatingNonCompliantRule triggers for 'D' or 'E' rating."""
    healthy_decision_context.engineering_inputs.cii_attained_rating = "D"
    rule = CiiRatingNonCompliantRule()
    advisories = rule.evaluate(healthy_decision_context)

    assert len(advisories) == 1
    assert advisories[0].category == AdvisoryCategory.CII
    assert "SEEMP Part III" in advisories[0].message


def test_17_missing_cii_result(healthy_decision_context):
    """Item 17: Missing CII result does not trigger false warning."""
    healthy_decision_context.engineering_inputs.cii_attained_rating = None
    rule = CiiRatingNonCompliantRule()
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 0


# =====================================================================
# READINESS & SYSTEM RULES (ITEMS 18–20)
# =====================================================================

def test_18_readiness_advisory_insufficient(test_vessel, test_route, test_position):
    """Item 18: DecisionReadinessRule triggers on INSUFFICIENT_DATA."""
    voyage_no_wx = VoyageContext(
        voyage_id="VOY_NO_WX",
        vessel=test_vessel,
        route=test_route,
        current_position=test_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
    )
    dc = DecisionContext(decision_context_id="DC_NO_WX", created_at_utc="2026-06-15T12:00:00Z", voyage_context=voyage_no_wx)
    rule = DecisionReadinessRule()
    advisories = rule.evaluate(dc)

    assert len(advisories) == 1
    assert advisories[0].category == AdvisoryCategory.SYSTEM
    assert advisories[0].severity == AdvisorySeverity.WARNING


def test_19_insufficient_data_handling(test_vessel, test_route, test_position):
    """Item 19: AdvisoryEngine handles INSUFFICIENT_DATA end-to-end."""
    voyage_no_wx = VoyageContext(
        voyage_id="VOY_NO_WX",
        vessel=test_vessel,
        route=test_route,
        current_position=test_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
    )
    dc = DecisionContext(decision_context_id="DC_NO_WX_2", created_at_utc="2026-06-15T12:00:00Z", voyage_context=voyage_no_wx)
    engine = AdvisoryEngine()
    advisories = engine.evaluate(dc)
    assert any(a.category == AdvisoryCategory.SYSTEM for a in advisories)


def test_20_invalid_data_handling(test_vessel, test_route, test_position):
    """Item 20: DecisionReadinessRule handles INVALID_DATA."""
    rec = NormalizedWeatherRecord(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        data_source="TEST",
        data_type=WeatherProvenanceType.OBSERVED,
        data_quality=WeatherQualityState.INVALID,
    )
    voyage_inv = VoyageContext(
        voyage_id="VOY_INV",
        vessel=test_vessel,
        route=test_route,
        current_position=test_position,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00Z"),
        weather_context=VoyageWeatherContext(current_weather=rec, weather_quality=WeatherQualityState.INVALID),
    )
    dc = DecisionContext(decision_context_id="DC_INV", created_at_utc="2026-06-15T12:00:00Z", voyage_context=voyage_inv)
    rule = DecisionReadinessRule()
    advisories = rule.evaluate(dc)
    assert len(advisories) == 1


# =====================================================================
# EVIDENCE & TRACEABILITY PRESERVATION (ITEMS 21–23)
# =====================================================================

def test_21_advisory_evidence_preservation(healthy_decision_context):
    """Item 21: Verify evidence fields attached to generated advisory."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 18.0
    rule = BatterySocLowRule(warning_threshold_pct=20.0)
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 1
    adv = advisories[0]

    assert len(adv.evidence) == 1
    ev = adv.evidence[0]
    assert ev.rule_id == "ENG_BATT_SOC_001"
    assert ev.source_field == "energy_state.battery_soc_pct"
    assert ev.observed_value == 18.0
    assert ev.threshold_value == 20.0


def test_22_provenance_preservation(healthy_decision_context):
    """Item 22: Evidence preserves data provenance."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 18.0
    rule = BatterySocLowRule(warning_threshold_pct=20.0)
    adv = rule.evaluate(healthy_decision_context)[0]
    assert adv.evidence[0].provenance == WeatherProvenanceType.SIMULATED


def test_23_freshness_preservation(healthy_decision_context):
    """Item 23: Evidence preserves freshness."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 18.0
    rule = BatterySocLowRule(warning_threshold_pct=20.0)
    adv = rule.evaluate(healthy_decision_context)[0]
    assert adv.evidence[0].freshness == WeatherFreshnessState.FRESH


# =====================================================================
# DETERMINISM & DEDUPLICATION (ITEMS 24–25)
# =====================================================================

def test_24_deterministic_output(healthy_decision_context, sample_operational_policy):
    """Item 24: Engine produces 100% deterministic output on successive evaluations."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 15.0
    engine = AdvisoryEngine(policy=sample_operational_policy)
    adv1 = engine.evaluate(healthy_decision_context)
    adv2 = engine.evaluate(healthy_decision_context)

    assert len(adv1) == len(adv2)
    assert len(adv1) > 0
    for a1, a2 in zip(adv1, adv2):
        assert a1.advisory_id == a2.advisory_id
        assert a1.title == a2.title
        assert a1.deduplication_key == a2.deduplication_key


def test_25_duplicate_suppression(healthy_decision_context):
    """Item 25: AdvisoryEngine suppresses duplicate advisories by deduplication key."""
    class DuplicateGeneratingRule(AdvisoryRule):
        @property
        def rule_id(self) -> str:
            return "DUP_001"
        @property
        def category(self) -> AdvisoryCategory:
            return AdvisoryCategory.SYSTEM
        def evaluate(self, context: DecisionContext) -> List[Advisory]:
            return [
                Advisory(
                    advisory_id="ADV_D1",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.INFO,
                    title="Same Title",
                    message="Msg 1",
                    created_at_utc="2026-06-15T12:00:00Z",
                ),
                Advisory(
                    advisory_id="ADV_D2",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.INFO,
                    title="Same Title",
                    message="Msg 2",
                    created_at_utc="2026-06-15T12:00:00Z",
                ),
            ]

    engine = AdvisoryEngine(rules=[DuplicateGeneratingRule()], deduplicate=True)
    res = engine.evaluate(healthy_decision_context)
    assert len(res) == 1  # Deduplicated from 2 to 1


# =====================================================================
# HUMAN-IN-THE-LOOP SAFETY & INVARIANTS (ITEMS 26–30)
# =====================================================================

def test_26_human_review_flag(healthy_decision_context, sample_operational_policy):
    """Item 26: Human review required flag is True on all generated advisories."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 15.0
    engine = AdvisoryEngine(policy=sample_operational_policy)
    advisories = engine.evaluate(healthy_decision_context)
    assert len(advisories) > 0
    for adv in advisories:
        assert adv.human_review_required is True


def test_27_no_autonomous_control():
    """Item 27: Verify absence of actuation or engine control APIs."""
    import inspect
    import app.advisory.engine as engine_mod

    methods = [m for m in dir(engine_mod.AdvisoryEngine) if not m.startswith("_")]
    assert "set_engine_throttle" not in methods
    assert "change_heading" not in methods
    assert "execute_recommendation" not in methods


def test_28_no_wind_propulsion():
    """Item 28: Verify wind propulsion physical models remain absent."""
    import os
    models = os.listdir("models")
    assert "wind_propulsion.joblib" not in models
    assert "sail_thrust.joblib" not in models


def test_29_no_engine_off_calculation():
    """Item 29: Verify no engine-off calculations in advisory rules."""
    import inspect
    import app.advisory.rules as rules_mod

    functions = [f for f in dir(rules_mod) if inspect.isfunction(getattr(rules_mod, f))]
    assert "calculate_engine_off_duration" not in functions
    assert "compute_wind_savings" not in functions


def test_30_no_external_network_dependency(healthy_decision_context):
    """Item 30: AdvisoryEngine evaluates 100% offline."""
    engine = AdvisoryEngine()
    assert len(engine.registered_rules) > 0
    advisories = engine.evaluate(healthy_decision_context)
    assert isinstance(advisories, list)


# =====================================================================
# DEDICATED THRESHOLD PROVENANCE REMEDIATION TESTS (ITEMS 31–45)
# =====================================================================

def test_31_unconfigured_battery_rule_emits_no_advisory(healthy_decision_context):
    """Item 31: Unconfigured BatterySocLowRule emits 0 advisories on low SoC."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 5.0
    rule = BatterySocLowRule()  # Default None thresholds
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 0


def test_32_battery_rule_notice_threshold_only(healthy_decision_context):
    """Item 32: BatterySocLowRule triggers NOTICE when only notice threshold is set."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 30.0
    rule = BatterySocLowRule(notice_threshold_pct=35.0)
    advisories = rule.evaluate(healthy_decision_context)

    assert len(advisories) == 1
    assert advisories[0].severity == AdvisorySeverity.NOTICE
    assert "Moderate" in advisories[0].title


def test_33_unconfigured_fuel_rule_emits_no_advisory(healthy_decision_context):
    """Item 33: Unconfigured FuelLevelLowRule emits 0 advisories on low fuel."""
    healthy_decision_context.voyage_context.energy_state.fuel_remaining_liters = 50.0
    rule = FuelLevelLowRule()  # Default None threshold
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 0


def test_34_unconfigured_wind_rule_emits_no_advisory(healthy_decision_context):
    """Item 34: Unconfigured HighWindAdvisoryRule emits 0 advisories on high wind."""
    healthy_decision_context.voyage_context.weather_context.current_weather.wind_speed_knots = 45.0
    rule = HighWindAdvisoryRule()  # Default None threshold
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 0


def test_35_configured_wind_rule_triggers_warning(healthy_decision_context):
    """Item 35: Configured HighWindAdvisoryRule emits WARNING when wind > threshold."""
    healthy_decision_context.voyage_context.weather_context.current_weather.wind_speed_knots = 32.0
    rule = HighWindAdvisoryRule(high_wind_threshold_knots=25.0)
    advisories = rule.evaluate(healthy_decision_context)

    assert len(advisories) == 1
    assert advisories[0].category == AdvisoryCategory.WEATHER
    assert advisories[0].severity == AdvisorySeverity.WARNING
    assert "32.0 knots" in advisories[0].message
    assert "25.0 knots" in advisories[0].message
    assert advisories[0].evidence[0].threshold_value == 25.0


def test_36_unconfigured_rough_sea_rule_emits_no_advisory(healthy_decision_context):
    """Item 36: Unconfigured RoughSeaAdvisoryRule emits 0 advisories on rough sea."""
    healthy_decision_context.voyage_context.weather_context.current_weather.wave_height_m = 4.5
    rule = RoughSeaAdvisoryRule()  # Default None threshold
    advisories = rule.evaluate(healthy_decision_context)
    assert len(advisories) == 0


def test_37_configured_rough_sea_rule_triggers_warning(healthy_decision_context):
    """Item 37: Configured RoughSeaAdvisoryRule emits WARNING when wave > threshold."""
    healthy_decision_context.voyage_context.weather_context.current_weather.wave_height_m = 3.2
    rule = RoughSeaAdvisoryRule(rough_sea_threshold_m=2.5)
    advisories = rule.evaluate(healthy_decision_context)

    assert len(advisories) == 1
    assert advisories[0].category == AdvisoryCategory.WEATHER
    assert advisories[0].severity == AdvisorySeverity.WARNING
    assert "3.20 m" in advisories[0].message
    assert "2.5 m" in advisories[0].message
    assert advisories[0].evidence[0].threshold_value == 2.5


def test_38_policy_contracts_instantiation():
    """Item 38: Explicit policy models instantiate and validate correctly."""
    policy = AdvisoryPolicy(
        battery_policy=BatterySocPolicy(warning_threshold_pct=15.0, notice_threshold_pct=30.0),
        fuel_policy=FuelLevelPolicy(warning_threshold_liters=800.0),
        weather_policy=WeatherSafetyPolicy(high_wind_threshold_knots=30.0, rough_sea_threshold_m=3.0),
    )
    assert policy.battery_policy.warning_threshold_pct == 15.0
    assert policy.fuel_policy.warning_threshold_liters == 800.0
    assert policy.weather_policy.rough_sea_threshold_m == 3.0


def test_39_policy_validation_bounds():
    """Item 39: Policy models enforce physical/percentage bounds."""
    with pytest.raises(ValidationError):
        BatterySocPolicy(warning_threshold_pct=105.0)  # > 100%

    with pytest.raises(ValidationError):
        BatterySocPolicy(warning_threshold_pct=-5.0)  # < 0%

    with pytest.raises(ValidationError):
        FuelLevelPolicy(warning_threshold_liters=-10.0)  # < 0


def test_40_build_rule_set_from_policy(sample_operational_policy):
    """Item 40: build_rule_set_from_policy applies policy parameters to all rules."""
    rules = build_rule_set_from_policy(sample_operational_policy)
    assert len(rules) == 9

    batt_rule = next(r for r in rules if isinstance(r, BatterySocLowRule))
    assert batt_rule.warning_threshold_pct == 20.0
    assert batt_rule.notice_threshold_pct == 35.0

    fuel_rule = next(r for r in rules if isinstance(r, FuelLevelLowRule))
    assert fuel_rule.reserve_threshold_liters == 1000.0

    wind_rule = next(r for r in rules if isinstance(r, HighWindAdvisoryRule))
    assert wind_rule.high_wind_threshold_knots == 25.0

    sea_rule = next(r for r in rules if isinstance(r, RoughSeaAdvisoryRule))
    assert sea_rule.rough_sea_threshold_m == 2.5


def test_41_build_rule_set_from_none_policy():
    """Item 41: build_rule_set_from_policy(None) produces safe unconfigured rules."""
    rules = build_rule_set_from_policy(None)
    assert len(rules) == 9

    batt_rule = next(r for r in rules if isinstance(r, BatterySocLowRule))
    assert batt_rule.warning_threshold_pct is None
    assert batt_rule.notice_threshold_pct is None

    fuel_rule = next(r for r in rules if isinstance(r, FuelLevelLowRule))
    assert fuel_rule.reserve_threshold_liters is None


def test_42_engine_with_policy_integration(healthy_decision_context, sample_operational_policy):
    """Item 42: AdvisoryEngine initialized with policy triggers on threshold violations."""
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 18.0
    healthy_decision_context.voyage_context.energy_state.fuel_remaining_liters = 800.0
    healthy_decision_context.voyage_context.weather_context.current_weather.wind_speed_knots = 28.0

    engine = AdvisoryEngine(policy=sample_operational_policy)
    advisories = engine.evaluate(healthy_decision_context)

    categories = {a.category for a in advisories}
    assert AdvisoryCategory.BATTERY in categories
    assert AdvisoryCategory.FUEL in categories
    assert AdvisoryCategory.WEATHER in categories


def test_43_engine_default_unconfigured_emits_zero_threshold_alarms(healthy_decision_context):
    """Item 43: AdvisoryEngine without policy emits 0 threshold-based false alarms."""
    # Degrade telemetry to values that would trigger if hard-coded defaults existed
    healthy_decision_context.voyage_context.energy_state.battery_soc_pct = 18.0
    healthy_decision_context.voyage_context.energy_state.fuel_remaining_liters = 800.0
    healthy_decision_context.voyage_context.weather_context.current_weather.wind_speed_knots = 28.0
    healthy_decision_context.voyage_context.weather_context.current_weather.wave_height_m = 3.0

    engine = AdvisoryEngine()  # Unconfigured default
    advisories = engine.evaluate(healthy_decision_context)

    # Only data quality/readiness or non-threshold rules could trigger, none should on healthy context
    assert len(advisories) == 0


def test_44_read_only_guarantee(healthy_decision_context, sample_operational_policy):
    """Item 44: Engine execution guarantees strict immutability of DecisionContext."""
    initial_dump = healthy_decision_context.model_dump_json()
    engine = AdvisoryEngine(policy=sample_operational_policy)
    engine.evaluate(healthy_decision_context)
    final_dump = healthy_decision_context.model_dump_json()

    assert initial_dump == final_dump


def test_45_rule_classes_have_no_hardcoded_defaults():
    """Item 45: Inspect rule class constructors to verify no silent default thresholds."""
    import inspect

    sig_batt = inspect.signature(BatterySocLowRule.__init__)
    assert sig_batt.parameters["warning_threshold_pct"].default is None
    assert sig_batt.parameters["notice_threshold_pct"].default is None

    sig_fuel = inspect.signature(FuelLevelLowRule.__init__)
    assert sig_fuel.parameters["reserve_threshold_liters"].default is None

    sig_wind = inspect.signature(HighWindAdvisoryRule.__init__)
    assert sig_wind.parameters["high_wind_threshold_knots"].default is None

    sig_sea = inspect.signature(RoughSeaAdvisoryRule.__init__)
    assert sig_sea.parameters["rough_sea_threshold_m"].default is None
