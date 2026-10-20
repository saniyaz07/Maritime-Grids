"""
phase7_contracts.py — Pydantic V2 Contracts for Lifecycle Techno-Economics & Capital Budgeting
=============================================================================================
Defines:
  - FinancialParameters: Configurable macro-economic, hardware CAPEX, OPEX, and lifecycle assumptions.
  - LifecycleCashFlow: Annual accounting cash flow row (t = 0 ... N).
  - InvestmentAppraisalResult: Complete quantitative capital budgeting appraisal metrics and diagnostics.

All fields adhere strictly to the frozen Phase 7 specification:
  - No evaluative investment recommendation labels ("VIABLE", "MARGINAL", "UNECONOMIC").
  - Objective diagnostic statuses for IRR, Payback, Discounted Payback, and LCOE.
  - Explicit parameter provenance tracking.
"""

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class FinancialParameters(BaseModel):
    """
    Configurable macroeconomic, unit capital cost, operational maintenance,
    and lifecycle timing assumptions for clean-energy maritime retrofits.
    All cost inputs are configurable external economic assumptions.
    """
    analysis_horizon_years: int = Field(
        default=15,
        ge=1,
        le=30,
        description="Economic planning evaluation horizon in years (1 to 30)."
    )
    discount_rate: float = Field(
        default=0.08,
        ge=0.0,
        le=0.25,
        description="Nominal annual discount rate / hurdle rate (0.0 to 0.25, i.e., 0% to 25%)."
    )
    fuel_price_usd_per_l: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Optional user fuel price override in USD/L. If None, resolved from catalog."
    )
    fuel_escalation_rate: float = Field(
        default=0.02,
        ge=-0.05,
        le=0.15,
        description="Annual real fuel price escalation rate (-0.05 to 0.15, i.e., -5% to +15%)."
    )
    solar_capex_usd_per_m2: float = Field(
        default=250.0,
        ge=0.0,
        description="Unit solar PV procurement and structural racking capital expenditure in USD/m2."
    )
    battery_capex_usd_per_kwh: float = Field(
        default=450.0,
        ge=0.0,
        description="Unit marine-grade containerized/rack battery pack capital expenditure in USD/kWh."
    )
    inverter_bop_capex_usd: float = Field(
        default=15000.0,
        ge=0.0,
        description="Fixed electrical balance of plant, inverter, DC-DC converter, and switchgear in USD."
    )
    installation_retrofit_capex_usd: float = Field(
        default=20000.0,
        ge=0.0,
        description="Fixed shipyard integration, labor, cabling, and naval architecture certification in USD."
    )
    opex_pct_of_capex: float = Field(
        default=0.015,
        ge=0.0,
        le=0.10,
        description="Annual routine operations and maintenance expenditure as a fraction of initial CAPEX (0% to 10%)."
    )
    battery_replacement_cost_usd_per_kwh: float = Field(
        default=300.0,
        ge=0.0,
        description="Future unit battery cell/module replacement expenditure in USD/kWh."
    )
    battery_replacement_interval_years: Optional[int] = Field(
        default=8,
        ge=1,
        description="Scheduled battery pack replacement interval in years. Explicit economic assumption."
    )
    salvage_value_pct: float = Field(
        default=0.05,
        ge=0.0,
        le=0.30,
        description="Residual salvage / second-life equipment recovery value as a fraction of initial CAPEX (0% to 30%)."
    )
    carbon_price_usd_per_tonne: float = Field(
        default=0.0,
        ge=0.0,
        description="Voluntary or statutory carbon compliance price in USD/tonne CO2. Default 0.0 (no automatic monetization)."
    )


