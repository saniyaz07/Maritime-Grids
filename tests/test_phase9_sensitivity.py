"""
tests/test_phase9_sensitivity.py — Test Suite for Phase 9 Candidate 1
======================================================================
Comprehensive test suite validating:
  1. Contract validation & boundary enforcement (Pydantic V2)
  2. One-At-A-Time (OAT) sensitivity sweeps across financial & physical variables
  3. Normalized elasticity coefficients with strict edge-case diagnostics
  4. Deterministic 1D Brent root-finding break-even solvers
  5. 2D parameter grid sweeps and contour matrix generation
  6. Evaluation budget enforcement (hard 1,000 limit, counter behavior)
  7. Deterministic repeated execution
  8. Canonical numerical reconciliation with Phase 7 / Phase 8 benchmarks
  9. Error handling, invalid inputs, and edge cases
"""

import pytest
import numpy as np

from phase7_contracts import FinancialParameters
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
    Grid2DResult,
    FROZEN_DEFAULT_RANGES,
    STATUS_ELASTICITY_COMPUTED,
    STATUS_BASELINE_ZERO,
    STATUS_PARAMETER_BASELINE_ZERO,
    STATUS_ZERO_PARAMETER_CHANGE,
    STATUS_METRIC_UNAVAILABLE,
    STATUS_ROOT_FOUND,
    STATUS_NO_ROOT_IN_BOUNDS,
    STATUS_INVALID_BRACKET,
    STATUS_BUDGET_EXCEEDED,
    MAX_EVALUATIONS_LIMIT,
    MAX_EXECUTION_TIME_SECONDS,
)
from phase9_sensitivity import (
    EvaluationBudgetCounter,
    EvaluationBudgetExceededError,
    calculate_normalized_elasticity,
    generate_sweep_values,
    run_oat_sensitivity,
    solve_break_even,
    run_2d_parameter_grid,
    evaluate_financial_perturbation,
)


# ==============================================================================
# Fixtures: Canonical Tanker Candidate & Baseline Financial Parameters
# ==============================================================================
@pytest.fixture
def baseline_financial_params():
    return FinancialParameters(
        analysis_horizon_years=15,
        discount_rate=0.08,
        fuel_price_usd_per_l=1.0,
        fuel_escalation_rate=0.02,
        solar_capex_usd_per_m2=250.0,
        battery_capex_usd_per_kwh=450.0,
        inverter_bop_capex_usd=15000.0,
        installation_retrofit_capex_usd=20000.0,
        opex_pct_of_capex=0.015,
        battery_replacement_cost_usd_per_kwh=300.0,
        battery_replacement_interval_years=8,
        salvage_value_pct=0.05,
        carbon_price_usd_per_tonne=0.0,
    )


@pytest.fixture
def canonical_tanker_candidate(baseline_financial_params):
    opt_params = OptimizationParameters(
        ship_type="Tanker Ship",
        annual_voyages=52,
        financial_parameters=baseline_financial_params,
    )
    return evaluate_single_sizing_candidate(
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
        params=opt_params,
        deck_area_limit_m2=1000.0,
        battery_weight_limit_tonnes=100.0,
        predicted_soh=0.7387438,
        auxiliary_energy_demand_kwh=400.0,
        voyage_duration_hours=40.5,
        predicted_fuel_consumption_L=20124.3,
        predicted_CO2_kg=53268.0,
        route_id="Warri-Bonny",
        month=7,
        daily_ghi_kwh_per_m2=3.469395,
    )


# ==============================================================================
# 1. Contract Validation Tests
# ==============================================================================
def test_parameter_sweep_bounds_valid():
    bounds = ParameterSweepBounds(
        parameter_name="fuel_price_usd_per_l",
        min_value=0.5,
        max_value=1.5,
        step=0.05,
        is_relative=True,
    )
    assert bounds.parameter_name == "fuel_price_usd_per_l"
    assert bounds.min_value == 0.5
    assert bounds.max_value == 1.5
    assert bounds.step == 0.05


def test_parameter_sweep_bounds_invalid_name():
    with pytest.raises(ValueError, match="Invalid parameter_name"):
        ParameterSweepBounds(
            parameter_name="invalid_parameter_foo",
            min_value=0.0,
            max_value=1.0,
            step=0.1,
        )


def test_parameter_sweep_bounds_reversed():
    with pytest.raises(ValueError, match="cannot exceed max_value"):
        ParameterSweepBounds(
            parameter_name="discount_rate",
            min_value=0.20,
            max_value=0.05,
            step=0.01,
        )


