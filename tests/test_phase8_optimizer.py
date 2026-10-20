"""
tests/test_phase8_optimizer.py — Test Suite for Phase 8 Parametric Sizing Optimization
=====================================================================================
Comprehensive validation covering:
  1. Parameter validation & constraints (bounds, steps, objectives)
  2. Discrete grid generation & traversal ordering
  3. Hard physical constraints (deck area, battery weight)
  4. Economic budget constraints & feasibility gates
  5. Boundary conditions (zero PV, zero battery, zero PV + zero battery)
  6. Saturation behavior & diminishing returns
  7. All 5 single-objective functions (MAX_NPV, MAX_FUEL, MAX_CO2, MIN_LCOE, MIN_CAPEX)
  8. LCOE=None semantics & diagnostic statuses
  9. Deterministic tie-breaking hierarchy (CAPEX -> Apv -> Ebatt)
  10. Multi-objective Pareto frontier non-domination sorting
  11. Deterministic repeated execution
  12. Real vessel catalog integration (Tanker Ship & Oil Service Boat)
  13. Upstream integration adapters (Single-voyage & Annual schedule)
  14. Cryptographic regression integrity of Phase 2 frozen model hashes
"""

import os
import hashlib
import pytest
from typing import List

from phase3_contracts import FROZEN_MODEL_HASHES
from phase6_contracts import VoyageSimulationRequest
from phase6_gateway import simulate_voyage
from phase7_contracts import FinancialParameters
from phase8_contracts import (
    OptimizationParameters,
    OptimizationCandidate,
    OptimizationResult,
    SMALL_CRAFT_TYPES,
    LARGE_VESSEL_TYPES,
)
from phase8_optimizer import (
    resolve_grid_bounds,
    generate_sizing_lattice,
    evaluate_single_sizing_candidate,
    compare_candidates,
    _pareto_dominates,
    optimize_system_sizing,
    evaluate_single_voyage_sizing,
    evaluate_annual_schedule_sizing,
    EPSILON_RELATIVE,
    EPSILON_ABSOLUTE,
)


# ==============================================================================
# 1. Parameter Validation Tests
# ==============================================================================
def test_parameter_validation_success():
    """Verify valid OptimizationParameters instantiate with defaults."""
    params = OptimizationParameters(ship_type="Oil Service Boat")
    assert params.ship_type == "Oil Service Boat"
    assert params.min_solar_area_m2 == 0.0
    assert params.step_solar_area_m2 == 10.0
    assert params.min_battery_capacity_kwh == 0.0
    assert params.fdeck_max == 0.25
    assert params.fdwt_max == 0.05
    assert params.battery_specific_mass_kg_per_kwh == 8.5
    assert params.objective == "MAX_NPV"
    assert params.annual_voyages == 52


def test_parameter_validation_invalid_bounds():
    """Verify max < min bounds raise ValueError."""
    with pytest.raises(ValueError, match="max_solar_area_m2 .* cannot be less than min_solar_area_m2"):
        OptimizationParameters(
            ship_type="Oil Service Boat",
            min_solar_area_m2=50.0,
            max_solar_area_m2=40.0,
        )

    with pytest.raises(ValueError, match="max_battery_capacity_kwh .* cannot be less than min_battery_capacity_kwh"):
        OptimizationParameters(
            ship_type="Oil Service Boat",
            min_battery_capacity_kwh=500.0,
            max_battery_capacity_kwh=200.0,
        )


def test_parameter_validation_invalid_step_sizes():
    """Verify non-positive step sizes raise ValidationError."""
    with pytest.raises(Exception):
        OptimizationParameters(ship_type="Oil Service Boat", step_solar_area_m2=0.0)

    with pytest.raises(Exception):
        OptimizationParameters(ship_type="Oil Service Boat", step_battery_capacity_kwh=-10.0)


def test_parameter_validation_invalid_objective():
    """Verify unsupported objective string is rejected."""
    with pytest.raises(ValueError, match="Invalid objective 'MAX_PROFIT'"):
        OptimizationParameters(ship_type="Oil Service Boat", objective="MAX_PROFIT")


