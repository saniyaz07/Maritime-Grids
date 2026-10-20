"""
app/services/operator_service.py — Phase 10C.8 / 10C.10 Operator & Bridge Service
================================================================================
Provides application-level service entry points for operator situational awareness,
dashboard telemetry aggregation, route progression, truthful data availability,
deterministic advisory summarization, and persistent voyage state management.

Key Invariants:
  - Read-only situational awareness & decision support.
  - Zero autonomous vessel control, throttle actuation, steering, or engine control.
  - Strict preservation of data availability (unmeasured fields remain None, never 0.0).
  - Strict preservation of weather provenance (OBSERVED, HISTORICAL, FORECAST, etc.).
  - human_review_required = True enforced on all generated advisories.
  - Persistent voyage state delegation through abstract StateRepository.
"""

from datetime import datetime, timezone, timedelta
import math
from typing import Any, Dict, List, Optional

from app.advisory.contracts import (
    Advisory,
    AdvisoryCategory,
    AdvisoryPolicy,
    AdvisorySeverity,
    AdvisoryStatus,
)
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
    EngineeringDecisionInputs,
)
from app.pipeline.advisory_pipeline import AdvisoryPipeline
from app.services.contracts import (
    FieldAvailabilityClassification,
    OperatorAdvisorySummary,
    OperatorEnergyState,
    OperatorRegulatoryState,
    OperatorStateMetadata,
    OperatorStateResponse,
    OperatorVesselState,
    OperatorWeatherState,
    RouteProgressInfo,
)
from app.state.contracts import (
    PersistedVoyageState,
    StateNotFoundError,
    StateUpdateRequest,
)
from app.state.repository import StateRepository
from app.state.memory_repository import InMemoryStateRepository
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
from app.weather.provider import WeatherProvider


