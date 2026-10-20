"""
app/weather/cache.py — Phase 10C.1 Weather Caching Contract & Minimal Implementation
===================================================================================
Defines the cache contract, TTL policy, and in-memory cache implementation for
weather data records. Prevents redundant external network API hits and protects
downstream components from rate limits.

Key Invariants:
  - Strongly-typed cache entry schema.
  - Deterministic key generation from provider, coordinates, timestamp, and data type.
  - Explicit TTL expiration checks.
  - Thread-safe in-memory cache suitable for desktop and local deployments.
"""

from datetime import datetime, timezone
import hashlib
from typing import Dict, Optional, Union
from pydantic import BaseModel, Field

from app.weather.contracts import (
    NormalizedWeatherRecord,
    WeatherProvenanceType,
)


class WeatherCacheEntry(BaseModel):
    """
    Standardized cache metadata and payload entry.
    """
    cache_key: str = Field(..., description="Unique deterministic cache key")
    location_lat: float = Field(..., ge=-90.0, le=90.0)
    location_lon: float = Field(..., ge=-180.0, le=180.0)
    timestamp_utc: str = Field(..., description="ISO 8601 UTC validity timestamp")
    data_type: WeatherProvenanceType
    provider_name: str
    retrieval_time_utc: str = Field(..., description="ISO 8601 UTC cache write timestamp")
    ttl_seconds: float = Field(..., gt=0.0, description="Time to live in seconds")
    record: NormalizedWeatherRecord

    def is_expired(self, current_time: Optional[Union[datetime, str]] = None) -> bool:
        """Determines if the cached entry has exceeded its TTL."""
        try:
            write_dt = datetime.fromisoformat(self.retrieval_time_utc)
            if current_time is None:
                now_dt = datetime.now(timezone.utc)
            elif isinstance(current_time, str):
                now_dt = datetime.fromisoformat(current_time)
                if now_dt.tzinfo is None:
                    now_dt = now_dt.replace(tzinfo=timezone.utc)
            else:
                now_dt = current_time.astimezone(timezone.utc) if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)

            age = (now_dt - write_dt).total_seconds()
            return age >= self.ttl_seconds
        except Exception:
            return True


class InMemoryWeatherCache:
    """
    Simple, fast in-memory weather cache supporting TTL and key lookup.
    """

    def __init__(self, default_ttl_seconds: float = 3600.0) -> None:
        self.default_ttl_seconds = default_ttl_seconds
        self._store: Dict[str, WeatherCacheEntry] = {}

    @staticmethod
    def generate_cache_key(
        provider_name: str,
        latitude: float,
        longitude: float,
        timestamp_utc: str,
        data_type: WeatherProvenanceType,
    ) -> str:
        """Generates a normalized, collision-resistant deterministic cache key."""
        lat_rounded = round(latitude, 4)
        lon_rounded = round(longitude, 4)
        raw_key = f"{provider_name.upper()}:{lat_rounded}:{lon_rounded}:{timestamp_utc}:{data_type.value}"
        hash_digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
        return f"wx:{provider_name.lower()}:{lat_rounded}:{lon_rounded}:{hash_digest}"

    def get(
        self,
        cache_key: str,
        current_time: Optional[Union[datetime, str]] = None,
    ) -> Optional[NormalizedWeatherRecord]:
        """Retrieves a non-expired record from the cache, or None if expired/missing."""
        entry = self._store.get(cache_key)
        if entry is None:
            return None
        if entry.is_expired(current_time):
            del self._store[cache_key]
            return None
        return entry.record

    def set(
        self,
        record: NormalizedWeatherRecord,
        ttl_seconds: Optional[float] = None,
        retrieval_time: Optional[datetime] = None,
        custom_key: Optional[str] = None,
    ) -> str:
        """Stores a weather record with a defined TTL and returns its cache key."""
        ttl = ttl_seconds or self.default_ttl_seconds
        retrieval_dt = retrieval_time or datetime.now(timezone.utc)
        if retrieval_dt.tzinfo is None:
            retrieval_dt = retrieval_dt.replace(tzinfo=timezone.utc)

        key = custom_key or self.generate_cache_key(
            provider_name=record.data_source,
            latitude=record.latitude,
            longitude=record.longitude,
            timestamp_utc=record.timestamp_utc,
            data_type=record.data_type,
        )

        entry = WeatherCacheEntry(
            cache_key=key,
            location_lat=record.latitude,
            location_lon=record.longitude,
            timestamp_utc=record.timestamp_utc,
            data_type=record.data_type,
            provider_name=record.data_source,
            retrieval_time_utc=retrieval_dt.isoformat(),
            ttl_seconds=ttl,
            record=record,
        )
        self._store[key] = entry
        return key

    def clear(self) -> None:
        """Flushes the entire cache."""
        self._store.clear()

    def size(self) -> int:
        """Returns the current number of cached entries."""
        return len(self._store)

    def cleanup_expired(self, current_time: Optional[Union[datetime, str]] = None) -> int:
        """Removes all expired entries and returns the count of purged items."""
        expired_keys = [k for k, entry in self._store.items() if entry.is_expired(current_time)]
        for k in expired_keys:
            del self._store[k]
        return len(expired_keys)
