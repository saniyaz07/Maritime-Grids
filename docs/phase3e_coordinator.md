# Phase 3E — Decision Coordinator & Pipeline Orchestration Documentation

**Project Root:** `C:\maritime grids`  
**Module:** `phase3_coordinator.py`  
**Test Suite:** `tests/test_phase3e_coordinator.py`  
**Status:** IMPLEMENTED AND FULLY VERIFIED  

---

## 1. Purpose & Architectural Role

Phase 3E implements the master pipeline orchestration layer (`phase3_coordinator.py`) for the Maritime Grid Simulation Decision Coordinator. Its role is to connect, sequence, and validate the end-to-end data flow across all four conceptual tiers without introducing new machine-learning models or recomputing lower-tier engineering equations.

```
Authoritative Tier 1 Phase 2 Predictions
                │
                ▼
      Phase 3E Decision Coordinator
                │
        ┌───────┼────────┐
        ▼       ▼        ▼
      Tier 2   Tier 3   Tier 4
     Baseline  Clean    Displacement
               Energy
        │       │        │
        └───────┼────────┘
                ▼
          Phase3Output
   (Root Contract Validation)
```

---

## 2. Explicit Modeling & Phase 2 Boundaries

* **No New Machine Learning Models:** Phase 3E introduces zero new machine-learning models, training pipelines, or inferencing networks.
* **No Phase 2 Modification:** Phase 2 models, weights, training pipelines, feature transformers, and datasets remain 100% frozen.
* **No Inference Logic in Coordinator:** Pre-computed or pipeline-derived Phase 2 predictions enter the coordinator strictly as validated `Tier1Phase2Predictions` data structures.
* **No Formula Duplication:** Phase 3E does not independently evaluate baseline fuel cost, baseline CII, effective battery capacity, solar irradiance scaling, generator displacement, or net assisted performance metrics. It delegates entirely to the verified lower-tier modules: `phase3_baseline.py`, `phase3_feasibility.py`, and `phase3_displacement.py`.
* **Distinction Between Predictions vs. Estimates:**
  * **Tier 1 Predictions:** Statistical ML outputs (`fuel_xgb.joblib`, `battery_soh_final.joblib`, `weather_final.joblib`, `battery_soc_lstm.pt`).
  * **Tier 2 Baseline:** Pure deterministic standard IMO / economic metrics.
  * **Tier 3 Feasibility:** Physical battery degradation and climatological insolation engineering budgets.
  * **Tier 4 Displacement:** Counterfactual auxiliary generator-equivalent scenario estimates (`status = "ENGINEERING SCENARIO ESTIMATE"`).

---

## 3. Public API Specification

The coordinator exposes two deterministic, side-effect-free public functions:

### 3.1 `orchestrate_phase3_voyage`
```python
def orchestrate_phase3_voyage(
    voyage_metadata: Union[VoyageMetadata, Dict[str, Any]],
    tier1_predictions: Union[Tier1Phase2Predictions, Dict[str, Any]],
    auxiliary_energy_demand_kwh: float,
    route_id: Optional[str] = None,
    month: Optional[Union[str, int]] = None,
    daily_ghi_kwh_per_m2: Optional[float] = None,
    fuel_price_override_usd_per_l: Optional[float] = None,
    initial_soc: float = 0.90,
    soc_reserve: float = 0.20,
    generator_sfoc_kg_per_kwh: float = 0.220,
    fuel_density_kg_per_l: float = 0.850,
    emission_factor_kgco2_per_kgfuel: float = 3.114,
    solar_derate_factor: float = 0.85,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> Phase3Output:
```

### 3.2 `run_coordinator_scenario`
```python
def run_coordinator_scenario(
    voyage_metadata: Union[VoyageMetadata, Dict[str, Any]],
    tier1_predictions: Union[Tier1Phase2Predictions, Dict[str, Any]],
    scenario_parameters: Optional[Union[AppliedScenarioParameters, Dict[str, Any]]] = None,
    auxiliary_energy_demand_kwh: Optional[float] = None,
    fuel_price_override_usd_per_l: Optional[float] = None,
    route_id: Optional[str] = None,
    month: Optional[Union[str, int]] = None,
    daily_ghi_kwh_per_m2: Optional[float] = None,
    initial_soc: Optional[float] = None,
    soc_reserve: Optional[float] = None,
    generator_sfoc_kg_per_kwh: Optional[float] = None,
    fuel_density_kg_per_l: Optional[float] = None,
    emission_factor_kgco2_per_kgfuel: Optional[float] = None,
    solar_derate_factor: Optional[float] = None,
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> Phase3Output:
```