def test_parameter_validation_invalid_pareto_objectives():
    """Verify invalid Pareto objective combinations are rejected."""
    # Fewer than 2 objectives
    with pytest.raises(ValueError, match="pareto_objectives must contain at least 2 objectives"):
        OptimizationParameters(
            ship_type="Oil Service Boat",
            objective="PARETO_FRONTIER",
            pareto_objectives=["MIN_CAPEX"],
        )

    # Unknown Pareto objective
    with pytest.raises(ValueError, match="Invalid Pareto objective 'MAX_SPEED'"):
        OptimizationParameters(
            ship_type="Oil Service Boat",
            objective="PARETO_FRONTIER",
            pareto_objectives=["MIN_CAPEX", "MAX_SPEED"],
        )


# ==============================================================================
# 2. Discrete Grid Generation & Ordering Tests
# ==============================================================================
def test_grid_lattice_generation():
    """Verify generate_sizing_lattice generates deterministic points without partial drift."""
    pts = generate_sizing_lattice(0.0, 50.0, 10.0)
    assert pts == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]


def test_grid_lattice_no_partial_step():
    """Verify lattice does NOT add a partial step if max does not land on step increment."""
    pts = generate_sizing_lattice(0.0, 45.0, 10.0)
    # 45 is not a multiple of 10, so lattice ends at 40.0
    assert pts == [0.0, 10.0, 20.0, 30.0, 40.0]
    assert 45.0 not in pts


def test_grid_point_count_exceeded():
    """Verify that grids exceeding 10,000 candidates raise ValueError."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=2000.0,
        step_solar_area_m2=1.0,  # 2001 points
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=5000.0,
        step_battery_capacity_kwh=5.0,  # 1001 points -> > 2,000,000 points
    )
    with pytest.raises(ValueError, match="Total grid points .* exceeds maximum allowed"):
        optimize_system_sizing(params)


def test_deterministic_traversal_order():
    """Verify candidates are evaluated in ascending Apv, then ascending Ebatt."""
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
    )
    result = optimize_system_sizing(params)
    assert result.total_candidates_evaluated == 3 * 3  # (0, 10, 20) x (0, 25, 50)
    
    pairs = [(c.solar_area_m2, c.battery_capacity_kwh) for c in result.candidate_results]
    expected_pairs = [
        (0.0, 0.0), (0.0, 25.0), (0.0, 50.0),
        (10.0, 0.0), (10.0, 25.0), (10.0, 50.0),
        (20.0, 0.0), (20.0, 25.0), (20.0, 50.0),
    ]
    assert pairs == expected_pairs


# ==============================================================================
# 3. Hard Physical & Economic Constraint Tests
# ==============================================================================
def test_deck_area_constraint_clipping():
    """Verify candidates exceeding deck area limit are tagged CONSTRAINED_OUT."""
    # OSV deck: 65 * 15.5 * 0.25 = 251.875 m2
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=250.0,
        max_solar_area_m2=260.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=50.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=50.0,
    )
    result = optimize_system_sizing(params)
    c250 = [c for c in result.candidate_results if c.solar_area_m2 == 250.0][0]
    c260 = [c for c in result.candidate_results if c.solar_area_m2 == 260.0][0]

    assert c250.is_physically_valid is True
    assert c250.candidate_status == "VALID"

    assert c260.is_physically_valid is False
    assert "DECK_AREA_EXCEEDED" in c260.constraint_violations
    assert c260.candidate_status == "CONSTRAINED_OUT"


def test_battery_weight_constraint_clipping():
    """Verify candidates exceeding allowable battery DWT fraction are tagged CONSTRAINED_OUT."""
    # Surfer Boat DWT = 35 tonnes. At 5% fdwt_max = 1.75 tonnes = 1750 kg.
    # At 8.5 kg/kWh, max Ebatt = 1750 / 8.5 = 205.88 kWh.
    params = OptimizationParameters(
        ship_type="Surfer Boat",
        min_solar_area_m2=10.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=200.0,
        max_battery_capacity_kwh=225.0,
        step_battery_capacity_kwh=25.0,
    )
    result = optimize_system_sizing(params)
    c200 = [c for c in result.candidate_results if c.battery_capacity_kwh == 200.0][0]
    c225 = [c for c in result.candidate_results if c.battery_capacity_kwh == 225.0][0]

    assert c200.is_physically_valid is True
    assert c225.is_physically_valid is False
    assert "BATTERY_WEIGHT_EXCEEDED" in c225.constraint_violations
    assert c225.candidate_status == "CONSTRAINED_OUT"


def test_budget_constraint_filtering():
    """Verify candidates exceeding max_capex_budget_usd are filtered out of ranking."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=40.0,
        step_solar_area_m2=20.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
        max_capex_budget_usd=60000.0,  # Restricts higher sizing
        objective="MAX_FUEL_DISPLACEMENT",
    )
    result = optimize_system_sizing(params)
    for c in result.candidate_results:
        if c.total_initial_capex_usd > 60000.0:
            assert c.candidate_status == "BUDGET_EXCEEDED"
            assert "BUDGET_EXCEEDED" in c.constraint_violations

    assert result.optimal_candidate is not None
    assert result.optimal_candidate.total_initial_capex_usd <= 60000.0


