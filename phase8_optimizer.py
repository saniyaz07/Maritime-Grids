"""
phase8_optimizer.py — Parametric System Sizing Optimization Engine
===================================================================
Implementation of the Phase 8 Parametric Sizing Optimization Layer.

Determines optimal solar PV array surface area (A_pv) and battery capacity (E_batt)
via exhaustive bounded grid search across physical, engineering, and capital constraints.

Core capabilities:
  1. Automatic catalog bound resolution (L, B, DWT) from ship_profiles.csv.
  2. Deterministic discrete lattice generation without arbitrary fractional partial steps.
  3. Single candidate evaluation delegating strictly to Phase 3 and Phase 7 engines.
  4. Physical constraint enforcement:
     - Deck area limit: A_pv <= fdeck_max * L * B
     - Battery weight limit: M_batt <= fdwt_max * DWT
     - Capital expenditure limit: CAPEX_0 <= max_capex_budget_usd
     - Auxiliary feasibility gate: 100% hotel load coverage when require_fully_feasible=True
  5. Multi-objective & single-objective extraction:
     - MAX_NPV
     - MAX_FUEL_DISPLACEMENT
     - MAX_CO2_DISPLACEMENT
     - MIN_LCOE (preserving Phase 7 None semantics; never inf or sentinel)
     - MIN_CAPEX
     - PARETO_FRONTIER (strict non-domination)
  6. Deterministic tie-breaking hierarchy:
     Primary Objective -> min CAPEX_0 -> min A_pv -> min E_batt -> lattice traversal order.
  7. High-level adapters for Phase 6 single-voyage and Phase 3G annual multi-voyage schedules.

Zero subjective evaluative labels ("best", "ideal", "recommended").
Zero modification to frozen upstream models, contracts, or reference data.
"""

import os
import math
import functools
from typing import Dict, Any, Optional, List, Tuple, Union
import numpy as np
import pandas as pd

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    Phase3Output,
)
from phase3_feasibility import (
    calculate_tier3_clean_energy_feasibility,
    get_vessel_clean_energy_specs,
    lookup_solar_climatology_ghi,
)
from phase3_displacement import (
    calculate_fuel_displacement,
    calculate_co2_displacement,
)
from phase6_contracts import (
    VoyageSimulationRequest,
    Phase6SimulationResult,
)
from phase6_gateway import (
    simulate_voyage,
    DEFAULT_AUXILIARY_DEMAND_KWH,
    CANONICAL_ROUTE_DISTANCES,
    TANKER_CANONICAL_DISTANCES,
)
from phase7_contracts import (
    FinancialParameters,
    InvestmentAppraisalResult,
)
from phase7_economics import (
    evaluate_clean_energy_investment,
    load_ship_profiles_catalog,
)
from phase8_contracts import (
    OptimizationParameters,
    OptimizationCandidate,
    OptimizationResult,
    SMALL_CRAFT_TYPES,
    LARGE_VESSEL_TYPES,
    VALID_OBJECTIVES,
    VALID_PARETO_OBJECTIVES,
)

# Relative tolerance for primary objective equality comparisons
EPSILON_RELATIVE: float = 1e-6

# Absolute tolerance for physical, weight, and budget boundary comparisons
EPSILON_ABSOLUTE: float = 1e-6

# Hard ceiling on total grid points to prevent unbounded execution
MAX_CANDIDATES_ALLOWED: int = 10000

# Canonical default single-voyage operational profiles for reference resolution
CANONICAL_VOYAGE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "Oil Service Boat": {
        "route_id": "Escravos-Lagos",
        "month": 7,
        "speed_knots": 12.0,
        "auxiliary_energy_demand_kwh": 180.0,
    },
    "Fishing Trawler": {
        "route_id": "Warri-Bonny",
        "month": 7,
        "speed_knots": 10.0,
        "auxiliary_energy_demand_kwh": 80.0,
    },
    "Surfer Boat": {
        "route_id": "Lagos-Apapa",
        "month": 7,
        "speed_knots": 25.0,
        "auxiliary_energy_demand_kwh": 37.0,
    },
    "Tanker Ship": {
        "route_id": "Escravos-Lagos",
        "month": 7,
        "speed_knots": 12.0,
        "auxiliary_energy_demand_kwh": 400.0,
    },
}


