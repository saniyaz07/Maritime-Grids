# Phase 3G — Fleet & Annual Multi-Voyage Schedule Aggregation Documentation

**Project Root:** `C:\maritime grids`  
**Module:** `phase3g_fleet.py`  
**Test Suite:** `tests/test_phase3g_fleet.py`  
**Status:** IMPLEMENTED AND FULLY VERIFIED  

---

> [!IMPORTANT]
> **Mandatory Methodological Disclosure:**  
> Fleet and annual aggregations are deterministic schedule summaries derived from frozen Phase 2 voyage point predictions and assumed auxiliary generator parameters. They do not constitute dispatch simulations, dynamic weather-routed schedules, or guaranteed annual savings.

---

## 1. Purpose & Overview

Phase 3G implements the **Fleet & Annual Multi-Voyage Schedule Aggregation Layer** for the Maritime Grid Simulation. It aggregates ordered sequences of discrete commercial voyages into multi-voyage operational schedules (e.g. quarterly or 12-month annual profiles) for single vessels.

Phase 3G acts as an authoritative, typed aggregation layer over Phase 3E single-voyage orchestrations:
1. Ingests an ordered schedule of discrete voyages (`VoyageScheduleEntry`).
2. Resolves voyage-level parameter overrides against schedule-wide base scenario parameters.
3. Delegates each voyage evaluation to `orchestrate_phase3_voyage` in Phase 3E (exactly $N$ delegations for $N$ voyages).
4. Accumulates transport work, baseline fuel, baseline $\text{CO}_2$, clean energy utilized, curtailed clean energy, and fuel/$\text{CO}_2$ displacements.
5. Derives annual operational Carbon Intensity Indicator (CII) conforming strictly to **IMO Resolution MEPC.352(78)** from cumulative transport work.
6. Enforces physical conservation identities and displacement bounds.
7. Tracks feasibility counts (`FEASIBLE` and `PARTIAL`) and retains complete single-voyage evaluation traces.

---

## 2. Scope & Non-Scope

### 2.1 In Scope
- Ordered schedule ingestion and validation (`AnnualFleetEvaluationRequest`).
- Single-vessel schedule integrity enforcement (non-empty schedule, unique `voyage_id`, uniform `ship_type`).
- Parameter inheritance and override resolution (`ScenarioOverride` precedence over `base_scenario_parameters`).
- Pure delegation to Phase 3E (`orchestrate_phase3_voyage`).
- Cumulative metric aggregation across distance, duration, transport work, fuel, costs, clean energy, and emissions.
- Cumulative transport-work weighted annual operational CII calculation.
- Mathematical verification that annual operational CII is not an arithmetic average of single-voyage CIIs.
- Physical fuel and $\text{CO}_2$ conservation checks ($\text{Assisted} + \text{Displaced} \equiv \text{Baseline}$).
- Feasibility status tracking (`feasible_voyage_count`, `partial_voyage_count`).
- Full auditability via `voyage_evaluations` trace and `audit_metadata`.

### 2.2 Out of Scope
- **No Machine Learning Models:** Zero model loading, inference, training, retraining, or hyperparameter tuning. All Phase 2 models remain cryptographically frozen.
- **No Autonomous Machinery Control:** No governor setpoints, battery charge dispatching, or engine control.
- **No Route or Speed Optimization:** Voyage routes, distances, durations, and speeds are fixed inputs.
- **No Dispatch Engine:** No multi-vessel dynamic route assignment or fleet dispatch scheduling.
- **No Weather Dispatch Gating:** Weather classifications remain descriptive metadata; climatological monthly GHI is looked up deterministically.
- **No Replacement of Phase 3E or 3F:** Phase 3G delegates to Phase 3E for physics and economics and does not duplicate lower-tier equations.

---

## 3. Architectural Design & Workflow

```text
AnnualFleetEvaluationRequest
   │
   ├── vessel_id
   ├── base_scenario_parameters (AppliedScenarioParameters)
   └── schedule: [VoyageScheduleEntry_1, ..., VoyageScheduleEntry_N]
                │
                ▼
        Validation & Integrity Checks
        ├── Non-empty schedule
        ├── Unique voyage IDs
        └── Consistent ship_type
                │
                ▼
        Parameter Resolution (Precedence: Voyage Override -> Base Scenario -> Defaults)
                │
                ▼
        Phase 3E Orchestrator (orchestrate_phase3_voyage)
        [Executed exactly N times — once per scheduled voyage]
                │
                ▼
        N x Validated Phase3Output Records
                │
                ▼
        Phase 3G Cumulative Aggregation & Invariant Validation
        ├── Sum distance, duration, transport work: Σ (DWT * Distance)
        ├── Sum baseline fuel, costs, and CO2 emissions
        ├── Sum clean energy utilized and curtailed
        ├── Sum fuel and CO2 displacements
        ├── Sum net assisted fuel, costs, and CO2 emissions
        ├── Enforce exact fuel & CO2 conservation identities
        └── Derive IMO MEPC.352(78) Annual Baseline & Assisted Operational CII
                │
                ▼
        AnnualScheduleSummary
```

