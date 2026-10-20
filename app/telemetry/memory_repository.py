"""
app/telemetry/memory_repository.py — Phase 10C.13 In-Memory Telemetry Audit Repository
====================================================================================
Thread-safe, high-performance in-memory implementation of TelemetryAuditRepository
with bounded memory buffers for fast development, testing, and transient simulation.
"""

from datetime import datetime, timezone
import threading
from typing import List, Optional

from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    TelemetryProvenanceType,
    TelemetryQualityState,
)
from app.telemetry.repository import TelemetryAuditRecord, TelemetryAuditRepository


class InMemoryTelemetryAuditRepository(TelemetryAuditRepository):
    """
    In-memory thread-safe implementation of TelemetryAuditRepository.
    """

    def __init__(self, max_records: int = 5000) -> None:
        self.max_records = max_records
        self._lock = threading.RLock()
        self._records: List[TelemetryAuditRecord] = []
        self._by_id: dict[str, TelemetryAuditRecord] = {}

    def record(self, payload: CanonicalTelemetryPayload) -> TelemetryAuditRecord:
        with self._lock:
            audit_entry = TelemetryAuditRecord.from_payload(payload)
            self._records.append(audit_entry)
            self._by_id[audit_entry.record_id] = audit_entry

            # Enforce bounded buffer size
            if len(self._records) > self.max_records:
                evicted = self._records.pop(0)
                self._by_id.pop(evicted.record_id, None)

            return audit_entry

    def get(self, record_id: str) -> Optional[TelemetryAuditRecord]:
        with self._lock:
            return self._by_id.get(record_id)

    def get_by_id(self, record_id: str) -> Optional[TelemetryAuditRecord]:
        return self.get(record_id)

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
        with self._lock:
            filtered = self._records

            if vessel_id is not None:
                filtered = [r for r in filtered if r.vessel_id == vessel_id]
            if source is not None:
                filtered = [r for r in filtered if r.source == source]
            if mode is not None:
                filtered = [r for r in filtered if r.mode == mode]
            if quality is not None:
                filtered = [r for r in filtered if r.quality == quality]
            if start_time_utc is not None:
                filtered = [r for r in filtered if r.timestamp_utc >= start_time_utc]
            if end_time_utc is not None:
                filtered = [r for r in filtered if r.timestamp_utc <= end_time_utc]

            # Sort descending by timestamp_utc
            sorted_records = sorted(filtered, key=lambda r: r.timestamp_utc, reverse=True)
            safe_limit = min(max(1, limit), 1000)
            safe_offset = max(0, offset)
            return sorted_records[safe_offset : safe_offset + safe_limit]

    def count(self, vessel_id: Optional[str] = None) -> int:
        with self._lock:
            if vessel_id is None:
                return len(self._records)
            return sum(1 for r in self._records if r.vessel_id == vessel_id)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._by_id.clear()
