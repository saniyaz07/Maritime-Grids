"""
test_phase3g_fleet.py — Test Suite for Phase 3G Fleet & Annual Schedule Aggregation
==================================================================================
Validates:
  1. Single voyage schedule evaluation
  2. 12-month annual schedule evaluation
  3. Empty schedule rejection
  4. Duplicate voyage_id rejection
  5. Inconsistent ship_type rejection
  6. Invalid Tier 1 input propagation
  7. Exact N-voyage delegation spy (orchestrate_phase3_voyage called exactly N times)
  8. Schedule order preservation in voyage_evaluations
  9. Cumulative distance sum matches individual distances
  10. Cumulative duration sum matches individual durations
  11. Cumulative transport work matches sum of individual (DWT * distance)
  12. Cumulative baseline fuel sum matches individual baseline fuels
  13. Cumulative baseline fuel cost matches individual baseline fuel costs
  14. Cumulative baseline CO2 matches individual baseline CO2s
  15. Cumulative clean energy utilized matches individual clean energies utilized
  16. Cumulative clean energy curtailed matches individual curtailments
  17. Cumulative fuel displaced matches individual displaced fuels
  18. Cumulative CO2 displaced matches individual displaced CO2s
  19. Cumulative net assisted fuel matches individual net assisted fuels
  20. Cumulative net assisted fuel cost matches individual net assisted costs
  21. Cumulative net assisted CO2 matches individual net assisted CO2s
  22. Annual baseline operational CII equals (total_co2 * 1000) / total_transport_work
  23. Annual assisted operational CII equals (total_assisted_co2 * 1000) / total_transport_work
  24. Counterexample: Annual CII != arithmetic average of voyage CIIs
  25. Exact fuel conservation: total_assisted_fuel_L + total_fuel_displaced_L == total_baseline_fuel_L
  26. Exact CO2 conservation: total_assisted_co2_kg + total_co2_displaced_kg == total_baseline_co2_kg
  27. Displacement upper bound: displaced <= baseline
  28. Mixed feasibility: schedule with both FEASIBLE and PARTIAL voyages
  29. Seasonal monthly GHI variation across operational profile
  30. Repeated evaluation determinism
  31. Raw dictionary request support
  32. Voyage-specific override precedence
  33. Frozen model SHA-256 hash preservation
"""

import pytest
from unittest.mock import patch
from pydantic import ValidationError

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    AppliedScenarioParameters,
    FROZEN_MODEL_HASHES,
)
from phase3f_comparison import ScenarioOverride
from phase3g_fleet import (
    VoyageScheduleEntry,
    AnnualFleetEvaluationRequest,
    AnnualScheduleSummary,
    evaluate_annual_fleet_schedule,
)


# ==============================================================================
# Pytest Fixtures and Helpers
# ==============================================================================
@pytest.fixture
def base_scenario_params():
    return AppliedScenarioParameters(
        fuel_price_usd_per_l=1.15,
        initial_soc=0.90,
        auxiliary_energy_demand_kwh=180.0,
        soc_reserve=0.20,
        generator_sfoc_kg_per_kwh=0.220,
        fuel_density_kg_per_l=0.850,
        emission_factor_kgco2_per_kgfuel=3.114,
        solar_derate_factor=0.85,
    )


