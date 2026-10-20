"""
app/weather/mock_provider.py — Phase 10C.1 Deterministic Mock Weather Provider
==============================================================================
Provides a completely deterministic, offline mock weather provider for testing,
simulation fixtures, and CI/CD pipelines without external API keys or network calls.

Key Invariants:
  - 100% deterministic mathematical generation (sin/cos on lat/lon/doy).
  - No use of random numbers (zero flaky tests).
  - Configurable fault modes: normal, missing_fields, stale, invalid, custom overrides.
  - Full adherence to WeatherProvider interface.
"""

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Union

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.provider import WeatherProvider


class MockWeatherProvider(WeatherProvider):
    """
    Deterministic mock weather provider for testing and offline scenarios.
    Generates realistic, physically bounded maritime environmental variables.
    """

    def __init__(
        self,
        provider_name: str = "MOCK_DETERMINISTIC",
        mode: str = "normal",
        field_overrides: Optional[Dict[str, Any]] = None,
        fixed_reference_time: Optional[datetime] = None,
    ) -> None:
        """
        Initialize the deterministic mock provider.

        Args:
            provider_name: Name label for this provider.
            mode: Operating mode ('normal', 'missing_fields', 'stale', 'invalid').
            field_overrides: Dict of explicit field values to override generated output.
            fixed_reference_time: Optional fixed UTC datetime for time-freezing in tests.
        """
        self._provider_name = provider_name
        self.mode = mode
        self.field_overrides = field_overrides or {}
        self.fixed_reference_time = fixed_reference_time or datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def _generate_synthetic_record(
        self,
        latitude: float,
        longitude: float,
        validity_dt: datetime,
        provenance: WeatherProvenanceType,
    ) -> NormalizedWeatherRecord:
        """
        Generates deterministic physical weather fields from coordinates and timestamp.
        Uses smooth harmonic trigonometric equations to simulate realistic geography & diurnal variation.
        """
        # Coordinate sanity check
        if not (-90.0 <= latitude <= 90.0) or not (-180.0 <= longitude <= 180.0):
            raise ValueError(f"Invalid coordinates: lat={latitude}, lon={longitude}")

        # Deterministic base harmonics
        doy = validity_dt.timetuple().tm_yday
        hour = validity_dt.hour + validity_dt.minute / 60.0
        lat_rad = math.radians(latitude)
        lon_rad = math.radians(longitude)
        day_angle = 2.0 * math.pi * (doy / 365.25)
        hour_angle = 2.0 * math.pi * (hour / 24.0)

        # 1. Wind Speed (typical 5 to 25 knots)
        base_wind_ms = 4.0 + 3.0 * math.sin(lat_rad * 3.0 + day_angle) + 1.5 * math.cos(lon_rad + hour_angle)
        wind_speed_ms = round(max(0.5, abs(base_wind_ms)), 2)
        wind_speed_knots = round(wind_speed_ms * 1.94384, 2)

        # 2. Wind Direction (0 to 360)
        wind_dir = (180.0 + 120.0 * math.sin(lat_rad * 2.0) + 60.0 * math.cos(day_angle)) % 360.0
        wind_direction_deg = round(wind_dir, 1)

        # 3. Air Temperature (15C to 35C)
        t_base = 28.0 - 0.2 * abs(latitude) + 4.0 * math.sin(day_angle) + 2.5 * math.cos(hour_angle - math.pi)
        temperature_c = round(t_base, 2)

        # 4. Relative Humidity (50% to 95%)
        rh_base = 75.0 + 15.0 * math.sin(lon_rad * 2.0) - 10.0 * math.cos(hour_angle)
        relative_humidity_pct = round(min(99.0, max(30.0, rh_base)), 1)

        # 5. Surface Pressure (1005 to 1020 hPa)
        p_base = 1013.25 + 5.0 * math.sin(day_angle * 2.0) + 2.0 * math.cos(lat_rad)
        surface_pressure_hpa = round(p_base, 1)

        # 6. Solar Irradiance & GHI
        sun_elevation = math.sin(lat_rad) * math.sin(0.4 * math.sin(day_angle)) + math.cos(lat_rad) * math.cos(0.4 * math.sin(day_angle)) * math.cos(hour_angle - math.pi)
        if sun_elevation > 0.0:
            solar_irradiance_w_per_m2 = round(1000.0 * sun_elevation * 0.85, 1)
        else:
            solar_irradiance_w_per_m2 = 0.0
        daily_ghi_kwh_per_m2 = round(max(1.0, 5.5 + 1.2 * math.cos(lat_rad)), 2)

        # 7. Cloud Cover & Precipitation
        cloud_cover_pct = round(max(0.0, min(100.0, 40.0 + 30.0 * math.sin(lon_rad + day_angle))), 1)
        precipitation_mm_per_hr = 0.0 if cloud_cover_pct < 70.0 else round((cloud_cover_pct - 70.0) * 0.1, 2)

        # 8. Marine & Oceanics
        wave_height_m = round(max(0.2, 1.2 + 0.8 * math.sin(lat_rad * 4.0 + day_angle)), 2)
        wave_direction_deg = round((wind_direction_deg + 15.0) % 360.0, 1)
        wave_period_s = round(max(3.0, 6.0 + 2.5 * math.cos(day_angle)), 1)
        ocean_current_speed_knots = round(max(0.1, 0.8 + 0.5 * math.sin(lon_rad * 3.0)), 2)
        ocean_current_direction_deg = round((lat_rad * 180.0 / math.pi * 2.0) % 360.0, 1)

        # Build raw dict
        data: Dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "timestamp_utc": validity_dt.isoformat(),
            "retrieval_timestamp_utc": self.fixed_reference_time.isoformat(),
            "data_source": self.provider_name,
            "data_type": provenance,
            "data_quality": WeatherQualityState.VALID,
            "freshness": WeatherFreshnessState.FRESH,
            "wind_speed_ms": wind_speed_ms,
            "wind_speed_knots": wind_speed_knots,
            "wind_direction_deg": wind_direction_deg,
            "temperature_c": temperature_c,
            "relative_humidity_pct": relative_humidity_pct,
            "surface_pressure_hpa": surface_pressure_hpa,
            "solar_irradiance_w_per_m2": solar_irradiance_w_per_m2,
            "daily_ghi_kwh_per_m2": daily_ghi_kwh_per_m2,
            "cloud_cover_pct": cloud_cover_pct,
            "precipitation_mm_per_hr": precipitation_mm_per_hr,
            "wave_height_m": wave_height_m,
            "wave_direction_deg": wave_direction_deg,
            "wave_period_s": wave_period_s,
            "ocean_current_speed_knots": ocean_current_speed_knots,
            "ocean_current_direction_deg": ocean_current_direction_deg,
        }

        # Apply fault modes if requested
        if self.mode == "missing_fields":
            # Simulate a provider lacking oceanic & solar data
            data["wave_height_m"] = None
            data["wave_direction_deg"] = None
            data["wave_period_s"] = None
            data["ocean_current_speed_knots"] = None
            data["ocean_current_direction_deg"] = None
            data["solar_irradiance_w_per_m2"] = None
            data["data_quality"] = WeatherQualityState.PARTIAL

        elif self.mode == "stale":
            # Set timestamp 48 hours before reference retrieval
            stale_dt = validity_dt - timedelta(days=2)
            data["timestamp_utc"] = stale_dt.isoformat()
            data["freshness"] = WeatherFreshnessState.EXPIRED

        elif self.mode == "invalid":
            # Deliberately violate physical bounds (for negative testing)
            data["relative_humidity_pct"] = 150.0  # Invalid > 100%

        # Apply explicit field overrides if configured
        for k, v in self.field_overrides.items():
            data[k] = v

        record = NormalizedWeatherRecord(**data)
        record.evaluate_freshness(current_time_utc=self.fixed_reference_time)
        record.evaluate_quality()
        return record

    def get_current_weather(
        self,
        latitude: float,
        longitude: float,
    ) -> NormalizedWeatherRecord:
        return self._generate_synthetic_record(
            latitude=latitude,
            longitude=longitude,
            validity_dt=self.fixed_reference_time,
            provenance=WeatherProvenanceType.OBSERVED,
        )

    def get_historical_weather(
        self,
        latitude: float,
        longitude: float,
        timestamp: Union[datetime, str],
    ) -> NormalizedWeatherRecord:
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)

        return self._generate_synthetic_record(
            latitude=latitude,
            longitude=longitude,
            validity_dt=dt,
            provenance=WeatherProvenanceType.HISTORICAL,
        )

    def get_forecast_weather(
        self,
        latitude: float,
        longitude: float,
        horizon_hours: int = 24,
        step_hours: int = 1,
    ) -> List[NormalizedWeatherRecord]:
        if horizon_hours < 1:
            raise ValueError(f"horizon_hours must be >= 1, got {horizon_hours}")
        if step_hours < 1:
            raise ValueError(f"step_hours must be >= 1, got {step_hours}")

        forecasts: List[NormalizedWeatherRecord] = []
        for h in range(0, horizon_hours + 1, step_hours):
            dt = self.fixed_reference_time + timedelta(hours=h)
            record = self._generate_synthetic_record(
                latitude=latitude,
                longitude=longitude,
                validity_dt=dt,
                provenance=WeatherProvenanceType.FORECAST,
            )
            forecasts.append(record)

        return forecasts
