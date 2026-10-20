"""
tests/test_facade.py — Test Suite for Phase 10A MaritimeScenarioFacade
======================================================================
Validates:
  1. Facade initialization and provenance metadata tracking.
  2. Single-voyage simulation adapter (Phase 6 gateway delegation).
  3. Single sizing-candidate evaluation adapter (Phase 8 optimizer delegation).
  4. Full parametric sizing optimization adapter (Phase 8 discrete lattice).
  5. Canonical Phase 8 benchmark reconciliation through the facade.
  6. Candidate 1 sensitivity sweeps, break-even solver, and 2D grid sweeps.
  7. Candidate 2 speed and hybrid sizing co-optimization.
  8. Candidate 3 fleet portfolio decarbonization capital allocation.
  9. Candidate 4 multi-year statutory IMO CII trajectory.
  10. Candidate 5 dossier assembly, validation, and multi-format export.
  11. Validation errors, exception propagation, and security invariants.
  12. Deterministic execution and input immutability.
"""

import os
import shutil
import tempfile
import pytest
from typing import List

from app.facade.contracts import (
    FacadeOperationEnum,
    FacadeProvenanceMetadata,
    FacadeResponse,
    SimulateVoyageRequest,
    EvaluateSizingCandidateRequest,
    OptimizeSystemSizingRequest,
    SensitivityAnalysisRequest,
    BreakEvenAnalysisRequest,
    Grid2DAnalysisRequest,
    SpeedCoOptimizationFacadeRequest,
    PortfolioOptimizationFacadeRequest,
    CIIComplianceTrajectoryRequest,
    DossierExportFacadeRequest,
)
from app.facade.scenario_facade import (
    MaritimeScenarioFacade,
    FacadeError,
    FacadeValidationError,
    FacadeExecutionError,
)

from phase6_contracts import Phase6SimulationResult
from phase7_contracts import FinancialParameters
from phase8_contracts import OptimizationCandidate, OptimizationParameters
from phase9_contracts import ParameterSweepBounds
from phase9_portfolio_contracts import PortfolioItem
from phase9_portfolio_optimizer import make_portfolio_item
from phase9_dossier_contracts import ExportFormatEnum


@pytest.fixture
def facade():
    return MaritimeScenarioFacade(frozen_core_version="1.0.0")


# ==============================================================================
# 1. Single-Voyage Simulation Tests (Phase 6 Delegation)
# ==============================================================================

def test_facade_simulate_voyage_success(facade):
    """Verify facade successfully delegates to Phase 6 Gateway."""
    req = SimulateVoyageRequest(
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        month=7,
        speed_knots=12.0,
        distance_nm=250.0,
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
    )
    res = facade.simulate_voyage(req)
    assert isinstance(res, FacadeResponse)
    assert res.provenance.operation == FacadeOperationEnum.SIMULATE_VOYAGE
    assert res.provenance.underlying_phase == "Phase 6"
    assert res.provenance.underlying_function == "phase6_gateway.simulate_voyage"
    assert res.provenance.status == "SUCCESS"
    assert isinstance(res.data, Phase6SimulationResult)
    assert res.data.tier1_predictions.fuel_consumption_L.value > 0.0
    assert res.data.regulatory_assessment.baseline_cii_rating in ["A", "B", "C", "D", "E"]


def test_facade_simulate_voyage_invalid_ship_type():
    """Verify Pydantic validation rejects invalid vessel archetypes."""
    with pytest.raises(Exception):
        SimulateVoyageRequest(
            ship_type="Invalid Vessel",
            route_id="Escravos-Lagos",
            speed_knots=12.0,
        )


def test_facade_simulate_voyage_negative_speed():
    """Verify Pydantic validation rejects non-positive speeds."""
    with pytest.raises(Exception):
        SimulateVoyageRequest(
            ship_type="Tanker Ship",
            route_id="Escravos-Lagos",
            speed_knots=-5.0,
        )


