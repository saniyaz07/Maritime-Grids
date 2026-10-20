"""
app.facade — Integration Facade Foundation for Frozen Phase 0–9 Core.
Phase 10A Application Layer.
"""

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

__all__ = [
    "FacadeOperationEnum",
    "FacadeProvenanceMetadata",
    "FacadeResponse",
    "SimulateVoyageRequest",
    "EvaluateSizingCandidateRequest",
    "OptimizeSystemSizingRequest",
    "SensitivityAnalysisRequest",
    "BreakEvenAnalysisRequest",
    "Grid2DAnalysisRequest",
    "SpeedCoOptimizationFacadeRequest",
    "PortfolioOptimizationFacadeRequest",
    "CIIComplianceTrajectoryRequest",
    "DossierExportFacadeRequest",
    "MaritimeScenarioFacade",
    "FacadeError",
    "FacadeValidationError",
    "FacadeExecutionError",
]
