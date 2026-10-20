# Phase 2 Modelling Report (Stage 2D Corrected)

**Project:** Maritime Grid Battery Simulation
**Corrected:** 2026-09-27 (Stage 2D — pack topology reconciliation + model wiring fix)

---

## 1. Overview

Phase 2 trains and evaluates four production models:

| Model | Task | Algorithm | Status |
|-------|------|-----------|--------|
| Model A | Voyage weather classification | Majority-class baseline | COMPLETE |
| Model B | Fuel consumption regression | XGBoost | COMPLETE |
| Model C-SOC | Battery SOC estimation | 2-layer LSTM | COMPLETE |
| Model C-SOH | Battery SOH estimation | HistGradientBoosting | COMPLETE |

Stage 2D corrections:
1. All four ship-type battery pack topologies reconciled (ship_profiles.csv).
2. Invalid `soh_24_model` (pooled LinearRegression) removed; replaced by `battery_soh_final.joblib`.
3. Phase 3 output contract updated.

---

## 2. Data Validation

- **Master training table:** 1,440 rows x 47 columns (`data/processed/master_training_table.csv`)
- **Ship-holdout split:** 96 train ships / 24 test ships, stratified by ship_type, leakage-safe
- **Battery data:** 2,769 discharge records, 34 NASA 18650 cells
- **Fuel unit:** Liters (L) per voyage (Evidence Level B — Strongly Inferred; original raw source lacks explicit unit annotation)
- **Weather ceiling:** Mean route-month majority agreement = 0.4251 (low ceiling)

---

## 3. Battery SOH Correction (Phase 1)

SOH = Capacity_numeric / 2.0 Ah (nominal-reference, not usable SOH).
Denominator is fixed 2.0 Ah across all 34 cells. Verified in Stage 2C SOH audit:
max absolute diff between recomputed and stored SOH = 2.22e-16 (floating-point only).

---

## 4. Weather Ceiling Diagnostic

Route-month majority class agreement: 0.4251.
None of the classifiers exceeded the majority-class baseline.
Conclusion: weather signal in this dataset is insufficient for reliable classification.

---

## 5. CO2 Diagnostic

Empirical emission factors derived from CO2/fuel ratio in master training table:
- Diesel: 2.749960 (CV ~5.3%)
- HFO:    2.753806 (CV ~5.3%)

Fuel unit classification: Evidence Level B — Strongly Inferred as Liters (L) per voyage. Factor units are [kg CO2 / L]. Supported by empirical ratio (~2.750 kg CO2/L for Diesel, ~2.754 kg CO2/L for HFO) matching standard volumetric combustion factors, and vessel engine load plausibility; this is an engineering inference, not an explicitly sourced unit.

---

## 6. Train / Validation / Test Split

Ship-level holdout. 96 train ships / 24 test ships. No leakage across split boundary.
Battery: cell-level holdout. Train=27 cells, Val=B0006, Test=B0007.

---

## 7. Model A — Weather Classifier

| Model | Accuracy |
|-------|----------|
| Majority-class baseline (Calm) | **34.72%** |
| Logistic Regression | 33.33% |
| Tuned XGBoost | 31.94% |

**Selected:** Majority-class baseline. No ML model exceeded baseline.
Saved: `models/weather_final.joblib`

---

## 8. Model B — Fuel Regression

| Model | RMSE | MAE | R2 |
|-------|------|-----|----|
| Linear Regression | 1221.57 | 876.97 | 0.9390 |
| Tuned XGBoost | **1092.22** | **662.09** | **0.9513** |

**Selected:** XGBoost. Route holdouts: R2 > 0.95 on all 4 routes.
CO2 deterministic: RMSE=3310.00 kg, R2=0.9423.
Saved: `models/fuel_xgb.joblib`

---

## 9. Model C — Battery SOC (LSTM)

- Architecture: 2-layer LSTM, hidden=64, dropout=0.2, Adam lr=0.001
- Best epoch: 11 (early stopping at epoch 16)
- Train: RMSE=0.0788, MAE=0.0617, R2=0.8728
- Validation: RMSE=0.0868, MAE=0.0727, R2=0.7703
- **B0007 Unseen-Cell Test: RMSE=0.0678, MAE=0.0539, R2=0.9089**
- Saved: `models/battery_soc_lstm.pt`

SOC definition: Nominal-reference SOC = clip(1 - Q_discharged / 2.0 Ah, 0, 1).
Scaler: `data/processed/battery/soc_scaler.joblib` (fitted on train only, frozen for val/test).

---

## 10. Model C — Battery SOH (Regression)

