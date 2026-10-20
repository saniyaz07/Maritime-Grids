"""
phase9_speed_cooptimizer.py — Operational Transit Speed & Hybrid Sizing Co-Optimizer
====================================================================================
Implements Phase 9 Candidate 2:
  1. Simultaneous 3D search over Operational Transit Speed (V), Solar Array Area (Apv),
     and Battery Storage Capacity (Ebatt).
  2. Quadratic voyage-fuel hydrodynamic scaling derived from cubic propulsion-power scaling
     under the Candidate 2 constant-SFOC assumption:
         F_prop(V) = F_prop_ref * (V / V_ref)^2
         F_voyage(V) = F_prop(V) + P_aux * T_voyage * SFOC_gen / rho_fuel
  3. Transit delivery deadline constraint enforcement:
         T_voyage <= T_deadline
  4. Integration with frozen Phase 8 sizing and Phase 7 capital budgeting engines.
  5. Deterministic multi-objective 3D Pareto frontier non-domination sorting across
     Transit Duration, Net Annual Fuel Consumption, and Lifecycle Net Present Value (NPV).
  6. Strict computational budgeting (max 2,500 evaluations, target latency < 2.0s).

ZERO DUPLICATION RULE:
  - Consumes frozen Phase 6 gateway for baseline inference.
  - Consumes frozen Phase 8 evaluate_single_sizing_candidate for physical/economic sizing.
  - Leaves Phase 0–8 and Phase 9 Candidate 1 code 100% untouched.
"""

from typing import List, Dict, Optional, Tuple, Any
import time
import math
import os
import pandas as pd

from phase6_gateway import (
    CANONICAL_ROUTE_DISTANCES,
    TANKER_CANONICAL_DISTANCES,
    DEFAULT_AUXILIARY_DEMAND_KWH,
    simulate_voyage,
)
from phase6_contracts import VoyageSimulationRequest
from phase7_contracts import FinancialParameters
from phase8_contracts import (
    OptimizationParameters,
    SMALL_CRAFT_TYPES,
    LARGE_VESSEL_TYPES,
)
from phase8_optimizer import (
    evaluate_single_sizing_candidate,
    get_vessel_clean_energy_specs,
    EPSILON_RELATIVE,
    EPSILON_ABSOLUTE,
)
from phase9_speed_contracts import (
    SpeedCoOptimizationParameters,
    SpeedSizingCandidate,
    SpeedCoOptimizationResult,
    DEFAULT_SPEED_STEP_KNOTS,
    VALID_SPEED_PARETO_OBJECTIVES,
    MAX_SPEED_EVALUATIONS_LIMIT,
    MAX_EXECUTION_TIME_LIMIT_SECONDS,
)


# ==============================================================================
# 1. Parameter and Lattice Resolution Helpers
# ==============================================================================
def resolve_route_distance(
    ship_type: str,
    route_id: str,
    distance_override_nm: Optional[float] = None,
) -> float:
    """Resolve voyage distance from canonical tables or explicit user override."""
    if distance_override_nm is not None:
        if distance_override_nm <= 0.0 or not math.isfinite(distance_override_nm):
            raise ValueError(f"distance_override_nm must be strictly positive, got {distance_override_nm}")
        return float(distance_override_nm)

    if ship_type == "Tanker Ship":
        return float(TANKER_CANONICAL_DISTANCES.get(route_id, 250.0))
    return float(CANONICAL_ROUTE_DISTANCES.get(route_id, 250.0))


