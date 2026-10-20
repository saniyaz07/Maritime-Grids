"""
phase9_contracts.py — Pydantic V2 Contracts for Phase 9 Candidate 1
====================================================================
Defines:
  - SupportedSensitivityParameter: Enumerated parameter identifiers.
  - ParameterSweepBounds: Configuration bounds and steps for sensitivity sweeps.
  - OATSensitivityPoint: Structured evaluation point for 1D sensitivity analysis.
  - OATSensitivityResult: Aggregated 1D sensitivity curve and diagnostic metadata.
  - BreakEvenRequest: Configuration for 1D root-finding break-even analysis.
  - BreakEvenResult: Detailed root-finding outcome and bracketing diagnostics.
  - Grid2DRequest: Configuration for 2D parameter grid sweeps.
  - Grid2DPoint: Individual point in a 2D parameter grid.
  - Grid2DResult: Structured 2D contour grid data and matrices.
  - EvaluationBudgetTracker: Budget tracking payload for execution boundaries.

All models adhere to:
  - Strict Pydantic V2 validation.
  - Zero evaluative/subjective recommendation labels.
  - Deterministic evaluation boundaries (max 1,000 evaluations per execution).
  - Exact reconciliation with frozen Phase 7 and Phase 8 contracts.
"""

from typing import List, Dict, Optional, Literal, Any
import math
from pydantic import BaseModel, Field, field_validator, model_validator

from phase7_contracts import FinancialParameters, InvestmentAppraisalResult
from phase8_contracts import OptimizationParameters, OptimizationCandidate

# Authorized sensitivity parameters
VALID_FINANCIAL_PARAMETERS = [
    "fuel_price_usd_per_l",
    "carbon_price_usd_per_tonne",
    "discount_rate",
    "battery_replacement_cost_usd_per_kwh",
]

VALID_PHYSICAL_PARAMETERS = [
    "daily_ghi_kwh_per_m2",
    "auxiliary_energy_demand_kwh",
]

VALID_SENSITIVITY_PARAMETERS = VALID_FINANCIAL_PARAMETERS + VALID_PHYSICAL_PARAMETERS

VALID_BREAK_EVEN_PARAMETERS = [
    "fuel_price_usd_per_l",
    "carbon_price_usd_per_tonne",
    "discount_rate",
]

VALID_SENSITIVITY_METRICS = [
    "net_present_value_usd",
    "internal_rate_of_return_pct",
    "simple_payback_years",
    "discounted_payback_years",
    "lcoe_usd_per_kwh",
    "annual_fuel_displaced_L",
    "annual_co2_displaced_kg",
    "total_initial_capex_usd",
]

# Elasticity status constants
STATUS_ELASTICITY_COMPUTED = "ELASTICITY_COMPUTED"
STATUS_BASELINE_ZERO = "BASELINE_ZERO"
STATUS_PARAMETER_BASELINE_ZERO = "PARAMETER_BASELINE_ZERO"
STATUS_ZERO_PARAMETER_CHANGE = "ZERO_PARAMETER_CHANGE"
STATUS_METRIC_UNAVAILABLE = "METRIC_UNAVAILABLE"

# Break-even status constants
STATUS_ROOT_FOUND = "ROOT_FOUND"
STATUS_NO_ROOT_IN_BOUNDS = "NO_ROOT_IN_BOUNDS"
STATUS_INVALID_BRACKET = "INVALID_BRACKET"
STATUS_OBJECTIVE_UNDEFINED = "OBJECTIVE_UNDEFINED"
STATUS_MAX_EVALUATIONS_EXCEEDED = "MAX_EVALUATIONS_EXCEEDED"
STATUS_BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

# Hard execution limits
MAX_EVALUATIONS_LIMIT = 1000
MAX_EXECUTION_TIME_SECONDS = 1.0


# ==============================================================================
# 1. Parameter Sweep Configuration
# ==============================================================================
class ParameterSweepBounds(BaseModel):
    """
    Configuration for sweeping a single parameter across a bounded discrete range.
    Supports either relative multipliers/deltas or absolute numeric values.
    """
    parameter_name: str = Field(
        ...,
        description="Name of the parameter to vary. Must be one of VALID_SENSITIVITY_PARAMETERS."
    )
    min_value: float = Field(..., description="Lower bound of sweep range (relative multiplier/delta or absolute value).")
    max_value: float = Field(..., description="Upper bound of sweep range (relative multiplier/delta or absolute value).")
    step: float = Field(..., gt=0.0, description="Discrete step increment.")
    is_relative: bool = Field(
        default=False,
        description="If True, values represent relative multipliers or fractional deltas relative to baseline."
    )

    @field_validator("parameter_name")
    @classmethod
    def validate_param_name(cls, v: str) -> str:
        if v not in VALID_SENSITIVITY_PARAMETERS:
            raise ValueError(f"Invalid parameter_name '{v}'. Must be one of: {VALID_SENSITIVITY_PARAMETERS}")
        return v

    @model_validator(mode="after")
    def validate_bounds(self) -> "ParameterSweepBounds":
        if self.min_value > self.max_value:
            raise ValueError(f"min_value ({self.min_value}) cannot exceed max_value ({self.max_value}).")
        if self.step <= 0.0 or not math.isfinite(self.step):
            raise ValueError(f"step must be strictly positive and finite, got {self.step}")
        return self


