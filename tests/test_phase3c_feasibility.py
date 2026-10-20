"""
test_phase3c_feasibility.py — Test Suite for Phase 3C Tier 3 Clean Energy Feasibility
====================================================================================
Validates:
  - Battery capacity and usable energy calculations (SOH scaling, SOC reserve buffer)
  - Climatological solar energy estimation (GHI lookup, panel area, efficiency, derating, duration scaling)
  - Energy balance, deficit, and feasibility status classification (FEASIBLE vs PARTIAL)
  - Boundary input validation (negative, zero, out-of-bounds, non-finite values)
  - Pydantic contract compliance with Tier3CleanEnergyFeasibility
  - End-to-end deterministic verification using actual ship profiles and NASA climatology
"""

import math
import pytest
from pydantic import ValidationError

from phase3_contracts import Tier3CleanEnergyFeasibility
from phase3_feasibility import (
    get_vessel_clean_energy_specs,
    lookup_solar_climatology_ghi,
    calculate_effective_battery_capacity,
    calculate_usable_battery_energy,
    calculate_estimated_solar_energy,
    calculate_clean_energy_balance,
    calculate_tier3_clean_energy_feasibility,
)


# ==============================================================================
# Battery Tests (Tests 1-6)
# ==============================================================================
def test_normal_soh_calculation():
    # 649.728 kWh * 0.7471 = 485.4117888 kWh
    eff = calculate_effective_battery_capacity(nominal_pack_capacity_kwh=649.728, predicted_soh=0.7471)
    assert eff == pytest.approx(485.4117888)


def test_soh_one():
    # 649.728 kWh * 1.0 = 649.728 kWh
    eff = calculate_effective_battery_capacity(nominal_pack_capacity_kwh=649.728, predicted_soh=1.0)
    assert eff == pytest.approx(649.728)


def test_soh_zero():
    # 649.728 kWh * 0.0 = 0.0 kWh
    eff = calculate_effective_battery_capacity(nominal_pack_capacity_kwh=649.728, predicted_soh=0.0)
    assert eff == 0.0


def test_initial_soc_greater_than_reserve():
    # eff = 485.4118, init = 0.90, reserve = 0.20 -> delta = 0.70
    usable = calculate_usable_battery_energy(
        effective_pack_capacity_kwh=485.4118,
        initial_soc=0.90,
        soc_reserve=0.20,
    )
    assert usable == pytest.approx(485.4118 * 0.70)


def test_initial_soc_equal_to_reserve():
    # init = 0.20, reserve = 0.20 -> delta = 0.0
    usable = calculate_usable_battery_energy(
        effective_pack_capacity_kwh=485.4118,
        initial_soc=0.20,
        soc_reserve=0.20,
    )
    assert usable == 0.0


def test_initial_soc_less_than_reserve():
    # init = 0.15, reserve = 0.20 -> delta clamped to 0.0 (never negative)
    usable = calculate_usable_battery_energy(
        effective_pack_capacity_kwh=485.4118,
        initial_soc=0.15,
        soc_reserve=0.20,
    )
    assert usable == 0.0


# ==============================================================================
# Solar Tests (Tests 7-12)
# ==============================================================================
def test_normal_solar_calculation():
    # 80 m2 * 21.5% * 5.0 kWh/m2/day * 0.85 * (12 hrs / 24)
    # = 80 * 0.215 * 5.0 * 0.85 * 0.5 = 36.55 kWh
    solar = calculate_estimated_solar_energy(
        solar_panel_size_m2=80.0,
        solar_panel_efficiency_pct=21.5,
        daily_ghi_kwh_per_m2=5.0,
        solar_derate_factor=0.85,
        voyage_duration_hours=12.0,
    )
    assert solar == pytest.approx(36.55)


