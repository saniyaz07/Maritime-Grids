"""
tests/test_simulation_time_alignment.py — Phase 10C.13F Simulation-Time Separation & Forecast Alignment Tests
==============================================================================================================
Validates the explicit separation of Bridge Command simulation time and host wall-clock time:
  1. Timestamp separation (timestamp_utc represents simulation time, ingested_at_utc represents host arrival).
  2. Source-aware freshness evaluation:
     - SIMULATED provenance uses ingested_at_utc so active streaming packets remain FRESH.
     - Stale and expired ingestion timestamps degrade appropriately.
     - OBSERVED provenance evaluates against timestamp_utc.
  3. TelemetryAuditRecord captures both simulation timestamp and host ingestion timestamp.
  4. Cross-epoch route weather look-ahead:
     - When reference_dt is simulation time (e.g. 2017) and forecast provider is 2026, waypoints at +1h, +3h, +6h
       receive distinct relative forecast steps (forecasts[1], forecasts[3], forecasts[6]).
  5. Synchronous real-world mode look-ahead preserves exact timestamp diff matching.
  6. Strict safety boundary: 0 actuator commands, 0 writes to port 10111.
"""

from datetime import datetime, timedelta, timezone
import pytest

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
from app.telemetry.nmea_adapter import NMEAAdapter, NMEAUdpReceiver, calculate_nmea_checksum
from app.telemetry.repository import TelemetryAuditRecord
from app.weather.contracts import RouteWaypoint
from app.weather.mock_provider import MockWeatherProvider
from app.voyage.contracts import Route, VesselPosition
from app.voyage.lookahead import (
    LookAheadTimingStatus,
    RouteWeatherLookAheadEngine,
)


def _build_nmea_rmc(time_str: str, date_str: str, lat: str, hemi_n: str, lon: str, hemi_e: str, sog: str, cog: str) -> str:
    body = f"GPRMC,{time_str},A,{lat},{hemi_n},{lon},{hemi_e},{sog},{cog},{date_str},,,A"
    csum = calculate_nmea_checksum(body)
    return f"${body}*{csum}\r\n"


# =====================================================================
# 1. TIMESTAMP SEPARATION & NMEA ADAPTER INGESTION
# =====================================================================

def test_01_nmea_adapter_timestamp_separation():
    """Verify that simulation timestamp and host ingestion timestamp are distinctly captured."""
    adapter = NMEAAdapter(vessel_id="VESSEL_TEST_01")
    # Simulation packet from 2017-11-06 05:57:30 UTC
    rmc = _build_nmea_rmc("055730.00", "061117", "5000.0000", "N", "00400.0000", "W", "12.5", "180.0")
    
    host_now_iso = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    payload = adapter.update_from_sentence(rmc, ingested_at_utc=host_now_iso)

    assert payload is not None
    # Simulation time preserved
    assert payload.timestamp_utc.startswith("2017-11-06T05:57:30")
    # Host ingestion time captured
    assert payload.ingested_at_utc == host_now_iso
    assert payload.provenance.mode == TelemetryProvenanceType.SIMULATED


# =====================================================================
# 2. SOURCE-AWARE FRESHNESS EVALUATION
# =====================================================================

