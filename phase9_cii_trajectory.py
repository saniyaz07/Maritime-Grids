"""
phase9_cii_trajectory.py — Phase 9 Candidate 4
===============================================
Multi-Year Regulatory Compliance Trajectory & IMO CII Aging Simulator

Implements:
  1. Multi-year activity and transport work accumulation over calendar horizons.
  2. Baseline and clean-assisted annual emissions and fuel trajectory calculations.
  3. Reusable integration with frozen Phase 6 statutory CII calculation routines.
  4. Explicit regulatory basis resolution (STATUTORY vs. PROJECTED vs. UNSPECIFIED vs. EXEMPT vs. NOT_ASSESSED).
  5. Multi-year sequential MARPOL Annex VI Regulation 28 corrective-action tracking (3x D or 1x E).
  6. Rigorous compliance extension metric calculation.
  7. Optional annual physical degradation compounding.

Zero modification to frozen upstream contracts or models.
Zero duplicate financial or physical formulas.
"""

from typing import Dict, List, Optional, Tuple
import math

from phase6_contracts import (
    IMO_CII_REDUCTION_FACTORS,
    CIIAssessmentResult,
)
from phase6_regulatory import (
    calculate_tanker_cii_reference,
    calculate_tanker_required_cii,
    calculate_tanker_rating_boundaries,
    assign_tanker_cii_rating,
    calculate_attained_cii,
    evaluate_regulatory_cii,
)
from phase9_cii_contracts import (
    SUPPORTED_CII_SHIP_TYPES,
    REGULATORY_BASIS_STATUTORY,
    REGULATORY_BASIS_PROJECTED,
    REGULATORY_BASIS_UNSPECIFIED,
    REGULATORY_BASIS_EXEMPT,
    REGULATORY_BASIS_NOT_ASSESSED,
    CII_RATING_A,
    CII_RATING_B,
    CII_RATING_C,
    CII_RATING_D,
    CII_RATING_E,
    CII_RATING_EXEMPT,
    CII_RATING_NOT_ASSESSED,
    CII_RATING_UNSPECIFIED,
    DIAG_TRAJECTORY_COMPLETED,
    DIAG_TRAJECTORY_UNSPECIFIED_POST_2026,
    DIAG_TRAJECTORY_EXEMPT,
    DIAG_TRAJECTORY_NOT_ASSESSED,
    RegulatoryScenarioParameters,
    PhysicalDegradationParameters,
    TrajectorySimulationRequest,
    AnnualTrajectoryRecord,
    TrajectorySimulationResult,
)


# ==============================================================================
# 1. Regulatory Schedule Resolver
# ==============================================================================

def resolve_year_regulatory_basis(
    ship_type: str,
    year: int,
    scenario_params: RegulatoryScenarioParameters,
) -> Tuple[str, Optional[float]]:
    """
    Resolve the regulatory basis and reduction factor Z% for a given vessel and year.

    Rules:
      - Fishing Trawler: EXEMPT (Z = None)
      - Oil Service Boat / Surfer Boat: NOT_ASSESSED (Z = None)
      - Tanker Ship:
          * 2023..2026: STATUTORY (Z from frozen Phase 6 schedule: 5, 7, 9, 11%)
          * 2027+:
              - If explicit post_2026_reduction_factors provided: PROJECTED (Z = lookup)
              - If annual_z_increment_pct provided: PROJECTED (Z = 11.0 + (year - 2026) * inc)
              - Otherwise: UNSPECIFIED (Z = None)
          * < 2023: UNSPECIFIED (Z = None)

    Returns
    -------
    (regulatory_basis: str, reduction_factor_z_pct: Optional[float])
    """
    if ship_type == "Fishing Trawler":
        return REGULATORY_BASIS_EXEMPT, None

    if ship_type in ("Oil Service Boat", "Surfer Boat"):
        return REGULATORY_BASIS_NOT_ASSESSED, None

    # Tanker Ship
    if year in IMO_CII_REDUCTION_FACTORS:
        return REGULATORY_BASIS_STATUTORY, IMO_CII_REDUCTION_FACTORS[year]

    if year >= 2027:
        if scenario_params.post_2026_reduction_factors and year in scenario_params.post_2026_reduction_factors:
            return REGULATORY_BASIS_PROJECTED, scenario_params.post_2026_reduction_factors[year]
        if scenario_params.annual_z_increment_pct is not None:
            projected_z = 11.0 + (year - 2026) * scenario_params.annual_z_increment_pct
            return REGULATORY_BASIS_PROJECTED, round(projected_z, 4)
        return REGULATORY_BASIS_UNSPECIFIED, None

    # Year < 2023 for Tanker
    return REGULATORY_BASIS_UNSPECIFIED, None


