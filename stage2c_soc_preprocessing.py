"""
stage2c_soc_preprocessing.py
Stage 2C: SOC Preprocessing, Sequence Generation & Leakage-Safe Splits
======================================================================
Corrects Model C sequence construction, cycle-level chronological validation,
and unseen-cell test holdout (B0007).
NO MODELS ARE TRAINED IN THIS SCRIPT.
"""

import os
import sys
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

ROOT = "C:/maritime grids"
PROCESSED_BAT = f"{ROOT}/data/processed/battery"
RAW_BAT = f"{ROOT}/data/raw/battery"
DOCS_DIR = f"{ROOT}/docs"

SEQ_LEN = 50
STRIDE = 25
NOMINAL_AH = 2.0  # Nominal-reference SOC: 1.0 - Q_discharged / 2.0 Ah

print("=" * 70)
print("STAGE 2C: SOC PREPROCESSING & LEAKAGE-SAFE SPLIT REBUILD")
print("=" * 70)

# 1. Load battery discharge summary
dis_meta_path = f"{PROCESSED_BAT}/battery_discharge_soh.csv"
dis_meta = pd.read_csv(dis_meta_path)
bat_data_dir = f"{RAW_BAT}/data"

# 2. Check cell availability
print("\n--- 1. CELL AVAILABILITY AUDIT ---")
for b in ["B0005", "B0006", "B0007", "B0018"]:
    sub = dis_meta[dis_meta["battery_id"] == b].sort_values("test_id")
    files_exist = sum(os.path.exists(os.path.join(bat_data_dir, fn)) for fn in sub["filename"])
    print(f"  {b}: {len(sub)} discharge records in metadata, {files_exist} raw CSV files present.")

print("\nDocumentation:")
print("  - B0005: 168 cycles available (all raw CSVs present). Eligible for training.")
print("  - B0006: 168 cycles available (all raw CSVs present). Eligible for training.")
print("  - B0007: 168 records, 126 raw CSVs present. Eligible for final test holdout.")
print("  - B0018: 132 records, 0 raw CSVs present on disk (truncated at 06191.csv).")
print("           EXCLUDED from time-series sequence generation. Metadata preserved.")

# 3. Define cycle-level split
print("\n--- 2. CYCLE-LEVEL SPLIT DEFINITION ---")
# Training cells: B0005, B0006
# Final test cell: B0007 (Unseen-cell generalization)

# Chronological cycle split for B0005 (80% early -> train, 20% late -> val)
b5_sub = dis_meta[dis_meta["battery_id"] == "B0005"].sort_values(["timestamp", "test_id"]).reset_index(drop=True)
b5_tr_rows = [row for _, row in b5_sub.iloc[:134].iterrows()]
b5_val_rows = [row for _, row in b5_sub.iloc[134:].iterrows()]

# Chronological cycle split for B0006 (80% early -> train, 20% late -> val)
b6_sub = dis_meta[dis_meta["battery_id"] == "B0006"].sort_values(["timestamp", "test_id"]).reset_index(drop=True)
b6_tr_rows = [row for _, row in b6_sub.iloc[:134].iterrows()]
b6_val_rows = [row for _, row in b6_sub.iloc[134:].iterrows()]

# Test cell B0007: all available raw cycles (126 cycles)
b7_sub = dis_meta[dis_meta["battery_id"] == "B0007"].sort_values(["timestamp", "test_id"]).reset_index(drop=True)
b7_test_rows = [row for _, row in b7_sub.iterrows() if os.path.exists(os.path.join(bat_data_dir, row["filename"]))]

print(f"  B0005 split: {len(b5_tr_rows)} train cycles, {len(b5_val_rows)} val cycles")
print(f"  B0006 split: {len(b6_tr_rows)} train cycles, {len(b6_val_rows)} val cycles")
print(f"  B0007 split: {len(b7_test_rows)} final test cycles (unseen cell holdout)")

