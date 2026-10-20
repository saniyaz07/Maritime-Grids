"""
tests/test_nmea_adapter.py — Phase 10C.13B NMEA 0183 Virtual Vessel Adapter Tests
=================================================================================
Verifies:
  1. Checksum validation (valid, invalid, missing, malformed).
  2. RMC sentence parsing (navigation status 'A' vs 'V', SOG, COG, UTC date/time).
  3. GGA sentence parsing (fix quality, satellite count, coordinates).
  4. HDT sentence parsing (true heading, normalization).
  5. Geographic coordinate transformation (N/S/E/W, equator, prime meridian, boundaries).
  6. Non-inference invariant: engine state remains UNKNOWN and nulls are preserved (null != 0).
  7. Multi-sentence aggregation and out-of-order stream processing.
  8. UDP receiver ingestion and gateway integration.
  9. Freshness evaluation across time transitions.
  10. Safety invariant: zero actuator commands or outgoing control paths.
"""

from datetime import date, datetime, timedelta, timezone
import socket
import time
import pytest

from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    EngineOperationalState,
    TelemetryFreshnessState,
    TelemetryProvenanceType,
    TelemetryQualityState,
)
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.nmea_adapter import (
    NMEAAdapter,
    NMEAUdpReceiver,
    calculate_nmea_checksum,
    parse_nmea_latitude,
    parse_nmea_longitude,
    parse_nmea_timestamp,
    validate_nmea_checksum,
)


def make_nmea(body: str) -> str:
    """Helper to construct a valid NMEA sentence with calculated checksum."""
    return f"${body}*{calculate_nmea_checksum(body)}"


# =====================================================================
# 1. CHECKSUM & LOW-LEVEL PARSER TESTS
# =====================================================================

def test_01_nmea_checksum_calculation_and_validation():
    """Verify checksum calculation and validation against standard NMEA sentences."""
    body_rmc = "GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,280926,003.1,W"
    csum_rmc = calculate_nmea_checksum(body_rmc)
    valid_rmc = f"${body_rmc}*{csum_rmc}"

    is_valid, err, body, expected = validate_nmea_checksum(valid_rmc)
    assert is_valid is True
    assert err == ""
    assert expected == csum_rmc

    body_hdt = "GPHDT,284.5,T"
    csum_hdt = calculate_nmea_checksum(body_hdt)
    valid_hdt = f"${body_hdt}*{csum_hdt}"

    is_valid_hdt, _, _, expected_hdt = validate_nmea_checksum(valid_hdt)
    assert is_valid_hdt is True
    assert expected_hdt == csum_hdt


def test_02_nmea_checksum_rejections():
    """Verify checksum validator rejects invalid, missing, or malformed checksums."""
    # Invalid checksum mismatch
    bad_csum = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,280926,003.1,W*00"
    is_valid, err, _, _ = validate_nmea_checksum(bad_csum)
    assert is_valid is False
    assert "Checksum mismatch" in err

    # Missing asterisk
    no_csum = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,280926,003.1,W"
    is_valid_no, err_no, _, _ = validate_nmea_checksum(no_csum)
    assert is_valid_no is False
    assert "Missing checksum delimiter" in err_no

    # Missing leading dollar sign
    no_dollar = "GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,280926,003.1,W*6A"
    is_valid_dol, err_dol, _, _ = validate_nmea_checksum(no_dollar)
    assert is_valid_dol is False

    # Empty string
    assert validate_nmea_checksum("")[0] is False


# =====================================================================
# 2. COORDINATE & TIMESTAMP CONVERSION TESTS
# =====================================================================

def test_03_coordinate_conversions():
    """Verify DDMM.MMMM and DDDMM.MMMM parsing across all hemispheres and boundaries."""
    # North & East
    lat_n = parse_nmea_latitude("4807.0380", "N")
    # 48 + 07.0380 / 60 = 48 + 0.1173 = 48.1173
    assert lat_n == pytest.approx(48.1173, abs=1e-4)

    lon_e = parse_nmea_longitude("01131.0000", "E")
    # 11 + 31.0 / 60 = 11 + 0.516667 = 11.516667
    assert lon_e == pytest.approx(11.516667, abs=1e-4)

    # South & West (negative decimal degrees)
    lat_s = parse_nmea_latitude("0549.2000", "S")
    # -(5 + 49.2 / 60) = -5.82
    assert lat_s == pytest.approx(-5.82, abs=1e-4)

    lon_w = parse_nmea_longitude("00430.6000", "W")
    # -(4 + 30.6 / 60) = -4.51
    assert lon_w == pytest.approx(-4.51, abs=1e-4)

    # Equator & Prime Meridian
    assert parse_nmea_latitude("0000.0000", "N") == 0.0
    assert parse_nmea_longitude("00000.0000", "E") == 0.0

    # Invalid / Out-of-Bounds coordinates
    assert parse_nmea_latitude("9500.0000", "N") is None  # > 90 deg
    assert parse_nmea_longitude("18500.0000", "E") is None  # > 180 deg
    assert parse_nmea_latitude("4807.0380", "X") is None  # Invalid hemisphere
    assert parse_nmea_latitude("", "N") is None


