# Model C - SOH Lightweight Training Report

**Project:** Maritime Grid Battery Modelling
**Date:** 2026-09-27
**Stage:** Phase 2C - SOH Training

---

## 1. OBJECTIVE

Train lightweight SOH regression models on NASA 18650 battery discharge data.
CPU-only. No neural networks. No hyperparameter search.

---

## 2. TARGET DEFINITION

```
SOH = Capacity_numeric / 2.0 Ah  (nominal-reference)
```

- Denominator: fixed 2.0 Ah nominal capacity (not first-discharge, not actual)
- SOH > 1.0 records are retained (not clipped)
- Capacity_numeric is the target — never used as an input feature

---

## 3. DATASET

Source: `data/processed/battery/battery_discharge_soh.csv`

| Item | Count |
|------|-------|
| Total discharge records | 2769 |
| Unique cells | 34 |
| Eligible after all exclusions | 2187 |

---

## 4. EXCLUSIONS

| Reason | Records | Description |
|--------|---------|-------------|
| zero_capacity_interrupted | 3 | B0042/B0043/B0044 cycle 6 (cap=0.000 Ah) |
| B0041_calibration_artifact | 42 | B0041 cycles 1-42 (cap<0.5 Ah; hard discontinuity at cycle 43) |
| missing_waveform | 537 | B0007(42), B0018(132), B0053(56), B0054(103), B0055(102), B0056(102) |
| **Total excluded** | **582** | |

B0041 exclusion criterion: `Capacity_numeric < 0.5 Ah` applied to cycle_number 1-42.
- Max capacity in excluded range: 0.0569 Ah
- Min capacity in retained range: 0.8365 Ah
- Hard discontinuity confirmed: gap of >0.78 Ah between groups.

Source file NOT modified. Exclusion flags stored in `soh_training_metadata.csv`.

---

## 5. TRAIN / VALIDATION / TEST SPLIT

| Partition | Cells | n Cells | n Observations |
|-----------|-------|---------|----------------|
| TRAIN | ['B0005', 'B0025', 'B0026', 'B0027', 'B0028', 'B0029', 'B0030', 'B0031', 'B0032', 'B0033', 'B0034', 'B0036', 'B0038', 'B0039', 'B0040', 'B0041', 'B0042', 'B0043', 'B0044', 'B0045', 'B0046', 'B0047', 'B0048', 'B0049', 'B0050', 'B0051', 'B0052'] | 27 | 1893 |
| VALIDATION | ['B0006'] | 1 | 168 |
| TEST (final) | ['B0007'] | 1 | 126 |

- B0006 selected as validation cell (established reference cell, consistent with SOC split)
- B0007 reserved as final unseen test cell (never in train, val, scaler fit, or model selection)
- Split is cell-level holdout (no random cycle splitting)

---

## 6. FEATURES

| Feature | Source | Notes |
|---------|--------|-------|
| V_end | Voltage_measured at final timestep | From discharge waveform |
| V_drop | V_start - V_end | Fully within discharge window |
| V_mean | Mean Voltage_measured | Within discharge window |
| V_min | Min Voltage_measured | Within discharge window |
| duration | Time_final - Time_initial | Within discharge window |
| ambient_temperature | Discharge metadata | Cell-level, known at cycle start |
| cycle_number | Sequential discharge index per cell | From metadata |

No target-derived features. No Capacity. No SOH. No Re/Rct (null in processed CSV).

---

## 7. PREPROCESSING

- StandardScaler fitted on TRAIN partition only
- Same frozen scaler applied to transform val and test
- No scaling applied to B0006 or B0007 during fitting
- RandomForest and HistGradientBoosting: no scaling required

---

## 8. BASELINE

Predict `mean_train_SOH = 0.6724` for all observations.

| Set | RMSE | MAE | R2 |
|-----|------|-----|----|
| Validation (B0006) | 0.1612 | 0.1232 | -0.6471 |
| Test B0007 | 0.1938 | 0.1825 | -7.8165 |

---

## 9. MODEL RESULTS

| Model | Train RMSE | Train MAE | Train R2 | Val RMSE | Val MAE | Val R2 |
|-------|-----------|----------|---------|---------|--------|-------|
| LinearRegression                              | 0.1415 | 0.1035 | 0.6710 | 0.1267 | 0.0989 | -0.0166 |
| Ridge(alpha=1.0)                              | 0.1415 | 0.1034 | 0.6707 | 0.1264 | 0.0988 | -0.0117 |
| RandomForestRegressor(n_est=200, depth=8)     | 0.0174 | 0.0097 | 0.9950 | 0.0396 | 0.0322 | 0.9004 |
| HistGradientBoosting(iter=200, lr=0.05)       | 0.0222 | 0.0104 | 0.9919 | 0.0392 | 0.0344 | 0.9028 |

---

## 10. B0007 FINAL TEST

Selected model: **HistGradientBoosting(iter=200, lr=0.05)** (lowest validation RMSE = 0.0392)

B0007 was evaluated ONCE after model selection.

