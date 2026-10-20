"""
test_phase3_contracts.py — Test Suite for Phase 3A Contracts & Pydantic Schemas
==============================================================================
Validates the frozen four-tier contract architecture, mathematical boundaries,
provenance metadata, single-source fuel price invariant, and clean separation
of Phase 2 predictions vs Phase 3 scenario inputs (including initial_soc).
"""

import pytest
from pydantic import ValidationError

from phase3_contracts import (
    VoyageMetadata,
    WeatherPrediction,
    FuelPrediction,
    CO2Prediction,
    BatteryHealthPrediction,
    BatteryOperationPrediction,
    Tier1Phase2Predictions,
    Tier2BaselineMetrics,
    Tier3CleanEnergyFeasibility,
    Tier4EngineeringScenarioEstimates,
    AppliedScenarioParameters,
    AuditMetadata,
    Phase3Output,
    FROZEN_MODEL_HASHES,
    SOURCED_FUEL_PRICES_USD_PER_L,
    get_sourced_fuel_price,
)


def get_valid_payload():
    """Helper returning a fully valid four-tier Phase3Output payload dict."""
    return {
        "voyage_metadata": {
            "ship_type": "Oil Service Boat",
            "distance_nm": 250.0,
            "voyage_duration_hours": 18.5,
            "deadweight_tonnes": 1800.0,
        },
        "tier_1_phase2_predictions": {
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
        },
        "tier_2_baseline_metrics": {
            "baseline_fuel_cost_usd": 4738.575,
            "baseline_operational_cii_gco2_per_dwt_nm": 24.2376,
            "fuel_price_usd_per_l": 1.15,
        },
        "tier_3_clean_energy_feasibility": {
            "auxiliary_energy_demand_kwh": 180.0,
            "usable_battery_energy_kwh": 339.7883,
            "estimated_solar_energy_kwh": 42.15,
            "total_clean_energy_available_kwh": 381.9383,
            "clean_energy_utilized_kwh": 180.0,
            "energy_balance_kwh": 201.9383,
            "energy_deficit_kwh": 0.0,
            "feasibility_status": "FEASIBLE",
        },
        "tier_4_engineering_scenario_estimates": {
            "status": "ENGINEERING SCENARIO ESTIMATE",
            "disclaimer": (
                "Auxiliary fuel and CO2 displacement values are engineering scenario estimates "
                "based on assumed generator SFOC and fuel density. They are NOT derived from a "
                "validated machine-learning propulsion-vs-auxiliary decomposition."
            ),
            "estimated_fuel_displaced_L": 46.5882,
            "estimated_co2_displaced_kg": 123.3155,
            "net_assisted_fuel_L": 4073.9118,
            "net_assisted_co2_kg": 10783.5845,
            "net_assisted_fuel_cost_usd": 4684.9986,
            "net_assisted_operational_cii_gco2_per_dwt_nm": 23.9635,
            "delta_fuel_pct": -1.1306,
            "delta_cii_pct": -1.1306,
        },
        "applied_scenario_parameters": {
            "fuel_price_usd_per_l": 1.15,
            "initial_soc": 0.90,
            "auxiliary_energy_demand_kwh": 180.0,
            "soc_reserve": 0.20,
            "generator_sfoc_kg_per_kwh": 0.220,
            "fuel_density_kg_per_l": 0.850,
            "emission_factor_kgco2_per_kgfuel": 3.114,
            "solar_derate_factor": 0.85,
        },
        "audit_metadata": {
            "phase2_models_frozen": True,
            "data_raw_modified": False,
            "scenario_assumptions_applied": True,
            "model_hashes": dict(FROZEN_MODEL_HASHES),
        },
    }


# ==============================================================================
# Test 1 — Valid complete Phase 3 output
# ==============================================================================
def test_valid_complete_phase3_output():
    payload = get_valid_payload()
    output = Phase3Output.model_validate(payload)
    assert output.voyage_metadata.ship_type == "Oil Service Boat"
    assert output.tier_1_phase2_predictions.fuel_consumption_L.value == 4120.5
    assert output.tier_1_phase2_predictions.battery_operation.predicted_soc_end_of_voyage == 0.5292
    assert output.tier_2_baseline_metrics.baseline_fuel_cost_usd == pytest.approx(4738.575)
    assert output.tier_3_clean_energy_feasibility.feasibility_status == "FEASIBLE"
    assert output.tier_4_engineering_scenario_estimates.status == "ENGINEERING SCENARIO ESTIMATE"
    assert output.audit_metadata.phase2_models_frozen is True
    assert output.audit_metadata.data_raw_modified is False


# ==============================================================================
# Test 2 — Invalid negative distance
# ==============================================================================
def test_invalid_negative_distance():
    payload = get_valid_payload()
    payload["voyage_metadata"]["distance_nm"] = -10.0
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "distance_nm" in str(exc_info.value)


