"""
phase7_economics.py — Lifecycle Techno-Economic & Capital Budgeting Engine
==========================================================================
Implements the frozen Phase 7 specification:
  1. Strict bunker fuel price resolution hierarchy (User override -> Catalog -> Explicit ValueError).
  2. Modular Capital Expenditure (CAPEX) accounting (Solar, Battery, BOP/Inverter, Installation).
  3. Annual Lifecycle Cash Flow generator (Years 0 to N) with end-of-year discounting.
  4. Operational Expenditure (OPEX), scheduled battery replacement, and terminal salvage accounting.
  5. Quantitative Capital Budgeting Metrics:
     - Net Present Value (NPV)
     - Simple Payback Period with exact fractional-year linear interpolation
     - Discounted Payback Period with exact fractional-year linear interpolation
     - Levelized Cost of Clean Energy (LCOE) using strictly verified utilized energy
     - Deterministic Internal Rate of Return (IRR) via 550-subinterval bracketed Brent root search
  6. High-level adapters for Phase 3G AnnualScheduleSummary and Phase 6 Phase6SimulationResult.

Zero evaluative investment decisions ("VIABLE" / "UNECONOMIC") — objective diagnostic metrics only.
Zero modification to frozen upstream models or simulation logic.
"""

import os
import math
from typing import Dict, Any, Optional, List, Tuple, Union
import numpy as np
import pandas as pd
from scipy.optimize import brentq

from phase7_contracts import (
    FinancialParameters,
    LifecycleCashFlow,
    InvestmentAppraisalResult,
)


# ==============================================================================
# 1. Reference Data Loading & Fuel Price Resolution
# ==============================================================================
def load_ship_profiles_catalog(ship_profiles_csv: Optional[str] = None) -> pd.DataFrame:
    """Load canonical ship profiles catalog with ship_type index."""
    if ship_profiles_csv is not None:
        path = ship_profiles_csv
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, "data", "reference", "ship_profiles.csv")
    
    if not os.path.exists(path):
        raise FileNotFoundError(f"Ship profiles catalog not found at: {path}")
    
    df = pd.read_csv(path)
    return df.set_index("ship_type")


def resolve_fuel_price(
    parameters: FinancialParameters,
    ship_type: Optional[str] = None,
    ship_profiles_csv: Optional[str] = None,
) -> float:
    """
    Resolve bunker fuel price under strict frozen priority:
      Priority 1: User override in FinancialParameters.fuel_price_usd_per_l
      Priority 2: Canonical ship_profiles.csv fuel_price_per_litre for vessel archetype
      Priority 3: Explicit ValueError (NO silent arbitrary fallback).
    """
    # Priority 1: User explicit override
    if parameters.fuel_price_usd_per_l is not None:
        if parameters.fuel_price_usd_per_l <= 0.0:
            raise ValueError(
                f"fuel_price_usd_per_l must be strictly positive (> 0.0), got {parameters.fuel_price_usd_per_l}"
            )
        return float(parameters.fuel_price_usd_per_l)

    # Priority 2: Catalog lookup
    if ship_type is not None:
        try:
            catalog = load_ship_profiles_catalog(ship_profiles_csv)
            if ship_type in catalog.index:
                row = catalog.loc[ship_type]
                cat_price = float(row["fuel_price_per_litre"])
                if cat_price > 0.0:
                    return cat_price
        except Exception as e:
            # If catalog fails to load, proceed to Priority 3 error
            pass

    # Priority 3: Explicit failure
    raise ValueError(
        f"Missing required fuel price: fuel_price_usd_per_l was not provided in parameters "
        f"and could not be resolved for ship_type='{ship_type}' from ship_profiles.csv. "
        f"Silent fallback values are prohibited."
    )


