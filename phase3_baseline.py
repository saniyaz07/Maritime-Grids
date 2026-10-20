"""
phase3_baseline.py — Maritime Grid Simulation, Phase 3 Tier 2 Baseline Calculations
===================================================================================
Implementation of unassisted baseline operational calculations for Phase 3 Decision
Coordinator:
  1. Resolved fuel price (sourced default or scenario override)
  2. Baseline fuel OPEX (fuel_L * price_USD_per_L)
  3. Baseline operational CII (co2_kg * 1000 / (dwt_tonnes * distance_nm))
  4. Tier 2 baseline metrics orchestration producing Tier2BaselineMetrics

This module implements unassisted baseline calculations ONLY.
It performs NO clean energy calculations, NO fuel displacement, and NO ML inference.
"""

import math
import os
import csv
from typing import Optional, Dict

from phase3_contracts import (
    Tier2BaselineMetrics,
    SOURCED_FUEL_PRICES_USD_PER_L,
)

DEFAULT_SHIP_PROFILES_CSV = "C:/maritime grids/data/reference/ship_profiles.csv"


def _load_ship_profiles_fuel_prices(csv_path: Optional[str] = None) -> Dict[str, float]:
    """
    Read default fuel prices from data/reference/ship_profiles.csv.
    Falls back to SOURCED_FUEL_PRICES_USD_PER_L if file is unavailable.
    """
    path = csv_path or DEFAULT_SHIP_PROFILES_CSV
    if not os.path.exists(path):
        return dict(SOURCED_FUEL_PRICES_USD_PER_L)

    prices: Dict[str, float] = {}
    try:
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                st = row.get("ship_type", "").strip()
                p_str = row.get("fuel_price_per_litre", "").strip()
                if st and p_str:
                    try:
                        prices[st] = float(p_str)
                    except ValueError:
                        pass
        # Add alias for Tanker if Tanker Ship is present
        if "Tanker Ship" in prices and "Tanker" not in prices:
            prices["Tanker"] = prices["Tanker Ship"]
    except Exception:
        return dict(SOURCED_FUEL_PRICES_USD_PER_L)

    return prices if prices else dict(SOURCED_FUEL_PRICES_USD_PER_L)


def resolve_fuel_price_usd_per_l(
    ship_type: str,
    override_price: Optional[float] = None,
    csv_path: Optional[str] = None,
) -> float:
    """
    Resolve exactly one fuel price (USD/L) for baseline calculations.
    
    Source hierarchy:
      1. If override_price is provided, validate and use it.
      2. Otherwise, resolve vessel default price from ship_profiles.csv.
    
    Raises:
      ValueError: if override is invalid (<= 0, NaN, Inf), or if ship_type is unknown.
    """
    if override_price is not None:
        if not isinstance(override_price, (int, float)):
            raise ValueError(f"fuel_price_override must be numeric, got {type(override_price)}")
        if not math.isfinite(override_price):
            raise ValueError(f"fuel_price_override must be finite, got {override_price}")
        if override_price <= 0.0:
            raise ValueError(f"fuel_price_override must be strictly positive (> 0), got {override_price}")
        return float(override_price)

    if not ship_type or not isinstance(ship_type, str):
        raise ValueError(f"ship_type must be a non-empty string, got {ship_type}")

    ref_prices = _load_ship_profiles_fuel_prices(csv_path)
    clean_type = ship_type.strip()
    if clean_type in ref_prices:
        resolved = ref_prices[clean_type]
    elif clean_type in SOURCED_FUEL_PRICES_USD_PER_L:
        resolved = SOURCED_FUEL_PRICES_USD_PER_L[clean_type]
    else:
        valid_types = list(ref_prices.keys())
        raise ValueError(f"Unknown ship_type '{ship_type}'. Expected one of: {valid_types}")

    if not math.isfinite(resolved) or resolved <= 0.0:
        raise ValueError(f"Resolved default fuel price for '{ship_type}' is invalid: {resolved}")

    return float(resolved)


