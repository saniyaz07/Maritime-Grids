"""
app/telemetry/adapter.py — Phase 10C.12 Telemetry Ingestion & Normalization Adapter
==================================================================================
Provides validation, range checking, quarantine of invalid measurements,
and normalization from external, provider, or simulated telemetry streams
into the CanonicalTelemetryPayload contract.

Key Invariants:
  - Strict validation: coordinates out of bounds, negative fuel, invalid SOC (>100%),
    and malformed timestamps are quarantined and marked INVALID/PARTIAL.
  - Zero fabrication: missing fields remain None (null != 0).
  - Engine state: strictly ON, OFF, or UNKNOWN.
  - Telemetry freshness is evaluated immediately upon adapter normalization.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple, Union

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


class TelemetryAdapter:
    """
    Adapter responsible for parsing, validating, and normalizing telemetry streams.
    """

    def __init__(
        self,
        fresh_threshold_sec: float = 60.0,
        stale_threshold_sec: float = 900.0,
        expired_threshold_sec: float = 3600.0,
    ) -> None:
        self.fresh_threshold_sec = fresh_threshold_sec
        self.stale_threshold_sec = stale_threshold_sec
        self.expired_threshold_sec = expired_threshold_sec


    def normalize(
        self,
        raw_payload: Dict[str, Any],
        default_source: str = "TELEMETRY_ADAPTER",
        default_mode: TelemetryProvenanceType = TelemetryProvenanceType.OBSERVED,
        reference_time_utc: Optional[Union[datetime, str]] = None,
    ) -> CanonicalTelemetryPayload:
        """
        Normalizes a raw telemetry dictionary into a CanonicalTelemetryPayload.
        Validates all inputs, records any validation anomalies, and sets appropriate quality states.
        """
        errors: List[str] = []

        # 1. Telemetry ID & Timestamp
        telemetry_id = str(raw_payload.get("telemetry_id") or f"TEL_{int(datetime.now(timezone.utc).timestamp() * 1000)}")
        raw_ts = raw_payload.get("timestamp_utc") or raw_payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
        ts_valid, normalized_ts = self._validate_timestamp(raw_ts)
        if not ts_valid:
            errors.append(f"Invalid timestamp format '{raw_ts}'")
            normalized_ts = datetime.now(timezone.utc).isoformat()

        # 2. Vessel ID
        vessel_id = str(raw_payload.get("vessel_id") or "UNKNOWN_VESSEL").strip()
        if not vessel_id:
            vessel_id = "UNKNOWN_VESSEL"
            errors.append("Missing vessel_id in telemetry payload")

        # 3. Position & Kinematics Extraction
        raw_pos = raw_payload.get("position") or raw_payload.get("vessel") or {}
        pos_telemetry, pos_errors = self._extract_position(raw_pos, raw_payload)
        errors.extend(pos_errors)

        # 4. Engine Extraction
        raw_engine = raw_payload.get("engine") or {}
        engine_telemetry, engine_errors = self._extract_engine(raw_engine, raw_payload)
        errors.extend(engine_errors)

        # 5. Energy Extraction
        raw_energy = raw_payload.get("energy") or {}
        energy_telemetry, energy_errors = self._extract_energy(raw_energy, raw_payload)
        errors.extend(energy_errors)

        # 6. Provenance Extraction
        raw_prov = raw_payload.get("provenance") or {}
        source_name = raw_prov.get("source") or default_source
        mode_str = str(raw_prov.get("mode") or default_mode.value).upper()
        try:
            mode = TelemetryProvenanceType(mode_str)
        except ValueError:
            mode = TelemetryProvenanceType.UNAVAILABLE
            errors.append(f"Unknown provenance mode '{mode_str}'")

        stream_id = raw_prov.get("stream_id") or raw_payload.get("stream_id")
        provenance = TelemetryProvenance(source=source_name, mode=mode, stream_id=stream_id)

        # 7. Quality Assessment
        quality_state = self._determine_quality(pos_telemetry, engine_telemetry, energy_telemetry, errors)
        quality = TelemetryQuality(
            overall=quality_state,
            freshness=TelemetryFreshnessState.FRESH,
            validation_errors=errors,
        )

        payload = CanonicalTelemetryPayload(
            telemetry_id=telemetry_id,
            timestamp_utc=normalized_ts,
            vessel_id=vessel_id,
            position=pos_telemetry,
            engine=engine_telemetry,
            energy=energy_telemetry,
            quality=quality,
            provenance=provenance,
        )

        # 8. Freshness evaluation
        payload.evaluate_freshness(
            current_time_utc=reference_time_utc,
            fresh_threshold_seconds=self.fresh_threshold_sec,
            stale_threshold_seconds=self.stale_threshold_sec,
            expired_threshold_seconds=self.expired_threshold_sec,
        )

        return payload

    def _validate_timestamp(self, ts_str: Any) -> Tuple[bool, str]:
        if not ts_str or not isinstance(ts_str, str):
            return False, ""
        try:
            clean = ts_str.strip()
            if clean.endswith("Z"):
                clean = clean[:-1] + "+00:00"
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return True, dt.isoformat()
        except Exception:
            return False, ""

    def _extract_position(self, pos_dict: Dict[str, Any], top: Dict[str, Any]) -> Tuple[PositionTelemetry, List[str]]:
        errors = []
        lat = pos_dict.get("latitude") if pos_dict.get("latitude") is not None else top.get("latitude")
        lon = pos_dict.get("longitude") if pos_dict.get("longitude") is not None else top.get("longitude")
        sog = pos_dict.get("speed_over_ground_knots") if pos_dict.get("speed_over_ground_knots") is not None else (
            pos_dict.get("speed_knots") if pos_dict.get("speed_knots") is not None else top.get("speed_knots")
        )
        cog = pos_dict.get("course_over_ground_deg") if pos_dict.get("course_over_ground_deg") is not None else (
            pos_dict.get("heading_deg") if pos_dict.get("heading_deg") is not None else top.get("heading_deg")
        )
        hdg = pos_dict.get("heading_deg") if pos_dict.get("heading_deg") is not None else top.get("heading_deg")

        # Range Validations
        valid_lat: Optional[float] = None
        if lat is not None:
            try:
                f_lat = float(lat)
                if -90.0 <= f_lat <= 90.0:
                    valid_lat = round(f_lat, 6)
                else:
                    errors.append(f"Latitude {f_lat} out of range [-90, 90]")
            except (ValueError, TypeError):
                errors.append(f"Invalid latitude value: {lat}")

        valid_lon: Optional[float] = None
        if lon is not None:
            try:
                f_lon = float(lon)
                if -180.0 <= f_lon <= 180.0:
                    valid_lon = round(f_lon, 6)
                else:
                    errors.append(f"Longitude {f_lon} out of range [-180, 180]")
            except (ValueError, TypeError):
                errors.append(f"Invalid longitude value: {lon}")

        valid_sog: Optional[float] = None
        if sog is not None:
            try:
                f_sog = float(sog)
                if 0.0 <= f_sog <= 100.0:
                    valid_sog = round(f_sog, 2)
                else:
                    errors.append(f"SOG {f_sog} out of physical range [0, 100] kn")
            except (ValueError, TypeError):
                errors.append(f"Invalid SOG value: {sog}")

        valid_cog: Optional[float] = None
        if cog is not None:
            try:
                f_cog = float(cog)
                if 0.0 <= f_cog <= 360.0:
                    valid_cog = round(f_cog % 360.0, 1)
                else:
                    errors.append(f"COG {f_cog} out of range [0, 360]")
            except (ValueError, TypeError):
                errors.append(f"Invalid COG value: {cog}")

        valid_hdg: Optional[float] = None
        if hdg is not None:
            try:
                f_hdg = float(hdg)
                if 0.0 <= f_hdg <= 360.0:
                    valid_hdg = round(f_hdg % 360.0, 1)
                else:
                    errors.append(f"Heading {f_hdg} out of range [0, 360]")
            except (ValueError, TypeError):
                errors.append(f"Invalid Heading value: {hdg}")

        pos = PositionTelemetry(
            latitude=valid_lat,
            longitude=valid_lon,
            speed_over_ground_knots=valid_sog,
            course_over_ground_deg=valid_cog,
            heading_deg=valid_hdg,
        )
        return pos, errors

    def _extract_engine(self, eng_dict: Dict[str, Any], top: Dict[str, Any]) -> Tuple[EngineTelemetry, List[str]]:
        errors = []
        raw_state = eng_dict.get("state") or top.get("engine_state")
        rpm = eng_dict.get("rpm") if eng_dict.get("rpm") is not None else top.get("engine_rpm")
        load = eng_dict.get("load_percent") if eng_dict.get("load_percent") is not None else (
            eng_dict.get("load_pct") if eng_dict.get("load_pct") is not None else top.get("engine_load_pct")
        )
        power = eng_dict.get("power_kw") if eng_dict.get("power_kw") is not None else top.get("engine_power_kw")
        fuel_rate = eng_dict.get("fuel_rate_lph") if eng_dict.get("fuel_rate_lph") is not None else top.get("engine_fuel_rate_lph")

        # Engine state mapping
        state = EngineOperationalState.UNKNOWN
        if raw_state is not None:
            s_clean = str(raw_state).strip().upper()
            if s_clean in ("ON", "RUNNING", "TRUE", "1"):
                state = EngineOperationalState.ON
            elif s_clean in ("OFF", "STOPPED", "FALSE", "0"):
                state = EngineOperationalState.OFF
            elif s_clean == "UNKNOWN":
                state = EngineOperationalState.UNKNOWN
            else:
                errors.append(f"Invalid engine state '{raw_state}'")
                state = EngineOperationalState.UNKNOWN

        valid_rpm: Optional[float] = None
        if rpm is not None:
            try:
                f_rpm = float(rpm)
                if 0.0 <= f_rpm <= 10000.0:
                    valid_rpm = round(f_rpm, 1)
                else:
                    errors.append(f"Engine RPM {f_rpm} out of range [0, 10000]")
            except (ValueError, TypeError):
                errors.append(f"Invalid RPM value: {rpm}")

        valid_load: Optional[float] = None
        if load is not None:
            try:
                f_load = float(load)
                if 0.0 <= f_load <= 100.0:
                    valid_load = round(f_load, 1)
                else:
                    errors.append(f"Engine Load {f_load}% out of range [0, 100]")
            except (ValueError, TypeError):
                errors.append(f"Invalid Engine Load value: {load}")

        valid_power: Optional[float] = None
        if power is not None:
            try:
                f_pwr = float(power)
                if f_pwr >= 0.0:
                    valid_power = round(f_pwr, 1)
                else:
                    errors.append(f"Engine Power cannot be negative: {f_pwr}")
            except (ValueError, TypeError):
                errors.append(f"Invalid Engine Power value: {power}")

        valid_fuel_rate: Optional[float] = None
        if fuel_rate is not None:
            try:
                f_fr = float(fuel_rate)
                if f_fr >= 0.0:
                    valid_fuel_rate = round(f_fr, 2)
                else:
                    errors.append(f"Engine fuel rate cannot be negative: {f_fr}")
            except (ValueError, TypeError):
                errors.append(f"Invalid engine fuel rate: {fuel_rate}")

        eng = EngineTelemetry(
            state=state,
            rpm=valid_rpm,
            load_percent=valid_load,
            power_kw=valid_power,
            fuel_rate_lph=valid_fuel_rate,
        )
        return eng, errors

    def _extract_energy(self, nrg_dict: Dict[str, Any], top: Dict[str, Any]) -> Tuple[EnergyTelemetry, List[str]]:
        errors = []
        fuel_rem = nrg_dict.get("fuel_remaining_liters") if nrg_dict.get("fuel_remaining_liters") is not None else (
            nrg_dict.get("fuel_remaining_l") if nrg_dict.get("fuel_remaining_l") is not None else top.get("fuel_remaining_liters")
        )
        fuel_rate = nrg_dict.get("fuel_rate_lph") if nrg_dict.get("fuel_rate_lph") is not None else (
            nrg_dict.get("fuel_consumption_rate_lph") if nrg_dict.get("fuel_consumption_rate_lph") is not None else top.get("fuel_consumption_rate_lph")
        )
        soc = nrg_dict.get("battery_soc_pct") if nrg_dict.get("battery_soc_pct") is not None else (
            nrg_dict.get("battery_soc_percent") if nrg_dict.get("battery_soc_percent") is not None else top.get("battery_soc_pct")
        )
        soh = nrg_dict.get("battery_soh_pct") if nrg_dict.get("battery_soh_pct") is not None else (
            nrg_dict.get("battery_soh_percent") if nrg_dict.get("battery_soh_percent") is not None else top.get("battery_soh_pct")
        )
        usable_kwh = nrg_dict.get("battery_usable_kwh") if nrg_dict.get("battery_usable_kwh") is not None else (
            nrg_dict.get("battery_energy_available_kwh") if nrg_dict.get("battery_energy_available_kwh") is not None else top.get("battery_energy_available_kwh")
        )
        batt_pwr = nrg_dict.get("battery_power_kw") if nrg_dict.get("battery_power_kw") is not None else top.get("battery_power_kw")
        solar_pwr = nrg_dict.get("solar_power_kw") if nrg_dict.get("solar_power_kw") is not None else top.get("solar_power_kw")

        valid_fuel_rem: Optional[float] = None
        if fuel_rem is not None:
            try:
                f_fr = float(fuel_rem)
                if f_fr >= 0.0:
                    valid_fuel_rem = round(f_fr, 1)
                else:
                    errors.append(f"Fuel remaining cannot be negative: {f_fr} L")
            except (ValueError, TypeError):
                errors.append(f"Invalid fuel remaining value: {fuel_rem}")

        valid_fuel_rate: Optional[float] = None
        if fuel_rate is not None:
            try:
                f_rate = float(fuel_rate)
                if f_rate >= 0.0:
                    valid_fuel_rate = round(f_rate, 2)
                else:
                    errors.append(f"Fuel rate cannot be negative: {f_rate} L/h")
            except (ValueError, TypeError):
                errors.append(f"Invalid fuel rate value: {fuel_rate}")

        valid_soc: Optional[float] = None
        if soc is not None:
            try:
                f_soc = float(soc)
                if 0.0 <= f_soc <= 100.0:
                    valid_soc = round(f_soc, 1)
                else:
                    errors.append(f"Battery SOC {f_soc}% out of valid range [0, 100]")
            except (ValueError, TypeError):
                errors.append(f"Invalid Battery SOC value: {soc}")

        valid_soh: Optional[float] = None
        if soh is not None:
            try:
                f_soh = float(soh)
                if 0.0 <= f_soh <= 100.0:
                    valid_soh = round(f_soh, 1)
                else:
                    errors.append(f"Battery SOH {f_soh}% out of valid range [0, 100]")
            except (ValueError, TypeError):
                errors.append(f"Invalid Battery SOH value: {soh}")

        valid_usable: Optional[float] = None
        if usable_kwh is not None:
            try:
                f_ukwh = float(usable_kwh)
                if f_ukwh >= 0.0:
                    valid_usable = round(f_ukwh, 1)
                else:
                    errors.append(f"Battery usable energy cannot be negative: {f_ukwh}")
            except (ValueError, TypeError):
                errors.append(f"Invalid usable battery kWh: {usable_kwh}")

        valid_batt_pwr: Optional[float] = None
        if batt_pwr is not None:
            try:
                valid_batt_pwr = round(float(batt_pwr), 2)
            except (ValueError, TypeError):
                errors.append(f"Invalid battery power: {batt_pwr}")

        valid_solar_pwr: Optional[float] = None
        if solar_pwr is not None:
            try:
                f_spwr = float(solar_pwr)
                if f_spwr >= 0.0:
                    valid_solar_pwr = round(f_spwr, 2)
                else:
                    errors.append(f"Solar power cannot be negative: {f_spwr}")
            except (ValueError, TypeError):
                errors.append(f"Invalid solar power: {solar_pwr}")

        nrg = EnergyTelemetry(
            fuel_remaining_liters=valid_fuel_rem,
            fuel_rate_lph=valid_fuel_rate,
            battery_soc_pct=valid_soc,
            battery_soh_pct=valid_soh,
            battery_usable_kwh=valid_usable,
            battery_power_kw=valid_batt_pwr,
            solar_power_kw=valid_solar_pwr,
        )
        return nrg, errors

    def _determine_quality(
        self,
        pos: PositionTelemetry,
        eng: EngineTelemetry,
        nrg: EnergyTelemetry,
        errors: List[str],
    ) -> TelemetryQualityState:
        if errors:
            # If critical physical errors occurred
            if any("out of range" in e or "cannot be negative" in e or "Invalid" in e for e in errors):
                return TelemetryQualityState.INVALID

        has_pos = pos.latitude is not None and pos.longitude is not None
        has_speed = pos.speed_over_ground_knots is not None
        has_energy = nrg.fuel_remaining_liters is not None or nrg.battery_soc_pct is not None

        if has_pos and has_speed and has_energy:
            return TelemetryQualityState.VALID
        elif has_pos or has_speed or has_energy or eng.state != EngineOperationalState.UNKNOWN:
            return TelemetryQualityState.PARTIAL
        else:
            return TelemetryQualityState.UNAVAILABLE
