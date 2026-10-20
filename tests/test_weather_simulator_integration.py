"""
tests/test_weather_simulator_integration.py
============================================
Comprehensive test suite verifying automatic weather integration into the Native Virtual Vessel Simulator:
  1. Mapping valid normalized weather records into simulator ocean conditions.
  2. Missing fields and invalid values handling (preserving last valid values).
  3. Automatic updates changing the active ocean state and kinematics/physics.
  4. Manual scenarios remaining in control until explicitly released.
  5. Weather-fetch failures preserving last valid data and exposing degraded status.
  6. Marine forecast parsing, timestamp alignment, and graceful handling.
  7. Route look-ahead wave heights populated when marine data is available.
  8. Safe concurrent updates while the simulation loop is running.
  9. Existing physics, fuel, battery, and navigation calculations.
  10. Safety boundaries: zero actuators and port 10111 prohibited.
"""

from datetime import datetime, timezone, timedelta
import threading
import time
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.dependencies import get_virtual_simulator, get_weather_provider
from app.telemetry.simulator import (
    OceanConditions,
    SimulatorControlRequest,
    SimulationStatus,
    VirtualVesselSimulator,
)
from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.mock_provider import MockWeatherProvider
from app.weather.open_meteo_provider import OpenMeteoWeatherProvider
from app.voyage.contracts import Route, VesselPosition
from app.voyage.lookahead import compute_route_weather_lookahead


def test_01_mapping_valid_weather_into_simulator():
    """Verify that a valid NormalizedWeatherRecord updates simulator ocean conditions accurately."""
    sim = VirtualVesselSimulator()
    now_iso = datetime.now(timezone.utc).isoformat()

    record = NormalizedWeatherRecord(
        latitude=5.58,
        longitude=5.18,
        timestamp_utc=now_iso,
        data_source="TEST_PROVIDER",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=22.4,
        wind_direction_deg=180.0,
        wave_height_m=2.1,
        wave_period_s=7.5,
        wave_direction_deg=190.0,
        ocean_current_speed_knots=1.2,
        ocean_current_direction_deg=90.0,
        temperature_c=29.0,
        relative_humidity_pct=85.0,
        surface_pressure_hpa=1010.5,
        precipitation_mm_per_hr=1.5,
    )

    success = sim.update_ocean_conditions(record)
    assert success is True

    oc = sim.state.ocean_conditions
    assert oc.wind_speed_knots == 22.4
    assert oc.wind_direction_deg == 180.0
    assert oc.wave_height_m == 2.1
    assert oc.wave_period_s == 7.5
    assert oc.wave_direction_deg == 190.0
    assert oc.current_speed_knots == 1.2
    assert oc.current_direction_deg == 90.0
    assert oc.air_temperature_c == 29.0
    assert oc.humidity_pct == 85.0
    assert oc.pressure_hpa == 1010.5
    assert oc.precipitation_mm == 1.5
    assert oc.weather_source == "TEST_PROVIDER"
    assert oc.source_timestamp_utc == now_iso
    assert oc.environmental_mode == "AUTOMATIC_FORECAST"


def test_02_missing_fields_and_invalid_values_preserve_last_valid():
    """Verify that None fields or physically out-of-bounds values do not corrupt existing ocean state."""
    sim = VirtualVesselSimulator()
    now_iso = datetime.now(timezone.utc).isoformat()

    # Seed with initial valid record
    initial_rec = NormalizedWeatherRecord(
        latitude=5.58,
        longitude=5.18,
        timestamp_utc=now_iso,
        data_source="TEST_PROVIDER",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=18.0,
        wave_height_m=1.8,
        ocean_current_speed_knots=0.9,
    )
    sim.update_ocean_conditions(initial_rec)
    assert sim.state.ocean_conditions.wave_height_m == 1.8
    assert sim.state.ocean_conditions.wind_speed_knots == 18.0

    # New record with missing wave height and out-of-bounds wind speed (> 100 kn)
    partial_rec = NormalizedWeatherRecord(
        latitude=5.58,
        longitude=5.18,
        timestamp_utc=now_iso,
        data_source="TEST_PROVIDER",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=150.0,  # Invalid: > 100.0 kn
        wave_height_m=None,      # Missing: should preserve 1.8m
        ocean_current_speed_knots=1.1,
    )
    sim.update_ocean_conditions(partial_rec)

    oc = sim.state.ocean_conditions
    assert oc.wave_height_m == 1.8           # Preserved!
    assert oc.wind_speed_knots == 18.0       # Preserved, not overwritten by 150.0!
    assert oc.current_speed_knots == 1.1     # Valid update applied


