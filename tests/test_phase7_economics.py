"""
test_phase7_economics.py — Comprehensive Test Suite for Phase 7 Lifecycle Techno-Economics
===========================================================================================
Validates:
  1. Contract validation & parameter constraints
  2. Fuel price resolution hierarchy (User override -> Catalog -> Explicit ValueError)
  3. Modular CAPEX arithmetic and physical sizing overrides
  4. Fuel savings escalation and carbon price monetization rules
  5. Cash flow schedule generation, timing conventions, OPEX, replacement, and salvage
  6. Discounting math and Net Present Value (NPV)
  7. Simple & Discounted Payback Period linear interpolation and horizon thresholds
  8. Deterministic Internal Rate of Return (IRR) bracketed Brent root search & diagnostic states:
     - Unique root detection
     - No-root detection
     - Multiple-root detection (returns None, machine-readable status, warnings)
     - All-negative cash flows
     - All-positive cash flows
     - All-zero cash flows
     - Zero-CAPEX with mixed signs
  9. Levelized Cost of Clean Energy (LCOE) with discounted utilized energy and zero-energy safety
 10. Upstream adapters: Phase 3G AnnualScheduleSummary and Phase 6 Phase6SimulationResult
 11. Zero-CAPEX edge-case calculations
"""

import pytest
from pydantic import ValidationError

from phase7_contracts import (
    FinancialParameters,
    LifecycleCashFlow,
    InvestmentAppraisalResult,
)
from phase7_economics import (
    resolve_fuel_price,
    resolve_ship_sizing,
    calculate_initial_capex,
    generate_lifecycle_cash_flows,
    calculate_payback_period,
    calculate_irr,
    calculate_lcoe,
    evaluate_clean_energy_investment,
    evaluate_annual_schedule_investment,
    evaluate_voyage_simulation_investment,
)


# ==============================================================================
# 1. Contract Validation Tests
# ==============================================================================
def test_financial_parameters_defaults():
    p = FinancialParameters()
    assert p.analysis_horizon_years == 15
    assert p.discount_rate == 0.08
    assert p.fuel_price_usd_per_l is None
    assert p.fuel_escalation_rate == 0.02
    assert p.solar_capex_usd_per_m2 == 250.0
    assert p.battery_capex_usd_per_kwh == 450.0
    assert p.inverter_bop_capex_usd == 15000.0
    assert p.installation_retrofit_capex_usd == 20000.0
    assert p.opex_pct_of_capex == 0.015
    assert p.battery_replacement_cost_usd_per_kwh == 300.0
    assert p.battery_replacement_interval_years == 8
    assert p.salvage_value_pct == 0.05
    assert p.carbon_price_usd_per_tonne == 0.0


def test_financial_parameters_invalid_horizon():
    with pytest.raises(ValidationError):
        FinancialParameters(analysis_horizon_years=0)
    with pytest.raises(ValidationError):
        FinancialParameters(analysis_horizon_years=35)


def test_financial_parameters_invalid_discount_rate():
    with pytest.raises(ValidationError):
        FinancialParameters(discount_rate=-0.01)
    with pytest.raises(ValidationError):
        FinancialParameters(discount_rate=0.30)


def test_financial_parameters_invalid_costs():
    with pytest.raises(ValidationError):
        FinancialParameters(solar_capex_usd_per_m2=-1.0)
    with pytest.raises(ValidationError):
        FinancialParameters(battery_capex_usd_per_kwh=-50.0)
    with pytest.raises(ValidationError):
        FinancialParameters(fuel_price_usd_per_l=-0.5)


def test_financial_parameters_invalid_percentages():
    with pytest.raises(ValidationError):
        FinancialParameters(opex_pct_of_capex=-0.01)
    with pytest.raises(ValidationError):
        FinancialParameters(opex_pct_of_capex=0.15)
    with pytest.raises(ValidationError):
        FinancialParameters(salvage_value_pct=0.50)


# ==============================================================================
# 2. Fuel Price Resolution Tests
# ==============================================================================
def test_fuel_price_priority_user_override():
    # User override takes precedence over catalog
    p = FinancialParameters(fuel_price_usd_per_l=1.45)
    price = resolve_fuel_price(p, ship_type="Tanker Ship")
    assert price == 1.45


