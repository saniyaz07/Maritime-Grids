"""
app/pipeline — Phase 10C.6 End-to-End Advisory Pipeline
=========================================================
Orchestrates the end-to-end maritime decision support pipeline:
  WeatherProvider -> Normalized Weather -> VoyageContext -> DecisionContext -> AdvisoryEngine -> Structured Output
"""

from app.pipeline.advisory_pipeline import (
    AdvisoryPipeline,
    AdvisoryPipelineResult,
)

__all__ = [
    "AdvisoryPipeline",
    "AdvisoryPipelineResult",
]
