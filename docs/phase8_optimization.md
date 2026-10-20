# PHASE 8 — PARAMETRIC SYSTEM SIZING OPTIMIZATION ENGINE

## 1. Executive Summary & Purpose

Phase 8 introduces the **Parametric System Sizing Optimization Layer** for the Maritime Grids simulation framework. Building upon the verified physical foundation of Phase 3 (Clean Energy Feasibility and Generator Displacement) and the capital budgeting engine of Phase 7 (Lifecycle Techno-Economics), Phase 8 determines the mathematical trade-offs of scaling solar photovoltaic (PV) array surface area ($A_{\text{pv}}$) and nominal battery energy storage capacity ($E_{\text{batt}}$).

The optimizer identifies globally optimal sizing points and multi-objective Pareto trade-off frontiers across competing physical, operational, and financial dimensions:
- Physical deck area and vessel deadweight carrying capacity limits.
- Maximum initial capital investment limits (CAPEX budget).
- Auxiliary electrical hotel load demand coverage (clean-energy feasibility).
- Annual bunker fuel and $\text{CO}_2$ emissions displacement.
- Net Present Value ($\text{NPV}$), Levelized Cost of Clean Energy ($\text{LCOE}$), and Simple/Discounted Payback.

---

## 2. Architectural Boundaries & Conservation Principles

Phase 8 adheres strictly to zero-touch governance and mathematical conservation principles:

```
+-----------------------------------------------------------------------------------+
|                        Phase 8 Sizing Optimization Engine                         |
|   (Exhaustive Bounded Discrete Lattice Search — Deterministic Tie-Breaking)      |
+----------------------------------------+------------------------------------------+
                                         |
               +-------------------------+-------------------------+
               | (Apv, Ebatt overrides)                            | (Annual displacements & CAPEX)
               v                                                   v
+-------------------------------+                 +---------------------------------+
|      Phase 3 Physics          |                 |       Phase 7 Economics         |
|  - Usable Battery Energy      |                 |  - Initial CAPEX_0              |
|  - Climatological Solar Yield |                 |  - Annual Cash Flows (0 to N)   |
|  - Clean Energy Balance       |                 |  - NPV, Payback Periods         |
|  - Auxiliary SFOC Displacement|                 |  - LCOE (Zero-Energy Aware)     |
+-------------------------------+                 |  - Deterministic Brent IRR      |
                                                  +---------------------------------+
```

### Critical Architectural Constraints:
1. **Consumer-Only Role:** Phase 8 does not implement independent machine learning inference, load models, or duplicate formulas owned by Phase 2, Phase 3, Phase 6, or Phase 7.
2. **Snapshot SOH Semantics:** Battery degradation ($\text{SOH}$) is consumed as a static operational snapshot input from Phase 2 ($\text{models/battery\_soh\_final.joblib}$). Phase 8 does not extrapolate future SOH or simulate dynamic cell aging.
3. **Auxiliary Displacement Invariant:** Auxiliary generator clean-energy absorption is bounded strictly by requested auxiliary hotel load demand ($E_{\text{utilized}} \le E_{\text{aux}}$). Clean energy surplus beyond auxiliary demand is curtailed and cannot displace main propulsion fuel.
4. **Strict LCOE Semantics:** When annual clean energy utilized is zero ($E_{\text{utilized}} = 0$), $\text{LCOE}$ is strictly `None` with diagnostic `LCOE_UNDEFINED_ZERO_ENERGY`. It is never converted to $\infty$, $0.0$, or arbitrary sentinels.
5. **Neutral Diagnostic Outputs:** Zero evaluative investment recommendations (`"VIABLE"`, `"RECOMMENDED"`, `"BEST"`). All outputs report objective numerical metrics and machine-readable diagnostic statuses.

---

## 3. Optimization Variables & Search Lattice Formulation

The search space is defined by two continuous physical parameters evaluated over a deterministic discrete lattice:

$$\mathcal{S} = \left\{ (A_{\text{pv}, i}, E_{\text{batt}, j}) \mid A_{\text{pv}, i} \in \mathcal{L}_A, \; E_{\text{batt}, j} \in \mathcal{L}_E \right\}$$

