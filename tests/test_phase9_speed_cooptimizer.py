"""
tests/test_phase9_speed_cooptimizer.py — Test Suite for Phase 9 Candidate 2
=============================================================================
Validates:
  1. Pydantic V2 contract validation & bounds enforcement
  2. Hydrodynamic power-speed quadratic fuel scaling & duration physics
  3. Transit delivery deadline constraint filtering
  4. 3D discrete grid generation & computational budget ceiling enforcement
  5. Phase 8 sizing and Phase 7 capital budgeting integration
  6. Multi-objective 3D Pareto frontier non-domination sorting & tie-breaking
  7. Deterministic repeated execution & performance latency (< 2.0 seconds)
"""

import pytest
import math

from phase7_contracts import FinancialParameters
from phase9_speed_contracts import (
    SpeedCoOptimizationParameters,
    SpeedSizingCandidate,
    SpeedCoOptimizationResult,
    MAX_SPEED_EVALUATIONS_LIMIT,
    MAX_EXECUTION_TIME_LIMIT_SECONDS,
)
from phase9_speed_cooptimizer import (
    resolve_route_distance,
    resolve_vessel_design_profile,
    resolve_speed_lattice,
    resolve_sizing_lattices,
    calculate_speed_scaled_voyage,
    pareto_dominates_speed_candidate,
    filter_speed_pareto_frontier,
    optimize_speed_and_sizing,
)


# ==============================================================================
# Fixtures
# ==============================================================================
@pytest.fixture
def base_tanker_params():
    return SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        route_id="Warri-Bonny",
        vmin=8.0,
        vmax=13.5,
        v_step=1.0,
        apv_min=0.0,
        apv_max=50.0,
        apv_step=25.0,
        ebatt_min=0.0,
        ebatt_max=100.0,
        ebatt_step=50.0,
        annual_voyages=52,
    )


# ==============================================================================
# 1. Contract Validation Tests
# ==============================================================================
def test_contract_valid_defaults():
    params = SpeedCoOptimizationParameters(ship_type="Tanker Ship")
    assert params.ship_type == "Tanker Ship"
    assert params.apv_step == 10.0
    assert params.ebatt_step == 25.0
    assert params.max_evaluations == MAX_SPEED_EVALUATIONS_LIMIT


def test_contract_invalid_ship_type():
    with pytest.raises(ValueError, match="Invalid ship_type"):
        SpeedCoOptimizationParameters(ship_type="Cargo Airplane")


def test_contract_reversed_speed_bounds():
    with pytest.raises(ValueError, match="vmin .* cannot exceed vmax"):
        SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            vmin=14.0,
            vmax=10.0,
        )


def test_contract_reversed_solar_bounds():
    with pytest.raises(ValueError, match="apv_min .* cannot exceed apv_max"):
        SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            apv_min=100.0,
            apv_max=50.0,
        )


def test_contract_reversed_battery_bounds():
    with pytest.raises(ValueError, match="ebatt_min .* cannot exceed ebatt_max"):
        SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            ebatt_min=200.0,
            ebatt_max=100.0,
        )


def test_contract_invalid_pareto_objectives_count():
    with pytest.raises(ValueError, match="at least 2 distinct objectives"):
        SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            pareto_objectives=["MIN_DURATION"],
        )


def test_contract_invalid_pareto_objective_name():
    with pytest.raises(ValueError, match="Invalid Pareto objective"):
        SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            pareto_objectives=["MIN_DURATION", "INVALID_OBJ"],
        )


def test_contract_exceeds_design_speed():
    # Tanker max design speed is 13.5 kn
    with pytest.raises(ValueError, match="exceeds vessel maximum design speed"):
        params = SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            vmax=18.0,
        )
        profile = resolve_vessel_design_profile("Tanker Ship")
        resolve_speed_lattice(params.ship_type, profile, params.vmin, params.vmax, params.v_step)


