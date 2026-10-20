"""
phase3_displacement.py — Maritime Grid Simulation, Phase 3 Tier 4 Displacement Calculations
===========================================================================================
Implementation of Tier 4: Clean-Energy Auxiliary-Assisted Voyage scenario estimates.

Calculates generator-equivalent energy displacement from clean energy:
  1. Fuel displacement (Liters) based on auxiliary generator SFOC and fuel density.
  2. CO2 emissions displacement (kg) based on fuel density and carbon factor.
  3. Net assisted voyage fuel consumption, CO2 emissions, and fuel cost.
  4. Net assisted operational Carbon Intensity Indicator (CII).
  5. Percentage reductions relative to unassisted baseline.
  6. Conformance to Tier4EngineeringScenarioEstimates Pydantic contract.

CRITICAL ARCHITECTURAL BOUNDARIES & CONSERVATION INVARIANTS:
  - Phase 2 ML model (fuel_xgb.joblib) predicts TOTAL voyage fuel consumption.
  - No ML decomposition into propulsion vs auxiliary fuel exists in Phase 2.
  - Tier 4 is strictly an ENGINEERING SCENARIO ESTIMATE assuming 100% of clean energy
    utilized (clean_energy_utilized_kwh) displaces auxiliary diesel generator (ADG) output.
  - Main propulsion fuel is NOT displaced.
  - Displaced fuel CANNOT exceed total predicted baseline fuel.
  - Displaced CO2 CANNOT exceed baseline predicted CO2.
  - All outputs retain status="ENGINEERING SCENARIO ESTIMATE".
"""

import math
from typing import Dict, Any, Union

from phase3_contracts import (
    Tier4EngineeringScenarioEstimates,
    Tier3CleanEnergyFeasibility,
)


def calculate_fuel_displacement(
    clean_energy_utilized_kwh: float,
    generator_sfoc_kg_per_kwh: float,
    fuel_density_kg_per_l: float,
    predicted_fuel_consumption_L: float,
) -> float:
    """
    Calculate generator-equivalent fuel displacement in Liters.
    
    Formula:
      fuel_displaced_raw_L = clean_energy_utilized_kwh * generator_sfoc_kg_per_kwh / fuel_density_kg_per_l
      estimated_fuel_displaced_L = min(max(0.0, fuel_displaced_raw_L), predicted_fuel_consumption_L)
    
    Validation:
      - clean_energy_utilized_kwh >= 0, finite
      - generator_sfoc_kg_per_kwh > 0, finite
      - fuel_density_kg_per_l > 0, finite
      - predicted_fuel_consumption_L >= 0, finite
    """
    if clean_energy_utilized_kwh is None or not isinstance(clean_energy_utilized_kwh, (int, float)):
        raise ValueError(f"clean_energy_utilized_kwh must be numeric, got {clean_energy_utilized_kwh}")
    if not math.isfinite(clean_energy_utilized_kwh):
        raise ValueError(f"clean_energy_utilized_kwh must be finite, got {clean_energy_utilized_kwh}")
    if clean_energy_utilized_kwh < 0.0:
        raise ValueError(f"clean_energy_utilized_kwh cannot be negative, got {clean_energy_utilized_kwh}")

    if generator_sfoc_kg_per_kwh is None or not isinstance(generator_sfoc_kg_per_kwh, (int, float)):
        raise ValueError(f"generator_sfoc_kg_per_kwh must be numeric, got {generator_sfoc_kg_per_kwh}")
    if not math.isfinite(generator_sfoc_kg_per_kwh):
        raise ValueError(f"generator_sfoc_kg_per_kwh must be finite, got {generator_sfoc_kg_per_kwh}")
    if generator_sfoc_kg_per_kwh <= 0.0:
        raise ValueError(f"generator_sfoc_kg_per_kwh must be strictly positive (> 0), got {generator_sfoc_kg_per_kwh}")

    if fuel_density_kg_per_l is None or not isinstance(fuel_density_kg_per_l, (int, float)):
        raise ValueError(f"fuel_density_kg_per_l must be numeric, got {fuel_density_kg_per_l}")
    if not math.isfinite(fuel_density_kg_per_l):
        raise ValueError(f"fuel_density_kg_per_l must be finite, got {fuel_density_kg_per_l}")
    if fuel_density_kg_per_l <= 0.0:
        raise ValueError(f"fuel_density_kg_per_l must be strictly positive (> 0), got {fuel_density_kg_per_l}")

    if predicted_fuel_consumption_L is None or not isinstance(predicted_fuel_consumption_L, (int, float)):
        raise ValueError(f"predicted_fuel_consumption_L must be numeric, got {predicted_fuel_consumption_L}")
    if not math.isfinite(predicted_fuel_consumption_L):
        raise ValueError(f"predicted_fuel_consumption_L must be finite, got {predicted_fuel_consumption_L}")
    if predicted_fuel_consumption_L < 0.0:
        raise ValueError(f"predicted_fuel_consumption_L cannot be negative, got {predicted_fuel_consumption_L}")

    if clean_energy_utilized_kwh == 0.0 or predicted_fuel_consumption_L == 0.0:
        return 0.0

    raw_displaced_L = (clean_energy_utilized_kwh * generator_sfoc_kg_per_kwh) / fuel_density_kg_per_l
    return float(min(max(0.0, raw_displaced_L), predicted_fuel_consumption_L))