def resolve_ship_sizing(
    ship_type: Optional[str] = None,
    solar_area_m2_override: Optional[float] = None,
    battery_capacity_kwh_override: Optional[float] = None,
    ship_profiles_csv: Optional[str] = None,
) -> Tuple[float, float]:
    """Resolve physical solar surface area and nominal battery capacity."""
    solar_m2 = solar_area_m2_override
    battery_kwh = battery_capacity_kwh_override

    if (solar_m2 is None or battery_kwh is None) and ship_type is not None:
        try:
            catalog = load_ship_profiles_catalog(ship_profiles_csv)
            if ship_type in catalog.index:
                row = catalog.loc[ship_type]
                if solar_m2 is None:
                    solar_m2 = float(row["solar_panel_size_m2"])
                if battery_kwh is None:
                    battery_kwh = float(row["battery_pack_capacity_kwh"])
        except Exception:
            pass

    if solar_m2 is None:
        solar_m2 = 0.0
    if battery_kwh is None:
        battery_kwh = 0.0

    if solar_m2 < 0.0:
        raise ValueError(f"solar_area_m2 cannot be negative, got {solar_m2}")
    if battery_kwh < 0.0:
        raise ValueError(f"battery_capacity_kwh cannot be negative, got {battery_kwh}")

    return float(solar_m2), float(battery_kwh)


# ==============================================================================
# 2. CAPEX & Lifecycle Cash Flow Generator
# ==============================================================================
def calculate_initial_capex(
    solar_area_m2: float,
    battery_capacity_kwh: float,
    parameters: FinancialParameters,
) -> float:
    """
    Calculate total initial overnight capital expenditure at t=0:
      CAPEX0 = (solar_area_m2 * solar_capex_usd_per_m2)
             + (battery_capacity_kwh * battery_capex_usd_per_kwh)
             + inverter_bop_capex_usd
             + installation_retrofit_capex_usd
    """
    solar_capex = solar_area_m2 * parameters.solar_capex_usd_per_m2
    battery_capex = battery_capacity_kwh * parameters.battery_capex_usd_per_kwh
    total_capex = (
        solar_capex
        + battery_capex
        + parameters.inverter_bop_capex_usd
        + parameters.installation_retrofit_capex_usd
    )
    return float(total_capex)


def generate_lifecycle_cash_flows(
    capex_0: float,
    annual_fuel_displaced_L: float,
    resolved_fuel_price_usd_per_l: float,
    annual_clean_energy_utilized_kwh: float,
    annual_co2_displaced_kg: float,
    battery_capacity_kwh: float,
    parameters: FinancialParameters,
) -> List[LifecycleCashFlow]:
    """
    Generate annual lifecycle accounting cash flows for t = 0 ... N.
    Timing Convention:
      - t = 0: Overnight initial CAPEX. Zero operational benefits.
      - t >= 1: End-of-year fuel/carbon savings, OPEX, periodic replacement, and terminal salvage.
    """
    horizon = parameters.analysis_horizon_years
    r = parameters.discount_rate
    cash_flows: List[LifecycleCashFlow] = []

    # t = 0: Initial Investment
    cf_0 = LifecycleCashFlow(
        year=0,
        capex_usd=-capex_0,
        opex_usd=0.0,
        fuel_savings_usd=0.0,
        carbon_savings_usd=0.0,
        replacement_expenditure_usd=0.0,
        salvage_value_usd=0.0,
        net_cash_flow_usd=-capex_0,
        discount_factor=1.0,
        discounted_cash_flow_usd=-capex_0,
        cumulative_cash_flow_usd=-capex_0,
        cumulative_discounted_cash_flow_usd=-capex_0,
        clean_energy_utilized_kwh=0.0,
        discounted_clean_energy_kwh=0.0,
    )
    cash_flows.append(cf_0)

    cum_ncf = -capex_0
    cum_d_ncf = -capex_0

    # t = 1 ... N: Operating Years
    for t in range(1, horizon + 1):
        # 1. Fuel savings with annual escalation
        fuel_price_t = resolved_fuel_price_usd_per_l * ((1.0 + parameters.fuel_escalation_rate) ** (t - 1))
        fuel_savings_t = annual_fuel_displaced_L * fuel_price_t

        # 2. Carbon savings (zero if carbon_price == 0.0)
        carbon_savings_t = (annual_co2_displaced_kg / 1000.0) * parameters.carbon_price_usd_per_tonne

        # 3. Annual routine OPEX
        opex_t = capex_0 * parameters.opex_pct_of_capex

        # 4. Periodic battery replacement (strictly t < N and interval multiples)
        replacement_t = 0.0
        if (
            parameters.battery_replacement_interval_years is not None
            and parameters.battery_replacement_interval_years > 0
            and t < horizon
            and t % parameters.battery_replacement_interval_years == 0
        ):
            replacement_t = battery_capacity_kwh * parameters.battery_replacement_cost_usd_per_kwh

        # 5. Terminal salvage value (strictly at t = N)
        salvage_t = 0.0
        if t == horizon:
            salvage_t = capex_0 * parameters.salvage_value_pct

        # 6. Net cash flow
        net_cash_flow_t = fuel_savings_t + carbon_savings_t - opex_t - replacement_t + salvage_t

        # 7. Discounting
        df_t = (1.0 + r) ** (-t)
        discounted_ncf_t = net_cash_flow_t * df_t

        cum_ncf += net_cash_flow_t
        cum_d_ncf += discounted_ncf_t

        # 8. Clean energy discounting (using exact same r)
        d_clean_energy_t = annual_clean_energy_utilized_kwh * df_t

        cash_flows.append(
            LifecycleCashFlow(
                year=t,
                capex_usd=0.0,
                opex_usd=float(opex_t),
                fuel_savings_usd=float(fuel_savings_t),
                carbon_savings_usd=float(carbon_savings_t),
                replacement_expenditure_usd=float(replacement_t),
                salvage_value_usd=float(salvage_t),
                net_cash_flow_usd=float(net_cash_flow_t),
                discount_factor=float(df_t),
                discounted_cash_flow_usd=float(discounted_ncf_t),
                cumulative_cash_flow_usd=float(cum_ncf),
                cumulative_discounted_cash_flow_usd=float(cum_d_ncf),
                clean_energy_utilized_kwh=float(annual_clean_energy_utilized_kwh),
                discounted_clean_energy_kwh=float(d_clean_energy_t),
            )
        )

    return cash_flows


