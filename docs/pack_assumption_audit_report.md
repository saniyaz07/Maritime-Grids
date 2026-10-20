# Pack Assumption Audit Report

**Project:** Maritime Grid Battery Modelling
**Date:** 2026-09-27
**Stage:** Pre-Pack-Extrapolation Audit (Read-Only)
**Auditor:** pack_audit_fast.py — 20 files inspected

> [!IMPORTANT]
> READ-ONLY AUDIT. No files were modified. No models were retrained. No data was altered.

---

## 1. Executive Summary

The project contains **two co-existing and internally inconsistent pack energy assumptions**:

| Source | Value | Based On |
|--------|-------|----------|
| NASA 18650 cell math (96S250P, 2.0 Ah, 3.6 V) | **172.8 kWh** | Mathematically derived from verified NASA cell data |
| `ship_profiles.csv` — Tanker row | **1,200 kWh** | Engineering default, 800 V nominal bus, unexplained cell format |

The discrepancy arises because the Tanker profile uses a **800 V nominal bus** (not 345.6 V), and the 1,200 kWh assumption implies cells of approximately **13.89 Ah** equivalent capacity — not the NASA 2.0 Ah 18650 cells.

The existing `phase2_pipeline.py` already explicitly acknowledges this discrepancy in a comment (line 760):
> *"The ship_profiles.csv lists 1,200 kWh which assumes higher cell format or different architecture — documented discrepancy between cell-level NASA data and assumed pack spec is noted explicitly."*

All four frozen models operate at **cell level** and are unaffected by this discrepancy. The inconsistency only manifests at the pack aggregation layer, which does not yet exist in production code.

---

## 2. Pack Assumption Table

| Parameter | Current Project Value | NASA/Derived Value | Source | Classification | Status |
|-----------|----------------------|-------------------|--------|---------------|--------|
| Series cells (S) | 96 | — | `ship_profiles.csv`, `phase2_pipeline.py` | **D — Hardcoded project assumption** | Consistent across all files |
| Parallel cells (P) | 250 (Tanker) | — | `ship_profiles.csv`, `phase2_pipeline.py` | **D — Hardcoded project assumption** | Consistent across all files |
| Cell nominal voltage | 3.6 V | 3.6 V | NASA 18650 specification | **A — Verified from NASA data** | Consistent |
| Cell nominal capacity | 2.0 Ah | 2.0 Ah | NASA discharge data (SOH denominator) | **A — Verified from NASA data** | Consistent |
| Pack nominal voltage (derived) | 345.6 V | 345.6 V | 96 × 3.6 V | **B — Derived mathematically** | Consistent in pipeline code |
| Pack nominal voltage (ship profile — Tanker) | **800 V** | 345.6 V | `ship_profiles.csv` line 5 | **C — Explicit engineering assumption** | **INCONSISTENT with 96 × 3.6 V = 345.6 V** |
| Pack nominal capacity (derived) | 500 Ah | 500 Ah | 250 × 2.0 Ah | **B — Derived mathematically** | Consistent in pipeline code |
| Pack nominal energy (NASA-cell-derived) | 172.8 kWh | 172.8 kWh | 345.6 V × 500 Ah / 1000 | **B — Derived mathematically** | In pipeline code, labelled as cell-level estimate |
| Pack nominal energy (ship profile — Tanker) | **1,200 kWh** | 172.8 kWh | `ship_profiles.csv` line 5 | **C — Explicit engineering assumption** | **INCONSISTENT with 2.0 Ah / 3.6 V cells** |

---

## 3. 96S250P Occurrences

| File | Line | Content | Used For | Affects Computation |
|------|------|---------|----------|-------------------|
| `data/reference/ship_profiles.csv` | 5 | `96S250P` in `battery_cell_config` column — Tanker row | Documentation / ship profile lookup | Yes — read by pipeline for Tanker config |
| `phase2_pipeline.py` | 755 | `Pack configuration example (Tanker Ship): 96S250P` | Comment/documentation | No (comment) |
| `phase2_pipeline.py` | 786 | `print(f"  Pack config: {S_COUNT}S{P_COUNT}P (ASSUMPTION)")` | Console output | No (print only) |
| `docs/phase0_data_acquisition.md` | 133 | `96S250P` in ship profile table | Documentation | No |