### Solar Array Surface Area Lattice ($\mathcal{L}_A$)
$$A_{\text{pv}, i} = A_{\min} + i \cdot \Delta A_{\text{pv}}, \quad i \in \mathbb{N}_0, \quad A_{\text{pv}, i} \le A_{\text{pv}, \max}$$
- Default minimum: $A_{\min} = 0.0\text{ m}^2$
- Default discrete step: $\Delta A_{\text{pv}} = 10.0\text{ m}^2$
- Automatic maximum boundary: $A_{\text{pv}, \max} = A_{\text{deck, max}} = f_{\text{deck, max}} \cdot L \cdot B$

### Nominal Battery Storage Capacity Lattice ($\mathcal{L}_E$)
$$E_{\text{batt}, j} = E_{\min} + j \cdot \Delta E_{\text{batt}}, \quad j \in \mathbb{N}_0, \quad E_{\text{batt}, j} \le E_{\text{batt}, \max}$$
- Default minimum: $E_{\min} = 0.0\text{ kWh}$
- Discrete step increment rule:
  - Small Craft (`Fishing Trawler`, `Surfer Boat`): $\Delta E_{\text{batt}} = 25.0\text{ kWh}$
  - Large Vessels (`Oil Service Boat`, `Tanker Ship`): $\Delta E_{\text{batt}} = 50.0\text{ kWh}$
- Automatic maximum boundary: $E_{\text{batt}, \max} = \frac{M_{\text{dwt, max}} \cdot 1000}{\rho_{\text{batt}}} = \frac{f_{\text{dwt, max}} \cdot \text{DWT} \cdot 1000}{\rho_{\text{batt}}}$

### Grid Generation Invariants:
- **No Fractional Partial Steps:** Traversal terminates at $\max \{x \in \mathcal{L} \mid x \le x_{\max}\}$. Points that do not land on the discrete step increment are not appended.
- **Search Bound Ceiling:** Grids exceeding $10,000$ points are rejected immediately with a descriptive `ValueError` to prevent unbounded execution.
- **Traversal Ordering:** Deterministically ordered in ascending $A_{\text{pv}}$, then ascending $E_{\text{batt}}$.

---

## 4. Engineering & Physical Constraints

Every candidate $(A_{\text{pv}}, E_{\text{batt}})$ is evaluated against four hard boundaries:

| Constraint Name | Mathematical Boundary | Candidate Violation Tag | Action |
| :--- | :--- | :--- | :--- |
| **Deck Area Limit** | $A_{\text{pv}} \le f_{\text{deck, max}} \cdot L \cdot B + \epsilon_{\text{abs}}$ | `DECK_AREA_EXCEEDED` | Candidate status $\rightarrow$ `CONSTRAINED_OUT` |
| **Battery Weight Limit** | $M_{\text{batt}} = \frac{E_{\text{batt}} \cdot \rho_{\text{batt}}}{1000} \le f_{\text{dwt, max}} \cdot \text{DWT} + \epsilon_{\text{abs}}$ | `BATTERY_WEIGHT_EXCEEDED` | Candidate status $\rightarrow$ `CONSTRAINED_OUT` |
| **CAPEX Budget** | $\text{CAPEX}_0 \le \text{Budget} + \epsilon_{\text{abs}}$ (if configured) | `BUDGET_EXCEEDED` | Candidate status $\rightarrow$ `BUDGET_EXCEEDED` |
| **Feasibility Gate** | Feasibility status $== \text{"FEASIBLE"}$ (if `require_fully_feasible=True`) | `INCOMPLETE_AUXILIARY_FEASIBILITY` | Candidate status $\rightarrow$ `INCOMPLETE_FEASIBILITY` |

Tolerance standard: $\epsilon_{\text{abs}} = 1\times 10^{-6}$.

All candidates, whether valid or constrained out, are retained in `candidate_results` for complete execution auditability.

---

## 5. Primary Objectives & Optimization Formulations

Phase 8 supports five single-objective scalar optimizations and one multi-objective trade-off formulation:

### 1. `MAX_NPV` (Net Present Value Maximization)
$$\max_{(A_{\text{pv}}, E_{\text{batt}}) \in \mathcal{S}_{\text{feasible}}} \text{NPV} = \sum_{t=0}^{N} \frac{\text{NCF}_t}{(1 + r)^t}$$
Maximizes discounted net present value over the 15-year analysis horizon by default, configurable via FinancialParameters.analysis_horizon_years.

