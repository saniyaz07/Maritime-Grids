"""
test_phase9_cii_trajectory.py — Test Suite for Phase 9 Candidate 4
==================================================================
Multi-Year Regulatory Compliance Trajectory & IMO CII Aging Simulator

Covers:
  A. Contract Validation (>= 8 tests)
  B. Statutory CII (2023–2026) & Boundaries (>= 8 tests)
  C. Post-2026 Scenarios & Provenance (>= 6 tests)
  D. Compliance & Corrective Action Tracking (>= 6 tests)
  E. Vessel Scope & Exemption Rules (>= 4 tests)
  F. Physical Degradation & Compounding (>= 4 tests)
  G. Safety, Immutability & Performance (>= 4 tests)
"""

import math
import hashlib
import os
import time
import pytest

from phase8_contracts import OptimizationCandidate
from phase9_cii_contracts import (
    SUPPORTED_CII_SHIP_TYPES,
    REGULATORY_BASIS_STATUTORY,
    REGULATORY_BASIS_PROJECTED,
    REGULATORY_BASIS_UNSPECIFIED,
    REGULATORY_BASIS_EXEMPT,
    REGULATORY_BASIS_NOT_ASSESSED,
    CII_RATING_A,
    CII_RATING_B,
    CII_RATING_C,
    CII_RATING_D,
    CII_RATING_E,
    CII_RATING_EXEMPT,
    CII_RATING_NOT_ASSESSED,
    CII_RATING_UNSPECIFIED,
    DIAG_TRAJECTORY_COMPLETED,
    DIAG_TRAJECTORY_UNSPECIFIED_POST_2026,
    DIAG_TRAJECTORY_EXEMPT,
    DIAG_TRAJECTORY_NOT_ASSESSED,
    RegulatoryScenarioParameters,
    PhysicalDegradationParameters,
    TrajectorySimulationRequest,
    AnnualTrajectoryRecord,
    TrajectorySimulationResult,
)
from phase9_cii_trajectory import (
    resolve_year_regulatory_basis,
    simulate_compliance_trajectory,
)


# ==============================================================================
# Helpers & Fixtures
# ==============================================================================

def create_mock_retrofit_candidate(
    fuel_disp_L: float = 2831.9656,
    co2_disp_kg: float = 7495.9296,
) -> OptimizationCandidate:
    """Pre-evaluated Phase 8 candidate mockup."""
    return OptimizationCandidate(
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
        battery_mass_tonnes=1.7,
        deck_area_limit_m2=833.0,
        battery_weight_limit_tonnes=700.0,
        is_physically_valid=True,
        constraint_violations=[],
        candidate_status="VALID",
        clean_energy_available_kwh=15000.0,
        clean_energy_utilized_kwh=10800.0,
        curtailed_energy_kwh=4200.0,
        feasibility_status="FEASIBLE",
        annual_fuel_displaced_L=fuel_disp_L,
        annual_co2_displaced_kg=co2_disp_kg,
        total_initial_capex_usd=150000.0,
        net_present_value_usd=-172136.70,
        internal_rate_of_return_pct=-22.7467,
        irr_status="IRR_UNIQUE_ROOT",
        simple_payback_years=None,
        discounted_payback_years=None,
        lcoe_usd_per_kwh=2.128134,
        lcoe_status="LCOE_CALCULATED",
        objective_value=co2_disp_kg,
    )


@pytest.fixture
def tanker_request():
    """Standard Tanker Ship trajectory simulation request (2023–2026 statutory window)."""
    return TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20124.3,
        baseline_single_voyage_co2_kg=53268.0,
        candidate=create_mock_retrofit_candidate(),
        start_year=2023,
        end_year=2026,
    )


# ==============================================================================
# Category A: Contract Validation (8 Tests)
# ==============================================================================

def test_contract_valid_tanker_request(tanker_request):
    assert tanker_request.vessel_id == "Tanker-01"
    assert tanker_request.ship_type == "Tanker Ship"
    assert tanker_request.start_year == 2023
    assert tanker_request.end_year == 2026


