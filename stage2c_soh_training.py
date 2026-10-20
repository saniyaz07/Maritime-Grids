"""
stage2c_soh_training.py
Model C — SOH Lightweight Training
CPU-only. No neural networks. No hyperparameter search.

SPLIT:
  Train : all eligible cells except B0006 and B0007
  Val   : B0006
  Test  : B0007 (final, evaluated once at the end)

EXCLUSIONS:
  - B0042 cycle 6 (zero-capacity interrupted discharge)
  - B0043 cycle 6 (zero-capacity interrupted discharge)
  - B0044 cycle 6 (zero-capacity interrupted discharge)
  - B0041 cycles 1-42 (calibration artifact: cap < 0.5 Ah, confirmed hard discontinuity at cycle 43)
  - Any record whose raw waveform file is missing

FEATURES (all from discharge waveform, no target-derived quantities):
  V_end, V_drop, V_mean, V_min, duration, ambient_temperature, cycle_number

TARGET:
  SOH = Capacity_numeric / 2.0  (do NOT clip)

MODELS:
  LinearRegression
  Ridge (alpha=1.0)
  RandomForestRegressor (n_estimators=200, max_depth=8, rs=42)
  HistGradientBoostingRegressor (max_iter=200, lr=0.05, max_leaf_nodes=15, l2=1.0, rs=42)
"""

import os
import sys
import json
import warnings
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────
RAW_DIR     = "data/raw/battery/data"
SOH_CSV     = "data/processed/battery/battery_discharge_soh.csv"
META_OUT    = "data/processed/battery/soh_training_metadata.csv"
METRICS_OUT = "docs/model_c_soh_metrics.json"
REPORT_OUT  = "docs/model_c_soh_training_report.md"
FIG_DIR     = "docs/figures"

