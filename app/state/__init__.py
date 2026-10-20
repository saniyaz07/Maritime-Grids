"""
app/state — Phase 10C.10 Persistent Application & Voyage State
===============================================================
Exposes contracts, repository abstractions, in-memory store, SQLite store,
and domain exceptions for persistent voyage application state.
"""

from app.state.contracts import (
    PersistedVoyageState,
    StateConflictError,
    StateNotFoundError,
    StateRepositoryError,
    StateUpdateRequest,
    StateValidationError,
)
from app.state.memory_repository import InMemoryStateRepository
from app.state.repository import StateRepository
from app.state.sqlite_repository import SQLiteStateRepository

__all__ = [
    "PersistedVoyageState",
    "StateUpdateRequest",
    "StateRepository",
    "InMemoryStateRepository",
    "SQLiteStateRepository",
    "StateRepositoryError",
    "StateNotFoundError",
    "StateConflictError",
    "StateValidationError",
]
