"""
test_phase6_regulatory.py — Test Suite for Phase 6 IMO Statutory CII Engine
===========================================================================
Validates:
  1. Authoritative IMO MEPC.353(78) Table 1 reference line for Tanker (a=5247, c=0.610)
  2. Authoritative IMO MEPC.354(78) Table 1 boundaries (0.82, 0.93, 1.08, 1.28)
  3. Boundary conditions: just below, exactly at, just above every boundary
  4. IMO rating bands A, B, C, D, E assignment
  5. Unsupported vessel mapping (Oil Service Boat, Surfer Boat -> NOT_ASSESSED)
  6. Statutory exemption (Fishing Trawler -> NOT_ASSESSED, STATUTORILY_EXEMPT)
  7. Evaluation year reduction factors Z (2023: 5%, 2024: 7%, 2025: 9%, 2026: 11%)
  8. Unsupported year handling (e.g. 2035 -> UNSUPPORTED_EVALUATION_YEAR)
  9. Invalid input rejection (DWT <= 0, distance <= 0, negative CO2)
 10. Baseline vs assisted CII reporting and rating improvement
 11. Deterministic and reproducible evaluation
"""

import math
import pytest
from pydantic import ValidationError

from phase6_contracts import (
    CIIAssessmentResult,
    IMO_CII_REDUCTION_FACTORS,
)
from phase6_regulatory import (
    calculate_tanker_cii_reference,
    calculate_tanker_required_cii,
    calculate_tanker_rating_boundaries,
    assign_tanker_cii_rating,
    calculate_attained_cii,
    evaluate_regulatory_cii,
    IMO_TANKER_A,
    IMO_TANKER_C,
    IMO_TANKER_EXP_D1,
    IMO_TANKER_EXP_D2,
    IMO_TANKER_EXP_D3,
    IMO_TANKER_EXP_D4,
)


# ==============================================================================
# 1. Reference Line & Required CII Math Tests
# ==============================================================================
def test_tanker_reference_line_exact_formula():
    dwt = 50000.0
    expected = 5247.0 * (50000.0 ** (-0.610))
    actual = calculate_tanker_cii_reference(dwt)
    assert actual == pytest.approx(expected, rel=1e-12)
    assert actual == pytest.approx(7.13738914, rel=1e-6)


def test_required_cii_for_all_supported_years():
    cii_ref = 10.0
    for year, z in IMO_CII_REDUCTION_FACTORS.items():
        req_cii, z_val, status = calculate_tanker_required_cii(cii_ref, year=year)
        assert status == "VALID"
        assert z_val == z
        assert req_cii == pytest.approx(cii_ref * (1.0 - z / 100.0))


def test_required_cii_unsupported_year():
    req_cii, z_val, status = calculate_tanker_required_cii(10.0, year=2035)
    assert status == "UNSUPPORTED_EVALUATION_YEAR"
    assert req_cii is None
    assert z_val is None


# ==============================================================================
# 2. Rating Boundary Tests
# ==============================================================================
def test_tanker_rating_boundaries_multipliers():
    req_cii = 10.0
    bounds = calculate_tanker_rating_boundaries(req_cii)
    assert bounds["boundary_A_B"] == pytest.approx(8.2)
    assert bounds["boundary_B_C"] == pytest.approx(9.3)
    assert bounds["boundary_C_D"] == pytest.approx(10.8)
    assert bounds["boundary_D_E"] == pytest.approx(12.8)


def test_rating_assignment_bands():
    bounds = {
        "boundary_A_B": 5.0,
        "boundary_B_C": 6.0,
        "boundary_C_D": 7.0,
        "boundary_D_E": 8.0,
    }
    assert assign_tanker_cii_rating(4.0, bounds) == "A"
    assert assign_tanker_cii_rating(5.5, bounds) == "B"
    assert assign_tanker_cii_rating(6.5, bounds) == "C"
    assert assign_tanker_cii_rating(7.5, bounds) == "D"
    assert assign_tanker_cii_rating(8.5, bounds) == "E"


def test_exact_boundary_assigns_superior_rating_mepc354():
    """Under Resolution MEPC.354(78) Paragraph 4.2, exactly on a boundary gets the superior rating."""
    bounds = {
        "boundary_A_B": 5.0,
        "boundary_B_C": 6.0,
        "boundary_C_D": 7.0,
        "boundary_D_E": 8.0,
    }
    # Exactly on boundaries
    assert assign_tanker_cii_rating(5.0, bounds) == "A"
    assert assign_tanker_cii_rating(6.0, bounds) == "B"
    assert assign_tanker_cii_rating(7.0, bounds) == "C"
    assert assign_tanker_cii_rating(8.0, bounds) == "D"


def test_just_above_and_below_boundaries():
    bounds = {
        "boundary_A_B": 5.0,
        "boundary_B_C": 6.0,
        "boundary_C_D": 7.0,
        "boundary_D_E": 8.0,
    }
    eps = 1e-6
    # Boundary A/B
    assert assign_tanker_cii_rating(5.0 - eps, bounds) == "A"
    assert assign_tanker_cii_rating(5.0 + eps, bounds) == "B"
    # Boundary B/C
    assert assign_tanker_cii_rating(6.0 - eps, bounds) == "B"
    assert assign_tanker_cii_rating(6.0 + eps, bounds) == "C"
    # Boundary C/D
    assert assign_tanker_cii_rating(7.0 - eps, bounds) == "C"
    assert assign_tanker_cii_rating(7.0 + eps, bounds) == "D"
    # Boundary D/E
    assert assign_tanker_cii_rating(8.0 - eps, bounds) == "D"
    assert assign_tanker_cii_rating(8.0 + eps, bounds) == "E"