def test_feasibility_gate_filtering():
    """Verify require_fully_feasible filters out candidates with PARTIAL feasibility."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=40.0,
        step_solar_area_m2=20.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
        require_fully_feasible=True,
    )
    result = optimize_system_sizing(params)
    # Demand is 180 kWh. Sizing of (0, 0) gives 0 clean energy -> PARTIAL
    c0 = [c for c in result.candidate_results if c.solar_area_m2 == 0 and c.battery_capacity_kwh == 0][0]
    assert c0.feasibility_status == "PARTIAL"
    assert c0.candidate_status == "INCOMPLETE_FEASIBILITY"
    assert "INCOMPLETE_AUXILIARY_FEASIBILITY" in c0.constraint_violations


# ==============================================================================
# 4. Sizing Boundary Conditions & Saturation Tests
# ==============================================================================
def test_zero_pv_candidate():
    """Verify evaluation runs cleanly with solar_area_m2 == 0.0."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=0.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=50.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=50.0,
    )
    result = optimize_system_sizing(params)
    cand = result.optimal_candidate
    assert cand is not None
    assert cand.solar_area_m2 == 0.0
    assert cand.clean_energy_available_kwh > 0.0  # From battery


def test_zero_battery_candidate():
    """Verify evaluation runs cleanly with battery_capacity_kwh == 0.0."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=40.0,
        max_solar_area_m2=40.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=0.0,
        step_battery_capacity_kwh=25.0,
    )
    result = optimize_system_sizing(params)
    cand = result.optimal_candidate
    assert cand is not None
    assert cand.battery_capacity_kwh == 0.0
    assert cand.battery_mass_tonnes == 0.0
    assert cand.clean_energy_available_kwh > 0.0  # From solar PV


def test_zero_pv_zero_battery_candidate():
    """Verify evaluation runs cleanly with solar = 0 and battery = 0."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=0.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=0.0,
        step_battery_capacity_kwh=25.0,
    )
    result = optimize_system_sizing(params)
    cand = result.optimal_candidate
    assert cand is not None
    assert cand.solar_area_m2 == 0.0
    assert cand.battery_capacity_kwh == 0.0
    assert cand.clean_energy_available_kwh == 0.0
    assert cand.clean_energy_utilized_kwh == 0.0
    assert cand.annual_fuel_displaced_L == 0.0
    assert cand.annual_co2_displaced_kg == 0.0
    assert cand.lcoe_usd_per_kwh is None
    assert cand.lcoe_status == "LCOE_UNDEFINED_ZERO_ENERGY"


def test_saturation_behavior():
    """Verify that auxiliary load capping produces curtailment and diminishes NPV beyond saturation."""
    # Auxiliary demand for OSV is 180 kWh per voyage.
    # At Ebatt = 500 kWh, usable battery energy is ~343 kWh, which easily covers 100% of demand (180 kWh).
    # Expanding to Ebatt = 600 kWh cannot increase fuel displacement (capped at 180 kWh),
    # but incurs additional battery CAPEX, leading to lower NPV.
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=0.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=400.0,
        max_battery_capacity_kwh=600.0,
        step_battery_capacity_kwh=100.0,
        objective="MAX_FUEL_DISPLACEMENT",
    )
    result = optimize_system_sizing(params)
    c400 = [c for c in result.candidate_results if c.battery_capacity_kwh == 400.0][0]
    c500 = [c for c in result.candidate_results if c.battery_capacity_kwh == 500.0][0]
    c600 = [c for c in result.candidate_results if c.battery_capacity_kwh == 600.0][0]

    # Both saturate auxiliary demand
    assert c500.clean_energy_utilized_kwh == 180.0
    assert c600.clean_energy_utilized_kwh == 180.0
    assert c600.curtailed_energy_kwh > c500.curtailed_energy_kwh
    assert c500.annual_fuel_displaced_L == c600.annual_fuel_displaced_L
    # Additional CAPEX with identical benefits causes NPV to decline
    assert c600.net_present_value_usd < c500.net_present_value_usd