# ==============================================================================
# Test 3 — Invalid SOH > 1
# ==============================================================================
def test_invalid_soh_greater_than_one():
    payload = get_valid_payload()
    payload["tier_1_phase2_predictions"]["battery_health"]["predicted_soh"] = 1.05
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "predicted_soh" in str(exc_info.value)

    # Also test SOH < 0
    payload["tier_1_phase2_predictions"]["battery_health"]["predicted_soh"] = -0.05
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "predicted_soh" in str(exc_info.value)


# ==============================================================================
# Test 4 — Invalid SOC > 1
# ==============================================================================
def test_invalid_soc_greater_than_one():
    payload = get_valid_payload()
    payload["tier_1_phase2_predictions"]["battery_operation"]["predicted_soc_end_of_voyage"] = 1.25
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "predicted_soc_end_of_voyage" in str(exc_info.value)


# ==============================================================================
# Test 5 — Invalid reserve > 1
# ==============================================================================
def test_invalid_reserve_greater_than_one():
    payload = get_valid_payload()
    payload["applied_scenario_parameters"]["soc_reserve"] = 1.50
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "soc_reserve" in str(exc_info.value)

    # Also test negative reserve
    payload["applied_scenario_parameters"]["soc_reserve"] = -0.10
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "soc_reserve" in str(exc_info.value)


# ==============================================================================
# Test 6 — Invalid negative energy
# ==============================================================================
def test_invalid_negative_energy():
    payload = get_valid_payload()
    payload["tier_3_clean_energy_feasibility"]["usable_battery_energy_kwh"] = -5.0
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "usable_battery_energy_kwh" in str(exc_info.value)

    payload = get_valid_payload()
    payload["tier_3_clean_energy_feasibility"]["auxiliary_energy_demand_kwh"] = -50.0
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "auxiliary_energy_demand_kwh" in str(exc_info.value)


# ==============================================================================
# Test 7 — Invalid zero/negative SFOC
# ==============================================================================
def test_invalid_zero_or_negative_sfoc():
    payload = get_valid_payload()
    payload["applied_scenario_parameters"]["generator_sfoc_kg_per_kwh"] = 0.0
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "generator_sfoc_kg_per_kwh" in str(exc_info.value)

    payload["applied_scenario_parameters"]["generator_sfoc_kg_per_kwh"] = -0.220
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "generator_sfoc_kg_per_kwh" in str(exc_info.value)


# ==============================================================================
# Test 8 — Invalid zero/negative fuel density
# ==============================================================================
def test_invalid_zero_or_negative_fuel_density():
    payload = get_valid_payload()
    payload["applied_scenario_parameters"]["fuel_density_kg_per_l"] = 0.0
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "fuel_density_kg_per_l" in str(exc_info.value)

    payload["applied_scenario_parameters"]["fuel_density_kg_per_l"] = -0.85
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "fuel_density_kg_per_l" in str(exc_info.value)


# ==============================================================================
# Test 9 — Invalid solar derate > 1
# ==============================================================================
def test_invalid_solar_derate_greater_than_one():
    payload = get_valid_payload()
    payload["applied_scenario_parameters"]["solar_derate_factor"] = 1.15
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "solar_derate_factor" in str(exc_info.value)

    payload["applied_scenario_parameters"]["solar_derate_factor"] = -0.1
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "solar_derate_factor" in str(exc_info.value)


# ==============================================================================
# Test 10 — Tier 4 status must identify an engineering scenario estimate
# ==============================================================================
def test_tier4_status_must_identify_engineering_scenario_estimate():
    payload = get_valid_payload()
    payload["tier_4_engineering_scenario_estimates"]["status"] = "ML PREDICTION"
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "status" in str(exc_info.value)

    tier4 = Tier4EngineeringScenarioEstimates(
        estimated_fuel_displaced_L=10.0,
        estimated_co2_displaced_kg=30.0,
        net_assisted_fuel_L=90.0,
        net_assisted_co2_kg=270.0,
        net_assisted_fuel_cost_usd=100.0,
        net_assisted_operational_cii_gco2_per_dwt_nm=12.0,
        delta_fuel_pct=-10.0,
        delta_cii_pct=-10.0,
    )
    assert tier4.status == "ENGINEERING SCENARIO ESTIMATE"
    assert "not derived from a validated machine-learning" in tier4.disclaimer.lower()


# ==============================================================================
# Test 11 — Scenario displacement cannot exceed total predicted fuel
# ==============================================================================
def test_scenario_displacement_cannot_exceed_total_predicted_fuel():
    payload = get_valid_payload()
    payload["tier_4_engineering_scenario_estimates"]["estimated_fuel_displaced_L"] = 5000.0
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "cannot exceed total predicted_fuel_consumption_L" in str(exc_info.value)


