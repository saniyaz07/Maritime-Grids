"""
phase3g_fleet.py — Maritime Grid Simulation, Phase 3G Fleet & Annual Schedule Aggregation
========================================================================================
Implementation of the Fleet & Annual Multi-Voyage Schedule Aggregation Layer.

This module evaluates multi-voyage operational schedules for maritime vessels by:
  1. Ingesting ordered schedules of discrete voyages (VoyageScheduleEntry).
  2. Delegating single-voyage physical and economic evaluations to Phase 3E (orchestrate_phase3_voyage).
  3. Accumulating transport work, baseline fuel, baseline CO2, clean energy, and displacements.
  4. Calculating annual operational Carbon Intensity Indicator (CII) per IMO Resolution MEPC.352(78)
     strictly from cumulative transport work (sum CO2 * 1000 / sum(DWT * distance)).
  5. Enforcing exact conservation identities across cumulative sums.
  6. Preserving single-voyage feasibility statuses (FEASIBLE vs. PARTIAL) and evaluation traces.

CRITICAL ARCHITECTURAL BOUNDARIES:
  - Phase 3G is an AGGREGATION layer over verified Phase 3E single-voyage evaluations.
  - Phase 3G performs NO machine learning inference, model loading, training, or tuning.
  - Phase 3G does NOT implement autonomous control, speed governing, or route optimization.
  - Phase 3G delegates 100% of single-voyage evaluations to Phase 3E.
  - Annual CII is calculated strictly from cumulative transport work, NEVER by arithmetic averaging.
"""

from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field, model_validator

from phase3_contracts import (
    VoyageMetadata,
    Tier1Phase2Predictions,
    AppliedScenarioParameters,
    AuditMetadata,
    Phase3Output,
)
from phase3_coordinator import orchestrate_phase3_voyage
from phase3f_comparison import ScenarioOverride


# ==============================================================================
# Input Contracts
# ==============================================================================
class VoyageScheduleEntry(BaseModel):
    """Specification of an individual scheduled voyage within an annual schedule."""
    voyage_id: str = Field(..., min_length=1, description="Unique voyage identifier within the schedule")
    voyage_metadata: VoyageMetadata = Field(..., description="Vessel transit parameters (DWT, distance, duration)")
    tier_1_phase2_predictions: Tier1Phase2Predictions = Field(..., description="Authoritative frozen Phase 2 predictions for this voyage")
    route_id: str = Field(..., min_length=1, description="Commercial shipping corridor (e.g. 'Escravos-Lagos')")
    month: Union[str, int] = Field(..., description="Operating month (name or integer 1-12) for climatological solar lookup")
    scenario_overrides: Optional[ScenarioOverride] = Field(default=None, description="Optional voyage-specific scenario parameter overrides")


class AnnualFleetEvaluationRequest(BaseModel):
    """Input contract for multi-voyage schedule evaluation."""
    vessel_id: str = Field(..., min_length=1, description="Unique vessel tracking identifier")
    schedule: List[VoyageScheduleEntry] = Field(..., min_length=1, description="Ordered collection of scheduled voyages")
    base_scenario_parameters: AppliedScenarioParameters = Field(..., description="Default scenario parameters applied across the schedule")
    ship_profiles_csv: Optional[str] = Field(default=None, description="Optional custom path to ship_profiles.csv")
    climatology_csv: Optional[str] = Field(default=None, description="Optional custom path to nasa_monthly_climatology.csv")

    @model_validator(mode="after")
    def validate_schedule_integrity(self) -> "AnnualFleetEvaluationRequest":
        """Validate non-empty schedule, unique voyage IDs, and consistent vessel ship_type."""
        if not self.schedule:
            raise ValueError("schedule must contain at least one VoyageScheduleEntry")

        # 1. Ensure voyage IDs are unique
        v_ids = [entry.voyage_id for entry in self.schedule]
        if len(v_ids) != len(set(v_ids)):
            duplicates = [vid for vid in set(v_ids) if v_ids.count(vid) > 1]
            raise ValueError(f"Duplicate voyage_id detected in schedule: {duplicates}")

        # 2. Ensure consistent ship_type across the single-vessel schedule
        expected_ship_type = self.schedule[0].voyage_metadata.ship_type
        for entry in self.schedule:
            if entry.voyage_metadata.ship_type != expected_ship_type:
                raise ValueError(
                    f"Inconsistent ship_type in single-vessel schedule: expected '{expected_ship_type}', "
                    f"got '{entry.voyage_metadata.ship_type}' in voyage '{entry.voyage_id}'"
                )

        return self


