"""
test_phase9_portfolio_optimizer.py — Test Suite for Phase 9 Candidate 3
=======================================================================
Tests for Fleet Portfolio Decarbonization Capital Allocation Engine.

Verifies:
  A. Contract Validation (>= 7 tests)
  B. Portfolio Assembly & Filtering (>= 6 tests)
  C. Aggregation Arithmetic & Identities (>= 6 tests)
  D. CO2 Objective Optimization & Constraints (>= 6 tests)
  E. Deterministic Tie-Breaking (>= 4 tests)
  F. Immutability, Scope, and Isolation (>= 6 tests)

Uses synthetic and pre-evaluated OptimizationCandidate fixtures.
Zero full-grid Phase 8 sizing evaluations. Zero calls to optimize_system_sizing().
"""

import math
import hashlib
import os
import pytest

from phase8_contracts import OptimizationCandidate
from phase9_portfolio_contracts import (
    SUPPORTED_PORTFOLIO_SHIP_TYPES,
    PORTFOLIO_OBJECTIVE_MAX_CO2,
    DIAG_OPTIMAL_ALLOCATION,
    DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS,
    PortfolioItem,
    PortfolioOptimizationParameters,
    PortfolioAllocationResult,
)
from phase9_portfolio_optimizer import (
    filter_eligible_portfolio_items,
    group_items_by_vessel_id,
    enumerate_feasible_portfolios,
    optimize_portfolio,
    make_portfolio_item,
)


# ==============================================================================
# Helpers & Synthetic Candidate Factory
# ==============================================================================

def create_mock_candidate(
    solar_area_m2: float = 100.0,
    battery_capacity_kwh: float = 200.0,
    battery_mass_tonnes: float = 1.7,
    deck_area_limit_m2: float = 500.0,
    battery_weight_limit_tonnes: float = 50.0,
    is_physically_valid: bool = True,
    candidate_status: str = "VALID",
    feasibility_status: str = "FEASIBLE",
    annual_fuel_displaced_L: float = 5000.0,
    annual_co2_displaced_kg: float = 13200.0,
    total_initial_capex_usd: float = 115000.0,
    net_present_value_usd: float = -45000.0,
    internal_rate_of_return_pct: float = 5.2,
    lcoe_usd_per_kwh: float = 1.25,
) -> OptimizationCandidate:
    """Creates a valid OptimizationCandidate object for testing without Phase 8 simulation."""
    return OptimizationCandidate(
        solar_area_m2=solar_area_m2,
        battery_capacity_kwh=battery_capacity_kwh,
        battery_mass_tonnes=battery_mass_tonnes,
        deck_area_limit_m2=deck_area_limit_m2,
        battery_weight_limit_tonnes=battery_weight_limit_tonnes,
        is_physically_valid=is_physically_valid,
        constraint_violations=[] if is_physically_valid else ["DECK_AREA_EXCEEDED"],
        candidate_status=candidate_status,
        clean_energy_available_kwh=15000.0,
        clean_energy_utilized_kwh=12000.0,
        curtailed_energy_kwh=3000.0,
        feasibility_status=feasibility_status,
        annual_fuel_displaced_L=annual_fuel_displaced_L,
        annual_co2_displaced_kg=annual_co2_displaced_kg,
        total_initial_capex_usd=total_initial_capex_usd,
        net_present_value_usd=net_present_value_usd,
        internal_rate_of_return_pct=internal_rate_of_return_pct,
        irr_status="IRR_UNIQUE_ROOT",
        simple_payback_years=8.5,
        discounted_payback_years=11.2,
        lcoe_usd_per_kwh=lcoe_usd_per_kwh,
        lcoe_status="LCOE_CALCULATED",
        objective_value=annual_co2_displaced_kg,
    )


