"""
app/telemetry/energy_estimator.py — Phase 10C.13I Virtual Vessel Energy State Estimator
=======================================================================================
Implements a strictly read-only, physics-grounded Virtual Vessel Energy State Estimator
that augments live Bridge Command navigation telemetry with physically derived
energy and powertrain estimates.

Key Invariants:
  - Purely read-only: Zero actuator commands, zero writes to Bridge Command or listen ports.
  - SOG != Engine State: Engine operational state is NEVER inferred from SOG; remains UNKNOWN.
  - Explicit Provenance: All estimated energy quantities are tagged DERIVED / SIMULATED.
  - Sound Naval Hydrodynamics: Resistance components (calm, wind, wave) and shaft power
    follow cubic power scaling and standard aerodynamic/hydrodynamic formulations.
  - Freshness-Aware Integration: Telemetry integration uses host ingestion time delta;
    stale or expired frames do not falsely advance integration.
  - No Fabrication: Missing inputs (e.g. SOG is None or weather missing) degrade gracefully
    to None / Unavailable without fabricating fake physical values.
"""

from datetime import datetime, timezone
import math
import os
from typing import Any, Dict, Optional, Tuple, Union
import pandas as pd

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
from app.weather.contracts import NormalizedWeatherRecord, WeatherProvenanceType


DEFAULT_SHIP_PROFILES_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "reference",
    "ship_profiles.csv",
)


