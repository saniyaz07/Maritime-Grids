"""
SOH Audit — Sections D through J
Read-only. No data modification.
"""

import pandas as pd
import numpy as np
import os
import json
from scipy import stats
import joblib

RAW_DIR = "data/raw/battery/data"
SOH_CSV = "data/processed/battery/battery_discharge_soh.csv"
PIPELINE_PY = "phase2_pipeline.py"
SOH_MODEL = "models/battery_soh_regression.joblib"

df = pd.read_csv(SOH_CSV)
# Assign sequential cycle number per cell (by timestamp)
df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
df = df.sort_values(['battery_id', 'timestamp_dt']).reset_index(drop=True)
df['cycle_num'] = df.groupby('battery_id').cumcount() + 1

print("=" * 80)
print("SECTION D — PER-CELL SOH TRENDS")
print("=" * 80)

results_d = []
for cell, grp in df.groupby('battery_id'):
    grp = grp.sort_values('cycle_num')
    n = len(grp)
    if n < 5:
        continue
    x = grp['cycle_num'].values
    y = grp['SOH'].values
    slope, intercept, r, p, se = stats.linregress(x, y)
    results_d.append({
        'cell_id': cell,
        'temperature': grp['ambient_temperature'].iloc[0],
        'cycles': n,
        'first_soh': round(y[0], 4),
        'last_soh': round(y[-1], 4),
        'slope': round(slope, 6),
        'correlation': round(r, 4),
        'p_value': round(p, 4),
    })

d_df = pd.DataFrame(results_d).sort_values('slope')
print(d_df.to_string(index=False))

strongly_neg = d_df[d_df['slope'] < -0.001]
strongly_pos = d_df[d_df['slope'] > 0.001]
near_zero    = d_df[(d_df['slope'] >= -0.001) & (d_df['slope'] <= 0.001)]

print(f"\nStrongly negative slope (<-0.001): {list(strongly_neg['cell_id'])}")
print(f"Strongly positive slope (>+0.001): {list(strongly_pos['cell_id'])}")
print(f"Near-zero slope:                   {list(near_zero['cell_id'])}")


print("\n" + "=" * 80)
print("SECTION E — B0041–B0044 INVESTIGATION")
print("=" * 80)

for cell in ['B0041', 'B0042', 'B0043', 'B0044']:
    grp = df[df['battery_id'] == cell].sort_values('cycle_num').reset_index(drop=True)
    n = len(grp)
    print(f"\n--- {cell} | temp={grp['ambient_temperature'].iloc[0]}°C | {n} cycles ---")
    print("First 10 discharges:")
    print(grp[['cycle_num', 'filename', 'Capacity_numeric', 'SOH']].head(10).to_string(index=False))
    print("Last 10 discharges:")
    print(grp[['cycle_num', 'filename', 'Capacity_numeric', 'SOH']].tail(10).to_string(index=False))
    mid = n // 2
    first_half = grp.iloc[:mid]
    second_half = grp.iloc[mid:]
    print(f"First-half capacity:  mean={first_half['Capacity_numeric'].mean():.4f} Ah  std={first_half['Capacity_numeric'].std():.4f}")
    print(f"Second-half capacity: mean={second_half['Capacity_numeric'].mean():.4f} Ah  std={second_half['Capacity_numeric'].std():.4f}")
    # Check waveform for first 3 cycles
    for _, row in grp.head(3).iterrows():
        fpath = os.path.join(RAW_DIR, row['filename'])
        if os.path.exists(fpath):
            try:
                wf = pd.read_csv(fpath)
                required = {'Time', 'Voltage_measured', 'Current_measured', 'Temperature_measured'}
                has_cols = required.issubset(set(wf.columns))
                dur = wf['Time'].max() - wf['Time'].min() if 'Time' in wf.columns else float('nan')
                print(f"  WF {row['filename']}: rows={len(wf)}, has_required_cols={has_cols}, time_span={dur:.1f}s, cap={row['Capacity_numeric']:.4f}")
            except Exception as e:
                print(f"  WF {row['filename']}: READ ERROR — {e}")
        else:
            print(f"  WF {row['filename']}: FILE MISSING")


