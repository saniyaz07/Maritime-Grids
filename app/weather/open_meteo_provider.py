"""
app/weather/open_meteo_provider.py — Phase 10C.2 Open-Meteo Weather Provider
============================================================================
Connects the platform to the Open-Meteo open-access APIs for live, historical,
and forecast meteorological and marine data. Normalizes all responses to the
Phase 10C.1 NormalizedWeatherRecord contract.

Key Invariants:
  - 100% implements the WeatherProvider abstract base class.
  - Zero proprietary API key dependencies.
  - Robust error classification: Timeout, Rate-Limit (429), Network, Malformed.
  - Bounded retries with backoff (no infinite loops).
  - Integrated with Phase 10C.1 InMemoryWeatherCache.
  - Strict data isolation: missing values remain None (never silently 0.0).
  - Explicit provenance tagging: OBSERVED/CURRENT vs HISTORICAL vs FORECAST.
"""

from datetime import datetime, date, timezone
import json
import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.parse
import urllib.request
import urllib.error

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.provider import WeatherProvider
from app.weather.cache import InMemoryWeatherCache


# =====================================================================
# 1. TYPED EXCEPTION HIERARCHY
# =====================================================================

class WeatherProviderError(Exception):
    """Base exception for external weather provider operations."""
    pass


class WeatherProviderUnavailableError(WeatherProviderError):
    """Raised when external provider service is unreachable or returns 5xx."""
    pass


class WeatherProviderTimeoutError(WeatherProviderError):
    """Raised when request to provider times out."""
    pass


class WeatherProviderRateLimitError(WeatherProviderError):
    """Raised when provider returns HTTP 429 Too Many Requests."""
    pass


class WeatherProviderInvalidResponseError(WeatherProviderError):
    """Raised when provider payload is malformed or unparseable JSON."""
    pass


class WeatherProviderInvalidRequestError(WeatherProviderError):
    """Raised when client parameters are out-of-bounds or invalid for the provider (HTTP 400)."""
    pass


# =====================================================================
# 2. OPEN-METEO PROVIDER IMPLEMENTATION
# =====================================================================

