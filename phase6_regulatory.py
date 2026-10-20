"""
phase6_regulatory.py — IMO Statutory CII Engine & Multi-Pollutant Emissions Layer
================================================================================
Implements:
  1. Authoritative IMO MEPC.353(78) Table 1 Operational CII Reference Lines (Tanker)
  2. Authoritative IMO MEPC.354(78) Table 1 Operational CII Rating Boundaries (Tanker)
  3. Reduction factor Z scheduling under MARPOL Annex VI Regulation 28.4
  4. Statutory A–E rating assignment with MEPC.354(78) Paragraph 4.2 boundary handling
  5. Strict non-assessment enforcement for non-qualifying vessels (OSV, Surfer, Fishing)
  6. Multi-pollutant engineering estimates (NOx, SOx, PM10, PM2.5) via Fourth IMO GHG Study
"""

from typing import Dict, Any, Optional, Tuple
import math

from phase6_contracts import (
    CIIAssessmentResult,
    PollutantEmissionFactors,
    PollutantAssessmentResult,
    IMO_CII_REDUCTION_FACTORS,
)

# Resolution MEPC.353(78) Table 1 parameters for Tanker
IMO_TANKER_A: float = 5247.0
IMO_TANKER_C: float = 0.610

# Resolution MEPC.354(78) Table 1 exponential boundary vectors for Tanker
IMO_TANKER_EXP_D1: float = 0.82  # Superior boundary (A/B)
IMO_TANKER_EXP_D2: float = 0.93  # Lower boundary (B/C)
IMO_TANKER_EXP_D3: float = 1.08  # Upper boundary (C/D)
IMO_TANKER_EXP_D4: float = 1.28  # Inferior boundary (D/E)


def calculate_tanker_cii_reference(dwt: float) -> float:
    """
    Calculate 2019 baseline reference line CII for Tanker under IMO MEPC.353(78) Table 1.
    Formula: CII_ref = a * Capacity^(-c) = 5247 * DWT^(-0.610)
    Units: g CO2 / (DWT * nm)
    """
    if dwt <= 0.0 or not math.isfinite(dwt):
        raise ValueError(f"DWT must be strictly positive and finite, got {dwt}")
    return IMO_TANKER_A * (dwt ** (-IMO_TANKER_C))


def calculate_tanker_required_cii(
    cii_ref: float,
    year: int = 2026,
) -> Tuple[Optional[float], Optional[float], str]:
    """
    Calculate Required CII for a given evaluation year applying reduction factor Z.
    Formula: Required_CII = CII_ref * (1 - Z / 100)
    """
    if cii_ref <= 0.0 or not math.isfinite(cii_ref):
        raise ValueError(f"cii_ref must be strictly positive and finite, got {cii_ref}")

    if year not in IMO_CII_REDUCTION_FACTORS:
        return None, None, "UNSUPPORTED_EVALUATION_YEAR"

    z = IMO_CII_REDUCTION_FACTORS[year]
    required_cii = cii_ref * (1.0 - z / 100.0)
    return required_cii, z, "VALID"


def calculate_tanker_rating_boundaries(required_cii: float) -> Dict[str, float]:
    """
    Calculate rating band boundaries for Tanker under IMO MEPC.354(78) Table 1.
    boundary_A_B = 0.82 * Required_CII
    boundary_B_C = 0.93 * Required_CII
    boundary_C_D = 1.08 * Required_CII
    boundary_D_E = 1.28 * Required_CII
    """
    if required_cii <= 0.0 or not math.isfinite(required_cii):
        raise ValueError(f"required_cii must be strictly positive and finite, got {required_cii}")

    return {
        "boundary_A_B": IMO_TANKER_EXP_D1 * required_cii,
        "boundary_B_C": IMO_TANKER_EXP_D2 * required_cii,
        "boundary_C_D": IMO_TANKER_EXP_D3 * required_cii,
        "boundary_D_E": IMO_TANKER_EXP_D4 * required_cii,
    }


def assign_tanker_cii_rating(attained_cii: float, boundaries: Dict[str, float]) -> str:
    """
    Assign statutory letter rating (A, B, C, D, E) based on attained CII and boundaries.
    Convention under Resolution MEPC.354(78) Paragraph 4.2:
    If attained CII lands exactly on a boundary, the ship is assigned the superior rating.
    """
    if attained_cii < 0.0 or not math.isfinite(attained_cii):
        raise ValueError(f"attained_cii must be non-negative and finite, got {attained_cii}")

    b_ab = boundaries["boundary_A_B"]
    b_bc = boundaries["boundary_B_C"]
    b_cd = boundaries["boundary_C_D"]
    b_de = boundaries["boundary_D_E"]

    if attained_cii <= b_ab:
        return "A"
    elif attained_cii <= b_bc:
        return "B"
    elif attained_cii <= b_cd:
        return "C"
    elif attained_cii <= b_de:
        return "D"
    else:
        return "E"


