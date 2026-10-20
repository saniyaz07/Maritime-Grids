# Phase 3A — Contracts and Pydantic Schemas Documentation

**Project Root:** `C:\maritime grids`  
**Module:** `phase3_contracts.py`  
**Test Suite:** `tests/test_phase3_contracts.py`  
**Status:** IMPLEMENTED AND VERIFIED (Updated for Phase 3A.1 & Phase 3B.1)  

---

## 1. Overview and Architectural Purpose

`phase3_contracts.py` defines the canonical Pydantic v2 data models for the Phase 3 Decision Coordinator. It enforces strict separation of responsibilities:
- **Contract & Validation Layer ONLY:** Performs zero model inference, zero fuel/weather/battery predictions, and zero business logic orchestration.
- **Strict Four-Tier Hierarchy:** Formally separates authoritative Phase 2 ML outputs, deterministic unassisted baselines, physical clean-energy feasibility checks, and engineering scenario estimates.
- **Cross-Tier Invariant Enforcement:** Guards against impossible displacement conditions (e.g., displaced fuel exceeding total voyage fuel) and ensures single resolved fuel price consistency.
- **Explicit Ownership of State:** 
  - `predicted_soc_end_of_voyage` is an **authoritative Phase 2 ML output**.
  - `initial_soc` is an **operational scenario input** under `AppliedScenarioParameters`, NOT a Tier 1 ML prediction.
- **Single Resolved Fuel Price:** Exactly one resolved fuel price is accepted across the calculation (`tier_2_baseline_metrics.fuel_price_usd_per_l` and `applied_scenario_parameters.fuel_price_usd_per_l` must be identical).

---

## 2. Four-Tier Schema Hierarchy

```text
Phase3Output
├── voyage_metadata (VoyageMetadata)
├── tier_1_phase2_predictions (Tier1Phase2Predictions)
│   ├── weather (WeatherPrediction)
│   ├── fuel_consumption_L (FuelPrediction)
│   ├── co2_emissions_kg (CO2Prediction)
│   ├── battery_health (BatteryHealthPrediction)
│   └── battery_operation (BatteryOperationPrediction)
├── tier_2_baseline_metrics (Tier2BaselineMetrics)
├── tier_3_clean_energy_feasibility (Tier3CleanEnergyFeasibility)
├── tier_4_engineering_scenario_estimates (Tier4EngineeringScenarioEstimates)
├── applied_scenario_parameters (AppliedScenarioParameters)
└── audit_metadata (AuditMetadata)
```

---

## 3. Tier Specifications

### Tier 1 — Phase 2 Predictions (`Tier1Phase2Predictions`)
Represents the authoritative, frozen Phase 2 machine-learning predictions:
- `weather`: `temperature_c`, `wind_speed_knots` ($\ge 0$), `significant_wave_height_m` ($\ge 0$).
- `fuel_consumption_L`: `value` ($\ge 0$), `unit="Liters"`, `evidence_level="B - STRONGLY INFERRED"`, `scope="Total voyage fuel consumption"`.
- `co2_emissions_kg`: `value` ($\ge 0$), `unit="kg"`.
- `battery_health`: `predicted_soh` $\in [0, 1]$, `nominal_pack_capacity_kwh` ($\ge 0$), `effective_pack_capacity_kwh` ($\ge 0$).
- `battery_operation`: `predicted_soc_end_of_voyage` $\in [0, 1]$ (authoritative SOH-aware Phase 2 prediction), `soc_formulation="Degradation-adjusted pack SOC"`. *(Note: `initial_soc` is an operational scenario input and resides under `AppliedScenarioParameters`)*.

### Tier 2 — Deterministic Baseline Metrics (`Tier2BaselineMetrics`)
Calculates the unassisted baseline voyage performance:
- `baseline_fuel_cost_usd` ($\ge 0$)
- `baseline_operational_cii_gco2_per_dwt_nm` ($\ge 0$) per IMO Resolution MEPC.352(78)
- `fuel_price_usd_per_l` ($\ge 0$) — resolved price used for baseline calculations, strictly aligned with `applied_scenario_parameters.fuel_price_usd_per_l`.