def calculate_co2_displacement(
    estimated_fuel_displaced_L: float,
    fuel_density_kg_per_l: float,
    emission_factor_kgco2_per_kgfuel: float,
    predicted_CO2_kg: float,
) -> float:
    """
    Calculate CO2 emissions displacement in kg.
    
    Formula:
      co2_displaced_raw_kg = estimated_fuel_displaced_L * fuel_density_kg_per_l * emission_factor_kgco2_per_kgfuel
      estimated_co2_displaced_kg = min(max(0.0, co2_displaced_raw_kg), predicted_CO2_kg)
    
    Validation:
      - estimated_fuel_displaced_L >= 0, finite
      - fuel_density_kg_per_l > 0, finite
      - emission_factor_kgco2_per_kgfuel > 0, finite
      - predicted_CO2_kg >= 0, finite
    """
    if estimated_fuel_displaced_L is None or not isinstance(estimated_fuel_displaced_L, (int, float)):
        raise ValueError(f"estimated_fuel_displaced_L must be numeric, got {estimated_fuel_displaced_L}")
    if not math.isfinite(estimated_fuel_displaced_L):
        raise ValueError(f"estimated_fuel_displaced_L must be finite, got {estimated_fuel_displaced_L}")
    if estimated_fuel_displaced_L < 0.0:
        raise ValueError(f"estimated_fuel_displaced_L cannot be negative, got {estimated_fuel_displaced_L}")

    if fuel_density_kg_per_l is None or not isinstance(fuel_density_kg_per_l, (int, float)):
        raise ValueError(f"fuel_density_kg_per_l must be numeric, got {fuel_density_kg_per_l}")
    if not math.isfinite(fuel_density_kg_per_l):
        raise ValueError(f"fuel_density_kg_per_l must be finite, got {fuel_density_kg_per_l}")
    if fuel_density_kg_per_l <= 0.0:
        raise ValueError(f"fuel_density_kg_per_l must be strictly positive (> 0), got {fuel_density_kg_per_l}")

    if emission_factor_kgco2_per_kgfuel is None or not isinstance(emission_factor_kgco2_per_kgfuel, (int, float)):
        raise ValueError(f"emission_factor_kgco2_per_kgfuel must be numeric, got {emission_factor_kgco2_per_kgfuel}")
    if not math.isfinite(emission_factor_kgco2_per_kgfuel):
        raise ValueError(f"emission_factor_kgco2_per_kgfuel must be finite, got {emission_factor_kgco2_per_kgfuel}")
    if emission_factor_kgco2_per_kgfuel <= 0.0:
        raise ValueError(f"emission_factor_kgco2_per_kgfuel must be strictly positive (> 0), got {emission_factor_kgco2_per_kgfuel}")

    if predicted_CO2_kg is None or not isinstance(predicted_CO2_kg, (int, float)):
        raise ValueError(f"predicted_CO2_kg must be numeric, got {predicted_CO2_kg}")
    if not math.isfinite(predicted_CO2_kg):
        raise ValueError(f"predicted_CO2_kg must be finite, got {predicted_CO2_kg}")
    if predicted_CO2_kg < 0.0:
        raise ValueError(f"predicted_CO2_kg cannot be negative, got {predicted_CO2_kg}")

    if estimated_fuel_displaced_L == 0.0 or predicted_CO2_kg == 0.0:
        return 0.0

    raw_displaced_co2 = estimated_fuel_displaced_L * fuel_density_kg_per_l * emission_factor_kgco2_per_kgfuel
    return float(min(max(0.0, raw_displaced_co2), predicted_CO2_kg))


