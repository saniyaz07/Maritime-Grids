# Phase 10C.12 — Telemetry Gateway & Live Driver Dashboard Integration

## 1. Objective

Phase 10C.12 establishes the canonical **Telemetry Gateway** and ingestion layer for the maritime platform, bridging raw, provider, and simulated telemetry streams directly to Driver Dashboard V1 while preserving all frozen engineering, physical, and regulatory boundaries.

The pipeline architecture is:

```text
External / Simulated Telemetry
             ↓
     Telemetry Adapter
 (Validation + Normalization)
             ↓
Canonical Telemetry Contract
             ↓
     Telemetry Gateway
             ↓
   Operator API / Service
             ↓
     Driver Dashboard
```

---

## 2. Pre-Implementation Audit Summary

A rigorous 15-point forensic audit was conducted before implementation and documented in [`docs/phase10c12_pre_implementation_audit.md`](file:///C:/maritime%20grids/docs/phase10c12_pre_implementation_audit.md):
- Verified existing vessel, navigation, fuel, and battery schemas in `app/voyage/` and `app/services/`.
- Identified the need for a dedicated `EngineTelemetry` contract with strictly 3 discrete states (`ON`, `OFF`, `UNKNOWN`) and no false inferences from SOG or fuel rate.
- Confirmed zero actuation or vessel control paths across the repository.

---

## 3. Existing Architecture Integration

The Telemetry Gateway sits cleanly beneath the Operator API layer and alongside the Weather Gateway:
- **`app/telemetry/contracts.py`**: Canonical telemetry payload contract (`CanonicalTelemetryPayload`), kinematics (`PositionTelemetry`), engine (`EngineTelemetry`), and energy (`EnergyTelemetry`).
- **`app/telemetry/adapter.py`**: Validates ranges (lat $[-90, 90]$, lon $[-180, 180]$, SOG $[0, 100]$, heading $[0, 360]$, fuel $\ge 0$, SOC $[0, 100]\%$), quarantines errors, and evaluates freshness.
- **`app/telemetry/simulator.py`**: Deterministic test fixture generator for Scenarios A through H.
- **`app/telemetry/gateway.py`**: Thread-safe in-memory cache and gateway buffer.
- **`app/api/operator.py`**: Exposes read-only telemetry endpoints (`/telemetry/ingest`, `/telemetry/current`, `/telemetry/simulated/{scenario_id}`, `/telemetry/validate`).

---

## 4. Canonical Telemetry Contract

The canonical schema represents a single source of truth:

```json
{
  "telemetry_id": "TEL_001",
  "timestamp_utc": "2026-09-28T12:00:00+00:00",
  "vessel_id": "VESSEL_OSV_01",
  "position": {
    "latitude": 5.8214,
    "longitude": 4.5120,
    "speed_over_ground_knots": 11.8,
    "course_over_ground_deg": 284.5,
    "heading_deg": 285.0
  },
  "engine": {
    "state": "ON",
    "rpm": 1450.0,
    "load_percent": 72.5,
    "power_kw": 1740.0,
    "fuel_rate_lph": 142.5
  },
  "energy": {
    "fuel_remaining_liters": 14200.0,
    "fuel_rate_lph": 142.5,
    "battery_soc_pct": 78.5,
    "battery_soh_pct": 94.2,
    "battery_usable_kwh": 480.0,
    "battery_power_kw": -15.0,
    "solar_power_kw": 12.8
  },
  "quality": {
    "overall": "VALID",
    "freshness": "FRESH",
    "freshness_age_seconds": 0.0,
    "validation_errors": []
  },
  "provenance": {
    "source": "GPS_NMEA",
    "mode": "OBSERVED",
    "stream_id": "STREAM_01"
  }
}
```

---

## 5. Telemetry Adapter & Validation Rules

`TelemetryAdapter` enforces strict boundary rules:
1. **Range Validation**:
   - Latitude: $\in [-90.0, 90.0]$
   - Longitude: $\in [-180.0, 180.0]$
   - SOG: $\in [0.0, 100.0]\text{ kn}$
   - Heading / COG: $\in [0.0, 360.0]^\circ$
   - Battery SOC / SOH: $\in [0.0, 100.0]\%$
   - Fuel remaining & rates: $\ge 0.0\text{ L}$ (negative fuel strictly quarantined).
2. **Strict Null Semantics (`null != 0`)**:
   - Missing or unmeasured fields remain `None`. They are never defaulted to `0.0`.
3. **Data Quality Classification**:
   - `VALID`: All physical fields valid and within range.
   - `PARTIAL`: Some sensor streams available, others missing.
   - `INVALID`: Quarantined out-of-range or malformed measurements.
   - `UNAVAILABLE`: All fields null / unmeasured.

---

## 6. Freshness Semantics

Freshness is evaluated dynamically against reference UTC time:
- **`FRESH`**: Age $\le 60\text{ s}$ (or future-dated forecast).
- **`STALE`**: $60\text{ s} < \text{Age} \le 900\text{ s}$ (15 minutes).
- **`EXPIRED`**: $\text{Age} > 900\text{ s}$ (triggers automatic degradation of engine state to `UNKNOWN`).
- **`DISCONNECTED`**: Telemetry stream source unavailable or silent.

---

## 7. Engine-State Semantics

Engine state strictly operates in three states:
1. **`ON`**: Rendered only when explicit telemetry reports ON.
2. **`OFF`**: Rendered only when explicit telemetry reports OFF.
3. **`UNKNOWN`**: Rendered when sensors are uninstrumented, disconnected, or expired.
- Engine state is **never inferred** from SOG, fuel rate, or voyage status.

---

## 8. Simulated Telemetry Mode (Scenarios A through H)

| Scenario ID | Scenario Name | Engine State | Speed (SOG) | Telemetry Freshness | Provenance Mode | Quality State |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A** | Normal Telemetry | `ON` (1450 RPM, 72.5% Load) | 11.8 kn | `FRESH` | `SIMULATED` | `VALID` |
| **B** | Engine OFF | `OFF` (0 RPM, 0% Load) | 0.2 kn | `FRESH` | `SIMULATED` | `VALID` |
| **C** | Engine UNKNOWN | `UNKNOWN` (Null RPM/Load) | 12.0 kn | `FRESH` | `SIMULATED` | `PARTIAL` |
| **D** | Missing Speed | `ON` (1400 RPM, 70% Load) | `None` (`Unavailable`) | `FRESH` | `SIMULATED` | `PARTIAL` |
| **E** | Stale Telemetry | `ON` (1450 RPM) | 11.8 kn | `STALE` (10 min old) | `SIMULATED` | `VALID` |
| **F** | Expired Telemetry | `UNKNOWN` (Degraded) | 11.8 kn | `EXPIRED` (2h old) | `SIMULATED` | `VALID` |
| **G** | Disconnected | `UNKNOWN` | `None` | `DISCONNECTED` | `UNAVAILABLE` | `UNAVAILABLE` |
| **H** | Invalid Quarantined | `ON` | `None` (Quarantined) | `FRESH` | `SIMULATED` | `INVALID` |

---

## 9. Dashboard Integration & Status Indicator

Driver Dashboard V1 integrates:
1. **Telemetry Status Badge**:
   - `TELEMETRY ● LIVE` (Green)
   - `TELEMETRY ● STALE` (Amber)
   - `TELEMETRY ● EXPIRED` (Red)
   - `TELEMETRY ● DISCONNECTED` (Muted Red)
   - `TELEMETRY ● SIMULATED` (Cyan)
2. **Scenario Selector Dropdown**: Allows instant deterministic scenario testing (Scenarios A–H).
3. **Null-Safe Component Presentation**: All cards preserve `null != 0` and display `"Unavailable"` when telemetry is missing.

---

## 10. Safety & Non-Actuation Invariants

- **Read-Only Telemetry**: The telemetry gateway contains zero hardware write paths, zero actuator endpoints, and zero autonomous vessel control pathways.
- **Human-in-the-Loop Review**: All decision advisories retain `human_review_required = True`.
- **Search Audit**: Repository verified free of executable actuation methods (`set_throttle`, `set_rudder`, `start_engine`, `stop_engine`, `steer_vessel`, `override_route`).

---

## 11. Verification & Test Results

- **Pytest Telemetry Contracts Suite (`tests/test_telemetry_contracts.py`)**: **9 / 9 PASS**
- **Pytest Telemetry Gateway Suite (`tests/test_telemetry_gateway.py`)**: **5 / 5 PASS**
- **Pytest Frontend Contracts Suite (`tests/test_frontend_contracts.py`)**: **10 / 10 PASS**
- **Node.js Telemetry Gateway Suite (`frontend/tests/telemetry_gateway.test.js`)**: **14 / 14 PASS**
- **Node.js Driver Dashboard V1 Suite (`frontend/tests/dashboard_v1.test.js`)**: **20 / 20 PASS**
- **Full Backend Regression Suite**: **807 / 807 PASS (100%)**

---

## 12. Canonical Integrity Hashes & Dataset Audit

- `models/weather_final.joblib`: `39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3`
- `models/fuel_xgb.joblib`: `cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323`
- `models/battery_soh_final.joblib`: `9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1`
- `models/battery_soc_lstm.pt`: `c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25`
- `data/reference/ship_profiles.csv`: `0f2040a481790b034fac11cd9e2b628c725281397610fe0bdba09f6feed7de75`
- `data/raw/` file count: Exactly **6,228 files preserved**.

---

## 13. Known Limitations & Next Phase Recommendations

1. **Known Limitations**:
   - Live hardware connectors (NMEA 0183, NMEA 2000, Modbus TCP, MQTT broker) are represented via adapter boundaries and simulated deterministic fixtures. No physical CAN-bus or serial drivers exist in this environment.
   - Dynamic throttle advisory recommendations remain offline (Phase 9 co-optimizer) and are intentionally not streamed into real-time operational actuation.
2. **Recommended Next Phase (Phase 10C.13)**:
   - Introduce WebSocket/SSE push streaming transport for real-time live telemetry feeds.
   - Implement audit logging and historical telemetry playback.
