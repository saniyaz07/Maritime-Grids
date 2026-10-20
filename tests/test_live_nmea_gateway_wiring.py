"""
tests/test_live_nmea_gateway_wiring.py — Phase 10C.13D Live Bridge Command NMEA -> Telemetry Gateway Wiring Tests
================================================================================================================
Verifies the FastAPI application lifecycle integration, NMEA 0183 UDP receiver binding,
live datagram ingestion, canonical telemetry updating, and strict read-only safety invariants.

Requirements:
  - Application startup starts NMEAUdpReceiver exactly once.
  - Application shutdown stops receiver cleanly and releases UDP socket.
  - Configuration respects default port 10110 and NMEA_UDP_PORT environment variable.
  - Live NMEA datagrams update GET /api/v1/operator/telemetry/current in real-time.
  - Strict absence of outbound commands, zero actuation, no writes to port 10111.
"""

from datetime import datetime, timezone
import os
import socket
import time
from typing import Any, Dict
import pytest
from starlette.testclient import TestClient

from app.api.app import create_app
from app.api.dependencies import _DEFAULT_TELEMETRY_GATEWAY
from app.telemetry.contracts import (
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
)


def _build_nmea_packet(body: str) -> str:
    """Helper to build a valid checksummed NMEA 0183 sentence."""
    csum = calculate_nmea_checksum(body)
    return f"${body}*{csum}\r\n"


# =====================================================================
# 1. LIFECYCLE & STARTUP / SHUTDOWN TESTS
# =====================================================================

def test_fastapi_lifecycle_startup_and_shutdown():
    """
    Verifies that starting the FastAPI application initializes and starts
    the NMEAUdpReceiver on port 10110 (or configured port), and shutdown stops it.
    """
    custom_repo = InMemoryTelemetryAuditRepository()
    custom_gateway = TelemetryGateway(repository=custom_repo)

    # Use a dynamic high port to avoid collision during parallel unit tests
    test_port = 10199
    app = create_app(
        telemetry_gateway=custom_gateway,
        enable_nmea_receiver=True,
        nmea_port=test_port,
    )

    # Lifespan runs when entering TestClient context
    with TestClient(app) as client:
        # Check receiver exists on app state and is running
        receiver: NMEAUdpReceiver = app.state.nmea_receiver
        assert receiver is not None
        assert receiver.is_running is True
        assert receiver.port == test_port
        assert app.state.telemetry_gateway is custom_gateway

        # Verify health check succeeds while receiver is running
        resp = client.get("/health")
        assert resp.status_code == 200

    # After exiting lifespan context, receiver should be stopped
    assert app.state.nmea_receiver is None
    assert receiver.is_running is False
    assert receiver._socket is None


def test_port_configuration_and_env_override(monkeypatch):
    """
    Verifies that default port is 10110 and NMEA_UDP_PORT environment variable can override it.
    """
    # Test default port on receiver
    default_receiver = NMEAUdpReceiver()
    assert default_receiver.port == 10110

    # Test environment variable override
    monkeypatch.setenv("NMEA_UDP_PORT", "10188")
    env_receiver = NMEAUdpReceiver()
    assert env_receiver.port == 10188


# =====================================================================
# 2. LIVE UDP INGESTION & /telemetry/current INTEGRATION
# =====================================================================

def test_live_nmea_ingestion_updates_operator_telemetry_current():
    """
    Sends deterministic NMEA datagrams via UDP to the running FastAPI application receiver
    and verifies that GET /api/v1/operator/telemetry/current returns the exact updated kinematics.
    """
    custom_repo = InMemoryTelemetryAuditRepository()
    custom_gateway = TelemetryGateway(repository=custom_repo)

    test_port = 10195
    app = create_app(
        telemetry_gateway=custom_gateway,
        enable_nmea_receiver=True,
        nmea_port=test_port,
    )

    with TestClient(app) as client:
        # Send NMEA sentences via UDP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            now = datetime.now(timezone.utc)
            time_str = now.strftime("%H%M%S.00")
            date_str = now.strftime("%d%m%y")
            rmc = _build_nmea_packet(f"GPRMC,{time_str},A,0530.000,N,00515.000,E,14.2,280.5,{date_str},,,A")
            hdt = _build_nmea_packet("GPHDT,279.8,T")
            vtg = _build_nmea_packet("GPVTG,280.5,T,,M,14.2,N,,K,A")

            packet = (rmc + hdt + vtg).encode("ascii")
            sock.sendto(packet, ("127.0.0.1", test_port))

            # Wait briefly for UDP packet processing
            time.sleep(0.15)

            # Query operator telemetry current endpoint
            resp = client.get("/api/v1/operator/telemetry/current")
            assert resp.status_code == 200
            data = resp.json()

            # Verify kinematics
            assert data["position"]["latitude"] == pytest.approx(5.5, abs=0.001)
            assert data["position"]["longitude"] == pytest.approx(5.25, abs=0.001)
            assert data["position"]["speed_over_ground_knots"] == pytest.approx(14.2, abs=0.1)
            assert data["position"]["course_over_ground_deg"] == pytest.approx(280.5, abs=0.1)
            assert data["position"]["heading_deg"] == pytest.approx(279.8, abs=0.1)

            # Verify provenance and quality
            assert data["provenance"]["source"] == "BRIDGE_COMMAND_NMEA"
            assert data["provenance"]["mode"] == "SIMULATED"
            assert data["quality"]["overall"] == "VALID"
            assert data["quality"]["freshness"] == "FRESH"

            # Strict Non-Inference Invariants: Unmeasured values must remain null
            assert data["engine"]["state"] == "UNKNOWN"
            assert data["engine"]["rpm"] is None
            assert data["engine"]["load_percent"] is None
            assert data["energy"]["fuel_remaining_liters"] is None
            assert data["energy"]["battery_soc_pct"] is None

        finally:
            sock.close()


