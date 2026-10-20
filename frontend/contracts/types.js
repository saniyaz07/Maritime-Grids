/**
 * frontend/contracts/types.js — Phase 10C.11A Typed Frontend Contracts & Enums
 * ==============================================================================
 * Mirrors backend Pydantic V2 schemas for OperatorStateResponse, PersistedVoyageState,
 * NormalizedWeatherRecord, VesselEnergyState, AdvisoryNotice, and Engineering APIs.
 * 
 * Strict Invariants:
 *   - Null is NEVER converted to zero (null != 0).
 *   - Provenance enums match backend WeatherProvenanceType exactly.
 *   - 'DERIVED' is NOT a weather provenance enum.
 *   - Human review required is preserved as an explicit boolean.
 */

// 1. Semantic Enums matching backend app/weather/contracts.py
export const WeatherProvenanceType = Object.freeze({
  OBSERVED: "OBSERVED",
  HISTORICAL: "HISTORICAL",
  FORECAST: "FORECAST",
  MODEL_PREDICTION: "MODEL_PREDICTION",
  SIMULATED: "SIMULATED",
  UNAVAILABLE: "UNAVAILABLE",
});

export const WeatherQualityState = Object.freeze({
  VALID: "VALID",
  PARTIAL: "PARTIAL",
  INVALID: "INVALID",
  UNAVAILABLE: "UNAVAILABLE",
});

export const WeatherFreshnessState = Object.freeze({
  FRESH: "FRESH",
  STALE: "STALE",
  EXPIRED: "EXPIRED",
  UNKNOWN: "UNKNOWN",
});

export const VoyageStatus = Object.freeze({
  PLANNED: "PLANNED",
  ACTIVE: "ACTIVE",
  PAUSED: "PAUSED",
  COMPLETED: "COMPLETED",
  CANCELLED: "CANCELLED",
  ABORTED: "ABORTED",
});

export const AdvisorySeverity = Object.freeze({
  CRITICAL: "CRITICAL",
  WARNING: "WARNING",
  NOTICE: "NOTICE",
  INFO: "INFO",
});

export const AdvisoryCategory = Object.freeze({
  WEATHER: "WEATHER",
  ENERGY: "ENERGY",
  NAVIGATION: "NAVIGATION",
  REGULATORY: "REGULATORY",
  SYSTEM: "SYSTEM",
});

export const DecisionReadinessState = Object.freeze({
  READY: "READY",
  PARTIAL_DATA: "PARTIAL_DATA",
  UNAVAILABLE: "UNAVAILABLE",
  STALE_WEATHER: "STALE_WEATHER",
  BLOCKED: "BLOCKED",
});

// Semantic origin categories for UI cards
export const DataOriginCategory = Object.freeze({
  MEASURED: "MEASURED",
  FORECAST: "FORECAST",
  HISTORICAL: "HISTORICAL",
  MODEL_PREDICTION: "MODEL_PREDICTION",
  CLIMATOLOGICAL_ESTIMATE: "CLIMATOLOGICAL_ESTIMATE",
  SIMULATED: "SIMULATED",
  APPLICATION_POLICY: "APPLICATION_POLICY",
  REGULATORY: "REGULATORY",
  DERIVED: "DERIVED",
});

// 2. Telemetry Gateway Enums (Phase 10C.12) matching backend app/telemetry/contracts.py
export const EngineOperationalState = Object.freeze({
  ON: "ON",
  OFF: "OFF",
  UNKNOWN: "UNKNOWN",
});

export const TelemetryFreshnessState = Object.freeze({
  FRESH: "FRESH",
  STALE: "STALE",
  EXPIRED: "EXPIRED",
  UNKNOWN: "UNKNOWN",
  DISCONNECTED: "DISCONNECTED",
});

export const TelemetryQualityState = Object.freeze({
  VALID: "VALID",
  PARTIAL: "PARTIAL",
  INVALID: "INVALID",
  UNAVAILABLE: "UNAVAILABLE",
});

export const TelemetryStatusState = Object.freeze({
  LIVE: "LIVE",
  STALE: "STALE",
  EXPIRED: "EXPIRED",
  DISCONNECTED: "DISCONNECTED",
  SIMULATED: "SIMULATED",
});

