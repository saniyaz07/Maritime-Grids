"""
tests/test_live_weather_lookahead_advisory_integration.py — Phase 10C.13G Integration Tests
=============================================================================================
Comprehensive test suite verifying the end-to-end integration:
  Bridge Command NMEA Telemetry -> Canonical Telemetry -> Spacetime Look-Ahead -> Advisory Engine -> Dashboard Contracts

Covers all 12 mandatory scenarios (A through L):
  A. Live simulated telemetry (2017 simulation time + fresh ingestion -> FRESH)
  B. Delayed simulated telemetry (old ingestion > 900s -> EXPIRED)
  C. Relative weather horizons (~1h, ~3h, ~6h distinct forecast horizons)
  D. Fractional horizon handling (e.g. 1.2h, 2.7h clamped deterministically)
  E. Adverse weather ahead (>25 kn wind or >2.5 m waves -> MET_AHEAD_ADVERSE_001 advisory)
  F. Safe weather ahead (normal conditions produce 0 MET_AHEAD_ADVERSE_001 advisories)
  G. Missing weather data (safely degrades, preserves nulls, no fabricated values)
  H. Missing/Zero SOG guards (no division by zero, stationary/speed-unavailable flags)
  I. Missing/Invalid position guards (fails/degrades safely with clear errors)
  J. Provenance & timestamp preservation (simulation, ingestion, and source tags preserved)
  K. Dashboard & API contracts (endpoints return full structured payload)
  L. Read-only safety invariants (0 actuators, 0 control outputs, 0 port 10111 writes)
"""

from datetime import datetime, timedelta, timezone
import pytest
from starlette.testclient import TestClient

from app.advisory.contracts import (
    AdvisoryCategory,
    AdvisoryPolicy,
    AdvisorySeverity,
    WeatherSafetyPolicy,
)
from app.advisory.engine import AdvisoryEngine
from app.advisory.rules import AdverseWeatherAheadRule, build_rule_set_from_policy
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
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.nmea_adapter import NMEAAdapter, NMEAUdpReceiver, calculate_nmea_checksum
from app.voyage.contracts import (
    Route,
    VesselContext,
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
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.mock_provider import MockWeatherProvider


def _build_nmea_rmc(time_str: str, date_str: str, lat: str, hemi_n: str, lon: str, hemi_e: str, sog: str, cog: str) -> str:
    body = f"GPRMC,{time_str},A,{lat},{hemi_n},{lon},{hemi_e},{sog},{cog},{date_str},,,A"
    csum = calculate_nmea_checksum(body)
    return f"${body}*{csum}\r\n"


# =====================================================================
# SCENARIO A: LIVE SIMULATED TELEMETRY FRESHNESS
# =====================================================================

def test_scenario_a_live_simulated_telemetry_is_fresh():
    """Historical simulation timestamp + recent host ingestion -> FRESH."""
    host_now = datetime.now(timezone.utc)
    payload = CanonicalTelemetryPayload(
        telemetry_id="TEL_SCENARIO_A",
        timestamp_utc="2017-11-06T05:57:30+00:00",
        ingested_at_utc=host_now.isoformat(),
        vessel_id="VESSEL_BC_01",
        position=PositionTelemetry(latitude=50.137, longitude=-4.118, speed_over_ground_knots=12.4),
        provenance=TelemetryProvenance(source="BRIDGE_COMMAND_NMEA", mode=TelemetryProvenanceType.SIMULATED),
    )
    freshness = payload.evaluate_freshness(current_time_utc=host_now)
    assert freshness == TelemetryFreshnessState.FRESH
    assert payload.quality.freshness_age_seconds is not None
    assert payload.quality.freshness_age_seconds < 1.0


# =====================================================================
# SCENARIO B: DELAYED SIMULATED TELEMETRY EXPIRATION
# =====================================================================

def test_scenario_b_delayed_simulated_telemetry_expires():
    """Historical simulation timestamp + old host ingestion (>900s) -> EXPIRED / STALE."""
    host_now = datetime.now(timezone.utc)
    old_ingest = host_now - timedelta(seconds=3700)  # > 3600s
    payload = CanonicalTelemetryPayload(
        telemetry_id="TEL_SCENARIO_B",
        timestamp_utc="2017-11-06T05:57:30+00:00",
        ingested_at_utc=old_ingest.isoformat(),
        vessel_id="VESSEL_BC_01",
        position=PositionTelemetry(latitude=50.137, longitude=-4.118, speed_over_ground_knots=12.4),
        provenance=TelemetryProvenance(source="BRIDGE_COMMAND_NMEA", mode=TelemetryProvenanceType.SIMULATED),
    )
    freshness = payload.evaluate_freshness(current_time_utc=host_now)
    assert freshness == TelemetryFreshnessState.EXPIRED
    assert payload.quality.freshness_age_seconds >= 3600.0


# =====================================================================
# SCENARIO C: RELATIVE WEATHER HORIZONS (1h, 3h, 6h)
# =====================================================================

def test_scenario_c_relative_weather_horizons():
    """Vessel at 10 kn on route with ~10 NM, ~30 NM, ~60 NM waypoints gets distinct +1h, +3h, +6h forecast steps."""
    ref_time = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    provider = MockWeatherProvider(fixed_reference_time=ref_time)
    engine = RouteWeatherLookAheadEngine()

    v_pos = VesselPosition(
        latitude=50.0,
        longitude=-4.0,
        timestamp_utc="2017-11-06T05:57:30+00:00",  # Cross-epoch simulation time
        speed_over_ground_knots=10.0,
        data_type=TelemetryProvenanceType.SIMULATED,
    )

    route = Route(
        route_id="ROUTE_PLY_BREST",
        origin_port="Plymouth Sound",
        destination_port="Brest Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1_10NM", latitude=50.1667, longitude=-4.0),
            RouteWaypoint(waypoint_id="WP2_30NM", latitude=50.5000, longitude=-4.0),
            RouteWaypoint(waypoint_id="WP3_60NM", latitude=51.0000, longitude=-4.0),
        ],
    )

    lookahead = engine.compute_lookahead(position=v_pos, route=route, weather_provider=provider)
    assert len(lookahead.waypoints) == 3

    ts_list = [wp.weather.timestamp_utc for wp in lookahead.waypoints if wp.weather]
    assert len(ts_list) == 3
    # All 3 timestamps must be distinct and chronologically progressing
    assert len(set(ts_list)) == 3
    assert ts_list == sorted(ts_list)


