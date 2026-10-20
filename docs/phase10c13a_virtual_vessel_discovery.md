# PHASE 10C.13A — VIRTUAL VESSEL ENVIRONMENT DISCOVERY & INTEGRATION FEASIBILITY REPORT

**Project Root:** `C:\maritime grids`  
**Execution Mode:** READ-ONLY DISCOVERY, ARCHITECTURE AUDIT, FEASIBILITY ANALYSIS, AND INTEGRATION PLAN  
**Status:** COMPLETE (Zero Production Code Changes, Zero Actuator Paths)

---

## 1. EXECUTIVE SUMMARY

Maritime Grids is evolving from an advisory/telemetry dashboard into a **virtual maritime operational environment**. The core requirement is to enable an operator to enter an existing virtual ship simulator, manually drive a virtual vessel on a virtual ocean, while the Maritime Grids platform receives the vessel's live spatial and kinematic telemetry (latitude, longitude, SOG, COG, heading) and delivers advance operational advisories, energy state analysis, and time-aware real-world weather look-ahead forecasts along the vessel's voyage route.

This phase was executed under strict read-only discovery constraints:
* **Zero production code modifications** were made to existing backend, frontend, contracts, or models.
* **Zero real-world actuator pathways** exist or were designed; all vehicle control loops are 100% isolated within the virtual simulation runtime.
* An exhaustive forensic audit of the existing codebase was conducted across backend services, telemetry gateways, weather connectors, voyage contexts, advisory engines, and Driver Dashboard V1 components.
* Candidate maritime simulation environments were evaluated against technical, operational, licensing, and integration criteria.
* A robust, decoupled adapter-based integration architecture was designed, mapping standard maritime telemetry protocols (such as NMEA 0183 over UDP/TCP) into the canonical Maritime Grids telemetry gateway without requiring a 3D ocean engine to be developed from scratch.

---

## 2. CURRENT ARCHITECTURE AUDIT

The Maritime Grids system architecture is structured in strict hierarchical layers, ensuring that computational physics, machine learning models, domain services, and presentation boundaries remain decoupled:

```text
                               DRIVER DASHBOARD V1
                                       │
                                       ▼
                       FASTAPI TRANSPORT BOUNDARY (API)
                                       │
                       ┌───────────────┴───────────────┐
                       ▼                               ▼
             ENGINEERING SERVICE               OPERATOR SERVICE
                       │                               │
                       ▼                               ▼
             INTEGRATION FACADE                ADVISORY PIPELINE
                       │                               │
        ┌──────────────┼──────────────┐                ▼
        ▼              ▼              ▼         ADVISORY ENGINE
  COORDINATOR     FEASIBILITY    OPTIMIZERS            │
        │              │              │                ▼
        └──────────────┼──────────────┘        DECISION CONTEXT
                       ▼                               │
              FROZEN CORE MODELS                       ▼
        (Fuel, Battery, Solar, Speed)           VOYAGE CONTEXT
                                                       │
                                                       ▼
                                                WEATHER PROVIDER
                                                       ▲
                                                       │
                                               TELEMETRY GATEWAY
```

### 2.1 Backend Component Locations & State

| Component Subsystem | File / Directory Location | Implementation Summary | Invariants & Purity |
| :--- | :--- | :--- | :--- |
| **FastAPI Application** | `app/api/app.py`, `app/api/` | Routers for operator, engineering, state, and telemetry. | Pure transport boundary; zero business logic in routes. |
| **Telemetry Gateway** | `app/telemetry/gateway.py` | Validates, normalizes, caches latest telemetry, and manages pub/sub. | In-memory latest frame; zero actuator dispatch. |
| **Telemetry Contracts** | `app/telemetry/contracts.py` | Pydantic V2 models (`CanonicalTelemetryPayload`, `PositionTelemetry`, `EngineTelemetry`, `EnergyTelemetry`). | Strict null preservation (`null != 0`); typed enums. |
| **Telemetry Adapter** | `app/telemetry/adapter.py` | Validates raw payload dictionaries against physical bounds. | Quarantines invalid fields; never silently drops records. |
| **Telemetry Simulator** | `app/telemetry/simulator.py` | Generates 8 deterministic operational test scenarios (A–H). | Offline deterministic generation for automated test suites. |
| **Telemetry Audit Log** | `app/telemetry/repository.py`, `sqlite_repository.py`, `memory_repository.py` | Bounded audit logging with indexed querying. | Bounded memory buffer (5,000 max) or indexed SQLite. |
| **Weather Providers** | `app/weather/provider.py`, `open_meteo_provider.py`, `mock_provider.py` | Abstract provider interface with live Open-Meteo and offline mock implementations. | Typed error hierarchy; exponential backoff; cache layer. |
| **Route / Voyage Models** | `app/voyage/contracts.py`, `app/voyage/context_builder.py` | Pydantic V2 voyage aggregates (`VoyageContext`, `Route`, `VesselContext`, `VesselPosition`). | Geographic validation; chronological waypoint ordering. |
| **Decision Context** | `app/decision/contracts.py`, `builder.py` | Merges `VoyageContext`, `EngineeringState`, `RegulatoryState`, and `MarketState`. | Read-only input snapshot for rule evaluation. |
| **Advisory Engine** | `app/advisory/engine.py`, `rules.py`, `pipeline.py` | Executes 10 deterministic advisory rules with evidence tracking. | `human_review_required = True` on all advisories; zero automated actuation. |
| **Integration Facade** | `src/facade.py` (`MaritimeScenarioFacade`) | Unified facade to 10 core engineering capabilities. | Preserves frozen core; zero direct mutation. |
| **Frozen Core Models** | `src/fuel_model.py`, `src/battery_model.py`, `src/solar_model.py`, `src/speed_cooptimizer.py` | ML models (XGBoost, LSTM, Ridge) and physics calculators. | 5 canonical models cryptographically verified via SHA-256. |

