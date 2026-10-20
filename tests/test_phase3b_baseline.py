"""
test_phase3b_baseline.py — Test Suite for Phase 3B Tier 2 Baseline Calculations
==============================================================================
Validates:
  - Fuel price resolution hierarchy (vessel defaults from ship_profiles.csv vs overrides)
  - Baseline fuel OPEX formula (fuel_L * price_USD_per_L)
  - Baseline operational CII formula (co2_kg * 1000 / (dwt_tonnes * distance_nm))
  - Boundary input validation (negative, zero, NaN, Inf)
  - Contract compatibility with Phase3Output and Tier2BaselineMetrics
  - Strict cross-tier fuel price consistency
"""

import math
import pytest
from pydantic import ValidationError

from phase3_contracts import (
    Phase3Output,
    Tier2BaselineMetrics,
    FROZEN_MODEL_HASHES,
)
from phase3_baseline import (
    resolve_fuel_price_usd_per_l,
    calculate_baseline_fuel_cost,
    calculate_baseline_operational_cii,
    calculate_tier2_baseline,
)


# ==============================================================================
# Test 1 — Normal fuel cost
# ==============================================================================
def test_normal_fuel_cost():
    cost = calculate_baseline_fuel_cost(fuel_consumption_L=1000.0, fuel_price_usd_per_l=1.15)
    assert cost == pytest.approx(1150.0)


# ==============================================================================
# Test 2 — Zero fuel
# ==============================================================================
def test_zero_fuel():
    cost = calculate_baseline_fuel_cost(fuel_consumption_L=0.0, fuel_price_usd_per_l=1.15)
    assert cost == 0.0


# ==============================================================================
# Test 3 — Fuel price override
# ==============================================================================
def test_fuel_price_override():
    # Oil Service Boat default is 1.15; provide explicit override of 1.45
    default_price = resolve_fuel_price_usd_per_l("Oil Service Boat")
    assert default_price == 1.15

    override_price = 1.45
    resolved = resolve_fuel_price_usd_per_l("Oil Service Boat", override_price=override_price)
    assert resolved == override_price
    assert resolved != default_price

    cost = calculate_baseline_fuel_cost(1000.0, resolved)
    assert cost == pytest.approx(1450.0)


# ==============================================================================
# Test 4 — Invalid negative fuel
# ==============================================================================
def test_invalid_negative_fuel():
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_baseline_fuel_cost(fuel_consumption_L=-50.0, fuel_price_usd_per_l=1.15)


# ==============================================================================
# Test 5 — Invalid negative fuel price
# ==============================================================================
def test_invalid_negative_fuel_price():
    with pytest.raises(ValueError, match="strictly positive"):
        calculate_baseline_fuel_cost(fuel_consumption_L=1000.0, fuel_price_usd_per_l=-1.15)

    with pytest.raises(ValueError, match="strictly positive"):
        calculate_baseline_fuel_cost(fuel_consumption_L=1000.0, fuel_price_usd_per_l=0.0)

    with pytest.raises(ValueError, match="strictly positive"):
        resolve_fuel_price_usd_per_l("Oil Service Boat", override_price=-0.5)

    with pytest.raises(ValueError, match="strictly positive"):
        resolve_fuel_price_usd_per_l("Oil Service Boat", override_price=0.0)


# ==============================================================================
# Test 6 — Normal operational CII
# ==============================================================================
def test_normal_operational_cii():
    # 10,000 kg CO2, 50,000 tonnes DWT, 1000 nm
    # Formula: 10,000 * 1000 / (50,000 * 1000) = 0.2 gCO2 / (DWT * nm)
    cii = calculate_baseline_operational_cii(
        co2_emissions_kg=10000.0,
        deadweight_tonnes=50000.0,
        distance_nm=1000.0,
    )
    assert cii == pytest.approx(0.2)


# ==============================================================================
# Test 7 — Zero CO2
# ==============================================================================
def test_zero_co2():
    cii = calculate_baseline_operational_cii(
        co2_emissions_kg=0.0,
        deadweight_tonnes=50000.0,
        distance_nm=1000.0,
    )
    assert cii == 0.0


# ==============================================================================
# Test 8 — Zero DWT
# ==============================================================================
def test_zero_dwt():
    with pytest.raises(ValueError, match="deadweight_tonnes must be strictly positive"):
        calculate_baseline_operational_cii(
            co2_emissions_kg=10000.0,
            deadweight_tonnes=0.0,
            distance_nm=1000.0,
        )

    with pytest.raises(ValueError, match="deadweight_tonnes must be strictly positive"):
        calculate_baseline_operational_cii(
            co2_emissions_kg=10000.0,
            deadweight_tonnes=-100.0,
            distance_nm=1000.0,
        )


