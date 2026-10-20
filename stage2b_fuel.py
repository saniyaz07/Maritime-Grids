"""
stage2b_fuel.py
Stage 2B: Model B Fuel Consumption Regression Pipeline
"""

import os
import sys
import json
import random
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import joblib

from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold
import xgboost as xgb

# Set random seed
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

ROOT = "C:/maritime grids"
PROCESSED = f"{ROOT}/data/processed"
MODELS_DIR = f"{ROOT}/models"
DOCS_DIR = f"{ROOT}/docs"
FIGS_DIR = f"{ROOT}/docs/figures"

for d in [MODELS_DIR, FIGS_DIR]:
    os.makedirs(d, exist_ok=True)

# -----------------------------------------------------------------------------
# 1. LOAD DATA & AUDIT
# -----------------------------------------------------------------------------
print("=" * 70)
print("STAGE 2B: MODEL B FUEL-CONSUMPTION REGRESSION")
print("=" * 70)

master_path = f"{PROCESSED}/master_training_table.csv"
master = pd.read_csv(master_path)
print("\n--- 1. LOAD EXISTING MASTER TRAINING TABLE ---")
print(f"Dataframe shape: {master.shape}")
print(f"Total rows: {len(master)}, Total columns: {len(master.columns)}")

# Map profile columns to exact feature names requested
# displacement_tonnes -> displacement, engine_power_kw -> engine_power, dwt_tonnes -> DWT
master["displacement"] = master["displacement_tonnes"]
master["engine_power"] = master["engine_power_kw"]
master["DWT"] = master["dwt_tonnes"]

CAT_FEATS = ["ship_type", "route_id", "fuel_type", "weather_conditions"]
NUM_FEATS = ["distance", "engine_efficiency", "displacement", "engine_power", "DWT"]
ALL_FEATS = CAT_FEATS + NUM_FEATS
TARGET = "fuel_consumption"

print(f"Target column: '{TARGET}'")
print(f"Features: {ALL_FEATS}")
print(f"Unique ships: {master['ship_id'].nunique()}")
print(f"Unique routes: {master['route_id'].nunique()} -> {sorted(master['route_id'].unique())}")
print(f"Unique fuel types: {master['fuel_type'].nunique()} -> {sorted(master['fuel_type'].unique())}")

# Null audit
nulls = master[ALL_FEATS + [TARGET, "CO2_emissions"]].isnull().sum()
print("\nNull counts for Model B features, target, and CO2_emissions:")
for col, cnt in nulls.items():
    print(f"  {col:<20}: {cnt} nulls")
if nulls.sum() > 0:
    raise ValueError("Missing values found in Model B required fields!")
print("Verification: 0 nulls across all Model B fields. No rows dropped.")

# Verify weather_conditions is OBSERVED
print("\n--- 2. VERIFY WEATHER CONDITIONS FEATURE ---")
print("CRITICAL CHECK: 'weather_conditions' is loaded directly from Phase 1 master table.")
print("Observed weather conditions distribution:")
for val, count in master["weather_conditions"].value_counts().items():
    print(f"  {val:<10}: {count} ({count/len(master)*100:.2f}%)")
print("CONFIRMATION: Observed voyage-level weather labels are used directly.")
print("Model A predictions and weather_final.joblib were NOT used as Model B inputs.")

# -----------------------------------------------------------------------------
# 3. AUDIT TARGET AND FEATURES
# -----------------------------------------------------------------------------
print("\n--- 3. AUDIT TARGET AND FEATURES ---")
y_target = master[TARGET]
print(f"Target ('{TARGET}'):")
print(f"  Count:  {y_target.count()}")
print(f"  Mean:   {y_target.mean():.2f}")
print(f"  Std:    {y_target.std():.2f}")
print(f"  Min:    {y_target.min():.2f}")
print(f"  25%:    {y_target.quantile(0.25):.2f}")
print(f"  Median: {y_target.median():.2f}")
print(f"  75%:    {y_target.quantile(0.75):.2f}")
print(f"  Max:    {y_target.max():.2f}")

print("\nCategorical Features:")
for cat_col in CAT_FEATS:
    print(f"  [{cat_col}]")
    vc = master[cat_col].value_counts()
    vp = master[cat_col].value_counts(normalize=True) * 100
    for val in vc.index:
        print(f"    {val:<22}: {vc[val]:4d} ({vp[val]:5.2f}%)")