def make_schedule_entry(
    voyage_id: str,
    distance_nm: float = 250.0,
    duration_hours: float = 18.5,
    dwt: float = 1800.0,
    fuel_L: float = 4120.5,
    co2_kg: float = 10906.9,
    month: str = "January",
    route_id: str = "Escravos-Lagos",
    overrides: ScenarioOverride = None,
    ship_type: str = "Oil Service Boat"
) -> VoyageScheduleEntry:
    meta = VoyageMetadata(
        ship_type=ship_type,
        distance_nm=distance_nm,
        voyage_duration_hours=duration_hours,
        deadweight_tonnes=dwt,
    )
    preds = Tier1Phase2Predictions.model_validate({
        "weather": {"temperature_c": 22.0, "wind_speed_knots": 14.0, "significant_wave_height_m": 1.5},
        "fuel_consumption_L": {"value": fuel_L, "unit": "Liters", "evidence_level": "B - STRONGLY INFERRED", "scope": "Total voyage fuel consumption"},
        "co2_emissions_kg": {"value": co2_kg, "unit": "kg"},
        "battery_health": {"predicted_soh": 0.75, "nominal_pack_capacity_kwh": 649.728, "effective_pack_capacity_kwh": 487.296},
        "battery_operation": {"predicted_soc_end_of_voyage": 0.55, "soc_formulation": "Degradation-adjusted pack SOC"},
    })
    return VoyageScheduleEntry(
        voyage_id=voyage_id,
        voyage_metadata=meta,
        tier_1_phase2_predictions=preds,
        route_id=route_id,
        month=month,
        scenario_overrides=overrides,
    )


# ==============================================================================
# Category 1: Single Voyage & Annual Schedule Execution
# ==============================================================================
def test_single_voyage_schedule_evaluation(base_scenario_params):
    entry = make_schedule_entry("V001", distance_nm=200.0, duration_hours=15.0, dwt=1500.0)
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-ALPHA",
        schedule=[entry],
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    assert isinstance(summary, AnnualScheduleSummary)
    assert summary.vessel_id == "VESSEL-ALPHA"
    assert summary.ship_type == "Oil Service Boat"
    assert summary.total_voyages == 1
    assert summary.total_distance_nm == 200.0
    assert summary.total_duration_hours == 15.0
    assert summary.total_transport_work_dwt_nm == 200.0 * 1500.0
    assert len(summary.voyage_evaluations) == 1
    assert summary.voyage_evaluations[0].voyage_metadata.distance_nm == 200.0


def test_twelve_month_annual_schedule_evaluation(base_scenario_params):
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    schedule = [
        make_schedule_entry(f"VOY-2026-{i+1:02d}", month=m, distance_nm=300.0, duration_hours=20.0, dwt=1800.0)
        for i, m in enumerate(months)
    ]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-ANNUAL-12",
        schedule=schedule,
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    assert summary.total_voyages == 12
    assert summary.total_distance_nm == 300.0 * 12
    assert summary.total_duration_hours == 20.0 * 12
    assert summary.total_transport_work_dwt_nm == 300.0 * 1800.0 * 12
    assert summary.annual_baseline_operational_cii > 0.0
    assert summary.annual_assisted_operational_cii > 0.0
    assert summary.annual_assisted_operational_cii < summary.annual_baseline_operational_cii


# ==============================================================================
# Category 2: Validation & Contract Integrity
# ==============================================================================
def test_empty_schedule_rejected(base_scenario_params):
    with pytest.raises(ValidationError):
        AnnualFleetEvaluationRequest(
            vessel_id="VESSEL-EMPTY",
            schedule=[],
            base_scenario_parameters=base_scenario_params,
        )


def test_duplicate_voyage_id_rejected(base_scenario_params):
    v1 = make_schedule_entry("VOY-DUP", distance_nm=100.0)
    v2 = make_schedule_entry("VOY-DUP", distance_nm=200.0)
    with pytest.raises(ValueError) as exc:
        AnnualFleetEvaluationRequest(
            vessel_id="VESSEL-DUP",
            schedule=[v1, v2],
            base_scenario_parameters=base_scenario_params,
        )
    assert "Duplicate voyage_id detected" in str(exc.value)


def test_inconsistent_ship_type_rejected(base_scenario_params):
    v1 = make_schedule_entry("V1", ship_type="Oil Service Boat")
    v2 = make_schedule_entry("V2", ship_type="Platform Supply Vessel")
    with pytest.raises(ValueError) as exc:
        AnnualFleetEvaluationRequest(
            vessel_id="VESSEL-MISMATCH",
            schedule=[v1, v2],
            base_scenario_parameters=base_scenario_params,
        )
    assert "Inconsistent ship_type in single-vessel schedule" in str(exc.value)


