"""
app/decision/context_builder.py — Phase 10C.4 Decision Context Builder
======================================================================
Fluent builder utility to assemble, validate, and compute readiness for
DecisionContext aggregates.

Key Invariants:
  - Validates underlying VoyageContext and EngineeringDecisionInputs.
  - Computes AdvisoryReadinessState deterministically.
  - Zero physics recalculation.
"""

from datetime import datetime, timezone
from typing import Optional

from app.voyage.contracts import VoyageContext
from app.decision.contracts import (
    AdvisoryReadinessState,
    DecisionContext,
    EngineeringDecisionInputs,
)


class DecisionContextBuilder:
    """
    Builder pattern implementation for assembling DecisionContext instances.
    """

    def __init__(self, decision_context_id: Optional[str] = None) -> None:
        self.decision_context_id = decision_context_id or f"DC_{int(datetime.now(timezone.utc).timestamp())}"
        self._voyage_context: Optional[VoyageContext] = None
        self._engineering_inputs: Optional[EngineeringDecisionInputs] = None
        self._created_at_utc: Optional[str] = None

    def set_id(self, decision_context_id: str) -> "DecisionContextBuilder":
        self.decision_context_id = decision_context_id
        return self

    def set_voyage_context(self, voyage_context: VoyageContext) -> "DecisionContextBuilder":
        self._voyage_context = voyage_context
        return self

    def set_engineering_inputs(self, engineering_inputs: EngineeringDecisionInputs) -> "DecisionContextBuilder":
        self._engineering_inputs = engineering_inputs
        return self

    def set_created_at_utc(self, timestamp_utc: str) -> "DecisionContextBuilder":
        self._created_at_utc = timestamp_utc
        return self

    def build(self) -> DecisionContext:
        """
        Validates components and builds the final DecisionContext.
        """
        if self._voyage_context is None:
            raise ValueError("VoyageContext must be provided to construct DecisionContext.")

        created_at = self._created_at_utc or datetime.now(timezone.utc).isoformat()

        return DecisionContext(
            decision_context_id=self.decision_context_id,
            created_at_utc=created_at,
            voyage_context=self._voyage_context,
            engineering_inputs=self._engineering_inputs,
        )