def resolve_vessel_design_profile(
    ship_type: str,
    ship_profiles_csv: Optional[str] = None,
) -> Dict[str, Any]:
    """Load vessel design specifications from ship_profiles.csv."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sp_path = ship_profiles_csv or os.path.join(base_dir, "data", "reference", "ship_profiles.csv")
    df_sp = pd.read_csv(sp_path).set_index("ship_type")

    if ship_type not in df_sp.index:
        raise ValueError(f"Unknown ship_type '{ship_type}'. Available: {list(df_sp.index)}")

    row = df_sp.loc[ship_type]
    return {
        "max_speed_knots": float(row["max_speed_knots"]),
        "dwt_tonnes": float(row["dwt_tonnes"]),
        "displacement_tonnes": float(row["displacement_tonnes"]),
        "hull_length_m": float(row["hull_length_m"]),
        "hull_beam_m": float(row["hull_beam_m"]),
        "engine_power_kw": float(row["engine_power_kw"]),
        "battery_pack_capacity_kwh": float(row["battery_pack_capacity_kwh"]),
        "solar_panel_size_m2": float(row["solar_panel_size_m2"]),
        "solar_panel_efficiency_pct": float(row["solar_panel_efficiency_pct"]),
    }


def resolve_speed_lattice(
    ship_type: str,
    profile: Dict[str, Any],
    vmin: Optional[float],
    vmax: Optional[float],
    v_step: Optional[float],
) -> Tuple[List[float], float, float, float, float]:
    """
    Generate deterministic discrete speed steps spanning [vmin, vmax].
    Returns (speeds, Vref, vmin, vmax, v_step).
    """
    v_design = profile["max_speed_knots"]
    v_ref = v_design

    res_vmax = vmax if vmax is not None else v_design
    if res_vmax <= 0.0 or not math.isfinite(res_vmax):
        raise ValueError(f"vmax must be strictly positive and finite, got {res_vmax}")
    if res_vmax > v_design + EPSILON_ABSOLUTE:
        raise ValueError(f"Requested vmax ({res_vmax} kn) exceeds vessel maximum design speed ({v_design} kn).")

    res_vmin = vmin if vmin is not None else round(0.60 * v_design, 2)
    if res_vmin <= 0.0 or not math.isfinite(res_vmin):
        raise ValueError(f"vmin must be strictly positive and finite, got {res_vmin}")
    if res_vmin > res_vmax:
        raise ValueError(f"vmin ({res_vmin} kn) cannot exceed vmax ({res_vmax} kn).")

    res_vstep = v_step if v_step is not None else DEFAULT_SPEED_STEP_KNOTS.get(ship_type, 0.5)
    if res_vstep <= 0.0 or not math.isfinite(res_vstep):
        raise ValueError(f"v_step must be strictly positive and finite, got {res_vstep}")

    num_steps = int(round((res_vmax - res_vmin) / res_vstep)) + 1
    speeds = [round(res_vmin + i * res_vstep, 4) for i in range(num_steps)]
    speeds = [s for s in speeds if s <= res_vmax + EPSILON_ABSOLUTE]

    if len(speeds) == 0:
        speeds = [res_vmax]

    return speeds, v_ref, res_vmin, res_vmax, res_vstep


def resolve_sizing_lattices(
    profile: Dict[str, Any],
    apv_min: float,
    apv_max: Optional[float],
    apv_step: float,
    ebatt_min: float,
    ebatt_max: Optional[float],
    ebatt_step: float,
    fdeck_max: float,
    fdwt_max: float,
    rho_batt: float,
) -> Tuple[List[float], List[float], float, float]:
    """Generate discrete solar PV area and battery capacity steps."""
    # Deck area bound
    deck_area = profile["hull_length_m"] * profile["hull_beam_m"]
    deck_limit = round(fdeck_max * deck_area, 2)
    res_apv_max = apv_max if apv_max is not None else deck_limit

    num_a = int(round((res_apv_max - apv_min) / apv_step)) + 1
    solar_steps = [round(apv_min + i * apv_step, 4) for i in range(num_a)]
    solar_steps = [a for a in solar_steps if a <= res_apv_max + EPSILON_ABSOLUTE]

    # Battery capacity bound
    batt_weight_limit = round(fdwt_max * profile["dwt_tonnes"], 3)
    calc_ebatt_max = round((batt_weight_limit * 1000.0) / rho_batt, 2)
    res_ebatt_max = ebatt_max if ebatt_max is not None else calc_ebatt_max

    num_e = int(round((res_ebatt_max - ebatt_min) / ebatt_step)) + 1
    battery_steps = [round(ebatt_min + j * ebatt_step, 4) for j in range(num_e)]
    battery_steps = [e for e in battery_steps if e <= res_ebatt_max + EPSILON_ABSOLUTE]

    return solar_steps, battery_steps, res_apv_max, res_ebatt_max


# ==============================================================================
# 2. Hydrodynamic Speed-Power & Baseline Fuel Scaling
# ==============================================================================
def resolve_reference_hydrodynamics(
    params: SpeedCoOptimizationParameters,
    profile: Dict[str, Any],
    distance_nm: float,
    v_ref: float,
) -> Tuple[float, float, float, float, float, float]:
    """
    Resolve baseline reference voyage fuel, auxiliary power, duration, and SOH.
    Returns (F_total_ref, F_prop_ref, P_aux_kw, T_ref, predicted_soh, daily_ghi).
    """
    t_ref = distance_nm / v_ref

    # 1. Resolve auxiliary hotel load power (kW)
    if params.paux_kw is not None:
        p_aux_kw = params.paux_kw
    else:
        e_aux_default = DEFAULT_AUXILIARY_DEMAND_KWH.get(params.ship_type, 180.0)
        p_aux_kw = e_aux_default / t_ref

    # 2. Resolve reference baseline fuel
    if params.reference_fuel_consumption_L is not None:
        f_total_ref = params.reference_fuel_consumption_L
        pred_soh = params.predicted_soh if params.predicted_soh is not None else 0.7387
        daily_ghi = params.daily_ghi_kwh_per_m2 if params.daily_ghi_kwh_per_m2 is not None else 4.50
    else:
        # Evaluate reference voyage via frozen Phase 6 gateway
        sim_req = VoyageSimulationRequest(
            ship_type=params.ship_type,
            route_id=params.route_id,
            distance_nm=distance_nm,
            month=params.month,
            speed_knots=v_ref,
        )
        sim_res = simulate_voyage(sim_req)
        f_total_ref = float(sim_res.tier1_predictions.fuel_consumption_L.value)
        pred_soh = (
            params.predicted_soh
            if params.predicted_soh is not None
            else float(sim_res.tier1_predictions.battery_health.predicted_soh)
        )
        daily_ghi = params.daily_ghi_kwh_per_m2 if params.daily_ghi_kwh_per_m2 is not None else 4.50

    # 3. Separate auxiliary fuel from propulsion fuel at V_ref
    f_aux_ref = (p_aux_kw * t_ref * params.generator_sfoc_kg_per_kwh) / params.fuel_density_kg_per_l
    f_prop_ref = max(0.0, f_total_ref - f_aux_ref)

    return f_total_ref, f_prop_ref, p_aux_kw, t_ref, pred_soh, daily_ghi


def calculate_speed_scaled_voyage(
    speed_knots: float,
    distance_nm: float,
    v_ref: float,
    f_prop_ref: float,
    p_aux_kw: float,
    sfoc_gen: float,
    rho_fuel: float,
    emission_factor_co2: float,
) -> Dict[str, float]:
    """
    Evaluate transit duration, quadratic propulsion fuel scaling, auxiliary fuel,
    total voyage baseline fuel, and total baseline CO2 at operational speed V.
    """
    t_voyage = distance_nm / speed_knots

    # Candidate 2 quadratic voyage-fuel scaling (from cubic power: P ~ V^3, T ~ 1/V => E ~ V^2)
    f_prop = f_prop_ref * ((speed_knots / v_ref) ** 2)

    # Auxiliary engine diesel consumption over transit duration
    e_aux_kwh = p_aux_kw * t_voyage
    f_aux = (e_aux_kwh * sfoc_gen) / rho_fuel

    f_voyage_total = f_prop + f_aux
    co2_voyage_kg = f_voyage_total * rho_fuel * emission_factor_co2

    return {
        "voyage_duration_hours": round(t_voyage, 4),
        "propulsion_fuel_L": round(f_prop, 4),
        "auxiliary_fuel_L": round(f_aux, 4),
        "total_fuel_L": round(f_voyage_total, 4),
        "auxiliary_demand_kwh": round(e_aux_kwh, 4),
        "co2_voyage_kg": round(co2_voyage_kg, 4),
    }


# ==============================================================================
# 3. Multi-Objective Pareto Dominance
# ==============================================================================
def pareto_dominates_speed_candidate(
    c_a: SpeedSizingCandidate,
    c_b: SpeedSizingCandidate,
    objectives: List[str],
) -> bool:
    """
    Determine if candidate A Pareto-dominates candidate B across the configured objectives.
    Only VALID, deadline-compliant candidates can dominate.
    """
    if c_a.candidate_status != "VALID" or not c_a.meets_deadline:
        return False
    if c_b.candidate_status != "VALID" or not c_b.meets_deadline:
        return True  # Valid candidate strictly dominates invalid/deadline-exceeded candidate

    def get_obj_val(cand: SpeedSizingCandidate, obj: str) -> float:
        if obj == "MIN_DURATION":
            return cand.voyage_duration_hours
        elif obj == "MIN_ANNUAL_FUEL":
            return cand.net_annual_fuel_consumed_L
        elif obj == "MAX_NPV":
            return cand.net_present_value_usd
        elif obj == "MAX_FUEL_DISPLACEMENT":
            return cand.annual_fuel_displaced_L
        elif obj == "MIN_CAPEX":
            return cand.total_initial_capex_usd
        raise ValueError(f"Unsupported objective '{obj}'")

    strictly_better_in_at_least_one = False

    for obj in objectives:
        v_a = get_obj_val(c_a, obj)
        v_b = get_obj_val(c_b, obj)

        is_minimization = obj.startswith("MIN_")

        if is_minimization:
            # For minimization: A must be <= B + eps
            if v_a > v_b + EPSILON_RELATIVE * max(1.0, abs(v_a), abs(v_b)):
                return False  # A is worse than B
            if v_a < v_b - EPSILON_RELATIVE * max(1.0, abs(v_a), abs(v_b)):
                strictly_better_in_at_least_one = True
        else:
            # For maximization: A must be >= B - eps
            if v_a < v_b - EPSILON_RELATIVE * max(1.0, abs(v_a), abs(v_b)):
                return False  # A is worse than B
            if v_a > v_b + EPSILON_RELATIVE * max(1.0, abs(v_a), abs(v_b)):
                strictly_better_in_at_least_one = True

    return strictly_better_in_at_least_one


def filter_speed_pareto_frontier(
    candidates: List[SpeedSizingCandidate],
    objectives: List[str],
) -> List[SpeedSizingCandidate]:
    """
    Extract non-dominated Pareto frontier candidates and sort deterministically:
    Ascending Duration -> Ascending Net Fuel -> Descending NPV -> Ascending CAPEX -> Apv -> Ebatt.
    """
    valid_candidates = [
        c for c in candidates if c.candidate_status == "VALID" and c.meets_deadline
    ]
    frontier: List[SpeedSizingCandidate] = []

    for i, c_i in enumerate(valid_candidates):
        dominated = False
        for j, c_j in enumerate(valid_candidates):
            if i != j and pareto_dominates_speed_candidate(c_j, c_i, objectives):
                dominated = True
                break
        if not dominated:
            frontier.append(c_i)

    # Deterministic multi-key sort
    frontier.sort(
        key=lambda c: (
            round(c.voyage_duration_hours, 4),
            round(c.net_annual_fuel_consumed_L, 2),
            -round(c.net_present_value_usd, 2),
            round(c.total_initial_capex_usd, 2),
            round(c.solar_area_m2, 2),
            round(c.battery_capacity_kwh, 2),
        )
    )
    return frontier


# ==============================================================================
# 4. Primary Co-Optimization Engine
# ==============================================================================
def optimize_speed_and_sizing(
    parameters: SpeedCoOptimizationParameters,
    ship_profiles_csv: Optional[str] = None,
) -> SpeedCoOptimizationResult:
    """
    Primary Candidate 2 orchestration and co-optimization API.
    Evaluates the 3D lattice: Speed (V) x Solar Area (Apv) x Battery Capacity (Ebatt).
    """
    t_start = time.perf_counter()
    warnings: List[str] = []

    # 1. Load vessel specifications and distance
    profile = resolve_vessel_design_profile(parameters.ship_type, ship_profiles_csv)
    distance_nm = resolve_route_distance(
        parameters.ship_type,
        parameters.route_id,
        parameters.distance_nm,
    )

    # 2. Resolve speed lattice and bounds
    speeds, v_ref, vmin, vmax, v_step = resolve_speed_lattice(
        ship_type=parameters.ship_type,
        profile=profile,
        vmin=parameters.vmin,
        vmax=parameters.vmax,
        v_step=parameters.v_step,
    )

    # 3. Validate delivery deadline feasibility
    min_possible_duration = distance_nm / vmax
    if parameters.t_deadline is not None:
        if parameters.t_deadline < min_possible_duration - EPSILON_ABSOLUTE:
            raise ValueError(
                f"t_deadline ({parameters.t_deadline:.2f} h) is less than fastest possible transit time "
                f"({min_possible_duration:.2f} h at Vmax={vmax} kn). No candidate can meet deadline."
            )

    # 4. Resolve sizing lattices
    solar_steps, battery_steps, resolved_apv_max, resolved_ebatt_max = resolve_sizing_lattices(
        profile=profile,
        apv_min=parameters.apv_min,
        apv_max=parameters.apv_max,
        apv_step=parameters.apv_step,
        ebatt_min=parameters.ebatt_min,
        ebatt_max=parameters.ebatt_max,
        ebatt_step=parameters.ebatt_step,
        fdeck_max=parameters.fdeck_max,
        fdwt_max=parameters.fdwt_max,
        rho_batt=parameters.battery_specific_mass_kg_per_kwh,
    )

    # 5. Enforce hard computational budget upfront
    total_evals = len(speeds) * len(solar_steps) * len(battery_steps)
    if total_evals > parameters.max_evaluations:
        raise ValueError(
            f"Requested 3D search lattice ({len(speeds)} speeds x {len(solar_steps)} solar x {len(battery_steps)} battery = "
            f"{total_evals} configurations) exceeds maximum computational limit of {parameters.max_evaluations}."
        )

    # 6. Resolve baseline reference hydrodynamic fuel scaling
    f_total_ref, f_prop_ref, p_aux_kw, t_ref, pred_soh, daily_ghi = resolve_reference_hydrodynamics(
        params=parameters,
        profile=profile,
        distance_nm=distance_nm,
        v_ref=v_ref,
    )

    # 7. Evaluate 3D lattice
    opt_params = OptimizationParameters(
        ship_type=parameters.ship_type,
        annual_voyages=parameters.annual_voyages,
        financial_parameters=parameters.financial_parameters,
    )
    deck_limit = parameters.fdeck_max * profile["hull_length_m"] * profile["hull_beam_m"]
    batt_weight_limit = parameters.fdwt_max * profile["dwt_tonnes"]

    candidate_results: List[SpeedSizingCandidate] = []
    speed_tradeoff_map: Dict[float, SpeedSizingCandidate] = {}

    valid_count = 0
    deadline_exceeded_count = 0

    for v in speeds:
        scaled_hydro = calculate_speed_scaled_voyage(
            speed_knots=v,
            distance_nm=distance_nm,
            v_ref=v_ref,
            f_prop_ref=f_prop_ref,
            p_aux_kw=p_aux_kw,
            sfoc_gen=parameters.generator_sfoc_kg_per_kwh,
            rho_fuel=parameters.fuel_density_kg_per_l,
            emission_factor_co2=parameters.emission_factor_kgco2_per_kgfuel,
        )
        t_voyage = scaled_hydro["voyage_duration_hours"]
        meets_deadline = (
            parameters.t_deadline is None
            or t_voyage <= parameters.t_deadline + EPSILON_ABSOLUTE
        )

        for a_pv in solar_steps:
            for e_batt in battery_steps:
                # Phase 8 single candidate physical feasibility and capital budgeting
                phase8_cand = evaluate_single_sizing_candidate(
                    solar_area_m2=a_pv,
                    battery_capacity_kwh=e_batt,
                    params=opt_params,
                    deck_area_limit_m2=deck_limit,
                    battery_weight_limit_tonnes=batt_weight_limit,
                    predicted_soh=pred_soh,
                    auxiliary_energy_demand_kwh=scaled_hydro["auxiliary_demand_kwh"],
                    voyage_duration_hours=t_voyage,
                    predicted_fuel_consumption_L=scaled_hydro["total_fuel_L"],
                    predicted_CO2_kg=scaled_hydro["co2_voyage_kg"],
                    route_id=parameters.route_id,
                    month=parameters.month,
                    daily_ghi_kwh_per_m2=daily_ghi,
                    ship_profiles_csv=ship_profiles_csv,
                )

                # Determine overall candidate status
                violations = list(phase8_cand.constraint_violations)
                if not meets_deadline:
                    violations.append("DEADLINE_EXCEEDED")
                    status = "DEADLINE_EXCEEDED"
                    deadline_exceeded_count += 1
                else:
                    status = phase8_cand.candidate_status
                    if status == "VALID":
                        valid_count += 1

                # Net annual operational totals
                gross_annual_fuel = scaled_hydro["total_fuel_L"] * parameters.annual_voyages
                net_annual_fuel = max(0.0, gross_annual_fuel - phase8_cand.annual_fuel_displaced_L)
                net_annual_co2 = net_annual_fuel * parameters.fuel_density_kg_per_l * parameters.emission_factor_kgco2_per_kgfuel

                # Construct 3D candidate audit record
                candidate = SpeedSizingCandidate(
                    speed_knots=v,
                    solar_area_m2=a_pv,
                    battery_capacity_kwh=e_batt,
                    battery_mass_tonnes=phase8_cand.battery_mass_tonnes,
                    voyage_duration_hours=t_voyage,
                    meets_deadline=meets_deadline,
                    is_physically_valid=phase8_cand.is_physically_valid and meets_deadline,
                    constraint_violations=violations,
                    candidate_status=status,
                    single_voyage_propulsion_fuel_L=scaled_hydro["propulsion_fuel_L"],
                    single_voyage_auxiliary_fuel_L=scaled_hydro["auxiliary_fuel_L"],
                    single_voyage_total_fuel_L=scaled_hydro["total_fuel_L"],
                    clean_energy_utilized_kwh=phase8_cand.clean_energy_utilized_kwh,
                    annual_fuel_displaced_L=phase8_cand.annual_fuel_displaced_L,
                    annual_co2_displaced_kg=phase8_cand.annual_co2_displaced_kg,
                    feasibility_status=phase8_cand.feasibility_status,
                    annual_fuel_consumed_L=gross_annual_fuel,
                    net_annual_fuel_consumed_L=net_annual_fuel,
                    annual_co2_emissions_kg=net_annual_co2,
                    total_initial_capex_usd=phase8_cand.total_initial_capex_usd,
                    net_present_value_usd=phase8_cand.net_present_value_usd,
                    internal_rate_of_return_pct=phase8_cand.internal_rate_of_return_pct,
                    irr_status=phase8_cand.irr_status,
                    simple_payback_years=phase8_cand.simple_payback_years,
                    discounted_payback_years=phase8_cand.discounted_payback_years,
                    lcoe_usd_per_kwh=phase8_cand.lcoe_usd_per_kwh,
                    lcoe_status=phase8_cand.lcoe_status,
                    objective_values={
                        "MIN_DURATION": t_voyage,
                        "MIN_ANNUAL_FUEL": net_annual_fuel,
                        "MAX_NPV": phase8_cand.net_present_value_usd,
                        "MAX_FUEL_DISPLACEMENT": phase8_cand.annual_fuel_displaced_L,
                        "MIN_CAPEX": phase8_cand.total_initial_capex_usd,
                    },
                )
                candidate_results.append(candidate)

                # Track best sizing candidate at this speed (by NPV if valid)
                if meets_deadline and status == "VALID":
                    if v not in speed_tradeoff_map or candidate.net_present_value_usd > speed_tradeoff_map[v].net_present_value_usd:
                        speed_tradeoff_map[v] = candidate

    # 8. Compute non-dominated 3D Pareto frontier
    pareto_frontier = filter_speed_pareto_frontier(
        candidate_results,
        parameters.pareto_objectives,
    )

    # 9. Identify single optimal candidate
    valid_cands = [c for c in candidate_results if c.candidate_status == "VALID" and c.meets_deadline]
    optimal_candidate: Optional[SpeedSizingCandidate] = None

    if len(valid_cands) > 0:
        if parameters.objective == "MIN_ANNUAL_FUEL":
            valid_cands.sort(key=lambda c: (c.net_annual_fuel_consumed_L, -c.net_present_value_usd))
            optimal_candidate = valid_cands[0]
        elif parameters.objective == "MAX_NPV":
            valid_cands.sort(key=lambda c: (-c.net_present_value_usd, c.net_annual_fuel_consumed_L))
            optimal_candidate = valid_cands[0]
        elif parameters.objective == "MIN_DURATION":
            valid_cands.sort(key=lambda c: (c.voyage_duration_hours, c.net_annual_fuel_consumed_L))
            optimal_candidate = valid_cands[0]
        else:
            # PARETO_FRONTIER: highest NPV on frontier
            if len(pareto_frontier) > 0:
                pareto_sorted = sorted(pareto_frontier, key=lambda c: -c.net_present_value_usd)
                optimal_candidate = pareto_sorted[0]
            else:
                optimal_candidate = valid_cands[0]

    speed_tradeoff_curve = [speed_tradeoff_map[s] for s in sorted(speed_tradeoff_map.keys())]
    elapsed = time.perf_counter() - t_start

    diagnostics = "OPTIMIZATION_COMPLETED"
    if valid_count == 0:
        diagnostics = "NO_VALID_CANDIDATE_FOUND"
        warnings.append("No candidates satisfied both physical boundaries and transit deadline constraints.")

    return SpeedCoOptimizationResult(
        parameters=parameters,
        resolved_distance_nm=distance_nm,
        resolved_vref_knots=v_ref,
        resolved_vmin_knots=vmin,
        resolved_vmax_knots=vmax,
        resolved_vstep_knots=v_step,
        speed_candidate_count=len(speeds),
        solar_candidate_count=len(solar_steps),
        battery_candidate_count=len(battery_steps),
        total_configurations_evaluated=len(candidate_results),
        valid_candidates_count=valid_count,
        deadline_exceeded_count=deadline_exceeded_count,
        optimal_candidate=optimal_candidate,
        speed_tradeoff_curve=speed_tradeoff_curve,
        pareto_frontier=pareto_frontier,
        candidate_results=candidate_results,
        execution_time_seconds=round(elapsed, 4),
        diagnostics=diagnostics,
        warnings=warnings,
    )