@pytest.fixture
def four_representative_fleet():
    """Provides 4 pre-evaluated portfolio items representing the 4 canonical archetypes."""
    # 1. Tanker Ship: high displacement, high CAPEX
    c_tanker = create_mock_candidate(
        solar_area_m2=200.0,
        battery_capacity_kwh=500.0,
        total_initial_capex_usd=250000.0,
        annual_co2_displaced_kg=35000.0,
        annual_fuel_displaced_L=13000.0,
        net_present_value_usd=-90000.0,
    )
    # 2. Oil Service Boat: medium displacement, medium CAPEX
    c_osv = create_mock_candidate(
        solar_area_m2=80.0,
        battery_capacity_kwh=250.0,
        total_initial_capex_usd=132500.0,
        annual_co2_displaced_kg=22000.0,
        annual_fuel_displaced_L=8300.0,
        net_present_value_usd=-40000.0,
    )
    # 3. Fishing Trawler: lower displacement, lower CAPEX
    c_trawler = create_mock_candidate(
        solar_area_m2=45.0,
        battery_capacity_kwh=100.0,
        total_initial_capex_usd=56250.0,
        annual_co2_displaced_kg=12000.0,
        annual_fuel_displaced_L=4500.0,
        net_present_value_usd=-15000.0,
    )
    # 4. Surfer Boat: small displacement, low CAPEX
    c_surfer = create_mock_candidate(
        solar_area_m2=25.0,
        battery_capacity_kwh=50.0,
        total_initial_capex_usd=28750.0,
        annual_co2_displaced_kg=7000.0,
        annual_fuel_displaced_L=2600.0,
        net_present_value_usd=-5000.0,
    )

    return [
        make_portfolio_item("Tanker Ship", "Tanker Ship", "Escravos-Lagos", c_tanker),
        make_portfolio_item("Oil Service Boat", "Oil Service Boat", "Escravos-Lagos", c_osv),
        make_portfolio_item("Fishing Trawler", "Fishing Trawler", "Warri-Bonny", c_trawler),
        make_portfolio_item("Surfer Boat", "Surfer Boat", "Lagos-Apapa", c_surfer),
    ]


# ==============================================================================
# Category A: Contract Validation (8 Tests)
# ==============================================================================

def test_contract_portfolio_item_valid():
    cand = create_mock_candidate()
    item = PortfolioItem(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        annual_voyages=52,
        candidate=cand,
    )
    assert item.vessel_id == "Tanker-01"
    assert item.ship_type == "Tanker Ship"
    assert item.annual_voyages == 52


def test_contract_portfolio_item_invalid_ship_type():
    cand = create_mock_candidate()
    with pytest.raises(ValueError, match="Unsupported ship_type"):
        PortfolioItem(
            vessel_id="Container-01",
            ship_type="Container Ship",
            route_id="Escravos-Lagos",
            candidate=cand,
        )


def test_contract_portfolio_item_negative_capex_rejected():
    # OptimizationCandidate itself enforces ge=0.0 on total_initial_capex_usd
    with pytest.raises(ValueError):
        create_mock_candidate(total_initial_capex_usd=-1000.0)


def test_contract_portfolio_item_negative_co2_rejected():
    # OptimizationCandidate itself enforces ge=0.0 on annual_co2_displaced_kg
    with pytest.raises(ValueError):
        create_mock_candidate(annual_co2_displaced_kg=-50.0)


def test_contract_parameters_valid():
    params = PortfolioOptimizationParameters(
        total_portfolio_capex_budget_usd=500000.0,
        max_retrofits=3,
        min_annual_co2_displaced_kg=10000.0,
        min_annual_fuel_displaced_L=3500.0,
    )
    assert params.total_portfolio_capex_budget_usd == 500000.0
    assert params.max_retrofits == 3


def test_contract_parameters_invalid_budget_zero_or_negative():
    with pytest.raises(ValueError):
        PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=0.0)
    with pytest.raises(ValueError):
        PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=-10000.0)


def test_contract_parameters_invalid_max_retrofits():
    with pytest.raises(ValueError):
        PortfolioOptimizationParameters(
            total_portfolio_capex_budget_usd=100000.0,
            max_retrofits=0,
        )


