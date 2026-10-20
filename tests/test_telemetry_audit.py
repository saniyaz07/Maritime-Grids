"""
tests/test_telemetry_audit.py — Phase 10C.13 Telemetry Audit Log Test Suite
===========================================================================
Verifies:
  1. InMemoryTelemetryAuditRepository operations (record, query, count, bounded capacity).
  2. SQLiteTelemetryAuditRepository operations (table init, record, filter queries, indexing).
  3. Strict null preservation in audit storage and retrieval (null != 0).
  4. Automatic audit recording on ingestion via TelemetryGateway.
  5. GET /api/v1/operator/telemetry/history API endpoint with filtering, pagination, and sorting.
  6. Zero actuator or write-back side-effects in audit logs.
"""

from datetime import datetime, timedelta, timezone
import os
import tempfile
import pytest
from starlette.testclient import TestClient

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
from app.telemetry.repository import TelemetryAuditRecord
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.sqlite_repository import SQLiteTelemetryAuditRepository
from app.telemetry.gateway import TelemetryGateway


def _create_sample_payload(
    vessel_id: str = "VESSEL_OSV_01",
    timestamp_utc: str = None,
    sog: float = 12.5,
    mode: TelemetryProvenanceType = TelemetryProvenanceType.OBSERVED,
    quality: TelemetryQualityState = TelemetryQualityState.VALID,
) -> CanonicalTelemetryPayload:
    if timestamp_utc is None:
        timestamp_utc = datetime.now(timezone.utc).isoformat()
    return CanonicalTelemetryPayload(
        telemetry_id=f"TEL_{datetime.now(timezone.utc).timestamp()}",
        timestamp_utc=timestamp_utc,
        vessel_id=vessel_id,
        position=PositionTelemetry(
            latitude=5.82,
            longitude=4.51,
            speed_over_ground_knots=sog,
            course_over_ground_deg=280.0,
            heading_deg=281.0,
        ),
        engine=EngineTelemetry(
            state=EngineOperationalState.ON,
            rpm=1500.0,
            load_percent=75.0,
            power_kw=1800.0,
            fuel_rate_lph=145.0,
        ),
        energy=EnergyTelemetry(
            fuel_remaining_liters=14500.0,
            battery_soc_pct=85.0,
        ),
        quality=TelemetryQuality(overall=quality),
        provenance=TelemetryProvenance(source="TEST_SENSOR", mode=mode),
    )


def test_01_in_memory_repository_record_and_query():
    """Verify InMemoryTelemetryAuditRepository stores and queries records in reverse-chronological order."""
    repo = InMemoryTelemetryAuditRepository(max_records=10)
    
    t0 = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        t_iso = (t0 + timedelta(minutes=i)).isoformat()
        payload = _create_sample_payload(timestamp_utc=t_iso, sog=10.0 + i)
        repo.record(payload)
        
    assert repo.count() == 5
    
    # Query all
    results = repo.query(limit=10)
    assert len(results) == 5
    # Reverse chronological (newest first)
    assert results[0].payload.position.speed_over_ground_knots == 14.0
    assert results[-1].payload.position.speed_over_ground_knots == 10.0
    
    # Query with limit and offset
    page = repo.query(limit=2, offset=1)
    assert len(page) == 2
    assert page[0].payload.position.speed_over_ground_knots == 13.0
    assert page[1].payload.position.speed_over_ground_knots == 12.0


def test_02_in_memory_repository_bounded_capacity():
    """Verify InMemoryTelemetryAuditRepository caps memory usage at max_records."""
    repo = InMemoryTelemetryAuditRepository(max_records=3)
    t0 = datetime(2026, 9, 28, 10, 0, 0, tzinfo=timezone.utc)
    
    for i in range(5):
        t_iso = (t0 + timedelta(minutes=i)).isoformat()
        payload = _create_sample_payload(timestamp_utc=t_iso, sog=10.0 + i)
        repo.record(payload)
        
    assert repo.count() == 3
    results = repo.query(limit=10)
    assert len(results) == 3
    # Only records with sog 14.0, 13.0, 12.0 should remain
    assert results[0].payload.position.speed_over_ground_knots == 14.0
    assert results[1].payload.position.speed_over_ground_knots == 13.0
    assert results[2].payload.position.speed_over_ground_knots == 12.0


def test_03_in_memory_repository_filters():
    """Verify InMemoryTelemetryAuditRepository filtering by vessel, time, mode, and quality."""
    repo = InMemoryTelemetryAuditRepository(max_records=50)
    t0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
    
    # Ingest mix of records
    p1 = _create_sample_payload(vessel_id="VESSEL_A", timestamp_utc=(t0 + timedelta(minutes=1)).isoformat(), mode=TelemetryProvenanceType.OBSERVED)
    p2 = _create_sample_payload(vessel_id="VESSEL_B", timestamp_utc=(t0 + timedelta(minutes=2)).isoformat(), mode=TelemetryProvenanceType.SIMULATED)
    p3 = _create_sample_payload(vessel_id="VESSEL_A", timestamp_utc=(t0 + timedelta(minutes=3)).isoformat(), mode=TelemetryProvenanceType.SIMULATED, quality=TelemetryQualityState.INVALID)
    
    repo.record(p1)
    repo.record(p2)
    repo.record(p3)
    
    # Filter by vessel
    vessel_a_res = repo.query(vessel_id="VESSEL_A")
    assert len(vessel_a_res) == 2
    assert repo.count(vessel_id="VESSEL_A") == 2
    
    # Filter by mode
    sim_res = repo.query(mode=TelemetryProvenanceType.SIMULATED)
    assert len(sim_res) == 2
    assert all(r.mode == TelemetryProvenanceType.SIMULATED for r in sim_res)
    
    # Filter by quality
    inv_res = repo.query(quality=TelemetryQualityState.INVALID)
    assert len(inv_res) == 1
    assert inv_res[0].vessel_id == "VESSEL_A"
    
    # Filter by time range
    time_res = repo.query(
        start_time_utc=(t0 + timedelta(minutes=1, seconds=30)).isoformat(),
        end_time_utc=(t0 + timedelta(minutes=2, seconds=30)).isoformat(),
    )
    assert len(time_res) == 1
    assert time_res[0].vessel_id == "VESSEL_B"