# ==============================================================================
# Output Contract
# ==============================================================================
class AnnualScheduleSummary(BaseModel):
    """Aggregated operational, financial, and environmental metrics for an annual schedule."""
    vessel_id: str
    ship_type: str
    total_voyages: int
    total_distance_nm: float
    total_duration_hours: float
    total_transport_work_dwt_nm: float

    # Cumulative baseline totals
    total_baseline_fuel_L: float
    total_baseline_fuel_cost_usd: float
    total_baseline_co2_kg: float
    annual_baseline_operational_cii: float

    # Cumulative clean energy metrics
    total_clean_energy_utilized_kwh: float
    total_clean_energy_curtailed_kwh: float

    # Cumulative displacement totals
    total_fuel_displaced_L: float
    total_co2_displaced_kg: float

    # Cumulative net assisted totals
    total_assisted_fuel_L: float
    total_assisted_fuel_cost_usd: float
    total_assisted_co2_kg: float
    annual_assisted_operational_cii: float

    # Annual relative percentage changes
    annual_delta_fuel_pct: float
    annual_delta_cost_pct: float
    annual_delta_cii_pct: float

    # Feasibility auditing
    feasible_voyage_count: int
    partial_voyage_count: int

    # Traceability trace
    voyage_evaluations: List[Phase3Output]
    audit_metadata: AuditMetadata = Field(default_factory=AuditMetadata)


