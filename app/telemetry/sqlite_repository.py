"""
app/telemetry/sqlite_repository.py — Phase 10C.13 SQLite Telemetry Audit Repository
==================================================================================
Thread-safe SQLite persistent repository for telemetry time-series and audit logging.

Key Invariants:
  - Parameterized SQL queries (100% injection-safe).
  - Pydantic model serialization & deserialization.
  - Indexed for fast range filtering by timestamp and vessel.
  - Thread-safe connection synchronization via threading.RLock.
"""

import json
import sqlite3
import threading
from typing import Any, List, Optional

from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    TelemetryProvenanceType,
    TelemetryQualityState,
)
from app.telemetry.repository import TelemetryAuditRecord, TelemetryAuditRepository


class SQLiteTelemetryAuditRepository(TelemetryAuditRepository):
    """
    SQLite persistent implementation of TelemetryAuditRepository.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Creates table and indexes if not existing."""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS telemetry_audit_log (
                        record_id TEXT PRIMARY KEY,
                        telemetry_id TEXT NOT NULL,
                        timestamp_utc TEXT NOT NULL,
                        vessel_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        stream_id TEXT,
                        quality TEXT NOT NULL,
                        freshness TEXT NOT NULL,
                        freshness_age_seconds REAL,
                        payload_json TEXT NOT NULL,
                        validation_errors_json TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_telemetry_audit_vessel_time
                    ON telemetry_audit_log(vessel_id, timestamp_utc)
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_telemetry_audit_time
                    ON telemetry_audit_log(timestamp_utc)
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_telemetry_audit_mode
                    ON telemetry_audit_log(mode)
                    """
                )

    def record(self, payload: CanonicalTelemetryPayload) -> TelemetryAuditRecord:
        with self._lock:
            audit_entry = TelemetryAuditRecord.from_payload(payload)
            payload_json = audit_entry.payload.model_dump_json()
            errors_json = json.dumps(audit_entry.validation_errors)

            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO telemetry_audit_log (
                        record_id, telemetry_id, timestamp_utc, vessel_id,
                        source, mode, stream_id, quality, freshness,
                        freshness_age_seconds, payload_json, validation_errors_json,
                        created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_entry.record_id,
                        audit_entry.telemetry_id,
                        audit_entry.timestamp_utc,
                        audit_entry.vessel_id,
                        audit_entry.source,
                        audit_entry.mode.value,
                        audit_entry.stream_id,
                        audit_entry.quality.value,
                        audit_entry.freshness.value,
                        audit_entry.freshness_age_seconds,
                        payload_json,
                        errors_json,
                        audit_entry.created_at_utc,
                    ),
                )
            return audit_entry

    def get(self, record_id: str) -> Optional[TelemetryAuditRecord]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM telemetry_audit_log WHERE record_id = ?",
                (record_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

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
            clauses: List[str] = []
            params: List[Any] = []

            if vessel_id is not None:
                clauses.append("vessel_id = ?")
                params.append(vessel_id)
            if source is not None:
                clauses.append("source = ?")
                params.append(source)
            if mode is not None:
                clauses.append("mode = ?")
                params.append(mode.value)
            if quality is not None:
                clauses.append("quality = ?")
                params.append(quality.value)
            if start_time_utc is not None:
                clauses.append("timestamp_utc >= ?")
                params.append(start_time_utc)
            if end_time_utc is not None:
                clauses.append("timestamp_utc <= ?")
                params.append(end_time_utc)

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            safe_limit = min(max(1, limit), 1000)
            safe_offset = max(0, offset)

            params.extend([safe_limit, safe_offset])

            sql = f"""
                SELECT * FROM telemetry_audit_log
                {where_sql}
                ORDER BY timestamp_utc DESC
                LIMIT ? OFFSET ?
            """

            cur = self._conn.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [self._row_to_record(r) for r in rows]

    def count(self, vessel_id: Optional[str] = None) -> int:
        with self._lock:
            if vessel_id is not None:
                cur = self._conn.execute(
                    "SELECT COUNT(*) as cnt FROM telemetry_audit_log WHERE vessel_id = ?",
                    (vessel_id,),
                )
            else:
                cur = self._conn.execute("SELECT COUNT(*) as cnt FROM telemetry_audit_log")
            row = cur.fetchone()
            return int(row["cnt"]) if row else 0

    def clear(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM telemetry_audit_log")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TelemetryAuditRecord:
        payload_data = json.loads(row["payload_json"])
        errors_data = json.loads(row["validation_errors_json"])
        payload = CanonicalTelemetryPayload.model_validate(payload_data)

        return TelemetryAuditRecord(
            record_id=row["record_id"],
            telemetry_id=row["telemetry_id"],
            timestamp_utc=row["timestamp_utc"],
            vessel_id=row["vessel_id"],
            source=row["source"],
            mode=TelemetryProvenanceType(row["mode"]),
            stream_id=row["stream_id"],
            quality=TelemetryQualityState(row["quality"]),
            freshness=payload.quality.freshness,
            freshness_age_seconds=row["freshness_age_seconds"],
            payload=payload,
            validation_errors=errors_data,
            created_at_utc=row["created_at_utc"],
        )
