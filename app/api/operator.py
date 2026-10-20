"""
app/api/operator.py — Phase 10C.9 / 10C.10 Operator State Endpoints Router
==========================================================================
Exposes read-only operator state assembly, situational awareness, deterministic
decision-support advisories, and persistent voyage lifecycle endpoints over HTTP.

Key Invariants:
  - Read-only situational awareness & decision support.
  - Zero autonomous actuation or vessel control endpoints.
  - Strict preservation of data quality (VALID, PARTIAL, STALE, INVALID, UNAVAILABLE).
  - Strict preservation of weather provenance (OBSERVED, HISTORICAL, FORECAST, etc.).
  - Missing telemetry fields remain None (never 0.0 or fabricated).
  - Explicit advisory policy requirements; no hidden threshold defaults.
  - human_review_required = True on all advisories.
  - Persistent voyage lifecycle management via abstract StateRepository.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.advisory.contracts import AdvisoryPolicy
from app.api.dependencies import (
    get_operator_service,
    get_telemetry_audit_repository,
    get_telemetry_gateway,
    get_virtual_simulator,
    get_weather_provider,
)
from app.telemetry.simulator import (
    SimulatorControlRequest,
    VirtualVesselSimulator,
    VirtualVesselState,
)
from app.decision.contracts import DecisionContext, EngineeringDecisionInputs
from app.services.contracts import OperatorStateResponse
from app.services.operator_service import OperatorService
from app.state.contracts import (
    PersistedVoyageState,
    StateNotFoundError,
    StateUpdateRequest,
)
from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    TelemetryProvenanceType,
    TelemetryQualityState,
)
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.repository import TelemetryAuditRecord, TelemetryAuditRepository
from app.voyage.contracts import (
    Route,
    VesselContext,
    VesselEnergyState,
    VesselPosition,
    VoyageContext,
    VoyageTimeline,
)
from app.voyage.lookahead import (
    RouteWeatherLookAhead,
    RouteWeatherLookAheadRequest,
)
from app.weather.provider import WeatherProvider


router = APIRouter(prefix="/operator", tags=["Operator"])



class OperatorContextRequest(BaseModel):
    """Request payload for state evaluation from an existing DecisionContext."""
    context: DecisionContext = Field(..., description="Complete normalized decision context")
    policy: Optional[AdvisoryPolicy] = Field(default=None, description="Explicit operator advisory policy rules")
    request_id: Optional[str] = Field(default=None, description="Optional correlation ID for logging/auditing")


class OperatorVoyageRequest(BaseModel):
    """Request payload for state evaluation from an existing VoyageContext."""
    voyage_context: VoyageContext = Field(..., description="Vessel, route, and environmental voyage context")
    engineering_inputs: Optional[EngineeringDecisionInputs] = Field(default=None, description="Optional engineering metrics")
    policy: Optional[AdvisoryPolicy] = Field(default=None, description="Explicit operator advisory policy rules")
    request_id: Optional[str] = Field(default=None, description="Optional correlation ID for logging/auditing")


class OperatorTelemetryRequest(BaseModel):
    """Request payload for state evaluation from live or simulated telemetry streams."""
    vessel: VesselContext = Field(..., description="Static vessel particulars")
    route: Route = Field(..., description="Planned voyage route")
    position: VesselPosition = Field(..., description="Instantaneous vessel position and kinematics")
    energy_state: Optional[VesselEnergyState] = Field(default=None, description="Battery, fuel, and solar telemetry")
    timeline: Optional[VoyageTimeline] = Field(default=None, description="Departure and schedule timeline")
    engineering_inputs: Optional[EngineeringDecisionInputs] = Field(default=None, description="Optional engineering metrics")
    policy: Optional[AdvisoryPolicy] = Field(default=None, description="Explicit operator advisory policy rules")
    request_id: Optional[str] = Field(default=None, description="Optional correlation ID for logging/auditing")


# =====================================================================
# EPHEMERAL SITUATIONAL AWARENESS ENDPOINTS (PHASE 10C.9)
# =====================================================================

@router.post(
    "/state",
    response_model=OperatorStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operator state from DecisionContext",
    description="Evaluates advisory rules against a DecisionContext and returns structured operator state.",
)
def get_state(
    request: OperatorContextRequest,
    service: OperatorService = Depends(get_operator_service),
) -> OperatorStateResponse:
    return service.get_operator_state(
        context=request.context,
        policy=request.policy,
        request_id=request.request_id,
    )


@router.post(
    "/state/from-voyage",
    response_model=OperatorStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operator state from VoyageContext",
    description="Wraps VoyageContext into DecisionContext, evaluates advisories, and returns operator state.",
)
def get_state_from_voyage(
    request: OperatorVoyageRequest,
    service: OperatorService = Depends(get_operator_service),
) -> OperatorStateResponse:
    return service.get_operator_state_from_voyage(
        voyage_context=request.voyage_context,
        engineering_inputs=request.engineering_inputs,
        policy=request.policy,
        request_id=request.request_id,
    )


@router.post(
    "/state/from-telemetry",
    response_model=OperatorStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operator state from raw telemetry streams",
    description="Enriches telemetry with weather provider data, runs advisory pipeline, and returns operator state.",
)
def get_state_from_telemetry(
    request: OperatorTelemetryRequest,
    service: OperatorService = Depends(get_operator_service),
    weather_provider: WeatherProvider = Depends(get_weather_provider),
) -> OperatorStateResponse:
    return service.get_operator_state_from_telemetry(
        vessel=request.vessel,
        route=request.route,
        position=request.position,
        weather_provider=weather_provider,
        energy_state=request.energy_state,
        timeline=request.timeline,
        engineering_inputs=request.engineering_inputs,
        policy=request.policy,
        request_id=request.request_id,
    )


# =====================================================================
# PERSISTENT VOYAGE STATE ENDPOINTS (PHASE 10C.10)
# =====================================================================

@router.post(
    "/voyages",
    response_model=PersistedVoyageState,
    status_code=status.HTTP_201_CREATED,
    summary="Create and persist a new voyage state",
    description="Stores a new initial PersistedVoyageState in the persistent repository.",
)
def create_voyage_state(
    state: PersistedVoyageState,
    service: OperatorService = Depends(get_operator_service),
) -> PersistedVoyageState:
    return service.save_voyage_state(state)


@router.get(
    "/voyages",
    response_model=List[PersistedVoyageState],
    status_code=status.HTTP_200_OK,
    summary="List persisted voyage states",
    description="Retrieves a paginated list of all stored voyage states.",
)
def list_voyage_states(
    limit: int = Query(default=100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Number of records to skip"),
    service: OperatorService = Depends(get_operator_service),
) -> List[PersistedVoyageState]:
    return service.list_voyage_states(limit=limit, offset=offset)


@router.get(
    "/voyages/{voyage_id}",
    response_model=PersistedVoyageState,
    status_code=status.HTTP_200_OK,
    summary="Get persisted voyage state by ID",
    description="Retrieves the current state snapshot for a specific voyage_id.",
)
def get_voyage_state(
    voyage_id: str,
    service: OperatorService = Depends(get_operator_service),
) -> PersistedVoyageState:
    return service.get_voyage_state(voyage_id)


@router.put(
    "/voyages/{voyage_id}",
    response_model=PersistedVoyageState,
    status_code=status.HTTP_200_OK,
    summary="Update persisted voyage state",
    description="Applies partial updates to an existing voyage state with optimistic concurrency protection.",
)
def update_voyage_state(
    voyage_id: str,
    update: StateUpdateRequest,
    service: OperatorService = Depends(get_operator_service),
) -> PersistedVoyageState:
    return service.update_voyage_state(voyage_id=voyage_id, update=update)


@router.delete(
    "/voyages/{voyage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete persisted voyage state",
    description="Deletes a voyage state snapshot from the repository.",
)
def delete_voyage_state(
    voyage_id: str,
    service: OperatorService = Depends(get_operator_service),
) -> None:
    deleted = service.delete_voyage_state(voyage_id)
    if not deleted:
        raise StateNotFoundError(voyage_id)


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Operator service health check",
    description="Liveness and readiness check for operator service endpoint.",
)
def operator_health() -> Dict[str, str]:
    return {"status": "healthy", "service": "OperatorService"}


# =====================================================================
# TELEMETRY GATEWAY ENDPOINTS (PHASE 10C.12)
# =====================================================================

@router.post(
    "/telemetry/ingest",
    response_model=CanonicalTelemetryPayload,
    status_code=status.HTTP_200_OK,
    summary="Ingest and normalize raw telemetry stream",
    description="Validates, normalizes, and stores the latest telemetry frame in the read-only gateway buffer.",
)
def ingest_telemetry(
    raw_payload: Dict[str, Any],
    source: str = Query(default="API_INGEST", description="Telemetry source identifier"),
    mode: TelemetryProvenanceType = Query(default=TelemetryProvenanceType.OBSERVED, description="Provenance mode"),
    gateway: TelemetryGateway = Depends(get_telemetry_gateway),
) -> CanonicalTelemetryPayload:
    return gateway.ingest_raw(raw_dict=raw_payload, default_source=source, default_mode=mode)


@router.get(
    "/telemetry/current",
    response_model=CanonicalTelemetryPayload,
    status_code=status.HTTP_200_OK,
    summary="Get current normalized telemetry frame",
    description="Returns the latest buffered telemetry frame with freshly evaluated temporal freshness.",
)
def get_current_telemetry(
    reference_time_utc: Optional[str] = Query(default=None, description="Optional reference ISO 8601 UTC timestamp"),
    gateway: TelemetryGateway = Depends(get_telemetry_gateway),
) -> CanonicalTelemetryPayload:
    return gateway.get_current_frame(reference_time_utc=reference_time_utc)


@router.get(
    "/telemetry/simulated/{scenario_id}",
    response_model=CanonicalTelemetryPayload,
    status_code=status.HTTP_200_OK,
    summary="Load and return a deterministic simulated scenario",
    description="Loads scenario (A, B, C, D, E, F, G, H) into the gateway buffer and returns the canonical frame.",
)
def get_simulated_scenario(
    scenario_id: str,
    gateway: TelemetryGateway = Depends(get_telemetry_gateway),
) -> CanonicalTelemetryPayload:
    from fastapi import HTTPException
    try:
        return gateway.load_scenario(scenario_id=scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))



@router.post(
    "/telemetry/validate",
    response_model=CanonicalTelemetryPayload,
    status_code=status.HTTP_200_OK,
    summary="Validate and normalize raw telemetry without buffering",
    description="Validates a raw telemetry payload and returns the normalized canonical frame without altering gateway state.",
)
def validate_telemetry(
    raw_payload: Dict[str, Any],
    source: str = Query(default="VALIDATOR", description="Telemetry source identifier"),
    mode: TelemetryProvenanceType = Query(default=TelemetryProvenanceType.OBSERVED, description="Provenance mode"),
    gateway: TelemetryGateway = Depends(get_telemetry_gateway),
) -> CanonicalTelemetryPayload:
    return gateway.adapter.normalize(raw_payload=raw_payload, default_source=source, default_mode=mode)


# =====================================================================
# REAL-TIME STREAMING & AUDIT HISTORY ENDPOINTS (PHASE 10C.13)
# =====================================================================

@router.get(
    "/telemetry/stream",
    summary="Subscribe to real-time server-sent events (SSE) telemetry push stream",
    description="Maintains an open SSE connection streaming canonical telemetry updates in real-time.",
)
async def stream_telemetry(
    gateway: TelemetryGateway = Depends(get_telemetry_gateway),
) -> StreamingResponse:
    return StreamingResponse(
        gateway.stream_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/telemetry/history",
    response_model=List[TelemetryAuditRecord],
    status_code=status.HTTP_200_OK,
    summary="Query historical telemetry audit log",
    description="Retrieves a filtered, paginated time-series log of recorded telemetry frames ordered by timestamp DESC.",
)
def get_telemetry_history(
    vessel_id: Optional[str] = Query(default=None, description="Filter by vessel identifier"),
    start_time_utc: Optional[str] = Query(default=None, description="Earliest ISO 8601 UTC timestamp"),
    end_time_utc: Optional[str] = Query(default=None, description="Latest ISO 8601 UTC timestamp"),
    source: Optional[str] = Query(default=None, description="Filter by data source provider"),
    mode: Optional[TelemetryProvenanceType] = Query(default=None, description="Filter by provenance mode"),
    quality: Optional[TelemetryQualityState] = Query(default=None, description="Filter by quality classification"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max audit entries to retrieve"),
    offset: int = Query(default=0, ge=0, description="Number of entries to skip"),
    audit_repo: TelemetryAuditRepository = Depends(get_telemetry_audit_repository),
) -> List[TelemetryAuditRecord]:
    return audit_repo.query(
        vessel_id=vessel_id,
        start_time_utc=start_time_utc,
        end_time_utc=end_time_utc,
        source=source,
        mode=mode,
        quality=quality,
        limit=limit,
        offset=offset,
    )


# =====================================================================
# ROUTE WEATHER LOOK-AHEAD ENDPOINTS (PHASE 10C.13C)
# =====================================================================

@router.post(
    "/weather/lookahead",
    response_model=RouteWeatherLookAhead,
    status_code=status.HTTP_200_OK,
    summary="Compute route weather spacetime look-ahead",
    description="Calculates time-aware weather forecast along route waypoints based on vessel position, kinematics, and forecast models.",
)
def get_route_weather_lookahead_endpoint(
    request: RouteWeatherLookAheadRequest,
    service: OperatorService = Depends(get_operator_service),
    weather_provider: WeatherProvider = Depends(get_weather_provider),
) -> RouteWeatherLookAhead:
    return service.get_route_weather_lookahead(
        position=request.position,
        route=request.route,
        weather_provider=weather_provider,
        vessel_id=request.vessel_id,
        reference_time_utc=request.reference_time_utc,
        policy=request.policy,
        max_lookahead_nm=request.max_lookahead_nm,
        max_lookahead_hours=request.max_lookahead_hours,
    )


# =====================================================================
# NATIVE VIRTUAL VESSEL SIMULATOR ENDPOINTS
# =====================================================================

@router.get(
    "/simulator/state",
    response_model=VirtualVesselState,
    status_code=status.HTTP_200_OK,
    summary="Get current virtual vessel simulator state",
    description="Returns complete canonical state of the native virtual vessel simulator.",
)
def get_simulator_state(
    simulator: VirtualVesselSimulator = Depends(get_virtual_simulator),
) -> VirtualVesselState:
    return simulator.get_state()


@router.post(
    "/simulator/start",
    response_model=VirtualVesselState,
    status_code=status.HTTP_200_OK,
    summary="Start virtual vessel simulation",
    description="Starts continuous real-time execution of the virtual vessel simulator.",
)
def start_simulator(
    simulator: VirtualVesselSimulator = Depends(get_virtual_simulator),
) -> VirtualVesselState:
    return simulator.start()


@router.post(
    "/simulator/pause",
    response_model=VirtualVesselState,
    status_code=status.HTTP_200_OK,
    summary="Pause virtual vessel simulation",
    description="Pauses the virtual vessel simulation advancement.",
)
def pause_simulator(
    simulator: VirtualVesselSimulator = Depends(get_virtual_simulator),
) -> VirtualVesselState:
    return simulator.pause()


@router.post(
    "/simulator/reset",
    response_model=VirtualVesselState,
    status_code=status.HTTP_200_OK,
    summary="Reset virtual vessel simulation",
    description="Resets virtual vessel to initial Escravos departure parameters.",
)
def reset_simulator(
    simulator: VirtualVesselSimulator = Depends(get_virtual_simulator),
) -> VirtualVesselState:
    return simulator.reset()


@router.post(
    "/simulator/control",
    response_model=VirtualVesselState,
    status_code=status.HTTP_200_OK,
    summary="Update virtual vessel driver controls",
    description="Updates driver target speed, throttle, heading, or environmental overrides on the virtual simulator.",
)
def control_simulator(
    controls: SimulatorControlRequest,
    simulator: VirtualVesselSimulator = Depends(get_virtual_simulator),
) -> VirtualVesselState:
    return simulator.set_controls(controls)


@router.post(
    "/simulator/step",
    response_model=VirtualVesselState,
    status_code=status.HTTP_200_OK,
    summary="Execute single simulation step",
    description="Advances the virtual simulator by dt_seconds.",
)
def step_simulator(
    dt_seconds: float = Query(default=1.0, ge=0.01, le=3600.0, description="Step duration in seconds"),
    simulator: VirtualVesselSimulator = Depends(get_virtual_simulator),
) -> VirtualVesselState:
    return simulator.step(dt_seconds=dt_seconds)


@router.post(
    "/simulator/weather/refresh",
    response_model=VirtualVesselState,
    status_code=status.HTTP_200_OK,
    summary="Refresh virtual vessel weather from Open-Meteo",
    description="Forces an immediate update of simulator ocean conditions from live Open-Meteo weather.",
)
def refresh_simulator_weather(
    simulator: VirtualVesselSimulator = Depends(get_virtual_simulator),
) -> VirtualVesselState:
    simulator.fetch_and_update_weather(force=True)
    return simulator.get_state()