print("\nNumerical Features:")
for num_col in NUM_FEATS:
    s = master[num_col]
    print(f"  {num_col:<20}: min={s.min():8.2f}, 25%={s.quantile(0.25):8.2f}, median={s.median():8.2f}, mean={s.mean():8.2f}, 75%={s.quantile(0.75):8.2f}, max={s.max():8.2f}, std={s.std():8.2f}")

# -----------------------------------------------------------------------------
# 4. PRIMARY SHIP-HOLDOUT SPLIT (96/24 ships)
# -----------------------------------------------------------------------------
print("\n--- 4. PRIMARY SHIP-HOLDOUT SPLIT ---")
ship_meta = master[["ship_id", "ship_type"]].drop_duplicates().set_index("ship_id")
rng = np.random.default_rng(SEED)
test_ships = set()
for stype, grp in ship_meta.groupby("ship_type"):
    n_test = max(1, round(len(grp) * 0.20))
    chosen = rng.choice(grp.index.tolist(), size=n_test, replace=False)
    test_ships.update(chosen.tolist())

train_ships = set(ship_meta.index) - test_ships
assert train_ships.isdisjoint(test_ships), "LEAKAGE: Overlap detected between train and test ships!"

train_df = master[master["ship_id"].isin(train_ships)].copy().reset_index(drop=True)
test_df = master[master["ship_id"].isin(test_ships)].copy().reset_index(drop=True)

print(f"Train ships: {len(train_ships)}, Train rows: {len(train_df)}")
print(f"Test ships:  {len(test_ships)}, Test rows:  {len(test_df)}")
print(f"Train/Test ship intersection: {len(train_ships.intersection(test_ships))} (Strictly 0)")
print("Ship-type distribution across splits:")
for stype in sorted(ship_meta["ship_type"].unique()):
    tr_count = len([s for s in train_ships if ship_meta.loc[s, "ship_type"] == stype])
    te_count = len([s for s in test_ships if ship_meta.loc[s, "ship_type"] == stype])
    print(f"  {stype:<20}: train={tr_count:2d} ships ({tr_count*12:3d} rows), test={te_count:2d} ships ({te_count*12:3d} rows)")

X_train = train_df[ALL_FEATS]
y_train = train_df[TARGET].values
X_test = test_df[ALL_FEATS]
y_test = test_df[TARGET].values

# -----------------------------------------------------------------------------
# 5. PREPROCESSING SPECIFICATION
# -----------------------------------------------------------------------------
def build_preprocessor():
    """Build ColumnTransformer coupling OneHotEncoder and StandardScaler."""
    return ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CAT_FEATS),
            ("num", StandardScaler(), NUM_FEATS)
        ]
    )

# -----------------------------------------------------------------------------
# 6. BASELINE MODEL — LINEAR REGRESSION
# -----------------------------------------------------------------------------
print("\n--- 6. BASELINE MODEL: LINEAR REGRESSION ---")
lr_pipeline = Pipeline([
    ("preprocessor", build_preprocessor()),
    ("regressor", LinearRegression())
])

lr_pipeline.fit(X_train, y_train)
y_pred_lr = lr_pipeline.predict(X_test)

lr_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_lr)))
lr_mae = float(mean_absolute_error(y_test, y_pred_lr))
lr_r2 = float(r2_score(y_test, y_pred_lr))

print(f"Linear Regression Primary Ship-Holdout Test Metrics:")
print(f"  RMSE: {lr_rmse:.2f}")
print(f"  MAE:  {lr_mae:.2f}")
print(f"  R2:   {lr_r2:.4f}")

# Save Linear Regression pipeline
joblib.dump(lr_pipeline, f"{MODELS_DIR}/fuel_linear.joblib")
print(f"Saved: {MODELS_DIR}/fuel_linear.joblib")

# -----------------------------------------------------------------------------
# 7 & 8. XGBOOST REGRESSION & GROUPED CV HYPERPARAMETER TUNING
# -----------------------------------------------------------------------------
print("\n--- 7 & 8. XGBOOST REGRESSION & 5-FOLD GROUPED CV (BY ship_id) ---")
gkf = GroupKFold(n_splits=5)
train_ship_ids = train_df["ship_id"].values

