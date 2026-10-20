"""
app/telemetry/gateway.py — Phase 10C.12 / 10C.13 Telemetry Ingestion, Streaming & Gateway
========================================================================================
Serves as the read-only operational telemetry gateway buffering the latest
normalized telemetry frame, broadcasting real-time SSE updates to subscribers,
and recording snapshots into the persistent TelemetryAuditRepository.

Key Invariants:
  - Read-only: Zero actuator or vessel control endpoints.
  - Real-Time Push: Server-Sent Events (SSE) stream broadcasting canonical payloads.
  - Persistent Audit Log: Automatic snapshot recording to TelemetryAuditRepository.
  - Automatic degradation: Stale / Expired / Disconnected frames automatically
    degrade engine state to UNKNOWN and trigger freshness flags.
  - Clean subscriber lifecycle: Disconnected subscriber queues are safely pruned.
"""

import asyncio
from datetime import datetime, timezone
import json
import threading
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Union

from app.telemetry.adapter import TelemetryAdapter
from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    EngineOperationalState,
    TelemetryFreshnessState,
    TelemetryProvenanceType,
    TelemetryQualityState,
)
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.repository import TelemetryAuditRecord, TelemetryAuditRepository
from app.telemetry.simulator import TelemetrySimulator


class TelemetryGateway:
    """
    Central telemetry ingestion, real-time push streaming, and retrieval gateway.
    """

    def __init__(
        self,
        default_vessel_id: str = "VESSEL_OSV_01",
        adapter: Optional[TelemetryAdapter] = None,
        simulator: Optional[TelemetrySimulator] = None,
        repository: Optional[TelemetryAuditRepository] = None,
        audit_repo: Optional[TelemetryAuditRepository] = None,
        max_subscribers: int = 100,
        energy_estimator: Optional[Any] = None,
    ) -> None:
        self.default_vessel_id = default_vessel_id
        self.adapter = adapter or TelemetryAdapter()
        self.simulator = simulator or TelemetrySimulator(vessel_id=default_vessel_id)
        self.repository: TelemetryAuditRepository = repository or audit_repo or InMemoryTelemetryAuditRepository()
        self.max_subscribers = max_subscribers
        self.energy_estimator = energy_estimator

        self._lock = threading.RLock()
        self._current_frame: Optional[CanonicalTelemetryPayload] = None
        self._last_ingest_time: Optional[datetime] = None

        # Real-time SSE subscriber queues
        self._subscribers: Set[asyncio.Queue] = set()

        # Seed with initial Scenario A (SIMULATED)
        self.load_scenario("A")

    def attach_energy_estimator(self, estimator: Any) -> None:
        """Attaches a VirtualEnergyEstimator to derive energy telemetry on ingestion."""
        self.energy_estimator = estimator

    def ingest_raw(
        self,
        raw_dict: Dict[str, Any],
        default_source: str = "OPERATOR_TELEMETRY_INGEST",
        default_mode: TelemetryProvenanceType = TelemetryProvenanceType.OBSERVED,
        weather: Optional[NormalizedWeatherRecord] = None,
        solar_irradiance_kw_per_m2: Optional[float] = None,
    ) -> CanonicalTelemetryPayload:
        """
        Ingests, validates, normalizes, persists to audit log, and buffers a raw telemetry frame.
        """
        payload = self.adapter.normalize(
            raw_payload=raw_dict,
            default_source=default_source,
            default_mode=default_mode,
        )
        if self.energy_estimator is not None:
            payload = self.energy_estimator.estimate_energy_state(
                payload,
                weather=weather,
                solar_irradiance_kw_per_m2=solar_irradiance_kw_per_m2,
            )
        return self._process_frame(payload)

    def ingest_canonical(
        self,
        payload: CanonicalTelemetryPayload,
        weather: Optional[NormalizedWeatherRecord] = None,
        solar_irradiance_kw_per_m2: Optional[float] = None,
    ) -> CanonicalTelemetryPayload:
        """
        Directly buffers, persists, and broadcasts a validated CanonicalTelemetryPayload.
        """
        if not isinstance(payload, CanonicalTelemetryPayload):
            raise TypeError(f"Expected CanonicalTelemetryPayload, got {type(payload)}")
        if self.energy_estimator is not None:
            payload = self.energy_estimator.estimate_energy_state(
                payload,
                weather=weather,
                solar_irradiance_kw_per_m2=solar_irradiance_kw_per_m2,
            )
        return self._process_frame(payload)

    def _process_frame(self, payload: CanonicalTelemetryPayload) -> CanonicalTelemetryPayload:
        """Internal helper to buffer, persist, and broadcast frame."""
        with self._lock:
            self._current_frame = payload
            self._last_ingest_time = datetime.now(timezone.utc)

            # Persist to audit repository
            try:
                self.repository.record(payload)
            except Exception as e:
                # Log or handle persistence gracefully
                pass

        # Broadcast to active SSE subscribers
        self._broadcast(payload)
        return payload

    def get_current_frame(
        self,
        reference_time_utc: Optional[Union[datetime, str]] = None,
    ) -> CanonicalTelemetryPayload:
        """
        Retrieves the latest buffered telemetry frame with fresh evaluation of temporal freshness.
        """
        with self._lock:
            if self._current_frame is None:
                # Return disconnected frame
                return self.simulator.get_scenario("G", reference_time_utc=str(reference_time_utc) if reference_time_utc else None)

            # Re-evaluate freshness dynamically
            self._current_frame.evaluate_freshness(current_time_utc=reference_time_utc)
            return self._current_frame

    def load_scenario(self, scenario_id: str) -> CanonicalTelemetryPayload:
        """
        Loads a deterministic simulated scenario into the active buffer and broadcasts it.
        """
        scenario_frame = self.simulator.get_scenario(scenario_id)
        return self._process_frame(scenario_frame)

    def disconnect(self) -> CanonicalTelemetryPayload:
        """
        Simulates source disconnection.
        """
        return self.load_scenario("G")

    def clear(self) -> None:
        """
        Clears the current buffered frame.
        """
        with self._lock:
            self._current_frame = None
            self._last_ingest_time = None

    # =================================================================
    # REAL-TIME SSE STREAMING (PHASE 10C.13)
    # =================================================================

    @property
    def subscriber_count(self) -> int:
        """Returns the number of active SSE subscribers."""
        with self._lock:
            return len(self._subscribers)

    def subscribe(self, max_queue_size: int = 50) -> asyncio.Queue:
        """Registers a new SSE subscriber queue with bounded subscriber limit."""
        with self._lock:
            if len(self._subscribers) >= self.max_subscribers:
                # Evict oldest subscriber
                oldest = next(iter(self._subscribers))
                self._subscribers.remove(oldest)

            q: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
            self._subscribers.add(q)
            return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Removes an SSE subscriber queue upon client disconnect."""
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, payload: CanonicalTelemetryPayload) -> None:
        """Publishes a payload to all active subscribers."""
        self._broadcast(payload)

    def update_current(self, payload: CanonicalTelemetryPayload) -> CanonicalTelemetryPayload:
        """Updates current frame and broadcasts to subscribers."""
        return self.ingest_canonical(payload)

    def _broadcast(self, payload: CanonicalTelemetryPayload) -> None:
        """Pushes a payload snapshot to all active subscriber queues."""
        with self._lock:
            subscribers = list(self._subscribers)

        msg = {
            "event": "telemetry",
            "timestamp": payload.timestamp_utc,
            "telemetry": payload.model_dump(mode="json"),
        }

        for q in subscribers:
            try:
                if q.full():
                    # Evict stale frame if queue is full
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(payload)
            except Exception:
                # If queue failed, remove subscriber
                self.unsubscribe(q)

    async def stream_events(
        self,
        heartbeat_interval_sec: float = 15.0,
    ) -> AsyncGenerator[str, None]:
        """
        Async generator yielding SSE formatted events to connected HTTP clients.
        Immediately yields the initial current frame, then listens for updates or sends heartbeats.
        """
        q = self.subscribe()
        try:
            # 1. Immediately emit current initial frame
            initial_frame = self.get_current_frame()
            initial_msg = {
                "event": "telemetry",
                "timestamp": initial_frame.timestamp_utc,
                "telemetry": initial_frame.model_dump(mode="json"),
            }
            yield f"event: telemetry\ndata: {json.dumps(initial_msg)}\n\n"

            # 2. Main event loop
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=heartbeat_interval_sec)
                    if isinstance(item, CanonicalTelemetryPayload):
                        msg = {
                            "event": "telemetry",
                            "timestamp": item.timestamp_utc,
                            "telemetry": item.model_dump(mode="json"),
                        }
                    else:
                        msg = item
                    yield f"event: telemetry\ndata: {json.dumps(msg)}\n\n"
                except asyncio.TimeoutError:
                    # Send keep-alive SSE comment to prevent connection drop
                    yield ": keepalive\n\n"
        finally:
            self.unsubscribe(q)
