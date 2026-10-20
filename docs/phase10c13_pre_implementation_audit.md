# Phase 10C.13 — Pre-Implementation Architecture Audit: Real-Time Streaming & Telemetry Audit Log

**Project Root:** `C:\maritime grids`  
**Execution Mode:** STRICT READ-ONLY FORENSIC AUDIT  
**Phase Target:** `PHASE 10C.13 — REAL-TIME TELEMETRY STREAMING & TELEMETRY AUDIT LOG`  
**Current Baseline:** 808 / 808 Backend Tests PASS (100%), 14/14 Frontend Telemetry Tests PASS, 20/20 Driver Dashboard Tests PASS, 10/10 Frontend Contract Tests PASS, 5 Canonical Model Hashes Verified, 6,228 Raw Data Files Preserved.

---

## 1. Executive Summary

This pre-implementation architecture audit investigates the requirements and existing codebase structure for adding:
1. **Real-Time Read-Only Push Streaming** (SSE / WebSocket) from `TelemetryGateway` to Driver Dashboard V1.
2. **Persistent Telemetry Audit Logging** & Historical Query API using the established repository pattern.

---

## 2. 10-Point Architectural Discovery

### 1. Existing Database Technology
- **Repository Technology**: The project uses **SQLite** (`sqlite3` module) and **In-Memory** repository backends (`InMemoryStateRepository`, `SQLiteStateRepository`).
- **Design Decision**: Continue using SQLite for persistence and an In-Memory alternative for rapid in-memory testing. No secondary database engine (e.g. Postgres, MongoDB) is needed.

### 2. Existing Repository Pattern
- Defined via an abstract base class (`StateRepository`) in `app/state/repository.py` with concrete implementations `InMemoryStateRepository` and `SQLiteStateRepository`.
- Uses thread-safe synchronization (`threading.RLock`), parameterized SQL queries, and Pydantic V2 `model_dump_json()` / `model_validate()` serialization.

### 3. Existing SQLAlchemy / Session Architecture
- **None**: The project does not use an ORM or SQLAlchemy session layer. It relies directly on parameterized SQLite queries with strongly typed Pydantic models. We will adhere to this lightweight, high-performance approach.

### 4. Existing Migration Mechanism
- Schema initialization occurs idempotently via `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` inside repository `_init_db()` during construction.

### 5. Existing API Conventions
- Built with **FastAPI** routers mounted under `/api/v1/operator` and `/api/v1/engineering`.
- Dependency injection via `app/api/dependencies.py` (`get_operator_service`, `get_telemetry_gateway`, `get_state_repository`, `get_weather_provider`).
- Standardized error handling, query parameters with validation, and strict Pydantic response models.

### 6. Existing Telemetry Gateway Behavior
- Implemented in `app/telemetry/gateway.py` with `TelemetryAdapter`, `TelemetrySimulator`, and thread-safe lock buffering the latest `CanonicalTelemetryPayload`.
- Provides `.ingest_raw()`, `.get_current_frame()`, and `.load_scenario()` (Scenarios A through H).
- Freshness evaluation automatically degrades engine state to `UNKNOWN` when expired ($> 900\text{ s}$) or disconnected.

### 7. Existing Frontend Polling Behavior
- `DriverDashboardPage` currently polls `/api/v1/operator/telemetry/current` every 15,000 ms via `setInterval`.
- SSE push streaming will replace / augment this polling loop with immediate push event notifications upon frame ingestion.

### 8. Existing Error-Handling Conventions
- Standard HTTP exceptions (`400 Bad Request`, `404 Not Found`, `409 Conflict`, `422 Unprocessable Content`).
- Validation failures in telemetry normalization are recorded into `quality.validation_errors` rather than throwing uncaught crashes.

### 9. Existing Timestamp Conventions
- All timestamps across backend and frontend are normalized to **ISO 8601 UTC strings** via `NormalizedWeatherRecord.validate_and_normalize_iso_utc()`.

### 10. Existing Provenance & Freshness Semantics
- **Provenance**: `OBSERVED`, `HISTORICAL`, `FORECAST`, `SIMULATED`, `UNAVAILABLE`.
- **Freshness**: `FRESH`, `STALE`, `EXPIRED`, `UNKNOWN`, `DISCONNECTED`.
- **Stream Connection State** vs **Data Freshness**:
  - Stream State: `CONNECTED`, `WAITING`, `RECONNECTING`, `DISCONNECTED`.
  - Data Freshness: `FRESH`, `STALE`, `EXPIRED`.
  - These two orthogonal states must be displayed separately on the dashboard.

---

## 3. Streaming Protocol Decision: Server-Sent Events (SSE)

**Decision: Server-Sent Events (SSE) via `GET /api/v1/operator/telemetry/stream`**
- **Rationale**:
  1. The bridge telemetry stream is strictly **server-to-client (unidirectional push)**. The client does not need to send upstream messages over the stream.
  2. Native browser `EventSource` provides automatic, robust, built-in reconnection with backoff without requiring complex custom WebSocket ping/pong and framed handshake infrastructure.
  3. Seamlessly integrates with FastAPI / Starlette via `StreamingResponse` (MIME `text/event-stream`).
  4. Fully testable via standard HTTP streaming clients.

---

## 4. Pre-Implementation Audit Sign-Off

The audit confirms full architectural readiness. Implementation of **Phase 10C.13 Real-Time Telemetry Streaming & Audit Log** may proceed.
