"""
test_phase3f_comparison.py — Test Suite for Phase 3F Multi-Scenario Comparative Analysis
========================================================================================
Validates:
  - Contract validation (valid request, empty scenarios, duplicate IDs, invalid reference ID, invalid criterion)
  - Inheritance rules (base fallback, single-field override, multi-field override, isolation across scenarios)
  - Delegation (exactly N Phase 3E calls for N scenarios, parameter propagation, no formula duplication)
  - Comparison deltas (baseline-relative cost/CO2, pairwise differentials against reference scenario)
  - Deterministic ranking (min cost, min CO2, min fuel, min CII, max clean energy, max fuel displacement, tie-breaking)
  - Feasibility preservation (FEASIBLE and PARTIAL retained without silent dropping)
  - Determinism & idempotency across runs
  - Conservation invariant preservation across all evaluated scenarios
  - Frozen model SHA-256 hash integrity
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
from phase3f_comparison import (
    ScenarioOverride,
    ScenarioDefinition,
    Phase3FComparisonRequest,
    Phase3FComparisonOutput,
    compare_phase3_scenarios,
    compare_scenarios,
)


@pytest.fixture
def base_voyage_metadata():
    return VoyageMetadata(
        ship_type="Oil Service Boat",
        distance_nm=250.0,
        voyage_duration_hours=18.5,
        deadweight_tonnes=1800.0,
    )


@pytest.fixture
def base_tier1_predictions():
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


# ==============================================================================
# Contract Validation Tests (Tests 1-5)
# ==============================================================================
def test_valid_request(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S1", description="Baseline configuration"),
            ScenarioDefinition(scenario_id="S2", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=220.0)),
        ],
    )
    assert len(req.scenarios) == 2
    assert req.ranking_criterion is None


def test_empty_scenarios_rejected(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    with pytest.raises(ValidationError):
        Phase3FComparisonRequest(
            voyage_metadata=base_voyage_metadata,
            tier_1_phase2_predictions=base_tier1_predictions,
            base_scenario_parameters=base_scenario_params,
            daily_ghi_kwh_per_m2=5.0,
            scenarios=[],
        )


def test_duplicate_scenario_ids_rejected(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    with pytest.raises(ValueError) as exc:
        Phase3FComparisonRequest(
            voyage_metadata=base_voyage_metadata,
            tier_1_phase2_predictions=base_tier1_predictions,
            base_scenario_parameters=base_scenario_params,
            daily_ghi_kwh_per_m2=5.0,
            scenarios=[
                ScenarioDefinition(scenario_id="duplicate_id"),
                ScenarioDefinition(scenario_id="duplicate_id"),
            ],
        )
    assert "Duplicate scenario_id" in str(exc.value)


def test_invalid_reference_scenario_id_rejected(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    with pytest.raises(ValueError) as exc:
        Phase3FComparisonRequest(
            voyage_metadata=base_voyage_metadata,
            tier_1_phase2_predictions=base_tier1_predictions,
            base_scenario_parameters=base_scenario_params,
            daily_ghi_kwh_per_m2=5.0,
            scenarios=[ScenarioDefinition(scenario_id="S1")],
            reference_scenario_id="non_existent_ref",
        )
    assert "reference_scenario_id 'non_existent_ref' not found" in str(exc.value)


def test_invalid_ranking_criterion_rejected(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    with pytest.raises(ValidationError):
        Phase3FComparisonRequest(
            voyage_metadata=base_voyage_metadata,
            tier_1_phase2_predictions=base_tier1_predictions,
            base_scenario_parameters=base_scenario_params,
            daily_ghi_kwh_per_m2=5.0,
            scenarios=[ScenarioDefinition(scenario_id="S1")],
            ranking_criterion="invented_composite_score",  # Not in Literal
        )


# ==============================================================================
# Inheritance and Isolation Tests (Tests 6-9)
# ==============================================================================
def test_base_parameter_inheritance(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[ScenarioDefinition(scenario_id="S1")],
    )
    res = compare_phase3_scenarios(req)
    s1 = res.scenarios[0]
    assert s1.auxiliary_energy_demand_kwh == base_scenario_params.auxiliary_energy_demand_kwh
    assert s1.resolved_fuel_price_usd_per_l == base_scenario_params.fuel_price_usd_per_l


def test_single_field_override(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(
                scenario_id="S1",
                overrides=ScenarioOverride(auxiliary_energy_demand_kwh=300.0),
            )
        ],
    )
    res = compare_phase3_scenarios(req)
    s1 = res.scenarios[0]
    assert s1.auxiliary_energy_demand_kwh == 300.0
    # Other parameters remain inherited from base
    assert s1.resolved_fuel_price_usd_per_l == 1.15


def test_multiple_field_overrides(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(
                scenario_id="S1",
                overrides=ScenarioOverride(
                    auxiliary_energy_demand_kwh=250.0,
                    fuel_price_usd_per_l=1.45,
                    generator_sfoc_kg_per_kwh=0.230,
                    initial_soc=0.85,
                ),
            )
        ],
    )
    res = compare_phase3_scenarios(req)
    s1 = res.scenarios[0]
    assert s1.auxiliary_energy_demand_kwh == 250.0
    assert s1.resolved_fuel_price_usd_per_l == 1.45
    assert s1.phase3_output.applied_scenario_parameters.generator_sfoc_kg_per_kwh == 0.230
    assert s1.phase3_output.applied_scenario_parameters.initial_soc == 0.85


def test_scenario_isolation_between_a_and_b(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="A", overrides=ScenarioOverride(fuel_price_usd_per_l=2.00, auxiliary_energy_demand_kwh=50.0)),
            ScenarioDefinition(scenario_id="B", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=180.0)),
        ],
    )
    res = compare_phase3_scenarios(req)
    s_a = next(s for s in res.scenarios if s.scenario_id == "A")
    s_b = next(s for s in res.scenarios if s.scenario_id == "B")

    # A's price override (2.00) did not bleed into B (which retains base 1.15)
    assert s_a.resolved_fuel_price_usd_per_l == 2.00
    assert s_b.resolved_fuel_price_usd_per_l == 1.15
    assert s_a.auxiliary_energy_demand_kwh == 50.0
    assert s_b.auxiliary_energy_demand_kwh == 180.0


# ==============================================================================
# Delegation Tests (Tests 10-12)
# ==============================================================================
def test_delegates_exactly_n_times(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    from phase3f_comparison import orchestrate_phase3_voyage

    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S1"),
            ScenarioDefinition(scenario_id="S2"),
            ScenarioDefinition(scenario_id="S3"),
        ],
    )
    with patch("phase3f_comparison.orchestrate_phase3_voyage", wraps=orchestrate_phase3_voyage) as spy_coord:
        res = compare_phase3_scenarios(req)
        assert spy_coord.call_count == 3
        assert res.scenario_count == 3


def test_phase3e_receives_resolved_parameters(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    from phase3f_comparison import orchestrate_phase3_voyage

    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(
                scenario_id="S1",
                overrides=ScenarioOverride(generator_sfoc_kg_per_kwh=0.235, fuel_price_usd_per_l=1.30),
            )
        ],
    )
    with patch("phase3f_comparison.orchestrate_phase3_voyage", wraps=orchestrate_phase3_voyage) as spy_coord:
        compare_phase3_scenarios(req)
        call_kwargs = spy_coord.call_args.kwargs
        assert call_kwargs["generator_sfoc_kg_per_kwh"] == 0.235
        assert call_kwargs["fuel_price_override_usd_per_l"] == 1.30


def test_convenience_alias_compare_scenarios(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[ScenarioDefinition(scenario_id="S1")],
    )
    res = compare_scenarios(req)
    assert isinstance(res, Phase3FComparisonOutput)
    assert res.scenario_count == 1


# ==============================================================================
# Comparison & Differencing Tests (Tests 13-17)
# ==============================================================================
def test_baseline_deltas_reported(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[ScenarioDefinition(scenario_id="S1", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=180.0))],
    )
    res = compare_phase3_scenarios(req)
    s1 = res.scenarios[0]
    assert s1.delta_fuel_pct_vs_baseline < 0.0
    assert s1.delta_cii_pct_vs_baseline < 0.0
    assert res.baseline_unassisted_fuel_cost_usd == pytest.approx(4120.5 * 1.15)


def test_pairwise_comparison_against_reference(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="LowClean", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=50.0)),
            ScenarioDefinition(scenario_id="HighClean", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=180.0)),
        ],
        reference_scenario_id="LowClean",
    )
    res = compare_phase3_scenarios(req)
    assert res.pairwise_comparisons is not None
    assert len(res.pairwise_comparisons) == 2

    high_delta = next(p for p in res.pairwise_comparisons if p.target_scenario_id == "HighClean")
    low_delta = next(p for p in res.pairwise_comparisons if p.target_scenario_id == "LowClean")

    # LowClean vs LowClean is 0
    assert low_delta.delta_net_fuel_cost_usd == pytest.approx(0.0)
    assert low_delta.delta_clean_energy_utilized_kwh == pytest.approx(0.0)

    # HighClean utilizes more clean energy and costs less than LowClean
    assert high_delta.delta_clean_energy_utilized_kwh == pytest.approx(180.0 - 50.0)
    assert high_delta.delta_net_fuel_cost_usd < 0.0
    assert high_delta.delta_net_co2_kg < 0.0
    assert high_delta.delta_net_cii < 0.0


# ==============================================================================
# Ranking Tests (Tests 18-25)
# ==============================================================================
def test_ranking_min_net_fuel_cost_usd(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="LowDemand", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=50.0)),
            ScenarioDefinition(scenario_id="HighDemand", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=180.0)),
        ],
        ranking_criterion="min_net_fuel_cost_usd",
    )
    res = compare_phase3_scenarios(req)
    assert res.ranked_scenario_ids is not None
    # HighDemand displaces more fuel -> lower net fuel cost -> ranked first
    assert res.ranked_scenario_ids == ["HighDemand", "LowDemand"]


def test_ranking_min_net_co2_kg(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S1_50kwh", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=50.0)),
            ScenarioDefinition(scenario_id="S2_180kwh", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=180.0)),
        ],
        ranking_criterion="min_net_co2_kg",
    )
    res = compare_phase3_scenarios(req)
    assert res.ranked_scenario_ids == ["S2_180kwh", "S1_50kwh"]


def test_ranking_min_net_fuel_L(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S1", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=20.0)),
            ScenarioDefinition(scenario_id="S2", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=150.0)),
        ],
        ranking_criterion="min_net_fuel_L",
    )
    res = compare_phase3_scenarios(req)
    assert res.ranked_scenario_ids == ["S2", "S1"]


def test_ranking_min_net_operational_cii(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="LowUtil", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=30.0)),
            ScenarioDefinition(scenario_id="HighUtil", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=160.0)),
        ],
        ranking_criterion="min_net_operational_cii",
    )
    res = compare_phase3_scenarios(req)
    assert res.ranked_scenario_ids == ["HighUtil", "LowUtil"]


def test_ranking_max_clean_energy_utilized_kwh(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S_low", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=40.0)),
            ScenarioDefinition(scenario_id="S_high", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=200.0)),
        ],
        ranking_criterion="max_clean_energy_utilized_kwh",
    )
    res = compare_phase3_scenarios(req)
    assert res.ranked_scenario_ids == ["S_high", "S_low"]


def test_ranking_max_fuel_displaced_L(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S_low", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=50.0)),
            ScenarioDefinition(scenario_id="S_high", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=180.0)),
        ],
        ranking_criterion="max_fuel_displaced_L",
    )
    res = compare_phase3_scenarios(req)
    assert res.ranked_scenario_ids == ["S_high", "S_low"]


def test_deterministic_tie_breaking(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    # Two scenarios with identical parameters will have identical metrics
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="Z_scenario"),
            ScenarioDefinition(scenario_id="A_scenario"),
        ],
        ranking_criterion="min_net_fuel_cost_usd",
    )
    res = compare_phase3_scenarios(req)
    # Identical cost -> tie-breaker orders alphanumerically by scenario_id
    assert res.ranked_scenario_ids == ["A_scenario", "Z_scenario"]


def test_no_criterion_no_ranking(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="Scenario_2"),
            ScenarioDefinition(scenario_id="Scenario_1"),
        ],
        ranking_criterion=None,
    )
    res = compare_phase3_scenarios(req)
    assert res.ranking_criterion is None
    assert res.ranked_scenario_ids is None
    # Scenarios output list preserves exact input order
    assert [s.scenario_id for s in res.scenarios] == ["Scenario_2", "Scenario_1"]


# ==============================================================================
# Feasibility & Invariants Tests (Tests 26-28)
# ==============================================================================
def test_feasibility_status_preserved(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S_feasible", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=100.0)),
            ScenarioDefinition(scenario_id="S_partial", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=10000.0)),
        ],
    )
    res = compare_phase3_scenarios(req)
    s_f = next(s for s in res.scenarios if s.scenario_id == "S_feasible")
    s_p = next(s for s in res.scenarios if s.scenario_id == "S_partial")
    assert s_f.feasibility_status == "FEASIBLE"
    assert s_p.feasibility_status == "PARTIAL"


def test_partial_not_silently_discarded(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="PartialScenario", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=5000.0)),
        ],
        ranking_criterion="min_net_fuel_cost_usd",
    )
    res = compare_phase3_scenarios(req)
    assert len(res.scenarios) == 1
    assert res.scenarios[0].feasibility_status == "PARTIAL"
    assert res.ranked_scenario_ids == ["PartialScenario"]


def test_curtailed_clean_energy_reporting(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="SmallDemand", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=50.0)),
        ],
    )
    res = compare_phase3_scenarios(req)
    s = res.scenarios[0]
    total_avail = s.phase3_output.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh
    assert s.clean_energy_curtailed_kwh == pytest.approx(total_avail - 50.0)


# ==============================================================================
# Determinism & Model Integrity Tests (Tests 29-31)
# ==============================================================================
def test_pairwise_deltas_explicit_math(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S_ref", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=100.0)),
            ScenarioDefinition(scenario_id="S_target", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=200.0)),
        ],
        reference_scenario_id="S_ref",
    )
    res = compare_phase3_scenarios(req)
    target_delta = next(p for p in res.pairwise_comparisons if p.target_scenario_id == "S_target")
    s_ref = next(s for s in res.scenarios if s.scenario_id == "S_ref")
    s_target = next(s for s in res.scenarios if s.scenario_id == "S_target")

    assert target_delta.delta_net_fuel_cost_usd == pytest.approx(
        s_target.net_assisted_fuel_cost_usd - s_ref.net_assisted_fuel_cost_usd
    )
    assert target_delta.delta_net_co2_kg == pytest.approx(
        s_target.net_assisted_co2_kg - s_ref.net_assisted_co2_kg
    )
    assert target_delta.delta_net_fuel_L == pytest.approx(
        s_target.net_assisted_fuel_L - s_ref.net_assisted_fuel_L
    )
    assert target_delta.delta_net_cii == pytest.approx(
        s_target.net_assisted_operational_cii - s_ref.net_assisted_operational_cii
    )


def test_scenario_ghi_override_takes_precedence(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=2.0,  # Request-level low GHI
        scenarios=[
            ScenarioDefinition(scenario_id="LowGHI"),
            ScenarioDefinition(scenario_id="HighGHI", overrides=ScenarioOverride(daily_ghi_kwh_per_m2=6.0)),
        ],
    )
    res = compare_phase3_scenarios(req)
    s_low = next(s for s in res.scenarios if s.scenario_id == "LowGHI")
    s_high = next(s for s in res.scenarios if s.scenario_id == "HighGHI")
    assert s_high.phase3_output.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh > \
           s_low.phase3_output.tier_3_clean_energy_feasibility.estimated_solar_energy_kwh


def test_conservation_invariants_hold_across_all_scenarios(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="ZeroAux", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=0.0)),
            ScenarioDefinition(scenario_id="NormalAux", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=150.0)),
            ScenarioDefinition(scenario_id="LargeAux", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=5000.0)),
        ],
    )
    res = compare_phase3_scenarios(req)
    baseline_fuel = base_tier1_predictions.fuel_consumption_L.value
    baseline_co2 = base_tier1_predictions.co2_emissions_kg.value

    for s in res.scenarios:
        assert s.estimated_fuel_displaced_L <= baseline_fuel + 1e-6
        assert s.estimated_co2_displaced_kg <= baseline_co2 + 1e-6
        assert s.clean_energy_utilized_kwh <= s.auxiliary_energy_demand_kwh + 1e-6
        assert s.net_assisted_fuel_L >= 0.0
        assert s.net_assisted_co2_kg >= 0.0
        assert s.net_assisted_fuel_cost_usd >= 0.0
        assert s.net_assisted_operational_cii >= 0.0


def test_frozen_model_hashes_verified():
    from phase3_contracts import FROZEN_MODEL_HASHES
    expected = {
        "weather_final.joblib": "39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3",
        "fuel_xgb.joblib": "cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323",
        "battery_soc_lstm.pt": "c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25",
        "battery_soh_final.joblib": "9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1",
    }
    assert FROZEN_MODEL_HASHES == expected


def test_scenario_error_annotated_with_scenario_id(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=None,  # Force route lookup
        route_id="Escravos-Lagos",
        month="January",
        scenarios=[
            ScenarioDefinition(scenario_id="BadScenario", overrides=ScenarioOverride(route_id="NonExistentCorridor")),
        ],
    )
    with pytest.raises(ValueError) as exc:
        compare_phase3_scenarios(req)
    assert "Scenario 'BadScenario' evaluation failed" in str(exc.value)


def test_repeated_identical_evaluation_deterministic(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    req = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=base_tier1_predictions,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=[
            ScenarioDefinition(scenario_id="S1"),
            ScenarioDefinition(scenario_id="S2", overrides=ScenarioOverride(auxiliary_energy_demand_kwh=100.0)),
        ],
        ranking_criterion="min_net_fuel_cost_usd",
        reference_scenario_id="S1",
    )
    out1 = compare_phase3_scenarios(req)
    out2 = compare_phase3_scenarios(req)
    assert out1.model_dump() == out2.model_dump()


# ==============================================================================
# Weather Invariance Boundary Test
# ==============================================================================
def test_phase3f_comparison_weather_invariance(base_voyage_metadata, base_tier1_predictions, base_scenario_params):
    """
    Verify that multi-scenario comparison evaluations are strictly invariant to
    weather variations. Changing predicted weather does not affect scenario metrics,
    pairwise deltas, clean energy utilization, displacements, or ranking.
    """
    t1_calm_dict = base_tier1_predictions.model_dump()
    t1_calm_dict["weather"] = {
        "temperature_c": 28.0,
        "wind_speed_knots": 5.0,
        "significant_wave_height_m": 0.3,
    }
    t1_calm = Tier1Phase2Predictions.model_validate(t1_calm_dict)

    t1_storm_dict = base_tier1_predictions.model_dump()
    t1_storm_dict["weather"] = {
        "temperature_c": 1.0,
        "wind_speed_knots": 52.0,
        "significant_wave_height_m": 10.5,
    }
    t1_storm = Tier1Phase2Predictions.model_validate(t1_storm_dict)

    scenarios = [
        ScenarioDefinition(scenario_id="S1_Base", description="Baseline auxiliary load"),
        ScenarioDefinition(
            scenario_id="S2_HighAux",
            description="High auxiliary load",
            overrides=ScenarioOverride(auxiliary_energy_demand_kwh=300.0),
        ),
        ScenarioDefinition(
            scenario_id="S3_LowReserve",
            description="Lower battery reserve",
            overrides=ScenarioOverride(soc_reserve=0.10),
        ),
    ]

    req_calm = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=t1_calm,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=scenarios,
        reference_scenario_id="S1_Base",
        ranking_criterion="min_net_fuel_cost_usd",
    )

    req_storm = Phase3FComparisonRequest(
        voyage_metadata=base_voyage_metadata,
        tier_1_phase2_predictions=t1_storm,
        base_scenario_parameters=base_scenario_params,
        daily_ghi_kwh_per_m2=5.0,
        scenarios=scenarios,
        reference_scenario_id="S1_Base",
        ranking_criterion="min_net_fuel_cost_usd",
    )

    out_calm = compare_phase3_scenarios(req_calm)
    out_storm = compare_phase3_scenarios(req_storm)

    # 1. Ranking order and ranking criteria are identical
    assert out_calm.ranked_scenario_ids == out_storm.ranked_scenario_ids
    assert out_calm.ranking_criterion == out_storm.ranking_criterion
    assert out_calm.scenario_count == out_storm.scenario_count

    # 2. Scenario results match
    assert len(out_calm.scenarios) == len(out_storm.scenarios)
    for res_c, res_s in zip(out_calm.scenarios, out_storm.scenarios):
        assert res_c.scenario_id == res_s.scenario_id
        assert res_c.feasibility_status == res_s.feasibility_status
        assert res_c.clean_energy_utilized_kwh == res_s.clean_energy_utilized_kwh
        assert res_c.clean_energy_curtailed_kwh == res_s.clean_energy_curtailed_kwh
        assert res_c.estimated_fuel_displaced_L == res_s.estimated_fuel_displaced_L
        assert res_c.estimated_co2_displaced_kg == res_s.estimated_co2_displaced_kg
        assert res_c.net_assisted_fuel_L == res_s.net_assisted_fuel_L
        assert res_c.net_assisted_fuel_cost_usd == res_s.net_assisted_fuel_cost_usd
        assert res_c.net_assisted_co2_kg == res_s.net_assisted_co2_kg
        assert res_c.net_assisted_operational_cii == res_s.net_assisted_operational_cii
        assert res_c.delta_fuel_pct_vs_baseline == res_s.delta_fuel_pct_vs_baseline
        assert res_c.delta_cii_pct_vs_baseline == res_s.delta_cii_pct_vs_baseline

    # 3. Pairwise comparisons match
    assert len(out_calm.pairwise_comparisons) == len(out_storm.pairwise_comparisons)
    for pw_c, pw_s in zip(out_calm.pairwise_comparisons, out_storm.pairwise_comparisons):
        assert pw_c.target_scenario_id == pw_s.target_scenario_id
        assert pw_c.reference_scenario_id == pw_s.reference_scenario_id
        assert pw_c.delta_net_fuel_cost_usd == pw_s.delta_net_fuel_cost_usd
        assert pw_c.delta_net_co2_kg == pw_s.delta_net_co2_kg
        assert pw_c.delta_net_fuel_L == pw_s.delta_net_fuel_L
        assert pw_c.delta_net_cii == pw_s.delta_net_cii
        assert pw_c.delta_clean_energy_utilized_kwh == pw_s.delta_clean_energy_utilized_kwh