def test_invalid_tier1_input_propagation(base_scenario_params):
    with pytest.raises(ValidationError):
        VoyageScheduleEntry(
            voyage_id="V_INVALID",
            voyage_metadata=VoyageMetadata(
                ship_type="Oil Service Boat",
                distance_nm=-50.0,
                voyage_duration_hours=10.0,
                deadweight_tonnes=1800.0,
            ),
            tier_1_phase2_predictions=Tier1Phase2Predictions.model_validate({}),
            route_id="Escravos-Lagos",
            month="January",
        )


# ==============================================================================
# Category 3: Delegation & Schedule Ordering
# ==============================================================================
def test_exact_n_voyage_delegation_spy(base_scenario_params):
    schedule = [make_schedule_entry(f"VOY-SPY-{i}", distance_nm=150.0) for i in range(5)]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-SPY",
        schedule=schedule,
        base_scenario_parameters=base_scenario_params,
    )

    with patch("phase3g_fleet.orchestrate_phase3_voyage", wraps=evaluate_annual_fleet_schedule.__globals__["orchestrate_phase3_voyage"]) as spy_coord:
        summary = evaluate_annual_fleet_schedule(req)
        assert spy_coord.call_count == 5
        assert summary.total_voyages == 5


def test_schedule_order_preserved(base_scenario_params):
    ids = ["VOY-JAN", "VOY-FEB", "VOY-MAR", "VOY-APR", "VOY-MAY"]
    schedule = [make_schedule_entry(vid, distance_nm=100.0 + i * 20) for i, vid in enumerate(ids)]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-ORDER",
        schedule=schedule,
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    assert len(summary.voyage_evaluations) == 5
    for i, expected_id in enumerate(ids):
        assert summary.voyage_evaluations[i].voyage_metadata.distance_nm == 100.0 + i * 20


# ==============================================================================
# Category 4: Exact Cumulative Metric Sums (Individual Tests 9-21)
# ==============================================================================
def test_cumulative_distance_sum(base_scenario_params):
    entries = [
        make_schedule_entry("V1", distance_nm=120.0),
        make_schedule_entry("V2", distance_nm=230.0),
        make_schedule_entry("V3", distance_nm=340.0),
    ]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    assert pytest.approx(summary.total_distance_nm, 1e-4) == 120.0 + 230.0 + 340.0


def test_cumulative_duration_sum(base_scenario_params):
    entries = [
        make_schedule_entry("V1", duration_hours=10.0),
        make_schedule_entry("V2", duration_hours=16.0),
        make_schedule_entry("V3", duration_hours=24.0),
    ]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    assert pytest.approx(summary.total_duration_hours, 1e-4) == 10.0 + 16.0 + 24.0


def test_cumulative_transport_work_sum(base_scenario_params):
    entries = [
        make_schedule_entry("V1", distance_nm=120.0, dwt=1500.0),
        make_schedule_entry("V2", distance_nm=230.0, dwt=1500.0),
        make_schedule_entry("V3", distance_nm=340.0, dwt=1500.0),
    ]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    expected_work = (120.0 * 1500.0) + (230.0 * 1500.0) + (340.0 * 1500.0)
    assert pytest.approx(summary.total_transport_work_dwt_nm, 1e-4) == expected_work


def test_cumulative_baseline_fuel_sum(base_scenario_params):
    entries = [
        make_schedule_entry("V1", fuel_L=2000.0),
        make_schedule_entry("V2", fuel_L=3500.0),
    ]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    assert pytest.approx(summary.total_baseline_fuel_L, 1e-4) == 2000.0 + 3500.0


def test_cumulative_baseline_fuel_cost_sum(base_scenario_params):
    entries = [
        make_schedule_entry("V1", fuel_L=2000.0),
        make_schedule_entry("V2", fuel_L=3500.0),
    ]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_cost = sum(out.tier_2_baseline_metrics.baseline_fuel_cost_usd for out in summary.voyage_evaluations)
    assert pytest.approx(summary.total_baseline_fuel_cost_usd, 1e-4) == sum_cost


