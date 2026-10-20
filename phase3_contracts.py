"""
phase3_contracts.py — Maritime Grid Simulation, Phase 3 Decision Coordinator Contracts
======================================================================================
Frozen Four-Tier Architecture Contracts & Pydantic Schemas.

Tier 1: Phase 2 ML Predictions (Untouched Authoritative Outputs)
Tier 2: Deterministic Baseline Metrics (Unassisted Voyage OPEX & CII)
Tier 3: Clean Energy Feasibility (Battery & Solar Available Budget vs Auxiliary Demand)
Tier 4: Engineering Scenario Estimates (Auxiliary Fuel & CO2 Displacement)

This module defines data contracts, boundary validation, and provenance tracking ONLY.
It performs NO machine learning inference, optimization, or business calculations.
"""

from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field, model_validator


# ==============================================================================
# Provenance Constants (Frozen Phase 2 Model Hashes)
# ==============================================================================
FROZEN_MODEL_HASHES: Dict[str, str] = {
    "weather_final.joblib": "39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3",
    "fuel_xgb.joblib": "cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323",
    "battery_soc_lstm.pt": "c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25",
    "battery_soh_final.joblib": "9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1",
}

# Sourced fuel price defaults per vessel type from data/reference/ship_profiles.csv
SOURCED_FUEL_PRICES_USD_PER_L: Dict[str, float] = {
    "Oil Service Boat": 1.15,
    "Fishing Trawler": 1.10,
    "Surfer Boat": 1.20,
    "Tanker Ship": 0.95,
    "Tanker": 0.95,  # Convenient alias
}


def get_sourced_fuel_price(ship_type: str) -> float:
    """Return the sourced fuel price (USD/L) from ship_profiles.csv for the given ship type."""
    if ship_type in SOURCED_FUEL_PRICES_USD_PER_L:
        return SOURCED_FUEL_PRICES_USD_PER_L[ship_type]
    raise ValueError(
        f"Unknown ship_type '{ship_type}'. Expected one of: {list(SOURCED_FUEL_PRICES_USD_PER_L.keys())}"
    )


# ==============================================================================
# Voyage Metadata
# ==============================================================================
class VoyageMetadata(BaseModel):
    """Voyage specification and vessel identification."""
    ship_type: str = Field(..., min_length=1, description="Vessel type name matching ship_profiles.csv")
    distance_nm: float = Field(..., gt=0.0, description="Voyage distance in nautical miles (must be > 0)")
    voyage_duration_hours: float = Field(..., gt=0.0, description="Estimated voyage duration in hours (must be > 0)")
    deadweight_tonnes: float = Field(..., gt=0.0, description="Vessel deadweight tonnage (must be > 0)")


# ==============================================================================
# Tier 1 — Authoritative Phase 2 ML Predictions
# ==============================================================================
class WeatherPrediction(BaseModel):
    """Phase 2 environmental predictions from models/weather_final.joblib."""
    temperature_c: float = Field(..., description="Ambient temperature in degrees Celsius")
    wind_speed_knots: float = Field(..., ge=0.0, description="Wind speed in knots")
    significant_wave_height_m: float = Field(..., ge=0.0, description="Significant wave height in meters")


class FuelPrediction(BaseModel):
    """Phase 2 fuel consumption prediction from models/fuel_xgb.joblib."""
    value: float = Field(..., ge=0.0, description="Predicted total voyage fuel consumption")
    unit: Literal["Liters"] = Field(
        default="Liters",
        description="Physical unit (Evidence Level B — Strongly Inferred)"
    )
    evidence_level: Literal["B - STRONGLY INFERRED"] = Field(
        default="B - STRONGLY INFERRED",
        description="Data provenance classification"
    )
    scope: Literal["Total voyage fuel consumption"] = Field(
        default="Total voyage fuel consumption",
        description="Operational fuel scope (not decomposed into propulsion/auxiliary)"
    )


class CO2Prediction(BaseModel):
    """Phase 2 baseline CO2 emission prediction from models/fuel_xgb.joblib."""
    value: float = Field(..., ge=0.0, description="Predicted total voyage baseline CO2 emissions in kg")
    unit: Literal["kg"] = Field(default="kg", description="Physical mass unit")


class BatteryHealthPrediction(BaseModel):
    """Phase 2 battery degradation predictions from models/battery_soh_final.joblib."""
    predicted_soh: float = Field(..., ge=0.0, le=1.0, description="Predicted State of Health fraction [0.0, 1.0]")
    nominal_pack_capacity_kwh: float = Field(..., ge=0.0, description="Nameplate nominal pack capacity in kWh")
    effective_pack_capacity_kwh: float = Field(..., ge=0.0, description="Degradation-adjusted effective capacity (nominal * SOH)")


