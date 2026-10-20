"""
phase3f_comparison.py — Maritime Grid Simulation, Phase 3F Comparative Analysis Layer
=====================================================================================
Multi-Scenario Comparative Analysis Layer for Phase 3 Decision Coordinator.

This module evaluates multiple explicitly parameterized scenarios for a single voyage
by delegating to Phase 3E (orchestrate_phase3_voyage), computes comparative deltas
against baseline and optional reference scenarios, and provides deterministic single-criterion
ranking without introducing optimization heuristics, black-box search, or new ML models.

CRITICAL ARCHITECTURAL BOUNDARIES:
  - Phase 3F is an ANALYTICAL AGGREGATOR and COMPARISON layer only.
  - Phase 3F performs NO machine learning inference, training, or tuning.
  - Phase 3F does NOT implement autonomous control, dispatch, or search optimization.
  - Phase 3F delegates 100% of physical and economic evaluations to Phase 3E.
  - Phase 3F preserves all conservation invariants and feasibility statuses (FEASIBLE / PARTIAL).
"""

from typing import Dict, List, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, model_validator

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    AppliedScenarioParameters,
    AuditMetadata,
    Phase3Output,
)
from phase3_coordinator import orchestrate_phase3_voyage


# ==============================================================================
# Supported Ranking Criteria
# ==============================================================================
RankingCriterion = Literal[
    "min_net_fuel_cost_usd",
    "min_net_co2_kg",
    "min_net_fuel_L",
    "min_net_operational_cii",
    "max_clean_energy_utilized_kwh",
    "max_fuel_displaced_L",
]


# ==============================================================================
# Input Contracts
# ==============================================================================
class ScenarioOverride(BaseModel):
    """Scenario-specific parameter overrides applied over base scenario parameters."""
    auxiliary_energy_demand_kwh: Optional[float] = Field(default=None, ge=0.0)
    fuel_price_usd_per_l: Optional[float] = Field(default=None, ge=0.0)
    initial_soc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    soc_reserve: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    generator_sfoc_kg_per_kwh: Optional[float] = Field(default=None, gt=0.0)
    fuel_density_kg_per_l: Optional[float] = Field(default=None, gt=0.0)
    emission_factor_kgco2_per_kgfuel: Optional[float] = Field(default=None, gt=0.0)
    solar_derate_factor: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    route_id: Optional[str] = None
    month: Optional[Union[str, int]] = None
    daily_ghi_kwh_per_m2: Optional[float] = Field(default=None, ge=0.0)


class ScenarioDefinition(BaseModel):
    """Specification of an individual candidate scenario."""
    scenario_id: str = Field(..., min_length=1, description="Unique alphanumeric scenario identifier")
    description: Optional[str] = Field(default=None, description="Human-readable scenario description")
    overrides: ScenarioOverride = Field(default_factory=ScenarioOverride)


class Phase3FComparisonRequest(BaseModel):
    """Master input schema for Phase 3F multi-scenario evaluation."""
    voyage_metadata: VoyageMetadata
    tier_1_phase2_predictions: Tier1Phase2Predictions
    base_scenario_parameters: AppliedScenarioParameters
    route_id: Optional[str] = None
    month: Optional[Union[str, int]] = None
    daily_ghi_kwh_per_m2: Optional[float] = None
    scenarios: List[ScenarioDefinition] = Field(..., min_length=1)
    ranking_criterion: Optional[RankingCriterion] = None
    reference_scenario_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_request_integrity(self) -> "Phase3FComparisonRequest":
        """Validate scenario collection constraints and reference ID resolution."""
        # 1. Ensure scenario IDs are unique
        ids = [s.scenario_id for s in self.scenarios]
        if len(ids) != len(set(ids)):
            duplicates = [sid for sid in set(ids) if ids.count(sid) > 1]
            raise ValueError(f"Duplicate scenario_id detected in scenarios list: {duplicates}")

        # 2. Ensure reference_scenario_id exists in defined scenarios if supplied
        if self.reference_scenario_id is not None:
            if self.reference_scenario_id not in ids:
                raise ValueError(
                    f"reference_scenario_id '{self.reference_scenario_id}' not found in defined scenarios: {ids}"
                )

        return self