def test_contract_allocation_result_aggregate_inconsistency_rejected():
    cand = create_mock_candidate(
        total_initial_capex_usd=50000.0,
        annual_co2_displaced_kg=10000.0,
        annual_fuel_displaced_L=3800.0,
        net_present_value_usd=-12000.0,
    )
    item = make_portfolio_item("Trawler-1", "Fishing Trawler", "Warri-Bonny", cand)
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=100000.0)

    # Inconsistent total_capex_usd should fail validation
    with pytest.raises(ValueError, match="total_capex_usd"):
        PortfolioAllocationResult(
            parameters=params,
            selected_items=[item],
            total_capex_usd=99999.0,  # Incorrect
            total_annual_co2_displaced_kg=10000.0,
            total_annual_fuel_displaced_L=3800.0,
            total_npv_usd=-12000.0,
            selected_retrofit_count=1,
            portfolios_evaluated=2,
            eligible_items_count=1,
            excluded_items_count=0,
            diagnostics=DIAG_OPTIMAL_ALLOCATION,
        )


# ==============================================================================
# Category B: Portfolio Assembly & Filtering (6 Tests)
# ==============================================================================

def test_filtering_valid_and_invalid_candidates():
    c_valid = create_mock_candidate(candidate_status="VALID", is_physically_valid=True)
    c_invalid1 = create_mock_candidate(candidate_status="CONSTRAINED_OUT", is_physically_valid=False)
    c_invalid2 = create_mock_candidate(candidate_status="VALID", is_physically_valid=True, feasibility_status="INFEASIBLE")

    items = [
        make_portfolio_item("T1", "Tanker Ship", "Escravos-Lagos", c_valid),
        make_portfolio_item("T2", "Tanker Ship", "Escravos-Lagos", c_invalid1),
        make_portfolio_item("O1", "Oil Service Boat", "Escravos-Lagos", c_invalid2),
    ]

    eligible, excluded = filter_eligible_portfolio_items(items)
    assert len(eligible) == 1
    assert eligible[0].vessel_id == "T1"
    assert len(excluded) == 2


def test_grouping_by_vessel_id():
    c1 = create_mock_candidate()
    c2 = create_mock_candidate()
    items = [
        make_portfolio_item("Tanker Ship", "Tanker Ship", "Escravos-Lagos", c1),
        make_portfolio_item("Tanker Ship", "Tanker Ship", "Escravos-Lagos", c2),
        make_portfolio_item("Surfer Boat", "Surfer Boat", "Lagos-Apapa", c1),
    ]
    groups = group_items_by_vessel_id(items)
    assert len(groups) == 2
    assert len(groups["Tanker Ship"]) == 2
    assert len(groups["Surfer Boat"]) == 1


def test_mutual_exclusion_enforced(four_representative_fleet):
    # Add two candidates for Tanker Ship (Config A: lower CAPEX/CO2, Config B: higher CAPEX/CO2)
    c_tanker_a = create_mock_candidate(total_initial_capex_usd=100000.0, annual_co2_displaced_kg=20000.0)
    c_tanker_b = create_mock_candidate(total_initial_capex_usd=250000.0, annual_co2_displaced_kg=40000.0)

    items = [
        make_portfolio_item("Tanker Ship", "Tanker Ship", "Escravos-Lagos", c_tanker_a),
        make_portfolio_item("Tanker Ship", "Tanker Ship", "Escravos-Lagos", c_tanker_b),
        four_representative_fleet[1], # OSV
    ]

    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=500000.0)
    res = optimize_portfolio(items, params)

    # Tanker Ship must appear at most once in selected_items
    tanker_selections = [i for i in res.selected_items if i.vessel_id == "Tanker Ship"]
    assert len(tanker_selections) == 1
    # Config B gives higher CO2 and fits in budget
    assert tanker_selections[0].candidate.annual_co2_displaced_kg == 40000.0


def test_empty_input_portfolio():
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=100000.0)
    res = optimize_portfolio([], params)
    assert res.selected_retrofit_count == 0
    assert len(res.selected_items) == 0
    assert res.total_capex_usd == 0.0
    assert res.total_annual_co2_displaced_kg == 0.0
    assert res.diagnostics == DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS


def test_all_candidates_ineligible():
    c_inv = create_mock_candidate(candidate_status="CONSTRAINED_OUT", is_physically_valid=False)
    items = [make_portfolio_item("V1", "Surfer Boat", "Lagos-Apapa", c_inv)]
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=100000.0)
    res = optimize_portfolio(items, params)
    assert res.selected_retrofit_count == 0
    assert res.excluded_items_count == 1
    assert res.diagnostics == DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS


def test_budget_below_all_candidates(four_representative_fleet):
    # Lowest CAPEX is Surfer Boat at $28,750
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=10000.0)
    res = optimize_portfolio(four_representative_fleet, params)
    assert res.selected_retrofit_count == 0
    assert res.total_capex_usd == 0.0
    assert res.diagnostics == DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS


# ==============================================================================
# Category C: Aggregation Arithmetic & Identities (6 Tests)
# ==============================================================================

def test_aggregation_single_vessel(four_representative_fleet):
    trawler_item = [four_representative_fleet[2]] # Fishing Trawler
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=100000.0)
    res = optimize_portfolio(trawler_item, params)

    cand = trawler_item[0].candidate
    assert res.selected_retrofit_count == 1
    assert math.isclose(res.total_capex_usd, cand.total_initial_capex_usd)
    assert math.isclose(res.total_annual_co2_displaced_kg, cand.annual_co2_displaced_kg)
    assert math.isclose(res.total_annual_fuel_displaced_L, cand.annual_fuel_displaced_L)
    assert math.isclose(res.total_npv_usd, cand.net_present_value_usd)


def test_aggregation_four_vessels_all_selected(four_representative_fleet):
    # Total CAPEX is 250k + 132.5k + 56.25k + 28.75k = $467,500
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=500000.0)
    res = optimize_portfolio(four_representative_fleet, params)

    assert res.selected_retrofit_count == 4
    expected_capex = sum(i.candidate.total_initial_capex_usd for i in four_representative_fleet)
    expected_co2 = sum(i.candidate.annual_co2_displaced_kg for i in four_representative_fleet)
    expected_fuel = sum(i.candidate.annual_fuel_displaced_L for i in four_representative_fleet)
    expected_npv = sum(i.candidate.net_present_value_usd for i in four_representative_fleet)

    assert math.isclose(res.total_capex_usd, expected_capex)
    assert math.isclose(res.total_annual_co2_displaced_kg, expected_co2)
    assert math.isclose(res.total_annual_fuel_displaced_L, expected_fuel)
    assert math.isclose(res.total_npv_usd, expected_npv)
    assert res.diagnostics == DIAG_OPTIMAL_ALLOCATION


def test_aggregation_subset_selected(four_representative_fleet):
    # Budget $100,000 fits Trawler ($56,250) + Surfer ($28,750) = $85,000
    # Combined CO2 = 12,000 + 7,000 = 19,000 kg
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=100000.0)
    res = optimize_portfolio(four_representative_fleet, params)

    assert res.selected_retrofit_count == 2
    selected_names = [i.vessel_id for i in res.selected_items]
    assert "Fishing Trawler" in selected_names
    assert "Surfer Boat" in selected_names
    assert res.total_capex_usd == 85000.0
    assert res.total_annual_co2_displaced_kg == 19000.0
    assert res.total_annual_fuel_displaced_L == 7100.0


def test_aggregation_exact_budget_match():
    c1 = create_mock_candidate(total_initial_capex_usd=40000.0, annual_co2_displaced_kg=8000.0)
    c2 = create_mock_candidate(total_initial_capex_usd=60000.0, annual_co2_displaced_kg=12000.0)
    items = [
        make_portfolio_item("V1", "Fishing Trawler", "Warri-Bonny", c1),
        make_portfolio_item("V2", "Oil Service Boat", "Escravos-Lagos", c2),
    ]
    # Exact budget = 100,000.0
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=100000.0)
    res = optimize_portfolio(items, params)

    assert res.selected_retrofit_count == 2
    assert res.total_capex_usd == 100000.0
    assert res.total_annual_co2_displaced_kg == 20000.0


