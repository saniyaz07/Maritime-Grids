# Phase 10C.10 — Persistent Application & Voyage State

**Status:** IMPLEMENTED / VERIFIED / READY FOR NEXT PHASE  
**Execution Mode:** Controlled Implementation + State Contract Validation + Mandatory Self-Audit  
**Location:** `app/state/`, `app/services/operator_service.py`, `app/api/`  
**Test Baseline:** 784 / 784 PASS (100% green across all phases: 731 baseline + 53 Phase 10C.10 state contract, repository, and API tests)  

---

## 1. Executive Summary & Purpose

Phase 10C.10 establishes the **Persistent Application & Voyage State Boundary** beneath the application services and HTTP API transport layer.

This layer enables maritime clean-energy operational situational awareness, route monitoring, weather updates, and decision-support advisory contexts to maintain and retrieve validated application state across requests.

```
                      +-----------------------------+
                      |  Future Dashboard / Client  |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |          HTTP API           |
                      |   `/api/v1/operator/voyages`|
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |    APPLICATION SERVICES     |
                      |      `OperatorService`      |
                      +--------------+--------------+
                                     |
                                     v
                      +-----------------------------+
                      |     PERSISTENCE BOUNDARY    |
                      |        `StateRepository`    |
                      +--------------+--------------+
                                     |
             +-----------------------+-----------------------+
             |                                               |
             v                                               v
+--------------------------+                   +--------------------------+
| InMemoryStateRepository  |                   |   SQLiteStateRepository  |
|  (Thread-safe RLock,     |                   |  (100% Parameterized SQL,|
|   Snapshot Isolation)    |                   |   Atomic Transactions)   |
+--------------------------+                   +--------------------------+
```

---

## 2. Strict Scope & Invariants Preserved

1. **Pure Persistence Boundary:**
   - Provides CRUD operations (`save`, `get`, `get_or_raise`, `list_all`, `update`, `delete`) for `PersistedVoyageState`.
   - Thread-safe in-memory repository with snapshot isolation (`model_copy(deep=True)`).
   - Embedded SQLite repository with 100% parameterized SQL queries (`?` placeholders) and zero string formatting.
2. **Optimistic Concurrency Control:**
   - Every persisted voyage record contains an integer `state_version` (starting at 1).
   - Atomic conditional updates: an optional `expected_version` in `StateUpdateRequest` ensures concurrent edits do not overwrite newer state, raising `StateConflictError` (HTTP 409) upon mismatch.
   - Successful updates increment `state_version += 1` and refresh `updated_at_utc`.
3. **Zero Forbidden Technologies:**
   - **No** React, HTML, or UI widgets.
   - **No** WebSockets, SSE, or streaming sockets.
   - **No** Cloud databases, external services, or heavyweight ORMs.
   - **No** Authentication, JWTs, sessions, or RBAC.
   - **No** LLMs, RAG, or autonomous agents.
4. **Zero Autonomous Actuation / Vessel Control:**
   - **No** methods or endpoints for throttle, rudder, steering, engine start/stop, speed change, or route override.
   - Pure state storage and human-in-the-loop decision support (`human_review_required = True`).
5. **Zero Physics Invention:**
   - **No** physics calculations or altered fuel equations in persistence models or repository layers.
   - **No** wind propulsion, sails, rotors, kites, or engine-off duration calculations.
6. **Truthful Telemetry Preservation:**
   - Unobserved/missing telemetry fields remain `None` (`Optional[float]`), never defaulted to `0.0`.
   - Stale/invalid weather states remain explicitly `STALE` and `INVALID`.
   - Weather provenance (`OBSERVED`, `HISTORICAL`, `FORECAST`, `SIMULATED`) preserved intact.
7. **Explicit Advisory Policies:**
   - Zero hardcoded threshold defaults (`20%`, `35%`, `1000 L`, `25 kts`, `2.5 m`).

---

## 3. Package Structure

```
app/state/
├── __init__.py               # Exports contracts, repositories, and domain exceptions
├── contracts.py              # Pydantic state models (PersistedVoyageState, StateUpdateRequest)
├── repository.py             # Abstract base class StateRepository
├── memory_repository.py      # Thread-safe in-memory store with snapshot isolation
└── sqlite_repository.py      # 100% Parameterized SQLite store with optimistic concurrency
```

---

## 4. State Contracts (`app/state/contracts.py`)

