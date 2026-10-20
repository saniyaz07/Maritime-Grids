"""
phase9_cii_contracts.py — Pydantic V2 Contracts for Phase 9 Candidate 4
========================================================================
Multi-Year Regulatory Compliance Trajectory & IMO CII Aging Simulator

Defines:
  - SUPPORTED_CII_SHIP_TYPES: Canonical project vessel archetypes.
  - RegulatoryProvenanceConstants: STATUTORY, PROJECTED, UNSPECIFIED, EXEMPT, NOT_ASSESSED.
  - CIIRatingConstants: A, B, C, D, E, EXEMPT, NOT_ASSESSED, UNSPECIFIED.
  - RegulatoryScenarioParameters: Caller-supplied post-2026 scenario assumptions.
  - PhysicalDegradationParameters: Optional caller-supplied annual degradation rates.
  - TrajectorySimulationRequest: Multi-year simulation input contract.
  - AnnualTrajectoryRecord: Audit record for an individual calendar evaluation year.
  - TrajectorySimulationResult: Unified multi-year trajectory response envelope.

Architectural boundaries:
  - Strictly adheres to zero-assumption governance.
  - Reuses frozen Phase 6 contracts and statutory tables.
  - Post-2026 reduction factors have NO silent default rate.
  - Physical degradation parameters default to 0.0 (static snapshot semantics).
"""

from typing import Dict, List, Optional
import math
from pydantic import BaseModel, Field, field_validator, model_validator

from phase8_contracts import OptimizationCandidate

# ==============================================================================
# Constants
# ==============================================================================

SUPPORTED_CII_SHIP_TYPES: List[str] = [
    "Tanker Ship",
    "Oil Service Boat",
    "Fishing Trawler",
    "Surfer Boat",
]

# Regulatory basis classifications
REGULATORY_BASIS_STATUTORY = "STATUTORY"
REGULATORY_BASIS_PROJECTED = "PROJECTED"
REGULATORY_BASIS_UNSPECIFIED = "UNSPECIFIED"
REGULATORY_BASIS_EXEMPT = "EXEMPT"
REGULATORY_BASIS_NOT_ASSESSED = "NOT_ASSESSED"

# CII rating classifications
CII_RATING_A = "A"
CII_RATING_B = "B"
CII_RATING_C = "C"
CII_RATING_D = "D"
CII_RATING_E = "E"
CII_RATING_EXEMPT = "EXEMPT"
CII_RATING_NOT_ASSESSED = "NOT_ASSESSED"
CII_RATING_UNSPECIFIED = "UNSPECIFIED"

# Diagnostic status constants
DIAG_TRAJECTORY_COMPLETED = "TRAJECTORY_COMPLETED"
DIAG_TRAJECTORY_UNSPECIFIED_POST_2026 = "TRAJECTORY_COMPLETED_WITH_UNSPECIFIED_POST_2026"
DIAG_TRAJECTORY_EXEMPT = "TRAJECTORY_COMPLETED_STATUTORILY_EXEMPT"
DIAG_TRAJECTORY_NOT_ASSESSED = "TRAJECTORY_COMPLETED_NOT_ASSESSED"


# ==============================================================================
# 1. Parameter Sub-Contracts
# ==============================================================================

class RegulatoryScenarioParameters(BaseModel):
    """
    Caller-supplied post-2026 regulatory scenario assumptions.
    All post-2026 schedules are explicit scenario assumptions and are NEVER
    treated as adopted MARPOL statutory requirements.
    """
    post_2026_reduction_factors: Optional[Dict[int, float]] = Field(
        default=None,
        description=(
            "Explicit mapping of year -> reduction factor Z% (e.g. {2027: 13.0, 2028: 15.0}). "
            "If None and no increment is supplied, post-2026 years are marked UNSPECIFIED."
        ),
    )
    annual_z_increment_pct: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=10.0,
        description=(
            "Optional linear annual escalation rate applied beyond 2026 (e.g. 2.0% per year). "
            "Applied only if post_2026_reduction_factors is None."
        ),
    )

    @field_validator("post_2026_reduction_factors")
    @classmethod
    def validate_reduction_factors(cls, v: Optional[Dict[int, float]]) -> Optional[Dict[int, float]]:
        if v is not None:
            for yr, z in v.items():
                if yr < 2027:
                    raise ValueError(f"post_2026_reduction_factors keys must be >= 2027, got year {yr}")
                if z < 0.0 or z > 100.0 or not math.isfinite(z):
                    raise ValueError(f"Reduction factor Z% must be between 0.0 and 100.0, got {z} for year {yr}")
        return v


