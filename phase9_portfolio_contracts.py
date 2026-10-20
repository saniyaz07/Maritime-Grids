"""
phase9_portfolio_contracts.py — Pydantic V2 Contracts for Phase 9 Candidate 3
==============================================================================
Fleet Portfolio Decarbonization Capital Allocation Engine

Defines:
  - SUPPORTED_PORTFOLIO_SHIP_TYPES: Canonical vessel archetypes.
  - PortfolioItem: Wrapper binding vessel identity to a pre-evaluated Phase 8
    OptimizationCandidate.  The frozen OptimizationCandidate does not itself carry
    vessel identity; this wrapper preserves the relationship
    (vessel_id + ship_type + route_id + annual_voyages) ↔ candidate.
  - PortfolioOptimizationParameters: Portfolio-level constraints and settings.
    Primary objective is fixed to MAX_ANNUAL_CO2_DISPLACEMENT.
  - PortfolioAllocationResult: Complete allocation output with selected items,
    aggregate metrics, and machine-readable diagnostic.

Architectural constraints:
  - Zero modification to frozen upstream contracts (Phase 7, Phase 8).
  - Zero reimplementation of NPV, IRR, LCOE, cash flows, displacement, or
    physical feasibility equations.
  - Portfolio objective is fixed to maximize annual CO₂ displacement.
  - Only pre-evaluated Phase 8 OptimizationCandidate objects are consumed.
  - No dependency on Phase 9 Candidate 1 (Sensitivity) or
    Candidate 2 (Speed Co-Optimizer).
"""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from phase8_contracts import OptimizationCandidate

# ==============================================================================
# Constants
# ==============================================================================

# The four canonical vessel archetypes supported as representative fleet vessels.
# Each archetype represents ONE canonical vessel in the portfolio.  The system
# does not model operator fleet sizes or duplicate instances.
SUPPORTED_PORTFOLIO_SHIP_TYPES: List[str] = [
    "Tanker Ship",
    "Oil Service Boat",
    "Fishing Trawler",
    "Surfer Boat",
]

# Primary portfolio objective — FIXED for Candidate 3 v1.
PORTFOLIO_OBJECTIVE_MAX_CO2 = "MAX_ANNUAL_CO2_DISPLACEMENT"

# Diagnostic status constants
DIAG_OPTIMAL_ALLOCATION = "OPTIMAL_ALLOCATION"
DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS = "NO_ALLOCATION_WITHIN_CONSTRAINTS"
DIAG_ZERO_RETROFIT_ALLOCATION = "ZERO_RETROFIT_ALLOCATION"
DIAG_PARTIAL_ALLOCATION = "PARTIAL_ALLOCATION"