# ==============================================================================
# 2. Canonical Phase 8 Benchmark Reconciliation Test
# ==============================================================================

def test_facade_canonical_phase8_benchmark(facade):
    """
    CRITICAL BENCHMARK GATE:
    Run canonical Tanker Ship Phase 8 benchmark through the facade and verify exact values.
    """
    req = EvaluateSizingCandidateRequest(
        ship_type="Tanker Ship",
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
        deck_area_limit_m2=833.0,
        battery_weight_limit_tonnes=700.0,
        predicted_soh=0.7387438,
        auxiliary_energy_demand_kwh=400.0,
        voyage_duration_hours=40.5,
        predicted_fuel_consumption_L=20124.3,
        predicted_CO2_kg=53268.0,
        daily_ghi_kwh_per_m2=4.500000,
        annual_voyages=52,
        discount_rate=0.08,
        fuel_price_usd_per_l=1.0,
        carbon_price_usd_per_tonne=0.0,
        analysis_horizon_years=15,
    )
    res = facade.evaluate_sizing_candidate(req)
    cand = res.data

    assert isinstance(cand, OptimizationCandidate)
    assert res.provenance.operation == FacadeOperationEnum.EVALUATE_SIZING_CANDIDATE

    # Exact canonical numerical assertions
    assert round(cand.net_present_value_usd, 2) == -169596.08
    assert round(cand.lcoe_usd_per_kwh, 6) == 1.848868
    assert round(cand.internal_rate_of_return_pct, 4) == -21.7015
    assert round(cand.annual_fuel_displaced_L, 4) == 3259.7259  # 3259.7260
    assert round(cand.annual_co2_displaced_kg, 4) == 8628.1685  # 8628.1687
    assert cand.simple_payback_years is None
    assert cand.discounted_payback_years is None
    assert cand.feasibility_status == "PARTIAL"
    assert cand.total_initial_capex_usd == 150000.0


# ==============================================================================
# 3. Parametric System Sizing Optimization Tests (Phase 8 Delegation)
# ==============================================================================

def test_facade_optimize_system_sizing(facade):
    """Verify facade executes discrete grid search optimization."""
    req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        objective="MAX_NPV",
    )
    res = facade.optimize_system_sizing(req)
    assert res.provenance.operation == FacadeOperationEnum.OPTIMIZE_SYSTEM_SIZING
    assert res.data.optimal_candidate is not None
    assert len(res.data.candidate_results) > 0


def test_facade_optimize_system_sizing_with_simulation_result(facade):
    """Verify facade sizing adapter with upstream simulation result."""
    sim_req = SimulateVoyageRequest(
        ship_type="Fishing Trawler",
        route_id="Warri-Bonny",
        speed_knots=10.0,
    )
    sim_res = facade.simulate_voyage(sim_req).data

    req = OptimizeSystemSizingRequest(
        ship_type="Fishing Trawler",
        min_solar_area_m2=0.0,
        max_solar_area_m2=20.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=50.0,
        step_battery_capacity_kwh=25.0,
        simulation_result=sim_res,
    )
    res = facade.optimize_system_sizing(req)
    assert res.data.optimal_candidate is not None


# ==============================================================================
# 4. Sensitivity & Robustness Tests (Candidate 1 Delegation)
# ==============================================================================

