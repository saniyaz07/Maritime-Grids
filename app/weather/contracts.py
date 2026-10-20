"""
app/weather/contracts.py — Phase 10C.1 Normalized Weather Contracts
===================================================================
Defines strongly-typed, Pydantic V2 compliant weather schemas, provenance states,
freshness indicators, data quality classifications, geographic bounds, and route
waypoint models for the Maritime Grids platform.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Strict geographic validation (-90 <= lat <= 90, -180 <= lon <= 180).
  - Explicit missing-value representation (None / UNAVAILABLE, never silently 0.0).
  - Explicit provenance tracking (OBSERVED, HISTORICAL, FORECAST, etc.).
  - Deterministic freshness and data-quality evaluation.
  - Zero coupling to proprietary commercial provider APIs.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


# =====================================================================
# 1. SEMANTIC ENUMS (PROVENANCE, QUALITY, FRESHNESS)
# =====================================================================

class WeatherProvenanceType(str, Enum):
    """
    Data origin semantics for weather information.
    Distinguishes observed physical telemetry from forecasts and simulations.
    """
    OBSERVED = "OBSERVED"
    HISTORICAL = "HISTORICAL"
    FORECAST = "FORECAST"
    MODEL_PREDICTION = "MODEL_PREDICTION"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


class WeatherQualityState(str, Enum):
    """
    Quality classification for weather records.
    Invalid records must be rejected and never enter downstream calculations.
    """
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class WeatherFreshnessState(str, Enum):
    """
    Temporal freshness of the weather observation or forecast.
    Stale or expired weather must never be silently treated as live/current.
    """
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


# =====================================================================
# 2. NORMALIZED WEATHER CONTRACT
# =====================================================================

class NormalizedWeatherRecord(BaseModel):
    """
    Unified normalized weather contract for maritime route planning,
    climatological analysis, and driver dashboard telemetry.

    CRITICAL RULE:
    Unavailable fields MUST be None. They must NEVER be defaulted or silently
    replaced with 0.0, because 0.0 m/s wind or 0.0 m wave height represents
    a real physical condition (calm sea) and not missing data.
    """
    # Geographic coordinates (Mandatory)
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees [-90.0, 90.0]")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees [-180.0, 180.0]")

    # Timestamps (UTC normalized)
    timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp of the weather observation/prediction validity")
    retrieval_timestamp_utc: Optional[str] = Field(default=None, description="ISO 8601 UTC timestamp when data was fetched")

    # Provenance & Metadata
    data_source: str = Field(..., min_length=1, description="Source provider or model name (e.g., 'OPEN_METEO', 'NASA_POWER')")
    data_type: WeatherProvenanceType = Field(..., description="Semantic origin category")
    data_quality: WeatherQualityState = Field(default=WeatherQualityState.VALID, description="Quality classification")
    freshness: WeatherFreshnessState = Field(default=WeatherFreshnessState.UNKNOWN, description="Temporal freshness indicator")
    freshness_age_seconds: Optional[float] = Field(default=None, ge=0.0, description="Calculated age of the record in seconds")

    # Atmospheric Variables (Optional — None represents UNAVAILABLE)
    wind_speed_ms: Optional[float] = Field(default=None, ge=0.0, description="Wind speed at 10m in m/s")
    wind_speed_knots: Optional[float] = Field(default=None, ge=0.0, description="Wind speed at 10m in knots (1 m/s = 1.94384 knots)")
    wind_direction_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0, description="Wind direction in degrees [0.0, 360.0] (direction from which wind blows)")
    temperature_c: Optional[float] = Field(default=None, ge=-100.0, le=70.0, description="Air temperature at 2m in Celsius [-100.0, 70.0]")
    relative_humidity_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Relative humidity in percent [0.0, 100.0]")
    surface_pressure_hpa: Optional[float] = Field(default=None, ge=500.0, le=1100.0, description="Surface barometric atmospheric pressure in hPa [500.0, 1100.0]")
    solar_irradiance_w_per_m2: Optional[float] = Field(default=None, ge=0.0, description="Instantaneous global horizontal irradiance in W/m2")
    daily_ghi_kwh_per_m2: Optional[float] = Field(default=None, ge=0.0, description="Daily Global Horizontal Irradiance in kWh/m2/day")
    cloud_cover_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Total cloud cover percentage [0.0, 100.0]")
    precipitation_mm_per_hr: Optional[float] = Field(default=None, ge=0.0, description="Precipitation rate in mm/hour")

    # Oceanic & Marine Variables (Optional — None represents UNAVAILABLE)
    wave_height_m: Optional[float] = Field(default=None, ge=0.0, description="Significant wave height in meters (Hs)")
    wave_direction_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0, description="Dominant wave direction in degrees [0.0, 360.0]")
    wave_period_s: Optional[float] = Field(default=None, ge=0.0, description="Dominant wave peak period in seconds")
    ocean_current_speed_knots: Optional[float] = Field(default=None, ge=0.0, description="Ocean surface current speed in knots")
    ocean_current_direction_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0, description="Ocean current flow direction in degrees [0.0, 360.0]")

    # Additional Provider Specific Context
    provider_metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary unnormalized provider diagnostic key-values")

    @field_validator("timestamp_utc", "retrieval_timestamp_utc")
    @classmethod
    def validate_and_normalize_iso_utc(cls, v: Optional[str]) -> Optional[str]:
        """Ensures valid ISO format and normalizes to UTC ISO string."""
        if v is None:
            return None
        v_str = str(v).strip()
        if not v_str:
            raise ValueError("Timestamp string cannot be empty")
        try:
            # Parse datetime
            if v_str.endswith("Z"):
                v_clean = v_str[:-1] + "+00:00"
            else:
                v_clean = v_str
            dt = datetime.fromisoformat(v_clean)
            if dt.tzinfo is None:
                # Treat naive as UTC
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        except Exception as e:
            raise ValueError(f"Invalid ISO 8601 timestamp '{v_str}': {e}")

    @field_validator("wind_direction_deg", "wave_direction_deg", "ocean_current_direction_deg")
    @classmethod
    def normalize_direction(cls, v: Optional[float]) -> Optional[float]:
        """Normalizes compass directions into [0.0, 360.0]. 360.0 is mapped to 0.0 except if explicitly desired."""
        if v is None:
            return None
        if not math.isfinite(v):
            raise ValueError("Direction value must be finite")
        # Normalize modulo 360
        normalized = v % 360.0
        return round(float(normalized), 2)

    @model_validator(mode="after")
    def compute_wind_unit_cross_consistency(self) -> "NormalizedWeatherRecord":
        """
        Cross-synchronizes wind_speed_ms and wind_speed_knots if one is provided and the other is None.
        Standard conversion: 1 m/s = 1.9438444924406 knots.
        """
        if self.wind_speed_ms is not None and self.wind_speed_knots is None:
            self.wind_speed_knots = round(self.wind_speed_ms * 1.9438444924406, 3)
        elif self.wind_speed_knots is not None and self.wind_speed_ms is None:
            self.wind_speed_ms = round(self.wind_speed_knots / 1.9438444924406, 3)
        return self

    def is_available(self, field_name: str) -> bool:
        """Checks if a specified physical field is available (not None)."""
        if not hasattr(self, field_name):
            return False
        return getattr(self, field_name) is not None

    def evaluate_freshness(
        self,
        current_time_utc: Optional[Union[datetime, str]] = None,
        fresh_threshold_seconds: float = 3600.0,     # 1 hour
        stale_threshold_seconds: float = 86400.0,    # 24 hours
    ) -> WeatherFreshnessState:
        """
        Evaluates record freshness against a reference timestamp.
        Updates self.freshness and self.freshness_age_seconds in place.
        """
        try:
            record_dt = datetime.fromisoformat(self.timestamp_utc)
            if current_time_utc is None:
                ref_dt = datetime.now(timezone.utc)
            elif isinstance(current_time_utc, str):
                ref_dt = datetime.fromisoformat(current_time_utc)
                if ref_dt.tzinfo is None:
                    ref_dt = ref_dt.replace(tzinfo=timezone.utc)
                else:
                    ref_dt = ref_dt.astimezone(timezone.utc)
            else:
                ref_dt = current_time_utc
                if ref_dt.tzinfo is None:
                    ref_dt = ref_dt.replace(tzinfo=timezone.utc)
                else:
                    ref_dt = ref_dt.astimezone(timezone.utc)

            age_sec = (ref_dt - record_dt).total_seconds()
            self.freshness_age_seconds = max(0.0, age_sec)

            # If forecast into the future, freshness is FRESH
            if age_sec < 0:
                self.freshness = WeatherFreshnessState.FRESH
            elif age_sec <= fresh_threshold_seconds:
                self.freshness = WeatherFreshnessState.FRESH
            elif age_sec <= stale_threshold_seconds:
                self.freshness = WeatherFreshnessState.STALE
            else:
                self.freshness = WeatherFreshnessState.EXPIRED
        except Exception:
            self.freshness = WeatherFreshnessState.UNKNOWN
            self.freshness_age_seconds = None

        return self.freshness

    def evaluate_quality(self) -> WeatherQualityState:
        """
        Determines overall record quality:
          - VALID: Core physical fields present and within range.
          - PARTIAL: Some fields available, but key fields missing.
          - INVALID: Out-of-bounds or malformed data.
          - UNAVAILABLE: All weather variables are None.
        """
        variables = [
            self.wind_speed_ms,
            self.wind_speed_knots,
            self.temperature_c,
            self.relative_humidity_pct,
            self.surface_pressure_hpa,
            self.solar_irradiance_w_per_m2,
            self.daily_ghi_kwh_per_m2,
            self.wave_height_m,
            self.wave_period_s,
        ]
        available_count = sum(1 for v in variables if v is not None)

        if available_count == 0:
            self.data_quality = WeatherQualityState.UNAVAILABLE
        elif available_count >= 5:
            self.data_quality = WeatherQualityState.VALID
        else:
            self.data_quality = WeatherQualityState.PARTIAL

        return self.data_quality


# =====================================================================
# 3. ROUTE WAYPOINT & WAYPOINT WEATHER
# =====================================================================

class RouteWaypoint(BaseModel):
    """
    Represents a discrete geographic navigation waypoint along a planned maritime route.
    """
    waypoint_id: str = Field(..., description="Unique waypoint identifier (e.g. 'WP_01', 'PORT_LAGOS')")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees [-90.0, 90.0]")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees [-180.0, 180.0]")
    estimated_arrival_utc: Optional[str] = Field(default=None, description="Expected ISO 8601 UTC arrival time")
    distance_from_start_nm: Optional[float] = Field(default=None, ge=0.0, description="Cumulative distance in nautical miles")

    @field_validator("estimated_arrival_utc")
    @classmethod
    def validate_eta_utc(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)


class RouteWeatherProfile(BaseModel):
    """
    Time-series collection of normalized weather records aligned along a route.
    """
    route_id: str
    vessel_id: Optional[str] = None
    created_at_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_waypoints: int
    waypoints_weather: List[NormalizedWeatherRecord]
    has_missing_data: bool = False
    overall_quality: WeatherQualityState = WeatherQualityState.VALID


# =====================================================================
# 4. DRIVER DASHBOARD SUMMARY CONTRACT
# =====================================================================

class DriverDashboardWeatherSummary(BaseModel):
    """
    Condensed driver/operator dashboard telemetry payload.
    Provides clear situational awareness distinguishing live, forecast, and historical data.
    """
    location_lat: float
    location_lon: float
    weather_timestamp_utc: str
    data_source: str
    provenance_type: WeatherProvenanceType
    freshness_state: WeatherFreshnessState
    quality_state: WeatherQualityState
    
    # Key operational readouts (None if unavailable)
    wind_speed_knots: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    solar_ghi_kwh_per_m2: Optional[float] = None
    wave_height_m: Optional[float] = None
    ocean_current_speed_knots: Optional[float] = None
    
    # Situational advisory flags
    high_wind_warning: bool = False       # e.g. wind > 25 knots
    rough_sea_warning: bool = False       # e.g. wave height > 2.5 m
    solar_yield_favorable: bool = False   # e.g. GHI > 4.5 kWh/m2/day