Also: all four ship types use 96S topology (96S120P, 96S50P, 96S30P, 96S250P) — 96 series cells is a consistent engineering assumption across all vessel profiles.

---

## 4. 1,200 kWh Occurrences

| File | Line | Content | Source Type | Purpose |
|------|------|---------|------------|---------|
| `data/reference/ship_profiles.csv` | 5 | `battery_pack_capacity_kwh = 1200` — Tanker row | **Primary origin** — engineering default entered directly into CSV | Provides pack energy figure for Tanker ship type |
| `docs/phase0_data_acquisition.md` | 134 | `1,200 kWh` — Tanker battery pack size | Documentation | Explanatory — justification: "Sized for peak shaving, spinning reserve, and zero-emission port maneuvering" |
| `phase2_pipeline.py` | 760 | `(The ship_profiles.csv lists 1,200 kWh which assumes higher cell format...)` | Comment noting the discrepancy | No computation — explicit warning |
| `phase2_pipeline.py` | 790 | `print(f"  Note: ship_profiles.csv states 1,200 kWh — discrepancy from cell format difference")` | Console warning | No computation |

**Origin classification:** The 1,200 kWh figure is a **directly hardcoded engineering default** in `ship_profiles.csv`, entered as a representative Tanker battery capacity sized for operational requirements (peak shaving, zero-emission maneuvering). It is **not derived from the NASA cell data** and is not calculated from the 96S250P topology with 2.0 Ah cells.

The `ship_profiles.csv` Tanker row also specifies `nominal_voltage_v = 800` — this is the intended bus voltage. To achieve 800 V with 3.6 V cells: 800 / 3.6 ≈ 222 series cells, not 96. The 96S topology at 800 V bus is also internally inconsistent within `ship_profiles.csv` itself.

---

## 5. 2.0 Ah Occurrences

| File | Line | Content | Classification |
|------|------|---------|---------------|
| `stage2c_soh_training.py` | ~11 | `NOMINAL_CAP = 2.0` | **A — NASA-verified** — SOH denominator |
| `stage2c_soc_preprocessing.py` | ~varies | `Q_discharged / 2.0` in SOC formula | **A — NASA-verified** — SOC denominator |
| `phase2_pipeline.py` | 757 | `250 × 2.0 Ah ≈ 500 Ah` | **A — NASA-verified** — pack capacity derivation |
| `phase2_pipeline.py` | 772 | `"cell_nominal_ah": 2.0` in `PACK_CONFIG` | **A — NASA-verified** — configuration constant |
| `docs/model_c_soh_audit_report.md` | multiple | `SOH = Capacity_numeric / 2.0` | **A — NASA-verified** — target definition |
| `docs/model_c_soh_training_report.md` | multiple | `SOH = Capacity_numeric / 2.0 Ah` | **A — NASA-verified** — target definition |

All `2.0 Ah` usages refer to the NASA 18650 cell nominal capacity and are used as the fixed SOH/SOC denominator. This value is consistent across all files.

---

## 6. 3.6 V Occurrences

| File | Line | Content | Classification |
|------|------|---------|---------------|
| `phase2_pipeline.py` | 756 | `96 × 3.6V ≈ 345.6V (nominal 400V bus)` | **A — NASA-verified** — cell nominal voltage |
| `phase2_pipeline.py` | 773 | `"cell_nominal_v": 3.6` in `PACK_CONFIG` | **A — NASA-verified** — configuration constant |
| `phase2_pipeline.py` | 782 | `pack_voltage_v = S_COUNT * CELL_V  # 345.6 V` | **B — Derived mathematically** |
| `docs/phase2_metrics.json` | 70 | `"pack_voltage_v": 345.6` | **B — Derived mathematically** |

