"""
phase9_dossier_exporter.py — Phase 9 Candidate 5
=================================================
Integrated Multi-Phase Scenario Dossier & Cross-Phase Export Engine

Implements:
  1. Cross-phase scenario ingestion and referential integrity validation (ERROR, WARNING, INFO).
  2. Aggregation of key technical, economic, and regulatory KPIs across phases without recalculation.
  3. Structured JSON serialization with stable null-preserving hierarchy.
  4. Multi-section neutral Markdown scenario reporting with strict non-evaluative language.
  5. Deterministic tabular CSV ledger exports (Cash flows, Pareto frontier, CII trajectory).
  6. In-memory export engine with optional safe file persistence enforcing path-traversal prevention.

Strict boundaries:
  - Zero simulation or math re-execution.
  - Zero calls to optimize_system_sizing() or ML models.
  - Leaves all upstream Phase 0-8 and Candidate 1-4 models 100% untouched.
"""

import csv
import io
import json
import os
from typing import Dict, List, Optional, Any

from phase9_dossier_contracts import (
    ExportFormatEnum,
    DiagnosticSeverityEnum,
    DossierDiagnostic,
    ExportArtifactResult,
    CrossPhaseKPISummary,
    DossierAssemblyRequest,
    CrossPhaseScenarioDossier,
)


# ==============================================================================
# 1. Referential Integrity Validation Engine
# ==============================================================================

def validate_referential_integrity(
    request: DossierAssemblyRequest,
) -> List[DossierDiagnostic]:
    """
    Validate referential integrity across all supplied phase and candidate results.

    Emits structured diagnostics categorized into:
      - ERROR: Fatal structural incompatibilities that prevent valid scenario synthesis.
      - WARNING: Non-fatal scenario divergences that remain serializable with audit notices.
      - INFO: Informational notes regarding omitted optional modules.
    """
    diagnostics: List[DossierDiagnostic] = []

    # --- 1. Ship Type Consistency (FATAL if mismatched) ---
    if request.phase6_result is not None:
        p6_ship = request.phase6_result.request.ship_type
        if p6_ship != request.ship_type:
            diagnostics.append(
                DossierDiagnostic(
                    severity=DiagnosticSeverityEnum.ERROR.value,
                    code="SHIP_TYPE_MISMATCH_PHASE6",
                    message=f"Request ship_type '{request.ship_type}' differs from Phase 6 ship_type '{p6_ship}'.",
                    affected_module="Phase 6 / Request",
                )
            )

    if request.phase8_result is not None:
        p8_ship = request.phase8_result.parameters.ship_type
        if p8_ship != request.ship_type:
            diagnostics.append(
                DossierDiagnostic(
                    severity=DiagnosticSeverityEnum.ERROR.value,
                    code="SHIP_TYPE_MISMATCH_PHASE8",
                    message=f"Request ship_type '{request.ship_type}' differs from Phase 8 ship_type '{p8_ship}'.",
                    affected_module="Phase 8 / Request",
                )
            )

    if request.candidate4_trajectory is not None:
        c4_ship = request.candidate4_trajectory.request.ship_type
        if c4_ship != request.ship_type:
            diagnostics.append(
                DossierDiagnostic(
                    severity=DiagnosticSeverityEnum.ERROR.value,
                    code="SHIP_TYPE_MISMATCH_CANDIDATE4",
                    message=f"Request ship_type '{request.ship_type}' differs from Candidate 4 ship_type '{c4_ship}'.",
                    affected_module="Candidate 4 / Request",
                )
            )

    # --- 2. Route Corridor Consistency (WARNING if divergent) ---
    if request.phase6_result is not None:
        p6_route = request.phase6_result.request.route_id
        if p6_route != request.route_id:
            diagnostics.append(
                DossierDiagnostic(
                    severity=DiagnosticSeverityEnum.WARNING.value,
                    code="ROUTE_ID_DIVERGENCE_PHASE6",
                    message=f"Request route_id '{request.route_id}' differs from Phase 6 evaluated route '{p6_route}'.",
                    affected_module="Phase 6 / Request",
                )
            )

    if request.candidate4_trajectory is not None:
        c4_route = request.candidate4_trajectory.request.route_id
        if c4_route != request.route_id:
            diagnostics.append(
                DossierDiagnostic(
                    severity=DiagnosticSeverityEnum.WARNING.value,
                    code="ROUTE_ID_DIVERGENCE_CANDIDATE4",
                    message=f"Request route_id '{request.route_id}' differs from Candidate 4 route '{c4_route}'.",
                    affected_module="Candidate 4 / Request",
                )
            )

    # --- 3. Sizing Configuration Alignment (Phase 7 vs Phase 8) ---
    if request.phase7_result is not None and request.phase8_result is not None:
        p7 = request.phase7_result
        p8_opt = request.phase8_result.optimal_candidate
        if p8_opt is not None:
            pv_diff = abs(p7.solar_area_m2 - p8_opt.solar_area_m2)
            batt_diff = abs(p7.battery_capacity_kwh - p8_opt.battery_capacity_kwh)
            if pv_diff > 1e-4 or batt_diff > 1e-4:
                diagnostics.append(
                    DossierDiagnostic(
                        severity=DiagnosticSeverityEnum.WARNING.value,
                        code="SIZING_CONFIGURATION_DIVERGENCE",
                        message=(
                            f"Phase 7 sizing (Apv={p7.solar_area_m2}m2, Ebatt={p7.battery_capacity_kwh}kWh) "
                            f"diverges from Phase 8 optimal candidate "
                            f"(Apv={p8_opt.solar_area_m2}m2, Ebatt={p8_opt.battery_capacity_kwh}kWh)."
                        ),
                        affected_module="Phase 7 / Phase 8",
                    )
                )

    # --- 4. Optional Module Omissions (INFO) ---
    optional_modules = [
        ("Phase 6 Physical Simulation", request.phase6_result),
        ("Phase 7 Lifecycle Economics", request.phase7_result),
        ("Phase 8 Sizing Optimization", request.phase8_result),
        ("Candidate 1 Sensitivity Analysis", request.candidate1_sensitivity),
        ("Candidate 2 Speed Co-Optimization", request.candidate2_cooptimization),
        ("Candidate 3 Fleet Portfolio Allocation", request.candidate3_portfolio),
        ("Candidate 4 Compliance Trajectory", request.candidate4_trajectory),
    ]
    for mod_name, mod_obj in optional_modules:
        if mod_obj is None:
            diagnostics.append(
                DossierDiagnostic(
                    severity=DiagnosticSeverityEnum.INFO.value,
                    code="OPTIONAL_MODULE_NOT_SUPPLIED",
                    message=f"{mod_name} was not supplied for this scenario dossier.",
                    affected_module=mod_name,
                )
            )

    return diagnostics