# ==============================================================================
# 5. Objective Function Optimization Tests
# ==============================================================================
def test_objective_max_npv():
    """Verify MAX_NPV selects candidate with maximum Net Present Value."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=40.0,
        step_solar_area_m2=20.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
        objective="MAX_NPV",
    )
    result = optimize_system_sizing(params)
    opt = result.optimal_candidate
    assert opt is not None
    for c in result.candidate_results:
        if c.candidate_status == "VALID":
            assert opt.net_present_value_usd >= c.net_present_value_usd - 1e-6


def test_objective_max_fuel_displacement():
    """Verify MAX_FUEL_DISPLACEMENT selects candidate with highest fuel savings."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=40.0,
        step_solar_area_m2=20.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
        objective="MAX_FUEL_DISPLACEMENT",
    )
    result = optimize_system_sizing(params)
    opt = result.optimal_candidate
    assert opt is not None
    assert opt.solar_area_m2 == 40.0
    assert opt.battery_capacity_kwh == 100.0


def test_objective_max_co2_displacement():
    """Verify MAX_CO2_DISPLACEMENT selects candidate with highest CO2 avoided."""
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=30.0,
        step_solar_area_m2=15.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="MAX_CO2_DISPLACEMENT",
    )
    result = optimize_system_sizing(params)
    opt = result.optimal_candidate
    assert opt is not None
    assert opt.annual_co2_displaced_kg == max(c.annual_co2_displaced_kg for c in result.candidate_results if c.candidate_status == "VALID")