class BatteryOperationPrediction(BaseModel):
    """
    Phase 2 battery operational state from models/battery_soc_lstm.pt.
    Contains ONLY authoritative Phase 2 outputs. initial_soc is an operational scenario input
    and belongs strictly under AppliedScenarioParameters.
    """
    predicted_soc_end_of_voyage: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Authoritative Phase 2 SOH-aware end-of-voyage SOC fraction [0.0, 1.0]"
    )
    soc_formulation: str = Field(
        default="Degradation-adjusted pack SOC",
        description="Description of authoritative Phase 2 SOC formulation"
    )


class Tier1Phase2Predictions(BaseModel):
    """
    Tier 1: Authoritative Phase 2 ML Predictions.
    These values must be ingested directly and NEVER recomputed or substituted in Phase 3.
    """
    weather: WeatherPrediction
    fuel_consumption_L: FuelPrediction
    co2_emissions_kg: CO2Prediction
    battery_health: BatteryHealthPrediction
    battery_operation: BatteryOperationPrediction


# ==============================================================================
# Tier 2 — Deterministic Baseline Metrics
# ==============================================================================
class Tier2BaselineMetrics(BaseModel):
    """
    Tier 2: Unassisted Baseline Metrics.
    Pure deterministic calculations from Phase 2 ML outputs and standard IMO/economic formulas.
    Does NOT include any clean energy displacement or scenario offsets.
    fuel_price_usd_per_l reflects the resolved price used for baseline calculations.
    """
    baseline_fuel_cost_usd: float = Field(..., ge=0.0, description="Baseline unassisted fuel cost in USD")
    baseline_operational_cii_gco2_per_dwt_nm: float = Field(
        ...,
        ge=0.0,
        description="Baseline operational CII in gCO2 / (DWT * nm) per IMO Resolution MEPC.352(78)"
    )
    fuel_price_usd_per_l: float = Field(
        ...,
        ge=0.0,
        description="Resolved fuel price in USD per liter used for baseline fuel cost calculation"
    )


# ==============================================================================
# Tier 3 — Clean Energy Feasibility
# ==============================================================================
class Tier3CleanEnergyFeasibility(BaseModel):
    """
    Tier 3: Clean Energy Feasibility Assessment.
    Evaluates physical battery & solar clean energy availability against requested auxiliary demand.
    """
    auxiliary_energy_demand_kwh: float = Field(..., ge=0.0, description="Requested auxiliary electrical energy demand in kWh")
    usable_battery_energy_kwh: float = Field(..., ge=0.0, description="Available battery energy above operational reserve buffer in kWh")
    estimated_solar_energy_kwh: float = Field(..., ge=0.0, description="Climatological solar energy generation in kWh")
    total_clean_energy_available_kwh: float = Field(..., ge=0.0, description="Total clean energy budget (battery + solar) in kWh")
    clean_energy_utilized_kwh: float = Field(..., ge=0.0, description="Clean energy utilized towards auxiliary load in kWh")
    energy_balance_kwh: float = Field(..., description="Energy balance (total available - demand) in kWh")
    energy_deficit_kwh: float = Field(..., ge=0.0, description="Unmet auxiliary electrical demand in kWh")
    feasibility_status: Literal["FEASIBLE", "PARTIAL"] = Field(
        ...,
        description="FEASIBLE if available >= demand, PARTIAL if clean energy cannot cover full auxiliary demand"
    )
    solar_estimate_diurnal_uncertainty_flag: bool = Field(
        default=False,
        description="Informational flag set to True when voyage_duration_hours > 24.0, indicating higher diurnal modeling uncertainty"
    )



# ==============================================================================
# Tier 4 — Engineering Scenario Estimates
# ==============================================================================
class Tier4EngineeringScenarioEstimates(BaseModel):
    """
    Tier 4: Engineering Scenario Estimates.
    Auxiliary fuel and CO2 displacement estimates based on assumed generator SFOC and fuel density.
    Strictly isolated from ML predictions and guarded against exceeding total voyage fuel/CO2.
    """
    status: Literal["ENGINEERING SCENARIO ESTIMATE"] = Field(
        default="ENGINEERING SCENARIO ESTIMATE",
        description="Mandatory classification identifying outputs as scenario estimates"
    )
    disclaimer: str = Field(
        default=(
            "Auxiliary fuel and CO2 displacement values are engineering scenario estimates "
            "based on assumed generator SFOC and fuel density. They are NOT derived from a "
            "validated machine-learning propulsion-vs-auxiliary decomposition."
        ),
        description="Methodological transparency disclosure"
    )
    estimated_fuel_displaced_L: float = Field(..., ge=0.0, description="Estimated fuel displaced by clean energy in Liters")
    estimated_co2_displaced_kg: float = Field(..., ge=0.0, description="Estimated CO2 mass displaced in kg")
    net_assisted_fuel_L: float = Field(..., ge=0.0, description="Net assisted voyage fuel consumption in Liters")
    net_assisted_co2_kg: float = Field(..., ge=0.0, description="Net assisted voyage CO2 emissions in kg")
    net_assisted_fuel_cost_usd: float = Field(..., ge=0.0, description="Net assisted fuel cost in USD")
    net_assisted_operational_cii_gco2_per_dwt_nm: float = Field(
        ...,
        ge=0.0,
        description="Operational CII under assisted scenario in gCO2 / (DWT * nm)"
    )
    delta_fuel_pct: float = Field(..., description="Percentage change in fuel consumption relative to baseline")
    delta_cii_pct: float = Field(..., description="Percentage change in operational CII relative to baseline")


