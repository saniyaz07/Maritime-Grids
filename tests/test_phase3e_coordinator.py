"""
test_phase3e_coordinator.py — Test Suite for Phase 3E Decision Coordinator
==========================================================================
Validates:
  - Complete end-to-end orchestration for all four vessel profiles
  - Canonical tier execution sequence (Tier 1 -> Tier 2 -> Tier 3 -> Tier 4)
  - Data propagation across tiers (fuel, CO2, SOH, clean energy utilized, price)
  - Critical anti-double-counting rule (curtailed surplus never displaces fuel)
  - Scenario parameter overrides (price, SFOC, density, emission factor, derate, SOC)
  - Edge cases (zero demand, zero solar, zero displacement, partial/full feasibility)
  - Fail-fast error propagation (invalid inputs, unknown vessel, missing route/month)
  - Root contract validation enforcement (cross-tier price matching, displacement caps)
  - Idempotency and deterministic execution
  - Delegation to lower-tier calculation modules (no duplicated formulas)
"""

import copy
import pytest
from unittest.mock import patch
from pydantic import ValidationError

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    Tier2BaselineMetrics,
    Tier3CleanEnergyFeasibility,
    Tier4EngineeringScenarioEstimates,
    AppliedScenarioParameters,
    AuditMetadata,
    Phase3Output,
    FROZEN_MODEL_HASHES,
    get_sourced_fuel_price,
)
from phase3_coordinator import (
    orchestrate_phase3_voyage,
    run_coordinator_scenario,
)
from phase3_baseline import calculate_tier2_baseline
from phase3_feasibility import calculate_tier3_clean_energy_feasibility
from phase3_displacement import calculate_tier4_engineering_scenario_estimates


@pytest.fixture
def sample_voyage_metadata():
    return VoyageMetadata(
        ship_type="Oil Service Boat",
        distance_nm=250.0,
        voyage_duration_hours=18.5,
        deadweight_tonnes=1800.0,
    )


@pytest.fixture
def sample_tier1_predictions():
    return Tier1Phase2Predictions.model_validate({
        "weather": {
            "temperature_c": 22.4,
            "wind_speed_knots": 14.2,
            "significant_wave_height_m": 1.6,
        },
        "fuel_consumption_L": {
            "value": 4120.5,
            "unit": "Liters",
            "evidence_level": "B - STRONGLY INFERRED",
            "scope": "Total voyage fuel consumption",
        },
        "co2_emissions_kg": {
            "value": 10906.9,
            "unit": "kg",
        },
        "battery_health": {
            "predicted_soh": 0.7471,
            "nominal_pack_capacity_kwh": 649.728,
            "effective_pack_capacity_kwh": 485.4118,
        },
        "battery_operation": {
            "predicted_soc_end_of_voyage": 0.5292,
            "soc_formulation": "Degradation-adjusted pack SOC",
        },
    })