def test_objective_min_capex():
    """Verify MIN_CAPEX selects lowest overnight initial investment."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=40.0,
        step_solar_area_m2=20.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
        objective="MIN_CAPEX",
    )
    result = optimize_system_sizing(params)
    opt = result.optimal_candidate
    assert opt is not None
    assert opt.solar_area_m2 == 0.0
    assert opt.battery_capacity_kwh == 0.0
    assert opt.total_initial_capex_usd == min(c.total_initial_capex_usd for c in result.candidate_results if c.candidate_status == "VALID")


def test_objective_min_lcoe():
    """Verify MIN_LCOE selects lowest valid levelized cost of clean energy."""
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=10.0,
        max_solar_area_m2=30.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=25.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="MIN_LCOE",
    )
    result = optimize_system_sizing(params)
    opt = result.optimal_candidate
    assert opt is not None
    assert opt.lcoe_usd_per_kwh is not None
    for c in result.candidate_results:
        if c.candidate_status == "VALID" and c.lcoe_usd_per_kwh is not None:
            assert opt.lcoe_usd_per_kwh <= c.lcoe_usd_per_kwh + 1e-6


# ==============================================================================
# 6. LCOE=None Semantics & Diagnostic Tests
# ==============================================================================
def test_lcoe_none_handling_min_lcoe():
    """Verify that candidates with LCOE=None cannot be chosen as MIN_LCOE optimum."""
    # When grid includes (0, 0), it produces LCOE=None.
    # MIN_LCOE must choose a candidate with numeric LCOE, not (0, 0).
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="MIN_LCOE",
    )
    result = optimize_system_sizing(params)
    opt = result.optimal_candidate
    assert opt is not None
    assert opt.lcoe_usd_per_kwh is not None
    assert not (opt.solar_area_m2 == 0.0 and opt.battery_capacity_kwh == 0.0)


def test_no_valid_lcoe_candidate_diagnostic():
    """Verify diagnostic when all candidates have LCOE=None."""
    # Grid consisting ONLY of (0, 0)
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=0.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=0.0,
        step_battery_capacity_kwh=25.0,
        objective="MIN_LCOE",
    )
    result = optimize_system_sizing(params)
    assert result.optimal_candidate is None
    assert result.diagnostics == "NO_VALID_LCOE_CANDIDATE"


def test_no_feasible_candidate_diagnostic():
    """Verify diagnostic when all candidates are constrained out."""
    # Budget too low for any system
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=10.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=50.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=50.0,
        max_capex_budget_usd=1000.0,  # OSV base installation alone is $35,000
    )
    result = optimize_system_sizing(params)
    assert result.optimal_candidate is None
    assert result.feasible_candidates_count == 0
    assert result.diagnostics == "NO_FEASIBLE_CANDIDATE_FOUND"


# ==============================================================================
# 7. Deterministic Tie-Breaking Tests
# ==============================================================================
def test_deterministic_tie_breaking_hierarchy():
    """Verify tie-breaking resolves to min CAPEX -> min Apv -> min Ebatt."""
    # When demand is saturated (e.g. at 180 kWh), both (0, 500) and (0, 600)
    # achieve the identical fuel displacement.
    # For MAX_FUEL_DISPLACEMENT, if we consider only saturated points, tie-breaker must select min CAPEX.
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=0.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=400.0,
        max_battery_capacity_kwh=500.0,
        step_battery_capacity_kwh=100.0,
        objective="MAX_FUEL_DISPLACEMENT",
    )
    result = optimize_system_sizing(params)
    # Both 400 and 500 kWh cover 180 kWh auxiliary load (fuel displacement is identical)
    c400 = result.candidate_results[0]
    c500 = result.candidate_results[1]
    assert abs(c400.annual_fuel_displaced_L - c500.annual_fuel_displaced_L) < 1e-6
    # Tie-breaking selects lower CAPEX (400 kWh)
    assert result.optimal_candidate.battery_capacity_kwh == 400.0
    assert len(result.top_candidates) == 2
    assert len(result.tie_candidates_notes) > 0


# ==============================================================================
# 8. Pareto Frontier Non-Domination Tests
# ==============================================================================
def test_pareto_frontier_non_domination():
    """Verify that candidates in the Pareto frontier are strictly non-dominated."""
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"],
    )
    result = optimize_system_sizing(params)
    assert len(result.pareto_frontier) > 0

    # Ensure no frontier candidate is dominated by any other eligible candidate
    for c_frontier in result.pareto_frontier:
        for c_other in result.candidate_results:
            if c_other.candidate_status == "VALID":
                assert not _pareto_dominates(c_other, c_frontier, ["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"])


def test_pareto_frontier_with_lcoe():
    """Verify that valid LCOE candidates dominate LCOE=None candidates in Pareto search."""
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MIN_LCOE", "MAX_FUEL_DISPLACEMENT"],
    )
    result = optimize_system_sizing(params)
    # The (0, 0) candidate has fuel=0 and LCOE=None.
    # Any candidate with fuel > 0 and valid numeric LCOE dominates (0, 0) under these 2 objectives.
    c00 = [c for c in result.pareto_frontier if c.solar_area_m2 == 0 and c.battery_capacity_kwh == 0]
    assert len(c00) == 0  # (0, 0) must be dominated!


# ==============================================================================
# 9. Deterministic Repeated Execution
# ==============================================================================
def test_deterministic_repeated_execution():
    """Verify repeated optimization runs return bitwise identical candidate metrics."""
    params = OptimizationParameters(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="MAX_NPV",
    )
    run1 = optimize_system_sizing(params)
    run2 = optimize_system_sizing(params)

    assert run1.optimal_candidate.solar_area_m2 == run2.optimal_candidate.solar_area_m2
    assert run1.optimal_candidate.battery_capacity_kwh == run2.optimal_candidate.battery_capacity_kwh
    assert run1.optimal_candidate.net_present_value_usd == run2.optimal_candidate.net_present_value_usd
    assert run1.optimal_candidate.total_initial_capex_usd == run2.optimal_candidate.total_initial_capex_usd


# ==============================================================================
# 10. Real Vessel Catalog Integration Tests
# ==============================================================================
def test_real_tanker_ship_integration():
    """Verify optimization on canonical Tanker Ship resolves 14,000 DWT and step=50 kWh."""
    params = OptimizationParameters(
        ship_type="Tanker Ship",
        min_solar_area_m2=0.0,
        max_solar_area_m2=100.0,
        step_solar_area_m2=50.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=200.0,
        step_battery_capacity_kwh=None,  # Must resolve to 50.0
    )
    result = optimize_system_sizing(params)
    assert result.resolved_step_battery_capacity_kwh == 50.0
    assert result.optimal_candidate is not None
    assert result.parameters.ship_type == "Tanker Ship"


def test_real_oil_service_boat_integration():
    """Verify optimization on Oil Service Boat resolves 1,800 DWT and step=50 kWh."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=50.0,
        step_solar_area_m2=25.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=None,  # Must resolve to 50.0
    )
    result = optimize_system_sizing(params)
    assert result.resolved_step_battery_capacity_kwh == 50.0
    assert result.optimal_candidate is not None