class OpenMeteoWeatherProvider(WeatherProvider):
    """
    Open-Meteo API connector for weather, historical archive, and marine datasets.
    """

    FORECAST_API_URL = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
    MARINE_API_URL = "https://marine-api.open-meteo.com/v1/marine"

    def __init__(
        self,
        provider_name: str = "OPEN_METEO",
        cache: Optional[InMemoryWeatherCache] = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        enable_marine_enrichment: bool = True,
    ) -> None:
        """
        Initialize the Open-Meteo weather provider.

        Args:
            provider_name: Name identifier.
            cache: Optional weather cache instance.
            timeout_seconds: HTTP socket timeout in seconds.
            max_retries: Maximum retry attempts for transient failures.
            backoff_factor: Exponential backoff delay multiplier.
            enable_marine_enrichment: Whether to query marine API for waves/currents.
        """
        self._provider_name = provider_name
        self.cache = cache if cache is not None else InMemoryWeatherCache()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)
        self.backoff_factor = max(0.0, backoff_factor)
        self.enable_marine_enrichment = enable_marine_enrichment

    @property
    def provider_name(self) -> str:
        return self._provider_name

    # -----------------------------------------------------------------
    # Safe HTTP Client with Bounded Retries & Error Classification
    # -----------------------------------------------------------------
    def _execute_http_get(self, base_url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes an HTTP GET request with bounded retries and typed error handling.
        """
        query_string = urllib.parse.urlencode(params)
        full_url = f"{base_url}?{query_string}"
        headers = {"User-Agent": "MaritimeGrids/10.0 (DecarbonizationResearch)"}
        req = urllib.request.Request(full_url, headers=headers)

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                    status_code = response.getcode()
                    if status_code != 200:
                        raise WeatherProviderUnavailableError(f"Open-Meteo returned non-200 status code: {status_code}")
                    raw_data = response.read().decode("utf-8")
                    try:
                        return json.loads(raw_data)
                    except json.JSONDecodeError as json_err:
                        raise WeatherProviderInvalidResponseError(f"Malformed JSON from Open-Meteo: {json_err}")

            except WeatherProviderError:
                raise

            except urllib.error.HTTPError as http_err:
                last_error = http_err
                if http_err.code == 429:
                    raise WeatherProviderRateLimitError(f"Open-Meteo rate limit exceeded (HTTP 429): {http_err.reason}")
                elif 400 <= http_err.code < 500:
                    raise WeatherProviderInvalidRequestError(f"Invalid request to Open-Meteo (HTTP {http_err.code}): {http_err.reason}")
                # 5xx errors can be retried
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
                    continue

            except urllib.error.URLError as url_err:
                last_error = url_err
                if isinstance(url_err.reason, TimeoutError) or "timed out" in str(url_err.reason).lower():
                    if attempt < self.max_retries:
                        time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
                        continue
                    raise WeatherProviderTimeoutError(f"Open-Meteo connection timed out after {self.max_retries} attempts: {url_err}")
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
                    continue

            except TimeoutError as timeout_err:
                last_error = timeout_err
                if attempt < self.max_retries:
                    time.sleep(self.backoff_factor * (2 ** (attempt - 1)))
                    continue
                raise WeatherProviderTimeoutError(f"Open-Meteo connection timed out after {self.max_retries} attempts: {timeout_err}")

            except Exception as generic_err:
                last_error = generic_err
                raise WeatherProviderError(f"Unexpected error communicating with Open-Meteo: {generic_err}")

        raise WeatherProviderUnavailableError(f"Open-Meteo unavailable after {self.max_retries} attempts: {last_error}")

    # -----------------------------------------------------------------
    # Field Parsing & Normalization Helpers
    # -----------------------------------------------------------------
    def _parse_normalized_record(
        self,
        latitude: float,
        longitude: float,
        timestamp_utc: str,
        data_type: WeatherProvenanceType,
        atm_data: Dict[str, Any],
        marine_data: Optional[Dict[str, Any]] = None,
    ) -> NormalizedWeatherRecord:
        """
        Translates raw Open-Meteo atmospheric and marine dictionaries into NormalizedWeatherRecord.
        Guarantees missing fields remain None and are never silently 0.0.
        """
        # 1. Atmospheric mappings
        wind_speed_ms = atm_data.get("wind_speed_10m")
        wind_direction_deg = atm_data.get("wind_direction_10m")
        temperature_c = atm_data.get("temperature_2m")
        relative_humidity_pct = atm_data.get("relative_humidity_2m")
        surface_pressure_hpa = atm_data.get("surface_pressure")
        cloud_cover_pct = atm_data.get("cloud_cover")
        precipitation_mm_per_hr = atm_data.get("precipitation")
        solar_irradiance_w_per_m2 = atm_data.get("shortwave_radiation_instant") or atm_data.get("direct_normal_irradiance")

        # Estimate daily GHI if hourly shortwave is available
        daily_ghi = round(solar_irradiance_w_per_m2 * 24.0 / 1000.0, 2) if solar_irradiance_w_per_m2 is not None else None

        # 2. Oceanic mappings
        wave_height_m = None
        wave_direction_deg = None
        wave_period_s = None
        ocean_current_speed_knots = None
        ocean_current_direction_deg = None

        if marine_data:
            wave_height_m = marine_data.get("wave_height")
            wave_direction_deg = marine_data.get("wave_direction")
            wave_period_s = marine_data.get("wave_period")
            curr_vel_ms = marine_data.get("ocean_current_velocity")
            if curr_vel_ms is not None:
                ocean_current_speed_knots = round(float(curr_vel_ms) * 1.94384, 2)
            ocean_current_direction_deg = marine_data.get("ocean_current_direction")

        # Wind speed knots derived if ms is present
        wind_speed_knots = round(float(wind_speed_ms) * 1.94384, 2) if wind_speed_ms is not None else None

        record = NormalizedWeatherRecord(
            latitude=latitude,
            longitude=longitude,
            timestamp_utc=timestamp_utc,
            retrieval_timestamp_utc=datetime.now(timezone.utc).isoformat(),
            data_source=self.provider_name,
            data_type=data_type,
            wind_speed_ms=float(wind_speed_ms) if wind_speed_ms is not None else None,
            wind_speed_knots=wind_speed_knots,
            wind_direction_deg=float(wind_direction_deg) if wind_direction_deg is not None else None,
            temperature_c=float(temperature_c) if temperature_c is not None else None,
            relative_humidity_pct=float(relative_humidity_pct) if relative_humidity_pct is not None else None,
            surface_pressure_hpa=float(surface_pressure_hpa) if surface_pressure_hpa is not None else None,
            solar_irradiance_w_per_m2=float(solar_irradiance_w_per_m2) if solar_irradiance_w_per_m2 is not None else None,
            daily_ghi_kwh_per_m2=daily_ghi,
            cloud_cover_pct=float(cloud_cover_pct) if cloud_cover_pct is not None else None,
            precipitation_mm_per_hr=float(precipitation_mm_per_hr) if precipitation_mm_per_hr is not None else None,
            wave_height_m=float(wave_height_m) if wave_height_m is not None else None,
            wave_direction_deg=float(wave_direction_deg) if wave_direction_deg is not None else None,
            wave_period_s=float(wave_period_s) if wave_period_s is not None else None,
            ocean_current_speed_knots=ocean_current_speed_knots,
            ocean_current_direction_deg=float(ocean_current_direction_deg) if ocean_current_direction_deg is not None else None,
        )

        record.evaluate_freshness()
        record.evaluate_quality()
        return record

    # -----------------------------------------------------------------
    # WeatherProvider Interface Methods
    # -----------------------------------------------------------------
    def get_current_weather(
        self,
        latitude: float,
        longitude: float,
    ) -> NormalizedWeatherRecord:
        """
        Retrieves current weather observation from Open-Meteo.
        """
        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            raise WeatherProviderInvalidRequestError(f"Coordinates out of bounds: lat={latitude}, lon={longitude}")

        cache_key = InMemoryWeatherCache.generate_cache_key(
            provider_name=self.provider_name,
            latitude=latitude,
            longitude=longitude,
            timestamp_utc="CURRENT",
            data_type=WeatherProvenanceType.OBSERVED,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        atm_params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation,shortwave_radiation_instant",
            "wind_speed_unit": "ms",
            "timeformat": "iso8601",
            "timezone": "UTC",
        }

        atm_resp = self._execute_http_get(self.FORECAST_API_URL, atm_params)
        current_atm = atm_resp.get("current", {})
        time_iso = current_atm.get("time", datetime.now(timezone.utc).isoformat())

        marine_data: Optional[Dict[str, Any]] = None
        if self.enable_marine_enrichment:
            try:
                marine_params = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": "wave_height,wave_direction,wave_period,ocean_current_velocity,ocean_current_direction",
                    "wind_speed_unit": "ms",
                    "timezone": "UTC",
                }
                marine_resp = self._execute_http_get(self.MARINE_API_URL, marine_params)
                marine_data = marine_resp.get("current", {})
            except Exception:
                # Non-fatal: inland or unsupported marine coordinates
                marine_data = None

        record = self._parse_normalized_record(
            latitude=latitude,
            longitude=longitude,
            timestamp_utc=time_iso,
            data_type=WeatherProvenanceType.OBSERVED,
            atm_data=current_atm,
            marine_data=marine_data,
        )

        self.cache.set(record, ttl_seconds=1800.0, custom_key=cache_key)  # 30 min cache for live
        return record

    def get_historical_weather(
        self,
        latitude: float,
        longitude: float,
        timestamp: Union[datetime, str],
    ) -> NormalizedWeatherRecord:
        """
        Retrieves historical weather observation for a specific point in time.
        """
        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            raise WeatherProviderInvalidRequestError(f"Coordinates out of bounds: lat={latitude}, lon={longitude}")

        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        else:
            dt = timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)

        target_date_str = dt.strftime("%Y-%m-%d")
        target_iso = dt.isoformat()

        cache_key = InMemoryWeatherCache.generate_cache_key(
            provider_name=self.provider_name,
            latitude=latitude,
            longitude=longitude,
            timestamp_utc=target_iso,
            data_type=WeatherProvenanceType.HISTORICAL,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": target_date_str,
            "end_date": target_date_str,
            "hourly": "temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation,shortwave_radiation_instant",
            "wind_speed_unit": "ms",
            "timeformat": "iso8601",
            "timezone": "UTC",
        }

        resp = self._execute_http_get(self.ARCHIVE_API_URL, params)
        hourly = resp.get("hourly", {})
        times = hourly.get("time", [])

        if not times:
            raise WeatherProviderInvalidResponseError(f"No historical hourly time series returned for date {target_date_str}")

        # Find closest hour index
        target_hour = dt.hour
        best_idx = min(range(len(times)), key=lambda i: abs(i - target_hour))

        atm_point = {
            "wind_speed_10m": hourly.get("wind_speed_10m", [None])[best_idx] if hourly.get("wind_speed_10m") else None,
            "wind_direction_10m": hourly.get("wind_direction_10m", [None])[best_idx] if hourly.get("wind_direction_10m") else None,
            "temperature_2m": hourly.get("temperature_2m", [None])[best_idx] if hourly.get("temperature_2m") else None,
            "relative_humidity_2m": hourly.get("relative_humidity_2m", [None])[best_idx] if hourly.get("relative_humidity_2m") else None,
            "surface_pressure": hourly.get("surface_pressure", [None])[best_idx] if hourly.get("surface_pressure") else None,
            "cloud_cover": hourly.get("cloud_cover", [None])[best_idx] if hourly.get("cloud_cover") else None,
            "precipitation": hourly.get("precipitation", [None])[best_idx] if hourly.get("precipitation") else None,
            "shortwave_radiation_instant": hourly.get("shortwave_radiation_instant", [None])[best_idx] if hourly.get("shortwave_radiation_instant") else None,
        }

        record = self._parse_normalized_record(
            latitude=latitude,
            longitude=longitude,
            timestamp_utc=times[best_idx],
            data_type=WeatherProvenanceType.HISTORICAL,
            atm_data=atm_point,
            marine_data=None,
        )

        self.cache.set(record, ttl_seconds=86400.0 * 7)  # 7-day cache for immutable historical
        return record

    def get_forecast_weather(
        self,
        latitude: float,
        longitude: float,
        horizon_hours: int = 24,
        step_hours: int = 1,
    ) -> List[NormalizedWeatherRecord]:
        """
        Retrieves weather forecast time series from Open-Meteo.
        """
        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            raise WeatherProviderInvalidRequestError(f"Coordinates out of bounds: lat={latitude}, lon={longitude}")
        if horizon_hours < 1:
            raise WeatherProviderInvalidRequestError(f"horizon_hours must be >= 1, got {horizon_hours}")
        if step_hours < 1:
            raise WeatherProviderInvalidRequestError(f"step_hours must be >= 1, got {step_hours}")

        forecast_days = math.ceil(horizon_hours / 24.0) + 1
        forecast_days = min(16, max(1, forecast_days))

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m,cloud_cover,precipitation,shortwave_radiation_instant",
            "forecast_days": forecast_days,
            "wind_speed_unit": "ms",
            "timeformat": "iso8601",
            "timezone": "UTC",
        }

        resp = self._execute_http_get(self.FORECAST_API_URL, params)
        hourly = resp.get("hourly", {})
        times = hourly.get("time", [])

        if not times:
            raise WeatherProviderInvalidResponseError("Empty forecast hourly array received from Open-Meteo")

        # Query marine forecast time series if enrichment is enabled
        marine_by_time: Dict[str, Dict[str, Any]] = {}
        if self.enable_marine_enrichment:
            try:
                marine_params = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "hourly": "wave_height,wave_direction,wave_period,ocean_current_velocity,ocean_current_direction",
                    "forecast_days": forecast_days,
                    "wind_speed_unit": "ms",
                    "timeformat": "iso8601",
                    "timezone": "UTC",
                }
                marine_resp = self._execute_http_get(self.MARINE_API_URL, marine_params)
                m_hourly = marine_resp.get("hourly", {})
                m_times = m_hourly.get("time", [])
                m_wh = m_hourly.get("wave_height", [])
                m_wd = m_hourly.get("wave_direction", [])
                m_wp = m_hourly.get("wave_period", [])
                m_cv = m_hourly.get("ocean_current_velocity", [])
                m_cd = m_hourly.get("ocean_current_direction", [])

                for i, m_t in enumerate(m_times):
                    # Normalize time key to 16 chars (YYYY-MM-DDTHH:MM)
                    norm_k = str(m_t)[:16]
                    marine_by_time[norm_k] = {
                        "wave_height": m_wh[i] if i < len(m_wh) else None,
                        "wave_direction": m_wd[i] if i < len(m_wd) else None,
                        "wave_period": m_wp[i] if i < len(m_wp) else None,
                        "ocean_current_velocity": m_cv[i] if i < len(m_cv) else None,
                        "ocean_current_direction": m_cd[i] if i < len(m_cd) else None,
                    }
            except Exception:
                # Non-fatal: inland, marine unavailable, or timeout
                marine_by_time = {}

        records: List[NormalizedWeatherRecord] = []
        max_points = min(len(times), horizon_hours + 1)

        for idx in range(0, max_points, step_hours):
            t_str = times[idx]
            atm_point = {
                "wind_speed_10m": hourly.get("wind_speed_10m", [None])[idx] if hourly.get("wind_speed_10m") else None,
                "wind_direction_10m": hourly.get("wind_direction_10m", [None])[idx] if hourly.get("wind_direction_10m") else None,
                "temperature_2m": hourly.get("temperature_2m", [None])[idx] if hourly.get("temperature_2m") else None,
                "relative_humidity_2m": hourly.get("relative_humidity_2m", [None])[idx] if hourly.get("relative_humidity_2m") else None,
                "surface_pressure": hourly.get("surface_pressure", [None])[idx] if hourly.get("surface_pressure") else None,
                "cloud_cover": hourly.get("cloud_cover", [None])[idx] if hourly.get("cloud_cover") else None,
                "precipitation": hourly.get("precipitation", [None])[idx] if hourly.get("precipitation") else None,
                "shortwave_radiation_instant": hourly.get("shortwave_radiation_instant", [None])[idx] if hourly.get("shortwave_radiation_instant") else None,
            }

            norm_t = str(t_str)[:16]
            marine_point = marine_by_time.get(norm_t)

            rec = self._parse_normalized_record(
                latitude=latitude,
                longitude=longitude,
                timestamp_utc=t_str,
                data_type=WeatherProvenanceType.FORECAST,
                atm_data=atm_point,
                marine_data=marine_point,
            )
            records.append(rec)

        return records

    def get_route_weather(
        self,
        waypoints: List[RouteWaypoint],
        route_id: str = "ROUTE_001",
        vessel_id: Optional[str] = None,
    ) -> RouteWeatherProfile:
        """
        Sequences weather records across route waypoints chronologically.
        """
        if not waypoints:
            raise WeatherProviderInvalidRequestError("Waypoints list cannot be empty for route weather profiling.")

        records: List[NormalizedWeatherRecord] = []
        has_missing = False

        for wp in waypoints:
            if wp.estimated_arrival_utc:
                # Point-in-time lookup
                rec = self.get_historical_weather(
                    latitude=wp.latitude,
                    longitude=wp.longitude,
                    timestamp=wp.estimated_arrival_utc,
                )
            else:
                # Default current weather at waypoint
                rec = self.get_current_weather(
                    latitude=wp.latitude,
                    longitude=wp.longitude,
                )

            records.append(rec)
            if rec.data_quality != WeatherQualityState.VALID:
                has_missing = True

        overall_quality = WeatherQualityState.PARTIAL if has_missing else WeatherQualityState.VALID

        return RouteWeatherProfile(
            route_id=route_id,
            vessel_id=vessel_id,
            total_waypoints=len(waypoints),
            waypoints_weather=records,
            has_missing_data=has_missing,
            overall_quality=overall_quality,
        )