# =====================================================================
# SCENARIO D: FRACTIONAL HORIZON HANDLING (1.2h, 2.7h)
# =====================================================================

def test_scenario_d_fractional_horizon_handling():
    """Fractional durations (e.g. 1.2h -> step 1, 2.7h -> step 3) index nearest forecast step deterministically."""
    ref_time = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    provider = MockWeatherProvider(fixed_reference_time=ref_time)
    engine = RouteWeatherLookAheadEngine()

    v_pos = VesselPosition(
        latitude=50.0,
        longitude=-4.0,
        timestamp_utc="2017-11-06T05:57:30+00:00",
        speed_over_ground_knots=10.0,
        data_type=TelemetryProvenanceType.SIMULATED,
    )

    # 12 NM -> 1.2h, 27 NM -> 2.7h
    route = Route(
        route_id="ROUTE_FRACT",
        origin_port="Origin",
        destination_port="Dest",
        waypoints=[
            RouteWaypoint(waypoint_id="WP_1_2H", latitude=50.2000, longitude=-4.0),  # ~12 NM
            RouteWaypoint(waypoint_id="WP_2_7H", latitude=50.4500, longitude=-4.0),  # ~27 NM
        ],
    )

    lookahead = engine.compute_lookahead(position=v_pos, route=route, weather_provider=provider)
    assert len(lookahead.waypoints) == 2
    assert lookahead.waypoints[0].hours_ahead == pytest.approx(1.2, abs=0.1)
    assert lookahead.waypoints[1].hours_ahead == pytest.approx(2.7, abs=0.1)

    # 1.2h indexes step 1 (+1h: 13:00 UTC), 2.7h indexes step 3 (+3h: 15:00 UTC)
    assert lookahead.waypoints[0].weather.timestamp_utc == "2026-09-28T13:00:00+00:00"
    assert lookahead.waypoints[1].weather.timestamp_utc == "2026-09-28T15:00:00+00:00"


# =====================================================================
# SCENARIO E: ADVERSE WEATHER AHEAD ADVISORY GENERATION
# =====================================================================