---

## 4. Tier Execution Sequence & Data Flow

Phase 3E orchestrates execution through nine sequential stages:

```
[Step 1] Ingest & Validate Inputs (VoyageMetadata, Tier1Phase2Predictions)
   │
[Step 2] Resolve Single Authoritative Fuel Price via resolve_fuel_price_usd_per_l()
   │
[Step 3] Execute Tier 2 Baseline via calculate_tier2_baseline()
   │      └── Baseline Fuel Cost, Baseline Operational CII, Resolved Price
   │
[Step 4] Execute Tier 3 Feasibility via calculate_tier3_clean_energy_feasibility()
   │      └── Effective Capacity, Usable Battery, Climatological Solar, Utilized Clean Energy
   │
[Step 5] Execute Tier 4 Displacement via calculate_tier4_engineering_scenario_estimates()
   │      └── Displaced Fuel & CO2 (from clean_energy_utilized_kwh ONLY), Net Assisted Metrics
   │
[Step 6] Construct Audit Metadata (Frozen SHA-256 Model Hashes, Integrity Flags)
   │
[Step 7] Assemble Complete Phase3Output Payload
   │
[Step 8] Trigger Pydantic Root Cross-Tier Invariant Validators
   │      ├── Enforce Single Fuel Price across Tier 2 and Applied Parameters
   │      ├── Cap Displaced Fuel <= Total Predicted Fuel
   │      └── Cap Displaced CO2 <= Total Baseline CO2
   │
[Step 9] Return Validated Phase3Output Instance
```

---

## 5. Field Provenance & Epistemic Traceability