def test_cumulative_baseline_co2_sum(base_scenario_params):
    entries = [
        make_schedule_entry("V1", co2_kg=5300.0),
        make_schedule_entry("V2", co2_kg=9275.0),
    ]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    assert pytest.approx(summary.total_baseline_co2_kg, 1e-4) == 5300.0 + 9275.0


def test_cumulative_clean_energy_utilized_sum(base_scenario_params):
    entries = [make_schedule_entry("V1", month="March"), make_schedule_entry("V2", month="August")]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_clean_util = sum(out.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh for out in summary.voyage_evaluations)
    assert pytest.approx(summary.total_clean_energy_utilized_kwh, 1e-4) == sum_clean_util


def test_cumulative_clean_energy_curtailed_sum(base_scenario_params):
    entries = [make_schedule_entry("V1", month="March"), make_schedule_entry("V2", month="August")]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_clean_curt = sum(
        max(0.0, out.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh - out.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh)
        for out in summary.voyage_evaluations
    )
    assert pytest.approx(summary.total_clean_energy_curtailed_kwh, 1e-4) == sum_clean_curt


def test_cumulative_fuel_displaced_sum(base_scenario_params):
    entries = [make_schedule_entry("V1", month="January"), make_schedule_entry("V2", month="May")]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_disp = sum(out.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L for out in summary.voyage_evaluations)
    assert pytest.approx(summary.total_fuel_displaced_L, 1e-4) == sum_disp


def test_cumulative_co2_displaced_sum(base_scenario_params):
    entries = [make_schedule_entry("V1", month="January"), make_schedule_entry("V2", month="May")]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_disp = sum(out.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg for out in summary.voyage_evaluations)
    assert pytest.approx(summary.total_co2_displaced_kg, 1e-4) == sum_disp


def test_cumulative_assisted_fuel_sum(base_scenario_params):
    entries = [make_schedule_entry("V1"), make_schedule_entry("V2")]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_asst = sum(out.tier_4_engineering_scenario_estimates.net_assisted_fuel_L for out in summary.voyage_evaluations)
    assert pytest.approx(summary.total_assisted_fuel_L, 1e-4) == sum_asst


def test_cumulative_assisted_fuel_cost_sum(base_scenario_params):
    entries = [make_schedule_entry("V1"), make_schedule_entry("V2")]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_cost = sum(out.tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd for out in summary.voyage_evaluations)
    assert pytest.approx(summary.total_assisted_fuel_cost_usd, 1e-4) == sum_cost


def test_cumulative_assisted_co2_sum(base_scenario_params):
    entries = [make_schedule_entry("V1"), make_schedule_entry("V2")]
    req = AnnualFleetEvaluationRequest(vessel_id="VESSEL-SUMS", schedule=entries, base_scenario_parameters=base_scenario_params)
    summary = evaluate_annual_fleet_schedule(req)
    sum_co2 = sum(out.tier_4_engineering_scenario_estimates.net_assisted_co2_kg for out in summary.voyage_evaluations)
    assert pytest.approx(summary.total_assisted_co2_kg, 1e-4) == sum_co2


# ==============================================================================
# Category 5: Operational Carbon Intensity Indicator (CII) Rigor
# ==============================================================================
def test_annual_baseline_operational_cii_math(base_scenario_params):
    entries = [
        make_schedule_entry("V1", distance_nm=150.0, dwt=2000.0, co2_kg=4000.0),
        make_schedule_entry("V2", distance_nm=300.0, dwt=2000.0, co2_kg=8000.0),
    ]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-CII-BASE",
        schedule=entries,
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    expected_transport_work = (150.0 * 2000.0) + (300.0 * 2000.0)
    expected_co2 = 4000.0 + 8000.0
    expected_cii = (expected_co2 * 1000.0) / expected_transport_work

    assert pytest.approx(summary.annual_baseline_operational_cii, 1e-4) == expected_cii