def test_contract_invalid_deadline():
    # Warri-Bonny distance for Tanker is 250 nm. Fastest speed 13.5 kn -> 18.518 h.
    # A deadline of 10.0 hours is physically impossible.
    with pytest.raises(ValueError, match="is less than fastest possible transit time"):
        params = SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            route_id="Warri-Bonny",
            vmax=13.5,
            t_deadline=10.0,
        )
        optimize_speed_and_sizing(params)


# ==============================================================================
# 2. Hydrodynamic Power-Speed Scaling & Duration Physics
# ==============================================================================
def test_duration_decreases_with_speed():
    dist = 250.0
    t_slow = dist / 8.0
    t_fast = dist / 13.5
    assert t_fast < t_slow
    assert t_slow == pytest.approx(31.25, abs=1e-3)
    assert t_fast == pytest.approx(18.5185, abs=1e-3)


def test_propulsion_fuel_quadratic_scaling():
    # Vref = 10 kn, F_ref = 1000 L
    # At V = 12 kn: (12/10)^2 = 1.44 => F = 1440 L
    # At V = 8 kn:  (8/10)^2 = 0.64 => F = 640 L
    res_12 = calculate_speed_scaled_voyage(
        speed_knots=12.0,
        distance_nm=120.0,
        v_ref=10.0,
        f_prop_ref=1000.0,
        p_aux_kw=0.0,  # Isolate propulsion
        sfoc_gen=0.220,
        rho_fuel=0.850,
        emission_factor_co2=3.114,
    )
    res_8 = calculate_speed_scaled_voyage(
        speed_knots=8.0,
        distance_nm=120.0,
        v_ref=10.0,
        f_prop_ref=1000.0,
        p_aux_kw=0.0,
        sfoc_gen=0.220,
        rho_fuel=0.850,
        emission_factor_co2=3.114,
    )
    assert res_12["propulsion_fuel_L"] == pytest.approx(1440.0, abs=1e-2)
    assert res_8["propulsion_fuel_L"] == pytest.approx(640.0, abs=1e-2)


def test_reference_speed_reconciliation():
    # At V = Vref, F_prop(V) must equal F_prop_ref exactly
    res = calculate_speed_scaled_voyage(
        speed_knots=13.5,
        distance_nm=250.0,
        v_ref=13.5,
        f_prop_ref=8500.0,
        p_aux_kw=50.0,
        sfoc_gen=0.220,
        rho_fuel=0.850,
        emission_factor_co2=3.114,
    )
    assert res["propulsion_fuel_L"] == pytest.approx(8500.0, abs=1e-3)


def test_auxiliary_fuel_increases_at_lower_speed():
    # At lower speed, voyage duration is longer, so auxiliary generator runs longer
    res_slow = calculate_speed_scaled_voyage(
        speed_knots=8.0,
        distance_nm=240.0,
        v_ref=12.0,
        f_prop_ref=5000.0,
        p_aux_kw=100.0,
        sfoc_gen=0.220,
        rho_fuel=0.850,
        emission_factor_co2=3.114,
    )
    res_fast = calculate_speed_scaled_voyage(
        speed_knots=12.0,
        distance_nm=240.0,
        v_ref=12.0,
        f_prop_ref=5000.0,
        p_aux_kw=100.0,
        sfoc_gen=0.220,
        rho_fuel=0.850,
        emission_factor_co2=3.114,
    )
    assert res_slow["voyage_duration_hours"] > res_fast["voyage_duration_hours"]
    assert res_slow["auxiliary_fuel_L"] > res_fast["auxiliary_fuel_L"]


# ==============================================================================
# 3. Transit Delivery Deadline Tests
# ==============================================================================
def test_deadline_satisfied_by_all():
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=10.0,
        vmax=12.0,
        v_step=2.0,
        t_deadline=30.0,  # 250 nm at 10 kn is 25 h <= 30 h
        apv_min=0.0,
        apv_max=20.0,
        apv_step=20.0,
        ebatt_min=0.0,
        ebatt_max=50.0,
        ebatt_step=50.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.deadline_exceeded_count == 0
    assert all(c.meets_deadline for c in res.candidate_results)