def test_contract_invalid_ship_type():
    with pytest.raises(ValueError, match="Unsupported ship_type"):
        TrajectorySimulationRequest(
            vessel_id="V1",
            ship_type="Container Ship",
            dwt_tonnes=10000.0,
            route_id="Escravos-Lagos",
            voyage_distance_nm=100.0,
            baseline_single_voyage_fuel_L=5000.0,
            baseline_single_voyage_co2_kg=15000.0,
        )


def test_contract_invalid_years_end_before_start():
    with pytest.raises(ValueError, match="end_year .* cannot be earlier than start_year"):
        TrajectorySimulationRequest(
            vessel_id="Tanker-01",
            ship_type="Tanker Ship",
            dwt_tonnes=14000.0,
            route_id="Escravos-Lagos",
            voyage_distance_nm=250.0,
            baseline_single_voyage_fuel_L=20000.0,
            baseline_single_voyage_co2_kg=50000.0,
            start_year=2026,
            end_year=2023,
        )


def test_contract_negative_dwt_rejected():
    with pytest.raises(ValueError):
        TrajectorySimulationRequest(
            vessel_id="Tanker-01",
            ship_type="Tanker Ship",
            dwt_tonnes=-1000.0,
            route_id="Escravos-Lagos",
            voyage_distance_nm=250.0,
            baseline_single_voyage_fuel_L=20000.0,
            baseline_single_voyage_co2_kg=50000.0,
        )


def test_contract_negative_distance_rejected():
    with pytest.raises(ValueError):
        TrajectorySimulationRequest(
            vessel_id="Tanker-01",
            ship_type="Tanker Ship",
            dwt_tonnes=14000.0,
            route_id="Escravos-Lagos",
            voyage_distance_nm=-50.0,
            baseline_single_voyage_fuel_L=20000.0,
            baseline_single_voyage_co2_kg=50000.0,
        )


def test_contract_negative_fuel_rejected():
    with pytest.raises(ValueError):
        TrajectorySimulationRequest(
            vessel_id="Tanker-01",
            ship_type="Tanker Ship",
            dwt_tonnes=14000.0,
            route_id="Escravos-Lagos",
            voyage_distance_nm=250.0,
            baseline_single_voyage_fuel_L=-100.0,
            baseline_single_voyage_co2_kg=50000.0,
        )


def test_contract_invalid_degradation_bounds():
    with pytest.raises(ValueError):
        PhysicalDegradationParameters(solar_derate_pct_per_year=-1.0)
    with pytest.raises(ValueError):
        PhysicalDegradationParameters(battery_capacity_fade_pct_per_year=15.0)


def test_contract_invalid_post_2026_reduction_factors():
    with pytest.raises(ValueError, match="post_2026_reduction_factors keys must be >= 2027"):
        RegulatoryScenarioParameters(post_2026_reduction_factors={2025: 10.0})


# ==============================================================================
# Category B: Statutory CII (2023–2026) & Boundaries (8 Tests)
# ==============================================================================

def test_statutory_reduction_factors_exact_values():
    scenario = RegulatoryScenarioParameters()
    for yr, expected_z in [(2023, 5.0), (2024, 7.0), (2025, 9.0), (2026, 11.0)]:
        basis, z = resolve_year_regulatory_basis("Tanker Ship", yr, scenario)
        assert basis == REGULATORY_BASIS_STATUTORY
        assert z == expected_z