def test_annual_assisted_operational_cii_math(base_scenario_params):
    entries = [
        make_schedule_entry("V1", distance_nm=100.0, dwt=1800.0),
        make_schedule_entry("V2", distance_nm=250.0, dwt=1800.0),
    ]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-CII-ASST",
        schedule=entries,
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    expected_cii = (summary.total_assisted_co2_kg * 1000.0) / summary.total_transport_work_dwt_nm
    assert pytest.approx(summary.annual_assisted_operational_cii, 1e-4) == expected_cii


def test_counterexample_cii_not_arithmetic_average(base_scenario_params):
    """
    CRITICAL PROOF TEST:
    Demonstrates that IMO MEPC.352(78) annual operational CII is NOT the arithmetic
    average of individual voyage CIIs when voyages have unequal transport work.
    """
    v1 = make_schedule_entry("V1-SHORT", distance_nm=50.0, dwt=1000.0, fuel_L=2000.0, co2_kg=5300.0)
    v2 = make_schedule_entry("V2-LONG", distance_nm=500.0, dwt=2500.0, fuel_L=6000.0, co2_kg=15900.0)

    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-COUNTEREXAMPLE",
        schedule=[v1, v2],
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    out1, out2 = summary.voyage_evaluations
    work1 = out1.voyage_metadata.deadweight_tonnes * out1.voyage_metadata.distance_nm
    work2 = out2.voyage_metadata.deadweight_tonnes * out2.voyage_metadata.distance_nm

    asst_co2_1 = out1.tier_4_engineering_scenario_estimates.net_assisted_co2_kg
    asst_co2_2 = out2.tier_4_engineering_scenario_estimates.net_assisted_co2_kg

    cii_voyage_1 = (asst_co2_1 * 1000.0) / work1
    cii_voyage_2 = (asst_co2_2 * 1000.0) / work2

    arithmetic_avg_cii = (cii_voyage_1 + cii_voyage_2) / 2.0
    true_annual_cii = summary.annual_assisted_operational_cii

    # Must be substantially different
    assert abs(true_annual_cii - arithmetic_avg_cii) > 1.0, (
        f"Counterexample failed: True annual CII ({true_annual_cii}) is too close to "
        f"arithmetic average ({arithmetic_avg_cii})"
    )


# ==============================================================================
# Category 6: Physical Conservation Invariants
# ==============================================================================
def test_exact_fuel_conservation_identity(base_scenario_params):
    entries = [make_schedule_entry(f"V{i}", distance_nm=120.0 + i*30) for i in range(4)]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-FUEL-CONS",
        schedule=entries,
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    lhs = summary.total_assisted_fuel_L + summary.total_fuel_displaced_L
    rhs = summary.total_baseline_fuel_L
    assert abs(lhs - rhs) < 1e-4


def test_exact_co2_conservation_identity(base_scenario_params):
    entries = [make_schedule_entry(f"V{i}", distance_nm=120.0 + i*30) for i in range(4)]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-CO2-CONS",
        schedule=entries,
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    lhs = summary.total_assisted_co2_kg + summary.total_co2_displaced_kg
    rhs = summary.total_baseline_co2_kg
    assert abs(lhs - rhs) < 1e-4


def test_displacement_upper_bounds(base_scenario_params):
    entries = [make_schedule_entry(f"V{i}") for i in range(3)]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-BOUNDS",
        schedule=entries,
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    assert summary.total_fuel_displaced_L <= summary.total_baseline_fuel_L + 1e-4
    assert summary.total_co2_displaced_kg <= summary.total_baseline_co2_kg + 1e-4
    assert summary.total_assisted_fuel_L >= 0.0
    assert summary.total_assisted_co2_kg >= 0.0


