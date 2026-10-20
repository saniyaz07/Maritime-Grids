# Model C — Battery SOC LSTM Training & Evaluation Report

**Generated:** 2026-09-27  
**Stage:** Stage 2C SOC LSTM (Baseline Unseen-Cell Generalization)  
**Status:** Complete  

---

## 1. Dataset Partitioning & Cycle Counts

| Partition | Cells | Cycles | Sequences | Dimensions ($X$) | Target ($y$) |
|---|---|---|---|---|---|
| **Training** | B0005, B0006 | 268 cycles (134 each) | 2,798 | `(2798, 50, 3)` | `(2798,)` |
| **Validation** | B0005, B0006 | 68 cycles (34 each) | 724 | `(724, 50, 3)` | `(724,)` |
| **Final Test** | **B0007** (Unseen cell) | 126 cycles | 1,311 | `(1311, 50, 3)` | `(1311,)` |
| **Total** | 3 cells | 462 cycles | 4,833 | — | — |

* All cycles were strictly partitioned: no cycle spans train, validation, or test.
* Test cell **B0007 was strictly held out**: completely absent from training, validation, early stopping, and hyperparameter tuning.

---

## 2. Target Ground-Truth Definition: Nominal-Reference SOC

* **Formula**:
  $$\text{SOC}(t) = \text{clip}\left(1.0 - \frac{Q_{\text{discharged}}(t)}{2.0\text{ Ah}}, \, 0.0, \, 1.0\right)$$
* **Designation**: **Nominal-reference SOC** (based on fixed 2.0 Ah fresh rating).
* *Important Distinction*: This is **NOT** operational usable SOC ($1 - Q/C_{\text{actual}}$). For degraded cycles, available capacity is less than 2.0 Ah; thus, full discharge ends before reaching 0.0.

---

## 3. Scaling & Preprocessing Integrity

* The input `.npz` files contain **raw physical features**: `[Voltage_measured, Current_measured, Temperature_measured]`.
* The `StandardScaler` from `data/processed/battery/soc_scaler.joblib` was fitted **strictly on the 2,798 training sequences**:
  * Means: `[3.4984, 1.9367, 32.5747]`
  * Stds: `[0.2196, 0.3803, 3.6429]`
* The same frozen scaler was applied to transform Training, Validation, and Test sets.
* **Zero scaler fitting** was performed on validation or B0007 test data.

---

## 4. Model Architecture & Training Configuration

* **Architecture**:
  * Input Size: 3 (`Voltage_measured`, `Current_measured`, `Temperature_measured`)
  * Recurrent Backbone: 2-layer LSTM (`hidden_size=64`, `dropout=0.2`, `batch_first=True`)
  * Head: `Linear(64 -> 1)` on final timestep representation
* **Training Hyperparameters**:
  * Loss: `MSELoss`
  * Optimizer: `Adam(lr=0.001)`
  * Batch Size: 64
  * Maximum Epochs: 20
  * Early Stopping: Patience of 5 epochs on Validation MSE
  * Random Seed: 42
  * Execution Device: CPU

---

## 5. Training History & Model Selection

* **Epochs Completed**: 16
* **Best Validation Epoch**: **Epoch 11**
* **Best Validation Loss (MSE)**: **0.007549**
* Checkpointing restored the exact weights from Epoch 11 before final B0007 test evaluation.

---

## 6. Performance Evaluation Metrics

| Partition | RMSE | MAE | R² |
|---|---|---|---|
| **Training (B0005/B0006)** | **0.0788** | **0.0617** | **0.8728** |
| **Validation (B0005/B0006)** | **0.0868** | **0.0727** | **0.7703** |
| **Final Test (B0007 Unseen Cell)** | **0.0678** | **0.0539** | **0.9089** |

---

## 7. Prediction Range Analysis (Raw Unclipped Model Output)

* **Train**: Actual [0.0884, 0.8743] | Predicted [0.0334, 0.8874]
* **Validation**: Actual [0.3136, 0.8743] | Predicted [0.2263, 0.8334]
* **B0007 Test**: Actual [0.0980, 0.8756] | Predicted [0.0922, 0.8894]
* *Note*: Raw predictions stay closely bounded within $[0, 1]$. No artificial clipping was applied to alter metric evaluations.

---

## 8. Diagnostic Error Analysis on B0007

### 8.1 Performance by SOC Bins

| SOC Range | Sample Count | MAE | RMSE | Mean Residual |
|---|---|---|---|---|
| **0.0 – 0.2** | 111 | 0.0988 | 0.1091 | -0.0971 |
| **0.2 – 0.4** | 347 | 0.0560 | 0.0693 | -0.0323 |
| **0.4 – 0.6** | 316 | 0.0644 | 0.0768 | +0.0136 |
| **0.6 – 0.8** | 347 | 0.0430 | 0.0525 | -0.0091 |
| **0.8 – 1.0** | 190 | 0.0264 | 0.0336 | +0.0228 |

### 8.2 Error Correlations with Physical Signals
* Correlation with Terminal Voltage: $r = -0.1709$
* Correlation with Current: $r = +0.0411$
* Correlation with Temperature: $r = +0.2566$
* Correlation with Cycle ID: $r = -0.2007$

---

## 9. Per-Cycle Performance Summary (B0007)
* Per-cycle metrics saved to `data/processed/battery/soc_test_cycle_metrics.csv` across all 126 B0007 cycles.
* Mean per-cycle MAE: **0.0566** (min: 0.0154, max: 0.1112).
* Mean per-cycle RMSE: **0.0646** (min: 0.0172, max: 0.1166).

---

## 10. Limitations

1. **Unseen-Cell Sample Size**: Only cell B0007 was available as the unseen-cell test set under the room-temperature condition.
2. **Raw File Truncation**: B0007 is limited to 126 raw measurement files (raw archive stops at `06191.csv`).
3. **Missing B0018 Measurements**: B0018 lacks raw measurement CSV files and was excluded from time-series modeling.
4. **Nominal-Reference Metric**: Nominal-reference SOC measures remaining charge against a pristine 2.0 Ah capacity; operational marine simulation should pair this with SOH tracking to establish usable SOC limits.