def test_deadline_filtering_slow_candidates():
    # Warri-Bonny 250 nm.
    # At 8 kn: 31.25 h. At 10 kn: 25.0 h. At 12.5 kn: 20.0 h.
    # Deadline: 26.0 h => 8 kn is filtered out; 10 and 12.5 kn pass.
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=8.0,
        vmax=12.5,
        v_step=2.0,  # [8.0, 10.0, 12.0]
        t_deadline=26.0,
        apv_min=0.0,
        apv_max=10.0,
        apv_step=10.0,
        ebatt_min=0.0,
        ebatt_max=25.0,
        ebatt_step=25.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.deadline_exceeded_count > 0
    for c in res.candidate_results:
        if c.speed_knots == 8.0:
            assert c.meets_deadline is False
            assert c.candidate_status == "DEADLINE_EXCEEDED"
            assert "DEADLINE_EXCEEDED" in c.constraint_violations
        else:
            assert c.meets_deadline is True


def test_deadline_exact_boundary():
    # Distance 250 nm. Speed 10 kn => duration exactly 25.0 h.
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=10.0,
        vmax=10.0,
        t_deadline=25.0,
        apv_min=0.0,
        apv_max=10.0,
        apv_step=10.0,
        ebatt_min=0.0,
        ebatt_max=25.0,
        ebatt_step=25.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.deadline_exceeded_count == 0
    assert all(c.meets_deadline for c in res.candidate_results)


def test_deadline_rejected_when_shorter_than_fastest_transit():
    # 250 nm at vmax 10 kn -> min possible transit time is 25.0 h.
    # A deadline of 22.0 h must be rejected upfront with ValueError.
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=8.0,
        vmax=10.0,
        v_step=1.0,
        t_deadline=22.0,
        apv_min=0.0,
        apv_max=10.0,
        apv_step=10.0,
        ebatt_min=0.0,
        ebatt_max=25.0,
        ebatt_step=25.0,
    )
    with pytest.raises(ValueError, match="is less than fastest possible transit time"):
        optimize_speed_and_sizing(params)


def test_deadline_filters_slow_candidates():
    # 250 nm: 10 kn -> 25.0 h; 9 kn -> 27.78 h; 8 kn -> 31.25 h.
    # With deadline = 28.0 h: speeds 10 kn and 9 kn meet deadline; 8 kn exceeds deadline.
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=8.0,
        vmax=10.0,
        v_step=1.0,
        t_deadline=28.0,
        apv_min=0.0,
        apv_max=10.0,
        apv_step=10.0,
        ebatt_min=0.0,
        ebatt_max=25.0,
        ebatt_step=25.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.total_configurations_evaluated == 3 * 2 * 2  # 12
    assert res.deadline_exceeded_count == 1 * 2 * 2  # 4 (the 8 kn candidates)
    assert res.valid_candidates_count == 2 * 2 * 2  # 8 (9 kn and 10 kn candidates)
    assert all(c.speed_knots in [9.0, 10.0] for c in res.pareto_frontier)


# ==============================================================================
# 4. Grid Generation & Computational Budget Tests
# ==============================================================================
def test_grid_generation_counts(base_tanker_params):
    res = optimize_speed_and_sizing(base_tanker_params)
    # Speeds: 8.0, 9.0, 10.0, 11.0, 12.0, 13.0 (6 speeds, 14.0 > 13.5)
    # Solar: 0.0, 25.0, 50.0 (3)
    # Battery: 0.0, 50.0, 100.0 (3)
    # Total = 6 * 3 * 3 = 54
    assert res.speed_candidate_count == 6
    assert res.solar_candidate_count == 3
    assert res.battery_candidate_count == 3
    assert res.total_configurations_evaluated == 54
    assert len(res.candidate_results) == 54