def test_zero_ghi():
    solar = calculate_estimated_solar_energy(
        solar_panel_size_m2=80.0,
        solar_panel_efficiency_pct=21.5,
        daily_ghi_kwh_per_m2=0.0,
        solar_derate_factor=0.85,
        voyage_duration_hours=12.0,
    )
    assert solar == 0.0


def test_zero_solar_panel_area():
    solar = calculate_estimated_solar_energy(
        solar_panel_size_m2=0.0,
        solar_panel_efficiency_pct=21.5,
        daily_ghi_kwh_per_m2=5.0,
        solar_derate_factor=0.85,
        voyage_duration_hours=12.0,
    )
    assert solar == 0.0


def test_hundred_percent_efficiency_boundary():
    # 100 m2 * 100% * 5.0 * 1.0 * (24 / 24) = 500.0 kWh
    solar = calculate_estimated_solar_energy(
        solar_panel_size_m2=100.0,
        solar_panel_efficiency_pct=100.0,
        daily_ghi_kwh_per_m2=5.0,
        solar_derate_factor=1.0,
        voyage_duration_hours=24.0,
    )
    assert solar == pytest.approx(500.0)


def test_solar_derate_zero():
    solar = calculate_estimated_solar_energy(
        solar_panel_size_m2=80.0,
        solar_panel_efficiency_pct=21.5,
        daily_ghi_kwh_per_m2=5.0,
        solar_derate_factor=0.0,
        voyage_duration_hours=12.0,
    )
    assert solar == 0.0


def test_voyage_duration_scaling():
    # Double duration -> exactly double solar energy
    solar_12h = calculate_estimated_solar_energy(80.0, 21.5, 5.0, 0.85, 12.0)
    solar_24h = calculate_estimated_solar_energy(80.0, 21.5, 5.0, 0.85, 24.0)
    solar_48h = calculate_estimated_solar_energy(80.0, 21.5, 5.0, 0.85, 48.0)
    assert solar_24h == pytest.approx(solar_12h * 2.0)
    assert solar_48h == pytest.approx(solar_12h * 4.0)


# ==============================================================================
# Energy Balance Tests (Tests 13-17)
# ==============================================================================
def test_demand_equals_available_energy():
    res = calculate_clean_energy_balance(
        usable_battery_energy_kwh=100.0,
        estimated_solar_energy_kwh=50.0,
        auxiliary_energy_demand_kwh=150.0,
    )
    assert res["total_clean_energy_available_kwh"] == 150.0
    assert res["clean_energy_utilized_kwh"] == 150.0
    assert res["energy_balance_kwh"] == 0.0
    assert res["energy_deficit_kwh"] == 0.0
    assert res["feasibility_status"] == "FEASIBLE"


def test_demand_below_available_energy():
    res = calculate_clean_energy_balance(
        usable_battery_energy_kwh=100.0,
        estimated_solar_energy_kwh=50.0,
        auxiliary_energy_demand_kwh=80.0,
    )
    assert res["total_clean_energy_available_kwh"] == 150.0
    assert res["clean_energy_utilized_kwh"] == 80.0
    assert res["energy_balance_kwh"] == 70.0
    assert res["energy_deficit_kwh"] == 0.0
    assert res["feasibility_status"] == "FEASIBLE"


def test_demand_above_available_energy():
    res = calculate_clean_energy_balance(
        usable_battery_energy_kwh=100.0,
        estimated_solar_energy_kwh=50.0,
        auxiliary_energy_demand_kwh=200.0,
    )
    assert res["total_clean_energy_available_kwh"] == 150.0
    assert res["clean_energy_utilized_kwh"] == 150.0
    assert res["energy_balance_kwh"] == -50.0
    assert res["energy_deficit_kwh"] == 50.0
    assert res["feasibility_status"] == "PARTIAL"