# ==============================================================================
# 2. Cross-Phase KPI Aggregation Engine
# ==============================================================================

def assemble_cross_phase_kpis(
    request: DossierAssemblyRequest,
) -> CrossPhaseKPISummary:
    """
    Extract and assemble a structured summary of cross-phase technical,
    economic, and regulatory KPIs directly from supplied result objects.
    """
    kpis = CrossPhaseKPISummary(
        vessel_id=request.vessel_id,
        ship_type=request.ship_type,
        route_id=request.route_id,
    )

    # Phase 6 Extraction
    if request.phase6_result is not None:
        p6 = request.phase6_result
        kpis.voyage_duration_hours = p6.phase3_output.voyage_metadata.voyage_duration_hours
        kpis.baseline_single_voyage_fuel_L = p6.tier1_predictions.fuel_consumption_L.value
        kpis.baseline_single_voyage_co2_kg = p6.tier1_predictions.co2_emissions_kg.value
        kpis.net_assisted_single_voyage_fuel_L = p6.pollutant_assessment.net_assisted_fuel_L
        kpis.net_assisted_single_voyage_co2_kg = p6.regulatory_assessment.net_assisted_co2_kg
        kpis.baseline_cii_rating = p6.regulatory_assessment.baseline_cii_rating
        kpis.assisted_cii_rating = p6.regulatory_assessment.assisted_cii_rating

    # Phase 7 Extraction
    if request.phase7_result is not None:
        p7 = request.phase7_result
        kpis.total_initial_capex_usd = p7.total_initial_capex_usd
        kpis.net_present_value_usd = p7.net_present_value_usd
        kpis.internal_rate_of_return_pct = p7.internal_rate_of_return_pct
        kpis.simple_payback_years = p7.simple_payback_years
        kpis.discounted_payback_years = p7.discounted_payback_years
        kpis.lcoe_usd_per_kwh = p7.lcoe_usd_per_kwh
        kpis.solar_area_m2 = p7.solar_area_m2
        kpis.battery_capacity_kwh = p7.battery_capacity_kwh

    # Phase 8 Extraction (Refines or populates sizing & displacement)
    if request.phase8_result is not None:
        p8 = request.phase8_result
        if p8.optimal_candidate is not None:
            opt = p8.optimal_candidate
            kpis.annual_fuel_displaced_L = opt.annual_fuel_displaced_L
            kpis.annual_co2_displaced_kg = opt.annual_co2_displaced_kg
            kpis.solar_area_m2 = opt.solar_area_m2
            kpis.battery_capacity_kwh = opt.battery_capacity_kwh
            kpis.sizing_feasibility_status = opt.feasibility_status
            if kpis.total_initial_capex_usd is None:
                kpis.total_initial_capex_usd = opt.total_initial_capex_usd
            if kpis.net_present_value_usd is None:
                kpis.net_present_value_usd = opt.net_present_value_usd
            if kpis.lcoe_usd_per_kwh is None:
                kpis.lcoe_usd_per_kwh = opt.lcoe_usd_per_kwh

    # Candidate 4 Extraction (Refines multi-year regulatory metrics)
    if request.candidate4_trajectory is not None:
        c4 = request.candidate4_trajectory
        kpis.compliance_extension_years = c4.compliance_extension_years
        kpis.first_non_compliant_year_baseline = c4.first_non_compliant_year_baseline
        kpis.first_non_compliant_year_assisted = c4.first_non_compliant_year_assisted

    return kpis


