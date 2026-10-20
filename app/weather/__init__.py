"""
app/weather — Phase 10C.1 / 10C.2 Weather Provider Abstraction & Connectors
===========================================================================
Provides a unified, provider-independent weather abstraction, normalized
data contracts, provenance tracking, freshness evaluation, quality assessment,
deterministic mock fixtures, and Open-Meteo live/historical/forecast connectors.
"""

from app.weather.contracts import (
    WeatherProvenanceType,
    WeatherQualityState,
    WeatherFreshnessState,
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    DriverDashboardWeatherSummary,
)
from app.weather.provider import WeatherProvider
from app.weather.mock_provider import MockWeatherProvider
from app.weather.cache import WeatherCacheEntry, InMemoryWeatherCache
from app.weather.open_meteo_provider import (
    OpenMeteoWeatherProvider,
    WeatherProviderError,
    WeatherProviderUnavailableError,
    WeatherProviderTimeoutError,
    WeatherProviderRateLimitError,
    WeatherProviderInvalidResponseError,
    WeatherProviderInvalidRequestError,
)

__all__ = [
    "WeatherProvenanceType",
    "WeatherQualityState",
    "WeatherFreshnessState",
    "NormalizedWeatherRecord",
    "RouteWaypoint",
    "RouteWeatherProfile",
    "DriverDashboardWeatherSummary",
    "WeatherProvider",
    "MockWeatherProvider",
    "WeatherCacheEntry",
    "InMemoryWeatherCache",
    "OpenMeteoWeatherProvider",
    "WeatherProviderError",
    "WeatherProviderUnavailableError",
    "WeatherProviderTimeoutError",
    "WeatherProviderRateLimitError",
    "WeatherProviderInvalidResponseError",
    "WeatherProviderInvalidRequestError",
]
