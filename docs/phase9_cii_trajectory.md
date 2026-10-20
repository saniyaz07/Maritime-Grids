# Phase 9 Candidate 4: Multi-Year Regulatory Compliance Trajectory & IMO CII Aging Simulator

## 1. Executive Purpose & Scope

Phase 9 Candidate 4 introduces the **Multi-Year Regulatory Compliance Trajectory & IMO Carbon Intensity Indicator (CII) Aging Simulation Layer** for the maritime clean-energy microgrid framework.

Operating as an isolated trajectory and compliance projection layer, Candidate 4 simulates year-by-year vessel activity, baseline emissions, clean-assisted emissions, attained operational CII, statutory/projected required CII, letter ratings ($A$–$E$), and MARPOL Annex VI Regulation 28 corrective-action obligations over multi-year evaluation horizons (e.g. 2023–2035+).

### Key Architectural Characteristics:
- **Consumer of Frozen Phase 6 APIs:** Reuses verified Phase 6 reference line formulas (MEPC.353(78)), rating boundaries (MEPC.354(78)), and statutory reduction factors ($Z\%$) directly.
- **Consumer of Pre-Evaluated Sizing Candidates:** Evaluates clean-assisted trajectories by wrapping pre-evaluated Phase 8 `OptimizationCandidate` objects. It performs **zero** full-grid sizing search.
- **Explicit Regulatory Provenance Flagging:** Each evaluation year is independently tagged as `STATUTORY` (2023–2026), `PROJECTED` (caller-supplied post-2026 assumption), `UNSPECIFIED` (post-2026 with no schedule), `EXEMPT` (e.g. Fishing Trawler), or `NOT_ASSESSED` (e.g. OSV, Surfer Boat).
- **Zero Silent Extrapolation:** Post-2026 regulatory schedules have **no implicit default rate**. Projected values are explicitly labeled as scenario assumptions and not as adopted treaty requirements.
- **Sequential Corrective-Action Tracking:** Implements multi-year MARPOL Regulation 28 corrective-action triggers ($1 \times E$ or $3 \times \text{consecutive } D$ ratings) with rating-C reset mechanics.
- **Deterministic Compliance Extension Metric:** Measures net additional evaluated years that clean energy maintains a compliant rating ($\ge C$) relative to baseline.

---

## 2. Architectural Boundaries & Reusability

```
+-----------------------------------------------------------------------------------+
|                        Phase 9 Candidate 4 Trajectory Engine                      |
|   (Multi-Year Activity Accumulation — Sequential MARPOL Reg 28 Corrective Tracker)|
+----------------------------------------+------------------------------------------+
                                         |
               +-------------------------+-------------------------+
               | (Statutory Formulas & Boundaries)                 | (Pre-Evaluated Candidates)
               v                                                   v
+-------------------------------+                 +---------------------------------+
|      Phase 6 Regulatory Engine|                 |      Phase 8 Sizing Outputs     |
|  - calculate_tanker_cii_ref() |                 |  - OptimizationCandidate        |
|  - calculate_tanker_req_cii() |                 |  - Annual Fuel/CO2 Displaced    |
|  - calculate_tanker_boundaries|                 |  - No full-grid sizing calls    |
|  - assign_tanker_cii_rating() |                 +---------------------------------+
|  - calculate_attained_cii()   |
+-------------------------------+
```

### Prohibited Actions:
1. **Zero Full-Grid Search:** Candidate 4 never calls `optimize_system_sizing()` or evaluates combinatorial lattices.
2. **Zero ML Inference:** No model loading, retraining, or inference.
3. **Zero Formula Duplication:** Reuses frozen Phase 6 functions directly for reference line, rating boundary, and attained CII calculations.
4. **Zero Inter-Candidate Coupling:** Independent of Candidate 1, Candidate 2, and Candidate 3.

---

## 3. Mathematical & Regulatory Formulation

### 3.1 Annual Activity & Emissions
For each calendar year $t \in [t_{\text{start}}, t_{\text{end}}]$ with $t_{\text{idx}} = t - t_{\text{start}}$:

1. **Annual Distance & Transport Work:**
   $$\text{Distance}_{\text{annual}} = N_{\text{voyages}} \times \text{Distance}_{\text{voyage}}$$
   $$\text{Transport Work}_{\text{annual}} = \text{DWT} \times \text{Distance}_{\text{annual}} \quad [\text{DWT} \cdot \text{nm}]$$

2. **Baseline Annual Fuel & $\text{CO}_2$ (with optional degradation):**
   $$\text{Fuel}_{\text{base}}(t) = (F_{\text{single\_voyage}} \times N_{\text{voyages}}) \cdot (1 + d_{\text{fuel}})^{t_{\text{idx}}}$$
   $$\text{CO}_{2, \text{base}}(t) = (E_{\text{single\_voyage}} \times N_{\text{voyages}}) \cdot (1 + d_{\text{fuel}})^{t_{\text{idx}}}$$