The 3.6 V nominal cell voltage is consistently used in the pipeline. However, `ship_profiles.csv` Tanker row specifies `nominal_voltage_v = 800` V — a different figure entirely.

---

## 7. Existing Pack Calculations

All existing pack calculations reside exclusively in `phase2_pipeline.py` (lines 750–844) and the resulting stored values in `docs/phase2_metrics.json`.

### In `phase2_pipeline.py`

```
PACK_CONFIG = {series: 96, parallel: 250, cell_nominal_ah: 2.0, cell_nominal_v: 3.6}

pack_voltage_v   = 96 × 3.6        = 345.6 V
pack_capacity_ah = 250 × 2.0       = 500 Ah
pack_energy_kwh  = 345.6 × 500 / 1000 = 172.8 kWh  [labelled "cell-level estimate"]

predict_pack_soh(cycle_n):
    # Uses old pooled LinearRegression (soh_24_model from old pipeline)
    # SOH is scale-invariant — pack SOH = cell SOH (uniform cell assumption)

predict_pack_soc_end(current_a, duration_s, initial_soc, nominal_ah):
    # Simple coulomb-counting: SOC_end = initial_soc - (I×t/3600) / nominal_ah
    # Uses pack_capacity_ah = 500 Ah (from NASA-cell-derived value)
    # Does NOT use the 1,200 kWh figure

pack_energy_remaining = pack_energy_kwh × pack_soh_150
    # = 172.8 × soh_value  (uses 172.8 kWh, NOT 1,200 kWh)
```

> [!WARNING]
> The `predict_pack_soh()` function in `phase2_pipeline.py` uses `soh_24_model` — the **old invalid pooled LinearRegression** model that was declared invalid in Section J of the SOH audit. It does NOT use the new `battery_soh_final.joblib`. This function must be replaced before any pack extrapolation is implemented.

### In `docs/phase2_metrics.json` (stored results)

```json
"pack_extrapolation": {
  "status": "ASSUMPTION-BASED — not measured ship data",
  "pack_config": {series: 96, parallel: 250, cell_nominal_ah: 2.0, cell_nominal_v: 3.6},
  "pack_voltage_v": 345.6,
  "pack_capacity_ah": 500.0,
  "pack_energy_kwh_cell_estimate": 172.8,
  "example_pack_energy_remaining_kwh": 121.7
}
```

These stored values use the **172.8 kWh NASA-derived figure**, not the 1,200 kWh ship_profiles figure.

### In `docs/phase3_output_contract.json`

```json
"predicted_SOH": "models/battery_soh_regression.joblib + pack scaling"
"notes": "predicted_SOH and predicted_SOC_end_of_voyage use pack-level assumption (96S250P)"
```

This references `battery_soh_regression.joblib` — the **old invalid model**. The contract is stale and must be updated to reference `battery_soh_final.joblib`.

---

## 8. Model Impact

| Model | Pack Assumptions Used | Training Level | Changing Pack Assumptions Affects Model | Retraining Required |
|-------|-----------------------|---------------|----------------------------------------|---------------------|
| `weather_final.joblib` | **None** | Ship voyage level (weather features) | No | No |
| `fuel_xgb.joblib` | **None** | Ship voyage level (fuel/speed/route features) | No | No |
| `battery_soc_lstm.pt` | **None** | Cell level (V, I, T waveform sequences) | No — SOC is a normalized ratio | No |
| `battery_soh_final.joblib` | **None** | Cell level (V stats, duration, cycle_num) | No — SOH is a normalized ratio [0,1] | No |

**All four frozen models operate entirely at cell level.** None of them use pack voltage, pack energy (kWh), series count, parallel count, or any pack-level quantity as an input or output.

Pack assumptions only enter **downstream of the models** — in the aggregation layer that converts cell-level SOH/SOC predictions into pack-level energy figures. This aggregation layer does not currently exist in production form; the only implementation is the illustrative code in `phase2_pipeline.py` (lines 792–830), which itself uses the old invalid SOH model.