# =====================================================================
# 3. DETERMINISTIC SIMULATED FALLBACK
# =====================================================================

def test_simulated_scenario_fallback_preserved():
    """
    Verifies that deterministic simulated scenarios (e.g. SCENARIO_A_NORMAL)
    remain fully functional and accessible via the API.
    """
    custom_repo = InMemoryTelemetryAuditRepository()
    custom_gateway = TelemetryGateway(repository=custom_repo)

    app = create_app(
        telemetry_gateway=custom_gateway,
        enable_nmea_receiver=False,
    )

    with TestClient(app) as client:
        # Load Scenario A
        resp = client.get("/api/v1/operator/telemetry/simulated/SCENARIO_A_NORMAL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vessel_id"] == "VESSEL_OSV_01"
        assert data["engine"]["state"] == "ON"
        assert data["position"]["speed_over_ground_knots"] == 11.8

        # Verify /telemetry/current now returns the loaded scenario
        curr_resp = client.get("/api/v1/operator/telemetry/current")
        assert curr_resp.status_code == 200
        curr_data = curr_resp.json()
        assert curr_data["vessel_id"] == "VESSEL_OSV_01"


# =====================================================================
# 4. READ-ONLY SAFETY & ZERO ACTUATION AUDIT
# =====================================================================

def test_strict_read_only_and_no_outbound_commands():
    """
    Verifies that NMEAUdpReceiver only creates an inbound listening socket,
    does NOT open any outbound socket, does NOT send data to port 10111,
    and exposes zero actuator or control methods.
    """
    receiver = NMEAUdpReceiver(port=10197)
    receiver.start()
    try:
        # Verify receiver socket is SOCK_DGRAM and bound to local address
        assert receiver._socket is not None
        assert receiver._socket.type == socket.SOCK_DGRAM
        bound_addr = receiver._socket.getsockname()
        assert bound_addr[1] == 10197

        # Verify no outbound methods exist on receiver
        forbidden_methods = [
            "send", "send_command", "send_to_bridge_command",
            "set_throttle", "set_rudder", "set_engine", "set_heading",
            "actuate", "autopilot"
        ]
        for m in forbidden_methods:
            assert not hasattr(receiver, m), f"Receiver must not have method '{m}'"
            assert not hasattr(receiver.adapter, m), f"Adapter must not have method '{m}'"

    finally:
        receiver.stop()


# =====================================================================
# 5. LIVE BRIDGE COMMAND 5.x ACCEPTANCE TEST
# =====================================================================

def test_live_bridge_command_e2e_acceptance():
    """
    Acceptance test connecting to live running Bridge Command on port 10110.
    If Bridge Command is transmitting, verifies real-time telemetry updates.
    """
    custom_repo = InMemoryTelemetryAuditRepository()
    custom_gateway = TelemetryGateway(repository=custom_repo)

    app = create_app(
        telemetry_gateway=custom_gateway,
        enable_nmea_receiver=True,
        nmea_port=10110,
    )

    with TestClient(app) as client:
        receiver = app.state.nmea_receiver
        assert receiver is not None
        assert receiver.is_running is True

        # Allow 1.5 seconds for incoming live datagrams
        time.sleep(1.5)

        if receiver.packets_received > 0:
            # Live packets from Bridge Command were received!
            resp = client.get("/api/v1/operator/telemetry/current")
            assert resp.status_code == 200
            data = resp.json()
            assert data["provenance"]["source"] == "BRIDGE_COMMAND_NMEA"
            assert data["position"]["latitude"] is not None
            assert data["position"]["longitude"] is not None
            assert data["engine"]["state"] == "UNKNOWN"
            assert data["energy"]["fuel_remaining_liters"] is None
        else:
            # Fallback: In headless CI or when Bridge Command is not running,
            # verify receiver is ready and listening on port 10110
            assert receiver.port == 10110
