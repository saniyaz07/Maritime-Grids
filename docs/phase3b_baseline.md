# Phase 3B — Tier 2 Baseline Calculation Implementation

**Project Root:** `C:\maritime grids`  
**Module:** `phase3_baseline.py`  
**Test Suite:** `tests/test_phase3b_baseline.py`  
**Status:** IMPLEMENTED AND VERIFIED  

---

## 1. Phase 3B Purpose

Phase 3B implements the deterministic, unassisted operational baseline calculations for the Maritime Grid Simulation Decision Coordinator. It consumes authoritative Phase 2 machine-learning predictions and standard maritime economic / environmental indicators to establish the baseline voyage benchmark before any clean-energy interventions are considered.

---

## 2. Tier 2 Position in Architecture

The Decision Coordinator enforces a strict four-tier hierarchy:
* **Tier 1:** Phase 2 ML Predictions (`predicted_weather`, `predicted_fuel_consumption_L`, `predicted_CO2_kg`, `predicted_SOH`, `predicted_SOC_end_of_voyage`).
* **Tier 2 (Phase 3B):** **Deterministic Baseline Metrics** (unassisted fuel cost and baseline operational CII).
* **Tier 3 (Phase 3C):** Clean Energy Feasibility Assessment (battery and solar budget vs auxiliary demand).
* **Tier 4 (Phase 3D):** Engineering Scenario Estimates (auxiliary fuel and $\text{CO}_2$ displacement).

Tier 2 is completely independent of Tier 3 and Tier 4. The baseline values represent the unassisted voyage and must **never** be overwritten, reduced, or modified by clean-energy assistance.

---

## 3. Fuel Price Source & Resolution Hierarchy

Fuel price resolution is handled by `resolve_fuel_price_usd_per_l()` following a strict single-source hierarchy:
1. **Scenario Override:** If an explicit, valid `fuel_price_override_usd_per_l` is supplied, it is validated ($> 0$, finite) and used as the single resolved price.
2. **Vessel Default:** Otherwise, the default fuel price is resolved directly from `data/reference/ship_profiles.csv`:
   - **Oil Service Boat:** \$1.15 USD/L
   - **Fishing Trawler:** \$1.10 USD/L
   - **Surfer Boat:** \$1.20 USD/L
   - **Tanker Ship:** \$0.95 USD/L

**Single Resolved Price Guarantee:** The resolved fuel price is recorded in `tier_2_baseline_metrics.fuel_price_usd_per_l` and mirrored in `applied_scenario_parameters.fuel_price_usd_per_l`. The cross-tier Pydantic model validator rejects any mismatch between Tier 2 and scenario parameters.

---

## 4. Baseline Formulas & Units

### 4.1 Baseline Fuel OPEX
$$\text{baseline\_fuel\_cost\_usd} = \text{predicted\_fuel\_consumption\_L} \times \text{resolved\_fuel\_price\_usd\_per\_l}$$

* `predicted_fuel_consumption_L`: Liters per voyage (Phase 2 XGBoost total voyage fuel prediction, Evidence Level B — Strongly Inferred).
* `resolved_fuel_price_usd_per_l`: USD (\$) per Liter.
* **Output Unit:** USD (\$).
* *Note: Total voyage fuel is directly multiplied by volumetric price. It is not converted to hourly rates or derived from engine power.*

### 4.2 Baseline Operational CII
$$\text{baseline\_operational\_cii} = \frac{\text{predicted\_CO2\_kg} \times 1000}{\text{deadweight\_tonnes} \times \text{distance\_nm}}$$

* `predicted_CO2_kg`: kg $\text{CO}_2$ per voyage (Phase 2 prediction).
* Factor $1000$: Explicit conversion from kilograms to grams of $\text{CO}_2$.
* `deadweight_tonnes`: Metric deadweight tonnes (DWT) from voyage metadata / vessel profile.
* `distance_nm`: Voyage distance in nautical miles.
* **Output Unit:** $\text{gCO}_2 / (\text{DWT-tonne} \cdot \text{nm})$.
* **Governing Standard:** IMO Resolution MEPC.352(78).

---

## 5. Input Validation Rules

The calculation functions strictly validate all inputs before evaluation:

| Parameter | Validation Constraint | Rejection Behavior |
|---|---|---|
| `fuel_consumption_L` | Finite, $\ge 0.0$ | Raises `ValueError` if negative, NaN, or $\pm\infty$. Zero yields \$0.00 cost. |
| `fuel_price_usd_per_l` | Finite, $> 0.0$ | Raises `ValueError` if $\le 0.0$, NaN, or $\pm\infty$. |
| `co2_emissions_kg` | Finite, $\ge 0.0$ | Raises `ValueError` if negative, NaN, or $\pm\infty$. Zero yields $0.0\text{ gCO}_2/(\text{DWT}\cdot\text{nm})$. |
| `deadweight_tonnes` | Finite, $> 0.0$ | Raises `ValueError` if $\le 0.0$, NaN, or $\pm\infty$. |
| `distance_nm` | Finite, $> 0.0$ | Raises `ValueError` if $\le 0.0$, NaN, or $\pm\infty$. |
| `ship_type` | Non-empty string, known vessel | Raises `ValueError` if empty or unknown. |

---

## 6. Architectural Boundary Statements

1. **No IMO A–E Rating Assigned:** This module calculates only the raw operational Carbon Intensity Indicator metric in $\text{gCO}_2/(\text{DWT}\cdot\text{nm})$. It does not assign an A–E categorical rating, as vessel-specific CII reference-line parameters ($CII_{\text{ref}} = a \cdot \text{Capacity}^{-c}$) and reduction factors are not part of the dataset.
2. **Distinction Between Baseline and Assisted Metrics:**
   - Baseline metrics (Tier 2) quantify the unmodified, unassisted voyage.
   - Assisted metrics (Tier 4) estimate net fuel and $\text{CO}_2$ after clean-energy auxiliary displacement.
   - Tier 2 metrics are never modified by Tier 3 or Tier 4.
3. **Clean Energy and Scenarios are Out of Scope:** Battery energy budgeting, solar climatology estimation, auxiliary load coverage, generator SFOC displacement, and net assisted metrics belong exclusively to Phase 3C and Phase 3D.
