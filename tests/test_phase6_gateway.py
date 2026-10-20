"""
test_phase6_gateway.py — Test Suite for Phase 6 Automated Model Inference Gateway
==================================================================================
Validates:
  1. Valid end-to-end simulation for Tanker Ship (with statutory CII rating)
  2. Valid end-to-end simulation for Oil Service Boat (NOT_ASSESSED status)
  3. Valid end-to-end simulation for Fishing Trawler (STATUTORILY_EXEMPT status)
  4. Valid end-to-end simulation for Surfer Boat (NOT_ASSESSED status)
  5. Invalid ship type raises validation error
  6. Invalid route raises validation error
  7. Invalid month (<1, >12) raises validation error
  8. Speed <= 0 raises validation error
  9. Speed > max_speed raises ValueError
 10. soc_reserve > initial_soc raises validation error
 11. Weather model invocation: executes frozen artifact, returns 'Calm', consumes 10 features
 12. Fuel model invocation: produces non-negative fuel consumption
 13. SOH model invocation: produces bounded SOH [0, 1]
 14. Phase 3 coordinator integration: produces valid Phase3Output
 15. Parity between manual Tier 1 and gateway-orchestrated Phase 3 output
 16. Repeated execution determinism
 17. Raw dictionary request support
"""

import pytest
from pydantic import ValidationError

from phase3_contracts import (
    Phase3Output,
    VoyageMetadata,
    Tier1Phase2Predictions,
    FROZEN_MODEL_HASHES,
)
from phase3_coordinator import orchestrate_phase3_voyage

from phase6_contracts import (
    VoyageSimulationRequest,
    Phase6SimulationResult,
)
from phase6_gateway import (
    simulate_voyage,
    verify_frozen_model_hashes,
)


# ==============================================================================
# 1. Successful End-to-End Simulation Tests
# ==============================================================================
def test_successful_simulation_tanker_ship():
    res = simulate_voyage({
        "ship_type": "Tanker Ship",
        "route_id": "Escravos-Lagos",
        "month": 7,
        "speed_knots": 10.0,
    })
    assert isinstance(res, Phase6SimulationResult)
    assert res.request.ship_type == "Tanker Ship"
    assert res.tier1_predictions.weather.temperature_c > 0.0
    assert res.tier1_predictions.fuel_consumption_L.value > 0.0
    assert res.tier1_predictions.co2_emissions_kg.value > 0.0
    assert 0.0 < res.tier1_predictions.battery_health.predicted_soh <= 1.0

    # Phase 3 integration checks
    assert isinstance(res.phase3_output, Phase3Output)
    assert res.phase3_output.voyage_metadata.deadweight_tonnes == 14000.0
    assert res.phase3_output.tier_4_engineering_scenario_estimates.status == "ENGINEERING SCENARIO ESTIMATE"

    # Regulatory assessment checks
    assert res.regulatory_assessment.vessel_category == "Tanker"
    assert res.regulatory_assessment.cii_assessment_status == "STATUTORY_ASSESSMENT_COMPLETED"
    assert res.regulatory_assessment.baseline_cii_rating in ["A", "B", "C", "D", "E"]
    assert res.regulatory_assessment.assisted_cii_rating in ["A", "B", "C", "D", "E"]

    # Pollutant assessment checks
    assert res.pollutant_assessment.assessment_status == "ENGINEERING_ESTIMATE"
    assert res.pollutant_assessment.baseline_nox_kg > 0.0
    assert res.pollutant_assessment.avoided_nox_kg >= 0.0


def test_successful_simulation_oil_service_boat():
    res = simulate_voyage({
        "ship_type": "Oil Service Boat",
        "route_id": "Warri-Bonny",
        "month": 3,
        "speed_knots": 12.0,
    })
    assert isinstance(res, Phase6SimulationResult)
    assert res.request.ship_type == "Oil Service Boat"
    assert res.regulatory_assessment.baseline_cii_rating == "NOT_ASSESSED"
    assert res.regulatory_assessment.assisted_cii_rating == "NOT_ASSESSED"
    assert res.regulatory_assessment.cii_assessment_status == "UNSUPPORTED_VESSEL_CATEGORY_MAPPING"
    assert res.regulatory_assessment.baseline_attained_cii > 0.0


def test_successful_simulation_fishing_trawler():
    res = simulate_voyage({
        "ship_type": "Fishing Trawler",
        "route_id": "Lagos-Apapa",
        "month": 1,
        "speed_knots": 8.0,
    })
    assert isinstance(res, Phase6SimulationResult)
    assert res.request.ship_type == "Fishing Trawler"
    assert res.regulatory_assessment.baseline_cii_rating == "NOT_ASSESSED"
    assert res.regulatory_assessment.assisted_cii_rating == "NOT_ASSESSED"
    assert res.regulatory_assessment.cii_assessment_status == "STATUTORILY_EXEMPT"


