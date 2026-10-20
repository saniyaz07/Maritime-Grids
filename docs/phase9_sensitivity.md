# Phase 9 Candidate 1: Multi-Dimensional Parametric Sensitivity & Robustness Engine

## 1. Executive Purpose & Scope

Phase 9 Candidate 1 implements a high-performance, deterministic parametric sensitivity, elasticity, break-even, and multi-dimensional grid analysis engine for the maritime clean-energy microgrid framework.

This subsystem quantifies how perturbations in macroeconomic conditions (fuel prices, carbon compliance penalties, discount/hurdle rates, battery replacement costs) and operational/environmental variables (Global Horizontal Irradiance, auxiliary hotel loads) impact clean-energy investment economics and physical sizing feasibility.

### Strictly Scoped Functionality:
- **One-At-A-Time (OAT) Sensitivity Sweeps:** Deterministic 1D parameter sweeps evaluating financial and physical displacement trajectories.
- **Normalized Elasticity Coefficients:** Dimensionless elasticity scores $(\Delta Y / Y_0) / (\Delta X / X_0)$ with explicit handling of zero baselines and zero deltas.
- **Deterministic 1D Break-Even Solvers:** Numerical Brent root-finding ($g(X) = Y(X) - Y_{\text{target}} = 0$) discovering financial break-even points (e.g., minimum fuel price for $\text{NPV} \ge 0$).
- **2D Parameter Grid & Contour Data Generation:** Orthogonal 2D parameter lattices producing structured matrices for contour and sensitivity surface mapping.
- **Strict Computational Budgeting:** Enforced maximum limit of 1,000 evaluations per execution with runtime latency $< 1.0\text{ second}$.

---

## 2. Architectural Boundaries & Upstream Integration

Phase 9 Candidate 1 strictly adheres to the repository's 18 immutable boundary rules:
- **Phases 0 through 8 are completely frozen, verified, and untouched.**
- **Zero Financial Equation Duplication:** All lifecycle cash flows, net present value, internal rate of return, simple/discounted payback, and levelized cost of energy are calculated exclusively by delegating to Phase 7:
  - `phase7_economics.evaluate_clean_energy_investment`
  - `phase7_contracts.FinancialParameters`
  - `phase7_contracts.InvestmentAppraisalResult`
- **Zero Physical Simulation Duplication:** Sizing feasibility, solar yield, usable battery capacity, and auxiliary load coverage are evaluated exclusively by delegating to Phase 8:
  - `phase8_optimizer.evaluate_single_sizing_candidate`
  - `phase8_contracts.OptimizationParameters`
  - `phase8_contracts.OptimizationCandidate`
- **Zero ML Model Retraining:** Frozen Phase 2 models (`battery_soc_lstm.pt`, `battery_soh_final.joblib`, `fuel_xgb.joblib`, `weather_final.joblib`) remain cryptographically identical.

---

## 3. Frozen Standard Default Parameter Ranges

| Parameter Name | Target Dimension | Default Bound | Discrete Step | Mode |
| :--- | :--- | :--- | :--- | :--- |
| `fuel_price_usd_per_l` | Macroeconomic | $0.50\times$ to $1.50\times$ baseline | $0.05\times$ (5%) | Relative Multiplier |
| `carbon_price_usd_per_tonne` | Macroeconomic | $\$0.0$ to $\$200.0/\text{tCO}_2$ | $\$10.0/\text{tCO}_2$ | Absolute ($/tCO2) |
| `discount_rate` | Financial Hurdle | $0.04$ to $0.16$ (4% to 16%) | $0.01$ (1%) | Absolute Fraction |
| `battery_replacement_cost_usd_per_kwh` | Technology Inflation | $-0.40$ to $+0.40$ (-40% to +40%) | $0.10$ (10%) | Relative Delta |
| `daily_ghi_kwh_per_m2` | Environmental | $-0.25$ to $+0.25$ (-25% to +25%) | $0.05$ (5%) | Relative Delta |
| `auxiliary_energy_demand_kwh` | Operational Load | $-0.25$ to $+0.25$ (-25% to +25%) | $0.05$ (5%) | Relative Delta |

---

## 4. Methodologies

### 4.1 One-At-A-Time (OAT) Sensitivity
For each sweep point:
1. The unperturbed baseline candidate is established.
2. Exactly one parameter is varied along its discrete grid, holding all other variables constant.
3. If the parameter is financial, Phase 7 `evaluate_clean_energy_investment` is invoked reusing pre-computed physical displacement values ($E_{\text{clean}}$, $\Delta V_{\text{fuel}}$, $\Delta \text{CO}_2$).
4. If the parameter is physical (GHI, hotel load), Phase 8 `evaluate_single_sizing_candidate` is invoked.
5. Absolute change ($\Delta Y = Y - Y_0$), relative change ($\Delta Y / Y_0$), and normalized elasticity are recorded.