def calculate_attained_cii(co2_kg: float, dwt: float, distance_nm: float) -> float:
    """
    Calculate attained operational Carbon Intensity Indicator in g CO2 / (DWT * nm).
    Formula: (co2_kg * 1000.0) / (dwt * distance_nm)
    """
    if co2_kg < 0.0 or not math.isfinite(co2_kg):
        raise ValueError(f"co2_kg must be non-negative and finite, got {co2_kg}")
    if dwt <= 0.0 or not math.isfinite(dwt):
        raise ValueError(f"dwt must be strictly positive (> 0), got {dwt}")
    if distance_nm <= 0.0 or not math.isfinite(distance_nm):
        raise ValueError(f"distance_nm must be strictly positive (> 0), got {distance_nm}")

    return (co2_kg * 1000.0) / (dwt * distance_nm)


def evaluate_regulatory_cii(
    ship_type: str,
    dwt_tonnes: float,
    distance_nm: float,
    baseline_co2_kg: float,
    net_assisted_co2_kg: float,
    evaluation_year: int = 2026,
) -> CIIAssessmentResult:
    """
    Execute full regulatory CII evaluation.
    Only 'Tanker Ship' is eligible for statutory A–E rating.
    Other vessel types return NOT_ASSESSED with an explicit machine-readable status.
    """
    # Calculate attained CII metrics for both baseline and assisted operations
    baseline_attained = calculate_attained_cii(baseline_co2_kg, dwt_tonnes, distance_nm)
    assisted_attained = calculate_attained_cii(net_assisted_co2_kg, dwt_tonnes, distance_nm)

    if ship_type == "Tanker Ship":
        cii_ref = calculate_tanker_cii_reference(dwt_tonnes)
        req_cii, z_pct, year_status = calculate_tanker_required_cii(cii_ref, year=evaluation_year)

        if year_status != "VALID" or req_cii is None:
            return CIIAssessmentResult(
                vessel_category="Tanker",
                evaluation_year=evaluation_year,
                capacity_dwt=dwt_tonnes,
                distance_nm=distance_nm,
                baseline_co2_kg=baseline_co2_kg,
                net_assisted_co2_kg=net_assisted_co2_kg,
                baseline_attained_cii=baseline_attained,
                assisted_attained_cii=assisted_attained,
                cii_reference=cii_ref,
                required_cii=None,
                reduction_factor_z_pct=None,
                rating_boundaries=None,
                baseline_cii_rating="NOT_ASSESSED",
                assisted_cii_rating="NOT_ASSESSED",
                cii_assessment_status="UNSUPPORTED_EVALUATION_YEAR",
                source_document="IMO Resolution MEPC.353(78) & MEPC.354(78)",
            )

        boundaries = calculate_tanker_rating_boundaries(req_cii)
        base_rating = assign_tanker_cii_rating(baseline_attained, boundaries)
        assist_rating = assign_tanker_cii_rating(assisted_attained, boundaries)

        return CIIAssessmentResult(
            vessel_category="Tanker",
            evaluation_year=evaluation_year,
            capacity_dwt=dwt_tonnes,
            distance_nm=distance_nm,
            baseline_co2_kg=baseline_co2_kg,
            net_assisted_co2_kg=net_assisted_co2_kg,
            baseline_attained_cii=baseline_attained,
            assisted_attained_cii=assisted_attained,
            cii_reference=cii_ref,
            required_cii=req_cii,
            reduction_factor_z_pct=z_pct,
            rating_boundaries=boundaries,
            baseline_cii_rating=base_rating,
            assisted_cii_rating=assist_rating,
            cii_assessment_status="STATUTORY_ASSESSMENT_COMPLETED",
            source_document="IMO Resolution MEPC.353(78) & MEPC.354(78)",
        )

    elif ship_type == "Fishing Trawler":
        return CIIAssessmentResult(
            vessel_category=None,
            evaluation_year=evaluation_year,
            capacity_dwt=dwt_tonnes,
            distance_nm=distance_nm,
            baseline_co2_kg=baseline_co2_kg,
            net_assisted_co2_kg=net_assisted_co2_kg,
            baseline_attained_cii=baseline_attained,
            assisted_attained_cii=assisted_attained,
            cii_reference=None,
            required_cii=None,
            reduction_factor_z_pct=None,
            rating_boundaries=None,
            baseline_cii_rating="NOT_ASSESSED",
            assisted_cii_rating="NOT_ASSESSED",
            cii_assessment_status="STATUTORILY_EXEMPT",
            source_document="MARPOL Annex VI Regulation 19.2.3",
        )

    else:
        # Oil Service Boat and Surfer Boat
        return CIIAssessmentResult(
            vessel_category=None,
            evaluation_year=evaluation_year,
            capacity_dwt=dwt_tonnes,
            distance_nm=distance_nm,
            baseline_co2_kg=baseline_co2_kg,
            net_assisted_co2_kg=net_assisted_co2_kg,
            baseline_attained_cii=baseline_attained,
            assisted_attained_cii=assisted_attained,
            cii_reference=None,
            required_cii=None,
            reduction_factor_z_pct=None,
            rating_boundaries=None,
            baseline_cii_rating="NOT_ASSESSED",
            assisted_cii_rating="NOT_ASSESSED",
            cii_assessment_status="UNSUPPORTED_VESSEL_CATEGORY_MAPPING",
            source_document="IMO Resolution MEPC.353(78) & MEPC.354(78)",
        )