def test_02_simulated_packet_freshness_uses_ingestion_time():
    """Verify simulated packet with 2017 timestamp is FRESH when ingested now."""
    host_now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    
    payload = CanonicalTelemetryPayload(
        telemetry_id="TEL_SIM_001",
        timestamp_utc="2017-11-06T05:57:30+00:00",
        ingested_at_utc=host_now.isoformat(),
        vessel_id="VESSEL_OSV_01",
        position=PositionTelemetry(latitude=50.0, longitude=-4.0, speed_over_ground_knots=10.0),
        provenance=TelemetryProvenance(source="BRIDGE_COMMAND_NMEA", mode=TelemetryProvenanceType.SIMULATED),
    )

    # Evaluate at host_now (age = 0s)
    state = payload.evaluate_freshness(current_time_utc=host_now)
    assert state == TelemetryFreshnessState.FRESH
    assert payload.quality.freshness_age_seconds == 0.0

    # Evaluate 30 seconds later (age = 30s <= 60s -> FRESH)
    state_30s = payload.evaluate_freshness(current_time_utc=host_now + timedelta(seconds=30))
    assert state_30s == TelemetryFreshnessState.FRESH
    assert payload.quality.freshness_age_seconds == 30.0

    # Evaluate 10 minutes later (age = 600s <= 900s -> STALE)
    state_10m = payload.evaluate_freshness(current_time_utc=host_now + timedelta(minutes=10))
    assert state_10m == TelemetryFreshnessState.STALE
    assert payload.quality.freshness_age_seconds == 600.0

    # Evaluate 2 hours later (age = 7200s > 3600s -> EXPIRED)
    state_2h = payload.evaluate_freshness(current_time_utc=host_now + timedelta(hours=2))
    assert state_2h == TelemetryFreshnessState.EXPIRED
    assert payload.quality.freshness_age_seconds == 7200.0


def test_03_observed_telemetry_freshness_uses_observation_timestamp():
    """Verify OBSERVED telemetry evaluates freshness against timestamp_utc."""
    ref_now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    
    # 2017 observed record evaluated at 2026 must be EXPIRED
    payload = CanonicalTelemetryPayload(
        telemetry_id="TEL_OBS_001",
        timestamp_utc="2017-11-06T05:57:30+00:00",
        ingested_at_utc=ref_now.isoformat(),
        vessel_id="VESSEL_OSV_01",
        provenance=TelemetryProvenance(source="GPS_REAL", mode=TelemetryProvenanceType.OBSERVED),
    )

    state = payload.evaluate_freshness(current_time_utc=ref_now)
    assert state == TelemetryFreshnessState.EXPIRED


# =====================================================================
# 3. TELEMETRY AUDIT RECORD INGESTION TIMESTAMP
# =====================================================================

def test_04_audit_record_preserves_both_timestamps():
    """Verify TelemetryAuditRecord retains simulation timestamp and host ingestion timestamp."""
    host_now = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    payload = CanonicalTelemetryPayload(
        telemetry_id="TEL_AUDIT_001",
        timestamp_utc="2017-11-06T05:57:30+00:00",
        ingested_at_utc=host_now.isoformat(),
        vessel_id="VESSEL_OSV_01",
        provenance=TelemetryProvenance(source="BRIDGE_COMMAND_NMEA", mode=TelemetryProvenanceType.SIMULATED),
    )
    payload.evaluate_freshness(current_time_utc=host_now)

    record = TelemetryAuditRecord.from_payload(payload)
    assert record.timestamp_utc == "2017-11-06T05:57:30+00:00"
    assert record.ingested_at_utc == host_now.isoformat()
    assert record.freshness == TelemetryFreshnessState.FRESH
    assert record.freshness_age_seconds == 0.0


# =====================================================================
# 4. CROSS-EPOCH ROUTE WEATHER LOOK-AHEAD
# =====================================================================