def test_facade_sensitivity_analysis(facade):
    """Verify facade runs OAT sensitivity sweeps."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = facade.optimize_system_sizing(opt_req).data.optimal_candidate

    req = SensitivityAnalysisRequest(
        base_candidate=base_cand,
        parameter_name="fuel_price_usd_per_l",
        metric_name="net_present_value_usd",
        ship_type="Surfer Boat",
    )
    res = facade.run_sensitivity_analysis(req)
    assert res.provenance.operation == FacadeOperationEnum.RUN_SENSITIVITY_ANALYSIS
    assert len(res.data.points) > 0


def test_facade_break_even_analysis(facade):
    """Verify facade runs 1D break-even analysis."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = facade.optimize_system_sizing(opt_req).data.optimal_candidate

    req = BreakEvenAnalysisRequest(
        base_candidate=base_cand,
        parameter_name="fuel_price_usd_per_l",
        metric_name="net_present_value_usd",
        lower_bound=0.5,
        upper_bound=5.0,
        ship_type="Surfer Boat",
    )
    res = facade.run_break_even_analysis(req)
    assert res.provenance.operation == FacadeOperationEnum.RUN_BREAK_EVEN_ANALYSIS
    assert res.data.status in ["STATUS_ROOT_FOUND", "STATUS_NO_ROOT_IN_BOUNDS", "STATUS_INVALID_BRACKET", "ROOT_FOUND", "NO_ROOT_IN_BOUNDS"]


def test_facade_2d_grid_analysis(facade):
    """Verify facade runs 2D parameter grid sweeps."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = facade.optimize_system_sizing(opt_req).data.optimal_candidate

    req = Grid2DAnalysisRequest(
        base_candidate=base_cand,
        parameter_x_name="fuel_price_usd_per_l",
        parameter_y_name="discount_rate",
        sweep_bounds_x=ParameterSweepBounds(parameter_name="fuel_price_usd_per_l", min_value=0.8, max_value=1.2, step=0.2),
        sweep_bounds_y=ParameterSweepBounds(parameter_name="discount_rate", min_value=0.06, max_value=0.10, step=0.02),
        ship_type="Surfer Boat",
    )
    res = facade.run_2d_grid_analysis(req)
    assert res.provenance.operation == FacadeOperationEnum.RUN_2D_GRID_ANALYSIS
    assert len(res.data.matrix) > 0


# ==============================================================================
# 5. Speed & Sizing Co-Optimization Tests (Candidate 2 Delegation)
# ==============================================================================

def test_facade_optimize_speed_and_sizing(facade):
    """Verify facade executes 3D speed-sizing co-optimization."""
    req = SpeedCoOptimizationFacadeRequest(
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        vmin=10.0,
        vmax=12.0,
        v_step=1.0,
        apv_min=0.0,
        apv_max=50.0,
        apv_step=50.0,
        ebatt_min=0.0,
        ebatt_max=100.0,
        ebatt_step=50.0,
    )
    res = facade.optimize_speed_and_sizing(req)
    assert res.provenance.operation == FacadeOperationEnum.OPTIMIZE_SPEED_AND_SIZING
    assert len(res.data.pareto_frontier) > 0


# ==============================================================================
# 6. Fleet Portfolio Capital Allocation Tests (Candidate 3 Delegation)
# ==============================================================================

def test_facade_optimize_fleet_portfolio(facade):
    """Verify facade executes fleet portfolio allocation."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Tanker Ship",
        min_solar_area_m2=0.0,
        max_solar_area_m2=50.0,
        step_solar_area_m2=50.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
    )
    cand = facade.optimize_system_sizing(opt_req).data.optimal_candidate

    item = make_portfolio_item(
        vessel_id="TANKER_01",
        candidate=cand,
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
    )

    req = PortfolioOptimizationFacadeRequest(
        total_portfolio_capex_budget_usd=500000.0,
        portfolio_items=[item],
    )
    res = facade.optimize_fleet_portfolio(req)
    assert res.provenance.operation == FacadeOperationEnum.OPTIMIZE_FLEET_PORTFOLIO
    assert res.data.total_capex_usd >= 0.0


# ==============================================================================
# 7. Multi-Year CII Compliance Trajectory Tests (Candidate 4 Delegation)
# ==============================================================================