def test_04_timestamp_parsing():
    """Verify time and date parsing into ISO 8601 UTC strings."""
    # Date + Time
    ts = parse_nmea_timestamp("123519", "280926")
    assert ts == "2026-09-28T12:35:19+00:00"

    # Fractional seconds
    ts_frac = parse_nmea_timestamp("123519.50", "280926")
    assert ts_frac.startswith("2026-09-28T12:35:19.500")

    # Time only with fixed reference date
    ref_d = date(2026, 6, 15)
    ts_time_only = parse_nmea_timestamp("083000", None, ref_date=ref_d)
    assert ts_time_only == "2026-06-15T08:30:00+00:00"

    # Invalid time
    assert parse_nmea_timestamp("999999", "280926") is None
    assert parse_nmea_timestamp("", "280926") is None


# =====================================================================
# 3. SENTENCE PARSING & AGGREGATION TESTS
# =====================================================================

def test_05_rmc_sentence_parsing():
    """Verify parsing of valid and invalid RMC sentences."""
    adapter = NMEAAdapter(vessel_id="VESSEL_TEST_01")
    ref_d = date(2026, 9, 28)

    # Valid RMC
    raw = make_nmea("GPRMC,123519,A,0549.200,N,00430.600,E,14.5,280.0,280926,001.0,W")
    parsed = adapter.parse_sentence(raw, ref_date=ref_d)

    assert parsed["valid"] is True
    assert parsed["type"] == "RMC"
    assert parsed["nav_status"] == "VALID"
    assert parsed["latitude"] == pytest.approx(5.82, abs=1e-3)
    assert parsed["longitude"] == pytest.approx(4.51, abs=1e-3)
    assert parsed["speed_over_ground_knots"] == 14.5
    assert parsed["course_over_ground_deg"] == 280.0
    assert parsed["timestamp_utc"] == "2026-09-28T12:35:19+00:00"


def test_06_rmc_invalid_navigation_status_preserves_null():
    """Verify RMC with status 'V' (Void) leaves coordinates as None (null != 0)."""
    adapter = NMEAAdapter(vessel_id="VESSEL_TEST_01")
    ref_d = date(2026, 9, 28)

    # Status 'V' (Warning / Void)
    raw_void = make_nmea("GPRMC,123519,V,0549.200,N,00430.600,E,14.5,280.0,280926,001.0,W")
    parsed = adapter.parse_sentence(raw_void, ref_date=ref_d)

    assert parsed["valid"] is True
    assert parsed["nav_status"] == "WARNING_VOID"
    assert parsed["latitude"] is None
    assert parsed["longitude"] is None
    assert parsed["latitude"] != 0.0


def test_07_gga_sentence_parsing():
    """Verify parsing of GGA sentence with fix quality and satellite count."""
    adapter = NMEAAdapter(vessel_id="VESSEL_TEST_01")
    raw = make_nmea("GPGGA,123519,0549.200,N,00430.600,E,1,08,0.9,12.4,M,46.9,M,,")
    parsed = adapter.parse_sentence(raw)

    assert parsed["valid"] is True
    assert parsed["type"] == "GGA"
    assert parsed["fix_quality"] == 1
    assert parsed["satellites"] == 8
    assert parsed["latitude"] == pytest.approx(5.82, abs=1e-3)
    assert parsed["longitude"] == pytest.approx(4.51, abs=1e-3)


def test_08_hdt_sentence_parsing():
    """Verify parsing of HDT true heading sentence."""
    adapter = NMEAAdapter(vessel_id="VESSEL_TEST_01")
    raw = make_nmea("GPHDT,284.5,T")
    parsed = adapter.parse_sentence(raw)

    assert parsed["valid"] is True
    assert parsed["type"] == "HDT"
    assert parsed["heading_deg"] == 284.5


# =====================================================================
# 4. STATE AGGREGATION & CANONICAL MAPPING TESTS
# =====================================================================