---

## 3. EXISTING TELEMETRY ARCHITECTURE

The current telemetry subsystem (`app/telemetry/`) provides the exact ingestion, normalization, and distribution foundation required for virtual vessel integration:

### 3.1 Telemetry Flow
```text
Raw Ingestion (Dict / JSON)
            │
            ▼
    TelemetryAdapter.validate_and_normalize()
            │
            ▼
 CanonicalTelemetryPayload (Strongly-typed Pydantic V2)
            │
            ▼
    TelemetryGateway.update_current()
            │
      ┌─────┴───────────────────────┐
      ▼                             ▼
TelemetryAuditRepository       Pub/Sub Broadcast
 (In-Memory / SQLite)         (Active Subscriber Queues)
```

### 3.2 Ingestion & Gateway Invariants
1. **Strict Null Preservation:** Unmeasured fields remain `None` throughout the pipeline and are never fabricated as `0.0`. Missing speed is rendered as `Unavailable` rather than stationary `0.0 kn`.
2. **Engine State Semantics:** `EngineOperationalState` strictly distinguishes `ON`, `OFF`, and `UNKNOWN`. Missing engine data is explicitly categorized as `UNKNOWN` with zero false inferences.
3. **Data Provenance:** Telemetry frames explicitly declare `mode: OBSERVED` (physical sensors) vs `mode: SIMULATED` (virtual simulators or scenario engines).
4. **Subscriber Isolation:** Pub/sub event queues are bounded (default 100 frames) with automatic drop-oldest overflow protection and automatic cleanup of disconnected clients.

---

## 4. EXISTING WEATHER ARCHITECTURE

The platform implements a normalized weather abstraction (`app/weather/`) supporting both live network queries and deterministic offline generation.

### 4.1 Weather & Oceanographic Data Matrix

| Environmental Variable | Existing Provider | Code Implementation | Availability | Mode / Resolution | Downstream Consuming Systems |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Air Temperature ($T_{2m}$)** | Open-Meteo & Mock | `temperature_c` | **Available** | Hourly / 0.1°C | Solar model efficiency, HVAC load, Crew comfort advisory |
| **Relative Humidity ($RH_{2m}$)** | Open-Meteo & Mock | `relative_humidity_pct` | **Available** | Hourly / 1.0% | Atmospheric density, Weather display card |
| **Surface Barometric Pressure ($P_{sfc}$)** | Open-Meteo & Mock | `surface_pressure_hpa` | **Available** | Hourly / 0.1 hPa | Barometric depression storm warning rules |
| **Wind Speed ($V_{wind}$)** | Open-Meteo & Mock | `wind_speed_ms`, `wind_speed_knots` | **Available** | Hourly / 0.1 kn | Aerodynamic drag resistance, Advisory rule `ADVISORY_WEATHER_WIND_WARNING` |
| **Wind Direction ($\theta_{wind}$)** | Open-Meteo & Mock | `wind_direction_deg` | **Available** | Hourly / 1.0° | Relative wind angle calculation, Apparent wind vectors |
| **Cloud Cover ($CC$)** | Open-Meteo & Mock | `cloud_cover_pct` | **Available** | Hourly / 1.0% | Solar irradiance attenuation, Weather display card |
| **Precipitation Rate ($P_{rate}$)** | Open-Meteo & Mock | `precipitation_mm_per_hr` | **Available** | Hourly / 0.1 mm/h | Advisory engine, Visibility factor |
| **Solar Irradiance ($GHI$)** | Open-Meteo & Mock | `solar_irradiance_w_per_m2`, `daily_ghi_kwh_per_m2` | **Available** | Hourly / 1 W/m² | Solar PV model generation estimates (`SolarPVModel`) |
| **Significant Wave Height ($H_s$)** | Open-Meteo Marine & Mock | `wave_height_m` | **Available** | Hourly / 0.1 m | Added wave resistance, Advisory rule `ADVISORY_WEATHER_WAVE_WARNING` |
| **Dominant Wave Direction ($\theta_{wave}$)** | Open-Meteo Marine & Mock | `wave_direction_deg` | **Available** | Hourly / 1.0° | Head/beam/following sea interaction analysis |
| **Wave Peak Period ($T_p$)** | Open-Meteo Marine & Mock | `wave_period_s` | **Available** | Hourly / 0.1 s | Parametric roll resonance risk, Sea state severity |
| **Ocean Current Speed ($V_{curr}$)** | Open-Meteo Marine & Mock | `ocean_current_speed_knots` | **Available** | Hourly / 0.01 kn | Speed-over-ground vs Speed-through-water navigation corrections |
| **Ocean Current Direction ($\theta_{curr}$)** | Open-Meteo Marine & Mock | `ocean_current_direction_deg`| **Available** | Hourly / 1.0° | Drift angle estimation, Route navigation offset |
| **Sea Surface Temperature ($SST$)** | Open-Meteo Marine | Not normalized in contract | *Not Extracted* | N/A | Available from Open-Meteo Marine API, but currently omitted from contract |