---

## 9. Data-vs-Assumption Classification

| Value | Classification | Basis |
|-------|---------------|-------|
| Cell nominal capacity = 2.0 Ah | **A — NASA-verified** | NASA 18650 cell; SOH denominator confirmed from discharge data |
| Cell nominal voltage = 3.6 V | **A — NASA-verified** | Standard 18650 Li-ion nominal; used in NASA dataset context |
| SOH = Capacity / 2.0 | **B — Derived from A** | Mathematical, verified in SOH target audit |
| Pack voltage = 345.6 V | **B — Derived from A** | 96 × 3.6 V |
| Pack capacity = 500 Ah | **B — Derived from A** | 250 × 2.0 Ah |
| Pack energy = 172.8 kWh | **B — Derived from A** | 345.6 × 500 / 1000 |
| 96S250P topology | **C — Engineering assumption** | Selected for Tanker profile; not from NASA data |
| 1,200 kWh (Tanker) | **D — Hardcoded legacy assumption** | Entered directly in `ship_profiles.csv`; justified operationally in `phase0_data_acquisition.md` as "sized for peak shaving and zero-emission port maneuvering" |
| 800 V nominal bus (Tanker) | **C — Engineering assumption** | Entered in `ship_profiles.csv`; inconsistent with 96 × 3.6 = 345.6 V |
| 13.89 Ah required cell (1200 kWh / 96S250P / 3.6 V) | **E — Unknown/unverified** | Mathematical consequence of the 1,200 kWh + 96S250P + 3.6 V combination; no physical cell of this spec referenced anywhere in the project |

---

## 10. Dependency / Impact Map

```
NASA 18650 cell data (B0005-B0056, 2.0 Ah, 3.6 V nominal)
      |
      v
  [Cell-level preprocessing]
  - SOC: clip(1 - Q_discharged / 2.0 Ah, 0, 1)       <-- 2.0 Ah enters here (A)
  - SOH: Capacity_numeric / 2.0                         <-- 2.0 Ah enters here (A)
      |
      v
  [Cell-level models — FROZEN]
  - battery_soc_lstm.pt     : predicts cell SOC (fraction)
  - battery_soh_final.joblib: predicts cell SOH (fraction)
  - weather_final.joblib    : voyage weather (no battery input)
  - fuel_xgb.joblib         : voyage fuel (no battery input)
      |
      v
  [Pack aggregation — NOT YET IN PRODUCTION]              <== DECISION POINT
  - pack_voltage   = S × V_cell  = 96 × 3.6 = 345.6 V   (B)
  - pack_capacity  = P × C_cell  = 250 × 2.0 = 500 Ah   (B)
  - pack_energy    = V × C / 1000 = 172.8 kWh            (B)
        OR
  - pack_energy    = 1,200 kWh   [from ship_profiles.csv] (D)  <== INCONSISTENCY ENTERS HERE
      |
      v
  [Pack outputs]
  - pack_energy_remaining = pack_energy × SOH_cell
  - pack_soc_end_voyage   = coulomb counting with pack_capacity_ah
      |
      v
  [Simulation / reporting outputs]
  - Route energy balance
  - Voyage-level battery state
```

The 1,200 kWh assumption enters **only at the pack aggregation layer**, which does not yet exist in production. All cell-level models and all model artifacts are unaffected.

---

## 11. Risks / Inconsistencies

