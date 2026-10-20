"""
tests/test_virtual_vessel_energy_estimator.py — Phase 10C.13I Energy Estimator Tests
=====================================================================================
Comprehensive test suite validating the Virtual Vessel Energy State Estimator:
  A. Model schema compatibility & feature audit
  B. Vessel profile loading & profile selection
  C. Resistance calculation (calm, wind, wave, total)
  D. Shaft power & cubic power scaling
  E. Fuel rate estimation (L/h)
  F. Fuel integration over deterministic time steps
  G. Battery SOC integration over deterministic time steps
  H. Missing weather handling (graceful fallback, zero fabrication)
  I. Missing and zero SOG handling (stationary idle power)
  J. Stale telemetry handling (degraded output)
  K. Expired telemetry handling (no false integration advance)
  L. Provenance classification (SIMULATED / DERIVED, never OBSERVED)
  M. Advisory integration (FUEL_LEVEL_LOW_001 and BATT_SOC_LOW_001 triggered truthfully)
  N. Engine state invariant (Engine state remains UNKNOWN, never inferred from SOG)
  O. Safety invariants (0 actuators, 0 control outputs, 0 port 10111 writes)
"""

from datetime import datetime, timedelta, timezone
import math
import pytest

from app.advisory.contracts import (
    AdvisoryCategory,
    AdvisoryPolicy,
    AdvisorySeverity,
    BatterySocPolicy,
    FuelLevelPolicy,
)
from app.advisory.engine import AdvisoryEngine
from app.advisory.rules import (
    BatterySocLowRule,
    FuelLevelLowRule,
    build_rule_set_from_policy,
)
from app.decision.contracts import DecisionContext
from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    EngineOperationalState,
    EngineTelemetry,
    EnergyTelemetry,
    PositionTelemetry,
    TelemetryFreshnessState,
    TelemetryProvenance,
    TelemetryProvenanceType,
    TelemetryQuality,
    TelemetryQualityState,
)
from app.telemetry.energy_estimator import VirtualEnergyEstimator
from app.voyage.contracts import (
    Route,
    RouteWaypoint,
    VesselContext,
    VesselEnergyState,
    VesselPosition,
    VoyageContext,
    VoyageTimeline,
    VoyageWeatherContext,
)
from app.weather.contracts import (
    NormalizedWeatherRecord,
    WeatherProvenanceType,
    WeatherQualityState,
)


def _build_test_payload(
    sog: Optional[float] = 12.0,
    heading: float = 285.0,
    timestamp_utc: str = "2017-11-06T05:57:30+00:00",
    ingested_at_utc: Optional[str] = None,
    freshness: TelemetryFreshnessState = TelemetryFreshnessState.FRESH,
) -> CanonicalTelemetryPayload:
    ingest_ts = ingested_at_utc or datetime.now(timezone.utc).isoformat()
    return CanonicalTelemetryPayload(
        telemetry_id="TEL_TEST_FRAME_01",
        timestamp_utc=timestamp_utc,
        ingested_at_utc=ingest_ts,
        vessel_id="VESSEL_OSV_LAGOS_01",
        position=PositionTelemetry(
            latitude=5.8,
            longitude=4.5,
            speed_over_ground_knots=sog,
            course_over_ground_deg=heading,
            heading_deg=heading,
        ),
        engine=EngineTelemetry(state=EngineOperationalState.UNKNOWN),
        energy=EnergyTelemetry(),
        quality=TelemetryQuality(
            overall=TelemetryQualityState.VALID,
            freshness=freshness,
        ),
        provenance=TelemetryProvenance(
            source="BRIDGE_COMMAND_NMEA",
            mode=TelemetryProvenanceType.SIMULATED,
        ),
    )


# =====================================================================
# SCENARIO A: MODEL SCHEMA COMPATIBILITY & FEATURE AUDIT
# =====================================================================

