"""
tests/test_application_api.py — Phase 10C.9 API Transport Boundary Verification Suite
======================================================================================
Comprehensive test suite verifying the FastAPI application transport boundary.

Coverage Matrix:
  - Application factory & OpenAPI schema generation (Tests 1-3)
  - Operator API situational awareness & telemetry (Tests 4-15)
  - Engineering API 10-operation delegation (Tests 16-25)
  - Security, error handling, no-autonomy, & no-physics audits (Tests 26-36)
"""

import inspect
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import pytest
from starlette.testclient import TestClient

from app.advisory.contracts import (
    Advisory,
    AdvisoryCategory,
    AdvisoryPolicy,
    AdvisorySeverity,
    BatterySocPolicy,
    FuelLevelPolicy,
    WeatherSafetyPolicy,
)
from app.api.app import create_app
from app.api.dependencies import get_operator_service, get_weather_provider
from app.api.errors import APIErrorResponse
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
    EngineeringDecisionInputs,
)
from app.facade.contracts import (
    BreakEvenAnalysisRequest,
    CIIComplianceTrajectoryRequest,
    DossierExportFacadeRequest,
    EvaluateSizingCandidateRequest,
    Grid2DAnalysisRequest,
    OptimizeSystemSizingRequest,
    PortfolioOptimizationFacadeRequest,
    SensitivityAnalysisRequest,
    SimulateVoyageRequest,
    SpeedCoOptimizationFacadeRequest,
)
from app.services.contracts import OperatorStateResponse
from app.services.engineering_service import EngineeringService
from app.services.operator_service import OperatorService
from app.voyage.contracts import (
    Route,
    RouteWaypoint,
    VesselContext,
    VesselEnergyState,
    VesselPosition,
    VoyageContext,
    VoyageStatus,
    VoyageTimeline,
    VoyageWeatherContext,
)
from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.mock_provider import MockWeatherProvider
from app.weather.provider import WeatherProvider
from phase8_contracts import OptimizationCandidate
from phase9_contracts import ParameterSweepBounds
from phase9_dossier_contracts import ExportFormatEnum
from phase9_portfolio_optimizer import make_portfolio_item


# =====================================================================
# FIXTURES & HELPER DATA
# =====================================================================

class FailingWeatherProvider(WeatherProvider):
    """WeatherProvider that raises runtime errors to test error handling."""

    @property
    def provider_name(self) -> str:
        return "FailingWeatherProvider"

    def get_current_weather(self, latitude: float, longitude: float) -> NormalizedWeatherRecord:
        raise RuntimeError("External weather provider network timeout")

    def get_historical_weather(self, latitude: float, longitude: float, timestamp: Any):
        raise RuntimeError("External weather provider network timeout")

    def get_forecast_weather(self, latitude: float, longitude: float, horizon_hours: int = 24, step_hours: int = 1):
        raise RuntimeError("External weather provider network timeout")


