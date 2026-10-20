"""
tests/test_engineering_service.py — Phase 10C.8 Engineering Service Tests
==========================================================================
Validates that EngineeringService cleanly delegates all 10 engineering capabilities
to MaritimeScenarioFacade, preserves underlying results and diagnostics without
recalculation, validates request schemas, and properly propagates errors.
"""

import pytest
from pydantic import ValidationError

from app.facade.contracts import (
    BreakEvenAnalysisRequest,
    CIIComplianceTrajectoryRequest,
    DossierExportFacadeRequest,
    EvaluateSizingCandidateRequest,
    FacadeOperationEnum,
    FacadeResponse,
    Grid2DAnalysisRequest,
    OptimizeSystemSizingRequest,
    PortfolioOptimizationFacadeRequest,
    SensitivityAnalysisRequest,
    SimulateVoyageRequest,
    SpeedCoOptimizationFacadeRequest,
)
from app.facade.scenario_facade import MaritimeScenarioFacade, FacadeExecutionError
from app.services.engineering_service import EngineeringService
from phase6_contracts import Phase6SimulationResult
from phase7_contracts import FinancialParameters
from phase8_contracts import OptimizationCandidate, OptimizationResult
from phase9_contracts import BreakEvenResult, Grid2DResult, OATSensitivityResult, ParameterSweepBounds
from phase9_speed_contracts import SpeedCoOptimizationResult
from phase9_portfolio_contracts import PortfolioAllocationResult, PortfolioItem
from phase9_portfolio_optimizer import make_portfolio_item
from phase9_cii_contracts import TrajectorySimulationResult
from phase9_dossier_contracts import ExportFormatEnum


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def engineering_service() -> EngineeringService:
    return EngineeringService()


# =====================================================================
# 1. DELEGATION TESTS FOR ALL 10 CAPABILITIES
# =====================================================================

def test_01_simulate_voyage_delegation(engineering_service):
    """Test 1: EngineeringService.simulate_voyage delegates to Phase 6 Gateway."""
    req = SimulateVoyageRequest(
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        month=6,
        speed_knots=12.0,
        distance_nm=250.0,
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
    )
    res = engineering_service.simulate_voyage(req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, Phase6SimulationResult)
    assert res.provenance.operation == FacadeOperationEnum.SIMULATE_VOYAGE
    assert res.data.tier1_predictions.fuel_consumption_L.value > 0.0


def test_02_evaluate_sizing_candidate_delegation(engineering_service):
    """Test 2: EngineeringService.evaluate_sizing_candidate delegates to Phase 8."""
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
        daily_ghi_kwh_per_m2=4.5,
        annual_voyages=52,
    )
    res = engineering_service.evaluate_sizing_candidate(req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, OptimizationCandidate)
    assert res.provenance.operation == FacadeOperationEnum.EVALUATE_SIZING_CANDIDATE
    assert res.data.net_present_value_usd is not None


def test_03_optimize_system_sizing_delegation(engineering_service):
    """Test 3: EngineeringService.optimize_system_sizing delegates to Phase 8."""
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
    res = engineering_service.optimize_system_sizing(req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, OptimizationResult)
    assert res.provenance.operation == FacadeOperationEnum.OPTIMIZE_SYSTEM_SIZING


def test_04_run_sensitivity_analysis_delegation(engineering_service):
    """Test 4: EngineeringService.run_sensitivity_analysis delegates to Candidate 1."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = engineering_service.optimize_system_sizing(opt_req).data.optimal_candidate

    sens_req = SensitivityAnalysisRequest(
        base_candidate=base_cand,
        parameter_name="fuel_price_usd_per_l",
        metric_name="net_present_value_usd",
        ship_type="Surfer Boat",
    )
    res = engineering_service.run_sensitivity_analysis(sens_req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, OATSensitivityResult)
    assert res.provenance.operation == FacadeOperationEnum.RUN_SENSITIVITY_ANALYSIS


def test_05_run_break_even_analysis_delegation(engineering_service):
    """Test 5: EngineeringService.run_break_even_analysis delegates to Candidate 1."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = engineering_service.optimize_system_sizing(opt_req).data.optimal_candidate

    be_req = BreakEvenAnalysisRequest(
        base_candidate=base_cand,
        parameter_name="fuel_price_usd_per_l",
        metric_name="net_present_value_usd",
        lower_bound=0.5,
        upper_bound=5.0,
        ship_type="Surfer Boat",
    )
    res = engineering_service.run_break_even_analysis(be_req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, BreakEvenResult)
    assert res.provenance.operation == FacadeOperationEnum.RUN_BREAK_EVEN_ANALYSIS


