# Phase 3D — Tier 4 Displacement & Assisted Scenario Documentation

**Project Root:** `C:\maritime grids`  
**Module:** `phase3_displacement.py`  
**Test Suite:** `tests/test_phase3d_displacement.py`  
**Status:** IMPLEMENTED AND VERIFIED  

---

## 1. Purpose & Architectural Role

Phase 3D implements Tier 4 (`Tier4EngineeringScenarioEstimates`) of the Maritime Grid Simulation Decision Coordinator. It computes auxiliary diesel-generator equivalent fuel and $\text{CO}_2$ displacement achieved by the clean electrical energy utilized from Tier 3 (`clean_energy_utilized_kwh`), and derives the resulting net assisted voyage performance metrics (fuel consumption, $\text{CO}_2$ emissions, fuel expenditure, operational Carbon Intensity Indicator (CII), and percentage deltas relative to baseline).

---

## 2. Implementation Scope

* **Included:**
  * Deterministic calculation of auxiliary diesel-generator fuel displacement from `clean_energy_utilized_kwh`.
  * Deterministic calculation of auxiliary generator $\text{CO}_2$ displacement from displaced fuel.
  * Calculation of net assisted fuel consumption ($\text{L}$), net assisted $\text{CO}_2$ ($\text{kg}$), net assisted fuel cost ($\text{USD}$), and net assisted operational CII ($\text{g CO}_2 / \text{DWT} \cdot \text{nm}$).
  * Calculation of relative delta percentages for fuel consumption ($\Delta \text{Fuel } [\%]$) and operational CII ($\Delta \text{CII } [\%]$).
  * Enforcement of strict physical conservation invariants and capping logic preventing displacement from exceeding baseline quantities.
  * Enforcement of single resolved fuel price across Tier 2 and Tier 4.
  * Safe handling of edge cases (zero clean energy, zero auxiliary demand, zero baseline fuel/CII).
  * Conformance to the Pydantic schema `Tier4EngineeringScenarioEstimates` with immutable `status = "ENGINEERING SCENARIO ESTIMATE"`.
* **Explicitly Excluded (Out of Scope):**
  * Main propulsion engine fuel displacement or hybrid/electric mechanical drive.
  * Dynamic dispatch optimization, variable engine load modeling, or minute-by-minute simulation.
  * Machine-learning model training, refitting, or execution.
  * Modification of frozen Phase 2 artifacts, contracts, or prior tier modules.

---

## 3. Data Sources & Epistemic Classification

| Parameter / Field | Source | Epistemic Classification |
|---|---|---|
| `clean_energy_utilized_kwh` | Tier 3 (`Tier3CleanEnergyFeasibility`) | Derived Physical Feasibility Budget |
| `predicted_fuel_consumption_L` | Tier 1 (`Tier1Phase2Predictions`) / `phase3_baseline.py` | Modeled (Phase 2 XGBoost Regressor) |
| `predicted_CO2_kg` | Tier 1 (`Tier1Phase2Predictions`) / `phase3_baseline.py` | Authoritative Phase 2 Deterministic Product |
| `baseline_fuel_cost_usd` | Tier 2 (`Tier2BaselineCalculations`) | Derived Baseline Financial Metric |
| `baseline_operational_cii` | Tier 2 (`Tier2BaselineCalculations`) | Derived Baseline IMO Metric |
| `specific_fuel_oil_consumption_kg_per_kwh` | `AppliedScenarioParameters` (default $0.220$) | Configurable Engineering Assumption |
| `fuel_density_kg_per_l` | `AppliedScenarioParameters` (default $0.850$) | Sourced Physical Constant (MGO @ 15°C) |
| `fuel_co2_emission_factor_cf` | IMO MEPC.245(66) / MEPC.308(73) (fixed $3.114$) | Sourced International Regulatory Standard |
| `resolved_fuel_price_usd_per_l` | Tier 2 resolution (`ship_profiles.csv` or override) | Sourced Economic Parameter |
| `deadweight_tonnage` | `data/reference/ship_profiles.csv` | Observed Hardware Fact |
| `voyage_distance_nm` | `VoyageMetadata` | Operational Scenario Input |