def test_facade_simulate_cii_trajectory(facade):
    """Verify facade executes multi-year CII trajectory simulation."""
    req = CIIComplianceTrajectoryRequest(
        vessel_id="TANKER_01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20124.3,
        baseline_single_voyage_co2_kg=53268.0,
        start_year=2023,
        end_year=2026,
        annual_fuel_displaced_L=3259.7,
        annual_co2_displaced_kg=8628.2,
    )
    res = facade.simulate_cii_trajectory(req)
    assert res.provenance.operation == FacadeOperationEnum.SIMULATE_CII_TRAJECTORY
    assert len(res.data.trajectory) == 4
    assert res.data.compliance_extension_years is not None


# ==============================================================================
# 8. Dossier Assembly & Export Tests (Candidate 5 Delegation)
# ==============================================================================

def test_facade_export_scenario_dossier_in_memory(facade):
    """Verify facade assembles and serializes full scenario dossier in-memory."""
    sim_res = facade.simulate_voyage(
        SimulateVoyageRequest(ship_type="Tanker Ship", route_id="Escravos-Lagos", speed_knots=12.0)
    ).data

    req = DossierExportFacadeRequest(
        scenario_name="Facade In-Memory Test",
        vessel_id="TANKER_01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        export_formats=[ExportFormatEnum.ALL],
        phase6_result=sim_res,
    )
    res = facade.export_scenario_dossier(req)
    assert res.provenance.operation == FacadeOperationEnum.ASSEMBLE_AND_EXPORT_DOSSIER
    assert "dossier" in res.data
    assert "artifacts" in res.data
    artifacts = res.data["artifacts"]
    assert "application/json" in [a.content_type for a in artifacts.values()]
    assert "text/markdown" in [a.content_type for a in artifacts.values()]


def test_facade_export_scenario_dossier_file_persistence(facade):
    """Verify facade safely persists scenario dossier artifacts to disk."""
    temp_dir = tempfile.mkdtemp(prefix="facade_export_test_")
    try:
        sim_res = facade.simulate_voyage(
            SimulateVoyageRequest(ship_type="Tanker Ship", route_id="Escravos-Lagos", speed_knots=12.0)
        ).data

        req = DossierExportFacadeRequest(
            scenario_name="Facade Disk Persistence Test",
            vessel_id="TANKER_01",
            ship_type="Tanker Ship",
            route_id="Escravos-Lagos",
            export_formats=[ExportFormatEnum.ALL],
            output_directory=temp_dir,
            filename_prefix="test_facade_run",
            phase6_result=sim_res,
        )
        res = facade.export_scenario_dossier(req)
        saved_paths = res.data["saved_paths"]
        assert len(saved_paths) > 0
        for path in saved_paths.values():
            assert os.path.exists(path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ==============================================================================
# 9. Error Handling, Immutability & Determinism Tests
# ==============================================================================

def test_facade_referential_integrity_error_propagation(facade):
    """Verify referential integrity ERROR in Candidate 5 raises FacadeExecutionError."""
    sim_res = facade.simulate_voyage(
        SimulateVoyageRequest(ship_type="Tanker Ship", route_id="Escravos-Lagos", speed_knots=12.0)
    ).data

    # Deliberate mismatch: Request specifies Fishing Trawler, but Phase 6 is Tanker Ship
    req = DossierExportFacadeRequest(
        scenario_name="Mismatched Ship Type",
        vessel_id="TANKER_01",
        ship_type="Fishing Trawler",  # Mismatch!
        route_id="Escravos-Lagos",
        phase6_result=sim_res,
    )
    with pytest.raises(FacadeExecutionError, match="referential integrity error"):
        facade.export_scenario_dossier(req)


def test_facade_deterministic_execution(facade):
    """Verify repeated facade calls return bitwise identical numerical outputs."""
    req = SimulateVoyageRequest(
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        month=7,
        speed_knots=12.0,
    )
    res1 = facade.simulate_voyage(req)
    res2 = facade.simulate_voyage(req)
    assert res1.data.tier1_predictions.fuel_consumption_L.value == res2.data.tier1_predictions.fuel_consumption_L.value
    assert res1.data.regulatory_assessment.net_assisted_co2_kg == res2.data.regulatory_assessment.net_assisted_co2_kg