# ==============================================================================
# 2. Frozen Default Sensitivity Parameter Ranges
# ==============================================================================
FROZEN_DEFAULT_RANGES: Dict[str, ParameterSweepBounds] = {
    "fuel_price_usd_per_l": ParameterSweepBounds(
        parameter_name="fuel_price_usd_per_l",
        min_value=0.50,
        max_value=1.50,
        step=0.05,
        is_relative=True,
    ),
    "carbon_price_usd_per_tonne": ParameterSweepBounds(
        parameter_name="carbon_price_usd_per_tonne",
        min_value=0.0,
        max_value=200.0,
        step=10.0,
        is_relative=False,
    ),
    "discount_rate": ParameterSweepBounds(
        parameter_name="discount_rate",
        min_value=0.04,
        max_value=0.16,
        step=0.01,
        is_relative=False,
    ),
    "battery_replacement_cost_usd_per_kwh": ParameterSweepBounds(
        parameter_name="battery_replacement_cost_usd_per_kwh",
        min_value=-0.40,
        max_value=0.40,
        step=0.10,
        is_relative=True,
    ),
    "daily_ghi_kwh_per_m2": ParameterSweepBounds(
        parameter_name="daily_ghi_kwh_per_m2",
        min_value=-0.25,
        max_value=0.25,
        step=0.05,
        is_relative=True,
    ),
    "auxiliary_energy_demand_kwh": ParameterSweepBounds(
        parameter_name="auxiliary_energy_demand_kwh",
        min_value=-0.25,
        max_value=0.25,
        step=0.05,
        is_relative=True,
    ),
}


# ==============================================================================
# 3. OAT Sensitivity Models
# ==============================================================================
class OATSensitivityPoint(BaseModel):
    """
    Evaluated point along a 1D One-At-A-Time (OAT) parameter variation sweep.
    """
    parameter_name: str = Field(..., description="Name of the parameter being varied.")
    parameter_value: float = Field(..., description="Actual absolute value applied in this evaluation.")
    baseline_parameter_value: float = Field(..., description="Baseline value of the parameter.")
    metric_name: str = Field(..., description="Name of the tracked financial/technical output metric.")
    metric_value: Optional[float] = Field(default=None, description="Evaluated output metric value or None if unavailable.")
    baseline_metric_value: Optional[float] = Field(default=None, description="Baseline output metric value or None.")
    absolute_change: Optional[float] = Field(default=None, description="Delta Y = Y - Y0 or None.")
    relative_change: Optional[float] = Field(default=None, description="(Y - Y0) / Y0 or None.")
    elasticity: Optional[float] = Field(default=None, description="Normalized elasticity ((Y - Y0)/Y0) / ((X - X0)/X0) or None.")
    elasticity_status: str = Field(..., description="Diagnostic status code for elasticity calculation.")
    evaluation_status: str = Field(..., description="'VALID', 'ERROR', 'BUDGET_EXCEEDED', or constraint diagnostic.")


class OATSensitivityResult(BaseModel):
    """
    Structured outcome of a complete 1D OAT sensitivity sweep.
    """
    parameter_name: str = Field(..., description="Name of the swept parameter.")
    baseline_parameter_value: float = Field(..., description="Unperturbed baseline parameter value.")
    metric_name: str = Field(..., description="Evaluated metric name.")
    points: List[OATSensitivityPoint] = Field(default_factory=list, description="Array of evaluated sweep points.")
    total_evaluations: int = Field(..., ge=0, description="Total number of model evaluations consumed by this sweep.")
    diagnostics: str = Field(..., description="Execution diagnostic status.")


