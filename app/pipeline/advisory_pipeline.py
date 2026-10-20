"""
app/pipeline/advisory_pipeline.py — Phase 10C.6 End-to-End Advisory Pipeline
=============================================================================
Orchestrates the end-to-end decision support pipeline:
  WeatherProvider -> Normalized Weather -> VoyageContext -> DecisionContext -> AdvisoryEngine -> AdvisoryPipelineResult

Key Invariants:
  - 100% deterministic, offline execution.
  - Zero autonomous actuation, throttle commands, or steering control.
  - Truthful failure propagation (preserves missing, invalid, or stale data states without fake fallback).
  - Explicit policy handling (zero invented default thresholds; unconfigured policies emit 0 false alarms).
  - Preserves data provenance, quality, freshness, and UTC timestamps.
  - Pure orchestration adapter: uses existing contracts and components without reimplementing physics or optimization.
"""

from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.weather.contracts import (
    NormalizedWeatherRecord,
    RouteWaypoint,
    WeatherFreshnessState,
    WeatherProvenanceType,
    WeatherQualityState,
)
from app.weather.provider import WeatherProvider
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
from app.voyage.context_builder import VoyageContextBuilder
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
    EngineeringDecisionInputs,
)
from app.decision.context_builder import DecisionContextBuilder
from app.advisory.contracts import (
    Advisory,
    AdvisoryCategory,
    AdvisoryEvidence,
    AdvisoryPolicy,
    AdvisorySeverity,
    AdvisoryStatus,
)
from app.advisory.engine import AdvisoryEngine


# =====================================================================
# 1. PIPELINE OUTPUT SCHEMA
# =====================================================================

class AdvisoryPipelineResult(BaseModel):
    """
    Structured, strongly-typed output of the end-to-end advisory pipeline execution.
    Provides complete traceability from raw context through final deduplicated advisories.
    """
    pipeline_id: str = Field(..., min_length=1, description="Unique identifier for this pipeline execution run")
    execution_timestamp_utc: str = Field(..., description="ISO 8601 UTC timestamp of execution")
    decision_context: DecisionContext = Field(..., description="Snapshot of DecisionContext evaluated")
    policy_applied: Optional[AdvisoryPolicy] = Field(default=None, description="Explicit operational policy applied")
    advisories: List[Advisory] = Field(default_factory=list, description="Ordered, deduplicated list of generated advisories")
    readiness_state: AdvisoryReadinessState = Field(..., description="Decision readiness state of the evaluated context")
    
    # Summary metrics
    total_advisories: int = Field(default=0, ge=0, description="Total count of active advisories generated")
    critical_count: int = Field(default=0, ge=0, description="Count of CRITICAL severity advisories")
    warning_count: int = Field(default=0, ge=0, description="Count of WARNING severity advisories")
    notice_count: int = Field(default=0, ge=0, description="Count of NOTICE severity advisories")
    info_count: int = Field(default=0, ge=0, description="Count of INFO severity advisories")

    @field_validator("execution_timestamp_utc")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        return NormalizedWeatherRecord.validate_and_normalize_iso_utc(v) or v

    def get_advisories_by_category(self, category: AdvisoryCategory) -> List[Advisory]:
        """Returns all generated advisories in the specified domain category."""
        return [a for a in self.advisories if a.category == category]

    def get_advisories_by_severity(self, severity: AdvisorySeverity) -> List[Advisory]:
        """Returns all generated advisories with the specified severity level."""
        return [a for a in self.advisories if a.severity == severity]

    def has_critical_advisories(self) -> bool:
        """Returns True if any CRITICAL severity advisories were generated."""
        return self.critical_count > 0

    def to_summary_dict(self) -> Dict[str, Any]:
        """Generates a compact dictionary representation suitable for UI feeds and logging."""
        return {
            "pipeline_id": self.pipeline_id,
            "execution_timestamp_utc": self.execution_timestamp_utc,
            "decision_context_id": self.decision_context.decision_context_id,
            "readiness_state": self.readiness_state.value,
            "total_advisories": self.total_advisories,
            "counts": {
                "critical": self.critical_count,
                "warning": self.warning_count,
                "notice": self.notice_count,
                "info": self.info_count,
            },
            "advisories": [
                {
                    "advisory_id": a.advisory_id,
                    "rule_id": a.rule_id,
                    "category": a.category.value,
                    "severity": a.severity.value,
                    "title": a.title,
                    "message": a.message,
                    "human_review_required": a.human_review_required,
                }
                for a in self.advisories
            ],
        }


# =====================================================================
# 2. ADVISORY PIPELINE ORCHESTRATOR
# =====================================================================