**Model Identity & Architecture:**
- **Model Type:** `HistGradientBoostingRegressor` (from `sklearn.ensemble`)
- **Nature:** Per-cycle waveform SOH regressor
- **Target:** `SOH = Capacity_numeric / 2.0 Ah` (nominal-reference SOH, continuous fraction [0, 1])
- **Input Features (7):**
  1. `V_end`: Voltage at final timestep of discharge waveform
  2. `V_drop`: `V_start - V_end` across the discharge event
  3. `V_mean`: Mean voltage during discharge
  4. `V_min`: Minimum voltage recorded during discharge
  5. `duration`: `Time_final - Time_initial` of discharge (seconds)
  6. `ambient_temperature`: Cell ambient temperature (°C)
  7. `cycle_number`: Sequential discharge cycle count for the cell
- **Split Strategy:** Strict Cell-Holdout (disjoint battery cells):
  - Train: 27 cells (1,893 observations pooled)
  - Validation: 1 cell — `B0006` (168 observations, 24°C)
  - Test: 1 cell — `B0007` (126 observations, 24°C)
- **Exclusions:** 582 records excluded (B0041 calibration cycles 1–42 [capacity < 0.5 Ah], B0042/43/44 cycle 6 [zero capacity], 537 records with missing raw waveform files).

| Model | Train RMSE | Train MAE | Train R2 | Val RMSE | Val MAE | Val R2 | Test RMSE | Test MAE | Test R2 |
|-------|------------|-----------|----------|----------|---------|--------|-----------|----------|---------|
| LinearRegression | 0.1415 | 0.1035 | 0.6710 | 0.1267 | 0.0989 | -0.0166 | 0.1655 | 0.1581 | -5.4252 |
| Ridge (α=1.0) | 0.1415 | 0.1034 | 0.6707 | 0.1264 | 0.0988 | -0.0117 | 0.1663 | 0.1590 | -5.4894 |
| RandomForest | 0.0174 | 0.0097 | 0.9950 | 0.0396 | 0.0322 | 0.9004 | 0.0401 | 0.0350 | 0.6217 |
| **HistGradientBoosting** | **0.0222** | **0.0104** | **0.9919** | **0.0392** | **0.0344** | **0.9028** | **0.0397** | **0.0335** | **0.6308** |

**Selected Model:** `HistGradientBoosting(max_iter=200, lr=0.05, max_leaf_nodes=15, l2_regularization=1.0, random_state=42)`
- Selected strictly by lowest validation RMSE (0.0392 on B0006).
- Evaluated once on held-out test cell B0007: RMSE = 0.0397, MAE = 0.0335, R² = 0.6308.
- Saved: `models/battery_soh_final.joblib`

**Theil-Sen Reconciliation:**
- Theil-Sen robust regression was never executed or saved as an artifact in this project; the Stage 2C production model is the 7-feature HistGradientBoostingRegressor above.

**Cross-Temperature Generalization Status:**
- Validation (`B0006`) and test (`B0007`) are both 24°C room-temperature cells.
- Cross-temperature held-out performance is not available from existing artifacts without retraining diagnostic models; no retraining performed.
- Validated primarily on room-temperature cells; reduced confidence for ships assumed to operate in significantly warmer or colder conditions.

---

## 11. Stage 2D — Pack Topology Reconciliation

### Before (all INCONSISTENT)

| Ship | Old Config | Old Voltage | Old kWh |
|------|-----------|-------------|---------|
| Oil Service Boat | 96S120P | 400 V | 650 |
| Fishing Trawler | 96S50P | 400 V | 250 |
| Surfer Boat | 96S30P | 400 V | 150 |
| Tanker Ship | 96S250P | 800 V | 1200 |

### After (all CONSISTENT — 96 x 3.6 = 345.6 V, P solved from kWh target)

| Ship | New Config | New Voltage | Exact kWh |
|------|-----------|-------------|----------|
| Oil Service Boat | 96S940P | 345.6 V | 649.7280 |
| Fishing Trawler | 96S362P | 345.6 V | 250.2144 |
| Surfer Boat | 96S217P | 345.6 V | 149.9904 |
| Tanker Ship | 96S1736P | 345.6 V | 1199.9232 |

All kWh design targets preserved within rounding (max deviation <0.08 kWh).
Source file: `data/reference/ship_profiles.csv`. Raw data NOT modified.

### Model Wiring & SOH-Aware SOC Integration

1. `predict_pack_soh()` previously called `soh_24_model` (pooled LinearRegression — declared invalid in Stage 2C SOH audit). Now calls `models/battery_soh_final.joblib` (HistGradientBoosting, cell-holdout split, B0007 RMSE=0.0397).
2. `predict_pack_soc_end()` implements degradation-adjusted Coulomb counting:
   ```python
   effective_ah = pack_capacity_ah * predicted_soh
   soc_end = initial_soc - q_discharged_ah / effective_ah
   soc_end = max(0.0, min(1.0, soc_end))
   ```
   **Design Decision:** Battery end-of-voyage SOC calculations apply predicted SOH to available capacity, so battery degradation directly affects reported end-of-voyage SOC. This is the SOC representation consumed by the Phase 3 Decision Coordinator.
