# Phase 3C — Tier 3 Clean Energy Feasibility Documentation

**Project Root:** `C:\maritime grids`  
**Module:** `phase3_feasibility.py`  
**Test Suite:** `tests/test_phase3c_feasibility.py`  
**Status:** IMPLEMENTED AND VERIFIED  

---

## 1. Purpose & Architectural Role

Phase 3C implements the physical clean-energy feasibility budgeting layer for the Maritime Grid Simulation Decision Coordinator. It evaluates whether available clean-energy resources (usable battery energy above reserve buffer plus climatological solar PV generation) are sufficient to satisfy the requested voyage auxiliary electrical energy demand ($E_{\text{aux\_demand}}$).

---

## 2. Implementation Scope

* **Included:**
  * Degradation-adjusted effective battery capacity calculation ($C_{\text{nominal}} \times \text{SOH}$).
  * Usable battery energy calculation above operational reserve buffer ($\max(0, \text{SOC}_{\text{init}} - \text{SOC}_{\text{res}})$).
  * Deterministic NASA POWER monthly solar climatology lookup (`ALLSKY_SFC_SW_DWN`).
  * Deterministic climatological solar PV energy estimation.
  * Clean-energy budget aggregation, auxiliary energy balance, deficit evaluation, and feasibility classification (`FEASIBLE` vs. `PARTIAL`).
  * Conformance to the Pydantic contract `Tier3CleanEnergyFeasibility`.
* **Explicitly Excluded (Out of Scope):**
  * Tier 4 auxiliary generator fuel and $\text{CO}_2$ displacement calculations.
  * Specific Fuel Oil Consumption (SFOC) and fuel density operations.
  * Hourly dynamic dispatch optimization and minute-by-minute simulation.
  * Battery charging/discharging control or propulsion load integration.
  * Machine-learning model training or execution.

---

## 3. Data Sources & Epistemic Classification

| Parameter / Field | Source | Epistemic Classification |
|---|---|---|
| `nominal_pack_capacity_kwh` | `data/reference/ship_profiles.csv` | Observed / Sourced Hardware Fact |
| `solar_panel_size_m2` | `data/reference/ship_profiles.csv` | Observed / Sourced Hardware Fact |
| `solar_panel_efficiency_pct` | `data/reference/ship_profiles.csv` | Observed / Sourced Hardware Fact |
| `predicted_soh` | `models/battery_soh_final.joblib` | Modeled (Phase 2 ML Regression) |
| `daily_ghi_kwh_per_m2` | `data/processed/nasa_power/nasa_monthly_climatology.csv` (`ALLSKY_SFC_SW_DWN`) | Observed Climatological Average |
| `initial_soc` | `AppliedScenarioParameters` (default $0.90$) | Operational Scenario Input |
| `soc_reserve` | `AppliedScenarioParameters` (default $0.20$) | Configurable Engineering Assumption |
| `solar_derate_factor` | `AppliedScenarioParameters` (default $0.85$) | Configurable Engineering Assumption |
| `voyage_duration_hours` | `VoyageMetadata` | Operational Scenario Input |
| `auxiliary_energy_demand_kwh` | `AppliedScenarioParameters` | Explicit Scenario Input |

---

## 4. Governing Formulas & Calculations

### 4.1 Effective Battery Capacity
$$\text{effective\_pack\_capacity\_kwh} = \text{nominal\_pack\_capacity\_kwh} \times \text{predicted\_soh}$$
* `nominal_pack_capacity_kwh`: Sourced pack nameplate capacity ($C_{\text{nominal}}$) in $\text{kWh}$.
* `predicted_soh`: State of Health fraction $\in [0.0, 1.0]$ from frozen Phase 2 regressor.

### 4.2 Usable Battery Energy
$$\text{usable\_battery\_energy\_kwh} = \text{effective\_pack\_capacity\_kwh} \times \max(0.0, \text{initial\_soc} - \text{soc\_reserve})$$
* Enforces that usable energy can never become negative if $\text{initial\_soc} \le \text{soc\_reserve}$.

