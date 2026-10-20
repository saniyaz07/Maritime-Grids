"""
app/api/engineering.py — Phase 10C.9 Engineering Endpoints Router
==================================================================
Exposes the 10 verified maritime engineering, sizing, optimization, sensitivity,
regulatory trajectory, and scenario dossier generation operations over HTTP.

Key Invariants:
  - Strict delegation to EngineeringService -> MaritimeScenarioFacade.
  - Zero numerical recalculation in router.
  - Zero new physics or arbitrary equations.
  - Pure request validation and response transport serialization.
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_engineering_service
from app.facade.contracts import (
    BreakEvenAnalysisRequest,
    CIIComplianceTrajectoryRequest,
    DossierExportFacadeRequest,
    EvaluateSizingCandidateRequest,
    FacadeResponse,
    Grid2DAnalysisRequest,
    OptimizeSystemSizingRequest,
    PortfolioOptimizationFacadeRequest,
    SensitivityAnalysisRequest,
    SimulateVoyageRequest,
    SpeedCoOptimizationFacadeRequest,
)
from app.services.engineering_service import EngineeringService
from phase6_contracts import Phase6SimulationResult
from phase8_contracts import OptimizationCandidate, OptimizationResult
from phase9_contracts import BreakEvenResult, Grid2DResult, OATSensitivityResult
from phase9_speed_contracts import SpeedCoOptimizationResult
from phase9_portfolio_contracts import PortfolioAllocationResult
from phase9_cii_contracts import TrajectorySimulationResult

router = APIRouter(prefix="/engineering", tags=["Engineering"])


@router.post(
    "/simulate-voyage",
    response_model=FacadeResponse[Phase6SimulationResult],
    status_code=status.HTTP_200_OK,
    summary="Simulate a single voyage profile",
    description="Delegates to MaritimeScenarioFacade to execute Phase 6 physics & regulatory simulation.",
)
def simulate_voyage(
    request: SimulateVoyageRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[Phase6SimulationResult]:
    return service.simulate_voyage(request)


@router.post(
    "/evaluate-sizing",
    response_model=FacadeResponse[OptimizationCandidate],
    status_code=status.HTTP_200_OK,
    summary="Evaluate a single sizing candidate",
    description="Evaluates battery and solar sizing candidate with technical feasibility and emissions metrics.",
)
def evaluate_sizing(
    request: EvaluateSizingCandidateRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[OptimizationCandidate]:
    return service.evaluate_sizing_candidate(request)


@router.post(
    "/optimize-sizing",
    response_model=FacadeResponse[OptimizationResult],
    status_code=status.HTTP_200_OK,
    summary="Optimize battery and solar system sizing",
    description="Executes Phase 8 multi-objective optimization across Pareto frontier.",
)
def optimize_sizing(
    request: OptimizeSystemSizingRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[OptimizationResult]:
    return service.optimize_system_sizing(request)


@router.post(
    "/sensitivity-analysis",
    response_model=FacadeResponse[OATSensitivityResult],
    status_code=status.HTTP_200_OK,
    summary="Run one-at-a-time sensitivity analysis",
    description="Executes Phase 9 economic sensitivity variations across fuel, capex, and discount rates.",
)
def sensitivity_analysis(
    request: SensitivityAnalysisRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[OATSensitivityResult]:
    return service.run_sensitivity_analysis(request)


@router.post(
    "/break-even-analysis",
    response_model=FacadeResponse[BreakEvenResult],
    status_code=status.HTTP_200_OK,
    summary="Run break-even economic analysis",
    description="Computes payback period and break-even points under various fuel and carbon price scenarios.",
)
def break_even_analysis(
    request: BreakEvenAnalysisRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[BreakEvenResult]:
    return service.run_break_even_analysis(request)


@router.post(
    "/grid-2d-analysis",
    response_model=FacadeResponse[Grid2DResult],
    status_code=status.HTTP_200_OK,
    summary="Run 2D parameter grid scan",
    description="Evaluates economic and environmental performance across a 2D parameter sweep.",
)
def grid_2d_analysis(
    request: Grid2DAnalysisRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[Grid2DResult]:
    return service.run_2d_grid_analysis(request)


@router.post(
    "/speed-cooptimization",
    response_model=FacadeResponse[SpeedCoOptimizationResult],
    status_code=status.HTTP_200_OK,
    summary="Optimize operational speed and equipment sizing jointly",
    description="Executes joint speed and sizing co-optimization for minimal voyage cost.",
)
def speed_cooptimization(
    request: SpeedCoOptimizationFacadeRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[SpeedCoOptimizationResult]:
    return service.optimize_speed_and_sizing(request)


@router.post(
    "/portfolio-optimization",
    response_model=FacadeResponse[PortfolioAllocationResult],
    status_code=status.HTTP_200_OK,
    summary="Optimize fleet retrofit portfolio under capital budget",
    description="Executes knapsack/portfolio allocation across multiple vessels given a capex limit.",
)
def portfolio_optimization(
    request: PortfolioOptimizationFacadeRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[PortfolioAllocationResult]:
    return service.optimize_fleet_portfolio(request)


@router.post(
    "/cii-trajectory",
    response_model=FacadeResponse[TrajectorySimulationResult],
    status_code=status.HTTP_200_OK,
    summary="Simulate multi-year CII trajectory and compliance standing",
    description="Projects year-over-year IMO CII ratings and emission reduction trajectories.",
)
def cii_trajectory(
    request: CIIComplianceTrajectoryRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[TrajectorySimulationResult]:
    return service.simulate_cii_trajectory(request)


@router.post(
    "/export-dossier",
    response_model=FacadeResponse[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="Export comprehensive multi-scenario engineering dossier",
    description="Packages complete simulation, optimization, economics, and CII data into a single scenario dossier.",
)
def export_dossier(
    request: DossierExportFacadeRequest,
    service: EngineeringService = Depends(get_engineering_service),
) -> FacadeResponse[Dict[str, Any]]:
    return service.export_scenario_dossier(request)
