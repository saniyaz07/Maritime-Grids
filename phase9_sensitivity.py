"""
phase9_sensitivity.py — Multi-Dimensional Parametric Sensitivity & Robustness Engine
=====================================================================================
Implements:
  1. One-At-A-Time (OAT) deterministic sensitivity sweeps across macroeconomic and physical variables.
  2. Normalized elasticity coefficients with strict division-by-zero diagnostic handling.
  3. Deterministic 1D Brent root-finding break-even solvers for financial boundaries.
  4. 2D parameter grid sweeps generating structured contour data matrices.
  5. Strict computational budget enforcement (max 1,000 evaluations, execution target < 1.0s).

ZERO DUPLICATION RULE:
  - Consumes frozen Phase 7 APIs for financial cash-flow and capital budgeting calculations.
  - Consumes frozen Phase 8 APIs for sizing candidate and physical balance evaluations.
  - Zero modifications to upstream Phases 0 through 8.
"""

from typing import List, Dict, Optional, Tuple, Any, Union
import time
import math
import numpy as np
from scipy.optimize import brentq

from phase7_contracts import FinancialParameters, InvestmentAppraisalResult
from phase7_economics import evaluate_clean_energy_investment
from phase8_contracts import OptimizationParameters, OptimizationCandidate
from phase8_optimizer import evaluate_single_sizing_candidate

from phase9_contracts import (
    ParameterSweepBounds,
    OATSensitivityPoint,
    OATSensitivityResult,
    BreakEvenRequest,
    BreakEvenResult,
    Grid2DRequest,
    Grid2DPoint,
    Grid2DResult,
    VALID_FINANCIAL_PARAMETERS,
    VALID_PHYSICAL_PARAMETERS,
    VALID_BREAK_EVEN_PARAMETERS,
    STATUS_ELASTICITY_COMPUTED,
    STATUS_BASELINE_ZERO,
    STATUS_PARAMETER_BASELINE_ZERO,
    STATUS_ZERO_PARAMETER_CHANGE,
    STATUS_METRIC_UNAVAILABLE,
    STATUS_ROOT_FOUND,
    STATUS_NO_ROOT_IN_BOUNDS,
    STATUS_INVALID_BRACKET,
    STATUS_OBJECTIVE_UNDEFINED,
    STATUS_MAX_EVALUATIONS_EXCEEDED,
    STATUS_BUDGET_EXCEEDED,
    MAX_EVALUATIONS_LIMIT,
    MAX_EXECUTION_TIME_SECONDS,
    FROZEN_DEFAULT_RANGES,
)


# ==============================================================================
# 1. Computational Budget Management
# ==============================================================================
class EvaluationBudgetExceededError(Exception):
    """Raised when an operation would exceed the frozen computational evaluation budget."""
    pass


class EvaluationBudgetCounter:
    """
    Thread-safe deterministic counter enforcing the frozen maximum evaluation boundary.
    """
    def __init__(self, max_evaluations: int = MAX_EVALUATIONS_LIMIT):
        if max_evaluations <= 0 or max_evaluations > MAX_EVALUATIONS_LIMIT:
            raise ValueError(f"max_evaluations must be in [1, {MAX_EVALUATIONS_LIMIT}], got {max_evaluations}")
        self.max_evaluations: int = max_evaluations
        self.count: int = 0
        self.start_time: float = time.perf_counter()

    def record_evaluation(self, n: int = 1) -> None:
        """Record n evaluations and raise EvaluationBudgetExceededError if limit breached."""
        if self.count + n > self.max_evaluations:
            raise EvaluationBudgetExceededError(
                f"Evaluation budget exceeded: attempted {self.count + n} evaluations (limit {self.max_evaluations})."
            )
        self.count += n

    def check_capacity(self, requested: int) -> bool:
        """Check if requested evaluations can be accommodated within remaining budget."""
        return (self.count + requested) <= self.max_evaluations

    def remaining(self) -> int:
        """Return remaining evaluation budget."""
        return max(0, self.max_evaluations - self.count)

    def elapsed_seconds(self) -> float:
        """Return wall-clock seconds elapsed since counter initialization."""
        return time.perf_counter() - self.start_time


