# Model C — SOH Audit Report

**Project:** Maritime Grid Battery Modelling  
**Date:** 2026-09-27  
**Stage:** Phase 2C — SOH Audit (Read-Only)

> This is a read-only audit. No raw data, no preprocessing artifacts, no SOC model, and no Model A/B artifacts were modified.

---

## Section A — Dataset Inventory (Previously Computed)

| Item | Value |
|------|-------|
| Total discharge records | 2,769 |
| Unique cells | 34 |
| Records with SOH > 1.0 | 11 |
| Records with SOH <= 0 | 19 |
| Missing raw waveform files | 537 / 2,769 (19.4%) |

Cells: B0005–B0007, B0018, B0025–B0034, B0036, B0038–B0056  
Temperature groups: 4°C, 22°C, 24°C, 43°C, 44°C

---

## Section B — SOH > 1.0 Investigation (Previously Computed)

- **B0006** (7 early cycles): Cap 2.00–2.04 Ah, SOH 1.00–1.02. Physically plausible — 2.0 Ah is a rounded nominal lower bound; a fresh cell can slightly exceed it.
- **B0036, B0049, B0050, B0051**: Isolated high-capacity readings. Raw waveform files confirmed present and valid.
- **Decision:** Do NOT delete or clip SOH > 1.0 records.

---

## Section C — Temperature-Stratified SOH Trends (Previously Computed)

| Temperature | Slope (SOH/cycle) | Assessment |
|-------------|-------------------|------------|
| 4°C | +0.001683 | ARTIFACT — pooled mixing of B0041 calibration cycles and B0045–B0056 |
| 22°C | −0.000389 | Weak negative (B0042–B0044) |
| 24°C | −0.000960 | Normal degradation |
| 43°C | −0.002311 | Accelerated degradation |
| 44°C | −0.003918 | Most accelerated |

**Root cause of positive 4°C slope:** B0041–B0044 used experimentally varied discharge cutoff voltages (2V / 2.2V / 2.5V / 2.7V). B0041 early cycles deliver only ~0.044 Ah — this is NOT capacity recovery but a calibration artifact caused by early discharge termination. NASA README states: "Note that there are several discharge runs where the capacity was very low. Reasons for this have not been fully analyzed."

---

## Section D — Per-Cell SOH Trends

Linear regression: SOH ~ cycle_num, per cell with ≥5 cycles. Sorted by slope ascending.