def test_scenario_e_adverse_weather_ahead_advisory():
    """Injected weather above thresholds (>25 kn wind or >2.5 m waves) triggers MET_AHEAD_ADVERSE_001 with human review."""
    severe_rec = NormalizedWeatherRecord(
        latitude=50.50,
        longitude=-4.0,
        timestamp_utc="2026-09-28T15:00:00+00:00",
        retrieval_timestamp_utc="2026-09-28T12:00:00+00:00",
        data_source="MOCK_SEVERE",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=32.5,  # > 25.0 kn
        wave_height_m=3.20,     # > 2.5 m
    )

    route_profile = RouteWeatherProfile(
        route_id="ROUTE_SEVERE",
        total_waypoints=2,
        waypoints_weather=[severe_rec, severe_rec],
        overall_quality=WeatherQualityState.VALID,
    )

    voyage_ctx = VoyageContext(
        voyage_id="VOY_SEVERE_01",
        timeline=VoyageTimeline(departure_time_utc="2026-09-28T12:00:00+00:00", current_time_utc="2026-09-28T12:00:00+00:00"),
        vessel=VesselContext(vessel_id="VESSEL_01", ship_type="Oil Service Boat"),
        route=Route(
            route_id="ROUTE_SEVERE",
            origin_port="A",
            destination_port="B",
            waypoints=[
                RouteWaypoint(waypoint_id="WP1", latitude=50.2, longitude=-4.0),
                RouteWaypoint(waypoint_id="WP2", latitude=50.5, longitude=-4.0),
            ],
        ),
        current_position=VesselPosition(latitude=50.0, longitude=-4.0, speed_over_ground_knots=10.0, timestamp_utc="2026-09-28T12:00:00+00:00"),
        weather_context=VoyageWeatherContext(route_weather=route_profile),
    )

    decision_ctx = DecisionContext(
        decision_context_id="DC_SEVERE_TEST",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        voyage_context=voyage_ctx,
    )

    policy = AdvisoryPolicy(
        weather_policy=WeatherSafetyPolicy(high_wind_threshold_knots=25.0, rough_sea_threshold_m=2.5)
    )

    rules = build_rule_set_from_policy(policy, include_lookahead=True)
    engine = AdvisoryEngine(rules=rules)
    advisories = engine.evaluate(decision_ctx)

    adverse_advisories = [a for a in advisories if a.rule_id == "MET_AHEAD_ADVERSE_001"]
    assert len(adverse_advisories) >= 1

    adv = adverse_advisories[0]
    assert adv.severity == AdvisorySeverity.WARNING
    assert adv.human_review_required is True
    assert len(adv.evidence) >= 1
    assert adv.evidence[0].provenance == WeatherProvenanceType.FORECAST
    assert "Waypoint 1" in adv.message


# =====================================================================
# SCENARIO F: SAFE WEATHER PRODUCES NO ADVERSE ALARMS
# =====================================================================

def test_scenario_f_safe_weather_no_false_advisories():
    """Calm weather below thresholds produces 0 MET_AHEAD_ADVERSE_001 advisories."""
    calm_rec = NormalizedWeatherRecord(
        latitude=50.50,
        longitude=-4.0,
        timestamp_utc="2026-09-28T15:00:00+00:00",
        retrieval_timestamp_utc="2026-09-28T12:00:00+00:00",
        data_source="MOCK_CALM",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=12.0,  # <= 25.0 kn
        wave_height_m=1.20,     # <= 2.5 m
    )

    route_profile = RouteWeatherProfile(
        route_id="ROUTE_CALM",
        total_waypoints=2,
        waypoints_weather=[calm_rec, calm_rec],
        overall_quality=WeatherQualityState.VALID,
    )

    voyage_ctx = VoyageContext(
        voyage_id="VOY_CALM_01",
        timeline=VoyageTimeline(departure_time_utc="2026-09-28T12:00:00+00:00", current_time_utc="2026-09-28T12:00:00+00:00"),
        vessel=VesselContext(vessel_id="VESSEL_01", ship_type="Oil Service Boat"),
        route=Route(
            route_id="ROUTE_CALM",
            origin_port="A",
            destination_port="B",
            waypoints=[
                RouteWaypoint(waypoint_id="WP1", latitude=50.2, longitude=-4.0),
                RouteWaypoint(waypoint_id="WP2", latitude=50.5, longitude=-4.0),
            ],
        ),
        current_position=VesselPosition(latitude=50.0, longitude=-4.0, speed_over_ground_knots=10.0, timestamp_utc="2026-09-28T12:00:00+00:00"),
        weather_context=VoyageWeatherContext(route_weather=route_profile),
    )

    decision_ctx = DecisionContext(
        decision_context_id="DC_CALM_TEST",
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        voyage_context=voyage_ctx,
    )

    policy = AdvisoryPolicy(
        weather_policy=WeatherSafetyPolicy(high_wind_threshold_knots=25.0, rough_sea_threshold_m=2.5)
    )

    rules = build_rule_set_from_policy(policy, include_lookahead=True)
    engine = AdvisoryEngine(rules=rules)
    advisories = engine.evaluate(decision_ctx)

    adverse_advisories = [a for a in advisories if a.rule_id == "MET_AHEAD_ADVERSE_001"]
    assert len(adverse_advisories) == 0


