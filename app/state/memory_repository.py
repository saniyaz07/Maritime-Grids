"""
app/state/memory_repository.py — Phase 10C.10 In-Memory State Repository
=========================================================================
Thread-safe in-memory implementation of StateRepository for deterministic unit tests.

Key Invariants:
  - Thread-safe mutation via RLock.
  - Snapshot isolation via Pydantic model_copy(deep=True).
  - Deterministic version incrementation and optimistic concurrency checks.
"""

from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional

from app.state.contracts import (
    PersistedVoyageState,
    StateConflictError,
    StateNotFoundError,
    StateUpdateRequest,
)
from app.state.repository import StateRepository


class InMemoryStateRepository(StateRepository):
    """Thread-safe in-memory store for PersistedVoyageState records."""

    def __init__(self) -> None:
        self._store: Dict[str, PersistedVoyageState] = {}
        self._lock = threading.RLock()

    def save(self, state: PersistedVoyageState) -> PersistedVoyageState:
        with self._lock:
            if state.voyage_id in self._store:
                raise StateConflictError(
                    f"Voyage state with voyage_id '{state.voyage_id}' already exists.",
                    voyage_id=state.voyage_id,
                )
            stored_state = state.model_copy(deep=True)
            self._store[state.voyage_id] = stored_state
            return stored_state.model_copy(deep=True)

    def get(self, voyage_id: str) -> Optional[PersistedVoyageState]:
        with self._lock:
            state = self._store.get(voyage_id)
            if state is None:
                return None
            return state.model_copy(deep=True)

    def list_all(self, limit: int = 100, offset: int = 0) -> List[PersistedVoyageState]:
        with self._lock:
            all_records = list(self._store.values())
            # Return ordered by created_at_utc ascending
            all_records.sort(key=lambda s: s.created_at_utc)
            sliced = all_records[offset : offset + limit]
            return [s.model_copy(deep=True) for s in sliced]

    def update(self, voyage_id: str, update: StateUpdateRequest) -> PersistedVoyageState:
        with self._lock:
            current = self._store.get(voyage_id)
            if current is None:
                raise StateNotFoundError(voyage_id)

            # Optimistic concurrency guard
            if update.expected_version is not None and update.expected_version != current.state_version:
                raise StateConflictError(
                    f"Version conflict for voyage '{voyage_id}': expected version {update.expected_version}, "
                    f"but current version is {current.state_version}.",
                    voyage_id=voyage_id,
                )

            # Construct updated fields
            updated_dict = current.model_dump()
            now_ts = datetime.now(timezone.utc).isoformat()

            # Apply partial updates
            if update.status is not None:
                updated_dict["status"] = update.status
            if update.current_position is not None:
                updated_dict["current_position"] = update.current_position.model_dump()
            if update.route is not None:
                updated_dict["route"] = update.route.model_dump()
            if update.route_progress is not None:
                updated_dict["route_progress"] = update.route_progress.model_dump()
            if update.weather is not None:
                updated_dict["weather"] = update.weather.model_dump()
            if update.energy is not None:
                updated_dict["energy"] = update.energy.model_dump()
            if update.regulatory is not None:
                updated_dict["regulatory"] = update.regulatory.model_dump()
            if update.advisories is not None:
                updated_dict["advisories"] = update.advisories.model_dump()
            if update.metadata is not None:
                updated_dict["metadata"] = update.metadata

            # Increment state version and update timestamp
            updated_dict["state_version"] = current.state_version + 1
            updated_dict["updated_at_utc"] = now_ts

            updated_state = PersistedVoyageState.model_validate(updated_dict)
            self._store[voyage_id] = updated_state
            return updated_state.model_copy(deep=True)

    def delete(self, voyage_id: str) -> bool:
        with self._lock:
            if voyage_id in self._store:
                del self._store[voyage_id]
                return True
            return False

    def clear(self) -> None:
        """Utility for test suite cleanup."""
        with self._lock:
            self._store.clear()
