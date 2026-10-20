"""
app/advisory — Phase 10C.5 Advisory Engine Contract & Deterministic Rules
========================================================================
Provides strongly-typed advisory contracts, evidence models, deterministic
rule definitions, policy contracts, and a human-in-the-loop advisory engine
for maritime decision-support and operator dashboard telemetry.
"""

from app.advisory.contracts import (
    AdvisoryCategory,
    AdvisorySeverity,
    AdvisoryStatus,
    AdvisoryEvidence,
    Advisory,
    BatterySocPolicy,
    FuelLevelPolicy,
    WeatherSafetyPolicy,
    AdvisoryPolicy,
)
from app.advisory.rules import (
    AdvisoryRule,
    DataQualityWeatherStaleRule,
    DataQualityWeatherUnavailableRule,
    DataQualityWeatherInvalidRule,
    BatterySocLowRule,
    FuelLevelLowRule,
    CiiRatingNonCompliantRule,
    HighWindAdvisoryRule,
    RoughSeaAdvisoryRule,
    DecisionReadinessRule,
    DEFAULT_RULE_SET,
    build_rule_set_from_policy,
)
from app.advisory.engine import AdvisoryEngine

__all__ = [
    "AdvisoryCategory",
    "AdvisorySeverity",
    "AdvisoryStatus",
    "AdvisoryEvidence",
    "Advisory",
    "BatterySocPolicy",
    "FuelLevelPolicy",
    "WeatherSafetyPolicy",
    "AdvisoryPolicy",
    "AdvisoryRule",
    "DataQualityWeatherStaleRule",
    "DataQualityWeatherUnavailableRule",
    "DataQualityWeatherInvalidRule",
    "BatterySocLowRule",
    "FuelLevelLowRule",
    "CiiRatingNonCompliantRule",
    "HighWindAdvisoryRule",
    "RoughSeaAdvisoryRule",
    "DecisionReadinessRule",
    "DEFAULT_RULE_SET",
    "build_rule_set_from_policy",
    "AdvisoryEngine",
]
