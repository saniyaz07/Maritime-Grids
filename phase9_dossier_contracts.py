"""
phase9_dossier_contracts.py — Pydantic V2 Contracts for Phase 9 Candidate 5
============================================================================
Integrated Multi-Phase Scenario Dossier & Cross-Phase Export Engine

Defines:
  - ExportFormatEnum: Enumeration of supported output formats (JSON, MARKDOWN, CSVs, ALL).
  - DiagnosticSeverityEnum: ERROR, WARNING, INFO.
  - DossierDiagnostic: Referential integrity audit notice.
  - ExportArtifactResult: Serialized payload container with MIME typing and record counts.
  - CrossPhaseKPISummary: Structured summary of key performance indicators extracted from supplied phases.
  - DossierAssemblyRequest: Top-level ingestion request container.
  - CrossPhaseScenarioDossier: Unified hierarchical dossier data structure.

Architectural boundaries:
  - Pure consumer of upstream Pydantic models (Phases 6, 7, 8 and Candidates 1-4).
  - Zero simulation, optimization, prediction, or recalculation logic.
  - Fully deterministic in-memory serialization with standard MIME content types.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator

from phase6_contracts import Phase6SimulationResult
from phase7_contracts import InvestmentAppraisalResult
from phase8_contracts import OptimizationResult
from phase9_contracts import OATSensitivityResult, BreakEvenResult, Grid2DResult
from phase9_speed_contracts import SpeedCoOptimizationResult
from phase9_portfolio_contracts import PortfolioAllocationResult
from phase9_cii_contracts import TrajectorySimulationResult


# ==============================================================================
# 1. Enums & Diagnostic Constants
# ==============================================================================

class ExportFormatEnum(str, Enum):
    JSON = "JSON"
    MARKDOWN = "MARKDOWN"
    CSV_CASH_FLOWS = "CSV_CASH_FLOWS"
    CSV_PARETO_FRONTIER = "CSV_PARETO_FRONTIER"
    CSV_CII_TRAJECTORY = "CSV_CII_TRAJECTORY"
    ALL = "ALL"


class DiagnosticSeverityEnum(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


SUPPORTED_DOSSIER_SHIP_TYPES: List[str] = [
    "Tanker Ship",
    "Oil Service Boat",
    "Fishing Trawler",
    "Surfer Boat",
]


# ==============================================================================
# 2. Diagnostic & Artifact Contracts
# ==============================================================================

class DossierDiagnostic(BaseModel):
    """
    Referential integrity audit notice or scenario consistency diagnostic.
    """
    severity: str = Field(..., description="Severity level: 'ERROR', 'WARNING', or 'INFO'.")
    code: str = Field(..., min_length=1, description="Machine-readable diagnostic code.")
    message: str = Field(..., min_length=1, description="Human-readable explanation.")
    affected_module: str = Field(..., min_length=1, description="Upstream phase or module identifier.")

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        valid = {"ERROR", "WARNING", "INFO"}
        if v not in valid:
            raise ValueError(f"Invalid severity '{v}'. Must be one of {valid}")
        return v


class ExportArtifactResult(BaseModel):
    """
    Container for an individual serialized export artifact.
    """
    format_type: str = Field(..., description="Export format identifier.")
    content_type: str = Field(..., description="Standard MIME type (application/json, text/markdown, text/csv).")
    raw_content: str = Field(..., description="In-memory serialized string content.")
    record_count: Optional[int] = Field(default=None, ge=0, description="Row/record count for tabular data.")


# ==============================================================================
# 3. Cross-Phase KPI Summary Contract
# ==============================================================================

class CrossPhaseKPISummary(BaseModel):
    """
    Aggregated summary of key technical, economic, and regulatory KPIs
    extracted directly from supplied upstream results without recalculation.
    """
    vessel_id: str
    ship_type: str
    route_id: str
    
    # Physical / Operational KPIs (Phase 6)
    voyage_duration_hours: Optional[float] = None
    baseline_single_voyage_fuel_L: Optional[float] = None
    baseline_single_voyage_co2_kg: Optional[float] = None
    net_assisted_single_voyage_fuel_L: Optional[float] = None
    net_assisted_single_voyage_co2_kg: Optional[float] = None
    
    # Financial / Economic KPIs (Phase 7 / Phase 8)
    total_initial_capex_usd: Optional[float] = None
    net_present_value_usd: Optional[float] = None
    internal_rate_of_return_pct: Optional[float] = None
    simple_payback_years: Optional[float] = None
    discounted_payback_years: Optional[float] = None
    lcoe_usd_per_kwh: Optional[float] = None
    annual_fuel_displaced_L: Optional[float] = None
    annual_co2_displaced_kg: Optional[float] = None
    
    # Sizing Configuration KPIs (Phase 8 / Phase 7)
    solar_area_m2: Optional[float] = None
    battery_capacity_kwh: Optional[float] = None
    sizing_feasibility_status: Optional[str] = None
    
    # Regulatory Compliance KPIs (Phase 6 / Candidate 4)
    baseline_cii_rating: Optional[str] = None
    assisted_cii_rating: Optional[str] = None
    compliance_extension_years: Optional[int] = None
    first_non_compliant_year_baseline: Optional[int] = None
    first_non_compliant_year_assisted: Optional[int] = None


# ==============================================================================
# 4. Dossier Request Contract
# ==============================================================================

class DossierAssemblyRequest(BaseModel):
    """
    Top-level request to assemble, validate, and serialize an integrated multi-phase scenario dossier.
    """
    scenario_name: str = Field(..., min_length=1, description="Human-readable scenario identifier.")
    vessel_id: str = Field(..., min_length=1, description="Vessel identifier.")
    ship_type: str = Field(..., description="Canonical project vessel archetype.")
    route_id: str = Field(..., min_length=1, description="Commercial shipping corridor.")

    # Ingested upstream results (Mode A: >= 1 supplied; Mode B: Phase 6+7+8 supplied)
    phase6_result: Optional[Phase6SimulationResult] = Field(default=None, description="Phase 6 physical/regulatory simulation.")
    phase7_result: Optional[InvestmentAppraisalResult] = Field(default=None, description="Phase 7 lifecycle techno-economics.")
    phase8_result: Optional[OptimizationResult] = Field(default=None, description="Phase 8 system sizing optimization.")

    # Optional Phase 9 analytical extensions
    candidate1_sensitivity: Optional[OATSensitivityResult] = Field(default=None, description="Candidate 1 sensitivity analysis.")
    candidate2_cooptimization: Optional[SpeedCoOptimizationResult] = Field(default=None, description="Candidate 2 speed co-optimization.")
    candidate3_portfolio: Optional[PortfolioAllocationResult] = Field(default=None, description="Candidate 3 fleet portfolio allocation.")
    candidate4_trajectory: Optional[TrajectorySimulationResult] = Field(default=None, description="Candidate 4 multi-year compliance trajectory.")

    export_formats: List[ExportFormatEnum] = Field(
        default=[ExportFormatEnum.ALL],
        min_length=1,
        description="List of requested export formats (e.g. [JSON, MARKDOWN], or [ALL])."
    )

    @field_validator("ship_type")
    @classmethod
    def validate_ship_type(cls, v: str) -> str:
        if v not in SUPPORTED_DOSSIER_SHIP_TYPES:
            raise ValueError(f"Unsupported ship_type '{v}'. Supported: {SUPPORTED_DOSSIER_SHIP_TYPES}")
        return v

    @model_validator(mode="after")
    def validate_at_least_one_phase_supplied(self) -> "DossierAssemblyRequest":
        payloads = [
            self.phase6_result,
            self.phase7_result,
            self.phase8_result,
            self.candidate1_sensitivity,
            self.candidate2_cooptimization,
            self.candidate3_portfolio,
            self.candidate4_trajectory,
        ]
        if all(p is None for p in payloads):
            raise ValueError(
                "At least one phase or candidate result payload must be supplied to assemble a dossier. "
                "All supplied payloads were None."
            )
        return self


# ==============================================================================
# 5. Top-Level Dossier Result Contract
# ==============================================================================

class CrossPhaseScenarioDossier(BaseModel):
    """
    Unified hierarchical schema-validated dossier envelope.
    """
    metadata: Dict[str, Any] = Field(..., description="Dossier generation metadata and engine version.")
    scenario: Dict[str, Any] = Field(..., description="Scenario identity and commercial parameters.")
    
    # Ingested Phase Models (serialized with stable null for omitted sections)
    phase6: Optional[Phase6SimulationResult] = None
    phase7: Optional[InvestmentAppraisalResult] = None
    phase8: Optional[OptimizationResult] = None
    
    # Ingested Candidate Models
    candidate1: Optional[OATSensitivityResult] = None
    candidate2: Optional[SpeedCoOptimizationResult] = None
    candidate3: Optional[PortfolioAllocationResult] = None
    candidate4: Optional[TrajectorySimulationResult] = None
    
    cross_phase_kpis: CrossPhaseKPISummary = Field(..., description="Summary KPIs extracted across available phases.")
    diagnostics: List[DossierDiagnostic] = Field(default_factory=list, description="Referential integrity audit notices.")
    audit_metadata: Dict[str, Any] = Field(..., description="Audit provenance, immutability hashes, and timestamp record.")
