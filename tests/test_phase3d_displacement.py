"""
test_phase3d_displacement.py — Test Suite for Phase 3D Tier 4 Displacement Calculations
======================================================================================
Validates:
  - Auxiliary generator fuel displacement (SFOC and fuel density equivalence)
  - CO2 emissions displacement (carbon emission factor)
  - Net assisted fuel, CO2, fuel cost, and operational CII
  - Delta percentage reductions relative to unassisted baseline
  - Boundary input validation (zero, negative, out-of-range, non-finite values)
  - Zero-baseline edge cases (zero fuel, zero CO2)
  - Conservation invariants (non-negative displacement, upper-bound capping)
  - Pydantic contract compliance with Tier4EngineeringScenarioEstimates and Phase3Output
  - End-to-end deterministic trace with Phase 2 predictions and Tier 3 clean energy
"""

import math
import pytest
from pydantic import ValidationError

from phase3_contracts import (
    Phase3Output,
    Tier4EngineeringScenarioEstimates,
    Tier3CleanEnergyFeasibility,
    FROZEN_MODEL_HASHES,
)
from phase3_displacement import (
    calculate_fuel_displacement,
    calculate_co2_displacement,
    calculate_net_assisted_metrics,
    calculate_tier4_engineering_scenario_estimates,
)


# ==============================================================================
# Tests 1-8 — Normal Calculations & Net Assisted Metrics
# ==============================================================================
def test_normal_fuel_displacement():
    # 180 kWh * 0.220 kg/kWh / 0.850 kg/L = 46.588235 L
    disp_fuel = calculate_fuel_displacement(
        clean_energy_utilized_kwh=180.0,
        generator_sfoc_kg_per_kwh=0.220,
        fuel_density_kg_per_l=0.850,
        predicted_fuel_consumption_L=4120.5,
    )
    expected = (180.0 * 0.220) / 0.850
    assert disp_fuel == pytest.approx(expected)
    assert disp_fuel == pytest.approx(46.58823529)


def test_normal_co2_displacement():
    # 46.588235 L * 0.850 kg/L * 3.114 kg CO2/kg fuel = 123.3144 kg CO2
    disp_co2 = calculate_co2_displacement(
        estimated_fuel_displaced_L=46.58823529,
        fuel_density_kg_per_l=0.850,
        emission_factor_kgco2_per_kgfuel=3.114,
        predicted_CO2_kg=10906.9,
    )
    expected = 46.58823529 * 0.850 * 3.114
    assert disp_co2 == pytest.approx(expected)
    assert disp_co2 == pytest.approx(123.3144)


def test_net_assisted_fuel():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        estimated_fuel_displaced_L=100.0,
        estimated_co2_displaced_kg=260.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    assert metrics["net_assisted_fuel_L"] == pytest.approx(3900.0)


def test_net_assisted_co2():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        estimated_fuel_displaced_L=100.0,
        estimated_co2_displaced_kg=260.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    assert metrics["net_assisted_co2_kg"] == pytest.approx(9740.0)


def test_net_assisted_fuel_cost():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        estimated_fuel_displaced_L=100.0,
        estimated_co2_displaced_kg=260.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    assert metrics["net_assisted_fuel_cost_usd"] == pytest.approx(3900.0 * 1.15)


def test_net_assisted_cii():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        estimated_fuel_displaced_L=100.0,
        estimated_co2_displaced_kg=260.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    expected_cii = (9740.0 * 1000.0) / (1800.0 * 250.0)
    assert metrics["net_assisted_operational_cii_gco2_per_dwt_nm"] == pytest.approx(expected_cii)


def test_fuel_percentage_change():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        estimated_fuel_displaced_L=100.0,
        estimated_co2_displaced_kg=260.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    # (3900 - 4000) / 4000 * 100 = -2.5%
    assert metrics["delta_fuel_pct"] == pytest.approx(-2.5)


def test_cii_percentage_change():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        estimated_fuel_displaced_L=100.0,
        estimated_co2_displaced_kg=260.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    # (9740 - 10000) / 10000 * 100 = -2.6%
    assert metrics["delta_cii_pct"] == pytest.approx(-2.6)


# ==============================================================================
# Tests 9-14 — Boundary & Capping Tests
# ==============================================================================
def test_zero_clean_energy():
    tier4 = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        clean_energy_utilized_kwh=0.0,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
    )
    assert tier4.estimated_fuel_displaced_L == 0.0
    assert tier4.estimated_co2_displaced_kg == 0.0
    assert tier4.net_assisted_fuel_L == 4000.0
    assert tier4.net_assisted_co2_kg == 10000.0
    assert tier4.delta_fuel_pct == 0.0
    assert tier4.delta_cii_pct == 0.0