def test_fuel_price_priority_catalog():
    # Catalog resolution when override is None
    p = FinancialParameters(fuel_price_usd_per_l=None)
    assert resolve_fuel_price(p, ship_type="Tanker Ship") == 0.95
    assert resolve_fuel_price(p, ship_type="Oil Service Boat") == 1.15
    assert resolve_fuel_price(p, ship_type="Fishing Trawler") == 1.10
    assert resolve_fuel_price(p, ship_type="Surfer Boat") == 1.20


def test_fuel_price_missing_raises_error():
    # Explicit ValueError when price cannot be resolved (no silent fallback!)
    p = FinancialParameters(fuel_price_usd_per_l=None)
    with pytest.raises(ValueError, match="Missing required fuel price"):
        resolve_fuel_price(p, ship_type=None)

    with pytest.raises(ValueError, match="Missing required fuel price"):
        resolve_fuel_price(p, ship_type="Nonexistent Ship")


# ==============================================================================
# 3. CAPEX & Sizing Resolution Tests
# ==============================================================================
def test_capex_exact_arithmetic():
    p = FinancialParameters(
        solar_capex_usd_per_m2=200.0,
        battery_capex_usd_per_kwh=400.0,
        inverter_bop_capex_usd=10000.0,
        installation_retrofit_capex_usd=15000.0,
    )
    # solar: 100 m2 * 200 = 20,000
    # battery: 50 kWh * 400 = 20,000
    # BOP: 10,000
    # Install: 15,000
    # Total = 65,000
    capex = calculate_initial_capex(100.0, 50.0, p)
    assert capex == 65000.0


def test_capex_zero_components():
    p = FinancialParameters(
        solar_capex_usd_per_m2=0.0,
        battery_capex_usd_per_kwh=0.0,
        inverter_bop_capex_usd=0.0,
        installation_retrofit_capex_usd=0.0,
    )
    capex = calculate_initial_capex(100.0, 50.0, p)
    assert capex == 0.0


def test_resolve_ship_sizing_catalog_and_override():
    s_m2, b_kwh = resolve_ship_sizing(ship_type="Tanker Ship")
    assert s_m2 == 250.0
    assert b_kwh == pytest.approx(1199.9232)

    # Overrides take precedence
    s_m2_ov, b_kwh_ov = resolve_ship_sizing(
        ship_type="Tanker Ship",
        solar_area_m2_override=300.0,
        battery_capacity_kwh_override=1500.0,
    )
    assert s_m2_ov == 300.0
    assert b_kwh_ov == 1500.0


# ==============================================================================
# 4. Cash Flow & Annual Savings Tests
# ==============================================================================
def test_cash_flow_timing_and_fuel_escalation():
    # 5-year horizon, 10% escalation, zero OPEX, zero replacement
    p = FinancialParameters(
        analysis_horizon_years=5,
        discount_rate=0.0,
        fuel_escalation_rate=0.10,
        opex_pct_of_capex=0.0,
        battery_replacement_interval_years=None,
        salvage_value_pct=0.0,
        carbon_price_usd_per_tonne=0.0,
    )
    cfs = generate_lifecycle_cash_flows(
        capex_0=1000.0,
        annual_fuel_displaced_L=100.0,
        resolved_fuel_price_usd_per_l=1.0,
        annual_clean_energy_utilized_kwh=500.0,
        annual_co2_displaced_kg=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )

    assert len(cfs) == 6  # t=0, 1, 2, 3, 4, 5
    assert cfs[0].year == 0
    assert cfs[0].capex_usd == -1000.0
    assert cfs[0].net_cash_flow_usd == -1000.0

    # Fuel savings escalate: P_t = P_0 * (1 + 0.10)^(t-1)
    # Year 1: 100 * 1.0 * (1.10)^0 = 100.0
    # Year 2: 100 * 1.0 * (1.10)^1 = 110.0
    # Year 3: 100 * 1.0 * (1.10)^2 = 121.0
    # Year 4: 100 * 1.0 * (1.10)^3 = 133.1
    # Year 5: 100 * 1.0 * (1.10)^4 = 146.41
    assert cfs[1].fuel_savings_usd == pytest.approx(100.0)
    assert cfs[2].fuel_savings_usd == pytest.approx(110.0)
    assert cfs[3].fuel_savings_usd == pytest.approx(121.0)
    assert cfs[4].fuel_savings_usd == pytest.approx(133.1)
    assert cfs[5].fuel_savings_usd == pytest.approx(146.41)