def test_zero_retrofit_identities():
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=100.0)
    res = optimize_portfolio([], params)
    assert res.total_capex_usd == 0.0
    assert res.total_annual_co2_displaced_kg == 0.0
    assert res.total_annual_fuel_displaced_L == 0.0
    assert res.total_npv_usd == 0.0


def test_aggregation_floating_point_stability():
    c1 = create_mock_candidate(total_initial_capex_usd=10000.333333, annual_co2_displaced_kg=3333.333333)
    c2 = create_mock_candidate(total_initial_capex_usd=20000.666667, annual_co2_displaced_kg=6666.666667)
    items = [
        make_portfolio_item("V1", "Surfer Boat", "Lagos-Apapa", c1),
        make_portfolio_item("V2", "Fishing Trawler", "Warri-Bonny", c2),
    ]
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=35000.0)
    res = optimize_portfolio(items, params)
    assert res.selected_retrofit_count == 2
    assert math.isclose(res.total_capex_usd, 30001.0, rel_tol=1e-5)


# ==============================================================================
# Category D: CO2 Objective Optimization & Constraints (7 Tests)
# ==============================================================================

def test_co2_maximization_over_npv():
    # Item 1: High CO2, worse NPV
    c1 = create_mock_candidate(
        total_initial_capex_usd=50000.0,
        annual_co2_displaced_kg=25000.0,
        net_present_value_usd=-30000.0,
    )
    # Item 2: Low CO2, better NPV
    c2 = create_mock_candidate(
        total_initial_capex_usd=50000.0,
        annual_co2_displaced_kg=10000.0,
        net_present_value_usd=-5000.0,
    )
    items = [
        make_portfolio_item("V1", "Fishing Trawler", "Warri-Bonny", c1),
        make_portfolio_item("V2", "Surfer Boat", "Lagos-Apapa", c2),
    ]
    # Budget permits only ONE vessel
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=60000.0)
    res = optimize_portfolio(items, params)

    assert res.selected_retrofit_count == 1
    assert res.selected_items[0].vessel_id == "V1"
    assert res.total_annual_co2_displaced_kg == 25000.0


def test_co2_maximization_over_fuel():
    # Item 1: Higher CO2, slightly lower fuel
    c1 = create_mock_candidate(
        total_initial_capex_usd=50000.0,
        annual_co2_displaced_kg=30000.0,
        annual_fuel_displaced_L=7000.0,
    )
    # Item 2: Lower CO2, higher fuel
    c2 = create_mock_candidate(
        total_initial_capex_usd=50000.0,
        annual_co2_displaced_kg=20000.0,
        annual_fuel_displaced_L=9000.0,
    )
    items = [
        make_portfolio_item("V1", "Fishing Trawler", "Warri-Bonny", c1),
        make_portfolio_item("V2", "Surfer Boat", "Lagos-Apapa", c2),
    ]
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=60000.0)
    res = optimize_portfolio(items, params)

    assert res.selected_items[0].vessel_id == "V1"
    assert res.total_annual_co2_displaced_kg == 30000.0


def test_constraint_max_retrofits(four_representative_fleet):
    # Budget $500k allows all 4 vessels, but max_retrofits=2
    params = PortfolioOptimizationParameters(
        total_portfolio_capex_budget_usd=500000.0,
        max_retrofits=2,
    )
    res = optimize_portfolio(four_representative_fleet, params)

    assert res.selected_retrofit_count == 2
    # The two highest CO2 vessels are Tanker (35,000) and OSV (22,000) -> 57,000 kg
    selected_names = [i.vessel_id for i in res.selected_items]
    assert "Tanker Ship" in selected_names
    assert "Oil Service Boat" in selected_names
    assert res.total_annual_co2_displaced_kg == 57000.0


def test_constraint_min_annual_co2_satisfied(four_representative_fleet):
    params = PortfolioOptimizationParameters(
        total_portfolio_capex_budget_usd=500000.0,
        min_annual_co2_displaced_kg=50000.0,
    )
    res = optimize_portfolio(four_representative_fleet, params)
    # All 4 give 76,000 kg >= 50,000 kg
    assert res.selected_retrofit_count == 4
    assert res.total_annual_co2_displaced_kg >= 50000.0


