"""
app/voyage/lookahead.py — Phase 10C.13C Real-World Weather + Route Spacetime Look-Ahead
======================================================================================
Combines virtual vessel telemetry (lat, lon, SOG, COG), route waypoints, speed,
and reference time with real/mock weather providers to produce a time-aware,
spacetime weather look-ahead along the planned voyage route.

Key Invariants:
  - 100% Pydantic V2 compliant contracts.
  - Strict preservation of missing values (None is preserved, never faked as 0.0).
  - Explicit timing status: "ESTIMATED", "STATIONARY", "SPEED_UNAVAILABLE".
  - Strictly guards against zero/negative/missing SOG: No division by zero, no fabricated speeds.
  - Geodesic distance calculation along waypoint chain (Haversine formula, R = 3440.065 NM).
  - Explicit weather provenance tagging (FORECAST for future point queries).
  - Purely advisory: 0 actuator paths, 0 vessel control commands.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.provider import WeatherProvider
from app.voyage.contracts import Route, VesselPosition
from app.advisory.contracts import AdvisoryPolicy


# =====================================================================
# 1. ENUMS & DATA CONTRACTS
# =====================================================================

class LookAheadTimingStatus(str, Enum):
    """Timing estimation status for spacetime look-ahead."""
    ESTIMATED = "ESTIMATED"
    STATIONARY = "STATIONARY"
    SPEED_UNAVAILABLE = "SPEED_UNAVAILABLE"


class LookAheadWaypointWeather(BaseModel):
    """
    Spacetime weather observation/forecast at a specific route waypoint.
    """
    waypoint_id: str = Field(..., description="Waypoint identifier")
    name: Optional[str] = Field(default=None, description="Optional human-readable waypoint name")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude [-90.0, 90.0]")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude [-180.0, 180.0]")
    distance_from_vessel_nm: float = Field(..., ge=0.0, description="Cumulative distance from vessel along route (NM)")
    estimated_arrival_utc: Optional[str] = Field(default=None, description="ISO 8601 UTC estimated arrival time (None if stationary/speed unavailable)")
    hours_ahead: Optional[float] = Field(default=None, ge=0.0, description="Elapsed hours from reference time to waypoint arrival")
    timing_status: LookAheadTimingStatus = Field(default=LookAheadTimingStatus.ESTIMATED, description="ETA derivation status")
    weather: Optional[NormalizedWeatherRecord] = Field(default=None, description="Point-in-time forecast/observed weather at waypoint")
    
    # Operational alerts for this waypoint
    high_wind_warning: bool = Field(default=False, description="True if forecasted wind exceeds threshold")
    rough_sea_warning: bool = Field(default=False, description="True if forecasted wave height exceeds threshold")

    @field_validator("estimated_arrival_utc")
    @classmethod
    def validate_eta_timestamp(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)


class RouteWeatherLookAheadSummary(BaseModel):
    """
    Aggregated summary and operational highlights across the look-ahead horizon.
    """
    total_lookahead_distance_nm: float = Field(..., ge=0.0, description="Total distance covered by look-ahead profile (NM)")
    total_lookahead_hours: Optional[float] = Field(default=None, ge=0.0, description="Total duration covered by look-ahead profile (hours)")
    max_wind_knots: Optional[float] = Field(default=None, ge=0.0, description="Maximum forecasted wind speed along look-ahead (knots)")
    max_wave_height_m: Optional[float] = Field(default=None, ge=0.0, description="Maximum forecasted significant wave height (meters)")
    has_adverse_conditions: bool = Field(default=False, description="True if any waypoint has high wind or rough seas")
    adverse_condition_reasons: List[str] = Field(default_factory=list, description="Descriptive reasons for adverse condition flags")


class RouteWeatherLookAhead(BaseModel):
    """
    Time-aware route weather look-ahead aggregate.
    """
    vessel_id: Optional[str] = Field(default=None, description="Optional vessel identifier")
    route_id: str = Field(..., description="Route identifier")
    generated_at_utc: str = Field(..., description="ISO 8601 UTC timestamp of look-ahead generation")
    reference_time_utc: str = Field(..., description="ISO 8601 UTC reference starting time")
    reference_position: VesselPosition = Field(..., description="Current vessel position fix used for calculation")
    speed_over_ground_knots: Optional[float] = Field(default=None, ge=0.0, description="SOG used for spacetime progression")
    timing_status: LookAheadTimingStatus = Field(default=LookAheadTimingStatus.ESTIMATED, description="Overall timing status")
    waypoints: List[LookAheadWaypointWeather] = Field(default_factory=list, description="Sequenced waypoint look-ahead entries")
    summary: RouteWeatherLookAheadSummary = Field(..., description="Aggregated look-ahead summary")
    provenance: WeatherProvenanceType = Field(default=WeatherProvenanceType.FORECAST, description="Semantic data provenance")
    overall_quality: WeatherQualityState = Field(default=WeatherQualityState.VALID, description="Overall data quality")


class RouteWeatherLookAheadRequest(BaseModel):
    """Request payload for route weather look-ahead query."""
    position: VesselPosition = Field(..., description="Current vessel position and kinematics")
    route: Route = Field(..., description="Planned voyage route and waypoints")
    vessel_id: Optional[str] = Field(default=None, description="Optional vessel identifier")
    reference_time_utc: Optional[str] = Field(default=None, description="Optional reference starting time")
    policy: Optional[AdvisoryPolicy] = Field(default=None, description="Optional operational policy thresholds")
    max_lookahead_nm: Optional[float] = Field(default=None, ge=0.0, description="Optional maximum distance look-ahead window (NM)")
    max_lookahead_hours: Optional[float] = Field(default=None, ge=0.0, description="Optional maximum duration look-ahead window (hours)")


# =====================================================================
# 2. GEOMETRIC & TIME-AWARE ENGINE
# =====================================================================

def haversine_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes the great-circle distance between two points in Nautical Miles.
    Uses Earth radius R = 3440.065 NM.
    """
    r_earth_nm = 3440.065
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    l1 = math.radians(lat1)
    l2 = math.radians(lat2)
    a = math.sin(d_lat / 2.0) ** 2 + math.cos(l1) * math.cos(l2) * math.sin(d_lon / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return round(r_earth_nm * c, 2)


class RouteWeatherLookAheadEngine:
    """
    Deterministic engine that computes time-aware weather forecast look-ahead
    along a vessel route based on kinematics and point forecast models.
    """

    def __init__(
        self,
        default_high_wind_threshold_knots: float = 25.0,
        default_rough_sea_threshold_m: float = 2.5,
    ) -> None:
        self.default_high_wind_threshold_knots = default_high_wind_threshold_knots
        self.default_rough_sea_threshold_m = default_rough_sea_threshold_m

    def _get_point_weather(
        self,
        provider: WeatherProvider,
        latitude: float,
        longitude: float,
        target_dt: Optional[datetime],
        reference_dt: datetime,
    ) -> NormalizedWeatherRecord:
        """
        Retrieves weather for a specific point in spacetime.
        """
        if target_dt is None or abs((target_dt - reference_dt).total_seconds()) < 1800:
            # Stationary, current waypoint, or arrival at/near reference time: fetch current observation
            return provider.get_current_weather(latitude=latitude, longitude=longitude)

        # Historical point in time (substantially before reference datetime)
        if target_dt < reference_dt:
            return provider.get_historical_weather(
                latitude=latitude,
                longitude=longitude,
                timestamp=target_dt.isoformat(),
            )
        else:
            # Future point in time: query forecast time-series and select corresponding forecast record
            hours_ahead = (target_dt - reference_dt).total_seconds() / 3600.0
            horizon = max(1, math.ceil(hours_ahead) + 1)
            try:
                forecasts = provider.get_forecast_weather(
                    latitude=latitude,
                    longitude=longitude,
                    horizon_hours=horizon,
                    step_hours=1,
                )
                if forecasts:
                    first_dt = datetime.fromisoformat(forecasts[0].timestamp_utc)
                    if first_dt.tzinfo is None:
                        first_dt = first_dt.replace(tzinfo=timezone.utc)
                    else:
                        first_dt = first_dt.astimezone(timezone.utc)

                    # Check if forecast series epoch aligns with reference_dt (within 7 days)
                    if abs((first_dt - reference_dt).total_seconds()) < 7 * 86400:
                        # Aligned epoch (real-world / synchronous mode): pick closest by timestamp
                        def _time_diff(rec: NormalizedWeatherRecord) -> float:
                            rec_dt = datetime.fromisoformat(rec.timestamp_utc)
                            if rec_dt.tzinfo is None:
                                rec_dt = rec_dt.replace(tzinfo=timezone.utc)
                            else:
                                rec_dt = rec_dt.astimezone(timezone.utc)
                            return abs((rec_dt - target_dt).total_seconds())

                        return min(forecasts, key=_time_diff)
                    else:
                        # Cross-epoch / simulated voyage time vs real-world forecast:
                        # Select forecast record by relative horizon offset from the start of forecast series
                        step_idx = min(max(0, int(round(hours_ahead))), len(forecasts) - 1)
                        return forecasts[step_idx]
            except Exception:
                pass

            # Fallback to historical/point query if forecast series unavailable
            return provider.get_historical_weather(
                latitude=latitude,
                longitude=longitude,
                timestamp=target_dt.isoformat(),
            )

    def compute_lookahead(
        self,
        position: VesselPosition,
        route: Route,
        weather_provider: WeatherProvider,
        vessel_id: Optional[str] = None,
        reference_time_utc: Optional[str] = None,
        policy: Optional[AdvisoryPolicy] = None,
        max_lookahead_nm: Optional[float] = None,
        max_lookahead_hours: Optional[float] = None,
    ) -> RouteWeatherLookAhead:
        """
        Computes the complete spacetime route weather look-ahead profile.
        """
        if not route.waypoints or len(route.waypoints) == 0:
            raise ValueError("Route must contain at least one waypoint for look-ahead calculation.")

        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Parse reference starting datetime
        ref_time_str = reference_time_utc or position.timestamp_utc or now_iso
        try:
            ref_dt = datetime.fromisoformat(ref_time_str)
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=timezone.utc)
            else:
                ref_dt = ref_dt.astimezone(timezone.utc)
        except Exception:
            ref_dt = datetime.now(timezone.utc)
        ref_iso = ref_dt.isoformat()

        # Evaluate SOG and timing status (Strict guards against 0/None)
        sog = position.speed_over_ground_knots
        if sog is None:
            timing_status = LookAheadTimingStatus.SPEED_UNAVAILABLE
        elif sog <= 0.1:
            timing_status = LookAheadTimingStatus.STATIONARY
        else:
            timing_status = LookAheadTimingStatus.ESTIMATED

        # Thresholds from explicit policy or defaults
        wind_thresh = self.default_high_wind_threshold_knots
        sea_thresh = self.default_rough_sea_threshold_m
        if policy and policy.weather_policy:
            if policy.weather_policy.high_wind_threshold_knots is not None:
                wind_thresh = policy.weather_policy.high_wind_threshold_knots
            if policy.weather_policy.rough_sea_threshold_m is not None:
                sea_thresh = policy.weather_policy.rough_sea_threshold_m

        waypoint_entries: List[LookAheadWaypointWeather] = []
        cumulative_dist = 0.0
        prev_lat, prev_lon = position.latitude, position.longitude

        has_partial = False
        adverse_reasons: List[str] = []

        for idx, wp in enumerate(route.waypoints):
            # Calculate distance segment
            seg_dist = haversine_distance_nm(prev_lat, prev_lon, wp.latitude, wp.longitude)
            cumulative_dist += seg_dist
            prev_lat, prev_lon = wp.latitude, wp.longitude

            # Check distance window cap
            if max_lookahead_nm is not None and cumulative_dist > max_lookahead_nm and idx > 0:
                break

            # Calculate ETA & duration ahead
            eta_utc: Optional[str] = None
            hours_ahead: Optional[float] = None
            target_dt: Optional[datetime] = None

            if timing_status == LookAheadTimingStatus.ESTIMATED and sog is not None and sog > 0.1:
                hours = cumulative_dist / sog
                if max_lookahead_hours is not None and hours > max_lookahead_hours and idx > 0:
                    break
                hours_ahead = round(hours, 2)
                target_dt = ref_dt + timedelta(hours=hours)
                eta_utc = target_dt.isoformat()

            # Query weather at spacetime point
            wp_weather = self._get_point_weather(
                provider=weather_provider,
                latitude=wp.latitude,
                longitude=wp.longitude,
                target_dt=target_dt,
                reference_dt=ref_dt,
            )

            if wp_weather.data_quality != WeatherQualityState.VALID:
                has_partial = True

            # Evaluate adverse conditions
            high_wind = False
            rough_sea = False

            if wp_weather.wind_speed_knots is not None and wp_weather.wind_speed_knots > wind_thresh:
                high_wind = True
                eta_label = f"+{hours_ahead:.1f}h" if hours_ahead is not None else "stationary"
                adverse_reasons.append(
                    f"High wind ahead ({wp_weather.wind_speed_knots:.1f} kn > {wind_thresh:.1f} kn) at {wp.waypoint_id} ({eta_label})"
                )

            if wp_weather.wave_height_m is not None and wp_weather.wave_height_m > sea_thresh:
                rough_sea = True
                eta_label = f"+{hours_ahead:.1f}h" if hours_ahead is not None else "stationary"
                adverse_reasons.append(
                    f"Rough seas ahead ({wp_weather.wave_height_m:.2f} m > {sea_thresh:.1f} m) at {wp.waypoint_id} ({eta_label})"
                )

            entry = LookAheadWaypointWeather(
                waypoint_id=wp.waypoint_id,
                name=getattr(wp, "waypoint_id", None),
                latitude=wp.latitude,
                longitude=wp.longitude,
                distance_from_vessel_nm=round(cumulative_dist, 2),
                estimated_arrival_utc=eta_utc,
                hours_ahead=hours_ahead,
                timing_status=timing_status,
                weather=wp_weather,
                high_wind_warning=high_wind,
                rough_sea_warning=rough_sea,
            )
            waypoint_entries.append(entry)

        # Assemble summary
        total_dist = waypoint_entries[-1].distance_from_vessel_nm if waypoint_entries else 0.0
        total_hours = waypoint_entries[-1].hours_ahead if (waypoint_entries and timing_status == LookAheadTimingStatus.ESTIMATED) else None

        wind_vals = [w.weather.wind_speed_knots for w in waypoint_entries if w.weather and w.weather.wind_speed_knots is not None]
        max_wind = max(wind_vals) if wind_vals else None

        wave_vals = [w.weather.wave_height_m for w in waypoint_entries if w.weather and w.weather.wave_height_m is not None]
        max_wave = max(wave_vals) if wave_vals else None

        has_adverse = any(w.high_wind_warning or w.rough_sea_warning for w in waypoint_entries)

        summary = RouteWeatherLookAheadSummary(
            total_lookahead_distance_nm=round(total_dist, 2),
            total_lookahead_hours=total_hours,
            max_wind_knots=max_wind,
            max_wave_height_m=max_wave,
            has_adverse_conditions=has_adverse,
            adverse_condition_reasons=adverse_reasons,
        )

        overall_quality = WeatherQualityState.PARTIAL if has_partial else WeatherQualityState.VALID

        return RouteWeatherLookAhead(
            vessel_id=vessel_id,
            route_id=route.route_id,
            generated_at_utc=now_iso,
            reference_time_utc=ref_iso,
            reference_position=position,
            speed_over_ground_knots=sog,
            timing_status=timing_status,
            waypoints=waypoint_entries,
            summary=summary,
            provenance=WeatherProvenanceType.FORECAST,
            overall_quality=overall_quality,
        )


def compute_route_weather_lookahead(
    position: VesselPosition,
    route: Route,
    weather_provider: WeatherProvider,
    vessel_id: Optional[str] = None,
    reference_time_utc: Optional[str] = None,
    policy: Optional[AdvisoryPolicy] = None,
    max_lookahead_nm: Optional[float] = None,
    max_lookahead_hours: Optional[float] = None,
) -> RouteWeatherLookAhead:
    """
    Convenience functional interface to compute route weather look-ahead.
    """
    engine = RouteWeatherLookAheadEngine()
    return engine.compute_lookahead(
        position=position,
        route=route,
        weather_provider=weather_provider,
        vessel_id=vessel_id,
        reference_time_utc=reference_time_utc,
        policy=policy,
        max_lookahead_nm=max_lookahead_nm,
        max_lookahead_hours=max_lookahead_hours,
    )
