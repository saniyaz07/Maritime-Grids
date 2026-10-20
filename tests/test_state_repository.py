"""
tests/test_state_repository.py — Phase 10C.10 Repository Implementations Test Suite
====================================================================================
Tests InMemoryStateRepository and SQLiteStateRepository across CRUD operations,
optimistic concurrency control, version increments, error handling, and data isolation.
"""

import os
import tempfile
import pytest

from app.state.contracts import (
    PersistedVoyageState,
    StateConflictError,
    StateNotFoundError,
    StateUpdateRequest,
)
from app.state.repository import StateRepository
from app.state.memory_repository import InMemoryStateRepository
from app.state.sqlite_repository import SQLiteStateRepository
from app.voyage.contracts import (
    Route,
    RouteWaypoint,
    VesselPosition,
    VoyageStatus,
)


def create_sample_state(voyage_id: str = "VOY_001", vessel_id: str = "VESSEL_01") -> PersistedVoyageState:
    pos = VesselPosition(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        speed_over_ground_knots=12.0,
    )
    route = Route(
        route_id="ESCRAVOS_LAGOS",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1", latitude=5.58, longitude=5.18),
            RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.50),
        ],
        total_distance_nm=130.0,
    )
    return PersistedVoyageState(
        voyage_id=voyage_id,
        vessel_id=vessel_id,
        ship_type="Oil Service Boat",
        route_id="ESCRAVOS_LAGOS",
        status=VoyageStatus.PLANNED,
        state_version=1,
        created_at_utc="2026-06-15T12:00:00Z",
        updated_at_utc="2026-06-15T12:00:00Z",
        current_position=pos,
        route=route,
    )


@pytest.fixture(params=["in_memory", "sqlite_memory", "sqlite_file"])
def repository(request):
    """Parametrized fixture providing both in-memory and SQLite repository backends."""
    if request.param == "in_memory":
        yield InMemoryStateRepository()
    elif request.param == "sqlite_memory":
        repo = SQLiteStateRepository(db_path=":memory:")
        yield repo
        repo.close()
    elif request.param == "sqlite_file":
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo = SQLiteStateRepository(db_path=path)
        yield repo
        repo.close()
        if os.path.exists(path):
            os.remove(path)


def test_01_save_and_get_state(repository: StateRepository):
    """Verify state can be stored and retrieved by voyage_id."""
    state = create_sample_state("VOY_101")
    saved = repository.save(state)
    assert saved.voyage_id == "VOY_101"

    retrieved = repository.get("VOY_101")
    assert retrieved is not None
    assert retrieved.voyage_id == "VOY_101"
    assert retrieved.vessel_id == "VESSEL_01"
    assert retrieved.status == VoyageStatus.PLANNED
    assert retrieved.state_version == 1


def test_02_get_nonexistent_state_returns_none(repository: StateRepository):
    """Verify get() on unknown voyage_id returns None."""
    assert repository.get("NONEXISTENT_VOYAGE") is None


def test_03_get_or_raise_raises_not_found(repository: StateRepository):
    """Verify get_or_raise() on unknown voyage_id raises StateNotFoundError."""
    with pytest.raises(StateNotFoundError) as exc_info:
        repository.get_or_raise("MISSING_VOY")
    assert exc_info.value.voyage_id == "MISSING_VOY"


def test_04_save_duplicate_raises_conflict(repository: StateRepository):
    """Verify attempting to save duplicate voyage_id raises StateConflictError."""
    state = create_sample_state("VOY_DUP_01")
    repository.save(state)

    with pytest.raises(StateConflictError):
        repository.save(state)


def test_05_list_all_with_pagination(repository: StateRepository):
    """Verify list_all returns sorted list and respects limit and offset."""
    for i in range(5):
        st = create_sample_state(f"VOY_PAGE_{i:02d}")
        # Offset creation timestamps to ensure deterministic sort order
        st.created_at_utc = f"2026-06-15T12:{i:02d}:00Z"
        repository.save(st)

    all_items = repository.list_all(limit=10, offset=0)
    assert len(all_items) == 5

    paged_items = repository.list_all(limit=2, offset=1)
    assert len(paged_items) == 2
    assert paged_items[0].voyage_id == "VOY_PAGE_01"
    assert paged_items[1].voyage_id == "VOY_PAGE_02"


def test_06_update_state_increments_version(repository: StateRepository):
    """Verify updating a state increments state_version and updates updated_at_utc."""
    state = create_sample_state("VOY_UPD_01")
    repository.save(state)

    update = StateUpdateRequest(
        status=VoyageStatus.ACTIVE,
        metadata={"operator_note": "Underway"},
    )
    updated = repository.update("VOY_UPD_01", update)
    assert updated.status == VoyageStatus.ACTIVE
    assert updated.state_version == 2
    assert updated.metadata == {"operator_note": "Underway"}

    # Fetch from store and verify persisted version
    fetched = repository.get("VOY_UPD_01")
    assert fetched.state_version == 2
    assert fetched.status == VoyageStatus.ACTIVE


def test_07_update_with_matching_expected_version_succeeds(repository: StateRepository):
    """Verify update succeeds when expected_version matches current state_version."""
    state = create_sample_state("VOY_CONC_01")
    repository.save(state)  # version 1

    update = StateUpdateRequest(
        expected_version=1,
        status=VoyageStatus.PAUSED,
    )
    updated = repository.update("VOY_CONC_01", update)
    assert updated.state_version == 2
    assert updated.status == VoyageStatus.PAUSED


def test_08_update_with_mismatched_expected_version_raises_conflict(repository: StateRepository):
    """Verify update raises StateConflictError when expected_version is stale."""
    state = create_sample_state("VOY_CONC_02")
    repository.save(state)  # version 1

    update = StateUpdateRequest(
        expected_version=99,  # Mismatched version
        status=VoyageStatus.COMPLETED,
    )
    with pytest.raises(StateConflictError):
        repository.update("VOY_CONC_02", update)


def test_09_update_nonexistent_raises_not_found(repository: StateRepository):
    """Verify updating nonexistent voyage raises StateNotFoundError."""
    update = StateUpdateRequest(status=VoyageStatus.ACTIVE)
    with pytest.raises(StateNotFoundError):
        repository.update("NONEXISTENT_VOY", update)


def test_10_delete_state(repository: StateRepository):
    """Verify deleting a state removes it and returns True, subsequent delete returns False."""
    state = create_sample_state("VOY_DEL_01")
    repository.save(state)

    assert repository.get("VOY_DEL_01") is not None
    assert repository.delete("VOY_DEL_01") is True
    assert repository.get("VOY_DEL_01") is None
    assert repository.delete("VOY_DEL_01") is False


def test_11_sqlite_persistence_across_instances():
    """Verify SQLite persistence preserves state across different repository connections."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    try:
        # Instance 1: Save state
        repo1 = SQLiteStateRepository(db_path=path)
        st = create_sample_state("VOY_PERSIST_01")
        repo1.save(st)
        repo1.close()

        # Instance 2: Open same DB and retrieve state
        repo2 = SQLiteStateRepository(db_path=path)
        fetched = repo2.get("VOY_PERSIST_01")
        assert fetched is not None
        assert fetched.voyage_id == "VOY_PERSIST_01"
        assert fetched.vessel_id == "VESSEL_01"
        repo2.close()
    finally:
        if os.path.exists(path):
            os.remove(path)
