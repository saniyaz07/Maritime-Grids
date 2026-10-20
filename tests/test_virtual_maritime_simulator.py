"""
tests/test_virtual_maritime_simulator.py — Unit & Integration Tests for Native Virtual Maritime Simulator
========================================================================================================
Validates:
  1. VirtualVesselSimulator lifecycle (START, PAUSE, RESET, STEP)
  2. Dead reckoning kinematics and ocean current drift vector math
  3. Propulsion speed and throttle power scaling (Admiralty cubic speed scaling)
  4. Environmental weather coupling (Wave and wind resistance elevate shaft power & fuel burn)
  5. Continuous fuel consumption integration (monotonically decreasing fuel remaining)
  6. Battery SOC & usable energy bookkeeping with solar power contribution
  7. Signal Agent decision support alerts (NORMAL, WEATHER_ALERT, FUEL_ALERT, BATTERY_ALERT)
  8. Mandatory "HUMAN REVIEW REQUIRED" on all advisories
  9. FastAPI REST endpoints (/api/v1/operator/simulator/*)
  10. Strict safety boundaries (Zero external actuator commands, no port 10111)
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.telemetry.simulator import (
    VirtualVesselSimulator,
    SimulationStatus,
    OceanConditions,
    SimulatorControlRequest,
)


@pytest.fixture
def sim():
    """Returns a fresh VirtualVesselSimulator instance."""
    s = VirtualVesselSimulator(vessel_id="VESSEL_OSV_01")
    s.reset()
    return s


@pytest.fixture
def client():
    """FastAPI Test Client."""
    return TestClient(app)


def test_simulator_lifecycle_and_reset(sim):
    """Test start, pause, step, and reset restore initial Escravos origin state."""
    assert sim.status == SimulationStatus.IDLE
    assert sim.latitude == 5.58
    assert sim.longitude == 5.18
    assert sim.fuel_remaining_liters == 25000.0
    assert sim.battery_soc_pct == 85.0

    # Start
    sim.start()
    assert sim.status == SimulationStatus.RUNNING

    # Step 5 seconds
    st = sim.step(dt_seconds=5.0)
    assert st.status == SimulationStatus.RUNNING
    assert st.voyage_elapsed_seconds == 5
    assert st.latitude != 5.58 or st.longitude != 5.18  # Position advanced

    # Pause
    sim.pause()
    assert sim.status == SimulationStatus.PAUSED

    # Step while paused shouldn't advance position
    st2 = sim.step(dt_seconds=5.0)
    assert st2.voyage_elapsed_seconds == 5

    # Reset
    st_reset = sim.reset()
    assert st_reset.status == SimulationStatus.IDLE
    assert st_reset.latitude == 5.58
    assert st_reset.longitude == 5.18
    assert st_reset.fuel_remaining_liters == 25000.0
    assert st_reset.battery_soc_pct == 85.0
    assert st_reset.voyage_elapsed_seconds == 0


def test_dead_reckoning_and_current_drift(sim):
    """Verify dead reckoning kinematics and ocean current vector addition."""
    sim.start()
    # Heading 285° (West-Northwest), STW 12 kn, Current 1.0 kn at 105° (opposing)
    sim.update_controls(
        SimulatorControlRequest(
            target_speed_knots=12.0,
            heading_deg=285.0,
            current_speed_knots=1.0,
            current_direction_deg=105.0,
        )
    )

    st = sim.step(dt_seconds=60.0)
    # Opposing current should reduce SOG below STW
    assert st.speed_through_water_knots == 12.0
    assert st.speed_over_ground_knots < 12.0  # Approx 11.0 kn
    assert st.speed_over_ground_knots > 10.5


def test_speed_and_throttle_coupling(sim):
    """Verify throttle and target speed increase shaft power and fuel burn rate."""
    sim.start()

    # 1. Low speed (8 knots)
    sim.update_controls(SimulatorControlRequest(target_speed_knots=8.0))
    st_slow = sim.step(dt_seconds=1.0)

    # 2. High speed (13 knots)
    sim.update_controls(SimulatorControlRequest(target_speed_knots=13.0))
    st_fast = sim.step(dt_seconds=1.0)

    assert st_fast.shaft_power_kw > st_slow.shaft_power_kw
    assert st_fast.fuel_consumption_rate_lph > st_slow.fuel_consumption_rate_lph


def test_wave_and_wind_resistance_coupling(sim):
    """Verify rough sea (wave & wind resistance) increases power and fuel burn rate."""
    sim.start()

    # Calm Sea
    sim.update_controls(
        SimulatorControlRequest(
            target_speed_knots=12.0,
            wave_height_m=0.8,
            wind_speed_knots=8.0,
        )
    )
    st_calm = sim.step(dt_seconds=1.0)

    # Rough Sea
    sim.update_controls(
        SimulatorControlRequest(
            target_speed_knots=12.0,
            wave_height_m=3.5,
            wind_speed_knots=32.0,
        )
    )
    st_rough = sim.step(dt_seconds=1.0)

    # Rough sea must have significantly higher shaft power and fuel burn rate
    assert st_rough.shaft_power_kw > st_calm.shaft_power_kw
    assert st_rough.fuel_consumption_rate_lph > st_calm.fuel_consumption_rate_lph


def test_fuel_consumption_monotonically_decreases(sim):
    """Verify fuel remaining decreases monotonically over time while running."""
    sim.start()
    sim.update_controls(SimulatorControlRequest(target_speed_knots=12.0))

    initial_fuel = sim.fuel_remaining_liters
    for _ in range(5):
        st = sim.step(dt_seconds=60.0)  # Step 1 minute each

    assert st.fuel_remaining_liters < initial_fuel
    consumed = initial_fuel - st.fuel_remaining_liters
    assert consumed > 0.0


def test_battery_soc_and_usable_energy(sim):
    """Verify battery SOC bookkeeping with auxiliary load."""
    sim.start()
    initial_soc = sim.battery_soc_pct

    # Step forward 10 minutes
    for _ in range(10):
        st = sim.step(dt_seconds=60.0)

    assert st.battery_soc_pct <= initial_soc
    assert st.battery_energy_kwh > 0.0


def test_signal_agent_weather_alert(sim):
    """Verify Signal Agent triggers WEATHER_ALERT on adverse sea state."""
    sim.start()
    # Calm sea -> NORMAL
    sim.update_controls(SimulatorControlRequest(wave_height_m=1.0, wind_speed_knots=10.0))
    st_calm = sim.step(dt_seconds=1.0)
    assert st_calm.signal_agent.status == "NORMAL"
    assert st_calm.signal_agent.human_review_required is True

    # Rough sea (Hs = 3.0m) -> WEATHER_ALERT
    sim.update_controls(SimulatorControlRequest(wave_height_m=3.0, wind_speed_knots=28.0))
    st_rough = sim.step(dt_seconds=1.0)
    assert st_rough.signal_agent.status == "WEATHER_ALERT"
    assert st_rough.signal_agent.severity == "WARNING"
    assert st_rough.signal_agent.human_review_required is True
    assert any("resistance" in d.lower() or "wave" in d.lower() or "sea" in d.lower() for d in st_rough.signal_agent.details)


def test_signal_agent_fuel_alert(sim):
    """Verify Signal Agent triggers FUEL_ALERT when bunker drops below reserve."""
    sim.start()
    sim.fuel_remaining_liters = 400.0  # Set below 500 L threshold
    st = sim.step(dt_seconds=1.0)

    assert st.signal_agent.status == "FUEL_ALERT"
    assert st.signal_agent.severity == "CRITICAL"
    assert st.signal_agent.human_review_required is True
    assert "reserve" in st.signal_agent.headline.lower() or "fuel" in st.signal_agent.headline.lower() or "bunker" in st.signal_agent.headline.lower()


def test_signal_agent_battery_alert(sim):
    """Verify Signal Agent triggers BATTERY_ALERT when SOC drops below 20%."""
    sim.start()
    sim.battery_soc_pct = 18.0
    st = sim.step(dt_seconds=1.0)

    assert st.signal_agent.status == "BATTERY_ALERT"
    assert st.signal_agent.severity == "NOTICE"
    assert st.signal_agent.human_review_required is True


def test_api_simulator_endpoints(client):
    """Verify FastAPI endpoints for simulator state, start, pause, reset, control, step."""
    # 1. State
    res = client.get("/api/v1/operator/simulator/state")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "latitude" in data
    assert "longitude" in data
    assert "signal_agent" in data
    assert data["signal_agent"]["human_review_required"] is True

    # 2. Start
    res_start = client.post("/api/v1/operator/simulator/start")
    assert res_start.status_code == 200
    assert res_start.json()["status"] == "RUNNING"

    # 3. Control
    res_ctrl = client.post(
        "/api/v1/operator/simulator/control",
        json={
            "target_speed_knots": 13.0,
            "heading_deg": 280.0,
            "wave_height_m": 2.2,
        },
    )
    assert res_ctrl.status_code == 200
    ctrl_data = res_ctrl.json()
    assert ctrl_data["target_speed_knots"] == 13.0
    assert ctrl_data["heading_deg"] == 280.0

    # 4. Step
    res_step = client.post("/api/v1/operator/simulator/step?dt_seconds=5.0")
    assert res_step.status_code == 200
    assert res_step.json()["voyage_elapsed_seconds"] > 0

    # 5. Pause
    res_pause = client.post("/api/v1/operator/simulator/pause")
    assert res_pause.status_code == 200
    assert res_pause.json()["status"] == "PAUSED"

    # 6. Reset
    res_reset = client.post("/api/v1/operator/simulator/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["status"] == "IDLE"
    assert res_reset.json()["latitude"] == 5.58
    assert res_reset.json()["longitude"] == 5.18


def test_safety_boundary_zero_actuators():
    """Verify simulator operates purely as decision-support with zero actuator paths."""
    sim = VirtualVesselSimulator()
    st = sim.reset()

    # Verify no external command strings or ports exist in simulator state
    assert not hasattr(sim, "send_actuator_command")
    assert not hasattr(sim, "bridge_command_tx_port")
    assert st.signal_agent.human_review_required is True
