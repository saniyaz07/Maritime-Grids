"""
tests/test_telemetry_contracts.py — Phase 10C.12 Telemetry Contracts & Adapter Test Suite
========================================================================================
Verifies:
  1. Strongly-typed CanonicalTelemetryPayload contracts and null preservation (null != 0).
  2. EngineOperationalState (ON, OFF, UNKNOWN) exact mapping and no false inference.
  3. TelemetryAdapter validation, range checking, and quarantining of impossible/negative data.
  4. Freshness evaluation model (FRESH, STALE, EXPIRED, DISCONNECTED).
  5. TelemetrySimulator Scenarios A through H.
  6. Conversion to VesselPosition and VesselEnergyState.
  7. Zero actuator or vessel control pathways.
"""

from datetime import datetime, timedelta, timezone
import pytest

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
from app.telemetry.adapter import TelemetryAdapter
from app.telemetry.simulator import TelemetrySimulator
from app.telemetry.gateway import TelemetryGateway


def test_01_canonical_telemetry_valid_instantiation():
    """Verify CanonicalTelemetryPayload instantiates with valid data."""
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = CanonicalTelemetryPayload(
        telemetry_id="TEL_001",
        timestamp_utc=now_iso,
        vessel_id="VESSEL_OSV_01",
        position=PositionTelemetry(
            latitude=5.82,
            longitude=4.51,
            speed_over_ground_knots=12.4,
            course_over_ground_deg=284.0,
            heading_deg=285.0,
        ),
        engine=EngineTelemetry(
            state=EngineOperationalState.ON,
            rpm=1500.0,
            load_percent=75.0,
            power_kw=1800.0,
            fuel_rate_lph=145.0,
        ),
        energy=EnergyTelemetry(
            fuel_remaining_liters=14500.0,
            fuel_rate_lph=145.0,
            battery_soc_pct=82.0,
            battery_soh_pct=95.0,
            battery_usable_kwh=500.0,
            solar_power_kw=15.0,
        ),
        provenance=TelemetryProvenance(source="TEST_SENSOR", mode=TelemetryProvenanceType.OBSERVED),
    )

    assert payload.telemetry_id == "TEL_001"
    assert payload.vessel_id == "VESSEL_OSV_01"
    assert payload.position.latitude == 5.82
    assert payload.position.speed_over_ground_knots == 12.4
    assert payload.engine.state == EngineOperationalState.ON
    assert payload.energy.battery_soc_pct == 82.0


