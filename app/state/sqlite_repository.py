"""
app/state/sqlite_repository.py — Phase 10C.10 SQLite Persistent State Repository
================================================================================
Thread-safe SQLite-backed persistent repository for development and local testing.

Key Invariants:
  - 100% parameterized SQL statements (zero SQL injection risk).
  - Pydantic model serialization & deserialization.
  - Optimistic concurrency protection and version incrementation.
  - Automatic table schema creation.
  - Thread-safe connection synchronization via threading.RLock.
"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List, Optional

from app.state.contracts import (
    PersistedVoyageState,
    StateConflictError,
    StateNotFoundError,
    StateUpdateRequest,
)
from app.state.repository import StateRepository


class SQLiteStateRepository(StateRepository):
    """SQLite-backed persistent implementation of StateRepository."""

    def __init__(self, db_path: str = ":memory:") -> None:
        """
        Initialize the SQLiteStateRepository.

        Args:
            db_path: Path to the SQLite database file or ':memory:'.
        """
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Creates the voyage_states table schema if it does not already exist."""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS voyage_states (
                        voyage_id TEXT PRIMARY KEY,
                        vessel_id TEXT NOT NULL,
                        route_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        state_version INTEGER NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_voyage_states_vessel
                    ON voyage_states(vessel_id)
                    """
                )

    def save(self, state: PersistedVoyageState) -> PersistedVoyageState:
        with self._lock:
            # Check for existing record
            cur = self._conn.execute(
                "SELECT 1 FROM voyage_states WHERE voyage_id = ?",
                (state.voyage_id,),
            )
            if cur.fetchone() is not None:
                raise StateConflictError(
                    f"Voyage state with voyage_id '{state.voyage_id}' already exists.",
                    voyage_id=state.voyage_id,
                )

            state_json = state.model_dump_json()
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO voyage_states (
                        voyage_id, vessel_id, route_id, status,
                        state_version, created_at_utc, updated_at_utc, state_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.voyage_id,
                        state.vessel_id,
                        state.route_id,
                        state.status.value,
                        state.state_version,
                        state.created_at_utc,
                        state.updated_at_utc,
                        state_json,
                    ),
                )
            return state.model_copy(deep=True)

    def get(self, voyage_id: str) -> Optional[PersistedVoyageState]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT state_json FROM voyage_states WHERE voyage_id = ?",
                (voyage_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            data = json.loads(row["state_json"])
            return PersistedVoyageState.model_validate(data)

    def list_all(self, limit: int = 100, offset: int = 0) -> List[PersistedVoyageState]:
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT state_json FROM voyage_states
                ORDER BY created_at_utc ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
            return [PersistedVoyageState.model_validate(json.loads(r["state_json"])) for r in rows]

    def update(self, voyage_id: str, update: StateUpdateRequest) -> PersistedVoyageState:
        with self._lock:
            cur = self._conn.execute(
                "SELECT state_version, state_json FROM voyage_states WHERE voyage_id = ?",
                (voyage_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise StateNotFoundError(voyage_id)

            current_version = int(row["state_version"])
            # Optimistic concurrency check
            if update.expected_version is not None and update.expected_version != current_version:
                raise StateConflictError(
                    f"Version conflict for voyage '{voyage_id}': expected version {update.expected_version}, "
                    f"but current version is {current_version}.",
                    voyage_id=voyage_id,
                )

            current_dict = json.loads(row["state_json"])
            now_ts = datetime.now(timezone.utc).isoformat()

            # Apply partial updates
            if update.status is not None:
                current_dict["status"] = update.status.value
            if update.current_position is not None:
                current_dict["current_position"] = update.current_position.model_dump()
            if update.route is not None:
                current_dict["route"] = update.route.model_dump()
            if update.route_progress is not None:
                current_dict["route_progress"] = update.route_progress.model_dump()
            if update.weather is not None:
                current_dict["weather"] = update.weather.model_dump()
            if update.energy is not None:
                current_dict["energy"] = update.energy.model_dump()
            if update.regulatory is not None:
                current_dict["regulatory"] = update.regulatory.model_dump()
            if update.advisories is not None:
                current_dict["advisories"] = update.advisories.model_dump()
            if update.metadata is not None:
                current_dict["metadata"] = update.metadata

            new_version = current_version + 1
            current_dict["state_version"] = new_version
            current_dict["updated_at_utc"] = now_ts

            updated_state = PersistedVoyageState.model_validate(current_dict)
            state_json = updated_state.model_dump_json()

            with self._conn:
                self._conn.execute(
                    """
                    UPDATE voyage_states
                    SET status = ?, state_version = ?, updated_at_utc = ?, state_json = ?
                    WHERE voyage_id = ?
                    """,
                    (
                        updated_state.status.value,
                        new_version,
                        now_ts,
                        state_json,
                        voyage_id,
                    ),
                )
            return updated_state

    def delete(self, voyage_id: str) -> bool:
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM voyage_states WHERE voyage_id = ?",
                    (voyage_id,),
                )
                return cur.rowcount > 0

    def close(self) -> None:
        """Closes the underlying SQLite connection."""
        with self._lock:
            self._conn.close()
