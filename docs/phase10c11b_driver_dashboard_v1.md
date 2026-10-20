# Phase 10C.11B — Driver Dashboard V1 Telemetry, Speed & Engine-State Foundation

## Executive Summary

Phase 10C.11B advances the maritime operator interface to **Driver Dashboard V1**, establishing a high-integrity, semantically aligned presentation layer for operational bridge monitoring. This phase integrates real-time vessel kinematics, engine state representation, bunker fuel consumption, clean battery storage, climatological solar scenario estimation, localized route weather, and human-in-the-loop advisory alerts.

Crucially, Driver Dashboard V1 respects all frozen computational, physical, and regulatory boundaries established in Phases 0–9 and 10A–10C.10.

---

## 1. Data Availability Matrix

| Domain / Variable | Telemetry Source / Provider | Live Availability | Dashboard State / Representation | Safety & Semantic Boundary |
| :--- | :--- | :--- | :--- | :--- |
| **Current Speed (SOG)** | GPS / Telemetry (`vessel.speed_knots`) | **Available** | Rendered in kn with provenance & freshness | Displays `Unavailable` if null (`null != 0`). |
| **Course Over Ground (COG)** | Compass / GPS (`vessel.heading_deg`) | **Available** | Rendered in degrees (°) | Displays `Unavailable` if null. |
| **Recommended Speed** | Phase 9 Co-Optimizer (Offline Tool) | **Not Connected Live** | Explicitly displays `Not available` | Offline optimization tool only; real-time dynamic throttle co-steering is not connected. |
| **Engine State (ON/OFF)** | Engine Management System | **Not Connected Live** | Explicitly displays `ENGINE STATE UNKNOWN` | Never inferred or fabricated from SOG, fuel, or voyage status. |
| **Engine RPM / Load** | Engine Sensors / Shaft Tachometer | **Not Connected Live** | Explicitly displays `Unavailable` | Telemetry is not connected. |
| **Fuel Remaining / Rate** | Flow Meter / Tank Gauges (`energy.fuel_*`) | **Available** | Rendered in L and L/h | Preserves `Unavailable` when unmeasured; does not default to `0`. |
| **Battery SOC / SOH** | Battery Management System (`energy.battery_*`) | **Available** | Rendered in % and Usable kWh | Gauges indicate charge & health status. |
| **Solar Generation** | Climatological Solar Profile | **Available (Scenario)** | Rendered with mandatory `CLIMATOLOGICAL SCENARIO ESTIMATE` label | Flagged with Diurnal Uncertainty when voyage $> 24\text{ h}$. |
| **Route Weather (Wind/Wave)** | Weather Context / Open-Meteo | **Available** | Rendered in kn, °, m, s, °C, %, hPa | Informs bridge advisories; does not directly alter frozen Phase 2 fuel model coefficients. |
| **Corridor Progression / ETA** | Voyage Context Linear Extrapolation | **Available** | Rendered with linear estimate disclaimer | Labeled: `Application-level linear estimate. Not a hydrodynamic voyage predictor.` |
| **Operational Advisories** | Phase 10C.5 Advisory Engine | **Available** | Prioritized advisory list with telemetry evidence | Labeled: `👤 HUMAN REVIEW REQUIRED. Advisory only — No automated actuation.` |

---

## 2. Dashboard Architecture & Components

```text
                                 DRIVER DASHBOARD V1 (frontend/index.html)
                                                     │
               ┌─────────────────────────────────────┴─────────────────────────────────────┐
               ▼                                                                           ▼
      OPERATOR DASHBOARD (DriverDashboard.js)                         ENGINEERING DASHBOARD (EngineeringDashboard.js)
               │                                                                           │
   ┌───────────┴───────────┐                                                   ┌───────────┴───────────┐
   ▼                       ▼                                                   ▼                       ▼
Top Vessel Hero    Section Grid:                                        Engineering Scenario    10 Facade Operations:
& Live Status      - Speed & Engine State (SpeedEngineCard.js)          Workbench               - Simulate Voyage
                   - Voyage Progression & ETA (VoyageStatusCard.js)     (EngineeringWorkbench)  - Evaluate/Optimize Sizing
                   - Fuel & Battery Storage (EnergyCard.js)                                     - Sensitivity / Break-Even
                   - Climatological Solar (SolarCard.js)                                        - Speed Co-optimization
                   - Route Weather Telemetry (WeatherCard.js)                                   - CII Trajectory / Portfolio
                   - Prioritized Advisories (AdvisoryPanel.js)                                  - Dossier Export
```