# ==============================================================================
# 1. Engineering Bound & Step Resolution
# ==============================================================================
def resolve_grid_bounds(
    params: OptimizationParameters,
    ship_profiles_csv: Optional[str] = None,
) -> Dict[str, float]:
    """
    Resolve maximum solar area, battery capacity, and discrete step size from
    catalog physical dimensions and configurable engineering assumptions.

    Formulas:
      Adeck_max = fdeck_max * L * B  (derived engineering sizing bound)
      Mdwt_max = fdwt_max * DWT      (allowable battery mass in tonnes)
      Ebatt_max = (Mdwt_max * 1000) / battery_specific_mass_kg_per_kwh
    """
    catalog = load_ship_profiles_catalog(ship_profiles_csv)
    ship_type = params.ship_type

    # Normalize archetype lookup (e.g. 'Tanker' -> 'Tanker Ship' if needed)
    matched_type = ship_type
    if matched_type not in catalog.index:
        for idx in catalog.index:
            if idx.lower() == ship_type.lower() or (ship_type.lower() in idx.lower()):
                matched_type = idx
                break
        if matched_type not in catalog.index:
            raise ValueError(
                f"Unknown ship_type '{ship_type}'. Must be present in ship_profiles catalog: {list(catalog.index)}"
            )

    row = catalog.loc[matched_type]
    length_m = float(row["hull_length_m"])
    beam_m = float(row["hull_beam_m"])
    dwt_tonnes = float(row["dwt_tonnes"])

    # Derived engineering physical boundaries
    deck_area_limit_m2 = params.fdeck_max * length_m * beam_m
    battery_weight_limit_tonnes = params.fdwt_max * dwt_tonnes
    battery_capacity_limit_kwh = (battery_weight_limit_tonnes * 1000.0) / params.battery_specific_mass_kg_per_kwh

    # Resolved search boundaries
    if params.max_solar_area_m2 is not None:
        resolved_max_solar_m2 = float(params.max_solar_area_m2)
    else:
        resolved_max_solar_m2 = deck_area_limit_m2

    if params.max_battery_capacity_kwh is not None:
        resolved_max_battery_kwh = float(params.max_battery_capacity_kwh)
    else:
        resolved_max_battery_kwh = battery_capacity_limit_kwh

    # Resolved discrete battery step size
    if params.step_battery_capacity_kwh is not None:
        resolved_step_battery_kwh = float(params.step_battery_capacity_kwh)
    else:
        if matched_type in SMALL_CRAFT_TYPES:
            resolved_step_battery_kwh = 25.0
        elif matched_type in LARGE_VESSEL_TYPES:
            resolved_step_battery_kwh = 50.0
        else:
            raise ValueError(
                f"Cannot resolve default battery step for unknown ship_type '{matched_type}'. "
                f"Expected small craft ({SMALL_CRAFT_TYPES}) or large vessel ({LARGE_VESSEL_TYPES})."
            )

    return {
        "deck_area_limit_m2": float(deck_area_limit_m2),
        "battery_weight_limit_tonnes": float(battery_weight_limit_tonnes),
        "resolved_max_solar_area_m2": float(resolved_max_solar_m2),
        "resolved_max_battery_capacity_kwh": float(resolved_max_battery_kwh),
        "resolved_step_battery_capacity_kwh": float(resolved_step_battery_kwh),
        "hull_length_m": length_m,
        "hull_beam_m": beam_m,
        "dwt_tonnes": dwt_tonnes,
    }


# ==============================================================================
# 2. Discrete Sizing Lattice Generator
# ==============================================================================
def generate_sizing_lattice(
    min_val: float,
    max_val: float,
    step_val: float,
) -> List[float]:
    """
    Generate a deterministic discrete search lattice from min_val to max_val
    in increments of step_val.
    
    Invariant: Points must lie strictly on the lattice (val = min + i * step <= max).
    No arbitrary partial steps are appended if they do not land on the grid.
    """
    if min_val < 0.0:
        raise ValueError(f"min_val cannot be negative, got {min_val}")
    if max_val < min_val:
        raise ValueError(f"max_val ({max_val}) cannot be less than min_val ({min_val})")
    if step_val <= 0.0:
        raise ValueError(f"step_val must be strictly positive (> 0), got {step_val}")

    points: List[float] = []
    val = min_val
    while val <= max_val + 1e-9:
        points.append(round(val, 6))
        val += step_val

    # Ensure at least min_val is evaluated if lattice is degenerate
    if not points:
        points = [round(min_val, 6)]

    return points