# ==============================================================================
# Primary Public API
# ==============================================================================
def evaluate_annual_fleet_schedule(
    request: Union[AnnualFleetEvaluationRequest, Dict[str, Any]],
    ship_profiles_csv: Optional[str] = None,
    climatology_csv: Optional[str] = None,
) -> AnnualScheduleSummary:
    """
    Evaluate an annual multi-voyage operational schedule for a vessel.

    Delegates each scheduled voyage to orchestrate_phase3_voyage, validates
    cross-tier outputs, accumulates transport work and emissions, and derives
    IMO MEPC.352(78) compliant annual baseline and assisted operational CII.

    Parameters:
      request: AnnualFleetEvaluationRequest instance or dict
      ship_profiles_csv: Optional custom path to ship_profiles.csv
      climatology_csv: Optional custom path to nasa_monthly_climatology.csv

    Returns:
      AnnualScheduleSummary instance conforming to the frozen output contract.
    """
    req = (
        AnnualFleetEvaluationRequest.model_validate(request)
        if isinstance(request, dict)
        else request
    )

    profiles_csv = ship_profiles_csv or req.ship_profiles_csv
    clim_csv = climatology_csv or req.climatology_csv

    voyage_outputs: List[Phase3Output] = []

    # ─── STEP 1: Execute single-voyage evaluations via Phase 3E ────────────────
    for entry in req.schedule:
        ov = entry.scenario_overrides

        # Parameter resolution: Override -> Base Scenario Parameter
        resolved_aux = (
            ov.auxiliary_energy_demand_kwh
            if ov and ov.auxiliary_energy_demand_kwh is not None
            else req.base_scenario_parameters.auxiliary_energy_demand_kwh
        )
        resolved_price = (
            ov.fuel_price_usd_per_l
            if ov and ov.fuel_price_usd_per_l is not None
            else req.base_scenario_parameters.fuel_price_usd_per_l
        )
        resolved_initial_soc = (
            ov.initial_soc
            if ov and ov.initial_soc is not None
            else req.base_scenario_parameters.initial_soc
        )
        resolved_soc_reserve = (
            ov.soc_reserve
            if ov and ov.soc_reserve is not None
            else req.base_scenario_parameters.soc_reserve
        )
        resolved_sfoc = (
            ov.generator_sfoc_kg_per_kwh
            if ov and ov.generator_sfoc_kg_per_kwh is not None
            else req.base_scenario_parameters.generator_sfoc_kg_per_kwh
        )
        resolved_density = (
            ov.fuel_density_kg_per_l
            if ov and ov.fuel_density_kg_per_l is not None
            else req.base_scenario_parameters.fuel_density_kg_per_l
        )
        resolved_ef = (
            ov.emission_factor_kgco2_per_kgfuel
            if ov and ov.emission_factor_kgco2_per_kgfuel is not None
            else req.base_scenario_parameters.emission_factor_kgco2_per_kgfuel
        )
        resolved_derate = (
            ov.solar_derate_factor
            if ov and ov.solar_derate_factor is not None
            else req.base_scenario_parameters.solar_derate_factor
        )

        # Route / Month / GHI Resolution
        if ov and ov.daily_ghi_kwh_per_m2 is not None:
            resolved_ghi = ov.daily_ghi_kwh_per_m2
            resolved_route = None
            resolved_month = None
        else:
            resolved_ghi = None
            resolved_route = (ov.route_id if ov and ov.route_id is not None else entry.route_id)
            resolved_month = (ov.month if ov and ov.month is not None else entry.month)

        try:
            p3_output: Phase3Output = orchestrate_phase3_voyage(
                voyage_metadata=entry.voyage_metadata,
                tier1_predictions=entry.tier_1_phase2_predictions,
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
                ship_profiles_csv=profiles_csv,
                climatology_csv=clim_csv,
            )
        except Exception as exc:
            raise ValueError(f"Voyage '{entry.voyage_id}' evaluation failed: {exc}") from exc

        voyage_outputs.append(p3_output)

    # ─── STEP 2: Aggregate cumulative quantities ──────────────────────────────
    total_distance_nm = 0.0
    total_duration_hours = 0.0
    total_transport_work_dwt_nm = 0.0

    total_baseline_fuel_L = 0.0
    total_baseline_fuel_cost_usd = 0.0
    total_baseline_co2_kg = 0.0

    total_clean_energy_utilized_kwh = 0.0
    total_clean_energy_curtailed_kwh = 0.0

    total_fuel_displaced_L = 0.0
    total_co2_displaced_kg = 0.0

    total_assisted_fuel_L = 0.0
    total_assisted_fuel_cost_usd = 0.0
    total_assisted_co2_kg = 0.0

    feasible_count = 0
    partial_count = 0

    for out in voyage_outputs:
        d = float(out.voyage_metadata.distance_nm)
        dur = float(out.voyage_metadata.voyage_duration_hours)
        dwt = float(out.voyage_metadata.deadweight_tonnes)
        w = dwt * d

        total_distance_nm += d
        total_duration_hours += dur
        total_transport_work_dwt_nm += w

        total_baseline_fuel_L += float(out.tier_1_phase2_predictions.fuel_consumption_L.value)
        total_baseline_fuel_cost_usd += float(out.tier_2_baseline_metrics.baseline_fuel_cost_usd)
        total_baseline_co2_kg += float(out.tier_1_phase2_predictions.co2_emissions_kg.value)

        e_util = float(out.tier_3_clean_energy_feasibility.clean_energy_utilized_kwh)
        e_avail = float(out.tier_3_clean_energy_feasibility.total_clean_energy_available_kwh)
        e_curt = max(0.0, e_avail - e_util)

        total_clean_energy_utilized_kwh += e_util
        total_clean_energy_curtailed_kwh += e_curt

        total_fuel_displaced_L += float(out.tier_4_engineering_scenario_estimates.estimated_fuel_displaced_L)
        total_co2_displaced_kg += float(out.tier_4_engineering_scenario_estimates.estimated_co2_displaced_kg)

        total_assisted_fuel_L += float(out.tier_4_engineering_scenario_estimates.net_assisted_fuel_L)
        total_assisted_fuel_cost_usd += float(out.tier_4_engineering_scenario_estimates.net_assisted_fuel_cost_usd)
        total_assisted_co2_kg += float(out.tier_4_engineering_scenario_estimates.net_assisted_co2_kg)

        if out.tier_3_clean_energy_feasibility.feasibility_status == "FEASIBLE":
            feasible_count += 1
        elif out.tier_3_clean_energy_feasibility.feasibility_status == "PARTIAL":
            partial_count += 1

    # ─── STEP 3: Enforce Conservation Invariants ──────────────────────────────
    TOLERANCE = 1e-4

    # Exact fuel conservation
    if abs((total_assisted_fuel_L + total_fuel_displaced_L) - total_baseline_fuel_L) > TOLERANCE:
        raise ValueError(
            f"Annual fuel conservation violated: assisted ({total_assisted_fuel_L}) + "
            f"displaced ({total_fuel_displaced_L}) != baseline ({total_baseline_fuel_L})"
        )

    # Exact CO2 conservation
    if abs((total_assisted_co2_kg + total_co2_displaced_kg) - total_baseline_co2_kg) > TOLERANCE:
        raise ValueError(
            f"Annual CO2 conservation violated: assisted ({total_assisted_co2_kg}) + "
            f"displaced ({total_co2_displaced_kg}) != baseline ({total_baseline_co2_kg})"
        )

    # Displacement upper bounds
    if total_fuel_displaced_L > total_baseline_fuel_L + TOLERANCE:
        raise ValueError(f"Total fuel displaced ({total_fuel_displaced_L}) exceeds baseline ({total_baseline_fuel_L})")

    if total_co2_displaced_kg > total_baseline_co2_kg + TOLERANCE:
        raise ValueError(f"Total CO2 displaced ({total_co2_displaced_kg}) exceeds baseline ({total_baseline_co2_kg})")

    # Non-negativity
    if total_assisted_fuel_L < 0.0 or total_assisted_co2_kg < 0.0 or total_assisted_fuel_cost_usd < 0.0:
        raise ValueError("Net assisted aggregate quantities cannot be negative")

    # ─── STEP 4: Calculate Annual Operational CII (IMO MEPC.352(78)) ──────────
    # CRITICAL: Calculated ONLY from cumulative transport work, NEVER averaged across voyages!
    if total_transport_work_dwt_nm > 0.0:
        annual_baseline_operational_cii = float((total_baseline_co2_kg * 1000.0) / total_transport_work_dwt_nm)
        annual_assisted_operational_cii = float((total_assisted_co2_kg * 1000.0) / total_transport_work_dwt_nm)
    else:
        annual_baseline_operational_cii = 0.0
        annual_assisted_operational_cii = 0.0

    # ─── STEP 5: Calculate Annual Relative Percentage Changes ─────────────────
    if total_baseline_fuel_L > 0.0:
        annual_delta_fuel_pct = float(
            ((total_assisted_fuel_L - total_baseline_fuel_L) / total_baseline_fuel_L) * 100.0
        )
    else:
        annual_delta_fuel_pct = 0.0

    if total_baseline_fuel_cost_usd > 0.0:
        annual_delta_cost_pct = float(
            ((total_assisted_fuel_cost_usd - total_baseline_fuel_cost_usd) / total_baseline_fuel_cost_usd) * 100.0
        )
    else:
        annual_delta_cost_pct = 0.0

    if annual_baseline_operational_cii > 0.0:
        annual_delta_cii_pct = float(
            ((annual_assisted_operational_cii - annual_baseline_operational_cii) / annual_baseline_operational_cii) * 100.0
        )
    else:
        annual_delta_cii_pct = 0.0

    # ─── STEP 6: Assemble and Return AnnualScheduleSummary ────────────────────
    return AnnualScheduleSummary(
        vessel_id=req.vessel_id,
        ship_type=req.schedule[0].voyage_metadata.ship_type,
        total_voyages=len(voyage_outputs),
        total_distance_nm=total_distance_nm,
        total_duration_hours=total_duration_hours,
        total_transport_work_dwt_nm=total_transport_work_dwt_nm,
        total_baseline_fuel_L=total_baseline_fuel_L,
        total_baseline_fuel_cost_usd=total_baseline_fuel_cost_usd,
        total_baseline_co2_kg=total_baseline_co2_kg,
        annual_baseline_operational_cii=annual_baseline_operational_cii,
        total_clean_energy_utilized_kwh=total_clean_energy_utilized_kwh,
        total_clean_energy_curtailed_kwh=total_clean_energy_curtailed_kwh,
        total_fuel_displaced_L=total_fuel_displaced_L,
        total_co2_displaced_kg=total_co2_displaced_kg,
        total_assisted_fuel_L=total_assisted_fuel_L,
        total_assisted_fuel_cost_usd=total_assisted_fuel_cost_usd,
        total_assisted_co2_kg=total_assisted_co2_kg,
        annual_assisted_operational_cii=annual_assisted_operational_cii,
        annual_delta_fuel_pct=annual_delta_fuel_pct,
        annual_delta_cost_pct=annual_delta_cost_pct,
        annual_delta_cii_pct=annual_delta_cii_pct,
        feasible_voyage_count=feasible_count,
        partial_voyage_count=partial_count,
        voyage_evaluations=voyage_outputs,
        audit_metadata=AuditMetadata(),
    )