def test_parameter_sweep_bounds_zero_or_negative_step():
    with pytest.raises(ValueError, match="Input should be greater than 0"):
        ParameterSweepBounds(
            parameter_name="discount_rate",
            min_value=0.04,
            max_value=0.16,
            step=0.0,
        )


def test_break_even_request_valid():
    req = BreakEvenRequest(
        parameter_name="fuel_price_usd_per_l",
        target_metric="net_present_value_usd",
        target_value=0.0,
        lower_bound=0.5,
        upper_bound=5.0,
    )
    assert req.parameter_name == "fuel_price_usd_per_l"
    assert req.target_value == 0.0


def test_break_even_request_invalid_parameter():
    with pytest.raises(ValueError, match="Invalid break-even parameter"):
        BreakEvenRequest(
            parameter_name="daily_ghi_kwh_per_m2",  # GHI is physical, not authorized for 1D financial break-even
            lower_bound=1.0,
            upper_bound=5.0,
        )


def test_break_even_request_reversed_bounds():
    with pytest.raises(ValueError, match="lower_bound .* must be strictly less than upper_bound"):
        BreakEvenRequest(
            parameter_name="discount_rate",
            lower_bound=0.15,
            upper_bound=0.05,
        )


def test_grid_2d_request_identical_parameters():
    bounds = FROZEN_DEFAULT_RANGES["fuel_price_usd_per_l"]
    with pytest.raises(ValueError, match="param_x and param_y must be distinct"):
        Grid2DRequest(
            param_x=bounds,
            param_y=bounds,
        )


# ==============================================================================
# 2. Normalized Elasticity Tests
# ==============================================================================
def test_elasticity_normal_calculation():
    # X0 = 100, X = 110 (10% increase)
    # Y0 = 200, Y = 240 (20% increase)
    # Elasticity = 0.20 / 0.10 = 2.0
    elast, status = calculate_normalized_elasticity(
        metric_val=240.0,
        metric_base=200.0,
        param_val=110.0,
        param_base=100.0,
    )
    assert status == STATUS_ELASTICITY_COMPUTED
    assert elast == pytest.approx(2.0, abs=1e-5)


def test_elasticity_zero_parameter_change():
    elast, status = calculate_normalized_elasticity(
        metric_val=200.0,
        metric_base=200.0,
        param_val=100.0,
        param_base=100.0,
    )
    assert status == STATUS_ZERO_PARAMETER_CHANGE
    assert elast is None


def test_elasticity_parameter_baseline_zero():
    elast, status = calculate_normalized_elasticity(
        metric_val=250.0,
        metric_base=200.0,
        param_val=50.0,
        param_base=0.0,
    )
    assert status == STATUS_PARAMETER_BASELINE_ZERO
    assert elast is None


def test_elasticity_metric_baseline_zero():
    elast, status = calculate_normalized_elasticity(
        metric_val=100.0,
        metric_base=0.0,
        param_val=120.0,
        param_base=100.0,
    )
    assert status == STATUS_BASELINE_ZERO
    assert elast is None


def test_elasticity_metric_unavailable():
    elast, status = calculate_normalized_elasticity(
        metric_val=None,
        metric_base=200.0,
        param_val=110.0,
        param_base=100.0,
    )
    assert status == STATUS_METRIC_UNAVAILABLE
    assert elast is None


# ==============================================================================
# 3. Parameter Sweep Generation Tests
# ==============================================================================
def test_generate_sweep_values_relative_multiplier():
    bounds = ParameterSweepBounds(
        parameter_name="fuel_price_usd_per_l",
        min_value=0.50,
        max_value=1.50,
        step=0.25,
        is_relative=True,
    )
    vals = generate_sweep_values(baseline_value=2.0, sweep_bounds=bounds)
    # Expected: 2.0 * [0.5, 0.75, 1.0, 1.25, 1.50] = [1.0, 1.5, 2.0, 2.5, 3.0]
    assert vals == [1.0, 1.5, 2.0, 2.5, 3.0]


