"""
app/state/contracts.py — Phase 10C.10 Persistent Application & Voyage State Contracts
=====================================================================================
Defines strongly-typed Pydantic contracts for persisted voyage state, state updates,
versioning/optimistic concurrency control, and repository domain exceptions.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Strict preservation of data availability (None != 0.0).
  - Explicit temporal semantics (created_at_utc, updated_at_utc, observed_at).
  - Deterministic state versioning (state_version integer counter).
  - Advisory safety preserved (human_review_required = True).
  - Pure state representation: zero business rules, zero physics, zero autonomous control.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.contracts import (
    OperatorAdvisorySummary,
    OperatorEnergyState,
    OperatorRegulatoryState,
    OperatorStateResponse,
    OperatorVesselState,
    OperatorWeatherState,
    RouteProgressInfo,
)
from app.voyage.contracts import (
    Route,
    VesselPosition,
    VoyageStatus,
)
from app.weather.contracts import NormalizedWeatherRecord


# =====================================================================
# 1. REPOSITORY EXCEPTIONS
# =====================================================================

class StateRepositoryError(Exception):
    """Base exception for all state repository errors."""
    pass


class StateNotFoundError(StateRepositoryError):
    """Raised when the requested voyage state does not exist in the repository."""
    def __init__(self, voyage_id: str) -> None:
        super().__init__(f"Voyage state not found for voyage_id '{voyage_id}'")
        self.voyage_id = voyage_id


class StateConflictError(StateRepositoryError):
    """Raised when an optimistic concurrency conflict or duplicate record is detected."""
    def __init__(self, message: str, voyage_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.voyage_id = voyage_id


class StateValidationError(StateRepositoryError):
    """Raised when persisted state data fails validation or invariant checks."""
    pass


# =====================================================================
# 2. PERSISTED VOYAGE STATE CONTRACT
# =====================================================================

class PersistedVoyageState(BaseModel):
    """
    Standardized contract for persisted application and voyage state.
    Provides snapshot storage of vessel telemetry, navigation, energy,
    weather, regulatory standing, and active advisories across requests.
    """
    voyage_id: str = Field(..., min_length=1, description="Unique voyage identifier (e.g. 'VOY_2026_001')")
    vessel_id: str = Field(..., min_length=1, description="Unique vessel registration/ID")
    ship_type: str = Field(..., min_length=1, description="Ship classification type")
    route_id: str = Field(..., min_length=1, description="Assigned route identifier")
    status: VoyageStatus = Field(default=VoyageStatus.PLANNED, description="Operational lifecycle status")
    state_version: int = Field(default=1, ge=1, description="Monotonically increasing state revision counter")
    created_at_utc: str = Field(..., description="ISO 8601 UTC timestamp of initial state creation")
    updated_at_utc: str = Field(..., description="ISO 8601 UTC timestamp of most recent state revision")
    current_position: Optional[VesselPosition] = Field(default=None, description="Latest recorded vessel position")
    route: Optional[Route] = Field(default=None, description="Active route waypoints and geometry")
    route_progress: Optional[RouteProgressInfo] = Field(default=None, description="Derived route progression & linear ETA")
    weather: Optional[OperatorWeatherState] = Field(default=None, description="Persisted environmental observations & forecast")
    energy: Optional[OperatorEnergyState] = Field(default=None, description="Persisted battery, fuel, and solar telemetry")
    regulatory: Optional[OperatorRegulatoryState] = Field(default=None, description="Attained IMO CII standing & emissions")
    advisories: Optional[OperatorAdvisorySummary] = Field(default=None, description="Active deterministic decision-support advisories")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional application or UI metadata tags")

    @field_validator("created_at_utc", "updated_at_utc")
    @classmethod
    def validate_utc_timestamps(cls, v: str) -> str:
        norm = NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)
        if norm is None:
            raise ValueError(f"Invalid ISO 8601 UTC timestamp: {v}")
        return norm

    @classmethod
    def from_operator_state(
        cls,
        response: OperatorStateResponse,
        voyage_id: str,
        route_id: Optional[str] = None,
        state_version: int = 1,
        status: VoyageStatus = VoyageStatus.ACTIVE,
        created_at_utc: Optional[str] = None,
        updated_at_utc: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "PersistedVoyageState":
        """
        Factory to construct a PersistedVoyageState from an OperatorStateResponse.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        r_id = route_id or (response.vessel.route.route_id if response.vessel.route else "UNKNOWN_ROUTE")

        return cls(
            voyage_id=voyage_id,
            vessel_id=response.vessel.vessel_id,
            ship_type=response.vessel.ship_type,
            route_id=r_id,
            status=status,
            state_version=state_version,
            created_at_utc=created_at_utc or now_ts,
            updated_at_utc=updated_at_utc or now_ts,
            current_position=response.vessel.current_position,
            route=response.vessel.route,
            route_progress=response.vessel.route_progress,
            weather=response.weather,
            energy=response.energy,
            regulatory=response.regulatory,
            advisories=response.advisories,
            metadata=metadata,
        )


# =====================================================================
# 3. STATE UPDATE REQUEST CONTRACT
# =====================================================================

class StateUpdateRequest(BaseModel):
    """
    Structured request payload for modifying existing persisted voyage state.
    Supports optimistic concurrency protection via expected_version.
    """
    expected_version: Optional[int] = Field(default=None, ge=1, description="Expected current version for concurrency guard")
    status: Optional[VoyageStatus] = Field(default=None, description="New operational voyage status")
    current_position: Optional[VesselPosition] = Field(default=None, description="Updated vessel position telemetry")
    route: Optional[Route] = Field(default=None, description="Updated planned route")
    route_progress: Optional[RouteProgressInfo] = Field(default=None, description="Updated route progression & ETA")
    weather: Optional[OperatorWeatherState] = Field(default=None, description="Updated environmental telemetry")
    energy: Optional[OperatorEnergyState] = Field(default=None, description="Updated battery/fuel reserves")
    regulatory: Optional[OperatorRegulatoryState] = Field(default=None, description="Updated regulatory metrics")
    advisories: Optional[OperatorAdvisorySummary] = Field(default=None, description="Updated active advisories")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Updated application metadata")
