"""
app/telemetry — Phase 10C.12 / 10C.13 Telemetry Gateway & Streaming Package
===========================================================================
"""

from app.telemetry.contracts import (
    CanonicalTelemetryPayload,
    EngineOperationalState,
    EngineTelemetry,
    EnergyTelemetry,
    PositionTelemetry,
    TelemetryFreshnessState,
    TelemetryProvenance,
    TelemetryProvenanceType,
    TelemetryQuality,
    TelemetryQualityState,
)
from app.telemetry.adapter import TelemetryAdapter
from app.telemetry.simulator import TelemetrySimulator
from app.telemetry.gateway import TelemetryGateway
from app.telemetry.repository import TelemetryAuditRecord, TelemetryAuditRepository
from app.telemetry.memory_repository import InMemoryTelemetryAuditRepository
from app.telemetry.sqlite_repository import SQLiteTelemetryAuditRepository
from app.telemetry.nmea_adapter import (
    NMEAAdapter,
    NMEAUdpReceiver,
    calculate_nmea_checksum,
    validate_nmea_checksum,
    parse_nmea_latitude,
    parse_nmea_longitude,
    parse_nmea_timestamp,
)

from app.telemetry.energy_estimator import VirtualEnergyEstimator

__all__ = [
    "CanonicalTelemetryPayload",
    "EngineOperationalState",
    "EngineTelemetry",
    "EnergyTelemetry",
    "PositionTelemetry",
    "TelemetryFreshnessState",
    "TelemetryProvenance",
    "TelemetryProvenanceType",
    "TelemetryQuality",
    "TelemetryQualityState",
    "TelemetryAdapter",
    "TelemetrySimulator",
    "TelemetryGateway",
    "TelemetryAuditRecord",
    "TelemetryAuditRepository",
    "InMemoryTelemetryAuditRepository",
    "SQLiteTelemetryAuditRepository",
    "NMEAAdapter",
    "NMEAUdpReceiver",
    "VirtualEnergyEstimator",
    "calculate_nmea_checksum",
    "validate_nmea_checksum",
    "parse_nmea_latitude",
    "parse_nmea_longitude",
    "parse_nmea_timestamp",
]
