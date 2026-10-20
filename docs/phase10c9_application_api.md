# Phase 10C.9 — Application API Transport Boundary Implementation

**Status:** IMPLEMENTED / VERIFIED / READY FOR NEXT PHASE  
**Execution Mode:** Controlled Implementation + API Contract Validation + Mandatory Self-Audit  
**Location:** `app/api/`  
**Test Baseline:** 731 / 731 PASS (100% green across all phases: 695 baseline + 36 dedicated Phase 10C.9 API tests)  

---

## 1. Executive Summary & Purpose

Phase 10C.9 establishes the **Application API Transport Boundary** for the maritime clean-energy simulation, sizing, optimization, and real-time operational decision-support system.

Sitting strictly above `app/services/` (`EngineeringService` and `OperatorService`), this layer implements a lightweight, deterministic, dependency-injected FastAPI boundary that provides HTTP entry points for future presentation interfaces (Driver/Operator Dashboard, Engineering Scenario Workbench).

```
                      +-----------------------------+
                      |  Future Dashboard / Client  |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |          HTTP API           |
                      |          (FastAPI)          |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |    Application API Layer    |
                      |         `app/api/`          |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |    APPLICATION SERVICES     |
                      |      `app/services/`        |
                      +--------------+--------------+
                                     |
             +-----------------------+-----------------------+
             |                                               |
             v                                               v
+--------------------------+                   +--------------------------+
|    EngineeringService    |                   |     OperatorService      |
+------------+-------------+                   +-------------+------------+
             |                                               |
             v                                               v
+--------------------------+                   +--------------------------+
|  MaritimeScenarioFacade  |                   |     AdvisoryPipeline     |
|   (10 Eng Operations)    |                   |   VoyageContextBuilder   |
+--------------------------+                   +--------------------------+
```

---

## 2. Strict Scope & Invariants Preserved

1. **Pure Transport Boundary:**
   - Exposes RESTful HTTP endpoints for all 10 engineering operations and operator situational awareness.
   - Pydantic v2 input validation and response schema generation.
   - Deterministic HTTP error normalization (400, 404, 409, 422, 500, 503).
2. **Zero Forbidden Technologies:**
   - **No** React / HTML / UI widgets.
   - **No** WebSockets or streaming sockets.
   - **No** Database connections, ORMs, or disk persistence.
   - **No** Authentication, JWTs, sessions, or RBAC.
   - **No** LLMs, RAG, or autonomous agent loops.
3. **Zero Autonomous Actuation / Vessel Control:**
   - **No** endpoints for throttle, rudder, steering, engine start/stop, speed change, or route override.
   - Bridge decision support only (`human_review_required = True`).
4. **Zero Physics Invention:**
   - **No** re-calculated fuel equations or propulsion models in API routers.
   - **No** wind propulsion, sails, rotors, kites, or engine-off duration estimates.
5. **Truthful Telemetry Preservation:**
   - Unobserved/missing telemetry fields remain `None` (`Optional[float]`), never defaulted to `0.0`.
   - Stale/invalid weather states remain explicitly `STALE` and `INVALID`.
   - Weather provenance (`OBSERVED`, `HISTORICAL`, `FORECAST`, `SIMULATED`) preserved intact.
6. **Explicit Advisory Policies:**
   - Zero hardcoded threshold defaults (`20%`, `35%`, `1000 L`, `25 kts`, `2.5 m`).

---

## 3. Package Structure

```
app/api/
├── __init__.py         # Package exports (create_app, dependencies, APIErrorResponse)
├── app.py              # Application factory with exception handlers & routers
├── dependencies.py     # Dependency injection providers (services & weather connectors)
├── errors.py           # Structured error schema (APIErrorResponse) & exception handlers
├── engineering.py      # APIRouter for 10 engineering operations (/api/v1/engineering)
└── operator.py         # APIRouter for operator situational awareness (/api/v1/operator)
```

---

## 4. Application Factory (`create_app`)

The `create_app()` factory provides:
- **Deterministic Initialization:** Zero startup network requests, database connections, or background worker threads.
- **Dependency Injection:** Overridable dependencies (`get_engineering_service`, `get_operator_service`, `get_weather_provider`) enabling seamless unit testing without global state mutation.
- **OpenAPI Schema Generation:** Native documentation generated at `/docs`, `/redoc`, and `/openapi.json`.
- **Global Error Handlers:** Exception handling registered for `FacadeValidationError`, `FacadeExecutionError`, `FacadeError`, `RequestValidationError`, `StarletteHTTPException`, and generic `Exception`.

---

## 5. API Endpoint Specifications

### 5.1 Engineering Router (`/api/v1/engineering`)

