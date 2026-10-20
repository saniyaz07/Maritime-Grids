# Phase 10C.12 — Read-Only Architecture Audit & Pre-Implementation Discovery

**Project Root:** `C:\maritime grids`  
**Execution Mode:** STRICT READ-ONLY FORENSIC AUDIT  
**Phase Target:** `PHASE 10C.12 — TELEMETRY GATEWAY & LIVE DRIVER DASHBOARD INTEGRATION`  
**Baseline Regression:** `793 / 793 PASS` (100%), `20 / 20 Frontend PASS`, `9 / 9 Frontend Contracts PASS`  
**Data Integrity:** 6,228 files in `data/raw/`, All 5 canonical model SHA-256 hashes verified.

---

## 1. Executive Summary

This pre-implementation architecture audit evaluates the entire telemetry, vessel kinematics, engine state, energy storage, freshness/provenance tracking, and API transport pipeline across Phases 0–10C.11B. 

The purpose is to map all existing telemetry schemas, identify architectural integration points and gaps, establish the canonical telemetry ingestion contract, and guarantee absolute compliance with safety boundaries (zero actuation, read-only telemetry, human-in-the-loop decision support).

---

## 2. 15-Point Forensic Audit

### 1. Current Telemetry Sources
- **Simulated / Historical Scenario Streams**: Telemetry currently originates from `data/raw/` (NASA POWER daily solar datasets, simulated vessel profiles, synthetic voyages) and `Phase 10C.2` `OpenMeteoWeatherProvider` / `MockWeatherProvider`.
- **Operator API Ingestion**: `app/api/operator.py` exposes `POST /api/v1/operator/state/from-telemetry` accepting `OperatorTelemetryRequest` (`vessel`, `route`, `position`, `energy_state`, `timeline`).
- **Frontend Demo Player**: `frontend/pages/DriverDashboard.js` contains a local simulated scenario playback loop (`loadDemoState()`) tagged `SIMULATED`.

