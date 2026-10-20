"""
phase8_contracts.py — Pydantic V2 Contracts for Parametric System Sizing Optimization
======================================================================================
Defines:
  - OptimizationParameters: Grid bounds, discrete step increments, engineering limits,
    objective selection, and financial parameters.
  - OptimizationCandidate: Sizing candidate (A_pv, E_batt) with physical feasibility,
    generator displacement, lifecycle financials, and constraint violation status.
  - OptimizationResult: Complete optimization output with optimal candidate, top tied
    candidates, Pareto frontier, and execution diagnostics.

Zero subjective evaluative labels ("best", "ideal", "recommended").
Zero modification to frozen upstream contracts or models.
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from phase7_contracts import FinancialParameters

VALID_OBJECTIVES = [
    "MAX_NPV",
    "MAX_FUEL_DISPLACEMENT",
    "MAX_CO2_DISPLACEMENT",
    "MIN_LCOE",
    "MIN_CAPEX",
    "PARETO_FRONTIER",
]

VALID_PARETO_OBJECTIVES = [
    "MIN_CAPEX",
    "MAX_FUEL_DISPLACEMENT",
    "MAX_CO2_DISPLACEMENT",
    "MAX_NPV",
    "MIN_LCOE",
]

SMALL_CRAFT_TYPES = ["Fishing Trawler", "Surfer Boat"]
LARGE_VESSEL_TYPES = ["Oil Service Boat", "Tanker Ship", "Tanker"]


class OptimizationParameters(BaseModel):
    """
    Search lattice parameters, physical and economic constraint boundaries,
    objective selection, and financial assumptions for parametric sizing optimization.
    """
    ship_type: str = Field(
        ...,
        description="Vessel archetype: 'Oil Service Boat', 'Fishing Trawler', 'Surfer Boat', or 'Tanker Ship'."
    )
    min_solar_area_m2: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum solar PV array surface area in m2."
    )
    max_solar_area_m2: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Maximum solar PV array surface area in m2. If None, resolved from fdeck_max * L * B."
    )
    step_solar_area_m2: float = Field(
        default=10.0,
        gt=0.0,
        description="Discrete grid step size for solar array area in m2."
    )
    min_battery_capacity_kwh: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum nominal battery pack capacity in kWh."
    )
    max_battery_capacity_kwh: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Maximum nominal battery pack capacity in kWh. If None, resolved from fdwt_max * DWT."
    )
    step_battery_capacity_kwh: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Discrete grid step size for battery pack capacity in kWh. If None, resolved via small-craft rule."
    )
    fdeck_max: float = Field(
        default=0.25,
        ge=0.01,
        le=0.80,
        description="Configurable engineering assumption for maximum available deck area fraction (0.01 to 0.80)."
    )
    fdwt_max: float = Field(
        default=0.05,
        ge=0.001,
        le=0.20,
        description="Configurable engineering assumption for maximum allowable battery payload DWT fraction."
    )
    battery_specific_mass_kg_per_kwh: float = Field(
        default=8.5,
        ge=1.0,
        le=50.0,
        description="Configurable engineering assumption for battery pack gravimetric mass density in kg/kWh."
    )
    require_fully_feasible: bool = Field(
        default=False,
        description="If True, filters out candidates that do not achieve 100% auxiliary load coverage (FEASIBLE status)."
    )
    max_capex_budget_usd: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Optional upper boundary on total initial capital expenditure (CAPEX_0)."
    )
    objective: str = Field(
        default="MAX_NPV",
        description="Optimization objective: 'MAX_NPV', 'MAX_FUEL_DISPLACEMENT', 'MAX_CO2_DISPLACEMENT', 'MIN_LCOE', 'MIN_CAPEX', or 'PARETO_FRONTIER'."
    )
    pareto_objectives: Optional[List[str]] = Field(
        default_factory=lambda: ["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"],
        description="Multi-objective criteria list when objective == 'PARETO_FRONTIER'."
    )
    annual_voyages: int = Field(
        default=52,
        ge=1,
        description="Annual voyage multiplier applied to single-voyage physical displacement metrics."
    )
    financial_parameters: FinancialParameters = Field(
        default_factory=FinancialParameters,
        description="Phase 7 financial and macroeconomic parameters."
    )

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, v: str) -> str:
        if v not in VALID_OBJECTIVES:
            raise ValueError(f"Invalid objective '{v}'. Must be one of: {VALID_OBJECTIVES}")
        return v

    @field_validator("pareto_objectives")
    @classmethod
    def validate_pareto_objectives(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None:
            if len(v) < 2:
                raise ValueError("pareto_objectives must contain at least 2 objectives for multi-objective analysis.")
            for obj in v:
                if obj not in VALID_PARETO_OBJECTIVES:
                    raise ValueError(f"Invalid Pareto objective '{obj}'. Must be one of: {VALID_PARETO_OBJECTIVES}")
        return v

    @model_validator(mode="after")
    def validate_bounds_and_steps(self) -> "OptimizationParameters":
        if self.max_solar_area_m2 is not None and self.max_solar_area_m2 < self.min_solar_area_m2:
            raise ValueError(
                f"max_solar_area_m2 ({self.max_solar_area_m2}) cannot be less than min_solar_area_m2 ({self.min_solar_area_m2})."
            )
        if self.max_battery_capacity_kwh is not None and self.max_battery_capacity_kwh < self.min_battery_capacity_kwh:
            raise ValueError(
                f"max_battery_capacity_kwh ({self.max_battery_capacity_kwh}) cannot be less than min_battery_capacity_kwh ({self.min_battery_capacity_kwh})."
            )
        return self


class OptimizationCandidate(BaseModel):
    """
    Detailed audit record of an individual evaluated candidate sizing point (A_pv, E_batt).
    """
    solar_area_m2: float = Field(..., ge=0.0, description="Evaluated solar array area in m2.")
    battery_capacity_kwh: float = Field(..., ge=0.0, description="Evaluated nominal battery capacity in kWh.")
    battery_mass_tonnes: float = Field(..., ge=0.0, description="Calculated total battery pack weight in metric tonnes.")
    deck_area_limit_m2: float = Field(..., ge=0.0, description="Upper deck boundary limit applied in m2.")
    battery_weight_limit_tonnes: float = Field(..., ge=0.0, description="Upper battery weight limit applied in metric tonnes.")
    
    is_physically_valid: bool = Field(..., description="True iff candidate satisfies all hard physical and economic boundaries.")
    constraint_violations: List[str] = Field(default_factory=list, description="List of violated hard constraints, if any.")
    candidate_status: str = Field(..., description="'VALID', 'CONSTRAINED_OUT', 'INCOMPLETE_FEASIBILITY', or 'BUDGET_EXCEEDED'.")
    
    # Phase 3 physical metrics
    clean_energy_available_kwh: float = Field(..., ge=0.0, description="Total clean energy available per voyage in kWh.")
    clean_energy_utilized_kwh: float = Field(..., ge=0.0, description="Clean electrical energy absorbed by hotel load per voyage in kWh.")
    curtailed_energy_kwh: float = Field(..., ge=0.0, description="Surplus clean energy curtailed per voyage in kWh.")
    feasibility_status: str = Field(..., description="'FEASIBLE' or 'PARTIAL'.")
    annual_fuel_displaced_L: float = Field(..., ge=0.0, description="Total annual bunker fuel displaced in Litres.")
    annual_co2_displaced_kg: float = Field(..., ge=0.0, description="Total annual CO2 emissions avoided in kg.")
    
    # Phase 7 economic metrics
    total_initial_capex_usd: float = Field(..., ge=0.0, description="Total initial overnight capital investment in USD.")
    net_present_value_usd: float = Field(..., description="Net Present Value in USD over the analysis horizon.")
    internal_rate_of_return_pct: Optional[float] = Field(default=None, description="Internal Rate of Return percentage or None.")
    irr_status: str = Field(..., description="Neutral diagnostic IRR status from Phase 7.")
    simple_payback_years: Optional[float] = Field(default=None, ge=0.0, description="Simple payback period in years or None.")
    discounted_payback_years: Optional[float] = Field(default=None, ge=0.0, description="Discounted payback period in years or None.")
    lcoe_usd_per_kwh: Optional[float] = Field(default=None, ge=0.0, description="Levelized Cost of Clean Energy in USD/kWh or None.")
    lcoe_status: str = Field(..., description="'LCOE_CALCULATED' or 'LCOE_UNDEFINED_ZERO_ENERGY'.")
    
    objective_value: Optional[float] = Field(default=None, description="Scalar numerical score according to selected objective.")


class OptimizationResult(BaseModel):
    """
    Unified result payload of the Phase 8 Parametric Sizing Optimization run.
    """
    parameters: OptimizationParameters = Field(..., description="Parameters and constraints applied during optimization.")
    resolved_max_solar_area_m2: float = Field(..., ge=0.0, description="Actual maximum solar area bound applied.")
    resolved_max_battery_capacity_kwh: float = Field(..., ge=0.0, description="Actual maximum battery capacity bound applied.")
    resolved_step_battery_capacity_kwh: float = Field(..., gt=0.0, description="Actual battery step increment applied.")
    
    solar_candidate_count: int = Field(..., ge=1, description="Number of discrete solar points in grid.")
    battery_candidate_count: int = Field(..., ge=1, description="Number of discrete battery points in grid.")
    total_candidates_evaluated: int = Field(..., ge=1, description="Total grid points evaluated.")
    feasible_candidates_count: int = Field(..., ge=0, description="Count of valid candidates meeting all constraints.")
    infeasible_candidates_count: int = Field(..., ge=0, description="Count of candidates filtered out by constraints.")
    
    optimal_candidate: Optional[OptimizationCandidate] = Field(
        default=None,
        description="Globally optimal candidate on the grid for the requested objective (with deterministic tie-breaking)."
    )
    top_candidates: List[OptimizationCandidate] = Field(
        default_factory=list,
        description="Top candidates, including any tied optimal candidates."
    )
    tie_candidates_notes: List[str] = Field(
        default_factory=list,
        description="Diagnostic notes regarding primary objective ties resolved via deterministic tie-breaking."
    )
    pareto_frontier: List[OptimizationCandidate] = Field(
        default_factory=list,
        description="Non-dominated Pareto frontier candidates when objective == 'PARETO_FRONTIER'."
    )
    candidate_results: List[OptimizationCandidate] = Field(
        default_factory=list,
        description="Complete list of all evaluated candidates across the grid (for full auditability)."
    )
    diagnostics: str = Field(
        ...,
        description="'OPTIMIZATION_COMPLETED', 'NO_FEASIBLE_CANDIDATE_FOUND', or 'NO_VALID_LCOE_CANDIDATE'."
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Machine-readable diagnostic notices and boundary observations."
    )
