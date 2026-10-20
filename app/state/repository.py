"""
app/state/repository.py — Phase 10C.10 State Repository Interface Abstraction
=============================================================================
Defines the abstract StateRepository interface for persistent voyage state storage.

Key Invariants:
  - Strict abstraction decoupling services/API from concrete persistence backends.
  - Consistent error semantics (StateNotFoundError, StateConflictError).
  - Explicit optimistic concurrency support via expected_version.
  - Zero SQL or backend-specific code leaked through the interface.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from app.state.contracts import (
    PersistedVoyageState,
    StateNotFoundError,
    StateUpdateRequest,
)


class StateRepository(ABC):
    """
    Abstract interface for persisting, retrieving, listing, updating,
    and deleting voyage application states across requests.
    """

    @abstractmethod
    def save(self, state: PersistedVoyageState) -> PersistedVoyageState:
        """
        Creates and stores a new PersistedVoyageState record.

        Args:
            state: Complete initial PersistedVoyageState.

        Returns:
            The stored PersistedVoyageState.

        Raises:
            StateConflictError: If a state with the same voyage_id already exists.
            StateValidationError: If state fails validation.
        """
        pass

    @abstractmethod
    def get(self, voyage_id: str) -> Optional[PersistedVoyageState]:
        """
        Retrieves a PersistedVoyageState by voyage_id.

        Args:
            voyage_id: Unique voyage identifier.

        Returns:
            PersistedVoyageState if found, else None.
        """
        pass

    def get_or_raise(self, voyage_id: str) -> PersistedVoyageState:
        """
        Retrieves a PersistedVoyageState or raises StateNotFoundError.

        Args:
            voyage_id: Unique voyage identifier.

        Returns:
            PersistedVoyageState if found.

        Raises:
            StateNotFoundError: If no record exists for voyage_id.
        """
        state = self.get(voyage_id)
        if state is None:
            raise StateNotFoundError(voyage_id)
        return state

    @abstractmethod
    def list_all(self, limit: int = 100, offset: int = 0) -> List[PersistedVoyageState]:
        """
        Lists stored voyage states with pagination.

        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).

        Returns:
            List of PersistedVoyageState items.
        """
        pass

    @abstractmethod
    def update(self, voyage_id: str, update: StateUpdateRequest) -> PersistedVoyageState:
        """
        Applies updates to an existing PersistedVoyageState with optimistic concurrency protection.

        Args:
            voyage_id: Identifier of the voyage to update.
            update: StateUpdateRequest containing updated fields and optional expected_version.

        Returns:
            The updated PersistedVoyageState with incremented state_version and new updated_at_utc.

        Raises:
            StateNotFoundError: If the voyage does not exist.
            StateConflictError: If expected_version is supplied and does not match current state_version.
        """
        pass

    @abstractmethod
    def delete(self, voyage_id: str) -> bool:
        """
        Removes a voyage state record from the repository.

        Args:
            voyage_id: Identifier of the voyage to delete.

        Returns:
            True if record was deleted, False if record did not exist.
        """
        pass