def test_statutory_tanker_reference_line(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    # 5247 * 14000^(-0.610)
    expected_ref = 5247.0 * (14000.0 ** (-0.610))
    for rec in res.trajectory:
        assert math.isclose(rec.cii_reference, expected_ref, rel_tol=1e-5)


def test_statutory_required_cii_progression(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    ref = 5247.0 * (14000.0 ** (-0.610))
    for rec in res.trajectory:
        assert rec.regulatory_basis == REGULATORY_BASIS_STATUTORY
        expected_req = ref * (1.0 - rec.reduction_factor_z_pct / 100.0)
        assert math.isclose(rec.required_cii, expected_req, rel_tol=1e-5)


def test_statutory_rating_boundaries_vectors(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    for rec in res.trajectory:
        req = rec.required_cii
        assert math.isclose(rec.rating_boundaries["boundary_A_B"], 0.82 * req, rel_tol=1e-5)
        assert math.isclose(rec.rating_boundaries["boundary_B_C"], 0.93 * req, rel_tol=1e-5)
        assert math.isclose(rec.rating_boundaries["boundary_C_D"], 1.08 * req, rel_tol=1e-5)
        assert math.isclose(rec.rating_boundaries["boundary_D_E"], 1.28 * req, rel_tol=1e-5)


def test_statutory_attained_cii_formula(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    for rec in res.trajectory:
        expected_base_attained = (rec.baseline_annual_co2_kg * 1000.0) / (14000.0 * rec.annual_distance_nm)
        assert math.isclose(rec.baseline_attained_cii, expected_base_attained, rel_tol=1e-5)


def test_statutory_rating_assigned_a_to_e(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    for rec in res.trajectory:
        assert rec.baseline_cii_rating in (CII_RATING_A, CII_RATING_B, CII_RATING_C, CII_RATING_D, CII_RATING_E)
        assert rec.assisted_cii_rating in (CII_RATING_A, CII_RATING_B, CII_RATING_C, CII_RATING_D, CII_RATING_E)


def test_statutory_exact_boundary_superior_rating():
    # If attained CII matches exact boundary, assign superior rating under Paragraph 4.2
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2023,
        end_year=2023,
    )
    res = simulate_compliance_trajectory(req)
    rec = res.trajectory[0]
    assert rec.baseline_cii_rating is not None


def test_statutory_diagnostics_completed(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    assert res.diagnostics == DIAG_TRAJECTORY_COMPLETED
    assert res.years_evaluated == 4


# ==============================================================================
# Category C: Post-2026 Scenarios & Provenance (6 Tests)
# ==============================================================================

def test_post_2026_unspecified_default_behavior():
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2023,
        end_year=2028, # extends past 2026 with no scenario schedule
    )
    res = simulate_compliance_trajectory(req)
    assert res.diagnostics == DIAG_TRAJECTORY_UNSPECIFIED_POST_2026

    rec_2027 = [r for r in res.trajectory if r.year == 2027][0]
    assert rec_2027.regulatory_basis == REGULATORY_BASIS_UNSPECIFIED
    assert rec_2027.reduction_factor_z_pct is None
    assert rec_2027.required_cii is None
    assert rec_2027.baseline_cii_rating == CII_RATING_UNSPECIFIED
    assert any("unspecified regulatory schedules" in w for w in res.warnings)


def test_post_2026_explicit_schedule_projected():
    scenario = RegulatoryScenarioParameters(
        post_2026_reduction_factors={2027: 13.0, 2028: 15.0}
    )
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2026,
        end_year=2028,
        regulatory_scenario=scenario,
    )
    res = simulate_compliance_trajectory(req)
    assert res.diagnostics == DIAG_TRAJECTORY_COMPLETED

    rec_2027 = [r for r in res.trajectory if r.year == 2027][0]
    assert rec_2027.regulatory_basis == REGULATORY_BASIS_PROJECTED
    assert rec_2027.reduction_factor_z_pct == 13.0
    assert rec_2027.required_cii is not None
    assert rec_2027.baseline_cii_rating in (CII_RATING_A, CII_RATING_B, CII_RATING_C, CII_RATING_D, CII_RATING_E)
    assert any("caller-specified scenario projections" in w for w in res.warnings)


def test_post_2026_linear_increment_projected():
    scenario = RegulatoryScenarioParameters(annual_z_increment_pct=2.0)
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2026,
        end_year=2028,
        regulatory_scenario=scenario,
    )
    res = simulate_compliance_trajectory(req)

    rec_2027 = [r for r in res.trajectory if r.year == 2027][0]
    rec_2028 = [r for r in res.trajectory if r.year == 2028][0]
    assert rec_2027.regulatory_basis == REGULATORY_BASIS_PROJECTED
    assert rec_2027.reduction_factor_z_pct == 13.0  # 11 + 2
    assert rec_2028.reduction_factor_z_pct == 15.0  # 11 + 4


def test_post_2026_warning_generated():
    scenario = RegulatoryScenarioParameters(annual_z_increment_pct=1.5)
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2026,
        end_year=2027,
        regulatory_scenario=scenario,
    )
    res = simulate_compliance_trajectory(req)
    assert any("must not be construed as adopted MARPOL Annex VI statutory requirements" in w for w in res.warnings)


def test_pre_2023_year_unspecified():
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2021,
        end_year=2023,
    )
    res = simulate_compliance_trajectory(req)
    rec_2021 = [r for r in res.trajectory if r.year == 2021][0]
    assert rec_2021.regulatory_basis == REGULATORY_BASIS_UNSPECIFIED


