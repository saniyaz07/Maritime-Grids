"""
app/voyage/context_builder.py — Phase 10C.3 Voyage Context Builder
==================================================================
Fluent builder utility to assemble, validate, and enrich VoyageContext
aggregates using application parameters and pluggable weather providers.

Key Invariants:
  - Validates all components before final object instantiation.
  - Interacts with WeatherProvider strictly via abstract interface.
  - Preserves data provenance and explicit missing values.
  - Zero physics recalculation.
"""

from datetime import datetime, timezone
from typing import List, Optional, Union

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherProvenanceType,
)
from app.weather.provider import WeatherProvider
from app.voyage.contracts import (
    Route,
    VesselContext,
    VesselEnergyState,
    VesselPosition,
    VoyageContext,
    VoyageStatus,
    VoyageTimeline,
    VoyageWeatherContext,
)


class VoyageContextBuilder:
    """
    Builder pattern implementation for constructing complete, valid VoyageContext instances.
    """

    def __init__(self, voyage_id: str) -> None:
        self.voyage_id = voyage_id
        self.status = VoyageStatus.PLANNED
        self._vessel: Optional[VesselContext] = None
        self._route: Optional[Route] = None
        self._position: Optional[VesselPosition] = None
        self._timeline: Optional[VoyageTimeline] = None
        self._weather_context: Optional[VoyageWeatherContext] = None
        self._energy_state: Optional[VesselEnergyState] = None

    def set_status(self, status: VoyageStatus) -> "VoyageContextBuilder":
        self.status = status
        return self

    def set_vessel(self, vessel: VesselContext) -> "VoyageContextBuilder":
        self._vessel = vessel
        return self

    def set_route(self, route: Route) -> "VoyageContextBuilder":
        self._route = route
        return self

    def set_position(self, position: VesselPosition) -> "VoyageContextBuilder":
        self._position = position
        return self

    def set_timeline(self, timeline: VoyageTimeline) -> "VoyageContextBuilder":
        self._timeline = timeline
        return self

    def set_energy_state(self, energy_state: VesselEnergyState) -> "VoyageContextBuilder":
        self._energy_state = energy_state
        return self

    def set_weather_context(self, weather_context: VoyageWeatherContext) -> "VoyageContextBuilder":
        self._weather_context = weather_context
        return self

    def enrich_weather_from_provider(
        self,
        provider: WeatherProvider,
    ) -> "VoyageContextBuilder":
        """
        Enriches the voyage context by querying the provided WeatherProvider
        for current weather at the vessel's position and route weather profile.
        """
        if self._position is None:
            raise ValueError("Cannot query weather without a configured vessel position.")
        if self._route is None:
            raise ValueError("Cannot query route weather without a configured route.")

        # 1. Fetch current weather at vessel position
        current_wx = provider.get_current_weather(
            latitude=self._position.latitude,
            longitude=self._position.longitude,
        )

        # 2. Fetch route weather profile across waypoints
        route_wx_profile = provider.get_route_weather(
            waypoints=self._route.waypoints,
            route_id=self._route.route_id,
            vessel_id=self._vessel.vessel_id if self._vessel else None,
        )

        # 3. Assemble weather context
        self._weather_context = VoyageWeatherContext(
            current_weather=current_wx,
            route_weather=route_wx_profile,
            weather_timestamp_utc=current_wx.timestamp_utc,
            weather_source=provider.provider_name,
            weather_quality=current_wx.data_quality,
            weather_freshness=current_wx.freshness,
        )
        return self

    def build(self) -> VoyageContext:
        """
        Validates all required fields and constructs the VoyageContext instance.
        """
        if self._vessel is None:
            raise ValueError("VesselContext must be configured to build VoyageContext.")
        if self._route is None:
            raise ValueError("Route must be configured to build VoyageContext.")
        if self._position is None:
            raise ValueError("VesselPosition must be configured to build VoyageContext.")

        if self._timeline is None:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._timeline = VoyageTimeline(current_time_utc=now_iso)

        if self._weather_context is None:
            self._weather_context = VoyageWeatherContext()

        if self._energy_state is None:
            self._energy_state = VesselEnergyState()

        return VoyageContext(
            voyage_id=self.voyage_id,
            status=self.status,
            vessel=self._vessel,
            route=self._route,
            current_position=self._position,
            timeline=self._timeline,
            weather_context=self._weather_context,
            energy_state=self._energy_state,
        )