# ==============================================================================
# 11. Upstream Adapters Tests
# ==============================================================================
def test_single_voyage_adapter():
    """Verify evaluate_single_voyage_sizing adapter produces expected OptimizationResult."""
    req = VoyageSimulationRequest(
        ship_type="Fishing Trawler",
        route_id="Warri-Bonny",
        month=7,
        speed_knots=10.0,
    )
    sim_res = simulate_voyage(req)
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
    )
    res = evaluate_single_voyage_sizing(params, simulation_result=sim_res)
    assert res.optimal_candidate is not None
    assert res.diagnostics == "OPTIMIZATION_COMPLETED"


def test_annual_schedule_adapter():
    """Verify evaluate_annual_schedule_sizing adapter integrates cleanly."""
    params = OptimizationParameters(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
    )
    res = evaluate_annual_schedule_sizing(params, annual_schedule_request=None)
    assert res.optimal_candidate is not None
    assert res.diagnostics == "OPTIMIZATION_COMPLETED"


# ==============================================================================
# 12. Frozen Model SHA-256 Hash Verification Test
# ==============================================================================
def test_frozen_model_hashes_intact():
    """Verify all 4 frozen Phase 2 machine learning models retain exact SHA-256 baselines."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(base_dir, "models")
    for filename, expected_hash in FROZEN_MODEL_HASHES.items():
        path = os.path.join(models_dir, filename)
        assert os.path.exists(path), f"Frozen model file missing: {path}"
        with open(path, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        assert actual_hash == expected_hash, f"Hash mismatch for {filename}: {actual_hash} != {expected_hash}"


# ==============================================================================
# 13. Targeted Pareto Frontier Ordering & Dominance Tests (Gate 2 & 3 Conformance)
# ==============================================================================
def test_pareto_ordering_min_capex_max_fuel():
    """TEST 1: pareto_objectives = ['MIN_CAPEX', 'MAX_FUEL_DISPLACEMENT'] -> verify frontier ordering follows MIN_CAPEX -> MAX_FUEL."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"],
    )
    res = optimize_system_sizing(params)
    assert len(res.pareto_frontier) > 1
    # Primary sort: CAPEX ascending; Secondary sort: Fuel descending
    capex_vals = [c.total_initial_capex_usd for c in res.pareto_frontier]
    assert capex_vals == sorted(capex_vals)
    for i in range(len(res.pareto_frontier) - 1):
        c_cur = res.pareto_frontier[i]
        c_nxt = res.pareto_frontier[i + 1]
        if abs(c_cur.total_initial_capex_usd - c_nxt.total_initial_capex_usd) < 1e-6:
            assert c_cur.annual_fuel_displaced_L >= c_nxt.annual_fuel_displaced_L - 1e-6


def test_pareto_ordering_max_co2_min_lcoe():
    """TEST 2: pareto_objectives = ['MAX_CO2_DISPLACEMENT', 'MIN_LCOE'] -> verify frontier ordering follows MAX_CO2 -> MIN_LCOE."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=30.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MAX_CO2_DISPLACEMENT", "MIN_LCOE"],
    )
    res = optimize_system_sizing(params)
    assert len(res.pareto_frontier) > 0
    # Primary sort: CO2 descending
    co2_vals = [c.annual_co2_displaced_kg for c in res.pareto_frontier]
    assert co2_vals == sorted(co2_vals, reverse=True)


def test_pareto_ordering_min_lcoe_min_capex():
    """TEST 3: pareto_objectives = ['MIN_LCOE', 'MIN_CAPEX'] -> verify frontier ordering follows MIN_LCOE -> MIN_CAPEX."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MIN_LCOE", "MIN_CAPEX"],
    )
    res = optimize_system_sizing(params)
    assert len(res.pareto_frontier) > 1
    # Candidates with numeric LCOE must come first in ascending order, followed by LCOE=None
    numeric_lcoe = [c for c in res.pareto_frontier if c.lcoe_usd_per_kwh is not None]
    none_lcoe = [c for c in res.pareto_frontier if c.lcoe_usd_per_kwh is None]

    assert len(numeric_lcoe) > 0
    assert len(none_lcoe) > 0
    # Verify frontier order places numeric LCOE before None
    frontier_lcoe = [c.lcoe_usd_per_kwh for c in res.pareto_frontier]
    last_numeric_idx = max(i for i, v in enumerate(frontier_lcoe) if v is not None)
    first_none_idx = min(i for i, v in enumerate(frontier_lcoe) if v is None)
    assert last_numeric_idx < first_none_idx
    # Numeric LCOE must be sorted ascending
    num_vals = [c.lcoe_usd_per_kwh for c in numeric_lcoe]
    assert num_vals == sorted(num_vals)


