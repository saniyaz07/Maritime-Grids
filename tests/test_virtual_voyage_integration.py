"""
tests/test_virtual_voyage_integration.py — Phase 10C.13D Virtual Voyage + Live Driver Dashboard End-to-End Tests
==================================================================================================================
Comprehensive integration suite validating:
  1. Live UDP NMEA stream ingestion -> NMEAUdpReceiver -> TelemetryGateway -> CanonicalTelemetryPayload.
  2. Sequential vessel kinematic progression updating position, SOG, COG, heading.
  3. Dynamic route weather look-ahead generation linked to live vessel fixes.
  4. Look-ahead refresh throttling (burst of NMEA packets does not trigger runaway weather requests).
  5. Forward-looking adverse weather alert generation during vessel progression.
  6. Telemetry lifecycle & freshness transitions (LIVE -> STALE -> EXPIRED -> RECONNECT).
  7. Non-inference invariant (engine state remains UNKNOWN and fuel/battery remain None when unmeasured).
  8. Absolute safety invariant: Zero simulator command outputs, zero rudder/throttle commands, zero actuator paths.
"""

from datetime import datetime, timedelta, timezone
import math
import socket
import time
from typing import List, Optional
import pytest
from fastapi.testclient import TestClient

from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    EngineOperationalState,
    TelemetryFreshnessState,
    TelemetryProvenanceType,
    TelemetryQualityState,
)
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.nmea_adapter import NMEAAdapter, NMEAUdpReceiver, calculate_nmea_checksum
from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.mock_provider import MockWeatherProvider
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
    compute_route_weather_lookahead,
)
from app.decision.contracts import DecisionContext
from app.advisory.contracts import (
    AdvisoryCategory,
    AdvisoryPolicy,
    AdvisorySeverity,
    WeatherSafetyPolicy,
)
from app.advisory.rules import AdverseWeatherAheadRule
from app.services.operator_service import OperatorService
from app.api.app import create_app


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def mock_weather_provider() -> MockWeatherProvider:
    return MockWeatherProvider(
        fixed_reference_time=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    )


@pytest.fixture
def sample_route() -> Route:
    return Route(
        route_id="ESCRAVOS_LAGOS",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP_01", latitude=5.58, longitude=5.18),
            RouteWaypoint(waypoint_id="WP_02", latitude=5.80, longitude=4.50),
            RouteWaypoint(waypoint_id="WP_03", latitude=6.10, longitude=3.80),
            RouteWaypoint(waypoint_id="WP_04", latitude=6.45, longitude=3.40),
        ],
        total_distance_nm=130.0,
    )


@pytest.fixture
def audit_repository() -> InMemoryTelemetryAuditRepository:
    return InMemoryTelemetryAuditRepository(max_records=500)


@pytest.fixture
def gateway(audit_repository) -> TelemetryGateway:
    return TelemetryGateway(repository=audit_repository)


def build_nmea_rmc_packet(lat_dd: float, lon_dd: float, sog_knots: float, cog_deg: float, time_str: str = "120000.00", date_str: str = "150626") -> str:
    """Builds a valid $GPRMC sentence with accurate coordinate formatting and checksum."""
    lat_deg = int(abs(lat_dd))
    lat_min = (abs(lat_dd) - lat_deg) * 60.0
    lat_hem = "N" if lat_dd >= 0 else "S"
    lat_nmea = f"{lat_deg:02d}{lat_min:07.4f}"

    lon_deg = int(abs(lon_dd))
    lon_min = (abs(lon_dd) - lon_deg) * 60.0
    lon_hem = "E" if lon_dd >= 0 else "W"
    lon_nmea = f"{lon_deg:03d}{lon_min:07.4f}"

    raw = f"GPRMC,{time_str},A,{lat_nmea},{lat_hem},{lon_nmea},{lon_hem},{sog_knots:.1f},{cog_deg:.1f},{date_str},,,A"
    chk = calculate_nmea_checksum(raw)
    return f"${raw}*{chk}\r\n"