---

## 5. EXISTING VOYAGE & ROUTE ARCHITECTURE

The voyage subsystem (`app/voyage/`) provides complete geographic route representation:
* **`Route` Model:** Defines ordered chains of `RouteWaypoint` objects $(lat, lon, name, order, speed\_knots)$.
* **`VoyageTimeline` Model:** Tracks departure time, current reference time, planned arrival time, and dynamic estimated arrival time ($ETA$).
* **`VoyageContextBuilder`:** Assembles all sub-contexts and enriches route waypoints via `provider.get_route_weather(waypoints, start_time_utc)`.
* **ETA Estimation Semantics:** Explicitly stamped as an application-level linear kinematic estimate ($ETA = T + \frac{\Delta d}{SOG}$), accompanied by mandatory operator disclaimers declaring that it is not a hydrodynamic maneuvering simulation.

---

## 6. EXISTING DASHBOARD CAPABILITIES

Driver Dashboard V1 (`frontend/`) is implemented in vanilla ECMAScript modules (ESM) with zero heavyweight frontend framework dependencies:
1. **Speed Kinematics & Engine Cards:** Displays live SOG, COG, and engine state (`ON`, `OFF`, `UNKNOWN`).
2. **Energy & Solar Cards:** Displays bunker fuel volume, battery SOC/SOH, and solar PV estimates with the mandatory label: `CLIMATOLOGICAL SCENARIO ESTIMATE`.
3. **Marine Weather Card:** Displays atmospheric variables (temperature, humidity, pressure, wind) and oceanic variables (wave height, wave period, current).
4. **Voyage Progression & ETA:** Displays linear route progress, distance remaining, and ETA with required non-hydrodynamic disclaimers.
5. **Bridge Decision Advisories:** Displays actionable recommendations color-coded by severity (`CRITICAL`, `WARNING`, `NOTICE`, `INFO`) with the mandatory badge: `HUMAN REVIEW REQUIRED`.
6. **Telemetry & Stream Status Indicators:** Separately renders stream connection state (`STREAM: CONNECTED / RECONNECTING / DISCONNECTED`) and data freshness (`DATA: FRESH / STALE / EXPIRED`).
7. **Recent Telemetry Stream Log Table:** Displays reverse-chronological persistent audit snapshots with explicit null rendering (`N/A`).

---

## 7. VIRTUAL VESSEL REQUIREMENTS

To integrate seamlessly with Maritime Grids, the candidate virtual vessel environment must fulfill the following functional and operational requirements:

### 7.1 Required Outputs (Simulator $\to$ Maritime Grids)
* **Geographic Position:** Latitude and Longitude in WGS84 decimal degrees.
* **Kinematics:** Speed Over Ground (SOG) in knots, Course Over Ground (COG) in degrees, True Heading in degrees.
* **Temporal Reference:** UTC timestamp corresponding to the simulation step.
* **Propulsion Telemetry (Optional/Where Supported):** Engine operational state, engine RPM, throttle/load percentage, fuel consumption rate.

### 7.2 Required Operator Controls (Operator $\to$ Simulator Only)
* **Interactive Steering:** Helm / rudder angle control.
* **Propulsion Control:** Throttle levers / engine telegraph (ahead / astern).
* **Vessel Navigation Views:** Bridge view, chart view, 3D sea view.

### 7.3 Environmental Capabilities
* **Geographic World Representation:** Navigable ocean, coastlines, bathymetry, and navigational aids.
* **Vessel Dynamics:** Realistic hydrodynamics (inertia, drift, turn rate, wave response).

---

## 8. CANDIDATE SIMULATOR COMPARISON

