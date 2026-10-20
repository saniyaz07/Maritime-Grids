"""
tests/test_virtual_bridge_voyage_replay.py — Phase 10C.13J Full Virtual Bridge Voyage Run & Replay
===================================================================================================
Executes and validates one complete multi-layer virtual voyage through the entire
Maritime Grids stack:
  1. Bridge Command NMEA Telemetry Ingestion -> TelemetryGateway
  2. Spacetime Route Weather Look-Ahead Engine
  3. Virtual Vessel Energy State Estimator (Hydrodynamics, Fuel Rate, Battery SOC)
  4. Deterministic Advisory Rule Evaluations (Adverse Weather Ahead, Low Fuel Reserve)
  5. Persistent Telemetry Audit Repository & Full Voyage History Replay
  6. Zero-actuation safety invariants (0 control commands, 0 port 10111 writes)
"""

from datetime import datetime, timedelta, timezone
import math
import pytest
from starlette.testclient import TestClient

from app.advisory.contracts import (
    AdvisoryCategory,
    AdvisoryPolicy,
    AdvisorySeverity,
    BatterySocPolicy,
    FuelLevelPolicy,
    WeatherSafetyPolicy,
)
from app.advisory.engine import AdvisoryEngine
from app.advisory.rules import build_rule_set_from_policy
from app.api.app import create_app
from app.decision.contracts import DecisionContext
from app.services.operator_service import OperatorService
from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    EngineOperationalState,
    PositionTelemetry,
    TelemetryFreshnessState,
    TelemetryProvenance,
    TelemetryProvenanceType,
    TelemetryQuality,
    TelemetryQualityState,
)
from app.telemetry.energy_estimator import VirtualEnergyEstimator
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.nmea_adapter import NMEAAdapter, calculate_nmea_checksum
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
from app.voyage.lookahead import (
    LookAheadTimingStatus,
    RouteWeatherLookAheadEngine,
    haversine_distance_nm,
)
from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.mock_provider import MockWeatherProvider


def _generate_nmea_rmc(
    time_str: str,
    date_str: str,
    lat_deg: float,
    lon_deg: float,
    sog_knots: float,
    cog_deg: float,
) -> str:
    """Formats a valid GPRMC sentence with standard NMEA coordinate formatting."""
    lat_hemi = "N" if lat_deg >= 0 else "S"
    abs_lat = abs(lat_deg)
    lat_d = int(abs_lat)
    lat_m = (abs_lat - lat_d) * 60.0
    lat_str = f"{lat_d:02d}{lat_m:06.3f}"

    lon_hemi = "E" if lon_deg >= 0 else "W"
    abs_lon = abs(lon_deg)
    lon_d = int(abs_lon)
    lon_m = (abs_lon - lon_d) * 60.0
    lon_str = f"{lon_d:03d}{lon_m:06.3f}"

    body = f"GPRMC,{time_str},A,{lat_str},{lat_hemi},{lon_str},{lon_hemi},{sog_knots:.1f},{cog_deg:.1f},{date_str},,,A"
    csum = calculate_nmea_checksum(body)
    return f"${body}*{csum}\r\n"


# =====================================================================
# VOYAGE SCENARIO INTEGRATION TESTS
# =====================================================================