def calculate_net_assisted_metrics(
    predicted_fuel_consumption_L: float,
    predicted_CO2_kg: float,
    estimated_fuel_displaced_L: float,
    estimated_co2_displaced_kg: float,
    fuel_price_usd_per_l: float,
    deadweight_tonnes: float,
    distance_nm: float,
) -> Dict[str, float]:
    """
    Calculate net assisted fuel, CO2, fuel cost, operational CII, and delta percentages.
    """
    if fuel_price_usd_per_l is None or not isinstance(fuel_price_usd_per_l, (int, float)):
        raise ValueError(f"fuel_price_usd_per_l must be numeric, got {fuel_price_usd_per_l}")
    if not math.isfinite(fuel_price_usd_per_l):
        raise ValueError(f"fuel_price_usd_per_l must be finite, got {fuel_price_usd_per_l}")
    if fuel_price_usd_per_l < 0.0:
        raise ValueError(f"fuel_price_usd_per_l cannot be negative, got {fuel_price_usd_per_l}")

    if deadweight_tonnes is None or not isinstance(deadweight_tonnes, (int, float)):
        raise ValueError(f"deadweight_tonnes must be numeric, got {deadweight_tonnes}")
    if not math.isfinite(deadweight_tonnes):
        raise ValueError(f"deadweight_tonnes must be finite, got {deadweight_tonnes}")
    if deadweight_tonnes <= 0.0:
        raise ValueError(f"deadweight_tonnes must be strictly positive (> 0), got {deadweight_tonnes}")

    if distance_nm is None or not isinstance(distance_nm, (int, float)):
        raise ValueError(f"distance_nm must be numeric, got {distance_nm}")
    if not math.isfinite(distance_nm):
        raise ValueError(f"distance_nm must be finite, got {distance_nm}")
    if distance_nm <= 0.0:
        raise ValueError(f"distance_nm must be strictly positive (> 0), got {distance_nm}")

    net_fuel_L = max(0.0, predicted_fuel_consumption_L - estimated_fuel_displaced_L)
    net_co2_kg = max(0.0, predicted_CO2_kg - estimated_co2_displaced_kg)
    net_cost_usd = net_fuel_L * fuel_price_usd_per_l

    baseline_cii = (predicted_CO2_kg * 1000.0) / (deadweight_tonnes * distance_nm)
    net_cii = (net_co2_kg * 1000.0) / (deadweight_tonnes * distance_nm)

    if predicted_fuel_consumption_L > 0.0:
        delta_fuel_pct = ((net_fuel_L - predicted_fuel_consumption_L) / predicted_fuel_consumption_L) * 100.0
    else:
        delta_fuel_pct = 0.0

    if baseline_cii > 0.0:
        delta_cii_pct = ((net_cii - baseline_cii) / baseline_cii) * 100.0
    else:
        delta_cii_pct = 0.0

    return {
        "net_assisted_fuel_L": float(net_fuel_L),
        "net_assisted_co2_kg": float(net_co2_kg),
        "net_assisted_fuel_cost_usd": float(net_cost_usd),
        "net_assisted_operational_cii_gco2_per_dwt_nm": float(net_cii),
        "delta_fuel_pct": float(delta_fuel_pct),
        "delta_cii_pct": float(delta_cii_pct),
    }