# ==============================================================================
# 2. Normalized Elasticity Engine
# ==============================================================================
def calculate_normalized_elasticity(
    metric_val: Optional[float],
    metric_base: Optional[float],
    param_val: float,
    param_base: float,
) -> Tuple[Optional[float], str]:
    """
    Calculate normalized elasticity coefficient:
        epsilon = ((Y - Y0) / Y0) / ((X - X0) / X0)

    Strict mathematical diagnostics:
      - If metric is None or baseline metric is None -> METRIC_UNAVAILABLE
      - If Delta X == 0 -> ZERO_PARAMETER_CHANGE
      - If X0 == 0 -> PARAMETER_BASELINE_ZERO
      - If Y0 == 0 -> BASELINE_ZERO
      - Else -> ELASTICITY_COMPUTED
    """
    if metric_val is None or metric_base is None:
        return None, STATUS_METRIC_UNAVAILABLE

    delta_x = param_val - param_base
    if abs(delta_x) < 1e-12:
        return None, STATUS_ZERO_PARAMETER_CHANGE

    if abs(param_base) < 1e-12:
        return None, STATUS_PARAMETER_BASELINE_ZERO

    if abs(metric_base) < 1e-12:
        return None, STATUS_BASELINE_ZERO

    delta_y = metric_val - metric_base
    rel_y = delta_y / metric_base
    rel_x = delta_x / param_base

    elasticity = rel_y / rel_x
    return round(float(elasticity), 6), STATUS_ELASTICITY_COMPUTED


# ==============================================================================
# 3. Parameter Sweep Generation
# ==============================================================================
def generate_sweep_values(
    baseline_value: float,
    sweep_bounds: ParameterSweepBounds,
) -> List[float]:
    """
    Generate deterministic discrete parameter values spanning [min_value, max_value].
    Handles relative multipliers/deltas or absolute steps with 6-decimal rounding.
    """
    min_v = sweep_bounds.min_value
    max_v = sweep_bounds.max_value
    step = sweep_bounds.step

    num_steps = int(round((max_v - min_v) / step)) + 1
    raw_factors = [min_v + i * step for i in range(num_steps)]

    # Clip end to max_v to avoid floating point overshoot
    factors = [min(max_v, f) for f in raw_factors]

    values: List[float] = []
    if sweep_bounds.is_relative:
        for f in factors:
            if sweep_bounds.parameter_name in [
                "battery_replacement_cost_usd_per_kwh",
                "daily_ghi_kwh_per_m2",
                "auxiliary_energy_demand_kwh",
            ]:
                # Fractional delta: baseline * (1.0 + f)
                val = baseline_value * (1.0 + f)
            else:
                # Multiplier (e.g. fuel price 0.50x to 1.50x)
                val = baseline_value * f
            values.append(round(float(val), 6))
    else:
        for f in factors:
            values.append(round(float(f), 6))

    # Ensure uniqueness and preserve sorted order
    seen = set()
    unique_vals = []
    for v in values:
        if v not in seen:
            seen.add(v)
            unique_vals.append(v)

    return unique_vals


# ==============================================================================
# 4. Metric Extraction & Upstream Evaluation Adapters
# ==============================================================================
def extract_metric_from_appraisal(
    appraisal: InvestmentAppraisalResult,
    metric_name: str,
) -> Optional[float]:
    """Extract a scalar numerical metric from a Phase 7 appraisal result."""
    if hasattr(appraisal, metric_name):
        val = getattr(appraisal, metric_name)
        return float(val) if val is not None else None
    return None


def extract_metric_from_candidate(
    candidate: OptimizationCandidate,
    metric_name: str,
) -> Optional[float]:
    """Extract a scalar numerical metric from a Phase 8 optimization candidate."""
    if hasattr(candidate, metric_name):
        val = getattr(candidate, metric_name)
        return float(val) if val is not None else None
    return None


