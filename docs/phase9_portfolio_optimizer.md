# Phase 9 Candidate 3: Fleet Portfolio Decarbonization Capital Allocation Engine

## 1. Executive Purpose & Scope

Phase 9 Candidate 3 introduces the **Fleet Portfolio Decarbonization Capital Allocation Layer** for the maritime clean-energy microgrid simulation framework.

Operating as a pure portfolio orchestration and constrained optimization layer, Candidate 3 allocates a finite, user-specified capital expenditure (CAPEX) budget across a fleet of maritime vessels to maximize annual fleet-wide carbon dioxide ($\text{CO}_2$) displacement.

### Key Architectural Characteristics:
- **Consumer of Pre-Evaluated Candidates:** Candidate 3 evaluates portfolios consisting strictly of pre-evaluated Phase 8 `OptimizationCandidate` objects. It performs **zero** simulation or sizing search internally.
- **No Full-Grid Phase 8 Search:** Candidate 3 **does not** call `optimize_system_sizing()`, avoiding the combinatorial grid evaluation limit (e.g. Tanker Ship's default 138,432-point grid).
- **Primary Objective:** Maximize total annual fleet $\text{CO}_2$ displacement ($\sum \Delta \text{CO}_{2, \text{annual}}$).
- **Secondary Metrics:** Aggregates and reports total CAPEX, total NPV, total fuel displacement, and retrofit count as straightforward linear sums of existing Phase 8 metrics.
- **Representative Fleet Universe:** Initial v1 scope is defined over the repository's **four representative canonical vessel archetypes** (`Tanker Ship`, `Oil Service Boat`, `Fishing Trawler`, `Surfer Boat`), yielding at most $2^4 = 16$ portfolio combinations to enumerate.

---

## 2. Architectural Boundaries & Immutability

```
+-----------------------------------------------------------------------------------+
|                        Phase 9 Candidate 3 Portfolio Engine                       |
|   (Deterministic Exhaustive Subset Enumeration — Bounded Space <= 16 Subsets)     |
+----------------------------------------+------------------------------------------+
                                         |
               +-------------------------+-------------------------+
               | (Pre-Evaluated Candidates)                        | (No Candidate 1 or 2 Calls)
               v                                                   v
+-------------------------------+                 +---------------------------------+
|      Phase 8 Sizing Outputs   |                 |     Phase 7 Lifecycle Cash Flows|
|  - OptimizationCandidate      |                 |  - Preserved exactly via Phase 8|
|  - Annual Fuel/CO2 Displaced  |                 |  - No new financial formulas    |
|  - Total Overnight CAPEX_0    |                 |  - Linear portfolio NPV sum     |
+-------------------------------+                 +---------------------------------+
```

### Critical Rules:
1. **Zero Upstream Modifications:** Phases 0 through 8, Candidate 1, and Candidate 2 remain completely untouched.
2. **No Physical or Financial Reimplementation:** Candidate 3 contains no equations for solar yield, battery dynamics, generator fuel curves, NPV, IRR, LCOE, or payback periods.
3. **No Candidate 1 or 2 Dependencies:** Operates directly on Phase 8 candidates to avoid double-counting or speed-scaling baseline inconsistencies.
4. **No Arbitrary Default Budget:** Total portfolio CAPEX budget (`total_portfolio_capex_budget_usd`) must be explicitly supplied by the caller.

---

## 3. Mathematical Formulation

### 3.1 Decision Variables & Mutual Exclusion
Let $\mathcal{V} = \{1, \ldots, K\}$ represent the set of distinct vessel slots ($K \le 4$). For each vessel $k$, a set of pre-evaluated candidate options $\mathcal{C}_k$ is provided.

The decision variable is binary selection $x_{k, j} \in \{0, 1\}$ for candidate $j \in \mathcal{C}_k$, subject to:
$$\sum_{j \in \mathcal{C}_k} x_{k, j} \le 1 \quad \forall k \in \mathcal{V} \quad \text{(Mutual Exclusion)}$$

### 3.2 Portfolio Optimization Model
$$\max_{\{x_{k, j}\}} \quad \sum_{k \in \mathcal{V}} \sum_{j \in \mathcal{C}_k} x_{k, j} \cdot \Delta \text{CO}_{2, k, j}$$

**Subject to:**
1. **Total Portfolio CAPEX Ceiling:**
   $$\sum_{k \in \mathcal{V}} \sum_{j \in \mathcal{C}_k} x_{k, j} \cdot \text{CAPEX}_{k, j} \le \text{Budget}_{\text{portfolio}}$$
2. **Maximum Allowed Retrofits (Optional):**
   $$\sum_{k \in \mathcal{V}} \sum_{j \in \mathcal{C}_k} x_{k, j} \le N_{\text{max\_retrofits}}$$
3. **Minimum Annual $\text{CO}_2$ Target (Optional):**
   $$\sum_{k \in \mathcal{V}} \sum_{j \in \mathcal{C}_k} x_{k, j} \cdot \Delta \text{CO}_{2, k, j} \ge \text{Target}_{\text{CO2}}$$
4. **Minimum Annual Fuel Displacement Target (Optional):**
   $$\sum_{k \in \mathcal{V}} \sum_{j \in \mathcal{C}_k} x_{k, j} \cdot \Delta \text{Fuel}_{k, j} \ge \text{Target}_{\text{Fuel}}$$

### 3.3 Deterministic Tie-Breaking Sequence
When multiple feasible portfolios produce identical total annual $\text{CO}_2$ displacement:
1. **Higher total annual $\text{CO}_2$ displacement** (Primary objective)
2. **Lower total CAPEX**
3. **Higher total NPV**
4. **Lower number of selected retrofits**
5. **Stable lexical ordering of selected vessel identifiers**

---

## 4. Computational Performance & Complexity

- **Fleet Scale:** $K = 4$ representative vessel archetypes.
- **Search Space:** $\le 2^4 = 16$ candidate portfolio subsets.
- **Execution Time:** Measured runtime $< 0.001\text{ s}$ ($< 1\text{ ms}$), providing instant deterministic capital allocation without any GPU/multiprocessing requirement.

---

## 5. Verification & Test Coverage

The test suite in `tests/test_phase9_portfolio_optimizer.py` implements 36 unit and integration tests verifying:
- Pydantic V2 contract integrity, field validations, and aggregate sum consistency.
- Pre-filtering of invalid/ineligible Phase 8 candidates.
- Strict enforcement of mutual exclusion per vessel.
- Bounded subset evaluation count ($N \le 16$).
- Deterministic tie-breaking behavior.
- Immutability of Phase 0–8, Candidate 1, Candidate 2, and reference data.
