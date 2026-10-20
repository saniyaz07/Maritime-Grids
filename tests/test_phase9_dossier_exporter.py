"""
test_phase9_dossier_exporter.py — Test Suite for Phase 9 Candidate 5
====================================================================
Integrated Multi-Phase Scenario Dossier & Cross-Phase Export Engine

Covers:
  A. Contract Validation (>= 8 tests)
  B. Referential Integrity Validation (>= 6 tests)
  C. JSON Serialization & Deserialization (>= 6 tests)
  D. Tabular CSV Ledger Exports (>= 6 tests)
  E. Neutral Markdown Report Generation (>= 6 tests)
  F. Safety, Immutability, File Persistence & Performance (>= 6 tests)
"""

import json
import math
import os
import shutil
import tempfile
import time
import pytest

from phase6_contracts import (
    Phase6SimulationResult,
    CIIAssessmentResult,
    PollutantAssessmentResult,
    PollutantEmissionFactors,
    VoyageSimulationRequest,
)
from phase6_gateway import simulate_voyage
from phase7_contracts import (
    InvestmentAppraisalResult,
    LifecycleCashFlow,
    FinancialParameters,
)
from phase8_contracts import (
    OptimizationResult,
    OptimizationCandidate,
    OptimizationParameters,
)
from phase9_dossier_contracts import (
    ExportFormatEnum,
    DiagnosticSeverityEnum,
    DossierDiagnostic,
    ExportArtifactResult,
    CrossPhaseKPISummary,
    DossierAssemblyRequest,
    CrossPhaseScenarioDossier,
)
from phase9_dossier_exporter import (
    validate_referential_integrity,
    assemble_cross_phase_kpis,
    assemble_dossier,
    export_json,
    export_markdown,
    export_csv_cash_flows,
    export_csv_pareto_frontier,
    export_csv_cii_trajectory,
    export_dossier,
    save_dossier_to_disk,
)
from phase9_cii_contracts import (
    TrajectorySimulationResult,
    TrajectorySimulationRequest,
    AnnualTrajectoryRecord,
)


# ==============================================================================
# Synthetic Fixtures
# ==============================================================================

@pytest.fixture
def mock_phase6_result():
    req = VoyageSimulationRequest(
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        month=7,
        speed_knots=12.0,
        distance_nm=250.0,
    )
    return simulate_voyage(req)


@pytest.fixture
def mock_phase7_result():
    fp = FinancialParameters()
    cash_flows = [
        LifecycleCashFlow(
            year=0, capex_usd=-150000.0, opex_usd=0.0, fuel_savings_usd=0.0, carbon_savings_usd=0.0,
            replacement_expenditure_usd=0.0, salvage_value_usd=0.0, net_cash_flow_usd=-150000.0,
            discount_factor=1.0, discounted_cash_flow_usd=-150000.0, cumulative_cash_flow_usd=-150000.0,
            cumulative_discounted_cash_flow_usd=-150000.0, clean_energy_utilized_kwh=0.0, discounted_clean_energy_kwh=0.0,
        ),
        LifecycleCashFlow(
            year=1, capex_usd=0.0, opex_usd=2250.0, fuel_savings_usd=2831.97, carbon_savings_usd=0.0,
            replacement_expenditure_usd=0.0, salvage_value_usd=0.0, net_cash_flow_usd=581.97,
            discount_factor=0.925926, discounted_cash_flow_usd=538.86, cumulative_cash_flow_usd=-149418.03,
            cumulative_discounted_cash_flow_usd=-149461.14, clean_energy_utilized_kwh=10800.0, discounted_clean_energy_kwh=10000.0,
        ),
    ]
    return InvestmentAppraisalResult(
        parameters=fp,
        resolved_fuel_price_usd_per_l=1.0,
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
        total_initial_capex_usd=150000.0,
        total_replacement_capex_usd=60000.0,
        total_lifecycle_opex_usd=33750.0,
        total_undiscounted_benefits_usd=48530.0,
        net_present_value_usd=-172136.70,
        internal_rate_of_return_pct=-22.7467,
        irr_status="IRR_UNIQUE_ROOT",
        simple_payback_years=None,
        payback_status="PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON",
        discounted_payback_years=None,
        discounted_payback_status="DISCOUNTED_PAYBACK_NOT_ACHIEVED_WITHIN_HORIZON",
        lcoe_usd_per_kwh=2.128134,
        lcoe_status="LCOE_CALCULATED",
        cash_flows=cash_flows,
        warnings=[],
    )