# ==============================================================================
# Test 9 — Zero distance
# ==============================================================================
def test_zero_distance():
    with pytest.raises(ValueError, match="distance_nm must be strictly positive"):
        calculate_baseline_operational_cii(
            co2_emissions_kg=10000.0,
            deadweight_tonnes=50000.0,
            distance_nm=0.0,
        )

    with pytest.raises(ValueError, match="distance_nm must be strictly positive"):
        calculate_baseline_operational_cii(
            co2_emissions_kg=10000.0,
            deadweight_tonnes=50000.0,
            distance_nm=-50.0,
        )


# ==============================================================================
# Test 10 — Negative CO2
# ==============================================================================
def test_negative_co2():
    with pytest.raises(ValueError, match="co2_emissions_kg cannot be negative"):
        calculate_baseline_operational_cii(
            co2_emissions_kg=-100.0,
            deadweight_tonnes=50000.0,
            distance_nm=1000.0,
        )


# ==============================================================================
# Test 11 — Non-finite inputs (NaN, +Inf, -Inf)
# ==============================================================================
def test_non_finite_inputs():
    non_finites = [float("nan"), float("inf"), float("-inf")]

    # Fuel cost non-finites
    for nf in non_finites:
        with pytest.raises(ValueError, match="must be finite"):
            calculate_baseline_fuel_cost(fuel_consumption_L=nf, fuel_price_usd_per_l=1.15)
        with pytest.raises(ValueError, match="must be finite"):
            calculate_baseline_fuel_cost(fuel_consumption_L=1000.0, fuel_price_usd_per_l=nf)
        with pytest.raises(ValueError, match="must be finite"):
            resolve_fuel_price_usd_per_l("Oil Service Boat", override_price=nf)

    # CII non-finites
    for nf in non_finites:
        with pytest.raises(ValueError, match="must be finite"):
            calculate_baseline_operational_cii(co2_emissions_kg=nf, deadweight_tonnes=1000.0, distance_nm=100.0)
        with pytest.raises(ValueError, match="must be finite"):
            calculate_baseline_operational_cii(co2_emissions_kg=100.0, deadweight_tonnes=nf, distance_nm=100.0)
        with pytest.raises(ValueError, match="must be finite"):
            calculate_baseline_operational_cii(co2_emissions_kg=100.0, deadweight_tonnes=1000.0, distance_nm=nf)


