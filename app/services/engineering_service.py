"""
app/services/engineering_service.py — Phase 10C.8 Engineering / Planning Service
=================================================================================
Provides application-level service entry points for engineering, sizing,
optimization, sensitivity, regulatory trajectory, and scenario dossier generation.

Key Invariants:
  - Strict delegation to MaritimeScenarioFacade.
  - Zero recomputation of physics, hydrodynamics, economics, or emissions.
  - Transparent error and diagnostic propagation without silent swallowing.
  - 100% deterministic and offline execution.
"""

from typing import Any, Dict, Optional

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
from app.facade.scenario_facade import (
    FacadeError,
    FacadeExecutionError,
    FacadeValidationError,
    MaritimeScenarioFacade,
)
from phase6_contracts import Phase6SimulationResult
from phase8_contracts import OptimizationCandidate, OptimizationResult
from phase9_contracts import BreakEvenResult, Grid2DResult, OATSensitivityResult
from phase9_speed_contracts import SpeedCoOptimizationResult
from phase9_portfolio_contracts import PortfolioAllocationResult
from phase9_cii_contracts import TrajectorySimulationResult


class EngineeringService:
    """
    Application-facing service for long-horizon engineering, sizing, and fleet planning.
    Wraps MaritimeScenarioFacade to provide clean service interfaces for planning dashboards.
    """

    def __init__(self, facade: Optional[MaritimeScenarioFacade] = None) -> None:
        """
        Initialize the EngineeringService.

        Args:
            facade: Optional MaritimeScenarioFacade instance (instantiates default if None).
        """
        self.facade = facade or MaritimeScenarioFacade()

    def simulate_voyage(
        self,
        request: SimulateVoyageRequest,
    ) -> FacadeResponse[Phase6SimulationResult]:
        """
        Executes single-voyage hydrodynamic, electrical balance, and emissions simulation.
        Delegates directly to MaritimeScenarioFacade.simulate_voyage.
        """
        if not isinstance(request, SimulateVoyageRequest):
            raise TypeError(f"Expected SimulateVoyageRequest, got {type(request)}")
        return self.facade.simulate_voyage(request)

    def evaluate_sizing_candidate(
        self,
        request: EvaluateSizingCandidateRequest,
    ) -> FacadeResponse[OptimizationCandidate]:
        """
        Evaluates a single solar area and battery capacity sizing candidate.
        Delegates directly to MaritimeScenarioFacade.evaluate_sizing_candidate.
        """
        if not isinstance(request, EvaluateSizingCandidateRequest):
            raise TypeError(f"Expected EvaluateSizingCandidateRequest, got {type(request)}")
        return self.facade.evaluate_sizing_candidate(request)

    def optimize_system_sizing(
        self,
        request: OptimizeSystemSizingRequest,
    ) -> FacadeResponse[OptimizationResult]:
        """
        Executes multi-objective parametric system sizing optimization.
        Delegates directly to MaritimeScenarioFacade.optimize_system_sizing.
        """
        if not isinstance(request, OptimizeSystemSizingRequest):
            raise TypeError(f"Expected OptimizeSystemSizingRequest, got {type(request)}")
        return self.facade.optimize_system_sizing(request)

    def run_sensitivity_analysis(
        self,
        request: SensitivityAnalysisRequest,
    ) -> FacadeResponse[OATSensitivityResult]:
        """
        Executes One-At-A-Time (OAT) parameter sensitivity sweeps.
        Delegates directly to MaritimeScenarioFacade.run_sensitivity_analysis.
        """
        if not isinstance(request, SensitivityAnalysisRequest):
            raise TypeError(f"Expected SensitivityAnalysisRequest, got {type(request)}")
        return self.facade.run_sensitivity_analysis(request)

    def run_break_even_analysis(
        self,
        request: BreakEvenAnalysisRequest,
    ) -> FacadeResponse[BreakEvenResult]:
        """
        Solves for 1D break-even thresholds on economic and operational parameters.
        Delegates directly to MaritimeScenarioFacade.run_break_even_analysis.
        """
        if not isinstance(request, BreakEvenAnalysisRequest):
            raise TypeError(f"Expected BreakEvenAnalysisRequest, got {type(request)}")
        return self.facade.run_break_even_analysis(request)

    def run_2d_grid_analysis(
        self,
        request: Grid2DAnalysisRequest,
    ) -> FacadeResponse[Grid2DResult]:
        """
        Evaluates 2D parameter sweep grids for sensitivity heatmaps.
        Delegates directly to MaritimeScenarioFacade.run_2d_grid_analysis.
        """
        if not isinstance(request, Grid2DAnalysisRequest):
            raise TypeError(f"Expected Grid2DAnalysisRequest, got {type(request)}")
        return self.facade.run_2d_grid_analysis(request)

    def optimize_speed_and_sizing(
        self,
        request: SpeedCoOptimizationFacadeRequest,
    ) -> FacadeResponse[SpeedCoOptimizationResult]:
        """
        Executes 3D transit speed, solar area, and battery sizing co-optimization.
        Delegates directly to MaritimeScenarioFacade.optimize_speed_and_sizing.
        """
        if not isinstance(request, SpeedCoOptimizationFacadeRequest):
            raise TypeError(f"Expected SpeedCoOptimizationFacadeRequest, got {type(request)}")
        return self.facade.optimize_speed_and_sizing(request)

    def optimize_fleet_portfolio(
        self,
        request: PortfolioOptimizationFacadeRequest,
    ) -> FacadeResponse[PortfolioAllocationResult]:
        """
        Executes fleet-wide decarbonization capital budget allocation.
        Delegates directly to MaritimeScenarioFacade.optimize_fleet_portfolio.
        """
        if not isinstance(request, PortfolioOptimizationFacadeRequest):
            raise TypeError(f"Expected PortfolioOptimizationFacadeRequest, got {type(request)}")
        return self.facade.optimize_fleet_portfolio(request)

    def simulate_cii_trajectory(
        self,
        request: CIIComplianceTrajectoryRequest,
    ) -> FacadeResponse[TrajectorySimulationResult]:
        """
        Simulates multi-year statutory IMO CII compliance ratings and margins.
        Delegates directly to MaritimeScenarioFacade.simulate_cii_trajectory.
        """
        if not isinstance(request, CIIComplianceTrajectoryRequest):
            raise TypeError(f"Expected CIIComplianceTrajectoryRequest, got {type(request)}")
        return self.facade.simulate_cii_trajectory(request)

    def export_scenario_dossier(
        self,
        request: DossierExportFacadeRequest,
    ) -> FacadeResponse[Dict[str, Any]]:
        """
        Assembles, validates, and serializes cross-phase scenario audit dossiers.
        Delegates directly to MaritimeScenarioFacade.export_scenario_dossier.
        """
        if not isinstance(request, DossierExportFacadeRequest):
            raise TypeError(f"Expected DossierExportFacadeRequest, got {type(request)}")
        return self.facade.export_scenario_dossier(request)
