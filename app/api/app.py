"""
app/api/app.py — Phase 10C.9 / 10C.10 FastAPI Application Entrypoint & Factory
==============================================================================
Defines the create_app() factory for the maritime engineering, operator, and
persistent voyage state API transport boundary.

Key Invariants:
  - Deterministic initialization with zero startup network calls or external database connects.
  - Dependency injection for application services, state repositories, and weather connectors.
  - Standardized error handlers mapping exceptions to structured APIErrorResponse.
  - Strict absence of actuation or autonomous control routes.
  - Safe import and instantiation during unit/integration tests.
"""

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies import (
    _DEFAULT_AUDIT_REPO,
    _DEFAULT_REPO,
    _DEFAULT_TELEMETRY_GATEWAY,
    get_engineering_service,
    get_operator_service,
    get_state_repository,
    get_telemetry_audit_repository,
    get_telemetry_gateway,
    get_weather_provider,
)
from app.api.engineering import router as engineering_router
from app.api.errors import (
    facade_execution_exception_handler,
    facade_generic_exception_handler,
    facade_validation_exception_handler,
    http_exception_handler,
    request_validation_exception_handler,
    state_conflict_exception_handler,
    state_not_found_exception_handler,
    state_validation_exception_handler,
    unhandled_exception_handler,
)
from app.api.operator import router as operator_router
from app.facade.scenario_facade import (
    FacadeError,
    FacadeExecutionError,
    FacadeValidationError,
)
from app.services.engineering_service import EngineeringService
from app.services.operator_service import OperatorService
from app.state.contracts import (
    StateConflictError,
    StateNotFoundError,
    StateValidationError,
)
from app.state.repository import StateRepository
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.nmea_adapter import NMEAUdpReceiver
from app.telemetry.repository import TelemetryAuditRepository
from app.weather.provider import WeatherProvider


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    FastAPI lifespan manager handling application startup and shutdown.
    Manages the lifecycle of the NMEA 0183 UDP telemetry receiver.
    """
    # Startup: Start NMEA UDP receiver if enabled
    enable_nmea = getattr(app.state, "enable_nmea_receiver", True)
    if enable_nmea:
        gateway = getattr(app.state, "telemetry_gateway", None) or _DEFAULT_TELEMETRY_GATEWAY
        receiver = getattr(app.state, "nmea_receiver", None)
        if receiver is None:
            host = getattr(app.state, "nmea_host", None)
            port = getattr(app.state, "nmea_port", None)
            receiver = NMEAUdpReceiver(gateway=gateway, host=host, port=port)
            app.state.nmea_receiver = receiver
        if not receiver.is_running:
            try:
                receiver.start()
            except Exception:
                pass
    yield
    # Shutdown: Stop receiver and release UDP socket
    receiver = getattr(app.state, "nmea_receiver", None)
    if receiver is not None:
        receiver.stop()
        app.state.nmea_receiver = None


def create_app(
    engineering_service: Optional[EngineeringService] = None,
    operator_service: Optional[OperatorService] = None,
    state_repository: Optional[StateRepository] = None,
    weather_provider: Optional[WeatherProvider] = None,
    telemetry_gateway: Optional[TelemetryGateway] = None,
    telemetry_audit_repository: Optional[TelemetryAuditRepository] = None,
    enable_nmea_receiver: bool = True,
    nmea_host: Optional[str] = None,
    nmea_port: Optional[int] = None,
) -> FastAPI:
    """
    Application factory for the Maritime Decision Support API.

    Args:
        engineering_service: Optional custom or mocked EngineeringService.
        operator_service: Optional custom or mocked OperatorService.
        state_repository: Optional custom or mocked StateRepository.
        weather_provider: Optional custom or mocked WeatherProvider.
        telemetry_gateway: Optional custom TelemetryGateway instance.
        telemetry_audit_repository: Optional custom TelemetryAuditRepository.
        enable_nmea_receiver: Whether to start the NMEA UDP receiver during lifespan startup.
        nmea_host: Optional host IP for NMEA UDP receiver (defaults to NMEA_UDP_HOST or 0.0.0.0).
        nmea_port: Optional port for NMEA UDP receiver (defaults to NMEA_UDP_PORT or 10110).

    Returns:
        FastAPI application instance with configured routers, error handlers, and dependencies.
    """
    app = FastAPI(
        title="Maritime Engineering & Operator Decision Support API",
        version="1.0.0",
        description=(
            "Application API transport boundary exposing verified maritime engineering "
            "simulations, operator situational awareness, and persistent voyage state."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=app_lifespan,
    )

    # Store state on application instance
    app.state.telemetry_gateway = telemetry_gateway or _DEFAULT_TELEMETRY_GATEWAY
    app.state.telemetry_audit_repository = telemetry_audit_repository or _DEFAULT_AUDIT_REPO
    app.state.enable_nmea_receiver = enable_nmea_receiver
    app.state.nmea_host = nmea_host
    app.state.nmea_port = nmea_port
    app.state.nmea_receiver = None

    # 1. Register Exception Handlers
    app.add_exception_handler(FacadeValidationError, facade_validation_exception_handler)
    app.add_exception_handler(FacadeExecutionError, facade_execution_exception_handler)
    app.add_exception_handler(FacadeError, facade_generic_exception_handler)
    app.add_exception_handler(StateNotFoundError, state_not_found_exception_handler)
    app.add_exception_handler(StateConflictError, state_conflict_exception_handler)
    app.add_exception_handler(StateValidationError, state_validation_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # 2. Dependency Overrides (if explicit instances provided)
    if engineering_service is not None:
        app.dependency_overrides[get_engineering_service] = lambda: engineering_service
    if state_repository is not None:
        app.dependency_overrides[get_state_repository] = lambda: state_repository
    if operator_service is not None:
        app.dependency_overrides[get_operator_service] = lambda: operator_service
    if weather_provider is not None:
        app.dependency_overrides[get_weather_provider] = lambda: weather_provider
    if telemetry_gateway is not None:
        app.dependency_overrides[get_telemetry_gateway] = lambda: telemetry_gateway
    if telemetry_audit_repository is not None:
        app.dependency_overrides[get_telemetry_audit_repository] = lambda: telemetry_audit_repository

    # 3. Include API Routers under /api/v1 prefix
    app.include_router(engineering_router, prefix="/api/v1")
    app.include_router(operator_router, prefix="/api/v1")

    # 4. Root & General Health Endpoints
    @app.get("/", status_code=status.HTTP_200_OK, tags=["System"])
    def root() -> Dict[str, Any]:
        return {
            "name": "Maritime Engineering & Operator Decision Support API",
            "version": "1.0.0",
            "status": "online",
            "dashboard": "/dashboard",
            "documentation": "/docs",
        }

    @app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
    def health() -> Dict[str, str]:
        return {"status": "healthy"}

    # 5. Mount Frontend Static Dashboard
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
    if os.path.isdir(frontend_dir):
        @app.middleware("http")
        async def add_no_cache_header(request, call_next):
            response = await call_next(request)
            if not request.url.path.startswith("/api"):
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response

        app.mount("/dashboard", StaticFiles(directory=frontend_dir, html=True), name="dashboard")
        app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

        pages_dir = os.path.join(frontend_dir, "pages")
        if os.path.isdir(pages_dir):
            app.mount("/pages", StaticFiles(directory=pages_dir), name="pages")
        components_dir = os.path.join(frontend_dir, "components")
        if os.path.isdir(components_dir):
            app.mount("/components", StaticFiles(directory=components_dir), name="components")

        # Explicit root-level routes for styles.css, app.js and index.html
        @app.get("/styles.css", include_in_schema=False)
        def serve_root_styles():
            return FileResponse(os.path.join(frontend_dir, "styles.css"), media_type="text/css")

        @app.get("/app.js", include_in_schema=False)
        def serve_root_app():
            return FileResponse(os.path.join(frontend_dir, "app.js"), media_type="application/javascript")

        @app.get("/dashboard", include_in_schema=False)
        def serve_dashboard_page():
            return FileResponse(os.path.join(frontend_dir, "index.html"), media_type="text/html")

    return app