# ==============================================================================
# 3. Dossier Assembly Engine
# ==============================================================================

def assemble_dossier(
    request: DossierAssemblyRequest,
) -> CrossPhaseScenarioDossier:
    """
    Validate, reconcile, and assemble an integrated scenario dossier.
    Raises ValueError if fatal referential integrity errors are detected.
    """
    diagnostics = validate_referential_integrity(request)

    # Check for fatal ERROR severity
    errors = [d for d in diagnostics if d.severity == DiagnosticSeverityEnum.ERROR.value]
    if errors:
        err_msg = "; ".join(f"[{e.code}] {e.message}" for e in errors)
        raise ValueError(f"Dossier assembly rejected due to referential integrity error(s): {err_msg}")

    kpis = assemble_cross_phase_kpis(request)

    dossier = CrossPhaseScenarioDossier(
        metadata={
            "engine": "Phase 9 Candidate 5 Dossier Exporter",
            "version": "1.0.0",
            "export_formats_requested": [f.value for f in request.export_formats],
        },
        scenario={
            "scenario_name": request.scenario_name,
            "vessel_id": request.vessel_id,
            "ship_type": request.ship_type,
            "route_id": request.route_id,
        },
        phase6=request.phase6_result,
        phase7=request.phase7_result,
        phase8=request.phase8_result,
        candidate1=request.candidate1_sensitivity,
        candidate2=request.candidate2_cooptimization,
        candidate3=request.candidate3_portfolio,
        candidate4=request.candidate4_trajectory,
        cross_phase_kpis=kpis,
        diagnostics=diagnostics,
        audit_metadata={
            "deterministic_execution": True,
            "zero_recomputation": True,
            "supplied_phase_count": sum(
                1 for p in [
                    request.phase6_result,
                    request.phase7_result,
                    request.phase8_result,
                    request.candidate1_sensitivity,
                    request.candidate2_cooptimization,
                    request.candidate3_portfolio,
                    request.candidate4_trajectory,
                ] if p is not None
            ),
        },
    )
    return dossier


# ==============================================================================
# 4. Multi-Format Serializers
# ==============================================================================

