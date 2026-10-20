# Phase 7 — Lifecycle Techno-Economic & Capital Budgeting Engine

## 1. Purpose & Scope

Phase 7 implements the **Lifecycle Techno-Economic & Capital Budgeting Engine** for the maritime clean-energy grid simulator. It couples the verified physical operational simulations from Phase 3 (feasibility, displacement, and fleet scheduling) and Phase 6 (automated gateway and multi-pollutant assessments) with multi-year financial cash flow modeling and quantitative capital budgeting appraisal.

### Key Capabilities
* **Strict Bunker Fuel Price Resolution Hierarchy:** Evaluates fuel savings strictly without silent fallback defaults (Priority 1: User override $\rightarrow$ Priority 2: Canonical vessel catalog $\rightarrow$ Priority 3: Explicit `ValueError`).
* **Modular Capital Expenditure (CAPEX) Accounting:** Models solar PV arrays, marine-grade battery storage packs, electrical balance of plant (BOP), and shipyard integration labor.
* **Multi-Year Discounted Cash Flow Schedules:** Generates detailed annual accounting rows (Year 0 through Year $N$, up to 30 years) with end-of-year discounting conventions.
* **Quantitative Capital Budgeting Metrics:**
  * **Net Present Value (NPV):** Evaluates discounted net lifetime value at the specified hurdle rate.
  * **Simple & Discounted Payback Periods:** Employs exact fractional-year linear interpolation between consecutive cumulative cash flows.
  * **Levelized Cost of Clean Energy (LCOE):** Evaluates the levelized lifecycle cost per kilowatt-hour of clean energy utilized by auxiliary loads.
  * **Deterministic Internal Rate of Return (IRR):** Solves for the internal rate of return using a 550-subinterval bracketed Brent root search over $r \in [-50\%, +500\%]$, with strict root multiplicity diagnostics.
* **Neutral Diagnostic Outputs:** Replaces subjective investment labels (`"VIABLE"` / `"UNECONOMIC"`) with objective mathematical diagnostics (`IRR_UNIQUE_ROOT`, `IRR_MULTIPLE_ROOTS`, `PAYBACK_ACHIEVED`, `LCOE_CALCULATED`, etc.).

---

## 2. Input Contracts & Parameter Provenance