# ==============================================================================
# Test 12 — Tier 2 contract compatibility
# ==============================================================================
def test_tier2_contract_compatibility():
    # Calculate Tier 2 baseline
    tier2 = calculate_tier2_baseline(
        ship_type="Oil Service Boat",
        predicted_fuel_L=4120.5,
        predicted_co2_kg=10906.9,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    assert isinstance(tier2, Tier2BaselineMetrics)
    assert tier2.fuel_price_usd_per_l == 1.15
    assert tier2.baseline_fuel_cost_usd == pytest.approx(4120.5 * 1.15)
    assert tier2.baseline_operational_cii_gco2_per_dwt_nm == pytest.approx(10906.9 * 1000 / (1800.0 * 250.0))

    # Construct complete Phase 3 output with the calculated Tier 2 object
    full_payload = {
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
        "tier_2_baseline_metrics": tier2.model_dump(),
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
            "disclaimer": "Scenario estimate based on assumed SFOC.",
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
            "fuel_price_usd_per_l": tier2.fuel_price_usd_per_l,
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

    output = Phase3Output.model_validate(full_payload)
    assert output.tier_2_baseline_metrics.baseline_fuel_cost_usd == pytest.approx(4738.575)


# ==============================================================================
# Test 13 — Fuel-price cross-tier consistency
# ==============================================================================
def test_fuel_price_cross_tier_consistency():
    tier2 = calculate_tier2_baseline(
        ship_type="Oil Service Boat",
        predicted_fuel_L=1000.0,
        predicted_co2_kg=2750.0,
        deadweight_tonnes=1800.0,
        distance_nm=100.0,
        fuel_price_override_usd_per_l=1.35,
    )
    assert tier2.fuel_price_usd_per_l == 1.35

    # Check that matching scenario parameters pass
    valid_payload = {
        "voyage_metadata": {
            "ship_type": "Oil Service Boat",
            "distance_nm": 100.0,
            "voyage_duration_hours": 10.0,
            "deadweight_tonnes": 1800.0,
        },
        "tier_1_phase2_predictions": {
            "weather": {"temperature_c": 20.0, "wind_speed_knots": 10.0, "significant_wave_height_m": 1.0},
            "fuel_consumption_L": {"value": 1000.0, "unit": "Liters", "evidence_level": "B - STRONGLY INFERRED", "scope": "Total voyage fuel consumption"},
            "co2_emissions_kg": {"value": 2750.0, "unit": "kg"},
            "battery_health": {"predicted_soh": 0.8, "nominal_pack_capacity_kwh": 600.0, "effective_pack_capacity_kwh": 480.0},
            "battery_operation": {"predicted_soc_end_of_voyage": 0.6, "soc_formulation": "Degradation-adjusted pack SOC"},
        },
        "tier_2_baseline_metrics": tier2.model_dump(),
        "tier_3_clean_energy_feasibility": {
            "auxiliary_energy_demand_kwh": 100.0,
            "usable_battery_energy_kwh": 200.0,
            "estimated_solar_energy_kwh": 20.0,
            "total_clean_energy_available_kwh": 220.0,
            "clean_energy_utilized_kwh": 100.0,
            "energy_balance_kwh": 120.0,
            "energy_deficit_kwh": 0.0,
            "feasibility_status": "FEASIBLE",
        },
        "tier_4_engineering_scenario_estimates": {
            "status": "ENGINEERING SCENARIO ESTIMATE",
            "disclaimer": "Scenario estimate",
            "estimated_fuel_displaced_L": 25.0,
            "estimated_co2_displaced_kg": 66.0,
            "net_assisted_fuel_L": 975.0,
            "net_assisted_co2_kg": 2684.0,
            "net_assisted_fuel_cost_usd": 975.0 * 1.35,
            "net_assisted_operational_cii_gco2_per_dwt_nm": 14.91,
            "delta_fuel_pct": -2.5,
            "delta_cii_pct": -2.4,
        },
        "applied_scenario_parameters": {
            "fuel_price_usd_per_l": 1.35,  # Matches tier2.fuel_price_usd_per_l
            "initial_soc": 0.90,
            "auxiliary_energy_demand_kwh": 100.0,
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
    output = Phase3Output.model_validate(valid_payload)
    assert output.tier_2_baseline_metrics.fuel_price_usd_per_l == 1.35

    # Check that mismatching scenario price is rejected by Phase 3A.1 validator
    invalid_payload = dict(valid_payload)
    invalid_payload["applied_scenario_parameters"] = dict(valid_payload["applied_scenario_parameters"])
    invalid_payload["applied_scenario_parameters"]["fuel_price_usd_per_l"] = 1.10  # Conflict!
    with pytest.raises(ValidationError, match="Conflicting fuel prices detected"):
        Phase3Output.model_validate(invalid_payload)


# ==============================================================================
# Test 14 — Vessel default price resolution
# ==============================================================================
def test_vessel_default_price_resolution():
    expected_defaults = {
        "Oil Service Boat": 1.15,
        "Fishing Trawler": 1.10,
        "Surfer Boat": 1.20,
        "Tanker Ship": 0.95,
        "Tanker": 0.95,
    }
    for ship_type, expected_price in expected_defaults.items():
        resolved = resolve_fuel_price_usd_per_l(ship_type)
        assert resolved == pytest.approx(expected_price), f"Failed for {ship_type}"

    with pytest.raises(ValueError, match="Unknown ship_type"):
        resolve_fuel_price_usd_per_l("Unknown Vessel")


# ==============================================================================
# Test 15 — End-to-end Tier 2 calculation
# ==============================================================================
def test_end_to_end_tier2_calculation():
    # Test for Fishing Trawler with default price 1.10
    # fuel = 2000.0 L, co2 = 5500.0 kg, dwt = 350.0 tonnes, distance = 150.0 nm
    res = calculate_tier2_baseline(
        ship_type="Fishing Trawler",
        predicted_fuel_L=2000.0,
        predicted_co2_kg=5500.0,
        deadweight_tonnes=350.0,
        distance_nm=150.0,
    )
    assert res.fuel_price_usd_per_l == 1.10
    assert res.baseline_fuel_cost_usd == pytest.approx(2000.0 * 1.10)
    assert res.baseline_operational_cii_gco2_per_dwt_nm == pytest.approx(5500.0 * 1000.0 / (350.0 * 150.0))

    # Test with override price 1.25
    res_override = calculate_tier2_baseline(
        ship_type="Fishing Trawler",
        predicted_fuel_L=2000.0,
        predicted_co2_kg=5500.0,
        deadweight_tonnes=350.0,
        distance_nm=150.0,
        fuel_price_override_usd_per_l=1.25,
    )
    assert res_override.fuel_price_usd_per_l == 1.25
    assert res_override.baseline_fuel_cost_usd == pytest.approx(2000.0 * 1.25)
    assert res_override.baseline_operational_cii_gco2_per_dwt_nm == pytest.approx(5500.0 * 1000.0 / (350.0 * 150.0))
