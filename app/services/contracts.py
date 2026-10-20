"""
app/services/contracts.py — Phase 10C.8 Application Service Layer Contracts
=============================================================================
Defines strongly-typed, Pydantic V2 compliant request and response schemas for
the application service boundary (Operator/Driver and Engineering services).

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Zero recomputation of physics, sizing, economics, or emissions.
  - Truthful missing data semantics (missing fields remain None, never 0.0).
  - Explicit classification of data availability (EXISTS, DERIVABLE, REQUIRES_NEW_INPUT, NOT_CURRENTLY_AVAILABLE).
  - Strict human-in-the-loop safety (human_review_required is preserved on all advisories).
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.voyage.contracts import (
    Route,
    VesselContext,
    VesselEnergyState,
    VesselPosition,
    VoyageContext,
    VoyageStatus,
    VoyageTimeline,
    VoyageWeatherContext,
)
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
    EngineeringDecisionInputs,
)
from app.advisory.contracts import (
    Advisory,
    AdvisoryCategory,
    AdvisoryEvidence,
    AdvisoryPolicy,
    AdvisorySeverity,
    AdvisoryStatus,
)


# =====================================================================
# 1. FIELD AVAILABILITY CLASSIFICATION ENUM
# =====================================================================

class FieldAvailabilityClassification(str, Enum):
    """Classification of field provenance at the service boundary."""
    EXISTS = "EXISTS"
    DERIVABLE = "DERIVABLE FROM EXISTING CONTRACT"
    REQUIRES_NEW_INPUT = "REQUIRES NEW INPUT"
    NOT_CURRENTLY_AVAILABLE = "NOT CURRENTLY AVAILABLE"


# =====================================================================
# 2. ROUTE & NAVIGATION DERIVATION CONTRACT
# =====================================================================

class RouteProgressInfo(BaseModel):
    """
    Application-level route progress and estimated time of arrival (ETA) derivation.
    CRITICAL: Instantaneous-SOG ETA is strictly documented as an application-level
    linear estimate, not a hydrodynamic prediction model.
    """
    route_id: str = Field(..., description="Identifier of the active route")
    total_distance_nm: float = Field(..., ge=0.0, description="Total planned route distance in nautical miles")
    distance_traveled_nm: Optional[float] = Field(default=None, ge=0.0, description="Estimated distance traveled from origin in nautical miles")
    distance_remaining_nm: Optional[float] = Field(default=None, ge=0.0, description="Estimated remaining distance to destination in nautical miles")
    route_progress_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Percentage of route completed (0.0 to 100.0%)")
    eta_utc: Optional[str] = Field(default=None, description="Estimated UTC arrival timestamp based on current SOG")
    eta_derivation_note: Optional[str] = Field(
        default="Application-level linear estimate (distance_remaining / SOG). Not a hydrodynamic voyage predictor.",
        description="Explicit disclaimer clarifying the derivation nature of ETA",
    )

    @field_validator("eta_utc")
    @classmethod
    def validate_eta_timestamp(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)


# =====================================================================
# 3. OPERATOR SERVICE RESPONSE CONTRACTS
# =====================================================================

class OperatorStateMetadata(BaseModel):
    """Execution metadata and overall decision readiness classification."""
    request_id: str = Field(..., min_length=1, description="Unique service request/response identifier")
    generated_at_utc: str = Field(..., description="ISO 8601 UTC timestamp of response generation")
    readiness_state: AdvisoryReadinessState = Field(..., description="Decision readiness classification")
    readiness_reasons: List[str] = Field(default_factory=list, description="Explanatory notes regarding readiness")

    @field_validator("generated_at_utc")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v) or v


class OperatorVesselState(BaseModel):
    """Current vessel telemetry, route, and navigation status."""
    vessel_id: str = Field(..., min_length=1, description="Unique vessel identifier")
    ship_type: str = Field(..., min_length=1, description="Ship classification type")
    engine_power_kw: Optional[float] = Field(default=None, ge=1.0, description="Installed main engine rated power in kW")
    design_speed_knots: Optional[float] = Field(default=None, ge=1.0, description="Design service speed in knots")
    max_speed_knots: Optional[float] = Field(default=None, ge=1.0, description="Maximum operating speed in knots")
    displacement_tonnes: Optional[float] = Field(default=None, ge=1.0, description="Vessel displacement in tonnes")
    propulsion_type: Optional[str] = Field(default=None, description="Propulsion configuration")
    current_position: VesselPosition = Field(..., description="Latest recorded vessel position and kinematics")
    route: Route = Field(..., description="Active route waypoints and geometry")
    route_progress: Optional[RouteProgressInfo] = Field(default=None, description="Derived route progression & ETA")


class OperatorWeatherState(BaseModel):
    """Current environmental conditions, route forecast, and telemetry quality."""
    current: Optional[NormalizedWeatherRecord] = Field(default=None, description="Instantaneous weather observation at vessel position")
    route_profile: Optional[RouteWeatherProfile] = Field(default=None, description="Weather forecast/profile along route waypoints")
    provenance: Optional[WeatherProvenanceType] = Field(default=None, description="Data origin (OBSERVED, HISTORICAL, FORECAST, etc.)")
    quality: Optional[WeatherQualityState] = Field(default=None, description="Data quality classification (VALID, PARTIAL, INVALID, UNAVAILABLE)")
    freshness: Optional[WeatherFreshnessState] = Field(default=None, description="Freshness classification (FRESH, STALE, EXPIRED)")
    freshness_age_seconds: Optional[Union[int, float]] = Field(default=None, ge=0, description="Age of current weather observation in seconds")


class OperatorEnergyState(BaseModel):
    """Instantaneous clean energy, battery storage, and bunker fuel telemetry."""
    battery_soc_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Battery State of Charge percentage")
    battery_soh_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Battery State of Health percentage")
    battery_energy_available_kwh: Optional[float] = Field(default=None, ge=0.0, description="Usable stored electrical energy in kWh")
    fuel_remaining_liters: Optional[float] = Field(default=None, ge=0.0, description="Remaining diesel bunker fuel volume in liters")
    fuel_consumption_rate_lph: Optional[float] = Field(default=None, ge=0.0, description="Current fuel consumption rate in liters/hour")
    solar_power_kw: Optional[float] = Field(default=None, ge=0.0, description="Instantaneous PV array generation in kW")
    solar_energy_today_kwh: Optional[float] = Field(default=None, ge=0.0, description="Cumulative PV generation today in kWh")


class OperatorRegulatoryState(BaseModel):
    """Attained Carbon Intensity Indicator rating and compliance status."""
    attained_cii_rating: Optional[str] = Field(default=None, description="Attained IMO CII rating grade ('A' through 'E')")
    co2_emissions_kg: Optional[float] = Field(default=None, ge=0.0, description="Total voyage/period CO2 emissions in kg")
    compliance_state: Optional[str] = Field(default=None, description="High-level regulatory standing ('COMPLIANT', 'NON_COMPLIANT', None)")


class OperatorAdvisorySummary(BaseModel):
    """Collection of active deterministic decision-support advisories with severity breakdown."""
    total_count: int = Field(default=0, ge=0, description="Total active advisories generated")
    critical_count: int = Field(default=0, ge=0, description="Count of CRITICAL severity advisories")
    warning_count: int = Field(default=0, ge=0, description="Count of WARNING severity advisories")
    notice_count: int = Field(default=0, ge=0, description="Count of NOTICE severity advisories")
    info_count: int = Field(default=0, ge=0, description="Count of INFO severity advisories")
    items: List[Advisory] = Field(default_factory=list, description="Ordered, deduplicated actionable advisories")


class OperatorStateResponse(BaseModel):
    """
    Standardized, strongly-typed response returned by OperatorService.
    Aggregates vessel navigation, weather telemetry, energy state, regulatory status,
    and deterministic advisories for dashboard presentation.
    """
    metadata: OperatorStateMetadata = Field(..., description="Response metadata and readiness")
    vessel: OperatorVesselState = Field(..., description="Vessel telemetry and route state")
    weather: OperatorWeatherState = Field(..., description="Environmental context and quality")
    energy: OperatorEnergyState = Field(..., description="Energy storage and fuel reserves")
    regulatory: OperatorRegulatoryState = Field(..., description="IMO CII compliance state")
    advisories: OperatorAdvisorySummary = Field(..., description="Active operational advisories")

    def has_critical_advisories(self) -> bool:
        """Returns True if any CRITICAL severity advisories are present."""
        return self.advisories.critical_count > 0

    def get_advisories_by_category(self, category: AdvisoryCategory) -> List[Advisory]:
        """Returns active advisories in the specified domain category."""
        return [a for a in self.advisories.items if a.category == category]

    def get_advisories_by_severity(self, severity: AdvisorySeverity) -> List[Advisory]:
        """Returns active advisories matching the specified severity."""
        return [a for a in self.advisories.items if a.severity == severity]

    def to_dict(self) -> Dict[str, Any]:
        """Returns a JSON-serializable dictionary representation suitable for UI feeds."""
        return self.model_dump(mode="json")