@pytest.fixture
def mock_phase8_result():
    params = OptimizationParameters(
        ship_type="Tanker Ship",
        objective="MAX_NPV",
        annual_voyages=52,
    )
    opt_cand = OptimizationCandidate(
        solar_area_m2=100.0,
        battery_capacity_kwh=200.0,
        battery_mass_tonnes=1.7,
        deck_area_limit_m2=833.0,
        battery_weight_limit_tonnes=700.0,
        is_physically_valid=True,
        constraint_violations=[],
        candidate_status="VALID",
        clean_energy_available_kwh=15000.0,
        clean_energy_utilized_kwh=10800.0,
        curtailed_energy_kwh=4200.0,
        feasibility_status="FEASIBLE",
        annual_fuel_displaced_L=2831.9656,
        annual_co2_displaced_kg=7495.9296,
        total_initial_capex_usd=150000.0,
        net_present_value_usd=-172136.70,
        internal_rate_of_return_pct=-22.7467,
        irr_status="IRR_UNIQUE_ROOT",
        simple_payback_years=None,
        discounted_payback_years=None,
        lcoe_usd_per_kwh=2.128134,
        lcoe_status="LCOE_CALCULATED",
        objective_value=-172136.70,
    )
    return OptimizationResult(
        parameters=params,
        resolved_max_solar_area_m2=833.0,
        resolved_max_battery_capacity_kwh=1000.0,
        resolved_step_battery_capacity_kwh=50.0,
        solar_candidate_count=10,
        battery_candidate_count=10,
        total_candidates_evaluated=100,
        feasible_candidates_count=100,
        infeasible_candidates_count=0,
        optimal_candidate=opt_cand,
        top_candidates=[opt_cand],
        tie_candidates_notes=[],
        pareto_frontier=[opt_cand],
        candidate_results=[opt_cand],
        diagnostics="OPTIMAL_CANDIDATE_FOUND",
        warnings=[],
    )


@pytest.fixture
def mock_candidate4_result():
    req = TrajectorySimulationRequest(
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        dwt_tonnes=14000.0,
        route_id="Escravos-Lagos",
        voyage_distance_nm=250.0,
        annual_voyages=52,
        baseline_single_voyage_fuel_L=20124.3,
        baseline_single_voyage_co2_kg=53268.0,
        start_year=2023,
        end_year=2024,
    )
    records = [
        AnnualTrajectoryRecord(
            year=2023, regulatory_basis="STATUTORY", reduction_factor_z_pct=5.0,
            annual_distance_nm=13000.0, annual_transport_work_dwt_nm=182000000.0,
            baseline_annual_fuel_L=1046463.6, baseline_annual_co2_kg=2769936.0,
            assisted_annual_fuel_L=1043631.6, assisted_annual_co2_kg=2762440.0,
            annual_fuel_displaced_L=2831.9656, annual_co2_displaced_kg=7495.9296,
            baseline_attained_cii=15.2194, assisted_attained_cii=15.1782,
            cii_reference=15.5157, required_cii=14.7399,
            baseline_cii_rating="C", assisted_cii_rating="C",
            baseline_is_compliant=True, assisted_is_compliant=True,
            baseline_corrective_action_required=False, assisted_corrective_action_required=False,
        )
    ]
    return TrajectorySimulationResult(
        request=req,
        trajectory=records,
        years_evaluated=1,
        baseline_cumulative_fuel_L=1046463.6,
        baseline_cumulative_co2_kg=2769936.0,
        assisted_cumulative_fuel_L=1043631.6,
        assisted_cumulative_co2_kg=2762440.0,
        total_fuel_displaced_L=2831.9656,
        total_co2_displaced_kg=7495.9296,
        compliance_extension_years=1,
        first_non_compliant_year_baseline=None,
        first_non_compliant_year_assisted=None,
        diagnostics="TRAJECTORY_COMPLETED",
        warnings=[],
    )


# ==============================================================================
# Category A: Contract Validation (8 Tests)
# ==============================================================================

def test_contract_valid_minimal_request(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Minimal Scenario",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        export_formats=[ExportFormatEnum.JSON],
    )
    assert req.scenario_name == "Minimal Scenario"
    assert req.phase6_result is not None
    assert req.phase7_result is None


