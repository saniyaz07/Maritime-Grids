# Phase 3F — Multi-Scenario Comparative Analysis Layer Documentation

**Project Root:** `C:\maritime grids`  
**Module:** `phase3f_comparison.py`  
**Test Suite:** `tests/test_phase3f_comparison.py`  
**Status:** IMPLEMENTED AND FULLY VERIFIED  

---

> [!IMPORTANT]
> **Mandatory Methodological Disclosure:**  
> Comparative metrics are deterministic scenario estimates derived from frozen Phase 2 point predictions and assumed auxiliary generator parameters. They do not constitute probabilistic forecasts or guaranteed operational savings.

---

## 1. Purpose & Overview

Phase 3F implements the **Multi-Scenario Comparative Analysis Layer** for the Maritime Grid Simulation Decision Coordinator. It provides a formal, typed, and deterministic batch evaluation framework enabling maritime fleet operators to compare alternative operational and clean-energy configurations (varying battery reserve, auxiliary electrical load, fuel market prices, generator SFOC, fuel density, or solar derating) for a given voyage without modifying underlying machine-learning models or recomputing physical equations.

---

## 2. Scope

* Ingestion and validation of multi-scenario requests (`Phase3FComparisonRequest`).
* Field-level scenario parameter resolution (`ScenarioOverride` over `base_scenario_parameters`).
* Hermetic scenario isolation (zero state leakage between scenarios).
* Pure delegation of individual scenario evaluations to `orchestrate_phase3_voyage` in Phase 3E.
* Baseline-relative differencing against unassisted Tier 2 metrics.
* Pairwise differencing against an explicitly nominated reference scenario.
* Deterministic, single-criterion ranking with alphanumeric tie-breaking.
* Calculation of curtailed clean energy (`clean_energy_curtailed_kwh`).
* Preservation of Phase 3C feasibility labels (`FEASIBLE` and `PARTIAL`).

---

## 3. Non-Scope

* **No Autonomous Control:** Phase 3F does not issue operational machinery commands or control shipboard equipment.
* **No Black-Box or Heuristic Optimization:** Zero genetic algorithms, scipy optimizers, or Bayesian searches.
* **No Multi-Objective Weighting:** Phase 3F will not construct subjective composite objective functions ($w_1 \cdot \text{Cost} + w_2 \cdot \text{CO}_2$).
* **No New Machine Learning Models:** Zero training, tuning, or inference. Phase 2 predictions remain frozen.
* **No Dynamic Dispatch Simulation:** Calculations remain voyage-level aggregates.
* **No Main Propulsion Displacement:** Clean energy is strictly applied to auxiliary diesel-generator electrical loads.
* **No Weather Dispatch Gating:** Weather classification remains purely descriptive context metadata.

---

## 4. Architecture & Workflow

```
Phase3FComparisonRequest
   │
   ├── VoyageMetadata (Authoritative)
   ├── Tier1Phase2Predictions (Authoritative Frozen ML)
   ├── Base AppliedScenarioParameters
   └── Scenarios Collection: [S_1, S_2, ..., S_N]
                │
                ▼
        Parameter Resolution (Precedence: Override -> Base -> Sourced Default)
                │
                ▼
      Phase 3E Orchestrator (orchestrate_phase3_voyage)
      [Called exactly N times — once per scenario]
                │
                ▼
     N x Validated Phase3Output
                │
                ▼
      Phase 3F Comparative Differencing & Ranking Layer
   ├── Baseline-relative deltas (ΔCost, ΔCO2, ΔCII)
   ├── Curtailed clean energy (Total Available - Utilized)
   ├── Pairwise differentials (Target - Reference)
   └── Deterministic Ranking (Optional explicit single-criterion)
                │
                ▼
     Phase3FComparisonOutput
```

---

## 5. Input Contracts

### 5.1 `ScenarioOverride`
Permits overriding individual scenario parameters without redefining the complete base configuration:
* `auxiliary_energy_demand_kwh`: Optional float ($\ge 0.0$)
* `fuel_price_usd_per_l`: Optional float ($\ge 0.0$)
* `initial_soc`: Optional float ($\in [0.0, 1.0]$)
* `soc_reserve`: Optional float ($\in [0.0, 1.0]$)
* `generator_sfoc_kg_per_kwh`: Optional float ($> 0.0$)
* `fuel_density_kg_per_l`: Optional float ($> 0.0$)
* `emission_factor_kgco2_per_kgfuel`: Optional float ($> 0.0$)
* `solar_derate_factor`: Optional float ($\in [0.0, 1.0]$)
* `route_id`: Optional string
* `month`: Optional string or integer ($1$–$12$)
* `daily_ghi_kwh_per_m2`: Optional direct GHI override ($\ge 0.0$)

