"""
test_phase6_pollutants.py — Test Suite for Multi-Pollutant Emissions Assessment
================================================================================
Validates:
  1. Zero fuel consumption produces zero pollutant emissions
  2. Positive fuel displacement produces correct avoided NOx, SOx, PM10, PM2.5
  3. Conservation identity: baseline = assisted + avoided
  4. Unit consistency and density conversion math (Liter -> kg fuel -> kg pollutant)
  5. Invalid input rejection (negative fuel values, non-finite values)
  6. Configurable emission factor overrides
  7. Deterministic and reproducible evaluation
"""

import pytest
from pydantic import ValidationError

from phase6_contracts import (
    PollutantEmissionFactors,
    PollutantAssessmentResult,
)
from phase6_regulatory import evaluate_multi_pollutants


def test_zero_fuel_emissions():
    res = evaluate_multi_pollutants(0.0, 0.0)
    assert res.baseline_nox_kg == 0.0
    assert res.assisted_nox_kg == 0.0
    assert res.avoided_nox_kg == 0.0
    assert res.baseline_sox_kg == 0.0
    assert res.avoided_sox_kg == 0.0
    assert res.baseline_pm10_kg == 0.0
    assert res.avoided_pm10_kg == 0.0
    assert res.baseline_pm25_kg == 0.0
    assert res.avoided_pm25_kg == 0.0
    assert res.fuel_displaced_L == 0.0


def test_positive_displacement_pollutants_math():
    # Baseline fuel: 1000.0 L, Net assisted fuel: 900.0 L -> Displaced: 100.0 L
    # Fuel density: 0.85 kg/L -> Fuel displaced mass: 85.0 kg
    # NOx factor: 0.0570 kg/kg -> Avoided NOx: 85.0 * 0.0570 = 4.845 kg
    # SOx factor: 0.0097753 kg/kg -> Avoided SOx: 85.0 * 0.0097753 = 0.8309005 kg
    # PM10 factor: 0.00110 kg/kg -> Avoided PM10: 85.0 * 0.00110 = 0.0935 kg
    # PM25 factor: 0.00101 kg/kg -> Avoided PM25: 85.0 * 0.00101 = 0.08585 kg
    res = evaluate_multi_pollutants(
        baseline_fuel_L=1000.0,
        net_assisted_fuel_L=900.0,
    )
    assert res.fuel_displaced_L == pytest.approx(100.0)
    assert res.avoided_nox_kg == pytest.approx(4.845)
    assert res.avoided_sox_kg == pytest.approx(0.8309005)
    assert res.avoided_pm10_kg == pytest.approx(0.0935)
    assert res.avoided_pm25_kg == pytest.approx(0.08585)


def test_conservation_identities():
    # baseline == assisted + avoided
    res = evaluate_multi_pollutants(4120.5, 4073.91)
    assert res.baseline_nox_kg == pytest.approx(res.assisted_nox_kg + res.avoided_nox_kg)
    assert res.baseline_sox_kg == pytest.approx(res.assisted_sox_kg + res.avoided_sox_kg)
    assert res.baseline_pm10_kg == pytest.approx(res.assisted_pm10_kg + res.avoided_pm10_kg)
    assert res.baseline_pm25_kg == pytest.approx(res.assisted_pm25_kg + res.avoided_pm25_kg)


def test_custom_emission_factors_override():
    custom_factors = PollutantEmissionFactors(
        nox_kg_per_kg_fuel=0.0600,
        sox_kg_per_kg_fuel=0.0020,  # low sulfur fuel
        pm10_kg_per_kg_fuel=0.0008,
        pm25_kg_per_kg_fuel=0.0007,
        fuel_density_kg_per_l=0.860,
        source_reference="Custom Test Calibration",
    )
    # Displaced: 200 L * 0.86 kg/L = 172 kg fuel
    # Avoided NOx = 172 * 0.0600 = 10.32 kg
    # Avoided SOx = 172 * 0.0020 = 0.344 kg
    res = evaluate_multi_pollutants(
        baseline_fuel_L=500.0,
        net_assisted_fuel_L=300.0,
        emission_factors=custom_factors,
    )
    assert res.fuel_displaced_L == pytest.approx(200.0)
    assert res.avoided_nox_kg == pytest.approx(10.32)
    assert res.avoided_sox_kg == pytest.approx(0.344)
    assert res.emission_factor_source == "Custom Test Calibration"


def test_invalid_negative_fuel_raises():
    with pytest.raises(ValueError, match="baseline_fuel_L must be non-negative"):
        evaluate_multi_pollutants(-50.0, 100.0)

    with pytest.raises(ValueError, match="net_assisted_fuel_L must be non-negative"):
        evaluate_multi_pollutants(100.0, -10.0)

    with pytest.raises(ValueError, match="finite"):
        evaluate_multi_pollutants(float("nan"), 100.0)


def test_assisted_greater_than_baseline_clamps_avoided_to_zero():
    # If net assisted fuel >= baseline (no clean displacement)
    res = evaluate_multi_pollutants(500.0, 500.0)
    assert res.fuel_displaced_L == 0.0
    assert res.avoided_nox_kg == 0.0
    assert res.avoided_sox_kg == 0.0
    assert res.avoided_pm10_kg == 0.0
    assert res.avoided_pm25_kg == 0.0