print("\n" + "=" * 80)
print("SECTION F — RAW WAVEFORM / METADATA CONSISTENCY")
print("=" * 80)

REQUIRED_COLS = {'Time', 'Voltage_measured', 'Current_measured', 'Temperature_measured'}
MIN_ROWS = 5

summary = {
    'total': 0, 'missing': 0, 'present': 0,
    'malformed_cols': 0, 'too_short': 0, 'ok': 0,
}
missing_files = []
malformed_files = []
short_files = []

for _, row in df.iterrows():
    summary['total'] += 1
    fpath = os.path.join(RAW_DIR, row['filename'])
    if not os.path.exists(fpath):
        summary['missing'] += 1
        missing_files.append((row['battery_id'], row['filename']))
        continue
    summary['present'] += 1
    try:
        wf = pd.read_csv(fpath)
        if not REQUIRED_COLS.issubset(set(wf.columns)):
            summary['malformed_cols'] += 1
            malformed_files.append((row['battery_id'], row['filename'], list(wf.columns)))
        elif len(wf) < MIN_ROWS:
            summary['too_short'] += 1
            short_files.append((row['battery_id'], row['filename'], len(wf)))
        else:
            summary['ok'] += 1
    except Exception as e:
        summary['malformed_cols'] += 1
        malformed_files.append((row['battery_id'], row['filename'], str(e)))

print("Summary:")
for k, v in summary.items():
    print(f"  {k}: {v}")

# Missing per cell
miss_df = pd.DataFrame(missing_files, columns=['battery_id','filename'])
print("\nMissing files per cell:")
print(miss_df.groupby('battery_id').size().reset_index(name='missing_count').to_string(index=False))

if malformed_files:
    print(f"\nMalformed/wrong-column files ({len(malformed_files)}):")
    for b, fn, cols in malformed_files[:20]:
        print(f"  {b} | {fn} | {cols}")
else:
    print("\nNo malformed files found.")

if short_files:
    print(f"\nToo-short files (<{MIN_ROWS} rows) ({len(short_files)}):")
    for b, fn, nr in short_files[:20]:
        print(f"  {b} | {fn} | {nr} rows")
else:
    print(f"\nNo files with < {MIN_ROWS} rows found.")


print("\n" + "=" * 80)
print("SECTION G — SOH TARGET CONSTRUCTION AUDIT")
print("=" * 80)

NOMINAL = 2.0
df['SOH_recomputed'] = df['Capacity_numeric'] / NOMINAL
df['soh_diff'] = (df['SOH_recomputed'] - df['SOH']).abs()
max_diff = df['soh_diff'].max()
mean_diff = df['soh_diff'].mean()
mismatches = (df['soh_diff'] > 1e-9).sum()
print(f"Max absolute difference (recomputed vs stored SOH): {max_diff:.2e}")
print(f"Mean absolute difference:                          {mean_diff:.2e}")
print(f"Rows with diff > 1e-9:                             {mismatches}")
if mismatches > 0:
    print("Sample mismatching rows:")
    print(df[df['soh_diff'] > 1e-9][['battery_id', 'cycle_num', 'Capacity_numeric', 'SOH', 'SOH_recomputed', 'soh_diff']].head(10).to_string(index=False))

# Check if any SOH col looks derived from timestamps/future data
print(f"\nSOH > 1.0: {(df['SOH'] > 1.0).sum()} records")
print(f"SOH <= 0 : {(df['SOH'] <= 0).sum()} records")
# Verify SOH formula uses only Capacity_numeric / 2.0, not Capacity_first_discharge or other columns
print("\nCapacity_first_discharge unique values (first 5 per cell):")
for cell, grp in df.groupby('battery_id'):
    first5 = grp['Capacity_first_discharge'].head(5).unique()
    print(f"  {cell}: {first5}")
    break  # just show B0005 as representative


print("\n" + "=" * 80)
print("SECTION H — LEAKAGE / SPLIT ANALYSIS")
print("=" * 80)

