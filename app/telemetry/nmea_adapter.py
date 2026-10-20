"""
app/telemetry/nmea_adapter.py — Phase 10C.13B NMEA 0183 Virtual Vessel Adapter
=============================================================================
Provides NMEA 0183 sentence parsing, checksum validation, coordinate conversion,
and state aggregation for Bridge Command 5.x virtual vessel simulation telemetry.

Key Invariants:
  - Strict checksum validation: XOR between '$' and '*' must match hex digits.
  - Accurate coordinate conversion: DDMM.MMMM / DDDMM.MMMM to decimal degrees.
  - Strict null semantics: null != 0 (missing or unmeasured fields remain None).
  - No engine inference: engine state remains UNKNOWN and RPM/fuel remain None.
  - Provenance: mode is strictly SIMULATED, source is 'BRIDGE_COMMAND_NMEA'.
  - Thread-safe UDP datagram receiver with graceful shutdown.
  - Zero actuator or control commands (one-way Simulator -> Maritime Grids only).
"""

from datetime import datetime, date, timezone
import math
import os
import re
import socket
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

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
from app.telemetry.gateway import TelemetryGateway


# =====================================================================
# 1. NMEA CHECKSUM & UTILITY FUNCTIONS
# =====================================================================

def calculate_nmea_checksum(sentence_body: str) -> str:
    """
    Calculates the 2-character hexadecimal XOR checksum of the sentence body
    (characters between '$' and '*').
    """
    csum = 0
    for char in sentence_body:
        csum ^= ord(char)
    return f"{csum:02X}"


def validate_nmea_checksum(raw_sentence: str) -> Tuple[bool, str, Optional[str], Optional[str]]:
    """
    Validates the NMEA 0183 checksum of a raw sentence.

    Returns:
        Tuple of (is_valid, error_msg, sentence_body, expected_checksum)
    """
    cleaned = raw_sentence.strip()
    if not cleaned:
        return False, "Empty NMEA sentence", None, None

    if not (cleaned.startswith("$") or cleaned.startswith("!")):
        return False, f"NMEA sentence must start with '$' or '!': '{cleaned[:10]}'", None, None

    if "*" not in cleaned:
        return False, f"Missing checksum delimiter '*' in sentence: '{cleaned}'", None, None

    parts = cleaned[1:].split("*", 1)
    body = parts[0]
    received_checksum = parts[1].strip()

    if len(received_checksum) < 2:
        return False, f"Malformed checksum '{received_checksum}' in sentence: '{cleaned}'", body, None

    expected_checksum = calculate_nmea_checksum(body)
    recv_hex = received_checksum[:2].upper()

    if recv_hex != expected_checksum:
        return False, f"Checksum mismatch: received '{recv_hex}', calculated '{expected_checksum}'", body, expected_checksum

    return True, "", body, expected_checksum


def parse_nmea_latitude(lat_str: str, hemisphere: str) -> Optional[float]:
    """
    Converts NMEA latitude (DDMM.MMMM or DDMM.MM) to signed decimal degrees.
    Hemisphere: 'N' -> positive, 'S' -> negative.
    """
    lat_str = lat_str.strip()
    hemi = hemisphere.strip().upper()
    if not lat_str or not hemi:
        return None

    try:
        val = float(lat_str)
        deg = int(val / 100)
        minutes = val - (deg * 100)
        decimal = deg + (minutes / 60.0)

        if hemi == "S":
            decimal = -decimal
        elif hemi != "N":
            return None

        if -90.0 <= decimal <= 90.0:
            return round(decimal, 7)
        return None
    except (ValueError, TypeError):
        return None


