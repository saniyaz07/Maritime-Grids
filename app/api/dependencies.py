"""
app/api/dependencies.py — Phase 10C.9 / 10C.10 Service & Repository Dependency Injection
========================================================================================
Provides FastAPI dependency providers for application services, state repositories,
and weather connectors. Enables deterministic testing and dependency overriding.

Key Invariants:
  - Zero network calls on dependency initialization.
  - Zero global state leakage.
  - Testable via FastAPI app.dependency_overrides.
"""

from typing import Optional
from fastapi import Depends

from app.services.engineering_service import EngineeringService
from app.services.operator_service import OperatorService
from app.state.memory_repository import InMemoryStateRepository
from app.state.repository import StateRepository
from app.telemetry.energy_estimator import VirtualEnergyEstimator
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.repository import TelemetryAuditRepository
from app.weather.provider import WeatherProvider
from app.weather.open_meteo_provider import OpenMeteoWeatherProvider

from app.telemetry.simulator import VirtualVesselSimulator

# Default process-level repository instances
_DEFAULT_REPO = InMemoryStateRepository()
_DEFAULT_AUDIT_REPO = InMemoryTelemetryAuditRepository()
_DEFAULT_ENERGY_ESTIMATOR = VirtualEnergyEstimator(ship_type="Oil Service Boat")
_DEFAULT_WEATHER_PROVIDER = OpenMeteoWeatherProvider()
_DEFAULT_TELEMETRY_GATEWAY = TelemetryGateway(
    repository=_DEFAULT_AUDIT_REPO,
    energy_estimator=_DEFAULT_ENERGY_ESTIMATOR,
)
_DEFAULT_VIRTUAL_SIMULATOR = VirtualVesselSimulator(
    vessel_id="VESSEL_OSV_01",
    ship_type="Oil Service Boat",
    route_id="Escravos-Lagos",
    gateway=_DEFAULT_TELEMETRY_GATEWAY,
    weather_provider=_DEFAULT_WEATHER_PROVIDER,
)


def get_state_repository() -> StateRepository:
    """Provides the active StateRepository instance."""
    return _DEFAULT_REPO


def get_telemetry_audit_repository() -> TelemetryAuditRepository:
    """Provides the active TelemetryAuditRepository instance."""
    return _DEFAULT_AUDIT_REPO


def get_telemetry_gateway(
    audit_repo: TelemetryAuditRepository = Depends(get_telemetry_audit_repository),
) -> TelemetryGateway:
    """Provides the active TelemetryGateway instance."""
    return _DEFAULT_TELEMETRY_GATEWAY


def get_virtual_simulator(
    gateway: TelemetryGateway = Depends(get_telemetry_gateway),
) -> VirtualVesselSimulator:
    """Provides the active VirtualVesselSimulator instance."""
    return _DEFAULT_VIRTUAL_SIMULATOR



def get_engineering_service() -> EngineeringService:
    """Provides an instance of EngineeringService."""
    return EngineeringService()


def get_operator_service(
    repository: StateRepository = Depends(get_state_repository),
) -> OperatorService:
    """Provides an instance of OperatorService with injected StateRepository."""
    return OperatorService(repository=repository)


def get_weather_provider() -> WeatherProvider:
    """Provides a default WeatherProvider instance."""
    return _DEFAULT_WEATHER_PROVIDER

