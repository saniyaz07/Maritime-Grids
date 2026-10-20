"""
tests/test_weather_lookahead.py — Phase 10C.13C Weather Look-Ahead Unit & Integration Tests
=============================================================================================
Comprehensive test suite validating:
  1. Geodesic distance calculation along route waypoints.
  2. Spacetime ETA estimation for moving vessels (SOG > 0).
  3. Safety guards for stationary (SOG = 0) and missing speed (SOG = None) vessels (no division by zero).
  4. Max distance and time lookahead window capping.
  5. Point-in-time forecast query and adverse condition detection.
  6. Deterministic AdverseWeatherAheadRule advisory generation with human_review_required = True.
  7. OperatorService and FastAPI REST endpoint integration.
  8. Zero actuator and zero control outputs safety boundary.
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.mock_provider import MockWeatherProvider
from app.voyage.contracts import (
    Route,
    VesselPosition,
    VesselContext,
    VoyageContext,
    VoyageTimeline,
    VoyageWeatherContext,
)
from app.voyage.lookahead import (
    LookAheadTimingStatus,
    LookAheadWaypointWeather,
    RouteWeatherLookAhead,
    RouteWeatherLookAheadEngine,
    RouteWeatherLookAheadRequest,
    RouteWeatherLookAheadSummary,
    compute_route_weather_lookahead,
    haversine_distance_nm,
)
from app.decision.contracts import DecisionContext
from app.advisory.contracts import (
    AdvisoryCategory,
    AdvisoryPolicy,
    AdvisorySeverity,
    WeatherSafetyPolicy,
)
from app.advisory.rules import AdverseWeatherAheadRule, build_rule_set_from_policy
from app.services.operator_service import OperatorService
from app.api.app import create_app


# =====================================================================
# FIXTURES
# =====================================================================

@pytest.fixture
def mock_weather_provider() -> MockWeatherProvider:
    return MockWeatherProvider(
        fixed_reference_time=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    )


@pytest.fixture
def sample_route() -> Route:
    return Route(
        route_id="ESCRAVOS_LAGOS",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP_ESCRAVOS", latitude=5.58, longitude=5.18),
            RouteWaypoint(waypoint_id="WP_MID_01", latitude=5.80, longitude=4.50),
            RouteWaypoint(waypoint_id="WP_MID_02", latitude=6.10, longitude=3.80),
            RouteWaypoint(waypoint_id="WP_LAGOS", latitude=6.45, longitude=3.40),
        ],
        total_distance_nm=130.0,
    )


@pytest.fixture
def moving_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.58,
        longitude=5.18,
        speed_over_ground_knots=12.0,
        course_over_ground_deg=295.0,
        timestamp_utc="2026-06-15T12:00:00+00:00",
        data_type=WeatherProvenanceType.OBSERVED,
    )


@pytest.fixture
def stationary_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.58,
        longitude=5.18,
        speed_over_ground_knots=0.0,
        course_over_ground_deg=0.0,
        timestamp_utc="2026-06-15T12:00:00+00:00",
        data_type=WeatherProvenanceType.OBSERVED,
    )


@pytest.fixture
def missing_speed_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.58,
        longitude=5.18,
        speed_over_ground_knots=None,
        course_over_ground_deg=None,
        timestamp_utc="2026-06-15T12:00:00+00:00",
        data_type=WeatherProvenanceType.OBSERVED,
    )


# =====================================================================
# 1. GEODESIC DISTANCE TESTS
# =====================================================================

def test_haversine_distance_calculation():
    # Test identical coordinates = 0 NM
    assert haversine_distance_nm(5.58, 5.18, 5.58, 5.18) == 0.0

    # Test 1 degree latitude = ~60 NM
    dist_lat = haversine_distance_nm(0.0, 0.0, 1.0, 0.0)
    assert 59.5 <= dist_lat <= 60.5

    # Test Escravos to Lagos distance (~120-135 NM)
    dist_route = haversine_distance_nm(5.58, 5.18, 6.45, 3.40)
    assert 115.0 <= dist_route <= 130.0


# =====================================================================
# 2. SPACETIME LOOK-AHEAD FOR MOVING VESSELS
# =====================================================================

def test_lookahead_moving_vessel(sample_route, moving_position, mock_weather_provider):
    engine = RouteWeatherLookAheadEngine()
    result = engine.compute_lookahead(
        position=moving_position,
        route=sample_route,
        weather_provider=mock_weather_provider,
        vessel_id="VESSEL_OSV_01",
    )

    assert result.timing_status == LookAheadTimingStatus.ESTIMATED
    assert result.speed_over_ground_knots == 12.0
    assert len(result.waypoints) == 4

    # First waypoint at vessel position: dist=0, ETA=T0, hours=0
    assert result.waypoints[0].distance_from_vessel_nm == 0.0
    assert result.waypoints[0].hours_ahead == 0.0
    assert result.waypoints[0].estimated_arrival_utc == "2026-06-15T12:00:00+00:00"

    # Subsequent waypoints should have strictly increasing distance and hours
    for i in range(1, len(result.waypoints)):
        curr_wp = result.waypoints[i]
        prev_wp = result.waypoints[i - 1]
        assert curr_wp.distance_from_vessel_nm > prev_wp.distance_from_vessel_nm
        assert curr_wp.hours_ahead > prev_wp.hours_ahead
        assert curr_wp.estimated_arrival_utc is not None
        assert curr_wp.weather is not None
        assert curr_wp.weather.latitude == curr_wp.latitude
        assert curr_wp.weather.longitude == curr_wp.longitude

    # Summary checks
    assert result.summary.total_lookahead_distance_nm > 100.0
    assert result.summary.total_lookahead_hours is not None
    assert result.summary.total_lookahead_hours > 0.0
    assert result.summary.max_wind_knots is not None
    assert result.summary.max_wave_height_m is not None
    assert result.provenance == WeatherProvenanceType.FORECAST
    assert result.overall_quality == WeatherQualityState.VALID


# =====================================================================
# 3. STATIONARY & MISSING SPEED GUARDS
# =====================================================================

def test_lookahead_stationary_vessel(sample_route, stationary_position, mock_weather_provider):
    engine = RouteWeatherLookAheadEngine()
    result = engine.compute_lookahead(
        position=stationary_position,
        route=sample_route,
        weather_provider=mock_weather_provider,
        vessel_id="VESSEL_OSV_01",
    )

    assert result.timing_status == LookAheadTimingStatus.STATIONARY
    assert result.speed_over_ground_knots == 0.0
    assert len(result.waypoints) == 4

    # ETAs must be None for all waypoints (no division by zero)
    for wp in result.waypoints:
        assert wp.estimated_arrival_utc is None
        assert wp.hours_ahead is None
        assert wp.timing_status == LookAheadTimingStatus.STATIONARY
        # Weather is still populated for spatial awareness
        assert wp.weather is not None

    assert result.summary.total_lookahead_hours is None
    assert result.summary.total_lookahead_distance_nm > 0.0


def test_lookahead_missing_speed(sample_route, missing_speed_position, mock_weather_provider):
    engine = RouteWeatherLookAheadEngine()
    result = engine.compute_lookahead(
        position=missing_speed_position,
        route=sample_route,
        weather_provider=mock_weather_provider,
        vessel_id="VESSEL_OSV_01",
    )

    assert result.timing_status == LookAheadTimingStatus.SPEED_UNAVAILABLE
    assert result.speed_over_ground_knots is None
    assert len(result.waypoints) == 4

    for wp in result.waypoints:
        assert wp.estimated_arrival_utc is None
        assert wp.hours_ahead is None
        assert wp.timing_status == LookAheadTimingStatus.SPEED_UNAVAILABLE
        assert wp.weather is not None

    assert result.summary.total_lookahead_hours is None


# =====================================================================
# 4. LOOK-AHEAD WINDOW CAPPING (DISTANCE & TIME)
# =====================================================================

def test_lookahead_max_distance_cap(sample_route, moving_position, mock_weather_provider):
    engine = RouteWeatherLookAheadEngine()
    # Route is ~125 NM total. Cap at 50 NM.
    result = engine.compute_lookahead(
        position=moving_position,
        route=sample_route,
        weather_provider=mock_weather_provider,
        max_lookahead_nm=50.0,
    )

    assert len(result.waypoints) < len(sample_route.waypoints)
    assert result.summary.total_lookahead_distance_nm <= 60.0  # Includes first segment <= cap


def test_lookahead_max_hours_cap(sample_route, moving_position, mock_weather_provider):
    engine = RouteWeatherLookAheadEngine()
    # At 12 knots, 125 NM takes ~10.4 hours. Cap at 3.0 hours (~36 NM).
    result = engine.compute_lookahead(
        position=moving_position,
        route=sample_route,
        weather_provider=mock_weather_provider,
        max_lookahead_hours=3.0,
    )

    assert len(result.waypoints) < len(sample_route.waypoints)
    for wp in result.waypoints:
        if wp.hours_ahead is not None:
            assert wp.hours_ahead <= 4.0  # Small overshoot allowance for final segment boundary


# =====================================================================
# 5. ADVERSE CONDITIONS DETECTION
# =====================================================================

def test_lookahead_adverse_weather_detection(sample_route, moving_position):
    # Provider configured to return severe wind (30 knots) and high waves (3.5 m)
    provider = MockWeatherProvider(
        fixed_reference_time=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        field_overrides={"wind_speed_knots": 30.0, "wind_speed_ms": 15.43, "wave_height_m": 3.5},
    )

    policy = AdvisoryPolicy(
        weather_policy=WeatherSafetyPolicy(
            high_wind_threshold_knots=20.0,
            rough_sea_threshold_m=2.0,
        )
    )

    result = compute_route_weather_lookahead(
        position=moving_position,
        route=sample_route,
        weather_provider=provider,
        policy=policy,
    )

    assert result.summary.has_adverse_conditions is True
    assert len(result.summary.adverse_condition_reasons) > 0
    assert result.summary.max_wind_knots == 30.0
    assert result.summary.max_wave_height_m == 3.5

    for wp in result.waypoints:
        assert wp.high_wind_warning is True
        assert wp.rough_sea_warning is True


# =====================================================================
# 6. ADVISORY RULE ADVERSE WEATHER AHEAD
# =====================================================================

def test_adverse_weather_ahead_rule():
    rule = AdverseWeatherAheadRule(high_wind_threshold_knots=25.0, rough_sea_threshold_m=2.5)
    assert rule.rule_id == "MET_AHEAD_ADVERSE_001"
    assert rule.category == AdvisoryCategory.WEATHER

    # Create synthetic route weather profile with 1 calm and 1 adverse record
    rec_calm = NormalizedWeatherRecord(
        latitude=5.58,
        longitude=5.18,
        timestamp_utc="2026-06-15T12:00:00+00:00",
        data_source="MOCK",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=12.0,
        wave_height_m=1.0,
    )
    rec_storm = NormalizedWeatherRecord(
        latitude=6.10,
        longitude=3.80,
        timestamp_utc="2026-06-15T15:00:00+00:00",
        data_source="MOCK",
        data_type=WeatherProvenanceType.FORECAST,
        wind_speed_knots=32.0,
        wave_height_m=3.8,
    )

    route_profile = RouteWeatherProfile(
        route_id="ESCRAVOS_LAGOS",
        total_waypoints=2,
        waypoints_weather=[rec_calm, rec_storm],
    )

    voyage_ctx = VoyageContext(
        voyage_id="VOY_001",
        vessel=VesselContext(vessel_id="V01", ship_type="OSV"),
        route=Route(
            route_id="R01",
            origin_port="A",
            destination_port="B",
            waypoints=[
                RouteWaypoint(waypoint_id="WP1", latitude=5.58, longitude=5.18),
                RouteWaypoint(waypoint_id="WP2", latitude=6.10, longitude=3.80),
            ],
        ),
        current_position=VesselPosition(latitude=5.58, longitude=5.18, timestamp_utc="2026-06-15T12:00:00+00:00"),
        timeline=VoyageTimeline(current_time_utc="2026-06-15T12:00:00+00:00"),
        weather_context=VoyageWeatherContext(route_weather=route_profile),
    )

    decision_ctx = DecisionContext(
        decision_context_id="DC_001",
        created_at_utc="2026-06-15T12:00:00+00:00",
        voyage_context=voyage_ctx,
    )

    advisories = rule.evaluate(decision_ctx)
    assert len(advisories) == 2  # 1 for high wind, 1 for rough sea
    for adv in advisories:
        assert adv.severity == AdvisorySeverity.WARNING
        assert adv.human_review_required is True
        assert len(adv.evidence) == 1
        assert adv.evidence[0].rule_id == "MET_AHEAD_ADVERSE_001"


# =====================================================================
# 7. OPERATOR SERVICE & FASTAPI REST INTEGRATION
# =====================================================================

def test_operator_service_get_route_weather_lookahead(sample_route, moving_position, mock_weather_provider):
    service = OperatorService()
    result = service.get_route_weather_lookahead(
        position=moving_position,
        route=sample_route,
        weather_provider=mock_weather_provider,
        vessel_id="VESSEL_OSV_01",
    )

    assert isinstance(result, RouteWeatherLookAhead)
    assert result.route_id == "ESCRAVOS_LAGOS"
    assert result.timing_status == LookAheadTimingStatus.ESTIMATED
    assert len(result.waypoints) == 4


def test_fastapi_weather_lookahead_endpoint(sample_route, moving_position, mock_weather_provider):
    app = create_app(weather_provider=mock_weather_provider)
    client = TestClient(app)
    req_body = {
        "position": moving_position.model_dump(mode="json"),
        "route": sample_route.model_dump(mode="json"),
        "vessel_id": "VESSEL_OSV_01",
        "reference_time_utc": "2026-06-15T12:00:00+00:00",
    }

    response = client.post("/api/v1/operator/weather/lookahead", json=req_body)
    assert response.status_code == 200
    data = response.json()
    assert data["route_id"] == "ESCRAVOS_LAGOS"
    assert data["timing_status"] == "ESTIMATED"
    assert len(data["waypoints"]) == 4
    assert data["summary"]["total_lookahead_distance_nm"] > 0.0


# =====================================================================
# 8. SAFETY BOUNDARY INVARIANT CHECK
# =====================================================================

def test_safety_boundary_zero_actuation(sample_route, moving_position, mock_weather_provider):
    """
    Verifies that no actuator commands, rudder angles, engine speed demands,
    or bridge control outputs are exposed or generated.
    """
    engine = RouteWeatherLookAheadEngine()
    result = engine.compute_lookahead(
        position=moving_position,
        route=sample_route,
        weather_provider=mock_weather_provider,
    )

    data = result.model_dump()
    forbidden_keys = [
        "rudder_angle_deg",
        "engine_throttle_pct",
        "set_rpm",
        "autopilot_engaged",
        "actuator_command",
        "steering_mode",
    ]

    for key in forbidden_keys:
        assert key not in data