print("""
Four candidate split strategies evaluated:

1. RANDOM CYCLE SPLIT (across all cells)
   - Randomly assigns individual discharge cycles to train/val/test.
   - VERDICT: INVALID — leakage.
     Reason: Adjacent cycles from the same cell (e.g., cycle 50 in train, cycle 51 in test)
     are strongly autocorrelated (same physical degradation trajectory). The model sees the
     cell at nearly the same SOH level in both train and test, yielding optimistically biased
     metrics. This does NOT test generalization.

2. RANDOM SEQUENCE SPLIT (within each cell)
   - Randomly assigns windows/sequences from a cell to train/val/test.
   - VERDICT: INVALID — leakage.
     Same reason as above but worse: overlapping or adjacent windows from one cell appear in
     both train and test sets.

3. CELL HOLDOUT SPLIT (entirely withheld cells as test)
   - Specific cells are held out: never in train/val, only in test.
   - VERDICT: VALID — the scientifically correct choice.
     Reason: Tests generalization to a genuinely unseen battery. No temporal leakage within
     cells. This is the standard approach in NASA battery literature.
     Implementation: e.g., train on B0005/B0006, test on B0007 (as SOC used).
     For SOH: train on a subset of cells, test on fully withheld cells.

4. CHRONOLOGICAL PER-CELL SPLIT (first N cycles train, last M cycles test, for each cell)
   - Within each cell, earlier cycles form train set, later cycles form test.
   - VERDICT: CONDITIONALLY VALID but INFERIOR to cell holdout for generalization testing.
     Reason: Preserves temporal ordering (avoids cycle-level leakage) but the model still
     trains and tests on the SAME physical cells. Metrics reflect interpolation, not
     extrapolation to new batteries.

RECOMMENDATION: Cell holdout split (Strategy 3).
- For SOH regression: hold out at least one full cell (e.g., B0007 or B0006 group) as test.
- Train cells must be fully disjoint from test cells.
- Within train cells, use chronological ordering to prevent within-cell leakage during
  sequence construction.
- The SOC precedent (unseen B0007) supports this approach.

Note on autocorrelation: SOH values between consecutive cycles of the same cell are
correlated with r typically > 0.99 for early cycles, gradually decorrelating over 100+
cycles. Random splits cannot break this correlation — cell holdout is the only safe option.
""")

# Empirically show autocorrelation for B0005
b5 = df[df['battery_id']=='B0005'].sort_values('cycle_num')['SOH'].values
if len(b5) > 2:
    lag1_r = np.corrcoef(b5[:-1], b5[1:])[0,1]
    print(f"B0005 lag-1 autocorrelation of SOH: r = {lag1_r:.4f}")


print("\n" + "=" * 80)
print("SECTION I — FEATURE DESIGN AUDIT")
print("=" * 80)

print("""
Feature                         | Classification  | Justification
--------------------------------|-----------------|------------------------------------------------
voltage_at_end_of_discharge     | SAFE            | Measured directly from the discharge waveform
voltage_drop (V_start - V_end)  | SAFE            | Fully within the discharge window
mean_voltage_during_discharge   | SAFE            | Aggregate of within-window measurements
min_voltage_during_discharge    | SAFE            | Fully within the discharge window
current_profile stats           | SAFE            | Measured during discharge
discharge_duration              | SAFE            | Fully within the discharge window
ambient_temperature             | SAFE            | Known at start of cycle; cell-level metadata
cycle_number (absolute)         | SAFE (label)    | Sequential counter; encodes degradation state
                                |                 | but is a legitimate feature for SOH tracking
Re (electrolyte resistance)     | CONDITIONAL     | Measured during impedance cycles, NOT during
                                |                 | discharge. Must confirm Re is measured BEFORE
                                |                 | the corresponding discharge cycle (not after).
                                |                 | Many NASA files: Re measured in EIS step
                                |                 | preceding discharge — usually safe.
Rct (charge transfer resist.)   | CONDITIONAL     | Same concern as Re. EIS is typically pre-
                                |                 | discharge; verify ordering in raw files.
Capacity_numeric (raw)          | LEAKAGE         | This IS the target (SOH = Cap / 2.0). Must
                                |                 | NEVER be used as a feature — direct leakage.
Capacity_first_discharge        | LEAKAGE         | Derived from Capacity_numeric. Must never be
                                |                 | used as a feature.
SOH (stored column)             | LEAKAGE         | This is the target label. Never a feature.
Future cycle statistics          | LEAKAGE         | Any aggregate computed across the full life
                                |                 | (e.g., end-of-life capacity) must not be used.
B0041–B0044 low-cap cycles      | CONDITIONAL     | Anomalous calibration cycles (cutoff voltage
                                |                 | experiments). If included, require a flag
                                |                 | feature or cell-level grouping; otherwise
                                |                 | they introduce distributional noise.

SUMMARY:
  SAFE features available:      voltage/current/temperature stats, duration, cycle_num, ambient_temp
  CONDITIONAL (verify ordering): Re, Rct (impedance measurements)
  LEAKAGE — never use:          Capacity_numeric, Capacity_first_discharge, SOH itself
  UNAVAILABLE (missing waveforms): B0018 (all), B0053–B0056 (all), B0007 (42 cycles)
""")