def test_zero_auxiliary_demand_yields_zero_displacement():
    # If auxiliary demand is 0, utilized clean energy from Tier 3 is 0
    tier4 = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=4000.0,
        predicted_CO2_kg=10000.0,
        clean_energy_utilized_kwh=0.0,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
    )
    assert tier4.estimated_fuel_displaced_L == 0.0
    assert tier4.delta_fuel_pct == 0.0


def test_clean_energy_equals_auxiliary_demand():
    disp_fuel = calculate_fuel_displacement(
        clean_energy_utilized_kwh=100.0,
        generator_sfoc_kg_per_kwh=0.220,
        fuel_density_kg_per_l=0.850,
        predicted_fuel_consumption_L=2000.0,
    )
    assert disp_fuel == pytest.approx((100.0 * 0.220) / 0.850)


def test_clean_energy_exceeds_demand_consumed_safely():
    # Tier 4 consumes clean_energy_utilized_kwh which is already capped at demand in Tier 3
    # If a Tier 3 object is passed directly, verify it extracts clean_energy_utilized_kwh
    t3 = Tier3CleanEnergyFeasibility(
        auxiliary_energy_demand_kwh=100.0,
        usable_battery_energy_kwh=300.0,
        estimated_solar_energy_kwh=50.0,
        total_clean_energy_available_kwh=350.0,
        clean_energy_utilized_kwh=100.0,  # Capped at demand
        energy_balance_kwh=250.0,
        energy_deficit_kwh=0.0,
        feasibility_status="FEASIBLE",
    )
    tier4 = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=3000.0,
        predicted_CO2_kg=8000.0,
        clean_energy_utilized_kwh=t3,  # Pass Tier 3 object directly
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
    )
    expected_fuel = (100.0 * 0.220) / 0.850
    assert tier4.estimated_fuel_displaced_L == pytest.approx(expected_fuel)


def test_fuel_displacement_cap():
    # Suppose raw displaced fuel is 1500 L, but predicted baseline fuel is only 1000 L
    disp_fuel = calculate_fuel_displacement(
        clean_energy_utilized_kwh=10000.0,  # Enormous clean energy
        generator_sfoc_kg_per_kwh=0.220,
        fuel_density_kg_per_l=0.850,
        predicted_fuel_consumption_L=1000.0,
    )
    assert disp_fuel == 1000.0  # Capped at predicted fuel


def test_co2_displacement_cap():
    disp_co2 = calculate_co2_displacement(
        estimated_fuel_displaced_L=1000.0,
        fuel_density_kg_per_l=0.850,
        emission_factor_kgco2_per_kgfuel=3.114,
        predicted_CO2_kg=2000.0,  # Cap at 2000 kg
    )
    # Raw is 1000 * 0.850 * 3.114 = 2646.9 kg -> should cap at 2000.0
    assert disp_co2 == 2000.0


