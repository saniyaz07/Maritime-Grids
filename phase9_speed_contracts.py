"""
phase9_speed_contracts.py — Pydantic V2 Contracts for Phase 9 Candidate 2
==========================================================================
Defines:
  - SpeedCoOptimizationParameters: 3D operational search lattice parameters (Speed x Apv x Ebatt),
    transit deadline constraints, objective formulation, and computational boundaries.
  - SpeedSizingCandidate: Detailed audit record of an individual 3D candidate configuration.
  - SpeedCoOptimizationResult: Complete optimization output including optimal candidate,
    speed-power tradeoff curve, and 3D non-dominated Pareto frontier.

All models adhere to:
  - Strict Pydantic V2 validation.
  - Explicit parameter validation without silent fallback guessing.
  - Hard computational evaluation ceiling (max 2,500 evaluations per execution).
  - Zero modification to frozen Phase 0–8 contracts or Phase 9 Candidate 1 contracts.
"""

from typing import List, Dict, Optional, Any
import math
from pydantic import BaseModel, Field, field_validator, model_validator

from phase7_contracts import FinancialParameters
from phase8_contracts import (
    SMALL_CRAFT_TYPES,
    LARGE_VESSEL_TYPES,
)

# Authorized Pareto objectives for Candidate 2
VALID_SPEED_PARETO_OBJECTIVES = [
    "MIN_DURATION",
    "MIN_ANNUAL_FUEL",
    "MAX_NPV",
    "MAX_FUEL_DISPLACEMENT",
    "MIN_CAPEX",
]

# Canonical speed step defaults per vessel category
DEFAULT_SPEED_STEP_KNOTS: Dict[str, float] = {
    "Oil Service Boat": 0.5,
    "Fishing Trawler": 0.5,
    "Tanker Ship": 0.5,
    "Surfer Boat": 1.0,
}

# Supported project vessel types
SUPPORTED_SHIP_TYPES = [
    "Oil Service Boat",
    "Fishing Trawler",
    "Surfer Boat",
    "Tanker Ship",
]

MAX_SPEED_EVALUATIONS_LIMIT = 2500
MAX_EXECUTION_TIME_LIMIT_SECONDS = 2.0


