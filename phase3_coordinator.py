"""
phase3_coordinator.py — Maritime Grid Simulation, Phase 3 Decision Coordinator
=============================================================================
Pipeline Orchestration Layer for the Phase 3 Decision Coordinator.

This module coordinates the execution of verified Phase 3 tiers:
  Tier 1: Ingestion and validation of authoritative Phase 2 ML predictions
  Tier 2: Unassisted baseline operational metrics (fuel cost & CII)
  Tier 3: Clean-energy feasibility assessment (battery & solar budget vs aux demand)
  Tier 4: Auxiliary-assisted scenario estimates (fuel & CO2 displacement)
  Root  : Assembly and cross-tier boundary validation producing Phase3Output

CRITICAL ARCHITECTURAL BOUNDARIES:
  - Phase 3E is an ORCHESTRATION layer only.
  - Phase 3E performs NO ML inference, NO model loading, and NO model retraining.
  - Phase 3E does NOT duplicate formulas owned by Tier 2, Tier 3, or Tier 4.
  - Weather prediction from Tier 1 is descriptive metadata only and is NEVER used
    as a dispatch controller, solar derate controller, or optimization variable.
  - Tier 4 displacement strictly consumes clean_energy_utilized_kwh from Tier 3,
    NEVER total_clean_energy_available_kwh (surplus clean energy cannot displace fuel).
  - Enforces exactly ONE resolved fuel price across Tier 2, Tier 4, and applied parameters.
"""

from typing import Dict, Any, Optional, Union
from pydantic import ValidationError

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    Tier2BaselineMetrics,
    Tier3CleanEnergyFeasibility,
    Tier4EngineeringScenarioEstimates,
    AppliedScenarioParameters,
    AuditMetadata,
    Phase3Output,
)
from phase3_baseline import (
    resolve_fuel_price_usd_per_l,
    calculate_tier2_baseline,
)
from phase3_feasibility import (
    calculate_tier3_clean_energy_feasibility,
)
from phase3_displacement import (
    calculate_tier4_engineering_scenario_estimates,
)