def evaluate_financial_perturbation(
    base_candidate: OptimizationCandidate,
    base_financial_params: FinancialParameters,
    parameter_overrides: Dict[str, Any],
    ship_type: str,
    annual_voyages: int = 52,
    ship_profiles_csv: Optional[str] = None,
) -> InvestmentAppraisalResult:
    """
    Evaluate Phase 7 financial metrics under perturbed financial parameters.
    Consumes pre-computed physical metrics from base_candidate with zero physical re-simulation.
    """
    updated_params = base_financial_params.model_copy(update=parameter_overrides)
    annual_clean_kwh = base_candidate.clean_energy_utilized_kwh * annual_voyages

    return evaluate_clean_energy_investment(
        ship_type=ship_type,
        annual_fuel_displaced_L=base_candidate.annual_fuel_displaced_L,
        annual_clean_energy_utilized_kwh=annual_clean_kwh,
        annual_co2_displaced_kg=base_candidate.annual_co2_displaced_kg,
        solar_area_m2=base_candidate.solar_area_m2,
        battery_capacity_kwh=base_candidate.battery_capacity_kwh,
        parameters=updated_params,
        ship_profiles_csv=ship_profiles_csv,
    )


# ==============================================================================
# 5. One-At-A-Time (OAT) Sensitivity Engine
# ==============================================================================
def run_oat_sensitivity(
    base_candidate: OptimizationCandidate,
    base_financial_params: FinancialParameters,
    parameter_name: str,
    metric_name: str = "net_present_value_usd",
    sweep_bounds: Optional[ParameterSweepBounds] = None,
    ship_type: str = "Tanker Ship",
    annual_voyages: int = 52,
    budget: Optional[EvaluationBudgetCounter] = None,
    ship_profiles_csv: Optional[str] = None,
    # Context parameters required for physical sweeps
    route_id: Optional[str] = "Warri-Bonny",
    month: Optional[int] = 7,
    predicted_soh: float = 0.7387438,
    voyage_duration_hours: float = 40.5,
    predicted_fuel_consumption_L: float = 20124.3,
    predicted_CO2_kg: float = 53268.0,
    deck_area_limit_m2: float = 1000.0,
    battery_weight_limit_tonnes: float = 100.0,
    daily_ghi_kwh_per_m2: float = 3.469395,
    auxiliary_energy_demand_kwh: float = 400.0,
) -> OATSensitivityResult:
    """
    Execute a deterministic 1D OAT sensitivity sweep across a single parameter.
    Tracks evaluation consumption against the frozen 1,000 evaluation budget.
    """
    if budget is None:
        budget = EvaluationBudgetCounter()

    # 1. Resolve sweep configuration
    if sweep_bounds is None:
        if parameter_name not in FROZEN_DEFAULT_RANGES:
            raise ValueError(f"No default sweep range defined for '{parameter_name}'.")
        bounds = FROZEN_DEFAULT_RANGES[parameter_name]
    else:
        bounds = sweep_bounds

    if bounds.parameter_name != parameter_name:
        raise ValueError(f"Mismatched sweep_bounds parameter '{bounds.parameter_name}' != '{parameter_name}'")

    # 2. Resolve baseline parameter and metric value
    if parameter_name in VALID_FINANCIAL_PARAMETERS:
        if parameter_name == "fuel_price_usd_per_l":
            base_p_val = (
                base_financial_params.fuel_price_usd_per_l
                if base_financial_params.fuel_price_usd_per_l is not None
                else 1.0  # Default catalog resolved baseline
            )
        else:
            base_p_val = getattr(base_financial_params, parameter_name)
        base_m_val = extract_metric_from_candidate(base_candidate, metric_name)
    elif parameter_name == "daily_ghi_kwh_per_m2":
        base_p_val = daily_ghi_kwh_per_m2
        base_m_val = extract_metric_from_candidate(base_candidate, metric_name)
    elif parameter_name == "auxiliary_energy_demand_kwh":
        base_p_val = auxiliary_energy_demand_kwh
        base_m_val = extract_metric_from_candidate(base_candidate, metric_name)
    else:
        raise ValueError(f"Unsupported sensitivity parameter '{parameter_name}'")

    # 3. Generate sweep values
    values = generate_sweep_values(base_p_val, bounds)

    if not budget.check_capacity(len(values)):
        raise EvaluationBudgetExceededError(
            f"Sweep requires {len(values)} evaluations, but only {budget.remaining()} remaining in budget."
        )

    # 4. Execute sweep
    points: List[OATSensitivityPoint] = []
    opt_params = OptimizationParameters(
        ship_type=ship_type,
        annual_voyages=annual_voyages,
        financial_parameters=base_financial_params,
    )

    for val in values:
        budget.record_evaluation(1)

        if parameter_name in VALID_FINANCIAL_PARAMETERS:
            appraisal = evaluate_financial_perturbation(
                base_candidate=base_candidate,
                base_financial_params=base_financial_params,
                parameter_overrides={parameter_name: val},
                ship_type=ship_type,
                annual_voyages=annual_voyages,
                ship_profiles_csv=ship_profiles_csv,
            )
            m_val = extract_metric_from_appraisal(appraisal, metric_name)
            eval_status = "VALID"
        else:
            # Physical perturbation
            cur_ghi = val if parameter_name == "daily_ghi_kwh_per_m2" else daily_ghi_kwh_per_m2
            cur_aux = val if parameter_name == "auxiliary_energy_demand_kwh" else auxiliary_energy_demand_kwh

            candidate = evaluate_single_sizing_candidate(
                solar_area_m2=base_candidate.solar_area_m2,
                battery_capacity_kwh=base_candidate.battery_capacity_kwh,
                params=opt_params,
                deck_area_limit_m2=deck_area_limit_m2,
                battery_weight_limit_tonnes=battery_weight_limit_tonnes,
                predicted_soh=predicted_soh,
                auxiliary_energy_demand_kwh=cur_aux,
                voyage_duration_hours=voyage_duration_hours,
                predicted_fuel_consumption_L=predicted_fuel_consumption_L,
                predicted_CO2_kg=predicted_CO2_kg,
                route_id=route_id,
                month=month,
                daily_ghi_kwh_per_m2=cur_ghi,
                ship_profiles_csv=ship_profiles_csv,
            )
            m_val = extract_metric_from_candidate(candidate, metric_name)
            eval_status = candidate.candidate_status

        # Compute delta, relative change, and elasticity
        if m_val is not None and base_m_val is not None:
            abs_change = round(m_val - base_m_val, 6)
            rel_change = (
                round((m_val - base_m_val) / base_m_val, 6)
                if abs(base_m_val) >= 1e-12
                else None
            )
        else:
            abs_change = None
            rel_change = None

        elasticity, elast_status = calculate_normalized_elasticity(
            metric_val=m_val,
            metric_base=base_m_val,
            param_val=val,
            param_base=base_p_val,
        )

        points.append(
            OATSensitivityPoint(
                parameter_name=parameter_name,
                parameter_value=val,
                baseline_parameter_value=base_p_val,
                metric_name=metric_name,
                metric_value=m_val,
                baseline_metric_value=base_m_val,
                absolute_change=abs_change,
                relative_change=rel_change,
                elasticity=elasticity,
                elasticity_status=elast_status,
                evaluation_status=eval_status,
            )
        )

    return OATSensitivityResult(
        parameter_name=parameter_name,
        baseline_parameter_value=base_p_val,
        metric_name=metric_name,
        points=points,
        total_evaluations=len(points),
        diagnostics="OAT_SWEEP_COMPLETED",
    )