### `PersistedVoyageState`
The core state entity representing the full operational and advisory context of an active, planned, or completed voyage:

- `voyage_id: str` — Unique voyage identifier (PK).
- `vessel_id: str` — Associated vessel identifier.
- `ship_type: str` — Vessel classification (e.g., `"Oil Service Boat"`, `"Crew Boat"`).
- `route_id: str` — Active route identifier.
- `status: VoyageStatus` — Lifecycle state (`PLANNED`, `ACTIVE`, `PAUSED`, `COMPLETED`, `ABORTED`).
- `state_version: int` — Monotonically increasing version counter (starts at 1, `>= 1`).
- `created_at_utc: str` — ISO 8601 creation timestamp.
- `updated_at_utc: str` — ISO 8601 last update timestamp.
- `current_position: VesselPosition` — Current spatial telemetry.
- `route: Route` — Voyage route geometry and waypoints.
- `timeline: Optional[VoyageTimeline]` — Progress metrics, remaining distance, ETA.
- `energy_state: Optional[VesselEnergyState]` — Fuel/battery telemetry (`None` when unobserved).
- `weather: Optional[VoyageWeatherContext]` — Point & route weather contexts.
- `regulatory: Optional[RegulatoryContext]` — Regulatory zones and environmental constraints.
- `advisories: Optional[List[AdvisoryNotice]]` — Evaluated advisory notices.
- `metadata: Dict[str, Any]` — Arbitrary extensible metadata.

Includes factory method `PersistedVoyageState.from_operator_state(state, voyage_id, route, state_version, metadata)` for mapping transient `OperatorStateResponse` into persistent records.

### `StateUpdateRequest`
Defines partial updates to existing state records:
- `expected_version: Optional[int]` — Target version for optimistic concurrency control.
- `status: Optional[VoyageStatus]` — Updated lifecycle status.
- `current_position: Optional[VesselPosition]` — Updated position telemetry.
- `route: Optional[Route]` — Updated route definition.
- `timeline: Optional[VoyageTimeline]` — Updated timeline metrics.
- `energy_state: Optional[VesselEnergyState]` — Updated energy state.
- `weather: Optional[VoyageWeatherContext]` — Updated weather context.
- `regulatory: Optional[RegulatoryContext]` — Updated regulatory context.
- `advisories: Optional[List[AdvisoryNotice]]` — Updated advisory notices.
- `metadata: Optional[Dict[str, Any]]` — Updated or merged metadata.

---

## 5. Repository Implementations

### Abstract Interface (`StateRepository`)
```python
class StateRepository(ABC):
    @abstractmethod
    def save(self, state: PersistedVoyageState) -> PersistedVoyageState: ...
    @abstractmethod
    def get(self, voyage_id: str) -> Optional[PersistedVoyageState]: ...
    @abstractmethod
    def get_or_raise(self, voyage_id: str) -> PersistedVoyageState: ...
    @abstractmethod
    def list_all(self, limit: int = 100, offset: int = 0) -> List[PersistedVoyageState]: ...
    @abstractmethod
    def update(self, voyage_id: str, update: StateUpdateRequest) -> PersistedVoyageState: ...
    @abstractmethod
    def delete(self, voyage_id: str) -> bool: ...
```

### `InMemoryStateRepository`
- **Concurrency Safety:** Uses `threading.RLock` guarding internal dictionary `_storage`.
- **Snapshot Isolation:** Deep-copies entities on input and output using `model_copy(deep=True)` to prevent outside reference mutations.
- **Optimistic Locking:** Rejects updates when `expected_version` does not match the stored `state_version`.

### `SQLiteStateRepository`
- **Pure Parameterization:** 100% of queries use `?` placeholders; zero string formatting or injection vulnerabilities.
- **Schema:**
  ```sql
  CREATE TABLE IF NOT EXISTS voyage_states (
      voyage_id TEXT PRIMARY KEY,
      vessel_id TEXT NOT NULL,
      route_id TEXT NOT NULL,
      status TEXT NOT NULL,
      state_version INTEGER NOT NULL DEFAULT 1,
      created_at_utc TEXT NOT NULL,
      updated_at_utc TEXT NOT NULL,
      state_json TEXT NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_voyage_states_vessel ON voyage_states (vessel_id);
  CREATE INDEX IF NOT EXISTS idx_voyage_states_status ON voyage_states (status);
  ```