class PhysicalDegradationParameters(BaseModel):
    """
    Optional caller-supplied annual physical degradation rates.
    Defaults strictly to 0.0 (static snapshot semantics).
    """
    solar_derate_pct_per_year: float = Field(
        default=0.0,
        ge=0.0,
        le=5.0,
        description="Annual degradation of clean solar yield (%/yr). Default 0.0.",
    )
    battery_capacity_fade_pct_per_year: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Annual capacity fade of battery storage (%/yr). Default 0.0.",
    )
    fuel_consumption_growth_pct_per_year: float = Field(
        default=0.0,
        ge=0.0,
        le=5.0,
        description="Annual baseline fuel consumption growth due to hull/engine aging (%/yr). Default 0.0.",
    )


# ==============================================================================
# 2. Request Contract
# ==============================================================================

class TrajectorySimulationRequest(BaseModel):
    """
    Input contract for multi-year regulatory trajectory simulation.
    """
    vessel_id: str = Field(..., min_length=1, description="Vessel identifier.")
    ship_type: str = Field(..., description="Canonical project vessel archetype.")
    dwt_tonnes: float = Field(..., gt=0.0, description="Vessel deadweight carrying capacity in metric tonnes.")
    route_id: str = Field(..., min_length=1, description="Shipping corridor identifier.")
    voyage_distance_nm: float = Field(..., gt=0.0, description="Single-voyage distance in nautical miles.")
    annual_voyages: int = Field(default=52, ge=1, description="Annual operating voyage count multiplier.")
    baseline_single_voyage_fuel_L: float = Field(..., gt=0.0, description="Single-voyage baseline fuel consumption in Litres.")
    baseline_single_voyage_co2_kg: float = Field(..., gt=0.0, description="Single-voyage baseline CO2 emissions in kg.")

    candidate: Optional[OptimizationCandidate] = Field(
        default=None,
        description="Optional pre-evaluated Phase 8 retrofit candidate sizing point."
    )

    start_year: int = Field(default=2023, ge=2020, le=2050, description="Start calendar year of evaluation.")
    end_year: int = Field(default=2030, ge=2020, le=2050, description="End calendar year of evaluation.")

    regulatory_scenario: RegulatoryScenarioParameters = Field(
        default_factory=RegulatoryScenarioParameters,
        description="Caller-supplied post-2026 regulatory assumptions (explicitly labeled as scenario projections)."
    )
    degradation_parameters: PhysicalDegradationParameters = Field(
        default_factory=PhysicalDegradationParameters,
        description="Caller-supplied physical aging parameters (default 0.0)."
    )

    @field_validator("ship_type")
    @classmethod
    def validate_ship_type(cls, v: str) -> str:
        if v not in SUPPORTED_CII_SHIP_TYPES:
            raise ValueError(f"Unsupported ship_type '{v}'. Supported: {SUPPORTED_CII_SHIP_TYPES}")
        return v

    @model_validator(mode="after")
    def validate_year_bounds(self) -> "TrajectorySimulationRequest":
        if self.end_year < self.start_year:
            raise ValueError(f"end_year ({self.end_year}) cannot be earlier than start_year ({self.start_year}).")
        return self


# ==============================================================================
# 3. Output Contracts
# ==============================================================================