def test_budget_rejection_over_limit():
    # 20 speeds x 20 solar x 20 battery = 8,000 points > 2500
    with pytest.raises(ValueError, match="exceeds maximum computational limit"):
        params = SpeedCoOptimizationParameters(
            ship_type="Tanker Ship",
            vmin=5.0,
            vmax=13.5,
            v_step=0.2,  # 43 speeds
            apv_min=0.0,
            apv_max=100.0,
            apv_step=5.0,  # 21 solar
            ebatt_min=0.0,
            ebatt_max=200.0,
            ebatt_step=10.0,  # 21 battery -> 43 * 21 * 21 = 18,963
            max_evaluations=2500,
        )
        optimize_speed_and_sizing(params)


def test_budget_exact_boundary():
    # Configure grid near or exactly at limit (e.g. 5 speeds x 20 solar x 20 battery = 2,000 <= 2500)
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=10.0,
        vmax=12.0,
        v_step=0.5,  # 5 speeds
        apv_min=0.0,
        apv_max=95.0,
        apv_step=5.0,  # 20 solar
        ebatt_min=0.0,
        ebatt_max=190.0,
        ebatt_step=10.0,  # 20 battery -> 5 * 20 * 20 = 2,000 points
        max_evaluations=2500,
    )
    res = optimize_speed_and_sizing(params)
    assert res.total_configurations_evaluated == 2000
    assert res.execution_time_seconds > 0.0
    assert res.execution_time_seconds < 30.0


# ==============================================================================
# 5. Phase 8 & Phase 7 Integration Tests
# ==============================================================================
def test_phase8_single_candidate_invocation(base_tanker_params):
    res = optimize_speed_and_sizing(base_tanker_params)
    assert res.valid_candidates_count > 0
    c0 = res.candidate_results[0]
    # Check that financial metrics are populated from Phase 7/8
    assert c0.net_present_value_usd is not None
    assert c0.total_initial_capex_usd >= 0.0
    assert c0.irr_status in ["IRR_UNIQUE_ROOT", "IRR_NOT_APPLICABLE_ALL_NEGATIVE", "IRR_NOT_APPLICABLE_ZERO_CAPEX"]


def test_solar_yield_increases_at_slower_speed():
    # For identical solar sizing, slower speed means longer duration, producing more solar kWh
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=8.0,
        vmax=12.0,
        v_step=4.0,  # 8.0 kn and 12.0 kn
        apv_min=100.0,
        apv_max=100.0,
        apv_step=10.0,
        ebatt_min=0.0,
        ebatt_max=0.0,
        ebatt_step=25.0,
    )
    res = optimize_speed_and_sizing(params)
    c_slow = [c for c in res.candidate_results if c.speed_knots == 8.0][0]
    c_fast = [c for c in res.candidate_results if c.speed_knots == 12.0][0]

    assert c_slow.voyage_duration_hours > c_fast.voyage_duration_hours
    assert c_slow.clean_energy_utilized_kwh >= c_fast.clean_energy_utilized_kwh


def test_annual_voyages_fixed_by_default(base_tanker_params):
    res = optimize_speed_and_sizing(base_tanker_params)
    # Check that annual gross fuel is strictly 52 * single_voyage_total_fuel_L
    for c in res.candidate_results:
        assert c.annual_fuel_consumed_L == pytest.approx(c.single_voyage_total_fuel_L * 52, abs=1e-2)