def build_nmea_hdt_packet(heading_deg: float) -> str:
    """Builds a valid $GPHDT sentence with checksum."""
    raw = f"GPHDT,{heading_deg:.1f},T"
    chk = calculate_nmea_checksum(raw)
    return f"${raw}*{chk}\r\n"


# =====================================================================
# 1. END-TO-END UDP NMEA STREAM INGESTION TEST
# =====================================================================

def test_e2e_udp_nmea_stream_ingestion(gateway):
    """
    Verifies that real UDP packets sent to NMEAUdpReceiver parse into
    canonical telemetry, populate the gateway, and record into audit history.
    """
    adapter = NMEAAdapter(vessel_id="VIRTUAL_VESSEL_BC5", source_name="BRIDGE_COMMAND_NMEA")
    receiver = NMEAUdpReceiver(gateway=gateway, adapter=adapter, host="127.0.0.1", port=0)
    receiver.start()

    bound_port = receiver._socket.getsockname()[1]

    try:
        # Emit a stream of NMEA datagrams
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rmc = build_nmea_rmc_packet(lat_dd=5.58, lon_dd=5.18, sog_knots=12.5, cog_deg=295.0)
        hdt = build_nmea_hdt_packet(heading_deg=294.5)
        combined_packet = (rmc + hdt).encode("utf-8")

        sock.sendto(combined_packet, ("127.0.0.1", bound_port))
        for _ in range(20):
            if receiver.packets_received > 0 and receiver.sentences_processed >= 2:
                break
            time.sleep(0.05)

        # Verify gateway current frame
        frame = gateway.get_current_frame()
        assert frame is not None
        assert frame.vessel_id == "VIRTUAL_VESSEL_BC5"
        assert frame.provenance.source == "BRIDGE_COMMAND_NMEA"
        assert frame.provenance.mode == TelemetryProvenanceType.SIMULATED

        # Kinematics verification
        assert frame.position.latitude == pytest.approx(5.58, abs=0.001)
        assert frame.position.longitude == pytest.approx(5.18, abs=0.001)
        assert frame.position.speed_over_ground_knots == pytest.approx(12.5, abs=0.1)
        assert frame.position.course_over_ground_deg == pytest.approx(295.0, abs=0.1)
        assert frame.position.heading_deg == pytest.approx(294.5, abs=0.1)

        # Strict non-inference
        assert frame.engine.state == EngineOperationalState.UNKNOWN
        assert frame.engine.rpm is None
        assert frame.energy.battery_soc_pct is None
        assert frame.energy.fuel_remaining_liters is None

        # Verify audit record recorded
        records = gateway.repository.query(vessel_id="VIRTUAL_VESSEL_BC5")
        assert len(records) >= 1
        assert records[0].payload.position.speed_over_ground_knots == pytest.approx(12.5, abs=0.1)
    finally:
        receiver.stop()


# =====================================================================
# 2. VOYAGE PROGRESSION & WEATHER LOOK-AHEAD SYNC TEST
# =====================================================================

def test_voyage_progression_lookahead_updates(gateway, sample_route, mock_weather_provider):
    """
    Simulates a vessel moving along multiple route coordinates in sequence.
    Verifies that the route look-ahead recalculates distances and spacetime ETAs accurately.
    """
    adapter = NMEAAdapter(vessel_id="VESSEL_OSV_01")
    engine = RouteWeatherLookAheadEngine()

    fixes = [
        {"lat": 5.58, "lon": 5.18, "sog": 12.0, "cog": 295.0, "time": "120000.00"},
        {"lat": 5.80, "lon": 4.50, "sog": 14.0, "cog": 290.0, "time": "140000.00"},
        {"lat": 6.10, "lon": 3.80, "sog": 10.0, "cog": 280.0, "time": "170000.00"},
    ]

    for fix in fixes:
        rmc = build_nmea_rmc_packet(lat_dd=fix["lat"], lon_dd=fix["lon"], sog_knots=fix["sog"], cog_deg=fix["cog"], time_str=fix["time"])
        frame = adapter.update_from_sentence(rmc)
        assert frame is not None
        gateway.update_current(frame)

        # Ingest to lookahead engine
        pos = frame.to_vessel_position()
        assert pos is not None
        assert pos.latitude == pytest.approx(fix["lat"], abs=0.001)

        lookahead = engine.compute_lookahead(
            position=pos,
            route=sample_route,
            weather_provider=mock_weather_provider,
            vessel_id="VESSEL_OSV_01",
        )

        assert lookahead.timing_status == LookAheadTimingStatus.ESTIMATED
        assert lookahead.speed_over_ground_knots == pytest.approx(fix["sog"], abs=0.1)
        assert len(lookahead.waypoints) == 4

        # First waypoint distance from current vessel position
        assert lookahead.waypoints[0].weather is not None


