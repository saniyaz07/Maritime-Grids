# Phase 10A: Integration Facade Foundation
**Application-Layer Adapter & Orchestration Facade for Frozen Phase 0–9 Core**

---

## 1. Executive Purpose & Scope

Phase 10A establishes the **Integration Facade Foundation** (`MaritimeScenarioFacade`) for the maritime clean-energy simulation, sizing, techno-economic, regulatory, and export platform.

Operating strictly as an application-level adapter layer, Phase 10A provides clean, unified, strongly-typed entry points into the frozen Phase 6–9 core without altering or duplicating any underlying physical, machine learning, financial, regulatory, or optimization logic.

### Key Architectural Tenets:
1. **Zero Recomputation & Zero Formula Duplication:** The facade purely coordinates and adapts incoming application payloads to existing upstream contracts. It never reimplements fuel models, solar/battery balances, IMO CII equations, capital budgeting formulas, or optimization algorithms.
2. **Strict Provenance Tracking:** Every facade operation returns a standardized `FacadeResponse[T]` wrapper containing structured `FacadeProvenanceMetadata` (identifying operation name, underlying phase, underlying function, and core version).
3. **Pydantic V2 Type Safety:** All incoming requests are validated against strict schema bounds (rejecting non-positive speeds, negative distances, invalid vessel archetypes, or impossible physical bounds) before delegating to frozen logic.
4. **Controlled Error Propagation:** Controlled application exceptions (`FacadeError`, `FacadeValidationError`, `FacadeExecutionError`) provide clear diagnostic feedback while preserving upstream exception chains without swallowing errors.
5. **Zero Mutation of Frozen Core:** All Phase 0–8 modules, Phase 9 Candidates 1–5, models, reference datasets, and the 481 existing regression tests remain 100% frozen, untouched, and release-baselined.

---

## 2. System Architecture & Boundaries

```
+---------------------------------------------------------------------------------------+
|                             PHASE 10 APPLICATION LAYER                                |
|          (Future CLI / REST API / Web UI / Batch Orchestrator / Enterprise Sizing)     |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            | Ingests Application Request Contracts
                                            v
+---------------------------------------------------------------------------------------+
|                    app.facade.scenario_facade.MaritimeScenarioFacade                  |
|                                                                                       |
|   1. simulate_voyage()               ──► phase6_gateway.simulate_voyage               |
|   2. evaluate_sizing_candidate()     ──► phase8_optimizer.evaluate_single_sizing      |
|   3. optimize_system_sizing()        ──► phase8_optimizer.optimize_system_sizing      |
|   4. run_sensitivity_analysis()      ──► phase9_sensitivity.run_oat_sensitivity       |
|   5. run_break_even_analysis()       ──► phase9_sensitivity.solve_break_even          |
|   6. run_2d_grid_analysis()          ──► phase9_sensitivity.run_2d_parameter_grid     |
|   7. optimize_speed_and_sizing()     ──► phase9_speed_cooptimizer.optimize_speed      |
|   8. optimize_fleet_portfolio()      ──► phase9_portfolio_optimizer.optimize_portfolio|
|   9. simulate_cii_trajectory()       ──► phase9_cii_trajectory.simulate_compliance    |
|  10. export_scenario_dossier()       ──► phase9_dossier_exporter.export_dossier       |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            | Strict Read-Only Function Delegation
                                            v
+---------------------------------------------------------------------------------------+
|                              FROZEN RELEASE BASELINE                                  |
|                                                                                       |
|   - Phase 0-5 Physical Models & Clean Energy Dispatch                                 |
|   - Phase 6 Regulatory Gateway & IMO CII Engine                                       |
|   - Phase 7 Lifecycle Techno-Economics & Capital Budgeting                            |
|   - Phase 8 Parametric Sizing Optimization                                            |
|   - Phase 9 Candidates 1-5 Analytical Modules & Multi-Format Exporter                 |
|   - 13 Pre-Trained ML Models | ship_profiles.csv | 6,228 Raw Data Files               |
+---------------------------------------------------------------------------------------+
```

---

## 3. Operation-to-Frozen-Function Mapping

| Facade Method | Request Contract | Underlying Module | Underlying Function | Return Data Contract |
| :--- | :--- | :--- | :--- | :--- |
| `simulate_voyage` | `SimulateVoyageRequest` | `phase6_gateway` | `simulate_voyage` | `Phase6SimulationResult` |
| `evaluate_sizing_candidate` | `EvaluateSizingCandidateRequest` | `phase8_optimizer` | `evaluate_single_sizing_candidate` | `OptimizationCandidate` |
| `optimize_system_sizing` | `OptimizeSystemSizingRequest` | `phase8_optimizer` | `optimize_system_sizing` | `OptimizationResult` |
| `run_sensitivity_analysis` | `SensitivityAnalysisRequest` | `phase9_sensitivity` | `run_oat_sensitivity` | `OATSensitivityResult` |
| `run_break_even_analysis` | `BreakEvenAnalysisRequest` | `phase9_sensitivity` | `solve_break_even` | `BreakEvenResult` |
| `run_2d_grid_analysis` | `Grid2DAnalysisRequest` | `phase9_sensitivity` | `run_2d_parameter_grid` | `Grid2DResult` |
| `optimize_speed_and_sizing` | `SpeedCoOptimizationFacadeRequest` | `phase9_speed_cooptimizer` | `optimize_speed_and_sizing` | `SpeedCoOptimizationResult` |
| `optimize_fleet_portfolio` | `PortfolioOptimizationFacadeRequest` | `phase9_portfolio_optimizer` | `optimize_portfolio` | `PortfolioAllocationResult` |
| `simulate_cii_trajectory` | `CIIComplianceTrajectoryRequest` | `phase9_cii_trajectory` | `simulate_compliance_trajectory` | `TrajectorySimulationResult` |
| `export_scenario_dossier` | `DossierExportFacadeRequest` | `phase9_dossier_exporter` | `export_dossier` / `save_dossier_to_disk` | `Dict[str, Any]` (Dossier + Artifacts) |

