"""
phase3_feasibility.py — Maritime Grid Simulation, Phase 3 Tier 3 Clean Energy Feasibility
========================================================================================
Implementation of clean-energy feasibility budgeting:
  1. Effective battery capacity (nominal_pack_capacity_kwh * predicted_soh)
  2. Usable battery energy (effective_capacity * max(0, initial_soc - soc_reserve))
  3. NASA POWER monthly solar climatology lookup (ALLSKY_SFC_SW_DWN)
  4. Deterministic climatological solar generation estimate
  5. Clean energy balance, deficit, and feasibility status (FEASIBLE vs PARTIAL)
  6. Tier 3 clean-energy feasibility orchestration returning Tier3CleanEnergyFeasibility

CRITICAL ARCHITECTURAL LIMITATIONS & BOUNDARIES:
  - Solar generation is an ENGINEERING SCENARIO ESTIMATE based on monthly average daily GHI.
    It is NOT an hourly dynamic simulation. Multiplying by (duration / 24) assumes average
    daily insolation scaling, which does not model day/night diurnal variations.
  - Phase 2 weather model (weather_final.joblib) is descriptive context only (34.72% baseline)
    and must NOT be used to gate or condition dispatch or solar derating.
  - Phase 3C does NOT implement generator displacement, fuel savings, or Tier 4 calculations.
"""

import os
import csv
import math
from typing import Dict, Any, Optional, Union

from phase3_contracts import Tier3CleanEnergyFeasibility

DEFAULT_SHIP_PROFILES_CSV = "C:/maritime grids/data/reference/ship_profiles.csv"
DEFAULT_NASA_CLIMATOLOGY_CSV = "C:/maritime grids/data/processed/nasa_power/nasa_monthly_climatology.csv"

# Month name mapping for robust climatology lookup
MONTH_NAME_TO_NUM: Dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Verified default hardware parameters from ship_profiles.csv (for robust fallback)
SOURCED_HARDWARE_SPECS: Dict[str, Dict[str, float]] = {
    "Oil Service Boat": {
        "nominal_pack_capacity_kwh": 649.7280,
        "solar_panel_size_m2": 80.0,
        "solar_panel_efficiency_pct": 21.5,
    },
    "Fishing Trawler": {
        "nominal_pack_capacity_kwh": 250.2144,
        "solar_panel_size_m2": 45.0,
        "solar_panel_efficiency_pct": 21.0,
    },
    "Surfer Boat": {
        "nominal_pack_capacity_kwh": 149.9904,
        "solar_panel_size_m2": 25.0,
        "solar_panel_efficiency_pct": 22.0,
    },
    "Tanker Ship": {
        "nominal_pack_capacity_kwh": 1199.9232,
        "solar_panel_size_m2": 250.0,
        "solar_panel_efficiency_pct": 21.5,
    },
    "Tanker": {
        "nominal_pack_capacity_kwh": 1199.9232,
        "solar_panel_size_m2": 250.0,
        "solar_panel_efficiency_pct": 21.5,
    },
}


