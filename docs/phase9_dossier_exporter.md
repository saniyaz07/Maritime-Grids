# Phase 9 Candidate 5: Integrated Multi-Phase Scenario Dossier & Cross-Phase Export Engine

## 1. Executive Purpose & Scope

Phase 9 Candidate 5 introduces the **Integrated Multi-Phase Scenario Dossier & Cross-Phase Export Engine** for the maritime clean-energy simulation framework.

Operating as a pure post-processing, validation, aggregation, formatting, and serialization layer, Candidate 5 synthesizes end-to-end simulation results across Phase 3 physical simulations, Phase 6 regulatory compliance, Phase 7 lifecycle techno-economics, Phase 8 system sizing optimization, and Phase 9 analytical modules (Candidates 1–4) into unified, schema-validated scenario dossiers and multi-format ledger exports.

### Key Architectural Characteristics:
- **Zero Simulation / Zero Math Recomputation:** Purely consumes already-computed Pydantic V2 result objects. Performs **zero** physical simulations, **zero** optimization searches (`optimize_system_sizing`), and **zero** machine learning inferences.
- **Referential Integrity Validation:** Automatically inspects cross-phase inputs for structural consistency, emitting structured diagnostics (`ERROR`, `WARNING`, `INFO`). Fatal mismatches cleanly prevent invalid reporting.
- **Cross-Phase KPI Summary:** Extracts and aligns key technical, economic, sizing, and regulatory indicators without altering or recalculating upstream numbers.
- **Multi-Format Serialization:**
  - Standard JSON: Hierarchical schema with stable `null` representations for omitted phases.
  - Tabular CSV Ledgers: Deterministic flat tables for 15-year cash flows, Pareto frontiers, and multi-year CII trajectories.
  - Neutral Engineering Markdown: Structured 11-section reporting with strict non-evaluative language (zero subjective recommendations).
- **In-Memory Core with Safe File Persistence:** Produces in-memory string payloads by default, with an optional persistence helper enforcing path-traversal prevention and source-file protection.

---

## 2. Architectural Boundaries & Pipeline Flow

```
+-----------------------------------------------------------------------------------+
|                        Phase 9 Candidate 5 Exporter Engine                        |
|   (Ingest → Validate Referential Integrity → Extract KPIs → Format & Serialize)    |
+----------------------------------------+------------------------------------------+
                                         |
         +-------------------------------+-------------------------------+
         | Ingested Result Payloads                                      | Output Serializers
         v                                                               v
+---------------------------------+                             +-----------------------------+
| - Phase 6: Phase6SimulationResult|                            | - JSON: application/json    |
| - Phase 7: InvestmentAppraisal   |                            | - Markdown: text/markdown   |
| - Phase 8: OptimizationResult   |                            | - CSV Cash Flows: text/csv  |
| - Candidate 1..4 Optional Outputs|                            | - CSV Pareto: text/csv      |
+---------------------------------+                             | - CSV CII Trajectory        |
                                                                +-----------------------------+
```

### Prohibited Behaviors:
1. **Zero Sizing Optimization:** Never invokes `optimize_system_sizing()` or generates physical sizing lattices.
2. **Zero ML Inference:** Never loads PyTorch, XGBoost, or Scikit-learn models.
3. **Zero Financial/Physical Duplication:** Never recalculates cash flows, NPV, IRR, LCOE, fuel displacement, or $\text{CO}_2$ displacement.
4. **Zero Recommendations:** Never emits evaluative labels (`"BEST"`, `"WORST"`, `"RECOMMENDED"`, `"IDEAL"`, `"SUPERIOR"`, `"VIABLE"`).

---

## 3. Operational Modes & Input Schema

### 3.1 Supported Operating Modes
- **Mode A (Minimal Dossier):** Requires scenario metadata and at least one valid phase or candidate result payload. Omitted phases serialize as `null` in JSON and render as `*Not supplied.*` in Markdown.
- **Mode B (Full Scenario Dossier):** Ingests Phase 6 + Phase 7 + Phase 8 (with optional Candidates 1–4) for a comprehensive end-to-end technical-economic-regulatory dossier.