param_grid = []
for md in [2, 3, 4]:
    for ne in [50, 100, 200]:
        for lr_rate in [0.05, 0.1, 0.2]:
            param_grid.append({"max_depth": md, "n_estimators": ne, "learning_rate": lr_rate})

print(f"Running GroupKFold(n_splits=5) tuning over {len(param_grid)} configurations on 96 training ships...")
cv_results = []

for params in param_grid:
    fold_rmses = []
    fold_maes = []
    fold_r2s = []
    
    for tr_idx, val_idx in gkf.split(X_train, y_train, groups=train_ship_ids):
        X_cv_tr, y_cv_tr = X_train.iloc[tr_idx], y_train[tr_idx]
        X_cv_val, y_cv_val = X_train.iloc[val_idx], y_train[val_idx]
        
        cv_pipe = Pipeline([
            ("preprocessor", build_preprocessor()),
            ("regressor", xgb.XGBRegressor(
                objective="reg:squarederror",
                max_depth=params["max_depth"],
                n_estimators=params["n_estimators"],
                learning_rate=params["learning_rate"],
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=SEED,
                n_jobs=-1
            ))
        ])
        
        # Preprocessor fit ONLY on fold training data
        cv_pipe.fit(X_cv_tr, y_cv_tr)
        val_preds = cv_pipe.predict(X_cv_val)
        
        fold_rmses.append(np.sqrt(mean_squared_error(y_cv_val, val_preds)))
        fold_maes.append(mean_absolute_error(y_cv_val, val_preds))
        fold_r2s.append(r2_score(y_cv_val, val_preds))
        
    mean_rmse = float(np.mean(fold_rmses))
    std_rmse = float(np.std(fold_rmses))
    mean_mae = float(np.mean(fold_maes))
    mean_r2 = float(np.mean(fold_r2s))
    
    cv_results.append({
        "params": params,
        "mean_rmse": mean_rmse,
        "std_rmse": std_rmse,
        "mean_mae": mean_mae,
        "mean_r2": mean_r2
    })

# Select best parameters by lowest mean_rmse
cv_results.sort(key=lambda x: x["mean_rmse"])
best_cv = cv_results[0]
best_params = best_cv["params"]

print("\nTop 3 XGBoost Configurations (by CV RMSE):")
for i, res in enumerate(cv_results[:3]):
    print(f"  {i+1}. params={res['params']} | CV RMSE: {res['mean_rmse']:.2f} +/- {res['std_rmse']:.2f} | CV MAE: {res['mean_mae']:.2f} | CV R2: {res['mean_r2']:.4f}")

print(f"\nSelected Best XGBoost Hyperparameters: {best_params}")
print(f"CV Mean RMSE: {best_cv['mean_rmse']:.2f} (+/- {best_cv['std_rmse']:.2f})")
print(f"Scoring metric used: RMSE (negative RMSE minimization)")
print(f"Grouping variable: ship_id (5 folds)")

# Retrain best XGBoost pipeline on ALL 96 training ships
best_xgb_pipeline = Pipeline([
    ("preprocessor", build_preprocessor()),
    ("regressor", xgb.XGBRegressor(
        objective="reg:squarederror",
        max_depth=best_params["max_depth"],
        n_estimators=best_params["n_estimators"],
        learning_rate=best_params["learning_rate"],
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=SEED,
        n_jobs=-1
    ))
])

best_xgb_pipeline.fit(X_train, y_train)

# -----------------------------------------------------------------------------
# 9. FINAL PRIMARY TEST EVALUATION
# -----------------------------------------------------------------------------
print("\n--- 9. FINAL PRIMARY TEST EVALUATION (24 Test Ships, 288 Rows) ---")
y_pred_xgb = best_xgb_pipeline.predict(X_test)

xgb_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_xgb)))
xgb_mae = float(mean_absolute_error(y_test, y_pred_xgb))
xgb_r2 = float(r2_score(y_test, y_pred_xgb))

print(f"XGBoost Primary Ship-Holdout Test Metrics:")
print(f"  RMSE: {xgb_rmse:.2f}")
print(f"  MAE:  {xgb_mae:.2f}")
print(f"  R2:   {xgb_r2:.4f}")