# ==============================================================================
# 1. Portfolio Item Contract
# ==============================================================================
class PortfolioItem(BaseModel):
    """
    Wrapper binding a pre-evaluated Phase 8 OptimizationCandidate to its
    vessel identity context.

    The frozen Phase 8 OptimizationCandidate does not carry vessel identity
    (ship_type or route_id).  PortfolioItem preserves the relationship between
    a specific (Apv, Ebatt) sizing candidate and the vessel+route it was
    evaluated for.

    The underlying candidate MUST have already been evaluated externally via
    phase8_optimizer.evaluate_single_sizing_candidate before being wrapped here.
    Candidate 3 does NOT call evaluate_single_sizing_candidate internally.
    """

    vessel_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Unique vessel key within the portfolio.  Typically the canonical "
            "ship type name (e.g. 'Tanker Ship') but may be any user-supplied "
            "non-empty string when multiple candidates per vessel are provided."
        ),
    )
    ship_type: str = Field(
        ...,
        description=(
            "Canonical vessel archetype.  Must be one of the four supported "
            "portfolio ship types."
        ),
    )
    route_id: str = Field(
        ...,
        min_length=1,
        description="Route identifier at which the candidate was evaluated.",
    )
    annual_voyages: int = Field(
        default=52,
        ge=1,
        description=(
            "Annual voyage count used when the candidate was evaluated.  "
            "Carried through for auditability; Candidate 3 does not re-scale "
            "displacement figures."
        ),
    )
    candidate: OptimizationCandidate = Field(
        ...,
        description=(
            "Pre-evaluated Phase 8 OptimizationCandidate for this vessel at "
            "the specified (Apv, Ebatt) sizing point."
        ),
    )

    @field_validator("ship_type")
    @classmethod
    def validate_ship_type(cls, v: str) -> str:
        if v not in SUPPORTED_PORTFOLIO_SHIP_TYPES:
            raise ValueError(
                f"Unsupported ship_type '{v}'. "
                f"Supported: {SUPPORTED_PORTFOLIO_SHIP_TYPES}"
            )
        return v

    @model_validator(mode="after")
    def validate_candidate_numerical_integrity(self) -> "PortfolioItem":
        """
        Verify that candidate numerical fields are finite and non-negative
        where the Phase 8 contract requires it.  Do not re-validate Phase 8
        feasibility; only check portfolio-level numeric guard rails.
        """
        cand = self.candidate
        import math

        # CAPEX must be finite and non-negative
        if not math.isfinite(cand.total_initial_capex_usd) or cand.total_initial_capex_usd < 0.0:
            raise ValueError(
                f"candidate.total_initial_capex_usd must be finite and >= 0; "
                f"got {cand.total_initial_capex_usd}"
            )

        # annual_fuel_displaced_L must be finite and non-negative
        if not math.isfinite(cand.annual_fuel_displaced_L) or cand.annual_fuel_displaced_L < 0.0:
            raise ValueError(
                f"candidate.annual_fuel_displaced_L must be finite and >= 0; "
                f"got {cand.annual_fuel_displaced_L}"
            )

        # annual_co2_displaced_kg must be finite and non-negative
        if not math.isfinite(cand.annual_co2_displaced_kg) or cand.annual_co2_displaced_kg < 0.0:
            raise ValueError(
                f"candidate.annual_co2_displaced_kg must be finite and >= 0; "
                f"got {cand.annual_co2_displaced_kg}"
            )

        # net_present_value_usd must be finite (may be negative)
        if not math.isfinite(cand.net_present_value_usd):
            raise ValueError(
                f"candidate.net_present_value_usd must be finite; "
                f"got {cand.net_present_value_usd}"
            )

        return self


# ==============================================================================
# 2. Portfolio Optimization Parameters Contract
# ==============================================================================
class PortfolioOptimizationParameters(BaseModel):
    """
    Portfolio-level constraints and settings for the CO₂-maximization
    capital allocation engine.

    Primary objective is FIXED to MAX_ANNUAL_CO2_DISPLACEMENT.
    Secondary metrics (CAPEX, NPV, fuel displacement) are reported but do not
    alter the allocation decision.
    """

    total_portfolio_capex_budget_usd: float = Field(
        ...,
        gt=0.0,
        description=(
            "Total portfolio capital expenditure ceiling in USD.  Required; "
            "no default is provided.  The sum of selected candidates' "
            "total_initial_capex_usd must not exceed this value."
        ),
    )
    max_retrofits: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Optional upper bound on the number of vessels that may be "
            "retrofitted.  If None, the ceiling equals the number of eligible "
            "portfolio items."
        ),
    )
    min_annual_co2_displaced_kg: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Optional minimum annual CO₂ displacement (kg) that the selected "
            "portfolio must achieve.  If the objective result falls below this "
            "floor the allocation is infeasible.  Default 0 (no minimum)."
        ),
    )
    min_annual_fuel_displaced_L: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Optional minimum annual fuel displacement (Litres) that the "
            "selected portfolio must achieve.  Default 0 (no minimum)."
        ),
    )

    @model_validator(mode="after")
    def validate_constraint_consistency(self) -> "PortfolioOptimizationParameters":
        if self.max_retrofits is not None and self.max_retrofits < 1:
            raise ValueError("max_retrofits must be >= 1 when specified.")
        return self