def get_vessel_clean_energy_specs(
    ship_type: str,
    csv_path: Optional[str] = None,
) -> Dict[str, float]:
    """
    Retrieve vessel battery and solar hardware specifications from ship_profiles.csv.
    Falls back to SOURCED_HARDWARE_SPECS if the file is missing or unreadable.
    """
    if not ship_type or not isinstance(ship_type, str):
        raise ValueError(f"ship_type must be a non-empty string, got {ship_type}")

    path = csv_path or DEFAULT_SHIP_PROFILES_CSV
    clean_type = ship_type.strip()

    if os.path.exists(path):
        try:
            with open(path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    st = row.get("ship_type", "").strip()
                    if st == clean_type or (clean_type == "Tanker" and st == "Tanker Ship"):
                        return {
                            "nominal_pack_capacity_kwh": float(row["battery_pack_capacity_kwh"]),
                            "solar_panel_size_m2": float(row["solar_panel_size_m2"]),
                            "solar_panel_efficiency_pct": float(row["solar_panel_efficiency_pct"]),
                        }
        except Exception:
            pass

    if clean_type in SOURCED_HARDWARE_SPECS:
        return dict(SOURCED_HARDWARE_SPECS[clean_type])

    valid_types = list(SOURCED_HARDWARE_SPECS.keys())
    raise ValueError(f"Unknown ship_type '{ship_type}'. Expected one of: {valid_types}")


def lookup_solar_climatology_ghi(
    route_id: str,
    month: Union[str, int],
    csv_path: Optional[str] = None,
) -> float:
    """
    Look up monthly average daily GHI (kWh/m²/day) from NASA POWER monthly climatology.
    
    Dimensions:
      - route_id: Corridor string (e.g., 'Escravos-Lagos', 'Warri-Bonny', etc.)
      - month: Month name (e.g., 'January') or integer (1-12)
    
    Returns:
      ALLSKY_SFC_SW_DWN (float >= 0.0) in kWh/m²/day
    """
    if not route_id or not isinstance(route_id, str):
        raise ValueError(f"route_id must be a non-empty string, got {route_id}")

    # Parse month to integer 1-12
    if isinstance(month, int):
        month_num = month
    elif isinstance(month, str):
        cleaned_m = month.strip().lower()
        if cleaned_m.isdigit():
            month_num = int(cleaned_m)
        elif cleaned_m in MONTH_NAME_TO_NUM:
            month_num = MONTH_NAME_TO_NUM[cleaned_m]
        else:
            raise ValueError(f"Unknown month string '{month}'. Expected standard month name or integer 1-12.")
    else:
        raise ValueError(f"month must be str or int, got {type(month)}")

    if not 1 <= month_num <= 12:
        raise ValueError(f"month_num must be in range [1, 12], got {month_num}")

    path = csv_path or DEFAULT_NASA_CLIMATOLOGY_CSV
    if not os.path.exists(path):
        raise FileNotFoundError(f"NASA monthly climatology file not found at: {path}")

    clean_route = route_id.strip()
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            r_id = row.get("route_id", "").strip()
            r_m = int(row.get("month_num", 0))
            if r_id == clean_route and r_m == month_num:
                ghi_val = float(row["ALLSKY_SFC_SW_DWN"])
                if not math.isfinite(ghi_val) or ghi_val < 0.0:
                    raise ValueError(f"Invalid GHI value ({ghi_val}) in climatology for {clean_route}, month {month_num}")
                return ghi_val

    raise ValueError(f"No climatology record found for route_id='{route_id}' and month={month_num}")


def calculate_effective_battery_capacity(
    nominal_pack_capacity_kwh: float,
    predicted_soh: float,
) -> float:
    """
    Calculate degradation-adjusted battery pack capacity.
    
    Formula:
      effective_pack_capacity_kwh = nominal_pack_capacity_kwh * predicted_soh
    """
    if nominal_pack_capacity_kwh is None or not isinstance(nominal_pack_capacity_kwh, (int, float)):
        raise ValueError(f"nominal_pack_capacity_kwh must be numeric, got {nominal_pack_capacity_kwh}")
    if not math.isfinite(nominal_pack_capacity_kwh):
        raise ValueError(f"nominal_pack_capacity_kwh must be finite, got {nominal_pack_capacity_kwh}")
    if nominal_pack_capacity_kwh <= 0.0:
        raise ValueError(f"nominal_pack_capacity_kwh must be strictly positive (> 0), got {nominal_pack_capacity_kwh}")

    if predicted_soh is None or not isinstance(predicted_soh, (int, float)):
        raise ValueError(f"predicted_soh must be numeric, got {predicted_soh}")
    if not math.isfinite(predicted_soh):
        raise ValueError(f"predicted_soh must be finite, got {predicted_soh}")
    if not 0.0 <= predicted_soh <= 1.0:
        raise ValueError(f"predicted_soh must be within [0.0, 1.0], got {predicted_soh}")

    return float(nominal_pack_capacity_kwh * predicted_soh)


def calculate_usable_battery_energy(
    effective_pack_capacity_kwh: float,
    initial_soc: float,
    soc_reserve: float = 0.20,
) -> float:
    """
    Calculate usable battery energy above operational reserve buffer.
    
    Formula:
      usable_battery_energy_kwh = effective_pack_capacity_kwh * max(0, initial_soc - soc_reserve)
    """
    if effective_pack_capacity_kwh is None or not isinstance(effective_pack_capacity_kwh, (int, float)):
        raise ValueError(f"effective_pack_capacity_kwh must be numeric, got {effective_pack_capacity_kwh}")
    if not math.isfinite(effective_pack_capacity_kwh):
        raise ValueError(f"effective_pack_capacity_kwh must be finite, got {effective_pack_capacity_kwh}")
    if effective_pack_capacity_kwh < 0.0:
        raise ValueError(f"effective_pack_capacity_kwh cannot be negative, got {effective_pack_capacity_kwh}")

    if initial_soc is None or not isinstance(initial_soc, (int, float)):
        raise ValueError(f"initial_soc must be numeric, got {initial_soc}")
    if not math.isfinite(initial_soc):
        raise ValueError(f"initial_soc must be finite, got {initial_soc}")
    if not 0.0 <= initial_soc <= 1.0:
        raise ValueError(f"initial_soc must be within [0.0, 1.0], got {initial_soc}")

    if soc_reserve is None or not isinstance(soc_reserve, (int, float)):
        raise ValueError(f"soc_reserve must be numeric, got {soc_reserve}")
    if not math.isfinite(soc_reserve):
        raise ValueError(f"soc_reserve must be finite, got {soc_reserve}")
    if not 0.0 <= soc_reserve <= 1.0:
        raise ValueError(f"soc_reserve must be within [0.0, 1.0], got {soc_reserve}")

    delta_soc = max(0.0, initial_soc - soc_reserve)
    return float(effective_pack_capacity_kwh * delta_soc)


def calculate_estimated_solar_energy(
    solar_panel_size_m2: float,
    solar_panel_efficiency_pct: float,
    daily_ghi_kwh_per_m2: float,
    solar_derate_factor: float,
    voyage_duration_hours: float,
) -> float:
    """
    Calculate deterministic climatological solar energy generation.
    
    Formula:
      estimated_solar_energy_kwh = (
          solar_panel_size_m2
          * (solar_panel_efficiency_pct / 100.0)
          * daily_ghi_kwh_per_m2
          * solar_derate_factor
          * (voyage_duration_hours / 24.0)
      )
    """
    if solar_panel_size_m2 is None or not isinstance(solar_panel_size_m2, (int, float)):
        raise ValueError(f"solar_panel_size_m2 must be numeric, got {solar_panel_size_m2}")
    if not math.isfinite(solar_panel_size_m2):
        raise ValueError(f"solar_panel_size_m2 must be finite, got {solar_panel_size_m2}")
    if solar_panel_size_m2 < 0.0:
        raise ValueError(f"solar_panel_size_m2 cannot be negative, got {solar_panel_size_m2}")

    if solar_panel_efficiency_pct is None or not isinstance(solar_panel_efficiency_pct, (int, float)):
        raise ValueError(f"solar_panel_efficiency_pct must be numeric, got {solar_panel_efficiency_pct}")
    if not math.isfinite(solar_panel_efficiency_pct):
        raise ValueError(f"solar_panel_efficiency_pct must be finite, got {solar_panel_efficiency_pct}")
    if not 0.0 <= solar_panel_efficiency_pct <= 100.0:
        raise ValueError(f"solar_panel_efficiency_pct must be within [0.0, 100.0], got {solar_panel_efficiency_pct}")

    if daily_ghi_kwh_per_m2 is None or not isinstance(daily_ghi_kwh_per_m2, (int, float)):
        raise ValueError(f"daily_ghi_kwh_per_m2 must be numeric, got {daily_ghi_kwh_per_m2}")
    if not math.isfinite(daily_ghi_kwh_per_m2):
        raise ValueError(f"daily_ghi_kwh_per_m2 must be finite, got {daily_ghi_kwh_per_m2}")
    if daily_ghi_kwh_per_m2 < 0.0:
        raise ValueError(f"daily_ghi_kwh_per_m2 cannot be negative, got {daily_ghi_kwh_per_m2}")

    if solar_derate_factor is None or not isinstance(solar_derate_factor, (int, float)):
        raise ValueError(f"solar_derate_factor must be numeric, got {solar_derate_factor}")
    if not math.isfinite(solar_derate_factor):
        raise ValueError(f"solar_derate_factor must be finite, got {solar_derate_factor}")
    if not 0.0 <= solar_derate_factor <= 1.0:
        raise ValueError(f"solar_derate_factor must be within [0.0, 1.0], got {solar_derate_factor}")

    if voyage_duration_hours is None or not isinstance(voyage_duration_hours, (int, float)):
        raise ValueError(f"voyage_duration_hours must be numeric, got {voyage_duration_hours}")
    if not math.isfinite(voyage_duration_hours):
        raise ValueError(f"voyage_duration_hours must be finite, got {voyage_duration_hours}")
    if voyage_duration_hours <= 0.0:
        raise ValueError(f"voyage_duration_hours must be strictly positive (> 0), got {voyage_duration_hours}")

    solar_yield = (
        solar_panel_size_m2
        * (solar_panel_efficiency_pct / 100.0)
        * daily_ghi_kwh_per_m2
        * solar_derate_factor
        * (voyage_duration_hours / 24.0)
    )
    return float(solar_yield)


def calculate_clean_energy_balance(
    usable_battery_energy_kwh: float,
    estimated_solar_energy_kwh: float,
    auxiliary_energy_demand_kwh: float,
) -> Dict[str, Any]:
    """
    Aggregate clean energy, calculate auxiliary energy balance, deficit, and feasibility status.
    """
    for val, name in [
        (usable_battery_energy_kwh, "usable_battery_energy_kwh"),
        (estimated_solar_energy_kwh, "estimated_solar_energy_kwh"),
        (auxiliary_energy_demand_kwh, "auxiliary_energy_demand_kwh"),
    ]:
        if val is None or not isinstance(val, (int, float)):
            raise ValueError(f"{name} must be numeric, got {val}")
        if not math.isfinite(val):
            raise ValueError(f"{name} must be finite, got {val}")
        if val < 0.0:
            raise ValueError(f"{name} cannot be negative, got {val}")

    total_clean_energy_available_kwh = float(usable_battery_energy_kwh + estimated_solar_energy_kwh)
    clean_energy_utilized_kwh = float(min(total_clean_energy_available_kwh, auxiliary_energy_demand_kwh))
    energy_balance_kwh = float(total_clean_energy_available_kwh - auxiliary_energy_demand_kwh)
    energy_deficit_kwh = float(max(0.0, auxiliary_energy_demand_kwh - total_clean_energy_available_kwh))
    feasibility_status = "FEASIBLE" if energy_balance_kwh >= 0.0 else "PARTIAL"

    return {
        "auxiliary_energy_demand_kwh": float(auxiliary_energy_demand_kwh),
        "usable_battery_energy_kwh": float(usable_battery_energy_kwh),
        "estimated_solar_energy_kwh": float(estimated_solar_energy_kwh),
        "total_clean_energy_available_kwh": total_clean_energy_available_kwh,
        "clean_energy_utilized_kwh": clean_energy_utilized_kwh,
        "energy_balance_kwh": energy_balance_kwh,
        "energy_deficit_kwh": energy_deficit_kwh,
        "feasibility_status": feasibility_status,
    }


def calculate_tier3_clean_energy_feasibility(
    ship_type: str,
    predicted_soh: float,
    auxiliary_energy_demand_kwh: float,
    voyage_duration_hours: float,
    route_id: Optional[str] = None,
    month: Optional[Union[str, int]] = None,
    daily_ghi_kwh_per_m2: Optional[float] = None,
    initial_soc: float = 0.90,
    soc_reserve: float = 0.20,
    solar_derate_factor: float = 0.85,
    nominal_pack_capacity_kwh: Optional[float] = None,
    solar_panel_size_m2: Optional[float] = None,
    solar_panel_efficiency_pct: Optional[float] = None,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> Tier3CleanEnergyFeasibility:
    """
    Orchestrate Tier 3 clean energy feasibility calculations.
    
    Returns:
      Validated Tier3CleanEnergyFeasibility Pydantic model.
    """
    # 1. Resolve hardware specifications
    specs = get_vessel_clean_energy_specs(ship_type, csv_path=ship_profiles_csv)
    nom_cap = nominal_pack_capacity_kwh if nominal_pack_capacity_kwh is not None else specs["nominal_pack_capacity_kwh"]
    p_size = solar_panel_size_m2 if solar_panel_size_m2 is not None else specs["solar_panel_size_m2"]
    p_eff = solar_panel_efficiency_pct if solar_panel_efficiency_pct is not None else specs["solar_panel_efficiency_pct"]

    # 2. Battery energy calculation
    eff_cap = calculate_effective_battery_capacity(nom_cap, predicted_soh)
    usable_batt = calculate_usable_battery_energy(eff_cap, initial_soc, soc_reserve)

    # 3. Solar insolation lookup
    if daily_ghi_kwh_per_m2 is not None:
        ghi = daily_ghi_kwh_per_m2
    else:
        if route_id is None or month is None:
            raise ValueError(
                "Either daily_ghi_kwh_per_m2 or both (route_id, month) must be provided for solar estimation."
            )
        ghi = lookup_solar_climatology_ghi(route_id, month, csv_path=climatology_csv)

    # 4. Solar generation calculation
    est_solar = calculate_estimated_solar_energy(
        solar_panel_size_m2=p_size,
        solar_panel_efficiency_pct=p_eff,
        daily_ghi_kwh_per_m2=ghi,
        solar_derate_factor=solar_derate_factor,
        voyage_duration_hours=voyage_duration_hours,
    )

    # 5. Clean energy balance and feasibility status
    balance_dict = calculate_clean_energy_balance(
        usable_battery_energy_kwh=usable_batt,
        estimated_solar_energy_kwh=est_solar,
        auxiliary_energy_demand_kwh=auxiliary_energy_demand_kwh,
    )
    balance_dict["solar_estimate_diurnal_uncertainty_flag"] = bool(voyage_duration_hours > 24.0)

    return Tier3CleanEnergyFeasibility.model_validate(balance_dict)