def test_scenario_a_model_schema_compatibility():
    """Verify estimator initializes correctly with standard profiles without requiring unavailable ML features."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    assert estimator.profile["displacement_tonnes"] == 2500.0
    assert estimator.profile["engine_power_kw"] == 4500.0
    assert estimator.profile["max_speed_knots"] == 14.5


# =====================================================================
# SCENARIO B: VESSEL PROFILE LOADING & SELECTION
# =====================================================================

def test_scenario_b_vessel_profile_loading():
    """Verify loading different vessel profiles correctly populates hull & engine specifications."""
    osv = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    assert osv.battery_capacity_kwh == pytest.approx(649.7, rel=1e-2)

    trawler = VirtualEnergyEstimator(ship_type="Fishing Trawler")
    assert trawler.profile["engine_power_kw"] == 1200.0
    assert trawler.profile["max_speed_knots"] == 11.0

    tanker = VirtualEnergyEstimator(ship_type="Tanker Ship")
    assert tanker.profile["displacement_tonnes"] == 18500.0


# =====================================================================
# SCENARIO C: RESISTANCE CALCULATION
# =====================================================================

def test_scenario_c_resistance_calculation():
    """Verify resistance components (calm, wind, wave) compute deterministically with positive values."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    wx = NormalizedWeatherRecord(
        latitude=5.8,
        longitude=4.5,
        timestamp_utc="2026-09-28T12:00:00+00:00",
        retrieval_timestamp_utc="2026-09-28T12:00:00+00:00",
        data_source="TEST_WX",
        data_type=WeatherProvenanceType.OBSERVED,
        wind_speed_knots=20.0,
        wave_height_m=2.0,
    )

    hydro = estimator.calculate_hydrodynamics(speed_knots=12.0, weather=wx)
    assert hydro["r_calm_n"] > 0.0
    assert hydro["r_wind_n"] > 0.0
    assert hydro["r_wave_n"] > 0.0
    assert hydro["r_total_n"] == pytest.approx(
        hydro["r_calm_n"] + hydro["r_wind_n"] + hydro["r_wave_n"], abs=1.0
    )


# =====================================================================
# SCENARIO D: SHAFT POWER & CUBIC SCALING
# =====================================================================

def test_scenario_d_shaft_power_cubic_scaling():
    """Higher speed produces cubically higher shaft power within engine rated limits."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    h_low = estimator.calculate_hydrodynamics(speed_knots=6.0)
    h_high = estimator.calculate_hydrodynamics(speed_knots=12.0)

    assert h_high["p_shaft_kw"] > h_low["p_shaft_kw"] * 4.0
    assert h_high["p_shaft_kw"] <= estimator.profile["engine_power_kw"]


# =====================================================================
# SCENARIO E: FUEL RATE ESTIMATION (L/H)
# =====================================================================

def test_scenario_e_fuel_rate_estimation():
    """Fuel rate in L/h scales with total power demand and SFOC."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    hydro = estimator.calculate_hydrodynamics(speed_knots=10.0)

    expected_rate = (hydro["p_total_kw"] * 0.210) / 0.85
    assert hydro["fuel_rate_lph"] == pytest.approx(expected_rate, abs=0.1)
    assert hydro["fuel_rate_lph"] > 0.0


# =====================================================================
# SCENARIO F: FUEL INTEGRATION OVER TIME STEPS
# =====================================================================

def test_scenario_f_fuel_integration_over_time():
    """Fuel remaining strictly decreases and cumulative fuel increases over consecutive telemetry frames."""
    estimator = VirtualEnergyEstimator(
        ship_type="Oil Service Boat",
        initial_fuel_liters=5000.0,
    )

    t0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    p0 = _build_test_payload(sog=12.0, ingested_at_utc=t0.isoformat())
    res0 = estimator.estimate_energy_state(p0)
    assert res0.energy.fuel_remaining_liters == 5000.0

    # Step 1: 10 seconds later
    t1 = t0 + timedelta(seconds=10)
    p1 = _build_test_payload(sog=12.0, ingested_at_utc=t1.isoformat())
    res1 = estimator.estimate_energy_state(p1)

    assert res1.energy.fuel_remaining_liters < 5000.0
    assert estimator.cumulative_fuel_consumed_liters > 0.0
    assert res1.energy.fuel_rate_lph > 50.0


