"""
tests/test_state_api.py — Phase 10C.10 Persistent State API Endpoints Verification Suite
========================================================================================
Comprehensive test suite verifying persistent voyage REST endpoints (/api/v1/operator/voyages),
status codes (201, 200, 204, 404, 409, 422), optimistic concurrency, and security audits.
"""

import inspect
import pytest
from starlette.testclient import TestClient

from app.api.app import create_app
from app.state.contracts import (
    PersistedVoyageState,
    StateUpdateRequest,
)
from app.state.memory_repository import InMemoryStateRepository
from app.voyage.contracts import (
    Route,
    RouteWaypoint,
    VesselPosition,
    VoyageStatus,
)


@pytest.fixture
def memory_repo() -> InMemoryStateRepository:
    return InMemoryStateRepository()


@pytest.fixture
def client(memory_repo: InMemoryStateRepository) -> TestClient:
    app = create_app(state_repository=memory_repo)
    return TestClient(app)


def create_sample_payload(voyage_id: str = "VOY_API_001") -> dict:
    return {
        "voyage_id": voyage_id,
        "vessel_id": "VESSEL_OSV_01",
        "ship_type": "Oil Service Boat",
        "route_id": "ESCRAVOS_LAGOS",
        "status": "PLANNED",
        "state_version": 1,
        "created_at_utc": "2026-06-15T12:00:00Z",
        "updated_at_utc": "2026-06-15T12:00:00Z",
        "current_position": {
            "latitude": 5.80,
            "longitude": 4.50,
            "timestamp_utc": "2026-06-15T12:00:00Z",
            "speed_over_ground_knots": 12.0,
        },
        "route": {
            "route_id": "ESCRAVOS_LAGOS",
            "origin_port": "Escravos Terminal",
            "destination_port": "Lagos Port",
            "waypoints": [
                {"waypoint_id": "WP1", "latitude": 5.58, "longitude": 5.18},
                {"waypoint_id": "WP2", "latitude": 5.80, "longitude": 4.50},
            ],
            "total_distance_nm": 130.0,
        },
    }