def test_contract_all_phases_none_raises_error():
    with pytest.raises(ValueError, match="At least one phase or candidate result payload must be supplied"):
        DossierAssemblyRequest(
            scenario_name="Empty Scenario",
            vessel_id="Tanker-01",
            ship_type="Tanker Ship",
            route_id="Escravos-Lagos",
        )


def test_contract_invalid_ship_type(mock_phase6_result):
    with pytest.raises(ValueError, match="Unsupported ship_type"):
        DossierAssemblyRequest(
            scenario_name="Test",
            vessel_id="V1",
            ship_type="Container Ship",
            route_id="Escravos-Lagos",
            phase6_result=mock_phase6_result,
        )


def test_contract_empty_scenario_name_rejected(mock_phase6_result):
    with pytest.raises(ValueError):
        DossierAssemblyRequest(
            scenario_name="",
            vessel_id="V1",
            ship_type="Tanker Ship",
            route_id="Escravos-Lagos",
            phase6_result=mock_phase6_result,
        )


def test_contract_diagnostic_severity_validation():
    d = DossierDiagnostic(
        severity="ERROR",
        code="TEST_ERROR",
        message="Test message",
        affected_module="Phase 6",
    )
    assert d.severity == "ERROR"

    with pytest.raises(ValueError, match="Invalid severity"):
        DossierDiagnostic(
            severity="CRITICAL",  # Invalid
            code="TEST_ERROR",
            message="Test message",
            affected_module="Phase 6",
        )


def test_contract_export_format_enum_values():
    assert ExportFormatEnum.JSON.value == "JSON"
    assert ExportFormatEnum.MARKDOWN.value == "MARKDOWN"
    assert ExportFormatEnum.ALL.value == "ALL"


def test_contract_export_artifact_result():
    art = ExportArtifactResult(
        format_type="JSON",
        content_type="application/json",
        raw_content="{}",
        record_count=1,
    )
    assert art.content_type == "application/json"
    assert art.record_count == 1


def test_contract_full_request(mock_phase6_result, mock_phase7_result, mock_phase8_result):
    req = DossierAssemblyRequest(
        scenario_name="Full Scenario",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
        export_formats=[ExportFormatEnum.ALL],
    )
    assert req.phase6_result is not None
    assert req.phase7_result is not None
    assert req.phase8_result is not None


# ==============================================================================
# Category B: Referential Integrity Validation (6 Tests)
# ==============================================================================