---

## 4. Contract Specifications

### 4.1 `VoyageScheduleEntry`
Encapsulates a single transit within an annual or multi-voyage operational schedule:
- `voyage_id`: Unique non-empty string identifier.
- `voyage_metadata`: Authoritative `VoyageMetadata` (`ship_type`, `distance_nm`, `voyage_duration_hours`, `deadweight_tonnes`).
- `tier_1_phase2_predictions`: Authoritative `Tier1Phase2Predictions` from frozen Phase 2 ML models.
- `route_id`: Commercial corridor identifier (e.g. `'Escravos-Lagos'`).
- `month`: Operational month (name `'January'` or integer `1`–`12`) for monthly NASA climatological solar insolation lookup.
- `scenario_overrides`: Optional `ScenarioOverride` for voyage-specific parameters.

### 4.2 `AnnualFleetEvaluationRequest`
Defines the multi-voyage evaluation request:
- `vessel_id`: Unique tracking identifier for the vessel.
- `schedule`: Ordered list of `VoyageScheduleEntry` objects ($\ge 1$).
- `base_scenario_parameters`: Default `AppliedScenarioParameters` applied across the schedule.
- `ship_profiles_csv`: Optional path to custom ship specification CSV.
- `climatology_csv`: Optional path to custom monthly NASA climatology CSV.

**Model Validators:**
- Rejects empty schedule.
- Detects and rejects duplicate `voyage_id`s.
- Enforces uniform `ship_type` across the schedule.

### 4.3 `AnnualScheduleSummary`
Defines the authoritative aggregated operational and environmental output:
- `vessel_id`: Vessel identifier.
- `ship_type`: Vessel category.
- `total_voyages`: Total voyages evaluated ($N$).
- `total_distance_nm`: Cumulative distance transited in nautical miles.
- `total_duration_hours`: Cumulative operating duration in hours.
- `total_transport_work_dwt_nm`: Cumulative transport work ($\sum_{k=1}^N \text{DWT}_k \times \text{Distance}_k$).
- `total_baseline_fuel_L`: Cumulative unassisted baseline fuel consumed.
- `total_baseline_fuel_cost_usd`: Cumulative baseline fuel expenditure in USD.
- `total_baseline_co2_kg`: Cumulative baseline $\text{CO}_2$ emissions in kg.
- `annual_baseline_operational_cii`: Baseline annual CII in $\text{gCO}_2 / (\text{DWT} \cdot \text{nm})$.
- `total_clean_energy_utilized_kwh`: Cumulative clean auxiliary electrical energy consumed.
- `total_clean_energy_curtailed_kwh`: Cumulative clean electrical energy generated but unutilized.
- `total_fuel_displaced_L`: Cumulative fuel displacement achieved through clean auxiliary energy.
- `total_co2_displaced_kg`: Cumulative $\text{CO}_2$ displacement achieved.
- `total_assisted_fuel_L`: Cumulative net assisted fuel consumption.
- `total_assisted_fuel_cost_usd`: Cumulative net assisted fuel cost in USD.
- `total_assisted_co2_kg`: Cumulative net assisted $\text{CO}_2$ emissions in kg.
- `annual_assisted_operational_cii`: Net assisted annual operational CII in $\text{gCO}_2 / (\text{DWT} \cdot \text{nm})$.
- `annual_delta_fuel_pct`: Percentage change in annual fuel consumption.
- `annual_delta_cost_pct`: Percentage change in annual fuel expenditure.
- `annual_delta_cii_pct`: Percentage change in annual operational CII.
- `feasible_voyage_count`: Count of voyages where auxiliary load was 100% met (`FEASIBLE`).
- `partial_voyage_count`: Count of voyages where auxiliary load was partially met (`PARTIAL`).
- `voyage_evaluations`: Complete ordered list of underlying `Phase3Output` records.
- `audit_metadata`: Standardized verification timestamp and schema versioning.

---

## 5. Mathematical Formulations & Standards

### 5.1 Cumulative Transport Work
Per maritime transport economics and IMO guidelines:
$$W_{\text{total}} = \sum_{k=1}^N \left(\text{DWT}_k \times \text{Distance}_k\right) \quad [\text{DWT} \cdot \text{nm}]$$

