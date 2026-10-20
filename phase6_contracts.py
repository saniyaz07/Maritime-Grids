"""
phase6_contracts.py — Pydantic V2 Contracts for Phase 6 Gateway & Regulatory Layer
==================================================================================
Defines:
  - VoyageSimulationRequest: High-level user inputs for automated simulation
  - CIIAssessmentResult: Statutory IMO MEPC.353(78) / MEPC.354(78) rating results
  - PollutantEmissionFactors: Parametric emission factors for marine diesel generators
  - PollutantAssessmentResult: Deterministic engineering estimates for NOx, SOx, and PM
  - Phase6SimulationResult: Unified top-level simulation response
"""

from typing import Dict, Any, Optional, List, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    Phase3Output,
    AuditMetadata,
)

# Supported project vessel types
VALID_SHIP_TYPES = [
    "Oil Service Boat",
    "Fishing Trawler",
    "Surfer Boat",
    "Tanker Ship",
]

# Supported project route corridors
VALID_ROUTES = [
    "Warri-Bonny",
    "Escravos-Lagos",
    "Lagos-Apapa",
    "Port Harcourt-Lagos",
]

# Supported fuel types
VALID_FUEL_TYPES = ["Diesel", "HFO"]

# Supported IMO CII assessment years and annual reduction factors (Z%)
# Source: MARPOL Annex VI Regulation 28.4 & Resolution MEPC.338(76)
IMO_CII_REDUCTION_FACTORS: Dict[int, float] = {
    2023: 5.0,
    2024: 7.0,
    2025: 9.0,
    2026: 11.0,
}


# ==============================================================================
# 1. User Voyage Simulation Request
# ==============================================================================
class VoyageSimulationRequest(BaseModel):
    """
    User-level entry point parameters for automated voyage simulation.
    The gateway automatically resolves ship specifications, route distances,
    marine and solar climatology, executes Phase 2 ML models, and evaluates
    Phase 3 feasibility, displacement, and Phase 6 regulatory/pollutant impacts.
    """
    ship_type: str = Field(
        ...,
        description="Vessel archetype: Oil Service Boat, Fishing Trawler, Surfer Boat, or Tanker Ship."
    )
    route_id: str = Field(
        ...,
        description="Corridor name: Warri-Bonny, Escravos-Lagos, Lagos-Apapa, or Port Harcourt-Lagos."
    )
    month: int = Field(
        ...,
        ge=1,
        le=12,
        description="Calendar month of voyage departure (1 to 12)."
    )
    speed_knots: float = Field(
        ...,
        gt=0.0,
        description="Operating sailing speed in knots. Must be strictly positive and <= vessel max speed."
    )
    distance_nm: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Optional explicit voyage distance in nautical miles. If None, resolved from route reference."
    )
    fuel_type: Optional[str] = Field(
        default="Diesel",
        description="Bunker fuel type: Diesel or HFO."
    )
    auxiliary_energy_demand_kwh: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Optional auxiliary hotel/electrical load in kWh. If None, resolved from vessel profile default."
    )
    daily_ghi_kwh_per_m2: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Optional daily GHI in kWh/m2/day. If None, resolved from NASA monthly climatology."
    )
    fuel_price_usd_per_l: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Optional fuel price override in USD/L. If None, uses sourced default (1.15 USD/L)."
    )
    initial_soc: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Initial battery pack State of Charge fraction at departure."
    )
    soc_reserve: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Minimum emergency battery SOC reserve fraction."
    )
    evaluation_year: int = Field(
        default=2026,
        description="Regulatory assessment calendar year for IMO CII reduction factor Z (2023-2026 supported)."
    )

    @field_validator("ship_type")
    @classmethod
    def validate_ship_type(cls, v: str) -> str:
        if v not in VALID_SHIP_TYPES:
            raise ValueError(
                f"Invalid ship_type '{v}'. Must be one of: {VALID_SHIP_TYPES}"
            )
        return v

    @field_validator("route_id")
    @classmethod
    def validate_route_id(cls, v: str) -> str:
        if v not in VALID_ROUTES:
            raise ValueError(
                f"Invalid route_id '{v}'. Must be one of: {VALID_ROUTES}"
            )
        return v

    @field_validator("fuel_type")
    @classmethod
    def validate_fuel_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_FUEL_TYPES:
            raise ValueError(
                f"Invalid fuel_type '{v}'. Must be one of: {VALID_FUEL_TYPES}"
            )
        return v

    @model_validator(mode="after")
    def validate_soc_bounds(self) -> "VoyageSimulationRequest":
        if self.soc_reserve > self.initial_soc:
            raise ValueError(
                f"soc_reserve ({self.soc_reserve}) cannot exceed initial_soc ({self.initial_soc})."
            )
        return self