def test_carbon_savings_monetization():
    p_zero = FinancialParameters(carbon_price_usd_per_tonne=0.0)
    cfs_zero = generate_lifecycle_cash_flows(
        capex_0=1000.0,
        annual_fuel_displaced_L=100.0,
        resolved_fuel_price_usd_per_l=1.0,
        annual_clean_energy_utilized_kwh=500.0,
        annual_co2_displaced_kg=5000.0,
        battery_capacity_kwh=0.0,
        parameters=p_zero,
    )
    assert cfs_zero[1].carbon_savings_usd == 0.0

    p_carbon = FinancialParameters(carbon_price_usd_per_tonne=50.0)
    cfs_carbon = generate_lifecycle_cash_flows(
        capex_0=1000.0,
        annual_fuel_displaced_L=100.0,
        resolved_fuel_price_usd_per_l=1.0,
        annual_clean_energy_utilized_kwh=500.0,
        annual_co2_displaced_kg=5000.0,  # 5 tonnes
        battery_capacity_kwh=0.0,
        parameters=p_carbon,
    )
    # 5 tonnes * 50 $/tonne = 250 $
    assert cfs_carbon[1].carbon_savings_usd == pytest.approx(250.0)


def test_battery_replacement_and_terminal_salvage():
    # 10-year horizon, replacement every 4 years (t=4, t=8, NOT t=10)
    p = FinancialParameters(
        analysis_horizon_years=10,
        battery_replacement_interval_years=4,
        battery_replacement_cost_usd_per_kwh=200.0,
        salvage_value_pct=0.10,
        opex_pct_of_capex=0.0,
    )
    cfs = generate_lifecycle_cash_flows(
        capex_0=10000.0,
        annual_fuel_displaced_L=0.0,
        resolved_fuel_price_usd_per_l=1.0,
        annual_clean_energy_utilized_kwh=0.0,
        annual_co2_displaced_kg=0.0,
        battery_capacity_kwh=50.0,
        parameters=p,
    )
    # Battery replacement = 50 kWh * 200 $/kWh = 10,000 $
    assert cfs[4].replacement_expenditure_usd == 10000.0
    assert cfs[8].replacement_expenditure_usd == 10000.0
    assert cfs[1].replacement_expenditure_usd == 0.0
    assert cfs[10].replacement_expenditure_usd == 0.0  # Terminal year excluded

    # Salvage value = 10,000 * 0.10 = 1,000 $ at t=10 only
    assert cfs[10].salvage_value_usd == 1000.0
    assert cfs[9].salvage_value_usd == 0.0


# ==============================================================================
# 5. NPV & Discounting Tests
# ==============================================================================
def test_npv_deterministic_reconciliation():
    # Initial: -1000, 3 years of 500 at r = 10%
    # PV = -1000 + 500/(1.1) + 500/(1.1^2) + 500/(1.1^3)
    # 500/1.1 = 454.5455
    # 500/1.21 = 413.2231
    # 500/1.331 = 375.6574
    # Sum PV = 1243.426 - 1000 = 243.426
    p = FinancialParameters(
        analysis_horizon_years=3,
        discount_rate=0.10,
        fuel_price_usd_per_l=1.0,
        fuel_escalation_rate=0.0,
        opex_pct_of_capex=0.0,
        salvage_value_pct=0.0,
        battery_replacement_interval_years=None,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=500.0,
        annual_clean_energy_utilized_kwh=1000.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    # Note: BOP=15000 + Install=20000 -> Initial CAPEX would be 35000 if defaults are kept!
    # Let's override fixed capex components to get exact 1000 initial capex:
    p_custom = FinancialParameters(
        analysis_horizon_years=3,
        discount_rate=0.10,
        fuel_price_usd_per_l=1.0,
        fuel_escalation_rate=0.0,
        solar_capex_usd_per_m2=0.0,
        battery_capex_usd_per_kwh=0.0,
        inverter_bop_capex_usd=500.0,
        installation_retrofit_capex_usd=500.0,  # Total = 1000
        opex_pct_of_capex=0.0,
        salvage_value_pct=0.0,
        battery_replacement_interval_years=None,
    )
    res_custom = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=500.0,
        annual_clean_energy_utilized_kwh=1000.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p_custom,
    )
    assert res_custom.total_initial_capex_usd == 1000.0
    assert res_custom.net_present_value_usd == pytest.approx(243.43, abs=0.05)