### 5.2 `ScenarioDefinition`
Encapsulates an individual scenario specification:
* `scenario_id`: Unique non-empty string identifier.
* `description`: Optional human-readable annotation.
* `overrides`: `ScenarioOverride` payload (default empty).

### 5.3 `RankingCriterion`
Supported criteria strictly limited to:
* `min_net_fuel_cost_usd` (ascending)
* `min_net_co2_kg` (ascending)
* `min_net_fuel_L` (ascending)
* `min_net_operational_cii` (ascending)
* `max_clean_energy_utilized_kwh` (descending)
* `max_fuel_displaced_L` (descending)

### 5.4 `Phase3FComparisonRequest`
Master batch comparison container enforcing non-empty scenarios, unique scenario IDs, and reference scenario existence.

---

## 6. Output Contracts

### 6.1 `ScenarioEvaluationSummary`
Extracts key comparative metrics alongside the full lower-tier `Phase3Output`:
* `scenario_id`: String
* `feasibility_status`: `"FEASIBLE"` or `"PARTIAL"`
* `auxiliary_energy_demand_kwh`: Float
* `clean_energy_utilized_kwh`: Float
* `clean_energy_curtailed_kwh`: Float ($\max(0.0, E_{\text{available}} - E_{\text{utilized}})$)
* `energy_deficit_kwh`: Float
* `estimated_fuel_displaced_L`: Float
* `estimated_co2_displaced_kg`: Float
* `net_assisted_fuel_L`: Float
* `net_assisted_co2_kg`: Float
* `net_assisted_fuel_cost_usd`: Float
* `net_assisted_operational_cii`: Float
* `delta_fuel_pct_vs_baseline`: Float
* `delta_cii_pct_vs_baseline`: Float
* `resolved_fuel_price_usd_per_l`: Float
* `phase3_output`: `Phase3Output`

### 6.2 `PairwiseComparisonDelta`
Pairwise difference between target scenario and reference scenario ($\text{Target} - \text{Reference}$):
* `target_scenario_id` & `reference_scenario_id`
* `delta_net_fuel_cost_usd`
* `delta_net_co2_kg`
* `delta_net_fuel_L`
* `delta_net_cii`
* `delta_clean_energy_utilized_kwh`

### 6.3 `Phase3FComparisonOutput`
Root output container containing summary collection, baseline metrics, optional ranking list, optional pairwise table, and audit metadata.

---

## 7. Parameter Inheritance & Scenario Isolation

### 7.1 Parameter Precedence
For each parameter $P$:
$$P_{\text{resolved}} = \begin{cases} P_{\text{override}} & \text{if } P_{\text{override}} \text{ is not None} \\ P_{\text{base}} & \text{otherwise} \end{cases}$$

### 7.2 Route / Climatology Precedence
$$\text{GHI} = \begin{cases} \text{Scenario GHI override} & \text{if specified} \\ \text{Request GHI} & \text{if specified} \\ \text{Lookup}(\text{Scenario Route/Month} \text{ or Request Route/Month}) & \text{otherwise} \end{cases}$$

### 7.3 Isolation Guarantees
* No scenario inherits from another scenario.
* Overriding fuel price or battery reserve in Scenario $A$ has zero impact on Scenario $B$.
* Phase 3E ensures that single fuel price consistency is enforced within each scenario run independently.

---

## 8. Ranking & Tie-Breaking Formulation

* **No Criterion:** If `ranking_criterion is None`, scenarios retain their exact input sequence, and `ranked_scenario_ids = None`.
* **Explicit Directionality:**
  * Ascending for minimization (`min_net_fuel_cost_usd`, `min_net_co2_kg`, `min_net_fuel_L`, `min_net_operational_cii`).
  * Descending for maximization (`max_clean_energy_utilized_kwh`, `max_fuel_displaced_L`).
* **Deterministic Tie-Breaking:**
  $$\text{Sort Key} = (\text{Directional Metric Value}, \text{scenario\_id})$$
  Ensures 100% reproducible ordering even under identical metric outcomes.

---

## 9. Conservation Rules & Feasibility

1. **Curtailed Clean Energy:** Surplus clean energy is accounted as `clean_energy_curtailed_kwh` and is strictly prevented from displacing auxiliary generator fuel.
2. **Conservation Preservation:** All Phase 3 invariants ($\text{Displacement} \le \text{Baseline}$, non-negativity) hold across every scenario.
3. **Feasibility Preservation:** Scenarios with `PARTIAL` feasibility are retained, fully evaluated, and ranked alongside `FEASIBLE` scenarios, with feasibility status explicitly reported.

---

## 10. API Usage Example

