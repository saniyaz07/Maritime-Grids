"""
app/telemetry/repository.py — Phase 10C.13 Telemetry Audit Log Contract & Repository
===================================================================================
Defines strongly-typed contracts for persistent telemetry audit logging,
historical queries, and the abstract TelemetryAuditRepository interface.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Strict preservation of raw telemetry values (null != 0).
  - Unmutated preservation of provenance (OBSERVED vs SIMULATED) and validation errors.
  - Bounded query results with deterministic ordering (timestamp_utc DESC).
  - Pure state logging: zero control logic, zero actuator commands.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    TelemetryFreshnessState,
    TelemetryProvenanceType,
    TelemetryQualityState,
)
from app.weather.contracts import NormalizedWeatherRecord


# =====================================================================
# 1. TELEMETRY AUDIT RECORD CONTRACT
# =====================================================================

class TelemetryAuditRecord(BaseModel):
    """
    Standardized persistent record of an ingested canonical telemetry frame.
    Enables historical inspection, voyage replay, and compliance auditing.
    """
    record_id: str = Field(..., min_length=1, description="Unique primary key for the audit log entry")
    telemetry_id: str = Field(..., min_length=1, description="Correlation identifier from the telemetry frame")
    timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp of telemetry observation")
    ingested_at_utc: Optional[str] = Field(default=None, description="ISO 8601 UTC timestamp of host ingestion")
    vessel_id: str = Field(..., min_length=1, description="Target vessel identifier")
    source: str = Field(..., min_length=1, description="Source provider or device name")
    mode: TelemetryProvenanceType = Field(..., description="Provenance mode (OBSERVED, SIMULATED, etc.)")
    stream_id: Optional[str] = Field(default=None, description="Optional stream or channel ID")
    quality: TelemetryQualityState = Field(default=TelemetryQualityState.VALID, description="Data validation quality")
    freshness: TelemetryFreshnessState = Field(default=TelemetryFreshnessState.FRESH, description="Freshness at time of ingest")
    freshness_age_seconds: Optional[float] = Field(default=None, ge=0.0, description="Observed age in seconds at ingest")
    payload: CanonicalTelemetryPayload = Field(..., description="Complete canonical telemetry payload snapshot")
    validation_errors: List[str] = Field(default_factory=list, description="Any quarantined validation errors")
    created_at_utc: str = Field(..., description="ISO 8601 UTC timestamp when recorded into audit database")

    @field_validator("timestamp_utc", "created_at_utc", "ingested_at_utc")
    @classmethod
    def validate_timestamps(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        norm = NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)
        if norm is None:
            raise ValueError(f"Invalid ISO 8601 UTC timestamp: {v}")
        return norm

    @classmethod
    def from_payload(
        cls,
        payload: CanonicalTelemetryPayload,
        record_id: Optional[str] = None,
    ) -> "TelemetryAuditRecord":
        """
        Factory to construct an audit record from a CanonicalTelemetryPayload.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        r_id = record_id or f"AUDIT_{int(datetime.now(timezone.utc).timestamp() * 1000000)}"
        return cls(
            record_id=r_id,
            telemetry_id=payload.telemetry_id,
            timestamp_utc=payload.timestamp_utc,
            ingested_at_utc=payload.ingested_at_utc,
            vessel_id=payload.vessel_id,
            source=payload.provenance.source,
            mode=payload.provenance.mode,
            stream_id=payload.provenance.stream_id,
            quality=payload.quality.overall,
            freshness=payload.quality.freshness,
            freshness_age_seconds=payload.quality.freshness_age_seconds,
            payload=payload,
            validation_errors=payload.quality.validation_errors,
            created_at_utc=now_ts,
        )


# =====================================================================
# 2. ABSTRACT AUDIT REPOSITORY INTERFACE
# =====================================================================

class TelemetryAuditRepository(ABC):
    """
    Abstract interface for persistent telemetry time-series logging.
    """

    @abstractmethod
    def record(self, payload: CanonicalTelemetryPayload) -> TelemetryAuditRecord:
        """
        Records a validated canonical telemetry frame into persistent history.
        """
        pass

    @abstractmethod
    def get(self, record_id: str) -> Optional[TelemetryAuditRecord]:
        """
        Retrieves an audit record by record_id. Returns None if not found.
        """
        pass

    @abstractmethod
    def query(
        self,
        vessel_id: Optional[str] = None,
        start_time_utc: Optional[str] = None,
        end_time_utc: Optional[str] = None,
        source: Optional[str] = None,
        mode: Optional[TelemetryProvenanceType] = None,
        quality: Optional[TelemetryQualityState] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TelemetryAuditRecord]:
        """
        Queries historical telemetry records matching filters ordered by timestamp_utc DESC.
        """
        pass

    @abstractmethod
    def count(self, vessel_id: Optional[str] = None) -> int:
        """
        Returns the total number of audit records stored.
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """
        Clears all audit records (primarily used in test fixtures).
        """
        pass