class OperatorService:
    """
    Application-facing service for bridge operators and driver situational awareness.
    Synthesizes DecisionContext and AdvisoryPipeline evaluations into OperatorStateResponse,
    and provides persistent voyage lifecycle storage through StateRepository.
    """

    def __init__(
        self,
        pipeline: Optional[AdvisoryPipeline] = None,
        repository: Optional[StateRepository] = None,
    ) -> None:
        """
        Initialize the OperatorService.

        Args:
            pipeline: Optional AdvisoryPipeline instance (instantiated by default).
            repository: Optional StateRepository instance (defaults to InMemoryStateRepository).
        """
        self.pipeline = pipeline or AdvisoryPipeline()
        self.repository = repository or InMemoryStateRepository()

    def get_operator_state(
        self,
        context: DecisionContext,
        policy: Optional[AdvisoryPolicy] = None,
        request_id: Optional[str] = None,
    ) -> OperatorStateResponse:
        """
        Synthesizes an OperatorStateResponse from a given DecisionContext.
        Evaluates active deterministic advisories via AdvisoryPipeline.

        Args:
            context: Complete normalized DecisionContext.
            policy: Optional explicit operational threshold policy.
            request_id: Optional correlation/request identifier.

        Returns:
            Structured OperatorStateResponse.
        """
        if not isinstance(context, DecisionContext):
            raise TypeError(f"Expected DecisionContext, got {type(context)}")

        req_id = request_id or f"OP_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        exec_ts = datetime.now(timezone.utc).isoformat()

        # 1. Run advisory pipeline
        pipeline_result = self.pipeline.run(context=context, policy=policy)

        voyage = context.voyage_context
        vessel = voyage.vessel
        route = voyage.route
        pos = voyage.current_position
        wx_ctx = voyage.weather_context or VoyageWeatherContext()
        curr_wx = wx_ctx.current_weather
        energy = voyage.energy_state or VesselEnergyState()
        eng = context.engineering_inputs

        # 2. Derive route progress and ETA
        route_progress = self._compute_route_progress(route=route, position=pos) if route and pos else None

        # 3. Assemble Metadata
        metadata = OperatorStateMetadata(
            request_id=req_id,
            generated_at_utc=exec_ts,
            readiness_state=context.readiness,
            readiness_reasons=context.readiness_reasons,
        )

        # 4. Assemble Vessel State
        vessel_state = OperatorVesselState(
            vessel_id=vessel.vessel_id,
            ship_type=vessel.ship_type,
            engine_power_kw=vessel.engine_power_kw,
            design_speed_knots=vessel.design_speed_knots,
            max_speed_knots=vessel.max_speed_knots,
            displacement_tonnes=vessel.displacement_tonnes,
            propulsion_type=vessel.propulsion_type,
            current_position=pos or VesselPosition(latitude=0.0, longitude=0.0, timestamp_utc=exec_ts),
            route=route or Route(route_id="UNKNOWN", origin_port="UNKNOWN", destination_port="UNKNOWN", waypoints=[RouteWaypoint(waypoint_id="WP1", latitude=0.0, longitude=0.0), RouteWaypoint(waypoint_id="WP2", latitude=0.0, longitude=0.0)]),
            route_progress=route_progress,
        )

        # 5. Assemble Weather State
        weather_state = OperatorWeatherState(
            current=curr_wx,
            route_profile=wx_ctx.route_weather,
            provenance=curr_wx.data_type if curr_wx else None,
            quality=curr_wx.data_quality if curr_wx else wx_ctx.weather_quality,
            freshness=curr_wx.freshness if curr_wx else wx_ctx.weather_freshness,
            freshness_age_seconds=int(curr_wx.freshness_age_seconds) if (curr_wx and curr_wx.freshness_age_seconds is not None) else None,
        )

        # 6. Assemble Energy State (Truthful None preservation)
        energy_state = OperatorEnergyState(
            battery_soc_pct=energy.battery_soc_pct,
            battery_soh_pct=energy.battery_soh_pct,
            battery_energy_available_kwh=energy.battery_energy_available_kwh,
            fuel_remaining_liters=energy.fuel_remaining_liters,
            fuel_consumption_rate_lph=energy.fuel_consumption_rate_lph,
            solar_power_kw=energy.solar_power_kw,
            solar_energy_today_kwh=energy.solar_energy_today_kwh,
        )

        # 7. Assemble Regulatory State
        attained_cii = eng.cii_attained_rating if eng else None
        compliance_state = None
        if attained_cii:
            rating_upper = attained_cii.strip().upper()
            compliance_state = "COMPLIANT" if rating_upper in ("A", "B", "C") else "NON_COMPLIANT"

        regulatory_state = OperatorRegulatoryState(
            attained_cii_rating=attained_cii,
            co2_emissions_kg=eng.co2_emissions_kg if eng else None,
            compliance_state=compliance_state,
        )

        # 8. Assemble Advisory Summary
        advisory_summary = OperatorAdvisorySummary(
            total_count=pipeline_result.total_advisories,
            critical_count=pipeline_result.critical_count,
            warning_count=pipeline_result.warning_count,
            notice_count=pipeline_result.notice_count,
            info_count=pipeline_result.info_count,
            items=pipeline_result.advisories,
        )

        return OperatorStateResponse(
            metadata=metadata,
            vessel=vessel_state,
            weather=weather_state,
            energy=energy_state,
            regulatory=regulatory_state,
            advisories=advisory_summary,
        )

    def get_operator_state_from_voyage(
        self,
        voyage_context: VoyageContext,
        engineering_inputs: Optional[EngineeringDecisionInputs] = None,
        policy: Optional[AdvisoryPolicy] = None,
        request_id: Optional[str] = None,
    ) -> OperatorStateResponse:
        """
        Constructs a DecisionContext from a VoyageContext and executes operator state retrieval.
        """
        if not isinstance(voyage_context, VoyageContext):
            raise TypeError(f"Expected VoyageContext, got {type(voyage_context)}")

        req_id = request_id or f"OP_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        dc = DecisionContext(
            decision_context_id=f"DC_{req_id}",
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            voyage_context=voyage_context,
            engineering_inputs=engineering_inputs,
        )
        return self.get_operator_state(context=dc, policy=policy, request_id=req_id)

    def get_operator_state_from_telemetry(
        self,
        vessel: VesselContext,
        route: Route,
        position: VesselPosition,
        weather_provider: WeatherProvider,
        energy_state: Optional[VesselEnergyState] = None,
        timeline: Optional[VoyageTimeline] = None,
        engineering_inputs: Optional[EngineeringDecisionInputs] = None,
        policy: Optional[AdvisoryPolicy] = None,
        request_id: Optional[str] = None,
    ) -> OperatorStateResponse:
        """
        Enriches telemetry through the weather provider, constructs a VoyageContext,
        and returns the full OperatorStateResponse.
        """
        req_id = request_id or f"OP_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        pipe_result = self.pipeline.run_from_telemetry(
            vessel=vessel,
            route=route,
            position=position,
            weather_provider=weather_provider,
            energy_state=energy_state,
            timeline=timeline,
            engineering_inputs=engineering_inputs,
            policy=policy,
            pipeline_id=req_id,
        )
        return self.get_operator_state(
            context=pipe_result.decision_context,
            policy=policy,
            request_id=req_id,
        )

    def get_route_weather_lookahead(
        self,
        position: VesselPosition,
        route: Route,
        weather_provider: WeatherProvider,
        vessel_id: Optional[str] = None,
        reference_time_utc: Optional[str] = None,
        policy: Optional[AdvisoryPolicy] = None,
        max_lookahead_nm: Optional[float] = None,
        max_lookahead_hours: Optional[float] = None,
    ) -> Any:
        """
        Computes spacetime weather forecast look-ahead across planned route waypoints.
        """
        from app.voyage.lookahead import compute_route_weather_lookahead
        return compute_route_weather_lookahead(
            position=position,
            route=route,
            weather_provider=weather_provider,
            vessel_id=vessel_id,
            reference_time_utc=reference_time_utc,
            policy=policy,
            max_lookahead_nm=max_lookahead_nm,
            max_lookahead_hours=max_lookahead_hours,
        )

    # =================================================================
    # PERSISTENCE METHODS (PHASE 10C.10)
    # =================================================================

    def save_voyage_state(self, state: PersistedVoyageState) -> PersistedVoyageState:
        """Saves a new PersistedVoyageState record via the repository."""
        if not isinstance(state, PersistedVoyageState):
            raise TypeError(f"Expected PersistedVoyageState, got {type(state)}")
        return self.repository.save(state)

    def get_voyage_state(self, voyage_id: str) -> PersistedVoyageState:
        """Retrieves a PersistedVoyageState or raises StateNotFoundError."""
        return self.repository.get_or_raise(voyage_id)

    def list_voyage_states(self, limit: int = 100, offset: int = 0) -> List[PersistedVoyageState]:
        """Lists persisted voyage states with pagination."""
        return self.repository.list_all(limit=limit, offset=offset)

    def update_voyage_state(self, voyage_id: str, update: StateUpdateRequest) -> PersistedVoyageState:
        """Updates a persisted voyage state with optimistic concurrency support."""
        if not isinstance(update, StateUpdateRequest):
            raise TypeError(f"Expected StateUpdateRequest, got {type(update)}")
        return self.repository.update(voyage_id=voyage_id, update=update)

    def delete_voyage_state(self, voyage_id: str) -> bool:
        """Deletes a persisted voyage state by voyage_id."""
        return self.repository.delete(voyage_id)

    def persist_operator_state(
        self,
        voyage_id: str,
        response: OperatorStateResponse,
        route_id: Optional[str] = None,
        status: VoyageStatus = VoyageStatus.ACTIVE,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PersistedVoyageState:
        """
        Creates and stores a PersistedVoyageState snapshot from an OperatorStateResponse.
        """
        state = PersistedVoyageState.from_operator_state(
            response=response,
            voyage_id=voyage_id,
            route_id=route_id,
            status=status,
            metadata=metadata,
        )
        return self.save_voyage_state(state)

    @staticmethod
    def _compute_route_progress(
        route: Route,
        position: VesselPosition,
    ) -> RouteProgressInfo:
        """
        Derives application-level route progress percentage and linear ETA estimate.
        Guards strictly against division-by-zero on zero/missing SOG.
        """
        total_dist = route.total_distance_nm or 0.0
        if total_dist <= 0.0:
            return RouteProgressInfo(
                route_id=route.route_id,
                total_distance_nm=total_dist,
                distance_traveled_nm=0.0,
                distance_remaining_nm=0.0,
                route_progress_pct=100.0,
                eta_utc=None,
            )

        # Estimate remaining distance to final destination waypoint
        dest_wp = route.waypoints[-1] if route.waypoints else None
        if dest_wp is not None:
            d_lat = math.radians(dest_wp.latitude - position.latitude)
            d_lon = math.radians(dest_wp.longitude - position.longitude)
            lat1 = math.radians(position.latitude)
            lat2 = math.radians(dest_wp.latitude)

            a = math.sin(d_lat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2.0) ** 2
            c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
            r_earth_nm = 3440.065
            remaining_nm = round(r_earth_nm * c, 2)
            remaining_nm = min(remaining_nm, total_dist)
            traveled_nm = round(max(0.0, total_dist - remaining_nm), 2)
            progress_pct = round(min(100.0, max(0.0, (traveled_nm / total_dist) * 100.0)), 1)
        else:
            remaining_nm = None
            traveled_nm = None
            progress_pct = None

        # Compute linear ETA if SOG is positive and valid
        eta_utc: Optional[str] = None
        sog = position.speed_over_ground_knots
        if sog is not None and sog > 0.1 and remaining_nm is not None:
            eta_hours = remaining_nm / sog
            try:
                base_dt = datetime.fromisoformat(position.timestamp_utc)
                if base_dt.tzinfo is None:
                    base_dt = base_dt.replace(tzinfo=timezone.utc)
                eta_dt = base_dt + timedelta(hours=eta_hours)
                eta_utc = eta_dt.isoformat()
            except Exception:
                eta_utc = None

        return RouteProgressInfo(
            route_id=route.route_id,
            total_distance_nm=total_dist,
            distance_traveled_nm=traveled_nm,
            distance_remaining_nm=remaining_nm,
            route_progress_pct=progress_pct,
            eta_utc=eta_utc,
        )