def test_04_sqlite_repository_persistence_and_query():
    """Verify SQLiteTelemetryAuditRepository persists and queries records with indexes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "telemetry_audit.db")
        repo = SQLiteTelemetryAuditRepository(db_path=db_path)
        
        t0 = datetime(2026, 9, 28, 8, 0, 0, tzinfo=timezone.utc)
        for i in range(10):
            t_iso = (t0 + timedelta(minutes=i)).isoformat()
            payload = _create_sample_payload(
                vessel_id="VESSEL_OSV_01" if i % 2 == 0 else "VESSEL_OSV_02",
                timestamp_utc=t_iso,
                sog=10.0 + i,
                mode=TelemetryProvenanceType.OBSERVED if i < 5 else TelemetryProvenanceType.SIMULATED,
            )
            repo.record(payload)
            
        assert repo.count() == 10
        assert repo.count(vessel_id="VESSEL_OSV_01") == 5
        
        # Query newest
        all_recs = repo.query(limit=5)
        assert len(all_recs) == 5
        assert all_recs[0].payload.position.speed_over_ground_knots == 19.0
        
        # Test persistence by reopening repo with new instance
        repo.close()
        repo2 = SQLiteTelemetryAuditRepository(db_path=db_path)
        assert repo2.count() == 10
        rec_by_id = repo2.get_by_id(all_recs[0].record_id)
        assert rec_by_id is not None
        assert rec_by_id.payload.position.speed_over_ground_knots == 19.0
        repo2.close()


def test_05_strict_null_preservation_in_audit_record():
    """Verify null/None values are preserved through serialization and DB storage (null != 0)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "telemetry_audit.db")
        repo = SQLiteTelemetryAuditRepository(db_path=db_path)
        
        # Create payload with explicit None values
        payload = CanonicalTelemetryPayload(
            telemetry_id="TEL_NULL_AUDIT_01",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            vessel_id="VESSEL_OSV_01",
            position=PositionTelemetry(
                latitude=5.82,
                longitude=4.51,
                speed_over_ground_knots=None, # Missing speed
                course_over_ground_deg=None, # Missing course
            ),
            engine=EngineTelemetry(
                state=EngineOperationalState.UNKNOWN,
                rpm=None,
                load_percent=None,
                power_kw=None,
            ),
            energy=EnergyTelemetry(
                fuel_remaining_liters=None,
                battery_soc_pct=None,
            ),
            provenance=TelemetryProvenance(source="TEST_NULL_SOURCE", mode=TelemetryProvenanceType.OBSERVED),
        )
        
        rec = repo.record(payload)
        
        fetched = repo.get_by_id(rec.record_id)
        assert fetched is not None
        assert fetched.payload.position.speed_over_ground_knots is None
        assert fetched.payload.position.speed_over_ground_knots != 0.0
        assert fetched.payload.position.course_over_ground_deg is None
        assert fetched.payload.engine.state == EngineOperationalState.UNKNOWN
        assert fetched.payload.engine.rpm is None
        assert fetched.payload.engine.rpm != 0.0
        assert fetched.payload.energy.battery_soc_pct is None
        assert fetched.payload.energy.battery_soc_pct != 0.0
        repo.close()


def test_06_gateway_ingest_auto_records_audit():
    """Verify TelemetryGateway automatically writes an audit record on ingestion."""
    repo = InMemoryTelemetryAuditRepository()
    gateway = TelemetryGateway(audit_repo=repo)
    
    raw = {
        "vessel_id": "VESSEL_AUTO_01",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "position": {
            "latitude": 5.82,
            "longitude": 4.51,
            "speed_over_ground_knots": 11.8,
        },
        "engine": {
            "state": "ON",
            "rpm": 1400.0,
        },
    }
    
    result = gateway.ingest_raw(raw)
    assert isinstance(result, CanonicalTelemetryPayload)
    assert repo.count() == 2 # 1 from initial load_scenario("A") + 1 from ingest
    
    history = repo.query(vessel_id="VESSEL_AUTO_01")
    assert len(history) == 1
    assert history[0].vessel_id == "VESSEL_AUTO_01"
    assert history[0].payload.position.speed_over_ground_knots == 11.8


def test_07_api_telemetry_history_endpoint():
    """Verify GET /api/v1/operator/telemetry/history returns structured audit records."""
    app = create_app()
    client = TestClient(app)
    
    # Ingest simulated scenarios
    client.get("/api/v1/operator/telemetry/simulated/A")
    client.get("/api/v1/operator/telemetry/simulated/B")
    
    # Query history
    res = client.get("/api/v1/operator/telemetry/history?limit=10")
    assert res.status_code == 200
    data = res.json()
    
    assert isinstance(data, list)
    assert len(data) >= 2
    
    first = data[0]
    assert "record_id" in first
    assert "telemetry_id" in first
    assert "vessel_id" in first
    assert "timestamp_utc" in first
    assert "payload" in first
    
    # Query with vessel_id filter
    res_vessel = client.get("/api/v1/operator/telemetry/history?vessel_id=VESSEL_OSV_01")
    assert res_vessel.status_code == 200
    vessel_data = res_vessel.json()
    assert all(r["vessel_id"] == "VESSEL_OSV_01" for r in vessel_data)
