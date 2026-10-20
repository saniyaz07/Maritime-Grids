"""
app/weather/provider.py — Phase 10C.1 Weather Provider Abstract Interface
==========================================================================
Defines the provider-independent base interface for weather data retrieval.
Allows arbitrary live, historical, forecast, or synthetic mock weather providers
to be plugged into the platform without modifying core application logic.

Key Invariants:
  - Strict abstract base class interface.
  - Zero hard-coded commercial API dependencies or credentials.
  - Provider-agnostic normalized outputs.
  - Comprehensive error handling and type annotations.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional, Union

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherQualityState,
)


class WeatherProvider(ABC):
    """
    Abstract interface for all weather providers in Maritime Grids.
    Implementations may query external REST APIs (e.g. Open-Meteo, NOAA, Copernicus),
    climatological databases (e.g. NASA POWER), or deterministic test fixtures.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier name for this provider instance."""
        pass

    @abstractmethod
    def get_current_weather(
        self,
        latitude: float,
        longitude: float,
    ) -> NormalizedWeatherRecord:
        """
        Retrieves current/live weather observation for a specific coordinate.

        Args:
            latitude: Geographic latitude [-90.0, 90.0]
            longitude: Geographic longitude [-180.0, 180.0]

        Returns:
            NormalizedWeatherRecord with data_type=OBSERVED or MODEL_PREDICTION
        """
        pass

    @abstractmethod
    def get_historical_weather(
        self,
        latitude: float,
        longitude: float,
        timestamp: Union[datetime, str],
    ) -> NormalizedWeatherRecord:
        """
        Retrieves historical weather observation for a specific coordinate and time.

        Args:
            latitude: Geographic latitude [-90.0, 90.0]
            longitude: Geographic longitude [-180.0, 180.0]
            timestamp: Valid ISO 8601 string or datetime object

        Returns:
            NormalizedWeatherRecord with data_type=HISTORICAL
        """
        pass

    @abstractmethod
    def get_forecast_weather(
        self,
        latitude: float,
        longitude: float,
        horizon_hours: int = 24,
        step_hours: int = 1,
    ) -> List[NormalizedWeatherRecord]:
        """
        Retrieves weather forecast time-series for a coordinate.

        Args:
            latitude: Geographic latitude [-90.0, 90.0]
            longitude: Geographic longitude [-180.0, 180.0]
            horizon_hours: Total forecast horizon duration (hours)
            step_hours: Discrete step size between forecast points (hours)

        Returns:
            List of NormalizedWeatherRecord instances with data_type=FORECAST
        """
        pass

    def get_route_weather(
        self,
        waypoints: List[RouteWaypoint],
        route_id: str = "ROUTE_001",
        vessel_id: Optional[str] = None,
    ) -> RouteWeatherProfile:
        """
        Constructs a complete weather profile along a sequenced set of route waypoints.
        Default implementation queries get_historical_weather (if ETA is past),
        get_forecast_weather (if ETA is future), or get_current_weather for each waypoint.
        """
        if not waypoints:
            raise ValueError("Waypoints list cannot be empty for route weather profiling.")

        records: List[NormalizedWeatherRecord] = []
        has_missing = False

        for wp in waypoints:
            if wp.estimated_arrival_utc:
                # If ETA is provided, fetch point-in-time weather
                record = self.get_historical_weather(
                    latitude=wp.latitude,
                    longitude=wp.longitude,
                    timestamp=wp.estimated_arrival_utc,
                )
            else:
                # Default to current weather at waypoint
                record = self.get_current_weather(
                    latitude=wp.latitude,
                    longitude=wp.longitude,
                )

            records.append(record)
            if record.data_quality != WeatherQualityState.VALID:
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