### Tier 3 — Clean Energy Feasibility (`Tier3CleanEnergyFeasibility`)
Assesses whether clean energy (battery + climatological solar) can meet auxiliary electrical demand:
- `auxiliary_energy_demand_kwh` ($\ge 0$)
- `usable_battery_energy_kwh` ($\ge 0$)
- `estimated_solar_energy_kwh` ($\ge 0$)
- `total_clean_energy_available_kwh` ($\ge 0$)
- `clean_energy_utilized_kwh` ($\ge 0$)
- `energy_balance_kwh`
- `energy_deficit_kwh` ($\ge 0$)
- `feasibility_status`: Literal `"FEASIBLE"` or `"PARTIAL"`.

### Tier 4 — Engineering Scenario Estimates (`Tier4EngineeringScenarioEstimates`)
Reports auxiliary fuel and emissions displacement:
- `status`: Literal `"ENGINEERING SCENARIO ESTIMATE"` (mandatory).
- `disclaimer`: Disclosure stating displacement is an engineering scenario estimate based on assumed generator SFOC/density, NOT a validated ML decomposition.
- `estimated_fuel_displaced_L` ($\ge 0$)
- `estimated_co2_displaced_kg` ($\ge 0$)
- `net_assisted_fuel_L` ($\ge 0$)
- `net_assisted_co2_kg` ($\ge 0$)
- `net_assisted_fuel_cost_usd` ($\ge 0$)
- `net_assisted_operational_cii_gco2_per_dwt_nm` ($\ge 0$)
- `delta_fuel_pct`, `delta_cii_pct`

---

## 4. Scenario Parameters & Defaults (`AppliedScenarioParameters`)

All configurable assumptions are isolated and exposed with sourced or standard defaults:
- `fuel_price_usd_per_l`: Sourced from `ship_profiles.csv` (OSV: \$1.15, Trawler: \$1.10, Surfer: \$1.20, Tanker: \$0.95), overrideable per scenario.
- `initial_soc`: Operational starting State of Charge fraction $\in [0, 1]$ (default $0.90$).
- `auxiliary_energy_demand_kwh`: Scenario-specified electrical load.
- `soc_reserve`: Default $0.20$ ($20\%$).
- `generator_sfoc_kg_per_kwh`: Default $0.220\text{ kg/kWh}$ (IMO medium-speed ADG default).
- `fuel_density_kg_per_l`: Default $0.850\text{ kg/L}$ (ISO 8217 distillate).
- `emission_factor_kgco2_per_kgfuel`: Default $3.114\text{ kg CO}_2\text{/kg fuel}$ (IMO standard MGO factor).
- `solar_derate_factor`: Default $0.85$.

---

## 5. Validation Invariants

1. **Range Validation:** All fractions ($\text{SOH}$, $\text{SOC}$, $\text{initial\_soc}$, $\text{SOC}_{\text{reserve}}$, solar derate) are bounded within $[0, 1]$.
2. **Positive Constants:** $\text{SFOC} > 0$, $\rho_{\text{fuel}} > 0$, emission factor $> 0$, distance $> 0$, duration $> 0$, DWT $> 0$.
3. **Cross-Tier Upper Bounds:**
   - $\text{estimated\_fuel\_displaced\_L} \le \text{predicted\_fuel\_consumption\_L}$
   - $\text{estimated\_co2\_displaced\_kg} \le \text{predicted\_CO2\_kg}$
4. **Single Resolved Fuel Price:**
   - $|\text{tier\_2\_baseline\_metrics.fuel\_price\_usd\_per\_l} - \text{applied\_scenario\_parameters.fuel\_price\_usd\_per\_l}| \le 10^{-6}$.

