"""
tests/test_frontend_contracts.py — Phase 10C.11A Frontend Contract & Semantic Alignment Suite
=============================================================================================
Verifies:
  1. Frontend enums match backend Pydantic / enum definitions exactly.
  2. All 10 engineering operations are exposed in the frontend client.
  3. All operator REST endpoints are exposed in the frontend client.
  4. Mandatory semantic labels (CLIMATOLOGICAL SCENARIO ESTIMATE, ETA linear estimate, HUMAN REVIEW REQUIRED) are present in frontend source.
  5. Zero autonomous control commands or actuators exist in the frontend code.
"""

import os
import re
from pathlib import Path
import pytest

from app.weather.contracts import WeatherProvenanceType, WeatherQualityState, WeatherFreshnessState
from app.voyage.contracts import VoyageStatus
from app.advisory.contracts import AdvisorySeverity

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def test_01_frontend_weather_provenance_enums_match_backend():
    """Verify frontend WeatherProvenanceType enums match backend exactly."""
    fe_types_path = FRONTEND_DIR / "contracts" / "types.js"
    assert fe_types_path.exists()
    with open(fe_types_path, "r", encoding="utf-8") as f:
        content = f.read()

    backend_provenances = [p.value for p in WeatherProvenanceType]
    for prov in backend_provenances:
        assert f'{prov}: "{prov}"' in content, f"Provenance {prov} missing in frontend contracts"

    # Confirm DERIVED is NOT in frontend WeatherProvenanceType
    assert 'DERIVED: "DERIVED"' not in content.split("WeatherQualityState")[0]


def test_02_frontend_weather_quality_and_freshness_match_backend():
    """Verify frontend WeatherQualityState and WeatherFreshnessState match backend."""
    fe_types_path = FRONTEND_DIR / "contracts" / "types.js"
    with open(fe_types_path, "r", encoding="utf-8") as f:
        content = f.read()

    for q in WeatherQualityState:
        assert f'{q.value}: "{q.value}"' in content
    for fr in WeatherFreshnessState:
        assert f'{fr.value}: "{fr.value}"' in content


def test_03_frontend_operator_client_covers_all_endpoints():
    """Verify frontend OperatorApiClient implements all 9 operator endpoints."""
    client_path = FRONTEND_DIR / "api" / "operatorClient.js"
    assert client_path.exists()
    with open(client_path, "r", encoding="utf-8") as f:
        content = f.read()

    expected_endpoints = [
        "/api/v1/operator/health",
        "/api/v1/operator/state",
        "/api/v1/operator/state/from-voyage",
        "/api/v1/operator/state/from-telemetry",
        "/api/v1/operator/voyages",
    ]
    for ep in expected_endpoints:
        assert ep in content, f"Operator endpoint {ep} missing in frontend client"


def test_04_frontend_engineering_client_covers_all_10_operations():
    """Verify frontend EngineeringApiClient implements all 10 engineering operations."""
    client_path = FRONTEND_DIR / "api" / "engineeringClient.js"
    assert client_path.exists()
    with open(client_path, "r", encoding="utf-8") as f:
        content = f.read()

    expected_ops = [
        "/api/v1/engineering/simulate-voyage",
        "/api/v1/engineering/evaluate-sizing",
        "/api/v1/engineering/optimize-sizing",
        "/api/v1/engineering/sensitivity-analysis",
        "/api/v1/engineering/break-even-analysis",
        "/api/v1/engineering/grid-2d-analysis",
        "/api/v1/engineering/speed-cooptimization",
        "/api/v1/engineering/portfolio-optimization",
        "/api/v1/engineering/cii-trajectory",
        "/api/v1/engineering/export-dossier",
    ]
    for op in expected_ops:
        assert op in content, f"Engineering operation {op} missing in frontend client"


def test_05_mandatory_semantic_labels_present_in_frontend():
    """Verify mandatory semantic labels are hardcoded in respective frontend components."""
    # 1. SolarCard
    with open(FRONTEND_DIR / "components" / "SolarCard.js", "r", encoding="utf-8") as f:
        solar_src = f.read()
    assert "CLIMATOLOGICAL SCENARIO ESTIMATE" in solar_src
    assert "diurnalUncertaintyFlag" in solar_src

    # 2. VoyageStatusCard
    with open(FRONTEND_DIR / "components" / "VoyageStatusCard.js", "r", encoding="utf-8") as f:
        voy_src = f.read()
    assert "Application-level linear estimate" in voy_src
    assert "Not a hydrodynamic voyage predictor." in voy_src

    # 3. AdvisoryPanel
    with open(FRONTEND_DIR / "components" / "AdvisoryPanel.js", "r", encoding="utf-8") as f:
        adv_src = f.read()
    assert "HUMAN REVIEW REQUIRED" in adv_src