class SpeedCoOptimizationParameters(BaseModel):
    """
    Search lattice parameters for simultaneous operational speed and hybrid sizing co-optimization.
    Lattice: V_speed x A_pv x E_batt.
    """
    ship_type: str = Field(
        ...,
        description="Vessel archetype: 'Oil Service Boat', 'Fishing Trawler', 'Surfer Boat', or 'Tanker Ship'."
    )
    route_id: str = Field(
        default="Warri-Bonny",
        description="Target corridor route identifier."
    )
    distance_nm: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Voyage distance in nautical miles. If None, resolved from canonical route distance tables."
    )
    month: int = Field(
        default=7,
        ge=1,
        le=12,
        description="Calendar month index (1 to 12) for climatological solar irradiance."
    )

    # Operational speed lattice
    vmin: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Minimum transit speed in knots. If None, resolved to 0.60 * Vdesign."
    )
    vmax: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Maximum transit speed in knots. If None, resolved to 1.00 * Vdesign."
    )
    v_step: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Discrete speed step in knots. If None, resolved to 0.5 kn (displacement) or 1.0 kn (Surfer)."
    )

    # Physical sizing lattice
    apv_min: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum solar PV array area in m2."
    )
    apv_max: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Maximum solar PV array area in m2. If None, resolved from fdeck_max * L * B."
    )
    apv_step: float = Field(
        default=10.0,
        gt=0.0,
        description="Discrete grid step size for solar array area in m2."
    )

    ebatt_min: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum battery storage capacity in kWh."
    )
    ebatt_max: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Maximum battery storage capacity in kWh. If None, resolved from fdwt_max * DWT."
    )
    ebatt_step: float = Field(
        default=25.0,
        gt=0.0,
        description="Discrete grid step size for battery pack capacity in kWh."
    )

    # Transit delivery deadline constraint
    t_deadline: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Maximum allowable voyage transit duration in hours."
    )

    # Auxiliary electrical load and hydrodynamic baseline parameters
    paux_kw: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Auxiliary hotel load power demand in kW. If None, resolved from default auxiliary demand."
    )
    reference_fuel_consumption_L: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Reference baseline total voyage fuel consumption in Liters at Vref. If None, inferred via Phase 6."
    )
    reference_speed_knots: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Reference speed in knots corresponding to reference_fuel_consumption_L."
    )

    # Operational schedule & financial parameters
    annual_voyages: int = Field(
        default=52,
        ge=1,
        description="Fixed annual voyage count multiplier applied to single-voyage metrics."
    )
    financial_parameters: FinancialParameters = Field(
        default_factory=FinancialParameters,
        description="Phase 7 macroeconomic, fuel price, and lifecycle financial assumptions."
    )

    # Physical limits and environmental assumptions
    fdeck_max: float = Field(default=0.25, ge=0.01, le=0.80)
    fdwt_max: float = Field(default=0.05, ge=0.001, le=0.20)
    battery_specific_mass_kg_per_kwh: float = Field(default=8.5, ge=1.0, le=50.0)
    generator_sfoc_kg_per_kwh: float = Field(default=0.220, gt=0.0)
    fuel_density_kg_per_l: float = Field(default=0.850, gt=0.0)
    emission_factor_kgco2_per_kgfuel: float = Field(default=3.114, gt=0.0)
    daily_ghi_kwh_per_m2: Optional[float] = Field(default=None, ge=0.0)
    predicted_soh: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Optimization objectives and constraints
    objective: str = Field(
        default="PARETO_FRONTIER",
        description="'PARETO_FRONTIER', 'MIN_ANNUAL_FUEL', 'MAX_NPV', or 'MIN_DURATION'."
    )
    pareto_objectives: List[str] = Field(
        default_factory=lambda: ["MIN_DURATION", "MIN_ANNUAL_FUEL", "MAX_NPV"],
        description="Tradeoff dimensions for multi-objective Pareto non-domination."
    )
    max_evaluations: int = Field(
        default=MAX_SPEED_EVALUATIONS_LIMIT,
        ge=1,
        le=MAX_SPEED_EVALUATIONS_LIMIT,
        description="Hard computational evaluation budget ceiling (max 2,500)."
    )

    @field_validator("ship_type")
    @classmethod
    def validate_ship_type(cls, v: str) -> str:
        if v not in SUPPORTED_SHIP_TYPES:
            raise ValueError(f"Invalid ship_type '{v}'. Supported: {SUPPORTED_SHIP_TYPES}")
        return v

    @field_validator("pareto_objectives")
    @classmethod
    def validate_pareto_objectives(cls, v: List[str]) -> List[str]:
        if len(v) < 2:
            raise ValueError("pareto_objectives must contain at least 2 distinct objectives.")
        for obj in v:
            if obj not in VALID_SPEED_PARETO_OBJECTIVES:
                raise ValueError(f"Invalid Pareto objective '{obj}'. Must be one of: {VALID_SPEED_PARETO_OBJECTIVES}")
        return v

    @model_validator(mode="after")
    def validate_bounds_and_steps(self) -> "SpeedCoOptimizationParameters":
        if self.vmin is not None and self.vmax is not None:
            if self.vmin > self.vmax:
                raise ValueError(f"vmin ({self.vmin}) cannot exceed vmax ({self.vmax}).")
        if self.apv_max is not None and self.apv_min > self.apv_max:
            raise ValueError(f"apv_min ({self.apv_min}) cannot exceed apv_max ({self.apv_max}).")
        if self.ebatt_max is not None and self.ebatt_min > self.ebatt_max:
            raise ValueError(f"ebatt_min ({self.ebatt_min}) cannot exceed ebatt_max ({self.ebatt_max}).")
        return self