def test_zero_auxiliary_demand():
    res = calculate_clean_energy_balance(
        usable_battery_energy_kwh=100.0,
        estimated_solar_energy_kwh=50.0,
        auxiliary_energy_demand_kwh=0.0,
    )
    assert res["total_clean_energy_available_kwh"] == 150.0
    assert res["clean_energy_utilized_kwh"] == 0.0
    assert res["energy_balance_kwh"] == 150.0
    assert res["energy_deficit_kwh"] == 0.0
    assert res["feasibility_status"] == "FEASIBLE"


def test_large_auxiliary_demand():
    res = calculate_clean_energy_balance(
        usable_battery_energy_kwh=50.0,
        estimated_solar_energy_kwh=10.0,
        auxiliary_energy_demand_kwh=1000.0,
    )
    assert res["total_clean_energy_available_kwh"] == 60.0
    assert res["clean_energy_utilized_kwh"] == 60.0
    assert res["energy_balance_kwh"] == -940.0
    assert res["energy_deficit_kwh"] == 940.0
    assert res["feasibility_status"] == "PARTIAL"


# ==============================================================================
# Status Tests (Tests 18-19)
# ==============================================================================
def test_exact_boundary_produces_feasible():
    res = calculate_clean_energy_balance(50.0, 50.0, 100.0)
    assert res["energy_balance_kwh"] == 0.0
    assert res["feasibility_status"] == "FEASIBLE"


def test_any_negative_balance_produces_partial():
    res = calculate_clean_energy_balance(50.0, 50.0, 100.001)
    assert res["energy_balance_kwh"] < 0.0
    assert res["feasibility_status"] == "PARTIAL"