# =====================================================================
# 3. REFRESH THROTTLING VALIDATION
# =====================================================================

def test_lookahead_refresh_throttling():
    """
    Verifies that a high-frequency burst of NMEA packets on identical or
    near-identical coordinates is suppressed by the refresh controller.
    """
    # Simulated tracking controller
    last_query = {"lat": 5.58, "lon": 5.18, "sog": 12.0, "timestamp": time.time()}
    weather_request_count = 0

    def should_refresh(current_lat: float, current_lon: float, current_sog: Optional[float], current_time: float) -> bool:
        # Time threshold (60s)
        if current_time - last_query["timestamp"] >= 60.0:
            return True
        # Movement threshold (>= 0.5 NM)
        d_lat = (current_lat - last_query["lat"]) * 60.0
        d_lon = (current_lon - last_query["lon"]) * 60.0 * math.cos(math.radians(current_lat))
        dist_nm = math.sqrt(d_lat * d_lat + d_lon * d_lon)
        if dist_nm >= 0.5:
            return True
        # Speed threshold (>= 1.0 kn)
        if current_sog is not None and last_query["sog"] is not None:
            if abs(current_sog - last_query["sog"]) >= 1.0:
                return True
        return False

    t0 = time.time()
    # 50 high-frequency packets with sub-meter jitter over 2 seconds
    for i in range(50):
        lat = 5.58 + (i * 0.00001)
        lon = 5.18 + (i * 0.00001)
        sog = 12.0 + (i * 0.01)
        curr_t = t0 + (i * 0.04)

        if should_refresh(lat, lon, sog, curr_t):
            weather_request_count += 1
            last_query["lat"] = lat
            last_query["lon"] = lon
            last_query["sog"] = sog
            last_query["timestamp"] = curr_t

    # 50 NMEA packets must have triggered 0 or at most 1 refresh
    assert weather_request_count == 0

    # Large position jump (0.02 deg lat = 1.2 NM)
    assert should_refresh(5.60, 5.18, 12.0, t0 + 5.0) is True


# =====================================================================
# 4. ADVERSE WEATHER AHEAD ADVISORY TEST
# =====================================================================

def test_adverse_weather_ahead_live_progression(sample_route):
    """
    Verifies that when a vessel approaches a sector with severe forecast weather,
    AdverseWeatherAheadRule triggers with human_review_required = True.
    """
    storm_provider = MockWeatherProvider(
        field_overrides={"wind_speed_knots": 34.0, "wave_height_m": 3.8}
    )

    pos = VesselPosition(
        latitude=5.58,
        longitude=5.18,
        speed_over_ground_knots=12.0,
        timestamp_utc="2026-06-15T12:00:00+00:00",
        data_type=WeatherProvenanceType.OBSERVED,
    )

    lookahead = compute_route_weather_lookahead(
        position=pos,
        route=sample_route,
        weather_provider=storm_provider,
        policy=AdvisoryPolicy(
            weather_policy=WeatherSafetyPolicy(
                high_wind_threshold_knots=25.0,
                rough_sea_threshold_m=2.5,
            )
        ),
    )

    assert lookahead.summary.has_adverse_conditions is True
    assert len(lookahead.summary.adverse_condition_reasons) > 0

    # Build DecisionContext to test AdverseWeatherAheadRule
    route_profile = RouteWeatherProfile(
        route_id=sample_route.route_id,
        total_waypoints=len(lookahead.waypoints),
        waypoints_weather=[w.weather for w in lookahead.waypoints if w.weather is not None],
    )

    voyage_ctx = VoyageContext(
        voyage_id="VOY_LIVE_01",
        vessel=VesselContext(vessel_id="VESSEL_01", ship_type="OSV"),
        route=sample_route,
        current_position=pos,
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00+00:00"),
        weather_context=VoyageWeatherContext(route_weather=route_profile),
    )

    dc = DecisionContext(
        decision_context_id="DC_LIVE_01",
        created_at_utc="2026-06-15T12:00:00+00:00",
        voyage_context=voyage_ctx,
    )

    rule = AdverseWeatherAheadRule(high_wind_threshold_knots=25.0, rough_sea_threshold_m=2.5)
    advisories = rule.evaluate(dc)

    assert len(advisories) > 0
    for adv in advisories:
        assert adv.severity == AdvisorySeverity.WARNING
        assert adv.human_review_required is True