# ==============================================================================
# A. Successful Orchestration & Vessel Profiles (Tests 1-5)
# ==============================================================================
def test_successful_orchestration_oil_service_boat(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    assert isinstance(output, Phase3Output)
    assert output.voyage_metadata.ship_type == "Oil Service Boat"
    assert output.applied_scenario_parameters.fuel_price_usd_per_l == 1.15
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == 1.15
    assert output.tier_3_clean_energy_feasibility.auxiliary_energy_demand_kwh == 180.0
    assert output.tier_4_engineering_scenario_estimates.status == "ENGINEERING SCENARIO ESTIMATE"
    assert output.audit_metadata.phase2_models_frozen is True


def test_successful_orchestration_fishing_trawler():
    v_meta = VoyageMetadata(
        ship_type="Fishing Trawler",
        distance_nm=120.0,
        voyage_duration_hours=12.0,
        deadweight_tonnes=450.0,
    )
    t1 = Tier1Phase2Predictions.model_validate({
        "weather": {"temperature_c": 18.0, "wind_speed_knots": 10.0, "significant_wave_height_m": 1.2},
        "fuel_consumption_L": {"value": 1500.0, "unit": "Liters", "evidence_level": "B - STRONGLY INFERRED", "scope": "Total voyage fuel consumption"},
        "co2_emissions_kg": {"value": 3950.0, "unit": "kg"},
        "battery_health": {"predicted_soh": 0.85, "nominal_pack_capacity_kwh": 250.2144, "effective_pack_capacity_kwh": 212.6822},
        "battery_operation": {"predicted_soc_end_of_voyage": 0.65},
    })
    output = orchestrate_phase3_voyage(
        voyage_metadata=v_meta,
        tier1_predictions=t1,
        auxiliary_energy_demand_kwh=80.0,
        daily_ghi_kwh_per_m2=4.8,
    )
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == 1.10
    assert output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L > 0.0


def test_successful_orchestration_surfer_boat():
    v_meta = VoyageMetadata(
        ship_type="Surfer Boat",
        distance_nm=60.0,
        voyage_duration_hours=3.5,
        deadweight_tonnes=120.0,
    )
    t1 = Tier1Phase2Predictions.model_validate({
        "weather": {"temperature_c": 26.0, "wind_speed_knots": 8.0, "significant_wave_height_m": 0.8},
        "fuel_consumption_L": {"value": 650.0, "unit": "Liters", "evidence_level": "B - STRONGLY INFERRED", "scope": "Total voyage fuel consumption"},
        "co2_emissions_kg": {"value": 1720.0, "unit": "kg"},
        "battery_health": {"predicted_soh": 0.92, "nominal_pack_capacity_kwh": 149.9904, "effective_pack_capacity_kwh": 137.9912},
        "battery_operation": {"predicted_soc_end_of_voyage": 0.70},
    })
    output = orchestrate_phase3_voyage(
        voyage_metadata=v_meta,
        tier1_predictions=t1,
        auxiliary_energy_demand_kwh=30.0,
        daily_ghi_kwh_per_m2=5.5,
    )
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == 1.20
    assert output.tier_3_clean_energy_feasibility.feasibility_status == "FEASIBLE"


def test_successful_orchestration_tanker_ship():
    v_meta = VoyageMetadata(
        ship_type="Tanker Ship",
        distance_nm=800.0,
        voyage_duration_hours=65.0,
        deadweight_tonnes=50000.0,
    )
    t1 = Tier1Phase2Predictions.model_validate({
        "weather": {"temperature_c": 24.0, "wind_speed_knots": 16.0, "significant_wave_height_m": 2.2},
        "fuel_consumption_L": {"value": 18500.0, "unit": "Liters", "evidence_level": "B - STRONGLY INFERRED", "scope": "Total voyage fuel consumption"},
        "co2_emissions_kg": {"value": 49000.0, "unit": "kg"},
        "battery_health": {"predicted_soh": 0.80, "nominal_pack_capacity_kwh": 1199.9232, "effective_pack_capacity_kwh": 959.9386},
        "battery_operation": {"predicted_soc_end_of_voyage": 0.45},
    })
    output = orchestrate_phase3_voyage(
        voyage_metadata=v_meta,
        tier1_predictions=t1,
        auxiliary_energy_demand_kwh=600.0,
        daily_ghi_kwh_per_m2=4.5,
    )
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == 0.95
    assert output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L < 18500.0


def test_run_coordinator_scenario_interface(sample_voyage_metadata, sample_tier1_predictions):
    scenario_params = AppliedScenarioParameters(
        fuel_price_usd_per_l=1.35,
        initial_soc=0.88,
        auxiliary_energy_demand_kwh=150.0,
        soc_reserve=0.25,
        generator_sfoc_kg_per_kwh=0.215,
        fuel_density_kg_per_l=0.845,
        emission_factor_kgco2_per_kgfuel=3.114,
        solar_derate_factor=0.80,
    )
    output = run_coordinator_scenario(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        scenario_parameters=scenario_params,
        daily_ghi_kwh_per_m2=5.2,
    )
    assert output.applied_scenario_parameters.fuel_price_usd_per_l == 1.35
    assert output.applied_scenario_parameters.initial_soc == 0.88
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == 1.35


# ==============================================================================
# B. Tier Ordering & Structure (Tests 6-7)
# ==============================================================================
def test_tier_ordering_and_structure(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    # Check all tiers are populated and typed
    assert hasattr(output, "tier_1_phase2_predictions")
    assert hasattr(output, "tier_2_baseline_metrics")
    assert hasattr(output, "tier_3_clean_energy_feasibility")
    assert hasattr(output, "tier_4_engineering_scenario_estimates")
    assert hasattr(output, "applied_scenario_parameters")
    assert hasattr(output, "audit_metadata")


def test_weather_prediction_retained_as_descriptive_metadata(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    # Weather is descriptive metadata in Tier 1 and does not alter solar derating or feasibility
    assert output.tier_1_phase2_predictions.weather.temperature_c == 22.4
    assert output.tier_1_phase2_predictions.weather.wind_speed_knots == 14.2
    assert output.tier_1_phase2_predictions.weather.significant_wave_height_m == 1.6


# ==============================================================================
# C. Data Propagation Between Tiers (Tests 8-10)
# ==============================================================================
def test_data_propagation_fuel_and_co2_to_tier2_and_tier4(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    pred_fuel = sample_tier1_predictions.fuel_consumption_L.value
    pred_co2 = sample_tier1_predictions.co2_emissions_kg.value
    price = output.tier_2_baseline_metrics.fuel_price_usd_per_l

    # Tier 2 baseline cost must match pred_fuel * price
    assert output.tier_2_baseline_metrics.baseline_fuel_cost_usd == pytest.approx(pred_fuel * price)

    # Tier 4 net fuel + displaced fuel must equal pred_fuel
    assert output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L + \
           output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L == pytest.approx(pred_fuel)

    # Tier 4 net CO2 + displaced CO2 must equal pred_co2
    assert output.tier_4_engineering_scenario_estimates.net_assisted_co2_kg + \
           output.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg == pytest.approx(pred_co2)


def test_data_propagation_soh_to_tier3(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    soh = sample_tier1_predictions.battery_health.predicted_soh
    nom_cap = sample_tier1_predictions.battery_health.nominal_pack_capacity_kwh
    expected_eff = nom_cap * soh
    assert output.tier_3_clean_energy_feasibility.usable_battery_energy_kwh == pytest.approx(expected_eff * (0.90 - 0.20))


def test_single_fuel_price_consistency_across_all_tiers(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    price_t2 = output.tier_2_baseline_metrics.fuel_price_usd_per_l
    price_applied = output.applied_scenario_parameters.fuel_price_usd_per_l
    assert price_t2 == price_applied
    # Tier 4 net fuel cost must use the exact same price
    net_fuel = output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L
    assert output.tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd == pytest.approx(net_fuel * price_t2)


# ==============================================================================
# D. Critical Anti-Double-Counting Rule (Test 11)
# ==============================================================================
def test_critical_anti_double_counting_surplus_clean_energy(sample_voyage_metadata, sample_tier1_predictions):
    """
    When available clean energy exceeds demand, Tier 4 must displace ONLY
    clean_energy_utilized_kwh, NEVER total_clean_energy_available_kwh.
    """
    small_demand = 50.0  # Much smaller than available energy (~381 kWh)
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=small_demand,
        daily_ghi_kwh_per_m2=5.0,
    )
    avail = output.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh
    util = output.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh
    assert avail > util
    assert util == small_demand

    # Expected displaced fuel based strictly on small_demand
    expected_displaced_L = (small_demand * 0.220) / 0.850
    assert output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L == pytest.approx(expected_displaced_L)

    # Assert it did NOT displace using total available
    wrong_displaced_L = (avail * 0.220) / 0.850
    assert output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L != pytest.approx(wrong_displaced_L)


# ==============================================================================
# E. Scenario Overrides (Tests 12-16)
# ==============================================================================
def test_fuel_price_override(sample_voyage_metadata, sample_tier1_predictions):
    override_price = 1.75
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
        fuel_price_override_usd_per_l=override_price,
    )
    assert output.applied_scenario_parameters.fuel_price_usd_per_l == override_price
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == override_price
    assert output.tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd == pytest.approx(
        output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L * override_price
    )


def test_engineering_constants_overrides(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
        generator_sfoc_kg_per_kwh=0.240,
        fuel_density_kg_per_l=0.860,
        emission_factor_kgco2_per_kgfuel=3.150,
    )
    assert output.applied_scenario_parameters.generator_sfoc_kg_per_kwh == 0.240
    assert output.applied_scenario_parameters.fuel_density_kg_per_l == 0.860
    assert output.applied_scenario_parameters.emission_factor_kgco2_per_kgfuel == 3.150

    expected_fuel_disp = (180.0 * 0.240) / 0.860
    assert output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L == pytest.approx(expected_fuel_disp)


def test_soc_overrides(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=100.0,
        daily_ghi_kwh_per_m2=5.0,
        initial_soc=0.80,
        soc_reserve=0.30,
    )
    assert output.applied_scenario_parameters.initial_soc == 0.80
    assert output.applied_scenario_parameters.soc_reserve == 0.30
    eff = sample_tier1_predictions.battery_health.effective_pack_capacity_kwh
    assert output.tier_3_clean_energy_feasibility.usable_battery_energy_kwh == pytest.approx(eff * 0.50)


def test_solar_derate_override(sample_voyage_metadata, sample_tier1_predictions):
    output_low_derate = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=100.0,
        daily_ghi_kwh_per_m2=5.0,
        solar_derate_factor=0.50,
    )
    output_high_derate = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=100.0,
        daily_ghi_kwh_per_m2=5.0,
        solar_derate_factor=0.90,
    )
    assert output_high_derate.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh > \
           output_low_derate.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh


def test_route_and_month_climatology_lookup(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=150.0,
        route_id="Escravos-Lagos",
        month="January",
    )
    assert output.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh > 0.0


# ==============================================================================
# F. Edge Cases (Tests 17-21)
# ==============================================================================
def test_zero_auxiliary_demand(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=0.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    assert output.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh == 0.0
    assert output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L == 0.0
    assert output.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg == 0.0
    assert output.tier_4_engineering_scenario_estimates.delta_fuel_pct == 0.0
    assert output.tier_4_engineering_scenario_estimates.delta_cii_pct == 0.0


def test_zero_solar_insolation(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=100.0,
        daily_ghi_kwh_per_m2=0.0,
    )
    assert output.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh == 0.0
    assert output.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh == pytest.approx(
        output.tier_3_clean_energy_feasibility.usable_battery_energy_kwh
    )


def test_partial_feasibility_status(sample_voyage_metadata, sample_tier1_predictions):
    huge_demand = 10000.0
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=huge_demand,
        daily_ghi_kwh_per_m2=5.0,
    )
    assert output.tier_3_clean_energy_feasibility.feasibility_status == "PARTIAL"
    assert output.tier_3_clean_energy_feasibility.energy_balance_kwh < 0.0
    assert output.tier_3_clean_energy_feasibility.energy_deficit_kwh > 0.0


def test_boundary_initial_soc_equal_to_reserve(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=50.0,
        daily_ghi_kwh_per_m2=5.0,
        initial_soc=0.20,
        soc_reserve=0.20,
    )
    assert output.tier_3_clean_energy_feasibility.usable_battery_energy_kwh == 0.0


def test_boundary_full_soc(sample_voyage_metadata, sample_tier1_predictions):
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=50.0,
        daily_ghi_kwh_per_m2=5.0,
        initial_soc=1.0,
        soc_reserve=0.0,
    )
    eff = sample_tier1_predictions.battery_health.effective_pack_capacity_kwh
    assert output.tier_3_clean_energy_feasibility.usable_battery_energy_kwh == pytest.approx(eff)


# ==============================================================================
# G. Fail-Fast Error Propagation (Tests 22-25)
# ==============================================================================
def test_invalid_voyage_metadata_raises(sample_tier1_predictions):
    with pytest.raises((ValidationError, ValueError)):
        orchestrate_phase3_voyage(
            voyage_metadata={"ship_type": "Oil Service Boat", "distance_nm": -10.0, "voyage_duration_hours": 10.0, "deadweight_tonnes": 1000.0},
            tier1_predictions=sample_tier1_predictions,
            auxiliary_energy_demand_kwh=100.0,
            daily_ghi_kwh_per_m2=5.0,
        )


def test_invalid_tier1_predictions_raises(sample_voyage_metadata):
    with pytest.raises((ValidationError, ValueError)):
        orchestrate_phase3_voyage(
            voyage_metadata=sample_voyage_metadata,
            tier1_predictions={"fuel_consumption_L": {"value": -50.0}},
            auxiliary_energy_demand_kwh=100.0,
            daily_ghi_kwh_per_m2=5.0,
        )


def test_unknown_ship_type_raises(sample_tier1_predictions):
    v_meta = VoyageMetadata(
        ship_type="Cargo Airplane",
        distance_nm=100.0,
        voyage_duration_hours=5.0,
        deadweight_tonnes=1000.0,
    )
    with pytest.raises(ValueError) as exc:
        orchestrate_phase3_voyage(
            voyage_metadata=v_meta,
            tier1_predictions=sample_tier1_predictions,
            auxiliary_energy_demand_kwh=100.0,
            daily_ghi_kwh_per_m2=5.0,
        )
    assert "Unknown ship_type" in str(exc.value)


def test_missing_route_and_month_raises(sample_voyage_metadata, sample_tier1_predictions):
    with pytest.raises(ValueError):
        orchestrate_phase3_voyage(
            voyage_metadata=sample_voyage_metadata,
            tier1_predictions=sample_tier1_predictions,
            auxiliary_energy_demand_kwh=100.0,
            # daily_ghi_kwh_per_m2, route_id, and month all omitted
        )


# ==============================================================================
# H. Idempotency & Determinism (Test 26)
# ==============================================================================
def test_coordinator_deterministic_and_idempotent(sample_voyage_metadata, sample_tier1_predictions):
    output_1 = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    output_2 = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    assert output_1.model_dump() == output_2.model_dump()


# ==============================================================================
# I. Lower-Tier Function Delegation (Test 27)
# ==============================================================================
def test_no_formula_duplication_delegates_to_lower_tiers(sample_voyage_metadata, sample_tier1_predictions):
    """
    Verify using mock spies that the coordinator calls the existing tier calculation
    functions rather than recalculating them independently.
    """
    with patch("phase3_coordinator.calculate_tier2_baseline", wraps=calculate_tier2_baseline) as spy_t2, \
         patch("phase3_coordinator.calculate_tier3_clean_energy_feasibility", wraps=calculate_tier3_clean_energy_feasibility) as spy_t3, \
         patch("phase3_coordinator.calculate_tier4_engineering_scenario_estimates", wraps=calculate_tier4_engineering_scenario_estimates) as spy_t4:

        output = orchestrate_phase3_voyage(
            voyage_metadata=sample_voyage_metadata,
            tier1_predictions=sample_tier1_predictions,
            auxiliary_energy_demand_kwh=180.0,
            daily_ghi_kwh_per_m2=5.0,
        )

        assert spy_t2.call_count == 1
        assert spy_t3.call_count == 1
        assert spy_t4.call_count == 1
        assert isinstance(output, Phase3Output)


# ==============================================================================
# J. Root Contract Invariant Enforcement (Test 28)
# ==============================================================================
def test_root_contract_enforces_invariants(sample_voyage_metadata, sample_tier1_predictions):
    """
    Confirms that Phase3Output root validation catches any artificial mismatch.
    """
    output = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=sample_tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    payload = output.model_dump()

    # Artificially tamper fuel price to create cross-tier conflict
    payload["tier_2_baseline_metrics"]["fuel_price_usd_per_l"] = 0.50
    with pytest.raises(ValidationError) as exc:
        Phase3Output.model_validate(payload)
    assert "Conflicting fuel prices detected" in str(exc.value)

    # Artificially tamper displaced fuel to exceed predicted baseline fuel
    payload_bad_fuel = output.model_dump()
    payload_bad_fuel["tier_4_engineering_scenario_estimates"]["estimated_fuel_displaced_L"] = 50000.0
    with pytest.raises(ValidationError) as exc:
        Phase3Output.model_validate(payload_bad_fuel)
    assert "cannot exceed total predicted_fuel_consumption_L" in str(exc.value)


# ==============================================================================
# K. Weather Invariance Boundary Test
# ==============================================================================
def test_phase3e_coordinator_weather_invariance(sample_voyage_metadata, sample_tier1_predictions):
    """
    Verify that orchestrate_phase3_voyage retains weather strictly as descriptive
    Tier 1 metadata, and that varying weather values produces numerically identical
    Tier 2 baseline, Tier 3 feasibility, and Tier 4 displacement outputs.
    """
    # Create two identical Tier 1 prediction payloads with materially different weather
    t1_calm_dict = sample_tier1_predictions.model_dump()
    t1_calm_dict["weather"] = {
        "temperature_c": 26.5,
        "wind_speed_knots": 6.0,
        "significant_wave_height_m": 0.4,
    }
    t1_calm = Tier1Phase2Predictions.model_validate(t1_calm_dict)

    t1_storm_dict = sample_tier1_predictions.model_dump()
    t1_storm_dict["weather"] = {
        "temperature_c": 2.0,
        "wind_speed_knots": 48.0,
        "significant_wave_height_m": 9.2,
    }
    t1_storm = Tier1Phase2Predictions.model_validate(t1_storm_dict)

    out_calm = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=t1_calm,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )

    out_storm = orchestrate_phase3_voyage(
        voyage_metadata=sample_voyage_metadata,
        tier1_predictions=t1_storm,
        auxiliary_energy_demand_kwh=180.0,
        daily_ghi_kwh_per_m2=5.0,
    )

    # 1. Weather changes metadata in Tier 1
    assert out_calm.tier_1_phase2_predictions.weather.temperature_c != out_storm.tier_1_phase2_predictions.weather.temperature_c
    assert out_calm.tier_1_phase2_predictions.weather.wind_speed_knots != out_storm.tier_1_phase2_predictions.weather.wind_speed_knots
    assert out_calm.tier_1_phase2_predictions.weather.significant_wave_height_m != out_storm.tier_1_phase2_predictions.weather.significant_wave_height_m

    # 2. Tier 2 baseline metrics are strictly identical
    assert out_calm.tier_2_baseline_metrics.baseline_fuel_cost_usd == out_storm.tier_2_baseline_metrics.baseline_fuel_cost_usd
    assert out_calm.tier_2_baseline_metrics.baseline_operational_cii_gco2_per_dwt_nm == out_storm.tier_2_baseline_metrics.baseline_operational_cii_gco2_per_dwt_nm
    assert out_calm.tier_2_baseline_metrics.fuel_price_usd_per_l == out_storm.tier_2_baseline_metrics.fuel_price_usd_per_l

    # 3. Tier 3 feasibility metrics are strictly identical
    assert out_calm.tier_3_clean_energy_feasibility.usable_battery_energy_kwh == out_storm.tier_3_clean_energy_feasibility.usable_battery_energy_kwh
    assert out_calm.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh == out_storm.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh
    assert out_calm.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh == out_storm.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh
    assert out_calm.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh == out_storm.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh
    assert out_calm.tier_3_clean_energy_feasibility.energy_balance_kwh == out_storm.tier_3_clean_energy_feasibility.energy_balance_kwh
    assert out_calm.tier_3_clean_energy_feasibility.energy_deficit_kwh == out_storm.tier_3_clean_energy_feasibility.energy_deficit_kwh
    assert out_calm.tier_3_clean_energy_feasibility.feasibility_status == out_storm.tier_3_clean_energy_feasibility.feasibility_status

    # 4. Tier 4 displacement metrics are strictly identical
    assert out_calm.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L == out_storm.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L
    assert out_calm.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg == out_storm.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg
    assert out_calm.tier_4_engineering_scenario_estimates.net_assisted_fuel_L == out_storm.tier_4_engineering_scenario_estimates.net_assisted_fuel_L
    assert out_calm.tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd == out_storm.tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd
    assert out_calm.tier_4_engineering_scenario_estimates.net_assisted_co2_kg == out_storm.tier_4_engineering_scenario_estimates.net_assisted_co2_kg
    assert out_calm.tier_4_engineering_scenario_estimates.net_assisted_operational_cii_gco2_per_dwt_nm == out_storm.tier_4_engineering_scenario_estimates.net_assisted_operational_cii_gco2_per_dwt_nm
    assert out_calm.tier_4_engineering_scenario_estimates.delta_fuel_pct == out_storm.tier_4_engineering_scenario_estimates.delta_fuel_pct
    assert out_calm.tier_4_engineering_scenario_estimates.delta_cii_pct == out_storm.tier_4_engineering_scenario_estimates.delta_cii_pct