def test_generate_sweep_values_relative_fractional_delta():
    bounds = ParameterSweepBounds(
        parameter_name="battery_replacement_cost_usd_per_kwh",
        min_value=-0.20,
        max_value=0.20,
        step=0.10,
        is_relative=True,
    )
    vals = generate_sweep_values(baseline_value=300.0, sweep_bounds=bounds)
    # Expected: 300 * (1 + [-0.2, -0.1, 0.0, 0.1, 0.2]) = [240.0, 270.0, 300.0, 330.0, 360.0]
    assert vals == [240.0, 270.0, 300.0, 330.0, 360.0]


def test_generate_sweep_values_absolute():
    bounds = ParameterSweepBounds(
        parameter_name="discount_rate",
        min_value=0.04,
        max_value=0.08,
        step=0.02,
        is_relative=False,
    )
    vals = generate_sweep_values(baseline_value=0.08, sweep_bounds=bounds)
    assert vals == [0.04, 0.06, 0.08]


# ==============================================================================
# 4. Evaluation Budget Counter Tests
# ==============================================================================
def test_budget_counter_normal_and_exhaustion():
    counter = EvaluationBudgetCounter(max_evaluations=5)
    assert counter.remaining() == 5
    counter.record_evaluation(3)
    assert counter.remaining() == 2
    assert counter.check_capacity(2) is True
    assert counter.check_capacity(3) is False

    counter.record_evaluation(2)
    assert counter.remaining() == 0

    with pytest.raises(EvaluationBudgetExceededError):
        counter.record_evaluation(1)


def test_budget_counter_invalid_initialization():
    with pytest.raises(ValueError):
        EvaluationBudgetCounter(max_evaluations=0)
    with pytest.raises(ValueError):
        EvaluationBudgetCounter(max_evaluations=MAX_EVALUATIONS_LIMIT + 1)


# ==============================================================================
# 5. One-At-A-Time (OAT) Sensitivity Tests
# ==============================================================================
def test_oat_sensitivity_fuel_price(canonical_tanker_candidate, baseline_financial_params):
    res = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="fuel_price_usd_per_l",
        metric_name="net_present_value_usd",
        ship_type="Tanker Ship",
    )
    assert res.parameter_name == "fuel_price_usd_per_l"
    assert res.diagnostics == "OAT_SWEEP_COMPLETED"
    assert len(res.points) == 21  # 0.50 to 1.50 with step 0.05 is 21 points
    assert res.total_evaluations == 21

    # As fuel price increases, NPV must strictly increase (monotonicity)
    npvs = [p.metric_value for p in res.points]
    assert all(npvs[i] <= npvs[i + 1] for i in range(len(npvs) - 1))

    # Baseline point (1.0 USD/L) must have zero parameter delta
    base_pt = [p for p in res.points if abs(p.parameter_value - 1.0) < 1e-5][0]
    assert base_pt.elasticity_status == STATUS_ZERO_PARAMETER_CHANGE


def test_oat_sensitivity_discount_rate(canonical_tanker_candidate, baseline_financial_params):
    res = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="discount_rate",
        metric_name="net_present_value_usd",
        ship_type="Tanker Ship",
    )
    assert res.parameter_name == "discount_rate"
    assert len(res.points) == 13  # 0.04 to 0.16 with step 0.01 is 13 points
    assert res.diagnostics == "OAT_SWEEP_COMPLETED"


def test_oat_sensitivity_carbon_price(canonical_tanker_candidate, baseline_financial_params):
    res = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="carbon_price_usd_per_tonne",
        metric_name="net_present_value_usd",
        ship_type="Tanker Ship",
    )
    assert res.parameter_name == "carbon_price_usd_per_tonne"
    assert len(res.points) == 21  # 0 to 200 with step 10 is 21 points


def test_oat_sensitivity_physical_ghi(canonical_tanker_candidate, baseline_financial_params):
    res = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="daily_ghi_kwh_per_m2",
        metric_name="annual_fuel_displaced_L",
        ship_type="Tanker Ship",
    )
    assert res.parameter_name == "daily_ghi_kwh_per_m2"
    assert len(res.points) == 11  # -25% to +25% with step 5% is 11 points
    # Fuel displacement increases with higher GHI
    fuels = [p.metric_value for p in res.points]
    assert all(fuels[i] <= fuels[i + 1] for i in range(len(fuels) - 1))


def test_oat_sensitivity_budget_exhaustion(canonical_tanker_candidate, baseline_financial_params):
    small_budget = EvaluationBudgetCounter(max_evaluations=5)
    with pytest.raises(EvaluationBudgetExceededError):
        run_oat_sensitivity(
            base_candidate=canonical_tanker_candidate,
            base_financial_params=baseline_financial_params,
            parameter_name="fuel_price_usd_per_l",
            budget=small_budget,
        )