---

## 6. Architectural Caveats & Model Boundaries

### 6.1 Critical Architectural Boundary — Solar (Caveat A)

> **CRITICAL ARCHITECTURAL BOUNDARY — SOLAR**
>
> There is no machine-learning solar generation model in Phase 2. All solar energy attributes in Phase 3, including `estimated_solar_energy_kwh` and `solar_derate_factor`, represent climatological engineering estimates derived from NASA POWER monthly average daily insolation data, not machine-learning predictions.
>
> The frozen Phase 2 battery models model battery/electrochemical behavior and do not predict solar PV generation.
>
> Battery-only capacity metrics must not be interpreted as combined battery-plus-solar predictions.

* **Phase 2 ML Prediction Scope:** Phase 2 models consist exclusively of weather classification baseline (`weather_final.joblib`), total voyage fuel consumption regression (`fuel_xgb.joblib`), battery degradation SOH regression (`battery_soh_final.joblib`), and battery discharge SOC sequence tracking (`battery_soc_lstm.pt`). None of these models predict solar radiation or photovoltaic generation.
* **NASA POWER Source Data:** Historical monthly-averaged all-sky surface shortwave downward irradiance (`ALLSKY_SFC_SW_DWN` in $\text{kWh/m}^2/\text{day}$) from `data/processed/nasa_power/nasa_monthly_climatology.csv` provides the solar insolation basis.
* **Phase 3 Engineering Estimate:** Solar PV yield is calculated deterministically as an engineering scenario estimate:
  $$\text{solar\_generation\_kwh} = \text{panel\_area\_m2} \times \left(\frac{\text{efficiency\_pct}}{100}\right) \times \text{daily\_ghi} \times \text{solar\_derate\_factor} \times \left(\frac{\text{voyage\_duration\_hours}}{24}\right)$$
  This is strictly an engineering scenario estimate, not an hourly or dynamic ML dispatch model.
* **Long-Voyage Diurnal Uncertainty Flag (`solar_estimate_diurnal_uncertainty_flag`):**
  Voyages exceeding 24 hours linearly scale average daily insolation without diurnal day/night integration. To transparently signal this modeling boundary, `Tier3CleanEnergyFeasibility` includes the boolean metadata flag `solar_estimate_diurnal_uncertainty_flag`:
  * Set to `True` when `voyage_duration_hours > 24.0`, indicating higher diurnal modeling uncertainty.
  * Set to `False` when `voyage_duration_hours <= 24.0`.
  * **155 of 1,440 dataset records (10.76%, exclusively Tanker Ship, up to 36.93 hours) fall into this uncertainty band; this is a data limitation stemming from the absence of voyage departure-time data, not a fixable code defect.**
  * The flag is informational only and does **not** alter existing solar calculations, battery energy, feasibility thresholds, or displacement estimates. The underlying solar generation formula remains completely unchanged.

### 6.2 Weather Prediction Limitation — Dispatch Boundary (Caveat B)

> **WEATHER PREDICTION LIMITATION — DISPATCH BOUNDARY**
>
> The Phase 2 weather model (`models/weather_final.joblib`) is a majority-class baseline classifier with a validated test accuracy of 34.72% [^weather_acc_ref].
>
> The tested Phase 2 classifiers (Logistic Regression and XGBoost, as documented in `stage_2a_weather`) did not outperform the 34.72% majority-class baseline on the balanced 3-class weather classification task.
>
> Therefore, `predicted_weather` is retained as descriptive context metadata only. It must not be used as a gating variable for battery dispatch, solar curtailment, hybrid-generator control, or other operational control decisions.

[^weather_acc_ref]: Authoritative accuracy metric quoted directly from `docs/phase2_metrics.json` (field `stage_2a_weather.majority_baseline.accuracy` = `0.3472` and field `weather_classifier.majority_baseline_accuracy` = `0.3472`).