Three established, viable maritime simulation environments were evaluated:

| Criterion | Candidate 1: Bridge Command 5.x | Candidate 2: OpenCPN (with Simulation Plugins) | Candidate 3: Gazebo / gz-waves (VRX Framework) |
| :--- | :--- | :--- | :--- |
| **Primary Nature** | Open-source 3D interactive ship bridge simulator | Open-source maritime chartplotter & navigational simulator | Research-grade robotics 3D surface vessel physics simulator |
| **Target Audience** | Commercial/Naval maritime training & navigation | Marine navigators, sailors, commercial vessel operators | Robotics researchers, autonomous vessel developers |
| **Supported OS** | Windows 10/11 (Native x64), Linux, macOS | Windows 10/11 (Native x64), Linux, macOS | Linux (Ubuntu), WSL2 on Windows |
| **License** | GPL v2+ (Fully Open Source) | GPL v2+ (Fully Open Source) | Apache 2.0 / BSD (Open Source) |
| **Interactive Driving** | **Full 3D Bridge**: Wheel, throttle, radar, binoculars, visual sea | **Chart-Based**: Interactive helm, speed sliders, route tracking | **3D Simulation**: Keyboard, gamepad, ROS2 topic control |
| **Geographic System** | Real-world WGS84 charts, terrain elevation, port databases | Worldwide NOAA / ENC / raster nautical charts | Local terrain tiles / Gazebo coordinate frames (requires GPS plugin) |
| **Telemetry Output** | **Standard NMEA 0183 via UDP / TCP broadcast or serial** | **NMEA 0183 via UDP / TCP / Serial multiplexer** | ROS2 topics, protobuf, or custom UDP bridge |
| **Telemetry Variables** | Lat, Lon, SOG, COG, Heading, Depth, Rudder angle, RPM | Lat, Lon, SOG, COG, Heading, Waypoints, AIS targets | Position (XYZ/LatLon), Linear/Angular velocity, IMU |
| **Weather Support** | Wind speed/direction, wave height/period, fog/visibility, rain | GRIB weather overlays (display only; does not affect kinematics) | Hydrodynamic wave forcing, wind forces, current drift |
| **Integration Complexity** | **Low:** Native UDP NMEA broadcast (`GPRMC`, `GPGGA`, `GPHDT`) | **Low:** Native NMEA multiplexer over UDP/TCP | **High:** Requires ROS2-to-REST/UDP bridge & WSL2 installation |
| **Offline Operation** | 100% Offline (Self-contained simulation loop) | 100% Offline | 100% Offline |
| **Avoids 3D Engine Build**| **YES:** Complete 3D ocean, ship models, weather visualizer | **Partial:** 2D ECDIS chart environment (no 3D ocean) | **YES:** Complete 3D Gazebo ocean rendering |

### 8.1 Detailed Candidate Evaluation

#### Candidate 1: Bridge Command 5.x (Recommended Primary)
* **Strengths:** Purpose-built for human maritime training. Provides realistic 3D bridge perspectives, physical multi-throttle and rudder controls, adjustable visual sea states, and native NMEA 0183 UDP streaming on port 10110/10111. Completely self-contained, runs natively on Windows with zero external framework dependencies.
* **Telemetry Compatibility:** Emits standard NMEA 0183 sentences (`$GPRMC`, `$GPGGA`, `$GPHDT`, `$SDDBT`) continuously during user navigation.
* **Verdict:** **Selected as Primary Simulator Candidate.**

#### Candidate 2: OpenCPN Navigational Environment (Recommended Lightweight Alternative)
* **Strengths:** Highly stable 2D marine electronic chart display and information system (ECDIS). Includes realistic vessel simulation plugins, route planning, and built-in NMEA broadcast servers. Extremely low resource footprint.
* **Telemetry Compatibility:** Emits standard NMEA 0183 sentences (`$ECRMC`, `$ECGGA`, `$ECHDT`) over TCP/UDP localhost ports.
* **Verdict:** **Selected as Lightweight 2D Fallback / Benchtop Environment.**

#### Candidate 3: Gazebo / gz-waves / VRX (Robotics Physics Candidate)
* **Strengths:** Advanced non-linear hydrodynamics, 3D wave spectra, and customizable sensor suites.
* **Weaknesses:** Substantial operational complexity; requires Linux/WSL2 and ROS2 runtime stacks; steeper learning curve for human bridge operation.
* **Verdict:** Retained for future advanced autonomous hydrodynamics testing.

---

## 9. INTEGRATION PROTOCOL COMPARISON

To connect the simulator to the Maritime Grids adapter layer, four transport protocols were analyzed:

| Protocol | Transport | Latency | Overhead | Industry Standard | Implementation Suitability for Maritime Grids |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NMEA 0183 over UDP** | Connectionless UDP | $< 1$ ms | Minimal (ASCII sentences) | **Global Marine Standard** | **Optimal for Simulator Ingestion:** Native to Bridge Command and OpenCPN; zero handshake overhead. |
| **NMEA 0183 over TCP** | Stream TCP | $1–5$ ms | Low | Marine standard | **Supported Alternative:** Guaranteed delivery; ideal for point-to-point connections. |
| **JSON over REST POST** | HTTP/1.1 | $5–20$ ms | Medium | Web standard | **Optimal for Backend Ingestion:** Already implemented via `POST /api/v1/operator/telemetry/ingest`. |
| **SSE (Server-Sent Events)**| HTTP Stream | $1–5$ ms | Low | Modern web standard | **Optimal for Dashboard Push:** Native browser `EventSource` with automatic reconnection. |

---

## 10. RECOMMENDED INTEGRATION ARCHITECTURE

The integration architecture preserves absolute decoupling between the virtual simulator and the Maritime Grids core:

```text
┌─────────────────────────────────────────────────────────────┐
│                 VIRTUAL MARITIME SIMULATOR                  │
│                   (Bridge Command / OpenCPN)                 │
│                                                             │
│   • User manually operates helm & throttles                 │
│   • 3D Ocean / Chart Navigation Runtime                     │
│   • Internal vessel kinematics & hydrodynamics              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               │ NMEA 0183 Datagrams over UDP
                               │ ($GPRMC, $GPGGA, $GPHDT, $RPM)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               VIRTUAL VESSEL TELEMETRY ADAPTER              │
│                        (Python Service)                     │
│                                                             │
│   • Listens on UDP socket (e.g., port 10110)                │
│   • Parses NMEA sentences (pynmea2 / native regex parser)   │
│   • Validates geographic coordinates & kinematics           │
│   • Tags provenance: mode="SIMULATED", source="SIMULATOR"   │
│   • Translates to CanonicalTelemetryPayload contract        │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               │ HTTP POST / In-Process Call
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 EXISTING TELEMETRY GATEWAY                  │
│                (app/telemetry/gateway.py)                   │
│                                                             │
│   • Updates current vessel snapshot                         │
│   • Records to TelemetryAuditRepository (SQLite/Memory)     │
│   • Dispatches to real-time pub/sub subscriber queues       │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               │ Live Telemetry               │ Position & Speed
               ▼                              ▼
┌─────────────────────────────┐┌──────────────────────────────┐
│     DRIVER DASHBOARD V1     ││ WEATHER / ROUTE LOOK-AHEAD   │
│                             ││ (Enriched Voyage Context)    │
│ • SOG / COG / Heading       │└──────────────┬───────────────┘
│ • Engine & Energy Status    │               │
│ • Real-time Stream Status   │               │ Forward Waypoints
│ • Telemetry Audit Log       │               ▼
│ • Actionable Advisories     │┌──────────────────────────────┐
└──────────────▲──────────────┘│   EXISTING ADVISORY ENGINE   │
               │               │   (app/advisory/engine.py)   │
               │               │                              │
               │               │ • Forecast storm warnings    │
               │               │ • Route speed advisory       │
               └───────────────┤ • Wave impact assessment     │
                               └──────────────────────────────┘
```

---

## 11. SIMULATOR-TO-MARITIME-GRIDS DATA MAPPING

The following mapping translates raw NMEA 0183 sentences emitted by the simulator into the strongly-typed `CanonicalTelemetryPayload`:

| Simulator NMEA Field | NMEA Sentence | Maritime Grids Canonical Field | Unit / Type in Contract | Conversion & Validation Logic |
| :--- | :--- | :--- | :--- | :--- |
| **Latitude** | `$GPRMC`, `$GPGGA` | `PositionTelemetry.latitude` | Decimal degrees (`float`) | Convert NMEA DDMM.MMMM to decimal degrees; validate $[-90.0, 90.0]$. |
| **Longitude** | `$GPRMC`, `$GPGGA` | `PositionTelemetry.longitude` | Decimal degrees (`float`) | Convert NMEA DDDMM.MMMM to decimal degrees; validate $[-180.0, 180.0]$. |
| **Speed Over Ground** | `$GPRMC`, `$GPVTG` | `PositionTelemetry.speed_over_ground_knots`| Knots (`float`) | Direct extraction from NMEA knots field; validate $\ge 0.0$. |
| **Course Over Ground** | `$GPRMC`, `$GPVTG` | `PositionTelemetry.course_over_ground_deg` | Degrees (`float`) | Modulo 360 normalization $[0.0, 360.0)$. |
| **True Heading** | `$GPHDT`, `$GPHDG` | `PositionTelemetry.heading_deg` | Degrees (`float`) | Modulo 360 normalization $[0.0, 360.0)$. |
| **Timestamp (UTC)** | `$GPRMC`, `$GPGGA` | `CanonicalTelemetryPayload.timestamp_utc` | ISO 8601 string | Parse HHMMSS.SS and date from NMEA; format as UTC ISO 8601. |
| **Engine State** | Simulator Proprietary / `$ERRPM` | `EngineTelemetry.state` | `EngineOperationalState` (`ON`, `OFF`, `UNKNOWN`) | If RPM $> 0 \to \text{ON}$; if RPM $= 0 \to \text{OFF}$; if missing $\to \text{UNKNOWN}$. |
| **Engine RPM** | Proprietary / `$ERRPM` | `EngineTelemetry.rpm` | RPM (`float` or `None`) | Preserved if reported; `None` if unmeasured (never 0.0). |
| **Engine Load / Power** | Proprietary sentence | `EngineTelemetry.load_percent`, `power_kw` | `%` / `kW` (`float` or `None`) | Preserved if reported; `None` if unmeasured. |
| **Fuel Remaining** | Calculated / Virtual Tank | `EnergyTelemetry.fuel_remaining_liters` | Liters (`float` or `None`) | Linked to virtual tank model or `None`. |
| **Battery SOC / SOH** | Virtual Battery State | `EnergyTelemetry.battery_soc_pct`, `battery_soh_pct`| `%` (`float` or `None`) | Calculated by clean energy state model or `None`. |
| **Data Provenance** | Adapter Metadata | `TelemetryProvenance.mode` | `TelemetryProvenanceType.SIMULATED` | Hardcoded by adapter to declare virtual simulator origin. |