### 2. `MAX_FUEL_DISPLACEMENT` (Bunker Fuel Savings Maximization)
$$\max_{(A_{\text{pv}}, E_{\text{batt}}) \in \mathcal{S}_{\text{feasible}}} \Delta V_{\text{fuel, annual}} = N_{\text{voyages}} \cdot \min \left( \frac{E_{\text{utilized}} \cdot \text{SFOC}_{\text{gen}}}{\rho_{\text{fuel}}}, \; V_{\text{fuel, baseline}} \right)$$
Finds the sizing configuration that displaces the maximum physical volume of marine diesel fuel.

### 3. `MAX_CO2_DISPLACEMENT` (Emissions Abatement Maximization)
$$\max_{(A_{\text{pv}}, E_{\text{batt}}) \in \mathcal{S}_{\text{feasible}}} \Delta M_{\text{CO}_2, \text{annual}} = N_{\text{voyages}} \cdot \min \left( \Delta V_{\text{fuel}} \cdot \rho_{\text{fuel}} \cdot C_F, \; M_{\text{CO}_2, \text{baseline}} \right)$$
Maximizes annual avoided greenhouse gas emissions.

### 4. `MIN_LCOE` (Levelized Cost of Clean Energy Minimization)
$$\min_{(A_{\text{pv}}, E_{\text{batt}}) \in \mathcal{S}_{\text{feasible}}, E_{\text{utilized}} > 0} \text{LCOE} = \frac{\text{CAPEX}_0 + \sum_{t=1}^N \frac{\text{OPEX}_t + \text{CAPEX}_{\text{repl}, t} - \text{Salvage}_t}{(1+r)^t}}{\sum_{t=1}^N \frac{E_{\text{utilized}, t}}{(1+r)^t}}$$
Finds the lowest cost per unit of utilized clean energy. Candidates with $E_{\text{utilized}} = 0$ ($\text{LCOE} = \text{None}$) are unrankable and cannot be selected.

### 5. `MIN_CAPEX` (Initial Capital Investment Minimization)
$$\min_{(A_{\text{pv}}, E_{\text{batt}}) \in \mathcal{S}_{\text{feasible}}} \text{CAPEX}_0 = A_{\text{pv}} \cdot C_{\text{pv}} + E_{\text{batt}} \cdot C_{\text{batt}} + C_{\text{BOP}} + C_{\text{install}}$$
Finds the lowest initial capital cost configuration satisfying constraints.

---

## 6. Deterministic Tie-Breaking Hierarchy

Due to hotel load demand saturation, multiple sizing candidates frequently achieve identical physical fuel and $\text{CO}_2$ displacement. Phase 8 implements an unambiguous, deterministic tie-breaking hierarchy:

```
                                  [ Candidate A vs Candidate B ]
                                                 |
                       |v_A - v_B| <= eps_rel * max(1.0, |v_A|, |v_B|) ?
                                                 |
                           +---------------------+---------------------+
                           | Yes (Tied)                                | No
                           v                                           v
                  [ Priority 1: Min CAPEX_0 ]                 [ Strictly Better Value ]
                           |
                |c_A - c_B| <= eps_rel * max(1.0, c_A, c_B) ?
                           |
              +------------+------------+
              | Yes (Tied)              | No
              v                         v
     [ Priority 2: Min A_pv ]       [ Lower CAPEX_0 Wins ]
              |
         |a_A - a_B| <= 1e-6 ?
              |
         +----+----+
         | Yes     | No
         v         v
[ Priority 3: Min E_batt ]   [ Smaller A_pv Wins ]
         |
    |e_A - e_B| <= 1e-6 ?
         |
    +----+----+
    | Yes     | No
    v         v
[ Priority 4: Lattice Traversal Order ]   [ Smaller E_batt Wins ]
```

When ties occur on the primary objective, all tied candidates are preserved in `top_candidates`, and the tie resolution is documented in `tie_candidates_notes`.

---

## 7. Multi-Objective Pareto Frontier Formulation

When `objective == "PARETO_FRONTIER"`, Phase 8 computes the non-dominated Pareto trade-off set across configured objectives (default: `["MIN_CAPEX", "MAX_FUEL_DISPLACEMENT"]`).