3. **Net Assisted Annual Fuel & $\text{CO}_2$:**
   $$\Delta \text{CO}_{2, \text{clean}}(t) = \Delta \text{CO}_{2, \text{cand}} \cdot (1 - d_{\text{solar}})^{t_{\text{idx}}} \cdot (1 - d_{\text{batt}})^{t_{\text{idx}}}$$
   $$\text{CO}_{2, \text{assisted}}(t) = \max\left(0.0, \; \text{CO}_{2, \text{base}}(t) - \Delta \text{CO}_{2, \text{clean}}(t)\right)$$

4. **Attained Operational CII (Resolution MEPC.352(78)):**
   $$\text{Attained CII}(t) = \frac{\text{CO}_{2, \text{annual}}(t) \times 1000}{\text{DWT} \times \text{Distance}_{\text{annual}}} \quad [\text{g CO}_2 / (\text{DWT} \cdot \text{nm})]$$

---

### 3.2 Statutory Reference Line & Rating Bands (Tanker Ship)

- **Reference Line (MEPC.353(78)):**
  $$\text{CII}_{\text{ref}} = 5247.0 \cdot \text{DWT}^{-0.610}$$

- **Required Target CII (MARPOL Annex VI Reg 28.4):**
  $$\text{Required CII}(t) = \text{CII}_{\text{ref}} \cdot \left(1 - \frac{Z(t)}{100}\right)$$

- **Statutory $Z\%$ Schedule ($2023–2026$):**
  - $2023 = 5.0\%$, $2024 = 7.0\%$, $2025 = 9.0\%$, $2026 = 11.0\%$.

- **Post-2026 Scenario Policy:**
  - If caller provides `post_2026_reduction_factors` or `annual_z_increment_pct`, $Z(t)$ is evaluated as `PROJECTED`.
  - Otherwise, $Z(t) = \text{None}$, `Required CII` = $\text{None}$, and rating = `UNSPECIFIED`.

- **Rating Boundaries (MEPC.354(78) Table 1):**
  - Band $A/B = 0.82 \cdot \text{Required CII}$
  - Band $B/C = 0.93 \cdot \text{Required CII}$
  - Band $C/D = 1.08 \cdot \text{Required CII}$
  - Band $D/E = 1.28 \cdot \text{Required CII}$
  - Boundary tie convention: Exact boundary matches receive superior rating (MEPC.354(78) Paragraph 4.2).

---

### 3.3 Multi-Year MARPOL Annex VI Reg 28.6 Corrective Action Tracking

The sequential state tracker evaluates rating history across evaluated years:
1. **Single Year $E$:** Sets `corrective_action_required = True`.
2. **Three Consecutive Years $D$:** If $D$ occurs in years $t, t+1, t+2$, year $t+2$ sets `corrective_action_required = True`.
3. **Rating $C$ Reset:** If a vessel achieves Rating $C, B, \text{ or } A$, the consecutive $D$ counter resets to $0$ and `corrective_action_required = False`.

---

### 3.4 Compliance Extension Metric

For statutory-rated vessels (`Tanker Ship`):
- A year is compliant iff its rating $\in \{A, B, C\}$.
- Net additional compliance years:
  $$\text{compliance\_extension\_years} = \max\left(0, \; N_{\text{compliant, assisted}} - N_{\text{compliant, baseline}}\right)$$
- If both or neither trajectories are compliant for all years: $\text{compliance\_extension\_years} = 0$.
- For `STATUTORILY_EXEMPT` and `NOT_ASSESSED` vessels: $\text{compliance\_extension\_years} = \text{None}$.

---

## 4. Vessel-Scope & Non-Tanker Handling

| Vessel Archetype | Statutory Classification | Required CII | Rating | Compliance Extension |
| :--- | :--- | :--- | :--- | :--- |
| **Tanker Ship** | Statutorily Assessable | Calculated ($Z = 5–11\%$ or projected) | $A, B, C, D, E$ | Calculated ($\ge 0$) |
| **Fishing Trawler** | `STATUTORILY_EXEMPT` (MARPOL Annex VI Reg 19.2.3) | `None` | `EXEMPT` | `None` |
| **Oil Service Boat** | `UNSUPPORTED_VESSEL_CATEGORY_MAPPING` | `None` | `NOT_ASSESSED` | `None` |
| **Surfer Boat** | `UNSUPPORTED_VESSEL_CATEGORY_MAPPING` | `None` | `NOT_ASSESSED` | `None` |

---

## 5. Computational Complexity & Execution Speed

- **Complexity:** $O(N)$ scalar operations for an $N$-year trajectory ($N \le 30$).
- **Measured Runtime:** $< 0.1\text{ ms}$ per multi-year trajectory.
- **Verification:** 38 unit and integration tests passing in `tests/test_phase9_cii_trajectory.py`.