---

## 4. Contract Hierarchy & Provenance Model

All facade operations wrap output data in a generic `FacadeResponse[T]`:

```python
class FacadeProvenanceMetadata(BaseModel):
    operation: FacadeOperationEnum
    underlying_phase: str
    underlying_function: str
    frozen_core_version: str = "1.0.0"
    status: str = "SUCCESS"
    scenario_name: Optional[str] = None
    vessel_id: Optional[str] = None

class FacadeResponse(BaseModel, Generic[T]):
    provenance: FacadeProvenanceMetadata
    data: T
    diagnostics: List[str] = Field(default_factory=list)
```

---

## 5. Security & Persistence Guard Rails

1. **Path-Traversal Protection:** When persisting export artifacts via `export_scenario_dossier()`, the facade enforces Candidate 5's path validation (`os.path.commonpath`), rejecting attempts to write outside the caller's target directory.
2. **Source-Code Protection:** Rejects attempts to overwrite Python files (`.py`) with `ValueError: Overwrite of Python source files is strictly prohibited`.
3. **Execution Ceilings:** Automatically enforces upstream computational budget caps (e.g., max 1,000 evaluations for sensitivity sweeps, max 2,500 evaluations for speed co-optimization).
4. **Input Sanitization:** Rejects NaN, infinite values, or out-of-bounds parameters at the Pydantic boundary before upstream functions are reached.

---

## 6. Python Usage Examples

### Example 1: Single-Voyage Simulation
```python
from app.facade import MaritimeScenarioFacade, SimulateVoyageRequest

facade = MaritimeScenarioFacade()
request = SimulateVoyageRequest(
    ship_type="Tanker Ship",
    route_id="Escravos-Lagos",
    month=7,
    speed_knots=12.0,
    solar_area_m2=100.0,
    battery_capacity_kwh=200.0,
)
response = facade.simulate_voyage(request)

print(f"Operation: {response.provenance.operation}")
print(f"Baseline CII Rating: {response.data.regulatory_assessment.baseline_cii_rating}")
print(f"Assisted CII Rating: {response.data.regulatory_assessment.assisted_cii_rating}")
```

### Example 2: Canonical Phase 8 Benchmark Evaluation
```python
from app.facade import MaritimeScenarioFacade, EvaluateSizingCandidateRequest

facade = MaritimeScenarioFacade()
bench_req = EvaluateSizingCandidateRequest(
    ship_type="Tanker Ship",
    solar_area_m2=100.0,
    battery_capacity_kwh=200.0,
    deck_area_limit_m2=833.0,
    battery_weight_limit_tonnes=700.0,
    predicted_soh=0.7387438,
    auxiliary_energy_demand_kwh=400.0,
    voyage_duration_hours=40.5,
    predicted_fuel_consumption_L=20124.3,
    predicted_CO2_kg=53268.0,
    daily_ghi_kwh_per_m2=4.500000,
    annual_voyages=52,
    discount_rate=0.08,
    fuel_price_usd_per_l=1.0,
    carbon_price_usd_per_tonne=0.0,
    analysis_horizon_years=15,
)
response = facade.evaluate_sizing_candidate(bench_req)
candidate = response.data

print(f"NPV: ${candidate.net_present_value_usd:,.2f}")  # -$169,596.08
print(f"LCOE: ${candidate.lcoe_usd_per_kwh:.6f}/kWh")   # $1.848868/kWh
```

---

## 7. Verification & Canonical Benchmark Reconciliation

The Phase 10A test suite (`tests/test_facade.py`) independently confirms that executing the canonical Phase 8 Tanker Ship benchmark through `MaritimeScenarioFacade` yields identical numerical results to the frozen baseline:
- **Net Present Value (NPV):** `-$169,596.08 USD`
- **Levelized Cost of Clean Energy (LCOE):** `$1.848868 USD/kWh`
- **Internal Rate of Return (IRR):** `-21.7015%`
- **Annual Fuel Displaced:** `3,259.7260 L`
- **Annual $\text{CO}_2$ Displaced:** `8,628.1687 kg`
- **Simple & Discounted Paybacks:** `None / None`
- **Auxiliary Feasibility Status:** `PARTIAL`

All 481 existing regression tests pass with zero modifications to frozen code.