| Metric | Value |
|--------|-------|
| RMSE | 0.0397 |
| MAE | 0.0335 |
| R2 | 0.6308 |
| Mean residual | 0.0252 |
| Median residual | 0.0238 |
| Predictions < 0 | 0 |
| Predictions > 1 | 0 |
| N (B0007 test) | 126 |

### By Cycle Range

| Cycles | N | RMSE | MAE | R2 |
|--------|---|------|-----|----|
| 1-40    |   40 | 0.0225 | 0.0192 | -4.4130 |
| 41-80   |   40 | 0.0234 | 0.0202 | 0.4265 |
| 81-126  |   46 | 0.0582 | 0.0575 | -7.1937 |

---

## 11. RESIDUAL ANALYSIS

Selected model: HistGradientBoosting(iter=200, lr=0.05) on B0007 test

| Metric | Value |
|--------|-------|
| Mean residual | 0.0252 |
| Median residual | 0.0238 |
| Std residual | 0.0306 |
| Corr(residual, actual SOH) | -0.9055 |

### By SOH Range

| SOH Range | N | Mean Resid | Median Resid | Std |
|-----------|---|-----------|-------------|-----|
| 0.6-0.8  |   37 | +0.0612 | +0.0615 | 0.0052 |
| 0.8-1.0  |   89 | +0.0102 | +0.0153 | 0.0235 |

---

## 12. FEATURE IMPORTANCE


**LinearRegression:**  - V_end: 0.3291  - V_drop: 0.3622  - V_mean: -0.0281  - V_min: 0.0305  - duration: 0.1135  - ambient_temperature: 0.1615  - cycle_number: 0.0088
**Ridge(alpha=1.0):**  - V_end: 0.2710  - V_drop: 0.3043  - V_mean: -0.0275  - V_min: 0.0301  - duration: 0.1137  - ambient_temperature: 0.1621  - cycle_number: 0.0091
**RandomForestRegressor(n_est=200, depth=8):**  - V_end: 0.0145  - V_drop: 0.1823  - V_mean: 0.0077  - V_min: 0.0395  - duration: 0.5822  - ambient_temperature: 0.1516  - cycle_number: 0.0222
**HistGradientBoosting(iter=200, lr=0.05):**

See: `docs/figures/battery_soh_feature_importance.png`

---

## 13. LEAKAGE CHECK

| Check | Status |
|-------|--------|
| B0007 absent from training | PASS |
| B0007 absent from scaler fitting | PASS |
| B0007 absent from model selection | PASS |
| No Capacity or SOH used as feature | PASS |
| No target-derived feature | PASS |
| No missing waveform silently imputed | PASS (excluded) |
| No zero-capacity cycle used | PASS (excluded) |
| No B0041 calibration cycle used | PASS (cycles 1-42 excluded) |
| No raw data modified | PASS |

---

## 14. LIMITATIONS

1. B0041 cycles 43-67 (25 cycles) are included. These are a small normal-operation sample after cutoff-voltage calibration runs; they represent a different degradation trajectory than typical cells.
2. B0042, B0043, B0044 are labelled 22C in the processed metadata despite being in the 4C NASA batch. Temperature feature may be inconsistent for these cells.
3. Re and Rct are entirely null in the processed CSV and are excluded. Electrochemical impedance features would likely improve the model.
4. Cells B0033, B0034, B0036, B0038, B0039, B0040 enter the dataset mid-life (first SOH 0.03-0.50). The model is trained on partial degradation trajectories for these cells.
5. SOH = Capacity / 2.0 Ah is a nominal-reference SOH, not actual usable SOH. The denominator is fixed and does not account for cell-to-cell capacity variation.
6. B0007 has 42 discharge records with missing raw waveform files. These 42 cycles are excluded from the test set; the final test covers 126 of 168 B0007 cycles.
7. This is a lightweight model. No neural network, no deep feature extraction, no SHAP analysis.

---

## 15. FINAL MODEL

**Selected model:** HistGradientBoosting(iter=200, lr=0.05)
- Selected by: lowest validation RMSE (0.0392) on B0006
- Evaluated once on B0007: RMSE=0.0397, MAE=0.0335, R2=0.6308
- Saved: `models/battery_soh_final.joblib`

---

## 16. NEXT STEP

SOH training is complete. Awaiting external review.

Do NOT:
- Start pack extrapolation
- Retrain any model
- Modify SOC, Model A, or Model B
- Introduce additional models
- Optimize further

Artifacts created:
- `models/battery_soh_linear.joblib`
- `models/battery_soh_ridge.joblib`
- `models/battery_soh_random_forest.joblib`
- `models/battery_soh_hist_gradient_boosting.joblib`
- `models/battery_soh_final.joblib`
- `data/processed/battery/soh_training_metadata.csv`
- `docs/model_c_soh_metrics.json`
- `docs/model_c_soh_training_report.md`
- `docs/figures/battery_soh_actual_vs_predicted.png`
- `docs/figures/battery_soh_residuals.png`
- `docs/figures/battery_soh_feature_importance.png`

*CPU-only lightweight training. B0007 untouched until final evaluation.*