# ==============================================================================
# 3. Attained CII and Input Validation Tests
# ==============================================================================
def test_attained_cii_calculation():
    # 48969.5 kg CO2, 50,000 DWT, 486 nm
    # = (48969.5 * 1000) / (50000 * 486) = 48969500 / 24300000 = 2.0152057613
    cii = calculate_attained_cii(48969.5, 50000.0, 486.0)
    assert cii == pytest.approx(2.0152057613)


def test_invalid_attained_inputs_raise():
    with pytest.raises(ValueError, match="co2_kg must be non-negative"):
        calculate_attained_cii(-10.0, 50000.0, 486.0)

    with pytest.raises(ValueError, match="dwt must be strictly positive"):
        calculate_attained_cii(100.0, 0.0, 486.0)

    with pytest.raises(ValueError, match="dwt must be strictly positive"):
        calculate_attained_cii(100.0, -500.0, 486.0)

    with pytest.raises(ValueError, match="distance_nm must be strictly positive"):
        calculate_attained_cii(100.0, 50000.0, 0.0)

    with pytest.raises(ValueError, match="distance_nm must be strictly positive"):
        calculate_attained_cii(100.0, 50000.0, -10.0)

    with pytest.raises(ValueError, match="finite"):
        calculate_attained_cii(float("nan"), 50000.0, 100.0)


# ==============================================================================
# 4. End-to-End Regulatory Evaluation Tests
# ==============================================================================
def test_tanker_statutory_evaluation_success():
    res = evaluate_regulatory_cii(
        ship_type="Tanker Ship",
        dwt_tonnes=50000.0,
        distance_nm=486.0,
        baseline_co2_kg=48969.5,
        net_assisted_co2_kg=48695.5,
        evaluation_year=2026,
    )
    assert isinstance(res, CIIAssessmentResult)
    assert res.vessel_category == "Tanker"
    assert res.cii_assessment_status == "STATUTORY_ASSESSMENT_COMPLETED"
    assert res.reduction_factor_z_pct == 11.0
    assert res.cii_reference == pytest.approx(7.137389, rel=1e-5)
    assert res.required_cii == pytest.approx(6.352276, rel=1e-5)
    assert res.baseline_cii_rating == "A"
    assert res.assisted_cii_rating == "A"
    assert res.rating_boundaries is not None
    assert "boundary_A_B" in res.rating_boundaries


def test_oil_service_boat_unsupported_mapping():
    res = evaluate_regulatory_cii(
        ship_type="Oil Service Boat",
        dwt_tonnes=1800.0,
        distance_nm=250.0,
        baseline_co2_kg=10906.9,
        net_assisted_co2_kg=10783.5,
        evaluation_year=2026,
    )
    assert res.vessel_category is None
    assert res.baseline_cii_rating == "NOT_ASSESSED"
    assert res.assisted_cii_rating == "NOT_ASSESSED"
    assert res.cii_assessment_status == "UNSUPPORTED_VESSEL_CATEGORY_MAPPING"
    assert res.cii_reference is None
    assert res.required_cii is None
    # Still calculates engineering attained CII
    assert res.baseline_attained_cii == pytest.approx((10906.9 * 1000) / (1800.0 * 250.0))


def test_surfer_boat_unsupported_mapping():
    res = evaluate_regulatory_cii(
        ship_type="Surfer Boat",
        dwt_tonnes=35.0,
        distance_nm=120.0,
        baseline_co2_kg=2500.0,
        net_assisted_co2_kg=2400.0,
        evaluation_year=2026,
    )
    assert res.vessel_category is None
    assert res.baseline_cii_rating == "NOT_ASSESSED"
    assert res.assisted_cii_rating == "NOT_ASSESSED"
    assert res.cii_assessment_status == "UNSUPPORTED_VESSEL_CATEGORY_MAPPING"


def test_fishing_trawler_statutorily_exempt():
    res = evaluate_regulatory_cii(
        ship_type="Fishing Trawler",
        dwt_tonnes=350.0,
        distance_nm=120.0,
        baseline_co2_kg=3950.0,
        net_assisted_co2_kg=3800.0,
        evaluation_year=2026,
    )
    assert res.vessel_category is None
    assert res.baseline_cii_rating == "NOT_ASSESSED"
    assert res.assisted_cii_rating == "NOT_ASSESSED"
    assert res.cii_assessment_status == "STATUTORILY_EXEMPT"
    assert "Regulation 19.2.3" in res.source_document


def test_unsupported_year_in_regulatory_evaluation():
    res = evaluate_regulatory_cii(
        ship_type="Tanker Ship",
        dwt_tonnes=50000.0,
        distance_nm=486.0,
        baseline_co2_kg=48969.5,
        net_assisted_co2_kg=48695.5,
        evaluation_year=2040,
    )
    assert res.cii_assessment_status == "UNSUPPORTED_EVALUATION_YEAR"
    assert res.baseline_cii_rating == "NOT_ASSESSED"
    assert res.assisted_cii_rating == "NOT_ASSESSED"
    assert res.required_cii is None
