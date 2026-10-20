"""
tests/test_state_contracts.py — Phase 10C.10 Persistent State Contracts Verification
====================================================================================
Validates PersistedVoyageState, StateUpdateRequest, versioning semantics,
truthful missing telemetry preservation, and serialization invariants.
"""

import pytest
from pydantic import ValidationError

from app.advisory.contracts import (
    Advisory,
    AdvisoryCategory,
    AdvisorySeverity,
    AdvisoryStatus,
)
from app.decision.contracts import AdvisoryReadinessState
from app.services.contracts import (
    OperatorAdvisorySummary,
    OperatorEnergyState,
    OperatorRegulatoryState,
    OperatorStateMetadata,
    OperatorStateResponse,
    OperatorVesselState,
    OperatorWeatherState,
    RouteProgressInfo,
)
from app.state.contracts import (
    PersistedVoyageState,
    StateConflictError,
    StateNotFoundError,
    StateUpdateRequest,
    StateValidationError,
)
from app.voyage.contracts import (
    Route,
    RouteWaypoint,
    VesselContext,
    VesselEnergyState,
    VesselPosition,
    VoyageStatus,
)
from app.weather.contracts import (
    NormalizedWeatherRecord,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)


def create_sample_state() -> PersistedVoyageState:
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
        voyage_id="VOY_2026_001",
        vessel_id="VESSEL_01",
        ship_type="Oil Service Boat",
        route_id="ESCRAVOS_LAGOS",
        status=VoyageStatus.ACTIVE,
        state_version=1,
        created_at_utc="2026-06-15T12:00:00Z",
        updated_at_utc="2026-06-15T12:00:00Z",
        current_position=pos,
        route=route,
    )


def test_01_valid_persisted_state_instantiation():
    """Verify valid PersistedVoyageState creates successfully with all fields."""
    state = create_sample_state()
    assert state.voyage_id == "VOY_2026_001"
    assert state.vessel_id == "VESSEL_01"
    assert state.status == VoyageStatus.ACTIVE
    assert state.state_version == 1


def test_02_invalid_state_rejection_missing_required_fields():
    """Verify missing required fields raise ValidationError."""
    with pytest.raises(ValidationError):
        PersistedVoyageState(
            voyage_id="VOY_001",
            # missing vessel_id, ship_type, route_id, created_at_utc, updated_at_utc
        )


def test_03_invalid_timestamp_format_rejection():
    """Verify malformed non-ISO timestamps are rejected."""
    with pytest.raises(ValidationError):
        PersistedVoyageState(
            voyage_id="VOY_001",
            vessel_id="VESSEL_01",
            ship_type="Crew Boat",
            route_id="R1",
            created_at_utc="invalid-date-format",
            updated_at_utc="2026-06-15T12:00:00Z",
        )


def test_04_state_version_must_be_positive():
    """Verify state_version < 1 is rejected by schema validator."""
    with pytest.raises(ValidationError):
        PersistedVoyageState(
            voyage_id="VOY_001",
            vessel_id="VESSEL_01",
            ship_type="Crew Boat",
            route_id="R1",
            state_version=0,
            created_at_utc="2026-06-15T12:00:00Z",
            updated_at_utc="2026-06-15T12:00:00Z",
        )


def test_05_truthful_missing_telemetry_preservation():
    """Verify optional unmeasured fields default to None and are never coerced to 0.0."""
    state = PersistedVoyageState(
        voyage_id="VOY_001",
        vessel_id="VESSEL_01",
        ship_type="Crew Boat",
        route_id="R1",
        created_at_utc="2026-06-15T12:00:00Z",
        updated_at_utc="2026-06-15T12:00:00Z",
    )
    assert state.current_position is None
    assert state.weather is None
    assert state.energy is None
    assert state.regulatory is None
    assert state.advisories is None


def test_06_from_operator_state_factory():
    """Verify PersistedVoyageState.from_operator_state constructs complete snapshot."""
    pos = VesselPosition(latitude=5.80, longitude=4.50, timestamp_utc="2026-06-15T12:00:00Z")
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
    op_resp = OperatorStateResponse(
        metadata=OperatorStateMetadata(
            request_id="REQ_001",
            generated_at_utc="2026-06-15T12:00:00Z",
            readiness_state=AdvisoryReadinessState.READY,
        ),
        vessel=OperatorVesselState(
            vessel_id="VESSEL_01",
            ship_type="Crew Boat",
            current_position=pos,
            route=route,
        ),
        weather=OperatorWeatherState(
            provenance=WeatherProvenanceType.OBSERVED,
            quality=WeatherQualityState.VALID,
            freshness=WeatherFreshnessState.FRESH,
        ),
        energy=OperatorEnergyState(battery_soc_pct=88.5, fuel_remaining_liters=5200.0),
        regulatory=OperatorRegulatoryState(compliance_state="COMPLIANT"),
        advisories=OperatorAdvisorySummary(
            total_count=1,
            items=[
                Advisory(
                    advisory_id="ADV_01",
                    rule_id="RULE_01",
                    category=AdvisoryCategory.WEATHER,
                    severity=AdvisorySeverity.NOTICE,
                    title="Advisory",
                    message="Weather notice",
                    created_at_utc="2026-06-15T12:00:00Z",
                    human_review_required=True,
                )
            ],
        ),
    )
    persisted = PersistedVoyageState.from_operator_state(
        response=op_resp,
        voyage_id="VOY_OP_001",
        route_id="ESCRAVOS_LAGOS",
        status=VoyageStatus.ACTIVE,
    )
    assert persisted.voyage_id == "VOY_OP_001"
    assert persisted.vessel_id == "VESSEL_01"
    assert persisted.energy.battery_soc_pct == 88.5
    assert persisted.weather.provenance == WeatherProvenanceType.OBSERVED
    assert persisted.advisories.items[0].human_review_required is True


def test_07_state_update_request_validation():
    """Verify StateUpdateRequest validates fields properly."""
    up = StateUpdateRequest(
        expected_version=2,
        status=VoyageStatus.COMPLETED,
        metadata={"note": "Voyage finished safely"},
    )
    assert up.expected_version == 2
    assert up.status == VoyageStatus.COMPLETED
    assert up.metadata == {"note": "Voyage finished safely"}


def test_08_json_serialization_roundtrip():
    """Verify PersistedVoyageState serializes and deserializes from JSON losslessly."""
    original = create_sample_state()
    json_str = original.model_dump_json()
    reconstructed = PersistedVoyageState.model_validate_json(json_str)
    assert reconstructed.voyage_id == original.voyage_id
    assert reconstructed.state_version == original.state_version
    assert reconstructed.created_at_utc == original.created_at_utc