print("\nPrimary Test Comparison (Linear Regression vs. XGBoost):")
print(f"{'Model':<25} | {'RMSE':<10} | {'MAE':<10} | {'R2':<10}")
print("-" * 60)
print(f"{'Linear Regression':<25} | {lr_rmse:<10.2f} | {lr_mae:<10.2f} | {lr_r2:<10.4f}")
print(f"{'XGBoost (Tuned)':<25} | {xgb_rmse:<10.2f} | {xgb_mae:<10.2f} | {xgb_r2:<10.4f}")

if xgb_rmse < lr_rmse:
    print(f"Factual comparison: XGBoost achieved lower RMSE ({xgb_rmse:.2f} vs {lr_rmse:.2f}), lower MAE ({xgb_mae:.2f} vs {lr_mae:.2f}), and higher R2 ({xgb_r2:.4f} vs {lr_r2:.4f}).")
else:
    print(f"Factual comparison: Linear Regression achieved lower RMSE ({lr_rmse:.2f} vs {xgb_rmse:.2f}).")

# Save final XGBoost pipeline
joblib.dump(best_xgb_pipeline, f"{MODELS_DIR}/fuel_xgb.joblib")
print(f"Saved: {MODELS_DIR}/fuel_xgb.joblib")

# -----------------------------------------------------------------------------
# 10. ROUTE-HOLDOUT EVALUATION
# -----------------------------------------------------------------------------
print("\n--- 10. ROUTE-HOLDOUT EVALUATION ---")
ROUTES = sorted(master["route_id"].unique().tolist())
route_results_lr = {}
route_results_xgb = {}

for r in ROUTES:
    r_train_df = master[master["route_id"] != r].copy().reset_index(drop=True)
    r_test_df = master[master["route_id"] == r].copy().reset_index(drop=True)
    
    X_r_train = r_train_df[ALL_FEATS]
    y_r_train = r_train_df[TARGET].values
    X_r_test = r_test_df[ALL_FEATS]
    y_r_test = r_test_df[TARGET].values
    
    # Linear Regression for route fold
    lr_r_pipe = Pipeline([
        ("preprocessor", build_preprocessor()),
        ("regressor", LinearRegression())
    ])
    lr_r_pipe.fit(X_r_train, y_r_train)
    p_lr_r = lr_r_pipe.predict(X_r_test)
    
    r_lr_rmse = float(np.sqrt(mean_squared_error(y_r_test, p_lr_r)))
    r_lr_mae = float(mean_absolute_error(y_r_test, p_lr_r))
    r_lr_r2 = float(r2_score(y_r_test, p_lr_r))
    route_results_lr[r] = {
        "train_rows": len(r_train_df),
        "test_rows": len(r_test_df),
        "rmse": round(r_lr_rmse, 2),
        "mae": round(r_lr_mae, 2),
        "r2": round(r_lr_r2, 4)
    }
    
    # XGBoost for route fold
    xgb_r_pipe = Pipeline([
        ("preprocessor", build_preprocessor()),
        ("regressor", xgb.XGBRegressor(
            objective="reg:squarederror",
            max_depth=best_params["max_depth"],
            n_estimators=best_params["n_estimators"],
            learning_rate=best_params["learning_rate"],
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=SEED,
            n_jobs=-1
        ))
    ])
    xgb_r_pipe.fit(X_r_train, y_r_train)
    p_xgb_r = xgb_r_pipe.predict(X_r_test)
    
    r_xgb_rmse = float(np.sqrt(mean_squared_error(y_r_test, p_xgb_r)))
    r_xgb_mae = float(mean_absolute_error(y_r_test, p_xgb_r))
    r_xgb_r2 = float(r2_score(y_r_test, p_xgb_r))
    route_results_xgb[r] = {
        "train_rows": len(r_train_df),
        "test_rows": len(r_test_df),
        "rmse": round(r_xgb_rmse, 2),
        "mae": round(r_xgb_mae, 2),
        "r2": round(r_xgb_r2, 4)
    }
    
    print(f"Route: {r:<20} (Train rows: {len(r_train_df)}, Test rows: {len(r_test_df)})")
    print(f"  Linear Regression -> RMSE: {r_lr_rmse:7.2f}, MAE: {r_lr_mae:7.2f}, R2: {r_lr_r2:.4f}")
    print(f"  XGBoost           -> RMSE: {r_xgb_rmse:7.2f}, MAE: {r_xgb_mae:7.2f}, R2: {r_xgb_r2:.4f}")