# ==============================================================================
# 6. Deterministic 1D Break-Even Tests
# ==============================================================================
def test_break_even_fuel_price_root_found(canonical_tanker_candidate, baseline_financial_params):
    # At baseline fuel price $1.0/L, NPV is negative (-173k).
    # If fuel price is high enough, NPV will become positive.
    req = BreakEvenRequest(
        parameter_name="fuel_price_usd_per_l",
        target_metric="net_present_value_usd",
        target_value=0.0,
        lower_bound=0.5,
        upper_bound=10.0,
        tolerance=1e-5,
    )
    result = solve_break_even(
        request=req,
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        ship_type="Tanker Ship",
    )
    assert result.status == STATUS_ROOT_FOUND
    assert result.break_even_value is not None
    assert 0.5 < result.break_even_value < 10.0

    # Verify that at the root, NPV is approximately 0
    appraisal = evaluate_financial_perturbation(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_overrides={"fuel_price_usd_per_l": result.break_even_value},
        ship_type="Tanker Ship",
    )
    assert appraisal.net_present_value_usd == pytest.approx(0.0, abs=1.0)


def test_break_even_no_root_in_bounds(canonical_tanker_candidate, baseline_financial_params):
    # Over [0.5, 1.5], NPV remains negative for this candidate
    req = BreakEvenRequest(
        parameter_name="fuel_price_usd_per_l",
        target_metric="net_present_value_usd",
        target_value=0.0,
        lower_bound=0.5,
        upper_bound=1.5,
    )
    result = solve_break_even(
        request=req,
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        ship_type="Tanker Ship",
    )
    assert result.status == STATUS_NO_ROOT_IN_BOUNDS
    assert result.break_even_value is None
    assert result.f_at_lower < 0.0
    assert result.f_at_upper < 0.0


def test_break_even_root_at_boundary(canonical_tanker_candidate, baseline_financial_params):
    # Find root first
    req1 = BreakEvenRequest(
        parameter_name="fuel_price_usd_per_l",
        lower_bound=0.5,
        upper_bound=10.0,
    )
    res1 = solve_break_even(req1, canonical_tanker_candidate, baseline_financial_params)
    assert res1.status == STATUS_ROOT_FOUND
    root_val = res1.break_even_value

    # Now request search where lower_bound == root_val
    req2 = BreakEvenRequest(
        parameter_name="fuel_price_usd_per_l",
        lower_bound=root_val,
        upper_bound=root_val + 2.0,
    )
    res2 = solve_break_even(req2, canonical_tanker_candidate, baseline_financial_params)
    assert res2.status == STATUS_ROOT_FOUND
    assert res2.break_even_value == pytest.approx(root_val, abs=1e-5)


def test_break_even_budget_exhaustion(canonical_tanker_candidate, baseline_financial_params):
    small_budget = EvaluationBudgetCounter(max_evaluations=1)
    req = BreakEvenRequest(
        parameter_name="fuel_price_usd_per_l",
        lower_bound=0.5,
        upper_bound=10.0,
    )
    res = solve_break_even(
        request=req,
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        budget=small_budget,
    )
    assert res.status == STATUS_BUDGET_EXCEEDED


# ==============================================================================
# 7. 2D Parameter Grid Tests
# ==============================================================================
def test_run_2d_parameter_grid_fuel_vs_carbon(canonical_tanker_candidate, baseline_financial_params):
    req = Grid2DRequest(
        param_x=ParameterSweepBounds(
            parameter_name="fuel_price_usd_per_l",
            min_value=1.0,
            max_value=2.0,
            step=0.5,
            is_relative=False,
        ),
        param_y=ParameterSweepBounds(
            parameter_name="carbon_price_usd_per_tonne",
            min_value=0.0,
            max_value=100.0,
            step=50.0,
            is_relative=False,
        ),
        metrics=["net_present_value_usd", "lcoe_usd_per_kwh"],
    )
    # X steps: [1.0, 1.5, 2.0] (3)
    # Y steps: [0.0, 50.0, 100.0] (3) -> Total 9 points
    res = run_2d_parameter_grid(
        request=req,
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
    )
    assert res.status == "GRID_COMPLETED"
    assert res.total_evaluations == 9
    assert len(res.points) == 9
    assert len(res.x_values) == 3
    assert len(res.y_values) == 3

    # Check matrix shape: matrix[metric][y_idx][x_idx]
    mat_npv = res.matrix["net_present_value_usd"]
    assert len(mat_npv) == 3  # rows = y
    assert len(mat_npv[0]) == 3  # cols = x

    # Top right node (fuel=2.0, carbon=100.0) must have highest NPV
    assert mat_npv[2][2] > mat_npv[0][0]