def test_06_run_2d_grid_analysis_delegation(engineering_service):
    """Test 6: EngineeringService.run_2d_grid_analysis delegates to Candidate 1."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = engineering_service.optimize_system_sizing(opt_req).data.optimal_candidate

    grid_req = Grid2DAnalysisRequest(
        base_candidate=base_cand,
        parameter_x_name="fuel_price_usd_per_l",
        parameter_y_name="discount_rate",
        sweep_bounds_x=ParameterSweepBounds(parameter_name="fuel_price_usd_per_l", min_value=0.8, max_value=1.2, step=0.2),
        sweep_bounds_y=ParameterSweepBounds(parameter_name="discount_rate", min_value=0.06, max_value=0.10, step=0.02),
        ship_type="Surfer Boat",
    )
    res = engineering_service.run_2d_grid_analysis(grid_req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, Grid2DResult)
    assert res.provenance.operation == FacadeOperationEnum.RUN_2D_GRID_ANALYSIS


def test_07_optimize_speed_and_sizing_delegation(engineering_service):
    """Test 7: EngineeringService.optimize_speed_and_sizing delegates to Candidate 2."""
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
    res = engineering_service.optimize_speed_and_sizing(req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, SpeedCoOptimizationResult)
    assert res.provenance.operation == FacadeOperationEnum.OPTIMIZE_SPEED_AND_SIZING


def test_08_optimize_fleet_portfolio_delegation(engineering_service):
    """Test 8: EngineeringService.optimize_fleet_portfolio delegates to Candidate 3."""
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Tanker Ship",
        min_solar_area_m2=0.0,
        max_solar_area_m2=50.0,
        step_solar_area_m2=50.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
    )
    cand = engineering_service.optimize_system_sizing(opt_req).data.optimal_candidate

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
    res = engineering_service.optimize_fleet_portfolio(req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, PortfolioAllocationResult)
    assert res.provenance.operation == FacadeOperationEnum.OPTIMIZE_FLEET_PORTFOLIO


def test_09_simulate_cii_trajectory_delegation(engineering_service):
    """Test 9: EngineeringService.simulate_cii_trajectory delegates to Candidate 4."""
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
    res = engineering_service.simulate_cii_trajectory(req)
    assert isinstance(res, FacadeResponse)
    assert isinstance(res.data, TrajectorySimulationResult)
    assert res.provenance.operation == FacadeOperationEnum.SIMULATE_CII_TRAJECTORY


def test_10_export_scenario_dossier_delegation(engineering_service):
    """Test 10: EngineeringService.export_scenario_dossier delegates to Candidate 5."""
    sim_res = engineering_service.simulate_voyage(
        SimulateVoyageRequest(ship_type="Tanker Ship", route_id="Escravos-Lagos", speed_knots=12.0)
    ).data

    req = DossierExportFacadeRequest(
        scenario_name="TEST_SCENARIO",
        vessel_id="VESSEL_01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        export_formats=[ExportFormatEnum.JSON],
        phase6_result=sim_res,
    )
    res = engineering_service.export_scenario_dossier(req)
    assert isinstance(res, FacadeResponse)
    assert "dossier" in res.data
    assert "artifacts" in res.data


# =====================================================================
# 2. VALIDATION & ERROR PROPAGATION TESTS
# =====================================================================

def test_11_request_type_validation(engineering_service):
    """Test 11: EngineeringService raises TypeError if wrong request object passed."""
    with pytest.raises(TypeError):
        engineering_service.simulate_voyage("invalid_request_string")

    with pytest.raises(TypeError):
        engineering_service.evaluate_sizing_candidate({"not": "a_request"})


def test_12_facade_exception_propagation():
    """Test 12: Facade exceptions are raised transparently without silent suppression."""
    class FaultyFacade(MaritimeScenarioFacade):
        def simulate_voyage(self, request):
            raise FacadeExecutionError("Simulated Phase 6 Gateway Failure")

    service = EngineeringService(facade=FaultyFacade())
    req = SimulateVoyageRequest(
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        month=6,
        speed_knots=12.0,
        distance_nm=250.0,
    )
    with pytest.raises(FacadeExecutionError) as exc_info:
        service.simulate_voyage(req)
    assert "Simulated Phase 6 Gateway Failure" in str(exc_info.value)


def test_13_no_recalculation_guarantee(engineering_service):
    """Test 13: Numerical outputs directly match underlying facade responses without alteration."""
    req = SimulateVoyageRequest(
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        month=6,
        speed_knots=12.0,
        distance_nm=250.0,
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
    )
    facade_res = engineering_service.facade.simulate_voyage(req)
    service_res = engineering_service.simulate_voyage(req)

    assert service_res.data.tier1_predictions.fuel_consumption_L.value == facade_res.data.tier1_predictions.fuel_consumption_L.value
    assert service_res.data.regulatory_assessment.net_assisted_co2_kg == facade_res.data.regulatory_assessment.net_assisted_co2_kg