# ==============================================================================
# 6. Multi-Objective 3D Pareto Frontier Tests
# ==============================================================================
def test_pareto_dominates_function():
    # Candidate A: duration=20 h, fuel=10,000 L, NPV=-100,000
    # Candidate B: duration=25 h, fuel=12,000 L, NPV=-120,000
    # A dominates B across all 3 objectives
    c_a = SpeedSizingCandidate(
        speed_knots=12.0, solar_area_m2=50.0, battery_capacity_kwh=100.0, battery_mass_tonnes=0.85,
        voyage_duration_hours=20.0, meets_deadline=True, is_physically_valid=True,
        candidate_status="VALID", single_voyage_propulsion_fuel_L=500.0, single_voyage_auxiliary_fuel_L=50.0,
        single_voyage_total_fuel_L=550.0, clean_energy_utilized_kwh=100.0, annual_fuel_displaced_L=500.0,
        annual_co2_displaced_kg=1300.0, feasibility_status="PARTIAL", annual_fuel_consumed_L=28600.0,
        net_annual_fuel_consumed_L=10000.0, annual_co2_emissions_kg=27000.0, total_initial_capex_usd=80000.0,
        net_present_value_usd=-100000.0, irr_status="IRR_UNIQUE_ROOT", lcoe_status="LCOE_CALCULATED",
    )
    c_b = c_a.model_copy(update={
        "voyage_duration_hours": 25.0,
        "net_annual_fuel_consumed_L": 12000.0,
        "net_present_value_usd": -120000.0,
    })
    objs = ["MIN_DURATION", "MIN_ANNUAL_FUEL", "MAX_NPV"]
    assert pareto_dominates_speed_candidate(c_a, c_b, objs) is True
    assert pareto_dominates_speed_candidate(c_b, c_a, objs) is False


def test_pareto_frontier_non_empty(base_tanker_params):
    res = optimize_speed_and_sizing(base_tanker_params)
    assert len(res.pareto_frontier) > 0
    # Verify no candidate in frontier is dominated by another in frontier
    for i, c1 in enumerate(res.pareto_frontier):
        for j, c2 in enumerate(res.pareto_frontier):
            if i != j:
                assert not pareto_dominates_speed_candidate(c1, c2, base_tanker_params.pareto_objectives)


def test_pareto_frontier_deterministic_ordering(base_tanker_params):
    res = optimize_speed_and_sizing(base_tanker_params)
    durations = [c.voyage_duration_hours for c in res.pareto_frontier]
    # Primary sort key is duration ascending
    assert all(durations[i] <= durations[i + 1] + 1e-6 for i in range(len(durations) - 1))


def test_speed_tradeoff_curve_coverage(base_tanker_params):
    res = optimize_speed_and_sizing(base_tanker_params)
    # Tradeoff curve should contain exactly one best sizing candidate per speed
    speeds_in_curve = [c.speed_knots for c in res.speed_tradeoff_curve]
    assert len(speeds_in_curve) == res.speed_candidate_count
    assert speeds_in_curve == sorted(speeds_in_curve)