def evaluate_multi_pollutants(
    baseline_fuel_L: float,
    net_assisted_fuel_L: float,
    emission_factors: Optional[PollutantEmissionFactors] = None,
) -> PollutantAssessmentResult:
    """
    Calculate deterministic engineering estimates for avoided air pollutants
    (NOx, SOx, PM10, PM2.5) derived from auxiliary fuel displacement.
    Source: Fourth IMO GHG Study (2020) Table 2-8.
    """
    if baseline_fuel_L < 0.0 or not math.isfinite(baseline_fuel_L):
        raise ValueError(f"baseline_fuel_L must be non-negative and finite, got {baseline_fuel_L}")
    if net_assisted_fuel_L < 0.0 or not math.isfinite(net_assisted_fuel_L):
        raise ValueError(f"net_assisted_fuel_L must be non-negative and finite, got {net_assisted_fuel_L}")

    if emission_factors is None:
        emission_factors = PollutantEmissionFactors()

    fuel_displaced_L = max(0.0, baseline_fuel_L - net_assisted_fuel_L)
    rho = emission_factors.fuel_density_kg_per_l

    # Mass of fuel in kg
    base_fuel_kg = baseline_fuel_L * rho
    assist_fuel_kg = net_assisted_fuel_L * rho
    displaced_fuel_kg = fuel_displaced_L * rho

    # Pollutant masses in kg
    base_nox = base_fuel_kg * emission_factors.nox_kg_per_kg_fuel
    assist_nox = assist_fuel_kg * emission_factors.nox_kg_per_kg_fuel
    avoided_nox = displaced_fuel_kg * emission_factors.nox_kg_per_kg_fuel

    base_sox = base_fuel_kg * emission_factors.sox_kg_per_kg_fuel
    assist_sox = assist_fuel_kg * emission_factors.sox_kg_per_kg_fuel
    avoided_sox = displaced_fuel_kg * emission_factors.sox_kg_per_kg_fuel

    base_pm10 = base_fuel_kg * emission_factors.pm10_kg_per_kg_fuel
    assist_pm10 = assist_fuel_kg * emission_factors.pm10_kg_per_kg_fuel
    avoided_pm10 = displaced_fuel_kg * emission_factors.pm10_kg_per_kg_fuel

    base_pm25 = base_fuel_kg * emission_factors.pm25_kg_per_kg_fuel
    assist_pm25 = assist_fuel_kg * emission_factors.pm25_kg_per_kg_fuel
    avoided_pm25 = displaced_fuel_kg * emission_factors.pm25_kg_per_kg_fuel

    return PollutantAssessmentResult(
        baseline_fuel_L=baseline_fuel_L,
        net_assisted_fuel_L=net_assisted_fuel_L,
        fuel_displaced_L=fuel_displaced_L,
        baseline_nox_kg=base_nox,
        assisted_nox_kg=assist_nox,
        avoided_nox_kg=avoided_nox,
        baseline_sox_kg=base_sox,
        assisted_sox_kg=assist_sox,
        avoided_sox_kg=avoided_sox,
        baseline_pm10_kg=base_pm10,
        assisted_pm10_kg=assist_pm10,
        avoided_pm10_kg=avoided_pm10,
        baseline_pm25_kg=base_pm25,
        assisted_pm25_kg=assist_pm25,
        avoided_pm25_kg=avoided_pm25,
        emission_factor_source=emission_factors.source_reference,
        assessment_status="ENGINEERING_ESTIMATE",
    )