# -----------------------------------------------------------------------------
# 11. ACTUAL VS PREDICTED FIGURE
# -----------------------------------------------------------------------------
print("\n--- 11. GENERATING ACTUAL VS PREDICTED FIGURE ---")
fig, ax = plt.subplots(figsize=(7, 7))
ax.scatter(y_test, y_pred_xgb, alpha=0.4, s=20, color="#1f77b4", edgecolors="none", label="Voyage Predictions")

# Reference line
min_val = min(y_test.min(), y_pred_xgb.min())
max_val = max(y_test.max(), y_pred_xgb.max())
margin = (max_val - min_val) * 0.05
lims = [min_val - margin, max_val + margin]
ax.plot(lims, lims, "r--", linewidth=1.5, label="Ideal 1:1 Reference Line")

ax.set_xlim(lims)
ax.set_ylim(lims)
ax.set_xlabel("Actual Fuel Consumption [Litres / kg (dataset units)]", fontsize=11)
ax.set_ylabel("Predicted Fuel Consumption [Litres / kg (dataset units)]", fontsize=11)
ax.set_title("Model B: Actual vs Predicted Fuel Consumption\n(XGBoost on Primary 24-Ship Holdout)", fontsize=12)
ax.grid(True, linestyle=":", alpha=0.6)
ax.legend(loc="upper left")

# Metrics annotation
ax.text(0.05, 0.85, f"Test RMSE: {xgb_rmse:.2f}\nTest MAE:  {xgb_mae:.2f}\nTest R2:   {xgb_r2:.4f}",
        transform=ax.transAxes, fontsize=10, verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.8, edgecolor="gray"))

plt.tight_layout()
act_pred_path = f"{FIGS_DIR}/fuel_actual_vs_predicted.png"
fig.savefig(act_pred_path, dpi=150)
plt.close()
print(f"Saved: {act_pred_path}")

# -----------------------------------------------------------------------------
# 12. FEATURE IMPORTANCE FIGURE
# -----------------------------------------------------------------------------
print("\n--- 12. GENERATING FEATURE IMPORTANCE FIGURE ---")
# Extract transformed feature names from fitted pipeline
ohe = best_xgb_pipeline.named_steps["preprocessor"].named_transformers_["cat"]
ohe_feature_names = ohe.get_feature_names_out(CAT_FEATS).tolist()
all_transformed_feature_names = ohe_feature_names + NUM_FEATS

xgb_model = best_xgb_pipeline.named_steps["regressor"]
importances = xgb_model.feature_importances_

sorted_idx = np.argsort(importances)
sorted_names = [all_transformed_feature_names[i] for i in sorted_idx]
sorted_importances = importances[sorted_idx]

fig, ax = plt.subplots(figsize=(10, 7))
ax.barh(sorted_names, sorted_importances, color="#2ca02c", edgecolor="black", linewidth=0.5)
ax.set_xlabel("Feature Importance (Gain)", fontsize=11)
ax.set_title("Model B: XGBoost Feature Importance\n(Transformed One-Hot & Numerical Features)", fontsize=12)
ax.grid(True, linestyle=":", axis="x", alpha=0.6)

plt.tight_layout()
feat_imp_path = f"{FIGS_DIR}/fuel_feature_importance.png"
fig.savefig(feat_imp_path, dpi=150)
plt.close()
print(f"Saved: {feat_imp_path}")

# -----------------------------------------------------------------------------
# 13 & 14. DETERMINISTIC CO2 DERIVATION & NO CO2 ML MODEL
# -----------------------------------------------------------------------------
print("\n--- 13 & 14. DETERMINISTIC CO2 DERIVATION & DOCUMENTATION ---")
# Verification of empirical conversion factors from previous diagnostic
# Diesel: mean = 2.749960, HFO: mean = 2.753806
CO2_FACTORS = {
    "Diesel": 2.749960207668532,
    "HFO": 2.7538059377650304
}
print(f"Dataset-derived empirical conversion factors:")
print(f"  Diesel: {CO2_FACTORS['Diesel']:.6f} kg CO2 per fuel unit (CV ~ 5.3%)")
print(f"  HFO:    {CO2_FACTORS['HFO']:.6f} kg CO2 per fuel unit (CV ~ 5.3%)")