### 4.3 Solar Climatological Energy Estimate
$$\text{estimated\_solar\_energy\_kwh} = \text{solar\_panel\_size\_m2} \times \left(\frac{\text{solar\_panel\_efficiency\_pct}}{100.0}\right) \times \text{daily\_ghi\_kwh\_per\_m2} \times \text{solar\_derate\_factor} \times \left(\frac{\text{voyage\_duration\_hours}}{24.0}\right)$$
* `daily_ghi_kwh_per_m2`: Monthly average daily global horizontal irradiance in $\text{kWh/m}^2/\text{day}$ from NASA POWER climatology for the corridor and month.
* `solar_derate_factor`: System derate factor accounting for inverter losses, cabling, dust, and operating temperature (default $0.85$).
* Scaled by $(\text{duration} / 24.0)$ to represent cumulative daily insolation over the voyage window.

### 4.4 Clean Energy Aggregation & Feasibility Status
$$\text{total\_clean\_energy\_available\_kwh} = \text{usable\_battery\_energy\_kwh} + \text{estimated\_solar\_energy\_kwh}$$
$$\text{clean\_energy\_utilized\_kwh} = \min(\text{total\_clean\_energy\_available\_kwh}, \text{auxiliary\_energy\_demand\_kwh})$$
$$\text{energy\_balance\_kwh} = \text{total\_clean\_energy\_available\_kwh} - \text{auxiliary\_energy\_demand\_kwh}$$
$$\text{energy\_deficit\_kwh} = \max(0.0, \text{auxiliary\_energy\_demand\_kwh} - \text{total\_clean\_energy\_available\_kwh})$$

$$\text{feasibility\_status} = \begin{cases} \text{"FEASIBLE"} & \text{if } \text{energy\_balance\_kwh} \ge 0.0 \\ \text{"PARTIAL"} & \text{if } \text{energy\_balance\_kwh} < 0.0 \end{cases}$$

---

## 5. Architectural Boundaries & Caveats

### 5.1 Critical Solar Temporal-Resolution Limitation
The solar calculation uses monthly climatological daily GHI scaled linearly by $(\text{voyage\_duration\_hours} / 24.0)$. Consequently:
* **Nighttime Voyages (< 24 hrs):** A voyage taking place entirely at night will still receive an average diurnal credit proportional to its duration.
* **Daytime Voyages (< 24 hrs):** A voyage operating during peak daylight will only receive a fraction of daily GHI rather than peak insolation.
* **Multi-Day Voyages (> 24 hrs):** Day and night cycles average out over full 24-hour periods, but fractional tails retain time-of-day distortion.
* **Conclusion:** This is strictly a **voyage-aggregate engineering scenario estimate**. It is not an hourly dynamic dispatch model.

### 5.2 Weather Model Boundary
The Phase 2 weather model (`models/weather_final.joblib`) is a majority-class baseline with 34.72% accuracy. It is retained strictly as descriptive context metadata. It is **NOT** used as an input to Phase 3C and does **NOT** condition solar derating, battery reserve buffers, or feasibility status.

### 5.3 Phase 2 Frozen Boundary
All Phase 2 models remain 100% frozen. Phase 3C performs zero model retraining, refitting, or execution during feasibility budgeting.

---

## 6. Input Validation Matrix

| Parameter | Validation Boundary | Rejection Behavior |
|---|---|---|
| `predicted_soh` | Finite, $\in [0.0, 1.0]$ | Raises `ValueError` |
| `initial_soc` | Finite, $\in [0.0, 1.0]$ | Raises `ValueError` |
| `soc_reserve` | Finite, $\in [0.0, 1.0]$ | Raises `ValueError` |
| `solar_derate_factor` | Finite, $\in [0.0, 1.0]$ | Raises `ValueError` |
| `voyage_duration_hours` | Finite, strictly $> 0.0$ | Raises `ValueError` |
| `auxiliary_energy_demand_kwh` | Finite, $\ge 0.0$ | Raises `ValueError` |
| `nominal_pack_capacity_kwh` | Finite, strictly $> 0.0$ | Raises `ValueError` |
| `solar_panel_size_m2` | Finite, $\ge 0.0$ | Raises `ValueError` |
| `solar_panel_efficiency_pct` | Finite, $\in [0.0, 100.0]$ | Raises `ValueError` |
| `daily_ghi_kwh_per_m2` | Finite, $\ge 0.0$ | Raises `ValueError` |
| `route_id`, `month` | Unambiguous record in climatology | Raises `ValueError` / `FileNotFoundError` |

---

## 7. Status of Downstream Phases

* **Tier 3 Feasibility:** **100% Complete & Verified**.
* **Tier 4 (Displacement & Assisted Scenarios):** **0% Implemented (Remains strictly unimplemented)**.