### Component Breakdown
1. **`SpeedEngineCard.js`**:
   - `renderSpeedCard`: Displays Current SOG, COG, and Design Speed with full provenance, quality, and freshness tags. Contains the Recommended Speed field with the mandatory *"Speed co-optimization is an offline planning tool"* notice.
   - `renderEngineStateCard`: Presents the Main Engine Operational State with an indicator ring. If live engine telemetry is absent, it renders `ENGINE STATE UNKNOWN` with notice *"Live engine telemetry is not connected"*. Displays non-actuation policy notice.
2. **`EnergyCard.js`**:
   - `renderFuelCard`: Presents bunker fuel remaining, fuel burn rate, and tank capacity.
   - `renderBatteryCard`: Displays clean energy battery SOC, SOH, usable storage, and discharge power.
3. **`SolarCard.js`**:
   - Presents solar PV generation with the prominent label `CLIMATOLOGICAL SCENARIO ESTIMATE` and diurnal cycle uncertainty flags for multi-day voyages.
4. **`WeatherCard.js`**:
   - Displays atmospheric and marine telemetry (wind, waves, temperature, humidity, surface pressure, ocean currents) with source and quality indicators.
5. **`VoyageStatusCard.js`**:
   - Displays departure/arrival terminals, progress percentage, distance covered/remaining, and ETA with linear estimate disclaimers.
6. **`AdvisoryPanel.js`**:
   - Renders prioritized operational advisories with severity badges (`CRITICAL`, `WARNING`, `ADVISORY`, `INFO`), triggered rule IDs, supporting telemetry evidence, and the mandatory `👤 HUMAN REVIEW REQUIRED` badge.

---

## 3. Strict Safety & Semantic Invariants

1. **Zero Actuation / Non-Autonomous Design**:
   - The dashboard contains zero controls, buttons, sliders, or triggers to actuate the vessel's propulsion, engine ignition, throttle, rudder, or navigation trajectory.
   - All advisories and telemetry are decision-support aids for qualified marine officers.
2. **Strict Null Preservation (`null != 0`)**:
   - Missing, unmeasured, or disconnected telemetry fields display as `"Unavailable"` or `"No telemetry"`. Telemetry is never coerced or fabricated to `0.0`.
3. **Engine State Unknown Principle**:
   - Engine ON/OFF status is strictly reported as `UNKNOWN` in the absence of direct engine controller telemetry. The dashboard refuses to infer engine state from ship speed, fuel consumption rate, or route status.
4. **Offline Optimizer Semantic Isolation**:
   - Recommended speed is explicitly labeled `"Not available"` on the live operator dashboard, preserving the strict separation between the Phase 9 offline speed co-optimizer and real-time operations.

---

## 4. Verification & Audit Results

- **Node.js Frontend Test Suite (`frontend/tests/dashboard_v1.test.js`)**: **20 / 20 PASS (100%)**
- **Pytest Frontend Contracts Suite (`tests/test_frontend_contracts.py`)**: **9 / 9 PASS (100%)**
- **Backend Regression Suite**: **781 / 784 PASS** (0 logical/assertion failures; 3 known Phase 9 timing threshold alerts under heavy CPU load).
- **Canonical Model Integrity Hashes**: All 5 canonical models match baseline SHA-256 hashes.
- **Raw Data File Count**: Exactly **6,228 files** preserved.
- **Backend Code Modifications**: **0 backend files modified**.