def test_03_automatic_updates_drive_vessel_physics():
    """Verify that updating ocean conditions dynamically recalculates SOG, COG, resistance, and fuel."""
    sim = VirtualVesselSimulator()
    sim.state.speed_through_water_knots = 12.0
    sim.state.heading_deg = 285.0
    sim._recalculate_physics()
    initial_sog = sim.state.speed_over_ground_knots
    initial_fuel = sim.state.fuel_consumption_rate_lph

    # Apply calm weather with following current (current direction 285 deg, 2.0 kn)
    calm_rec = NormalizedWeatherRecord(
        latitude=5.58,
        longitude=5.18,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        data_source="WEATHER_PROVIDER",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=5.0,
        wave_height_m=0.5,
        ocean_current_speed_knots=2.0,
        ocean_current_direction_deg=285.0,
    )
    sim.update_ocean_conditions(calm_rec)

    # Ground speed should increase from 12.0 STW + 2.0 current = ~14.0 kn
    assert sim.state.speed_over_ground_knots == pytest.approx(14.0, abs=0.2)
    calm_fuel = sim.state.fuel_consumption_rate_lph

    # Apply heavy rough weather (30 kn headwind, 3.5m waves)
    rough_rec = NormalizedWeatherRecord(
        latitude=5.58,
        longitude=5.18,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        data_source="WEATHER_PROVIDER",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=32.0,
        wave_height_m=3.5,
        ocean_current_speed_knots=0.5,
        ocean_current_direction_deg=105.0,
    )
    sim.update_ocean_conditions(rough_rec)

    # Shaft power and fuel burn rate must be significantly higher in rough seas than calm seas
    assert sim.state.fuel_consumption_rate_lph > calm_fuel
    assert sim.state.shaft_power_kw > 2000.0


def test_04_manual_scenarios_lock_and_persist_against_weather():
    """Verify that manual presets activate MANUAL_SCENARIO mode and block automatic updates."""
    sim = VirtualVesselSimulator()
    
    # Operator selects Rough Weather preset manually
    ctrl = SimulatorControlRequest(
        wave_height_m=3.2,
        wind_speed_knots=30.0,
        current_speed_knots=0.8,
        current_direction_deg=120.0,
    )
    sim.set_controls(ctrl)

    assert sim.state.ocean_conditions.environmental_mode == "MANUAL_SCENARIO"
    assert sim.state.ocean_conditions.wave_height_m == 3.2
    assert sim.state.ocean_conditions.wind_speed_knots == 30.0

    # Attempt automatic weather update while in MANUAL_SCENARIO
    auto_rec = NormalizedWeatherRecord(
        latitude=5.58,
        longitude=5.18,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        data_source="OPEN_METEO",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=10.0,
        wave_height_m=0.8,
        ocean_current_speed_knots=0.2,
    )
    updated = sim.update_ocean_conditions(auto_rec)
    assert updated is False  # Rejected!

    # Ocean state remains strictly at manual preset
    assert sim.state.ocean_conditions.wave_height_m == 3.2
    assert sim.state.ocean_conditions.wind_speed_knots == 30.0
    assert sim.state.ocean_conditions.environmental_mode == "MANUAL_SCENARIO"

    # Explicitly release manual scenario back to AUTOMATIC_FORECAST
    rel_ctrl = SimulatorControlRequest(environmental_mode="AUTOMATIC_FORECAST")
    sim.set_controls(rel_ctrl)
    assert sim.state.ocean_conditions.environmental_mode == "AUTOMATIC_FORECAST"

    # Now automatic update succeeds
    updated_again = sim.update_ocean_conditions(auto_rec)
    assert updated_again is True
    assert sim.state.ocean_conditions.wave_height_m == 0.8
    assert sim.state.ocean_conditions.wind_speed_knots == 10.0


def test_05_weather_fetch_failure_preserves_data_and_marks_degraded():
    """Verify that when weather provider fails, simulator preserves last valid data and marks degraded."""
    class FailingWeatherProvider:
        def get_current_weather(self, latitude, longitude):
            raise TimeoutError("Open-Meteo connection timed out")

    sim = VirtualVesselSimulator()
    sim.attach_weather_provider(FailingWeatherProvider())

    # Set valid initial conditions
    sim.state.ocean_conditions.wave_height_m = 1.6
    sim.state.ocean_conditions.wind_speed_knots = 14.0

    success = sim.fetch_and_update_weather(force=True)
    assert success is False
    # Preserves conditions
    assert sim.state.ocean_conditions.wave_height_m == 1.6
    assert sim.state.ocean_conditions.wind_speed_knots == 14.0
    # Marks freshness degraded
    assert sim.state.ocean_conditions.weather_freshness == "DEGRADED"


def test_06_open_meteo_forecast_marine_enrichment():
    """Verify that OpenMeteoWeatherProvider populates marine variables in get_forecast_weather."""
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=True)
    forecasts = provider.get_forecast_weather(latitude=5.58, longitude=5.18, horizon_hours=3)
    assert len(forecasts) >= 3

    # Check that at least one forecast has wave height populated from the marine API
    has_wave = any(f.wave_height_m is not None for f in forecasts)
    assert has_wave is True, "Forecast records should contain valid wave height when marine enrichment is enabled"

    first = forecasts[0]
    assert first.data_type == WeatherProvenanceType.FORECAST
    assert first.data_source == "OPEN_METEO"
    assert first.wind_speed_knots is not None