- **Atomic Version Increments:**
  Updates perform conditional SQL updates `WHERE voyage_id = ? AND state_version = ?` ensuring strict transaction-level concurrency control.

---

## 6. Service Layer Integration (`OperatorService`)

`OperatorService` accepts an optional `StateRepository` (defaulting to `InMemoryStateRepository`) and provides high-level persistence helpers:

- `save_voyage_state(state: PersistedVoyageState) -> PersistedVoyageState`
- `get_voyage_state(voyage_id: str) -> PersistedVoyageState`
- `list_voyage_states(limit: int = 100, offset: int = 0) -> List[PersistedVoyageState]`
- `update_voyage_state(voyage_id: str, update: StateUpdateRequest) -> PersistedVoyageState`
- `delete_voyage_state(voyage_id: str) -> bool`
- `persist_operator_state(state_response, voyage_id, route, metadata) -> PersistedVoyageState`

---

## 7. HTTP API Transport Boundary Endpoints

New persistent endpoints registered under `/api/v1/operator/voyages`:

| Method | Endpoint | Status | Description |
|---|---|---|---|
| `POST` | `/api/v1/operator/voyages` | `201 Created` | Creates and persists a new voyage state record. Returns `409 Conflict` if duplicate. |
| `GET` | `/api/v1/operator/voyages` | `200 OK` | Lists persisted voyages with `limit` and `offset` query parameters. |
| `GET` | `/api/v1/operator/voyages/{voyage_id}` | `200 OK` | Retrieves persisted voyage state by ID. Returns `404 Not Found` if missing. |
| `PUT` | `/api/v1/operator/voyages/{voyage_id}` | `200 OK` | Applies partial update, verifies `expected_version`, and increments `state_version`. |
| `DELETE` | `/api/v1/operator/voyages/{voyage_id}` | `204 No Content` | Removes persisted voyage state record. Returns `404 Not Found` if missing. |

---

## 8. Error Normalization & Status Code Mapping

| Exception | HTTP Status | Error Type | Description |
|---|---|---|---|
| `StateNotFoundError` | `404 Not Found` | `NOT_FOUND` | Voyage state does not exist in repository. |
| `StateConflictError` | `409 Conflict` | `CONFLICT` | Duplicate voyage ID on creation or optimistic version mismatch on update. |
| `StateValidationError` | `400 Bad Request` | `VALIDATION_ERROR` | Malformed state input or invalid transitions. |
| `RequestValidationError` | `422 Unprocessable Content` | `VALIDATION_ERROR` | Schema validation error in request body or parameters. |

All error responses adhere strictly to the standardized `APIErrorResponse` schema:
```json
{
  "error_type": "CONFLICT",
  "message": "Optimistic concurrency conflict: state_version 1 does not match expected_version 99",
  "detail": {
    "voyage_id": "VOY_001",
    "current_version": 1,
    "expected_version": 99
  },
  "timestamp_utc": "2026-06-15T12:00:00Z"
}
```

---

## 9. Verification & Regression Audit

### 1. Dedicated Test Suite
- `tests/test_state_contracts.py`: 8 tests
- `tests/test_state_repository.py`: 31 tests (across InMemory, SQLite memory, and SQLite disk)
- `tests/test_state_api.py`: 14 tests (CRUD endpoints, error handling, security and actuation audits)
- **Phase 10C.10 Total:** 53 tests (100% pass)

### 2. Full Regression Baseline
- **Total Tests:** 784 passed (0 failures, 0 errors)
- **Execution Time:** ~59 seconds

### 3. Canonical Model & Data Integrity Hashes
| Artifact | SHA-256 Hash | Status |
|---|---|---|
| `models/weather_final.joblib` | `39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3` | Verified Match |
| `models/fuel_xgb.joblib` | `cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323` | Verified Match |
| `models/battery_soh_final.joblib` | `9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1` | Verified Match |
| `models/battery_soc_lstm.pt` | `c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25` | Verified Match |
| `data/reference/ship_profiles.csv` | `0f2040a481790b034fac11cd9e2b628c725281397610fe0bdba09f6feed7de75` | Verified Match |
| `data/raw/` file count | `6,228` files | Verified Match |

---

## 10. Conclusion

Phase 10C.10 delivers a reliable, thread-safe, injection-proof persistent state boundary that completely integrates with `OperatorService` and the FastAPI transport layer, strictly preserving all safety, non-actuation, and data integrity guarantees.