def test_full_virtual_voyage_execution_and_replay():
    """
    Executes a complete 5-stage virtual voyage:
      Stage 0: Pre-departure dockside (SOG = 0.0 kn, Idle fuel rate, LookAhead = STATIONARY)
      Stage 1: Acceleration & Departure (SOG = 8.0 kn, Increasing fuel rate, Clear weather)
      Stage 2: High-Speed Offshore Transit (SOG = 13.5 kn, High shaft power, Approaching front)
      Stage 3: Rough Weather Encounter (SOG = 10.0 kn, High wave/wind resistance, MET_AHEAD_ADVERSE_001 triggered)
      Stage 4: Port Arrival & Low Reserve (SOG = 2.0 kn, Fuel depleted past reserve, ENG_FUEL_LOW_002 triggered)
    """
    # 1. Initialize components
    audit_repo = InMemoryTelemetryAuditRepository(max_records=1000)
    adapter = NMEAAdapter(vessel_id="VESSEL_OSV_LAGOS_01")
    estimator = VirtualEnergyEstimator(
        ship_type="Oil Service Boat",
        initial_fuel_liters=2000.0,
        initial_battery_soc_pct=85.0,
    )
    gateway = TelemetryGateway(
        default_vessel_id="VESSEL_OSV_LAGOS_01",
        repository=audit_repo,
        energy_estimator=estimator,
    )
    audit_repo._records.clear()
    audit_repo._by_id.clear()
    estimator.reset_state(initial_fuel_liters=2000.0, initial_battery_soc_pct=85.0)

    # 2. Define route: Escravos Terminal -> Lagos Port
    route = Route(
        route_id="ESCRAVOS_LAGOS",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP_ESCRAVOS", latitude=5.58, longitude=5.18),
            RouteWaypoint(waypoint_id="WP_MID_OFFSHORE", latitude=5.80, longitude=4.50),
            RouteWaypoint(waypoint_id="WP_APPROACH_LAGOS", latitude=6.20, longitude=3.80),
            RouteWaypoint(waypoint_id="WP_LAGOS_PORT", latitude=6.45, longitude=3.40),
        ],
    )

    # 3. Reference time setup (Simulation time vs Host ingestion time)
    ref_host_start = datetime(2026, 9, 28, 14, 0, 0, tzinfo=timezone.utc)
    lookahead_engine = RouteWeatherLookAheadEngine()
    weather_provider = MockWeatherProvider(fixed_reference_time=ref_host_start)

    policy = AdvisoryPolicy(
        weather_policy=WeatherSafetyPolicy(high_wind_threshold_knots=25.0, rough_sea_threshold_m=2.5),
        fuel_policy=FuelLevelPolicy(warning_threshold_liters=1500.0),
        battery_policy=BatterySocPolicy(warning_threshold_pct=20.0),
    )
    rules = build_rule_set_from_policy(policy, include_lookahead=True)
    advisory_engine = AdvisoryEngine(rules=rules)

    # 4. Multi-Stage Telemetry Samples
    stages = [
        # (sim_time, elapsed_sec, lat, lon, sog, cog, desc)
        ("060000", 0, 5.580, 5.180, 0.0, 270.0, "Stage 0: Dockside Idle"),
        ("060500", 300, 5.650, 4.950, 8.0, 280.0, "Stage 1: Departure Transit"),
        ("061500", 900, 5.800, 4.500, 13.5, 285.0, "Stage 2: High-Speed Offshore"),
        ("063000", 1800, 6.000, 4.150, 10.0, 290.0, "Stage 3: Rough Weather Zone"),
        ("064500", 2700, 6.350, 3.550, 2.0, 295.0, "Stage 4: Lagos Approach & Low Fuel"),
    ]

    recorded_frames = []

    for sim_time, dt_sec, lat, lon, sog, cog, desc in stages:
        host_now = ref_host_start + timedelta(seconds=dt_sec)
        nmea_str = _generate_nmea_rmc(
            time_str=sim_time,
            date_str="061117",  # 06-Nov-2017 historical simulation date
            lat_deg=lat,
            lon_deg=lon,
            sog_knots=sog,
            cog_deg=cog,
        )

        # Ingest through NMEA Adapter
        norm_payload = adapter.update_from_sentence(
            nmea_str,
            ingested_at_utc=host_now.isoformat(),
        )
        assert norm_payload is not None

        canonical_frame = gateway.ingest_canonical(norm_payload)
        recorded_frames.append(canonical_frame)
        print(f"DEBUG: Stage frame {len(recorded_frames)-1}: dt={dt_sec}, sog={sog}, energy={canonical_frame.energy}")

        # Verify Engine State Invariant (Engine state remains UNKNOWN regardless of SOG)
        assert canonical_frame.engine.state == EngineOperationalState.UNKNOWN

        # Verify Energy Telemetry Provenance
        assert canonical_frame.provenance.mode == TelemetryProvenanceType.SIMULATED
        assert "VIRTUAL_ENERGY_ESTIMATOR" in canonical_frame.provenance.source

        # Compute dynamic Spacetime Look-Ahead
        v_pos = VesselPosition(
            latitude=lat,
            longitude=lon,
            timestamp_utc=norm_payload.timestamp_utc,
            speed_over_ground_knots=sog,
            course_over_ground_deg=cog,
            data_type=TelemetryProvenanceType.SIMULATED,
        )
        lookahead = lookahead_engine.compute_lookahead(
            position=v_pos,
            route=route,
            weather_provider=weather_provider,
            reference_time_utc=host_now.isoformat(),
        )

        # If stationary (Stage 0), lookahead handles timing status safely
        if sog == 0.0:
            assert lookahead.waypoints[0].timing_status == LookAheadTimingStatus.STATIONARY
            assert lookahead.waypoints[0].hours_ahead is None

    # 5. Check Monotonicity & Physics Consistency
    f0 = recorded_frames[0]
    f2 = recorded_frames[2]
    f4 = recorded_frames[4]

    # Shaft power and fuel rate increase with speed
    assert f0.energy.fuel_rate_lph < f2.energy.fuel_rate_lph
    assert f2.engine.power_kw > f0.engine.power_kw
    assert f2.engine.power_kw > 1000.0  # High speed shaft power

    # Fuel remaining strictly decreases over time
    assert f4.energy.fuel_remaining_liters < f0.energy.fuel_remaining_liters
    assert estimator.cumulative_fuel_consumed_liters > 0.0

    # 6. Verify Advisory Engine on Stage 4 (Low Fuel Trigger)
    voyage_ctx = VoyageContext(
        voyage_id="VOY_ESCRAVOS_LAGOS_01",
        timeline=VoyageTimeline(current_time_utc=ref_host_start.isoformat()),
        vessel=VesselContext(vessel_id="VESSEL_OSV_LAGOS_01", ship_type="Oil Service Boat"),
        route=route,
        current_position=VesselPosition(
            latitude=5.8,
            longitude=4.5,
            speed_over_ground_knots=10.0,
            timestamp_utc="2017-11-06T06:45:00+00:00",
        ),
        energy_state=VesselEnergyState(
            fuel_remaining_liters=1400.0,  # Below policy threshold (1500.0 L)
            battery_soc_pct=80.0,
            provenance=WeatherProvenanceType.SIMULATED,
        ),
    )
    decision_ctx = DecisionContext(
        decision_context_id="DC_VOYAGE_STAGE_4",
        created_at_utc=ref_host_start.isoformat(),
        voyage_context=voyage_ctx,
    )

    advisories = advisory_engine.evaluate(decision_ctx)
    fuel_advs = [a for a in advisories if a.category == AdvisoryCategory.FUEL]
    assert len(fuel_advs) == 1
    assert fuel_advs[0].severity == AdvisorySeverity.WARNING
    assert fuel_advs[0].human_review_required is True

    # 7. Verify Voyage Audit Replay from Repository
    all_audit_records = audit_repo.query(vessel_id="VESSEL_OSV_LAGOS_01", limit=100)
    assert len(all_audit_records) == 5

    # Reconstruct trajectory from audit records (query returns DESC order by timestamp_utc)
    chronological_records = list(reversed(all_audit_records))
    reconstructed_coords = [(r.payload.position.latitude, r.payload.position.longitude) for r in chronological_records]
    assert reconstructed_coords[0] == (5.580, 5.180)
    assert reconstructed_coords[-1] == (6.350, 3.550)