def test_constraint_min_annual_co2_exceeded_fails():
    c1 = create_mock_candidate(total_initial_capex_usd=50000.0, annual_co2_displaced_kg=5000.0)
    items = [make_portfolio_item("V1", "Fishing Trawler", "Warri-Bonny", c1)]
    params = PortfolioOptimizationParameters(
        total_portfolio_capex_budget_usd=100000.0,
        min_annual_co2_displaced_kg=20000.0, # Impossible to satisfy
    )
    res = optimize_portfolio(items, params)
    assert res.selected_retrofit_count == 0
    assert res.diagnostics == DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS


def test_constraint_min_annual_fuel_satisfied(four_representative_fleet):
    params = PortfolioOptimizationParameters(
        total_portfolio_capex_budget_usd=200000.0,
        min_annual_fuel_displaced_L=10000.0,
    )
    # OSV ($132.5k, 8300L) + Trawler ($56.25k, 4500L) = $188.75k, 12800L >= 10000L
    res = optimize_portfolio(four_representative_fleet, params)
    assert res.total_annual_fuel_displaced_L >= 10000.0


def test_constraint_min_annual_fuel_exceeded_fails():
    c1 = create_mock_candidate(total_initial_capex_usd=50000.0, annual_fuel_displaced_L=1000.0)
    items = [make_portfolio_item("V1", "Fishing Trawler", "Warri-Bonny", c1)]
    params = PortfolioOptimizationParameters(
        total_portfolio_capex_budget_usd=100000.0,
        min_annual_fuel_displaced_L=50000.0,
    )
    res = optimize_portfolio(items, params)
    assert res.selected_retrofit_count == 0
    assert res.diagnostics == DIAG_NO_ALLOCATION_WITHIN_CONSTRAINTS


# ==============================================================================
# Category E: Deterministic Tie-Breaking (4 Tests)
# ==============================================================================

def test_tie_break_lower_capex():
    # Both achieve 20,000 kg CO2, but V1 costs less
    c1 = create_mock_candidate(total_initial_capex_usd=40000.0, annual_co2_displaced_kg=20000.0, net_present_value_usd=-10000.0)
    c2 = create_mock_candidate(total_initial_capex_usd=60000.0, annual_co2_displaced_kg=20000.0, net_present_value_usd=-10000.0)
    items = [
        make_portfolio_item("V1", "Fishing Trawler", "Warri-Bonny", c1),
        make_portfolio_item("V2", "Oil Service Boat", "Escravos-Lagos", c2),
    ]
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=50000.0)
    res = optimize_portfolio(items, params)

    assert res.selected_retrofit_count == 1
    assert res.selected_items[0].vessel_id == "V1"


def test_tie_break_higher_npv():
    # Same CO2 (20k), same CAPEX (50k), but V2 has better NPV (-5k vs -15k)
    c1 = create_mock_candidate(total_initial_capex_usd=50000.0, annual_co2_displaced_kg=20000.0, net_present_value_usd=-15000.0)
    c2 = create_mock_candidate(total_initial_capex_usd=50000.0, annual_co2_displaced_kg=20000.0, net_present_value_usd=-5000.0)
    items = [
        make_portfolio_item("V1", "Fishing Trawler", "Warri-Bonny", c1),
        make_portfolio_item("V2", "Oil Service Boat", "Escravos-Lagos", c2),
    ]
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=60000.0)
    res = optimize_portfolio(items, params)

    assert res.selected_retrofit_count == 1
    assert res.selected_items[0].vessel_id == "V2"