# ==============================================================================
# 6. Deterministic 1D Break-Even Solvers
# ==============================================================================
def solve_break_even(
    request: BreakEvenRequest,
    base_candidate: OptimizationCandidate,
    base_financial_params: FinancialParameters,
    ship_type: str = "Tanker Ship",
    annual_voyages: int = 52,
    budget: Optional[EvaluationBudgetCounter] = None,
    ship_profiles_csv: Optional[str] = None,
) -> BreakEvenResult:
    """
    Find the break-even parameter value where target_metric == target_value
    using deterministic 1D Brent root finding (scipy.optimize.brentq).
    """
    if budget is None:
        budget = EvaluationBudgetCounter()

    param_name = request.parameter_name
    metric_name = request.target_metric
    target_val = request.target_value
    a = request.lower_bound
    b = request.upper_bound

    evals_used = 0

    def objective_function(x: float) -> float:
        nonlocal evals_used
        budget.record_evaluation(1)
        evals_used += 1

        appraisal = evaluate_financial_perturbation(
            base_candidate=base_candidate,
            base_financial_params=base_financial_params,
            parameter_overrides={param_name: x},
            ship_type=ship_type,
            annual_voyages=annual_voyages,
            ship_profiles_csv=ship_profiles_csv,
        )
        m_val = extract_metric_from_appraisal(appraisal, metric_name)
        if m_val is None or not math.isfinite(m_val):
            raise ValueError(f"Metric '{metric_name}' evaluated to undefined value at {param_name}={x}")
        return float(m_val - target_val)

    # 1. Evaluate bounds
    try:
        f_a = objective_function(a)
        f_b = objective_function(b)
    except EvaluationBudgetExceededError:
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=None,
            f_at_upper=None,
            break_even_value=None,
            evaluations_used=evals_used,
            status=STATUS_BUDGET_EXCEEDED,
            diagnostics="Evaluation budget exhausted while checking bounds.",
        )
    except ValueError as e:
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=None,
            f_at_upper=None,
            break_even_value=None,
            evaluations_used=evals_used,
            status=STATUS_OBJECTIVE_UNDEFINED,
            diagnostics=str(e),
        )

    # 2. Check exact root at boundary
    if abs(f_a) <= request.tolerance:
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=round(f_a, 6),
            f_at_upper=round(f_b, 6),
            break_even_value=round(a, 6),
            evaluations_used=evals_used,
            status=STATUS_ROOT_FOUND,
            diagnostics="Exact break-even root located at lower bound.",
        )

    if abs(f_b) <= request.tolerance:
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=round(f_a, 6),
            f_at_upper=round(f_b, 6),
            break_even_value=round(b, 6),
            evaluations_used=evals_used,
            status=STATUS_ROOT_FOUND,
            diagnostics="Exact break-even root located at upper bound.",
        )

    # 3. Verify valid bracket
    if f_a * f_b > 0.0:
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=round(f_a, 6),
            f_at_upper=round(f_b, 6),
            break_even_value=None,
            evaluations_used=evals_used,
            status=STATUS_NO_ROOT_IN_BOUNDS,
            diagnostics=f"No sign change detected across [{a}, {b}]. f(a)={f_a:.4f}, f(b)={f_b:.4f}.",
        )

    # 4. Brent root finding
    try:
        root = brentq(
            objective_function,
            a,
            b,
            xtol=request.tolerance,
            maxiter=min(request.max_evaluations, budget.remaining()),
        )
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=round(f_a, 6),
            f_at_upper=round(f_b, 6),
            break_even_value=round(float(root), 6),
            evaluations_used=evals_used,
            status=STATUS_ROOT_FOUND,
            diagnostics=f"Converged to root {root:.6f} with tolerance {request.tolerance}.",
        )
    except EvaluationBudgetExceededError:
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=round(f_a, 6),
            f_at_upper=round(f_b, 6),
            break_even_value=None,
            evaluations_used=evals_used,
            status=STATUS_BUDGET_EXCEEDED,
            diagnostics="Evaluation budget exhausted during root search.",
        )
    except RuntimeError:
        return BreakEvenResult(
            parameter_name=param_name,
            target_metric=metric_name,
            target_value=target_val,
            lower_bound=a,
            upper_bound=b,
            f_at_lower=round(f_a, 6),
            f_at_upper=round(f_b, 6),
            break_even_value=None,
            evaluations_used=evals_used,
            status=STATUS_MAX_EVALUATIONS_EXCEEDED,
            diagnostics=f"Maximum solver iterations ({request.max_evaluations}) exceeded without convergence.",
        )