# ==============================================================================
# Test 12 — Scenario CO2 displacement cannot exceed predicted baseline CO2
# ==============================================================================
def test_scenario_co2_displacement_cannot_exceed_predicted_baseline_co2():
    payload = get_valid_payload()
    payload["tier_4_engineering_scenario_estimates"]["estimated_co2_displaced_kg"] = 12000.0
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "cannot exceed baseline predicted_CO2_kg" in str(exc_info.value)


# ==============================================================================
# Test 13 — Sourced fuel prices & lookup
# ==============================================================================
def test_sourced_fuel_prices():
    assert get_sourced_fuel_price("Oil Service Boat") == 1.15
    assert get_sourced_fuel_price("Fishing Trawler") == 1.10
    assert get_sourced_fuel_price("Surfer Boat") == 1.20
    assert get_sourced_fuel_price("Tanker Ship") == 0.95
    assert get_sourced_fuel_price("Tanker") == 0.95
    with pytest.raises(ValueError):
        get_sourced_fuel_price("Submarine")


# ==============================================================================
# Test 14 — Feasibility status allowed values
# ==============================================================================
def test_feasibility_status_partial_allowed():
    payload = get_valid_payload()
    payload["tier_3_clean_energy_feasibility"]["feasibility_status"] = "PARTIAL"
    payload["tier_3_clean_energy_feasibility"]["energy_balance_kwh"] = -50.0
    payload["tier_3_clean_energy_feasibility"]["energy_deficit_kwh"] = 50.0
    output = Phase3Output.model_validate(payload)
    assert output.tier_3_clean_energy_feasibility.feasibility_status == "PARTIAL"

    payload["tier_3_clean_energy_feasibility"]["feasibility_status"] = "UNSAFE"
    with pytest.raises(ValidationError):
        Phase3Output.model_validate(payload)


# ==============================================================================
# Phase 3A.1 Targeted Tests (Tests 15-18)
# ==============================================================================
def test_initial_soc_is_scenario_parameter_not_tier1_prediction():
    """Confirms initial_soc lives in applied_scenario_parameters and is not in BatteryOperationPrediction."""
    payload = get_valid_payload()
    # Confirm initial_soc is in applied_scenario_parameters
    assert "initial_soc" in payload["applied_scenario_parameters"]
    assert "initial_soc" not in payload["tier_1_phase2_predictions"]["battery_operation"]

    output = Phase3Output.model_validate(payload)
    assert output.applied_scenario_parameters.initial_soc == 0.90
    assert hasattr(output.tier_1_phase2_predictions.battery_operation, "predicted_soc_end_of_voyage")
    assert not hasattr(output.tier_1_phase2_predictions.battery_operation, "initial_soc")

    # Invalid initial_soc in scenario parameters (> 1)
    payload_bad = get_valid_payload()
    payload_bad["applied_scenario_parameters"]["initial_soc"] = 1.10
    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload_bad)
    assert "initial_soc" in str(exc_info.value)


def test_battery_operation_prediction_contains_only_authoritative_soc():
    """Confirms BatteryOperationPrediction only requires predicted_soc_end_of_voyage."""
    b_op = BatteryOperationPrediction(predicted_soc_end_of_voyage=0.5292)
    assert b_op.predicted_soc_end_of_voyage == 0.5292
    assert b_op.soc_formulation == "Degradation-adjusted pack SOC"


def test_fuel_price_consistency_enforced():
    """Confirms that Tier 2 baseline and applied scenario parameters must use the SAME resolved price."""
    payload = get_valid_payload()
    payload["applied_scenario_parameters"]["fuel_price_usd_per_l"] = 1.15
    payload["tier_2_baseline_metrics"]["fuel_price_usd_per_l"] = 0.90  # Conflicting!

    with pytest.raises(ValidationError) as exc_info:
        Phase3Output.model_validate(payload)
    assert "Conflicting fuel prices detected" in str(exc_info.value)


def test_fuel_price_override_without_conflict():
    """Confirms that overriding fuel price is fully supported when both match the resolved price."""
    payload = get_valid_payload()
    override_price = 1.45  # Custom market price scenario
    payload["applied_scenario_parameters"]["fuel_price_usd_per_l"] = override_price
    payload["tier_2_baseline_metrics"]["fuel_price_usd_per_l"] = override_price
    payload["tier_2_baseline_metrics"]["baseline_fuel_cost_usd"] = 4120.5 * override_price

    output = Phase3Output.model_validate(payload)
    assert output.applied_scenario_parameters.fuel_price_usd_per_l == 1.45
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == 1.45
    assert output.tier_2_baseline_metrics.baseline_fuel_cost_usd == pytest.approx(4120.5 * 1.45)