# ==============================================================================
# Output Contracts
# ==============================================================================
class ScenarioEvaluationSummary(BaseModel):
    """Performance summary of a single evaluated scenario."""
    scenario_id: str
    feasibility_status: Literal["FEASIBLE", "PARTIAL"]
    auxiliary_energy_demand_kwh: float
    clean_energy_utilized_kwh: float
    clean_energy_curtailed_kwh: float
    energy_deficit_kwh: float
    estimated_fuel_displaced_L: float
    estimated_co2_displaced_kg: float
    net_assisted_fuel_L: float
    net_assisted_co2_kg: float
    net_assisted_fuel_cost_usd: float
    net_assisted_operational_cii: float
    delta_fuel_pct_vs_baseline: float
    delta_cii_pct_vs_baseline: float
    resolved_fuel_price_usd_per_l: float
    phase3_output: Phase3Output


class PairwiseComparisonDelta(BaseModel):
    """Pairwise performance differential between a target scenario and the reference scenario."""
    target_scenario_id: str
    reference_scenario_id: str
    delta_net_fuel_cost_usd: float          # target - reference
    delta_net_co2_kg: float                 # target - reference
    delta_net_fuel_L: float                 # target - reference
    delta_net_cii: float                    # target - reference
    delta_clean_energy_utilized_kwh: float  # target - reference


class Phase3FComparisonOutput(BaseModel):
    """Complete Phase 3F comparative evaluation output payload."""
    voyage_id: str
    ship_type: str
    scenario_count: int
    scenarios: List[ScenarioEvaluationSummary]
    baseline_unassisted_fuel_cost_usd: float
    baseline_unassisted_cii: float
    ranking_criterion: Optional[RankingCriterion] = None
    ranked_scenario_ids: Optional[List[str]] = None
    pairwise_comparisons: Optional[List[PairwiseComparisonDelta]] = None
    audit_metadata: AuditMetadata = Field(default_factory=AuditMetadata)


