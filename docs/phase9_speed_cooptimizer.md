# Phase 9 Candidate 2: Operational Transit Speed & Power Co-Optimization Engine

## 1. Executive Purpose & Scope

Phase 9 Candidate 2 introduces the **Operational Transit Speed & Hybrid Sizing Co-Optimization Layer** for the maritime clean-energy microgrid simulation framework.

By integrating operational transit speed ($V_{\text{knots}}$) as a primary decision variable alongside physical solar photovoltaic array area ($A_{\text{pv}}$) and battery pack capacity ($E_{\text{batt}}$), Candidate 2 exploits the non-linear hydrodynamic speed-power relationship ($P_{\text{prop}} \propto V^3$) against transit delivery deadlines.

### Core Capabilities:
- **3D Operational Decision Lattice:** Evaluates combinations across Transit Speed ($V$), Solar PV Area ($A_{\text{pv}}$), and Battery Storage ($E_{\text{batt}}$).
- **Hydrodynamic Speed-Power Scaling:** Applies quadratic voyage fuel consumption scaling ($F_{\text{prop}}(V) \propto V^2$) derived from cubic propulsion-power physics under constant-SFOC assumptions.
- **Transit Delivery Deadline Filtering:** Enforces hard delivery constraints ($T_{\text{voyage}} \le T_{\text{deadline}}$), tagging violating candidates as `DEADLINE_EXCEEDED`.
- **Hybrid Sizing Orchestration:** Delegates single-candidate feasibility, displacement, and capital budgeting evaluations directly to the frozen Phase 8 optimizer and Phase 7 lifecycle economics engines.
- **Multi-Objective 3D Pareto Frontier:** Constructs the non-dominated Pareto tradeoff envelope across Voyage Duration, Net Annual Fuel Consumption, and Lifecycle Net Present Value (NPV).
- **Strict Computational Budgeting:** Enforces a hard maximum limit of 2,500 evaluations per run with verified sub-second execution latency ($< 2.0\text{ seconds}$).

---

## 2. Architectural Boundaries & Immutability

Candidate 2 sits as an isolated orchestration layer above frozen Phase 3, 6, 7, and 8 subsystems:
- **Zero Modifications to Upstream Phases:** Phases 0 through 8 and Phase 9 Candidate 1 remain completely untouched.
- **Zero ML Model Retraining:** Frozen Phase 2 models (`battery_soc_lstm.pt`, `battery_soh_final.joblib`, `fuel_xgb.joblib`, `weather_final.joblib`) remain cryptographically identical.
- **Zero Duplication of Physics/Economics:** Solar yield, battery dispatch, generator fuel displacement, lifecycle cash flows, and NPV are evaluated exclusively by calling:
  - `phase8_optimizer.evaluate_single_sizing_candidate`
  - `phase7_economics.evaluate_clean_energy_investment`
  - `phase6_gateway.simulate_voyage`

---

## 3. Mathematical & Hydrodynamic Formulation

### 3.1 Operational Speed Lattice
For each vessel archetype:
- Maximum speed: $V_{\max} = V_{\text{design}}$ (sourced from `ship_profiles.csv`).
- Minimum speed: $V_{\min} = 0.60 \times V_{\text{design}}$.
- Default speed step:
  - Displacement vessels (`Tanker Ship`, `Oil Service Boat`, `Fishing Trawler`): $\Delta V = 0.5\text{ knots}$.
  - Planing vessels (`Surfer Boat`): $\Delta V = 1.0\text{ knot}$.

### 3.2 Voyage Duration & Delivery Deadlines
$$T_{\text{voyage}}(V) = \frac{\text{Distance}_{\text{nm}}}{V_{\text{knots}}}$$
If a delivery deadline is specified:
$$T_{\text{voyage}}(V) \le T_{\text{deadline}}$$
Candidates with $T_{\text{voyage}} > T_{\text{deadline}}$ are marked with `candidate_status = "DEADLINE_EXCEEDED"` and excluded from Pareto dominance.

### 3.3 Quadratic Voyage-Fuel Scaling
Under classical naval architecture:
$$P_{\text{prop}} \propto V^3$$
Since voyage duration scales inversely with speed ($T \propto V^{-1}$), total propulsion energy and fuel consumed per voyage scale quadratically:
$$E_{\text{prop}} = P_{\text{prop}} \times T \propto V^3 \times V^{-1} = V^2$$
$$F_{\text{prop}}(V) = F_{\text{prop, ref}} \times \left(\frac{V}{V_{\text{ref}}}\right)^2$$
Where $F_{\text{prop, ref}}$ is the baseline propulsion fuel at design reference speed $V_{\text{ref}}$, derived from total reference fuel minus auxiliary generator fuel:
$$F_{\text{aux}}(V) = \frac{P_{\text{aux}} \times T_{\text{voyage}}(V) \times \text{SFOC}_{\text{gen}}}{\rho_{\text{fuel}}}$$
$$F_{\text{voyage}}(V) = F_{\text{prop}}(V) + F_{\text{aux}}(V)$$

---

## 4. Multi-Objective 3D Pareto Frontier

Candidate 2 computes the non-dominated Pareto frontier across the primary operational and economic objectives:
1. `MIN_DURATION`: Minimize voyage transit duration ($T_{\text{voyage}}$).
2. `MIN_ANNUAL_FUEL`: Minimize net annual fuel consumption ($F_{\text{annual, net}} = F_{\text{annual, gross}} - \Delta F_{\text{annual, clean}}$).
3. `MAX_NPV`: Maximize lifecycle net present value ($\text{NPV}$).

### Non-Domination Rule:
Candidate $X$ dominates candidate $Y$ ($X \succ Y$) iff:
1. $X$ is no worse than $Y$ in all configured objectives:
   - For minimization: $v_{X, k} \le v_{Y, k} + \epsilon_{\text{rel}} \cdot \max(1.0, |v_{X, k}|, |v_{Y, k}|)$
   - For maximization: $v_{X, k} \ge v_{Y, k} - \epsilon_{\text{rel}} \cdot \max(1.0, |v_{X, k}|, |v_{Y, k}|)$
2. $X$ is strictly better than $Y$ in at least one objective.

---

## 5. Computational Budget & Complexity

- **Budget Limit:** Maximum 2,500 evaluations per run.
- **Upfront Lattice Validation:** Before running evaluations, the total configuration count $N_V \times N_A \times N_E$ is calculated. If this exceeds 2,500, execution is halted immediately with a `ValueError`.
- **Measured Latency:** A 2,000-configuration co-optimization run executes in $\approx 0.15\text{ seconds}$, well below the $< 2.0\text{ second}$ target ceiling.
