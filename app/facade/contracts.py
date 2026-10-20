"""
app/facade/contracts.py — Phase 10A Integration Facade Contracts
================================================================
Defines application-level strongly-typed request and response contracts
for the MaritimeScenarioFacade.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Strict parameter validation (no negative distances, speeds, budgets, or invalid bounds).
  - Explicit provenance tracking on all facade responses.
  - Zero mutable global state.
  - Zero recomputation: purely wraps and adapts upstream frozen contracts.
"""

from enum import Enum
from typing import Dict, Generic, List, Optional, TypeVar, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from phase6_contracts import (
    Phase6SimulationResult,
    VoyageSimulationRequest,
)
from phase7_contracts import (
    FinancialParameters,
    InvestmentAppraisalResult,
)
from phase8_contracts import (
    OptimizationParameters,
    OptimizationCandidate,
    OptimizationResult,
    VALID_OBJECTIVES,
    VALID_PARETO_OBJECTIVES,
)
from phase9_contracts import (
    ParameterSweepBounds,
    OATSensitivityResult,
    BreakEvenRequest,
    BreakEvenResult,
    Grid2DRequest,
    Grid2DResult,
    VALID_SENSITIVITY_PARAMETERS,
    VALID_SENSITIVITY_METRICS,
    VALID_BREAK_EVEN_PARAMETERS,
)
from phase9_speed_contracts import (
    SpeedCoOptimizationParameters,
    SpeedCoOptimizationResult,
    VALID_SPEED_PARETO_OBJECTIVES,
)
from phase9_portfolio_contracts import (
    PortfolioItem,
    PortfolioOptimizationParameters,
    PortfolioAllocationResult,
)
from phase9_cii_contracts import (
    TrajectorySimulationRequest,
    TrajectorySimulationResult,
)
from phase9_dossier_contracts import (
    ExportFormatEnum,
    ExportArtifactResult,
    CrossPhaseScenarioDossier,
    DossierAssemblyRequest,
)


class FacadeOperationEnum(str, Enum):
    """Enumeration of all supported facade orchestration operations."""
    SIMULATE_VOYAGE = "SIMULATE_VOYAGE"
    EVALUATE_SIZING_CANDIDATE = "EVALUATE_SIZING_CANDIDATE"
    OPTIMIZE_SYSTEM_SIZING = "OPTIMIZE_SYSTEM_SIZING"
    RUN_SENSITIVITY_ANALYSIS = "RUN_SENSITIVITY_ANALYSIS"
    RUN_BREAK_EVEN_ANALYSIS = "RUN_BREAK_EVEN_ANALYSIS"
    RUN_2D_GRID_ANALYSIS = "RUN_2D_GRID_ANALYSIS"
    OPTIMIZE_SPEED_AND_SIZING = "OPTIMIZE_SPEED_AND_SIZING"
    OPTIMIZE_FLEET_PORTFOLIO = "OPTIMIZE_FLEET_PORTFOLIO"
    SIMULATE_CII_TRAJECTORY = "SIMULATE_CII_TRAJECTORY"
    ASSEMBLE_AND_EXPORT_DOSSIER = "ASSEMBLE_AND_EXPORT_DOSSIER"


class FacadeProvenanceMetadata(BaseModel):
    """Metadata tracking the exact origin and execution path of a facade call."""
    operation: FacadeOperationEnum
    underlying_phase: str
    underlying_function: str
    frozen_core_version: str = "1.0.0"
    status: str = "SUCCESS"
    scenario_name: Optional[str] = None
    vessel_id: Optional[str] = None


T = TypeVar("T")


class FacadeResponse(BaseModel, Generic[T]):
    """Standardized generic application wrapper containing payload and provenance."""
    provenance: FacadeProvenanceMetadata
    data: T
    diagnostics: List[str] = Field(default_factory=list)


# ==============================================================================
# 1. Single-Voyage Simulation Contract
# ==============================================================================

class SimulateVoyageRequest(BaseModel):
    """Application request for single-voyage hydrodynamic and regulatory simulation."""
    ship_type: str = Field(..., description="Vessel archetype: Tanker Ship, Oil Service Boat, Fishing Trawler, Surfer Boat")
    route_id: str = Field(..., description="Corridor: Escravos-Lagos, Warri-Bonny, Lagos-Apapa, Port Harcourt-Lagos")
    month: Union[int, str] = Field(default=7, description="Voyage calendar month (1-12 or month name)")
    speed_knots: float = Field(..., gt=0.0, le=40.0, description="Transit speed in knots")
    distance_nm: Optional[float] = Field(default=None, gt=0.0, description="Optional route distance override in NM")
    solar_area_m2: float = Field(default=0.0, ge=0.0, description="Installed PV area in m2")
    battery_capacity_kwh: float = Field(default=0.0, ge=0.0, description="Installed battery capacity in kWh")
    fuel_price_usd_per_mt: Optional[float] = Field(default=None, gt=0.0, description="Optional fuel price override")
    carbon_price_usd_per_mt: Optional[float] = Field(default=None, ge=0.0, description="Optional carbon price override")
    daily_ghi_kwh_per_m2: Optional[float] = Field(default=None, gt=0.0, description="Optional GHI override")
    regulatory_year: int = Field(default=2026, ge=2023, le=2030, description="Regulatory compliance reference year")

    @field_validator("ship_type")
    @classmethod
    def validate_ship_type(cls, v: str) -> str:
        valid_types = ["Tanker Ship", "Oil Service Boat", "Fishing Trawler", "Surfer Boat"]
        if v not in valid_types:
            raise ValueError(f"ship_type '{v}' is invalid. Must be one of {valid_types}")
        return v