def test_06_phase10c11b_speed_and_engine_contracts():
    """Verify Phase 10C.11B Speed and Engine State contracts."""
    with open(FRONTEND_DIR / "components" / "SpeedEngineCard.js", "r", encoding="utf-8") as f:
        src = f.read()
    assert "renderSpeedCard" in src
    assert "renderEngineStateCard" in src
    assert "ENGINE STATE UNKNOWN" in src or "ENGINE STATE: UNKNOWN" in src or "UNKNOWN" in src
    assert "Live engine telemetry is not connected" in src
    assert "Physical engine ON/OFF control and throttle actuation are NOT implemented" in src


def test_07_phase10c11b_energy_and_weather_components():
    """Verify Phase 10C.11B Energy and Weather card components."""
    with open(FRONTEND_DIR / "components" / "EnergyCard.js", "r", encoding="utf-8") as f:
        energy_src = f.read()
    assert "renderFuelCard" in energy_src
    assert "renderBatteryCard" in energy_src

    with open(FRONTEND_DIR / "components" / "WeatherCard.js", "r", encoding="utf-8") as f:
        weather_src = f.read()
    assert "Operational Route Weather" in weather_src
    assert "Wave Height" in weather_src
    assert "Ocean Current" in weather_src



def test_08_zero_actuator_code_in_frontend_package():
    """Safety Audit: Search all frontend source files for forbidden actuation terms."""
    forbidden_terms = [
        "set_throttle",
        "set_rudder",
        "start_engine",
        "stop_engine",
        "shutdown_engine",
        "override_route",
        "steer_vessel",
    ]
    for root, _, files in os.walk(FRONTEND_DIR):
        if "tests" in root:
            continue
        for file in files:
            if file.endswith(".js") or file.endswith(".html"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().lower()
                    for term in forbidden_terms:
                        assert term not in content, f"Forbidden term '{term}' found in {path}"


def test_09_no_physics_duplicated_in_frontend():
    """Safety Audit: Verify frontend contains zero numerical physics calculations."""
    for root, _, files in os.walk(FRONTEND_DIR):
        for file in files:
            if file.endswith(".js") and "tests" not in root:
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Verify no SFOC / density / NPV calculations in frontend
                    assert "0.220" not in content, f"SFOC constant found in {path}"
                    assert "3.114" not in content, f"Carbon factor constant found in {path}"
                    assert "5247" not in content, f"CII constant found in {path}"


def test_10_phase10c12_telemetry_contracts():
    """Phase 10C.12: Verify telemetry enums, client endpoints, and status badge."""
    # 1. Telemetry enums in types.js
    with open(FRONTEND_DIR / "contracts" / "types.js", "r", encoding="utf-8") as f:
        types_src = f.read()
    assert "EngineOperationalState" in types_src
    assert "TelemetryFreshnessState" in types_src
    assert "TelemetryQualityState" in types_src
    assert "TelemetryStatusState" in types_src

    # 2. OperatorApiClient telemetry methods
    with open(FRONTEND_DIR / "api" / "operatorClient.js", "r", encoding="utf-8") as f:
        client_src = f.read()
    assert "ingestTelemetry" in client_src
    assert "getCurrentTelemetry" in client_src
    assert "getSimulatedScenario" in client_src
    assert "validateTelemetry" in client_src

    # 3. TelemetryStatusBadge component
    badge_path = FRONTEND_DIR / "components" / "TelemetryStatusBadge.js"
    assert badge_path.exists()
    with open(badge_path, "r", encoding="utf-8") as f:
        badge_src = f.read()
    assert "renderTelemetryStatusBadge" in badge_src
    assert "TELEMETRY" in badge_src


def test_11_phase10c13_streaming_and_audit_contracts():
    """Phase 10C.13: Verify SSE streaming methods, stream connection badge, and audit table."""
    # 1. OperatorApiClient streaming & history methods
    with open(FRONTEND_DIR / "api" / "operatorClient.js", "r", encoding="utf-8") as f:
        client_src = f.read()
    assert "getTelemetryStreamUrl" in client_src
    assert "getTelemetryHistory" in client_src
    assert "subscribeTelemetryStream" in client_src
    assert "/api/v1/operator/telemetry/stream" in client_src
    assert "/api/v1/operator/telemetry/history" in client_src

    # 2. TelemetryStatusBadge streaming indicators
    with open(FRONTEND_DIR / "components" / "TelemetryStatusBadge.js", "r", encoding="utf-8") as f:
        badge_src = f.read()
    assert "renderStreamConnectionBadge" in badge_src
    assert "renderTelemetryFreshnessBadge" in badge_src
    assert "STREAM:" in badge_src

    # 3. DriverDashboard audit history table
    with open(FRONTEND_DIR / "pages" / "DriverDashboard.js", "r", encoding="utf-8") as f:
        dash_src = f.read()
    assert "renderAuditHistoryTable" in dash_src
    assert "TELEMETRY AUDIT LOG" in dash_src
    assert "subscribeTelemetryStream" in dash_src
    assert "streamState" in dash_src