### 5.2 Annual Operational CII (IMO Resolution MEPC.352(78))
The Carbon Intensity Indicator is strictly an aggregate operational index measuring cumulative carbon emitted per unit of cumulative transport work delivered:
$$\text{CII}_{\text{annual, baseline}} = \frac{\sum_{k=1}^N \text{CO}_{2,\text{baseline},k} \times 1000.0}{W_{\text{total}}} \quad \left[\frac{\text{gCO}_2}{\text{DWT} \cdot \text{nm}}\right]$$

$$\text{CII}_{\text{annual, assisted}} = \frac{\sum_{k=1}^N \text{CO}_{2,\text{assisted},k} \times 1000.0}{W_{\text{total}}} \quad \left[\frac{\text{gCO}_2}{\text{DWT} \cdot \text{nm}}\right]$$

### 5.3 Non-Equivalence with Arithmetic Averaging
Taking the arithmetic mean of individual voyage CIIs produces a mathematically erroneous value whenever voyages vary in distance or cargo capacity:
$$\text{CII}_{\text{annual}} \ne \frac{1}{N} \sum_{k=1}^N \text{CII}_k$$

Phase 3G enforces this rule strictly and verifies it with explicit counterexample tests.

### 5.4 Conservation Invariants
To prevent numerical drift and accounting errors across cumulative aggregations:
$$\text{Total Fuel}_{\text{assisted}} + \text{Total Fuel}_{\text{displaced}} \equiv \text{Total Fuel}_{\text{baseline}} \quad (\pm 10^{-4}\,\text{L})$$
$$\text{Total CO}_{2,\text{assisted}} + \text{Total CO}_{2,\text{displaced}} \equiv \text{Total CO}_{2,\text{baseline}} \quad (\pm 10^{-4}\,\text{kg})$$
$$\text{Total Fuel}_{\text{displaced}} \le \text{Total Fuel}_{\text{baseline}}$$
$$\text{Total CO}_{2,\text{displaced}} \le \text{Total CO}_{2,\text{baseline}}$$

---

## 6. Primary API Usage

```python
from phase3_contracts import VoyageMetadata, Tier1Phase2Predictions, AppliedScenarioParameters
from phase3g_fleet import (
    VoyageScheduleEntry,
    AnnualFleetEvaluationRequest,
    evaluate_annual_fleet_schedule,
)

# 1. Prepare base scenario parameters
base_params = AppliedScenarioParameters(
    fuel_price_usd_per_l=1.15,
    initial_soc=0.90,
    auxiliary_energy_demand_kwh=180.0,
    soc_reserve=0.20,
    generator_sfoc_kg_per_kwh=0.220,
    fuel_density_kg_per_l=0.850,
    emission_factor_kgco2_per_kgfuel=3.114,
    solar_derate_factor=0.85,
)

# 2. Build schedule entries for the operational period
schedule = [
    VoyageScheduleEntry(
        voyage_id=f"VOY-2026-{month_idx:02d}",
        voyage_metadata=VoyageMetadata(
            ship_type="Oil Service Boat",
            distance_nm=250.0,
            voyage_duration_hours=18.5,
            deadweight_tonnes=1800.0,
        ),
        tier_1_phase2_predictions=tier1_preds,
        route_id="Escravos-Lagos",
        month=month_name,
    )
    for month_idx, month_name in enumerate(["January", "February", ...], start=1)
]

# 3. Evaluate multi-voyage schedule
request = AnnualFleetEvaluationRequest(
    vessel_id="VESSEL-OSB-01",
    schedule=schedule,
    base_scenario_parameters=base_params,
)
summary = evaluate_annual_fleet_schedule(request)

print(f"Total Voyages: {summary.total_voyages}")
print(f"Annual Transport Work: {summary.total_transport_work_dwt_nm:.1f} DWT-nm")
print(f"Annual Baseline CII: {summary.annual_baseline_operational_cii:.3f} gCO2/(DWT*nm)")
print(f"Annual Assisted CII: {summary.annual_assisted_operational_cii:.3f} gCO2/(DWT*nm)")
print(f"Annual CO2 Reduction: {summary.annual_delta_cii_pct:.2f}%")
```

---

## 7. Verification & Test Suite Matrix

The Phase 3G test suite (`tests/test_phase3g_fleet.py`) executes 33 deterministic unit tests covering 8 operational categories:

| Category | Test Function Name | Tested Functionality |
| :--- | :--- | :--- |
| **1. Schedule Execution** | `test_single_voyage_schedule_evaluation` | Single-voyage schedule returns valid summary matching Phase 3E |
| | `test_twelve_month_annual_schedule_evaluation` | 12-month annual schedule aggregates all operational metrics |
| **2. Validation** | `test_empty_schedule_rejected` | Rejects empty voyage schedule |
| | `test_duplicate_voyage_id_rejected` | Rejects duplicate `voyage_id` strings within schedule |
| | `test_inconsistent_ship_type_rejected` | Enforces uniform `ship_type` across single-vessel schedule |
| | `test_invalid_tier1_input_propagation` | Pydantic validation propagation on malformed inputs |
| **3. Delegation** | `test_exact_n_voyage_delegation_spy` | Verifies `orchestrate_phase3_voyage` is invoked exactly $N$ times |
| | `test_schedule_order_preserved` | Verifies `voyage_evaluations` retains strict input ordering |
| **4. Metric Sums** | `test_cumulative_distance_sum` | $\sum \text{Distance} \equiv \text{total\_distance\_nm}$ |
| | `test_cumulative_duration_sum` | $\sum \text{Duration} \equiv \text{total\_duration\_hours}$ |
| | `test_cumulative_transport_work_sum` | $\sum (\text{DWT} \cdot \text{Distance}) \equiv \text{total\_transport\_work\_dwt\_nm}$ |
| | `test_cumulative_baseline_fuel_sum` | $\sum \text{Baseline Fuel} \equiv \text{total\_baseline\_fuel\_L}$ |
| | `test_cumulative_baseline_fuel_cost_sum` | $\sum \text{Baseline Cost} \equiv \text{total\_baseline\_fuel\_cost\_usd}$ |
| | `test_cumulative_baseline_co2_sum` | $\sum \text{Baseline CO}_2 \equiv \text{total\_baseline\_co2\_kg}$ |
| | `test_cumulative_clean_energy_utilized_sum` | $\sum \text{Utilized Clean Energy} \equiv \text{total\_clean\_energy\_utilized\_kwh}$ |
| | `test_cumulative_clean_energy_curtailed_sum` | $\sum \text{Curtailed Clean Energy} \equiv \text{total\_clean\_energy\_curtailed\_kwh}$ |
| | `test_cumulative_fuel_displaced_sum` | $\sum \text{Displaced Fuel} \equiv \text{total\_fuel\_displaced\_L}$ |
| | `test_cumulative_co2_displaced_sum` | $\sum \text{Displaced CO}_2 \equiv \text{total\_co2\_displaced\_kg}$ |
| | `test_cumulative_assisted_fuel_sum` | $\sum \text{Assisted Fuel} \equiv \text{total\_assisted\_fuel\_L}$ |
| | `test_cumulative_assisted_fuel_cost_sum` | $\sum \text{Assisted Cost} \equiv \text{total\_assisted\_fuel\_cost\_usd}$ |
| | `test_cumulative_assisted_co2_sum` | $\sum \text{Assisted CO}_2 \equiv \text{total\_assisted\_co2\_kg}$ |
| **5. Operational CII** | `test_annual_baseline_operational_cii_math` | Baseline CII computed strictly from cumulative transport work |
| | `test_annual_assisted_operational_cii_math` | Assisted CII computed strictly from cumulative transport work |
| | `test_counterexample_cii_not_arithmetic_average` | Formal counterexample proving $\text{CII}_{\text{annual}} \ne \frac{1}{N}\sum \text{CII}_k$ |
| **6. Conservation** | `test_exact_fuel_conservation_identity` | $\text{Assisted} + \text{Displaced} \equiv \text{Baseline Fuel}$ ($\pm 10^{-4}$) |
| | `test_exact_co2_conservation_identity` | $\text{Assisted} + \text{Displaced} \equiv \text{Baseline CO}_2$ ($\pm 10^{-4}$) |
| | `test_displacement_upper_bounds` | Displacements do not exceed baseline quantities |
| **7. Feasibility** | `test_mixed_feasibility_status_counting` | Precise counting of `FEASIBLE` and `PARTIAL` voyages |
| **8. Seasonality & Integrity** | `test_seasonal_monthly_ghi_variation` | Month-to-month solar insolation variance reflected in clean energy |
| | `test_repeated_evaluation_determinism` | Repeated calls produce bitwise identical Pydantic outputs |
| | `test_dict_input_support` | Raw Python dict request validation and conversion |
| | `test_voyage_override_takes_precedence` | Per-voyage overrides supersede base scenario parameters |
| | `test_frozen_model_hashes_verified` | Cryptographic SHA-256 verification of frozen Phase 2 models |

---

## 8. Cryptographic Artifact Integrity

Phase 3G operations maintain absolute isolation from the frozen Phase 2 models:
* `models/battery_soc_lstm.pt`: `c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25`
* `models/battery_soh_final.joblib`: `9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1`
* `models/fuel_xgb.joblib`: `cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323`
* `models/weather_final.joblib`: `39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3`

No model training, tuning, or file modification occurred. `data/raw/` remains untouched.