### 4.2 Normalized Elasticity
Elasticity measures percentage responsiveness:
$$\epsilon = \frac{(Y - Y_0) / Y_0}{(X - X_0) / X_0}$$
Mathematically undefined edge cases return `None` and an explicit diagnostic status:
- $Y_0 = 0 \implies \text{BASELINE\_ZERO}$
- $X_0 = 0 \implies \text{PARAMETER\_BASELINE\_ZERO}$
- $X = X_0 \implies \text{ZERO\_PARAMETER\_CHANGE}$
- $Y = \text{None} \implies \text{METRIC\_UNAVAILABLE}$
- Normal valid computation $\implies \text{ELASTICITY\_COMPUTED}$

### 4.3 Deterministic 1D Brent Break-Even Solvers
Solves $g(X) = Y(X) - Y_{\text{target}} = 0$ over $[a, b]$ using `scipy.optimize.brentq`:
- Evaluates $g(a)$ and $g(b)$ at boundary endpoints.
- If $g(a) == 0$ or $g(b) == 0$, boundary root is returned immediately.
- If $g(a) \cdot g(b) > 0$, returns `NO_ROOT_IN_BOUNDS`.
- If valid bracket exists, converges to root within numerical tolerance ($10^{-6}$).
- Every evaluation is counted against the execution budget.

### 4.4 2D Parameter Grid Generation
Generates orthogonal grid $(X_i, Y_j)$:
- Validates that total grid nodes $N_X \times N_Y \le 1,000$.
- Rejects upfront if requested grid exceeds budget with `status = "BUDGET_EXCEEDED"`.
- Returns both flat point lists and indexed 2D matrices organized as `matrix[metric][y_idx][x_idx]`.

---

## 5. Computational Budget & Determinism

- **Evaluation Budget Counter:** The `EvaluationBudgetCounter` tracks every invocation of upstream evaluation routines. If evaluations reach 1,000, execution halts with `EvaluationBudgetExceededError` or returns `STATUS_BUDGET_EXCEEDED`.
- **Latency Target:** Execution of standard default sweeps requires $< 0.15\text{ seconds}$ on standard hardware, strictly well below the authorized $1.0\text{ second}$ ceiling.
- **Determinism:** Repeated identical executions produce bitwise identical numerical outputs. No stochastic or unseeded random processes are used.

---

## 6. Numerical Reconciliation

Phase 9 Candidate 1 was reconciled against the canonical Tanker Ship benchmark:
- Vessel: Tanker Ship (14,000 DWT)
- Route: Warri-Bonny (40.5 h, GHI = 3.469 kWh/m2)
- Hardware: Solar PV = $100\text{ m}^2$, Battery Pack = $200\text{ kWh}$
- Baseline Financial Parameters: Default Phase 7 parameters ($r = 8\%$, $P_{\text{fuel}} = \$1.0/\text{L}$)

### Benchmark Comparison:
- **Baseline NPV:**
  - Upstream Phase 8: $-\$173,495.40$
  - Phase 9 Sensitivity: $-\$173,495.40$
  - Absolute Difference: $\mathbf{0.0\text{ USD}}$ ($\le 10^{-6}$)
- **Baseline LCOE:**
  - Upstream Phase 8: $\$2.128134/\text{kWh}$
  - Phase 9 Sensitivity: $\$2.128134/\text{kWh}$
  - Absolute Difference: $\mathbf{0.0\text{ USD/kWh}}$ ($\le 10^{-6}$)
- **Baseline IRR:**
  - Upstream Phase 8: $-23.3305\%$ (`IRR_UNIQUE_ROOT`)
  - Phase 9 Sensitivity: $-23.3305\%$ (`IRR_UNIQUE_ROOT`)
  - Absolute Difference: $\mathbf{0.0\%}$ ($\le 10^{-6}$)

---

## 7. Verification & Test Suite Summary

- **New Dedicated Phase 9 Tests:** 38 tests in `tests/test_phase9_sensitivity.py`.
- **Existing Regression Tests:** 290 tests passing (Phases 3A–3G, 6, 7, 8).
- **Combined Repository Tests:** **328 / 328 PASSED** (0 failures, 0 errors, 0 skips).
- **Frozen Models:** All 4 Phase 2 models verified bitwise identical via SHA-256.
- **Raw Data Integrity:** 6,228 files in `data/raw/` verified untouched.