# ==============================================================================
# 2. Single Sizing Candidate Evaluation Contract
# ==============================================================================

class EvaluateSizingCandidateRequest(BaseModel):
    """Application request to evaluate a single (Apv, Ebatt) sizing configuration."""
    ship_type: str = Field(...)
    solar_area_m2: float = Field(..., ge=0.0)
    battery_capacity_kwh: float = Field(..., ge=0.0)
    deck_area_limit_m2: float = Field(..., gt=0.0)
    battery_weight_limit_tonnes: float = Field(..., gt=0.0)
    predicted_soh: float = Field(..., gt=0.0, le=1.0)
    auxiliary_energy_demand_kwh: float = Field(..., ge=0.0)
    voyage_duration_hours: float = Field(..., gt=0.0)
    predicted_fuel_consumption_L: float = Field(..., ge=0.0)
    predicted_CO2_kg: float = Field(..., ge=0.0)
    daily_ghi_kwh_per_m2: float = Field(default=4.5, gt=0.0)
    annual_voyages: int = Field(default=52, ge=1)
    discount_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    fuel_price_usd_per_l: float = Field(default=1.0, gt=0.0)
    carbon_price_usd_per_tonne: float = Field(default=0.0, ge=0.0)
    analysis_horizon_years: int = Field(default=15, ge=1, le=30)
    generator_sfoc_kg_per_kwh: float = Field(default=0.22, gt=0.0)
    fuel_density_kg_per_l: float = Field(default=0.85, gt=0.0)
    emission_factor_kgco2_per_kgfuel: float = Field(default=3.114, gt=0.0)


# ==============================================================================
# 3. Parametric Sizing Optimization Contract
# ==============================================================================

class OptimizeSystemSizingRequest(BaseModel):
    """Application request for full parametric sizing optimization."""
    ship_type: str = Field(...)
    min_solar_area_m2: float = Field(default=0.0, ge=0.0)
    max_solar_area_m2: Optional[float] = Field(default=None, ge=0.0)
    step_solar_area_m2: Optional[float] = Field(default=None, gt=0.0)
    min_battery_capacity_kwh: float = Field(default=0.0, ge=0.0)
    max_battery_capacity_kwh: Optional[float] = Field(default=None, ge=0.0)
    step_battery_capacity_kwh: Optional[float] = Field(default=None, gt=0.0)
    objective: str = Field(default="MAX_NPV")
    pareto_objectives: Optional[List[str]] = Field(default=None)
    budget_limit_usd: Optional[float] = Field(default=None, gt=0.0)
    annual_voyages: int = Field(default=52, ge=1)
    discount_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    analysis_horizon_years: int = Field(default=15, ge=1, le=30)
    simulation_result: Optional[Phase6SimulationResult] = None

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, v: str) -> str:
        if v not in VALID_OBJECTIVES:
            raise ValueError(f"objective '{v}' invalid. Must be one of {VALID_OBJECTIVES}")
        return v


# ==============================================================================
# 4. Sensitivity & Robustness Contracts (Candidate 1)
# ==============================================================================

class SensitivityAnalysisRequest(BaseModel):
    """Application request for OAT sensitivity sweeps."""
    base_candidate: OptimizationCandidate
    parameter_name: str = Field(...)
    metric_name: str = Field(default="net_present_value_usd")
    base_financial_params: Optional[FinancialParameters] = None
    sweep_bounds: Optional[ParameterSweepBounds] = None
    ship_type: str = Field(default="Tanker Ship")
    annual_voyages: int = Field(default=52, ge=1)

    @field_validator("parameter_name")
    @classmethod
    def validate_param_name(cls, v: str) -> str:
        if v not in VALID_SENSITIVITY_PARAMETERS:
            raise ValueError(f"parameter_name '{v}' not in authorized list: {VALID_SENSITIVITY_PARAMETERS}")
        return v

    @field_validator("metric_name")
    @classmethod
    def validate_metric_name(cls, v: str) -> str:
        if v not in VALID_SENSITIVITY_METRICS:
            raise ValueError(f"metric_name '{v}' not in authorized list: {VALID_SENSITIVITY_METRICS}")
        return v


class BreakEvenAnalysisRequest(BaseModel):
    """Application request for 1D break-even root-finding."""
    base_candidate: OptimizationCandidate
    parameter_name: str = Field(...)
    metric_name: str = Field(default="net_present_value_usd")
    target_value: float = Field(default=0.0)
    lower_bound: float = Field(...)
    upper_bound: float = Field(...)
    base_financial_params: Optional[FinancialParameters] = None
    ship_type: str = Field(default="Tanker Ship")
    annual_voyages: int = Field(default=52, ge=1)