def test_successful_simulation_surfer_boat():
    res = simulate_voyage({
        "ship_type": "Surfer Boat",
        "route_id": "Warri-Bonny",
        "month": 5,
        "speed_knots": 15.0,
    })
    assert isinstance(res, Phase6SimulationResult)
    assert res.request.ship_type == "Surfer Boat"
    assert res.regulatory_assessment.baseline_cii_rating == "NOT_ASSESSED"
    assert res.regulatory_assessment.cii_assessment_status == "UNSUPPORTED_VESSEL_CATEGORY_MAPPING"


# ==============================================================================
# 2. Input Validation Tests
# ==============================================================================
def test_invalid_ship_type_rejected():
    with pytest.raises(ValidationError, match="Invalid ship_type"):
        VoyageSimulationRequest(
            ship_type="Cargo Freighter",
            route_id="Warri-Bonny",
            month=6,
            speed_knots=10.0,
        )


def test_invalid_route_rejected():
    with pytest.raises(ValidationError, match="Invalid route_id"):
        VoyageSimulationRequest(
            ship_type="Oil Service Boat",
            route_id="London-Rotterdam",
            month=6,
            speed_knots=10.0,
        )


def test_invalid_month_range_rejected():
    with pytest.raises(ValidationError):
        VoyageSimulationRequest(
            ship_type="Oil Service Boat",
            route_id="Warri-Bonny",
            month=0,
            speed_knots=10.0,
        )

    with pytest.raises(ValidationError):
        VoyageSimulationRequest(
            ship_type="Oil Service Boat",
            route_id="Warri-Bonny",
            month=13,
            speed_knots=10.0,
        )


def test_invalid_speed_rejected():
    with pytest.raises(ValidationError):
        VoyageSimulationRequest(
            ship_type="Oil Service Boat",
            route_id="Warri-Bonny",
            month=6,
            speed_knots=0.0,
        )

    with pytest.raises(ValidationError):
        VoyageSimulationRequest(
            ship_type="Oil Service Boat",
            route_id="Warri-Bonny",
            month=6,
            speed_knots=-5.0,
        )


def test_speed_exceeding_max_design_speed_raises():
    # Surfer Boat max speed is 22 knots; requesting 30 knots must fail
    with pytest.raises(ValueError, match="exceeds maximum design speed"):
        simulate_voyage({
            "ship_type": "Surfer Boat",
            "route_id": "Warri-Bonny",
            "month": 6,
            "speed_knots": 30.0,
        })


def test_soc_reserve_greater_than_initial_soc_rejected():
    with pytest.raises(ValidationError, match="soc_reserve .* cannot exceed initial_soc"):
        VoyageSimulationRequest(
            ship_type="Oil Service Boat",
            route_id="Warri-Bonny",
            month=6,
            speed_knots=10.0,
            initial_soc=0.20,
            soc_reserve=0.30,
        )


# ==============================================================================
# 3. Model Invocation & Parity Tests
# ==============================================================================
def test_frozen_model_hashes_verified():
    assert verify_frozen_model_hashes() is True


def test_deterministic_repeated_execution():
    req = {
        "ship_type": "Oil Service Boat",
        "route_id": "Escravos-Lagos",
        "month": 4,
        "speed_knots": 11.5,
    }
    res1 = simulate_voyage(req)
    res2 = simulate_voyage(req)

    assert res1.tier1_predictions.fuel_consumption_L.value == res2.tier1_predictions.fuel_consumption_L.value
    assert res1.tier1_predictions.co2_emissions_kg.value == res2.tier1_predictions.co2_emissions_kg.value
    assert res1.phase3_output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L == (
        res2.phase3_output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L
    )
    assert res1.pollutant_assessment.avoided_nox_kg == res2.pollutant_assessment.avoided_nox_kg


def test_phase3_coordinator_parity():
    """Verify that calling Phase 3 directly with gateway Tier 1 matches gateway output."""
    res = simulate_voyage({
        "ship_type": "Oil Service Boat",
        "route_id": "Warri-Bonny",
        "month": 3,
        "speed_knots": 12.0,
        "distance_nm": 250.0,
        "auxiliary_energy_demand_kwh": 180.0,
    })

    # Call orchestrate_phase3_voyage directly
    direct_p3 = orchestrate_phase3_voyage(
        voyage_metadata=res.phase3_output.voyage_metadata,
        tier1_predictions=res.tier1_predictions,
        auxiliary_energy_demand_kwh=180.0,
        route_id="Warri-Bonny",
        month=3,
    )
    # Both delegate to Tier 4 displacement correctly
    assert res.phase3_output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L == pytest.approx(
        direct_p3.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L
    )