# ==============================================================================
# Tests 15-22 — Input Validation & Error Rejections
# ==============================================================================
def test_invalid_sfoc():
    for bad in [0.0, -0.22, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_fuel_displacement(100.0, bad, 0.850, 4000.0)


def test_invalid_fuel_density():
    for bad in [0.0, -0.85, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_fuel_displacement(100.0, 0.220, bad, 4000.0)

        with pytest.raises(ValueError):
            calculate_co2_displacement(50.0, bad, 3.114, 10000.0)


def test_invalid_emission_factor():
    for bad in [0.0, -3.114, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_co2_displacement(50.0, 0.850, bad, 10000.0)


def test_invalid_fuel_price():
    for bad in [-1.0, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_net_assisted_metrics(4000.0, 10000.0, 100.0, 260.0, bad, 1800.0, 250.0)


def test_invalid_dwt():
    for bad in [0.0, -100.0, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_net_assisted_metrics(4000.0, 10000.0, 100.0, 260.0, 1.15, bad, 250.0)


def test_invalid_voyage_distance():
    for bad in [0.0, -50.0, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_net_assisted_metrics(4000.0, 10000.0, 100.0, 260.0, 1.15, 1800.0, bad)


def test_nan_input_rejection():
    with pytest.raises(ValueError):
        calculate_fuel_displacement(float("nan"), 0.220, 0.850, 4000.0)
    with pytest.raises(ValueError):
        calculate_fuel_displacement(100.0, 0.220, 0.850, float("nan"))


def test_infinite_input_rejection():
    with pytest.raises(ValueError):
        calculate_fuel_displacement(float("inf"), 0.220, 0.850, 4000.0)
    with pytest.raises(ValueError):
        calculate_fuel_displacement(100.0, 0.220, 0.850, float("inf"))


# ==============================================================================
# Tests 23-24 — Zero Baseline Handling
# ==============================================================================
def test_zero_baseline_fuel_handling():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=0.0,
        predicted_CO2_kg=0.0,
        estimated_fuel_displaced_L=0.0,
        estimated_co2_displaced_kg=0.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    assert metrics["net_assisted_fuel_L"] == 0.0
    assert metrics["net_assisted_fuel_cost_usd"] == 0.0
    assert metrics["delta_fuel_pct"] == 0.0
    assert math.isfinite(metrics["delta_fuel_pct"])


def test_zero_baseline_co2_handling():
    metrics = calculate_net_assisted_metrics(
        predicted_fuel_consumption_L=1000.0,
        predicted_CO2_kg=0.0,
        estimated_fuel_displaced_L=10.0,
        estimated_co2_displaced_kg=0.0,
        fuel_price_usd_per_l=1.15,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
    )
    assert metrics["net_assisted_co2_kg"] == 0.0
    assert metrics["net_assisted_operational_cii_gco2_per_dwt_nm"] == 0.0
    assert metrics["delta_cii_pct"] == 0.0
    assert math.isfinite(metrics["delta_cii_pct"])


# ==============================================================================
# Tests 25-28 — Contract, Root-Validator, and Conservation Checks
# ==============================================================================
def test_contract_validation():
    tier4 = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=4120.5,
        predicted_CO2_kg=10906.9,
        clean_energy_utilized_kwh=180.0,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
    )
    assert isinstance(tier4, Tier4EngineeringScenarioEstimates)
    assert tier4.status == "ENGINEERING SCENARIO ESTIMATE"
    assert "not derived from a validated machine-learning" in tier4.disclaimer.lower()
    assert tier4.estimated_fuel_displaced_L > 0.0
    assert tier4.estimated_co2_displaced_kg > 0.0
    assert tier4.delta_fuel_pct < 0.0
    assert tier4.delta_cii_pct < 0.0


def test_phase3_output_root_validator_compatibility():
    tier4 = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=4120.5,
        predicted_CO2_kg=10906.9,
        clean_energy_utilized_kwh=180.0,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
    )
    full_payload = {
        "voyage_metadata": {
            "ship_type": "Oil Service Boat",
            "distance_nm": 250.0,
            "voyage_duration_hours": 18.5,
            "deadweight_tonnes": 1800.0,
        },
        "tier_1_phase2_predictions": {
            "weather": {"temperature_c": 22.4, "wind_speed_knots": 14.2, "significant_wave_height_m": 1.6},
            "fuel_consumption_L": {"value": 4120.5, "unit": "Liters", "evidence_level": "B - STRONGLY INFERRED", "scope": "Total voyage fuel consumption"},
            "co2_emissions_kg": {"value": 10906.9, "unit": "kg"},
            "battery_health": {"predicted_soh": 0.7471, "nominal_pack_capacity_kwh": 649.728, "effective_pack_capacity_kwh": 485.4118},
            "battery_operation": {"predicted_soc_end_of_voyage": 0.5292, "soc_formulation": "Degradation-adjusted pack SOC"},
        },
        "tier_2_baseline_metrics": {
            "baseline_fuel_cost_usd": 4120.5 * 1.15,
            "baseline_operational_cii_gco2_per_dwt_nm": (10906.9 * 1000.0) / (1800.0 * 250.0),
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
        "tier_4_engineering_scenario_estimates": tier4.model_dump(),
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
    # Validate through root Phase3Output validator
    output = Phase3Output.model_validate(full_payload)
    assert output.tier_4_engineering_scenario_estimates.status == "ENGINEERING SCENARIO ESTIMATE"
    assert output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L <= output.tier_1_phase2_predictions.fuel_consumption_L.value


def test_conservation_invariant_checks():
    # Verify strict conservation bounds across a range of energy levels
    pred_fuel = 3000.0
    pred_co2 = 8000.0
    for energy in [0.0, 50.0, 500.0, 5000.0, 50000.0]:
        tier4 = calculate_tier4_engineering_scenario_estimates(
            predicted_fuel_consumption_L=pred_fuel,
            predicted_CO2_kg=pred_co2,
            clean_energy_utilized_kwh=energy,
            deadweight_tonnes=1800.0,
            distance_nm=250.0,
            fuel_price_usd_per_l=1.15,
        )
        assert 0.0 <= tier4.estimated_fuel_displaced_L <= pred_fuel
        assert 0.0 <= tier4.estimated_co2_displaced_kg <= pred_co2
        assert 0.0 <= tier4.net_assisted_fuel_L <= pred_fuel
        assert 0.0 <= tier4.net_assisted_co2_kg <= pred_co2
        assert tier4.delta_fuel_pct <= 0.0
        assert tier4.delta_cii_pct <= 0.0


def test_deterministic_end_to_end_trace():
    """
    Verify complete numeric trace for Oil Service Boat:
      - predicted fuel = 4120.5 L, predicted CO2 = 10906.9 kg
      - clean energy utilized = 180.0 kWh
      - SFOC = 0.220 kg/kWh, density = 0.850 kg/L, EF = 3.114 kg/kg
      - DWT = 1800.0 tonnes, distance = 250.0 nm, price = 1.15 USD/L
    Calculations:
      - displaced fuel = 180.0 * 0.220 / 0.850 = 46.588235 L
      - displaced CO2 = 46.588235 * 0.850 * 3.114 = 123.3144 kg
      - net fuel = 4120.5 - 46.588235 = 4073.911765 L
      - net CO2 = 10906.9 - 123.3144 = 10783.5856 kg
      - net cost = 4073.911765 * 1.15 = 4684.99853 USD
      - baseline CII = 10906.9 * 1000 / (1800 * 250) = 24.237556 gCO2/(DWT*nm)
      - net CII = 10783.5856 * 1000 / (1800 * 250) = 23.963524 gCO2/(DWT*nm)
      - delta fuel = (4073.911765 - 4120.5) / 4120.5 * 100 = -1.130645 %
      - delta CII = (23.963524 - 24.237556) / 24.237556 * 100 = -1.130645 %
    """
    tier4 = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=4120.5,
        predicted_CO2_kg=10906.9,
        clean_energy_utilized_kwh=180.0,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
        generator_sfoc_kg_per_kwh=0.220,
        fuel_density_kg_per_l=0.850,
        emission_factor_kgco2_per_kgfuel=3.114,
    )
    assert tier4.estimated_fuel_displaced_L == pytest.approx(46.58823529)
    assert tier4.estimated_co2_displaced_kg == pytest.approx(123.3144)
    assert tier4.net_assisted_fuel_L == pytest.approx(4073.9117647)
    assert tier4.net_assisted_co2_kg == pytest.approx(10783.5856)
    assert tier4.delta_fuel_pct == pytest.approx(-1.130645, rel=1e-4)
    assert tier4.delta_cii_pct == pytest.approx(-1.130645, rel=1e-4)


# ==============================================================================
# Weather Invariance Boundary Test
# ==============================================================================
def test_phase3d_displacement_weather_invariance():
    """
    Assert that Tier 4 auxiliary displacement calculations are strictly invariant
    to weather conditions. Phase 3D does not accept weather inputs or alter displacement
    based on environmental predictions.
    """
    import inspect
    sig = inspect.signature(calculate_tier4_engineering_scenario_estimates)
    assert "weather" not in sig.parameters
    assert "predicted_weather" not in sig.parameters
    assert "wind_speed_knots" not in sig.parameters
    assert "temperature_c" not in sig.parameters

    # Contextual invariance: Evaluate under identical displacement parameters
    tier4_calm = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=4120.5,
        predicted_CO2_kg=10906.9,
        clean_energy_utilized_kwh=180.0,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
        generator_sfoc_kg_per_kwh=0.220,
        fuel_density_kg_per_l=0.850,
        emission_factor_kgco2_per_kgfuel=3.114,
    )

    tier4_storm = calculate_tier4_engineering_scenario_estimates(
        predicted_fuel_consumption_L=4120.5,
        predicted_CO2_kg=10906.9,
        clean_energy_utilized_kwh=180.0,
        deadweight_tonnes=1800.0,
        distance_nm=250.0,
        fuel_price_usd_per_l=1.15,
        generator_sfoc_kg_per_kwh=0.220,
        fuel_density_kg_per_l=0.850,
        emission_factor_kgco2_per_kgfuel=3.114,
    )

    assert tier4_calm.estimated_fuel_displaced_L == tier4_storm.estimated_fuel_displaced_L
    assert tier4_calm.estimated_co2_displaced_kg == tier4_storm.estimated_co2_displaced_kg
    assert tier4_calm.net_assisted_fuel_L == tier4_storm.net_assisted_fuel_L
    assert tier4_calm.net_assisted_fuel_cost_usd == tier4_storm.net_assisted_fuel_cost_usd
    assert tier4_calm.net_assisted_co2_kg == tier4_storm.net_assisted_co2_kg
    assert tier4_calm.net_assisted_operational_cii_gco2_per_dwt_nm == tier4_storm.net_assisted_operational_cii_gco2_per_dwt_nm
    assert tier4_calm.delta_fuel_pct == tier4_storm.delta_fuel_pct
    assert tier4_calm.delta_cii_pct == tier4_storm.delta_cii_pct