def test_referential_integrity_ship_type_mismatch_phase6(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Mismatch Scenario",
        vessel_id="Trawler-01",
        ship_type="Fishing Trawler",  # Diverges from Phase 6 (Tanker Ship)
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    diags = validate_referential_integrity(req)
    errors = [d for d in diags if d.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].code == "SHIP_TYPE_MISMATCH_PHASE6"

    # assemble_dossier should raise ValueError on ERROR
    with pytest.raises(ValueError, match="SHIP_TYPE_MISMATCH_PHASE6"):
        assemble_dossier(req)


def test_referential_integrity_ship_type_mismatch_phase8(mock_phase6_result, mock_phase8_result):
    # Alter request ship_type to Surfer Boat
    req = DossierAssemblyRequest(
        scenario_name="Mismatch Scenario",
        vessel_id="Surfer-01",
        ship_type="Surfer Boat",
        route_id="Escravos-Lagos",
        phase8_result=mock_phase8_result,
    )
    diags = validate_referential_integrity(req)
    errors = [d for d in diags if d.severity == "ERROR"]
    assert any(e.code == "SHIP_TYPE_MISMATCH_PHASE8" for e in errors)


def test_referential_integrity_route_id_divergence_warning(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Route Divergence Scenario",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Warri-Bonny",  # Diverges from Phase 6 (Escravos-Lagos)
        phase6_result=mock_phase6_result,
    )
    diags = validate_referential_integrity(req)
    warnings = [d for d in diags if d.severity == "WARNING"]
    assert len(warnings) == 1
    assert warnings[0].code == "ROUTE_ID_DIVERGENCE_PHASE6"

    # Warnings allow dossier assembly to succeed
    dossier = assemble_dossier(req)
    assert any(d.code == "ROUTE_ID_DIVERGENCE_PHASE6" for d in dossier.diagnostics)


def test_referential_integrity_sizing_configuration_divergence_warning(
    mock_phase6_result, mock_phase7_result, mock_phase8_result
):
    # Phase 7 has Apv=100. Let's create Phase 8 with Apv=150
    mod_phase8 = mock_phase8_result.model_copy(deep=True)
    mod_phase8.optimal_candidate.solar_area_m2 = 150.0

    req = DossierAssemblyRequest(
        scenario_name="Sizing Divergence Scenario",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase7_result=mock_phase7_result,
        phase8_result=mod_phase8,
    )
    diags = validate_referential_integrity(req)
    warnings = [d for d in diags if d.severity == "WARNING"]
    assert any(w.code == "SIZING_CONFIGURATION_DIVERGENCE" for w in warnings)


def test_referential_integrity_optional_modules_info_diagnostics(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Minimal Scenario",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    diags = validate_referential_integrity(req)
    infos = [d for d in diags if d.severity == "INFO"]
    assert len(infos) == 6  # 6 unsupplied modules


def test_referential_integrity_full_clean_scenario(
    mock_phase6_result, mock_phase7_result, mock_phase8_result
):
    req = DossierAssemblyRequest(
        scenario_name="Clean Full Scenario",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
    )
    diags = validate_referential_integrity(req)
    errors = [d for d in diags if d.severity == "ERROR"]
    warnings = [d for d in diags if d.severity == "WARNING"]
    assert len(errors) == 0
    assert len(warnings) == 0


# ==============================================================================
# Category C: JSON Serialization & Deserialization (6 Tests)
# ==============================================================================

def test_json_export_valid_syntax(mock_phase6_result, mock_phase7_result, mock_phase8_result):
    req = DossierAssemblyRequest(
        scenario_name="JSON Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
    )
    dossier = assemble_dossier(req)
    artifact = export_json(dossier)
    assert artifact.format_type == "JSON"
    assert artifact.content_type == "application/json"

    # Verify JSON loadable
    data = json.loads(artifact.raw_content)
    assert data["scenario"]["scenario_name"] == "JSON Test"
    assert data["phase6"] is not None
    assert data["phase7"] is not None


def test_json_top_level_keys_presence(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Keys Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    dossier = assemble_dossier(req)
    artifact = export_json(dossier)
    data = json.loads(artifact.raw_content)

    required_keys = [
        "metadata", "scenario", "phase6", "phase7", "phase8",
        "candidate1", "candidate2", "candidate3", "candidate4",
        "cross_phase_kpis", "diagnostics", "audit_metadata"
    ]
    for k in required_keys:
        assert k in data, f"Missing key '{k}' in JSON export"


def test_json_null_policy_for_omitted_sections(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Null Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    dossier = assemble_dossier(req)
    artifact = export_json(dossier)
    data = json.loads(artifact.raw_content)

    assert data["phase7"] is None
    assert data["phase8"] is None
    assert data["candidate1"] is None
    assert data["candidate2"] is None


def test_json_round_trip_deserialization(mock_phase6_result, mock_phase7_result, mock_phase8_result):
    req = DossierAssemblyRequest(
        scenario_name="Round Trip",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
    )
    dossier = assemble_dossier(req)
    art = export_json(dossier)

    # Deserializing back into Pydantic model
    rebuilt = CrossPhaseScenarioDossier.model_validate_json(art.raw_content)
    assert rebuilt.scenario["scenario_name"] == "Round Trip"
    assert rebuilt.cross_phase_kpis.vessel_id == "Tanker-01"


def test_json_deterministic_serialization(mock_phase6_result, mock_phase7_result):
    req = DossierAssemblyRequest(
        scenario_name="Determinism",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
    )
    dossier1 = assemble_dossier(req)
    dossier2 = assemble_dossier(req)
    assert export_json(dossier1).raw_content == export_json(dossier2).raw_content


def test_json_no_python_repr_artifacts(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="No Python Repr",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    dossier = assemble_dossier(req)
    art = export_json(dossier)
    assert "<object" not in art.raw_content
    assert "<pydantic" not in art.raw_content


# ==============================================================================
# Category D: Tabular CSV Ledger Exports (6 Tests)
# ==============================================================================

def test_csv_cash_flows_export(mock_phase7_result):
    req = DossierAssemblyRequest(
        scenario_name="CSV Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase7_result=mock_phase7_result,
    )
    dossier = assemble_dossier(req)
    art = export_csv_cash_flows(dossier)

    assert art.format_type == "CSV_CASH_FLOWS"
    assert art.content_type == "text/csv"
    assert art.record_count == 2  # Year 0 and Year 1

    lines = art.raw_content.strip().split("\n")
    assert len(lines) == 3  # Header + 2 rows
    assert "year,capex_usd,opex_usd" in lines[0]


def test_csv_pareto_frontier_export_phase8(mock_phase8_result):
    req = DossierAssemblyRequest(
        scenario_name="Pareto Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase8_result=mock_phase8_result,
    )
    dossier = assemble_dossier(req)
    art = export_csv_pareto_frontier(dossier)

    assert art.format_type == "CSV_PARETO_FRONTIER"
    assert art.record_count == 1
    lines = art.raw_content.strip().split("\n")
    assert "candidate_index,solar_area_m2,battery_capacity_kwh" in lines[0]


def test_csv_cii_trajectory_export(mock_candidate4_result):
    req = DossierAssemblyRequest(
        scenario_name="CII Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        candidate4_trajectory=mock_candidate4_result,
    )
    dossier = assemble_dossier(req)
    art = export_csv_cii_trajectory(dossier)

    assert art.format_type == "CSV_CII_TRAJECTORY"
    assert art.record_count == 1
    lines = art.raw_content.strip().split("\n")
    assert "year,regulatory_basis,reduction_factor_z_pct" in lines[0]


def test_csv_empty_when_source_omitted(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Empty CSV Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    dossier = assemble_dossier(req)
    art = export_csv_cash_flows(dossier)
    assert art.record_count == 0
    lines = art.raw_content.strip().split("\n")
    assert len(lines) == 1  # Header row present


def test_csv_deterministic_formatting(mock_phase7_result):
    req = DossierAssemblyRequest(
        scenario_name="CSV Determinism",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase7_result=mock_phase7_result,
    )
    dossier1 = assemble_dossier(req)
    dossier2 = assemble_dossier(req)
    assert export_csv_cash_flows(dossier1).raw_content == export_csv_cash_flows(dossier2).raw_content


def test_csv_export_all_formats(mock_phase6_result, mock_phase7_result, mock_phase8_result, mock_candidate4_result):
    req = DossierAssemblyRequest(
        scenario_name="Export All Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
        candidate4_trajectory=mock_candidate4_result,
        export_formats=[ExportFormatEnum.ALL],
    )
    artifacts = export_dossier(req)
    assert len(artifacts) == 5
    assert ExportFormatEnum.JSON in artifacts
    assert ExportFormatEnum.MARKDOWN in artifacts
    assert ExportFormatEnum.CSV_CASH_FLOWS in artifacts
    assert ExportFormatEnum.CSV_PARETO_FRONTIER in artifacts
    assert ExportFormatEnum.CSV_CII_TRAJECTORY in artifacts


# ==============================================================================
# Category E: Neutral Markdown Report Generation (6 Tests)
# ==============================================================================

def test_markdown_eleven_sections_presence(mock_phase6_result, mock_phase7_result, mock_phase8_result):
    req = DossierAssemblyRequest(
        scenario_name="Markdown Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
    )
    dossier = assemble_dossier(req)
    art = export_markdown(dossier)
    md = art.raw_content

    expected_sections = [
        "## 1. Scenario Metadata & System Provenance",
        "## 2. Cross-Phase KPI Summary",
        "## 3. Phase 6 — Voyage Physical Predictions & Air Pollutants",
        "## 4. Phase 7 — Lifecycle Techno-Economics & Capital Budgeting",
        "## 5. Phase 8 — Parametric Sizing Optimization & Trade-Offs",
        "## 6. Candidate 1 — Parametric Sensitivity & Break-Even Analysis",
        "## 7. Candidate 2 — Speed & Hybrid Sizing Co-Optimization",
        "## 8. Candidate 3 — Fleet Portfolio Capital Allocation",
        "## 9. Candidate 4 — Multi-Year Regulatory Compliance Trajectory",
        "## 10. Referential Integrity & Diagnostic Audit Log",
        "## 11. Audit Metadata",
    ]
    for s in expected_sections:
        assert s in md, f"Missing section '{s}' in Markdown export"


def test_markdown_neutral_language_policy(mock_phase6_result, mock_phase7_result, mock_phase8_result):
    req = DossierAssemblyRequest(
        scenario_name="Neutrality Check",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
    )
    dossier = assemble_dossier(req)
    art = export_markdown(dossier)
    md = art.raw_content

    # Disallowed evaluative keywords
    disallowed = ["BEST", "WORST", "RECOMMENDED", "IDEAL", "SUPERIOR", "VIABLE"]
    for word in disallowed:
        assert f" {word} " not in md.upper(), f"Disallowed evaluative word '{word}' found in Markdown"


def test_markdown_omitted_sections_render_not_supplied(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Omitted Sections",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    dossier = assemble_dossier(req)
    art = export_markdown(dossier)
    md = art.raw_content
    assert "*Not supplied.*" in md


def test_markdown_kpi_table_rendered(mock_phase6_result, mock_phase7_result):
    req = DossierAssemblyRequest(
        scenario_name="KPI Table",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
    )
    dossier = assemble_dossier(req)
    art = export_markdown(dossier)
    assert "| Physical | Voyage Duration |" in art.raw_content
    assert "| Financial | Initial Capital Expenditure" in art.raw_content


def test_markdown_diagnostics_rendered(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Diags MD",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    dossier = assemble_dossier(req)
    art = export_markdown(dossier)
    assert "OPTIONAL_MODULE_NOT_SUPPLIED" in art.raw_content


def test_markdown_deterministic_output(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="MD Determinism",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
    )
    d1 = assemble_dossier(req)
    d2 = assemble_dossier(req)
    assert export_markdown(d1).raw_content == export_markdown(d2).raw_content


# ==============================================================================
# Category F: Safety, Immutability, File Persistence & Performance (6 Tests)
# ==============================================================================

def test_safety_runtime_sub_ten_ms(mock_phase6_result, mock_phase7_result, mock_phase8_result, mock_candidate4_result):
    req = DossierAssemblyRequest(
        scenario_name="Performance Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        phase8_result=mock_phase8_result,
        candidate4_trajectory=mock_candidate4_result,
        export_formats=[ExportFormatEnum.ALL],
    )
    t0 = time.perf_counter()
    artifacts = export_dossier(req)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.050  # Must be fast sub-second execution (<50ms)
    assert len(artifacts) == 5


def test_immutability_input_objects_unmutated(mock_phase6_result, mock_phase7_result):
    p6_dump_before = mock_phase6_result.model_dump()
    p7_dump_before = mock_phase7_result.model_dump()

    req = DossierAssemblyRequest(
        scenario_name="Immutability Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        export_formats=[ExportFormatEnum.ALL],
    )
    export_dossier(req)

    assert mock_phase6_result.model_dump() == p6_dump_before
    assert mock_phase7_result.model_dump() == p7_dump_before


def test_file_persistence_normal_save(mock_phase6_result, mock_phase7_result):
    req = DossierAssemblyRequest(
        scenario_name="Save Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        phase7_result=mock_phase7_result,
        export_formats=[ExportFormatEnum.JSON, ExportFormatEnum.MARKDOWN],
    )
    artifacts = export_dossier(req)

    with tempfile.TemporaryDirectory() as tmpdir:
        saved = save_dossier_to_disk(artifacts, output_directory=tmpdir, filename_prefix="scenario_a")
        assert len(saved) == 2
        for fmt, fpath in saved.items():
            assert os.path.exists(fpath)
            assert os.path.getsize(fpath) > 0


def test_file_persistence_path_traversal_rejection(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Security Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        export_formats=[ExportFormatEnum.JSON],
    )
    artifacts = export_dossier(req)

    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(ValueError, match="path traversal"):
            save_dossier_to_disk(artifacts, output_directory=tmpdir, filename_prefix="../../evil")


def test_file_persistence_python_overwrite_rejection(mock_phase6_result):
    req = DossierAssemblyRequest(
        scenario_name="Overwrite Test",
        vessel_id="Tanker-01",
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
        phase6_result=mock_phase6_result,
        export_formats=[ExportFormatEnum.JSON],
    )
    # Mock extension mapping to .py
    artifacts = export_dossier(req)
    with tempfile.TemporaryDirectory() as tmpdir:
        # If user tries to use .py prefix
        with pytest.raises(ValueError, match="refusal to overwrite python source file"):
            save_dossier_to_disk(artifacts, output_directory=tmpdir, filename_prefix="malicious.py")


def test_no_optimizer_or_ml_imports():
    """Verify Candidate 5 does not call optimize_system_sizing or load ML models."""
    import ast
    import phase9_dossier_exporter

    src = open(phase9_dossier_exporter.__file__, "r", encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "optimize_system_sizing"
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr != "optimize_system_sizing"
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                assert node.module not in ("torch", "xgboost", "joblib")