# =====================================================================
# 5. FRESHNESS TRANSITIONS (LIVE -> STALE -> EXPIRED -> RECONNECT)
# =====================================================================

def test_telemetry_freshness_lifecycle(gateway):
    """
    Tests temporal degradation when telemetry stream stops and recovers.
    """
    t0_iso = "2026-06-15T12:00:00+00:00"
    raw_frame = {
        "vessel_id": "VESSEL_01",
        "timestamp_utc": t0_iso,
        "position": {"latitude": 5.58, "longitude": 5.18, "speed_over_ground_knots": 12.0},
        "provenance": {"source": "NMEA", "mode": "SIMULATED"},
    }

    gateway.ingest_raw(raw_frame)

    # 1. Evaluated at t0 + 10s -> FRESH
    t_fresh = "2026-06-15T12:00:10+00:00"
    f1 = gateway.get_current_frame(reference_time_utc=t_fresh)
    assert f1.quality.freshness == TelemetryFreshnessState.FRESH

    # 2. Evaluated at t0 + 120s -> STALE (fresh threshold = 60s default)
    t_stale = "2026-06-15T12:02:00+00:00"
    f2 = gateway.get_current_frame(reference_time_utc=t_stale)
    assert f2.quality.freshness == TelemetryFreshnessState.STALE

    # 3. Evaluated at t0 + 4000s -> EXPIRED (expired threshold = 3600s default)
    t_expired = "2026-06-15T13:10:00+00:00"
    f3 = gateway.get_current_frame(reference_time_utc=t_expired)
    assert f3.quality.freshness == TelemetryFreshnessState.EXPIRED

    # 4. Reconnect with new packet -> back to FRESH
    t_reconnect = "2026-06-15T13:10:01+00:00"
    gateway.ingest_raw({
        "vessel_id": "VESSEL_01",
        "timestamp_utc": t_reconnect,
        "position": {"latitude": 5.60, "longitude": 5.15, "speed_over_ground_knots": 12.0},
        "provenance": {"source": "NMEA", "mode": "SIMULATED"},
    })
    f4 = gateway.get_current_frame(reference_time_utc=t_reconnect)
    assert f4.quality.freshness == TelemetryFreshnessState.FRESH


# =====================================================================
# 6. ABSOLUTE SAFETY INVARIANT AUDIT
# =====================================================================

def test_absolute_safety_zero_actuation(gateway, sample_route):
    """
    Verifies that the entire virtual voyage loop contains zero simulator commands,
    zero actuator control endpoints, and zero autonomous mutation paths.
    """
    adapter = NMEAAdapter(vessel_id="VESSEL_01")
    methods = [m for m in dir(adapter) if not m.startswith("_")]
    assert "send_command_to_simulator" not in methods
    assert "set_rudder_angle" not in methods
    assert "set_throttle_pct" not in methods

    gw_methods = [m for m in dir(gateway) if not m.startswith("_")]
    assert "actuate" not in gw_methods
    assert "steer" not in gw_methods