| Method | Route | Description | Request Model | Response Model |
|---|---|---|---|---|
| `POST` | `/simulate-voyage` | Simulate single voyage profile (Phase 6 gateway) | `SimulateVoyageRequest` | `FacadeResponse[Phase6SimulationResult]` |
| `POST` | `/evaluate-sizing` | Evaluate solar/battery sizing candidate (Phase 8) | `EvaluateSizingCandidateRequest` | `FacadeResponse[OptimizationCandidate]` |
| `POST` | `/optimize-sizing` | Multi-objective sizing optimization (Phase 8 Pareto) | `OptimizeSystemSizingRequest` | `FacadeResponse[OptimizationResult]` |
| `POST` | `/sensitivity-analysis` | One-at-a-time parameter sensitivity (Phase 9) | `SensitivityAnalysisRequest` | `FacadeResponse[OATSensitivityResult]` |
| `POST` | `/break-even-analysis` | Payback & break-even parameter scan (Phase 9) | `BreakEvenAnalysisRequest` | `FacadeResponse[BreakEvenResult]` |
| `POST` | `/grid-2d-analysis` | 2D parameter sweep analysis (Phase 9) | `Grid2DAnalysisRequest` | `FacadeResponse[Grid2DResult]` |
| `POST` | `/speed-cooptimization` | Joint speed & sizing co-optimization (Phase 9) | `SpeedCoOptimizationFacadeRequest` | `FacadeResponse[SpeedCoOptimizationResult]` |
| `POST` | `/portfolio-optimization` | Fleet retrofit portfolio allocation (Phase 9) | `PortfolioOptimizationFacadeRequest` | `FacadeResponse[PortfolioAllocationResult]` |
| `POST` | `/cii-trajectory` | Multi-year IMO CII trajectory simulation (Phase 9) | `CIIComplianceTrajectoryRequest` | `FacadeResponse[TrajectorySimulationResult]` |
| `POST` | `/export-dossier` | Scenario dossier artifact export (Phase 9) | `DossierExportFacadeRequest` | `FacadeResponse[Dict[str, Any]]` |

### 5.2 Operator Router (`/api/v1/operator`)

| Method | Route | Description | Request Model | Response Model |
|---|---|---|---|---|
| `POST` | `/state` | Evaluate operator state from `DecisionContext` | `OperatorContextRequest` | `OperatorStateResponse` |
| `POST` | `/state/from-voyage` | Evaluate operator state from `VoyageContext` | `OperatorVoyageRequest` | `OperatorStateResponse` |
| `POST` | `/state/from-telemetry` | Enrich telemetry with weather and evaluate state | `OperatorTelemetryRequest` | `OperatorStateResponse` |
| `GET` | `/health` | Liveness check for operator service | N/A | `{"status": "healthy", ...}` |

### 5.3 System Endpoints

| Method | Route | Description | Response |
|---|---|---|---|
| `GET` | `/` | API Root Metadata | `{"name": "...", "version": "1.0.0", "status": "online"}` |
| `GET` | `/health` | Application Health Status | `{"status": "healthy"}` |

---

## 6. Structured Error Contract (`APIErrorResponse`)

All error responses adhere to the standard Pydantic schema:

```json
{
  "status_code": 422,
  "error_type": "VALIDATION_ERROR",
  "message": "Request payload failed contract schema validation.",
  "details": [
    "body -> ship_type: Field required"
  ],
  "timestamp_utc": "2026-06-15T12:00:00+00:00"
}
```

### HTTP Status Code Mapping
- **400 Bad Request (`FACADE_VALIDATION_ERROR` / `FACADE_ERROR`):** Invalid business inputs (e.g. invalid ship type, invalid route ID).
- **404 Not Found (`NOT_FOUND`):** Non-existent API route or requested resource.
- **422 Unprocessable Entity (`VALIDATION_ERROR`):** Pydantic schema contract validation failure.
- **500 Internal Server Error (`INTERNAL_SERVER_ERROR` / `FACADE_EXECUTION_ERROR`):** Unhandled server error or fatal computation failure (raw tracebacks suppressed from client response).
- **503 Service Unavailable (`SERVICE_UNAVAILABLE`):** Upstream provider failure.

---

## 7. Security & Safety Audits

### 7.1 Security Audit Summary
- **No `eval()` / `exec()`:** Scanned and verified absent across `app/api/*`.
- **No Direct Subprocess Execution:** Scanned and verified absent across `app/api/*`.
- **No Arbitrary File I/O:** API routers perform zero disk reads/writes (`open()` absent).
- **No Direct External Weather Requests:** Routers strictly consume `WeatherProvider` abstraction through dependency injection; raw URLs (`open-meteo.com`) and direct HTTP client calls are strictly prohibited in routers.

