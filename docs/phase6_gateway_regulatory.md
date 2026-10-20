# Phase 6 — Automated Pipeline Gateway & IMO Regulatory / Emissions Layer

## 1. Executive Summary

Phase 6 implements two additive capabilities over the verified Phase 2–3 maritime clean-energy simulation architecture:
1. **Automated Live Model Inference Gateway (`phase6_gateway.py`):** Provides a single high-level entry point (`simulate_voyage`) that directly loads the frozen Phase 2 machine learning models, dynamically constructs required feature vectors from reference tables, runs model inference, populates `Tier1Phase2Predictions`, and delegates to the Phase 3 Decision Coordinator.
2. **IMO Statutory Regulatory & Multi-Pollutant Layer (`phase6_regulatory.py`):** Implements the official IMO MEPC.353(78) operational Carbon Intensity Indicator (CII) reference line and MEPC.354(78) rating boundaries for qualifying commercial tankers, strictly enforces non-assessment status for non-qualifying vessels, and computes engineering estimates for avoided air quality pollutants (NOx, SOx, PM10, PM2.5) derived from auxiliary fuel displacement.

---

## 2. Automated Pipeline Gateway Architecture

The gateway executes the following sequential pipeline:

```text
User Simulation Request (ship_type, route_id, month, speed_knots, [distance_nm])
       │
       ▼
Input Validation (Pydantic V2 VoyageSimulationRequest)
       │
       ▼
Reference Resolution (ship_profiles.csv, routes.csv, marine/nasa climatology)
       │
       ▼
Feature Assembly & Frozen Model Inference:
  ├── Weather: models/weather_final.joblib (DummyClassifier majority baseline -> 'Calm')
  ├── Fuel: models/fuel_xgb.joblib (XGBoost Regressor -> fuel_consumption_L)
  └── SOH: models/battery_soh_final.joblib (HistGradientBoostingRegressor -> predicted_soh)
       │
       ▼
Tier 1 Predictions Assembly (Tier1Phase2Predictions)
       │
       ▼
Phase 3 Coordinator Orchestration (orchestrate_phase3_voyage)
  ├── Tier 2 Baseline Metrics (fuel cost, operational CII)
  ├── Tier 3 Clean Energy Feasibility (battery usable, solar insolation, balance/deficit)
  └── Tier 4 Engineering Scenario Estimates (displaced fuel, net assisted fuel/CO2)
       │
       ▼
Regulatory & Pollutant Assessments:
  ├── IMO Statutory CII Engine (MEPC.353(78) / MEPC.354(78))
  └── Multi-Pollutant Air Quality Displacement (Fourth IMO GHG Study Table 2-8)
       │
       ▼
Phase6SimulationResult (Unified Top-Level Result)
```

---

## 3. Weather Model Integration & Verification

The frozen artifact `models/weather_final.joblib` was inspected and verified directly:

```text
Class: sklearn.dummy.DummyClassifier
Strategy: 'constant'
Constant: 0 (maps to class 'Calm')
Classes: ['Calm', 'Moderate', 'Stormy']
Expected Input Shape: (N, 10)
Test Accuracy: 34.72% (majority-class baseline)
```

### Verified Features (Order Preserved):
1. `WS10M` (MERRA-2 10m Wind Speed, m/s)
2. `WS50M` (MERRA-2 50m Wind Speed Mean, m/s)
3. `RH2M` (MERRA-2 Relative Humidity at 2m, %)
4. `PS` (MERRA-2 Surface Pressure, kPa)
5. `T2M_MIN` (MERRA-2 Min Temperature, °C)
6. `wave_height_max` (Significant Wave Height, m)
7. `wave_period_max` (Peak Wave Period, s)
8. `wave_direction_dominant` (Dominant Wave Direction, degrees)
9. `month_sin` ($\sin(2\pi \cdot \text{month} / 12)$)
10. `month_cos` ($\cos(2\pi \cdot \text{month} / 12)$)

> **Important Disclosure:** The weather model is a zero-information majority baseline classifier. It always predicts `"Calm"`. The gateway invokes the model to satisfy end-to-end integration provenance, but does not claim that the model predicts real meteorological variability.

---

## 4. IMO Statutory CII Methodology

### 4.1 Applicable Scope & Vessel Mapping
Under MARPOL Annex VI Regulation 28, mandatory statutory CII ratings apply to ships of $5,000\text{ GT}$ and above on international voyages. The project vessel mappings are:

| Project Vessel Type | IMO Category | Statutory Status | Mapping Type | Rating Allowed? |
| :--- | :--- | :--- | :--- | :---: |
| **Tanker Ship** | `Tanker` | Subject to MARPOL Annex VI Reg 28 ($50,000\text{ DWT}$) | **OFFICIAL** | **YES (A–E)** |
| **Oil Service Boat** | None (OSV) | Absent from MEPC.353(78) Table 1 ($1,800\text{ DWT} < 5,000\text{ GT}$) | **UNSUPPORTED** | **NO (`NOT_ASSESSED`)** |
| **Fishing Trawler** | None (Fishing) | Statutorily exempt under MARPOL Annex VI Reg 19.2.3 | **UNSUPPORTED** | **NO (`NOT_ASSESSED`)** |
| **Surfer Boat** | None (Crew Craft) | Absent from MEPC.353(78) Table 1 ($120\text{ DWT} < 5,000\text{ GT}$) | **UNSUPPORTED** | **NO (`NOT_ASSESSED`)** |

* **Strict Prohibition:** No silent category substitution is permitted. Unsupported and exempt vessels receive `cii_rating = "NOT_ASSESSED"` with machine-readable reasons (`"UNSUPPORTED_VESSEL_CATEGORY_MAPPING"` or `"STATUTORILY_EXEMPT"`).

### 4.2 Reference Line Formula
Under Resolution MEPC.353(78) Table 1 for Tankers:
$$\text{CII}_{\text{ref}} = 5247 \times \text{DWT}^{-0.610}\quad [\text{g CO}_2 / (\text{DWT} \cdot \text{nm})]$$

### 4.3 Required CII & Reduction Factor ($Z$)
$$\text{Required\_CII} = \text{CII}_{\text{ref}} \times \left(1 - \frac{Z}{100}\right)$$

Supported statutory reduction factors (MARPOL Annex VI Regulation 28.4 / MEPC.338(76)):
* 2023: $Z = 5.0\%$
* 2024: $Z = 7.0\%$
* 2025: $Z = 9.0\%$
* 2026: $Z = 11.0\%$

### 4.4 Rating Boundaries
Under Resolution MEPC.354(78) Table 1 for Tankers:
* $\text{Boundary}_{A/B} = 0.82 \times \text{Required\_CII}$
* $\text{Boundary}_{B/C} = 0.93 \times \text{Required\_CII}$
* $\text{Boundary}_{C/D} = 1.08 \times \text{Required\_CII}$
* $\text{Boundary}_{D/E} = 1.28 \times \text{Required\_CII}$

Rating assignment:
* $\text{Attained} \le \text{Boundary}_{A/B} \rightarrow \mathbf{A}\ (\text{Major Superior})$
* $\text{Boundary}_{A/B} < \text{Attained} \le \text{Boundary}_{B/C} \rightarrow \mathbf{B}\ (\text{Minor Superior})$
* $\text{Boundary}_{B/C} < \text{Attained} \le \text{Boundary}_{C/D} \rightarrow \mathbf{C}\ (\text{Moderate})$
* $\text{Boundary}_{C/D} < \text{Attained} \le \text{Boundary}_{D/E} \rightarrow \mathbf{D}\ (\text{Minor Inferior})$
* $\text{Attained} > \text{Boundary}_{D/E} \rightarrow \mathbf{E}\ (\text{Inferior})$

If attained CII lands exactly on a boundary, Resolution MEPC.354(78) Paragraph 4.2 assigns the superior rating.

---

## 5. Multi-Pollutant Emissions Methodology

Auxiliary diesel displacement yields air quality pollutant avoidance modeled as a deterministic engineering layer:

$$\text{Fuel Mass (kg)} = \text{Fuel Volume (L)} \times \rho_{\text{fuel}}$$
$$\text{Pollutant Mass (kg)} = \text{Fuel Mass (kg)} \times \text{Emission Factor (kg/kg fuel)}$$
$$\text{Avoided Pollutant (kg)} = \text{Displaced Fuel Mass (kg)} \times \text{Emission Factor (kg/kg fuel)}$$

### Default Emission Factors (Fourth IMO GHG Study 2020 Table 2-8):
* **$\text{NO}_x$:** $0.0570\ \text{kg NO}_x / \text{kg fuel}$ ($57.0\ \text{kg/tonne}$) for medium-speed 4-stroke auxiliary engines.
* **$\text{SO}_x$:** $0.0097753\ \text{kg SO}_x / \text{kg fuel}$ (based on global $0.50\% S$ sulfur cap, stoichiometric conversion $2 \times 0.97753 \times 0.0050$).
* **$\text{PM}_{10}$:** $0.00110\ \text{kg PM}_{10} / \text{kg fuel}$ ($1.10\ \text{kg/tonne}$).
* **$\text{PM}_{2.5}$:** $0.00101\ \text{kg PM}_{2.5} / \text{kg fuel}$ ($1.01\ \text{kg/tonne}$).
* **Fuel Density ($\rho$):** $0.850\ \text{kg/L}$ for Marine Diesel Oil (MDO).

> **Disclaimer:** Air quality pollutant figures are deterministic engineering estimates. They do not constitute statutory MARPOL Annex VI Regulation 13 / 14 certification.