def calculate_tier4_engineering_scenario_estimates(
    predicted_fuel_consumption_L: float,
    predicted_CO2_kg: float,
    clean_energy_utilized_kwh: Union[float, Tier3CleanEnergyFeasibility],
    deadweight_tonnes: float,
    distance_nm: float,
    fuel_price_usd_per_l: float,
    generator_sfoc_kg_per_kwh: float = 0.220,
    fuel_density_kg_per_l: float = 0.850,
    emission_factor_kgco2_per_kgfuel: float = 3.114,
) -> Tier4EngineeringScenarioEstimates:
    """
    Orchestrate Tier 4 displacement and assisted voyage metrics calculation.
    
    Returns:
      Validated Tier4EngineeringScenarioEstimates Pydantic instance.
    """
    # Accept clean_energy_utilized_kwh directly as a float or extracted from Tier3CleanEnergyFeasibility
    if isinstance(clean_energy_utilized_kwh, Tier3CleanEnergyFeasibility):
        utilized_kwh = clean_energy_utilized_kwh.clean_energy_utilized_kwh
    else:
        utilized_kwh = clean_energy_utilized_kwh

    # 1. Fuel displacement calculation
    displaced_fuel_L = calculate_fuel_displacement(
        clean_energy_utilized_kwh=utilized_kwh,
        generator_sfoc_kg_per_kwh=generator_sfoc_kg_per_kwh,
        fuel_density_kg_per_l=fuel_density_kg_per_l,
        predicted_fuel_consumption_L=predicted_fuel_consumption_L,
    )

    # 2. CO2 displacement calculation
    displaced_co2_kg = calculate_co2_displacement(
        estimated_fuel_displaced_L=displaced_fuel_L,
        fuel_density_kg_per_l=fuel_density_kg_per_l,
        emission_factor_kgco2_per_kgfuel=emission_factor_kgco2_per_kgfuel,
        predicted_CO2_kg=predicted_CO2_kg,
    )

    # 3. Net assisted metrics
    net_metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=predicted_fuel_consumption_L,
        predicted_CO2_kg=predicted_CO2_kg,
        estimated_fuel_displaced_L=displaced_fuel_L,
        estimated_co2_displaced_kg=displaced_co2_kg,
        fuel_price_usd_per_l=fuel_price_usd_per_l,
        deadweight_tonnes=deadweight_tonnes,
        distance_nm=distance_nm,
    )

    # 4. Construct Tier4 payload
    payload: Dict[str, Any] = {
        "status": "ENGINEERING SCENARIO ESTIMATE",
        "estimated_fuel_displaced_L": displaced_fuel_L,
        "estimated_co2_displaced_kg": displaced_co2_kg,
        "net_assisted_fuel_L": net_metrics["net_assisted_fuel_L"],
        "net_assisted_co2_kg": net_metrics["net_assisted_co2_kg"],
        "net_assisted_fuel_cost_usd": net_metrics["net_assisted_fuel_cost_usd"],
        "net_assisted_operational_cii_gco2_per_dwt_nm": net_metrics["net_assisted_operational_cii_gco2_per_dwt_nm"],
        "delta_fuel_pct": net_metrics["delta_fuel_pct"],
        "delta_cii_pct": net_metrics["delta_cii_pct"],
    }

    return Tier4EngineeringScenarioEstimates.model_validate(payload)