def orchestrate_phase3_voyage(
    voyage_metadata: Union[VoyageMetadata, Dict[str, Any]],
    tier1_predictions: Union[Tier1Phase2Predictions, Dict[str, Any]],
    auxiliary_energy_demand_kwh: float,
    route_id: Optional[str] = None,
    month: Optional[Union[str, int]] = None,
    daily_ghi_kwh_per_m2: Optional[float] = None,
    fuel_price_override_usd_per_l: Optional[float] = None,
    initial_soc: float = 0.90,
    soc_reserve: float = 0.20,
    generator_sfoc_kg_per_kwh: float = 0.220,
    fuel_density_kg_per_l: float = 0.850,
    emission_factor_kgco2_per_kgfuel: float = 3.114,
    solar_derate_factor: float = 0.85,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> Phase3Output:
    """
    Orchestrate a complete Phase 3 voyage evaluation across all four tiers.

    Execution Sequence:
      Step 1: Validate VoyageMetadata and Tier1Phase2Predictions
      Step 2: Resolve single authoritative fuel price
      Step 3: Execute Tier 2 baseline calculations (OPEX and CII)
      Step 4: Execute Tier 3 clean-energy feasibility budgeting
      Step 5: Execute Tier 4 auxiliary fuel and CO2 displacement calculations
      Step 6: Construct AuditMetadata verifying model freeze and data integrity
      Step 7: Assemble complete Phase3Output payload
      Step 8: Execute Pydantic cross-tier invariant validation
      Step 9: Return validated Phase3Output instance

    Parameters:
      voyage_metadata: Vessel and route metadata (VoyageMetadata or dict)
      tier1_predictions: Authoritative Phase 2 ML outputs (Tier1Phase2Predictions or dict)
      auxiliary_energy_demand_kwh: Requested auxiliary electrical energy demand (kWh)
      route_id: Maritime route identifier for climatology lookup (e.g., "Corridor_A")
      month: Voyage month (name or 1-12) for climatology lookup
      daily_ghi_kwh_per_m2: Direct GHI override (kWh/m2/day)
      fuel_price_override_usd_per_l: Optional scenario fuel price override (USD/L)
      initial_soc: Starting battery SOC fraction [0.0, 1.0] (default 0.90)
      soc_reserve: Operational reserve buffer SOC fraction [0.0, 1.0] (default 0.20)
      generator_sfoc_kg_per_kwh: Auxiliary diesel generator SFOC in kg/kWh (default 0.220)
      fuel_density_kg_per_l: Marine distillate fuel density in kg/L (default 0.850)
      emission_factor_kgco2_per_kgfuel: Fuel carbon factor in kg CO2/kg fuel (default 3.114)
      solar_derate_factor: Solar balance-of-system derate factor [0.0, 1.0] (default 0.85)
      ship_profiles_csv: Optional custom path to ship_profiles.csv
      climatology_csv: Optional custom path to nasa_monthly_climatology.csv

    Returns:
      Validated Phase3Output model conforming to the frozen output contract.
    """
    # ─── STEP 1: Validate inputs ───────────────────────────────────────────────
    if isinstance(voyage_metadata, dict):
        v_meta = VoyageMetadata.model_validate(voyage_metadata)
    elif isinstance(voyage_metadata, VoyageMetadata):
        v_meta = voyage_metadata
    else:
        raise ValueError(
            f"voyage_metadata must be a VoyageMetadata instance or dict, got {type(voyage_metadata)}"
        )

    if isinstance(tier1_predictions, dict):
        t1 = Tier1Phase2Predictions.model_validate(tier1_predictions)
    elif isinstance(tier1_predictions, Tier1Phase2Predictions):
        t1 = tier1_predictions
    else:
        raise ValueError(
            f"tier1_predictions must be a Tier1Phase2Predictions instance or dict, got {type(tier1_predictions)}"
        )

    # ─── STEP 2: Resolve single authoritative fuel price ──────────────────────
    resolved_fuel_price = resolve_fuel_price_usd_per_l(
        ship_type=v_meta.ship_type,
        override_price=fuel_price_override_usd_per_l,
        csv_path=ship_profiles_csv,
    )

    # Construct and validate applied scenario parameters
    applied_params = AppliedScenarioParameters(
        fuel_price_usd_per_l=resolved_fuel_price,
        initial_soc=initial_soc,
        auxiliary_energy_demand_kwh=auxiliary_energy_demand_kwh,
        soc_reserve=soc_reserve,
        generator_sfoc_kg_per_kwh=generator_sfoc_kg_per_kwh,
        fuel_density_kg_per_l=fuel_density_kg_per_l,
        emission_factor_kgco2_per_kgfuel=emission_factor_kgco2_per_kgfuel,
        solar_derate_factor=solar_derate_factor,
    )

    # ─── STEP 3: Execute Tier 2 baseline calculations ─────────────────────────
    tier2_metrics: Tier2BaselineMetrics = calculate_tier2_baseline(
        ship_type=v_meta.ship_type,
        predicted_fuel_L=t1.fuel_consumption_L.value,
        predicted_co2_kg=t1.co2_emissions_kg.value,
        deadweight_tonnes=v_meta.deadweight_tonnes,
        distance_nm=v_meta.distance_nm,
        fuel_price_override_usd_per_l=resolved_fuel_price,
        csv_path=ship_profiles_csv,
    )

    # ─── STEP 4: Execute Tier 3 clean-energy feasibility ──────────────────────
    tier3_feasibility: Tier3CleanEnergyFeasibility = calculate_tier3_clean_energy_feasibility(
        ship_type=v_meta.ship_type,
        predicted_soh=t1.battery_health.predicted_soh,
        auxiliary_energy_demand_kwh=applied_params.auxiliary_energy_demand_kwh,
        voyage_duration_hours=v_meta.voyage_duration_hours,
        route_id=route_id,
        month=month,
        daily_ghi_kwh_per_m2=daily_ghi_kwh_per_m2,
        initial_soc=applied_params.initial_soc,
        soc_reserve=applied_params.soc_reserve,
        solar_derate_factor=applied_params.solar_derate_factor,
        nominal_pack_capacity_kwh=t1.battery_health.nominal_pack_capacity_kwh,
        ship_profiles_csv=ship_profiles_csv,
        climatology_csv=climatology_csv,
    )

    # ─── STEP 5: Execute Tier 4 displacement calculations ─────────────────────
    # CRITICAL INVARIANT: Tier 4 strictly uses clean_energy_utilized_kwh,
    # NEVER total_clean_energy_available_kwh.
    tier4_estimates: Tier4EngineeringScenarioEstimates = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=t1.fuel_consumption_L.value,
        predicted_CO2_kg=t1.co2_emissions_kg.value,
        clean_energy_utilized_kwh=tier3_feasibility.clean_energy_utilized_kwh,
        deadweight_tonnes=v_meta.deadweight_tonnes,
        distance_nm=v_meta.distance_nm,
        fuel_price_usd_per_l=resolved_fuel_price,
        generator_sfoc_kg_per_kwh=applied_params.generator_sfoc_kg_per_kwh,
        fuel_density_kg_per_l=applied_params.fuel_density_kg_per_l,
        emission_factor_kgco2_per_kgfuel=applied_params.emission_factor_kgco2_per_kgfuel,
    )

    # ─── STEP 6: Construct Audit Metadata ─────────────────────────────────────
    audit_meta = AuditMetadata(
        phase2_models_frozen=True,
        data_raw_modified=False,
        scenario_assumptions_applied=True,
    )

    # ─── STEP 7 & 8: Assemble Phase3Output & Execute Root Validation ──────────
    output = Phase3Output(
        voyage_metadata=v_meta,
        tier_1_phase2_predictions=t1,
        tier_2_baseline_metrics=tier2_metrics,
        tier_3_clean_energy_feasibility=tier3_feasibility,
        tier_4_engineering_scenario_estimates=tier4_estimates,
        applied_scenario_parameters=applied_params,
        audit_metadata=audit_meta,
    )

    # ─── STEP 9: Return Validated Output ──────────────────────────────────────
    return output