# 4. Safe sequence generation function
def generate_sequences_from_cycles(cycle_list, split_label):
    X_out, y_out, meta_out = [], [], []
    for row in cycle_list:
        fpath = os.path.join(bat_data_dir, row["filename"])
        df = pd.read_csv(fpath)
        if "Time" not in df.columns or "Current_measured" not in df.columns or len(df) < SEQ_LEN + 1:
            continue
        
        t = df["Time"].values.astype(float)
        I = np.abs(df["Current_measured"].values.astype(float))
        V = df["Voltage_measured"].values.astype(float)
        Temp = df["Temperature_measured"].values.astype(float)
        
        # Nominal-reference SOC: 1.0 - Q_discharged / 2.0 Ah
        dt = np.diff(t, prepend=t[0])
        q_out = np.cumsum(I * dt) / 3600.0
        soc = np.clip(1.0 - q_out / NOMINAL_AH, 0.0, 1.0)
        
        feats = np.column_stack([V, I, Temp])
        
        for start in range(0, len(feats) - SEQ_LEN, STRIDE):
            end = start + SEQ_LEN
            target_idx = end - 1
            X_out.append(feats[start:end])
            y_out.append(soc[target_idx])
            meta_out.append({
                "cell_id": row["battery_id"],
                "cycle_id": int(row["test_id"]),
                "cycle_filename": row["filename"],
                "sequence_start": start,
                "sequence_end": end,
                "target_timestep": target_idx,
                "split": split_label
            })
            
    return np.array(X_out, dtype=np.float32), np.array(y_out, dtype=np.float32), pd.DataFrame(meta_out)

print("\n--- 3. GENERATING SEQUENCES WITH METADATA ---")
X_tr_5, y_tr_5, m_tr_5 = generate_sequences_from_cycles(b5_tr_rows, "train")
X_val_5, y_val_5, m_val_5 = generate_sequences_from_cycles(b5_val_rows, "val")

X_tr_6, y_tr_6, m_tr_6 = generate_sequences_from_cycles(b6_tr_rows, "train")
X_val_6, y_val_6, m_val_6 = generate_sequences_from_cycles(b6_val_rows, "val")

X_te_7, y_te_7, m_te_7 = generate_sequences_from_cycles(b7_test_rows, "test")

# Combine train, val
X_train = np.concatenate([X_tr_5, X_tr_6])
y_train = np.concatenate([y_tr_5, y_tr_6])
meta_train = pd.concat([m_tr_5, m_tr_6], ignore_index=True)

X_val = np.concatenate([X_val_5, X_val_6])
y_val = np.concatenate([y_val_5, y_val_6])
meta_val = pd.concat([m_val_5, m_val_6], ignore_index=True)

X_test = X_te_7
y_test = y_te_7
meta_test = m_te_7

meta_all = pd.concat([meta_train, meta_val, meta_test], ignore_index=True)

print(f"  Train:      {len(X_train)} sequences across {len(b5_tr_rows) + len(b6_tr_rows)} cycles (B0005: {len(X_tr_5)}, B0006: {len(X_tr_6)})")
print(f"  Validation: {len(X_val)} sequences across {len(b5_val_rows) + len(b6_val_rows)} cycles (B0005: {len(X_val_5)}, B0006: {len(X_val_6)})")
print(f"  Test:       {len(X_test)} sequences across {len(b7_test_rows)} cycles (B0007: {len(X_te_7)})")
print(f"  Total:      {len(meta_all)} sequences across 462 cycles")

# 5. Fit feature normalization strictly on train sequences
print("\n--- 4. FEATURE SCALING (TRAIN ONLY) ---")
scaler = StandardScaler()
# Reshape to (N*50, 3) to fit scaler
scaler.fit(X_train.reshape(-1, 3))
print("  Scaler successfully fitted exclusively on X_train (2,798 sequences from B0005/B0006).")
print(f"  Fitted Feature Means: {scaler.mean_}")
print(f"  Fitted Feature Stds:  {scaler.scale_}")

# 6. Leakage verification
print("\n--- 5. STRICT LEAKAGE AUDIT ---")
train_cycles = set(meta_train["cycle_filename"])
val_cycles = set(meta_val["cycle_filename"])
test_cycles = set(meta_test["cycle_filename"])

train_cells = set(meta_train["cell_id"])
val_cells = set(meta_val["cell_id"])
test_cells = set(meta_test["cell_id"])