class AdvisoryPipeline:
    """
    Orchestrates the end-to-end maritime decision support pipeline.
    
    Connects:
      WeatherProvider -> VoyageContext -> DecisionContext -> AdvisoryEngine -> AdvisoryPipelineResult
    """

    def __init__(
        self,
        default_policy: Optional[AdvisoryPolicy] = None,
        deduplicate: bool = True,
    ) -> None:
        """
        Initialize the AdvisoryPipeline.

        Args:
            default_policy: Optional default AdvisoryPolicy to apply if none is passed to run().
            deduplicate: Whether the advisory engine should deduplicate active advisories.
        """
        self.default_policy = default_policy
        self.deduplicate = deduplicate

    def run(
        self,
        context: DecisionContext,
        policy: Optional[AdvisoryPolicy] = None,
        pipeline_id: Optional[str] = None,
    ) -> AdvisoryPipelineResult:
        """
        Executes the advisory pipeline against an existing DecisionContext.

        Args:
            context: Fully constructed DecisionContext instance.
            policy: Explicit operational policy thresholds (overrides default_policy if provided).
            pipeline_id: Optional unique run identifier.

        Returns:
            AdvisoryPipelineResult containing evaluated advisories, metrics, and context snapshot.
        """
        if not isinstance(context, DecisionContext):
            raise TypeError(f"Expected DecisionContext instance, got {type(context)}")

        active_policy = policy if policy is not None else self.default_policy
        engine = AdvisoryEngine(policy=active_policy, deduplicate=self.deduplicate)

        advisories = engine.evaluate(context)
        exec_ts = datetime.now(timezone.utc).isoformat()
        run_id = pipeline_id or f"PIPE_{int(datetime.now(timezone.utc).timestamp() * 1000)}"

        # Compute severity distribution
        crit = sum(1 for a in advisories if a.severity == AdvisorySeverity.CRITICAL)
        warn = sum(1 for a in advisories if a.severity == AdvisorySeverity.WARNING)
        notc = sum(1 for a in advisories if a.severity == AdvisorySeverity.NOTICE)
        info = sum(1 for a in advisories if a.severity == AdvisorySeverity.INFO)

        return AdvisoryPipelineResult(
            pipeline_id=run_id,
            execution_timestamp_utc=exec_ts,
            decision_context=context,
            policy_applied=active_policy,
            advisories=advisories,
            readiness_state=context.readiness,
            total_advisories=len(advisories),
            critical_count=crit,
            warning_count=warn,
            notice_count=notc,
            info_count=info,
        )

    def run_from_voyage(
        self,
        voyage_context: VoyageContext,
        engineering_inputs: Optional[EngineeringDecisionInputs] = None,
        policy: Optional[AdvisoryPolicy] = None,
        pipeline_id: Optional[str] = None,
        decision_context_id: Optional[str] = None,
    ) -> AdvisoryPipelineResult:
        """
        Constructs a DecisionContext from a VoyageContext and optional engineering inputs,
        then executes the advisory evaluation.
        """
        dc_builder = DecisionContextBuilder(decision_context_id=decision_context_id)
        dc_builder.set_voyage_context(voyage_context)
        if engineering_inputs is not None:
            dc_builder.set_engineering_inputs(engineering_inputs)
        
        decision_ctx = dc_builder.build()
        return self.run(context=decision_ctx, policy=policy, pipeline_id=pipeline_id)

    def run_from_telemetry(
        self,
        vessel: VesselContext,
        route: Route,
        position: VesselPosition,
        weather_provider: WeatherProvider,
        energy_state: Optional[VesselEnergyState] = None,
        timeline: Optional[VoyageTimeline] = None,
        engineering_inputs: Optional[EngineeringDecisionInputs] = None,
        policy: Optional[AdvisoryPolicy] = None,
        voyage_id: Optional[str] = None,
        pipeline_id: Optional[str] = None,
    ) -> AdvisoryPipelineResult:
        """
        Constructs a full VoyageContext using the provided WeatherProvider,
        builds a DecisionContext, and executes the complete advisory pipeline.
        """
        v_id = voyage_id or f"VOY_{vessel.vessel_id}_{int(datetime.now(timezone.utc).timestamp())}"
        builder = VoyageContextBuilder(voyage_id=v_id)
        builder.set_vessel(vessel)
        builder.set_route(route)
        builder.set_position(position)

        if timeline is not None:
            builder.set_timeline(timeline)
        if energy_state is not None:
            builder.set_energy_state(energy_state)

        # Enrich weather through the provider abstraction
        builder.enrich_weather_from_provider(weather_provider)
        voyage_ctx = builder.build()

        return self.run_from_voyage(
            voyage_context=voyage_ctx,
            engineering_inputs=engineering_inputs,
            policy=policy,
            pipeline_id=pipeline_id,
        )