# ==============================================================================
# 4. 1D Break-Even Models
# ==============================================================================
class BreakEvenRequest(BaseModel):
    """
    Request specification for 1D deterministic Brent root-finding break-even analysis.
    """
    parameter_name: str = Field(
        ...,
        description="Break-even parameter: 'fuel_price_usd_per_l', 'carbon_price_usd_per_tonne', or 'discount_rate'."
    )
    target_metric: str = Field(
        default="net_present_value_usd",
        description="Target output metric to match (default 'net_present_value_usd')."
    )
    target_value: float = Field(
        default=0.0,
        description="Target numerical value for break-even condition (default 0.0 for NPV=0)."
    )
    lower_bound: float = Field(..., description="Lower search bound for the parameter.")
    upper_bound: float = Field(..., description="Upper search bound for the parameter.")
    tolerance: float = Field(default=1e-6, gt=0.0, description="Numerical convergence tolerance for the root.")
    max_evaluations: int = Field(default=100, ge=2, le=500, description="Maximum evaluations permitted for the root search.")

    @field_validator("parameter_name")
    @classmethod
    def validate_param(cls, v: str) -> str:
        if v not in VALID_BREAK_EVEN_PARAMETERS:
            raise ValueError(f"Invalid break-even parameter '{v}'. Must be one of: {VALID_BREAK_EVEN_PARAMETERS}")
        return v

    @field_validator("target_metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        if v not in VALID_SENSITIVITY_METRICS:
            raise ValueError(f"Invalid target_metric '{v}'. Must be one of: {VALID_SENSITIVITY_METRICS}")
        return v

    @model_validator(mode="after")
    def validate_bounds(self) -> "BreakEvenRequest":
        if self.lower_bound >= self.upper_bound:
            raise ValueError(f"lower_bound ({self.lower_bound}) must be strictly less than upper_bound ({self.upper_bound}).")
        # Validate parameter domain bounds
        if self.parameter_name == "discount_rate":
            if self.lower_bound < 0.0 or self.upper_bound > 0.25:
                raise ValueError("discount_rate bounds must stay within [0.0, 0.25] per Phase 7 financial contracts.")
        elif self.parameter_name in ["fuel_price_usd_per_l", "carbon_price_usd_per_tonne"]:
            if self.lower_bound < 0.0:
                raise ValueError(f"{self.parameter_name} lower_bound cannot be negative.")
        return self


class BreakEvenResult(BaseModel):
    """
    Detailed audit record of a 1D break-even root-finding search.
    """
    parameter_name: str = Field(..., description="Evaluated break-even parameter.")
    target_metric: str = Field(..., description="Target output metric.")
    target_value: float = Field(..., description="Target value matched.")
    lower_bound: float = Field(..., description="Lower search bound.")
    upper_bound: float = Field(..., description="Upper search bound.")
    f_at_lower: Optional[float] = Field(default=None, description="Objective function value at lower bound (f(a) - target).")
    f_at_upper: Optional[float] = Field(default=None, description="Objective function value at upper bound (f(b) - target).")
    break_even_value: Optional[float] = Field(default=None, description="Discovered break-even parameter root or None.")
    evaluations_used: int = Field(..., ge=0, description="Number of evaluations consumed by the root search.")
    status: str = Field(..., description="Diagnostic status: ROOT_FOUND, NO_ROOT_IN_BOUNDS, INVALID_BRACKET, etc.")
    diagnostics: str = Field(..., description="Human/machine readable summary notes.")


# ==============================================================================
# 5. 2D Parameter Grid Models
# ==============================================================================
class Grid2DRequest(BaseModel):
    """
    Request specification for a deterministic 2D parameter grid sweep.
    """
    param_x: ParameterSweepBounds = Field(..., description="Horizontal axis sweep configuration.")
    param_y: ParameterSweepBounds = Field(..., description="Vertical axis sweep configuration.")
    metrics: List[str] = Field(
        default_factory=lambda: ["net_present_value_usd"],
        description="List of metrics to record at each grid node."
    )

    @model_validator(mode="after")
    def validate_distinct_params(self) -> "Grid2DRequest":
        if self.param_x.parameter_name == self.param_y.parameter_name:
            raise ValueError(f"param_x and param_y must be distinct parameters, got '{self.param_x.parameter_name}' for both.")
        if len(self.metrics) == 0:
            raise ValueError("metrics list cannot be empty.")
        for m in self.metrics:
            if m not in VALID_SENSITIVITY_METRICS:
                raise ValueError(f"Invalid metric '{m}'. Must be one of: {VALID_SENSITIVITY_METRICS}")
        return self


class Grid2DPoint(BaseModel):
    """
    Individual evaluated node on a 2D parameter grid.
    """
    x_value: float = Field(..., description="Parameter value along X axis.")
    y_value: float = Field(..., description="Parameter value along Y axis.")
    metrics: Dict[str, Optional[float]] = Field(..., description="Mapping of metric name to numerical value or None.")
    evaluation_status: str = Field(..., description="'VALID', 'ERROR', or constraint status.")


class Grid2DResult(BaseModel):
    """
    Complete 2D parameter grid evaluation output with matrices for contour visualization.
    """
    param_x_name: str = Field(..., description="Name of parameter along X axis.")
    param_y_name: str = Field(..., description="Name of parameter along Y axis.")
    x_values: List[float] = Field(..., description="List of discrete X coordinate values.")
    y_values: List[float] = Field(..., description="List of discrete Y coordinate values.")
    points: List[Grid2DPoint] = Field(..., description="Flat list of all evaluated grid points.")
    matrix: Dict[str, List[List[Optional[float]]]] = Field(
        ...,
        description="Grid matrix organized by metric_name: matrix[metric][y_idx][x_idx]."
    )
    total_evaluations: int = Field(..., ge=0, description="Total number of model evaluations consumed.")
    status: str = Field(..., description="'GRID_COMPLETED', 'BUDGET_EXCEEDED', or 'INVALID_GRID_CONFIGURATION'.")
    diagnostics: str = Field(..., description="Execution summary notes.")