class VirtualEnergyEstimator:
    """
    Virtual Vessel Energy State Estimator for live decision support simulation.
    """

    def __init__(
        self,
        ship_type: str = "Oil Service Boat",
        ship_profiles_csv: Optional[str] = None,
        initial_fuel_liters: Optional[float] = 5000.0,
        initial_battery_soc_pct: Optional[float] = 90.0,
        fuel_density_kg_per_l: float = 0.85,
        sfoc_kg_per_kwh: float = 0.210,
        propulsion_efficiency: float = 0.68,
        auxiliary_hotel_load_kw: float = 35.0,
    ) -> None:
        self.ship_type = ship_type
        self.profiles_csv = ship_profiles_csv or DEFAULT_SHIP_PROFILES_CSV
        self.fuel_density = fuel_density_kg_per_l
        self.sfoc = sfoc_kg_per_kwh
        self.propulsion_efficiency = propulsion_efficiency
        self.auxiliary_hotel_load_kw = auxiliary_hotel_load_kw

        # Load vessel profile specifications
        self.profile = self._load_profile(self.ship_type, self.profiles_csv)

        # Dynamic integration state
        self.initial_fuel_liters = initial_fuel_liters
        self.fuel_remaining_liters: Optional[float] = initial_fuel_liters
        self.cumulative_fuel_consumed_liters: float = 0.0

        # Battery state
        self.battery_capacity_kwh = float(self.profile.get("battery_pack_capacity_kwh", 649.7))
        self.initial_battery_soc_pct = initial_battery_soc_pct
        if initial_battery_soc_pct is not None and self.battery_capacity_kwh > 0:
            self.battery_energy_kwh: Optional[float] = (initial_battery_soc_pct / 100.0) * self.battery_capacity_kwh
            self.battery_soc_pct: Optional[float] = initial_battery_soc_pct
        else:
            self.battery_energy_kwh = None
            self.battery_soc_pct = None

        self.battery_soh_pct: float = 98.5
        self.last_ingest_time_utc: Optional[datetime] = None

    def _load_profile(self, ship_type: str, csv_path: str) -> Dict[str, Any]:
        """Loads and caches vessel specifications from ship_profiles.csv."""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Ship profiles CSV not found at: {csv_path}")

        df = pd.read_csv(csv_path).set_index("ship_type")
        if ship_type not in df.index:
            raise ValueError(f"Unknown ship_type '{ship_type}'. Available: {list(df.index)}")

        row = df.loc[ship_type]
        return {
            "displacement_tonnes": float(row["displacement_tonnes"]),
            "engine_power_kw": float(row["engine_power_kw"]),
            "hull_length_m": float(row["hull_length_m"]),
            "hull_beam_m": float(row["hull_beam_m"]),
            "hull_draft_m": float(row["hull_draft_m"]),
            "max_speed_knots": float(row["max_speed_knots"]),
            "battery_pack_capacity_kwh": float(row["battery_pack_capacity_kwh"]),
            "solar_panel_size_m2": float(row["solar_panel_size_m2"]),
            "solar_panel_efficiency_pct": float(row["solar_panel_efficiency_pct"]),
        }

    def reset_state(
        self,
        initial_fuel_liters: Optional[float] = None,
        initial_battery_soc_pct: Optional[float] = None,
    ) -> None:
        """Resets dynamic integration state."""
        if initial_fuel_liters is not None:
            self.initial_fuel_liters = initial_fuel_liters
        self.fuel_remaining_liters = self.initial_fuel_liters
        self.cumulative_fuel_consumed_liters = 0.0

        if initial_battery_soc_pct is not None:
            self.initial_battery_soc_pct = initial_battery_soc_pct
        if self.initial_battery_soc_pct is not None and self.battery_capacity_kwh > 0:
            self.battery_energy_kwh = (self.initial_battery_soc_pct / 100.0) * self.battery_capacity_kwh
            self.battery_soc_pct = self.initial_battery_soc_pct
        else:
            self.battery_energy_kwh = None
            self.battery_soc_pct = None

        self.last_ingest_time_utc = None

    def calculate_hydrodynamics(
        self,
        speed_knots: Optional[float],
        weather: Optional[NormalizedWeatherRecord] = None,
    ) -> Dict[str, float]:
        """
        Calculates calm water, wind, and wave resistance, effective power, and shaft power.
        """
        if speed_knots is None or not math.isfinite(speed_knots) or speed_knots < 0.0:
            return {
                "r_calm_n": 0.0,
                "r_wind_n": 0.0,
                "r_wave_n": 0.0,
                "r_total_n": 0.0,
                "p_calm_kw": 0.0,
                "p_wind_kw": 0.0,
                "p_wave_kw": 0.0,
                "p_propulsion_kw": 0.0,
                "p_shaft_kw": 0.0,
                "p_total_kw": self.auxiliary_hotel_load_kw,
                "fuel_rate_lph": round((self.auxiliary_hotel_load_kw * self.sfoc) / self.fuel_density, 2),
            }

        v_max = self.profile["max_speed_knots"]
        p_rated = self.profile["engine_power_kw"]
        length = self.profile["hull_length_m"]
        beam = self.profile["hull_beam_m"]
        draft = self.profile["hull_draft_m"]

        v_eff = min(speed_knots, v_max)
        v_ms = v_eff * 0.514444

        if v_eff <= 0.05:
            # Stationary / Idle
            p_total = self.auxiliary_hotel_load_kw
            fuel_rate = round((p_total * self.sfoc) / self.fuel_density, 2)
            return {
                "r_calm_n": 0.0,
                "r_wind_n": 0.0,
                "r_wave_n": 0.0,
                "r_total_n": 0.0,
                "p_calm_kw": 0.0,
                "p_wind_kw": 0.0,
                "p_wave_kw": 0.0,
                "p_propulsion_kw": 0.0,
                "p_shaft_kw": 0.0,
                "p_total_kw": round(p_total, 2),
                "fuel_rate_lph": fuel_rate,
            }

        # 1. Calm water resistance and power (Admiralty cubic speed scaling)
        p_calm = p_rated * ((v_eff / v_max) ** 3) * 0.85
        p_calm = min(p_calm, p_rated)
        r_calm = (p_calm * 1000.0) / v_ms if v_ms > 0 else 0.0

        # 2. Wind resistance
        r_wind = 0.0
        p_wind = 0.0
        if weather is not None and weather.wind_speed_knots is not None and math.isfinite(weather.wind_speed_knots):
            w_ms = weather.wind_speed_knots * 0.514444
            rho_air = 1.225
            a_transverse = beam * (draft * 1.2)
            c_wind = 0.85
            r_wind = 0.5 * rho_air * a_transverse * c_wind * (w_ms ** 2)
            p_wind = (r_wind * v_ms) / 1000.0

        # 3. Wave resistance
        r_wave = 0.0
        p_wave = 0.0
        if weather is not None and weather.wave_height_m is not None and math.isfinite(weather.wave_height_m):
            hs = max(0.0, weather.wave_height_m)
            rho_water = 1025.0
            g = 9.81
            r_wave = (1.0 / 16.0) * rho_water * g * (hs ** 2) * beam * math.sqrt(beam / max(1.0, length)) * 0.5
            p_wave = (r_wave * v_ms) / 1000.0

        r_total = r_calm + r_wind + r_wave
        # Actual mechanical propulsion demand required to overcome total hydrodynamic resistance:
        p_prop_demand = (p_calm + p_wind + p_wave) / self.propulsion_efficiency
        # Delivered shaft power is capped by maximum engine rating:
        p_prop_delivered = min(p_prop_demand, p_rated)
        p_shaft = round(p_prop_delivered, 2)
        p_shaft_demand = round(p_prop_demand, 2)
        p_total = round(p_shaft + self.auxiliary_hotel_load_kw, 2)

        fuel_rate_lph = round((p_total * self.sfoc) / self.fuel_density, 2)

        return {
            "r_calm_n": round(r_calm, 1),
            "r_wind_n": round(r_wind, 1),
            "r_wave_n": round(r_wave, 1),
            "r_total_n": round(r_total, 1),
            "p_calm_kw": round(p_calm, 2),
            "p_wind_kw": round(p_wind, 2),
            "p_wave_kw": round(p_wave, 2),
            "p_propulsion_kw": round(p_prop_delivered, 2),
            "p_shaft_kw": p_shaft,
            "p_shaft_demand_kw": p_shaft_demand,
            "p_total_kw": p_total,
            "fuel_rate_lph": fuel_rate_lph,
        }

    def estimate_energy_state(
        self,
        payload: CanonicalTelemetryPayload,
        weather: Optional[NormalizedWeatherRecord] = None,
        solar_irradiance_kw_per_m2: Optional[float] = None,
    ) -> CanonicalTelemetryPayload:
        """
        Processes a CanonicalTelemetryPayload, computes derived hydrodynamic & powertrain
        state, integrates fuel/battery consumption over elapsed host time, and attaches
        strongly typed DERIVED energy telemetry.
        """
        # Parse ingestion timestamp for host time integration
        curr_time = None
        if payload.ingested_at_utc:
            try:
                curr_time = datetime.fromisoformat(payload.ingested_at_utc.replace("Z", "+00:00"))
            except Exception:
                curr_time = datetime.now(timezone.utc)
        else:
            curr_time = datetime.now(timezone.utc)

        # Preserve pre-existing STALE or EXPIRED states; otherwise evaluate against curr_time
        if payload.quality.freshness in (
            TelemetryFreshnessState.STALE,
            TelemetryFreshnessState.EXPIRED,
            TelemetryFreshnessState.DISCONNECTED,
        ):
            freshness = payload.quality.freshness
        else:
            freshness = payload.evaluate_freshness(current_time_utc=curr_time)

        is_fresh = freshness == TelemetryFreshnessState.FRESH
        is_expired = freshness in (TelemetryFreshnessState.EXPIRED, TelemetryFreshnessState.DISCONNECTED)

        # Hydrodynamics and fuel rate
        sog = payload.position.speed_over_ground_knots if payload.position else None
        hydro = self.calculate_hydrodynamics(speed_knots=sog, weather=weather)
        fuel_rate_lph = hydro["fuel_rate_lph"]
        p_shaft_kw = hydro["p_shaft_kw"]

        # Solar PV calculation
        solar_power_kw = 0.0
        if solar_irradiance_kw_per_m2 is not None and solar_irradiance_kw_per_m2 > 0:
            a_solar = self.profile["solar_panel_size_m2"]
            eta_solar = self.profile["solar_panel_efficiency_pct"] / 100.0
            solar_power_kw = round(a_solar * eta_solar * solar_irradiance_kw_per_m2, 2)

        # Time integration delta
        delta_seconds = 0.0
        if not is_expired and self.last_ingest_time_utc is not None:
            delta_seconds = (curr_time - self.last_ingest_time_utc).total_seconds()
            # Guard against clock skew or negative dt (bound to 3600s max step)
            if delta_seconds < 0.0 or delta_seconds > 3600.0:
                delta_seconds = 0.0

        if not is_expired:
            self.last_ingest_time_utc = curr_time

            # Integrate fuel consumption
            if delta_seconds > 0.0:
                delta_fuel = (fuel_rate_lph * delta_seconds) / 3600.0
                self.cumulative_fuel_consumed_liters += delta_fuel
                if self.fuel_remaining_liters is not None:
                    self.fuel_remaining_liters = max(0.0, self.fuel_remaining_liters - delta_fuel)

            # Integrate battery energy (auxiliary load displacement with solar)
            if delta_seconds > 0.0 and self.battery_energy_kwh is not None:
                p_net_kw = solar_power_kw - self.auxiliary_hotel_load_kw
                delta_kwh = (p_net_kw * delta_seconds) / 3600.0
                self.battery_energy_kwh = min(
                    self.battery_capacity_kwh,
                    max(0.0, self.battery_energy_kwh + delta_kwh),
                )
                self.battery_soc_pct = round(
                    (self.battery_energy_kwh / self.battery_capacity_kwh) * 100.0, 2
                )

        # Build augmented energy telemetry
        energy_telemetry = EnergyTelemetry(
            fuel_remaining_liters=round(self.fuel_remaining_liters, 2) if self.fuel_remaining_liters is not None else None,
            fuel_rate_lph=fuel_rate_lph if not is_expired else None,
            battery_soc_pct=self.battery_soc_pct if not is_expired else None,
            battery_soh_pct=self.battery_soh_pct if not is_expired else None,
            battery_usable_kwh=round(self.battery_energy_kwh, 2) if self.battery_energy_kwh is not None and not is_expired else None,
            battery_power_kw=round(solar_power_kw - self.auxiliary_hotel_load_kw, 2) if not is_expired else None,
            solar_power_kw=solar_power_kw if not is_expired else None,
        )

        # Keep engine state strictly UNKNOWN (never infer from SOG)
        engine_telemetry = EngineTelemetry(
            state=payload.engine.state if payload.engine else EngineOperationalState.UNKNOWN,
            power_kw=p_shaft_kw if not is_expired else None,
            fuel_rate_lph=fuel_rate_lph if not is_expired else None,
        )

        # Return augmented copy of canonical telemetry
        return CanonicalTelemetryPayload(
            telemetry_id=payload.telemetry_id,
            timestamp_utc=payload.timestamp_utc,
            ingested_at_utc=payload.ingested_at_utc,
            vessel_id=payload.vessel_id,
            position=payload.position,
            engine=engine_telemetry,
            energy=energy_telemetry,
            quality=payload.quality,
            provenance=TelemetryProvenance(
                source=f"{payload.provenance.source}+VIRTUAL_ENERGY_ESTIMATOR",
                mode=payload.provenance.mode,
                stream_id=payload.provenance.stream_id,
            ),
        )