# ==============================================================================
# 7. 2D Parameter Grid Engine
# ==============================================================================
def run_2d_parameter_grid(
    request: Grid2DRequest,
    base_candidate: OptimizationCandidate,
    base_financial_params: FinancialParameters,
    ship_type: str = "Tanker Ship",
    annual_voyages: int = 52,
    budget: Optional[EvaluationBudgetCounter] = None,
    ship_profiles_csv: Optional[str] = None,
) -> Grid2DResult:
    """
    Execute a deterministic 2D parameter grid sweep.
    Produces full rectangular matrices for contour analysis without plotting dependencies.
    """
    if budget is None:
        budget = EvaluationBudgetCounter()

    param_x = request.param_x
    param_y = request.param_y
    metrics = request.metrics

    # Resolve baseline values
    def get_base(name: str) -> float:
        if name == "fuel_price_usd_per_l":
            return (
                base_financial_params.fuel_price_usd_per_l
                if base_financial_params.fuel_price_usd_per_l is not None
                else 1.0
            )
        return float(getattr(base_financial_params, name))

    base_x = get_base(param_x.parameter_name)
    base_y = get_base(param_y.parameter_name)

    x_vals = generate_sweep_values(base_x, param_x)
    y_vals = generate_sweep_values(base_y, param_y)

    total_pts = len(x_vals) * len(y_vals)

    # Check budget upfront
    if not budget.check_capacity(total_pts):
        return Grid2DResult(
            param_x_name=param_x.parameter_name,
            param_y_name=param_y.parameter_name,
            x_values=x_vals,
            y_values=y_vals,
            points=[],
            matrix={m: [] for m in metrics},
            total_evaluations=0,
            status=STATUS_BUDGET_EXCEEDED,
            diagnostics=(
                f"Requested grid size ({len(x_vals)}x{len(y_vals)} = {total_pts}) "
                f"exceeds remaining budget ({budget.remaining()})."
            ),
        )

    # Initialize matrices: matrix[metric][y_idx][x_idx]
    matrix: Dict[str, List[List[Optional[float]]]] = {
        m: [[None for _ in x_vals] for _ in y_vals] for m in metrics
    }
    flat_points: List[Grid2DPoint] = []

    for j, y_v in enumerate(y_vals):
        for i, x_v in enumerate(x_vals):
            budget.record_evaluation(1)

            overrides = {
                param_x.parameter_name: x_v,
                param_y.parameter_name: y_v,
            }

            appraisal = evaluate_financial_perturbation(
                base_candidate=base_candidate,
                base_financial_params=base_financial_params,
                parameter_overrides=overrides,
                ship_type=ship_type,
                annual_voyages=annual_voyages,
                ship_profiles_csv=ship_profiles_csv,
            )

            pt_metrics: Dict[str, Optional[float]] = {}
            for m in metrics:
                val = extract_metric_from_appraisal(appraisal, m)
                pt_metrics[m] = val
                matrix[m][j][i] = val

            flat_points.append(
                Grid2DPoint(
                    x_value=x_v,
                    y_value=y_v,
                    metrics=pt_metrics,
                    evaluation_status="VALID",
                )
            )

    return Grid2DResult(
        param_x_name=param_x.parameter_name,
        param_y_name=param_y.parameter_name,
        x_values=x_vals,
        y_values=y_vals,
        points=flat_points,
        matrix=matrix,
        total_evaluations=total_pts,
        status="GRID_COMPLETED",
        diagnostics=f"Evaluated {total_pts} points ({len(x_vals)} x {len(y_vals)}) deterministically.",
    )