# ==============================================================================
# Master Execution Function
# ==============================================================================
def compare_phase3_scenarios(
    request: Union[Phase3FComparisonRequest, Dict[str, Any]],
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> Phase3FComparisonOutput:
    """
    Execute comparative analysis across a finite list of explicit Phase 3E scenarios.

    Precedence Hierarchy:
      Scenario Override -> Base Scenario Parameter -> Sourced default in Phase 3E

    GHI/Route Resolution:
      Scenario GHI -> Request GHI -> Scenario Route/Month -> Request Route/Month -> Phase 3E lookup

    Delegation:
      Calls orchestrate_phase3_voyage exactly once per scenario.
    """
    # Validate request contract
    req = (
        Phase3FComparisonRequest.model_validate(request)
        if isinstance(request, dict)
        else request
    )

    evaluated_summaries: List[ScenarioEvaluationSummary] = []
    baseline_cost: Optional[float] = None
    baseline_cii: Optional[float] = None

    for scenario_def in req.scenarios:
        sid = scenario_def.scenario_id
        ov = scenario_def.overrides

        # Parameter resolution: Override -> Base -> Sourced default
        resolved_aux = (
            ov.auxiliary_energy_demand_kwh
            if ov.auxiliary_energy_demand_kwh is not None
            else req.base_scenario_parameters.auxiliary_energy_demand_kwh
        )
        resolved_price = (
            ov.fuel_price_usd_per_l
            if ov.fuel_price_usd_per_l is not None
            else req.base_scenario_parameters.fuel_price_usd_per_l
        )
        resolved_initial_soc = (
            ov.initial_soc
            if ov.initial_soc is not None
            else req.base_scenario_parameters.initial_soc
        )
        resolved_soc_reserve = (
            ov.soc_reserve
            if ov.soc_reserve is not None
            else req.base_scenario_parameters.soc_reserve
        )
        resolved_sfoc = (
            ov.generator_sfoc_kg_per_kwh
            if ov.generator_sfoc_kg_per_kwh is not None
            else req.base_scenario_parameters.generator_sfoc_kg_per_kwh
        )
        resolved_density = (
            ov.fuel_density_kg_per_l
            if ov.fuel_density_kg_per_l is not None
            else req.base_scenario_parameters.fuel_density_kg_per_l
        )
        resolved_ef = (
            ov.emission_factor_kgco2_per_kgfuel
            if ov.emission_factor_kgco2_per_kgfuel is not None
            else req.base_scenario_parameters.emission_factor_kgco2_per_kgfuel
        )
        resolved_derate = (
            ov.solar_derate_factor
            if ov.solar_derate_factor is not None
            else req.base_scenario_parameters.solar_derate_factor
        )

        # Route / Month / GHI Resolution
        if ov.daily_ghi_kwh_per_m2 is not None:
            resolved_ghi = ov.daily_ghi_kwh_per_m2
            resolved_route = None
            resolved_month = None
        elif req.daily_ghi_kwh_per_m2 is not None:
            resolved_ghi = req.daily_ghi_kwh_per_m2
            resolved_route = None
            resolved_month = None
        else:
            resolved_ghi = None
            resolved_route = ov.route_id if ov.route_id is not None else req.route_id
            resolved_month = ov.month if ov.month is not None else req.month

        # Delegate evaluation strictly to Phase 3E orchestrator
        try:
            p3_output: Phase3Output = orchestrate_phase3_voyage(
                voyage_metadata=req.voyage_metadata,
                tier1_predictions=req.tier_1_phase2_predictions,
                auxiliary_energy_demand_kwh=resolved_aux,
                route_id=resolved_route,
                month=resolved_month,
                daily_ghi_kwh_per_m2=resolved_ghi,
                fuel_price_override_usd_per_l=resolved_price,
                initial_soc=resolved_initial_soc,
                soc_reserve=resolved_soc_reserve,
                generator_sfoc_kg_per_kwh=resolved_sfoc,
                fuel_density_kg_per_l=resolved_density,
                emission_factor_kgco2_per_kgfuel=resolved_ef,
                solar_derate_factor=resolved_derate,
                ship_profiles_csv=ship_profiles_csv,
                climatology_csv=climatology_csv,
            )
        except Exception as exc:
            raise ValueError(f"Scenario '{sid}' evaluation failed: {exc}") from exc

        # Extract baseline metrics (identical across scenarios with common Tier 1/Tier 2)
        if baseline_cost is None:
            baseline_cost = p3_output.tier_2_baseline_metrics.baseline_fuel_cost_usd
            baseline_cii = p3_output.tier_2_baseline_metrics.baseline_operational_cii_gco2_per_dwt_nm

        # Curtailed clean energy calculation
        avail_energy = p3_output.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh
        util_energy = p3_output.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh
        curtailed_energy = max(0.0, float(avail_energy - util_energy))

        # Build scenario summary
        summary = ScenarioEvaluationSummary(
            scenario_id=sid,
            feasibility_status=p3_output.tier_3_clean_energy_feasibility.feasibility_status,
            auxiliary_energy_demand_kwh=p3_output.tier_3_clean_energy_feasibility.auxiliary_energy_demand_kwh,
            clean_energy_utilized_kwh=util_energy,
            clean_energy_curtailed_kwh=curtailed_energy,
            energy_deficit_kwh=p3_output.tier_3_clean_energy_feasibility.energy_deficit_kwh,
            estimated_fuel_displaced_L=p3_output.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L,
            estimated_co2_displaced_kg=p3_output.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg,
            net_assisted_fuel_L=p3_output.tier_4_engineering_scenario_estimates.net_assisted_fuel_L,
            net_assisted_co2_kg=p3_output.tier_4_engineering_scenario_estimates.net_assisted_co2_kg,
            net_assisted_fuel_cost_usd=p3_output.tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd,
            net_assisted_operational_cii=p3_output.tier_4_engineering_scenario_estimates.net_assisted_operational_cii_gco2_per_dwt_nm,
            delta_fuel_pct_vs_baseline=p3_output.tier_4_engineering_scenario_estimates.delta_fuel_pct,
            delta_cii_pct_vs_baseline=p3_output.tier_4_engineering_scenario_estimates.delta_cii_pct,
            resolved_fuel_price_usd_per_l=p3_output.tier_2_baseline_metrics.fuel_price_usd_per_l,
            phase3_output=p3_output,
        )
        evaluated_summaries.append(summary)

    # Pairwise comparison against reference scenario (if specified)
    pairwise_deltas: Optional[List[PairwiseComparisonDelta]] = None
    if req.reference_scenario_id is not None:
        ref_summary = next(
            s for s in evaluated_summaries if s.scenario_id == req.reference_scenario_id
        )
        pairwise_deltas = []
        for target in evaluated_summaries:
            pairwise_deltas.append(
                PairwiseComparisonDelta(
                    target_scenario_id=target.scenario_id,
                    reference_scenario_id=ref_summary.scenario_id,
                    delta_net_fuel_cost_usd=float(target.net_assisted_fuel_cost_usd - ref_summary.net_assisted_fuel_cost_usd),
                    delta_net_co2_kg=float(target.net_assisted_co2_kg - ref_summary.net_assisted_co2_kg),
                    delta_net_fuel_L=float(target.net_assisted_fuel_L - ref_summary.net_assisted_fuel_L),
                    delta_net_cii=float(target.net_assisted_operational_cii - ref_summary.net_assisted_operational_cii),
                    delta_clean_energy_utilized_kwh=float(target.clean_energy_utilized_kwh - ref_summary.clean_energy_utilized_kwh),
                )
            )

    # Ranking by explicit criterion (if specified)
    ranked_ids: Optional[List[str]] = None
    if req.ranking_criterion is not None:
        criterion = req.ranking_criterion
        if criterion == "min_net_fuel_cost_usd":
            sorted_summaries = sorted(evaluated_summaries, key=lambda s: (s.net_assisted_fuel_cost_usd, s.scenario_id))
        elif criterion == "min_net_co2_kg":
            sorted_summaries = sorted(evaluated_summaries, key=lambda s: (s.net_assisted_co2_kg, s.scenario_id))
        elif criterion == "min_net_fuel_L":
            sorted_summaries = sorted(evaluated_summaries, key=lambda s: (s.net_assisted_fuel_L, s.scenario_id))
        elif criterion == "min_net_operational_cii":
            sorted_summaries = sorted(evaluated_summaries, key=lambda s: (s.net_assisted_operational_cii, s.scenario_id))
        elif criterion == "max_clean_energy_utilized_kwh":
            sorted_summaries = sorted(evaluated_summaries, key=lambda s: (-s.clean_energy_utilized_kwh, s.scenario_id))
        elif criterion == "max_fuel_displaced_L":
            sorted_summaries = sorted(evaluated_summaries, key=lambda s: (-s.estimated_fuel_displaced_L, s.scenario_id))
        else:
            raise ValueError(f"Unsupported ranking criterion: '{criterion}'")
        ranked_ids = [s.scenario_id for s in sorted_summaries]

    voyage_id = f"{req.voyage_metadata.ship_type}_{req.voyage_metadata.distance_nm:.1f}nm"

    return Phase3FComparisonOutput(
        voyage_id=voyage_id,
        ship_type=req.voyage_metadata.ship_type,
        scenario_count=len(evaluated_summaries),
        scenarios=evaluated_summaries,
        baseline_unassisted_fuel_cost_usd=baseline_cost or 0.0,
        baseline_unassisted_cii=baseline_cii or 0.0,
        ranking_criterion=req.ranking_criterion,
        ranked_scenario_ids=ranked_ids,
        pairwise_comparisons=pairwise_deltas,
        audit_metadata=AuditMetadata(),
    )


def compare_scenarios(
    request: Union[Phase3FComparisonRequest, Dict[str, Any]],
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> Phase3FComparisonOutput:
    """Convenience alias for compare_phase3_scenarios."""
    return compare_phase3_scenarios(
        request=request,
        ship_profiles_csv=ship_profiles_csv,
        climatology_csv=climatology_csv,
    )