3. For the historical Tanker voyage (200 A for 4 h = 800 Ah, starting SOC = 0.90, SOH = 0.7387 on the 96S1736P / 3,472 Ah pack), this yields:
   $$\text{SOC}_{\text{end}} = 0.90 - \frac{800.0\text{ Ah}}{3,472.0\text{ Ah} \times 0.7387} = 0.90 - 0.3119 = \mathbf{0.5881}$$

---

## 12. Phase 3 Contract

See `docs/phase3_output_contract.json` (updated Stage 2D Closeout).

Key outputs:
- `predicted_weather` — majority-class baseline
- `predicted_fuel_consumption` — XGBoost regression (Liters per voyage, Evidence Level B — Strongly Inferred)
- `predicted_CO2` — deterministic: fuel x emission_factor (kg CO2)
- `predicted_SOC_end_of_voyage` — degradation-adjusted Coulomb counting with SOH scaling + corrected pack topology
- `predicted_SOH` — HistGradientBoosting, cell-holdout regressor

---

## 13. Limitations

1. **Weather model:** majority-class only; no ML advantage found in this dataset.
2. **Fuel unit:** Inferred as Liters (L) per voyage (Evidence Level B — Strongly Inferred); not an explicitly sourced unit. Supported by empirical CO2/fuel ratio (~2.75 kg CO2/L) and vessel engine load plausibility. OPEX calculations safely apply fuel_consumption (L) x fuel_price_per_litre ($/L); CII calculates directly from CO2 mass.
3. **SOH R2 on B0007:** 0.631 overall; negative R2 on cycles 1-40 and 81-126 due to systematic
   +0.025 over-prediction bias (training population SOH distribution mismatch with B0007).
4. **Pack extrapolation:** uses engineering defaults for waveform features in SOH prediction.
   All pack outputs are ASSUMPTION-BASED and not validated against measured ship battery data.
5. **B0041 calibration cycles 1-42:** excluded from SOH training (cap < 0.5 Ah).
6. **Missing waveforms:** 537 of 2,769 discharge records lack raw files (B0018, B0053-B0056 complete; B0007 42 of 168).
7. **SOC model:** nominal-reference SOC (denominator 2.0 Ah fixed) — not usable SOC.

### Battery Role Scope Limitation

The Stage 2D end-of-voyage SOC evaluations establish a fundamental architectural boundary for battery utilization across all vessel classes under their current pack sizing:

| Ship Type | Pack Capacity | Predicted SOH | Usable Pack Energy | Evaluated Demand | Start SOC | End SOC | Evaluated Scenario |
|-----------|---------------|---------------|-------------------|------------------|-----------|---------|--------------------|
| Oil Service Boat | 649.7280 kWh | 0.7471 | 485.41 kWh | 180.00 kWh | 0.9000 | 0.5292 | Port maneuvering (1h @ 90 kW) + transit hotel (3h @ 30 kW) |
| Fishing Trawler | 250.2144 kWh | 0.7442 | 186.21 kWh | 80.00 kWh | 0.8500 | 0.4204 | Transit hotel load only (4h @ 20 kW) |
| Surfer Boat | 149.9904 kWh | 0.7488 | 112.32 kWh | 37.00 kWh | 0.8000 | 0.4706 | Sprint boost (0.1h @ 270 kW) + transit hotel (1h @ 10 kW) |
| Tanker Ship | 1199.9232 kWh | 0.7387 | 886.38 kWh | 632.00 kWh | 0.9000 | 0.1870 | Zero-emission port maneuvering (2h @ 216 kW) + hotel (2h @ 100 kW) |

**Architectural Scope Conclusion:**
The current battery pack sizing supports auxiliary/hotel electrical loads and short-duration port maneuvering / boost assistance rather than full propulsion replacement during multi-hour open-sea voyages.

*Key Context & Conditions:*
1. Sized at 150–1,200 kWh in `ship_profiles.csv`, the battery packs are dimensioned for auxiliary and short-duration assist duties. Full propulsion demands across multi-hour voyages (main engine ratings: 1,200–7,200 kW) would exceed the available onboard battery capacities.
2. This operational conclusion follows directly from the current assumed pack sizes in `ship_profiles.csv`. It is an engineering sizing constraint rather than an invariant physical law. If battery pack sizing assumptions are revised upward in future designs, this scope boundary must be re-evaluated accordingly.
3. In Phase 3 Decision Coordination, diesel engines must serve as the primary propulsion source, while battery and solar systems are coordinated for auxiliary power, hotel loads, peak shaving, and harbor maneuvering.

---

*Generated by stage2d_pack_reconciliation.py. Updated in Stage 2D Closeout. No raw data modified.*