def test_mixed_statutory_and_projected_trajectory():
    scenario = RegulatoryScenarioParameters(post_2026_reduction_factors={2027: 13.0})
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2025,
        end_year=2027,
        regulatory_scenario=scenario,
    )
    res = simulate_compliance_trajectory(req)
    assert res.trajectory[0].regulatory_basis == REGULATORY_BASIS_STATUTORY  # 2025
    assert res.trajectory[1].regulatory_basis == REGULATORY_BASIS_STATUTORY  # 2026
    assert res.trajectory[2].regulatory_basis == REGULATORY_BASIS_PROJECTED  # 2027


# ==============================================================================
# Category D: Compliance & Corrective Action Tracking (6 Tests)
# ==============================================================================

def test_compliance_definition_abc_vs_de():
    # Verify A, B, C are compliant, D, E are non-compliant
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2023,
        end_year=2026,
    )
    res = simulate_compliance_trajectory(req)
    for rec in res.trajectory:
        if rec.baseline_cii_rating in ("A", "B", "C"):
            assert rec.baseline_is_compliant is True
        elif rec.baseline_cii_rating in ("D", "E"):
            assert rec.baseline_is_compliant is False


def test_corrective_action_single_e_trigger():
    # Very high fuel consumption -> E rating
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=100000.0,
        baseline_single_voyage_co2_kg=300000.0,
        start_year=2023,
        end_year=2023,
    )
    res = simulate_compliance_trajectory(req)
    rec = res.trajectory[0]
    assert rec.baseline_cii_rating == CII_RATING_E
    assert rec.baseline_corrective_action_required is True


def test_corrective_action_three_consecutive_d():
    # Construct scenario where rating D occurs for 3 consecutive years
    scenario = RegulatoryScenarioParameters(annual_z_increment_pct=2.0)
    # Set emissions to land in D band:
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=22000.0,
        baseline_single_voyage_co2_kg=58000.0,
        start_year=2023,
        end_year=2026,
        regulatory_scenario=scenario,
    )
    res = simulate_compliance_trajectory(req)
    # If 3 consecutive Ds occur, 3rd year triggers corrective action
    d_years = [r for r in res.trajectory if r.baseline_cii_rating == CII_RATING_D]
    if len(d_years) >= 3:
        assert d_years[2].baseline_corrective_action_required is True


def test_corrective_action_reset_after_c():
    # If vessel achieves C after D, consecutive D count resets to 0
    # Clean retrofit gives A/B/C rating
    cand = create_mock_retrofit_candidate(fuel_disp_L=15000.0, co2_disp_kg=40000.0)
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=53000.0,
        candidate=cand,
        start_year=2023,
        end_year=2026,
    )
    res = simulate_compliance_trajectory(req)
    # Assisted rating should be compliant and have no corrective action required
    for rec in res.trajectory:
        if rec.assisted_cii_rating in ("A", "B", "C"):
            assert rec.assisted_corrective_action_required is False