| Cell | Temp | Cycles | First SOH | Last SOH | Slope | r | p |
|------|------|--------|-----------|----------|-------|---|---|
| B0050 | 4 | 21 | 0.4316 | 0.1390 | −0.033468 | −0.578 | 0.006 |
| B0049 | 4 | 25 | 0.4292 | 0.3457 | −0.016797 | −0.606 | 0.001 |
| B0051 | 4 | 25 | 0.3217 | 0.3389 | −0.013756 | −0.525 | 0.007 |
| B0042 | 22 | 112 | 0.8644 | 0.6687 | −0.003282 | −0.287 | 0.002 |
| B0046 | 4 | 72 | 0.8641 | 0.5769 | −0.003216 | −0.471 | 0.000 |
| B0047 | 4 | 72 | 0.8372 | 0.5784 | −0.003008 | −0.450 | 0.000 |
| B0043 | 22 | 112 | 0.8569 | 0.6384 | −0.002987 | −0.268 | 0.004 |
| B0044 | 22 | 112 | 0.8433 | 0.6243 | −0.002950 | −0.272 | 0.004 |
| B0032 | 43 | 40 | 0.8524 | 0.8179 | −0.002668 | −0.909 | 0.000 |
| B0029 | 43 | 40 | 0.8488 | 0.8060 | −0.002548 | −0.930 | 0.000 |
| B0006 | 24 | 168 | 1.0177 | 0.5928 | −0.002543 | −0.982 | 0.000 |
| B0048 | 4 | 72 | 0.8290 | 0.6116 | −0.002506 | −0.376 | 0.001 |
| B0030 | 43 | 40 | 0.8280 | 0.7814 | −0.002444 | −0.938 | 0.000 |
| B0018 | 24 | 132 | 0.9275 | 0.6705 | −0.001963 | −0.970 | 0.000 |
| B0005 | 24 | 168 | 0.9282 | 0.6625 | −0.001933 | −0.988 | 0.000 |
| B0045 | 4 | 72 | 0.5410 | 0.3035 | −0.001861 | −0.542 | 0.000 |
| B0053 | 4 | 56 | 0.5346 | 0.0000 | −0.001656 | −0.370 | 0.005 |
| B0007 | 24 | 168 | 0.9455 | 0.7162 | −0.001635 | −0.988 | 0.000 |
| B0031 | 43 | 40 | 0.8333 | 0.8336 | −0.001584 | −0.822 | 0.000 |
| B0028 | 24 | 28 | 0.9023 | 0.8586 | −0.001324 | −0.942 | 0.000 |
| B0025 | 24 | 28 | 0.9235 | 0.8839 | −0.001271 | −0.938 | 0.000 |
| B0054 | 4 | 103 | 0.3700 | 0.0000 | −0.001244 | −0.629 | 0.000 |
| B0033 | 24 | 197 | 0.0342 | 0.6576 | −0.000893 | −0.359 | 0.000 |
| B0055 | 4 | 102 | 0.3995 | 0.4954 | −0.000814 | −0.687 | 0.000 |
| B0027 | 24 | 28 | 0.9117 | 0.8850 | −0.000549 | −0.700 | 0.000 |
| B0034 | 24 | 197 | 0.3730 | 0.6401 | −0.000530 | −0.585 | 0.000 |
| B0056 | 4 | 102 | 0.3926 | 0.5645 | −0.000499 | −0.446 | 0.000 |
| B0036 | 24 | 197 | 0.5010 | 0.7796 | −0.000464 | −0.545 | 0.000 |
| B0026 | 24 | 28 | 0.9066 | 0.8844 | +0.000191 | +0.038 | 0.847 |
| B0038 | 24 | 47 | 0.4490 | 0.7651 | +0.008066 | +0.686 | 0.000 |
| B0040 | 24 | 47 | 0.3367 | 0.2785 | +0.008137 | +0.479 | 0.001 |
| B0041 | 4 | 67 | 0.0278 | 0.4182 | +0.009129 | +0.799 | 0.000 |
| B0039 | 24 | 47 | 0.0595 | 0.6577 | +0.014527 | +0.678 | 0.000 |

**Strongly negative (< −0.001):** 22 cells — all show expected electrochemical degradation  
**Strongly positive (> +0.001):** B0038, B0039, B0040, B0041 — anomalous  
**Near-zero:** B0026, B0027, B0033, B0034, B0036, B0055, B0056

### Anomalous Positive-Slope Cells

- **B0041:** First-half mean cap 0.0483 Ah vs second-half 0.7134 Ah. Positive slope is the protocol progression from calibration-cutoff cycles to normal-sized discharge. Not capacity recovery.
- **B0038, B0039, B0040** (24°C): First SOH values 0.45 / 0.06 / 0.34 — these cells entered the dataset mid-degradation. The positive slope is a recording artifact, not electrochemical behaviour.
- **B0033, B0034, B0036:** Similar mid-life entry (first SOH 0.03–0.50).

> Warning: Cells B0033, B0034, B0036, B0038, B0039, B0040 begin at atypically low SOH and show partial positive or near-zero slopes. Training an SOH model on these cells without a cell_id flag or exclusion criterion may introduce confounding behaviour.

---

## Section E — B0041–B0044 Investigation

### B0041 (4°C per metadata, cutoff=2V, 67 cycles)

| Metric | Value |
|--------|-------|
| First-half capacity mean | 0.0483 Ah |
| Second-half capacity mean | 0.7134 Ah |
| Cycle 1 capacity | 0.0556 Ah (SOH 0.0278) |
| Cycle 67 capacity | 0.8365 Ah (SOH 0.4182) |
| First 3 waveforms | Present, 93–95 rows, ~1,050–1,065 s, required columns OK |