def calculate_baseline_fuel_cost(
    fuel_consumption_L: float,
    fuel_price_usd_per_l: float,
) -> float:
    """
    Calculate baseline unassisted voyage fuel cost in USD.
    
    Formula:
      baseline_fuel_cost_usd = predicted_fuel_consumption_L * fuel_price_usd_per_l
    
    Validation:
      - fuel_consumption_L: finite, >= 0.0
      - fuel_price_usd_per_l: finite, > 0.0
    """
    if fuel_consumption_L is None or not isinstance(fuel_consumption_L, (int, float)):
        raise ValueError(f"fuel_consumption_L must be numeric, got {fuel_consumption_L}")
    if not math.isfinite(fuel_consumption_L):
        raise ValueError(f"fuel_consumption_L must be finite, got {fuel_consumption_L}")
    if fuel_consumption_L < 0.0:
        raise ValueError(f"fuel_consumption_L cannot be negative, got {fuel_consumption_L}")

    if fuel_price_usd_per_l is None or not isinstance(fuel_price_usd_per_l, (int, float)):
        raise ValueError(f"fuel_price_usd_per_l must be numeric, got {fuel_price_usd_per_l}")
    if not math.isfinite(fuel_price_usd_per_l):
        raise ValueError(f"fuel_price_usd_per_l must be finite, got {fuel_price_usd_per_l}")
    if fuel_price_usd_per_l <= 0.0:
        raise ValueError(f"fuel_price_usd_per_l must be strictly positive (> 0), got {fuel_price_usd_per_l}")

    if fuel_consumption_L == 0.0:
        return 0.0

    return float(fuel_consumption_L * fuel_price_usd_per_l)


def calculate_baseline_operational_cii(
    co2_emissions_kg: float,
    deadweight_tonnes: float,
    distance_nm: float,
) -> float:
    """
    Calculate baseline unassisted operational Carbon Intensity Indicator (CII).
    
    Formula:
      baseline_operational_cii = (predicted_CO2_kg * 1000) / (dwt_tonnes * distance_nm)
    
    Units:
      gCO2 / (DWT-tonne * nautical mile)
      Governing standard: IMO Resolution MEPC.352(78)
    
    Validation:
      - co2_emissions_kg: finite, >= 0.0
      - deadweight_tonnes: finite, > 0.0
      - distance_nm: finite, > 0.0
    """
    if co2_emissions_kg is None or not isinstance(co2_emissions_kg, (int, float)):
        raise ValueError(f"co2_emissions_kg must be numeric, got {co2_emissions_kg}")
    if not math.isfinite(co2_emissions_kg):
        raise ValueError(f"co2_emissions_kg must be finite, got {co2_emissions_kg}")
    if co2_emissions_kg < 0.0:
        raise ValueError(f"co2_emissions_kg cannot be negative, got {co2_emissions_kg}")

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

    if co2_emissions_kg == 0.0:
        return 0.0

    return float((co2_emissions_kg * 1000.0) / (deadweight_tonnes * distance_nm))


def calculate_tier2_baseline(
    ship_type: str,
    predicted_fuel_L: float,
    predicted_co2_kg: float,
    deadweight_tonnes: float,
    distance_nm: float,
    fuel_price_override_usd_per_l: Optional[float] = None,
    csv_path: Optional[str] = None,
) -> Tier2BaselineMetrics:
    """
    Orchestrate Tier 2 unassisted baseline calculations.
    
    Returns:
      Tier2BaselineMetrics instance conforming to the Phase 3 output contract.
    """
    resolved_price = resolve_fuel_price_usd_per_l(
        ship_type=ship_type,
        override_price=fuel_price_override_usd_per_l,
        csv_path=csv_path,
    )

    baseline_fuel_cost = calculate_baseline_fuel_cost(
        fuel_consumption_L=predicted_fuel_L,
        fuel_price_usd_per_l=resolved_price,
    )

    baseline_cii = calculate_baseline_operational_cii(
        co2_emissions_kg=predicted_co2_kg,
        deadweight_tonnes=deadweight_tonnes,
        distance_nm=distance_nm,
    )

    return Tier2BaselineMetrics(
        baseline_fuel_cost_usd=baseline_fuel_cost,
        baseline_operational_cii_gco2_per_dwt_nm=baseline_cii,
        fuel_price_usd_per_l=resolved_price,
    )