| Target Field in `Phase3Output` | Sourcing Tier | Responsible Lower-Tier Function | Epistemic Source |
|---|---|---|---|
| `voyage_metadata.*` | Metadata | Direct Ingestion | Voyage Log / Specification |
| `tier_1_phase2_predictions.weather.*` | Tier 1 | Ingestion / `phase2_pipeline.py` | `weather_final.joblib` (Descriptive Context) |
| `tier_1_phase2_predictions.fuel_consumption_L.value` | Tier 1 | Ingestion / `phase2_pipeline.py` | `fuel_xgb.joblib` (Inferred Liters) |
| `tier_1_phase2_predictions.co2_emissions_kg.value` | Tier 1 | Ingestion / `phase2_pipeline.py` | Fuel $\times$ Emission Factor |
| `tier_1_phase2_predictions.battery_health.predicted_soh` | Tier 1 | Ingestion / `phase2_pipeline.py` | `battery_soh_final.joblib` |
| `tier_1_phase2_predictions.battery_operation.predicted_soc_end_of_voyage` | Tier 1 | Ingestion / `phase2_pipeline.py` | `battery_soc_lstm.pt` / SOH Coulomb Counting |
| `tier_2_baseline_metrics.baseline_fuel_cost_usd` | Tier 2 | `phase3_baseline.calculate_tier2_baseline` | Predicted Fuel $\times$ Sourced/Override Price |
| `tier_2_baseline_metrics.baseline_operational_cii`| Tier 2 | `phase3_baseline.calculate_tier2_baseline` | IMO MEPC.352(78) Formula |
| `tier_2_baseline_metrics.fuel_price_usd_per_l` | Tier 2 | `phase3_baseline.resolve_fuel_price_usd_per_l` | Authoritative Sourced / Override Price |
| `tier_3_clean_energy_feasibility.usable_battery_energy_kwh` | Tier 3 | `phase3_feasibility.calculate_tier3_clean_energy_feasibility` | $C_{\text{nom}} \times \text{SOH} \times \max(0, \text{SOC}_{\text{init}} - \text{SOC}_{\text{res}})$ |
| `tier_3_clean_energy_feasibility.estimated_solar_energy_kwh` | Tier 3 | `phase3_feasibility.calculate_tier3_clean_energy_feasibility` | NASA POWER Climatology $\times$ Area $\times \eta \times \text{Derate} \times \frac{\text{Dur}}{24}$ |
| `tier_3_clean_energy_feasibility.clean_energy_utilized_kwh` | Tier 3 | `phase3_feasibility.calculate_clean_energy_balance` | $\min(\text{Available}, \text{Demand})$ |
| `tier_3_clean_energy_feasibility.feasibility_status` | Tier 3 | `phase3_feasibility.calculate_clean_energy_balance` | `FEASIBLE` if Balance $\ge 0$, else `PARTIAL` |
| `tier_4_engineering_scenario_estimates.status` | Tier 4 | `phase3_displacement.py` | Mandatory `"ENGINEERING SCENARIO ESTIMATE"` |
| `tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L` | Tier 4 | `phase3_displacement.calculate_tier4_engineering_scenario_estimates` | $\frac{E_{\text{clean\_util}} \times \text{SFOC}}{\rho_{\text{fuel}}}$ capped at Baseline Fuel |
| `tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg` | Tier 4 | `phase3_displacement.calculate_tier4_engineering_scenario_estimates` | $\text{Fuel}_{\text{disp}} \times \rho_{\text{fuel}} \times C_F$ capped at Baseline $\text{CO}_2$ |
| `tier_4_engineering_scenario_estimates.net_assisted_fuel_L` | Tier 4 | `phase3_displacement.calculate_net_assisted_metrics` | Baseline Fuel $-$ Displaced Fuel |
| `tier_4_engineering_scenario_estimates.net_assisted_co2_kg` | Tier 4 | `phase3_displacement.calculate_net_assisted_metrics` | Baseline $\text{CO}_2$ $-$ Displaced $\text{CO}_2$ |
| `tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd` | Tier 4 | `phase3_displacement.calculate_net_assisted_metrics` | Net Fuel $\times$ Resolved Fuel Price |
| `tier_4_engineering_scenario_estimates.net_assisted_operational_cii`| Tier 4 | `phase3_displacement.calculate_net_assisted_metrics` | Net $\text{CO}_2 \times 1000 / (\text{DWT} \times \text{dist})$ |
| `tier_4_engineering_scenario_estimates.delta_fuel_pct` | Tier 4 | `phase3_displacement.calculate_net_assisted_metrics` | Relative change in fuel (%) |
| `tier_4_engineering_scenario_estimates.delta_cii_pct` | Tier 4 | `phase3_displacement.calculate_net_assisted_metrics` | Relative change in operational CII (%) |
| `applied_scenario_parameters.*` | Metadata | Direct Assembly in Coordinator | Validated Applied Inputs & Constants |
| `audit_metadata.*` | Metadata | `phase3_contracts.AuditMetadata` | Frozen Model Hashes & Freeze Flags |

---

## 6. Critical Invariant Enforcement

### 6.1 Single Resolved Fuel Price
Phase 3E enforces that exactly ONE fuel price is resolved for any scenario. Calling `resolve_fuel_price_usd_per_l` establishes the price that is simultaneously passed to Tier 2 baseline calculations, recorded in `AppliedScenarioParameters`, and passed to Tier 4 net fuel cost derivations. Any divergence immediately triggers a Pydantic `ValidationError`.

### 6.2 Strict Tier 3 $\rightarrow$ Tier 4 Displacement Boundary
Tier 4 displacement consumes **ONLY** `tier3_feasibility.clean_energy_utilized_kwh`. Surplus clean energy (`total_clean_energy_available_kwh - clean_energy_utilized_kwh`) is curtailed by physical battery storage limitations and auxiliary demand limits. It is **never** credited towards additional generator displacement.

### 6.3 Displacement Capping
Displaced auxiliary generator fuel and $\text{CO}_2$ are strictly capped at baseline voyage predictions ($\text{Fuel}_{\text{disp}} \le \text{Fuel}_{\text{pred}}$ and $\text{CO}_{2,\text{disp}} \le \text{CO}_{2,\text{pred}}$). Clean assistance can never yield negative net consumption or negative net emissions.

### 6.4 Weather Descriptive Boundary
The Phase 2 weather model (`weather_final.joblib`) is descriptive context only (34.72% accuracy baseline). Phase 3E passes weather metadata into Tier 1 unchanged and strictly prevents it from being used to modulate solar yield, battery reserve buffers, dispatch control, or safety abort thresholds.

---

## 7. Determinism, Idempotency, and Side-Effect Boundaries