# ==============================================================================
# Category 7: Feasibility Auditing
# ==============================================================================
def test_mixed_feasibility_status_counting(base_scenario_params):
    v1 = make_schedule_entry("V1-FEASIBLE", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=10.0))
    v2 = make_schedule_entry("V2-PARTIAL", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=10000.0))
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-FEASIBILITY",
        schedule=[v1, v2],
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    assert summary.feasible_voyage_count == 1
    assert summary.partial_voyage_count == 1
    assert summary.feasible_voyage_count + summary.partial_voyage_count == summary.total_voyages


# ==============================================================================
# Category 8: Seasonality, Determinism & Integrity
# ==============================================================================
def test_seasonal_monthly_ghi_variation(base_scenario_params):
    v_jan = make_schedule_entry("V-JAN", month="January", route_id="Escravos-Lagos")
    v_jul = make_schedule_entry("V-JUL", month="July", route_id="Escravos-Lagos")

    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-SEASONAL",
        schedule=[v_jan, v_jul],
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)

    out_jan, out_jul = summary.voyage_evaluations
    solar_jan = out_jan.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh
    solar_jul = out_jul.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh

    assert solar_jan != solar_jul
    assert solar_jan > 0.0
    assert solar_jul > 0.0


def test_repeated_evaluation_determinism(base_scenario_params):
    entries = [make_schedule_entry("V1", month="March"), make_schedule_entry("V2", month="September")]
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-DETERMINISM",
        schedule=entries,
        base_scenario_parameters=base_scenario_params,
    )
    summary1 = evaluate_annual_fleet_schedule(req)
    summary2 = evaluate_annual_fleet_schedule(req)

    assert summary1.model_dump() == summary2.model_dump()


def test_dict_input_support(base_scenario_params):
    entry_dict = {
        "voyage_id": "V-DICT",
        "voyage_metadata": {
            "ship_type": "Oil Service Boat",
            "distance_nm": 200.0,
            "voyage_duration_hours": 15.0,
            "deadweight_tonnes": 1800.0,
        },
        "tier_1_phase2_predictions": {
            "weather": {"temperature_c": 22.0, "wind_speed_knots": 14.0, "significant_wave_height_m": 1.5},
            "fuel_consumption_L": {"value": 3000.0, "unit": "Liters", "evidence_level": "B - STRONGLY INFERRED", "scope": "Total voyage fuel consumption"},
            "co2_emissions_kg": {"value": 7950.0, "unit": "kg"},
            "battery_health": {"predicted_soh": 0.75, "nominal_pack_capacity_kwh": 649.728, "effective_pack_capacity_kwh": 487.296},
            "battery_operation": {"predicted_soc_end_of_voyage": 0.55, "soc_formulation": "Degradation-adjusted pack SOC"},
        },
        "route_id": "Escravos-Lagos",
        "month": "April",
    }
    req_dict = {
        "vessel_id": "VESSEL-DICT-INPUT",
        "schedule": [entry_dict],
        "base_scenario_parameters": base_scenario_params.model_dump(),
    }
    summary = evaluate_annual_fleet_schedule(req_dict)
    assert summary.total_voyages == 1
    assert summary.vessel_id == "VESSEL-DICT-INPUT"


def test_voyage_override_takes_precedence(base_scenario_params):
    v1 = make_schedule_entry(
        "V1-OVERRIDE",
        fuel_L=1000.0,
        overrides=ScenarioOverride(fuel_price_usd_per_l=2.00),
    )
    req = AnnualFleetEvaluationRequest(
        vessel_id="VESSEL-OVERRIDE",
        schedule=[v1],
        base_scenario_parameters=base_scenario_params,
    )
    summary = evaluate_annual_fleet_schedule(req)
    assert pytest.approx(summary.total_baseline_fuel_cost_usd, 1e-2) == 2000.0


def test_frozen_model_hashes_verified():
    expected = {
        "weather_final.joblib": "39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3",
        "fuel_xgb.joblib": "cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323",
        "battery_soc_lstm.pt": "c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25",
        "battery_soh_final.joblib": "9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1",
    }
    assert FROZEN_MODEL_HASHES == expected