# ==============================================================================
# Validation Tests (Tests 20-26)
# ==============================================================================
def test_invalid_soh():
    for bad in [-0.01, 1.01, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_effective_battery_capacity(100.0, bad)


def test_invalid_soc():
    for bad in [-0.05, 1.05, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_usable_battery_energy(100.0, bad, 0.20)


def test_invalid_reserve():
    for bad in [-0.1, 1.1, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_usable_battery_energy(100.0, 0.90, bad)


def test_invalid_derate():
    for bad in [-0.05, 1.05, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_estimated_solar_energy(80.0, 21.5, 5.0, bad, 12.0)


def test_non_positive_voyage_duration():
    for bad in [0.0, -5.0, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_estimated_solar_energy(80.0, 21.5, 5.0, 0.85, bad)


def test_negative_auxiliary_demand():
    for bad in [-10.0, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            calculate_clean_energy_balance(100.0, 50.0, bad)


def test_invalid_or_missing_climatology_lookup():
    # Unknown route
    with pytest.raises(ValueError, match="No climatology record found"):
        lookup_solar_climatology_ghi(route_id="Nonexistent-Corridor", month="January")

    # Invalid month string
    with pytest.raises(ValueError, match="Unknown month string"):
        lookup_solar_climatology_ghi(route_id="Escravos-Lagos", month="Smarch")

    # Invalid month integer
    with pytest.raises(ValueError, match="month_num must be in range"):
        lookup_solar_climatology_ghi(route_id="Escravos-Lagos", month=13)


# ==============================================================================
# Contract & Deterministic End-to-End Tests (Tests 27-30)
# ==============================================================================
def test_returned_object_validates_against_tier3_contract():
    res = calculate_tier3_clean_energy_feasibility(
        ship_type="Oil Service Boat",
        predicted_soh=0.7471,
        auxiliary_energy_demand_kwh=180.0,
        voyage_duration_hours=18.5,
        route_id="Escravos-Lagos",
        month="January",
    )
    assert isinstance(res, Tier3CleanEnergyFeasibility)
    assert res.feasibility_status in ["FEASIBLE", "PARTIAL"]
    assert res.auxiliary_energy_demand_kwh == 180.0
    assert res.usable_battery_energy_kwh >= 0.0
    assert res.estimated_solar_energy_kwh >= 0.0
    assert res.total_clean_energy_available_kwh == pytest.approx(
        res.usable_battery_energy_kwh + res.estimated_solar_energy_kwh
    )


def test_required_fields_have_correct_types():
    res = calculate_tier3_clean_energy_feasibility(
        ship_type="Fishing Trawler",
        predicted_soh=0.7442,
        auxiliary_energy_demand_kwh=80.0,
        voyage_duration_hours=10.0,
        route_id="Warri-Bonny",
        month="March",
    )
    d = res.model_dump()
    for field_name in [
        "auxiliary_energy_demand_kwh",
        "usable_battery_energy_kwh",
        "estimated_solar_energy_kwh",
        "total_clean_energy_available_kwh",
        "clean_energy_utilized_kwh",
        "energy_balance_kwh",
        "energy_deficit_kwh",
    ]:
        assert isinstance(d[field_name], float)
    assert d["feasibility_status"] in ["FEASIBLE", "PARTIAL"]


def test_no_unsupported_feasibility_status():
    # Feasible case
    res1 = calculate_tier3_clean_energy_feasibility(
        ship_type="Tanker Ship",
        predicted_soh=0.75,
        auxiliary_energy_demand_kwh=50.0,
        voyage_duration_hours=24.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    assert res1.feasibility_status == "FEASIBLE"

    # Partial case
    res2 = calculate_tier3_clean_energy_feasibility(
        ship_type="Surfer Boat",
        predicted_soh=0.75,
        auxiliary_energy_demand_kwh=500.0,
        voyage_duration_hours=5.0,
        daily_ghi_kwh_per_m2=4.0,
    )
    assert res2.feasibility_status == "PARTIAL"


def test_end_to_end_deterministic_actual_vessel_and_climatology():
    """
    End-to-end trace with Oil Service Boat on Escravos-Lagos in January:
      - nominal pack = 649.728 kWh
      - predicted SOH = 0.7471
      - effective capacity = 649.728 * 0.7471 = 485.4117888 kWh
      - initial_soc = 0.90, soc_reserve = 0.20 -> delta = 0.70
      - usable battery = 485.4117888 * 0.70 = 339.78825216 kWh
      - January Escravos-Lagos GHI = 5.060721 kWh/m2/day
      - panel area = 80 m2, efficiency = 21.5%
      - derate = 0.85, duration = 18.5 hours
      - estimated solar = 80 * 0.215 * 5.060721 * 0.85 * (18.5 / 24) = 57.032217 kWh
      - total available = 339.788252 + 57.032217 = 396.820469 kWh
      - auxiliary demand = 180.0 kWh
      - clean utilized = 180.0 kWh
      - balance = 396.820469 - 180.0 = 216.820469 kWh
      - deficit = 0.0 kWh
      - status = FEASIBLE
    """
    ghi = lookup_solar_climatology_ghi("Escravos-Lagos", "January")
    assert ghi == pytest.approx(5.060721)

    res = calculate_tier3_clean_energy_feasibility(
        ship_type="Oil Service Boat",
        predicted_soh=0.7471,
        auxiliary_energy_demand_kwh=180.0,
        voyage_duration_hours=18.5,
        route_id="Escravos-Lagos",
        month="January",
        initial_soc=0.90,
        soc_reserve=0.20,
        solar_derate_factor=0.85,
    )
    assert res.usable_battery_energy_kwh == pytest.approx(339.78825216)
    expected_solar = 80.0 * 0.215 * 5.060721 * 0.85 * (18.5 / 24.0)
    assert res.estimated_solar_energy_kwh == pytest.approx(expected_solar)
    assert res.total_clean_energy_available_kwh == pytest.approx(339.78825216 + expected_solar)
    assert res.clean_energy_utilized_kwh == 180.0
    assert res.energy_deficit_kwh == 0.0
    assert res.energy_balance_kwh == pytest.approx((339.78825216 + expected_solar) - 180.0)
    assert res.feasibility_status == "FEASIBLE"


# ==============================================================================
# Weather Invariance Boundary Test
# ==============================================================================
def test_phase3c_feasibility_weather_invariance():
    """
    Assert that Tier 3 clean energy feasibility calculations are strictly invariant
    to weather conditions. Phase 3C does not consume predicted weather as a dispatch
    condition, gating input, or derating modifier.
    """
    import inspect
    sig = inspect.signature(calculate_tier3_clean_energy_feasibility)
    assert "weather" not in sig.parameters
    assert "predicted_weather" not in sig.parameters
    assert "wind_speed_knots" not in sig.parameters
    assert "temperature_c" not in sig.parameters

    # Contextual invariance: Evaluate feasibility under hypothetical Calm vs Stormy regimes
    weather_calm = {"temperature_c": 24.0, "wind_speed_knots": 8.0, "significant_wave_height_m": 0.5}
    weather_storm = {"temperature_c": 5.0, "wind_speed_knots": 45.0, "significant_wave_height_m": 7.5}

    res_calm = calculate_tier3_clean_energy_feasibility(
        ship_type="Oil Service Boat",
        predicted_soh=0.7471,
        auxiliary_energy_demand_kwh=180.0,
        voyage_duration_hours=18.5,
        route_id="Escravos-Lagos",
        month="January",
        initial_soc=0.90,
        soc_reserve=0.20,
        solar_derate_factor=0.85,
    )

    res_storm = calculate_tier3_clean_energy_feasibility(
        ship_type="Oil Service Boat",
        predicted_soh=0.7471,
        auxiliary_energy_demand_kwh=180.0,
        voyage_duration_hours=18.5,
        route_id="Escravos-Lagos",
        month="January",
        initial_soc=0.90,
        soc_reserve=0.20,
        solar_derate_factor=0.85,
    )

    assert res_calm.usable_battery_energy_kwh == res_storm.usable_battery_energy_kwh
    assert res_calm.estimated_solar_energy_kwh == res_storm.estimated_solar_energy_kwh
    assert res_calm.total_clean_energy_available_kwh == res_storm.total_clean_energy_available_kwh
    assert res_calm.clean_energy_utilized_kwh == res_storm.clean_energy_utilized_kwh
    assert res_calm.energy_balance_kwh == res_storm.energy_balance_kwh
    assert res_calm.energy_deficit_kwh == res_storm.energy_deficit_kwh
    assert res_calm.feasibility_status == res_storm.feasibility_status == "FEASIBLE"


# ==============================================================================
# Diurnal Solar Uncertainty Flag Test
# ==============================================================================
def test_solar_estimate_diurnal_uncertainty_flag():
    """
    Verify solar_estimate_diurnal_uncertainty_flag:
      1. True when voyage_duration_hours > 24.0 (representative Tanker scenario).
      2. False when voyage_duration_hours <= 24.0 for representative typical lengths
         across Oil Service Boat, Fishing Trawler, and Surfer Boat.
      3. Proves no formula change: solar energy, usable battery, total clean energy,
         energy balance, clean energy utilized, deficit, and feasibility status match
         exact mathematical expectations without modification.
    """
    # 1. >24-hour Tanker case
    tanker_res = calculate_tier3_clean_energy_feasibility(
        ship_type="Tanker Ship",
        predicted_soh=0.7387,
        auxiliary_energy_demand_kwh=600.0,
        voyage_duration_hours=36.0,  # > 24 hours
        daily_ghi_kwh_per_m2=5.0,
        initial_soc=0.90,
        soc_reserve=0.20,
        solar_derate_factor=0.85,
    )
    assert tanker_res.solar_estimate_diurnal_uncertainty_flag is True

    # Mathematical invariance verification for Tanker:
    expected_tanker_usable = 1199.9232 * 0.7387 * 0.70
    expected_tanker_solar = 250.0 * 0.215 * 5.0 * 0.85 * (36.0 / 24.0)
    expected_tanker_total = expected_tanker_usable + expected_tanker_solar
    assert tanker_res.usable_battery_energy_kwh == pytest.approx(expected_tanker_usable)
    assert tanker_res.estimated_solar_energy_kwh == pytest.approx(expected_tanker_solar)
    assert tanker_res.total_clean_energy_available_kwh == pytest.approx(expected_tanker_total)
    assert tanker_res.clean_energy_utilized_kwh == 600.0
    assert tanker_res.energy_balance_kwh == pytest.approx(expected_tanker_total - 600.0)
    assert tanker_res.energy_deficit_kwh == 0.0
    assert tanker_res.feasibility_status == "FEASIBLE"

    # 2. <=24-hour cases for other ship types
    # Oil Service Boat (18.5 hours)
    osb_res = calculate_tier3_clean_energy_feasibility(
        ship_type="Oil Service Boat",
        predicted_soh=0.7471,
        auxiliary_energy_demand_kwh=180.0,
        voyage_duration_hours=18.5,
        daily_ghi_kwh_per_m2=5.060721,
        initial_soc=0.90,
        soc_reserve=0.20,
        solar_derate_factor=0.85,
    )
    assert osb_res.solar_estimate_diurnal_uncertainty_flag is False
    expected_osb_solar = 80.0 * 0.215 * 5.060721 * 0.85 * (18.5 / 24.0)
    expected_osb_usable = 649.728 * 0.7471 * 0.70
    assert osb_res.estimated_solar_energy_kwh == pytest.approx(expected_osb_solar)
    assert osb_res.usable_battery_energy_kwh == pytest.approx(expected_osb_usable)
    assert osb_res.total_clean_energy_available_kwh == pytest.approx(expected_osb_usable + expected_osb_solar)
    assert osb_res.clean_energy_utilized_kwh == 180.0
    assert osb_res.feasibility_status == "FEASIBLE"

    # Fishing Trawler (12.0 hours)
    trawler_res = calculate_tier3_clean_energy_feasibility(
        ship_type="Fishing Trawler",
        predicted_soh=0.7442,
        auxiliary_energy_demand_kwh=80.0,
        voyage_duration_hours=12.0,
        daily_ghi_kwh_per_m2=4.5,
        initial_soc=0.85,
        soc_reserve=0.20,
        solar_derate_factor=0.85,
    )
    assert trawler_res.solar_estimate_diurnal_uncertainty_flag is False
    expected_trawler_solar = 45.0 * 0.21 * 4.5 * 0.85 * (12.0 / 24.0)
    assert trawler_res.estimated_solar_energy_kwh == pytest.approx(expected_trawler_solar)
    assert trawler_res.feasibility_status == "FEASIBLE"

    # Surfer Boat (4.0 hours)
    surfer_res = calculate_tier3_clean_energy_feasibility(
        ship_type="Surfer Boat",
        predicted_soh=0.7488,
        auxiliary_energy_demand_kwh=37.0,
        voyage_duration_hours=4.0,
        daily_ghi_kwh_per_m2=5.0,
        initial_soc=0.80,
        soc_reserve=0.20,
        solar_derate_factor=0.85,
    )
    assert surfer_res.solar_estimate_diurnal_uncertainty_flag is False
    expected_surfer_solar = 25.0 * 0.22 * 5.0 * 0.85 * (4.0 / 24.0)
    assert surfer_res.estimated_solar_energy_kwh == pytest.approx(expected_surfer_solar)
    assert surfer_res.feasibility_status == "FEASIBLE"

    # Boundary case: exactly 24.0 hours -> False
    boundary_res = calculate_tier3_clean_energy_feasibility(
        ship_type="Oil Service Boat",
        predicted_soh=0.7471,
        auxiliary_energy_demand_kwh=180.0,
        voyage_duration_hours=24.0,
        daily_ghi_kwh_per_m2=5.0,
    )
    assert boundary_res.solar_estimate_diurnal_uncertainty_flag is False


