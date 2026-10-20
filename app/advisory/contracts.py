"""
app/advisory/contracts.py — Phase 10C.5 Advisory Contracts & Evidence Schema
============================================================================
Defines strongly-typed, Pydantic V2 compliant advisory schemas, categories,
severity levels, lifecycle states, and evidence models for operator decision support.

Key Invariants:
  - 100% Pydantic V2 compliant.
  - Zero autonomous control: human_review_required is ALWAYS True for actionable advisories.
  - Full evidence traceability: every advisory records the exact data condition that triggered it.
  - Deterministic deduplication key generation.
  - Explicit lifecycle states (ACTIVE, EXPIRED, SUPPRESSED, INVALID).
"""

from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from app.weather.contracts import (
    NormalizedWeatherRecord,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)


# =====================================================================
# 1. ENUMS (CATEGORY, SEVERITY, STATUS)
# =====================================================================

class AdvisoryCategory(str, Enum):
    """Functional domain category of the advisory."""
    WEATHER = "WEATHER"
    ROUTE = "ROUTE"
    ENERGY = "ENERGY"
    FUEL = "FUEL"
    BATTERY = "BATTERY"
    SOLAR = "SOLAR"
    SPEED = "SPEED"
    EMISSIONS = "EMISSIONS"
    CII = "CII"
    DATA_QUALITY = "DATA_QUALITY"
    SYSTEM = "SYSTEM"


class AdvisorySeverity(str, Enum):
    """
    Severity rating indicating operational urgency for the human operator.
      - INFO: Informational status or favorable operating condition.
      - NOTICE: Minor operational condition worthy of attention.
      - WARNING: Condition requiring operator evaluation or mitigation.
      - CRITICAL: Safety or compliance threshold violation requiring urgent review.
    """
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AdvisoryStatus(str, Enum):
    """Lifecycle state of an individual advisory."""
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPPRESSED = "SUPPRESSED"
    INVALID = "INVALID"


# =====================================================================
# 2. EVIDENCE CONTRACT
# =====================================================================

class AdvisoryEvidence(BaseModel):
    """
    Traceable evidence backing an advisory, capturing the exact data point,
    source, threshold, quality, freshness, and timestamp.
    """
    rule_id: str = Field(..., min_length=1, description="Identifier of the rule that generated this evidence")
    source_field: str = Field(..., min_length=1, description="Specific telemetry or calculated field inspected")
    observed_value: Any = Field(..., description="Observed or calculated value that triggered the condition")
    threshold_value: Optional[Any] = Field(default=None, description="Benchmark or safety threshold value if applicable")
    provenance: WeatherProvenanceType = Field(default=WeatherProvenanceType.OBSERVED, description="Origin semantics of the evidence data")
    quality: WeatherQualityState = Field(default=WeatherQualityState.VALID, description="Quality classification of evidence")
    freshness: WeatherFreshnessState = Field(default=WeatherFreshnessState.FRESH, description="Freshness classification of evidence")
    timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp when the evidence was recorded")

    @field_validator("timestamp_utc")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v) or v


# =====================================================================
# 3. ADVISORY CONTRACT
# =====================================================================

class Advisory(BaseModel):
    """
    Strongly-typed advisory message presented to human operators and dashboard feeds.
    CRITICAL: human_review_required is ALWAYS True; the system never actuates commands automatically.
    """
    advisory_id: str = Field(..., min_length=1, description="Unique advisory instance identifier")
    rule_id: str = Field(..., min_length=1, description="Unique rule identifier that triggered the advisory")
    category: AdvisoryCategory = Field(..., description="Functional advisory domain")
    severity: AdvisorySeverity = Field(..., description="Urgency / severity level")
    title: str = Field(..., min_length=1, description="Concise human-readable advisory headline")
    message: str = Field(..., min_length=1, description="Detailed explanatory advisory text and context")
    status: AdvisoryStatus = Field(default=AdvisoryStatus.ACTIVE, description="Lifecycle status")
    created_at_utc: str = Field(..., description="ISO 8601 UTC creation timestamp")
    valid_until_utc: Optional[str] = Field(default=None, description="Optional ISO 8601 UTC expiration timestamp")
    evidence: List[AdvisoryEvidence] = Field(default_factory=list, description="List of evidence items supporting this advisory")
    human_review_required: bool = Field(default=True, description="Strict safety flag: human operator review always required")
    deduplication_key: Optional[str] = Field(default=None, description="Deterministic key for suppressing duplicate active advisories")

    @field_validator("created_at_utc", "valid_until_utc")
    @classmethod
    def validate_advisory_timestamps(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v)

    @model_validator(mode="after")
    def compute_deduplication_key(self) -> "Advisory":
        """Generates a deterministic deduplication hash if not explicitly supplied."""
        if self.deduplication_key is None:
            raw = f"{self.rule_id}:{self.category.value}:{self.severity.value}:{self.title}"
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
            self.deduplication_key = f"adv:{self.category.value.lower()}:{digest}"
        return self

    def is_expired(self, current_time: Optional[Union[datetime, str]] = None) -> bool:
        """Determines if the advisory has exceeded its valid_until_utc timestamp."""
        if self.valid_until_utc is None:
            return False
        try:
            exp_dt = datetime.fromisoformat(self.valid_until_utc)
            if current_time is None:
                now_dt = datetime.now(timezone.utc)
            elif isinstance(current_time, str):
                now_dt = datetime.fromisoformat(current_time)
                if now_dt.tzinfo is None:
                    now_dt = now_dt.replace(tzinfo=timezone.utc)
            else:
                now_dt = current_time.astimezone(timezone.utc) if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)

            return now_dt >= exp_dt
        except Exception:
            return False


# =====================================================================
# 4. EXPLICIT OPERATIONAL POLICY CONTRACTS (PROVENANCE-CONTROLLED)
# =====================================================================

class BatterySocPolicy(BaseModel):
    """
    Caller-configurable battery SoC notification thresholds.
    If a threshold is None, no threshold-based advisory is emitted.
    CRITICAL RULE: Zero hard-coded default thresholds.
    """
    warning_threshold_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Warning trigger threshold (e.g. 20.0%)")
    notice_threshold_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Notice trigger threshold (e.g. 35.0%)")


class FuelLevelPolicy(BaseModel):
    """
    Caller-configurable bunker fuel reserve notification threshold.
    If None, no threshold-based advisory is emitted.
    """
    warning_threshold_liters: Optional[float] = Field(default=None, ge=0.0, description="Warning trigger volume in liters")


class WeatherSafetyPolicy(BaseModel):
    """
    Caller-configurable environmental safety notification thresholds.
    If None, no threshold-based advisory is emitted.
    """
    high_wind_threshold_knots: Optional[float] = Field(default=None, ge=0.0, description="High wind threshold in knots")
    rough_sea_threshold_m: Optional[float] = Field(default=None, ge=0.0, description="Rough sea significant wave height threshold in meters")


class AdvisoryPolicy(BaseModel):
    """
    Aggregated operational policy configuration supplied by the caller/application.
    Ensures all threshold evaluation is driven by explicit policy rather than invented defaults.
    """
    battery_policy: BatterySocPolicy = Field(default_factory=BatterySocPolicy)
    fuel_policy: FuelLevelPolicy = Field(default_factory=FuelLevelPolicy)
    weather_policy: WeatherSafetyPolicy = Field(default_factory=WeatherSafetyPolicy)