def parse_nmea_longitude(lon_str: str, hemisphere: str) -> Optional[float]:
    """
    Converts NMEA longitude (DDDMM.MMMM or DDDMM.MM) to signed decimal degrees.
    Hemisphere: 'E' -> positive, 'W' -> negative.
    """
    lon_str = lon_str.strip()
    hemi = hemisphere.strip().upper()
    if not lon_str or not hemi:
        return None

    try:
        val = float(lon_str)
        deg = int(val / 100)
        minutes = val - (deg * 100)
        decimal = deg + (minutes / 60.0)

        if hemi == "W":
            decimal = -decimal
        elif hemi != "E":
            return None

        if -180.0 <= decimal <= 180.0:
            return round(decimal, 7)
        return None
    except (ValueError, TypeError):
        return None


def parse_nmea_timestamp(time_str: str, date_str: Optional[str] = None, ref_date: Optional[date] = None) -> Optional[str]:
    """
    Combines NMEA time (hhmmss or hhmmss.ss) and optional date (ddmmyy) into a normalized UTC ISO 8601 string.
    """
    time_str = (time_str or "").strip()
    if not time_str or len(time_str) < 6:
        return None

    try:
        hour = int(time_str[0:2])
        minute = int(time_str[2:4])
        second_part = float(time_str[4:])
        second = int(second_part)
        microsecond = int(round((second_part - second) * 1_000_000))

        if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 60):
            return None

        d_str = (date_str or "").strip()
        if d_str and len(d_str) == 6:
            day = int(d_str[0:2])
            month = int(d_str[2:4])
            yy = int(d_str[4:6])
            year = 2000 + yy if yy < 80 else 1900 + yy
            d = date(year, month, day)
        elif d_str and len(d_str) == 8:
            if d_str.startswith("19") or d_str.startswith("20"):
                year = int(d_str[0:4])
                month = int(d_str[4:6])
                day = int(d_str[6:8])
            else:
                day = int(d_str[0:2])
                month = int(d_str[2:4])
                year = int(d_str[4:8])
            d = date(year, month, day)
        elif ref_date is not None:
            d = ref_date
        else:
            d = datetime.now(timezone.utc).date()

        dt = datetime(d.year, d.month, d.day, hour, minute, min(second, 59), microsecond, tzinfo=timezone.utc)
        return dt.isoformat()
    except (ValueError, TypeError):
        return None


# =====================================================================
# 2. NMEA 0183 ADAPTER & STATE AGGREGATOR
# =====================================================================