---

## 4. Governing Formulas & Calculations

### 4.1 Auxiliary Fuel Displacement
$$\text{fuel\_displaced\_raw\_L} = \frac{\text{clean\_energy\_utilized\_kwh} \times \text{specific\_fuel\_oil\_consumption\_kg\_per\_kwh}}{\text{fuel\_density\_kg\_per\_l}}$$
$$\text{estimated\_fuel\_displaced\_L} = \min(\max(0.0, \text{fuel\_displaced\_raw\_L}), \text{predicted\_fuel\_consumption\_L})$$
* Converts delivered electrical energy ($\text{kWh}$) to displaced auxiliary fuel mass ($\text{kg}$) via generator brake SFOC, and then to volume ($\text{L}$) via fuel density.
* Capped at `predicted_fuel_consumption_L` to ensure displacement never exceeds baseline voyage fuel consumption.

### 4.2 Auxiliary $\text{CO}_2$ Displacement
$$\text{co2\_displaced\_raw\_kg} = \text{estimated\_fuel\_displaced\_L} \times \text{fuel\_density\_kg\_per\_l} \times C_F$$
$$\text{estimated\_co2\_displaced\_kg} = \min(\max(0.0, \text{co2\_displaced\_raw\_kg}), \text{predicted\_CO2\_kg})$$
* Displaced $\text{CO}_2$ is calculated directly from the capped displaced fuel volume, ensuring strict physical stoichiometry.
* Capped at `predicted_CO2_kg` to ensure emissions reductions cannot exceed total baseline emissions.

### 4.3 Net Assisted Performance Metrics
$$\text{assisted\_fuel\_consumption\_L} = \max(0.0, \text{predicted\_fuel\_consumption\_L} - \text{estimated\_fuel\_displaced\_L})$$
$$\text{assisted\_co2\_kg} = \max(0.0, \text{predicted\_CO2\_kg} - \text{estimated\_co2\_displaced\_kg})$$
$$\text{assisted\_fuel\_cost\_usd} = \text{assisted\_fuel\_consumption\_L} \times \text{resolved\_fuel\_price\_usd\_per\_l}$$
$$\text{assisted\_operational\_cii} = \frac{\text{assisted\_co2\_kg} \times 10^6}{\text{deadweight\_tonnage} \times \text{voyage\_distance\_nm}}$$

### 4.4 Relative Percentage Changes
$$\Delta \text{Fuel } [\%] = \begin{cases} \left(\frac{\text{assisted\_fuel\_consumption\_L} - \text{predicted\_fuel\_consumption\_L}}{\text{predicted\_fuel\_consumption\_L}}\right) \times 100.0 & \text{if } \text{predicted\_fuel\_consumption\_L} > 0 \\ 0.0 & \text{if } \text{predicted\_fuel\_consumption\_L} = 0 \end{cases}$$

$$\Delta \text{CII } [\%] = \begin{cases} \left(\frac{\text{assisted\_operational\_cii} - \text{baseline\_operational\_cii}}{\text{baseline\_operational\_cii}}\right) \times 100.0 & \text{if } \text{baseline\_operational\_cii} > 0 \\ 0.0 & \text{if } \text{baseline\_operational\_cii} = 0 \end{cases}$$
* Zero-division safeguards guarantee deterministic float outputs ($0.0$) rather than `NaN` or unhandled exceptions.

---

## 5. Default Engineering Assumptions

1. **Specific Fuel Oil Consumption (SFOC):** $0.220\text{ kg/kWh}$ ($220\text{ g/kWh}$).
   * Represents standard auxiliary diesel generator set efficiency operating under typical marine auxiliary loads (50%–85% MCR).
2. **Fuel Density ($\rho_{\text{fuel}}$):** $0.850\text{ kg/L}$ ($850\text{ kg/m}^3$).
   * Standard density of ISO 8217 DMA/DMZ grade Marine Gas Oil (MGO) at 15°C.