# ==============================================================================
# 2. IMO Regulatory CII Assessment Contract
# ==============================================================================
class CIIAssessmentResult(BaseModel):
    """
    Statutory IMO MEPC.353(78) / MEPC.354(78) Operational Carbon Intensity Indicator assessment.
    Only Tanker Ship is officially assessable under IMO statutory regulations.
    Other vessel archetypes return NOT_ASSESSED with an explicit machine-readable status.
    """
    vessel_category: Optional[str] = Field(
        default=None,
        description="Official IMO vessel category (e.g. 'Tanker') or None if unsupported/exempt."
    )
    evaluation_year: int = Field(
        default=2026,
        description="Calendar year of evaluation."
    )
    capacity_dwt: float = Field(
        ...,
        gt=0.0,
        description="Vessel deadweight tonnage (DWT)."
    )
    distance_nm: float = Field(
        ...,
        gt=0.0,
        description="Voyage distance in nautical miles."
    )
    baseline_co2_kg: float = Field(
        ...,
        ge=0.0,
        description="Baseline voyage CO2 emissions in kg."
    )
    net_assisted_co2_kg: float = Field(
        ...,
        ge=0.0,
        description="Clean energy net-assisted voyage CO2 emissions in kg."
    )
    baseline_attained_cii: float = Field(
        ...,
        ge=0.0,
        description="Baseline attained operational CII in g CO2 / (DWT * nm)."
    )
    assisted_attained_cii: float = Field(
        ...,
        ge=0.0,
        description="Clean energy assisted attained operational CII in g CO2 / (DWT * nm)."
    )
    cii_reference: Optional[float] = Field(
        default=None,
        description="2019 baseline reference line CII value in g CO2 / (DWT * nm)."
    )
    required_cii: Optional[float] = Field(
        default=None,
        description="Target Required CII for the evaluation year: CII_ref * (1 - Z/100)."
    )
    reduction_factor_z_pct: Optional[float] = Field(
        default=None,
        description="Annual reduction factor Z percentage applied to CII_ref."
    )
    rating_boundaries: Optional[Dict[str, float]] = Field(
        default=None,
        description="Rating band boundary thresholds: boundary_A_B, boundary_B_C, boundary_C_D, boundary_D_E."
    )
    baseline_cii_rating: str = Field(
        ...,
        description="Statutory rating band: 'A', 'B', 'C', 'D', 'E', or 'NOT_ASSESSED'."
    )
    assisted_cii_rating: str = Field(
        ...,
        description="Statutory rating band under clean assistance: 'A', 'B', 'C', 'D', 'E', or 'NOT_ASSESSED'."
    )
    cii_assessment_status: str = Field(
        ...,
        description=(
            "Machine-readable assessment status: 'STATUTORY_ASSESSMENT_COMPLETED', "
            "'UNSUPPORTED_VESSEL_CATEGORY_MAPPING', 'STATUTORILY_EXEMPT', or 'UNSUPPORTED_EVALUATION_YEAR'."
        )
    )
    source_document: str = Field(
        default="IMO Resolution MEPC.353(78) & MEPC.354(78)",
        description="Authoritative regulatory reference source."
    )
    disclaimer: str = Field(
        default=(
            "CII rating bands (A-E) apply strictly to qualifying vessel categories under MARPOL Annex VI Reg 28. "
            "For non-qualifying vessels, numerical CII is reported as an engineering metric, but statutory rating is NOT_ASSESSED."
        ),
        description="Regulatory scope and compliance disclaimer."
    )