class LifecycleCashFlow(BaseModel):
    """
    Annual lifecycle accounting record representing Year t in [0, N].
    Timing convention:
      - Year 0: Overnight initial CAPEX. Zero operational flows.
      - Year 1 to N: End-of-year operational benefits, OPEX, periodic replacement, and terminal salvage.
    """
    year: int = Field(..., ge=0, description="Timeline year index (0 to N).")
    capex_usd: float = Field(..., description="Initial capital expenditure in USD (negative cash flow at t=0, 0.0 thereafter).")
    opex_usd: float = Field(..., ge=0.0, description="Routine operations and maintenance expenditure in USD.")
    fuel_savings_usd: float = Field(..., ge=0.0, description="Annual bunker fuel cost savings in USD.")
    carbon_savings_usd: float = Field(..., ge=0.0, description="Annual carbon avoidance cost savings in USD.")
    replacement_expenditure_usd: float = Field(..., ge=0.0, description="Periodic battery pack replacement expenditure in USD.")
    salvage_value_usd: float = Field(..., ge=0.0, description="Terminal residual salvage value in USD (non-zero only at t=N).")
    net_cash_flow_usd: float = Field(..., description="Undiscounted net cash flow in USD.")
    discount_factor: float = Field(..., ge=0.0, description="Present value discount factor (1 + r)^(-t).")
    discounted_cash_flow_usd: float = Field(..., description="Discounted net cash flow in USD.")
    cumulative_cash_flow_usd: float = Field(..., description="Cumulative undiscounted cash flow from Year 0 to Year t.")
    cumulative_discounted_cash_flow_usd: float = Field(..., description="Cumulative discounted cash flow from Year 0 to Year t.")
    clean_energy_utilized_kwh: float = Field(..., ge=0.0, description="Clean electrical energy utilized by auxiliary hotel load in kWh.")
    discounted_clean_energy_kwh: float = Field(..., ge=0.0, description="Discounted clean electrical energy utilized in kWh.")


class InvestmentAppraisalResult(BaseModel):
    """
    Complete lifecycle techno-economic appraisal report containing capital budgeting
    metrics, cash flow schedules, and machine-readable diagnostic statuses.
    """
    parameters: FinancialParameters = Field(..., description="Financial parameters applied during evaluation.")
    resolved_fuel_price_usd_per_l: float = Field(..., gt=0.0, description="Bunker fuel price resolved and applied in USD/L.")
    solar_area_m2: float = Field(..., ge=0.0, description="Installed solar array surface area in m2.")
    battery_capacity_kwh: float = Field(..., ge=0.0, description="Nominal installed battery pack capacity in kWh.")
    total_initial_capex_usd: float = Field(..., ge=0.0, description="Total initial overnight capital investment at t=0.")
    total_replacement_capex_usd: float = Field(..., ge=0.0, description="Undiscounted sum of future battery replacement expenditures.")
    total_lifecycle_opex_usd: float = Field(..., ge=0.0, description="Undiscounted sum of annual routine maintenance expenditures.")
    total_undiscounted_benefits_usd: float = Field(..., ge=0.0, description="Undiscounted sum of annual fuel and carbon savings.")
    net_present_value_usd: float = Field(..., description="Net Present Value (NPV) in USD at the specified discount rate.")
    internal_rate_of_return_pct: Optional[float] = Field(
        default=None,
        description="Internal Rate of Return (IRR) as a percentage (e.g. 12.3456%). None if undefined or non-unique."
    )
    irr_status: str = Field(
        ...,
        description=(
            "Neutral diagnostic status: 'IRR_UNIQUE_ROOT', 'IRR_NO_ROOT', 'IRR_MULTIPLE_ROOTS', "
            "'IRR_NOT_APPLICABLE_ALL_NEGATIVE', 'IRR_NOT_APPLICABLE_ALL_POSITIVE', "
            "'IRR_NOT_APPLICABLE_ZERO_CAPEX', or 'IRR_DEGENERATE_ZERO_CASH_FLOW'."
        )
    )
    simple_payback_years: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Simple undiscounted payback period in years. None if capital is unrecovered within horizon."
    )
    payback_status: str = Field(
        ...,
        description="'PAYBACK_ACHIEVED' or 'PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON'."
    )
    discounted_payback_years: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Discounted payback period in years. None if capital is unrecovered within horizon."
    )
    discounted_payback_status: str = Field(
        ...,
        description="'DISCOUNTED_PAYBACK_ACHIEVED' or 'DISCOUNTED_PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON'."
    )
    lcoe_usd_per_kwh: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Levelized Cost of Clean Energy (LCOE) in USD/kWh. None if zero clean energy utilized."
    )
    lcoe_status: str = Field(
        ...,
        description="'LCOE_CALCULATED' or 'LCOE_UNDEFINED_ZERO_ENERGY'."
    )
    cash_flows: List[LifecycleCashFlow] = Field(
        ...,
        description="Complete annual lifecycle cash flow schedule from Year 0 to Year N."
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Diagnostic notices, multiple-root details, and economic boundary observations."
    )