# ==============================================================================
# 3. Single Candidate Evaluation
# ==============================================================================
def evaluate_single_sizing_candidate(
    solar_area_m2: float,
    battery_capacity_kwh: float,
    params: OptimizationParameters,
    deck_area_limit_m2: float,
    battery_weight_limit_tonnes: float,
    predicted_soh: float,
    auxiliary_energy_demand_kwh: float,
    voyage_duration_hours: float,
    predicted_fuel_consumption_L: float,
    predicted_CO2_kg: float,
    route_id: Optional[str] = None,
    month: Optional[Union[str, int]] = None,
    daily_ghi_kwh_per_m2: Optional[float] = None,
    initial_soc: float = 0.90,
    soc_reserve: float = 0.20,
    solar_derate_factor: float = 0.85,
    generator_sfoc_kg_per_kwh: float = 0.220,
    fuel_density_kg_per_l: float = 0.850,
    emission_factor_kgco2_per_kgfuel: float = 3.114,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> OptimizationCandidate:
    """
    Evaluate physical feasibility, generator displacement, and lifecycle financials
    for a single candidate sizing point (A_pv, E_batt).
    
    Delegates strictly to:
      - Phase 3 calculate_tier3_clean_energy_feasibility
      - Phase 3 calculate_fuel_displacement & calculate_co2_displacement
      - Phase 7 evaluate_clean_energy_investment
    """
    # 1. Physical limits and battery mass
    battery_mass_tonnes = (battery_capacity_kwh * params.battery_specific_mass_kg_per_kwh) / 1000.0

    violations: List[str] = []
    if solar_area_m2 > deck_area_limit_m2 + EPSILON_ABSOLUTE:
        violations.append("DECK_AREA_EXCEEDED")
    if battery_mass_tonnes > battery_weight_limit_tonnes + EPSILON_ABSOLUTE:
        violations.append("BATTERY_WEIGHT_EXCEEDED")

    # 2. Phase 3 Tier 3 clean energy balance
    if battery_capacity_kwh > 0.0:
        tier3_result = calculate_tier3_clean_energy_feasibility(
            ship_type=params.ship_type,
            predicted_soh=predicted_soh,
            auxiliary_energy_demand_kwh=auxiliary_energy_demand_kwh,
            voyage_duration_hours=voyage_duration_hours,
            route_id=route_id,
            month=month,
            daily_ghi_kwh_per_m2=daily_ghi_kwh_per_m2,
            initial_soc=initial_soc,
            soc_reserve=soc_reserve,
            solar_derate_factor=solar_derate_factor,
            nominal_pack_capacity_kwh=battery_capacity_kwh,
            solar_panel_size_m2=solar_area_m2,
            ship_profiles_csv=ship_profiles_csv,
            climatology_csv=climatology_csv,
        )
        clean_avail_kwh = float(tier3_result.total_clean_energy_available_kwh)
        clean_util_kwh = float(tier3_result.clean_energy_utilized_kwh)
        curtailed_kwh = max(0.0, float(tier3_result.total_clean_energy_available_kwh - tier3_result.clean_energy_utilized_kwh))
        feasibility_status = tier3_result.feasibility_status
    else:
        # Zero battery pack installed: usable battery energy is strictly 0.0
        specs = get_vessel_clean_energy_specs(params.ship_type, csv_path=ship_profiles_csv)
        p_eff = specs["solar_panel_efficiency_pct"]
        if daily_ghi_kwh_per_m2 is not None:
            ghi = daily_ghi_kwh_per_m2
        else:
            if route_id is None or month is None:
                ghi = 4.5
            else:
                ghi = lookup_solar_climatology_ghi(route_id, month, csv_path=climatology_csv)

        from phase3_feasibility import calculate_estimated_solar_energy, calculate_clean_energy_balance
        est_solar = calculate_estimated_solar_energy(
            solar_panel_size_m2=solar_area_m2,
            solar_panel_efficiency_pct=p_eff,
            daily_ghi_kwh_per_m2=ghi,
            solar_derate_factor=solar_derate_factor,
            voyage_duration_hours=voyage_duration_hours,
        )
        balance = calculate_clean_energy_balance(
            usable_battery_energy_kwh=0.0,
            estimated_solar_energy_kwh=est_solar,
            auxiliary_energy_demand_kwh=auxiliary_energy_demand_kwh,
        )
        clean_avail_kwh = float(balance["total_clean_energy_available_kwh"])
        clean_util_kwh = float(balance["clean_energy_utilized_kwh"])
        curtailed_kwh = max(0.0, float(balance["total_clean_energy_available_kwh"] - balance["clean_energy_utilized_kwh"]))
        feasibility_status = balance["feasibility_status"]

    # 3. Phase 3 Tier 4 generator displacement
    v_fuel = calculate_fuel_displacement(
        clean_energy_utilized_kwh=clean_util_kwh,
        generator_sfoc_kg_per_kwh=generator_sfoc_kg_per_kwh,
        fuel_density_kg_per_l=fuel_density_kg_per_l,
        predicted_fuel_consumption_L=predicted_fuel_consumption_L,
    )
    v_co2 = calculate_co2_displacement(
        estimated_fuel_displaced_L=v_fuel,
        fuel_density_kg_per_l=fuel_density_kg_per_l,
        emission_factor_kgco2_per_kgfuel=emission_factor_kgco2_per_kgfuel,
        predicted_CO2_kg=predicted_CO2_kg,
    )

    # 4. Multi-voyage annual scaling
    annual_fuel_displaced_L = v_fuel * params.annual_voyages
    annual_co2_displaced_kg = v_co2 * params.annual_voyages
    annual_clean_utilized_kwh = clean_util_kwh * params.annual_voyages

    # 5. Phase 7 lifecycle financial appraisal
    appraisal: InvestmentAppraisalResult = evaluate_clean_energy_investment(
        ship_type=params.ship_type,
        annual_fuel_displaced_L=annual_fuel_displaced_L,
        annual_clean_energy_utilized_kwh=annual_clean_utilized_kwh,
        annual_co2_displaced_kg=annual_co2_displaced_kg,
        solar_area_m2=solar_area_m2,
        battery_capacity_kwh=battery_capacity_kwh,
        parameters=params.financial_parameters,
        ship_profiles_csv=ship_profiles_csv,
    )

    capex_0 = float(appraisal.total_initial_capex_usd)
    npv = float(appraisal.net_present_value_usd)
    irr = appraisal.internal_rate_of_return_pct
    irr_status = appraisal.irr_status
    spb = appraisal.simple_payback_years
    dpb = appraisal.discounted_payback_years
    lcoe = appraisal.lcoe_usd_per_kwh
    lcoe_status = appraisal.lcoe_status

    # 6. Economic budget and feasibility constraints
    if params.max_capex_budget_usd is not None:
        if capex_0 > params.max_capex_budget_usd + EPSILON_ABSOLUTE:
            violations.append("BUDGET_EXCEEDED")

    if params.require_fully_feasible:
        if feasibility_status != "FEASIBLE":
            violations.append("INCOMPLETE_AUXILIARY_FEASIBILITY")

    is_valid = (len(violations) == 0)

    # Categorize candidate audit status
    if "DECK_AREA_EXCEEDED" in violations or "BATTERY_WEIGHT_EXCEEDED" in violations:
        candidate_status = "CONSTRAINED_OUT"
    elif "BUDGET_EXCEEDED" in violations:
        candidate_status = "BUDGET_EXCEEDED"
    elif "INCOMPLETE_AUXILIARY_FEASIBILITY" in violations:
        candidate_status = "INCOMPLETE_FEASIBILITY"
    else:
        candidate_status = "VALID"

    # 7. Extract primary objective value
    if params.objective == "MAX_NPV":
        objective_value = npv
    elif params.objective == "MAX_FUEL_DISPLACEMENT":
        objective_value = annual_fuel_displaced_L
    elif params.objective == "MAX_CO2_DISPLACEMENT":
        objective_value = annual_co2_displaced_kg
    elif params.objective == "MIN_LCOE":
        objective_value = lcoe  # None if zero energy utilized
    elif params.objective == "MIN_CAPEX":
        objective_value = capex_0
    else:  # PARETO_FRONTIER
        objective_value = None

    return OptimizationCandidate(
        solar_area_m2=round(solar_area_m2, 4),
        battery_capacity_kwh=round(battery_capacity_kwh, 4),
        battery_mass_tonnes=round(battery_mass_tonnes, 4),
        deck_area_limit_m2=round(deck_area_limit_m2, 4),
        battery_weight_limit_tonnes=round(battery_weight_limit_tonnes, 4),
        is_physically_valid=is_valid,
        constraint_violations=violations,
        candidate_status=candidate_status,
        clean_energy_available_kwh=round(clean_avail_kwh, 4),
        clean_energy_utilized_kwh=round(clean_util_kwh, 4),
        curtailed_energy_kwh=round(curtailed_kwh, 4),
        feasibility_status=feasibility_status,
        annual_fuel_displaced_L=round(annual_fuel_displaced_L, 4),
        annual_co2_displaced_kg=round(annual_co2_displaced_kg, 4),
        total_initial_capex_usd=round(capex_0, 2),
        net_present_value_usd=round(npv, 2),
        internal_rate_of_return_pct=irr,
        irr_status=irr_status,
        simple_payback_years=spb,
        discounted_payback_years=dpb,
        lcoe_usd_per_kwh=lcoe,
        lcoe_status=lcoe_status,
        objective_value=objective_value,
    )


# ==============================================================================
# 4. Deterministic Comparator & Tie-Breaking
# ==============================================================================
def compare_candidates(
    a: OptimizationCandidate,
    b: OptimizationCandidate,
    objective: str,
    eps_rel: float = EPSILON_RELATIVE,
) -> int:
    """
    Deterministic candidate comparator implementing the strict tie-breaking hierarchy:
      1. Primary objective (within relative tolerance epsilon_relative).
      2. Minimum Initial CAPEX (CAPEX_0).
      3. Minimum Solar Array Area (A_pv).
      4. Minimum Battery Capacity (E_batt).

    Returns:
      -1 if candidate A is strictly preferred to B.
       1 if candidate B is strictly preferred to A.
       0 if completely tied across primary objective and all tie-breakers.
    """
    va = a.objective_value
    vb = b.objective_value

    # Handle None objective values (e.g. LCOE=None or PARETO_FRONTIER)
    if va is None or vb is None:
        if va is not None:
            return -1
        if vb is not None:
            return 1
        # Both are None on primary objective: proceed directly to tie-breakers
    else:
        tol = eps_rel * max(1.0, abs(va), abs(vb))
        if objective in ["MAX_NPV", "MAX_FUEL_DISPLACEMENT", "MAX_CO2_DISPLACEMENT"]:
            if va > vb + tol:
                return -1
            elif vb > va + tol:
                return 1
        elif objective in ["MIN_CAPEX", "MIN_LCOE"]:
            if va < vb - tol:
                return -1
            elif vb < va - tol:
                return 1

    # Tied on primary objective within tolerance: proceed to tie-breaker priority 1 (min CAPEX_0)
    ca = a.total_initial_capex_usd
    cb = b.total_initial_capex_usd
    tol_c = eps_rel * max(1.0, abs(ca), abs(cb))
    if ca < cb - tol_c:
        return -1
    elif cb < ca - tol_c:
        return 1

    # Tied on CAPEX_0: proceed to tie-breaker priority 2 (min A_pv)
    if a.solar_area_m2 < b.solar_area_m2 - 1e-6:
        return -1
    elif b.solar_area_m2 < a.solar_area_m2 - 1e-6:
        return 1

    # Tied on A_pv: proceed to tie-breaker priority 3 (min E_batt)
    if a.battery_capacity_kwh < b.battery_capacity_kwh - 1e-6:
        return -1
    elif b.battery_capacity_kwh < a.battery_capacity_kwh - 1e-6:
        return 1

    # Completely tied across all criteria
    return 0


# ==============================================================================
# 5. Multi-Objective Pareto Dominance
# ==============================================================================
def _pareto_dominates(
    c1: OptimizationCandidate,
    c2: OptimizationCandidate,
    objectives: List[str],
    eps_rel: float = EPSILON_RELATIVE,
) -> bool:
    """
    Check if candidate c1 Pareto-dominates candidate c2 (c1 > c2).
    
    Definition:
      c1 dominates c2 iff:
        - c1 is no worse than c2 in EVERY configured objective, AND
        - c1 is strictly better than c2 in AT LEAST ONE objective.

    Handles MIN_LCOE where LCOE=None is strictly dominated by a valid numeric LCOE.
    """
    strictly_better_in_at_least_one = False

    for obj in objectives:
        if obj == "MIN_CAPEX":
            v1 = c1.total_initial_capex_usd
            v2 = c2.total_initial_capex_usd
            tol = eps_rel * max(1.0, abs(v1), abs(v2))
            if v1 > v2 + tol:
                return False
            if v1 < v2 - tol:
                strictly_better_in_at_least_one = True

        elif obj == "MAX_FUEL_DISPLACEMENT":
            v1 = c1.annual_fuel_displaced_L
            v2 = c2.annual_fuel_displaced_L
            tol = eps_rel * max(1.0, abs(v1), abs(v2))
            if v1 < v2 - tol:
                return False
            if v1 > v2 + tol:
                strictly_better_in_at_least_one = True

        elif obj == "MAX_CO2_DISPLACEMENT":
            v1 = c1.annual_co2_displaced_kg
            v2 = c2.annual_co2_displaced_kg
            tol = eps_rel * max(1.0, abs(v1), abs(v2))
            if v1 < v2 - tol:
                return False
            if v1 > v2 + tol:
                strictly_better_in_at_least_one = True

        elif obj == "MAX_NPV":
            v1 = c1.net_present_value_usd
            v2 = c2.net_present_value_usd
            tol = eps_rel * max(1.0, abs(v1), abs(v2))
            if v1 < v2 - tol:
                return False
            if v1 > v2 + tol:
                strictly_better_in_at_least_one = True

        elif obj == "MIN_LCOE":
            v1 = c1.lcoe_usd_per_kwh
            v2 = c2.lcoe_usd_per_kwh
            if v1 is None and v2 is None:
                pass
            elif v1 is None and v2 is not None:
                return False  # c1 has undefined LCOE, c2 has valid LCOE -> c1 is worse
            elif v1 is not None and v2 is None:
                strictly_better_in_at_least_one = True  # c1 has valid LCOE, c2 undefined -> c1 is strictly better
            else:
                tol = eps_rel * max(1.0, abs(v1), abs(v2))
                if v1 > v2 + tol:
                    return False
                if v1 < v2 - tol:
                    strictly_better_in_at_least_one = True

    return strictly_better_in_at_least_one


def _pareto_sort_key(
    c: OptimizationCandidate,
    objectives: List[str],
) -> Tuple[Any, ...]:
    """
    Generate a dynamic sorting key tuple for Pareto frontier candidates
    ordered strictly by the configured pareto_objectives, followed by
    the deterministic tie-breaking hierarchy:
      1. First configured pareto objective
      2. Second configured pareto objective
      3. Subsequent configured objectives, if present
      4. Deterministic tie-breakers:
         - min CAPEX0 (ascending)
         - min Apv (ascending)
         - min Ebatt (ascending)
    """
    keys: List[Any] = []
    for obj in objectives:
        if obj == "MIN_CAPEX":
            keys.append(c.total_initial_capex_usd)
        elif obj == "MAX_FUEL_DISPLACEMENT":
            keys.append(-c.annual_fuel_displaced_L)
        elif obj == "MAX_CO2_DISPLACEMENT":
            keys.append(-c.annual_co2_displaced_kg)
        elif obj == "MAX_NPV":
            keys.append(-c.net_present_value_usd)
        elif obj == "MIN_LCOE":
            val = c.lcoe_usd_per_kwh
            # Numeric LCOE values sort before undefined LCOE (None) without modifying candidate
            keys.append((0, val) if val is not None else (1, 0.0))

    # Deterministic tie-breakers after configured objective keys
    keys.append(c.total_initial_capex_usd)
    keys.append(c.solar_area_m2)
    keys.append(c.battery_capacity_kwh)
    return tuple(keys)


# ==============================================================================
# 6. Core Optimization Engine
# ==============================================================================
def optimize_system_sizing(
    params: OptimizationParameters,
    voyage_context: Optional[Union[Phase6SimulationResult, Phase3Output, VoyageSimulationRequest, Dict[str, Any]]] = None,
    predicted_soh: Optional[float] = None,
    auxiliary_energy_demand_kwh: Optional[float] = None,
    voyage_duration_hours: Optional[float] = None,
    route_id: Optional[str] = None,
    month: Optional[Union[str, int]] = None,
    daily_ghi_kwh_per_m2: Optional[float] = None,
    predicted_fuel_consumption_L: Optional[float] = None,
    predicted_CO2_kg: Optional[float] = None,
    initial_soc: float = 0.90,
    soc_reserve: float = 0.20,
    solar_derate_factor: float = 0.85,
    generator_sfoc_kg_per_kwh: float = 0.220,
    fuel_density_kg_per_l: float = 0.850,
    emission_factor_kgco2_per_kgfuel: float = 3.114,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> OptimizationResult:
    """
    Execute exhaustive bounded grid search over (A_pv, E_batt) sizing candidates.
    
    Evaluates physical constraints, Phase 3 feasibility & displacement, Phase 7 lifecycle
    financials, deterministic tie-breaking, and Pareto frontier generation.
    """
    warnings: List[str] = []

    # 1. Resolve search bounds and engineering limits
    bounds = resolve_grid_bounds(params, ship_profiles_csv=ship_profiles_csv)
    res_max_solar = bounds["resolved_max_solar_area_m2"]
    res_max_battery = bounds["resolved_max_battery_capacity_kwh"]
    res_step_battery = bounds["resolved_step_battery_capacity_kwh"]
    deck_area_limit = bounds["deck_area_limit_m2"]
    battery_weight_limit = bounds["battery_weight_limit_tonnes"]

    # 2. Resolve operational voyage baseline inputs
    # If voyage_context is a Phase6SimulationResult or Phase3Output, extract authoritative metrics
    resolved_soh = predicted_soh
    resolved_aux_demand = auxiliary_energy_demand_kwh
    resolved_duration = voyage_duration_hours
    resolved_route = route_id
    resolved_month = month
    resolved_fuel_L = predicted_fuel_consumption_L
    resolved_co2_kg = predicted_CO2_kg

    if isinstance(voyage_context, Phase6SimulationResult):
        p2 = voyage_context.tier1_predictions
        p3 = voyage_context.phase3_output
        resolved_soh = resolved_soh if resolved_soh is not None else float(p2.battery_health.predicted_soh)
        resolved_fuel_L = resolved_fuel_L if resolved_fuel_L is not None else float(p2.fuel_consumption_L.value)
        resolved_co2_kg = resolved_co2_kg if resolved_co2_kg is not None else float(p2.co2_emissions_kg.value)
        resolved_duration = resolved_duration if resolved_duration is not None else float(p3.voyage_metadata.voyage_duration_hours)
        resolved_aux_demand = resolved_aux_demand if resolved_aux_demand is not None else float(p3.applied_scenario_parameters.auxiliary_energy_demand_kwh)
        resolved_route = resolved_route or voyage_context.request.route_id
        resolved_month = resolved_month or voyage_context.request.month

    elif isinstance(voyage_context, Phase3Output):
        p2 = voyage_context.tier_1_phase2_predictions
        resolved_soh = resolved_soh if resolved_soh is not None else float(p2.battery_health.predicted_soh)
        resolved_fuel_L = resolved_fuel_L if resolved_fuel_L is not None else float(p2.fuel_consumption_L.value)
        resolved_co2_kg = resolved_co2_kg if resolved_co2_kg is not None else float(p2.co2_emissions_kg.value)
        resolved_duration = resolved_duration if resolved_duration is not None else float(voyage_context.voyage_metadata.voyage_duration_hours)
        resolved_aux_demand = resolved_aux_demand if resolved_aux_demand is not None else float(voyage_context.applied_scenario_parameters.auxiliary_energy_demand_kwh)

    elif isinstance(voyage_context, VoyageSimulationRequest):
        sim = simulate_voyage(voyage_context, ship_profiles_csv=ship_profiles_csv, nasa_clim_csv=climatology_csv)
        p2 = sim.tier1_predictions
        p3 = sim.phase3_output
        resolved_soh = resolved_soh if resolved_soh is not None else float(p2.battery_health.predicted_soh)
        resolved_fuel_L = resolved_fuel_L if resolved_fuel_L is not None else float(p2.fuel_consumption_L.value)
        resolved_co2_kg = resolved_co2_kg if resolved_co2_kg is not None else float(p2.co2_emissions_kg.value)
        resolved_duration = resolved_duration if resolved_duration is not None else float(p3.voyage_metadata.voyage_duration_hours)
        resolved_aux_demand = resolved_aux_demand if resolved_aux_demand is not None else float(p3.applied_scenario_parameters.auxiliary_energy_demand_kwh)
        resolved_route = resolved_route or voyage_context.route_id
        resolved_month = resolved_month or voyage_context.month

    # If operational baseline is still unresolved, run canonical reference simulation via Phase 6 Gateway
    if resolved_fuel_L is None or resolved_co2_kg is None or resolved_soh is None or resolved_duration is None:
        def_config = CANONICAL_VOYAGE_DEFAULTS.get(params.ship_type)
        if def_config is None:
            # Fallback to general canonical values
            def_config = {
                "route_id": "Escravos-Lagos",
                "month": 7,
                "speed_knots": 12.0,
                "auxiliary_energy_demand_kwh": DEFAULT_AUXILIARY_DEMAND_KWH.get(params.ship_type, 100.0),
            }
        c_req = VoyageSimulationRequest(
            ship_type=params.ship_type,
            route_id=resolved_route or def_config["route_id"],
            month=int(resolved_month) if resolved_month is not None else int(def_config["month"]),
            speed_knots=float(def_config["speed_knots"]),
            initial_soc=initial_soc,
            soc_reserve=soc_reserve,
        )
        base_sim = simulate_voyage(c_req, ship_profiles_csv=ship_profiles_csv, nasa_clim_csv=climatology_csv)
        p2 = base_sim.tier1_predictions
        p3 = base_sim.phase3_output
        resolved_soh = resolved_soh if resolved_soh is not None else float(p2.battery_health.predicted_soh)
        resolved_fuel_L = resolved_fuel_L if resolved_fuel_L is not None else float(p2.fuel_consumption_L.value)
        resolved_co2_kg = resolved_co2_kg if resolved_co2_kg is not None else float(p2.co2_emissions_kg.value)
        resolved_duration = resolved_duration if resolved_duration is not None else float(p3.voyage_metadata.voyage_duration_hours)
        resolved_aux_demand = resolved_aux_demand if resolved_aux_demand is not None else float(p3.applied_scenario_parameters.auxiliary_energy_demand_kwh)
        resolved_route = resolved_route or c_req.route_id
        resolved_month = resolved_month or c_req.month

    if resolved_aux_demand is None:
        resolved_aux_demand = DEFAULT_AUXILIARY_DEMAND_KWH.get(params.ship_type, 100.0)

    # 3. Generate deterministic discrete lattice
    solar_lattice = generate_sizing_lattice(
        min_val=params.min_solar_area_m2,
        max_val=res_max_solar,
        step_val=params.step_solar_area_m2,
    )
    battery_lattice = generate_sizing_lattice(
        min_val=params.min_battery_capacity_kwh,
        max_val=res_max_battery,
        step_val=res_step_battery,
    )

    solar_count = len(solar_lattice)
    battery_count = len(battery_lattice)
    total_candidates = solar_count * battery_count

    if total_candidates > MAX_CANDIDATES_ALLOWED:
        raise ValueError(
            f"Total grid points ({total_candidates}) exceeds maximum allowed ({MAX_CANDIDATES_ALLOWED}). "
            f"Increase discrete step sizes (step_solar={params.step_solar_area_m2}, step_battery={res_step_battery}) "
            f"or narrow search bounds."
        )

    # 4. Exhaustive Grid Search Evaluation
    # Traversal order: ascending solar area, then ascending battery capacity
    candidate_results: List[OptimizationCandidate] = []
    feasible_count = 0
    infeasible_count = 0

    for a_pv in solar_lattice:
        for e_batt in battery_lattice:
            cand = evaluate_single_sizing_candidate(
                solar_area_m2=a_pv,
                battery_capacity_kwh=e_batt,
                params=params,
                deck_area_limit_m2=deck_area_limit,
                battery_weight_limit_tonnes=battery_weight_limit,
                predicted_soh=resolved_soh,
                auxiliary_energy_demand_kwh=resolved_aux_demand,
                voyage_duration_hours=resolved_duration,
                predicted_fuel_consumption_L=resolved_fuel_L,
                predicted_CO2_kg=resolved_co2_kg,
                route_id=resolved_route,
                month=resolved_month,
                daily_ghi_kwh_per_m2=daily_ghi_kwh_per_m2,
                initial_soc=initial_soc,
                soc_reserve=soc_reserve,
                solar_derate_factor=solar_derate_factor,
                generator_sfoc_kg_per_kwh=generator_sfoc_kg_per_kwh,
                fuel_density_kg_per_l=fuel_density_kg_per_l,
                emission_factor_kgco2_per_kgfuel=emission_factor_kgco2_per_kgfuel,
                ship_profiles_csv=ship_profiles_csv,
                climatology_csv=climatology_csv,
            )
            candidate_results.append(cand)
            if cand.candidate_status == "VALID":
                feasible_count += 1
            else:
                infeasible_count += 1

    # 5. Extract eligible ranking pool
    eligible_candidates = [c for c in candidate_results if c.candidate_status == "VALID"]

    optimal_candidate: Optional[OptimizationCandidate] = None
    top_candidates: List[OptimizationCandidate] = []
    tie_candidates_notes: List[str] = []
    pareto_frontier: List[OptimizationCandidate] = []
    diagnostics: str = "OPTIMIZATION_COMPLETED"

    # Multi-Objective Pareto Frontier Mode
    if params.objective == "PARETO_FRONTIER":
        pareto_objs = params.pareto_objectives or ["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"]
        if not eligible_candidates:
            diagnostics = "NO_FEASIBLE_CANDIDATE_FOUND"
            warnings.append("No candidate sizing points satisfied all hard physical and economic boundaries.")
        else:
            for cand_x in eligible_candidates:
                dominated = False
                for cand_y in eligible_candidates:
                    if _pareto_dominates(cand_y, cand_x, pareto_objs, eps_rel=EPSILON_RELATIVE):
                        dominated = True
                        break
                if not dominated:
                    pareto_frontier.append(cand_x)

            # Deterministic sorting of Pareto frontier dynamically ordered by configured pareto_objs
            pareto_frontier.sort(key=lambda c: _pareto_sort_key(c, pareto_objs))
            top_candidates = list(pareto_frontier)
            optimal_candidate = None  # Pareto frontier defines a tradeoff set rather than single scalar optimum

    # Single-Objective Optimization Mode
    else:
        # Special check for MIN_LCOE: filter out candidates where LCOE is None
        if params.objective == "MIN_LCOE":
            lcoe_candidates = [c for c in eligible_candidates if c.lcoe_usd_per_kwh is not None]
            if not eligible_candidates:
                diagnostics = "NO_FEASIBLE_CANDIDATE_FOUND"
                warnings.append("No candidate sizing points satisfied all hard physical and economic boundaries.")
            elif not lcoe_candidates:
                diagnostics = "NO_VALID_LCOE_CANDIDATE"
                warnings.append(
                    "All feasible candidates generated zero clean energy utilization, yielding undefined LCOE (None). "
                    "No valid numeric LCOE candidate exists on the grid."
                )
            else:
                sorted_candidates = sorted(
                    lcoe_candidates,
                    key=functools.cmp_to_key(lambda x, y: compare_candidates(x, y, params.objective, EPSILON_RELATIVE)),
                )
                optimal_candidate = sorted_candidates[0]
                best_val = optimal_candidate.objective_value
                tol = EPSILON_RELATIVE * max(1.0, abs(best_val))
                top_candidates = [c for c in sorted_candidates if abs(c.objective_value - best_val) <= tol]

        else:
            if not eligible_candidates:
                diagnostics = "NO_FEASIBLE_CANDIDATE_FOUND"
                warnings.append("No candidate sizing points satisfied all hard physical and economic boundaries.")
            else:
                # Stable sort using deterministic comparator
                sorted_candidates = sorted(
                    eligible_candidates,
                    key=functools.cmp_to_key(lambda x, y: compare_candidates(x, y, params.objective, EPSILON_RELATIVE)),
                )
                optimal_candidate = sorted_candidates[0]
                best_val = optimal_candidate.objective_value
                tol = EPSILON_RELATIVE * max(1.0, abs(best_val))
                top_candidates = [c for c in sorted_candidates if abs(c.objective_value - best_val) <= tol]

        # Record tie diagnostics if multiple candidates tied on primary objective
        if len(top_candidates) > 1:
            tie_candidates_notes.append(
                f"Identified {len(top_candidates)} candidates tied on primary objective '{params.objective}' "
                f"within relative tolerance {EPSILON_RELATIVE}. Optimal candidate resolved via deterministic tie-breaking: "
                f"min CAPEX_0 (${optimal_candidate.total_initial_capex_usd:,.2f}) -> "
                f"min A_pv ({optimal_candidate.solar_area_m2} m2) -> "
                f"min E_batt ({optimal_candidate.battery_capacity_kwh} kWh)."
            )

    return OptimizationResult(
        parameters=params,
        resolved_max_solar_area_m2=res_max_solar,
        resolved_max_battery_capacity_kwh=res_max_battery,
        resolved_step_battery_capacity_kwh=res_step_battery,
        solar_candidate_count=solar_count,
        battery_candidate_count=battery_count,
        total_candidates_evaluated=total_candidates,
        feasible_candidates_count=feasible_count,
        infeasible_candidates_count=infeasible_count,
        optimal_candidate=optimal_candidate,
        top_candidates=top_candidates,
        tie_candidates_notes=tie_candidates_notes,
        pareto_frontier=pareto_frontier,
        candidate_results=candidate_results,
        diagnostics=diagnostics,
        warnings=warnings,
    )


# ==============================================================================
# 7. Upstream Integration Adapters
# ==============================================================================
def evaluate_single_voyage_sizing(
    params: OptimizationParameters,
    simulation_result: Optional[Phase6SimulationResult] = None,
    voyage_request: Optional[VoyageSimulationRequest] = None,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> OptimizationResult:
    """
    Adapter executing parametric sizing optimization conditioned on a verified
    Phase 6 single-voyage simulation result or user voyage request.
    """
    context = simulation_result if simulation_result is not None else voyage_request
    return optimize_system_sizing(
        params=params,
        voyage_context=context,
        ship_profiles_csv=ship_profiles_csv,
        climatology_csv=climatology_csv,
    )


def evaluate_annual_schedule_sizing(
    params: OptimizationParameters,
    annual_schedule_request: Any,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> OptimizationResult:
    """
    Adapter executing parametric sizing optimization across a multi-voyage operational schedule.
    Aggregates multi-voyage clean energy utilization and fuel displacements directly.
    """
    # Extract voyages from schedule request if provided
    schedule = getattr(annual_schedule_request, "schedule", None)
    if schedule is None or not isinstance(schedule, list) or len(schedule) == 0:
        # Fall back to single-voyage scaling if schedule is not a list of voyages
        return optimize_system_sizing(
            params=params,
            ship_profiles_csv=ship_profiles_csv,
            climatology_csv=climatology_csv,
        )

    # Use first voyage as baseline operational archetype
    first_voyage = schedule[0]
    first_meta = getattr(first_voyage, "voyage_metadata", None)
    first_p2 = getattr(first_voyage, "tier_1_phase2_predictions", None)

    dur = getattr(first_meta, "voyage_duration_hours", 20.0) if first_meta else 20.0
    soh = getattr(first_p2.battery_health, "predicted_soh", 0.98) if first_p2 else 0.98
    fuel = getattr(first_p2.fuel_consumption_L, "value", 5000.0) if first_p2 else 5000.0
    co2 = getattr(first_p2.co2_emissions_kg, "value", 15000.0) if first_p2 else 15000.0

    # Override annual_voyages with schedule length if default
    adjusted_params = params.model_copy(update={"annual_voyages": len(schedule)})

    return optimize_system_sizing(
        params=adjusted_params,
        predicted_soh=soh,
        voyage_duration_hours=dur,
        predicted_fuel_consumption_L=fuel,
        predicted_CO2_kg=co2,
        route_id=getattr(first_voyage, "route_id", "Escravos-Lagos"),
        month=getattr(first_voyage, "month", 7),
        ship_profiles_csv=ship_profiles_csv,
        climatology_csv=climatology_csv,
    )