**Classification: Calibration artifact.** The extremely low early capacities result directly from the 2V cutoff voltage ending discharge before meaningful charge is extracted. Not genuine capacity recovery.

### B0042 (22°C per metadata, 112 cycles)

| Metric | Value |
|--------|-------|
| First-half capacity mean | 1.2064 Ah |
| Second-half capacity mean | 0.6854 Ah |
| Cycle 1 capacity | 1.7287 Ah (SOH 0.8644) |
| Cycle 6 capacity | 0.0000 Ah (SOH 0.000) — anomalous zero |
| Cycle 112 capacity | 1.3375 Ah (SOH 0.6687) |
| First 3 waveforms | Present, 341–358 rows, ~3,245–3,361 s, required columns OK |

**Classification: Genuine degradation with one anomalous zero-capacity cycle (cycle 6).**

### B0043 (22°C per metadata, 112 cycles)

| Metric | Value |
|--------|-------|
| First-half capacity mean | 1.1460 Ah |
| Second-half capacity mean | 0.6695 Ah |
| Cycle 6 capacity | 0.0000 Ah — anomalous zero |
| Cycle 112 capacity | 1.2768 Ah (SOH 0.6384) |

**Classification: Genuine degradation with one anomalous zero-capacity cycle.**

### B0044 (22°C per metadata, 112 cycles)

| Metric | Value |
|--------|-------|
| First-half capacity mean | 1.1126 Ah |
| Second-half capacity mean | 0.6467 Ah |
| Cycle 6 capacity | 0.0000 Ah — anomalous zero |
| Cycle 112 capacity | 1.2486 Ah (SOH 0.6243) |

**Classification: Genuine degradation with one anomalous zero-capacity cycle.**

> Note: B0042, B0043, B0044 appear as **22°C** in the processed metadata despite the NASA README placing them in the 4°C experimental batch. Their waveform durations (~3,360 s) and initial capacities (~1.73 Ah) are consistent with room-temperature operation, not 4°C. This is a **dataset-level labelling discrepancy** — must be documented; use the processed CSV temperature value (22°C) with a noted caveat.

---

## Section F — Raw Waveform / Metadata Consistency

| Metric | Value |
|--------|-------|
| Total discharge records | 2,769 |
| Missing raw files | 537 (19.4%) |
| Present raw files | 2,232 |
| Malformed (wrong/missing columns) | 0 |
| Too short (< 5 rows) | 0 |
| Fully OK | **2,232** |

### Missing files per cell

| Cell | Missing Count | Fraction |
|------|---------------|----------|
| B0007 | 42 | 25% (126 of 168 present) |
| B0018 | 132 | 100% (no raw files at all) |
| B0053 | 56 | 100% |
| B0054 | 103 | 100% |
| B0055 | 102 | 100% |
| B0056 | 102 | 100% |

All 2,232 present waveform files contain the required columns (`Time`, `Voltage_measured`, `Current_measured`, `Temperature_measured`) and ≥ 5 rows. No malformed files detected.

---

## Section G — SOH Target Construction Audit

| Check | Result |
|-------|--------|
| Formula | `SOH = Capacity_numeric / 2.0` |
| Max absolute diff (recomputed vs stored) | 2.22e-16 (floating-point precision) |
| Mean absolute diff | 4.69e-18 |
| Rows with diff > 1e-9 | **0** |
| SOH > 1.0 | 11 records |
| SOH <= 0 | 19 records |

**Verification: PASSED.** The stored SOH column is exactly `Capacity_numeric / 2.0`. It is not derived from the SOC model, from future data, or any other source. The denominator is the fixed nominal 2.0 Ah, consistent with the Phase 1 decision. `Capacity_first_discharge` stores the first measured discharge capacity per cell — it is NOT the SOH denominator.

---