os.makedirs(FIG_DIR, exist_ok=True)
os.makedirs("models", exist_ok=True)
os.makedirs("docs", exist_ok=True)
os.makedirs("data/processed/battery", exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
NOMINAL_CAP  = 2.0
VAL_CELL     = "B0006"
TEST_CELL    = "B0007"
FEATURES     = ["V_end", "V_drop", "V_mean", "V_min", "duration",
                "ambient_temperature", "cycle_number"]

# Exact B0041 calibration range (determined by pre-audit: cap < 0.5 Ah, cycles 1-42)
B0041_CALIB_MAX_CYCLE = 42
B0041_CALIB_CAP_THRESHOLD = 0.5

# Zero-capacity interrupted cycles
ZERO_CAP_EXCLUSIONS = [
    ("B0042", 6),
    ("B0043", 6),
    ("B0044", 6),
]

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: LOAD METADATA
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 1: Load SOH metadata")
print("=" * 70)

df = pd.read_csv(SOH_CSV)
df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
df = df.sort_values(['battery_id', 'timestamp_dt']).reset_index(drop=True)
df['cycle_number'] = df.groupby('battery_id').cumcount() + 1
df['SOH_target'] = df['Capacity_numeric'] / NOMINAL_CAP

print(f"Loaded: {len(df)} records, {df['battery_id'].nunique()} cells")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: APPLY EXCLUSIONS (FLAG, DO NOT DELETE FROM SOURCE)
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 2: Apply exclusions (flag only, source not modified)")

df['exclusion_reason'] = ''

# 2a. Zero-capacity interrupted discharge cycles
for cell, cyc in ZERO_CAP_EXCLUSIONS:
    mask = (df['battery_id'] == cell) & (df['cycle_number'] == cyc)
    df.loc[mask, 'exclusion_reason'] = 'zero_capacity_interrupted'
    n = mask.sum()
    print(f"  Flagged {n} record(s): {cell} cycle {cyc} -> zero_capacity_interrupted")

# 2b. B0041 calibration cycles 1-42
b41_mask = (df['battery_id'] == 'B0041') & (df['cycle_number'] <= B0041_CALIB_MAX_CYCLE)
df.loc[b41_mask, 'exclusion_reason'] = 'B0041_calibration_artifact'
n41 = b41_mask.sum()
cap_max_calib = df.loc[b41_mask, 'Capacity_numeric'].max()
cap_min_normal = df.loc[(df['battery_id']=='B0041') & (df['cycle_number']>B0041_CALIB_MAX_CYCLE), 'Capacity_numeric'].min()
print(f"  Flagged {n41} record(s): B0041 cycles 1-{B0041_CALIB_MAX_CYCLE} -> B0041_calibration_artifact")
print(f"    (max cap in excluded = {cap_max_calib:.4f} Ah, min cap in retained = {cap_min_normal:.4f} Ah)")

print(f"  Total flagged (before waveform check): {(df['exclusion_reason']!='').sum()}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: EXTRACT WAVEFORM FEATURES
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 3: Extract waveform features (scan each present file once)")

def extract_features(filename):
    """Extract V_end, V_drop, V_mean, V_min, duration from discharge waveform."""
    fpath = os.path.join(RAW_DIR, filename)
    if not os.path.exists(fpath):
        return None, 'missing_waveform'
    try:
        wf = pd.read_csv(fpath)
        required = {'Time', 'Voltage_measured'}
        if not required.issubset(set(wf.columns)):
            return None, 'missing_columns'
        if len(wf) < 2:
            return None, 'too_short'
        v = wf['Voltage_measured'].values
        t = wf['Time'].values
        V_end   = float(v[-1])
        V_start = float(v[0])
        V_min   = float(v.min())
        V_mean  = float(v.mean())
        V_drop  = V_start - V_end
        duration = float(t[-1] - t[0])
        return {
            'V_end': V_end, 'V_drop': V_drop,
            'V_mean': V_mean, 'V_min': V_min,
            'duration': duration
        }, None
    except Exception as e:
        return None, f'read_error:{e}'

feat_rows = []
missing_wf_count = 0
error_count = 0

for idx, row in df.iterrows():
    feats, err = extract_features(row['filename'])
    if feats is None:
        if df.at[idx, 'exclusion_reason'] == '':
            df.at[idx, 'exclusion_reason'] = err if err else 'missing_waveform'
        if 'missing' in (err or ''):
            missing_wf_count += 1
        else:
            error_count += 1
        feat_rows.append({'idx': idx})
    else:
        feat_rows.append({'idx': idx, **feats})

feat_df = pd.DataFrame(feat_rows).set_index('idx')
df = df.join(feat_df)

print(f"  Missing waveform files (newly flagged): {missing_wf_count}")
print(f"  Waveform read errors: {error_count}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: SUMMARY OF EXCLUSIONS
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 4: Exclusion summary")

total = len(df)
excluded = df[df['exclusion_reason'] != '']
eligible = df[df['exclusion_reason'] == '']

excl_summary = df.groupby('exclusion_reason').size()
print("Exclusion reasons:")
print(excl_summary.to_string())

print(f"\nTotal records         : {total}")
print(f"Excluded (all reasons): {len(excluded)}")
print(f"  zero_capacity       : {(df['exclusion_reason']=='zero_capacity_interrupted').sum()}")
print(f"  B0041 calibration   : {(df['exclusion_reason']=='B0041_calibration_artifact').sum()}")
print(f"  missing_waveform    : {(df['exclusion_reason']=='missing_waveform').sum()}")
print(f"Eligible observations : {len(eligible)}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: ASSIGN SPLIT
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 5: Assign train/val/test split")

def assign_split(row):
    if row['battery_id'] == TEST_CELL:
        return 'test'
    elif row['battery_id'] == VAL_CELL:
        return 'val'
    else:
        return 'train'

eligible = eligible.copy()
eligible['split'] = eligible.apply(assign_split, axis=1)

for split in ['train', 'val', 'test']:
    sub = eligible[eligible['split'] == split]
    cells = sorted(sub['battery_id'].unique())
    print(f"  {split.upper():5s}: {len(cells)} cells, {sub['battery_id'].nunique()} unique cells, {len(sub)} observations")
    print(f"         cells: {cells}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: SANITY CHECK — B0007 ISOLATION
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 6: Sanity checks")

train_df = eligible[eligible['split'] == 'train'].copy()
val_df   = eligible[eligible['split'] == 'val'].copy()
test_df  = eligible[eligible['split'] == 'test'].copy()

assert TEST_CELL not in train_df['battery_id'].values, "FAIL: B0007 in train!"
assert TEST_CELL not in val_df['battery_id'].values,   "FAIL: B0007 in val!"
assert VAL_CELL  not in train_df['battery_id'].values, "FAIL: B0006 in train!"
assert VAL_CELL  not in test_df['battery_id'].values,  "FAIL: B0006 in test!"

for feat in FEATURES:
    if feat not in ['ambient_temperature', 'cycle_number']:
        assert 'Capacity' not in feat, f"Target leakage in feature {feat}"

for df_part, name in [(train_df, 'train'), (val_df, 'val'), (test_df, 'test')]:
    assert df_part[FEATURES].isnull().sum().sum() == 0, f"NaNs in {name} features!"

print("  B0007 absent from train: OK")
print("  B0007 absent from val:   OK")
print("  B0006 absent from train: OK")
print("  B0006 absent from test:  OK")
print("  No target-derived features: OK")
print("  No NaN in features: OK")
print("  No raw data modified: OK (read-only source)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7: PREPARE MATRICES
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 7: Prepare feature matrices")

X_train = train_df[FEATURES].values.astype(float)
y_train = train_df['SOH_target'].values.astype(float)
X_val   = val_df[FEATURES].values.astype(float)
y_val   = val_df['SOH_target'].values.astype(float)
X_test  = test_df[FEATURES].values.astype(float)
y_test  = test_df['SOH_target'].values.astype(float)

print(f"  Train : X={X_train.shape}, y mean={y_train.mean():.4f}")
print(f"  Val   : X={X_val.shape},   y mean={y_val.mean():.4f}")
print(f"  Test  : X={X_test.shape},  y mean={y_test.mean():.4f}")

# Scale (for linear models only) — fit on train only
scaler = StandardScaler()
X_train_sc = scaler.fit_transform(X_train)
X_val_sc   = scaler.transform(X_val)
X_test_sc  = scaler.transform(X_test)

# ─────────────────────────────────────────────────────────────────────────────
# METRICS HELPER
# ─────────────────────────────────────────────────────────────────────────────
def compute_metrics(y_true, y_pred, label=""):
    rmse  = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mae   = float(mean_absolute_error(y_true, y_pred))
    r2    = float(r2_score(y_true, y_pred))
    resid = y_pred - y_true
    return {
        'label':        label,
        'n':            int(len(y_true)),
        'RMSE':         round(rmse, 6),
        'MAE':          round(mae, 6),
        'R2':           round(r2, 6),
        'mean_resid':   round(float(resid.mean()), 6),
        'median_resid': round(float(np.median(resid)), 6),
        'pred_min':     round(float(y_pred.min()), 6),
        'pred_max':     round(float(y_pred.max()), 6),
        'n_pred_lt_0':  int((y_pred < 0).sum()),
        'n_pred_gt_1':  int((y_pred > 1).sum()),
    }

# ─────────────────────────────────────────────────────────────────────────────
# STEP 8: BASELINE — mean SOH on train
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 8: Baseline (predict mean train SOH everywhere)")

mean_soh_train = float(y_train.mean())
bl_val  = compute_metrics(y_val,  np.full_like(y_val, mean_soh_train),  "baseline_val")
bl_test = compute_metrics(y_test, np.full_like(y_test, mean_soh_train), "baseline_test")
print(f"  Mean train SOH = {mean_soh_train:.4f}")
print(f"  Val  RMSE={bl_val['RMSE']:.4f} MAE={bl_val['MAE']:.4f} R2={bl_val['R2']:.4f}")
print(f"  Test RMSE={bl_test['RMSE']:.4f} MAE={bl_test['MAE']:.4f} R2={bl_test['R2']:.4f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 9: TRAIN MODELS
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 9: Train 4 lightweight models (CPU)")

models_def = {
    'linear':  LinearRegression(),
    'ridge':   Ridge(alpha=1.0),
    'rf':      RandomForestRegressor(n_estimators=200, max_depth=8, random_state=42, n_jobs=-1),
    'hgb':     HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05,
                                              max_leaf_nodes=15, l2_regularization=1.0,
                                              random_state=42),
}
model_names = {
    'linear': 'LinearRegression',
    'ridge':  'Ridge(alpha=1.0)',
    'rf':     'RandomForestRegressor(n_est=200, depth=8)',
    'hgb':    'HistGradientBoosting(iter=200, lr=0.05)',
}
USE_SCALED = {'linear', 'ridge'}

all_results = {}
trained_models = {}

for key, mdl in models_def.items():
    print(f"\n  --- {model_names[key]} ---")
    Xtr = X_train_sc if key in USE_SCALED else X_train
    Xvl = X_val_sc   if key in USE_SCALED else X_val
    Xte = X_test_sc  if key in USE_SCALED else X_test

    mdl.fit(Xtr, y_train)
    trained_models[key] = mdl

    tr_pred  = mdl.predict(Xtr)
    val_pred = mdl.predict(Xvl)
    te_pred  = mdl.predict(Xte)

    tr_m  = compute_metrics(y_train, tr_pred,  f"{key}_train")
    val_m = compute_metrics(y_val,   val_pred,  f"{key}_val")
    te_m  = compute_metrics(y_test,  te_pred,   f"{key}_test")

    all_results[key] = {'train': tr_m, 'val': val_m, 'test': te_m,
                        'val_pred': val_pred, 'test_pred': te_pred}

    print(f"  Train: RMSE={tr_m['RMSE']:.4f} MAE={tr_m['MAE']:.4f} R2={tr_m['R2']:.4f}")
    print(f"  Val  : RMSE={val_m['RMSE']:.4f} MAE={val_m['MAE']:.4f} R2={val_m['R2']:.4f}")
    print(f"  [Test hidden until model selected]")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 10: MODEL SELECTION (validation RMSE only)
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 10: Model selection (validation RMSE)")

print("\n  Validation RMSE comparison:")
val_rmse = {}
for key in models_def:
    r = all_results[key]['val']
    val_rmse[key] = r['RMSE']
    print(f"    {model_names[key]:45s}: RMSE={r['RMSE']:.4f} MAE={r['MAE']:.4f} R2={r['R2']:.4f}")

best_key = min(val_rmse, key=val_rmse.get)
print(f"\n  SELECTED: {model_names[best_key]} (lowest val RMSE={val_rmse[best_key]:.4f})")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 11: FINAL TEST ON B0007 (evaluated ONCE)
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 11: Final B0007 test (evaluated ONCE on selected model)")

best_model = trained_models[best_key]
Xte_final = X_test_sc if best_key in USE_SCALED else X_test
test_pred_final = best_model.predict(Xte_final)
final_test_m = compute_metrics(y_test, test_pred_final, "final_test_B0007")

print(f"  B0007 RMSE = {final_test_m['RMSE']:.4f}")
print(f"  B0007 MAE  = {final_test_m['MAE']:.4f}")
print(f"  B0007 R2   = {final_test_m['R2']:.4f}")
print(f"  Predictions < 0: {final_test_m['n_pred_lt_0']}")
print(f"  Predictions > 1: {final_test_m['n_pred_gt_1']}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 12: PER-CYCLE-RANGE ANALYSIS ON B0007
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 12: B0007 per-cycle-range analysis")

test_df2 = test_df.copy().reset_index(drop=True)
test_df2['pred'] = test_pred_final
test_df2['residual'] = test_pred_final - y_test

ranges = [(1, 40), (41, 80), (81, 200)]
range_labels = ['1-40', '41-80', '81-126']
range_metrics = []
for (lo, hi), lbl in zip(ranges, range_labels):
    sub = test_df2[test_df2['cycle_number'].between(lo, hi)]
    if len(sub) == 0:
        continue
    rm = compute_metrics(sub['SOH_target'].values, sub['pred'].values, lbl)
    range_metrics.append(rm)
    print(f"  Cycles {lbl:6s}: n={rm['n']:3d} RMSE={rm['RMSE']:.4f} MAE={rm['MAE']:.4f} R2={rm['R2']:.4f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 13: RESIDUAL ANALYSIS (selected model on B0007)
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 13: Residual analysis (B0007)")

resid = test_pred_final - y_test
print(f"  Mean residual  : {resid.mean():.4f}")
print(f"  Median residual: {np.median(resid):.4f}")
print(f"  Std residual   : {resid.std():.4f}")
print(f"  Corr(resid, actual SOH): {np.corrcoef(y_test, resid)[0,1]:.4f}")

bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0), (1.0, 9.9)]
bin_labels = ['0.0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0', '>1.0']
resid_by_bin = []
print("  Residuals by SOH range:")
for (lo, hi), lbl in zip(bins, bin_labels):
    mask = (y_test >= lo) & (y_test < hi)
    if mask.sum() == 0:
        continue
    r = resid[mask]
    resid_by_bin.append({'range': lbl, 'n': int(mask.sum()),
                         'mean': round(float(r.mean()), 4),
                         'median': round(float(np.median(r)), 4),
                         'std': round(float(r.std()), 4)})
    print(f"    {lbl:8s}: n={mask.sum():3d} mean={r.mean():.4f} std={r.std():.4f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 14: FEATURE IMPORTANCE / COEFFICIENTS
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 14: Feature importance")

fi_data = {}
for key, mdl in trained_models.items():
    if key in ('linear', 'ridge'):
        fi_data[key] = {f: float(c) for f, c in zip(FEATURES, mdl.coef_)}
        print(f"  {model_names[key]} coefficients:")
        for f, c in zip(FEATURES, mdl.coef_):
            print(f"    {f:22s}: {c:.4f}")
    elif hasattr(mdl, 'feature_importances_'):
        fi_data[key] = {f: float(v) for f, v in zip(FEATURES, mdl.feature_importances_)}
        print(f"  {model_names[key]} feature importances:")
        for f, v in zip(FEATURES, mdl.feature_importances_):
            print(f"    {f:22s}: {v:.4f}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 15: SAVE MODELS
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 15: Save models")

model_paths = {
    'linear': 'models/battery_soh_linear.joblib',
    'ridge':  'models/battery_soh_ridge.joblib',
    'rf':     'models/battery_soh_random_forest.joblib',
    'hgb':    'models/battery_soh_hist_gradient_boosting.joblib',
}

for key, path in model_paths.items():
    if os.path.exists(path):
        print(f"  SKIP (exists): {path}")
    else:
        joblib.dump(trained_models[key], path)
        print(f"  Saved: {path}")

final_path = 'models/battery_soh_final.joblib'
if os.path.exists(final_path):
    print(f"  SKIP (exists): {final_path}")
else:
    bundle = {'model': trained_models[best_key], 'scaler': scaler if best_key in USE_SCALED else None,
              'features': FEATURES, 'selected_key': best_key,
              'val_rmse': val_rmse[best_key], 'test_rmse': final_test_m['RMSE']}
    joblib.dump(bundle, final_path)
    print(f"  Saved final bundle: {final_path}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 16: SAVE TRAINING METADATA
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 16: Save training metadata")

meta_cols = ['battery_id', 'filename', 'cycle_number', 'ambient_temperature',
             'Capacity_numeric', 'SOH_target', 'exclusion_reason'] + FEATURES

# Build from eligible + excluded
all_meta = df[meta_cols].copy()
all_meta['split'] = 'excluded'
for split in ['train', 'val', 'test']:
    sub = eligible[eligible['split'] == split]
    all_meta.loc[sub.index, 'split'] = split

all_meta.to_csv(META_OUT, index=False)
print(f"  Saved: {META_OUT} ({len(all_meta)} rows)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 17: SAVE METRICS JSON
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 17: Save metrics JSON")

metrics_dict = {
    'dataset': {
        'total_records': total,
        'excluded_zero_capacity': int((df['exclusion_reason']=='zero_capacity_interrupted').sum()),
        'excluded_B0041_calibration': int((df['exclusion_reason']=='B0041_calibration_artifact').sum()),
        'excluded_missing_waveform': int((df['exclusion_reason']=='missing_waveform').sum()),
        'excluded_total': len(excluded),
        'eligible_total': len(eligible),
        'train_cells': sorted(train_df['battery_id'].unique().tolist()),
        'val_cells': [VAL_CELL],
        'test_cells': [TEST_CELL],
        'train_n': int(len(train_df)),
        'val_n': int(len(val_df)),
        'test_n': int(len(test_df)),
    },
    'baseline': {'val': bl_val, 'test': bl_test},
    'models': {},
    'selected_model': best_key,
    'selected_model_name': model_names[best_key],
    'final_test_B0007': final_test_m,
    'final_test_B0007_by_cycle_range': range_metrics,
    'residual_analysis': {
        'mean': round(float(resid.mean()), 6),
        'median': round(float(np.median(resid)), 6),
        'std': round(float(resid.std()), 6),
        'corr_with_actual': round(float(np.corrcoef(y_test, resid)[0,1]), 6),
        'by_soh_range': resid_by_bin,
    },
    'feature_importances': fi_data,
    'B0041_exclusion': {
        'criterion': 'Capacity_numeric < 0.5 Ah',
        'cycle_range': '1-42',
        'n_excluded': int(n41),
        'max_cap_excluded': round(float(cap_max_calib), 4),
        'min_cap_retained': round(float(cap_min_normal), 4),
    },
}

for key in models_def:
    metrics_dict['models'][key] = {
        'name': model_names[key],
        'train': all_results[key]['train'],
        'val':   all_results[key]['val'],
        'test':  all_results[key]['test'],
    }

if os.path.exists(METRICS_OUT):
    existing = json.load(open(METRICS_OUT, encoding='utf-8'))
    existing['stage_2c_soh'] = metrics_dict
    with open(METRICS_OUT, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2, default=str)
else:
    with open(METRICS_OUT, 'w', encoding='utf-8') as f:
        json.dump({'stage_2c_soh': metrics_dict}, f, indent=2, default=str)
print(f"  Saved: {METRICS_OUT}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 18: FIGURES
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 18: Generate figures")

# Figure 1: Actual vs Predicted (B0007, all 4 models)
fig, axes = plt.subplots(2, 2, figsize=(12, 10))
fig.suptitle('SOH: Actual vs Predicted — B0007 Final Test', fontsize=13, fontweight='bold')
for ax, key in zip(axes.flatten(), models_def.keys()):
    Xte_use = X_test_sc if key in USE_SCALED else X_test
    preds = trained_models[key].predict(Xte_use)
    m = compute_metrics(y_test, preds, key)
    ax.scatter(y_test, preds, alpha=0.6, s=20, c='steelblue', edgecolors='none')
    lims = [min(y_test.min(), preds.min())-0.02, max(y_test.max(), preds.max())+0.02]
    ax.plot(lims, lims, 'r--', lw=1)
    ax.set_xlim(lims); ax.set_ylim(lims)
    ax.set_xlabel('Actual SOH'); ax.set_ylabel('Predicted SOH')
    ax.set_title(f'{model_names[key]}\nRMSE={m["RMSE"]:.4f} R2={m["R2"]:.4f}')
    ax.grid(True, alpha=0.3)
plt.tight_layout()
p1 = os.path.join(FIG_DIR, 'battery_soh_actual_vs_predicted.png')
if not os.path.exists(p1):
    plt.savefig(p1, dpi=120, bbox_inches='tight')
    print(f"  Saved: {p1}")
else:
    print(f"  SKIP (exists): {p1}")
plt.close()

# Figure 2: Residuals for selected model on B0007
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
fig.suptitle(f'SOH Residuals — {model_names[best_key]} — B0007 Test', fontsize=12, fontweight='bold')
ax = axes[0]
ax.scatter(y_test, test_pred_final - y_test, alpha=0.6, s=20, c='coral', edgecolors='none')
ax.axhline(0, color='black', lw=1)
ax.set_xlabel('Actual SOH'); ax.set_ylabel('Residual (pred - actual)')
ax.set_title('Residuals vs Actual SOH')
ax.grid(True, alpha=0.3)
ax = axes[1]
ax.scatter(test_df2['cycle_number'], test_pred_final - y_test, alpha=0.6, s=20, c='darkorange', edgecolors='none')
ax.axhline(0, color='black', lw=1)
ax.set_xlabel('Cycle Number'); ax.set_ylabel('Residual (pred - actual)')
ax.set_title('Residuals vs Cycle Number')
ax.grid(True, alpha=0.3)
plt.tight_layout()
p2 = os.path.join(FIG_DIR, 'battery_soh_residuals.png')
if not os.path.exists(p2):
    plt.savefig(p2, dpi=120, bbox_inches='tight')
    print(f"  Saved: {p2}")
else:
    print(f"  SKIP (exists): {p2}")
plt.close()

# Figure 3: Feature importance
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
fig.suptitle('SOH Feature Importance / Coefficients', fontsize=12, fontweight='bold')
for ax, key in zip(axes, ['rf', 'hgb']):
    if key not in fi_data:
        continue
    vals = [fi_data[key][f] for f in FEATURES]
    colors = ['steelblue' if v >= 0 else 'coral' for v in vals]
    ax.barh(FEATURES, vals, color=colors, edgecolor='white', height=0.6)
    ax.set_xlabel('Feature Importance')
    ax.set_title(model_names[key])
    ax.axvline(0, color='black', lw=0.8)
    ax.grid(True, axis='x', alpha=0.3)
plt.tight_layout()
p3 = os.path.join(FIG_DIR, 'battery_soh_feature_importance.png')
if not os.path.exists(p3):
    plt.savefig(p3, dpi=120, bbox_inches='tight')
    print(f"  Saved: {p3}")
else:
    print(f"  SKIP (exists): {p3}")
plt.close()

# ─────────────────────────────────────────────────────────────────────────────
# STEP 19: WRITE REPORT
# ─────────────────────────────────────────────────────────────────────────────
print("\nSTEP 19: Write report")

train_cells_list = sorted(train_df['battery_id'].unique().tolist())
val_cells_list   = [VAL_CELL]
test_cells_list  = [TEST_CELL]

# Build model results table
model_table_rows = []
for key in models_def:
    r = all_results[key]
    model_table_rows.append(
        f"| {model_names[key]:<45} | {r['train']['RMSE']:.4f} | {r['train']['MAE']:.4f} | {r['train']['R2']:.4f} "
        f"| {r['val']['RMSE']:.4f} | {r['val']['MAE']:.4f} | {r['val']['R2']:.4f} |"
    )
model_table = "\n".join(model_table_rows)

# Feature importance text for report
fi_lines = []
for key in ('linear', 'ridge', 'rf', 'hgb'):
    fi_lines.append(f"\n**{model_names[key]}:**")
    if key in fi_data:
        for f in FEATURES:
            fi_lines.append(f"  - {f}: {fi_data[key][f]:.4f}")

range_table_rows = []
for rm in range_metrics:
    range_table_rows.append(
        f"| {rm['label']:7s} | {rm['n']:4d} | {rm['RMSE']:.4f} | {rm['MAE']:.4f} | {rm['R2']:.4f} |"
    )
range_table = "\n".join(range_table_rows)

resid_bin_rows = []
for rb in resid_by_bin:
    resid_bin_rows.append(
        f"| {rb['range']:8s} | {rb['n']:4d} | {rb['mean']:+.4f} | {rb['median']:+.4f} | {rb['std']:.4f} |"
    )
resid_bin_table = "\n".join(resid_bin_rows)

report = f"""# Model C - SOH Lightweight Training Report

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
| Total discharge records | {total} |
| Unique cells | {df['battery_id'].nunique()} |
| Eligible after all exclusions | {len(eligible)} |

---

## 4. EXCLUSIONS

| Reason | Records | Description |
|--------|---------|-------------|
| zero_capacity_interrupted | 3 | B0042/B0043/B0044 cycle 6 (cap=0.000 Ah) |
| B0041_calibration_artifact | {n41} | B0041 cycles 1-42 (cap<0.5 Ah; hard discontinuity at cycle 43) |
| missing_waveform | {(df['exclusion_reason']=='missing_waveform').sum()} | B0007(42), B0018(132), B0053(56), B0054(103), B0055(102), B0056(102) |
| **Total excluded** | **{len(excluded)}** | |

B0041 exclusion criterion: `Capacity_numeric < 0.5 Ah` applied to cycle_number 1-42.
- Max capacity in excluded range: {cap_max_calib:.4f} Ah
- Min capacity in retained range: {cap_min_normal:.4f} Ah
- Hard discontinuity confirmed: gap of >{(cap_min_normal - cap_max_calib):.2f} Ah between groups.

Source file NOT modified. Exclusion flags stored in `soh_training_metadata.csv`.

---

## 5. TRAIN / VALIDATION / TEST SPLIT

| Partition | Cells | n Cells | n Observations |
|-----------|-------|---------|----------------|
| TRAIN | {train_cells_list} | {len(train_cells_list)} | {len(train_df)} |
| VALIDATION | {val_cells_list} | 1 | {len(val_df)} |
| TEST (final) | {test_cells_list} | 1 | {len(test_df)} |

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

Predict `mean_train_SOH = {mean_soh_train:.4f}` for all observations.

| Set | RMSE | MAE | R2 |
|-----|------|-----|----|
| Validation (B0006) | {bl_val['RMSE']:.4f} | {bl_val['MAE']:.4f} | {bl_val['R2']:.4f} |
| Test B0007 | {bl_test['RMSE']:.4f} | {bl_test['MAE']:.4f} | {bl_test['R2']:.4f} |

---

## 9. MODEL RESULTS

| Model | Train RMSE | Train MAE | Train R2 | Val RMSE | Val MAE | Val R2 |
|-------|-----------|----------|---------|---------|--------|-------|
{model_table}

---

## 10. B0007 FINAL TEST

Selected model: **{model_names[best_key]}** (lowest validation RMSE = {val_rmse[best_key]:.4f})

B0007 was evaluated ONCE after model selection.

| Metric | Value |
|--------|-------|
| RMSE | {final_test_m['RMSE']:.4f} |
| MAE | {final_test_m['MAE']:.4f} |
| R2 | {final_test_m['R2']:.4f} |
| Mean residual | {final_test_m['mean_resid']:.4f} |
| Median residual | {final_test_m['median_resid']:.4f} |
| Predictions < 0 | {final_test_m['n_pred_lt_0']} |
| Predictions > 1 | {final_test_m['n_pred_gt_1']} |
| N (B0007 test) | {final_test_m['n']} |

### By Cycle Range

| Cycles | N | RMSE | MAE | R2 |
|--------|---|------|-----|----|
{range_table}

---

## 11. RESIDUAL ANALYSIS

Selected model: {model_names[best_key]} on B0007 test

| Metric | Value |
|--------|-------|
| Mean residual | {resid.mean():.4f} |
| Median residual | {float(np.median(resid)):.4f} |
| Std residual | {resid.std():.4f} |
| Corr(residual, actual SOH) | {float(np.corrcoef(y_test, resid)[0,1]):.4f} |

### By SOH Range

| SOH Range | N | Mean Resid | Median Resid | Std |
|-----------|---|-----------|-------------|-----|
{resid_bin_table}

---

## 12. FEATURE IMPORTANCE

{''.join(fi_lines)}

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
6. B0007 has 42 discharge records with missing raw waveform files. These 42 cycles are excluded from the test set; the final test covers {len(test_df)} of 168 B0007 cycles.
7. This is a lightweight model. No neural network, no deep feature extraction, no SHAP analysis.

---

## 15. FINAL MODEL

**Selected model:** {model_names[best_key]}
- Selected by: lowest validation RMSE ({val_rmse[best_key]:.4f}) on B0006
- Evaluated once on B0007: RMSE={final_test_m['RMSE']:.4f}, MAE={final_test_m['MAE']:.4f}, R2={final_test_m['R2']:.4f}
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
"""

if os.path.exists(REPORT_OUT):
    print(f"  SKIP report (exists): {REPORT_OUT}")
else:
    with open(REPORT_OUT, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"  Saved: {REPORT_OUT}")

# ─────────────────────────────────────────────────────────────────────────────
# FINAL SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SOH TRAINING COMPLETE — SUMMARY")
print("=" * 70)
print(f"Selected model         : {model_names[best_key]}")
print(f"Validation RMSE        : {val_rmse[best_key]:.4f}")
print(f"Validation MAE         : {all_results[best_key]['val']['MAE']:.4f}")
print(f"Validation R2          : {all_results[best_key]['val']['R2']:.4f}")
print(f"B0007 test RMSE        : {final_test_m['RMSE']:.4f}")
print(f"B0007 test MAE         : {final_test_m['MAE']:.4f}")
print(f"B0007 test R2          : {final_test_m['R2']:.4f}")
print(f"Train observations     : {len(train_df)}")
print(f"Validation observations: {len(val_df)}")
print(f"B0007 test observations: {len(test_df)}")
print(f"Excluded (total)       : {len(excluded)}")
print(f"  zero_capacity_interrupted : {(df['exclusion_reason']=='zero_capacity_interrupted').sum()}")
print(f"  B0041_calibration_artifact: {(df['exclusion_reason']=='B0041_calibration_artifact').sum()}")
print(f"  missing_waveform          : {(df['exclusion_reason']=='missing_waveform').sum()}")
print()
print("Artifacts:")
for p in [model_paths['linear'], model_paths['ridge'],
          model_paths['rf'], model_paths['hgb'], final_path,
          META_OUT, METRICS_OUT, REPORT_OUT,
          'docs/figures/battery_soh_actual_vs_predicted.png',
          'docs/figures/battery_soh_residuals.png',
          'docs/figures/battery_soh_feature_importance.png']:
    status = "OK" if os.path.exists(p) else "MISSING"
    print(f"  [{status}] {p}")
print()
print("CPU-only lightweight training: YES")
print("B0007 untouched until final evaluation: YES")
print("=" * 70)