def test_run_2d_parameter_grid_budget_exceeded(canonical_tanker_candidate, baseline_financial_params):
    # Request a grid exceeding remaining budget
    small_budget = EvaluationBudgetCounter(max_evaluations=10)
    req = Grid2DRequest(
        param_x=ParameterSweepBounds(
            parameter_name="fuel_price_usd_per_l",
            min_value=0.5,
            max_value=1.5,
            step=0.1,  # 11 points
            is_relative=False,
        ),
        param_y=ParameterSweepBounds(
            parameter_name="carbon_price_usd_per_tonne",
            min_value=0.0,
            max_value=100.0,
            step=20.0,  # 6 points -> 66 total
            is_relative=False,
        ),
    )
    res = run_2d_parameter_grid(
        request=req,
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        budget=small_budget,
    )
    assert res.status == STATUS_BUDGET_EXCEEDED
    assert res.total_evaluations == 0


# ==============================================================================
# 8. Determinism & Benchmark Numerical Reconciliation Tests
# ==============================================================================
def test_deterministic_repeated_execution(canonical_tanker_candidate, baseline_financial_params):
    res1 = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="fuel_price_usd_per_l",
        metric_name="net_present_value_usd",
    )
    res2 = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="fuel_price_usd_per_l",
        metric_name="net_present_value_usd",
    )
    assert res1.total_evaluations == res2.total_evaluations
    for p1, p2 in zip(res1.points, res2.points):
        assert p1.parameter_value == p2.parameter_value
        assert p1.metric_value == p2.metric_value
        assert p1.elasticity == p2.elasticity


def test_canonical_tanker_numerical_reconciliation(canonical_tanker_candidate, baseline_financial_params):
    """
    Verify that the baseline evaluation point in Phase 9 sensitivity reconciles
    with the frozen Phase 8 candidate metrics to <= 1e-6.
    """
    # Evaluate at baseline unperturbed parameters
    appraisal = evaluate_financial_perturbation(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_overrides={},
        ship_type="Tanker Ship",
    )
    # Check NPV
    diff_npv = abs(appraisal.net_present_value_usd - canonical_tanker_candidate.net_present_value_usd)
    assert diff_npv <= 1e-6, f"NPV mismatch: {diff_npv}"

    # Check LCOE
    diff_lcoe = abs(appraisal.lcoe_usd_per_kwh - canonical_tanker_candidate.lcoe_usd_per_kwh)
    assert diff_lcoe <= 1e-6, f"LCOE mismatch: {diff_lcoe}"

    # Check IRR
    assert appraisal.irr_status == canonical_tanker_candidate.irr_status
    if appraisal.internal_rate_of_return_pct is not None:
        diff_irr = abs(appraisal.internal_rate_of_return_pct - canonical_tanker_candidate.internal_rate_of_return_pct)
        assert diff_irr <= 1e-6, f"IRR mismatch: {diff_irr}"


def test_performance_latency_under_one_second(canonical_tanker_candidate, baseline_financial_params):
    """Verify that a full default OAT sweep executes well under the 1.0 second limit."""
    budget = EvaluationBudgetCounter(max_evaluations=1000)
    res = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="fuel_price_usd_per_l",
        budget=budget,
    )
    elapsed = budget.elapsed_seconds()
    assert elapsed < MAX_EXECUTION_TIME_SECONDS, f"Execution took {elapsed:.4f}s >= {MAX_EXECUTION_TIME_SECONDS}s"
    assert res.total_evaluations == 21


# ==============================================================================
# 9. Additional Edge-Case & Robustness Tests
# ==============================================================================
def test_elasticity_negative_values():
    # Test elasticity with negative baseline metrics (e.g. negative NPV)
    # X0 = 1.0, X = 1.2 (+20%)
    # Y0 = -100, Y = -80 (improvement of +20)
    # delta Y / Y0 = +20 / -100 = -0.20
    # delta X / X0 = +0.20 / 1.0 = +0.20
    # Elasticity = -0.20 / +0.20 = -1.0
    elast, status = calculate_normalized_elasticity(
        metric_val=-80.0,
        metric_base=-100.0,
        param_val=1.2,
        param_base=1.0,
    )
    assert status == STATUS_ELASTICITY_COMPUTED
    assert elast == pytest.approx(-1.0, abs=1e-5)