# ==============================================================================
# 7. Real Vessel Profiles Integration Tests
# ==============================================================================
def test_oil_service_boat_speed_cooptimization():
    params = SpeedCoOptimizationParameters(
        ship_type="Oil Service Boat",
        route_id="Warri-Bonny",
        vmin=10.0,
        vmax=14.0,
        v_step=2.0,
        apv_min=0.0,
        apv_max=20.0,
        apv_step=20.0,
        ebatt_min=0.0,
        ebatt_max=50.0,
        ebatt_step=50.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.optimal_candidate is not None
    assert res.parameters.ship_type == "Oil Service Boat"


def test_fishing_trawler_speed_cooptimization():
    params = SpeedCoOptimizationParameters(
        ship_type="Fishing Trawler",
        route_id="Warri-Bonny",
        vmin=8.0,
        vmax=11.0,
        v_step=1.0,
        apv_min=0.0,
        apv_max=20.0,
        apv_step=20.0,
        ebatt_min=0.0,
        ebatt_max=25.0,
        ebatt_step=25.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.optimal_candidate is not None
    assert res.resolved_vmax_knots == 11.0


def test_surfer_boat_speed_cooptimization():
    # Surfer Boat design speed is 28 kn. Step is 1.0 kn
    params = SpeedCoOptimizationParameters(
        ship_type="Surfer Boat",
        route_id="Warri-Bonny",
        vmin=20.0,
        vmax=28.0,
        v_step=4.0,
        apv_min=0.0,
        apv_max=10.0,
        apv_step=10.0,
        ebatt_min=0.0,
        ebatt_max=25.0,
        ebatt_step=25.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.optimal_candidate is not None
    assert res.resolved_vmax_knots == 28.0


# ==============================================================================
# 8. Deterministic Repeated Execution & Performance
# ==============================================================================
def test_deterministic_repeated_execution(base_tanker_params):
    run1 = optimize_speed_and_sizing(base_tanker_params)
    run2 = optimize_speed_and_sizing(base_tanker_params)

    assert run1.total_configurations_evaluated == run2.total_configurations_evaluated
    assert run1.optimal_candidate.speed_knots == run2.optimal_candidate.speed_knots
    assert run1.optimal_candidate.solar_area_m2 == run2.optimal_candidate.solar_area_m2
    assert run1.optimal_candidate.battery_capacity_kwh == run2.optimal_candidate.battery_capacity_kwh
    assert run1.optimal_candidate.net_present_value_usd == run2.optimal_candidate.net_present_value_usd
    assert len(run1.pareto_frontier) == len(run2.pareto_frontier)


def test_performance_typical_run_under_two_seconds():
    # Typical run with ~100–200 grid points: 5 speeds x 5 solar x 5 battery = 125 points
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=9.0,
        vmax=13.0,
        v_step=1.0,  # 5 speeds (9.0, 10.0, 11.0, 12.0, 13.0)
        apv_min=0.0,
        apv_max=40.0,
        apv_step=10.0,  # 5 solar (0, 10, 20, 30, 40)
        ebatt_min=0.0,
        ebatt_max=100.0,
        ebatt_step=25.0,  # 5 battery (0, 25, 50, 75, 100) -> 5 * 5 * 5 = 125
    )
    res = optimize_speed_and_sizing(params)
    assert res.total_configurations_evaluated == 125
    assert res.execution_time_seconds < MAX_EXECUTION_TIME_LIMIT_SECONDS, (
        f"Typical execution time {res.execution_time_seconds}s exceeded limit of {MAX_EXECUTION_TIME_LIMIT_SECONDS}s"
    )


def test_performance_2000_evaluations_boundary():
    # Near 2,000 evaluations (boundary verification)
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=9.0,
        vmax=13.5,
        v_step=1.0,  # 5 speeds (9.0, 10.0, 11.0, 12.0, 13.0)
        apv_min=0.0,
        apv_max=95.0,
        apv_step=5.0,  # 20 solar steps
        ebatt_min=0.0,
        ebatt_max=190.0,
        ebatt_step=10.0,  # 20 battery steps -> 5 * 20 * 20 = 2,000 evaluations
    )
    res = optimize_speed_and_sizing(params)
    assert res.total_configurations_evaluated == 2000
    assert res.execution_time_seconds > 0.0
    assert res.execution_time_seconds < 30.0


# ==============================================================================
# 9. Additional Boundary, Edge-Case & Invariant Tests
# ==============================================================================
def test_single_configuration_evaluation():
    # 1 speed x 1 solar x 1 battery = 1 evaluation
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=10.0,
        vmax=10.0,
        v_step=1.0,
        apv_min=50.0,
        apv_max=50.0,
        apv_step=10.0,
        ebatt_min=100.0,
        ebatt_max=100.0,
        ebatt_step=25.0,
    )
    res = optimize_speed_and_sizing(params)
    assert res.total_configurations_evaluated == 1
    assert res.valid_candidates_count == 1
    assert len(res.pareto_frontier) == 1
    assert res.optimal_candidate.speed_knots == 10.0
    assert res.optimal_candidate.solar_area_m2 == 50.0
    assert res.optimal_candidate.battery_capacity_kwh == 100.0


def test_vmax_exceeding_vessel_design_speed_rejected():
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=10.0,
        vmax=15.0,  # Tanker design speed is 13.5 kn
    )
    with pytest.raises(ValueError, match="exceeds vessel maximum design speed"):
        optimize_speed_and_sizing(params)