3. **Carbon Conversion Factor ($C_F$):** $3.114\text{ kg CO}_2 / \text{kg fuel}$.
   * Official IMO MEPC.245(66) and MEPC.308(73) carbon emission factor for marine diesel / gas oil.

---

## 6. Conservation Invariants & Cap Logic

Phase 3D strictly verifies the following physical and accounting invariants:

1. **Upper Bound Displacement Cap:**
   $$\text{estimated\_fuel\_displaced\_L} \le \text{predicted\_fuel\_consumption\_L}$$
   $$\text{estimated\_co2\_displaced\_kg} \le \text{predicted\_CO2\_kg}$$
2. **Exact Conservation Additivity:**
   $$\text{assisted\_fuel\_consumption\_L} + \text{estimated\_fuel\_displaced\_L} \equiv \text{predicted\_fuel\_consumption\_L}$$
   $$\text{assisted\_co2\_kg} + \text{estimated\_co2\_displaced\_kg} \equiv \text{predicted\_CO2\_kg}$$
3. **Non-Negativity Constraint:**
   $$\text{estimated\_fuel\_displaced\_L} \ge 0.0, \quad \text{estimated\_co2\_displaced\_kg} \ge 0.0$$
   $$\text{assisted\_fuel\_consumption\_L} \ge 0.0, \quad \text{assisted\_co2\_kg} \ge 0.0$$
   $$\text{assisted\_fuel\_cost\_usd} \ge 0.0, \quad \text{assisted\_operational\_cii} \ge 0.0$$
4. **Directional Non-Positive Delta:**
   $$\Delta \text{Fuel } [\%] \le 0.0, \quad \Delta \text{CII } [\%] \le 0.0$$
   *(Clean assistance never increases fuel consumption or emissions).*

---

## 7. Status Field Value & Engineering Rationale

The `status` attribute in `Tier4EngineeringScenarioEstimates` is hard-coded and validated as:
```python
status: str = "ENGINEERING SCENARIO ESTIMATE"
```
### Rationale:
* Tier 4 is **NOT** a machine-learning prediction.
* Tier 4 is **NOT** an operational dispatch schedule or telemetry recording.
* Tier 4 represents a post-hoc engineering counterfactual: if clean electrical energy displaced generator load at standard generator efficiency, what would be the resulting fuel, $\text{CO}_2$, cost, and CII reductions?
* Stamping the output as `"ENGINEERING SCENARIO ESTIMATE"` prevents downstream misinterpretation by operators or compliance auditors.

---

## 8. Input Validation Matrix

| Parameter | Type / Constraint | Validation Rule | Error Behavior |
|---|---|---|---|
| `clean_energy_utilized_kwh` | `float`, finite, $\ge 0.0$ | Physical energy quantity | Raises `ValueError` |
| `predicted_fuel_consumption_L` | `float`, finite, $\ge 0.0$ | Baseline volume | Raises `ValueError` |
| `predicted_CO2_kg` | `float`, finite, $\ge 0.0$ | Baseline emissions | Raises `ValueError` |
| `baseline_fuel_cost_usd` | `float`, finite, $\ge 0.0$ | Baseline cost | Raises `ValueError` |
| `baseline_operational_cii` | `float`, finite, $\ge 0.0$ | Baseline CII | Raises `ValueError` |
| `specific_fuel_oil_consumption_kg_per_kwh`| `float`, finite, $> 0.0$ | Non-zero generator efficiency | Raises `ValueError` |
| `fuel_density_kg_per_l` | `float`, finite, $> 0.0$ | Non-zero physical density | Raises `ValueError` |
| `fuel_co2_emission_factor_cf` | `float`, finite, $> 0.0$ | Non-zero stoichiometry | Raises `ValueError` |
| `resolved_fuel_price_usd_per_l` | `float`, finite, $> 0.0$ | Non-zero economic unit cost | Raises `ValueError` |
| `deadweight_tonnage` | `float`, finite, $> 0.0$ | Ship capacity parameter | Raises `ValueError` |
| `voyage_distance_nm` | `float`, finite, $> 0.0$ | Voyage length parameter | Raises `ValueError` |
| Any NaN or Infinite input | `math.isnan(x) or math.isinf(x)` | Strict finiteness check | Raises `ValueError` |