def test_01_create_persisted_voyage_state(client: TestClient):
    """Verify POST /api/v1/operator/voyages creates state and returns HTTP 201."""
    payload = create_sample_payload("VOY_CREATE_01")
    resp = client.post("/api/v1/operator/voyages", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["voyage_id"] == "VOY_CREATE_01"
    assert data["vessel_id"] == "VESSEL_OSV_01"
    assert data["state_version"] == 1


def test_02_create_duplicate_voyage_returns_409(client: TestClient):
    """Verify POST duplicate voyage_id returns HTTP 409 Conflict with structured APIErrorResponse."""
    payload = create_sample_payload("VOY_DUP_01")
    resp1 = client.post("/api/v1/operator/voyages", json=payload)
    assert resp1.status_code == 201

    resp2 = client.post("/api/v1/operator/voyages", json=payload)
    assert resp2.status_code == 409
    data = resp2.json()
    assert data["error_type"] == "CONFLICT"
    assert "timestamp_utc" in data


def test_03_get_persisted_voyage_state(client: TestClient):
    """Verify GET /api/v1/operator/voyages/{voyage_id} returns HTTP 200 with matching record."""
    payload = create_sample_payload("VOY_GET_01")
    client.post("/api/v1/operator/voyages", json=payload)

    resp = client.get("/api/v1/operator/voyages/VOY_GET_01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["voyage_id"] == "VOY_GET_01"
    assert data["status"] == "PLANNED"


def test_04_get_nonexistent_voyage_returns_404(client: TestClient):
    """Verify GET on unknown voyage_id returns HTTP 404 with structured APIErrorResponse."""
    resp = client.get("/api/v1/operator/voyages/NONEXISTENT_VOYAGE")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_type"] == "NOT_FOUND"


def test_05_list_persisted_voyage_states(client: TestClient):
    """Verify GET /api/v1/operator/voyages lists all stored voyages with pagination."""
    for i in range(3):
        p = create_sample_payload(f"VOY_LIST_{i}")
        client.post("/api/v1/operator/voyages", json=p)

    resp = client.get("/api/v1/operator/voyages?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 3


def test_06_update_persisted_voyage_state(client: TestClient):
    """Verify PUT /api/v1/operator/voyages/{voyage_id} updates state and increments version."""
    payload = create_sample_payload("VOY_PUT_01")
    client.post("/api/v1/operator/voyages", json=payload)

    update_payload = {
        "status": "ACTIVE",
        "metadata": {"shift": "morning"},
    }
    resp = client.put("/api/v1/operator/voyages/VOY_PUT_01", json=update_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ACTIVE"
    assert data["state_version"] == 2
    assert data["metadata"] == {"shift": "morning"}


def test_07_update_with_stale_expected_version_returns_409(client: TestClient):
    """Verify PUT with stale expected_version triggers HTTP 409 Conflict."""
    payload = create_sample_payload("VOY_CONC_01")
    client.post("/api/v1/operator/voyages", json=payload)  # version 1

    update_payload = {
        "expected_version": 99,  # Mismatched expected version
        "status": "COMPLETED",
    }
    resp = client.put("/api/v1/operator/voyages/VOY_CONC_01", json=update_payload)
    assert resp.status_code == 409
    data = resp.json()
    assert data["error_type"] == "CONFLICT"


def test_08_update_nonexistent_voyage_returns_404(client: TestClient):
    """Verify PUT on unknown voyage_id returns HTTP 404."""
    update_payload = {"status": "ACTIVE"}
    resp = client.put("/api/v1/operator/voyages/NONEXISTENT_VOY", json=update_payload)
    assert resp.status_code == 404
    assert resp.json()["error_type"] == "NOT_FOUND"


def test_09_delete_persisted_voyage_state(client: TestClient):
    """Verify DELETE /api/v1/operator/voyages/{voyage_id} returns HTTP 204, subsequent GET returns 404."""
    payload = create_sample_payload("VOY_DEL_01")
    client.post("/api/v1/operator/voyages", json=payload)

    resp_del = client.delete("/api/v1/operator/voyages/VOY_DEL_01")
    assert resp_del.status_code == 204

    resp_get = client.get("/api/v1/operator/voyages/VOY_DEL_01")
    assert resp_get.status_code == 404


def test_10_delete_nonexistent_voyage_returns_404(client: TestClient):
    """Verify DELETE on unknown voyage_id returns HTTP 404."""
    resp = client.delete("/api/v1/operator/voyages/NONEXISTENT_VOY")
    assert resp.status_code == 404
    assert resp.json()["error_type"] == "NOT_FOUND"


def test_11_invalid_creation_payload_returns_422(client: TestClient):
    """Verify invalid payload missing required fields returns HTTP 422."""
    resp = client.post("/api/v1/operator/voyages", json={"invalid": "payload"})
    assert resp.status_code == 422
    assert resp.json()["error_type"] == "VALIDATION_ERROR"


# =====================================================================
# SECURITY & SAFETY AUDIT TESTS
# =====================================================================

def test_12_no_sql_injection_in_sqlite_repo():
    """Security Audit: Verify SQLite repository source uses only parameterized queries (? placeholders)."""
    import app.state.sqlite_repository as sql_mod
    source = inspect.getsource(sql_mod)
    assert "format(" not in source or "CREATE" in source  # No string formatting of input
    assert "%s" not in source  # No unparameterized string formatting
    assert "?" in source  # Parameterized placeholders present


def test_13_no_actuation_code_in_state_package():
    """Safety Audit: Search app/state source code for forbidden autonomous actuation keywords."""
    import app.state.contracts as c_mod
    import app.state.repository as r_mod
    import app.state.memory_repository as mr_mod
    import app.state.sqlite_repository as sr_mod

    modules = [c_mod, r_mod, mr_mod, sr_mod]
    forbidden_terms = [
        "set_throttle",
        "set_rudder",
        "execute_steering",
        "start_engine",
        "stop_engine",
        "override_route",
        "actuate",
    ]
    for mod in modules:
        source = inspect.getsource(mod)
        for term in forbidden_terms:
            assert term not in source, f"Forbidden term '{term}' found in {mod.__name__}"


def test_14_no_dynamic_execution_in_state_package():
    """Security Audit: Verify eval() and exec() are absent from app/state codebase."""
    import app.state.contracts as c_mod
    import app.state.repository as r_mod
    import app.state.memory_repository as mr_mod
    import app.state.sqlite_repository as sr_mod

    modules = [c_mod, r_mod, mr_mod, sr_mod]
    for mod in modules:
        source = inspect.getsource(mod)
        assert "eval(" not in source, f"eval() found in {mod.__name__}"
        assert "exec(" not in source, f"exec() found in {mod.__name__}"