def test_annual_voyages_preservation():
    params = SpeedCoOptimizationParameters(
        ship_type="Tanker Ship",
        vmin=10.0,
        vmax=10.0,
        apv_min=10.0,
        apv_max=10.0,
        ebatt_min=25.0,
        ebatt_max=25.0,
        annual_voyages=75,
    )
    res = optimize_speed_and_sizing(params)
    assert res.parameters.annual_voyages == 75
    # Single voyage fuel displaced * 75 should equal annual fuel displaced
    cand = res.candidate_results[0]
    expected_annual_fuel_disp = (cand.clean_energy_utilized_kwh * 0.22 / 0.85) * 75
    assert abs(cand.annual_fuel_displaced_L - expected_annual_fuel_disp) < 1e-3


def test_pareto_frontier_tie_breaking_consistency():
    # Construct synthetic candidates with tied primary objective (MIN_DURATION)
    # MIN_DURATION, MIN_ANNUAL_FUEL, MAX_NPV
    c1 = SpeedSizingCandidate(
        speed_knots=10.0,
        solar_area_m2=10.0,
        battery_capacity_kwh=25.0,
        battery_mass_tonnes=0.2125,
        voyage_duration_hours=25.0,
        meets_deadline=True,
        is_physically_valid=True,
        candidate_status="VALID",
        single_voyage_propulsion_fuel_L=5000.0,
        single_voyage_auxiliary_fuel_L=100.0,
        single_voyage_total_fuel_L=5100.0,
        clean_energy_utilized_kwh=50.0,
        annual_fuel_displaced_L=600.0,
        annual_co2_displaced_kg=1500.0,
        feasibility_status="PARTIAL",
        annual_fuel_consumed_L=265200.0,
        net_annual_fuel_consumed_L=264600.0,
        annual_co2_emissions_kg=700000.0,
        total_initial_capex_usd=50000.0,
        net_present_value_usd=-50000.0,
        internal_rate_of_return_pct=-10.0,
        irr_status="IRR_UNIQUE_ROOT",
        lcoe_usd_per_kwh=1.5,
        lcoe_status="LCOE_CALCULATED",
        objective_values={"MIN_DURATION": 25.0, "MIN_ANNUAL_FUEL": 264600.0, "MAX_NPV": -50000.0},
    )
    c2 = SpeedSizingCandidate(
        speed_knots=10.0,
        solar_area_m2=20.0,
        battery_capacity_kwh=50.0,
        battery_mass_tonnes=0.425,
        voyage_duration_hours=25.0,
        meets_deadline=True,
        is_physically_valid=True,
        candidate_status="VALID",
        single_voyage_propulsion_fuel_L=5000.0,
        single_voyage_auxiliary_fuel_L=100.0,
        single_voyage_total_fuel_L=5100.0,
        clean_energy_utilized_kwh=100.0,
        annual_fuel_displaced_L=1200.0,
        annual_co2_displaced_kg=3000.0,
        feasibility_status="PARTIAL",
        annual_fuel_consumed_L=265200.0,
        net_annual_fuel_consumed_L=264000.0,
        annual_co2_emissions_kg=698000.0,
        total_initial_capex_usd=60000.0,
        net_present_value_usd=-45000.0,
        internal_rate_of_return_pct=-8.0,
        irr_status="IRR_UNIQUE_ROOT",
        lcoe_usd_per_kwh=1.4,
        lcoe_status="LCOE_CALCULATED",
        objective_values={"MIN_DURATION": 25.0, "MIN_ANNUAL_FUEL": 264000.0, "MAX_NPV": -45000.0},
    )
    # c2 has lower annual fuel and higher NPV -> c2 dominates c1 or appears first
    frontier = filter_speed_pareto_frontier([c1, c2], ["MIN_DURATION", "MIN_ANNUAL_FUEL", "MAX_NPV"])
    assert len(frontier) == 1
    assert frontier[0].battery_capacity_kwh == 50.0