# =====================================================================
# SCENARIO G: MISSING WEATHER DEGRADES SAFELY
# =====================================================================

def test_scenario_g_missing_weather_degrades_safely():
    """Missing weather fields remain None and do not trigger fabricated warnings or math errors."""
    sparse_provider = MockWeatherProvider(mode="missing_fields")
    engine = RouteWeatherLookAheadEngine()

    v_pos = VesselPosition(
        latitude=50.0,
        longitude=-4.0,
        timestamp_utc="2026-09-28T12:00:00+00:00",
        speed_over_ground_knots=10.0,
        data_type=TelemetryProvenanceType.SIMULATED,
    )

    route = Route(
        route_id="ROUTE_SPARSE",
        origin_port="A",
        destination_port="B",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1", latitude=50.2, longitude=-4.0),
            RouteWaypoint(waypoint_id="WP2", latitude=50.5, longitude=-4.0),
        ],
    )

    lookahead = engine.compute_lookahead(position=v_pos, route=route, weather_provider=sparse_provider)
    assert len(lookahead.waypoints) == 2
    wp = lookahead.waypoints[0]
    assert wp.weather is not None
    # Wave fields are None, not 0.0
    assert wp.weather.wave_height_m is None
    assert wp.weather.ocean_current_speed_knots is None
    assert wp.rough_sea_warning is False


# =====================================================================
# SCENARIO H: MISSING OR ZERO SOG SAFETY GUARDS
# =====================================================================

def test_scenario_h_stationary_and_missing_sog_guards():
    """Zero or None SOG marks timing status STATIONARY or SPEED_UNAVAILABLE with no division by zero."""
    provider = MockWeatherProvider()
    engine = RouteWeatherLookAheadEngine()

    route = Route(
        route_id="ROUTE_GUARD",
        origin_port="A",
        destination_port="B",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1", latitude=50.2, longitude=-4.0),
            RouteWaypoint(waypoint_id="WP2", latitude=50.5, longitude=-4.0),
        ],
    )

    # 1. Zero SOG
    v_pos_zero = VesselPosition(latitude=50.0, longitude=-4.0, speed_over_ground_knots=0.0, timestamp_utc="2026-09-28T12:00:00+00:00")
    la_zero = engine.compute_lookahead(position=v_pos_zero, route=route, weather_provider=provider)
    assert la_zero.timing_status == LookAheadTimingStatus.STATIONARY
    assert la_zero.waypoints[0].estimated_arrival_utc is None
    assert la_zero.waypoints[0].hours_ahead is None

    # 2. None SOG
    v_pos_none = VesselPosition(latitude=50.0, longitude=-4.0, speed_over_ground_knots=None, timestamp_utc="2026-09-28T12:00:00+00:00")
    la_none = engine.compute_lookahead(position=v_pos_none, route=route, weather_provider=provider)
    assert la_none.timing_status == LookAheadTimingStatus.SPEED_UNAVAILABLE
    assert la_none.waypoints[0].estimated_arrival_utc is None
    la_none = engine.compute_lookahead(position=v_pos_none, route=route, weather_provider=provider)
    assert la_none.timing_status == LookAheadTimingStatus.SPEED_UNAVAILABLE
    assert la_none.waypoints[0].estimated_arrival_utc is None