```python
from phase3_contracts import VoyageMetadata, Tier1Phase2Predictions, AppliedScenarioParameters
from phase3f_comparison import (
    ScenarioOverride,
    ScenarioDefinition,
    Phase3FComparisonRequest,
    compare_phase3_scenarios,
)

# 1. Define Request
request = Phase3FComparisonRequest(
    voyage_metadata=VoyageMetadata(
        ship_type="Oil Service Boat",
        distance_nm=250.0,
        voyage_duration_hours=18.5,
        deadweight_tonnes=1800.0,
    ),
    tier_1_phase2_predictions=tier1_preds,
    base_scenario_parameters=AppliedScenarioParameters(
        fuel_price_usd_per_l=1.15,
        auxiliary_energy_demand_kwh=180.0,
    ),
    daily_ghi_kwh_per_m2=5.0,
    scenarios=[
        ScenarioDefinition(scenario_id="Base_180kWh"),
        ScenarioDefinition(
            scenario_id="HighDemand_250kWh",
            overrides=ScenarioOverride(auxiliary_energy_demand_kwh=250.0)
        ),
        ScenarioDefinition(
            scenario_id="HighReserve_30pct",
            overrides=ScenarioOverride(soc_reserve=0.30)
        ),
    ],
    ranking_criterion="min_net_fuel_cost_usd",
    reference_scenario_id="Base_180kWh",
)

# 2. Execute Comparative Analysis
result = compare_phase3_scenarios(request)

# 3. Inspect Results
print("Ranked Scenarios:", result.ranked_scenario_ids)
for s in result.scenarios:
    print(f"{s.scenario_id}: Net Cost = ${s.net_assisted_fuel_cost_usd:.2f}, Curtailed = {s.clean_energy_curtailed_kwh:.1f} kWh")
```

---

## 11. Traceability Matrix

| Requirement / Test Focus | Test Name in `test_phase3f_comparison.py` | Status |
|---|---|---|
| Valid request contract parsing | `test_valid_request` | PASSED |
| Empty scenarios rejection | `test_empty_scenarios_rejected` | PASSED |
| Duplicate scenario ID rejection | `test_duplicate_scenario_ids_rejected` | PASSED |
| Non-existent reference scenario rejection | `test_invalid_reference_scenario_id_rejected` | PASSED |
| Unsupported ranking criterion rejection | `test_invalid_ranking_criterion_rejected` | PASSED |
| Base parameter inheritance | `test_base_parameter_inheritance` | PASSED |
| Single-field override | `test_single_field_override` | PASSED |
| Multi-field override | `test_multiple_field_overrides` | PASSED |
| Scenario isolation ($A$ vs $B$) | `test_scenario_isolation_between_a_and_b` | PASSED |
| Exactly $N$ calls to `orchestrate_phase3_voyage` | `test_delegates_exactly_n_times` | PASSED |
| Parameter propagation to Phase 3E | `test_phase3e_receives_resolved_parameters` | PASSED |
| Convenience alias `compare_scenarios` | `test_convenience_alias_compare_scenarios` | PASSED |
| Baseline-relative delta calculation | `test_baseline_deltas_reported` | PASSED |
| Pairwise differencing against reference | `test_pairwise_comparison_against_reference` | PASSED |
| Ranking: `min_net_fuel_cost_usd` | `test_ranking_min_net_fuel_cost_usd` | PASSED |
| Ranking: `min_net_co2_kg` | `test_ranking_min_net_co2_kg` | PASSED |
| Ranking: `min_net_fuel_L` | `test_ranking_min_net_fuel_L` | PASSED |
| Ranking: `min_net_operational_cii` | `test_ranking_min_net_operational_cii` | PASSED |
| Ranking: `max_clean_energy_utilized_kwh` | `test_ranking_max_clean_energy_utilized_kwh` | PASSED |
| Ranking: `max_fuel_displaced_L` | `test_ranking_max_fuel_displaced_L` | PASSED |
| Deterministic tie-breaking on identical metrics | `test_deterministic_tie_breaking` | PASSED |
| Unranked default when criterion omitted | `test_no_criterion_no_ranking` | PASSED |
| Feasibility status preservation | `test_feasibility_status_preserved` | PASSED |
| Partial feasibility not silently discarded | `test_partial_not_silently_discarded` | PASSED |
| Curtailed clean energy calculation | `test_curtailed_clean_energy_reporting` | PASSED |
| Pairwise deltas explicit arithmetic check | `test_pairwise_deltas_explicit_math` | PASSED |
| Scenario GHI precedence over request GHI | `test_scenario_ghi_override_takes_precedence` | PASSED |
| Conservation invariants hold across all scenarios | `test_conservation_invariants_hold_across_all_scenarios` | PASSED |
| Frozen model hash integrity | `test_frozen_model_hashes_verified` | PASSED |
| Scenario-annotated error handling | `test_scenario_error_annotated_with_scenario_id` | PASSED |
| Repeated evaluation determinism & idempotency | `test_repeated_identical_evaluation_deterministic` | PASSED |