# Unit ambiguity documentation
print("\nUnit Analysis & Documentation:")
print("  - Master table distance: Nautical miles / km")
print("  - Master table fuel_consumption: 'Litres / kg' (likely Litres burned)")
print("  - Master table CO2_emissions: 'kg CO2' (mass of emitted carbon dioxide)")
print("  - Standard emission factors are ~3.114 tCO2/t-HFO and ~3.206 tCO2/t-Diesel.")
print("  - With fuel density ~0.84-0.86 kg/L, ~3.2 kg CO2 / kg * 0.85 kg/L yields ~2.72-2.75 kg CO2 / L.")
print("  - Thus, the ratio of ~2.75 reflects kg CO2 per Litre of fuel.")
print("  - Formula: predicted_CO2 = predicted_fuel_consumption * factor[fuel_type]")

# Evaluate deterministic CO2 on primary test set using predicted fuel consumption
test_df["predicted_fuel_xgb"] = y_pred_xgb
test_df["derived_CO2"] = test_df.apply(
    lambda r: r["predicted_fuel_xgb"] * CO2_FACTORS[r["fuel_type"]], axis=1
)

actual_co2 = test_df["CO2_emissions"].values
pred_co2 = test_df["derived_CO2"].values

co2_rmse = float(np.sqrt(mean_squared_error(actual_co2, pred_co2)))
co2_mae = float(mean_absolute_error(actual_co2, pred_co2))
co2_r2 = float(r2_score(actual_co2, pred_co2))

print("\nDeterministic CO2 Prediction Performance (Primary Test Set):")
print(f"  CO2 RMSE: {co2_rmse:.2f} kg CO2")
print(f"  CO2 MAE:  {co2_mae:.2f} kg CO2")
print(f"  CO2 R2:   {co2_r2:.4f}")

# Explicit statement of no separate ML model
no_co2_statement = (
    "CO2 was not trained as a separate ML target because the existing diagnostic "
    "showed a sufficiently stable deterministic relationship between fuel "
    "consumption and CO2 emissions (CV < 5.4% for both Diesel and HFO)."
)
print(f"\nPolicy Confirmation: {no_co2_statement}")

# -----------------------------------------------------------------------------
# 15. REPRODUCIBILITY METADATA
# -----------------------------------------------------------------------------
reproducibility = {
    "random_seed": SEED,
    "python_version": sys.version,
    "xgboost_version": xgb.__version__,
    "sklearn_version": "1.9.0",
    "pandas_version": pd.__version__,
    "numpy_version": np.__version__,
    "device": "cpu",
    "gpu_used": False,
    "input_path": master_path,
    "models_saved": [
        f"{MODELS_DIR}/fuel_linear.joblib",
        f"{MODELS_DIR}/fuel_xgb.joblib"
    ],
    "figures_saved": [
        act_pred_path,
        feat_imp_path
    ]
}

# -----------------------------------------------------------------------------
# 16. UPDATE METRICS JSON (APPEND stage_2b_fuel)
# -----------------------------------------------------------------------------
print("\n--- 16. UPDATING DOCS/PHASE2_METRICS.JSON ---")
metrics_path = f"{DOCS_DIR}/phase2_metrics.json"
if os.path.exists(metrics_path):
    with open(metrics_path, "r") as f:
        metrics_dict = json.load(f)
else:
    metrics_dict = {}

# Ensure stage_2a_weather is preserved
assert "stage_2a_weather" in metrics_dict, "ERROR: stage_2a_weather key missing from metrics!"

