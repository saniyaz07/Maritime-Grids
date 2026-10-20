"""
app/decision/contracts.py — Phase 10C.4 Decision Context & Advisory Contracts
=============================================================================
Defines strongly-typed, Pydantic V2 compliant decision context contracts,
engineering inputs, and readiness state classifications for future advisory
and dashboard layers.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Zero physics recalculation: wraps existing VoyageContext and Phase 3–9 outputs.
  - Explicit readiness classification (READY, PARTIAL, INSUFFICIENT_DATA, etc.).
  - Explicit missing-value representation (None / UNAVAILABLE, never fake defaults).
  - Explicit provenance tracking (OBSERVED, HISTORICAL, FORECAST, SIMULATED, etc.).
  - Human-in-the-loop: purely an input context contract, zero autonomous control.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    RouteWeatherProfile,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
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


# =====================================================================
# 1. ADVISORY READINESS ENUMS
# =====================================================================

class AdvisoryReadinessState(str, Enum):
    """
    Evaluates whether the collected decision context contains sufficient,
    fresh, and valid data to support advisory recommendations.
    """
    READY = "READY"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE_DATA = "STALE_DATA"
    INVALID_DATA = "INVALID_DATA"


# =====================================================================
# 2. ENGINEERING DECISION INPUTS
# =====================================================================

class EngineeringDecisionInputs(BaseModel):
    """
    Optional engineering baseline indicators derived from Phase 3–9 core modules.
    CRITICAL RULE: This schema only accepts pre-calculated results; it NEVER recomputes them.
    """
    baseline_fuel_consumption_liters: Optional[float] = Field(default=None, ge=0.0, description="Baseline un-hybridized fuel consumption (L)")
    estimated_solar_energy_kwh: Optional[float] = Field(default=None, ge=0.0, description="Estimated solar yield across voyage (kWh)")
    estimated_battery_displacement_kwh: Optional[float] = Field(default=None, ge=0.0, description="Clean battery energy displacement (kWh)")
    total_clean_energy_kwh: Optional[float] = Field(default=None, ge=0.0, description="Total clean energy budget (kWh)")
    co2_emissions_kg: Optional[float] = Field(default=None, ge=0.0, description="Estimated CO2 emissions (kg)")
    cii_attained_rating: Optional[str] = Field(default=None, description="Attained IMO CII operational rating (A, B, C, D, E)")
    optimal_transit_speed_knots: Optional[float] = Field(default=None, ge=1.0, le=50.0, description="Recommended operational speed (knots)")
    net_present_value_usd: Optional[float] = Field(default=None, description="Lifecycle NPV of clean retrofit (USD)")
    payback_period_years: Optional[float] = Field(default=None, ge=0.0, description="Capital payback period (years)")
    provenance: WeatherProvenanceType = Field(default=WeatherProvenanceType.SIMULATED, description="Provenance of engineering inputs")


# =====================================================================
# 3. DECISION CONTEXT AGGREGATE
# =====================================================================

class DecisionContext(BaseModel):
    """
    Normalized decision-ready context aggregating vessel, voyage, position,
    timeline, weather observations, energy states, and engineering estimates.
    """
    decision_context_id: str = Field(..., min_length=1, description="Unique identifier for this decision context snapshot")
    created_at_utc: str = Field(..., description="ISO 8601 UTC timestamp of context creation")
    voyage_context: VoyageContext = Field(..., description="Underlying voyage and vessel state aggregate")
    engineering_inputs: Optional[EngineeringDecisionInputs] = Field(default=None, description="Optional upstream engineering indicators")
    readiness: AdvisoryReadinessState = Field(default=AdvisoryReadinessState.INSUFFICIENT_DATA, description="Advisory readiness classification")
    readiness_reasons: List[str] = Field(default_factory=list, description="Diagnostic reasons explaining readiness state")

    @field_validator("decision_context_id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("decision_context_id cannot be empty or whitespace only.")
        return s

    @field_validator("created_at_utc")
    @classmethod
    def validate_created_at(cls, v: str) -> str:
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v) or v

    @model_validator(mode="after")
    def compute_readiness(self) -> "DecisionContext":
        """
        Automatically assesses data completeness, freshness, and quality.
        """
        reasons: List[str] = []
        wx_ctx = self.voyage_context.weather_context
        curr_wx = wx_ctx.current_weather

        # 1. Check for invalid data
        if wx_ctx.weather_quality == WeatherQualityState.INVALID or (curr_wx and curr_wx.data_quality == WeatherQualityState.INVALID):
            self.readiness = AdvisoryReadinessState.INVALID_DATA
            self.readiness_reasons = ["Weather observation contains out-of-bounds or corrupted data."]
            return self

        # 2. Check for stale / expired data
        if wx_ctx.weather_freshness == WeatherFreshnessState.EXPIRED or (curr_wx and curr_wx.freshness == WeatherFreshnessState.EXPIRED):
            self.readiness = AdvisoryReadinessState.STALE_DATA
            self.readiness_reasons = ["Weather observation has expired (>24 hours old)."]
            return self

        # 3. Check for essential voyage components
        if not self.voyage_context.vessel or not self.voyage_context.route or not self.voyage_context.current_position:
            self.readiness = AdvisoryReadinessState.INSUFFICIENT_DATA
            self.readiness_reasons = ["Missing essential voyage definition or position fix."]
            return self

        # 4. Check for weather availability
        if curr_wx is None or wx_ctx.weather_quality == WeatherQualityState.UNAVAILABLE:
            reasons.append("Current weather observation is unavailable at vessel position.")
            self.readiness = AdvisoryReadinessState.INSUFFICIENT_DATA
            self.readiness_reasons = reasons
            return self

        # 5. Check for partial coverage
        if curr_wx.data_quality == WeatherQualityState.PARTIAL:
            reasons.append("Weather coverage is partial (some oceanic or atmospheric fields missing).")

        if wx_ctx.weather_freshness == WeatherFreshnessState.STALE:
            reasons.append("Weather observation is stale (between 1 and 24 hours old).")

        if self.voyage_context.energy_state.battery_soc_pct is None:
            reasons.append("Real-time battery SoC telemetry is unavailable.")

        if self.voyage_context.energy_state.fuel_remaining_liters is None:
            reasons.append("Bunker fuel telemetry is unavailable.")

        if self.engineering_inputs is None:
            reasons.append("Upstream engineering simulation inputs are unavailable.")

        if reasons:
            self.readiness = AdvisoryReadinessState.PARTIAL
            self.readiness_reasons = reasons
        else:
            self.readiness = AdvisoryReadinessState.READY
            self.readiness_reasons = ["All essential voyage, weather, energy, and engineering inputs are valid and fresh."]

        return self

    # -----------------------------------------------------------------
    # Convenience Projections
    # -----------------------------------------------------------------
    @property
    def voyage_id(self) -> str:
        return self.voyage_context.voyage_id

    @property
    def vessel_id(self) -> str:
        return self.voyage_context.vessel.vessel_id

    @property
    def route_id(self) -> str:
        return self.voyage_context.route.route_id

    @property
    def current_position(self) -> VesselPosition:
        return self.voyage_context.current_position

    @property
    def current_weather(self) -> Optional[NormalizedWeatherRecord]:
        return self.voyage_context.weather_context.current_weather

    @property
    def is_advisory_ready(self) -> bool:
        return self.readiness == AdvisoryReadinessState.READY
