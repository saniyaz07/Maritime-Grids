"""
stage2a_weather.py
Stage 2A: Model A Weather Classifier — Fix and Re-evaluate Only
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

from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix
from sklearn.model_selection import GroupKFold
import xgboost as xgb

# Set seeds
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

ROOT = "C:/maritime grids"
PROCESSED = f"{ROOT}/data/processed"
MODELS_DIR = f"{ROOT}/models"
DOCS_DIR = f"{ROOT}/docs"
FIGS_DIR = f"{ROOT}/docs/figures"

# 1. Load data
master = pd.read_csv(f"{PROCESSED}/master_training_table.csv")
assert len(master) == 1440, f"Expected 1440 rows, got {len(master)}"

MONTH_ORDER = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]
MONTH_NUM = {m: i+1 for i, m in enumerate(MONTH_ORDER)}

master["WS50M"] = (master["WS50M_MAX"] + master["WS50M_MIN"]) / 2
master["month_num"] = master["month"].map(MONTH_NUM)
master["month_sin"] = np.sin(2 * np.pi * master["month_num"] / 12)
master["month_cos"] = np.cos(2 * np.pi * master["month_num"] / 12)

# Features and target
A_FEATS = [
    "WS10M", "WS50M", "RH2M", "PS", "T2M_MIN",
    "wave_height_max", "wave_period_max", "wave_direction_dominant",
    "month_sin", "month_cos"
]
A_TARGET = "weather_conditions"
WEATHER_CLASSES = ["Calm", "Moderate", "Stormy"]

le_weather = LabelEncoder()
le_weather.fit(WEATHER_CLASSES)

# Recreate exact ship holdout split (same seed and logic as phase2_pipeline.py)
ship_meta = master[["ship_id", "ship_type"]].drop_duplicates().set_index("ship_id")
rng = np.random.default_rng(SEED)
test_ships = set()
for stype, grp in ship_meta.groupby("ship_type"):
    n_test = max(1, round(len(grp) * 0.20))
    chosen = rng.choice(grp.index.tolist(), size=n_test, replace=False)
    test_ships.update(chosen.tolist())

train_ships = set(ship_meta.index) - test_ships
assert train_ships.isdisjoint(test_ships), "Leakage detected!"

train_df = master[master["ship_id"].isin(train_ships)].copy().reset_index(drop=True)
test_df = master[master["ship_id"].isin(test_ships)].copy().reset_index(drop=True)

print("=" * 70)
print("STAGE 2A: MODEL A WEATHER CLASSIFIER EVALUATION")
print("=" * 70)

# STEP 1: Training weather class distribution
print("\n--- STEP 1: Training Weather Class Distribution (96 train ships, 1152 rows) ---")
tr_counts = train_df[A_TARGET].value_counts()
tr_pcts = train_df[A_TARGET].value_counts(normalize=True) * 100
for c in WEATHER_CLASSES:
    cnt = tr_counts.get(c, 0)
    pct = tr_pcts.get(c, 0.0)
    print(f"  {c:8s}: {cnt:4d} rows ({pct:6.2f}%)")

te_counts = test_df[A_TARGET].value_counts()
te_pcts = test_df[A_TARGET].value_counts(normalize=True) * 100
print("\n--- Test Set Weather Class Distribution (24 test ships, 288 rows) ---")
for c in WEATHER_CLASSES:
    cnt = te_counts.get(c, 0)
    pct = te_pcts.get(c, 0.0)
    print(f"  {c:8s}: {cnt:4d} rows ({pct:6.2f}%)")

# Preprocessing for Model A
X_train_raw = train_df[A_FEATS].values.astype(float)
y_train = le_weather.transform(train_df[A_TARGET].values)
X_test_raw = test_df[A_FEATS].values.astype(float)
y_test = le_weather.transform(test_df[A_TARGET].values)

# Scaler for Logistic Regression (fit only on train)
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train_raw)
X_test_scaled = scaler.transform(X_test_raw)

# Majority baseline evaluation on test set
maj_class_idx = train_df[A_TARGET].value_counts().index[0]
maj_class_num = le_weather.transform([maj_class_idx])[0]
maj_preds = np.full(len(y_test), maj_class_num)
maj_acc = accuracy_score(y_test, maj_preds)
maj_macro_f1 = f1_score(y_test, maj_preds, average="macro", zero_division=0)
maj_weighted_f1 = f1_score(y_test, maj_preds, average="weighted", zero_division=0)
maj_cm = confusion_matrix(y_test, maj_preds, labels=[0, 1, 2])

print("\n--- Majority Baseline (Predict majority train class: %s) ---" % maj_class_idx)
print(f"  Accuracy:    {maj_acc:.4f} ({maj_acc*100:.2f}%)")
print(f"  Macro-F1:    {maj_macro_f1:.4f}")
print(f"  Weighted-F1: {maj_weighted_f1:.4f}")
print(f"  Confusion Matrix:\n{maj_cm}")

# STEP 2: Multinomial Logistic Regression Baseline
print("\n--- STEP 2: Multinomial Logistic Regression Baseline ---")
logreg = LogisticRegression(
    solver="lbfgs",
    max_iter=1000,
    random_state=SEED,
    class_weight="balanced"  # balanced handles class frequencies
)
logreg.fit(X_train_scaled, y_train)
lr_preds = logreg.predict(X_test_scaled)

lr_acc = accuracy_score(y_test, lr_preds)
lr_macro_f1 = f1_score(y_test, lr_preds, average="macro", zero_division=0)
lr_weighted_f1 = f1_score(y_test, lr_preds, average="weighted", zero_division=0)
lr_cm = confusion_matrix(y_test, lr_preds, labels=[0, 1, 2])

print(f"  Accuracy:    {lr_acc:.4f} ({lr_acc*100:.2f}%)")
print(f"  Macro-F1:    {lr_macro_f1:.4f}")
print(f"  Weighted-F1: {lr_weighted_f1:.4f}")
print(f"  Confusion Matrix:\n{lr_cm}")

# STEP 3: Retrain/Tune XGBoost with Sample Weights & GroupKFold CV
print("\n--- STEP 3: GroupKFold CV (5-Fold by ship_id) Hyperparameter Tuning for XGBoost ---")
# Compute sample weights on training set: 1 / class_frequency
class_freqs = train_df[A_TARGET].value_counts(normalize=True)
# map frequency to each sample in train_df
train_class_freq = train_df[A_TARGET].map(class_freqs).values
sample_weights_train = 1.0 / train_class_freq
# normalize weights so mean = 1.0
sample_weights_train = sample_weights_train / np.mean(sample_weights_train)

# Grid parameters
param_grid = []
for md in [2, 3, 4]:
    for ne in [50, 100, 200]:
        for lr in [0.05, 0.1, 0.2]:
            param_grid.append({"max_depth": md, "n_estimators": ne, "learning_rate": lr})

# GroupKFold by ship_id on training set only (96 ships)
gkf = GroupKFold(n_splits=5)
train_ship_ids = train_df["ship_id"].values

cv_results = []

for params in param_grid:
    fold_macro_f1s = []
    fold_accs = []
    for tr_idx, val_idx in gkf.split(X_train_raw, y_train, groups=train_ship_ids):
        X_cv_tr, y_cv_tr = X_train_raw[tr_idx], y_train[tr_idx]
        w_cv_tr = sample_weights_train[tr_idx]
        X_cv_val, y_cv_val = X_train_raw[val_idx], y_train[val_idx]
        
        clf = xgb.XGBClassifier(
            objective="multi:softprob",
            eval_metric="mlogloss",
            max_depth=params["max_depth"],
            n_estimators=params["n_estimators"],
            learning_rate=params["learning_rate"],
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=SEED,
            n_jobs=-1
        )
        clf.fit(X_cv_tr, y_cv_tr, sample_weight=w_cv_tr)
        val_preds = clf.predict(X_cv_val)
        fold_macro_f1s.append(f1_score(y_cv_val, val_preds, average="macro", zero_division=0))
        fold_accs.append(accuracy_score(y_cv_val, val_preds))
        
    mean_macro_f1 = np.mean(fold_macro_f1s)
    std_macro_f1 = np.std(fold_macro_f1s)
    mean_acc = np.mean(fold_accs)
    cv_results.append({
        "params": params,
        "mean_macro_f1": mean_macro_f1,
        "std_macro_f1": std_macro_f1,
        "mean_acc": mean_acc
    })

# Sort by mean_macro_f1 descending
cv_results.sort(key=lambda x: x["mean_macro_f1"], reverse=True)
best_cv = cv_results[0]
best_params = best_cv["params"]

print("  Top 3 Grid Search Results (by CV Macro-F1):")
for i, res in enumerate(cv_results[:3]):
    print(f"    {i+1}. params={res['params']} | CV Macro-F1: {res['mean_macro_f1']:.4f} +/- {res['std_macro_f1']:.4f} | CV Acc: {res['mean_acc']:.4f}")

print(f"\n  Selected Best Hyperparameters: {best_params}")
print(f"  CV Mean Macro-F1: {best_cv['mean_macro_f1']:.4f} (+/- {best_cv['std_macro_f1']:.4f})")
print(f"  Scoring Metric Used: Macro-F1")

# Fit tuned XGBoost on full 96-ship training set with sample_weight
tuned_xgb = xgb.XGBClassifier(
    objective="multi:softprob",
    eval_metric="mlogloss",
    max_depth=best_params["max_depth"],
    n_estimators=best_params["n_estimators"],
    learning_rate=best_params["learning_rate"],
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=SEED,
    n_jobs=-1
)
tuned_xgb.fit(X_train_raw, y_train, sample_weight=sample_weights_train)

# STEP 4: Evaluate Tuned XGBoost
print("\n--- STEP 4: Evaluation of Tuned XGBoost ---")
tuned_preds = tuned_xgb.predict(X_test_raw)
tuned_acc = accuracy_score(y_test, tuned_preds)
tuned_macro_f1 = f1_score(y_test, tuned_preds, average="macro", zero_division=0)
tuned_weighted_f1 = f1_score(y_test, tuned_preds, average="weighted", zero_division=0)
tuned_cm = confusion_matrix(y_test, tuned_preds, labels=[0, 1, 2])

print("  Primary Ship Holdout (24 test ships, 288 rows):")
print(f"    Accuracy:    {tuned_acc:.4f} ({tuned_acc*100:.2f}%)")
print(f"    Macro-F1:    {tuned_macro_f1:.4f}")
print(f"    Weighted-F1: {tuned_weighted_f1:.4f}")
print(f"    Confusion Matrix:\n{tuned_cm}")

# Four Route Holdouts Evaluation for both Logistic Regression and Tuned XGBoost
ROUTES = sorted(master["route_id"].unique().tolist())
print("\n--- Route Holdouts Evaluation ---")

route_eval_xgb = {}
route_eval_lr = {}

for r in ROUTES:
    r_train = master[master["route_id"] != r].copy().reset_index(drop=True)
    r_test  = master[master["route_id"] == r].copy().reset_index(drop=True)
    
    X_r_train = r_train[A_FEATS].values.astype(float)
    y_r_train = le_weather.transform(r_train[A_TARGET].values)
    X_r_test  = r_test[A_FEATS].values.astype(float)
    y_r_test  = le_weather.transform(r_test[A_TARGET].values)
    
    # Weights for route train
    r_freq = r_train[A_TARGET].value_counts(normalize=True)
    r_weights = (1.0 / r_train[A_TARGET].map(r_freq).values)
    r_weights = r_weights / np.mean(r_weights)
    
    # Train tuned XGB on route train
    m_xgb = xgb.XGBClassifier(
        objective="multi:softprob",
        eval_metric="mlogloss",
        max_depth=best_params["max_depth"],
        n_estimators=best_params["n_estimators"],
        learning_rate=best_params["learning_rate"],
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=SEED,
        n_jobs=-1
    )
    m_xgb.fit(X_r_train, y_r_train, sample_weight=r_weights)
    p_xgb = m_xgb.predict(X_r_test)
    
    xgb_acc = accuracy_score(y_r_test, p_xgb)
    xgb_mf1 = f1_score(y_r_test, p_xgb, average="macro", zero_division=0)
    xgb_wf1 = f1_score(y_r_test, p_xgb, average="weighted", zero_division=0)
    route_eval_xgb[r] = {"accuracy": xgb_acc, "macro_f1": xgb_mf1, "weighted_f1": xgb_wf1}
    
    # Train Logistic Regression on route train
    r_scaler = StandardScaler()
    X_r_train_sc = r_scaler.fit_transform(X_r_train)
    X_r_test_sc = r_scaler.transform(X_r_test)
    m_lr = LogisticRegression(
        solver="lbfgs",
        max_iter=1000,
        random_state=SEED,
        class_weight="balanced"
    )
    m_lr.fit(X_r_train_sc, y_r_train)
    p_lr = m_lr.predict(X_r_test_sc)
    
    lr_acc_r = accuracy_score(y_r_test, p_lr)
    lr_mf1_r = f1_score(y_r_test, p_lr, average="macro", zero_division=0)
    lr_wf1_r = f1_score(y_r_test, p_lr, average="weighted", zero_division=0)
    route_eval_lr[r] = {"accuracy": lr_acc_r, "macro_f1": lr_mf1_r, "weighted_f1": lr_wf1_r}
    
    print(f"  Route: {r:20s}")
    print(f"    Tuned XGB  -> Acc: {xgb_acc:.4f}, Macro-F1: {xgb_mf1:.4f}, Weighted-F1: {xgb_wf1:.4f}")
    print(f"    LogReg     -> Acc: {lr_acc_r:.4f}, Macro-F1: {lr_mf1_r:.4f}, Weighted-F1: {lr_wf1_r:.4f}")

# STEP 5: Comparison of Candidate Models
print("\n--- STEP 5: Candidate Model Comparison on Primary Ship Holdout ---")
prev_acc = 0.3090
prev_macro_f1 = 0.2884
prev_weighted_f1 = 0.2912

print(f"{'Model':<30} | {'Accuracy':<10} | {'Macro-F1':<10} | {'Weighted-F1':<12}")
print("-" * 70)
print(f"{'Majority baseline':<30} | {maj_acc:<10.4f} | {maj_macro_f1:<10.4f} | {maj_weighted_f1:<12.4f}")
print(f"{'Logistic regression':<30} | {lr_acc:<10.4f} | {lr_macro_f1:<10.4f} | {lr_weighted_f1:<12.4f}")
print(f"{'Previous XGBoost':<30} | {prev_acc:<10.4f} | {prev_macro_f1:<10.4f} | {prev_weighted_f1:<12.4f}")
print(f"{'Tuned/weighted XGBoost':<30} | {tuned_acc:<10.4f} | {tuned_macro_f1:<10.4f} | {tuned_weighted_f1:<12.4f}")

# STEP 6: Production Model Selection
print("\n--- STEP 6: Production Model Selection Rule ---")
print("Rule criteria:")
print("1. Prefer the model with strongest primary ship-holdout macro-F1, provided it at least matches majority baseline in accuracy.")
print("2. If tuned XGBoost does not outperform logistic regression, do not force XGBoost.")
print("3. If neither learned model beats majority baseline, retain majority-class model as production baseline.")
print("4. Do not hide the previous 30.9% XGBoost result.")

selected_model_name = ""
selected_model_bundle = {}

# Check candidates against majority baseline
candidates = []
# Can tuned XGB beat or match majority baseline?
if tuned_acc >= maj_acc:
    candidates.append(("Tuned XGBoost", tuned_macro_f1, tuned_acc, tuned_xgb, None))
# Can LogReg beat or match majority baseline?
if lr_acc >= maj_acc:
    candidates.append(("Logistic Regression", lr_macro_f1, lr_acc, logreg, scaler))

if len(candidates) > 0:
    # Sort candidates by macro-F1
    candidates.sort(key=lambda x: x[1], reverse=True)
    selected_name, sel_mf1, sel_acc, sel_model, sel_scaler = candidates[0]
    selected_model_name = selected_name
    print(f"Selection: {selected_name} beats or matches majority baseline ({sel_acc:.4f} >= {maj_acc:.4f}) with Macro-F1 = {sel_mf1:.4f}.")
    final_artifact = {
        "model_type": selected_name,
        "model": sel_model,
        "scaler": sel_scaler,
        "label_encoder": le_weather,
        "features": A_FEATS,
        "classes": WEATHER_CLASSES,
        "best_params": best_params if "XGBoost" in selected_name else None,
        "test_accuracy": sel_acc,
        "test_macro_f1": sel_mf1
    }
else:
    # Neither learned model beats or matches majority baseline
    selected_model_name = "Majority Baseline (Calm)"
    print(f"Selection: Neither learned model matched majority baseline accuracy ({maj_acc:.4f}).")
    print(f"Tuned XGB: {tuned_acc:.4f}, LogReg: {lr_acc:.4f}. Retaining Majority-class model as production baseline.")
    dummy_maj = DummyClassifier(strategy="constant", constant=maj_class_num)
    dummy_maj.fit(X_train_raw, y_train)
    final_artifact = {
        "model_type": "Majority Baseline Classifier",
        "model": dummy_maj,
        "scaler": None,
        "label_encoder": le_weather,
        "features": A_FEATS,
        "classes": WEATHER_CLASSES,
        "majority_class": maj_class_idx,
        "test_accuracy": maj_acc,
        "test_macro_f1": maj_macro_f1
    }

# Save models/weather_final.joblib
joblib.dump(final_artifact, f"{MODELS_DIR}/weather_final.joblib")
print(f"Saved production artifact: {MODELS_DIR}/weather_final.joblib")

# STEP 7: Feature Importance Plot
print("\n--- STEP 7: Generating Feature Importance Figure ---")
fig, ax = plt.subplots(figsize=(9, 5))
if selected_model_name == "Tuned XGBoost" or ("XGBoost" in selected_model_name):
    importances = tuned_xgb.feature_importances_
    idx = np.argsort(importances)
    ax.barh([A_FEATS[i] for i in idx], importances[idx], color="steelblue")
    ax.set_xlabel("Importance (gain)")
    ax.set_title(f"Model A Feature Importance (Tuned XGBoost, Ship Holdout)")
elif selected_model_name == "Logistic Regression":
    # Multi-class logreg has coef_ shape (n_classes, n_features)
    # Use mean absolute coefficient across classes
    mean_coef = np.mean(np.abs(logreg.coef_), axis=0)
    idx = np.argsort(mean_coef)
    ax.barh([A_FEATS[i] for i in idx], mean_coef[idx], color="darkorange")
    ax.set_xlabel("Mean Absolute Standardized Coefficient")
    ax.set_title("Model A Feature Importance (Logistic Regression Coefficients)")
else:
    # Majority baseline selected, show tuned XGBoost feature importances with clear disclaimer
    importances = tuned_xgb.feature_importances_
    idx = np.argsort(importances)
    ax.barh([A_FEATS[i] for i in idx], importances[idx], color="slategray")
    ax.set_xlabel("Importance (gain)")
    ax.set_title("Model A Feature Importance (Tuned XGBoost - Reference Only; Majority Baseline Selected)")

plt.tight_layout()
feat_imp_path = f"{FIGS_DIR}/model_a_feature_importance_v2.png"
fig.savefig(feat_imp_path, dpi=120)
plt.close()
print(f"Saved: {feat_imp_path}")

# STEP 8: Confusion Matrix Plot
print("\n--- STEP 8: Generating Confusion Matrix Figure ---")
fig, ax = plt.subplots(figsize=(6, 5))
if selected_model_name == "Tuned XGBoost":
    cm_to_plot = tuned_cm
    plot_title = "Model A Confusion Matrix: Tuned XGBoost"
elif selected_model_name == "Logistic Regression":
    cm_to_plot = lr_cm
    plot_title = "Model A Confusion Matrix: Logistic Regression"
else:
    cm_to_plot = maj_cm
    plot_title = f"Model A Confusion Matrix: Majority Baseline ({maj_class_idx})"

im = ax.imshow(cm_to_plot, cmap="Blues")
ax.set_xticks(range(3)); ax.set_yticks(range(3))
ax.set_xticklabels(WEATHER_CLASSES); ax.set_yticklabels(WEATHER_CLASSES)
ax.set_xlabel("Predicted")
ax.set_ylabel("Actual")
ax.set_title(plot_title)
for i in range(3):
    for j in range(3):
        ax.text(j, i, str(cm_to_plot[i, j]), ha="center", va="center", color="black")
plt.colorbar(im, ax=ax)
plt.tight_layout()
cm_path = f"{FIGS_DIR}/model_a_confusion_matrix_v2.png"
fig.savefig(cm_path, dpi=120)
plt.close()
print(f"Saved: {cm_path}")

# Update docs/phase2_metrics.json with Stage 2A results
metrics_path = f"{DOCS_DIR}/phase2_metrics.json"
if os.path.exists(metrics_path):
    with open(metrics_path, "r") as f:
        all_metrics = json.load(f)
else:
    all_metrics = {}

all_metrics["stage_2a_weather"] = {
    "training_class_distribution": {c: int(tr_counts.get(c, 0)) for c in WEATHER_CLASSES},
    "training_class_percentages": {c: round(float(tr_pcts.get(c, 0.0)), 2) for c in WEATHER_CLASSES},
    "majority_baseline": {
        "predicted_class": maj_class_idx,
        "accuracy": round(float(maj_acc), 4),
        "macro_f1": round(float(maj_macro_f1), 4),
        "weighted_f1": round(float(maj_weighted_f1), 4)
    },
    "logistic_regression": {
        "accuracy": round(float(lr_acc), 4),
        "macro_f1": round(float(lr_macro_f1), 4),
        "weighted_f1": round(float(lr_weighted_f1), 4),
        "route_holdouts": {r: {k: round(float(v), 4) for k, v in m.items()} for r, m in route_eval_lr.items()}
    },
    "previous_xgboost": {
        "accuracy": prev_acc,
        "macro_f1": prev_macro_f1,
        "weighted_f1": prev_weighted_f1
    },
    "tuned_xgboost": {
        "best_hyperparameters": best_params,
        "cv_mean_macro_f1": round(float(best_cv["mean_macro_f1"]), 4),
        "cv_std_macro_f1": round(float(best_cv["std_macro_f1"]), 4),
        "scoring_metric": "macro-F1",
        "primary_ship_holdout": {
            "accuracy": round(float(tuned_acc), 4),
            "macro_f1": round(float(tuned_macro_f1), 4),
            "weighted_f1": round(float(tuned_weighted_f1), 4)
        },
        "route_holdouts": {r: {k: round(float(v), 4) for k, v in m.items()} for r, m in route_eval_xgb.items()}
    },
    "production_model_selected": selected_model_name,
    "beats_majority_baseline": bool((tuned_acc > maj_acc) if "XGBoost" in selected_model_name else (lr_acc > maj_acc if "Logistic" in selected_model_name else False)),
    "matches_majority_baseline": bool((tuned_acc >= maj_acc) if "XGBoost" in selected_model_name else (lr_acc >= maj_acc if "Logistic" in selected_model_name else True)),
    "improves_over_previous_xgb": bool(tuned_acc > prev_acc)
}

with open(metrics_path, "w") as f:
    json.dump(all_metrics, f, indent=2)

print("\nUpdated docs/phase2_metrics.json with Stage 2A results.")
print("STAGE 2A EXECUTION COMPLETE.")