class SpeedSizingCandidate(BaseModel):
    """
    Detailed audit record of an individual 3D candidate configuration (Speed x Apv x Ebatt).
    """
    speed_knots: float = Field(..., gt=0.0, description="Evaluated transit speed in knots.")
    solar_area_m2: float = Field(..., ge=0.0, description="Evaluated solar array area in m2.")
    battery_capacity_kwh: float = Field(..., ge=0.0, description="Evaluated battery capacity in kWh.")
    battery_mass_tonnes: float = Field(..., ge=0.0, description="Total battery pack mass in metric tonnes.")
    voyage_duration_hours: float = Field(..., gt=0.0, description="Transit voyage duration in hours.")
    meets_deadline: bool = Field(..., description="True iff voyage_duration_hours <= t_deadline.")
    
    is_physically_valid: bool = Field(..., description="True iff candidate satisfies hard physical constraints.")
    constraint_violations: List[str] = Field(default_factory=list, description="Hard constraint violation tags.")
    candidate_status: str = Field(..., description="'VALID', 'DEADLINE_EXCEEDED', 'CONSTRAINED_OUT', or error code.")

    # Hydrodynamic baseline & auxiliary fuel metrics
    single_voyage_propulsion_fuel_L: float = Field(..., ge=0.0, description="Propulsion diesel consumption per voyage in Liters.")
    single_voyage_auxiliary_fuel_L: float = Field(..., ge=0.0, description="Auxiliary diesel consumption per voyage in Liters.")
    single_voyage_total_fuel_L: float = Field(..., ge=0.0, description="Total baseline diesel consumption per voyage in Liters.")
    
    # Phase 8 physical clean-energy displacement
    clean_energy_utilized_kwh: float = Field(..., ge=0.0, description="Clean electrical energy utilized per voyage in kWh.")
    annual_fuel_displaced_L: float = Field(..., ge=0.0, description="Annual auxiliary diesel displaced in Liters.")
    annual_co2_displaced_kg: float = Field(..., ge=0.0, description="Annual CO2 emissions avoided in kg.")
    feasibility_status: str = Field(..., description="'FEASIBLE' or 'PARTIAL'.")

    # Net annual operational totals
    annual_fuel_consumed_L: float = Field(..., ge=0.0, description="Gross annual fuel consumption without hybrid assist in Liters.")
    net_annual_fuel_consumed_L: float = Field(..., ge=0.0, description="Net annual fuel consumption after hybrid displacement in Liters.")
    annual_co2_emissions_kg: float = Field(..., ge=0.0, description="Net annual CO2 emissions in kg.")

    # Phase 7 lifecycle economics
    total_initial_capex_usd: float = Field(..., ge=0.0, description="Total initial capital expenditure in USD.")
    net_present_value_usd: float = Field(..., description="Net Present Value in USD over analysis horizon.")
    internal_rate_of_return_pct: Optional[float] = Field(default=None, description="Internal Rate of Return percentage or None.")
    irr_status: str = Field(..., description="Phase 7 diagnostic IRR status.")
    simple_payback_years: Optional[float] = Field(default=None, ge=0.0, description="Simple payback period in years or None.")
    discounted_payback_years: Optional[float] = Field(default=None, ge=0.0, description="Discounted payback period in years or None.")
    lcoe_usd_per_kwh: Optional[float] = Field(default=None, ge=0.0, description="Levelized Cost of Energy in USD/kWh or None.")
    lcoe_status: str = Field(..., description="Phase 7 LCOE diagnostic status.")

    objective_values: Dict[str, float] = Field(
        default_factory=dict,
        description="Evaluated numerical scores for requested optimization objectives."
    )


class SpeedCoOptimizationResult(BaseModel):
    """
    Unified result payload of the Candidate 2 Speed x Sizing Co-Optimization engine.
    """
    parameters: SpeedCoOptimizationParameters = Field(..., description="Applied input parameters.")
    resolved_distance_nm: float = Field(..., gt=0.0, description="Resolved transit distance in nautical miles.")
    resolved_vref_knots: float = Field(..., gt=0.0, description="Resolved baseline reference speed in knots.")
    resolved_vmin_knots: float = Field(..., gt=0.0, description="Resolved minimum speed bound in knots.")
    resolved_vmax_knots: float = Field(..., gt=0.0, description="Resolved maximum speed bound in knots.")
    resolved_vstep_knots: float = Field(..., gt=0.0, description="Resolved speed step increment in knots.")

    speed_candidate_count: int = Field(..., ge=1, description="Number of discrete speed steps evaluated.")
    solar_candidate_count: int = Field(..., ge=1, description="Number of discrete solar points per speed.")
    battery_candidate_count: int = Field(..., ge=1, description="Number of discrete battery points per speed.")
    total_configurations_evaluated: int = Field(..., ge=1, description="Total 3D configurations evaluated.")
    valid_candidates_count: int = Field(..., ge=0, description="Count of valid, deadline-compliant candidates.")
    deadline_exceeded_count: int = Field(..., ge=0, description="Count of candidates filtered out by transit deadline.")

    optimal_candidate: Optional[SpeedSizingCandidate] = Field(
        default=None,
        description="Single optimal candidate for primary scalar objective (or highest NPV Pareto candidate)."
    )
    speed_tradeoff_curve: List[SpeedSizingCandidate] = Field(
        default_factory=list,
        description="Best sizing candidate evaluated at each discrete operational speed."
    )
    pareto_frontier: List[SpeedSizingCandidate] = Field(
        default_factory=list,
        description="Non-dominated Pareto frontier candidates across Duration, Annual Fuel, and NPV."
    )
    candidate_results: List[SpeedSizingCandidate] = Field(
        default_factory=list,
        description="Complete list of all evaluated 3D candidates across the lattice."
    )
    execution_time_seconds: float = Field(..., ge=0.0, description="Total wall-clock runtime in seconds.")
    diagnostics: str = Field(..., description="Execution diagnostic status.")
    warnings: List[str] = Field(default_factory=list, description="Diagnostic warnings and notices.")