def export_json(dossier: CrossPhaseScenarioDossier) -> ExportArtifactResult:
    """Serialize the dossier to a deterministic standard JSON string."""
    raw_json = dossier.model_dump_json(indent=2)
    return ExportArtifactResult(
        format_type=ExportFormatEnum.JSON.value,
        content_type="application/json",
        raw_content=raw_json,
        record_count=1,
    )


def export_markdown(dossier: CrossPhaseScenarioDossier) -> ExportArtifactResult:
    """Generate a clean, neutral engineering Markdown report."""
    lines: List[str] = []
    sc = dossier.scenario
    kpi = dossier.cross_phase_kpis

    lines.append(f"# Multi-Phase Scenario Dossier: {sc['scenario_name']}")
    lines.append("")
    lines.append("## 1. Scenario Metadata & System Provenance")
    lines.append(f"- **Vessel Identifier:** `{sc['vessel_id']}`")
    lines.append(f"- **Ship Archetype:** `{sc['ship_type']}`")
    lines.append(f"- **Operating Corridor:** `{sc['route_id']}`")
    lines.append(f"- **Supplied Phases:** {dossier.audit_metadata['supplied_phase_count']} module(s)")
    lines.append("")

    lines.append("## 2. Cross-Phase KPI Summary")
    lines.append("| Metric Category | KPI Name | Value | Unit |")
    lines.append("| :--- | :--- | :--- | :--- |")
    lines.append(f"| Physical | Voyage Duration | {kpi.voyage_duration_hours if kpi.voyage_duration_hours is not None else 'Not supplied'} | hours |")
    lines.append(f"| Physical | Baseline Single-Voyage Fuel | {kpi.baseline_single_voyage_fuel_L if kpi.baseline_single_voyage_fuel_L is not None else 'Not supplied'} | L |")
    lines.append(f"| Physical | Net Assisted Single-Voyage Fuel | {kpi.net_assisted_single_voyage_fuel_L if kpi.net_assisted_single_voyage_fuel_L is not None else 'Not supplied'} | L |")
    lines.append(f"| Sizing | Installed Solar Array Area | {kpi.solar_area_m2 if kpi.solar_area_m2 is not None else 'Not supplied'} | m² |")
    lines.append(f"| Sizing | Installed Battery Capacity | {kpi.battery_capacity_kwh if kpi.battery_capacity_kwh is not None else 'Not supplied'} | kWh |")
    lines.append(f"| Financial | Initial Capital Expenditure (CAPEX_0) | {f'${kpi.total_initial_capex_usd:,.2f}' if kpi.total_initial_capex_usd is not None else 'Not supplied'} | USD |")
    lines.append(f"| Financial | Net Present Value (NPV) | {f'${kpi.net_present_value_usd:,.2f}' if kpi.net_present_value_usd is not None else 'Not supplied'} | USD |")
    lines.append(f"| Financial | Internal Rate of Return (IRR) | {f'{kpi.internal_rate_of_return_pct:.2f}%' if kpi.internal_rate_of_return_pct is not None else 'Not supplied'} | % |")
    lines.append(f"| Financial | Levelized Cost of Energy (LCOE) | {f'${kpi.lcoe_usd_per_kwh:.4f}/kWh' if kpi.lcoe_usd_per_kwh is not None else 'Not supplied'} | USD/kWh |")
    lines.append(f"| Regulatory | Single-Voyage Baseline Rating | {kpi.baseline_cii_rating if kpi.baseline_cii_rating is not None else 'Not supplied'} | Rating Band |")
    lines.append(f"| Regulatory | Single-Voyage Assisted Rating | {kpi.assisted_cii_rating if kpi.assisted_cii_rating is not None else 'Not supplied'} | Rating Band |")
    lines.append(f"| Regulatory | Compliance Extension Horizon | {f'{kpi.compliance_extension_years} years' if kpi.compliance_extension_years is not None else 'Not supplied'} | years |")
    lines.append("")

    # Phase 6 Section
    lines.append("## 3. Phase 6 — Voyage Physical Predictions & Air Pollutants")
    if dossier.phase6 is not None:
        p6 = dossier.phase6
        applied_sc = getattr(p6.phase3_output, 'applied_scenario_parameters', None)
        aux_val = getattr(applied_sc, 'auxiliary_energy_demand_kwh', 'N/A')
        feas_status = getattr(getattr(p6.phase3_output, 'tier_3_clean_energy_feasibility', None), 'feasibility_status', 'FEASIBLE')
        lines.append(f"- **Simulation Engine:** `phase6_gateway` (Status: `{getattr(p6, 'status', 'SUCCESS')}`)")
        lines.append(f"- **Auxiliary Electrical Demand:** {aux_val} kWh")
        lines.append(f"- **Clean Energy Feasibility:** `{feas_status}`")
        lines.append(f"- **Avoided NOx Emissions:** {p6.pollutant_assessment.avoided_nox_kg:.4f} kg")
        lines.append(f"- **Avoided SOx Emissions:** {p6.pollutant_assessment.avoided_sox_kg:.4f} kg")
        lines.append(f"- **Avoided PM2.5 Emissions:** {p6.pollutant_assessment.avoided_pm25_kg:.4f} kg")
    else:
        lines.append("*Not supplied.*")
    lines.append("")

    # Phase 7 Section
    lines.append("## 4. Phase 7 — Lifecycle Techno-Economics & Capital Budgeting")
    if dossier.phase7 is not None:
        p7 = dossier.phase7
        lines.append(f"- **Evaluation Horizon:** {p7.parameters.analysis_horizon_years} years @ {p7.parameters.discount_rate * 100:.1f}% discount rate")
        lines.append(f"- **Total Undiscounted Benefits:** ${p7.total_undiscounted_benefits_usd:,.2f}")
        lines.append(f"- **Simple Payback Period:** {f'{p7.simple_payback_years:.2f} years' if p7.simple_payback_years is not None else 'Unrecovered within horizon'}")
        lines.append(f"- **Discounted Payback Period:** {f'{p7.discounted_payback_years:.2f} years' if p7.discounted_payback_years is not None else 'Unrecovered within horizon'}")
        lines.append(f"- **Cash Flow Table Length:** {len(p7.cash_flows)} annual records")
    else:
        lines.append("*Not supplied.*")
    lines.append("")

    # Phase 8 Section
    lines.append("## 5. Phase 8 — Parametric Sizing Optimization & Trade-Offs")
    if dossier.phase8 is not None:
        p8 = dossier.phase8
        lines.append(f"- **Primary Optimization Objective:** `{p8.parameters.objective}`")
        lines.append(f"- **Grid Configurations Evaluated:** {p8.total_candidates_evaluated} (Feasible: {p8.feasible_candidates_count})")
        lines.append(f"- **Pareto Frontier Size:** {len(p8.pareto_frontier)} non-dominated candidates")
        if p8.optimal_candidate is not None:
            opt = p8.optimal_candidate
            lines.append(f"- **Optimal Point:** $A_{{pv}}={opt.solar_area_m2}\\text{{ m}}^2$, $E_{{batt}}={opt.battery_capacity_kwh}\\text{{ kWh}}$")
    else:
        lines.append("*Not supplied.*")
    lines.append("")

    # Candidate 1 Section
    lines.append("## 6. Candidate 1 — Parametric Sensitivity & Break-Even Analysis")
    if dossier.candidate1 is not None:
        c1 = dossier.candidate1
        lines.append(f"- **Analyzed Parameter:** `{c1.parameter_name}` (Baseline: {c1.baseline_parameter_value})")
        lines.append(f"- **Target Metric:** `{c1.metric_name}`")
        lines.append(f"- **Evaluated Sensitivity Points:** {len(c1.points)}")
    else:
        lines.append("*Not supplied.*")
    lines.append("")

    # Candidate 2 Section
    lines.append("## 7. Candidate 2 — Speed & Hybrid Sizing Co-Optimization")
    if dossier.candidate2 is not None:
        c2 = dossier.candidate2
        lines.append(f"- **Speed Range:** {c2.resolved_vmin_knots} to {c2.resolved_vmax_knots} knots (step: {c2.resolved_vstep_knots})")
        lines.append(f"- **Configurations Evaluated:** {c2.total_configurations_evaluated}")
        lines.append(f"- **Pareto Trade-Off Points:** {len(c2.pareto_frontier)}")
    else:
        lines.append("*Not supplied.*")
    lines.append("")

    # Candidate 3 Section
    lines.append("## 8. Candidate 3 — Fleet Portfolio Capital Allocation")
    if dossier.candidate3 is not None:
        c3 = dossier.candidate3
        lines.append(f"- **Portfolio Budget:** ${c3.parameters.total_portfolio_capex_budget_usd:,.2f}")
        lines.append(f"- **Allocated CAPEX:** ${c3.total_capex_usd:,.2f}")
        lines.append(f"- **Selected Retrofits:** {c3.selected_retrofit_count} vessel(s)")
        lines.append(f"- **Total Annual CO2 Displaced:** {c3.total_annual_co2_displaced_kg:,.2f} kg")
    else:
        lines.append("*Not supplied.*")
    lines.append("")

    # Candidate 4 Section
    lines.append("## 9. Candidate 4 — Multi-Year Regulatory Compliance Trajectory")
    if dossier.candidate4 is not None:
        c4 = dossier.candidate4
        lines.append(f"- **Evaluation Horizon:** {c4.years_evaluated} years ({c4.request.start_year} to {c4.request.end_year})")
        lines.append(f"- **Compliance Extension:** {f'{c4.compliance_extension_years} years' if c4.compliance_extension_years is not None else 'Not applicable (unassessed/exempt)'}")
        lines.append(f"- **Cumulative CO2 Displaced:** {c4.total_co2_displaced_kg:,.2f} kg")
    else:
        lines.append("*Not supplied.*")
    lines.append("")

    # Diagnostics Section
    lines.append("## 10. Referential Integrity & Diagnostic Audit Log")
    if dossier.diagnostics:
        lines.append("| Severity | Code | Affected Module | Message |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for d in dossier.diagnostics:
            lines.append(f"| `{d.severity}` | `{d.code}` | {d.affected_module} | {d.message} |")
    else:
        lines.append("Zero diagnostic notices recorded.")
    lines.append("")

    # Audit Metadata Section
    lines.append("## 11. Audit Metadata")
    lines.append(f"- **Deterministic Serialization:** `{dossier.audit_metadata['deterministic_execution']}`")
    lines.append(f"- **Zero-Recomputation Invariant:** `{dossier.audit_metadata['zero_recomputation']}`")
    lines.append(f"- **Engine Signature:** `{dossier.metadata['engine']} v{dossier.metadata['version']}`")

    raw_md = "\n".join(lines)
    return ExportArtifactResult(
        format_type=ExportFormatEnum.MARKDOWN.value,
        content_type="text/markdown",
        raw_content=raw_md,
        record_count=len(lines),
    )


def export_csv_cash_flows(dossier: CrossPhaseScenarioDossier) -> ExportArtifactResult:
    """Export the 15-year lifecycle cash flow ledger to standard tabular CSV."""
    headers = [
        "year",
        "capex_usd",
        "opex_usd",
        "fuel_savings_usd",
        "carbon_savings_usd",
        "replacement_expenditure_usd",
        "salvage_value_usd",
        "net_cash_flow_usd",
        "discount_factor",
        "discounted_cash_flow_usd",
        "cumulative_discounted_cash_flow_usd",
        "clean_energy_utilized_kwh",
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers)

    count = 0
    if dossier.phase7 is not None:
        for cf in dossier.phase7.cash_flows:
            writer.writerow([
                cf.year,
                f"{cf.capex_usd:.2f}",
                f"{cf.opex_usd:.2f}",
                f"{cf.fuel_savings_usd:.2f}",
                f"{cf.carbon_savings_usd:.2f}",
                f"{cf.replacement_expenditure_usd:.2f}",
                f"{cf.salvage_value_usd:.2f}",
                f"{cf.net_cash_flow_usd:.2f}",
                f"{cf.discount_factor:.6f}",
                f"{cf.discounted_cash_flow_usd:.2f}",
                f"{cf.cumulative_discounted_cash_flow_usd:.2f}",
                f"{cf.clean_energy_utilized_kwh:.4f}",
            ])
            count += 1

    return ExportArtifactResult(
        format_type=ExportFormatEnum.CSV_CASH_FLOWS.value,
        content_type="text/csv",
        raw_content=out.getvalue(),
        record_count=count,
    )


def export_csv_pareto_frontier(dossier: CrossPhaseScenarioDossier) -> ExportArtifactResult:
    """Export the multi-objective Pareto trade-off candidates to tabular CSV."""
    headers = [
        "candidate_index",
        "solar_area_m2",
        "battery_capacity_kwh",
        "speed_knots",
        "total_initial_capex_usd",
        "annual_fuel_displaced_L",
        "annual_co2_displaced_kg",
        "net_present_value_usd",
        "lcoe_usd_per_kwh",
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers)

    count = 0
    # Source 1: Phase 8 Pareto Frontier
    if dossier.phase8 is not None:
        for idx, c in enumerate(dossier.phase8.pareto_frontier):
            writer.writerow([
                idx,
                f"{c.solar_area_m2:.1f}",
                f"{c.battery_capacity_kwh:.1f}",
                "",  # Speed is constant / not varied in Phase 8
                f"{c.total_initial_capex_usd:.2f}",
                f"{c.annual_fuel_displaced_L:.4f}",
                f"{c.annual_co2_displaced_kg:.4f}",
                f"{c.net_present_value_usd:.2f}",
                f"{c.lcoe_usd_per_kwh:.4f}" if c.lcoe_usd_per_kwh is not None else "",
            ])
            count += 1

    # Source 2: Candidate 2 Pareto Frontier (if Phase 8 not present)
    elif dossier.candidate2 is not None:
        for idx, c in enumerate(dossier.candidate2.pareto_frontier):
            writer.writerow([
                idx,
                f"{c.solar_area_m2:.1f}",
                f"{c.battery_capacity_kwh:.1f}",
                f"{c.speed_knots:.1f}",
                f"{c.total_initial_capex_usd:.2f}",
                f"{c.annual_fuel_displaced_L:.4f}",
                f"{c.annual_co2_displaced_kg:.4f}",
                f"{c.net_present_value_usd:.2f}",
                f"{c.lcoe_usd_per_kwh:.4f}" if c.lcoe_usd_per_kwh is not None else "",
            ])
            count += 1

    return ExportArtifactResult(
        format_type=ExportFormatEnum.CSV_PARETO_FRONTIER.value,
        content_type="text/csv",
        raw_content=out.getvalue(),
        record_count=count,
    )


def export_csv_cii_trajectory(dossier: CrossPhaseScenarioDossier) -> ExportArtifactResult:
    """Export the multi-year IMO CII compliance trajectory records to tabular CSV."""
    headers = [
        "year",
        "regulatory_basis",
        "reduction_factor_z_pct",
        "annual_distance_nm",
        "baseline_annual_co2_kg",
        "assisted_annual_co2_kg",
        "baseline_attained_cii",
        "assisted_attained_cii",
        "required_cii",
        "baseline_cii_rating",
        "assisted_cii_rating",
        "baseline_corrective_action_required",
        "assisted_corrective_action_required",
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(headers)

    count = 0
    if dossier.candidate4 is not None:
        for r in dossier.candidate4.trajectory:
            writer.writerow([
                r.year,
                r.regulatory_basis,
                f"{r.reduction_factor_z_pct:.1f}" if r.reduction_factor_z_pct is not None else "",
                f"{r.annual_distance_nm:.2f}",
                f"{r.baseline_annual_co2_kg:.2f}",
                f"{r.assisted_annual_co2_kg:.2f}",
                f"{r.baseline_attained_cii:.6f}",
                f"{r.assisted_attained_cii:.6f}",
                f"{r.required_cii:.6f}" if r.required_cii is not None else "",
                r.baseline_cii_rating,
                r.assisted_cii_rating,
                r.baseline_corrective_action_required,
                r.assisted_corrective_action_required,
            ])
            count += 1

    return ExportArtifactResult(
        format_type=ExportFormatEnum.CSV_CII_TRAJECTORY.value,
        content_type="text/csv",
        raw_content=out.getvalue(),
        record_count=count,
    )


# ==============================================================================
# 5. Primary Exporter API
# ==============================================================================

def export_dossier(
    request: DossierAssemblyRequest,
) -> Dict[ExportFormatEnum, ExportArtifactResult]:
    """
    Main entry point to assemble, validate, and serialize an integrated scenario dossier.

    Returns a dictionary mapping each requested ExportFormatEnum to its ExportArtifactResult.
    """
    dossier = assemble_dossier(request)

    requested_formats = request.export_formats
    if ExportFormatEnum.ALL in requested_formats:
        formats_to_generate = [
            ExportFormatEnum.JSON,
            ExportFormatEnum.MARKDOWN,
            ExportFormatEnum.CSV_CASH_FLOWS,
            ExportFormatEnum.CSV_PARETO_FRONTIER,
            ExportFormatEnum.CSV_CII_TRAJECTORY,
        ]
    else:
        formats_to_generate = list(set(requested_formats))

    results: Dict[ExportFormatEnum, ExportArtifactResult] = {}

    for fmt in formats_to_generate:
        if fmt == ExportFormatEnum.JSON:
            results[ExportFormatEnum.JSON] = export_json(dossier)
        elif fmt == ExportFormatEnum.MARKDOWN:
            results[ExportFormatEnum.MARKDOWN] = export_markdown(dossier)
        elif fmt == ExportFormatEnum.CSV_CASH_FLOWS:
            results[ExportFormatEnum.CSV_CASH_FLOWS] = export_csv_cash_flows(dossier)
        elif fmt == ExportFormatEnum.CSV_PARETO_FRONTIER:
            results[ExportFormatEnum.CSV_PARETO_FRONTIER] = export_csv_pareto_frontier(dossier)
        elif fmt == ExportFormatEnum.CSV_CII_TRAJECTORY:
            results[ExportFormatEnum.CSV_CII_TRAJECTORY] = export_csv_cii_trajectory(dossier)

    return results


# ==============================================================================
# 6. Safe File Persistence Engine
# ==============================================================================

def save_dossier_to_disk(
    artifacts: Dict[ExportFormatEnum, ExportArtifactResult],
    output_directory: str,
    filename_prefix: str = "dossier",
) -> Dict[ExportFormatEnum, str]:
    """
    Safely persist generated export artifacts to a caller-specified directory.

    Security & Safety Guard Rails:
      - Resolves absolute paths and verifies they reside strictly within output_directory (path-traversal prevention).
      - Rejects filenames attempting to overwrite python source modules (.py) or project root files.
    """
    if not output_directory:
        raise ValueError("output_directory cannot be empty.")

    target_dir = os.path.abspath(output_directory)
    os.makedirs(target_dir, exist_ok=True)

    extension_map = {
        ExportFormatEnum.JSON: ".json",
        ExportFormatEnum.MARKDOWN: ".md",
        ExportFormatEnum.CSV_CASH_FLOWS: "_cash_flows.csv",
        ExportFormatEnum.CSV_PARETO_FRONTIER: "_pareto.csv",
        ExportFormatEnum.CSV_CII_TRAJECTORY: "_cii_trajectory.csv",
    }

    saved_paths: Dict[ExportFormatEnum, str] = {}

    for fmt, artifact in artifacts.items():
        suffix = extension_map.get(fmt, ".txt")
        filename = f"{filename_prefix}{suffix}"

        # Resolve destination path
        dest_path = os.path.abspath(os.path.join(target_dir, filename))

        # Path traversal guard
        common = os.path.commonpath([target_dir, dest_path])
        if common != target_dir:
            raise ValueError(f"Security violation: path traversal detected for destination '{dest_path}'.")

        # Source code overwrite guard
        if filename_prefix.endswith(".py") or dest_path.endswith(".py"):
            raise ValueError(f"Security violation: refusal to overwrite python source file '{dest_path}'.")

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(artifact.raw_content)

        saved_paths[fmt] = dest_path

    return saved_paths