* **Bit-for-Bit Determinism:** Given identical inputs, repeated executions of `orchestrate_phase3_voyage` yield identical `Phase3Output` dictionary dumps.
* **No Randomness or External State:** Zero stochastic calls, zero system clock dependencies (`datetime.now`), and zero network requests.
* **Side-Effect Free:** Phase 3E writes zero files to `data/raw/`, `data/reference/`, `data/processed/`, or `models/`. All reference lookups against `ship_profiles.csv` and NASA monthly climatology are strictly read-only.

---

## 8. Requirements to Test Traceability Matrix

The Phase 3E test suite ([`tests/test_phase3e_coordinator.py`](file:///C:/maritime%20grids/tests/test_phase3e_coordinator.py)) implements 28 targeted unit and integration tests:

| Test Focus / Requirement | Test Name | Status |
|---|---|---|
| Complete orchestration for Oil Service Boat | `test_successful_orchestration_oil_service_boat` | PASSED |
| Complete orchestration for Fishing Trawler | `test_successful_orchestration_fishing_trawler` | PASSED |
| Complete orchestration for Surfer Boat | `test_successful_orchestration_surfer_boat` | PASSED |
| Complete orchestration for Tanker Ship | `test_successful_orchestration_tanker_ship` | PASSED |
| `run_coordinator_scenario` helper interface | `test_run_coordinator_scenario_interface` | PASSED |
| Tier ordering and complete hierarchy | `test_tier_ordering_and_structure` | PASSED |
| Weather prediction descriptive metadata retention | `test_weather_prediction_retained_as_descriptive_metadata` | PASSED |
| Fuel and $\text{CO}_2$ propagation to Tier 2 and Tier 4 | `test_data_propagation_fuel_and_co2_to_tier2_and_tier4` | PASSED |
| SOH propagation to Tier 3 effective capacity | `test_data_propagation_soh_to_tier3` | PASSED |
| Single fuel price consistency across all tiers | `test_single_fuel_price_consistency_across_all_tiers` | PASSED |
| Anti-double-counting: surplus clean energy not displaced | `test_critical_anti_double_counting_surplus_clean_energy` | PASSED |
| Scenario fuel price override | `test_fuel_price_override` | PASSED |
| Engineering constants overrides (SFOC, density, EF) | `test_engineering_constants_overrides` | PASSED |
| Initial SOC and SOC reserve overrides | `test_soc_overrides` | PASSED |
| Solar derate factor override | `test_solar_derate_override` | PASSED |
| Corridor climatology lookup via route and month | `test_route_and_month_climatology_lookup` | PASSED |
| Zero auxiliary demand edge case | `test_zero_auxiliary_demand` | PASSED |
| Zero solar insolation edge case | `test_zero_solar_insolation` | PASSED |
| Partial feasibility classification | `test_partial_feasibility_status` | PASSED |
| Boundary initial SOC equal to reserve | `test_boundary_initial_soc_equal_to_reserve` | PASSED |
| Boundary full SOC ($1.0$) and zero reserve | `test_boundary_full_soc` | PASSED |
| Error propagation: invalid voyage metadata | `test_invalid_voyage_metadata_raises` | PASSED |
| Error propagation: invalid Tier 1 predictions | `test_invalid_tier1_predictions_raises` | PASSED |
| Error propagation: unknown ship type | `test_unknown_ship_type_raises` | PASSED |
| Error propagation: missing route and month when GHI omitted | `test_missing_route_and_month_raises` | PASSED |
| Determinism and idempotency verification | `test_coordinator_deterministic_and_idempotent` | PASSED |
| Delegation to lower-tier calculation modules (no duplication) | `test_no_formula_duplication_delegates_to_lower_tiers` | PASSED |
| Root contract invariant enforcement | `test_root_contract_enforces_invariants` | PASSED |

---

## 9. Known Architectural Limitations

1. **Static Aggregate Voyage Model:** Phase 3E orchestrates cumulative voyage quantities. It does not perform minute-by-minute or hourly dynamic dispatch simulation.
2. **Auxiliary Displacement Only:** Clean electrical energy offsets diesel generator electrical loads only; main mechanical propulsion engines are not displaced.
3. **Climatological Insolation:** Solar generation reflects monthly mean daily insolation scaled by voyage duration, abstracting away diurnal peak vs. nighttime cycles.