---

## 12. REAL-WORLD WEATHER LOOK-AHEAD DESIGN

The weather look-ahead subsystem provides forward-looking environmental intelligence along the vessel's trajectory rather than solely querying instantaneous weather at the ship's current fix.

### 12.1 Algorithmic Look-Ahead Sequence

```text
[Step 1: Current Vessel Navigation Fix]
  Vessel Position: (lat_0, lon_0)
  Kinematics: SOG_0 (knots), COG_0 (deg)
  Timestamp: T_0 (UTC)
        │
        ▼
[Step 2: Dynamic Route Leg Projection]
  Identify nearest active route leg and upcoming waypoints:
  Waypoints: [WP_1, WP_2, ..., WP_N]
  Distances from vessel: [d_1, d_2, ..., d_N] (nautical miles)
        │
        ▼
[Step 3: Temporal Waypoint Arrival Estimation]
  For each waypoint i:
  Estimated Travel Time: Δt_i = d_i / max(SOG_0, 1.0) (hours)
  Estimated Arrival Time: T_i = T_0 + Δt_i (UTC ISO timestamp)
        │
        ▼
[Step 4: Space-Time Synchronized Weather Query]
  For each waypoint (lat_i, lon_i) at future time T_i:
  Query WeatherProvider.get_historical_or_forecast_weather(
      latitude=lat_i,
      longitude=lon_i,
      target_time_utc=T_i
  )
        │
        ▼
[Step 5: Assemble RouteWeatherProfile]
  Build timeline of future environmental conditions:
  WP_1 (in 30 min): Wind 14 kn, Waves 1.1 m (Moderate)
  WP_2 (in 2.5 hr): Wind 28 kn, Waves 3.2 m (Adverse - Alert Condition)
        │
        ▼
[Step 6: Feed Forward to Advisory Engine]
  AdvisoryEngine evaluates future leg profile:
  Triggers ADVISORY_WEATHER_WAVE_WARNING ("Adverse sea state expected at WP_2 in 2.5 hours")
  Operator receives actionable advance recommendation to adjust speed or alter route.
```

### 12.2 Provenance & Quality Governance
* All look-ahead weather points are explicitly tagged `data_type = WeatherProvenanceType.FORECAST`.
* If a future timestamp exceeds the provider's forecast horizon (e.g., $> 16$ days), data is flagged as `CLIMATOLOGICAL_ESTIMATE` or `UNAVAILABLE`.

---

## 13. VIRTUAL-CONTROL SAFETY BOUNDARY

Safety architecture is central to this platform:

```text
  ┌───────────────────────────────────────────────────────────┐
  │                    HUMAN OPERATOR / USER                  │
  └─────────────┬───────────────────────────────┬─────────────┘
                │                               │
                │ Drives Virtual Vessel         │ Views Advance Advisories
                │ (Keyboard / Mouse / Joystick) │ (Read-Only)
                ▼                               ▼
  ┌───────────────────────────┐   ┌───────────────────────────┐
  │ VIRTUAL SHIP SIMULATOR    │   │ MARITIME GRIDS PLATFORM   │
  │ (Bridge Command / OpenCPN)│   │ (Telemetry & Advisory)    │
  │                           │   │                           │
  │ • Simulated rudder/engine │   │ • Telemetry Gateway (Rx)  │
  │ • Simulated 3D ocean      │   │ • Real Weather & Forecast │
  │ • Simulator-only physics  │   │ • Advisory Engine         │
  │ • Zero external actuators │   │ • Driver Dashboard V1     │
  └─────────────┬─────────────┘   └───────────────────────────┘
                │
                │ Read-Only NMEA 0183 Telemetry (One-Way)
                ▼
  ═════════════════════════════════════════════════════════════
         STRICT SAFETY BOUNDARY (NO ACTUATION CHANNELS)
  ═════════════════════════════════════════════════════════════
                │
               XXX  PHYSICAL SHIPS, HARDWARE PLCS,
               XXX  MODBUS ACTUATORS, ENGINE GOVERNORS,
               XXX  AND AUTOPILOT HARDWARE ARE UNCONNECTED
```