# ==============================================================================
# 3. Capital Budgeting Metrics: NPV, Payback, IRR, LCOE
# ==============================================================================
def calculate_payback_period(
    cash_flows: List[LifecycleCashFlow],
    discounted: bool = False,
) -> Tuple[Optional[float], str]:
    """
    Calculate Simple or Discounted Payback Period with exact linear fraction-of-year interpolation.
    Returns (payback_years, status).
    """
    cum_key = "cumulative_discounted_cash_flow_usd" if discounted else "cumulative_cash_flow_usd"
    achieved_label = "DISCOUNTED_PAYBACK_ACHIEVED" if discounted else "PAYBACK_ACHIEVED"
    unachieved_label = (
        "DISCOUNTED_PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON"
        if discounted
        else "PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON"
    )

    c_0 = getattr(cash_flows[0], cum_key)
    if c_0 >= 0.0:
        return 0.0, achieved_label

    for t in range(1, len(cash_flows)):
        c_prev = getattr(cash_flows[t - 1], cum_key)
        c_curr = getattr(cash_flows[t], cum_key)

        if c_curr >= 0.0:
            delta = c_curr - c_prev
            if delta > 0.0:
                frac = abs(c_prev) / delta
            else:
                frac = 0.0
            payback = (t - 1) + frac
            return round(payback, 4), achieved_label

    return None, unachieved_label


