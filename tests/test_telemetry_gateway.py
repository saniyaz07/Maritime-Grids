"""
tests/test_telemetry_gateway.py — Phase 10C.12 Telemetry Gateway API Test Suite
==============================================================================
Verifies:
  1. POST /api/v1/operator/telemetry/ingest
  2. GET /api/v1/operator/telemetry/current
  3. GET /api/v1/operator/telemetry/simulated/{scenario_id}
  4. POST /api/v1/operator/telemetry/validate
  5. Zero actuator endpoints in router.
"""

from datetime import datetime, timezone
import pytest
from starlette.testclient import TestClient

from app.api.app import create_app
from app.telemetry.contracts import EngineOperationalState, TelemetryFreshnessState


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_01_telemetry_current_endpoint(client):
    """Verify GET /api/v1/operator/telemetry/current returns valid canonical frame."""
    res = client.get("/api/v1/operator/telemetry/current")
    assert res.status_code == 200
    data = res.json()
    assert "telemetry_id" in data
    assert "vessel_id" in data
    assert "position" in data
    assert "engine" in data
    assert "energy" in data
    assert "quality" in data
    assert "provenance" in data


def test_02_telemetry_simulated_scenario_endpoint(client):
    """Verify GET /api/v1/operator/telemetry/simulated/{scenario_id} loads and returns scenarios."""
    # Scenario B: Engine OFF
    res_b = client.get("/api/v1/operator/telemetry/simulated/B")
    assert res_b.status_code == 200
    data_b = res_b.json()
    assert data_b["engine"]["state"] == "OFF"
    assert data_b["provenance"]["mode"] == "SIMULATED"

    # Scenario C: Engine UNKNOWN
    res_c = client.get("/api/v1/operator/telemetry/simulated/C")
    assert res_c.status_code == 200
    data_c = res_c.json()
    assert data_c["engine"]["state"] == "UNKNOWN"

    # Scenario D: Missing Speed
    res_d = client.get("/api/v1/operator/telemetry/simulated/D")
    assert res_d.status_code == 200
    data_d = res_d.json()
    assert data_d["position"]["speed_over_ground_knots"] is None

    # Invalid scenario identifier -> 422 or 500
    res_bad = client.get("/api/v1/operator/telemetry/simulated/UNKNOWN_SCENARIO")
    assert res_bad.status_code in (400, 422, 500)


def test_03_telemetry_ingest_endpoint(client):
    """Verify POST /api/v1/operator/telemetry/ingest updates gateway buffer."""
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = {
        "telemetry_id": "TEL_INGEST_TEST_01",
        "timestamp_utc": now_iso,
        "vessel_id": "VESSEL_INGEST_01",
        "position": {
            "latitude": 6.12,
            "longitude": 3.55,
            "speed_over_ground_knots": 13.5,
            "course_over_ground_deg": 190.0,
        },
        "engine": {
            "state": "ON",
            "rpm": 1600.0,
            "load_percent": 80.0,
        },
        "energy": {
            "fuel_remaining_liters": 12000.0,
            "battery_soc_pct": 65.0,
        },
    }

    res = client.post("/api/v1/operator/telemetry/ingest?source=TEST_RUNNER&mode=OBSERVED", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["telemetry_id"] == "TEL_INGEST_TEST_01"
    assert data["position"]["speed_over_ground_knots"] == 13.5
    assert data["engine"]["state"] == "ON"
    assert data["provenance"]["mode"] == "OBSERVED"

    # Verify current endpoint now returns this frame
    res_curr = client.get("/api/v1/operator/telemetry/current")
    assert res_curr.status_code == 200
    curr_data = res_curr.json()
    assert curr_data["telemetry_id"] == "TEL_INGEST_TEST_01"


def test_04_telemetry_validate_endpoint(client):
    """Verify POST /api/v1/operator/telemetry/validate returns validation diagnostics without modifying gateway."""
    raw_invalid = {
        "latitude": 999.0, # Impossible
        "battery_soc_pct": 500.0, # Impossible
    }
    res = client.post("/api/v1/operator/telemetry/validate", json=raw_invalid)
    assert res.status_code == 200
    data = res.json()
    assert data["quality"]["overall"] == "INVALID"
    assert len(data["quality"]["validation_errors"]) > 0


def test_05_safety_zero_actuator_routes(client):
    """Safety Audit: Verify router contains zero engine/throttle/steering actuation endpoints."""
    app = create_app()
    forbidden_terms = ["engine/start", "engine/stop", "engine/control", "actuator", "throttle", "steering"]
    
    for route in app.routes:
        path = getattr(route, "path", "").lower()
        for term in forbidden_terms:
            assert term not in path, f"Forbidden actuation route found: {path}"