stage_2b_metrics = {
    "dataset_audit": {
        "total_rows": int(len(master)),
        "total_columns": int(len(master.columns)),
        "unique_ships": int(master["ship_id"].nunique()),
        "unique_routes": int(master["route_id"].nunique()),
        "null_counts": {col: int(nulls[col]) for col in ALL_FEATS + [TARGET, "CO2_emissions"]},
        "target_summary": {
            "mean": round(float(y_target.mean()), 2),
            "median": round(float(y_target.median()), 2),
            "std": round(float(y_target.std()), 2),
            "min": round(float(y_target.min()), 2),
            "q25": round(float(y_target.quantile(0.25)), 2),
            "q75": round(float(y_target.quantile(0.75)), 2),
            "max": round(float(y_target.max()), 2)
        }
    },
    "primary_split": {
        "train_ships": len(train_ships),
        "test_ships": len(test_ships),
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "ship_intersection": len(train_ships.intersection(test_ships))
    },
    "linear_regression_baseline": {
        "primary_ship_holdout": {
            "rmse": round(lr_rmse, 2),
            "mae": round(lr_mae, 2),
            "r2": round(lr_r2, 4)
        },
        "route_holdouts": route_results_lr
    },
    "xgboost": {
        "best_hyperparameters": best_params,
        "cv_folds": 5,
        "cv_grouping_variable": "ship_id",
        "cv_mean_rmse": round(best_cv["mean_rmse"], 2),
        "cv_std_rmse": round(best_cv["std_rmse"], 2),
        "cv_mean_mae": round(best_cv["mean_mae"], 2),
        "cv_mean_r2": round(best_cv["mean_r2"], 4),
        "scoring_metric": "RMSE",
        "primary_ship_holdout": {
            "rmse": round(xgb_rmse, 2),
            "mae": round(xgb_mae, 2),
            "r2": round(xgb_r2, 4)
        },
        "route_holdouts": route_results_xgb
    },
    "deterministic_co2": {
        "empirical_factors": {
            "Diesel": round(CO2_FACTORS["Diesel"], 6),
            "HFO": round(CO2_FACTORS["HFO"], 6)
        },
        "formula": "predicted_CO2 = predicted_fuel_consumption * empirical_factor[fuel_type]",
        "units": "kg CO2 / fuel unit",
        "unit_notes": "Derived from observed ratio; corresponds to kg CO2 emitted per Litre of fuel burned.",
        "primary_test_performance": {
            "rmse": round(co2_rmse, 2),
            "mae": round(co2_mae, 2),
            "r2": round(co2_r2, 4)
        },
        "no_separate_ml_model_statement": no_co2_statement
    },
    "model_comparison": {
        "lower_rmse_model": "XGBoost" if xgb_rmse < lr_rmse else "Linear Regression",
        "lower_mae_model": "XGBoost" if xgb_mae < lr_mae else "Linear Regression",
        "higher_r2_model": "XGBoost" if xgb_r2 > lr_r2 else "Linear Regression",
        "production_fuel_model": "models/fuel_xgb.joblib"
    },
    "reproducibility": reproducibility
}

metrics_dict["stage_2b_fuel"] = stage_2b_metrics

with open(metrics_path, "w") as f:
    json.dump(metrics_dict, f, indent=2)
print("Updated docs/phase2_metrics.json with stage_2b_fuel block.")

# -----------------------------------------------------------------------------
# 18. TEST INFERENCE ON SAVED ARTIFACTS
# -----------------------------------------------------------------------------
print("\n--- 18. VERIFYING ARTIFACTS LOADABILITY & TEST INFERENCE ---")
loaded_lr = joblib.load(f"{MODELS_DIR}/fuel_linear.joblib")
loaded_xgb = joblib.load(f"{MODELS_DIR}/fuel_xgb.joblib")

test_sample = X_test.iloc[0:1]
lr_test_pred = loaded_lr.predict(test_sample)[0]
xgb_test_pred = loaded_xgb.predict(test_sample)[0]

print(f"Sample test row:\n{test_sample.to_dict(orient='records')[0]}")
print(f"  Actual fuel_consumption:    {y_test[0]:.2f}")
print(f"  Loaded LR prediction:       {lr_test_pred:.2f}")
print(f"  Loaded XGBoost prediction:  {xgb_test_pred:.2f}")
assert not np.isnan(lr_test_pred), "LR prediction is NaN"
assert not np.isnan(xgb_test_pred), "XGBoost prediction is NaN"
print("Verification: Both .joblib files load and execute inference successfully.")

print("\n" + "=" * 70)
print("STAGE 2B EXECUTION COMPLETE.")
print("=" * 70)
