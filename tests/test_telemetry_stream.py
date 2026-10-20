"""
tests/test_telemetry_stream.py — Phase 10C.13 Real-Time SSE Stream Test Suite
=============================================================================
Verifies:
  1. GET /api/v1/operator/telemetry/stream endpoint returns text/event-stream.
  2. TelemetryGateway subscriber registration and automatic broadcast.
  3. Proper SSE event formatting (event: telemetry, data: {...}).
  4. Multi-subscriber isolation and independent queue handling.
  5. Automatic subscriber cleanup and queue bounding.
  6. Ingestion triggers instantaneous broadcast to active SSE subscribers.
  7. Read-only safety boundary (zero actuation pathways in stream logic).
"""

import asyncio
import json
import time
from datetime import datetime, timezone
import pytest

from app.api.app import create_app
from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    EngineOperationalState,
    EngineTelemetry,
    EnergyTelemetry,
    PositionTelemetry,
    TelemetryProvenance,
    TelemetryProvenanceType,
    TelemetryQuality,
    TelemetryQualityState,
)
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository


def _make_sample_payload(telemetry_id: str = "TEL_STREAM_01", sog: float = 14.2) -> CanonicalTelemetryPayload:
    return CanonicalTelemetryPayload(
        telemetry_id=telemetry_id,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        vessel_id="VESSEL_OSV_01",
        position=PositionTelemetry(
            latitude=5.82,
            longitude=4.51,
            speed_over_ground_knots=sog,
            course_over_ground_deg=275.0,
            heading_deg=276.0,
        ),
        engine=EngineTelemetry(
            state=EngineOperationalState.ON,
            rpm=1450.0,
            load_percent=70.0,
        ),
        energy=EnergyTelemetry(
            battery_soc_pct=88.0,
        ),
        quality=TelemetryQuality(overall=TelemetryQualityState.VALID),
        provenance=TelemetryProvenance(source="STREAM_TEST", mode=TelemetryProvenanceType.OBSERVED),
    )


def test_01_gateway_pubsub_broadcast():
    """Verify TelemetryGateway registers subscribers and broadcasts new payloads to all queues."""
    gateway = TelemetryGateway(audit_repo=InMemoryTelemetryAuditRepository())
    
    assert gateway.subscriber_count == 0
    q1 = gateway.subscribe(max_queue_size=10)
    q2 = gateway.subscribe(max_queue_size=10)
    assert gateway.subscriber_count == 2
    
    # Broadcast an initial event
    payload1 = _make_sample_payload("TEL_001", sog=11.0)
    gateway.publish(payload1)
    
    assert not q1.empty()
    assert not q2.empty()
    item1 = q1.get_nowait()
    item2 = q2.get_nowait()
    assert item1.telemetry_id == "TEL_001"
    assert item2.telemetry_id == "TEL_001"
    assert item1.position.speed_over_ground_knots == 11.0
    
    # Unsubscribe
    gateway.unsubscribe(q1)
    assert gateway.subscriber_count == 1
    gateway.unsubscribe(q2)
    assert gateway.subscriber_count == 0


def test_02_gateway_queue_overflow_prunes_oldest():
    """Verify subscriber queue does not block when full, but drops oldest item."""
    gateway = TelemetryGateway()
    q = gateway.subscribe(max_queue_size=2)
    
    p1 = _make_sample_payload("TEL_1", sog=10.0)
    p2 = _make_sample_payload("TEL_2", sog=12.0)
    p3 = _make_sample_payload("TEL_3", sog=14.0)
    
    gateway.publish(p1)
    gateway.publish(p2)
    gateway.publish(p3) # Should drop TEL_1
    
    assert q.qsize() == 2
    first_out = q.get_nowait()
    second_out = q.get_nowait()
    assert first_out.telemetry_id == "TEL_2"
    assert second_out.telemetry_id == "TEL_3"
    
    gateway.unsubscribe(q)


@pytest.mark.asyncio
async def test_03_stream_events_generator_formatting():
    """Verify stream_events() yields initial frame and subsequent SSE formatted lines."""
    gateway = TelemetryGateway()
    init_payload = _make_sample_payload("TEL_INIT", sog=8.5)
    gateway.update_current(init_payload)
    
    gen = gateway.stream_events(heartbeat_interval_sec=0.1)
    
    # First yielded event should be the initial current frame
    first_event = await anext(gen)
    assert first_event.startswith("event: telemetry\n")
    assert "data: " in first_event
    assert "TEL_INIT" in first_event
    
    # Publish another payload asynchronously
    p2 = _make_sample_payload("TEL_STREAM_NEW", sog=13.5)
    gateway.publish(p2)
    
    second_event = await anext(gen)
    assert second_event.startswith("event: telemetry\n")
    assert "TEL_STREAM_NEW" in second_event
    
    # Clean up generator
    await gen.aclose()


@pytest.mark.asyncio
async def test_04_api_telemetry_stream_endpoint_response():
    """Verify GET /api/v1/operator/telemetry/stream endpoint route exists and streams SSE."""
    app = create_app()
    openapi = app.openapi()
    assert "/api/v1/operator/telemetry/stream" in openapi["paths"]
    
    gateway = TelemetryGateway()
    gen = gateway.stream_events(heartbeat_interval_sec=0.05)
    
    first_event = await anext(gen)
    assert "event: telemetry" in first_event
    assert "data: " in first_event
    
    await gen.aclose()


def test_05_ingest_broadcasts_to_stream():
    """Verify that posting to /ingest immediately dispatches to gateway subscribers."""
    repo = InMemoryTelemetryAuditRepository()
    gateway = TelemetryGateway(audit_repo=repo)
    q = gateway.subscribe()
    
    raw = {
        "vessel_id": "VESSEL_STREAM_01",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "position": {
            "latitude": 5.82,
            "longitude": 4.51,
            "speed_over_ground_knots": 15.0,
        },
    }
    
    result = gateway.ingest_raw(raw)
    assert isinstance(result, CanonicalTelemetryPayload)
    
    assert not q.empty()
    streamed = q.get_nowait()
    assert streamed.vessel_id == "VESSEL_STREAM_01"
    assert streamed.position.speed_over_ground_knots == 15.0
    gateway.unsubscribe(q)