| # | Inconsistency | Files Affected | Severity |
|---|--------------|----------------|---------|
| 1 | `ship_profiles.csv` Tanker: `battery_pack_capacity_kwh = 1200` but `battery_cell_config = 96S250P` with `cell_nominal_ah = 2.0 Ah` → mathematically yields 172.8 kWh, not 1,200 kWh | `ship_profiles.csv`, `phase2_pipeline.py`, `docs/phase0_data_acquisition.md` | **HIGH** — the single largest inconsistency |
| 2 | `ship_profiles.csv` Tanker: `nominal_voltage_v = 800` but 96 × 3.6 V = 345.6 V (not 800 V). To achieve 800 V requires 222 series cells, not 96 | `ship_profiles.csv` | **HIGH** — the 800 V bus and 96S topology are mutually inconsistent |
| 3 | `phase2_pipeline.py` uses old `soh_24_model` (invalid pooled LinearRegression) for `predict_pack_soh()`. New `battery_soh_final.joblib` exists but is not used | `phase2_pipeline.py` | **HIGH** — any pack SOH output from existing pipeline is invalid |
| 4 | `docs/phase3_output_contract.json` references `battery_soh_regression.joblib` (old invalid model) | `docs/phase3_output_contract.json` | **MEDIUM** — stale contract; does not affect production yet |
| 5 | Other ship types (OSV: 96S120P → 650 kWh, Trawler: 96S50P → 250 kWh, Surfer: 96S30P → 150 kWh) also have internal inconsistencies between their cell configs and stated pack energies, but these are less extreme than the Tanker | `ship_profiles.csv` | **LOW-MEDIUM** — all ship profiles have the same category of inconsistency |
| 6 | No location in the project uses 96S250P + 2.0 Ah + 3.6 V and simultaneously claims 1,200 kWh without noting the discrepancy. The pipeline code explicitly notes the inconsistency but does not resolve it | — | **LOW** — discrepancy is documented, not silently propagated |

---

## 12. Recommended Authoritative Configuration (Not Implemented)

A future single authoritative configuration file should contain:

```python
# battery_pack_config.py  (proposed — do not create yet)

# Physical cell (from NASA data)
CELL_NOMINAL_VOLTAGE_V    = 3.6      # A — NASA-verified
CELL_NOMINAL_CAPACITY_AH  = 2.0      # A — NASA-verified

# Pack topology (engineering assumption — choose one option)
PACK_SERIES               = 96       # C — engineering assumption
PACK_PARALLEL             = 250      # C — engineering assumption (Tanker)

# Derived pack quantities (from cell × topology)
PACK_NOMINAL_VOLTAGE_V    = PACK_SERIES × CELL_NOMINAL_VOLTAGE_V   # = 345.6 V
PACK_NOMINAL_CAPACITY_AH  = PACK_PARALLEL × CELL_NOMINAL_CAPACITY_AH  # = 500 Ah
PACK_NOMINAL_ENERGY_KWH   = PACK_NOMINAL_VOLTAGE_V × PACK_NOMINAL_CAPACITY_AH / 1000  # = 172.8 kWh

# OR if Option B is chosen:
PACK_NOMINAL_ENERGY_KWH   = 1200.0   # D — override (requires justification of cell format)
PACK_ENERGY_BASIS         = "commercial_assumption"  # or "nasa_cell_derived"

# Scale factor (only applicable if Option B chosen)
PACK_SCALE_FACTOR         = 1200.0 / 172.8  # = 6.944  (if used — must be explicitly justified)

# SOH/SOC model level
MODEL_LEVEL               = "cell"   # SOH and SOC models operate at cell level
# Pack outputs are: cell_SOH × PACK_NOMINAL_ENERGY_KWH
```

The value of `PACK_NOMINAL_ENERGY_KWH` and whether `PACK_SCALE_FACTOR` is used must be explicitly decided before implementation.

---

## 13. Decision Required Before Implementation

> [!IMPORTANT]
> **Pack extrapolation must not be implemented until the authoritative pack-capacity assumption is explicitly selected.**

---

### OPTION A — NASA-cell-derived engineering pack

```
Pack topology  : 96S250P
Cell voltage   : 3.6 V  (NASA 18650, verified)
Cell capacity  : 2.0 Ah (NASA 18650, verified)
Pack voltage   : 345.6 V (derived)
Pack capacity  : 500 Ah  (derived)
Pack energy    : 172.8 kWh (derived)
Nominal bus    : ~345.6 V (or stepped up — requires clarification)
```