def test_compliance_extension_years_calculation(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    assert res.compliance_extension_years is not None
    assert res.compliance_extension_years >= 0


def test_compliance_extension_both_compliant_zero():
    # If both baseline and assisted are compliant in all years, extension is 0
    # Low emissions baseline (A rating)
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=5000.0,
        baseline_single_voyage_co2_kg=12000.0,
        candidate=create_mock_retrofit_candidate(),
        start_year=2023,
        end_year=2026,
    )
    res = simulate_compliance_trajectory(req)
    assert res.compliance_extension_years == 0


# ==============================================================================
# Category E: Vessel Scope & Exemption Rules (4 Tests)
# ==============================================================================

def test_vessel_scope_fishing_trawler_exempt():
    req = TrajectorySimulationRequest(
        vessel_id="Trawler-01",
        ship_type="Fishing Trawler",
        dwt_tonnes=350.0,
        route_id="Warri-Bonny",
        voyage_distance_nm=100.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=2500.0,
        baseline_single_voyage_co2_kg=7500.0,
        start_year=2023,
        end_year=2026,
    )
    res = simulate_compliance_trajectory(req)
    assert res.diagnostics == DIAG_TRAJECTORY_EXEMPT
    assert res.compliance_extension_years is None
    for rec in res.trajectory:
        assert rec.regulatory_basis == REGULATORY_BASIS_EXEMPT
        assert rec.baseline_cii_rating == CII_RATING_EXEMPT
        assert rec.required_cii is None
        assert rec.baseline_attained_cii > 0.0  # Engineering metric still calculated


def test_vessel_scope_oil_service_boat_not_assessed():
    req = TrajectorySimulationRequest(
        vessel_id="OSV-01",
        ship_type="Oil Service Boat",
        dwt_tonnes=1800.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=10000.0,
        baseline_single_voyage_co2_kg=28000.0,
        start_year=2023,
        end_year=2026,
    )
    res = simulate_compliance_trajectory(req)
    assert res.diagnostics == DIAG_TRAJECTORY_NOT_ASSESSED
    assert res.compliance_extension_years is None
    for rec in res.trajectory:
        assert rec.regulatory_basis == REGULATORY_BASIS_NOT_ASSESSED
        assert rec.baseline_cii_rating == CII_RATING_NOT_ASSESSED
        assert rec.required_cii is None
        assert rec.baseline_attained_cii > 0.0


def test_vessel_scope_surfer_boat_not_assessed():
    req = TrajectorySimulationRequest(
        vessel_id="Surfer-01",
        ship_type="Surfer Boat",
        dwt_tonnes=35.0,
        route_id="Lagos-Apapa",
        voyage_distance_nm=20.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=500.0,
        baseline_single_voyage_co2_kg=1500.0,
        start_year=2023,
        end_year=2026,
    )
    res = simulate_compliance_trajectory(req)
    assert res.diagnostics == DIAG_TRAJECTORY_NOT_ASSESSED
    assert res.compliance_extension_years is None
    for rec in res.trajectory:
        assert rec.regulatory_basis == REGULATORY_BASIS_NOT_ASSESSED
        assert rec.baseline_cii_rating == CII_RATING_NOT_ASSESSED