# ==============================================================================
# 3. Multi-Pollutant Emissions Contracts
# ==============================================================================
class PollutantEmissionFactors(BaseModel):
    """
    Parametric air pollutant emission factors for marine diesel generator sets.
    Source: Fourth IMO GHG Study (2020) Table 2-8 / EPA Marine Engine Tier II/III.
    """
    nox_kg_per_kg_fuel: float = Field(
        default=0.0570,
        ge=0.0,
        description="Nitrogen Oxides (NOx) emission factor in kg NOx / kg fuel."
    )
    sox_kg_per_kg_fuel: float = Field(
        default=0.0097753,
        ge=0.0,
        description="Sulphur Oxides (SOx) emission factor in kg SOx / kg fuel (0.50% S compliant fuel)."
    )
    pm10_kg_per_kg_fuel: float = Field(
        default=0.00110,
        ge=0.0,
        description="Particulate Matter PM10 emission factor in kg PM10 / kg fuel."
    )
    pm25_kg_per_kg_fuel: float = Field(
        default=0.00101,
        ge=0.0,
        description="Particulate Matter PM2.5 emission factor in kg PM2.5 / kg fuel."
    )
    fuel_density_kg_per_l: float = Field(
        default=0.850,
        gt=0.0,
        description="Fuel density in kg/L (0.85 for MDO/Diesel, 0.95 for HFO)."
    )
    source_reference: str = Field(
        default="Fourth IMO GHG Study (2020) Table 2-8 / MARPOL Annex VI Reg 14",
        description="Authoritative source citation for emission factors."
    )


class PollutantAssessmentResult(BaseModel):
    """
    Deterministic engineering estimates for avoided air pollutants (NOx, SOx, PM).
    Distinguished strictly from statutory regulatory CO2/CII accounting.
    """
    baseline_fuel_L: float = Field(
        ...,
        ge=0.0,
        description="Baseline voyage fuel consumption in Liters."
    )
    net_assisted_fuel_L: float = Field(
        ...,
        ge=0.0,
        description="Clean energy net-assisted voyage fuel consumption in Liters."
    )
    fuel_displaced_L: float = Field(
        ...,
        ge=0.0,
        description="Fuel displaced by auxiliary clean energy in Liters."
    )
    baseline_nox_kg: float = Field(..., ge=0.0, description="Baseline NOx mass in kg.")
    assisted_nox_kg: float = Field(..., ge=0.0, description="Assisted NOx mass in kg.")
    avoided_nox_kg: float = Field(..., ge=0.0, description="Avoided NOx mass in kg.")
    baseline_sox_kg: float = Field(..., ge=0.0, description="Baseline SOx mass in kg.")
    assisted_sox_kg: float = Field(..., ge=0.0, description="Assisted SOx mass in kg.")
    avoided_sox_kg: float = Field(..., ge=0.0, description="Avoided SOx mass in kg.")
    baseline_pm10_kg: float = Field(..., ge=0.0, description="Baseline PM10 mass in kg.")
    assisted_pm10_kg: float = Field(..., ge=0.0, description="Assisted PM10 mass in kg.")
    avoided_pm10_kg: float = Field(..., ge=0.0, description="Avoided PM10 mass in kg.")
    baseline_pm25_kg: float = Field(..., ge=0.0, description="Baseline PM2.5 mass in kg.")
    assisted_pm25_kg: float = Field(..., ge=0.0, description="Assisted PM2.5 mass in kg.")
    avoided_pm25_kg: float = Field(..., ge=0.0, description="Avoided PM2.5 mass in kg.")
    emission_factor_source: str = Field(
        default="Fourth IMO GHG Study (2020) Table 2-8",
        description="Source reference for emission factors."
    )
    assessment_status: str = Field(
        default="ENGINEERING_ESTIMATE",
        description="Classification label: 'ENGINEERING_ESTIMATE'."
    )
    disclaimer: str = Field(
        default="Pollutant figures are engineering estimates derived from auxiliary engine fuel displacement.",
        description="Engineering estimate disclaimer."
    )


# ==============================================================================
# 4. Top-Level Phase 6 Simulation Result Contract
# ==============================================================================
class Phase6SimulationResult(BaseModel):
    """
    Unified Phase 6 simulation output combining user request, Phase 2 model
    predictions, Phase 3 orchestrated tier results, IMO regulatory assessment,
    multi-pollutant air quality analysis, and audit provenance.
    """
    request: VoyageSimulationRequest = Field(
        ...,
        description="User-level simulation request parameters."
    )
    tier1_predictions: Tier1Phase2Predictions = Field(
        ...,
        description="Phase 2 ML predictions generated by the automated gateway."
    )
    phase3_output: Phase3Output = Field(
        ...,
        description="Full Phase 3 orchestrated voyage evaluation."
    )
    regulatory_assessment: CIIAssessmentResult = Field(
        ...,
        description="IMO MEPC.353(78) / MEPC.354(78) regulatory CII evaluation."
    )
    pollutant_assessment: PollutantAssessmentResult = Field(
        ...,
        description="Multi-pollutant (NOx, SOx, PM) air quality displacement assessment."
    )
    audit_metadata: AuditMetadata = Field(
        ...,
        description="Cryptographic and provenance audit metadata."
    )