### 13.1 Strict Safety Invariants
1. **Unidirectional Telemetry Ingestion:** Data flows strictly from the Simulator $\to$ Adapter $\to$ Gateway $\to$ Dashboard. The Maritime Grids backend never sends control commands back to any physical vessel or actuator.
2. **Zero Hardware Control Interfaces:** The repository contains zero Modbus master drivers, zero CAN bus talkers, zero NMEA actuator sentences, and zero PLC control loops.
3. **Simulated State Labeling:** All telemetry originating from the simulator is permanently tagged with `mode: SIMULATED` and `provenance: VIRTUAL_SIMULATOR`.

---

## 14. STREAMING ARCHITECTURE RECOMMENDATION

### 14.1 Simulator $\to$ Adapter Stream
* **Recommendation:** **NMEA 0183 over UDP Broadcast** (localhost / `127.0.0.1:10110`).
* **Rationale:** UDP avoids connection overhead, drops gracefully if the adapter restarts, and is natively supported by Bridge Command and OpenCPN without third-party plugins.

### 14.2 Adapter $\to$ Gateway Ingestion
* **Recommendation:** Direct Python class invocation or HTTP `POST /api/v1/operator/telemetry/ingest`.
* **Rationale:** Reuses the verified `TelemetryGateway.ingest_raw()` endpoint with automated validation and audit recording.

### 14.3 Gateway $\to$ Dashboard Push Stream
* **Recommendation:** **Server-Sent Events (SSE)** via `GET /api/v1/operator/telemetry/stream`.
* **Rationale:** Unidirectional push from server to browser; uses native browser `EventSource` with automatic reconnection; requires zero external WebSocket client libraries.

### 14.4 Telemetry Audit Storage
* **Recommendation:** **SQLite Parameterized Audit Repository** (`SQLiteTelemetryAuditRepository`).
* **Rationale:** Provides indexed reverse-chronological queries, zero external database setup, and strict null preservation.

---

## 15. REUSE VS EXTEND VS NEW COMPONENTS

### 15.1 Reuse Without Modification (100% Frozen & Untouched)
* `src/facade.py` (`MaritimeScenarioFacade`)
* All frozen core engineering models (`src/fuel_model.py`, `src/battery_model.py`, `src/solar_model.py`, `src/speed_cooptimizer.py`, `src/cii_trajectory.py`, `src/economics.py`)
* Model artifacts in `models/` (5 canonical files verified by SHA-256)
* Raw datasets in `data/raw/` (6,228 files)
* Application decision context and rules engine (`app/advisory/engine.py`, `app/advisory/rules.py`)

### 15.2 Extend Through Existing Contracts & Interfaces
* `app/telemetry/adapter.py`: Add an NMEA 0183 sentence parser adapter method.
* `app/weather/provider.py` & `open_meteo_provider.py`: Expose route look-ahead time-interpolation query helper.
* `frontend/pages/DriverDashboard.js`: Connect live stream handler to update route look-ahead summary card.

### 15.3 New Components Required
* `app/telemetry/nmea_adapter.py`: Dedicated lightweight UDP NMEA 0183 listener and sentence parser.
* `app/voyage/lookahead.py`: Service to compute dynamic forward waypoint arrival times and compile future weather profiles.
* Documentation and configuration scripts for Bridge Command / OpenCPN setup.

---

## 16. PROPOSED IMPLEMENTATION PHASES

```text
Phase 10C.13A (Current) ──► Virtual Vessel Discovery & Feasibility (Read-Only Complete)
          │
          ▼
Phase 10C.13B ────────────► NMEA 0183 Virtual Vessel Adapter (UDP Listener & Normalizer)
          │
          ▼
Phase 10C.13C ────────────► Space-Time Weather Look-Ahead Engine
          │
          ▼
Phase 10C.13D ────────────► Driver Dashboard Virtual Vessel Integration & Waypoint Viewer
          │
          ▼
Phase 10C.13E ────────────► End-to-End Simulation Verification & Comprehensive Safety Audit
```

---

## 17. TESTING STRATEGY FOR FUTURE PHASES

Future implementation phases must implement test coverage across the following verification vectors:

1. **NMEA Parsing & Validation Tests:**
   * Valid `$GPRMC`, `$GPGGA`, `$GPHDT` parsing and coordinate conversion.
   * Handling corrupted/truncated NMEA sentences without crashing.
   * Coordinate range enforcement (quarantine latitude $> 90°$ or longitude $> 180°$).
2. **Weather Look-Ahead Tests:**
   * Correct arrival time calculation across variable vessel speeds.
   * Multi-waypoint forward weather query assembly.
   * Degradation handling when future waypoints exceed forecast horizons.
3. **Advisory Generation Tests:**
   * Verification that future adverse weather along the route triggers advance advisories with `human_review_required = True`.
4. **Safety & Non-Actuation Invariant Tests:**
   * Automated AST search confirming zero control/actuator endpoints.
   * Confirmation of `mode = "SIMULATED"` on all simulator-originated frames.
5. **Full Regression Baseline:**
   * Continuous validation of $\ge 808$ backend tests and 52 frontend tests.

---

## 18. RISKS AND LIMITATIONS

| Risk / Limitation | Impact | Mitigation Strategy |
| :--- | :--- | :--- |
| **Simulator UDP Packet Loss** | Dropped frames during high network load | Gateway holds last known valid frame; freshness indicator degrades to `STALE` if no packets arrive for $> 30$ seconds. |
| **Open-Meteo Rate Limiting** | HTTP 429 when querying rapid waypoints | `InMemoryWeatherCache` with 15-minute TTL; batch route waypoint queries into single requests. |
| **Forecast Uncertainty** | Weather forecasts diverge $> 72$ hours out | Explicitly label look-ahead weather as `FORECAST` with confidence decay disclaimers. |
| **Simulator Clock Skew** | Simulator virtual time out of sync with real UTC | Adapter normalizes timestamps or records reception UTC; Driver Dashboard displays payload timestamp. |

---

## 19. DATA AND MODEL INTEGRITY STATUS

All system assets and cryptographic benchmarks remain 100% intact:

| Asset | Path | Expected Hash / Value | Current Status |
| :--- | :--- | :--- | :--- |
| Weather Joblib | `models/weather_final.joblib` | `39b08a4ba2c860dc74a094f8ad460b3aaa001a9d1b212717baadce55cfc1e6a3` | **VERIFIED UNCHANGED** |
| Fuel XGBoost | `models/fuel_xgb.joblib` | `cb6a4e0922b0b0919583ca453568960a2b6495f321d43cff0aab299a4aaf8323` | **VERIFIED UNCHANGED** |
| Battery SOH | `models/battery_soh_final.joblib` | `9611e0507b8bf840d31d0be3b1223ff2368ae6da93e89fca351aea7fc7420eb1` | **VERIFIED UNCHANGED** |
| Battery SOC | `models/battery_soc_lstm.pt` | `c2077e5111648234d7e3b3cc9b2944f1db95c1e6fedc1ea96fd0514e1f35ad25` | **VERIFIED UNCHANGED** |
| Ship Profiles | `data/reference/ship_profiles.csv`| `0f2040a481790b034fac11cd9e2b628c725281397610fe0bdba09f6feed7de75` | **VERIFIED UNCHANGED** |
| Raw Datasets | `data/raw/` | Exactly 6,228 files | **VERIFIED PRESERVED** |
| Production Code Changes | All modules | 0 modifications in discovery phase | **ZERO MODIFICATIONS** |
| Actuator Channels | Repository-wide | 0 executable physical actuator paths | **ZERO ACTUATOR PATHS** |

---

## 20. EXPLICIT RECOMMENDATION FOR NEXT PHASE

It is recommended to proceed to:

### `PHASE 10C.13B — NMEA 0183 VIRTUAL VESSEL ADAPTER IMPLEMENTATION`

**Scope of Phase 10C.13B:**
1. Implement `app/telemetry/nmea_adapter.py`: A lightweight, non-blocking UDP listener and NMEA 0183 sentence parser (`$GPRMC`, `$GPGGA`, `$GPHDT`).
2. Map parsed coordinates, SOG, COG, and heading into `CanonicalTelemetryPayload` with `mode: SIMULATED`.
3. Ingest frames into `TelemetryGateway.ingest_raw()`.
4. Validate with recorded NMEA broadcast fixtures from Bridge Command and OpenCPN.
5. Maintain zero modification to core engineering models and zero physical actuator pathways.

---

```text
PHASE 10C.13A — DISCOVERY COMPLETE
IMPLEMENTATION: NOT PERFORMED
PRODUCTION CODE CHANGES: 0
REAL-WORLD ACTUATOR PATHS: 0
SIMULATOR SELECTED: Bridge Command 5.x (Primary) / OpenCPN (2D Alternative)
NEXT AUTHORIZED PHASE: PHASE 10C.13B — NMEA 0183 VIRTUAL VESSEL ADAPTER
```