def calculate_irr(
    cash_flows: List[LifecycleCashFlow],
    capex_0: float,
) -> Tuple[Optional[float], str, List[str]]:
    """
    Calculate Internal Rate of Return (IRR) via frozen deterministic root-finding:
      - All-zero check -> IRR_DEGENERATE_ZERO_CASH_FLOW
      - All-negative check -> IRR_NOT_APPLICABLE_ALL_NEGATIVE
      - All-positive check -> IRR_NOT_APPLICABLE_ALL_POSITIVE
      - Zero CAPEX with mixed signs -> IRR_NOT_APPLICABLE_ZERO_CAPEX
      - 550 subinterval scan over [-0.50, 5.00] using Brent's method
      - Strict root uniqueness enforcement; multiple roots return None.
    """
    ncfs = [cf.net_cash_flow_usd for cf in cash_flows]
    warnings: List[str] = []
    eps = 1e-9

    # 1. All-zero cash flows
    if all(abs(x) < eps for x in ncfs):
        return None, "IRR_DEGENERATE_ZERO_CASH_FLOW", warnings

    # 2. All-negative cash flows (with at least one strictly negative)
    if all(x <= eps for x in ncfs) and any(x < -eps for x in ncfs):
        return None, "IRR_NOT_APPLICABLE_ALL_NEGATIVE", warnings

    # 3. All-positive cash flows (with at least one strictly positive)
    if all(x >= -eps for x in ncfs) and any(x > eps for x in ncfs):
        return None, "IRR_NOT_APPLICABLE_ALL_POSITIVE", warnings

    # 4. Zero-CAPEX with mixed signs
    if abs(capex_0) < eps and any(x > eps for x in ncfs) and any(x < -eps for x in ncfs):
        return None, "IRR_NOT_APPLICABLE_ZERO_CAPEX", warnings

    # 5. Numerical root search
    def npv_at_rate(r: float) -> float:
        val = 0.0
        for t, flow in enumerate(ncfs):
            val += flow / ((1.0 + r) ** t)
        return val

    # Grid of 550 subintervals across [-0.50, 5.00] (step 0.01)
    r_grid = np.linspace(-0.50, 5.00, 551)
    npv_grid = [npv_at_rate(r) for r in r_grid]

    detected_roots: List[float] = []

    for i in range(len(r_grid) - 1):
        r_a, r_b = r_grid[i], r_grid[i + 1]
        f_a, f_b = npv_grid[i], npv_grid[i + 1]

        if f_a * f_b <= 0.0:
            try:
                root = brentq(npv_at_rate, r_a, r_b, xtol=1e-7, maxiter=100)
                # Deduplicate roots within tolerance 1e-4
                if not any(abs(root - existing) < 1e-4 for existing in detected_roots):
                    detected_roots.append(root)
            except Exception:
                pass

    if len(detected_roots) == 0:
        return None, "IRR_NO_ROOT", warnings
    elif len(detected_roots) == 1:
        irr_pct = round(detected_roots[0] * 100.0, 4)
        return irr_pct, "IRR_UNIQUE_ROOT", warnings
    else:
        root_pcts = [round(r * 100.0, 4) for r in detected_roots]
        warnings.append(
            f"Multiple IRR roots detected in search interval [-50%, +500%]: {root_pcts}%. "
            f"IRR returned as None to prevent arbitrary root selection."
        )
        return None, "IRR_MULTIPLE_ROOTS", warnings


def calculate_lcoe(
    cash_flows: List[LifecycleCashFlow],
    capex_0: float,
    salvage_val_N: float,
    parameters: FinancialParameters,
) -> Tuple[Optional[float], str]:
    """
    Calculate Levelized Cost of Clean Energy (LCOE) using strictly verified utilized energy:
      PV_cost = CAPEX0 + sum(OPEX_t/(1+r)^t) + sum(Replacement_t/(1+r)^t) - Salvage_N/(1+r)^N
      PV_energy = sum(E_utilized,t/(1+r)^t)
      LCOE = PV_cost / PV_energy
    """
    r = parameters.discount_rate
    horizon = parameters.analysis_horizon_years

    pv_energy = sum(cf.discounted_clean_energy_kwh for cf in cash_flows[1:])

    if pv_energy <= 1e-9:
        return None, "LCOE_UNDEFINED_ZERO_ENERGY"

    pv_cost = capex_0
    for cf in cash_flows[1:]:
        pv_cost += (cf.opex_usd + cf.replacement_expenditure_usd) * cf.discount_factor
    
    # Terminal salvage deduction discounted at year N
    salvage_df = (1.0 + r) ** (-horizon)
    pv_cost -= salvage_val_N * salvage_df

    lcoe = pv_cost / pv_energy
    return round(float(lcoe), 6), "LCOE_CALCULATED"