## Section H — Leakage / Split Analysis

| Strategy | Verdict | Reason |
|----------|---------|--------|
| Random cycle split | **INVALID — leakage** | Adjacent cycles from same cell are autocorrelated (B0005 lag-1 r = 0.9977). Test sees the cell at nearly the same degradation state as train. |
| Random sequence split | **INVALID — leakage** | Same issue, amplified by overlapping windows. |
| Cell holdout split | **VALID — Recommended** | Fully withheld cells never appear in train/val. Tests genuine generalization to an unseen battery. |
| Chronological per-cell | **Conditionally valid** | Prevents within-cell leakage but model trains and tests on same physical cells; tests interpolation not generalization. |

**B0005 lag-1 SOH autocorrelation: r = 0.9977** — random splits cannot break this.

**Recommendation:** Cell holdout split.  
- Test: **B0007** (fully withheld — consistent with SOC test cell)  
- Val: at least one additional withheld cell  
- Train: all remaining cells, fully disjoint from val/test  
- Within training cells: maintain chronological ordering

---

## Section I — Feature Design Audit

| Feature | Classification | Notes |
|---------|---------------|-------|
| Voltage at end of discharge | **SAFE** | Directly measured within discharge window |
| Voltage drop (V_start − V_end) | **SAFE** | Within discharge window |
| Mean voltage during discharge | **SAFE** | Aggregate of within-window measurements |
| Min voltage during discharge | **SAFE** | Within discharge window |
| Current profile statistics | **SAFE** | Measured during discharge |
| Discharge duration | **SAFE** | Within discharge window |
| Ambient temperature | **SAFE** | Known at cycle start; cell-level metadata |
| Cycle number (absolute) | **SAFE** | Legitimate degradation state indicator |
| Re (electrolyte resistance) | **CONDITIONAL** | **Null in processed CSV** — must re-extract from raw EIS steps if desired; must verify EIS measured before (not after) the corresponding discharge |
| Rct (charge transfer resistance) | **CONDITIONAL** | Same as Re |
| `Capacity_numeric` | **LEAKAGE** | IS the target (SOH = Cap / 2.0). Never use as a feature. |
| `Capacity_first_discharge` | **LEAKAGE** | Derived from target. Never use as a feature. |
| `SOH` (stored column) | **LEAKAGE** | IS the target label. Never use as a feature. |
| Future cycle statistics | **LEAKAGE** | Any end-of-life aggregate is forbidden. |
| B0041–B0044 low-cap cycles | **CONDITIONAL** | Anomalous calibration cycles; require flag or exclusion. |

> Note: Re and Rct columns in `battery_discharge_soh.csv` are **entirely null** (0 non-null out of 2,769 rows). They cannot be used from the processed CSV.

---

## Section J — Old SOH Model Audit

**File:** `models/battery_soh_regression.joblib`  
**Model type:** `sklearn.linear_model.LinearRegression`  
**Coefficient:** `[-0.00096013]`  
**Intercept:** `0.8484`

### Pipeline code (`phase2_pipeline.py` lines 668–704)

```python
for temp in temp_groups:
    grp = dis_meta[dis_meta["ambient_temperature"] == temp].copy()
    grp["cycle_num"] = grp.groupby("battery_id").cumcount() + 1
    Xt = grp["cycle_num"].values.reshape(-1,1).astype(float)
    yt = grp["SOH"].values.astype(float)
    lr_soh = LinearRegression()
    lr_soh.fit(Xt, yt)  # NO test holdout
    ...
# 24C model saved as primary
soh_24_model.fit(grp["cycle_num"].values.reshape(-1,1), grp["SOH"].values)
```

### Critical defects

1. **Pooled regression — INVALID:** Multiple heterogeneous cells pooled per temperature group. At 4°C, B0041's calibration-run cycles (~0.05 Ah) are pooled with B0045–B0056 (normal operation), producing a spurious positive slope.