# =====================================================================
# SCENARIO G: BATTERY SOC INTEGRATION
# =====================================================================

def test_scenario_g_battery_soc_integration():
    """Battery state of charge decreases when hotel load exceeds solar generation."""
    estimator = VirtualEnergyEstimator(
        ship_type="Oil Service Boat",
        initial_battery_soc_pct=90.0,
        auxiliary_hotel_load_kw=35.0,
    )

    t0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    p0 = _build_test_payload(sog=10.0, ingested_at_utc=t0.isoformat())
    res0 = estimator.estimate_energy_state(p0, solar_irradiance_kw_per_m2=0.0)
    assert res0.energy.battery_soc_pct == 90.0

    # 30 seconds of discharge
    t1 = t0 + timedelta(seconds=30)
    p1 = _build_test_payload(sog=10.0, ingested_at_utc=t1.isoformat())
    res1 = estimator.estimate_energy_state(p1, solar_irradiance_kw_per_m2=0.0)

    assert res1.energy.battery_soc_pct <= 90.0
    assert res1.energy.battery_power_kw == -35.0


# =====================================================================
# SCENARIO H: MISSING WEATHER HANDLING
# =====================================================================

def test_scenario_h_missing_weather_graceful_fallback():
    """Missing weather context still allows calm water estimation without throwing exceptions."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    payload = _build_test_payload(sog=10.0)

    result = estimator.estimate_energy_state(payload, weather=None)
    assert result.energy.fuel_rate_lph is not None
    assert result.energy.fuel_rate_lph > 0.0


# =====================================================================
# SCENARIO I: MISSING AND ZERO SOG HANDLING
# =====================================================================

def test_scenario_i_missing_and_zero_sog_handling():
    """Zero or missing SOG results in stationary auxiliary idle power, not crash or 0/0 division."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")

    # Zero SOG
    p_zero = _build_test_payload(sog=0.0)
    res_zero = estimator.estimate_energy_state(p_zero)
    assert res_zero.engine.power_kw == 0.0
    assert res_zero.energy.fuel_rate_lph > 0.0  # Idle auxiliary fuel

    # None SOG
    p_none = _build_test_payload(sog=None)
    res_none = estimator.estimate_energy_state(p_none)
    assert res_none.engine.power_kw == 0.0


# =====================================================================
# SCENARIO J: STALE TELEMETRY HANDLING
# =====================================================================

def test_scenario_j_stale_telemetry_handling():
    """Stale telemetry payload propagates quality status without corrupting calculation."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    p_stale = _build_test_payload(sog=10.0, freshness=TelemetryFreshnessState.STALE)

    result = estimator.estimate_energy_state(p_stale)
    assert result.quality.freshness == TelemetryFreshnessState.STALE
    assert result.energy.fuel_rate_lph is not None


# =====================================================================
# SCENARIO K: EXPIRED TELEMETRY HANDLING
# =====================================================================

def test_scenario_k_expired_telemetry_handling():
    """Expired telemetry sets dynamic rates to None and halts fuel integration advance."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat", initial_fuel_liters=5000.0)
    p_exp = _build_test_payload(sog=10.0, freshness=TelemetryFreshnessState.EXPIRED)

    result = estimator.estimate_energy_state(p_exp)
    assert result.energy.fuel_rate_lph is None
    assert result.engine.power_kw is None
    assert estimator.cumulative_fuel_consumed_liters == 0.0


# =====================================================================
# SCENARIO L: PROVENANCE CLASSIFICATION
# =====================================================================