class Grid2DAnalysisRequest(BaseModel):
    """Application request for 2D parameter contour matrix evaluation."""
    base_candidate: OptimizationCandidate
    parameter_x_name: str = Field(...)
    parameter_y_name: str = Field(...)
    metric_name: str = Field(default="net_present_value_usd")
    sweep_bounds_x: ParameterSweepBounds
    sweep_bounds_y: ParameterSweepBounds
    base_financial_params: Optional[FinancialParameters] = None
    ship_type: str = Field(default="Tanker Ship")
    annual_voyages: int = Field(default=52, ge=1)


# ==============================================================================
# 5. Speed & Sizing Co-Optimization Contract (Candidate 2)
# ==============================================================================

class SpeedCoOptimizationFacadeRequest(BaseModel):
    """Application request for operational speed and hybrid sizing co-optimization."""
    ship_type: str = Field(...)
    route_id: str = Field(...)
    vmin: float = Field(..., gt=0.0)
    vmax: float = Field(..., gt=0.0)
    v_step: Optional[float] = Field(default=None, gt=0.0)
    apv_min: float = Field(default=0.0, ge=0.0)
    apv_max: Optional[float] = Field(default=None, ge=0.0)
    apv_step: Optional[float] = Field(default=None, gt=0.0)
    ebatt_min: float = Field(default=0.0, ge=0.0)
    ebatt_max: Optional[float] = Field(default=None, ge=0.0)
    ebatt_step: Optional[float] = Field(default=None, gt=0.0)
    objective: str = Field(default="PARETO_FRONTIER")
    pareto_objectives: Optional[List[str]] = Field(default=None)
    transit_deadline_hours: Optional[float] = Field(default=None, gt=0.0)
    annual_voyages: int = Field(default=52, ge=1)
    discount_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    analysis_horizon_years: int = Field(default=15, ge=1, le=30)
    fuel_price_usd_per_l: Optional[float] = Field(default=None, gt=0.0)


# ==============================================================================
# 6. Fleet Portfolio Optimization Contract (Candidate 3)
# ==============================================================================

class PortfolioOptimizationFacadeRequest(BaseModel):
    """Application request for fleet portfolio capital allocation."""
    total_portfolio_capex_budget_usd: float = Field(..., ge=0.0)
    portfolio_items: List[PortfolioItem] = Field(..., min_length=1)
    max_retrofits: Optional[int] = Field(default=None, ge=1)
    min_annual_co2_displaced_kg: float = Field(default=0.0, ge=0.0)
    min_annual_fuel_displaced_L: float = Field(default=0.0, ge=0.0)


# ==============================================================================
# 7. CII Compliance Trajectory Contract (Candidate 4)
# ==============================================================================

class CIIComplianceTrajectoryRequest(BaseModel):
    """Application request for multi-year IMO CII compliance aging trajectory."""
    vessel_id: str = Field(...)
    ship_type: str = Field(...)
    dwt_tonnes: float = Field(..., gt=0.0)
    route_id: str = Field(...)
    voyage_distance_nm: float = Field(..., gt=0.0)
    annual_voyages: int = Field(default=52, ge=1)
    baseline_single_voyage_fuel_L: float = Field(..., gt=0.0)
    baseline_single_voyage_co2_kg: float = Field(..., gt=0.0)
    start_year: int = Field(default=2023, ge=2020)
    end_year: int = Field(default=2026, ge=2023)
    annual_fuel_displaced_L: float = Field(default=0.0, ge=0.0)
    annual_co2_displaced_kg: float = Field(default=0.0, ge=0.0)
    custom_annual_degradation_rate_pct: Optional[float] = Field(default=None, ge=0.0, le=20.0)
    custom_z_reduction_pct_per_year: Optional[float] = Field(default=None, ge=0.0, le=10.0)


# ==============================================================================
# 8. Dossier Assembly & Export Contract (Candidate 5)
# ==============================================================================

class DossierExportFacadeRequest(BaseModel):
    """Application request for end-to-end dossier assembly, validation, and export."""
    scenario_name: str = Field(..., min_length=1)
    vessel_id: str = Field(..., min_length=1)
    ship_type: str = Field(...)
    route_id: str = Field(...)
    export_formats: List[ExportFormatEnum] = Field(default_factory=lambda: [ExportFormatEnum.ALL])
    output_directory: Optional[str] = Field(default=None, description="Optional directory to persist files")
    filename_prefix: str = Field(default="scenario_dossier")
    phase6_result: Optional[Phase6SimulationResult] = None
    phase7_result: Optional[InvestmentAppraisalResult] = None
    phase8_result: Optional[OptimizationResult] = None
    candidate1_sensitivity: Optional[OATSensitivityResult] = None
    candidate2_cooptimization: Optional[SpeedCoOptimizationResult] = None
    candidate3_portfolio: Optional[PortfolioAllocationResult] = None
    candidate4_trajectory: Optional[TrajectorySimulationResult] = None