class AnnualTrajectoryRecord(BaseModel):
    """
    Year-by-year regulatory and operational audit record.
    """
    year: int = Field(..., description="Calendar evaluation year.")
    regulatory_basis: str = Field(
        ...,
        description="Regulatory basis: 'STATUTORY', 'PROJECTED', 'UNSPECIFIED', 'EXEMPT', or 'NOT_ASSESSED'."
    )
    reduction_factor_z_pct: Optional[float] = Field(
        default=None,
        description="Reduction factor Z% applied (None if UNSPECIFIED, EXEMPT, or NOT_ASSESSED)."
    )

    # Activity & Transport Work
    annual_distance_nm: float = Field(..., ge=0.0, description="Total annual nautical miles sailed.")
    annual_transport_work_dwt_nm: float = Field(..., ge=0.0, description="Annual transport work in DWT-nm.")

    # Annual Emissions & Fuel
    baseline_annual_fuel_L: float = Field(..., ge=0.0, description="Baseline annual fuel consumed in Litres.")
    baseline_annual_co2_kg: float = Field(..., ge=0.0, description="Baseline annual CO2 emitted in kg.")
    assisted_annual_fuel_L: float = Field(..., ge=0.0, description="Net assisted annual fuel consumed in Litres.")
    assisted_annual_co2_kg: float = Field(..., ge=0.0, description="Net assisted annual CO2 emitted in kg.")
    annual_fuel_displaced_L: float = Field(..., ge=0.0, description="Annual fuel displaced by clean assistance in Litres.")
    annual_co2_displaced_kg: float = Field(..., ge=0.0, description="Annual CO2 displaced by clean assistance in kg.")

    # CII Metrics
    baseline_attained_cii: float = Field(..., ge=0.0, description="Baseline attained operational CII in g CO2 / (DWT * nm).")
    assisted_attained_cii: float = Field(..., ge=0.0, description="Assisted attained operational CII in g CO2 / (DWT * nm).")
    cii_reference: Optional[float] = Field(default=None, description="IMO MEPC.353(78) reference line CII.")
    required_cii: Optional[float] = Field(default=None, description="Required target CII for the evaluation year.")
    rating_boundaries: Optional[Dict[str, float]] = Field(default=None, description="MEPC.354(78) rating band boundaries.")

    # Ratings
    baseline_cii_rating: str = Field(..., description="'A', 'B', 'C', 'D', 'E', 'EXEMPT', 'NOT_ASSESSED', or 'UNSPECIFIED'.")
    assisted_cii_rating: str = Field(..., description="'A', 'B', 'C', 'D', 'E', 'EXEMPT', 'NOT_ASSESSED', or 'UNSPECIFIED'.")

    # Compliance & Corrective Action
    baseline_is_compliant: Optional[bool] = Field(
        default=None,
        description="True if baseline rating in ('A', 'B', 'C'); False if in ('D', 'E'); None if unrated/exempt."
    )
    assisted_is_compliant: Optional[bool] = Field(
        default=None,
        description="True if assisted rating in ('A', 'B', 'C'); False if in ('D', 'E'); None if unrated/exempt."
    )
    baseline_corrective_action_required: bool = Field(
        default=False,
        description="True if baseline triggers MARPOL Reg 28 corrective action (single E or 3 consecutive Ds)."
    )
    assisted_corrective_action_required: bool = Field(
        default=False,
        description="True if assisted triggers MARPOL Reg 28 corrective action (single E or 3 consecutive Ds)."
    )


class TrajectorySimulationResult(BaseModel):
    """
    Unified multi-year trajectory simulation response envelope.
    """
    request: TrajectorySimulationRequest = Field(..., description="Applied simulation request.")
    trajectory: List[AnnualTrajectoryRecord] = Field(..., description="Annual trajectory audit records.")
    years_evaluated: int = Field(..., ge=1, description="Total number of evaluated calendar years.")

    # Cumulative totals
    baseline_cumulative_fuel_L: float = Field(..., ge=0.0, description="Cumulative baseline fuel over the evaluation horizon.")
    baseline_cumulative_co2_kg: float = Field(..., ge=0.0, description="Cumulative baseline CO2 over the evaluation horizon.")
    assisted_cumulative_fuel_L: float = Field(..., ge=0.0, description="Cumulative assisted fuel over the evaluation horizon.")
    assisted_cumulative_co2_kg: float = Field(..., ge=0.0, description="Cumulative assisted CO2 over the evaluation horizon.")
    total_fuel_displaced_L: float = Field(..., ge=0.0, description="Cumulative clean fuel displaced over horizon.")
    total_co2_displaced_kg: float = Field(..., ge=0.0, description="Cumulative clean CO2 displaced over horizon.")

    # Compliance extension metrics
    compliance_extension_years: Optional[int] = Field(
        default=None,
        description=(
            "Net additional evaluated years assisted trajectory remains compliant (Rating >= C) relative to baseline. "
            "Strictly None for STATUTORILY_EXEMPT or NOT_ASSESSED vessel types."
        )
    )
    first_non_compliant_year_baseline: Optional[int] = Field(
        default=None,
        description="First calendar year baseline drops to Rating D or E (None if never non-compliant or unrated)."
    )
    first_non_compliant_year_assisted: Optional[int] = Field(
        default=None,
        description="First calendar year assisted drops to Rating D or E (None if never non-compliant or unrated)."
    )

    diagnostics: str = Field(..., description="Machine-readable execution status.")
    warnings: List[str] = Field(default_factory=list, description="Audit notices and regulatory disclaimers.")
