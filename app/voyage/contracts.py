"""
app/voyage/contracts.py — Phase 10C.3 Voyage State & Context Contracts
======================================================================
Defines strongly-typed, Pydantic V2 compliant contracts for vessels, routes,
voyages, navigation telemetry, timelines, energy states, and aggregated
weather-aware voyage contexts.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Strict geographic validation (-90 <= lat <= 90, -180 <= lon <= 180).
  - Explicit missing-value representation (None / UNAVAILABLE, never fake defaults).
  - Explicit provenance tracking (OBSERVED, HISTORICAL, FORECAST, SIMULATED, etc.).
  - Zero physics recomputation: pure data/state representation.
  - Waypoint ordering preserved chronologically and sequentially.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)


# =====================================================================
# 1. ENUMS (VOYAGE STATUS)
# =====================================================================

class VoyageStatus(str, Enum):
    """Lifecycle operational state of a maritime voyage."""
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# =====================================================================
# 2. VESSEL CONTEXT CONTRACT
# =====================================================================

class VesselContext(BaseModel):
    """
    Application-level vessel profile and equipment configuration.
    References ship profile attributes without mutating frozen data.
    """
    vessel_id: str = Field(..., min_length=1, description="Unique vessel registration/ID (e.g. 'VESSEL_OSV_01')")
    ship_type: str = Field(..., min_length=1, description="Ship classification type (e.g. 'Oil Service Boat')")
    design_speed_knots: Optional[float] = Field(default=None, ge=1.0, le=50.0, description="Design operational speed in knots")
    max_speed_knots: Optional[float] = Field(default=None, ge=1.0, le=50.0, description="Maximum vessel speed in knots")
    displacement_tonnes: Optional[float] = Field(default=None, ge=1.0, description="Vessel displacement in metric tonnes")
    engine_power_kw: Optional[float] = Field(default=None, ge=1.0, description="Installed main engine rated power in kW")
    propulsion_type: Optional[str] = Field(default=None, description="Propulsion train architecture description")
    battery_pack_capacity_kwh: Optional[float] = Field(default=None, ge=0.0, description="Installed clean battery capacity in kWh")
    solar_panel_size_m2: Optional[float] = Field(default=None, ge=0.0, description="Installed solar PV array surface area in m2")
    fuel_price_usd_per_liter: Optional[float] = Field(default=None, ge=0.0, description="Unit fuel price in USD/L")
    provenance: WeatherProvenanceType = Field(default=WeatherProvenanceType.OBSERVED, description="Data origin of vessel specs")

    @field_validator("vessel_id", "ship_type")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Vessel identifiers and ship types cannot be empty or whitespace only.")
        return s


# =====================================================================
# 3. ROUTE CONTRACT
# =====================================================================

class Route(BaseModel):
    """
    Validated maritime route representation comprising origin, destination,
    and a sequenced chain of geographic waypoints.
    """
    route_id: str = Field(..., min_length=1, description="Unique route identifier (e.g. 'ESCRAVOS_LAGOS')")
    origin_port: str = Field(..., min_length=1, description="Origin port or terminal name")
    destination_port: str = Field(..., min_length=1, description="Destination port or terminal name")
    waypoints: List[RouteWaypoint] = Field(..., min_length=2, description="Ordered sequence of geographic navigation waypoints (min 2)")
    total_distance_nm: Optional[float] = Field(default=None, ge=0.0, description="Total planned route distance in nautical miles")

    @field_validator("route_id", "origin_port", "destination_port")
    @classmethod
    def validate_route_strings(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Route identifiers and port names cannot be empty.")
        return s

    @model_validator(mode="after")
    def validate_waypoint_ordering(self) -> "Route":
        """Ensures waypoint list contains unique valid IDs and coordinates."""
        if not self.waypoints or len(self.waypoints) < 2:
            raise ValueError("A route must contain at least 2 waypoints (origin and destination).")
        return self


# =====================================================================
# 4. CURRENT POSITION TELEMETRY CONTRACT
# =====================================================================

class VesselPosition(BaseModel):
    """
    Current instantaneous geographic navigation fix of the vessel.
    """
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees [-90.0, 90.0]")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees [-180.0, 180.0]")
    timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp of the position fix")
    speed_over_ground_knots: Optional[float] = Field(default=None, ge=0.0, description="Instantaneous SOG in knots")
    course_over_ground_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0, description="Instantaneous COG in degrees")
    data_type: WeatherProvenanceType = Field(default=WeatherProvenanceType.OBSERVED, description="Provenance of position fix")

    @field_validator("timestamp_utc")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v) or v


# =====================================================================
# 5. VOYAGE TIMELINE CONTRACT
# =====================================================================

class VoyageTimeline(BaseModel):
    """
    Temporal timeline of the voyage. If ETA is unavailable, it remains None.
    """
    departure_time_utc: Optional[str] = Field(default=None, description="Actual or planned ISO 8601 UTC departure time")
    current_time_utc: str = Field(..., description="Current ISO 8601 UTC reference time")
    planned_arrival_time_utc: Optional[str] = Field(default=None, description="Planned ISO 8601 UTC arrival time")
    estimated_arrival_time_utc: Optional[str] = Field(default=None, description="Dynamic estimated arrival time (None if UNAVAILABLE)")

    @field_validator("departure_time_utc", "current_time_utc", "planned_arrival_time_utc", "estimated_arrival_time_utc")
    @classmethod
    def validate_timeline_timestamps(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)


# =====================================================================
# 6. VESSEL ENERGY STATE CONTRACT
# =====================================================================

class VesselEnergyState(BaseModel):
    """
    Application-level snapshot of vessel clean energy storage, generation,
    and fuel telemetry. All fields optional if unavailable from ship sensors.
    """
    battery_soc_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Battery State of Charge (%)")
    battery_soh_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Battery State of Health (%)")
    battery_energy_available_kwh: Optional[float] = Field(default=None, ge=0.0, description="Usable battery energy remaining (kWh)")
    solar_power_kw: Optional[float] = Field(default=None, ge=0.0, description="Instantaneous solar PV power output (kW)")
    solar_energy_today_kwh: Optional[float] = Field(default=None, ge=0.0, description="Cumulative solar energy harvested today (kWh)")
    fuel_remaining_liters: Optional[float] = Field(default=None, ge=0.0, description="Fuel volume remaining in bunker tanks (L)")
    fuel_consumption_rate_lph: Optional[float] = Field(default=None, ge=0.0, description="Instantaneous fuel consumption rate (L/hour)")
    provenance: WeatherProvenanceType = Field(default=WeatherProvenanceType.SIMULATED, description="Provenance of energy telemetry")


# =====================================================================
# 7. VOYAGE WEATHER CONTEXT CONTRACT
# =====================================================================

class VoyageWeatherContext(BaseModel):
    """
    Weather context associated with a voyage, encapsulating current environmental
    conditions at the vessel position and forecast profiles across the route.
    """
    current_weather: Optional[NormalizedWeatherRecord] = Field(default=None, description="Current weather at vessel position")
    route_weather: Optional[RouteWeatherProfile] = Field(default=None, description="Weather profile along route waypoints")
    weather_timestamp_utc: Optional[str] = Field(default=None, description="Timestamp of weather observation")
    weather_source: Optional[str] = Field(default=None, description="Provider/Source name of weather data")
    weather_quality: WeatherQualityState = Field(default=WeatherQualityState.UNAVAILABLE, description="Quality classification")
    weather_freshness: WeatherFreshnessState = Field(default=WeatherFreshnessState.UNKNOWN, description="Freshness classification")

    @model_validator(mode="after")
    def sync_weather_metadata(self) -> "VoyageWeatherContext":
        """Synchronizes top-level weather metadata from current_weather if present."""
        if self.current_weather is not None:
            if self.weather_timestamp_utc is None:
                self.weather_timestamp_utc = self.current_weather.timestamp_utc
            if self.weather_source is None:
                self.weather_source = self.current_weather.data_source
            self.weather_quality = self.current_weather.data_quality
            self.weather_freshness = self.current_weather.freshness
        return self


# =====================================================================
# 8. VOYAGE CONTEXT AGGREGATE CONTRACT
# =====================================================================

class VoyageContext(BaseModel):
    """
    Unified application-level state aggregate representing a vessel, route,
    telemetry position, timeline, energy state, and weather context.
    """
    voyage_id: str = Field(..., min_length=1, description="Unique voyage identifier (e.g. 'VOY_2026_001')")
    status: VoyageStatus = Field(default=VoyageStatus.PLANNED, description="Operational voyage lifecycle status")
    vessel: VesselContext = Field(..., description="Vessel profile and equipment context")
    route: Route = Field(..., description="Planned route and waypoint chain")
    current_position: VesselPosition = Field(..., description="Instantaneous vessel position fix")
    timeline: VoyageTimeline = Field(..., description="Voyage departure, reference, and arrival timeline")
    weather_context: VoyageWeatherContext = Field(default_factory=VoyageWeatherContext, description="Weather context")
    energy_state: VesselEnergyState = Field(default_factory=VesselEnergyState, description="Vessel energy and fuel state")

    @field_validator("voyage_id")
    @classmethod
    def validate_voyage_id(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Voyage identifier cannot be empty.")
        return s