# ==============================================================================
# 4. Primary High-Level Appraisal Engine
# ==============================================================================
def evaluate_clean_energy_investment(
    ship_type: Optional[str] = None,
    annual_fuel_displaced_L: float = 0.0,
    annual_clean_energy_utilized_kwh: float = 0.0,
    annual_co2_displaced_kg: float = 0.0,
    solar_area_m2: Optional[float] = None,
    battery_capacity_kwh: Optional[float] = None,
    parameters: Optional[FinancialParameters] = None,
    ship_profiles_csv: Optional[str] = None,
) -> InvestmentAppraisalResult:
    """
    Primary Phase 7 techno-economic appraisal API.
    Accepts physical operational metrics, resolves costs, generates lifecycle cash flows,
    and calculates quantitative investment appraisal metrics.
    """
    if parameters is None:
        params = FinancialParameters()
    else:
        params = parameters

    if annual_fuel_displaced_L < 0.0:
        raise ValueError(f"annual_fuel_displaced_L cannot be negative, got {annual_fuel_displaced_L}")
    if annual_clean_energy_utilized_kwh < 0.0:
        raise ValueError(f"annual_clean_energy_utilized_kwh cannot be negative, got {annual_clean_energy_utilized_kwh}")
    if annual_co2_displaced_kg < 0.0:
        raise ValueError(f"annual_co2_displaced_kg cannot be negative, got {annual_co2_displaced_kg}")

    # 1. Resolve bunker fuel price
    resolved_price = resolve_fuel_price(
        parameters=params,
        ship_type=ship_type,
        ship_profiles_csv=ship_profiles_csv,
    )

    # 2. Resolve hardware sizing
    resolved_solar_m2, resolved_battery_kwh = resolve_ship_sizing(
        ship_type=ship_type,
        solar_area_m2_override=solar_area_m2,
        battery_capacity_kwh_override=battery_capacity_kwh,
        ship_profiles_csv=ship_profiles_csv,
    )

    # 3. Calculate initial CAPEX
    capex_0 = calculate_initial_capex(
        solar_area_m2=resolved_solar_m2,
        battery_capacity_kwh=resolved_battery_kwh,
        parameters=params,
    )

    # 4. Generate annual cash flow schedule
    cash_flows = generate_lifecycle_cash_flows(
        capex_0=capex_0,
        annual_fuel_displaced_L=annual_fuel_displaced_L,
        resolved_fuel_price_usd_per_l=resolved_price,
        annual_clean_energy_utilized_kwh=annual_clean_energy_utilized_kwh,
        annual_co2_displaced_kg=annual_co2_displaced_kg,
        battery_capacity_kwh=resolved_battery_kwh,
        parameters=params,
    )

    # 5. Compute undiscounted accounting totals
    total_replacement_capex = sum(cf.replacement_expenditure_usd for cf in cash_flows[1:])
    total_lifecycle_opex = sum(cf.opex_usd for cf in cash_flows[1:])
    total_benefits = sum((cf.fuel_savings_usd + cf.carbon_savings_usd) for cf in cash_flows[1:])

    # 6. Net Present Value (NPV)
    npv = sum(cf.discounted_cash_flow_usd for cf in cash_flows)

    # 7. Payback Periods
    spb, spb_status = calculate_payback_period(cash_flows, discounted=False)
    dpb, dpb_status = calculate_payback_period(cash_flows, discounted=True)

    # 8. Internal Rate of Return (IRR)
    irr_val, irr_status, irr_warnings = calculate_irr(cash_flows, capex_0=capex_0)

    # 9. Levelized Cost of Clean Energy (LCOE)
    salvage_val_N = capex_0 * params.salvage_value_pct
    lcoe_val, lcoe_status = calculate_lcoe(
        cash_flows=cash_flows,
        capex_0=capex_0,
        salvage_val_N=salvage_val_N,
        parameters=params,
    )

    all_warnings = list(irr_warnings)
    if capex_0 == 0.0:
        all_warnings.append("Initial CAPEX is zero. Capital budgeting metrics reflect zero initial investment.")
    if annual_clean_energy_utilized_kwh == 0.0:
        all_warnings.append("Zero clean energy utilized. LCOE is mathematically undefined.")

    return InvestmentAppraisalResult(
        parameters=params,
        resolved_fuel_price_usd_per_l=round(resolved_price, 4),
        solar_area_m2=round(resolved_solar_m2, 2),
        battery_capacity_kwh=round(resolved_battery_kwh, 4),
        total_initial_capex_usd=round(capex_0, 2),
        total_replacement_capex_usd=round(total_replacement_capex, 2),
        total_lifecycle_opex_usd=round(total_lifecycle_opex, 2),
        total_undiscounted_benefits_usd=round(total_benefits, 2),
        net_present_value_usd=round(npv, 2),
        internal_rate_of_return_pct=irr_val,
        irr_status=irr_status,
        simple_payback_years=spb,
        payback_status=spb_status,
        discounted_payback_years=dpb,
        discounted_payback_status=dpb_status,
        lcoe_usd_per_kwh=lcoe_val,
        lcoe_status=lcoe_status,
        cash_flows=cash_flows,
        warnings=all_warnings,
    )