# ==============================================================================
# Applied Scenario Parameters
# ==============================================================================
class AppliedScenarioParameters(BaseModel):
    """
    Configurable engineering assumptions and economic/operational inputs for Phase 3 scenarios.
    All defaults are transparently documented and overrideable.
    """
    fuel_price_usd_per_l: float = Field(
        ...,
        ge=0.0,
        description="Resolved fuel price in USD per liter (sourced from ship_profiles.csv or scenario override)"
    )
    initial_soc: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Voyage starting battery State of Charge fraction [0.0, 1.0] (operational scenario input)"
    )
    auxiliary_energy_demand_kwh: float = Field(
        ...,
        ge=0.0,
        description="Auxiliary/hotel electrical energy demand for the voyage in kWh"
    )
    soc_reserve: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description="Configurable engineering assumption: minimum operational battery SOC reserve buffer"
    )
    generator_sfoc_kg_per_kwh: float = Field(
        default=0.220,
        gt=0.0,
        description="Configurable engineering assumption: auxiliary diesel generator SFOC in kg/kWh"
    )
    fuel_density_kg_per_l: float = Field(
        default=0.850,
        gt=0.0,
        description="Configurable engineering assumption: marine distillate fuel density in kg/L"
    )
    emission_factor_kgco2_per_kgfuel: float = Field(
        default=3.114,
        gt=0.0,
        description="Configurable engineering assumption: fuel carbon emission factor in kg CO2 / kg fuel"
    )
    solar_derate_factor: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Configurable engineering assumption: solar balance-of-system and thermal derate factor"
    )


# ==============================================================================
# Audit Metadata
# ==============================================================================
class AuditMetadata(BaseModel):
    """Provenance and audit metadata tracking Phase 2 model freeze and data integrity."""
    phase2_models_frozen: bool = Field(default=True, description="Flag verifying Phase 2 models are frozen")
    data_raw_modified: bool = Field(default=False, description="Flag verifying data/raw is untouched")
    scenario_assumptions_applied: bool = Field(default=True, description="Flag confirming scenario assumptions are active")
    model_hashes: Dict[str, str] = Field(
        default_factory=lambda: dict(FROZEN_MODEL_HASHES),
        description="SHA-256 hashes of frozen Phase 2 models"
    )


# ==============================================================================
# Complete Phase 3 Output Schema
# ==============================================================================
class Phase3Output(BaseModel):
    """
    Complete Phase 3 Decision Coordinator Output Contract.
    Enforces strict four-tier hierarchy, provenance metadata, and cross-tier boundary validation.
    """
    voyage_metadata: VoyageMetadata
    tier_1_phase2_predictions: Tier1Phase2Predictions
    tier_2_baseline_metrics: Tier2BaselineMetrics
    tier_3_clean_energy_feasibility: Tier3CleanEnergyFeasibility
    tier_4_engineering_scenario_estimates: Tier4EngineeringScenarioEstimates
    applied_scenario_parameters: AppliedScenarioParameters
    audit_metadata: AuditMetadata = Field(default_factory=AuditMetadata)

    @model_validator(mode="after")
    def validate_cross_tier_invariants(self) -> "Phase3Output":
        """
        Cross-tier boundary and consistency validation:
        1. Exact fuel price alignment between Tier 2 baseline and applied scenario parameters.
        2. Displaced fuel cannot exceed total predicted voyage fuel consumption.
        3. Displaced CO2 cannot exceed total baseline predicted CO2 emissions.
        """
        tier2_price = self.tier_2_baseline_metrics.fuel_price_usd_per_l
        scenario_price = self.applied_scenario_parameters.fuel_price_usd_per_l
        if abs(tier2_price - scenario_price) > 1e-6:
            raise ValueError(
                f"Conflicting fuel prices detected: tier_2_baseline_metrics.fuel_price_usd_per_l ({tier2_price}) "
                f"does not match applied_scenario_parameters.fuel_price_usd_per_l ({scenario_price}). "
                f"There must be exactly ONE resolved fuel price used across the calculation."
            )

        pred_fuel = self.tier_1_phase2_predictions.fuel_consumption_L.value
        displaced_fuel = self.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L
        if displaced_fuel > pred_fuel + 1e-6:
            raise ValueError(
                f"estimated_fuel_displaced_L ({displaced_fuel}) cannot exceed "
                f"total predicted_fuel_consumption_L ({pred_fuel})"
            )

        pred_co2 = self.tier_1_phase2_predictions.co2_emissions_kg.value
        displaced_co2 = self.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg
        if displaced_co2 > pred_co2 + 1e-6:
            raise ValueError(
                f"estimated_co2_displaced_kg ({displaced_co2}) cannot exceed "
                f"baseline predicted_CO2_kg ({pred_co2})"
            )
        return self