# ==============================================================================
# 6. Payback Period Tests
# ==============================================================================
def test_payback_immediate_recovery():
    # Initial capex = 0 -> payback = 0.0
    p = FinancialParameters(
        inverter_bop_capex_usd=0.0,
        installation_retrofit_capex_usd=0.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=100.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
        ship_type="Tanker Ship",
    )
    assert res.total_initial_capex_usd == 0.0
    assert res.simple_payback_years == 0.0
    assert res.payback_status == "PAYBACK_ACHIEVED"
    assert res.discounted_payback_years == 0.0
    assert res.discounted_payback_status == "DISCOUNTED_PAYBACK_ACHIEVED"


def test_payback_linear_interpolation():
    # Initial: -100, Annual savings: 40/year (no escalation, zero OPEX)
    # Year 1: Cum = -60
    # Year 2: Cum = -20
    # Year 3: Cum = +20 -> Recovered between Year 2 and 3!
    # Interpolation: 2 + (20 / 40) = 2.5 years
    p = FinancialParameters(
        analysis_horizon_years=5,
        discount_rate=0.05,
        fuel_escalation_rate=0.0,
        inverter_bop_capex_usd=100.0,
        installation_retrofit_capex_usd=0.0,
        opex_pct_of_capex=0.0,
        salvage_value_pct=0.0,
        battery_replacement_interval_years=None,
        fuel_price_usd_per_l=1.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=40.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.simple_payback_years == pytest.approx(2.5)
    assert res.payback_status == "PAYBACK_ACHIEVED"


def test_payback_not_achieved_within_horizon():
    # Initial: -10,000, Annual savings: 100/year, 10-year horizon -> Never recovered
    p = FinancialParameters(
        analysis_horizon_years=10,
        fuel_escalation_rate=0.0,
        inverter_bop_capex_usd=10000.0,
        installation_retrofit_capex_usd=0.0,
        opex_pct_of_capex=0.0,
        salvage_value_pct=0.0,
        battery_replacement_interval_years=None,
        fuel_price_usd_per_l=1.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=100.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.simple_payback_years is None
    assert res.payback_status == "PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON"
    assert res.discounted_payback_years is None
    assert res.discounted_payback_status == "DISCOUNTED_PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON"


# ==============================================================================
# 7. Internal Rate of Return (IRR) Tests
# ==============================================================================
def test_irr_unique_root():
    # Initial: -100, 5 years of +25
    # Standard closed-form finance textbook: IRR = 7.9308%
    p = FinancialParameters(
        analysis_horizon_years=5,
        discount_rate=0.08,
        fuel_escalation_rate=0.0,
        inverter_bop_capex_usd=100.0,
        installation_retrofit_capex_usd=0.0,
        opex_pct_of_capex=0.0,
        salvage_value_pct=0.0,
        battery_replacement_interval_years=None,
        fuel_price_usd_per_l=1.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=25.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.irr_status == "IRR_UNIQUE_ROOT"
    assert res.internal_rate_of_return_pct == pytest.approx(7.9308, abs=0.01)


def test_irr_all_negative():
    # All cash flows negative (CAPEX=1000, 0 savings, OPEX=15/yr)
    p = FinancialParameters(
        analysis_horizon_years=5,
        inverter_bop_capex_usd=1000.0,
        installation_retrofit_capex_usd=0.0,
        opex_pct_of_capex=0.05,
        salvage_value_pct=0.0,
        fuel_price_usd_per_l=1.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=0.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.internal_rate_of_return_pct is None
    assert res.irr_status == "IRR_NOT_APPLICABLE_ALL_NEGATIVE"


def test_irr_all_positive():
    # Zero initial CAPEX and positive annual cash flows
    p = FinancialParameters(
        inverter_bop_capex_usd=0.0,
        installation_retrofit_capex_usd=0.0,
        fuel_price_usd_per_l=1.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=100.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.internal_rate_of_return_pct is None
    assert res.irr_status == "IRR_NOT_APPLICABLE_ALL_POSITIVE"


def test_irr_all_zero():
    # Zero CAPEX, zero savings, zero OPEX
    p = FinancialParameters(
        inverter_bop_capex_usd=0.0,
        installation_retrofit_capex_usd=0.0,
        opex_pct_of_capex=0.0,
        salvage_value_pct=0.0,
        fuel_price_usd_per_l=1.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=0.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.net_present_value_usd == 0.0
    assert res.internal_rate_of_return_pct is None
    assert res.irr_status == "IRR_DEGENERATE_ZERO_CASH_FLOW"


def test_irr_zero_capex_with_mixed_signs():
    # CAPEX0 = 0, but operating costs or replacements exceed savings in some years
    # Cash flows: t=0: 0, t=1: -100, t=2: +200
    from phase7_contracts import LifecycleCashFlow
    cfs = [
        LifecycleCashFlow(
            year=0, capex_usd=0.0, opex_usd=0.0, fuel_savings_usd=0.0, carbon_savings_usd=0.0,
            replacement_expenditure_usd=0.0, salvage_value_usd=0.0, net_cash_flow_usd=0.0,
            discount_factor=1.0, discounted_cash_flow_usd=0.0, cumulative_cash_flow_usd=0.0,
            cumulative_discounted_cash_flow_usd=0.0, clean_energy_utilized_kwh=0.0, discounted_clean_energy_kwh=0.0,
        ),
        LifecycleCashFlow(
            year=1, capex_usd=0.0, opex_usd=200.0, fuel_savings_usd=100.0, carbon_savings_usd=0.0,
            replacement_expenditure_usd=0.0, salvage_value_usd=0.0, net_cash_flow_usd=-100.0,
            discount_factor=0.9, discounted_cash_flow_usd=-90.0, cumulative_cash_flow_usd=-100.0,
            cumulative_discounted_cash_flow_usd=-90.0, clean_energy_utilized_kwh=100.0, discounted_clean_energy_kwh=90.0,
        ),
        LifecycleCashFlow(
            year=2, capex_usd=0.0, opex_usd=0.0, fuel_savings_usd=200.0, carbon_savings_usd=0.0,
            replacement_expenditure_usd=0.0, salvage_value_usd=0.0, net_cash_flow_usd=200.0,
            discount_factor=0.81, discounted_cash_flow_usd=162.0, cumulative_cash_flow_usd=100.0,
            cumulative_discounted_cash_flow_usd=72.0, clean_energy_utilized_kwh=100.0, discounted_clean_energy_kwh=81.0,
        ),
    ]
    irr_val, status, warns = calculate_irr(cfs, capex_0=0.0)
    assert irr_val is None
    assert status == "IRR_NOT_APPLICABLE_ZERO_CAPEX"


def test_irr_multiple_roots_detection():
    # Classic project finance example with multiple sign changes:
    # t=0: -100, t=1: +230, t=2: -132
    # Roots: (1+r) = 1.10 (r = 10%) and (1+r) = 1.20 (r = 20%)
    from phase7_contracts import LifecycleCashFlow
    cfs = [
        LifecycleCashFlow(
            year=0, capex_usd=-100.0, opex_usd=0.0, fuel_savings_usd=0.0, carbon_savings_usd=0.0,
            replacement_expenditure_usd=0.0, salvage_value_usd=0.0, net_cash_flow_usd=-100.0,
            discount_factor=1.0, discounted_cash_flow_usd=-100.0, cumulative_cash_flow_usd=-100.0,
            cumulative_discounted_cash_flow_usd=-100.0, clean_energy_utilized_kwh=0.0, discounted_clean_energy_kwh=0.0,
        ),
        LifecycleCashFlow(
            year=1, capex_usd=0.0, opex_usd=0.0, fuel_savings_usd=230.0, carbon_savings_usd=0.0,
            replacement_expenditure_usd=0.0, salvage_value_usd=0.0, net_cash_flow_usd=230.0,
            discount_factor=0.9, discounted_cash_flow_usd=207.0, cumulative_cash_flow_usd=130.0,
            cumulative_discounted_cash_flow_usd=107.0, clean_energy_utilized_kwh=100.0, discounted_clean_energy_kwh=90.0,
        ),
        LifecycleCashFlow(
            year=2, capex_usd=0.0, opex_usd=0.0, fuel_savings_usd=0.0, carbon_savings_usd=0.0,
            replacement_expenditure_usd=132.0, salvage_value_usd=0.0, net_cash_flow_usd=-132.0,
            discount_factor=0.81, discounted_cash_flow_usd=-106.92, cumulative_cash_flow_usd=-2.0,
            cumulative_discounted_cash_flow_usd=0.08, clean_energy_utilized_kwh=100.0, discounted_clean_energy_kwh=81.0,
        ),
    ]
    irr_val, status, warns = calculate_irr(cfs, capex_0=100.0)
    assert irr_val is None
    assert status == "IRR_MULTIPLE_ROOTS"
    assert len(warns) == 1
    assert "Multiple IRR roots detected" in warns[0]


# ==============================================================================
# 8. LCOE Tests
# ==============================================================================
def test_lcoe_exact_deterministic():
    # Horizon 2 years, r = 0% for simple math
    # CAPEX0 = 1000
    # Year 1: OPEX = 100, Energy = 1000 kWh
    # Year 2: OPEX = 100, Energy = 1000 kWh, Salvage = 200
    # Total Lifecycle Cost = 1000 + 100 + 100 - 200 = 1000 $
    # Total Energy = 1000 + 1000 = 2000 kWh
    # LCOE = 1000 / 2000 = 0.50 $/kWh
    p = FinancialParameters(
        analysis_horizon_years=2,
        discount_rate=0.0,
        inverter_bop_capex_usd=1000.0,
        installation_retrofit_capex_usd=0.0,
        opex_pct_of_capex=0.10,  # 100 $/yr
        salvage_value_pct=0.20,  # 200 $
        battery_replacement_interval_years=None,
        fuel_price_usd_per_l=1.0,
    )
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=100.0,
        annual_clean_energy_utilized_kwh=1000.0,
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.lcoe_status == "LCOE_CALCULATED"
    assert res.lcoe_usd_per_kwh == pytest.approx(0.50, abs=1e-4)


def test_lcoe_zero_energy_handled_safely():
    p = FinancialParameters(fuel_price_usd_per_l=1.0)
    res = evaluate_clean_energy_investment(
        annual_fuel_displaced_L=100.0,
        annual_clean_energy_utilized_kwh=0.0,  # Zero clean energy
        solar_area_m2=0.0,
        battery_capacity_kwh=0.0,
        parameters=p,
    )
    assert res.lcoe_usd_per_kwh is None
    assert res.lcoe_status == "LCOE_UNDEFINED_ZERO_ENERGY"


# ==============================================================================
# 9. Upstream Integration Adapters Tests
# ==============================================================================
def test_evaluate_annual_schedule_investment_integration():
    # Mock an AnnualScheduleSummary from Phase 3G
    class MockAnnualSummary:
        ship_type = "Tanker Ship"
        total_fuel_displaced_L = 5383.52
        total_co2_displaced_kg = 14249.66
        total_clean_energy_utilized_kwh = 20800.0

    summary = MockAnnualSummary()
    res = evaluate_annual_schedule_investment(summary)
    assert isinstance(res, InvestmentAppraisalResult)
    assert res.resolved_fuel_price_usd_per_l == 0.95
    assert res.solar_area_m2 == 250.0
    assert res.battery_capacity_kwh == pytest.approx(1199.9232)
    assert res.total_initial_capex_usd == pytest.approx(637465.44, abs=0.1)


def test_evaluate_voyage_simulation_investment_integration():
    # Mock a Phase6SimulationResult from Phase 6
    class MockRequest:
        ship_type = "Oil Service Boat"

    class MockTier4:
        estimated_fuel_displaced_L = 80.0
        estimated_co2_displaced_kg = 210.0

    class MockTier3:
        clean_energy_utilized_kwh = 180.0

    class MockPhase3Output:
        tier_4_engineering_scenario_estimates = MockTier4()
        tier_3_clean_energy_feasibility = MockTier3()

    class MockSimResult:
        request = MockRequest()
        phase3_output = MockPhase3Output()

    sim = MockSimResult()
    # 50 annual voyages
    res = evaluate_voyage_simulation_investment(sim, annual_voyages=50)
    assert isinstance(res, InvestmentAppraisalResult)
    assert res.resolved_fuel_price_usd_per_l == 1.15
    assert res.solar_area_m2 == 80.0
    assert res.battery_capacity_kwh == pytest.approx(649.728)
