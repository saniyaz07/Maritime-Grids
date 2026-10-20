"""
app/telemetry/contracts.py — Phase 10C.12 Canonical Telemetry Ingestion Contracts
==================================================================================
Defines strongly-typed, Pydantic V2 compliant contracts for incoming vessel,
engine, and energy telemetry streams, establishing a single source of truth
for real-time and simulated bridge situational awareness.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Strict geographic validation (-90 <= lat <= 90, -180 <= lon <= 180).
  - Strict heading / course validation (0 <= deg <= 360).
  - Strict null semantics: null != 0 (unmeasured values remain None, never 0.0).
  - Engine operational state: exactly 3 states (ON, OFF, UNKNOWN).
  - Provenance tracking: OBSERVED, HISTORICAL, FORECAST, SIMULATED, UNAVAILABLE.
  - Freshness model: FRESH, STALE, EXPIRED, UNKNOWN, DISCONNECTED.
  - Read-only: Zero actuator or control commands.
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from app.weather.contracts import (
    NormalizedWeatherRecord,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.voyage.contracts import VesselEnergyState, VesselPosition


# =====================================================================
# 1. ENUMS (ENGINE STATE, FRESHNESS, QUALITY, PROVENANCE)
# =====================================================================

class EngineOperationalState(str, Enum):
    """
    Operational state of the vessel's propulsion engine.
    Must never be inferred from SOG or fuel alone without explicit telemetry.
    """
    ON = "ON"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"


class TelemetryFreshnessState(str, Enum):
    """
    Temporal freshness classification of the telemetry stream.
    """
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    DISCONNECTED = "DISCONNECTED"


class TelemetryQualityState(str, Enum):
    """
    Data validation quality classification.
    """
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class TelemetryProvenanceType(str, Enum):
    """
    Data source origin semantics.
    """
    OBSERVED = "OBSERVED"
    HISTORICAL = "HISTORICAL"
    FORECAST = "FORECAST"
    SIMULATED = "SIMULATED"
    UNAVAILABLE = "UNAVAILABLE"


# =====================================================================
# 2. TELEMETRY SUB-CONTRACTS
# =====================================================================

class PositionTelemetry(BaseModel):
    """
    Vessel geographic navigation and kinematics telemetry.
    """
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0, description="Latitude in decimal degrees [-90, 90]")
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0, description="Longitude in decimal degrees [-180, 180]")
    speed_over_ground_knots: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Speed Over Ground in knots")
    course_over_ground_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0, description="Course Over Ground in degrees [0, 360]")
    heading_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0, description="Vessel true heading in degrees [0, 360]")

    @field_validator("course_over_ground_deg", "heading_deg")
    @classmethod
    def normalize_degrees(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if not math.isfinite(v):
            raise ValueError("Angle value must be finite")
        return round(float(v % 360.0), 2)


class EngineTelemetry(BaseModel):
    """
    Main engine operating telemetry.
    Defaults to UNKNOWN if direct telemetry is missing or disconnected.
    """
    state: EngineOperationalState = Field(
        default=EngineOperationalState.UNKNOWN,
        description="Engine operational state (ON, OFF, UNKNOWN)",
    )
    rpm: Optional[float] = Field(default=None, ge=0.0, le=10000.0, description="Shaft revolutions per minute")
    load_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Engine MCR load percentage [0, 100]")
    power_kw: Optional[float] = Field(default=None, ge=0.0, description="Engine shaft output power in kW")
    fuel_rate_lph: Optional[float] = Field(default=None, ge=0.0, description="Direct engine fuel flow rate in L/h")


class EnergyTelemetry(BaseModel):
    """
    Vessel clean energy storage, generation, and bunker fuel telemetry.
    """
    fuel_remaining_liters: Optional[float] = Field(default=None, ge=0.0, description="Bunker fuel volume in liters")
    fuel_rate_lph: Optional[float] = Field(default=None, ge=0.0, description="Aggregate fuel consumption rate in L/h")
    battery_soc_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Battery State of Charge (%)")
    battery_soh_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Battery State of Health (%)")
    battery_usable_kwh: Optional[float] = Field(default=None, ge=0.0, description="Usable stored electrical energy in kWh")
    battery_power_kw: Optional[float] = Field(default=None, description="Battery net charging(+) or discharging(-) power in kW")
    solar_power_kw: Optional[float] = Field(default=None, ge=0.0, description="Instantaneous solar PV generation in kW")


class TelemetryQuality(BaseModel):
    """
    Telemetry frame quality and freshness assessment.
    """
    overall: TelemetryQualityState = Field(default=TelemetryQualityState.VALID, description="Overall quality classification")
    freshness: TelemetryFreshnessState = Field(default=TelemetryFreshnessState.FRESH, description="Freshness classification")
    freshness_age_seconds: Optional[float] = Field(default=None, ge=0.0, description="Age of telemetry in seconds")
    validation_errors: List[str] = Field(default_factory=list, description="List of quarantined validation errors if any")


class TelemetryProvenance(BaseModel):
    """
    Telemetry frame origin and metadata.
    """
    source: str = Field(..., min_length=1, description="Telemetry source identifier (e.g. 'GPS_NMEA', 'MODBUS_GW', 'SIMULATOR')")
    mode: TelemetryProvenanceType = Field(default=TelemetryProvenanceType.OBSERVED, description="Provenance mode")
    stream_id: Optional[str] = Field(default=None, description="Optional stream or device correlation ID")


# =====================================================================
# 3. CANONICAL TELEMETRY PAYLOAD CONTRACT
# =====================================================================

class CanonicalTelemetryPayload(BaseModel):
    """
    Unified canonical telemetry payload contract representing a complete,
    validated frame of vessel, engine, and energy state.
    """
    telemetry_id: str = Field(..., min_length=1, description="Unique telemetry frame identifier")
    timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp of telemetry acquisition")
    ingested_at_utc: Optional[str] = Field(default=None, description="ISO 8601 UTC timestamp of host ingestion")
    vessel_id: str = Field(..., min_length=1, description="Target vessel identifier (e.g. 'VESSEL_OSV_01')")
    position: PositionTelemetry = Field(default_factory=PositionTelemetry, description="Kinematics and navigation fix")
    engine: EngineTelemetry = Field(default_factory=EngineTelemetry, description="Main engine operational state")
    energy: EnergyTelemetry = Field(default_factory=EnergyTelemetry, description="Energy storage and fuel reserves")
    quality: TelemetryQuality = Field(default_factory=TelemetryQuality, description="Quality & freshness assessment")
    provenance: TelemetryProvenance = Field(..., description="Telemetry source and provenance classification")

    @field_validator("timestamp_utc", "ingested_at_utc")
    @classmethod
    def validate_timestamp(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        norm = NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)
        if norm is None:
            raise ValueError("Telemetry timestamp must be a valid ISO 8601 string")
        return norm

    def evaluate_freshness(
        self,
        current_time_utc: Optional[Union[datetime, str]] = None,
        fresh_threshold_seconds: float = 60.0,      # 1 minute
        stale_threshold_seconds: float = 900.0,     # 15 minutes
        expired_threshold_seconds: float = 3600.0,  # 1 hour
    ) -> TelemetryFreshnessState:
        """
        Evaluates frame freshness against reference time and updates quality.freshness.
        For simulated telemetry with an ingested_at_utc timestamp, evaluates freshness
        relative to the ingestion time rather than the simulation timestamp.
        """
        try:
            # Source-aware baseline timestamp selection:
            # For SIMULATED provenance with ingested_at_utc set, use ingested_at_utc.
            # Otherwise, use timestamp_utc.
            if self.provenance.mode == TelemetryProvenanceType.SIMULATED and self.ingested_at_utc:
                basis_ts = self.ingested_at_utc
            else:
                basis_ts = self.timestamp_utc

            record_dt = datetime.fromisoformat(basis_ts)
            if record_dt.tzinfo is None:
                record_dt = record_dt.replace(tzinfo=timezone.utc)
            else:
                record_dt = record_dt.astimezone(timezone.utc)

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
            self.quality.freshness_age_seconds = max(0.0, age_sec)

            if age_sec < 0:
                # Slight future clock drift treated as FRESH
                self.quality.freshness = TelemetryFreshnessState.FRESH
            elif age_sec <= fresh_threshold_seconds:
                self.quality.freshness = TelemetryFreshnessState.FRESH
            elif age_sec <= stale_threshold_seconds:
                self.quality.freshness = TelemetryFreshnessState.STALE
            else:
                self.quality.freshness = TelemetryFreshnessState.EXPIRED

            # If telemetry is expired or stale, engine state must degrade to UNKNOWN if not fresh
            if self.quality.freshness in (TelemetryFreshnessState.EXPIRED, TelemetryFreshnessState.DISCONNECTED):
                if self.engine.state != EngineOperationalState.UNKNOWN:
                    self.engine.state = EngineOperationalState.UNKNOWN

        except Exception:
            self.quality.freshness = TelemetryFreshnessState.UNKNOWN
            self.quality.freshness_age_seconds = None

        return self.quality.freshness

    def to_vessel_position(self) -> Optional[VesselPosition]:
        """
        Converts position telemetry to standard VesselPosition if coordinates are present.
        """
        if self.position.latitude is None or self.position.longitude is None:
            return None

        prov_map = {
            TelemetryProvenanceType.OBSERVED: WeatherProvenanceType.OBSERVED,
            TelemetryProvenanceType.HISTORICAL: WeatherProvenanceType.HISTORICAL,
            TelemetryProvenanceType.FORECAST: WeatherProvenanceType.FORECAST,
            TelemetryProvenanceType.SIMULATED: WeatherProvenanceType.SIMULATED,
            TelemetryProvenanceType.UNAVAILABLE: WeatherProvenanceType.UNAVAILABLE,
        }
        return VesselPosition(
            latitude=self.position.latitude,
            longitude=self.position.longitude,
            timestamp_utc=self.timestamp_utc,
            speed_over_ground_knots=self.position.speed_over_ground_knots,
            course_over_ground_deg=self.position.course_over_ground_deg,
            data_type=prov_map.get(self.provenance.mode, WeatherProvenanceType.OBSERVED),
        )

    def to_vessel_energy_state(self) -> VesselEnergyState:
        """
        Converts energy telemetry to standard VesselEnergyState.
        """
        prov_map = {
            TelemetryProvenanceType.OBSERVED: WeatherProvenanceType.OBSERVED,
            TelemetryProvenanceType.HISTORICAL: WeatherProvenanceType.HISTORICAL,
            TelemetryProvenanceType.FORECAST: WeatherProvenanceType.FORECAST,
            TelemetryProvenanceType.SIMULATED: WeatherProvenanceType.SIMULATED,
            TelemetryProvenanceType.UNAVAILABLE: WeatherProvenanceType.UNAVAILABLE,
        }
        return VesselEnergyState(
            battery_soc_pct=self.energy.battery_soc_pct,
            battery_soh_pct=self.energy.battery_soh_pct,
            battery_energy_available_kwh=self.energy.battery_usable_kwh,
            solar_power_kw=self.energy.solar_power_kw,
            fuel_remaining_liters=self.energy.fuel_remaining_liters,
            fuel_consumption_rate_lph=self.energy.fuel_rate_lph or self.engine.fuel_rate_lph,
            provenance=prov_map.get(self.provenance.mode, WeatherProvenanceType.SIMULATED),
        )