### Dominance Definition:
Candidate $X$ dominates candidate $Y$ ($X \succ Y$) if and only if:
1. $X$ is no worse than $Y$ in every objective $k \in \mathcal{O}_{\text{pareto}}$:
   - For minimization ($\text{MIN}$): $v_{X, k} \le v_{Y, k} + \epsilon_{\text{rel}} \cdot \max(1.0, |v_{X, k}|, |v_{Y, k}|)$
   - For maximization ($\text{MAX}$): $v_{X, k} \ge v_{Y, k} - \epsilon_{\text{rel}} \cdot \max(1.0, |v_{X, k}|, |v_{Y, k}|)$
2. $X$ is strictly better than $Y$ in at least one objective $j \in \mathcal{O}_{\text{pareto}}$:
   - For minimization ($\text{MIN}$): $v_{X, j} < v_{Y, j} - \epsilon_{\text{rel}} \cdot \max(1.0, |v_{X, j}|, |v_{Y, j}|)$
   - For maximization ($\text{MAX}$): $v_{X, j} > v_{Y, j} + \epsilon_{\text{rel}} \cdot \max(1.0, |v_{X, j}|, |v_{Y, j}|)$

### Special LCOE Rule in Pareto Dominance:
- If Candidate $X$ has a defined numeric $\text{LCOE}$ and Candidate $Y$ has $\text{LCOE} = \text{None}$, $X$ is strictly superior to $Y$ in the $\text{LCOE}$ objective.
- If both have $\text{LCOE} = \text{None}$, they are considered tied on $\text{LCOE}$.
- Candidate $Y$ with $\text{LCOE} = \text{None}$ can never dominate Candidate $X$ on $\text{LCOE}$.

The resulting `pareto_frontier` is sorted deterministically by ascending $\text{CAPEX}_0$, then descending fuel displacement, then $A_{\text{pv}}$, then $E_{\text{batt}}$.

---

## 8. Data Provenance & Engineering Disclaimers

> [!WARNING] Mandatory Transparency Disclosures
> 1. **Deck Area Assumption:** $A_{\text{deck, max}} = f_{\text{deck, max}} \cdot L \cdot B$ is a derived engineering sizing boundary based on assumed topside/superstructure clearance ($f_{\text{deck, max}} = 0.25$). It is **NOT** a certified structural deck rating or naval architectural stability limit.
> 2. **Battery Weight Assumption:** $M_{\text{dwt, max}} = f_{\text{dwt, max}} \cdot \text{DWT}$ ($f_{\text{dwt, max}} = 0.05$) and pack specific mass ($\rho_{\text{batt}} = 8.5\text{ kg/kWh}$) are parametric engineering assumptions. They do **NOT** account for localized deck shear stresses, longitudinal bending moments, or transverse stability ($\overline{GM}$).
> 3. **Propulsion Fuel Invariant:** Phase 2 machine learning models predict total voyage fuel consumption without ML decomposition into propulsion vs. auxiliary consumption. Clean energy displacement is strictly bounded by auxiliary electrical hotel load demand.

---

## 9. Verification & Regression Protection

The Phase 8 implementation is validated by a dedicated 34-test suite (`tests/test_phase8_optimizer.py`) and passes the full 283-test regression suite:
- Phase 3A–3G tests: 188/188 passing
- Phase 6 tests: 33/33 passing
- Phase 7 tests: 28/28 passing
- Phase 8 tests: 34/34 passing
- **Total Test Suite:** 283/283 passing (100% pass rate, 0 failures, 0 errors)
- **Model Cryptographic Hashes:** All four frozen Phase 2 models retain exact SHA-256 baseline hashes.
- **Raw Data Integrity:** All 6,228 files in `data/raw/` and `data/reference/ship_profiles.csv` remain unmodified.

---

## 10. Phase 9 Architectural Boundary

Phase 8 is bounded strictly to **parametric hardware sizing optimization**. It intentionally excludes:
1. **Dynamic Timestep Dispatch Simulation:** Evaluating real-time battery charge/discharge controllers, engine start-stop cycling, and diurnal solar profiles.
2. **Speed-Power Hydrodynamic Co-Optimization:** Simultaneous optimization of transit speed ($V_{\text{knots}}$) and hybrid clean-energy sizing.
3. **Multi-Leg Geospatial Routing:** Route selection and multi-port voyage optimization under dynamic ocean currents and sea states.
4. **Electrochemical Battery Degradation Modeling:** Dynamic cycle-counting (Rainflow algorithm) and calendar aging extrapolation over vessel lifespans.

These capabilities represent the logical boundary for future development phases.