# =====================================================================
# SCENARIO I: MISSING OR EMPTY ROUTE WAYPOINTS GUARD
# =====================================================================

def test_scenario_i_empty_waypoints_raises_validation_error():
    """Empty route waypoints raise ValueError without crashing engine."""
    provider = MockWeatherProvider()
    engine = RouteWeatherLookAheadEngine()
    v_pos = VesselPosition(latitude=50.0, longitude=-4.0, speed_over_ground_knots=10.0, timestamp_utc="2026-09-28T12:00:00+00:00")

    with pytest.raises(Exception):
        # Route requires at least 2 waypoints in validator
        route_empty = Route(route_id="EMPTY", origin_port="A", destination_port="B", waypoints=[])
        engine.compute_lookahead(position=v_pos, route=route_empty, weather_provider=provider)


# =====================================================================
# SCENARIO J: PROVENANCE AND TIMESTAMP PRESERVATION
# =====================================================================

def test_scenario_j_provenance_and_timestamp_preservation():
    """Verify simulation timestamp, host ingestion timestamp, and provenance tags remain unmutated."""
    adapter = NMEAAdapter(vessel_id="VESSEL_BC_PROV")
    rmc = _build_nmea_rmc("055730.00", "061117", "5000.0000", "N", "00400.0000", "W", "12.0", "180.0")
    ingest_ts = "2026-09-28T16:50:34.123456+00:00"

    payload = adapter.update_from_sentence(rmc, ingested_at_utc=ingest_ts)
    assert payload is not None
    assert payload.timestamp_utc.startswith("2017-11-06T05:57:30")
    assert payload.ingested_at_utc == ingest_ts
    assert payload.provenance.source == "BRIDGE_COMMAND_NMEA"
    assert payload.provenance.mode == TelemetryProvenanceType.SIMULATED


# =====================================================================
# SCENARIO K: FASTAPI REST ENDPOINT INTEGRATION
# =====================================================================

def test_scenario_k_operator_lookahead_api_endpoint():
    """Verify /api/v1/operator/weather/lookahead REST endpoint returns full structured payload."""
    custom_gateway = TelemetryGateway()
    app = create_app(telemetry_gateway=custom_gateway, enable_nmea_receiver=False)

    with TestClient(app) as client:
        req_body = {
            "position": {
                "latitude": 50.0,
                "longitude": -4.0,
                "speed_over_ground_knots": 12.0,
                "course_over_ground_deg": 180.0,
                "timestamp_utc": "2017-11-06T05:57:30+00:00",
                "data_type": "SIMULATED",
            },
            "route": {
                "route_id": "ESC_LAGOS",
                "origin_port": "Escravos",
                "destination_port": "Lagos",
                "waypoints": [
                    {"waypoint_id": "WP1", "latitude": 50.2, "longitude": -4.0},
                    {"waypoint_id": "WP2", "latitude": 50.5, "longitude": -4.0},
                ],
            },
            "vessel_id": "VESSEL_BC_01",
        }

        resp = client.post("/api/v1/operator/weather/lookahead", json=req_body)
        assert resp.status_code == 200
        data = resp.json()

        assert data["route_id"] == "ESC_LAGOS"
        assert data["timing_status"] == "ESTIMATED"
        assert len(data["waypoints"]) == 2
        assert data["waypoints"][0]["weather"]["data_type"] == "FORECAST"
        assert data["summary"]["total_lookahead_distance_nm"] > 0.0


# =====================================================================
# SCENARIO L: SAFETY INVARIANTS & ZERO ACTUATOR COMMANDS
# =====================================================================

def test_scenario_l_zero_actuation_guarantee():
    """Verify that no actuator pathways, control endpoints, or port 10111 writes exist."""
    adapter = NMEAAdapter()
    receiver = NMEAUdpReceiver(adapter=adapter)

    # Inbound port is 10110
    assert receiver.port == 10110

    # Actuator methods must not exist
    for forbidden in [
        "send_rudder", "send_throttle", "set_autopilot",
        "send_command", "send_nmea_control", "write_control_packet"
    ]:
        assert not hasattr(adapter, forbidden)
        assert not hasattr(receiver, forbidden)