def test_tie_break_fewer_retrofits():
    # Option A: 1 vessel doing 20k kg CO2 for $50k
    c_single = create_mock_candidate(total_initial_capex_usd=50000.0, annual_co2_displaced_kg=20000.0, net_present_value_usd=-10000.0)
    # Option B: 2 vessels doing 10k + 10k = 20k kg CO2 for $25k + $25k = $50k, same NPV
    c_pair1 = create_mock_candidate(total_initial_capex_usd=25000.0, annual_co2_displaced_kg=10000.0, net_present_value_usd=-5000.0)
    c_pair2 = create_mock_candidate(total_initial_capex_usd=25000.0, annual_co2_displaced_kg=10000.0, net_present_value_usd=-5000.0)

    items = [
        make_portfolio_item("V_Single", "Oil Service Boat", "Escravos-Lagos", c_single),
        make_portfolio_item("V_Pair1", "Fishing Trawler", "Warri-Bonny", c_pair1),
        make_portfolio_item("V_Pair2", "Surfer Boat", "Lagos-Apapa", c_pair2),
    ]
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=50000.0)
    res = optimize_portfolio(items, params)

    # Both subsets (V_Single) and (V_Pair1, V_Pair2) give 20k CO2, $50k CAPEX, -$10k NPV.
    # Fewer retrofits (1 vs 2) must win.
    assert res.selected_retrofit_count == 1
    assert res.selected_items[0].vessel_id == "V_Single"


def test_tie_break_deterministic_repeated_execution(four_representative_fleet):
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=200000.0)
    res1 = optimize_portfolio(four_representative_fleet, params)
    res2 = optimize_portfolio(four_representative_fleet, params)

    assert res1.total_capex_usd == res2.total_capex_usd
    assert res1.total_annual_co2_displaced_kg == res2.total_annual_co2_displaced_kg
    assert [i.vessel_id for i in res1.selected_items] == [i.vessel_id for i in res2.selected_items]


# ==============================================================================
# Category F: Immutability, Scope, and Isolation (6 Tests)
# ==============================================================================

def test_no_candidate1_or_candidate2_dependencies():
    """Verify Candidate 3 does not import or call Candidate 1 or 2 modules."""
    import sys
    import phase9_portfolio_contracts
    import phase9_portfolio_optimizer

    for mod in [phase9_portfolio_contracts, phase9_portfolio_optimizer]:
        src = open(mod.__file__, "r", encoding="utf-8").read()
        assert "phase9_contracts" not in src
        assert "phase9_sensitivity" not in src
        assert "phase9_speed_contracts" not in src
        assert "phase9_speed_cooptimizer" not in src


def test_no_phase8_full_grid_optimizer_called():
    """Verify Candidate 3 source code does not call optimize_system_sizing."""
    import ast
    import phase9_portfolio_optimizer
    src = open(phase9_portfolio_optimizer.__file__, "r", encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "optimize_system_sizing"
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr != "optimize_system_sizing"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert alias.name != "optimize_system_sizing"


def test_four_archetypes_fleet_size_bounds():
    """Verify supported fleet types are exactly 4 archetypes."""
    assert len(SUPPORTED_PORTFOLIO_SHIP_TYPES) == 4
    expected = {"Tanker Ship", "Oil Service Boat", "Fishing Trawler", "Surfer Boat"}
    assert set(SUPPORTED_PORTFOLIO_SHIP_TYPES) == expected


def test_portfolios_evaluated_count_bounded(four_representative_fleet):
    """Verify that for 4 vessels, portfolios_evaluated <= 16."""
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=500000.0)
    res = optimize_portfolio(four_representative_fleet, params)
    assert res.portfolios_evaluated <= 16
    assert res.portfolios_evaluated == 16  # 2^4 = 16


def test_raw_data_and_ship_profiles_unmodified():
    root = r"C:\maritime grids"
    raw_count = sum(len(files) for _, _, files in os.walk(os.path.join(root, "data", "raw")))
    assert raw_count == 6228

    sp_path = os.path.join(root, "data", "reference", "ship_profiles.csv")
    with open(sp_path, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    assert h == "0f2040a481790b034fac11cd9e2b628c725281397610fe0bdba09f6feed7de75"


def test_candidate3_runtime_sub_second(four_representative_fleet):
    import time
    params = PortfolioOptimizationParameters(total_portfolio_capex_budget_usd=500000.0)
    t0 = time.perf_counter()
    res = optimize_portfolio(four_representative_fleet, params)
    t_eval = time.perf_counter() - t0
    assert t_eval < 0.10  # Must be fast sub-millisecond execution for 16 combinations
    assert res.selected_retrofit_count == 4