class NMEAAdapter:
    """
    NMEA 0183 virtual vessel telemetry adapter.
    Parses RMC, GGA, HDT sentences, validates bounds, preserves nulls,
    and aggregates latest vessel navigation state.
    """

    def __init__(
        self,
        vessel_id: str = "VESSEL_OSV_01",
        source_name: str = "BRIDGE_COMMAND_NMEA",
    ) -> None:
        self.vessel_id = vessel_id
        self.source_name = source_name
        self._lock = threading.RLock()

        # Aggregated telemetry state
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None
        self._sog_knots: Optional[float] = None
        self._cog_deg: Optional[float] = None
        self._heading_deg: Optional[float] = None
        self._timestamp_utc: Optional[str] = None
        self._nav_status_valid: bool = False
        self._fix_quality: int = 0
        self._satellites: Optional[int] = None
        self._validation_errors: List[str] = []
        self._last_sentence_type: Optional[str] = None

    def parse_sentence(self, raw_sentence: str, ref_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Parses a single NMEA sentence string after verifying checksum.

        Returns:
            Dictionary containing parsed fields and validation status.
        """
        is_valid, err_msg, body, _ = validate_nmea_checksum(raw_sentence)
        if not is_valid:
            return {"valid": False, "type": "UNKNOWN", "error": err_msg, "raw": raw_sentence}

        fields = body.split(",")
        talker_type = fields[0].upper()
        # Extract sentence type e.g. GPRMC -> RMC
        sentence_type = talker_type[-3:] if len(talker_type) >= 3 else talker_type

        res: Dict[str, Any] = {
            "valid": True,
            "type": sentence_type,
            "talker": talker_type,
            "error": None,
            "raw": raw_sentence,
        }

        if sentence_type == "RMC":
            # $--RMC,hhmmss.ss,A,llll.ll,a,yyyyy.yy,a,x.x,x.x,ddmmyy,x.x,a,m*hh
            if len(fields) < 10:
                res["valid"] = False
                res["error"] = f"RMC sentence has insufficient fields ({len(fields)} < 10)"
                return res

            time_str = fields[1]
            status = fields[2].upper()
            lat_str = fields[3]
            lat_hemi = fields[4]
            lon_str = fields[5]
            lon_hemi = fields[6]
            sog_str = fields[7]
            cog_str = fields[8]
            date_str = fields[9]

            nav_valid = (status == "A")
            res["nav_status"] = "VALID" if nav_valid else "WARNING_VOID"
            res["status_char"] = status
            res["timestamp_utc"] = parse_nmea_timestamp(time_str, date_str, ref_date)

            if nav_valid:
                res["latitude"] = parse_nmea_latitude(lat_str, lat_hemi)
                res["longitude"] = parse_nmea_longitude(lon_str, lon_hemi)
            else:
                res["latitude"] = None
                res["longitude"] = None
                res["error"] = "RMC navigation status is 'V' (Warning/Void)"

            try:
                res["speed_over_ground_knots"] = float(sog_str) if sog_str else None
            except ValueError:
                res["speed_over_ground_knots"] = None

            try:
                res["course_over_ground_deg"] = float(cog_str) % 360.0 if cog_str else None
            except ValueError:
                res["course_over_ground_deg"] = None

        elif sentence_type == "GGA":
            # $--GGA,hhmmss.ss,llll.ll,a,yyyyy.yy,a,x,xx,x.x,x.x,M,x.x,M,x.x,xxxx*hh
            if len(fields) < 8:
                res["valid"] = False
                res["error"] = f"GGA sentence has insufficient fields ({len(fields)} < 8)"
                return res

            time_str = fields[1]
            lat_str = fields[2]
            lat_hemi = fields[3]
            lon_str = fields[4]
            lon_hemi = fields[5]
            fix_qual_str = fields[6]
            sats_str = fields[7]

            try:
                fix_qual = int(fix_qual_str) if fix_qual_str else 0
            except ValueError:
                fix_qual = 0

            try:
                sats = int(sats_str) if sats_str else None
            except ValueError:
                sats = None

            res["fix_quality"] = fix_qual
            res["satellites"] = sats
            res["timestamp_utc"] = parse_nmea_timestamp(time_str, None, ref_date)

            if fix_qual > 0:
                res["latitude"] = parse_nmea_latitude(lat_str, lat_hemi)
                res["longitude"] = parse_nmea_longitude(lon_str, lon_hemi)
            else:
                res["latitude"] = None
                res["longitude"] = None
                res["error"] = f"GGA fix quality is {fix_qual} (Invalid)"

        elif sentence_type == "HDT" or sentence_type == "HDG":
            # $--HDT,x.x,T*hh
            if len(fields) < 2:
                res["valid"] = False
                res["error"] = "HDT sentence missing heading field"
                return res

            hdg_str = fields[1]
            try:
                res["heading_deg"] = float(hdg_str) % 360.0 if hdg_str else None
            except ValueError:
                res["heading_deg"] = None
                res["error"] = f"Invalid heading value '{hdg_str}'"

        elif sentence_type == "VTG":
            # $--VTG,x.x,T,x.x,M,x.x,N,x.x,K,a*hh
            if len(fields) < 6:
                res["valid"] = False
                res["error"] = f"VTG sentence has insufficient fields ({len(fields)} < 6)"
                return res

            cog_str = fields[1]
            sog_str = fields[5]

            try:
                res["course_over_ground_deg"] = float(cog_str) % 360.0 if cog_str else None
            except ValueError:
                res["course_over_ground_deg"] = None

            try:
                res["speed_over_ground_knots"] = float(sog_str) if sog_str else None
            except ValueError:
                res["speed_over_ground_knots"] = None

        return res

    def update_from_sentence(
        self,
        raw_sentence: str,
        ref_date: Optional[date] = None,
        ingested_at_utc: Optional[str] = None,
    ) -> Optional[CanonicalTelemetryPayload]:
        """
        Processes a raw NMEA sentence, updates aggregated state, and returns
        the latest CanonicalTelemetryPayload.
        """
        parsed = self.parse_sentence(raw_sentence, ref_date=ref_date)
        with self._lock:
            self._validation_errors = []
            if not parsed.get("valid"):
                if parsed.get("error"):
                    self._validation_errors.append(parsed["error"])
                return None

            stype = parsed.get("type")
            self._last_sentence_type = stype

            if stype == "RMC":
                if parsed.get("timestamp_utc"):
                    self._timestamp_utc = parsed["timestamp_utc"]
                if parsed.get("status_char") == "A":
                    self._nav_status_valid = True
                    if parsed.get("latitude") is not None:
                        self._latitude = parsed["latitude"]
                    if parsed.get("longitude") is not None:
                        self._longitude = parsed["longitude"]
                    if parsed.get("speed_over_ground_knots") is not None:
                        self._sog_knots = parsed["speed_over_ground_knots"]
                    if parsed.get("course_over_ground_deg") is not None:
                        self._cog_deg = parsed["course_over_ground_deg"]
                else:
                    self._nav_status_valid = False
                    self._validation_errors.append("RMC navigation status is 'V' (Warning/Void)")

            elif stype == "GGA":
                if parsed.get("timestamp_utc") and not self._timestamp_utc:
                    self._timestamp_utc = parsed["timestamp_utc"]
                self._fix_quality = parsed.get("fix_quality", 0)
                self._satellites = parsed.get("satellites")
                if self._fix_quality > 0:
                    if parsed.get("latitude") is not None:
                        self._latitude = parsed["latitude"]
                    if parsed.get("longitude") is not None:
                        self._longitude = parsed["longitude"]
                else:
                    self._validation_errors.append(f"GGA fix quality is {self._fix_quality}")

            elif stype in ("HDT", "HDG"):
                if parsed.get("heading_deg") is not None:
                    self._heading_deg = parsed["heading_deg"]

            elif stype == "VTG":
                if parsed.get("course_over_ground_deg") is not None:
                    self._cog_deg = parsed["course_over_ground_deg"]
                if parsed.get("speed_over_ground_knots") is not None:
                    self._sog_knots = parsed["speed_over_ground_knots"]

            return self.get_canonical_payload(ingested_at_utc=ingested_at_utc)

    def get_canonical_payload(self, ingested_at_utc: Optional[str] = None) -> CanonicalTelemetryPayload:
        """
        Constructs a strongly-typed CanonicalTelemetryPayload from current aggregated state.
        Preserves strict null semantics (null != 0) and UNKNOWN engine state.
        """
        with self._lock:
            now_iso = datetime.now(timezone.utc).isoformat()
            ts = self._timestamp_utc or now_iso
            ingest_ts = ingested_at_utc or now_iso
            has_pos = (self._latitude is not None and self._longitude is not None)

            # Quality classification
            if has_pos and self._nav_status_valid:
                qual_state = TelemetryQualityState.VALID
            elif has_pos:
                qual_state = TelemetryQualityState.PARTIAL
            else:
                qual_state = TelemetryQualityState.DEGRADED

            position = PositionTelemetry(
                latitude=self._latitude,
                longitude=self._longitude,
                speed_over_ground_knots=self._sog_knots,
                course_over_ground_deg=self._cog_deg,
                heading_deg=self._heading_deg,
            )

            # Strict Invariant: Do NOT infer engine state from position / speed!
            engine = EngineTelemetry(
                state=EngineOperationalState.UNKNOWN,
                rpm=None,
                load_percent=None,
                power_kw=None,
                fuel_rate_lph=None,
            )

            # Strict Invariant: Unmeasured energy fields remain None
            energy = EnergyTelemetry(
                fuel_remaining_liters=None,
                fuel_rate_lph=None,
                battery_soc_pct=None,
                battery_soh_pct=None,
                battery_usable_kwh=None,
                solar_power_kw=None,
            )

            provenance = TelemetryProvenance(
                source=self.source_name,
                mode=TelemetryProvenanceType.SIMULATED,
                stream_id="NMEA_0183_BRIDGE_COMMAND",
            )

            quality = TelemetryQuality(
                overall=qual_state,
                freshness=TelemetryFreshnessState.FRESH,
                validation_errors=list(self._validation_errors),
            )

            payload = CanonicalTelemetryPayload(
                telemetry_id=f"TEL_NMEA_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
                timestamp_utc=ts,
                ingested_at_utc=ingest_ts,
                vessel_id=self.vessel_id,
                position=position,
                engine=engine,
                energy=energy,
                quality=quality,
                provenance=provenance,
            )

            payload.evaluate_freshness(current_time_utc=ingest_ts)
            return payload

    def feed_stream(
        self,
        sentences: List[str],
        ref_date: Optional[date] = None,
        ingested_at_utc: Optional[str] = None,
    ) -> List[CanonicalTelemetryPayload]:
        """
        Feeds a list of NMEA sentences sequentially and returns list of generated payloads.
        """
        payloads = []
        for s in sentences:
            p = self.update_from_sentence(s, ref_date=ref_date, ingested_at_utc=ingested_at_utc)
            if p is not None:
                payloads.append(p)
        return payloads


# =====================================================================
# 3. NMEA UDP INGESTION RECEIVER
# =====================================================================

class NMEAUdpReceiver:
    """
    Non-blocking / threaded UDP receiver listening for NMEA 0183 datagram broadcasts
    from Bridge Command or other maritime simulators.
    """

    def __init__(
        self,
        gateway: Optional[TelemetryGateway] = None,
        adapter: Optional[NMEAAdapter] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        self.gateway = gateway
        self.adapter = adapter or NMEAAdapter()
        self.host = host or os.environ.get("NMEA_UDP_HOST", "127.0.0.1")
        self.port = int(port if port is not None else os.environ.get("NMEA_UDP_PORT", 10110))

        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._packets_received = 0
        self._sentences_processed = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def packets_received(self) -> int:
        return self._packets_received

    @property
    def sentences_processed(self) -> int:
        return self._sentences_processed

    def start(self) -> None:
        """Starts the UDP receiver in a background daemon thread."""
        if self._running:
            return

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.settimeout(0.5)

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="NMEAUdpReceiver")
        self._thread.start()

    def stop(self) -> None:
        """Stops the UDP receiver and closes socket."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def process_datagram(self, data: bytes) -> List[CanonicalTelemetryPayload]:
        """
        Processes a raw bytes datagram containing one or more newline-delimited NMEA sentences.
        """
        self._packets_received += 1
        ingest_ts = datetime.now(timezone.utc).isoformat()
        text = data.decode("ascii", errors="ignore")
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        payloads = []
        for line in lines:
            if line.startswith("$") or line.startswith("!"):
                self._sentences_processed += 1
                payload = self.adapter.update_from_sentence(line, ingested_at_utc=ingest_ts)
                if payload:
                    payloads.append(payload)
                    if self.gateway:
                        self.gateway.ingest_canonical(payload)
        return payloads

    def _listen_loop(self) -> None:
        """Background socket polling loop."""
        while self._running and self._socket:
            try:
                data, _ = self._socket.recvfrom(4096)
                if data:
                    self.process_datagram(data)
            except socket.timeout:
                continue
            except Exception:
                if not self._running:
                    break