# ==============================================================================
# 3. Portfolio Allocation Result Contract
# ==============================================================================
class PortfolioAllocationResult(BaseModel):
    """
    Complete output of the Phase 9 Candidate 3 portfolio allocation run.

    All aggregate fields are arithmetic sums of the corresponding
    OptimizationCandidate fields across selected_items.  No new financial or
    physical equations are introduced.

    Portfolio aggregation identities (verifiable externally):
      total_capex_usd
        = Σ item.candidate.total_initial_capex_usd  for item in selected_items
      total_annual_co2_displaced_kg
        = Σ item.candidate.annual_co2_displaced_kg   for item in selected_items
      total_annual_fuel_displaced_L
        = Σ item.candidate.annual_fuel_displaced_L   for item in selected_items
      total_npv_usd
        = Σ item.candidate.net_present_value_usd     for item in selected_items
      selected_retrofit_count
        = len(selected_items)
    """

    parameters: PortfolioOptimizationParameters = Field(
        ...,
        description="Constraints and settings applied during allocation.",
    )

    # --- Selection output ---
    selected_items: List[PortfolioItem] = Field(
        default_factory=list,
        description=(
            "Ordered list of portfolio items selected by the optimizer.  "
            "At most one item per distinct vessel_id.  Empty when no "
            "allocation satisfies the constraints."
        ),
    )

    # --- Aggregate metrics (arithmetic sums over selected_items) ---
    total_capex_usd: float = Field(
        ...,
        ge=0.0,
        description="Sum of total_initial_capex_usd across all selected items.",
    )
    total_annual_co2_displaced_kg: float = Field(
        ...,
        ge=0.0,
        description="Sum of annual_co2_displaced_kg across all selected items.",
    )
    total_annual_fuel_displaced_L: float = Field(
        ...,
        ge=0.0,
        description="Sum of annual_fuel_displaced_L across all selected items.",
    )
    total_npv_usd: float = Field(
        ...,
        description=(
            "Sum of net_present_value_usd across all selected items.  "
            "May be negative."
        ),
    )
    selected_retrofit_count: int = Field(
        ...,
        ge=0,
        description="Number of portfolio items selected (len(selected_items)).",
    )

    # --- Solver diagnostics ---
    portfolios_evaluated: int = Field(
        ...,
        ge=0,
        description="Total number of portfolio subsets evaluated by the solver.",
    )
    eligible_items_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of portfolio items that passed the Phase 8 validity filter "
            "and entered the allocation engine."
        ),
    )
    excluded_items_count: int = Field(
        ...,
        ge=0,
        description=(
            "Number of portfolio items excluded due to Phase 8 validity "
            "failures (CONSTRAINED_OUT, BUDGET_EXCEEDED, invalid, infeasible)."
        ),
    )
    diagnostics: str = Field(
        ...,
        description=(
            f"Machine-readable outcome status.  One of: "
            f"'{DIAG_OPTIMAL_ALLOCATION}', "
            f"'{DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS}', "
            f"'{DIAG_ZERO_RETROFIT_ALLOCATION}'."
        ),
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Diagnostic notices and boundary observations.",
    )

    @model_validator(mode="after")
    def validate_aggregate_consistency(self) -> "PortfolioAllocationResult":
        """Verify that aggregate fields are consistent with selected_items."""
        import math

        expected_capex = sum(
            item.candidate.total_initial_capex_usd for item in self.selected_items
        )
        expected_co2 = sum(
            item.candidate.annual_co2_displaced_kg for item in self.selected_items
        )
        expected_fuel = sum(
            item.candidate.annual_fuel_displaced_L for item in self.selected_items
        )
        expected_npv = sum(
            item.candidate.net_present_value_usd for item in self.selected_items
        )
        expected_count = len(self.selected_items)

        tol = 1e-6

        def near(a: float, b: float) -> bool:
            return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol * max(1.0, abs(b))

        if not near(self.total_capex_usd, expected_capex):
            raise ValueError(
                f"total_capex_usd ({self.total_capex_usd}) inconsistent with "
                f"sum of selected items ({expected_capex})."
            )
        if not near(self.total_annual_co2_displaced_kg, expected_co2):
            raise ValueError(
                f"total_annual_co2_displaced_kg ({self.total_annual_co2_displaced_kg}) "
                f"inconsistent with sum of selected items ({expected_co2})."
            )
        if not near(self.total_annual_fuel_displaced_L, expected_fuel):
            raise ValueError(
                f"total_annual_fuel_displaced_L ({self.total_annual_fuel_displaced_L}) "
                f"inconsistent with sum of selected items ({expected_fuel})."
            )
        if not near(self.total_npv_usd, expected_npv):
            raise ValueError(
                f"total_npv_usd ({self.total_npv_usd}) inconsistent with "
                f"sum of selected items ({expected_npv})."
            )
        if self.selected_retrofit_count != expected_count:
            raise ValueError(
                f"selected_retrofit_count ({self.selected_retrofit_count}) != "
                f"len(selected_items) ({expected_count})."
            )
        return self