- Internally consistent with all NASA data and all cell-level models.
- Requires revising the 1,200 kWh figure in `ship_profiles.csv` and documentation.
- Accurately represents what a 96S250P pack of 2.0 Ah 18650 cells physically delivers.
- **172.8 kWh is a small pack for a 7,200 kW main engine tanker** — operationally appropriate only for peak shaving and port maneuvering (not full propulsion), consistent with the operational description in `phase0_data_acquisition.md`.

---

### OPTION B — Commercial-scale 1,200 kWh pack

```
Pack topology  : 96S250P  (or revised topology)
Cell voltage   : 3.6 V  (assumed)
Cell capacity  : ~13.89 Ah (required — not in NASA dataset)
Pack voltage   : 345.6 V (or 800 V if topology revised)
Pack capacity  : ~3,472 Ah (or different with revised topology)
Pack energy    : 1,200 kWh
```

- Operationally realistic for a large tanker battery system.
- **Requires cell data not present in the NASA dataset** (13.89 Ah cells ≠ 18650 cells).
- Cell-level SOH and SOC models trained on 2.0 Ah 18650 cells cannot be directly applied to 13.89 Ah pouch cells without additional assumptions.
- If adopted, requires an explicit `PACK_SCALE_FACTOR = 6.944` or a revised cell model, and honest documentation that the cell models are not validated for this cell format.

---

## Final Audit Output

**1. AUDIT STATUS:** PASS

**2. FILES INSPECTED:** 20

**3. RELEVANT OCCURRENCES:**
- 96S250P / series-parallel references: **4**
- 1,200 kWh: **4**
- 2.0 Ah: **6**
- 3.6 V: **4**
- Pack calculations (variables, formulas, outputs): **37+**

**4. FROZEN MODELS CONFIRMED UNMODIFIED:**

| Model | Size | Last Modified |
|-------|------|--------------|
| `weather_final.joblib` | 1,231 B | 2026-09-27 01:52 |
| `fuel_xgb.joblib` | 128,577 B | 2026-09-27 02:03 |
| `battery_soc_lstm.pt` | 208,501 B | 2026-09-27 02:32 |
| `battery_soh_final.joblib` | 376,890 B | 2026-09-27 03:30 |

All four confirmed present and unmodified.

**5. MAIN INCONSISTENCY:**
`ship_profiles.csv` Tanker row simultaneously specifies `96S250P` topology with `2.0 Ah` cells (→ 172.8 kWh derived) AND `battery_pack_capacity_kwh = 1200` AND `nominal_voltage_v = 800`. These three values are mutually inconsistent: 96 × 3.6 V = 345.6 V (not 800 V), and 96S250P with 2.0 Ah cells = 172.8 kWh (not 1,200 kWh).

**6. FILES AFFECTED BY A FUTURE PACK-ASSUMPTION CHANGE:**
- `data/reference/ship_profiles.csv` — primary source of 1,200 kWh and 800 V values
- `phase2_pipeline.py` — contains `PACK_CONFIG`, all pack formulas, `predict_pack_soh()`, `predict_pack_soc_end()`
- `docs/phase2_metrics.json` — stores pack extrapolation results (currently 172.8 kWh basis)
- `docs/phase3_output_contract.json` — references old SOH model; needs update to `battery_soh_final.joblib`
- `docs/phase0_data_acquisition.md` — documents the 1,200 kWh assumption
- `docs/model_c_soh_training_report.md` — may reference pack usage
- Any future pack simulation script

**7. FINAL BLOCKER:**
> **Pack extrapolation must not be implemented until the authoritative pack-capacity assumption is explicitly selected. The choice between Option A (172.8 kWh, NASA-cell-consistent) and Option B (1,200 kWh, operational requirement) determines what downstream calculations, scale factors, and disclaimers are required.**

---

*Audit performed by `pack_audit_fast.py`. Read-only. No files were modified.*
*Mathematical verification: 1,200,000 / (96 × 250 × 3.6) = **13.89 Ah** required cell capacity for Option B.*