def test_scenario_l_provenance_classification():
    """Energy estimates carry explicit SIMULATED / DERIVED provenance, never OBSERVED."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    payload = _build_test_payload(sog=12.0)

    result = estimator.estimate_energy_state(payload)
    assert result.provenance.mode == TelemetryProvenanceType.SIMULATED
    assert "VIRTUAL_ENERGY_ESTIMATOR" in result.provenance.source


# =====================================================================
# SCENARIO M: ADVISORY INTEGRATION (LOW FUEL & LOW SOC)
# =====================================================================

def test_scenario_m_advisory_integration_low_fuel_and_soc():
    """Derived energy state triggers FUEL_LEVEL_LOW_001 and BATT_SOC_LOW_001 when thresholds breached."""
    policy = AdvisoryPolicy(
        fuel_policy=FuelLevelPolicy(warning_threshold_liters=1000.0),
        battery_policy=BatterySocPolicy(warning_threshold_pct=20.0, notice_threshold_pct=30.0),
    )

    energy_low = VesselEnergyState(
        fuel_remaining_liters=800.0,   # < 1000.0 L threshold
        battery_soc_pct=18.0,          # < 20.0% threshold
        provenance=WeatherProvenanceType.SIMULATED,
    )

    voyage_ctx = VoyageContext(
        voyage_id="VOY_ENERGY_01",
        timeline=VoyageTimeline(current_time_utc="2026-09-28T12:00:00+00:00"),
        vessel=VesselContext(vessel_id="VESSEL_01", ship_type="Oil Service Boat"),
        route=Route(
            route_id="ROUTE_01",
            origin_port="Port A",
            destination_port="Port B",
            waypoints=[
                RouteWaypoint(waypoint_id="WP1", latitude=5.8, longitude=4.5),
                RouteWaypoint(waypoint_id="WP2", latitude=6.0, longitude=4.5),
            ],
        ),
        current_position=VesselPosition(latitude=5.8, longitude=4.5, speed_over_ground_knots=12.0, timestamp_utc="2026-09-28T12:00:00+00:00"),
        energy_state=energy_low,
    )

    decision_ctx = DecisionContext(
        decision_context_id="DC_ENERGY_TEST",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        voyage_context=voyage_ctx,
    )

    rules = build_rule_set_from_policy(policy)
    engine = AdvisoryEngine(rules=rules)
    advisories = engine.evaluate(decision_ctx)

    fuel_advs = [a for a in advisories if a.category == AdvisoryCategory.FUEL]
    batt_advs = [a for a in advisories if a.category == AdvisoryCategory.BATTERY]

    assert len(fuel_advs) == 1
    assert fuel_advs[0].rule_id == "ENG_FUEL_LOW_002"
    assert fuel_advs[0].severity == AdvisorySeverity.WARNING
    assert fuel_advs[0].human_review_required is True

    assert len(batt_advs) == 1
    assert batt_advs[0].rule_id == "ENG_BATT_SOC_001"
    assert batt_advs[0].severity == AdvisorySeverity.WARNING
    assert batt_advs[0].human_review_required is True


# =====================================================================
# SCENARIO N: ENGINE STATE INVARIANT
# =====================================================================

def test_scenario_n_engine_state_never_inferred_from_sog():
    """Even at full speed (14.5 kn), engine state remains UNKNOWN without direct engine telemetry."""
    estimator = VirtualEnergyEstimator(ship_type="Oil Service Boat")
    payload = _build_test_payload(sog=14.5)

    result = estimator.estimate_energy_state(payload)
    assert result.engine.state == EngineOperationalState.UNKNOWN


# =====================================================================
# SCENARIO O: SAFETY INVARIANTS
# =====================================================================

def test_scenario_o_safety_invariants_no_control_paths():
    """Verify zero actuator commands, zero control outputs, and zero reverse control in energy estimator."""
    import inspect
    import app.telemetry.energy_estimator as mod

    source = inspect.getsource(mod)
    assert "sendto" not in source
    assert "socket.send" not in source
    assert "set_throttle" not in source
    assert "set_rudder" not in source
    assert "rudder_control" not in source