### 2.1 Contracts Summary
Implemented in [`phase7_contracts.py`](file:///C:/maritime%20grids/phase7_contracts.py):
* `FinancialParameters`: Macroeconomic parameters, hardware unit costs, maintenance percentages, and lifecycle intervals.
* `LifecycleCashFlow`: Annual accounting record (Year $t \in [0, N]$).
* `InvestmentAppraisalResult`: Complete quantitative appraisal report, cash flow schedules, and diagnostic statuses.

### 2.2 Parameter Provenance Matrix

Every financial parameter is strictly classified according to its evidentiary origin:

| Parameter | Type / Unit | Default Value | Provenance Classification | Rationale & Evidence |
| :--- | :---: | :---: | :--- | :--- |
| `fuel_price_usd_per_l` | `float` ($\$/\text{L}$) | Dynamic | **A. Existing Project Data** | Resolved from [`data/reference/ship_profiles.csv`](file:///C:/maritime%20grids/data/reference/ship_profiles.csv). |
| `fuel_displaced_L` | `float` ($\text{L}$) | Dynamic | **B. Existing Model Output** | Output of Phase 3G / Phase 6 physical simulation. |
| `clean_energy_utilized_kwh`| `float` ($\text{kWh}$) | Dynamic | **C. Mathematical Derivation**| Energy balance: $\min(E_{\text{available}}, E_{\text{aux\_demand}})$ from Phase 3. |
| `analysis_horizon_years` | `int` (years) | `15` | **D. Configurable External Assumption** | Standard commercial planning horizon. |
| `discount_rate` | `float` (fraction) | `0.08` | **D. Configurable External Assumption** | Nominal maritime commercial hurdle rate ($8.0\%$). |
| `fuel_escalation_rate` | `float` (fraction) | `0.02` | **D. Configurable External Assumption** | Real annual bunker price escalation expectation ($2.0\%$). |
| `solar_capex_usd_per_m2` | `float` ($\$/\text{m}^2$) | `250.0` | **D. Configurable External Assumption** | Solar PV procurement and mounting benchmark. |
| `battery_capex_usd_per_kwh`| `float` ($\$/\text{kWh}$)| `450.0` | **D. Configurable External Assumption** | Marine-grade containerized battery pack benchmark. |
| `inverter_bop_capex_usd` | `float` ($\$$) | `15,000.0` | **D. Configurable External Assumption** | Marine inverter, converter, and switchgear package. |
| `installation_retrofit_capex`| `float` ($\$$) | `20,000.0` | **D. Configurable External Assumption** | Shipyard integration and labor parameter. |
| `opex_pct_of_capex` | `float` (fraction) | `0.015` | **D. Configurable External Assumption** | Annual routine electrical maintenance rate ($1.5\%$). |
| `battery_replacement_cost`| `float` ($\$/\text{kWh}$)| `300.0` | **D. Configurable External Assumption** | Cell/module replacement cost assumption. |
| `battery_replacement_interval`| `int` (years) | `8` | **D. Configurable External Assumption** | **Explicit assumption.** Not a prediction of SOH model. |
| `salvage_value_pct` | `float` (fraction) | `0.05` | **D. Configurable External Assumption** | Residual equipment value assumption ($5\%$). |
| `carbon_price_usd_per_tonne`| `float` ($\$/\text{t}$) | `0.0` | **D. Configurable External Assumption** | Zero by default. Must be supplied to monetize $\text{CO}_2$. |

> **Mandatory Disclaimer:** The financial assumptions are configurable and are **not** independently validated market quotations unless repository evidence exists.

> **Battery Replacement Provenance Notice:** The battery replacement interval (`battery_replacement_interval_years = 8`) is an **explicit economic assumption** and is **NOT** derived or extrapolated from the frozen Machine Learning model `battery_soh_final.joblib`. The frozen SOH model provides single-voyage snapshot capacity health only.

---

## 3. Mathematical Formulations

### 3.1 Fuel Savings Valuation
$$\text{Savings}_{\text{fuel}, t} = \Delta V_{\text{fuel}} \times P_{\text{fuel}, 0} \times (1 + e_{\text{fuel}})^{t-1} \quad [\$ \text{ for } t \in [1, N]]$$
* $\Delta V_{\text{fuel}}$: Annual fuel volume displaced in Litres (from `AnnualScheduleSummary.total_fuel_displaced_L` or `Tier4EngineeringScenarioEstimates.estimated_fuel_displaced_L`).
* $P_{\text{fuel}, 0}$: Resolved base-year fuel price in $\$ /\text{L}$.
* $e_{\text{fuel}}$: Annual real fuel price escalation rate.

### 3.2 Carbon Savings Valuation
$$\text{Savings}_{\text{carbon}, t} = \left(\frac{\Delta M_{\text{CO}_2}}{1,000.0}\right) \times P_{\text{carbon}} \quad [\$]$$
* **Monetization Policy:** By default, $P_{\text{carbon}} = 0.0\ \$/\text{tonne}$. Avoided $\text{CO}_2$ has **zero monetary value** unless an explicit positive carbon price is supplied.

### 3.3 Initial Capital Expenditure (CAPEX)
$$\text{CAPEX}_0 = \left(A_{\text{pv}} \times C_{\text{pv}}\right) + \left(E_{\text{batt}} \times C_{\text{batt}}\right) + C_{\text{bop}} + C_{\text{install}} \quad [\$]$$
* $A_{\text{pv}}$: Installed solar array area in $\text{m}^2$ (from catalog `solar_panel_size_m2` or override).
* $E_{\text{batt}}$: Nominal battery capacity in $\text{kWh}$ (from catalog `battery_pack_capacity_kwh` or override).

### 3.4 Operational Expenditure (OPEX)
$$\text{OPEX}_t = \text{CAPEX}_0 \times f_{\text{opex}} \quad [\$ \text{ for } t \in [1, N]]$$

### 3.5 Scheduled Battery Replacement
$$\text{Expenditure}_{\text{replace}, t} = \begin{cases} 
E_{\text{batt}} \times C_{\text{replace}} & \text{if } t \in \{k \cdot t_{\text{replace}} \mid k \in \mathbb{N}^+\} \text{ and } t < N \\
0 & \text{otherwise}
\end{cases} \quad [\$]$$
* Replacements never occur at the terminal year $N$.

### 3.6 Terminal Salvage Value
$$\text{Salvage}_N = \text{CAPEX}_0 \times f_{\text{salvage}} \quad [\$ \text{ strictly at } t = N]$$

### 3.7 Net Cash Flow & Present Value
$$\text{NCF}_0 = -\text{CAPEX}_0$$
$$\text{NCF}_t = \text{Savings}_{\text{fuel}, t} + \text{Savings}_{\text{carbon}, t} - \text{OPEX}_t - \text{Expenditure}_{\text{replace}, t} + \delta_{t, N} \cdot \text{Salvage}_N \quad [t \ge 1]$$
$$\text{NPV} = \sum_{t=0}^N \frac{\text{NCF}_t}{(1 + r)^t} = -\text{CAPEX}_0 + \sum_{t=1}^N \frac{\text{NCF}_t}{(1 + r)^t} \quad [\$]$$

### 3.8 Simple & Discounted Payback Periods
Let $C_t = \sum_{i=0}^t \text{NCF}_i$ and $D_t = \sum_{i=0}^t \frac{\text{NCF}_i}{(1 + r)^i}$.
* If $C_0 \ge 0$, $\text{Payback} = 0.0$ (`"PAYBACK_ACHIEVED"`).
* If $C_t \ge 0$ for the first time at year $k \in [1, N]$:
  $$\text{Payback} = (k - 1) + \frac{-C_{k-1}}{C_k - C_{k-1}} \quad [\text{years}]$$
* If $C_N < 0$, $\text{Payback} = \text{None}$ (`"PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON"`).
* The discounted payback applies the exact same interpolation to $D_t$.

### 3.9 Internal Rate of Return (IRR)
Solved via Brent's method over 550 subintervals across $r \in [-0.50, 5.00]$:
$$\text{NPV}(\text{IRR}) = \sum_{t=0}^N \frac{\text{NCF}_t}{(1 + \text{IRR})^t} = 0$$
* All-zero flows: `None` (`"IRR_DEGENERATE_ZERO_CASH_FLOW"`).
* All-negative flows: `None` (`"IRR_NOT_APPLICABLE_ALL_NEGATIVE"`).
* All-positive flows: `None` (`"IRR_NOT_APPLICABLE_ALL_POSITIVE"`).
* Zero-CAPEX with mixed signs: `None` (`"IRR_NOT_APPLICABLE_ZERO_CAPEX"`).
* Exactly 1 root found: `round(root * 100.0, 4)` (`"IRR_UNIQUE_ROOT"`).
* Multiple roots found ($> 1$): `None` (`"IRR_MULTIPLE_ROOTS"`, roots reported in warnings).
* No root in search interval: `None` (`"IRR_NO_ROOT"`).

### 3.10 Levelized Cost of Clean Energy (LCOE)
$$\text{PV}_{\text{cost}} = \text{CAPEX}_0 + \sum_{t=1}^N \frac{\text{OPEX}_t}{(1 + r)^t} + \sum_{t=1}^{N-1} \frac{\text{Replacement}_t}{(1 + r)^t} - \frac{\text{Salvage}_N}{(1 + r)^N} \quad [\$]$$
$$\text{PV}_{\text{energy}} = \sum_{t=1}^N \frac{E_{\text{utilized}, t}}{(1 + r)^t} \quad [\text{kWh}]$$
$$\text{LCOE} = \frac{\text{PV}_{\text{cost}}}{\text{PV}_{\text{energy}}} \quad [\$ /\text{kWh}]$$
* **Clean Energy Denominator Rule:** Strictly uses $E_{\text{utilized}}$ (`total_clean_energy_utilized_kwh`). If $\text{PV}_{\text{energy}} = 0$, $\text{LCOE} = \text{None}$ (`"LCOE_UNDEFINED_ZERO_ENERGY"`).

---

## 4. Upstream Integration Architecture

Phase 7 functions strictly as an additive post-processing layer without modifying upstream physical or machine learning models:

```
[Phase 2 Models (Frozen)]
           ↓
[Phase 3 Orchestration Pipeline (Frozen)]
           ↓
[Phase 3G AnnualScheduleSummary] ───────────────┐
                                                ↓
[Phase 6 Phase6SimulationResult] ───────> evaluate_*_investment()
                                                ↓
                                    InvestmentAppraisalResult
```

### Supported Integration Functions
1. `evaluate_clean_energy_investment(...)`: Direct raw physical inputs evaluation.
2. `evaluate_annual_schedule_investment(annual_summary, parameters, ...)`: Direct consumer of Phase 3G `AnnualScheduleSummary`.
3. `evaluate_voyage_simulation_investment(simulation_result, annual_voyages, parameters, ...)`: Direct consumer of Phase 6 `Phase6SimulationResult`, scaling single-voyage metrics by annual voyages count.

---

## 5. Phase 8 Scope Boundary

* **Phase 7 Implementation Scope:** Restricted purely to techno-economic cash flow generation, discounting, payback interpolation, root-finding, LCOE evaluation, and integration adapters.
* **Phase 8 Scope:** Dedicated parametric constrained system sizing optimization (optimizing $A_{\text{pv}}$ and $E_{\text{batt}}$ subject to deck space and weight limits). No optimization algorithms are included in Phase 7.