# ==============================================================================
# 5. Upstream Integration Adapters
# ==============================================================================
def evaluate_annual_schedule_investment(
    annual_summary: Any,
    parameters: Optional[FinancialParameters] = None,
    ship_profiles_csv: Optional[str] = None,
) -> InvestmentAppraisalResult:
    """
    Adapter consuming Phase 3G AnnualScheduleSummary output.
    Extracts ship_type, annual fuel displaced, CO2 displaced, and utilized clean energy.
    """
    ship_type = getattr(annual_summary, "ship_type", None)
    fuel_displaced_L = float(getattr(annual_summary, "total_fuel_displaced_L", 0.0))
    co2_displaced_kg = float(getattr(annual_summary, "total_co2_displaced_kg", 0.0))
    clean_utilized_kwh = float(getattr(annual_summary, "total_clean_energy_utilized_kwh", 0.0))

    return evaluate_clean_energy_investment(
        ship_type=ship_type,
        annual_fuel_displaced_L=fuel_displaced_L,
        annual_clean_energy_utilized_kwh=clean_utilized_kwh,
        annual_co2_displaced_kg=co2_displaced_kg,
        parameters=parameters,
        ship_profiles_csv=ship_profiles_csv,
    )


def evaluate_voyage_simulation_investment(
    simulation_result: Any,
    annual_voyages: int = 1,
    parameters: Optional[FinancialParameters] = None,
    ship_profiles_csv: Optional[str] = None,
) -> InvestmentAppraisalResult:
    """
    Adapter consuming Phase 6 Phase6SimulationResult output.
    Scales single-voyage fuel and clean energy metrics by annual_voyages count.
    """
    if annual_voyages < 1:
        raise ValueError(f"annual_voyages must be >= 1, got {annual_voyages}")

    # Extract ship_type
    req = getattr(simulation_result, "request", None)
    ship_type = getattr(req, "ship_type", None) if req else None

    # Extract Tier 4 displacement
    p3_out = getattr(simulation_result, "phase3_output", None)
    t4 = getattr(p3_out, "tier_4_engineering_scenario_estimates", None) if p3_out else None
    t3 = getattr(p3_out, "tier_3_clean_energy_feasibility", None) if p3_out else None

    voyage_fuel_displaced_L = float(getattr(t4, "estimated_fuel_displaced_L", 0.0)) if t4 else 0.0
    voyage_co2_displaced_kg = float(getattr(t4, "estimated_co2_displaced_kg", 0.0)) if t4 else 0.0
    voyage_clean_utilized_kwh = float(getattr(t3, "clean_energy_utilized_kwh", 0.0)) if t3 else 0.0

    annual_fuel_displaced_L = voyage_fuel_displaced_L * annual_voyages
    annual_co2_displaced_kg = voyage_co2_displaced_kg * annual_voyages
    annual_clean_energy_utilized_kwh = voyage_clean_utilized_kwh * annual_voyages

    return evaluate_clean_energy_investment(
        ship_type=ship_type,
        annual_fuel_displaced_L=annual_fuel_displaced_L,
        annual_clean_energy_utilized_kwh=annual_clean_energy_utilized_kwh,
        annual_co2_displaced_kg=annual_co2_displaced_kg,
        parameters=parameters,
        ship_profiles_csv=ship_profiles_csv,
    )