# ==============================================================================
# 2. Multi-Year Trajectory Engine
# ==============================================================================

def simulate_compliance_trajectory(
    request: TrajectorySimulationRequest,
) -> TrajectorySimulationResult:
    """
    Simulate multi-year operational activity, annual emissions, and statutory/projected
    IMO CII compliance trajectories.

    Parameters
    ----------
    request : TrajectorySimulationRequest
        Validated input parameters and optional retrofit candidate.

    Returns
    -------
    TrajectorySimulationResult
        Complete multi-year trajectory with annual audit records and compliance extension metrics.
    """
    warnings: List[str] = []

    # 1. Activity constants
    annual_distance_nm = request.annual_voyages * request.voyage_distance_nm
    annual_transport_work = request.dwt_tonnes * annual_distance_nm

    base_single_fuel = request.baseline_single_voyage_fuel_L
    base_single_co2 = request.baseline_single_voyage_co2_kg

    # 2. Retrofit clean displacements baseline (Year 0)
    if request.candidate is not None:
        cand_fuel_disp_0 = float(request.candidate.annual_fuel_displaced_L)
        cand_co2_disp_0 = float(request.candidate.annual_co2_displaced_kg)
    else:
        cand_fuel_disp_0 = 0.0
        cand_co2_disp_0 = 0.0

    # 3. Reference line for Tanker
    cii_ref = calculate_tanker_cii_reference(request.dwt_tonnes) if request.ship_type == "Tanker Ship" else None

    # 4. Trajectory state tracking
    records: List[AnnualTrajectoryRecord] = []
    base_consecutive_d_count = 0
    assist_consecutive_d_count = 0

    has_unspecified_post_2026 = False
    has_projected_post_2026 = False

    # Check for degradation parameter usage
    deg = request.degradation_parameters
    has_degradation = (
        deg.solar_derate_pct_per_year > 0.0
        or deg.battery_capacity_fade_pct_per_year > 0.0
        or deg.fuel_consumption_growth_pct_per_year > 0.0
    )
    if has_degradation:
        warnings.append(
            f"Physical degradation parameters applied: solar derate={deg.solar_derate_pct_per_year}%/yr, "
            f"battery fade={deg.battery_capacity_fade_pct_per_year}%/yr, fuel growth={deg.fuel_consumption_growth_pct_per_year}%/yr."
        )

    for yr in range(request.start_year, request.end_year + 1):
        t_idx = yr - request.start_year

        # --- A. Apply annual physical degradation ---
        # Baseline fuel & CO2 growth compounding
        fuel_growth_mult = (1.0 + (deg.fuel_consumption_growth_pct_per_year / 100.0)) ** t_idx
        base_annual_fuel = (base_single_fuel * request.annual_voyages) * fuel_growth_mult
        base_annual_co2 = (base_single_co2 * request.annual_voyages) * fuel_growth_mult

        # Clean displacement degradation compounding (combined solar and battery fade)
        clean_deg_mult = (
            (1.0 - (deg.solar_derate_pct_per_year / 100.0)) ** t_idx
            * (1.0 - (deg.battery_capacity_fade_pct_per_year / 100.0)) ** t_idx
        )
        clean_deg_mult = max(0.0, clean_deg_mult)
        ann_fuel_disp = cand_fuel_disp_0 * clean_deg_mult
        ann_co2_disp = cand_co2_disp_0 * clean_deg_mult

        # Net assisted annual totals
        assist_annual_fuel = max(0.0, base_annual_fuel - ann_fuel_disp)
        assist_annual_co2 = max(0.0, base_annual_co2 - ann_co2_disp)

        # --- B. Calculate attained operational CII ---
        base_attained = calculate_attained_cii(base_annual_co2, request.dwt_tonnes, annual_distance_nm)
        assist_attained = calculate_attained_cii(assist_annual_co2, request.dwt_tonnes, annual_distance_nm)

        # --- C. Resolve regulatory schedule and basis ---
        basis, z_pct = resolve_year_regulatory_basis(request.ship_type, yr, request.regulatory_scenario)

        if basis == REGULATORY_BASIS_UNSPECIFIED:
            has_unspecified_post_2026 = True
        elif basis == REGULATORY_BASIS_PROJECTED:
            has_projected_post_2026 = True

        # --- D. Evaluate required CII and rating bands ---
        req_cii: Optional[float] = None
        boundaries: Optional[Dict[str, float]] = None
        base_rating: str
        assist_rating: str
        base_compliant: Optional[bool]
        assist_compliant: Optional[bool]

        if basis == REGULATORY_BASIS_EXEMPT:
            base_rating = CII_RATING_EXEMPT
            assist_rating = CII_RATING_EXEMPT
            base_compliant = None
            assist_compliant = None

        elif basis == REGULATORY_BASIS_NOT_ASSESSED:
            base_rating = CII_RATING_NOT_ASSESSED
            assist_rating = CII_RATING_NOT_ASSESSED
            base_compliant = None
            assist_compliant = None

        elif basis in (REGULATORY_BASIS_STATUTORY, REGULATORY_BASIS_PROJECTED):
            assert cii_ref is not None and z_pct is not None
            req_cii = cii_ref * (1.0 - z_pct / 100.0)
            boundaries = calculate_tanker_rating_boundaries(req_cii)
            base_rating = assign_tanker_cii_rating(base_attained, boundaries)
            assist_rating = assign_tanker_cii_rating(assist_attained, boundaries)
            base_compliant = base_rating in (CII_RATING_A, CII_RATING_B, CII_RATING_C)
            assist_compliant = assist_rating in (CII_RATING_A, CII_RATING_B, CII_RATING_C)

        else:  # UNSPECIFIED
            base_rating = CII_RATING_UNSPECIFIED
            assist_rating = CII_RATING_UNSPECIFIED
            base_compliant = None
            assist_compliant = None

        # --- E. Multi-Year Sequential Corrective Action Tracking (MARPOL Reg 28.6 Context) ---
        base_corrective_action = False
        assist_corrective_action = False

        if basis in (REGULATORY_BASIS_STATUTORY, REGULATORY_BASIS_PROJECTED):
            # Baseline tracking
            if base_rating == CII_RATING_E:
                base_consecutive_d_count = 0
                base_corrective_action = True
            elif base_rating == CII_RATING_D:
                base_consecutive_d_count += 1
                base_corrective_action = (base_consecutive_d_count >= 3)
            elif base_rating in (CII_RATING_A, CII_RATING_B, CII_RATING_C):
                base_consecutive_d_count = 0
                base_corrective_action = False

            # Assisted tracking
            if assist_rating == CII_RATING_E:
                assist_consecutive_d_count = 0
                assist_corrective_action = True
            elif assist_rating == CII_RATING_D:
                assist_consecutive_d_count += 1
                assist_corrective_action = (assist_consecutive_d_count >= 3)
            elif assist_rating in (CII_RATING_A, CII_RATING_B, CII_RATING_C):
                assist_consecutive_d_count = 0
                assist_corrective_action = False

        record = AnnualTrajectoryRecord(
            year=yr,
            regulatory_basis=basis,
            reduction_factor_z_pct=z_pct,
            annual_distance_nm=round(annual_distance_nm, 4),
            annual_transport_work_dwt_nm=round(annual_transport_work, 4),
            baseline_annual_fuel_L=round(base_annual_fuel, 4),
            baseline_annual_co2_kg=round(base_annual_co2, 4),
            assisted_annual_fuel_L=round(assist_annual_fuel, 4),
            assisted_annual_co2_kg=round(assist_annual_co2, 4),
            annual_fuel_displaced_L=round(ann_fuel_disp, 4),
            annual_co2_displaced_kg=round(ann_co2_disp, 4),
            baseline_attained_cii=round(base_attained, 6),
            assisted_attained_cii=round(assist_attained, 6),
            cii_reference=round(cii_ref, 6) if cii_ref is not None else None,
            required_cii=round(req_cii, 6) if req_cii is not None else None,
            rating_boundaries=boundaries,
            baseline_cii_rating=base_rating,
            assisted_cii_rating=assist_rating,
            baseline_is_compliant=base_compliant,
            assisted_is_compliant=assist_compliant,
            baseline_corrective_action_required=base_corrective_action,
            assisted_corrective_action_required=assist_corrective_action,
        )
        records.append(record)

    # 5. Add regulatory notices to warnings
    if has_projected_post_2026:
        warnings.append(
            "Post-2026 CII reduction factors are caller-specified scenario projections and "
            "must not be construed as adopted MARPOL Annex VI statutory requirements."
        )
    if has_unspecified_post_2026:
        warnings.append(
            "Trajectory contains post-2026 evaluation years with unspecified regulatory schedules; "
            "required CII and ratings for these years are marked UNSPECIFIED."
        )

    # 6. Cumulative totals
    cum_base_fuel = sum(r.baseline_annual_fuel_L for r in records)
    cum_base_co2 = sum(r.baseline_annual_co2_kg for r in records)
    cum_assist_fuel = sum(r.assisted_annual_fuel_L for r in records)
    cum_assist_co2 = sum(r.assisted_annual_co2_kg for r in records)
    tot_fuel_disp = sum(r.annual_fuel_displaced_L for r in records)
    tot_co2_disp = sum(r.annual_co2_displaced_kg for r in records)

    # 7. Compliance extension metric & first non-compliant year
    compliance_extension_years: Optional[int] = None
    first_non_compliant_base: Optional[int] = None
    first_non_compliant_assist: Optional[int] = None

    if request.ship_type == "Tanker Ship":
        comp_base_count = sum(1 for r in records if r.baseline_is_compliant is True)
        comp_assist_count = sum(1 for r in records if r.assisted_is_compliant is True)
        compliance_extension_years = max(0, comp_assist_count - comp_base_count)

        for r in records:
            if r.baseline_is_compliant is False and first_non_compliant_base is None:
                first_non_compliant_base = r.year
            if r.assisted_is_compliant is False and first_non_compliant_assist is None:
                first_non_compliant_assist = r.year

    # 8. Diagnostics
    if request.ship_type == "Fishing Trawler":
        diagnostics = DIAG_TRAJECTORY_EXEMPT
    elif request.ship_type in ("Oil Service Boat", "Surfer Boat"):
        diagnostics = DIAG_TRAJECTORY_NOT_ASSESSED
    elif has_unspecified_post_2026:
        diagnostics = DIAG_TRAJECTORY_UNSPECIFIED_POST_2026
    else:
        diagnostics = DIAG_TRAJECTORY_COMPLETED

    return TrajectorySimulationResult(
        request=request,
        trajectory=records,
        years_evaluated=len(records),
        baseline_cumulative_fuel_L=round(cum_base_fuel, 4),
        baseline_cumulative_co2_kg=round(cum_base_co2, 4),
        assisted_cumulative_fuel_L=round(cum_assist_fuel, 4),
        assisted_cumulative_co2_kg=round(cum_assist_co2, 4),
        total_fuel_displaced_L=round(tot_fuel_disp, 4),
        total_co2_displaced_kg=round(tot_co2_disp, 4),
        compliance_extension_years=compliance_extension_years,
        first_non_compliant_year_baseline=first_non_compliant_base,
        first_non_compliant_year_assisted=first_non_compliant_assist,
        diagnostics=diagnostics,
        warnings=warnings,
    )