### 3.2 Canonical Request Contract
```python
class DossierAssemblyRequest(BaseModel):
    scenario_name: str
    vessel_id: str
    ship_type: str  # Tanker Ship, Oil Service Boat, Fishing Trawler, Surfer Boat
    route_id: str   # Escravos-Lagos, Warri-Bonny, Lagos-Apapa, Port Harcourt-Lagos
    
    # Ingested Phase Results (At least one must be non-None)
    phase6_result: Optional[Phase6SimulationResult] = None
    phase7_result: Optional[InvestmentAppraisalResult] = None
    phase8_result: Optional[OptimizationResult] = None
    
    # Ingested Phase 9 Analytical Outputs
    candidate1_sensitivity: Optional[OATSensitivityResult] = None
    candidate2_cooptimization: Optional[SpeedCoOptimizationResult] = None
    candidate3_portfolio: Optional[PortfolioAllocationResult] = None
    candidate4_trajectory: Optional[TrajectorySimulationResult] = None
    
    export_formats: List[ExportFormatEnum] = [ExportFormatEnum.ALL]
```

---

## 4. Referential Integrity Diagnostics

Candidate 5 audits cross-phase referential integrity and classifies notices into three severity levels:

| Severity | Diagnostic Code | Trigger Condition | Engine Action |
| :--- | :--- | :--- | :--- |
| **`ERROR`** | `SHIP_TYPE_MISMATCH_*` | Supplied result ship_type diverges from request ship_type | **Fatal:** Raises `ValueError`, prevents export |
| **`WARNING`** | `ROUTE_ID_DIVERGENCE_*` | Evaluated route differs from scenario request route | **Non-Fatal:** Generates warning in audit log |
| **`WARNING`** | `SIZING_CONFIGURATION_DIVERGENCE` | Phase 7 evaluation sizing differs from Phase 8 optimal sizing | **Non-Fatal:** Generates warning in audit log |
| **`INFO`** | `OPTIONAL_MODULE_NOT_SUPPLIED` | An optional phase or candidate result was omitted | **Informational:** Notes module omission |

---

## 5. Serialized Export Formats

### 5.1 Hierarchical JSON (`application/json`)
Exports the complete scenario under deterministic top-level keys:
```json
{
  "metadata": { ... },
  "scenario": { ... },
  "phase6": { ... },
  "phase7": { ... },
  "phase8": { ... },
  "candidate1": null,
  "candidate2": null,
  "candidate3": null,
  "candidate4": { ... },
  "cross_phase_kpis": { ... },
  "diagnostics": [ ... ],
  "audit_metadata": { ... }
}
```

### 5.2 Neutral Engineering Markdown (`text/markdown`)
Renders an 11-section structured engineering document:
1. Scenario Metadata & System Provenance
2. Cross-Phase KPI Summary (Formatted comparison table)
3. Phase 6 — Voyage Physical Predictions & Air Pollutants
4. Phase 7 — Lifecycle Techno-Economics & Capital Budgeting
5. Phase 8 — Parametric Sizing Optimization & Trade-Offs
6. Candidate 1 — Parametric Sensitivity & Break-Even Analysis
7. Candidate 2 — Speed & Hybrid Sizing Co-Optimization
8. Candidate 3 — Fleet Portfolio Capital Allocation
9. Candidate 4 — Multi-Year Regulatory Compliance Trajectory
10. Referential Integrity & Diagnostic Audit Log
11. Audit Metadata

### 5.3 Tabular Flat CSV Ledgers (`text/csv`)
- **`CSV_CASH_FLOWS`:** 15-year accounting cash flow schedule from `InvestmentAppraisalResult.cash_flows`.
- **`CSV_PARETO_FRONTIER`:** Multi-objective sizing Pareto trade-off points from `OptimizationResult.pareto_frontier` or `SpeedCoOptimizationResult.pareto_frontier`.
- **`CSV_CII_TRAJECTORY`:** Multi-year regulatory compliance records from `TrajectorySimulationResult.trajectory`.

---

## 6. Security, Determinism & File Persistence

- **In-Memory Core:** All export methods return self-contained `ExportArtifactResult` objects holding raw text and MIME metadata.
- **Safe Disk Persistence (`save_dossier_to_disk`):**
  - Resolves destination paths against a caller-specified directory.
  - Enforces path-traversal prevention (`os.path.commonpath`).
  - Rejects attempts to overwrite Python source modules (`.py`).
- **Deterministic Output:** Zero timestamps injected into data content; stable alphabetical key ordering; bitwise identical output on repeated executions.
- **Computational Performance:** Measured execution time **$< 5\text{ ms}$** per complete scenario export.