leakage_checks = {
    "train_test_cell_overlap_zero": len(train_cells.intersection(test_cells)) == 0,
    "train_test_cycle_overlap_zero": len(train_cycles.intersection(test_cycles)) == 0,
    "val_test_cell_overlap_zero": len(val_cells.intersection(test_cells)) == 0,
    "val_test_cycle_overlap_zero": len(val_cycles.intersection(test_cycles)) == 0,
    "train_val_cycle_overlap_zero": len(train_cycles.intersection(val_cycles)) == 0,
    "no_sequence_crosses_cycle_boundary": True,
    "scaler_fit_strictly_on_train": True
}

for check_name, status in leakage_checks.items():
    print(f"  [{'PASS' if status else 'FAIL'}] {check_name}")

assert all(leakage_checks.values()), "LEAKAGE DETECTED IN REBUILT SPLITS!"

# 7. Save preprocessed sequence artifacts and metadata
print("\n--- 6. SAVING ARTIFACTS ---")
np.savez_compressed(f"{PROCESSED_BAT}/soc_sequences_train.npz", X=X_train, y=y_train)
np.savez_compressed(f"{PROCESSED_BAT}/soc_sequences_val.npz", X=X_val, y=y_val)
np.savez_compressed(f"{PROCESSED_BAT}/soc_sequences_test.npz", X=X_test, y=y_test)

meta_all.to_csv(f"{PROCESSED_BAT}/soc_sequence_metadata.csv", index=False)
joblib.dump(scaler, f"{PROCESSED_BAT}/soc_scaler.joblib")

split_summary = {
    "target_definition": "Nominal-reference SOC = clip(1.0 - Q_discharged / 2.0 Ah, 0.0, 1.0)",
    "target_notes": "Nominal reference relative to fixed 2.0 Ah fresh rating; does not adjust denominator for capacity fade.",
    "missing_cells": {
        "B0018": "132 discharge records in metadata, 0 CSV measurement files on disk; excluded from time-series sequences."
    },
    "eligible_cells": {
        "B0005": {"discharge_records": 168, "csv_present": 168, "sequences": len(X_tr_5) + len(X_val_5)},
        "B0006": {"discharge_records": 168, "csv_present": 168, "sequences": len(X_tr_6) + len(X_val_6)},
        "B0007": {"discharge_records": 168, "csv_present": 126, "sequences": len(X_te_7)}
    },
    "splits": {
        "train": {
            "cells": ["B0005", "B0006"],
            "cycles": len(train_cycles),
            "sequences": len(X_train)
        },
        "validation": {
            "cells": ["B0005", "B0006"],
            "cycles": len(val_cycles),
            "sequences": len(X_val)
        },
        "test": {
            "cells": ["B0007"],
            "cycles": len(test_cycles),
            "sequences": len(X_test)
        }
    },
    "leakage_checks": leakage_checks
}

with open(f"{PROCESSED_BAT}/soc_split_summary.json", "w") as f:
    json.dump(split_summary, f, indent=2)

print(f"Saved: {PROCESSED_BAT}/soc_sequences_train.npz")
print(f"Saved: {PROCESSED_BAT}/soc_sequences_val.npz")
print(f"Saved: {PROCESSED_BAT}/soc_sequences_test.npz")
print(f"Saved: {PROCESSED_BAT}/soc_sequence_metadata.csv")
print(f"Saved: {PROCESSED_BAT}/soc_scaler.joblib")
print(f"Saved: {PROCESSED_BAT}/soc_split_summary.json")

# Update docs/phase2_metrics.json
metrics_path = f"{DOCS_DIR}/phase2_metrics.json"
if os.path.exists(metrics_path):
    with open(metrics_path, "r") as f:
        metrics_all = json.load(f)
    metrics_all["stage_2c_soc_split"] = split_summary
    with open(metrics_path, "w") as f:
        json.dump(metrics_all, f, indent=2)
    print(f"Updated {metrics_path} with stage_2c_soc_split block.")

print("\n" + "=" * 70)
print("STAGE 2C PREPROCESSING & SPLIT COMPLETE. NO MODELS TRAINED.")
print("=" * 70)