---

## 9. Requirements to Test Traceability Matrix

| Requirement / Test Focus | Unit Test Name | Test Result |
|---|---|---|
| Nominal fuel displacement formula | `test_normal_fuel_displacement` | PASSED |
| Nominal $\text{CO}_2$ displacement stoichiometry | `test_normal_co2_displacement` | PASSED |
| Net assisted fuel computation | `test_net_assisted_fuel` | PASSED |
| Net assisted $\text{CO}_2$ computation | `test_net_assisted_co2` | PASSED |
| Net assisted fuel cost calculation | `test_net_assisted_fuel_cost` | PASSED |
| Net assisted operational CII calculation | `test_net_assisted_cii` | PASSED |
| Delta fuel percentage calculation | `test_fuel_percentage_change` | PASSED |
| Delta CII percentage calculation | `test_cii_percentage_change` | PASSED |
| Zero clean energy behavior | `test_zero_clean_energy` | PASSED |
| Zero auxiliary demand yields zero displacement | `test_zero_auxiliary_demand_yields_zero_displacement` | PASSED |
| Clean energy equals auxiliary demand | `test_clean_energy_equals_auxiliary_demand` | PASSED |
| Clean energy exceeds demand capped safely | `test_clean_energy_exceeds_demand_consumed_safely` | PASSED |
| Fuel displacement capping at baseline | `test_fuel_displacement_cap` | PASSED |
| $\text{CO}_2$ displacement capping at baseline | `test_co2_displacement_cap` | PASSED |
| Invalid non-positive SFOC rejection | `test_invalid_sfoc` | PASSED |
| Invalid non-positive fuel density rejection | `test_invalid_fuel_density` | PASSED |
| Invalid non-positive carbon factor rejection | `test_invalid_emission_factor` | PASSED |
| Invalid non-positive fuel price rejection | `test_invalid_fuel_price` | PASSED |
| Invalid non-positive DWT rejection | `test_invalid_dwt` | PASSED |
| Invalid non-positive voyage distance rejection | `test_invalid_voyage_distance` | PASSED |
| Rejection of NaN values | `test_nan_input_rejection` | PASSED |
| Rejection of Infinite values | `test_infinite_input_rejection` | PASSED |
| Safe division handling for zero baseline fuel | `test_zero_baseline_fuel_handling` | PASSED |
| Safe division handling for zero baseline CII | `test_zero_baseline_co2_handling` | PASSED |
| Direct Pydantic Tier 4 contract validation | `test_contract_validation` | PASSED |
| End-to-end root contract validator compatibility | `test_phase3_output_root_validator_compatibility` | PASSED |
| Exact physical conservation invariants | `test_conservation_invariant_checks` | PASSED |
| End-to-end multi-tier deterministic integration trace | `test_deterministic_end_to_end_trace` | PASSED |

---

## 10. Known Architectural Limitations

1. **Auxiliary Displacement Only:** Clean energy (solar PV and battery) is applied exclusively to satisfy auxiliary electrical hotel loads. Main propulsion mechanical shaft power is not replaced.
2. **No Electric Propulsion / Hybrid Transmission:** Ships without diesel-electric propulsion cannot divert auxiliary electrical energy to main thrusters.
3. **Static Lumped Aggregate Scenario:** Calculations evaluate cumulative voyage totals. They do not simulate variable generator loading transients, spinning reserves, or minimum diesel generator loading limits (e.g., preventing generator fouling below 30% load).
4. **No Weather Coupling to Engine Performance:** Displacement does not dynamically adjust SFOC based on ambient weather or sea state.