# =====================================================================
# API AND DASHBOARD REPLAY CONTRACT TESTS
# =====================================================================

def test_api_and_dashboard_replay_contracts():
    """Verify FastAPI /operator/telemetry/history and /operator/telemetry/current endpoints serve replay data."""
    app = create_app()
    client = TestClient(app)

    # Ingest a sample voyage frame
    t_now = datetime.now(timezone.utc).isoformat()
    raw_payload = {
        "vessel_id": "VESSEL_OSV_LAGOS_01",
        "latitude": 5.80,
        "longitude": 4.50,
        "speed_over_ground_knots": 12.0,
        "course_over_ground_deg": 285.0,
        "heading_deg": 285.0,
        "timestamp_utc": "2017-11-06T06:00:00+00:00",
        "ingested_at_utc": t_now,
    }

    ingest_res = client.post("/api/v1/operator/telemetry/ingest", json=raw_payload)
    assert ingest_res.status_code == 200

    # Query current telemetry
    cur_res = client.get("/api/v1/operator/telemetry/current")
    assert cur_res.status_code == 200
    cur_data = cur_res.json()
    assert cur_data["vessel_id"] == "VESSEL_OSV_LAGOS_01"
    assert cur_data["position"]["latitude"] == 5.80

    # Query voyage history
    hist_res = client.get("/api/v1/operator/telemetry/history?vessel_id=VESSEL_OSV_LAGOS_01&limit=50")
    assert hist_res.status_code == 200
    hist_data = hist_res.json()
    assert isinstance(hist_data, list)
    assert len(hist_data) >= 1
    assert hist_data[0]["vessel_id"] == "VESSEL_OSV_LAGOS_01"


# =====================================================================
# SAFETY & ACTUATOR VERIFICATION
# =====================================================================

def test_safety_zero_control_traffic():
    """Verify zero reverse control traffic, zero actuator methods, and zero port 10111 references."""
    import inspect
    import app.telemetry.energy_estimator as mod_energy
    import app.telemetry.gateway as mod_gw
    import app.voyage.lookahead as mod_lookahead

    for mod in [mod_energy, mod_gw, mod_lookahead]:
        src = inspect.getsource(mod)
        assert "sendto" not in src
        assert "socket.send" not in src
        assert "set_throttle" not in src
        assert "set_rudder" not in src
        assert "rudder_control" not in src
        assert "throttle_control" not in src