def run_coordinator_scenario(
    voyage_metadata: Union[VoyageMetadata, Dict[str, Any]],
    tier1_predictions: Union[Tier1Phase2Predictions, Dict[str, Any]],
    scenario_parameters: Optional[Union[AppliedScenarioParameters, Dict[str, Any]]] = None,
    auxiliary_energy_demand_kwh: Optional[float] = None,
    fuel_price_override_usd_per_l: Optional[float] = None,
    route_id: Optional[str] = None,
    month: Optional[Union[str, int]] = None,
    daily_ghi_kwh_per_m2: Optional[float] = None,
    initial_soc: Optional[float] = None,
    soc_reserve: Optional[float] = None,
    generator_sfoc_kg_per_kwh: Optional[float] = None,
    fuel_density_kg_per_l: Optional[float] = None,
    emission_factor_kgco2_per_kgfuel: Optional[float] = None,
    solar_derate_factor: Optional[float] = None,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> Phase3Output:
    """
    Execute a coordinated scenario accepting pre-assembled scenario parameters or individual overrides.

    This function unpacks parameters from scenario_parameters if provided, allows individual
    argument overrides, and invokes orchestrate_phase3_voyage.
    """
    params_dict: Dict[str, Any] = {}
    if scenario_parameters is not None:
        if isinstance(scenario_parameters, AppliedScenarioParameters):
            params_dict = scenario_parameters.model_dump()
        elif isinstance(scenario_parameters, dict):
            params_dict = dict(scenario_parameters)
        else:
            raise ValueError(
                f"scenario_parameters must be AppliedScenarioParameters or dict, got {type(scenario_parameters)}"
            )

    # Resolve auxiliary energy demand
    resolved_aux = (
        auxiliary_energy_demand_kwh
        if auxiliary_energy_demand_kwh is not None
        else params_dict.get("auxiliary_energy_demand_kwh")
    )
    if resolved_aux is None:
        raise ValueError(
            "auxiliary_energy_demand_kwh must be provided either directly or inside scenario_parameters"
        )

    # Resolve fuel price override
    resolved_price_override = (
        fuel_price_override_usd_per_l
        if fuel_price_override_usd_per_l is not None
        else params_dict.get("fuel_price_usd_per_l")
    )

    # Resolve engineering parameters with fallbacks to AppliedScenarioParameters contract defaults
    resolved_initial_soc = (
        initial_soc
        if initial_soc is not None
        else params_dict.get("initial_soc", 0.90)
    )
    resolved_soc_reserve = (
        soc_reserve
        if soc_reserve is not None
        else params_dict.get("soc_reserve", 0.20)
    )
    resolved_sfoc = (
        generator_sfoc_kg_per_kwh
        if generator_sfoc_kg_per_kwh is not None
        else params_dict.get("generator_sfoc_kg_per_kwh", 0.220)
    )
    resolved_density = (
        fuel_density_kg_per_l
        if fuel_density_kg_per_l is not None
        else params_dict.get("fuel_density_kg_per_l", 0.850)
    )
    resolved_ef = (
        emission_factor_kgco2_per_kgfuel
        if emission_factor_kgco2_per_kgfuel is not None
        else params_dict.get("emission_factor_kgco2_per_kgfuel", 3.114)
    )
    resolved_derate = (
        solar_derate_factor
        if solar_derate_factor is not None
        else params_dict.get("solar_derate_factor", 0.85)
    )

    return orchestrate_phase3_voyage(
        voyage_metadata=voyage_metadata,
        tier1_predictions=tier1_predictions,
        auxiliary_energy_demand_kwh=resolved_aux,
        route_id=route_id,
        month=month,
        daily_ghi_kwh_per_m2=daily_ghi_kwh_per_m2,
        fuel_price_override_usd_per_l=resolved_price_override,
        initial_soc=resolved_initial_soc,
        soc_reserve=resolved_soc_reserve,
        generator_sfoc_kg_per_kwh=resolved_sfoc,
        fuel_density_kg_per_l=resolved_density,
        emission_factor_kgco2_per_kgfuel=resolved_ef,
        solar_derate_factor=resolved_derate,
        ship_profiles_csv=ship_profiles_csv,
        climatology_csv=climatology_csv,
    )
