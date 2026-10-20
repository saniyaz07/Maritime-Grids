"""
app/advisory/rules.py — Phase 10C.5 Deterministic Advisory Rules
================================================================
Defines deterministic, explainable, and independently testable advisory rules.
Every rule consumes a DecisionContext and produces zero or more Advisory items
backed by verifiable evidence.

Key Invariants:
  - 100% deterministic (no random numbers, no LLMs).
  - Purely read-only: never mutates DecisionContext or vessel state.
  - Zero autonomous control: all advisories require human operator review.
  - Strict evidence attachment: missing values never trigger fake warnings.
  - No wind propulsion or engine-off calculation rules.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.weather.contracts import (
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
)
from app.advisory.contracts import (
    Advisory,
    AdvisoryCategory,
    AdvisoryEvidence,
    AdvisorySeverity,
    AdvisoryStatus,
)


class AdvisoryRule(ABC):
    """
    Abstract base class for all deterministic advisory rules.
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for this rule."""
        pass

    @property
    @abstractmethod
    def category(self) -> AdvisoryCategory:
        """Functional domain category."""
        pass

    @abstractmethod
    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        """
        Evaluates the DecisionContext and returns zero or more Advisories.
        Must NOT modify context in place.
        """
        pass


# =====================================================================
# 1. DATA QUALITY & WEATHER RULES
# =====================================================================

class DataQualityWeatherStaleRule(AdvisoryRule):
    """Generates an advisory if weather telemetry is stale or expired."""

    @property
    def rule_id(self) -> str:
        return "DQ_WX_STALE_001"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.DATA_QUALITY

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        wx_ctx = context.voyage_context.weather_context
        curr_wx = wx_ctx.current_weather

        if curr_wx is None:
            return []

        if curr_wx.freshness in (WeatherFreshnessState.STALE, WeatherFreshnessState.EXPIRED):
            severity = AdvisorySeverity.WARNING if curr_wx.freshness == WeatherFreshnessState.EXPIRED else AdvisorySeverity.NOTICE
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="weather_context.current_weather.freshness",
                observed_value=curr_wx.freshness.value,
                threshold_value=WeatherFreshnessState.FRESH.value,
                provenance=curr_wx.data_type,
                quality=curr_wx.data_quality,
                freshness=curr_wx.freshness,
                timestamp_utc=curr_wx.timestamp_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_STALE_WX_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=severity,
                    title="Weather Data Freshness Notice",
                    message=(
                        f"Weather telemetry from {curr_wx.data_source} is {curr_wx.freshness.value} "
                        f"(Age: {curr_wx.freshness_age_seconds or 'unknown'}s). Do not treat as instantaneous live conditions."
                    ),
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


class DataQualityWeatherUnavailableRule(AdvisoryRule):
    """Generates an advisory if weather telemetry is absent."""

    @property
    def rule_id(self) -> str:
        return "DQ_WX_UNAVAIL_002"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.DATA_QUALITY

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        wx_ctx = context.voyage_context.weather_context
        curr_wx = wx_ctx.current_weather

        if curr_wx is None or wx_ctx.weather_quality == WeatherQualityState.UNAVAILABLE:
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="weather_context.current_weather",
                observed_value="UNAVAILABLE",
                threshold_value="AVAILABLE",
                provenance=WeatherProvenanceType.UNAVAILABLE,
                quality=WeatherQualityState.UNAVAILABLE,
                freshness=WeatherFreshnessState.UNKNOWN,
                timestamp_utc=context.created_at_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_UNAVAIL_WX_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.WARNING,
                    title="Weather Telemetry Unavailable",
                    message="Instantaneous weather observation is unavailable at current vessel coordinates.",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


class DataQualityWeatherInvalidRule(AdvisoryRule):
    """Generates a critical advisory if weather telemetry contains corrupted data."""

    @property
    def rule_id(self) -> str:
        return "DQ_WX_INVALID_003"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.DATA_QUALITY

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        wx_ctx = context.voyage_context.weather_context
        curr_wx = wx_ctx.current_weather

        if wx_ctx.weather_quality == WeatherQualityState.INVALID or (curr_wx and curr_wx.data_quality == WeatherQualityState.INVALID):
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="weather_context.current_weather.data_quality",
                observed_value="INVALID",
                threshold_value="VALID",
                provenance=curr_wx.data_type if curr_wx else WeatherProvenanceType.UNAVAILABLE,
                quality=WeatherQualityState.INVALID,
                freshness=curr_wx.freshness if curr_wx else WeatherFreshnessState.UNKNOWN,
                timestamp_utc=context.created_at_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_INVALID_WX_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.CRITICAL,
                    title="Corrupt Weather Telemetry Detected",
                    message="Weather telemetry contains out-of-bounds or malformed values. Discarded from downstream evaluations.",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


# =====================================================================
# 2. ENERGY & FUEL ADVISORY RULES (PROVENANCE-CONTROLLED THRESHOLDS)
# =====================================================================

class BatterySocLowRule(AdvisoryRule):
    """
    Generates an advisory if battery State of Charge falls below caller-configured operational thresholds.
    CRITICAL PROVENANCE RULE: If thresholds are None, no threshold-based advisory is generated.
    """

    def __init__(
        self,
        warning_threshold_pct: Optional[float] = None,
        notice_threshold_pct: Optional[float] = None,
    ) -> None:
        self.warning_threshold_pct = warning_threshold_pct
        self.notice_threshold_pct = notice_threshold_pct

    @property
    def rule_id(self) -> str:
        return "ENG_BATT_SOC_001"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.BATTERY

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        # If no policy threshold is configured, do not emit threshold advisory
        if self.warning_threshold_pct is None and self.notice_threshold_pct is None:
            return []

        energy = context.voyage_context.energy_state
        soc = energy.battery_soc_pct

        # If telemetry unavailable, do not trigger (missing != zero)
        if soc is None:
            return []

        if self.warning_threshold_pct is not None and soc < self.warning_threshold_pct:
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="energy_state.battery_soc_pct",
                observed_value=soc,
                threshold_value=self.warning_threshold_pct,
                provenance=energy.provenance,
                quality=WeatherQualityState.VALID,
                freshness=WeatherFreshnessState.FRESH,
                timestamp_utc=context.voyage_context.current_position.timestamp_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_BATT_LOW_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.WARNING,
                    title="Battery State of Charge Low",
                    message=f"Battery SoC is currently {soc:.1f}%, below the configured policy threshold ({self.warning_threshold_pct:.1f}%). Evaluate diesel generator auxiliary dispatch.",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        elif self.notice_threshold_pct is not None and soc < self.notice_threshold_pct:
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="energy_state.battery_soc_pct",
                observed_value=soc,
                threshold_value=self.notice_threshold_pct,
                provenance=energy.provenance,
                quality=WeatherQualityState.VALID,
                freshness=WeatherFreshnessState.FRESH,
                timestamp_utc=context.voyage_context.current_position.timestamp_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_BATT_NOTICE_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.NOTICE,
                    title="Battery State of Charge Moderate",
                    message=f"Battery SoC is {soc:.1f}%, below the configured notice threshold ({self.notice_threshold_pct:.1f}%).",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


class FuelLevelLowRule(AdvisoryRule):
    """
    Generates an advisory if remaining fuel volume falls below caller-configured reserve threshold.
    CRITICAL PROVENANCE RULE: If threshold is None, no threshold-based advisory is generated.
    """

    def __init__(self, reserve_threshold_liters: Optional[float] = None) -> None:
        self.reserve_threshold_liters = reserve_threshold_liters

    @property
    def rule_id(self) -> str:
        return "ENG_FUEL_LOW_002"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.FUEL

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        # If no policy threshold is configured, do not emit threshold advisory
        if self.reserve_threshold_liters is None:
            return []

        energy = context.voyage_context.energy_state
        fuel = energy.fuel_remaining_liters

        # If telemetry unavailable, do not trigger (missing != zero)
        if fuel is None:
            return []

        if fuel < self.reserve_threshold_liters:
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="energy_state.fuel_remaining_liters",
                observed_value=fuel,
                threshold_value=self.reserve_threshold_liters,
                provenance=energy.provenance,
                quality=WeatherQualityState.VALID,
                freshness=WeatherFreshnessState.FRESH,
                timestamp_utc=context.voyage_context.current_position.timestamp_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_FUEL_LOW_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.WARNING,
                    title="Bunker Fuel Level Low",
                    message=f"Remaining bunker fuel is {fuel:.1f} L, below configured policy reserve threshold ({self.reserve_threshold_liters:.1f} L). Review bunkering schedule.",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


# =====================================================================
# 3. REGULATORY & MARITIME SAFETY RULES
# =====================================================================

class CiiRatingNonCompliantRule(AdvisoryRule):
    """Generates an advisory if attained IMO CII rating indicates non-compliance ('D' or 'E')."""

    @property
    def rule_id(self) -> str:
        return "REG_CII_NONCOMPLIANT_001"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.CII

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        eng = context.engineering_inputs
        if eng is None or eng.cii_attained_rating is None:
            return []

        rating = eng.cii_attained_rating.upper().strip()
        if rating in ("D", "E"):
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="engineering_inputs.cii_attained_rating",
                observed_value=rating,
                threshold_value="C or better",
                provenance=eng.provenance,
                quality=WeatherQualityState.VALID,
                freshness=WeatherFreshnessState.FRESH,
                timestamp_utc=context.created_at_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_CII_RATING_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.WARNING,
                    title=f"IMO Carbon Intensity Indicator Rating {rating}",
                    message=(
                        f"Voyage profile results in an attained CII grade of '{rating}'. "
                        "IMO regulations require a Corrective Action Plan (SEEMP Part III) for consecutive D or E ratings."
                    ),
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


class HighWindAdvisoryRule(AdvisoryRule):
    """
    Generates an advisory for high wind conditions if caller configures a safety threshold.
    CRITICAL: Environmental context only, NO wind propulsion or fuel credit calculation.
    """

    def __init__(self, high_wind_threshold_knots: Optional[float] = None) -> None:
        self.high_wind_threshold_knots = high_wind_threshold_knots

    @property
    def rule_id(self) -> str:
        return "MET_WIND_HIGH_001"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.WEATHER

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        if self.high_wind_threshold_knots is None:
            return []

        curr_wx = context.current_weather
        if curr_wx is None or curr_wx.wind_speed_knots is None:
            return []

        wind_kts = curr_wx.wind_speed_knots
        if wind_kts > self.high_wind_threshold_knots:
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="current_weather.wind_speed_knots",
                observed_value=wind_kts,
                threshold_value=self.high_wind_threshold_knots,
                provenance=curr_wx.data_type,
                quality=curr_wx.data_quality,
                freshness=curr_wx.freshness,
                timestamp_utc=curr_wx.timestamp_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_HIGH_WIND_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.WARNING,
                    title="High Wind Advisory",
                    message=f"Observed wind speed is {wind_kts:.1f} knots (> configured threshold {self.high_wind_threshold_knots:.1f} knots). Increased aerodynamic drag and hull resistance expected.",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


class RoughSeaAdvisoryRule(AdvisoryRule):
    """
    Generates an advisory for rough sea states if caller configures a wave height threshold.
    """

    def __init__(self, rough_sea_threshold_m: Optional[float] = None) -> None:
        self.rough_sea_threshold_m = rough_sea_threshold_m

    @property
    def rule_id(self) -> str:
        return "MET_SEA_ROUGH_002"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.WEATHER

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        if self.rough_sea_threshold_m is None:
            return []

        curr_wx = context.current_weather
        if curr_wx is None or curr_wx.wave_height_m is None:
            return []

        hs = curr_wx.wave_height_m
        if hs > self.rough_sea_threshold_m:
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="current_weather.wave_height_m",
                observed_value=hs,
                threshold_value=self.rough_sea_threshold_m,
                provenance=curr_wx.data_type,
                quality=curr_wx.data_quality,
                freshness=curr_wx.freshness,
                timestamp_utc=curr_wx.timestamp_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_ROUGH_SEA_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.WARNING,
                    title="Rough Sea State Advisory",
                    message=f"Significant wave height is {hs:.2f} m (> configured threshold {self.rough_sea_threshold_m:.1f} m). Increased added wave resistance expected.",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


class DecisionReadinessRule(AdvisoryRule):
    """Generates a system advisory if context readiness is not READY."""

    @property
    def rule_id(self) -> str:
        return "SYS_READINESS_001"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.SYSTEM

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        if context.readiness in (AdvisoryReadinessState.INSUFFICIENT_DATA, AdvisoryReadinessState.INVALID_DATA):
            evidence = AdvisoryEvidence(
                rule_id=self.rule_id,
                source_field="decision_context.readiness",
                observed_value=context.readiness.value,
                threshold_value=AdvisoryReadinessState.READY.value,
                provenance=WeatherProvenanceType.SIMULATED,
                quality=WeatherQualityState.VALID,
                freshness=WeatherFreshnessState.FRESH,
                timestamp_utc=context.created_at_utc,
            )
            return [
                Advisory(
                    advisory_id=f"ADV_SYS_READINESS_{context.decision_context_id}",
                    rule_id=self.rule_id,
                    category=self.category,
                    severity=AdvisorySeverity.WARNING,
                    title="Decision Context Data Insufficient",
                    message="; ".join(context.readiness_reasons) if context.readiness_reasons else "Incomplete context data.",
                    created_at_utc=datetime.now(timezone.utc).isoformat(),
                    evidence=[evidence],
                    human_review_required=True,
                )
            ]
        return []


class AdverseWeatherAheadRule(AdvisoryRule):
    """
    Generates a forward-looking advisory if adverse weather (high wind or rough seas)
    is projected ahead along the vessel's route.
    """

    def __init__(
        self,
        high_wind_threshold_knots: Optional[float] = None,
        rough_sea_threshold_m: Optional[float] = None,
    ) -> None:
        self.high_wind_threshold_knots = high_wind_threshold_knots
        self.rough_sea_threshold_m = rough_sea_threshold_m

    @property
    def rule_id(self) -> str:
        return "MET_AHEAD_ADVERSE_001"

    @property
    def category(self) -> AdvisoryCategory:
        return AdvisoryCategory.WEATHER

    def evaluate(self, context: DecisionContext) -> List[Advisory]:
        if self.high_wind_threshold_knots is None and self.rough_sea_threshold_m is None:
            return []

        wx_ctx = context.voyage_context.weather_context
        if wx_ctx is None or wx_ctx.route_weather is None:
            return []

        route_wx = wx_ctx.route_weather
        advisories: List[Advisory] = []

        for idx, rec in enumerate(route_wx.waypoints_weather):
            wp_label = f"Waypoint {idx + 1}"

            # Check high wind ahead
            if (
                self.high_wind_threshold_knots is not None
                and rec.wind_speed_knots is not None
                and rec.wind_speed_knots > self.high_wind_threshold_knots
            ):
                evidence = AdvisoryEvidence(
                    rule_id=self.rule_id,
                    source_field=f"route_weather.waypoints_weather[{idx}].wind_speed_knots",
                    observed_value=rec.wind_speed_knots,
                    threshold_value=self.high_wind_threshold_knots,
                    provenance=rec.data_type,
                    quality=rec.data_quality,
                    freshness=rec.freshness,
                    timestamp_utc=rec.timestamp_utc,
                )
                advisories.append(
                    Advisory(
                        advisory_id=f"ADV_AHEAD_WIND_{context.decision_context_id}_{idx}",
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=AdvisorySeverity.WARNING,
                        title="Adverse High Wind Projected Ahead",
                        message=(
                            f"Forecasted wind speed of {rec.wind_speed_knots:.1f} knots exceeds safety threshold "
                            f"({self.high_wind_threshold_knots:.1f} knots) at {wp_label} (lat={rec.latitude:.2f}, lon={rec.longitude:.2f})."
                        ),
                        created_at_utc=datetime.now(timezone.utc).isoformat(),
                        evidence=[evidence],
                        human_review_required=True,
                    )
                )

            # Check rough sea ahead
            if (
                self.rough_sea_threshold_m is not None
                and rec.wave_height_m is not None
                and rec.wave_height_m > self.rough_sea_threshold_m
            ):
                evidence = AdvisoryEvidence(
                    rule_id=self.rule_id,
                    source_field=f"route_weather.waypoints_weather[{idx}].wave_height_m",
                    observed_value=rec.wave_height_m,
                    threshold_value=self.rough_sea_threshold_m,
                    provenance=rec.data_type,
                    quality=rec.data_quality,
                    freshness=rec.freshness,
                    timestamp_utc=rec.timestamp_utc,
                )
                advisories.append(
                    Advisory(
                        advisory_id=f"ADV_AHEAD_SEA_{context.decision_context_id}_{idx}",
                        rule_id=self.rule_id,
                        category=self.category,
                        severity=AdvisorySeverity.WARNING,
                        title="Adverse Rough Sea State Projected Ahead",
                        message=(
                            f"Forecasted significant wave height of {rec.wave_height_m:.2f} m exceeds safety threshold "
                            f"({self.rough_sea_threshold_m:.1f} m) at {wp_label} (lat={rec.latitude:.2f}, lon={rec.longitude:.2f})."
                        ),
                        created_at_utc=datetime.now(timezone.utc).isoformat(),
                        evidence=[evidence],
                        human_review_required=True,
                    )
                )

        return advisories


# =====================================================================
# DEFAULT RULE SET & POLICY-BASED BUILDER
# =====================================================================

def build_rule_set_from_policy(
    policy: Optional[Any] = None,
    include_lookahead: bool = False,
) -> List[AdvisoryRule]:
    """
    Constructs a standard rule set configured with explicit caller policy thresholds.
    If policy is omitted or empty, threshold rules default to None (zero unprompted alarms).
    If include_lookahead is True, AdverseWeatherAheadRule is included in the rule set.
    """
    batt_warn = getattr(getattr(policy, "battery_policy", None), "warning_threshold_pct", None)
    batt_notice = getattr(getattr(policy, "battery_policy", None), "notice_threshold_pct", None)
    fuel_warn = getattr(getattr(policy, "fuel_policy", None), "warning_threshold_liters", None)
    wind_warn = getattr(getattr(policy, "weather_policy", None), "high_wind_threshold_knots", None)
    sea_warn = getattr(getattr(policy, "weather_policy", None), "rough_sea_threshold_m", None)

    rules: List[AdvisoryRule] = [
        DataQualityWeatherStaleRule(),
        DataQualityWeatherUnavailableRule(),
        DataQualityWeatherInvalidRule(),
        BatterySocLowRule(warning_threshold_pct=batt_warn, notice_threshold_pct=batt_notice),
        FuelLevelLowRule(reserve_threshold_liters=fuel_warn),
        CiiRatingNonCompliantRule(),
        HighWindAdvisoryRule(high_wind_threshold_knots=wind_warn),
        RoughSeaAdvisoryRule(rough_sea_threshold_m=sea_warn),
        DecisionReadinessRule(),
    ]

    if include_lookahead:
        rules.append(
            AdverseWeatherAheadRule(
                high_wind_threshold_knots=wind_warn,
                rough_sea_threshold_m=sea_warn,
            )
        )

    return rules


DEFAULT_RULE_SET: List[AdvisoryRule] = [
    DataQualityWeatherStaleRule(),
    DataQualityWeatherUnavailableRule(),
    DataQualityWeatherInvalidRule(),
    BatterySocLowRule(),
    FuelLevelLowRule(),
    CiiRatingNonCompliantRule(),
    HighWindAdvisoryRule(),
    RoughSeaAdvisoryRule(),
    DecisionReadinessRule(),
]
