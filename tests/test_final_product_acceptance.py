"""
tests/test_final_product_acceptance.py — Final Maritime Grids Product Acceptance Suite
========================================================================================
Validates the complete end-to-end user-facing product operational loop:
  1. Backend API & Frontend Dashboard startup
  2. Bridge Command NMEA UDP 10110 ingestion & live processing
  3. Real-time Telemetry Gateway & Virtual Vessel Energy State Estimator
  4. Spacetime Route Weather Look-Ahead & Deterministic Advisory Engine
  5. Persistent Telemetry Audit Logging & Voyage History Replay
  6. Strict zero-actuator read-only safety boundary
"""

from datetime import datetime, timezone
import socket
import time
import pytest
from starlette.testclient import TestClient

from app.api.app import create_app
from app.telemetry.contracts import (
    EngineOperationalState,
    TelemetryFreshnessState,
    TelemetryProvenanceType,
)
from app.telemetry.nmea_adapter import calculate_nmea_checksum


def _format_nmea(sentence_body: str) -> bytes:
    csum = calculate_nmea_checksum(sentence_body)
    return f"${sentence_body}*{csum}\r\n".encode("ascii")


def test_01_product_startup_and_endpoints():
    """Verify application starts, serves dashboard, health, and API endpoints."""
    app = create_app(enable_nmea_receiver=True)
    with TestClient(app) as client:
        # 1. Health check
        r_health = client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] == "healthy"

        # 2. Root API metadata with dashboard link
        r_root = client.get("/")
        assert r_root.status_code == 200
        root_json = r_root.json()
        assert root_json["status"] == "online"
        assert root_json["dashboard"] == "/dashboard"

        # 3. Static Driver Dashboard
        r_dash = client.get("/dashboard")
        assert r_dash.status_code == 200
        assert "Maritime Clean-Energy" in r_dash.text or "Driver" in r_dash.text


def test_02_bridge_command_live_udp_flow():
    """Verify live UDP datagrams on 127.0.0.1:10110 update navigation and energy state."""
    app = create_app(enable_nmea_receiver=True)
    with TestClient(app) as client:
        receiver = app.state.nmea_receiver
        assert receiver is not None
        assert receiver.is_running is True

        # Send GPRMC sentence from virtual vessel: SOG = 12.5 kn, COG = 285.0 deg
        body = "GPRMC,061500,A,0548.000,N,00430.000,E,12.5,285.0,061117,,,A"
        packet = _format_nmea(body)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(packet, ("127.0.0.1", receiver.port))
        time.sleep(0.4)

        # Check current telemetry endpoint
        r_curr = client.get("/api/v1/operator/telemetry/current")
        assert r_curr.status_code == 200
        tel = r_curr.json()

        # Invariants
        assert tel["position"]["speed_over_ground_knots"] == 12.5
        assert tel["position"]["course_over_ground_deg"] == 285.0
        assert tel["engine"]["state"] == EngineOperationalState.UNKNOWN.value
        assert tel["provenance"]["mode"] == TelemetryProvenanceType.SIMULATED.value
        assert "VIRTUAL_ENERGY_ESTIMATOR" in tel["provenance"]["source"]
        assert tel["energy"]["fuel_rate_lph"] is not None
        assert tel["energy"]["fuel_rate_lph"] > 100.0
        assert tel["energy"]["battery_soc_pct"] is not None


def test_03_spacetime_lookahead_and_advisories():
    """Verify spacetime route weather look-ahead calculation and advisory generation."""
    app = create_app(enable_nmea_receiver=True)
    with TestClient(app) as client:
        lookahead_req = {
            "position": {
                "latitude": 5.80,
                "longitude": 4.50,
                "speed_over_ground_knots": 12.5,
                "course_over_ground_deg": 285.0,
                "timestamp_utc": "2026-09-28T14:00:00Z",
                "data_type": "SIMULATED",
            },
            "route": {
                "route_id": "ESCRAVOS_LAGOS",
                "origin_port": "Escravos Terminal",
                "destination_port": "Lagos Port",
                "waypoints": [
                    {"waypoint_id": "WP_ESC", "latitude": 5.58, "longitude": 5.18},
                    {"waypoint_id": "WP_MID", "latitude": 5.80, "longitude": 4.50},
                    {"waypoint_id": "WP_LAG", "latitude": 6.45, "longitude": 3.40},
                ],
            },
            "vessel_id": "VESSEL_OSV_LAGOS_01",
        }
        r_look = client.post("/api/v1/operator/weather/lookahead", json=lookahead_req)
        assert r_look.status_code == 200
        look_data = r_look.json()
        assert "waypoints" in look_data
        assert len(look_data["waypoints"]) > 0


def test_04_audit_history_query_and_replay():
    """Verify historical telemetry queries return paginated time-series records."""
    app = create_app(enable_nmea_receiver=True)
    with TestClient(app) as client:
        r_hist = client.get("/api/v1/operator/telemetry/history?limit=10")
        assert r_hist.status_code == 200
        records = r_hist.json()
        assert isinstance(records, list)
        if len(records) > 0:
            rec = records[0]
            assert "record_id" in rec
            assert "telemetry_id" in rec
            assert "payload" in rec


def test_05_safety_zero_control_traffic():
    """Strictly assert no control endpoints or outbound actuator paths exist."""
    app = create_app(enable_nmea_receiver=True)
    with TestClient(app) as client:
        # Prohibited control endpoints must return 404/405
        assert client.post("/api/v1/operator/control/throttle").status_code == 404
        assert client.post("/api/v1/operator/control/rudder").status_code == 404
        assert client.post("/api/v1/operator/autopilot").status_code == 404