def test_pareto_ordering_changes_with_configured_objectives():
    """TEST 4: Verify changing pareto_objectives changes frontier ordering for same candidates."""
    base_kwargs = dict(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
    )
    # Ordering A: MIN_CAPEX first
    p_capex = OptimizationParameters(**base_kwargs, pareto_objectives=["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"])
    r_capex = optimize_system_sizing(p_capex)

    # Ordering B: MAX_FUEL first
    p_fuel = OptimizationParameters(**base_kwargs, pareto_objectives=["MAX_FUEL_DISPLACEMENT", "MIN_CAPEX"])
    r_fuel = optimize_system_sizing(p_fuel)

    order_capex = [(c.solar_area_m2, c.battery_capacity_kwh) for c in r_capex.pareto_frontier]
    order_fuel = [(c.solar_area_m2, c.battery_capacity_kwh) for c in r_fuel.pareto_frontier]

    # The candidates on frontier are the same set, but their ordering must be reversed
    assert set(order_capex) == set(order_fuel)
    assert order_capex != order_fuel
    # First candidate in order_capex has lowest CAPEX
    assert r_capex.pareto_frontier[0].total_initial_capex_usd <= r_capex.pareto_frontier[-1].total_initial_capex_usd
    # First candidate in order_fuel has highest fuel displacement
    assert r_fuel.pareto_frontier[0].annual_fuel_displaced_L >= r_fuel.pareto_frontier[-1].annual_fuel_displaced_L


def test_lcoe_absent_does_not_influence_pareto():
    """TEST 5: Verify LCOE does NOT influence Pareto ordering or dominance when MIN_LCOE is absent."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"],
    )
    res = optimize_system_sizing(params)
    # The (0, 0) candidate has LCOE=None, but lowest CAPEX. It MUST be retained in frontier.
    c00 = [c for c in res.pareto_frontier if c.solar_area_m2 == 0 and c.battery_capacity_kwh == 0]
    assert len(c00) == 1
    assert c00[0].lcoe_usd_per_kwh is None


def test_min_lcoe_ordering_numeric_and_none():
    """TEST 6: Verify MIN_LCOE ordering handles numeric and None without mutating candidate values."""
    params = OptimizationParameters(
        ship_type="Oil Service Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MIN_LCOE", "MIN_CAPEX"],
    )
    res = optimize_system_sizing(params)
    # Check that candidate LCOE values are untouched
    for c in res.pareto_frontier:
        if c.clean_energy_utilized_kwh == 0.0:
            assert c.lcoe_usd_per_kwh is None
            assert c.lcoe_status == "LCOE_UNDEFINED_ZERO_ENERGY"
        else:
            assert isinstance(c.lcoe_usd_per_kwh, float)
            assert c.lcoe_usd_per_kwh > 0.0


def test_deterministic_repeated_pareto_execution():
    """TEST 7: Verify deterministic repeated execution produces identical Pareto frontier ordering."""
    params = OptimizationParameters(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=30.0,
        step_solar_area_m2=15.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="PARETO_FRONTIER",
        pareto_objectives=["MAX_CO2_DISPLACEMENT", "MIN_LCOE"],
    )
    run1 = optimize_system_sizing(params)
    run2 = optimize_system_sizing(params)

    assert len(run1.pareto_frontier) == len(run2.pareto_frontier)
    for c1, c2 in zip(run1.pareto_frontier, run2.pareto_frontier):
        assert c1.solar_area_m2 == c2.solar_area_m2
        assert c1.battery_capacity_kwh == c2.battery_capacity_kwh
        assert c1.annual_co2_displaced_kg == c2.annual_co2_displaced_kg
        assert c1.lcoe_usd_per_kwh == c2.lcoe_usd_per_kwh