### 7.2 No-Autonomy Audit Summary
- Verified zero actuation endpoints exist (`/throttle`, `/rudder`, `/steering`, `/engine-start`, `/engine-stop`, `/route-change`, `/actuation`).
- Prohibited actuation terms (`set_throttle`, `set_rudder`, `start_engine`, etc.) verified completely absent from `app/api/*`.
- `human_review_required = True` verified enforced on all advisory response items.

### 7.3 No-Physics Audit Summary
- Verified zero physics equations, fuel consumption formulas, or hydrodynamic drag calculations in `app/api/*`.
- Verified zero wind propulsion models (sails, rotors, kites) in `app/api/*`.
- Verified zero engine-off duration estimates in `app/api/*`.

---

## 8. Verification & Test Suite

### 8.1 Dedicated Phase 10C.9 API Tests (`tests/test_application_api.py`)

36 dedicated unit and integration tests covering:
- Tests 1–3: Application factory, health endpoints, and OpenAPI schema generation.
- Tests 4–15: Operator state from context, voyage, and telemetry; weather provenance/quality/freshness preservation; missing telemetry preservation (`None != 0.0`); advisory policy threshold sensitivity; and error propagation.
- Tests 16–25: All 10 engineering operations forwarded cleanly to `EngineeringService` -> `MaritimeScenarioFacade`.
- Tests 26–36: Schema rejection (422), non-existent routes (404), provider failure (500), no-actuation audit, no-dynamic-code audit, no-file-write audit, and no-direct-weather audit.

**Result: 36 / 36 PASS (100% green in 7.01s)**

### 8.2 Full Repository Regression

```text
tests/test_advisory_engine.py .......................................... [  5%]
tests/test_advisory_pipeline.py .........................                [  9%]
tests/test_application_api.py ....................................       [ 14%]
tests/test_decision_context.py .........................                 [ 17%]
tests/test_engineering_service.py .............                          [ 19%]
tests/test_facade.py ................                                    [ 21%]
tests/test_open_meteo_provider.py .......................                [ 25%]
tests/test_operator_service.py .......................                   [ 28%]
tests/test_phase3_contracts.py ..................                        [ 30%]
tests/test_phase3b_baseline.py ...............                           [ 32%]
tests/test_phase3c_feasibility.py ................................       [ 37%]
tests/test_phase3d_displacement.py .............................         [ 41%]
tests/test_phase3e_coordinator.py .............................          [ 45%]
tests/test_phase3f_comparison.py ................................        [ 49%]
tests/test_phase3g_fleet.py .................................            [ 53%]
tests/test_phase6_gateway.py .............                               [ 55%]
tests/test_phase6_pollutants.py ......                                   [ 56%]
tests/test_phase6_regulatory.py ..............                           [ 58%]
tests/test_phase7_economics.py ............................              [ 62%]
tests/test_phase8_optimizer.py ......................................... [ 67%]
tests/test_phase9_cii_trajectory.py .................................... [ 72%]
tests/test_phase9_dossier_exporter.py .................................. [ 77%]
tests/test_phase9_portfolio_optimizer.py ............................... [ 82%]
tests/test_phase9_sensitivity.py ......................................  [ 88%]
tests/test_phase9_speed_cooptimizer.py ................................. [ 93%]
tests/test_voyage_context.py ........................                    [ 97%]
tests/test_weather_provider.py ....................                      [100%]

==================== 731 passed, 76758 warnings in 57.72s =====================
```

---

## 9. Frozen Artifact Integrity Audit

| Canonical Asset | Expected / Frozen SHA-256 Hash | Status |
|---|---|---|
| `models/weather_final.joblib` | `39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3` | **MATCH** |
| `models/fuel_xgb.joblib` | `cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323` | **MATCH** |
| `models/battery_soh_final.joblib` | `9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1` | **MATCH** |
| `models/battery_soc_lstm.pt` | `c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25` | **MATCH** |
| `data/reference/ship_profiles.csv` | `0f2040a481790b034fac11cd9e2b628c725281397610fe0bdba09f6feed7de75` | **MATCH** |
| `data/raw/` file count | `6,228 files` | **MATCH** |

---

## 10. Conclusion & Final Status

Phase 10C.9 successfully establishes the complete, verified, strongly-typed HTTP API boundary for the maritime platform without compromising system boundaries, introducing ungrounded physics, or creating autonomous actuation pathways.

`PHASE 10C.9 — IMPLEMENTED / VERIFIED / READY FOR NEXT PHASE`