class ConfigurableWeatherProvider(MockWeatherProvider):
    """Deterministic mock provider for testing explicit provenance, quality, and freshness states."""

    def __init__(
        self,
        custom_provenance: WeatherProvenanceType = WeatherProvenanceType.OBSERVED,
        custom_quality: WeatherQualityState = WeatherQualityState.VALID,
        custom_freshness: WeatherFreshnessState = WeatherFreshnessState.FRESH,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.custom_provenance = custom_provenance
        self.custom_quality = custom_quality
        self.custom_freshness = custom_freshness

    def get_current_weather(self, latitude: float, longitude: float) -> NormalizedWeatherRecord:
        rec = super().get_current_weather(latitude, longitude)
        rec.data_type = self.custom_provenance
        rec.data_quality = self.custom_quality
        rec.freshness = self.custom_freshness
        return rec


def create_sample_vessel() -> VesselContext:
    return VesselContext(
        vessel_id="VESSEL_OSV_LAGOS_01",
        ship_type="Oil Service Boat",
        design_speed_knots=12.0,
        max_speed_knots=14.5,
        displacement_tonnes=2500.0,
        engine_power_kw=4500.0,
        battery_pack_capacity_kwh=649.7,
        solar_panel_size_m2=80.0,
        fuel_price_usd_per_liter=1.15,
        provenance=WeatherProvenanceType.OBSERVED,
    )


def create_sample_route() -> Route:
    return Route(
        route_id="ESCRAVOS_LAGOS",
        origin_port="Escravos Terminal",
        destination_port="Lagos Port",
        waypoints=[
            RouteWaypoint(waypoint_id="WP1", latitude=5.58, longitude=5.18),
            RouteWaypoint(waypoint_id="WP2", latitude=5.80, longitude=4.50),
            RouteWaypoint(waypoint_id="WP3", latitude=6.45, longitude=3.40),
        ],
        total_distance_nm=130.0,
    )


def create_sample_position() -> VesselPosition:
    return VesselPosition(
        latitude=5.80,
        longitude=4.50,
        timestamp_utc="2026-06-15T12:00:00Z",
        speed_over_ground_knots=12.0,
        course_over_ground_deg=285.0,
    )


def create_sample_voyage_context() -> VoyageContext:
    pos = create_sample_position()
    wx_record = NormalizedWeatherRecord(
        timestamp_utc="2026-06-15T12:00:00Z",
        retrieval_timestamp_utc="2026-06-15T12:00:00Z",
        latitude=5.80,
        longitude=4.50,
        wind_speed_knots=14.0,
        wind_speed_ms=7.2,
        wind_direction_deg=180.0,
        wave_height_m=1.5,
        wave_direction_deg=190.0,
        wave_period_s=6.0,
        temperature_c=26.0,
        relative_humidity_pct=65.0,
        surface_pressure_hpa=1013.0,
        solar_irradiance_w_per_m2=700.0,
        daily_ghi_kwh_per_m2=5.5,
        data_source="MockProvider",
        data_type=WeatherProvenanceType.OBSERVED,
        data_quality=WeatherQualityState.VALID,
        freshness=WeatherFreshnessState.FRESH,
    )
    wx_ctx = VoyageWeatherContext(
        current_weather=wx_record,
        weather_quality=WeatherQualityState.VALID,
        weather_freshness=WeatherFreshnessState.FRESH,
    )
    energy = VesselEnergyState(
        battery_soc_pct=85.0,
        battery_soh_pct=99.0,
        battery_energy_available_kwh=550.0,
        solar_power_kw=15.0,
        solar_energy_today_kwh=50.0,
        fuel_remaining_liters=6000.0,
        fuel_consumption_rate_lph=170.0,
    )
    timeline = VoyageTimeline(
        current_time_utc="2026-06-15T12:00:00Z",
        planned_departure_utc="2026-06-15T08:00:00Z",
        actual_departure_utc="2026-06-15T08:30:00Z",
        planned_arrival_utc="2026-06-15T20:00:00Z",
    )
    return VoyageContext(
        voyage_id="VOYAGE_TEST_001",
        status=VoyageStatus.ACTIVE,
        vessel=create_sample_vessel(),
        route=create_sample_route(),
        current_position=pos,
        timeline=timeline,
        weather_context=wx_ctx,
        energy_state=energy,
    )


def create_sample_decision_context() -> DecisionContext:
    voyage = create_sample_voyage_context()
    eng = EngineeringDecisionInputs(
        baseline_fuel_consumption_liters=3259.7,
        estimated_solar_energy_kwh=68.5,
        estimated_battery_displacement_kwh=120.0,
        total_clean_energy_kwh=188.5,
        co2_emissions_kg=8628.2,
        cii_attained_rating="A",
        optimal_transit_speed_knots=11.5,
        net_present_value_usd=145000.0,
        payback_period_years=4.2,
    )
    return DecisionContext(
        decision_context_id="DC_TEST_001",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=voyage,
        engineering_inputs=eng,
    )


@pytest.fixture
def client() -> TestClient:
    app = create_app(weather_provider=MockWeatherProvider())
    return TestClient(app)


# =====================================================================
# APPLICATION & OPENAPI TESTS (Tests 1–3)
# =====================================================================

def test_01_create_app_succeeds():
    """Verify create_app produces a valid FastAPI application."""
    app = create_app()
    assert app is not None
    assert app.title == "Maritime Engineering & Operator Decision Support API"


def test_02_app_import_and_root_endpoints(client: TestClient):
    """Verify application root and health endpoints return HTTP 200 without side effects."""
    resp_root = client.get("/")
    assert resp_root.status_code == 200
    assert resp_root.json()["status"] == "online"

    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "healthy"


def test_03_openapi_schema_generation(client: TestClient):
    """Verify OpenAPI JSON schema is automatically generated and contains required routes."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "paths" in schema
    paths = schema["paths"]
    assert "/api/v1/operator/state" in paths
    assert "/api/v1/engineering/simulate-voyage" in paths
    assert "/api/v1/engineering/optimize-sizing" in paths


# =====================================================================
# OPERATOR API TESTS (Tests 4–15)
# =====================================================================

def test_04_operator_state_from_decision_context(client: TestClient):
    """Verify POST /api/v1/operator/state returns valid OperatorStateResponse."""
    dc = create_sample_decision_context()
    payload = {"context": dc.model_dump(mode="json")}
    resp = client.post("/api/v1/operator/state", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["vessel"]["vessel_id"] == "VESSEL_OSV_LAGOS_01"
    assert data["regulatory"]["compliance_state"] == "COMPLIANT"
    assert "metadata" in data


def test_05_operator_response_conforms_to_contract(client: TestClient):
    """Verify parsed response matches OperatorStateResponse Pydantic model exactly."""
    dc = create_sample_decision_context()
    resp = client.post("/api/v1/operator/state", json={"context": dc.model_dump(mode="json")})
    assert resp.status_code == 200
    state = OperatorStateResponse.model_validate(resp.json())
    assert state.vessel.ship_type == "Oil Service Boat"
    assert state.energy.battery_soc_pct == 85.0


def test_06_weather_provenance_preserved(client: TestClient):
    """Verify weather provenance (OBSERVED) is truthfully preserved over API."""
    dc = create_sample_decision_context()
    resp = client.post("/api/v1/operator/state", json={"context": dc.model_dump(mode="json")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["weather"]["provenance"] == "OBSERVED"


def test_07_weather_quality_preserved(client: TestClient):
    """Verify weather quality (VALID) is preserved."""
    dc = create_sample_decision_context()
    resp = client.post("/api/v1/operator/state", json={"context": dc.model_dump(mode="json")})
    assert resp.status_code == 200
    assert resp.json()["weather"]["quality"] == "VALID"


def test_08_weather_freshness_preserved(client: TestClient):
    """Verify weather freshness classification is preserved."""
    dc = create_sample_decision_context()
    resp = client.post("/api/v1/operator/state", json={"context": dc.model_dump(mode="json")})
    assert resp.status_code == 200
    assert resp.json()["weather"]["freshness"] == "FRESH"


def test_09_missing_telemetry_remains_none(client: TestClient):
    """Verify unmeasured telemetry fields remain None and are never replaced by 0.0."""
    voyage = create_sample_voyage_context()
    voyage.energy_state = VesselEnergyState()
    dc = DecisionContext(
        decision_context_id="DC_MISSING_001",
        created_at_utc="2026-06-15T12:00:00Z",
        voyage_context=voyage,
    )
    resp = client.post("/api/v1/operator/state", json={"context": dc.model_dump(mode="json")})
    assert resp.status_code == 200
    data = resp.json()
    assert data["energy"]["battery_soc_pct"] is None
    assert data["energy"]["fuel_remaining_liters"] is None
    assert data["energy"]["solar_power_kw"] is None


def test_10_human_review_required_enforced(client: TestClient):
    """Verify human_review_required=True is enforced on every advisory item."""
    policy = AdvisoryPolicy(
        battery_policy=BatterySocPolicy(notice_threshold_pct=90.0),
    )
    dc = create_sample_decision_context()  # SoC is 85.0%, which is < 90.0% notice threshold
    payload = {
        "context": dc.model_dump(mode="json"),
        "policy": policy.model_dump(mode="json"),
    }
    resp = client.post("/api/v1/operator/state", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["advisories"]["total_count"] > 0
    for item in data["advisories"]["items"]:
        assert item["human_review_required"] is True


def test_11_explicit_policy_respected(client: TestClient):
    """Verify that supplied AdvisoryPolicy directly determines advisory generation."""
    high_policy = AdvisoryPolicy(
        weather_policy=WeatherSafetyPolicy(high_wind_threshold_knots=30.0),
    )
    low_policy = AdvisoryPolicy(
        weather_policy=WeatherSafetyPolicy(high_wind_threshold_knots=10.0),
    )
    dc = create_sample_decision_context()  # wind is 14.0 kts

    resp_high = client.post(
        "/api/v1/operator/state",
        json={"context": dc.model_dump(mode="json"), "policy": high_policy.model_dump(mode="json")},
    )
    assert resp_high.status_code == 200
    assert resp_high.json()["advisories"]["total_count"] == 0

    resp_low = client.post(
        "/api/v1/operator/state",
        json={"context": dc.model_dump(mode="json"), "policy": low_policy.model_dump(mode="json")},
    )
    assert resp_low.status_code == 200
    assert resp_low.json()["advisories"]["total_count"] > 0


def test_12_no_hidden_threshold_defaults(client: TestClient):
    """Verify that without policy, no arbitrary threshold alerts (20%, 35%, etc.) are triggered."""
    dc = create_sample_decision_context()
    resp = client.post("/api/v1/operator/state", json={"context": dc.model_dump(mode="json")})
    assert resp.status_code == 200
    assert resp.json()["advisories"]["total_count"] == 0


def test_13_operator_telemetry_endpoint(client: TestClient):
    """Verify POST /api/v1/operator/state/from-telemetry enriches weather and returns valid state."""
    vessel = create_sample_vessel()
    route = create_sample_route()
    pos = create_sample_position()
    payload = {
        "vessel": vessel.model_dump(mode="json"),
        "route": route.model_dump(mode="json"),
        "position": pos.model_dump(mode="json"),
    }
    resp = client.post("/api/v1/operator/state/from-telemetry", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["weather"]["provenance"] == "OBSERVED"
    assert data["vessel"]["vessel_id"] == "VESSEL_OSV_LAGOS_01"


def test_14_stale_weather_remains_stale():
    """Verify that stale weather telemetry is preserved as STALE in the API response."""
    provider = ConfigurableWeatherProvider(custom_freshness=WeatherFreshnessState.STALE)
    custom_app = create_app(weather_provider=provider)
    custom_client = TestClient(custom_app)

    payload = {
        "vessel": create_sample_vessel().model_dump(mode="json"),
        "route": create_sample_route().model_dump(mode="json"),
        "position": create_sample_position().model_dump(mode="json"),
    }
    resp = custom_client.post("/api/v1/operator/state/from-telemetry", json=payload)
    assert resp.status_code == 200
    assert resp.json()["weather"]["freshness"] == "STALE"


def test_15_invalid_weather_remains_invalid():
    """Verify that invalid weather telemetry is preserved as INVALID in the API response."""
    provider = ConfigurableWeatherProvider(custom_quality=WeatherQualityState.INVALID)
    custom_app = create_app(weather_provider=provider)
    custom_client = TestClient(custom_app)

    payload = {
        "vessel": create_sample_vessel().model_dump(mode="json"),
        "route": create_sample_route().model_dump(mode="json"),
        "position": create_sample_position().model_dump(mode="json"),
    }
    resp = custom_client.post("/api/v1/operator/state/from-telemetry", json=payload)
    assert resp.status_code == 200
    assert resp.json()["weather"]["quality"] == "INVALID"


# =====================================================================
# ENGINEERING API TESTS (10 OPERATIONS: Tests 16–25)
# =====================================================================

def test_16_engineering_simulate_voyage(client: TestClient):
    """Verify POST /api/v1/engineering/simulate-voyage endpoint."""
    payload = {
        "ship_type": "Tanker Ship",
        "route_id": "Escravos-Lagos",
        "month": 6,
        "speed_knots": 12.0,
        "distance_nm": 250.0,
        "solar_area_m2": 100.0,
        "battery_capacity_kwh": 200.0,
    }
    resp = client.post("/api/v1/engineering/simulate-voyage", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"
    assert "data" in data
    assert "tier1_predictions" in data["data"]


def test_17_engineering_evaluate_sizing(client: TestClient):
    """Verify POST /api/v1/engineering/evaluate-sizing endpoint."""
    payload = {
        "ship_type": "Tanker Ship",
        "solar_area_m2": 100.0,
        "battery_capacity_kwh": 200.0,
        "deck_area_limit_m2": 833.0,
        "battery_weight_limit_tonnes": 700.0,
        "predicted_soh": 0.7387438,
        "auxiliary_energy_demand_kwh": 400.0,
        "voyage_duration_hours": 40.5,
        "predicted_fuel_consumption_L": 20124.3,
        "predicted_CO2_kg": 53268.0,
        "daily_ghi_kwh_per_m2": 4.5,
        "annual_voyages": 52,
    }
    resp = client.post("/api/v1/engineering/evaluate-sizing", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"
    assert "net_present_value_usd" in data["data"]


def test_18_engineering_optimize_sizing(client: TestClient):
    """Verify POST /api/v1/engineering/optimize-sizing endpoint."""
    payload = {
        "ship_type": "Surfer Boat",
        "min_solar_area_m2": 0.0,
        "max_solar_area_m2": 20.0,
        "step_solar_area_m2": 10.0,
        "min_battery_capacity_kwh": 0.0,
        "max_battery_capacity_kwh": 50.0,
        "step_battery_capacity_kwh": 25.0,
        "objective": "MAX_NPV",
    }
    resp = client.post("/api/v1/engineering/optimize-sizing", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"
    assert "optimal_candidate" in data["data"]


def test_19_engineering_sensitivity_analysis(client: TestClient):
    """Verify POST /api/v1/engineering/sensitivity-analysis endpoint."""
    eng_service = EngineeringService()
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = eng_service.optimize_system_sizing(opt_req).data.optimal_candidate

    payload = {
        "base_candidate": base_cand.model_dump(mode="json"),
        "parameter_name": "fuel_price_usd_per_l",
        "metric_name": "net_present_value_usd",
        "ship_type": "Surfer Boat",
    }
    resp = client.post("/api/v1/engineering/sensitivity-analysis", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"


def test_20_engineering_break_even_analysis(client: TestClient):
    """Verify POST /api/v1/engineering/break-even-analysis endpoint."""
    eng_service = EngineeringService()
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = eng_service.optimize_system_sizing(opt_req).data.optimal_candidate

    payload = {
        "base_candidate": base_cand.model_dump(mode="json"),
        "parameter_name": "fuel_price_usd_per_l",
        "metric_name": "net_present_value_usd",
        "lower_bound": 0.5,
        "upper_bound": 5.0,
        "ship_type": "Surfer Boat",
    }
    resp = client.post("/api/v1/engineering/break-even-analysis", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"


def test_21_engineering_grid_2d_analysis(client: TestClient):
    """Verify POST /api/v1/engineering/grid-2d-analysis endpoint."""
    eng_service = EngineeringService()
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Surfer Boat",
        min_solar_area_m2=0.0,
        max_solar_area_m2=10.0,
        step_solar_area_m2=10.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=25.0,
        step_battery_capacity_kwh=25.0,
    )
    base_cand = eng_service.optimize_system_sizing(opt_req).data.optimal_candidate

    payload = {
        "base_candidate": base_cand.model_dump(mode="json"),
        "parameter_x_name": "fuel_price_usd_per_l",
        "parameter_y_name": "discount_rate",
        "sweep_bounds_x": {
            "parameter_name": "fuel_price_usd_per_l",
            "min_value": 0.8,
            "max_value": 1.2,
            "step": 0.2,
        },
        "sweep_bounds_y": {
            "parameter_name": "discount_rate",
            "min_value": 0.06,
            "max_value": 0.10,
            "step": 0.02,
        },
        "ship_type": "Surfer Boat",
    }
    resp = client.post("/api/v1/engineering/grid-2d-analysis", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"


def test_22_engineering_speed_cooptimization(client: TestClient):
    """Verify POST /api/v1/engineering/speed-cooptimization endpoint."""
    payload = {
        "ship_type": "Tanker Ship",
        "route_id": "Escravos-Lagos",
        "vmin": 10.0,
        "vmax": 12.0,
        "v_step": 1.0,
        "apv_min": 0.0,
        "apv_max": 50.0,
        "apv_step": 50.0,
        "ebatt_min": 0.0,
        "ebatt_max": 100.0,
        "ebatt_step": 50.0,
    }
    resp = client.post("/api/v1/engineering/speed-cooptimization", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"


def test_23_engineering_portfolio_optimization(client: TestClient):
    """Verify POST /api/v1/engineering/portfolio-optimization endpoint."""
    eng_service = EngineeringService()
    opt_req = OptimizeSystemSizingRequest(
        ship_type="Tanker Ship",
        min_solar_area_m2=0.0,
        max_solar_area_m2=50.0,
        step_solar_area_m2=50.0,
        min_battery_capacity_kwh=0.0,
        max_battery_capacity_kwh=100.0,
        step_battery_capacity_kwh=50.0,
    )
    cand = eng_service.optimize_system_sizing(opt_req).data.optimal_candidate
    item = make_portfolio_item(
        vessel_id="TANKER_01",
        candidate=cand,
        ship_type="Tanker Ship",
        route_id="Escravos-Lagos",
    )

    payload = {
        "total_portfolio_capex_budget_usd": 500000.0,
        "portfolio_items": [item.model_dump(mode="json")],
    }
    resp = client.post("/api/v1/engineering/portfolio-optimization", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"


def test_24_engineering_cii_trajectory(client: TestClient):
    """Verify POST /api/v1/engineering/cii-trajectory endpoint."""
    payload = {
        "vessel_id": "TANKER_01",
        "ship_type": "Tanker Ship",
        "dwt_tonnes": 14000.0,
        "route_id": "Escravos-Lagos",
        "voyage_distance_nm": 250.0,
        "annual_voyages": 52,
        "baseline_single_voyage_fuel_L": 20124.3,
        "baseline_single_voyage_co2_kg": 53268.0,
        "start_year": 2023,
        "end_year": 2026,
        "annual_fuel_displaced_L": 3259.7,
        "annual_co2_displaced_kg": 8628.2,
    }
    resp = client.post("/api/v1/engineering/cii-trajectory", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"


def test_25_engineering_export_dossier(client: TestClient):
    """Verify POST /api/v1/engineering/export-dossier endpoint."""
    eng_service = EngineeringService()
    sim_res = eng_service.simulate_voyage(
        SimulateVoyageRequest(ship_type="Tanker Ship", route_id="Escravos-Lagos", speed_knots=12.0)
    ).data

    payload = {
        "scenario_name": "TEST_SCENARIO",
        "vessel_id": "VESSEL_01",
        "ship_type": "Tanker Ship",
        "route_id": "Escravos-Lagos",
        "export_formats": ["JSON"],
        "phase6_result": sim_res.model_dump(mode="json"),
    }
    resp = client.post("/api/v1/engineering/export-dossier", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["provenance"]["status"] == "SUCCESS"
    assert "dossier" in data["data"]


# =====================================================================
# SECURITY, ERROR HANDLING, & NO-AUTONOMY AUDIT (Tests 26–36)
# =====================================================================

def test_26_invalid_request_schema_returns_422(client: TestClient):
    """Verify invalid request payloads trigger HTTP 422 with structured APIErrorResponse."""
    resp = client.post("/api/v1/engineering/simulate-voyage", json={"invalid_field": 123})
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_type"] == "VALIDATION_ERROR"
    assert "timestamp_utc" in data


def test_27_no_actuation_endpoints_exist(client: TestClient):
    """Audit: Verify no actuation/vessel control endpoints exist in the API."""
    forbidden_routes = [
        "/api/v1/operator/throttle",
        "/api/v1/operator/rudder",
        "/api/v1/operator/steering",
        "/api/v1/operator/engine-start",
        "/api/v1/operator/engine-stop",
        "/api/v1/operator/engine-power",
        "/api/v1/operator/route-change",
        "/api/v1/operator/speed-change",
        "/api/v1/operator/actuation",
    ]
    for route in forbidden_routes:
        resp = client.post(route, json={})
        assert resp.status_code in (404, 405), f"Forbidden actuation route {route} returned {resp.status_code}"


def test_28_no_autonomous_control_code_in_api():
    """Audit: Search app/api source code for prohibited autonomous actuation keywords."""
    import app.api.app as app_mod
    import app.api.engineering as eng_mod
    import app.api.operator as op_mod

    modules = [app_mod, eng_mod, op_mod]
    forbidden_terms = [
        "set_throttle",
        "set_rudder",
        "execute_steering",
        "start_engine",
        "stop_engine",
        "override_route",
        "actuate",
    ]
    for mod in modules:
        source = inspect.getsource(mod)
        for term in forbidden_terms:
            assert term not in source, f"Forbidden term '{term}' found in {mod.__name__}"


def test_29_no_wind_propulsion_endpoints(client: TestClient):
    """Audit: Verify no wind propulsion / sail thrust endpoints exist."""
    forbidden_routes = [
        "/api/v1/engineering/sail",
        "/api/v1/engineering/rotor",
        "/api/v1/engineering/kite",
        "/api/v1/engineering/wind-thrust",
    ]
    for route in forbidden_routes:
        resp = client.post(route, json={})
        assert resp.status_code in (404, 405)


def test_30_no_engine_off_endpoints(client: TestClient):
    """Audit: Verify no engine-off calculation endpoints exist."""
    forbidden_routes = [
        "/api/v1/engineering/engine-off",
        "/api/v1/operator/engine-off",
    ]
    for route in forbidden_routes:
        resp = client.post(route, json={})
        assert resp.status_code in (404, 405)


def test_31_no_dynamic_code_execution_in_api():
    """Audit: Verify eval() and exec() are absent from app/api codebase."""
    import app.api.app as app_mod
    import app.api.engineering as eng_mod
    import app.api.operator as op_mod
    import app.api.errors as err_mod
    import app.api.dependencies as dep_mod

    modules = [app_mod, eng_mod, op_mod, err_mod, dep_mod]
    for mod in modules:
        source = inspect.getsource(mod)
        assert "eval(" not in source, f"eval() found in {mod.__name__}"
        assert "exec(" not in source, f"exec() found in {mod.__name__}"


def test_32_no_arbitrary_file_writes_in_api():
    """Audit: Verify open(..., 'w') or 'wb' file writes are absent from API routers."""
    import app.api.app as app_mod
    import app.api.engineering as eng_mod
    import app.api.operator as op_mod

    modules = [app_mod, eng_mod, op_mod]
    for mod in modules:
        source = inspect.getsource(mod)
        assert "open(" not in source, f"open() found in {mod.__name__}"


def test_33_no_direct_external_weather_calls_in_router():
    """Audit: Verify routers do not make raw HTTP calls to Open-Meteo or external APIs."""
    import app.api.engineering as eng_mod
    import app.api.operator as op_mod

    modules = [eng_mod, op_mod]
    for mod in modules:
        source = inspect.getsource(mod)
        assert "requests.get" not in source, f"Direct requests.get found in {mod.__name__}"
        assert "httpx.get" not in source, f"Direct httpx.get found in {mod.__name__}"
        assert "open-meteo.com" not in source, f"Direct open-meteo URL found in {mod.__name__}"


def test_34_provider_failure_produces_structured_error():
    """Verify that external weather provider failure triggers structured internal error handling."""
    custom_app = create_app(weather_provider=FailingWeatherProvider())
    custom_client = TestClient(custom_app, raise_server_exceptions=False)

    payload = {
        "vessel": create_sample_vessel().model_dump(mode="json"),
        "route": create_sample_route().model_dump(mode="json"),
        "position": create_sample_position().model_dump(mode="json"),
    }
    resp = custom_client.post("/api/v1/operator/state/from-telemetry", json=payload)
    assert resp.status_code == 500
    data = resp.json()
    assert data["error_type"] == "INTERNAL_SERVER_ERROR"
    assert "timestamp_utc" in data


def test_35_not_found_endpoint_returns_404(client: TestClient):
    """Verify non-existent API route returns HTTP 404 with structured error."""
    resp = client.get("/api/v1/nonexistent/endpoint")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_type"] == "NOT_FOUND"


def test_36_operator_voyage_endpoint(client: TestClient):
    """Verify POST /api/v1/operator/state/from-voyage returns valid operator state."""
    voyage = create_sample_voyage_context()
    payload = {"voyage_context": voyage.model_dump(mode="json")}
    resp = client.post("/api/v1/operator/state/from-voyage", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["vessel"]["vessel_id"] == "VESSEL_OSV_LAGOS_01"