### 2. Existing Vessel Schema
- Defined in [`app/voyage/contracts.py`](file:///C:/maritime%20grids/app/voyage/contracts.py#L50-L75) as `VesselContext`:
  - `vessel_id`: str (min length 1)
  - `ship_type`: str (min length 1)
  - `design_speed_knots`: Optional[float] (1.0 to 50.0)
  - `max_speed_knots`: Optional[float] (1.0 to 50.0)
  - `displacement_tonnes`: Optional[float] (>= 1.0)
  - `engine_power_kw`: Optional[float] (>= 1.0)
  - `propulsion_type`: Optional[str]
  - `battery_pack_capacity_kwh`: Optional[float] (>= 0.0)
  - `solar_panel_size_m2`: Optional[float] (>= 0.0)
  - `fuel_price_usd_per_liter`: Optional[float] (>= 0.0)
  - `provenance`: `WeatherProvenanceType` (default `OBSERVED`)

### 3. Existing Speed Fields
- `VesselPosition.speed_over_ground_knots`: Optional[float] (>= 0.0, knots).
- In Operator Response: `OperatorVesselState.current_position.speed_over_ground_knots`.
- Design Speed: `VesselContext.design_speed_knots`.
- In Frontend: `renderSpeedCard` formats SOG with provenance/freshness, or renders `"Unavailable"` if null. Recommended speed is explicitly labeled `"Not available"` (preserving boundary with Phase 9 offline optimizer).

### 4. Existing Heading / COG Fields
- `VesselPosition.course_over_ground_deg`: Optional[float] (0.0 to 360.0 degrees).
- In Frontend: `renderSpeedCard` formats COG in degrees or `"Unavailable"` if null.

### 5. Existing Engine Fields
- In Backend `VesselContext`: `engine_power_kw` (installed rated power kW), `propulsion_type` (description).
- **Gap Identified**: There is currently no dedicated live `EngineTelemetry` contract in `app/voyage/` or `app/services/` containing instantaneous `state` (ON, OFF, UNKNOWN), `rpm`, or `load_pct`.
- In Frontend `SpeedEngineCard.js`: Displays `ENGINE STATE UNKNOWN` with notice *"Live engine telemetry is not connected"* because live engine gateway contracts were not yet formalized.

### 6. Existing Fuel Fields
- In Backend `VesselEnergyState`:
  - `fuel_remaining_liters`: Optional[float] (>= 0.0, liters)
  - `fuel_consumption_rate_lph`: Optional[float] (>= 0.0, L/h)
- In `OperatorEnergyState`: Propagates both fields faithfully preserving `None`.
- In Frontend `EnergyCard.js` / `renderFuelCard`: Formats volume in L, burn rate in L/h, preserving `"Unavailable"` when null.

### 7. Existing Battery Fields
- In Backend `VesselEnergyState`:
  - `battery_soc_pct`: Optional[float] (0.0 to 100.0%)
  - `battery_soh_pct`: Optional[float] (0.0 to 100.0%)
  - `battery_energy_available_kwh`: Optional[float] (>= 0.0, usable kWh)
- In `OperatorEnergyState`: Propagates all three fields.
- In Frontend `EnergyCard.js` / `renderBatteryCard`: Formats SOC/SOH gauges and usable kWh storage.

### 8. Existing Timestamp Fields
- All timestamps in backend schemas are strictly ISO-8601 UTC strings with validation via `NormalizedWeatherRecord.validate_and_normalize_iso_utc()`:
  - `VesselPosition.timestamp_utc`
  - `VoyageTimeline.departure_time_utc`, `current_time_utc`, `planned_arrival_time_utc`, `estimated_arrival_time_utc`
  - `NormalizedWeatherRecord.timestamp_utc`, `retrieval_timestamp_utc`
  - `OperatorStateMetadata.generated_at_utc`

### 9. Existing Provenance Fields
- `WeatherProvenanceType` in `app/weather/contracts.py`:
  - `OBSERVED`, `HISTORICAL`, `FORECAST`, `MODEL_PREDICTION`, `SIMULATED`, `UNAVAILABLE`
- Enforced across `VesselPosition.data_type`, `VesselEnergyState.provenance`, `VesselContext.provenance`, `OperatorWeatherState.provenance`.
- Mirrored in `frontend/contracts/types.js` (`WeatherProvenanceType`).

### 10. Existing Freshness Logic
- Defined in `app/weather/contracts.py`:
  - `WeatherFreshnessState`: `FRESH`, `STALE`, `EXPIRED`, `UNKNOWN`
  - Evaluated via `NormalizedWeatherRecord.evaluate_freshness(current_time_utc, fresh_threshold_seconds=3600.0, stale_threshold_seconds=86400.0)`.
  - Age calculation: `freshness_age_seconds = max(0.0, (ref_dt - record_dt).total_seconds())`.
  - Future-dated timestamps (e.g. forecasts) default to `FRESH`.
- Need to extend / apply this same unified model to incoming vessel and engine telemetry.

### 11. Existing API Endpoints
- **Operator API** (`app/api/operator.py`):
  - `POST /api/v1/operator/state`: Evaluates `DecisionContext`
  - `POST /api/v1/operator/state/from-voyage`: Evaluates `VoyageContext`
  - `POST /api/v1/operator/state/from-telemetry`: Evaluates `OperatorTelemetryRequest`
  - `GET /api/v1/operator/voyages`: Lists persisted voyages
  - `POST /api/v1/operator/voyages`: Creates persisted voyage
  - `GET /api/v1/operator/voyages/{voyage_id}`: Gets persisted voyage
  - `PUT /api/v1/operator/voyages/{voyage_id}`: Updates persisted voyage
  - `DELETE /api/v1/operator/voyages/{voyage_id}`: Deletes persisted voyage
  - `GET /api/v1/operator/health`: Service health check

### 12. Missing Telemetry Contracts
- **Canonical Telemetry Ingestion Contract**: A dedicated schema `CanonicalTelemetryPayload` / `VesselTelemetryStream` unifying:
  - Header: timestamp, stream_id, source_id
  - Vessel Navigation Telemetry: position, SOG, COG, heading
  - Engine Operational Telemetry: state (ON, OFF, UNKNOWN), RPM, load %, power kW
  - Energy Storage Telemetry: fuel remaining, fuel rate, battery SOC/SOH/kWh, solar power
  - Environmental / Weather snapshot
  - Stream-level Provenance, Quality, and Freshness evaluation
- **Telemetry Adapter & Ingestion Boundary**: An adapter validating raw payloads, handling missing data, applying validation rules, and normalizing to the canonical schema.
- **Telemetry Simulator**: A deterministic scenario generator (Scenarios A through H) for UI and contract testing.

### 13. Any Duplicated Telemetry Logic
- Currently, route progress estimation is implemented in `OperatorService._compute_route_progress()` using Great Circle distance math. No other duplicated physics exist.
- Frontend contains zero numerical physics calculations (verified by `test_09_no_physics_duplicated_in_frontend`).

### 14. Any Possible Null/Zero Semantic Violations
- All backend models use `Optional[float] = Field(default=None)` and reject default zeros.
- Frontend `renderTelemetryField` in `ProvenanceBadge.js` strictly checks `value !== null && value !== undefined` and displays `"Unavailable"` on null, ensuring `null != 0`.

### 15. Any Existing Actuator / Control Code
- **Complete Search Conducted**: Searched repository for actuation patterns (`set_throttle`, `set_rudder`, `start_engine`, `stop_engine`, `shutdown_engine`, `override_route`, `steer_vessel`).
- **Result**: Zero executable actuation or vessel control paths found in backend or frontend. All occurrences are strictly negative assertion security checks in test suites.

---

## 3. Pre-Implementation Audit Sign-Off

The audit confirms that the codebase is completely clean, strictly read-only, has zero physical actuation or control pathways, and has a clear architectural position for the **Phase 10C.12 Telemetry Gateway & Normalization Layer**.

Implementation of Phase 10C.12 may proceed.