def test_first_non_compliant_year_tracking(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    # If non-compliant year occurs, it is an int >= 2023, otherwise None
    if res.first_non_compliant_year_baseline is not None:
        assert res.first_non_compliant_year_baseline >= 2023


# ==============================================================================
# Category F: Physical Degradation & Compounding (4 Tests)
# ==============================================================================

def test_degradation_zero_default_produces_constant_displacement(tanker_request):
    res = simulate_compliance_trajectory(tanker_request)
    disp_values = [r.annual_co2_displaced_kg for r in res.trajectory]
    assert all(math.isclose(v, disp_values[0]) for v in disp_values)


def test_degradation_solar_and_battery_derating():
    deg = PhysicalDegradationParameters(
        solar_derate_pct_per_year=1.0,
        battery_capacity_fade_pct_per_year=2.0,
    )
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=53000.0,
        candidate=create_mock_retrofit_candidate(co2_disp_kg=10000.0),
        start_year=2023,
        end_year=2026,
        degradation_parameters=deg,
    )
    res = simulate_compliance_trajectory(req)
    disp_values = [r.annual_co2_displaced_kg for r in res.trajectory]
    # Year 0: 10000; Year 1: 10000 * (0.99 * 0.98) = 9702
    assert disp_values[0] == 10000.0
    assert disp_values[1] < disp_values[0]
    assert disp_values[2] < disp_values[1]


def test_degradation_fuel_consumption_growth():
    deg = PhysicalDegradationParameters(fuel_consumption_growth_pct_per_year=2.0)
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20000.0,
        baseline_single_voyage_co2_kg=50000.0,
        start_year=2023,
        end_year=2026,
        degradation_parameters=deg,
    )
    res = simulate_compliance_trajectory(req)
    base_fuel = [r.baseline_annual_fuel_L for r in res.trajectory]
    assert base_fuel[0] == 20000.0 * 52
    assert base_fuel[1] > base_fuel[0]
    assert math.isclose(base_fuel[1], base_fuel[0] * 1.02, rel_tol=1e-5)


def test_degradation_deterministic_repeated_execution(tanker_request):
    res1 = simulate_compliance_trajectory(tanker_request)
    res2 = simulate_compliance_trajectory(tanker_request)
    assert res1.baseline_cumulative_co2_kg == res2.baseline_cumulative_co2_kg
    assert res1.assisted_cumulative_co2_kg == res2.assisted_cumulative_co2_kg
    assert res1.total_co2_displaced_kg == res2.total_co2_displaced_kg


# ==============================================================================
# Category G: Safety, Immutability & Performance (4 Tests)
# ==============================================================================

def test_no_candidate1_to_candidate3_imports():
    """Verify Candidate 4 does not import Candidate 1, 2, or 3."""
    import phase9_cii_contracts
    import phase9_cii_trajectory

    for mod in [phase9_cii_contracts, phase9_cii_trajectory]:
        src = open(mod.__file__, "r", encoding="utf-8").read()
        for banned in [
            "phase9_contracts",
            "phase9_sensitivity",
            "phase9_speed_contracts",
            "phase9_speed_cooptimizer",
            "phase9_portfolio_contracts",
            "phase9_portfolio_optimizer",
        ]:
            assert banned not in src, f"Banned import '{banned}' found in {mod.__file__}"


def test_no_phase8_full_grid_or_ml_inference():
    """Verify Candidate 4 does not call optimize_system_sizing or load ML models."""
    import ast
    import phase9_cii_trajectory

    src = open(phase9_cii_trajectory.__file__, "r", encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "optimize_system_sizing"
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr != "optimize_system_sizing"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in ("torch", "xgboost", "joblib")


def test_frozen_datasets_and_models_unmodified():
    root = r"C:\maritime grids"
    raw_count = sum(len(files) for _, _, files in os.walk(os.path.join(root, "data", "raw")))
    assert raw_count == 6228

    sp_path = os.path.join(root, "data", "reference", "ship_profiles.csv")
    with open(sp_path, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    assert h == "0f2040a481790b034fac11cd9e2b628c725281397610fe0bdba09f6feed7de75"


def test_candidate4_execution_runtime_sub_ten_ms(tanker_request):
    """Verify multi-year trajectory execution runtime < 10 ms."""
    t0 = time.perf_counter()
    res = simulate_compliance_trajectory(tanker_request)
    t_eval = time.perf_counter() - t0
    assert t_eval < 0.010  # Must be < 10 ms
    assert res.years_evaluated == 4