def test_oat_battery_replacement_inflation(canonical_tanker_candidate, baseline_financial_params):
    res = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="battery_replacement_cost_usd_per_kwh",
        metric_name="net_present_value_usd",
    )
    assert res.parameter_name == "battery_replacement_cost_usd_per_kwh"
    assert len(res.points) == 9  # -40% to +40% with step 10% is 9 points
    # Higher replacement cost reduces NPV
    npvs = [p.metric_value for p in res.points]
    assert all(npvs[i] >= npvs[i + 1] for i in range(len(npvs) - 1))


def test_oat_auxiliary_load_variation(canonical_tanker_candidate, baseline_financial_params):
    res = run_oat_sensitivity(
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
        parameter_name="auxiliary_energy_demand_kwh",
        metric_name="annual_fuel_displaced_L",
    )
    assert res.parameter_name == "auxiliary_energy_demand_kwh"
    assert len(res.points) == 11  # -25% to +25% with step 5% is 11 points


def test_oat_sensitivity_all_negative_cash_flows_irr_none():
    # Candidate with zero displacement and positive OPEX/CAPEX, zero salvage
    zero_candidate = OptimizationCandidate(
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        battery_mass_tonnes=0.0,
        deck_area_limit_m2=1000.0,
        battery_weight_limit_tonnes=100.0,
        is_physically_valid=True,
        constraint_violations=[],
        candidate_status="VALID",
        clean_energy_available_kwh=0.0,
        clean_energy_utilized_kwh=0.0,
        curtailed_energy_kwh=0.0,
        feasibility_status="PARTIAL",
        annual_fuel_displaced_L=0.0,
        annual_co2_displaced_kg=0.0,
        total_initial_capex_usd=35000.0,
        net_present_value_usd=-39485.0,
        internal_rate_of_return_pct=None,
        irr_status="IRR_NOT_APPLICABLE_ALL_NEGATIVE",
        simple_payback_years=None,
        discounted_payback_years=None,
        lcoe_usd_per_kwh=None,
        lcoe_status="LCOE_UNDEFINED_ZERO_ENERGY",
        objective_value=-39485.0,
    )
    p = FinancialParameters(
        inverter_bop_capex_usd=15000.0,
        installation_retrofit_capex_usd=20000.0,
        opex_pct_of_capex=0.015,
        salvage_value_pct=0.0,
        fuel_price_usd_per_l=1.0,
    )
    res = run_oat_sensitivity(
        base_candidate=zero_candidate,
        base_financial_params=p,
        parameter_name="fuel_price_usd_per_l",
        metric_name="internal_rate_of_return_pct",
        sweep_bounds=ParameterSweepBounds(
            parameter_name="fuel_price_usd_per_l",
            min_value=0.5,
            max_value=1.5,
            step=0.5,
            is_relative=True,
        ),
    )
    for pt in res.points:
        assert pt.metric_value is None
        assert pt.elasticity_status == STATUS_METRIC_UNAVAILABLE


def test_break_even_invalid_discount_rate_bounds():
    with pytest.raises(ValueError, match="discount_rate bounds must stay within"):
        BreakEvenRequest(
            parameter_name="discount_rate",
            lower_bound=0.10,
            upper_bound=0.35,  # Exceeds 0.25 limit
        )


def test_2d_parameter_grid_fuel_vs_discount(canonical_tanker_candidate, baseline_financial_params):
    req = Grid2DRequest(
        param_x=ParameterSweepBounds(
            parameter_name="fuel_price_usd_per_l",
            min_value=1.0,
            max_value=1.5,
            step=0.25,
            is_relative=False,
        ),
        param_y=ParameterSweepBounds(
            parameter_name="discount_rate",
            min_value=0.06,
            max_value=0.10,
            step=0.02,
            is_relative=False,
        ),
        metrics=["net_present_value_usd"],
    )
    res = run_2d_parameter_grid(
        request=req,
        base_candidate=canonical_tanker_candidate,
        base_financial_params=baseline_financial_params,
    )
    assert res.status == "GRID_COMPLETED"
    assert res.total_evaluations == 9
    assert len(res.points) == 9