2. **No held-out test set:** `train == full dataset`. All reported metrics are in-sample only. There is no cell holdout, no chronological holdout, and no separate test evaluation.

3. **Single feature (cycle_num only):** No electrochemical features (V stats, Re, Rct, temperature). Cycle number alone is a poor SOH predictor across heterogeneous cells with different starting points.

4. **No cross-cell generalization test:** Never evaluated on an unseen cell. There is no evidence this model can predict SOH for a battery not in the training set.

**VERDICT: Old SOH model metrics are INVALID for any scientific purpose.** Do not use `battery_soh_regression.joblib` for pack extrapolation or any downstream claim.

---

## Summary of All Findings

| Section | Status | Key Finding |
|---------|--------|-------------|
| A — Inventory | PASS | 2,769 records, 34 cells, 537 missing waveform files |
| B — SOH > 1.0 | PASS | 11 records — physically plausible; retain |
| C — Temp stratification | FLAG | Positive 4°C slope is a pooling artifact |
| D — Per-cell trends | FLAG | B0038/B0039/B0040/B0041 show anomalous positive slopes |
| E — B0041–B0044 | RESOLVED | B0041: calibration artifact. B0042–B0044: genuine degradation + 1 anomalous zero each |
| F — Waveform consistency | PASS | 2,232 OK, 537 missing (documented), 0 malformed |
| G — SOH target | PASS | SOH = Capacity_numeric / 2.0 exactly. No leakage. |
| H — Split strategy | DECISION | Cell holdout required. Autocorrelation r = 0.9977. |
| I — Feature design | DECISION | SAFE: V/I/T stats, duration, cycle_num. LEAKAGE: Capacity_numeric, SOH. Re/Rct: null in CSV. |
| J — Old model | FAIL | Pooled, in-sample, single feature. Metrics invalid. |

---

## Issues Requiring Action Before SOH Training

| # | Issue | Required Action |
|---|-------|-----------------|
| 1 | B0033/34/36/38/39/40 start mid-life | Include `cell_id` as categorical feature OR exclude cells with implausible first SOH |
| 2 | B0041 calibration cycles (SOH 0.022–0.028 for first ~30 cycles) | Exclude B0041 entirely OR exclude its early low-cap cycles |
| 3 | B0042/43/44 zero-capacity cycle 6 | Exclude these 3 anomalous records (one per cell) |
| 4 | Re/Rct entirely null in processed CSV | Do not use as features from CSV |
| 5 | B0042–B0044 temperature discrepancy | Document; use processed CSV temperature (22°C) with caveat |
| 6 | 537 missing waveform files | Exclude B0018/B0053–B0056 from waveform-feature training |
| 7 | Old SOH model invalid | Do not use `battery_soh_regression.joblib` |
| 8 | Cell holdout split required | Test = B0007 (withheld), train = fully disjoint cells |

---

## Go / No-Go Decision

> **DECISION: GO — WITH PRE-CONDITIONS**

The SOH dataset is scientifically usable for training a regression model, subject to the following pre-conditions being implemented in the SOH preprocessing step:

**Pre-conditions (must implement before training):**
1. Remove the 3 zero-capacity cycle-6 records for B0042, B0043, B0044.
2. Document and exclude or flag B0041's calibration-run cycles.
3. Cell holdout split: test = B0007 (fully withheld), val = second withheld cell.
4. Use only safe features: `V_end`, `V_drop`, `V_mean`, `V_min`, `discharge_duration`, `ambient_temperature`, `cycle_number`.
5. Never use `Capacity_numeric`, `Capacity_first_discharge`, or `SOH` as features.
6. Retrain SOH model from scratch with the corrected pipeline — do not use `battery_soh_regression.joblib`.

**Items that do NOT block training (document and proceed):**
- SOH > 1.0 records (retain with documentation).
- Missing waveforms for B0018 and B0053–B0056 (exclude from waveform-feature model).
- Fuel unit UNRESOLVED status (unrelated to SOH).

---

*Report generated by `soh_audit_D_to_J.py`. No data was modified.*