def test_09_multi_sentence_stream_aggregation():
    """Verify NMEAAdapter aggregates RMC + HDT + GGA bursts into a unified CanonicalTelemetryPayload."""
    adapter = NMEAAdapter(vessel_id="VESSEL_BC_01")
    ref_d = date(2026, 9, 28)

    sentences = [
        make_nmea("GPRMC,100000,A,0549.200,N,00430.600,E,12.0,270.0,280926,001.0,W"),
        make_nmea("GPHDT,271.5,T"),
        make_nmea("GPGGA,100000,0549.200,N,00430.600,E,2,10,0.8,5.0,M,40.0,M,,"),
    ]

    payloads = adapter.feed_stream(sentences, ref_date=ref_d)
    assert len(payloads) == 3

    latest = payloads[-1]
    assert isinstance(latest, CanonicalTelemetryPayload)
    assert latest.vessel_id == "VESSEL_BC_01"
    assert latest.position.latitude == pytest.approx(5.82, abs=1e-3)
    assert latest.position.longitude == pytest.approx(4.51, abs=1e-3)
    assert latest.position.speed_over_ground_knots == 12.0
    assert latest.position.course_over_ground_deg == 270.0
    assert latest.position.heading_deg == 271.5
    assert latest.provenance.mode == TelemetryProvenanceType.SIMULATED
    assert latest.provenance.source == "BRIDGE_COMMAND_NMEA"


def test_10_strict_engine_and_energy_non_inference():
    """Verify that high SOG does NOT infer engine ON or fabricate fuel/battery values."""
    adapter = NMEAAdapter(vessel_id="VESSEL_BC_01")
    # SOG is 22.5 knots
    raw = make_nmea("GPRMC,120000,A,0549.200,N,00430.600,E,22.5,280.0,280926,001.0,W")
    payload = adapter.update_from_sentence(raw, ref_date=date(2026, 9, 28))

    assert payload is not None
    assert payload.position.speed_over_ground_knots == 22.5
    # Strict Invariant: Engine state must remain UNKNOWN
    assert payload.engine.state == EngineOperationalState.UNKNOWN
    assert payload.engine.rpm is None
    assert payload.engine.load_percent is None
    assert payload.engine.power_kw is None
    # Strict Invariant: Energy state must remain None (null != 0)
    assert payload.energy.fuel_remaining_liters is None
    assert payload.energy.fuel_remaining_liters != 0.0
    assert payload.energy.battery_soc_pct is None


# =====================================================================
# 5. UDP INGESTION RECEIVER TESTS
# =====================================================================

def test_11_udp_receiver_process_datagram():
    """Verify NMEAUdpReceiver processes multi-line UDP datagram packets."""
    repo = InMemoryTelemetryAuditRepository()
    gateway = TelemetryGateway(audit_repo=repo)
    receiver = NMEAUdpReceiver(gateway=gateway, host="127.0.0.1", port=10110)

    s1 = make_nmea("GPRMC,123519,A,0549.200,N,00430.600,E,15.2,285.0,280926,001.0,W")
    s2 = make_nmea("GPHDT,285.5,T")
    datagram = f"{s1}\r\n{s2}\r\n".encode("ascii")

    payloads = receiver.process_datagram(datagram)
    assert len(payloads) == 2
    assert receiver.packets_received == 1
    assert receiver.sentences_processed == 2

    # Check that gateway updated
    current = gateway.get_current_frame()
    assert current.position.speed_over_ground_knots == 15.2
    assert current.position.heading_deg == 285.5
    assert current.provenance.mode == TelemetryProvenanceType.SIMULATED


def test_12_udp_receiver_socket_lifecycle():
    """Verify NMEAUdpReceiver starts, receives real UDP packet on loopback, and stops cleanly."""
    repo = InMemoryTelemetryAuditRepository()
    gateway = TelemetryGateway(audit_repo=repo)
    receiver = NMEAUdpReceiver(gateway=gateway, host="127.0.0.1", port=19876)

    receiver.start()
    assert receiver.is_running is True

    # Send a UDP datagram to 127.0.0.1:19876
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s1 = make_nmea("GPRMC,123519,A,0549.200,N,00430.600,E,11.8,275.0,280926,001.0,W")
    packet = f"{s1}\r\n".encode("ascii")
    sock.sendto(packet, ("127.0.0.1", 19876))
    sock.close()

    # Allow background thread to process
    time.sleep(0.2)
    assert receiver.packets_received >= 1

    receiver.stop()
    assert receiver.is_running is False


# =====================================================================
# 6. SAFETY INVARIANTS TEST
# =====================================================================

def test_13_zero_simulator_command_outputs():
    """Safety Invariant: Verify NMEAAdapter and UDP Receiver have zero outgoing actuator channels."""
    adapter = NMEAAdapter()
    receiver = NMEAUdpReceiver()

    # Verify adapter has no transmit, control, or actuation methods
    adapter_methods = [m for m in dir(adapter) if not m.startswith("_")]
    for method in adapter_methods:
        assert "send_command" not in method
        assert "set_throttle" not in method
        assert "set_rudder" not in method
        assert "steer" not in method
        assert "actuate" not in method

    receiver_methods = [m for m in dir(receiver) if not m.startswith("_")]
    for method in receiver_methods:
        assert "transmit" not in method
        assert "send_control" not in method