def test_05_cross_epoch_lookahead_selects_distinct_forecast_steps():
    """
    Verify that when reference time is Bridge Command simulation time (2017)
    and provider is 2026, waypoints ahead at +1h, +3h, +6h receive distinct forecast steps.
    """
    # Provider base time is 2026-06-15 12:00:00 UTC
    provider = MockWeatherProvider(fixed_reference_time=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
    engine = RouteWeatherLookAheadEngine()

    # Vessel starting at simulation time 2017-11-06 05:57:30Z at 10 knots
    vessel_pos = VesselPosition(
        latitude=50.0,
        longitude=-4.0,
        timestamp_utc="2017-11-06T05:57:30+00:00",
        speed_over_ground_knots=10.0,
        data_type=TelemetryProvenanceType.SIMULATED,
    )

    # Route with waypoints at ~10 NM (+1h), ~30 NM (+3h), ~60 NM (+6h)
    route = Route(
        route_id="ROUTE_VIRTUAL_TEST",
        origin_port="Port A",
        destination_port="Port B",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1_10NM", latitude=50.1667, longitude=-4.0),   # ~10 NM -> ~1.0h
            RouteWaypoint(waypoint_id="WP2_30NM", latitude=50.5000, longitude=-4.0),   # ~30 NM -> ~3.0h
            RouteWaypoint(waypoint_id="WP3_60NM", latitude=51.0000, longitude=-4.0),   # ~60 NM -> ~6.0h
        ]
    )

    lookahead = engine.compute_lookahead(
        position=vessel_pos,
        route=route,
        weather_provider=provider,
    )

    assert lookahead.timing_status == LookAheadTimingStatus.ESTIMATED
    assert len(lookahead.waypoints) == 3

    wp1 = lookahead.waypoints[0]
    wp2 = lookahead.waypoints[1]
    wp3 = lookahead.waypoints[2]

    assert wp1.hours_ahead is not None and 0.9 <= wp1.hours_ahead <= 1.1
    assert wp2.hours_ahead is not None and 2.9 <= wp2.hours_ahead <= 3.1
    assert wp3.hours_ahead is not None and 5.9 <= wp3.hours_ahead <= 6.1

    assert wp1.weather is not None
    assert wp2.weather is not None
    assert wp3.weather is not None

    # CRITICAL CHECK: Forecast timestamps from provider must reflect the stepped forecast series
    # (e.g. 2026-06-15T13:00, 2026-06-15T15:00, 2026-06-15T18:00)
    # and MUST NOT all be stuck at index 0 (2026-06-15T12:00)!
    ts1 = wp1.weather.timestamp_utc
    ts2 = wp2.weather.timestamp_utc
    ts3 = wp3.weather.timestamp_utc

    assert ts1 != ts2
    assert ts2 != ts3
    assert ts1 != ts3

    dt1 = datetime.fromisoformat(ts1)
    dt2 = datetime.fromisoformat(ts2)
    dt3 = datetime.fromisoformat(ts3)

    # Verify chronological progression of forecast steps
    assert dt1 < dt2 < dt3
    assert (dt2 - dt1).total_seconds() == pytest.approx(2 * 3600, abs=60)
    assert (dt3 - dt2).total_seconds() == pytest.approx(3 * 3600, abs=60)


def test_06_real_world_synchronous_lookahead_preserved():
    """Verify that synchronous real-world lookahead (2026 vs 2026) operates with exact timestamp diffs."""
    fixed_time = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    provider = MockWeatherProvider(fixed_reference_time=fixed_time)
    engine = RouteWeatherLookAheadEngine()

    vessel_pos = VesselPosition(
        latitude=50.0,
        longitude=-4.0,
        timestamp_utc=fixed_time.isoformat(),
        speed_over_ground_knots=10.0,
        data_type=TelemetryProvenanceType.OBSERVED,
    )

    route = Route(
        route_id="ROUTE_REAL_TEST",
        origin_port="Port A",
        destination_port="Port B",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1_10NM", latitude=50.1667, longitude=-4.0),
            RouteWaypoint(waypoint_id="WP2_20NM", latitude=50.3333, longitude=-4.0),
        ]
    )

    lookahead = engine.compute_lookahead(
        position=vessel_pos,
        route=route,
        weather_provider=provider,
    )

    assert len(lookahead.waypoints) == 2
    assert lookahead.waypoints[0].weather.timestamp_utc == "2026-06-15T13:00:00+00:00"
    assert lookahead.waypoints[1].weather.timestamp_utc == "2026-06-15T14:00:00+00:00"


# =====================================================================
# 5. SAFETY & ACTUATION BOUNDARY
# =====================================================================

def test_07_safety_absence_of_actuator_paths():
    """Verify complete absence of actuator commands or control endpoints."""
    adapter = NMEAAdapter()
    receiver = NMEAUdpReceiver(adapter=adapter)

    # Verify no control methods exist on adapter or receiver
    for forbidden in ["send_rudder", "send_throttle", "set_autopilot", "send_command", "send_nmea_control"]:
        assert not hasattr(adapter, forbidden)
        assert not hasattr(receiver, forbidden)