def test_07_route_lookahead_wave_heights_populated():
    """Verify that compute_route_weather_lookahead includes forecast wave heights in waypoints and summary."""
    provider = OpenMeteoWeatherProvider(enable_marine_enrichment=True)
    route = Route(
        route_id="Escravos-Lagos",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1", latitude=5.58, longitude=5.18, sequence=1),
            RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.50, sequence=2),
            RouteWaypoint(waypoint_id="WP3", latitude=6.42, longitude=3.42, sequence=3),
        ],
    )
    pos = VesselPosition(
        latitude=5.58,
        longitude=5.18,
        speed_over_ground_knots=12.0,
        course_over_ground_deg=285.0,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )

    lookahead = compute_route_weather_lookahead(
        position=pos,
        route=route,
        weather_provider=provider,
        vessel_id="VESSEL_OSV_01",
    )

    assert lookahead is not None
    assert len(lookahead.waypoints) == 3
    # Check that waypoint forecast has wave height
    wp2 = lookahead.waypoints[1]
    assert wp2.weather is not None
    assert wp2.weather.wave_height_m is not None
    assert wp2.weather.wave_height_m > 0.0

    # Check summary
    assert lookahead.summary.max_wave_height_m is not None
    assert lookahead.summary.max_wave_height_m > 0.0


def test_08_concurrent_weather_updates_and_simulation_step():
    """Verify thread safety: weather updates and simulation loop step concurrently without deadlock or data races."""
    sim = VirtualVesselSimulator()
    sim.start()

    errors = []

    def weather_worker():
        for i in range(20):
            try:
                rec = NormalizedWeatherRecord(
                    latitude=5.58 + i * 0.01,
                    longitude=5.18 + i * 0.01,
                    timestamp_utc=datetime.now(timezone.utc).isoformat(),
                    data_source="CONCURRENT_TEST",
                    data_type=WeatherProvenanceType.FORECAST,
                    wind_speed_knots=10.0 + (i % 15),
                    wave_height_m=1.0 + (i % 3) * 0.5,
                    ocean_current_speed_knots=0.5,
                )
                sim.update_ocean_conditions(rec)
                time.sleep(0.01)
            except Exception as e:
                errors.append(e)

    def control_worker():
        for i in range(20):
            try:
                ctrl = SimulatorControlRequest(target_speed_knots=10.0 + (i % 4))
                sim.set_controls(ctrl)
                time.sleep(0.01)
            except Exception as e:
                errors.append(e)

    t1 = threading.Thread(target=weather_worker)
    t2 = threading.Thread(target=control_worker)
    t1.start()
    t2.start()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)

    sim.pause()
    assert len(errors) == 0, f"Concurrent execution produced errors: {errors}"
    assert sim.state.distance_travelled_nm >= 0.0


def test_09_fastapi_endpoints_weather_integration():
    """Verify that operator FastAPI endpoints expose the refreshed simulator weather and controls."""
    app = create_app()
    with TestClient(app) as client:
        # 1. State check
        r_state = client.get("/api/v1/operator/simulator/state")
        assert r_state.status_code == 200
        data = r_state.json()
        assert "ocean_conditions" in data
        assert "environmental_mode" in data["ocean_conditions"]
        assert data["ocean_conditions"]["environmental_mode"] in ("AUTOMATIC_FORECAST", "MANUAL_SCENARIO")

        # 2. Control with manual scenario
        ctrl_payload = {
            "wave_height_m": 2.8,
            "wind_speed_knots": 26.0,
            "current_speed_knots": 0.9,
            "current_direction_deg": 110.0,
        }
        r_ctrl = client.post("/api/v1/operator/simulator/control", json=ctrl_payload)
        assert r_ctrl.status_code == 200
        ctrl_data = r_ctrl.json()
        assert ctrl_data["ocean_conditions"]["environmental_mode"] == "MANUAL_SCENARIO"
        assert ctrl_data["ocean_conditions"]["wave_height_m"] == 2.8

        # 3. Release back to automatic forecast
        rel_payload = {"environmental_mode": "AUTOMATIC_FORECAST"}
        r_rel = client.post("/api/v1/operator/simulator/control", json=rel_payload)
        assert r_rel.status_code == 200
        rel_data = r_rel.json()
        assert rel_data["ocean_conditions"]["environmental_mode"] == "AUTOMATIC_FORECAST"

        # 4. Explicit weather refresh endpoint
        r_ref = client.post("/api/v1/operator/simulator/weather/refresh")
        assert r_ref.status_code == 200


def test_10_safety_boundary_zero_actuation_port_10111():
    """Verify strict safety boundary: zero external actuation and port 10111 prohibited."""
    import inspect
    from app.telemetry import simulator, gateway

    sim_src = inspect.getsource(simulator)
    assert "10111" not in sim_src
    assert "socket.socket" not in sim_src or "SOCK_DGRAM" not in sim_src or "10111" not in sim_src

    # Ensure no autonomous control or actuator endpoints
    app = create_app()
    routes = [getattr(r, "path", "") for r in app.routes if hasattr(r, "path")]
    for r in routes:
        assert "actuate" not in r
        assert "rudder" not in r
        assert "engine/control" not in r