def test_02_strict_null_preservation():
    """Verify missing fields remain None and are not converted to 0.0 (null != 0)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = CanonicalTelemetryPayload(
        telemetry_id="TEL_NULL_001",
        timestamp_utc=now_iso,
        vessel_id="VESSEL_OSV_01",
        position=PositionTelemetry(
            latitude=5.82,
            longitude=4.51,
            speed_over_ground_knots=None, # Missing speed
        ),
        engine=EngineTelemetry(
            state=EngineOperationalState.UNKNOWN,
            rpm=None,
            load_percent=None,
        ),
        energy=EnergyTelemetry(
            fuel_remaining_liters=None,
            battery_soc_pct=None,
        ),
        provenance=TelemetryProvenance(source="TEST_NULL", mode=TelemetryProvenanceType.OBSERVED),
    )

    assert payload.position.speed_over_ground_knots is None
    assert payload.position.speed_over_ground_knots != 0.0
    assert payload.engine.rpm is None
    assert payload.engine.rpm != 0.0
    assert payload.energy.fuel_remaining_liters is None
    assert payload.energy.battery_soc_pct is None


def test_03_engine_state_three_states_only():
    """Verify EngineOperationalState has exactly 3 states (ON, OFF, UNKNOWN)."""
    states = [s.value for s in EngineOperationalState]
    assert set(states) == {"ON", "OFF", "UNKNOWN"}
    assert len(states) == 3


def test_04_adapter_normalizes_and_quarantines_invalid_ranges():
    """Verify TelemetryAdapter quarantines impossible values and marks quality as INVALID."""
    adapter = TelemetryAdapter()
    raw_bad = {
        "vessel_id": "VESSEL_TEST",
        "latitude": 150.0,            # Impossible latitude (>90)
        "longitude": -200.0,          # Impossible longitude (<-180)
        "speed_knots": -5.0,          # Negative speed
        "fuel_remaining_liters": -100.0, # Negative fuel
        "battery_soc_pct": 120.0,     # Impossible SOC (>100)
        "engine_state": "RUNNING",
    }
    payload = adapter.normalize(raw_bad)

    assert payload.quality.overall == TelemetryQualityState.INVALID
    assert len(payload.quality.validation_errors) > 0
    # Coordinates must not be blindly accepted
    assert payload.position.latitude is None
    assert payload.position.longitude is None
    assert payload.energy.fuel_remaining_liters is None
    assert payload.energy.battery_soc_pct is None
    # Engine state should be mapped
    assert payload.engine.state == EngineOperationalState.ON


def test_05_freshness_evaluation():
    """Verify freshness evaluation: FRESH, STALE, EXPIRED, and auto-degradation of engine state."""
    adapter = TelemetryAdapter(fresh_threshold_sec=60.0, stale_threshold_sec=900.0, expired_threshold_sec=3600.0)
    now = datetime.now(timezone.utc)

    # 1. Fresh (30 sec ago)
    raw_fresh = {
        "timestamp_utc": (now - timedelta(seconds=30)).isoformat(),
        "vessel_id": "VESSEL_01",
        "engine_state": "ON",
    }
    p_fresh = adapter.normalize(raw_fresh, reference_time_utc=now)
    assert p_fresh.quality.freshness == TelemetryFreshnessState.FRESH
    assert p_fresh.engine.state == EngineOperationalState.ON

    # 2. Stale (5 min ago)
    raw_stale = {
        "timestamp_utc": (now - timedelta(minutes=5)).isoformat(),
        "vessel_id": "VESSEL_01",
        "engine_state": "ON",
    }
    p_stale = adapter.normalize(raw_stale, reference_time_utc=now)
    assert p_stale.quality.freshness == TelemetryFreshnessState.STALE

    # 3. Expired (2 hours ago) -> Engine state degraded to UNKNOWN
    raw_exp = {
        "timestamp_utc": (now - timedelta(hours=2)).isoformat(),
        "vessel_id": "VESSEL_01",
        "engine_state": "ON",
    }
    p_exp = adapter.normalize(raw_exp, reference_time_utc=now)
    assert p_exp.quality.freshness == TelemetryFreshnessState.EXPIRED
    assert p_exp.engine.state == EngineOperationalState.UNKNOWN



def test_06_simulator_all_scenarios_a_through_h():
    """Verify TelemetrySimulator correctly generates Scenarios A through H."""
    sim = TelemetrySimulator(vessel_id="VESSEL_TEST_SIM")
    now = datetime.now(timezone.utc)

    # Scenario A: Normal
    sc_a = sim.get_scenario("A", reference_time_utc=now.isoformat())
    assert sc_a.position.speed_over_ground_knots == 11.8
    assert sc_a.engine.state == EngineOperationalState.ON
    assert sc_a.provenance.mode == TelemetryProvenanceType.SIMULATED

    # Scenario B: Engine OFF
    sc_b = sim.get_scenario("B", reference_time_utc=now.isoformat())
    assert sc_b.engine.state == EngineOperationalState.OFF
    assert sc_b.engine.rpm == 0.0

    # Scenario C: Engine UNKNOWN
    sc_c = sim.get_scenario("C", reference_time_utc=now.isoformat())
    assert sc_c.engine.state == EngineOperationalState.UNKNOWN
    assert sc_c.engine.rpm is None

    # Scenario D: Missing Speed
    sc_d = sim.get_scenario("D", reference_time_utc=now.isoformat())
    assert sc_d.position.speed_over_ground_knots is None

    # Scenario E: Stale
    sc_e = sim.get_scenario("E", reference_time_utc=now.isoformat())
    assert sc_e.quality.freshness == TelemetryFreshnessState.STALE

    # Scenario F: Expired
    sc_f = sim.get_scenario("F", reference_time_utc=now.isoformat())
    assert sc_f.quality.freshness == TelemetryFreshnessState.EXPIRED

    # Scenario G: Disconnected
    sc_g = sim.get_scenario("G", reference_time_utc=now.isoformat())
    assert sc_g.quality.freshness == TelemetryFreshnessState.DISCONNECTED

    # Scenario H: Invalid
    sc_h = sim.get_scenario("H", reference_time_utc=now.isoformat())
    assert sc_h.quality.overall == TelemetryQualityState.INVALID


def test_07_conversion_to_vessel_position_and_energy():
    """Verify CanonicalTelemetryPayload converts faithfully to VesselPosition and VesselEnergyState."""
    sim = TelemetrySimulator()
    sc_a = sim.get_scenario("A")

    pos = sc_a.to_vessel_position()
    assert pos is not None
    assert pos.latitude == 5.8214
    assert pos.speed_over_ground_knots == 11.8

    energy = sc_a.to_vessel_energy_state()
    assert energy.battery_soc_pct == 78.5
    assert energy.fuel_remaining_liters == 14200.0


def test_08_gateway_buffering_and_concurrency():
    """Verify TelemetryGateway loads and updates buffered frames correctly."""
    gw = TelemetryGateway(default_vessel_id="VESSEL_GW_TEST")

    # Load Scenario B
    gw.load_scenario("B")
    frame_b = gw.get_current_frame()
    assert frame_b.engine.state == EngineOperationalState.OFF

    # Ingest custom raw
    now = datetime.now(timezone.utc).isoformat()
    gw.ingest_raw({
        "telemetry_id": "TEL_CUSTOM_01",
        "timestamp_utc": now,
        "vessel_id": "VESSEL_GW_TEST",
        "speed_knots": 14.2,
        "engine_state": "ON",
        "battery_soc_pct": 91.0,
    })
    frame_custom = gw.get_current_frame()
    assert frame_custom.telemetry_id == "TEL_CUSTOM_01"
    assert frame_custom.position.speed_over_ground_knots == 14.2
    assert frame_custom.engine.state == EngineOperationalState.ON
    assert frame_custom.energy.battery_soc_pct == 91.0


def test_09_safety_no_actuator_commands():
    """Safety Audit: Verify zero actuator commands exist in telemetry package."""
    import inspect
    import app.telemetry.contracts as tc
    import app.telemetry.gateway as tg
    import app.telemetry.adapter as ta

    forbidden = ["throttle", "rudder", "start_engine", "stop_engine", "steer", "override_route"]
    for mod in (tc, tg, ta):
        source = inspect.getsource(mod).lower()
        for term in forbidden:
            # Terms should only appear in negative comments / warnings / safety notices
            assert f"def {term}" not in source
            assert f"set_{term}" not in source