# Check if Re/Rct are present in the SOH dataframe
print(f"Re column non-null count in SOH CSV: {df['Re'].notna().sum()} / {len(df)}")
print(f"Rct column non-null count in SOH CSV: {df['Rct'].notna().sum()} / {len(df)}")


print("\n" + "=" * 80)
print("SECTION J — OLD SOH MODEL AUDIT")
print("=" * 80)

# Check if old model file exists
if os.path.exists(SOH_MODEL):
    print(f"File exists: {SOH_MODEL}")
    try:
        old_model = joblib.load(SOH_MODEL)
        print(f"Model type: {type(old_model)}")
        if hasattr(old_model, 'coef_'):
            print(f"Coefficients: {old_model.coef_}")
            print(f"Intercept:    {old_model.intercept_}")
    except Exception as e:
        print(f"Could not load model: {e}")
else:
    print(f"File NOT found: {SOH_MODEL}")

# Read the relevant lines from phase2_pipeline.py
print("\n--- Inspecting phase2_pipeline.py SOH regression code ---")
try:
    with open(PIPELINE_PY, 'r') as f:
        lines = f.readlines()
    # Show lines 660-710
    for i, line in enumerate(lines[660:720], start=661):
        print(f"{i}: {line}", end='')
except Exception as e:
    print(f"Could not read {PIPELINE_PY}: {e}")

print("\n\n--- OLD MODEL VALIDITY ASSESSMENT ---")
print("""
The old SOH code in phase2_pipeline.py performs:
  for temp in [4, 24, 43, 44]:
      subset = df[df['ambient_temperature'] == temp]
      LinearRegression(cycle_num → SOH)
      model.fit(subset[['cycle_num']], subset['SOH'])

Critical defects:

1. POOLED REGRESSION — INVALID:
   Multiple heterogeneous cells are pooled per temperature group.
   At 4°C this mixes B0041–B0044 (cutoff voltage experiments with
   tiny calibration-run capacities) with B0045–B0056 (normal operation).
   The pooled regression fits a spurious positive slope at 4°C.

2. NO HELD-OUT TEST SET:
   train == full dataset. There is no cell holdout, no chronological
   holdout, and no separate test evaluation. All reported metrics are
   IN-SAMPLE. They do not measure generalization.

3. FEATURE = CYCLE NUMBER ONLY:
   Ignores all electrochemical features (voltage, Re, Rct). Cycle number
   alone is a poor SOH predictor across heterogeneous cells.

4. NO CROSS-CELL GENERALIZATION TEST:
   The model is never evaluated on an unseen cell, so there is no
   evidence that it can predict SOH for a battery not in the training set.

VERDICT: Old SOH model metrics are INVALID for any scientific purpose.
The model must be retrained with:
  - Cell holdout split (at minimum one cell fully withheld as test)
  - Electrochemical features (not cycle_num alone)
  - Per-cell evaluation reported separately (not pooled)
""")

print("=" * 80)
print("SECTIONS D–J COMPLETE")
print("=" * 80)
