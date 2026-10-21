/**
 * frontend/pages/DriverDashboard.js — Native Virtual Maritime Simulator & Operational Dashboard
 * ==============================================================================================
 * Primary Bridge Driver Dashboard reorganized into a compact, professional maritime control-room interface:
 *   1. Compact persistent status bar: Simulator state, Telemetry freshness, Weather connection, Safety mode, NMEA standby.
 *   2. Compact vessel controls: Transport bar, speed/throttle lever, environment presets, collapsible heading.
 *   3. 6 Primary Cards:
 *        Card 1: Vessel & Route (map, position, speed, distance remaining, progress %, dynamic ETA)
 *        Card 2: Signal Agent (current status, highest-priority alert, required operator action, expandable details)
 *        Card 3: Fuel & Voyage (remaining fuel, burn rate, arrival estimate, collapsible financials)
 *        Card 4: Ocean Conditions (wind speed, wave height, current speed, source/freshness, expandable metrics)
 *        Card 5: Engine (shaft power, MCR load %, RPM, rated power 4500 kW, overload alerts)
 *        Card 6: Battery (SOC, usable energy kWh, SOH %, pack capacity)
 *   4. Collapsible Advanced Sections:
 *        - Route Weather Look-Ahead & Waypoint Forecast
 *        - Solar Clean Energy Budget
 *        - Bridge Decision Advisories Panel
 *        - Telemetry Audit History Log Table
 *        - Engineering Scenario Workbench
 * 
 * Strict Source Precedence & Safety:
 *   - In NATIVE SIMULATOR mode, VirtualVesselSimulator is the authoritative operational state.
 *   - Escravos (5.58° N, 5.18° E) -> Lagos (6.42° N, 3.42° E) corridor.
 *   - Decision support ONLY. Zero external actuators; Port 10111 strictly prohibited.
 *   - Every Signal Agent advisory displays "HUMAN REVIEW REQUIRED".
 */

import { OperatorApiClient } from "../api/operatorClient.js";
import { renderVesselControlsCard } from "../components/VesselControlsCard.js";
import { renderSignalAgentCard } from "../components/SignalAgentCard.js";
import { renderOceanConditionsCard } from "../components/OceanConditionsCard.js";
import { renderSpeedCard, renderEngineStateCard } from "../components/SpeedEngineCard.js";
import { renderFuelCard, renderBatteryCard } from "../components/EnergyCard.js";
import { renderSolarCard } from "../components/SolarCard.js";
import { renderWeatherCard } from "../components/WeatherCard.js";
import { renderVoyageStatusCard } from "../components/VoyageStatusCard.js";
import { renderRouteMapCard, MARITIME_ROUTES_CATALOG } from "../components/RouteMapCard.js";
import { renderAdvisoryPanel } from "../components/AdvisoryPanel.js";
import { renderTelemetryStatusBadge } from "../components/TelemetryStatusBadge.js";
import { renderEngineeringWorkbench } from "../components/EngineeringWorkbench.js?v=table_v2";

export class DriverDashboardPage {
  constructor(containerId, options = {}) {
    this.container = typeof document !== "undefined" ? document.getElementById(containerId) : null;
    this.apiClient = new OperatorApiClient(options.baseUrl || "");
    this.pollIntervalMs = options.pollIntervalMs || 15000;
    this.simPollIntervalMs = options.simPollIntervalMs || 1000;
    this.pollTimer = null;
    this.simPollTimer = null;
    this.unsubscribeStream = null;
    this.isFetching = false;
    this.isFetchingSim = false;
    this.activeScenario = "SIMULATOR"; // Default is Native Virtual Simulator
    this.streamState = "CONNECTING"; // CONNECTED, RECONNECTING, DISCONNECTED, WAITING
    this.recentHistory = []; // Bounded recent telemetry history buffer (max 10)
    this.travelledTrack = []; // History of coordinates for track polyline
    this.lastLookaheadQuery = { lat: null, lon: null, sog: null, timestamp: 0 };
    this.virtualSimState = null;
    this.activeRouteId = "ESC_LOS_01";
    this.mapLayersState = { corridor: true, track: true, vector: true };
    this.state = {
      loading: true,
      error: null,
      lastUpdatedUtc: null,
      operatorState: null,
      telemetryFrame: null,
      lookahead: null,
    };
  }

  async init() {
    // Initial immediate render so the operator dashboard never presents a blank view
    this.render();
    await this.fetchSimulatorState();
    if (this.activeScenario !== "SIMULATOR") {
      await this.fetchLatestState();
    }
    this.initStream();
    this.startPollingFallback();
    this.startSimPolling();
  }

  startSimPolling() {
    if (this.simPollTimer) clearInterval(this.simPollTimer);
    this.simPollTimer = setInterval(async () => {
      if (this.activeScenario === "SIMULATOR") {
        await this.fetchSimulatorState();
      }
    }, this.simPollIntervalMs);
  }

  initStream() {
    if (typeof EventSource !== "undefined") {
      this.unsubscribeStream = this.apiClient.subscribeTelemetryStream(
        (data) => {
          if (data && data.telemetry) {
            this.handleStreamFrame(data.telemetry);
          }
        },
        (err) => {
          if (this.activeScenario !== "SIMULATOR") {
            this.streamState = "RECONNECTING";
            this.renderStatusOnly();
          }
        },
        (status) => {
          if (this.activeScenario !== "SIMULATOR") {
            this.streamState = status;
            this.renderStatusOnly();
          }
        }
      );
    } else {
      if (this.activeScenario !== "SIMULATOR") {
        this.streamState = "DISCONNECTED";
      }
    }
  }

  async applySimulatorState(sim) {
    if (!sim) return;
    this.virtualSimState = sim;

    // Record travelled track point [lat, lon]
    if (sim.latitude !== undefined && sim.longitude !== undefined) {
      const lastPoint = this.travelledTrack[this.travelledTrack.length - 1];
      const curPt = [sim.latitude, sim.longitude];
      if (!lastPoint || Math.abs(lastPoint[0] - sim.latitude) > 0.0001 || Math.abs(lastPoint[1] - sim.longitude) > 0.0001) {
        this.travelledTrack.push(curPt);
        if (this.travelledTrack.length > 500) {
          this.travelledTrack.shift();
        }
      }
    }

    // Build canonical simulator telemetry frame
    const telFrame = {
      telemetry_id: sim.telemetry_id || "VIRT_TEL_FRAME",
      vessel_id: sim.vessel_id || "VESSEL_OSV_01",
      timestamp_utc: sim.timestamp_utc || new Date().toISOString(),
      position: {
        latitude: sim.latitude,
        longitude: sim.longitude,
        speed_over_ground_knots: sim.speed_over_ground_knots,
        course_over_ground_deg: sim.course_over_ground_deg,
        speed_through_water_knots: sim.speed_through_water_knots,
        heading_deg: sim.heading_deg,
        data_type: "SIMULATED",
      },
      engine: {
        state: sim.engine_state || (sim.status === "RUNNING" ? "ON" : "OFF"),
        rpm: sim.engine_rpm,
        load_percent: sim.engine_load_pct,
        fuel_rate_lph: sim.fuel_consumption_rate_lph,
      },
      energy: {
        battery_soc_pct: sim.battery_soc_pct,
        battery_soh_pct: sim.battery_soh_pct || 98.5,
        battery_usable_kwh: sim.battery_energy_kwh,
        solar_power_kw: sim.solar_power_kw,
        fuel_remaining_liters: sim.fuel_remaining_liters,
        fuel_rate_lph: sim.fuel_consumption_rate_lph,
      },
      quality: {
        overall: "VALID",
        freshness: "FRESH",
        freshness_age_seconds: 0.0,
      },
      provenance: {
        mode: "SIMULATED",
        source: "Virtual Vessel Simulator",
      },
    };

    if (this.activeScenario === "SIMULATOR") {
      this.state.telemetryFrame = telFrame;
      this.state.lastUpdatedUtc = sim.timestamp_utc || new Date().toISOString();
      this.streamState = "CONNECTED";
      this.state.error = null;

      // Append to bounded recent history buffer
      const timeFormatted = this.formatTimeOnly(sim.timestamp_utc);
      if (!this.recentHistory.length || this.recentHistory[0].time !== timeFormatted || this.recentHistory[0].lat !== sim.latitude) {
        this.recentHistory.unshift({
          time: timeFormatted,
          lat: sim.latitude,
          lon: sim.longitude,
          sog: sim.speed_over_ground_knots,
          engine: sim.engine_state || (sim.status === "RUNNING" ? "ON" : "OFF"),
          soc: sim.battery_soc_pct,
          fuel: sim.fuel_remaining_liters,
          mode: "SIMULATED",
          source: "Virtual Vessel Simulator",
        });
        if (this.recentHistory.length > 8) {
          this.recentHistory.pop();
        }
      }
    }

    this.render();
    if (this.activeScenario === "SIMULATOR") {
      await this.syncOperatorStateFromTelemetry(telFrame);
    }
  }

  async fetchSimulatorState() {
    if (this.isFetchingSim) return;
    this.isFetchingSim = true;
    try {
      const res = await this.apiClient.getSimulatorState();
      if (res.success && res.data) {
        await this.applySimulatorState(res.data);
      } else {
        this.render();
      }
    } catch (err) {
      console.warn("Simulator state fetch error:", err);
      this.render();
    } finally {
      this.isFetchingSim = false;
      this.state.loading = false;
    }
  }

  handleStreamFrame(telFrame) {
    if (this.activeScenario === "SIMULATOR") {
      return;
    }

    this.state.telemetryFrame = telFrame;
    this.state.lastUpdatedUtc = telFrame.timestamp_utc || new Date().toISOString();
    this.streamState = "CONNECTED";
    this.state.error = null;

    this.recentHistory.unshift({
      time: this.formatTimeOnly(telFrame.timestamp_utc),
      lat: telFrame.position?.latitude ?? null,
      lon: telFrame.position?.longitude ?? null,
      sog: telFrame.position?.speed_over_ground_knots ?? null,
      engine: telFrame.engine?.state ?? "UNKNOWN",
      soc: telFrame.energy?.battery_soc_pct ?? null,
      fuel: telFrame.energy?.fuel_remaining_liters ?? null,
      mode: telFrame.provenance?.mode ?? "OBSERVED",
      source: telFrame.provenance?.source ?? "Telemetry Gateway",
    });
    if (this.recentHistory.length > 8) {
      this.recentHistory.pop();
    }

    this.syncOperatorStateFromTelemetry(telFrame);
    this.render();
  }

  startPolling() {
    this.startSimPolling();
    this.startPollingFallback();
  }

  startPollingFallback() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = setInterval(() => {
      if (this.activeScenario !== "SIMULATOR" && this.streamState !== "CONNECTED") {
        this.fetchLatestState();
      }
    }, this.pollIntervalMs);
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    if (this.simPollTimer) {
      clearInterval(this.simPollTimer);
      this.simPollTimer = null;
    }
    if (this.unsubscribeStream) {
      this.unsubscribeStream();
      this.unsubscribeStream = null;
    }
  }

  async selectScenario(scenarioId) {
    this.activeScenario = scenarioId;
    this.state.loading = true;
    this.render();

    try {
      if (scenarioId === "SIMULATOR") {
        await this.fetchSimulatorState();
      } else {
        const res = await this.apiClient.getSimulatedScenario(scenarioId);
        if (res.success && res.data) {
          this.handleStreamFrame(res.data);
        } else {
          this.state.error = res.error || { message: `Failed to load scenario ${scenarioId}` };
        }
      }
    } catch (err) {
      this.state.error = { message: err.message || "Failed to load scenario" };
    } finally {
      this.state.loading = false;
      this.render();
    }
  }

  async syncOperatorStateFromTelemetry(telFrame) {
    try {
      const pos = telFrame.position || {};
      const eng = telFrame.engine || {};
      const nrg = telFrame.energy || {};

      const reqPayload = {
        vessel: {
          vessel_id: telFrame.vessel_id || "VESSEL_OSV_01",
          ship_type: "Oil Service Boat",
          design_speed_knots: 12.0,
          max_speed_knots: 14.5,
          displacement_tonnes: 2500.0,
          engine_power_kw: 4500.0,
          propulsion_type: "Diesel-Mechanical + Clean Auxiliary Hybrid",
          battery_pack_capacity_kwh: 650.0,
          solar_panel_size_m2: 80.0,
          fuel_price_usd_per_liter: 1.15,
        },
        route: {
          route_id: "Escravos-Lagos",
          origin_port: "Escravos Terminal",
          destination_port: "Lagos Port",
          total_distance_nm: 250.0,
          waypoints: [
            { waypoint_id: "WP1", latitude: 5.58, longitude: 5.18, sequence: 1 },
            { waypoint_id: "WP2", latitude: 5.80, longitude: 4.50, sequence: 2 },
            { waypoint_id: "WP3", latitude: 6.42, longitude: 3.42, sequence: 3 },
          ],
        },
        position: {
          latitude: pos.latitude ?? 5.58,
          longitude: pos.longitude ?? 5.18,
          timestamp_utc: telFrame.timestamp_utc,
          speed_over_ground_knots: pos.speed_over_ground_knots ?? null,
          course_over_ground_deg: pos.course_over_ground_deg ?? null,
          data_type: telFrame.provenance?.mode || "SIMULATED",
        },
        energy_state: {
          battery_soc_pct: nrg.battery_soc_pct ?? null,
          battery_soh_pct: nrg.battery_soh_pct ?? null,
          battery_energy_available_kwh: nrg.battery_usable_kwh ?? null,
          solar_power_kw: nrg.solar_power_kw ?? null,
          fuel_remaining_liters: nrg.fuel_remaining_liters ?? null,
          fuel_consumption_rate_lph: nrg.fuel_rate_lph ?? eng.fuel_rate_lph ?? null,
          provenance: telFrame.provenance?.mode || "SIMULATED",
        },
      };

      const res = await this.apiClient.getOperatorStateFromTelemetry(reqPayload);
      if (res.success && res.data) {
        this.state.operatorState = res.data;
      }

      await this.updateLookaheadIfAppropriate(reqPayload.position, reqPayload.route);
    } catch (e) {
      console.warn("Could not sync operator state from telemetry:", e);
    }
  }

  shouldRefreshLookahead(pos) {
    if (!this.lastLookaheadQuery.timestamp) return true;
    const now = Date.now();
    if (now - this.lastLookaheadQuery.timestamp >= 60000) return true;

    const lat = pos.latitude ?? null;
    const lon = pos.longitude ?? null;
    if (lat !== null && lon !== null && this.lastLookaheadQuery.lat !== null && this.lastLookaheadQuery.lon !== null) {
      const dLat = (lat - this.lastLookaheadQuery.lat) * 60.0;
      const dLon = (lon - this.lastLookaheadQuery.lon) * 60.0 * Math.cos((lat * Math.PI) / 180.0);
      const distNm = Math.sqrt(dLat * dLat + dLon * dLon);
      if (distNm >= 0.5) return true;
    }

    const sog = pos.speed_over_ground_knots ?? null;
    if (sog !== null && this.lastLookaheadQuery.sog !== null) {
      if (Math.abs(sog - this.lastLookaheadQuery.sog) >= 1.0) return true;
    } else if (sog !== this.lastLookaheadQuery.sog) {
      return true;
    }

    return false;
  }

  async updateLookaheadIfAppropriate(pos, route) {
    if (!this.shouldRefreshLookahead(pos)) return;
    try {
      const lookaheadReq = {
        position: {
          latitude: pos.latitude ?? 5.58,
          longitude: pos.longitude ?? 5.18,
          timestamp_utc: pos.timestamp_utc || new Date().toISOString(),
          speed_over_ground_knots: pos.speed_over_ground_knots ?? null,
          course_over_ground_deg: pos.course_over_ground_deg ?? null,
          data_type: pos.data_type || "SIMULATED",
        },
        route: route,
        vessel_id: "VESSEL_OSV_01",
        reference_time_utc: pos.timestamp_utc || new Date().toISOString(),
      };

      const res = await this.apiClient.getRouteWeatherLookahead(lookaheadReq);
      if (res.success && res.data) {
        this.state.lookahead = res.data;
        this.lastLookaheadQuery = {
          lat: pos.latitude ?? null,
          lon: pos.longitude ?? null,
          sog: pos.speed_over_ground_knots ?? null,
          timestamp: Date.now(),
        };
      }
    } catch (e) {
      console.warn("Could not update route weather lookahead:", e);
    }
  }

  async fetchLatestState() {
    if (this.isFetching) return;
    this.isFetching = true;

    try {
      const telRes = await this.apiClient.getCurrentTelemetry();
      if (telRes.success && telRes.data) {
        this.handleStreamFrame(telRes.data);
      } else {
        const reqPayload = {
          vessel_id: "VESSEL_OSV_01",
          ship_type: "Oil Service Boat",
          route_id: "Escravos-Lagos",
          current_position: {
            latitude: 5.58,
            longitude: 5.18,
            timestamp_utc: new Date().toISOString(),
            speed_over_ground_knots: 12.0,
          },
          include_weather: true,
        };
        const res = await this.apiClient.getOperatorState(reqPayload);
        if (res.success && res.data) {
          this.state.operatorState = res.data;
          this.state.lastUpdatedUtc = new Date().toISOString();
          this.state.error = null;
        } else {
          this.state.error = res.error || { message: `HTTP ${res.status} fetching operator state` };
        }
      }
    } catch (err) {
      this.state.error = { message: err.message || "Network connection failure" };
    } finally {
      this.state.loading = false;
      this.isFetching = false;
      this.render();
    }
  }

  formatTimeOnly(isoString) {
    if (!isoString) return new Date().toISOString().slice(11, 19);
    try {
      if (typeof isoString === "string" && isoString.includes("T")) {
        const parts = isoString.split("T");
        return parts[1].slice(0, 8);
      }
      if (typeof isoString === "string" && isoString.length >= 8 && isoString.includes(":")) {
        return isoString.slice(0, 8);
      }
      return String(isoString);
    } catch (e) {
      return String(isoString);
    }
  }

  renderStatusOnly() {
    const statusContainer = this.container?.querySelector(".dashboard-toolbar .toolbar-status");
    if (statusContainer) {
      const isSimMode = this.activeScenario === "SIMULATOR";
      const telQuality = this.state.telemetryFrame?.quality || {};
      const telProv = this.state.telemetryFrame?.provenance || {};
      const freshState = isSimMode ? "FRESH" : (telQuality.freshness || "FRESH");
      const provMode = isSimMode ? "SIMULATED" : (telProv.mode || "SIMULATED");
      const qualityState = isSimMode ? "VALID" : (telQuality.overall || "VALID");
      const ageSeconds = isSimMode ? 0.0 : (telQuality.freshness_age_seconds ?? null);
      const sourceName = isSimMode ? "Virtual Vessel Simulator" : (telProv.source || "Telemetry Gateway");

      const timeDisplay = this.state.lastUpdatedUtc
        ? `Last telemetry update: ${this.formatTimeOnly(this.state.lastUpdatedUtc)} UTC`
        : "Waiting for telemetry...";

      statusContainer.innerHTML = `
        ${renderTelemetryStatusBadge({
          freshness: freshState,
          provenanceMode: provMode,
          quality: qualityState,
          ageSeconds: ageSeconds,
          source: sourceName,
          streamState: isSimMode ? "CONNECTED" : this.streamState,
        })}
        <span class="sync-status-text">${escapeHtml(timeDisplay)}</span>
      `;
    }
  }

  async handleSimAction(action, payload = {}) {
    try {
      let res;
      if (action === "start") {
        res = await this.apiClient.startSimulation();
      } else if (action === "pause") {
        res = await this.apiClient.pauseSimulation();
      } else if (action === "reset") {
        this.travelledTrack = [];
        res = await this.apiClient.resetSimulation();
      } else if (action === "control") {
        res = await this.apiClient.setSimulatorControls(payload);
      }
      if (res && res.success && res.data) {
        await this.applySimulatorState(res.data);
      }
    } catch (e) {
      console.error("Simulation action failed:", e);
    }
  }

  async selectMaritimeRoute(routeId) {
    if (!MARITIME_ROUTES_CATALOG[routeId]) return;
    this.activeRouteId = routeId;
    const rObj = MARITIME_ROUTES_CATALOG[routeId];
    const departureWp = rObj.waypoints[0];
    const nextWp = rObj.waypoints[1] || rObj.waypoints[0];

    // Compute initial bearing towards next waypoint
    const lat1 = departureWp.latitude * Math.PI / 180;
    const lat2 = nextWp.latitude * Math.PI / 180;
    const dLon = (nextWp.longitude - departureWp.longitude) * Math.PI / 180;
    const y = Math.sin(dLon) * Math.cos(lat2);
    const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
    let initialHdg = Math.round((Math.atan2(y, x) * 180 / Math.PI + 360) % 360);

    this.travelledTrack = [[departureWp.latitude, departureWp.longitude]];

    if (this.virtualSimState) {
      this.virtualSimState.route_id = rObj.name;
      this.virtualSimState.origin_port = rObj.origin || departureWp.name;
      this.virtualSimState.destination_port = rObj.destination || rObj.waypoints[rObj.waypoints.length - 1].name;
      this.virtualSimState.latitude = departureWp.latitude;
      this.virtualSimState.longitude = departureWp.longitude;
      this.virtualSimState.heading_deg = initialHdg;
      this.virtualSimState.course_over_ground_deg = initialHdg;
      this.virtualSimState.total_distance_nm = rObj.distance_nm;
      this.virtualSimState.distance_remaining_nm = rObj.distance_nm;
      this.virtualSimState.distance_travelled_nm = 0.0;
      this.virtualSimState.route_progress_pct = 0.0;
      this.virtualSimState.travelled_track = [[departureWp.latitude, departureWp.longitude]];
    }

    try {
      await this.handleSimAction("control", {
        latitude: departureWp.latitude,
        longitude: departureWp.longitude,
        heading_deg: initialHdg,
        route_id: rObj.name,
        origin_port: rObj.origin || departureWp.name,
        destination_port: rObj.destination || rObj.waypoints[rObj.waypoints.length - 1].name,
        total_distance_nm: rObj.distance_nm,
      });
      await this.apiClient.refreshSimulatorWeather();
    } catch (err) {
      console.warn("Simulator backend route sync notice:", err);
    }

    this.render();
  }

  render() {
    if (!this.container && typeof document !== "undefined") {
      this.container = document.getElementById("view-driver-dashboard");
    }
    if (!this.container) return;

    const isSimMode = this.activeScenario === "SIMULATOR";
    const { loading, error, lastUpdatedUtc, operatorState, telemetryFrame } = this.state;
    const sim = this.virtualSimState || {};

    const timeDisplay = lastUpdatedUtc
      ? `Last update: ${this.formatTimeOnly(lastUpdatedUtc)} UTC`
      : "Waiting for telemetry...";

    // Extract Telemetry Frame details
    const telQuality = telemetryFrame?.quality || {};
    const telProv = telemetryFrame?.provenance || {};
    const telPos = telemetryFrame?.position || {};
    const telEng = telemetryFrame?.engine || {};
    const telEnergy = telemetryFrame?.energy || {};

    const freshState = isSimMode ? "FRESH" : (telQuality.freshness || "FRESH");
    const provMode = isSimMode ? "SIMULATED" : (telProv.mode || "SIMULATED");
    const qualityState = isSimMode ? "VALID" : (telQuality.overall || "VALID");
    const ageSeconds = isSimMode ? 0.0 : (telQuality.freshness_age_seconds ?? null);
    const sourceName = isSimMode ? "Virtual Vessel Simulator" : (telProv.source || "Telemetry Gateway");

    const isBridgeCommandLive = !isSimMode && (sourceName.includes("BRIDGE_COMMAND") || sourceName.includes("NMEA")) && freshState === "FRESH";

    // Extract Operator Contexts
    const vessel = operatorState?.vessel || null;
    const weather = operatorState?.weather || null;
    const energy = operatorState?.energy || null;
    const advisoriesObj = operatorState?.advisories || null;
    const advisoriesList = advisoriesObj?.advisories || (Array.isArray(operatorState?.advisories) ? operatorState.advisories : []);
    const metadata = operatorState?.metadata || null;
    const readiness = metadata?.readiness_state || metadata?.decision_readiness || "READY";

    // Navigation & Position strictly determined by active mode
    const pos = vessel?.current_position || null;
    const route = vessel?.route || null;
    const progress = vessel?.route_progress || null;

    // In Simulator Mode: Authoritative values strictly from simulator state
    const currentLat = isSimMode ? (sim.latitude ?? 5.58) : (telPos.latitude ?? pos?.latitude ?? 5.58);
    const currentLon = isSimMode ? (sim.longitude ?? 5.18) : (telPos.longitude ?? pos?.longitude ?? 5.18);
    const currentSog = isSimMode ? (sim.speed_over_ground_knots ?? 12.0) : (telPos.speed_over_ground_knots ?? pos?.speed_over_ground_knots ?? null);
    const currentCog = isSimMode ? (sim.course_over_ground_deg ?? 285.0) : (telPos.course_over_ground_deg ?? pos?.course_over_ground_deg ?? null);
    const currentHdg = isSimMode ? (sim.heading_deg ?? 285.0) : (telPos.heading_deg ?? 285.0);
    const currentStw = isSimMode ? (sim.speed_through_water_knots ?? 12.0) : (telPos.speed_through_water_knots ?? currentSog ?? 12.0);
    const targetSpeed = isSimMode ? (sim.target_speed_knots ?? 12.0) : 12.0;
    const throttlePct = isSimMode ? (sim.throttle_pct ?? 75.0) : 75.0;
    const simStatus = sim.status || "IDLE";
    
    // Environmental conditions: extract from simulator ocean_conditions
    const ocean = isSimMode ? (sim.ocean_conditions || sim.ocean || null) : null;
    const signalAgent = isSimMode ? (sim.signal_agent || null) : null;

    const designSpeed = vessel?.design_speed_knots ?? 12.0;

    // Engine Telemetry & Powertrain (Canonical Oil Service Boat rating is 4500 kW from ship_profiles.csv)
    const installedPower = Number(sim.rated_engine_power_kw || vessel?.engine_power_kw || 4500.0);
    const shaftPower = isSimMode ? (sim.shaft_power_kw ?? null) : (telEng.power_kw ?? null);
    const engineState = isSimMode ? (sim.engine_state || (simStatus === "RUNNING" ? "ON" : "OFF")) : (telEng.state || "UNKNOWN");
    const engineRpm = isSimMode ? (sim.engine_rpm ?? 1450.0) : (telEng.rpm ?? null);
    
    // Engine MCR Load %
    let engineLoad = null;
    if (isSimMode) {
      if (sim.engine_load_pct !== undefined && sim.engine_load_pct !== null) {
        engineLoad = Number(sim.engine_load_pct);
      } else if (shaftPower !== null && installedPower > 0) {
        engineLoad = Number(((shaftPower / installedPower) * 100.0).toFixed(1));
      }
    } else {
      if (telEng.load_percent !== undefined && telEng.load_percent !== null) {
        engineLoad = Number(telEng.load_percent);
      } else if (shaftPower !== null && installedPower > 0) {
        engineLoad = Number(((shaftPower / installedPower) * 100.0).toFixed(1));
      }
    }
    const propulsionType = vessel?.propulsion_type || "Diesel-Mechanical + Clean Auxiliary Hybrid";

    // Fuel & Battery metrics
    const fuelRemaining = isSimMode ? (sim.fuel_remaining_liters ?? 25000.0) : (telEnergy.fuel_remaining_liters ?? energy?.fuel_remaining_liters ?? null);
    const fuelRate = isSimMode ? (sim.fuel_consumption_rate_lph ?? sim.fuel_rate_lph ?? 142.5) : (telEnergy.fuel_rate_lph ?? telEng.fuel_rate_lph ?? energy?.fuel_consumption_rate_lph ?? null);
    const fuelConsumed = isSimMode ? (sim.fuel_consumed_liters ?? null) : null;
    const fuelPrice = vessel?.fuel_price_usd_per_liter ?? 1.15;

    const socPct = isSimMode ? (sim.battery_soc_pct ?? 85.0) : (telEnergy.battery_soc_pct ?? energy?.battery_soc_pct ?? null);
    const sohPct = isSimMode ? (sim.battery_soh_pct ?? 98.5) : (telEnergy.battery_soh_pct ?? energy?.battery_soh_pct ?? null);
    const usableBatt = isSimMode ? (sim.battery_usable_kwh ?? sim.battery_energy_kwh ?? 552.2) : (telEnergy.battery_usable_kwh ?? energy?.battery_energy_available_kwh ?? null);
    const nomBatt = vessel?.battery_pack_capacity_kwh ?? 650.0;

    // Solar metrics
    const estSolarKwh = energy?.solar_energy_today_kwh ?? 145.0;
    const solarM2 = vessel?.solar_panel_size_m2 ?? 80.0;
    const ghiVal = weather?.departure_weather?.daily_ghi_kwh_per_m2 ?? 4.85;

    // Dynamic weather context for simulator mode
    const simWeatherContext = ocean ? {
      departure_weather: {
        latitude: currentLat,
        longitude: currentLon,
        wind_speed_knots: ocean.wind_speed_knots,
        wind_direction_deg: ocean.wind_direction_deg,
        wave_height_m: ocean.wave_height_m,
        wave_period_s: ocean.wave_period_s,
        wave_direction_deg: ocean.wave_direction_deg,
        temperature_c: ocean.air_temperature_c,
        relative_humidity_pct: ocean.humidity_pct,
        surface_pressure_hpa: ocean.pressure_hpa,
        current_speed_knots: ocean.current_speed_knots,
        current_direction_deg: ocean.current_direction_deg,
        data_source: ocean.weather_source || (ocean.environmental_mode === "MANUAL_SCENARIO" ? "Manual Scenario Preset" : "Open-Meteo API"),
        timestamp_utc: ocean.source_timestamp_utc || lastUpdatedUtc,
      },
      environmental_mode: ocean.environmental_mode,
      vessel_latitude: currentLat,
      vessel_longitude: currentLon,
      weather_provenance: ocean.environmental_mode === "MANUAL_SCENARIO" ? "SIMULATED" : (ocean.provenance || "FORECAST"),
      weather_quality: ocean.weather_freshness === "DEGRADED" ? "PARTIAL" : "VALID",
      weather_freshness: ocean.weather_freshness || "FRESH",
      weather_timestamp_utc: ocean.source_timestamp_utc || lastUpdatedUtc,
      lookahead: this.state.lookahead,
    } : null;

    const activeRouteObj = MARITIME_ROUTES_CATALOG[this.activeRouteId] || MARITIME_ROUTES_CATALOG["ESC_LOS_01"];
    const routeTotalDist = activeRouteObj?.distance_nm ?? 250.0;
    const timelineContext = {
      remaining_distance_nm: isSimMode ? (sim.distance_remaining_nm ?? routeTotalDist) : (progress?.distance_remaining_nm ?? routeTotalDist),
      progress_pct: isSimMode ? (sim.route_progress_pct ?? 0.0) : (progress?.route_progress_pct ?? 0.0),
      estimated_arrival_utc: isSimMode ? (sim.eta_utc ?? "Calculated dynamically") : (progress?.eta_utc ?? "Calculated dynamically"),
    };

    // Preserve carousel scroll position across polling re-renders
    const existingTrack = this.container.querySelector("#telemetry-carousel-track, .card-slider");
    if (existingTrack) {
      this._savedCarouselScrollLeft = existingTrack.scrollLeft;
    }

    this.container.innerHTML = `
      <div class="driver-dashboard-v1 compact-control-room">
        <!-- A. Compact Persistent Status Bar -->
        <div class="system-status-bar compact-bar">
          <div class="system-status-item">
            <span class="system-status-label">Simulator:</span>
            <span class="system-status-value ${simStatus === 'RUNNING' ? 'val-running' : (simStatus === 'PAUSED' ? 'val-waiting' : 'val-active')}">
              ${simStatus === 'RUNNING' ? '● RUNNING' : (simStatus === 'PAUSED' ? '⏸ PAUSED' : '○ READY')}
            </span>
          </div>
          <div class="system-status-item">
            <span class="system-status-label">Telemetry:</span>
            <span class="system-status-value val-${freshState.toLowerCase()}">${escapeHtml(freshState)}</span>
          </div>
          <div class="system-status-item">
            <span class="system-status-label">Weather:</span>
            <span class="system-status-value ${ocean?.environmental_mode === 'MANUAL_SCENARIO' ? 'val-waiting' : 'val-active'}">
              ${ocean?.environmental_mode === 'MANUAL_SCENARIO' ? 'MANUAL PRESET' : 'OPEN-METEO FORECAST'}
            </span>
          </div>
          <div class="system-status-item">
            <span class="system-status-label">Safety:</span>
            <span class="system-status-value val-safe" title="Zero physical actuators connected. Port 10111 prohibited. Decision support only.">
              🛡️ READ-ONLY (0 ACTUATORS)
            </span>
          </div>
          <div class="system-status-item">
            <span class="system-status-label">NMEA:</span>
            <span class="system-status-value ${isBridgeCommandLive ? 'val-connected' : 'val-safe'}">
              ${isBridgeCommandLive ? 'LIVE (:10110)' : 'STANDBY (:10110)'}
            </span>
          </div>
          <div class="system-status-item ms-auto">
            <span class="sync-status-text">${escapeHtml(timeDisplay)}</span>
          </div>
        </div>

        <!-- Top Scenario Toolbar -->
        <div class="dashboard-toolbar compact-toolbar">
          <div class="toolbar-status">
            ${renderTelemetryStatusBadge({
              freshness: freshState,
              provenanceMode: provMode,
              quality: qualityState,
              ageSeconds: ageSeconds,
              source: sourceName,
              streamState: isSimMode ? "CONNECTED" : this.streamState,
            })}
          </div>

          <div class="toolbar-actions">
            <div class="scenario-selector-group">
              <label for="scenario-select" class="scenario-label">Mode:</label>
              <select id="scenario-select" class="form-select scenario-dropdown">
                <option value="SIMULATOR" ${this.activeScenario === "SIMULATOR" ? "selected" : ""}>Native Virtual Vessel Simulator (Primary)</option>
                <option value="A" ${this.activeScenario === "A" ? "selected" : ""}>Scenario A: Normal Telemetry</option>
                <option value="B" ${this.activeScenario === "B" ? "selected" : ""}>Scenario B: Engine OFF</option>
                <option value="C" ${this.activeScenario === "C" ? "selected" : ""}>Scenario C: Engine UNKNOWN</option>
                <option value="D" ${this.activeScenario === "D" ? "selected" : ""}>Scenario D: Missing Speed</option>
                <option value="E" ${this.activeScenario === "E" ? "selected" : ""}>Scenario E: Stale Telemetry</option>
                <option value="F" ${this.activeScenario === "F" ? "selected" : ""}>Scenario F: Expired Telemetry</option>
                <option value="G" ${this.activeScenario === "G" ? "selected" : ""}>Scenario G: Disconnected</option>
                <option value="H" ${this.activeScenario === "H" ? "selected" : ""}>Scenario H: Invalid Quarantined</option>
              </select>
            </div>

            <button id="btn-manual-refresh" class="btn btn-secondary btn-sm ${loading ? 'disabled' : ''}">
              🔄 Refresh
            </button>
          </div>
        </div>

        ${!isSimMode ? `
          <div class="alert-banner alert-warning py-1 my-1">
            <span class="alert-icon">ℹ️</span>
            <div class="alert-content">
              <strong>TELEMETRY SCENARIO SIMULATION (${escapeHtml(this.activeScenario)}):</strong> Viewing simulated test stream. Switch to <em>Native Virtual Vessel Simulator</em> to command virtual vessel.
            </div>
          </div>
        ` : ''}

        ${error ? `
          <div class="alert-banner alert-danger py-1 my-1">
            <span class="alert-icon">⚠️</span>
            <div class="alert-content">
              <strong>Notice:</strong> ${escapeHtml(error.message || JSON.stringify(error))}
            </div>
          </div>
        ` : ''}

        <!-- B. Compact Vessel Controls Cockpit -->
        <div class="mb-3">
          ${renderVesselControlsCard({
            status: simStatus,
            targetSpeedKnots: targetSpeed,
            throttlePct: throttlePct,
            headingDeg: currentHdg,
            speedThroughWaterKnots: currentStw,
            waveHeightM: ocean?.wave_height_m ?? 1.4,
            windSpeedKnots: ocean?.wind_speed_knots ?? 16.5,
            currentSpeedKnots: ocean?.current_speed_knots ?? 0.6,
            environmentalMode: ocean?.environmental_mode ?? "AUTOMATIC_FORECAST",
          })}
        </div>

        <!-- 3. SPATIAL NAUTICAL CHART & CORRIDOR -->
        <div class="nautical-chart-section mb-3">
          ${renderRouteMapCard({
            vessel,
            position: {
              latitude: currentLat,
              longitude: currentLon,
              speed_over_ground_knots: currentSog,
              course_over_ground_deg: currentCog,
              heading_deg: currentHdg,
            },
            route,
            lookahead: this.state.lookahead,
            recentHistory: this.recentHistory,
            travelledTrack: isSimMode ? (this.travelledTrack.length > 0 ? this.travelledTrack : (sim.travelled_track || [[currentLat, currentLon]])) : [],
            timeline: timelineContext,
            activeRouteId: this.activeRouteId || "ESC_LOS_01",
          })}
        </div>

        <!-- 4. HORIZONTAL CARD SLIDER / CAROUSEL FOR TELEMETRY & MODULES -->
        <div class="telemetry-carousel-container">
          <div class="telemetry-carousel-header">
            <span class="carousel-title">OPERATIONAL TELEMETRY &amp; DECISION SUPPORT</span>
            <div class="carousel-nav-controls">
              <button id="btn-carousel-prev" class="carousel-nav-btn" title="Scroll Left" aria-label="Previous Cards">◀</button>
              <button id="btn-carousel-next" class="carousel-nav-btn" title="Scroll Right" aria-label="Next Cards">▶</button>
            </div>
          </div>

          <div id="telemetry-carousel-track" class="telemetry-carousel-track card-slider">
            <!-- CARD 1: Ocean & Environmental Forces -->
            <div class="carousel-card-item card-ocean">
              ${renderOceanConditionsCard(ocean)}
            </div>

            <!-- CARD 2: Main Engine Operational State -->
            <div class="carousel-card-item card-engine">
              ${renderEngineStateCard({
                engineState: engineState,
                engineRpm: engineRpm,
                engineLoadPct: engineLoad,
                installedPowerKw: installedPower,
                shaftPowerKw: shaftPower,
                shaftPowerDemandKw: isSimMode ? (sim.shaft_power_demand_kw ?? shaftPower) : shaftPower,
                propulsionType: propulsionType,
                provenance: isSimMode ? "SIMULATED" : (engineState === "UNKNOWN" ? "UNAVAILABLE" : (isBridgeCommandLive ? "OBSERVED" : "SIMULATED")),
                timestamp: lastUpdatedUtc,
              })}
            </div>

            <!-- CARD 3: Clean Energy Battery Storage -->
            <div class="carousel-card-item card-battery">
              ${renderBatteryCard({
                batterySocPct: socPct,
                batterySohPct: sohPct,
                batteryEnergyAvailableKwh: usableBatt,
                nominalCapacityKwh: nomBatt,
                provenance: "DERIVED",
                source: "Virtual Energy Estimator",
                timestamp: lastUpdatedUtc,
              })}
            </div>

            <!-- CARD 4: Bunker Fuel Telemetry -->
            <div class="carousel-card-item card-fuel">
              ${renderFuelCard({
                fuelRemainingLiters: fuelRemaining,
                fuelConsumptionRateLph: fuelRate,
                fuelPriceUsdPerLiter: fuelPrice,
                fuelType: "Diesel",
                provenance: "DERIVED",
                source: "Virtual Energy Estimator",
                timestamp: lastUpdatedUtc,
                etaUtc: isSimMode ? (sim.eta_utc ? this.formatTimeOnly(sim.eta_utc) + " UTC" : "Calculating...") : "In transit",
                fuelConsumedLiters: fuelConsumed,
              })}
            </div>

            <!-- CARD 5: Signal Agent Decision Support -->
            <div class="carousel-card-item card-signal-agent">
              ${renderSignalAgentCard(signalAgent)}
            </div>

            <!-- CARD 6: Route Weather Look-Ahead & Spatial Forecast -->
            <div class="carousel-card-item card-lookahead">
              ${renderWeatherCard(isSimMode ? simWeatherContext : (weather ? { ...weather, lookahead: this.state.lookahead } : (this.state.lookahead ? { lookahead: this.state.lookahead } : null)))}
            </div>

            <!-- CARD 7: Solar PV Array & Climatological Energy Budget -->
            <div class="carousel-card-item card-solar">
              ${renderSolarCard({
                estimatedSolarKwh: estSolarKwh,
                panelSizeM2: solarM2,
                panelEfficiencyPct: 21.5,
                dailyGhiKwhM2: ghiVal,
                diurnalUncertaintyFlag: false,
                source: "NASA POWER Climatology",
                provenance: "CLIMATOLOGICAL_ESTIMATE",
              })}
            </div>

            <!-- CARD 8: Bridge Decision Advisories & Governance Panel -->
            <div class="carousel-card-item card-advisories">
              ${renderAdvisoryPanel(advisoriesList, readiness === 'PARTIAL' ? 'OPERATIONAL' : readiness)}
            </div>

            <!-- CARD 9: Real-Time Telemetry Audit History -->
            <div class="carousel-card-item card-audit-history">
              ${renderAuditHistoryTable(this.recentHistory)}
            </div>
          </div>
        </div>

        <!-- COLLAPSIBLE ENGINEERING SCENARIO WORKBENCH (INTEGRATED) -->
        <div class="collapsible-sections-wrapper mt-3">
          <details class="dashboard-collapsible-section">
            <summary class="collapsible-section-summary">
              <span>⚙️ Engineering Scenario Workbench (10 Integrated Operations)</span>
              <span class="summary-badge">Offline Analysis &amp; Sizing Optimization</span>
            </summary>
            <div class="collapsible-section-content mt-2">
              ${renderEngineeringWorkbench({})}
            </div>
          </details>
        </div>
      </div>
    `;

    // Attach Event Listeners safely
    try {
      this.attachEventListeners(targetSpeed, currentHdg);
    } catch (evtErr) {
      console.warn("Event listeners attachment warning:", evtErr);
    }
  }

  attachEventListeners(currentTargetSpeed, currentHeading) {
    // Toolbar controls
    this.container.querySelector("#btn-manual-refresh")?.addEventListener("click", async () => {
      if (this.activeScenario === "SIMULATOR") {
        await this.apiClient.refreshSimulatorWeather();
        await this.fetchSimulatorState();
      } else {
        await this.fetchLatestState();
      }
    });
    this.container.querySelector("#scenario-select")?.addEventListener("change", (e) => this.selectScenario(e.target.value));

    // Active Route Selection Dropdown (10 West African Corridors)
    const routeSelect = this.container.querySelector("#select-active-route");
    routeSelect?.addEventListener("change", async (e) => {
      const newRouteId = e.target.value;
      await this.selectMaritimeRoute(newRouteId);
    });

    // Simulator transport buttons
    this.container.querySelector("#btn-sim-start")?.addEventListener("click", () => this.handleSimAction("start"));
    this.container.querySelector("#btn-sim-pause")?.addEventListener("click", () => this.handleSimAction("pause"));
    this.container.querySelector("#btn-sim-reset")?.addEventListener("click", () => this.handleSimAction("reset"));

    // Throttle & Speed Slider
    const throttleSlider = this.container.querySelector("#slider-throttle");
    throttleSlider?.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      const disp = this.container.querySelector("#disp-target-speed");
      if (disp) {
        const estSpeed = (val / 100.0) * 14.5;
        disp.textContent = `${estSpeed.toFixed(1)} kn (${val.toFixed(0)}%)`;
      }
    });
    throttleSlider?.addEventListener("change", (e) => {
      const val = parseFloat(e.target.value);
      this.handleSimAction("control", { throttle_pct: val });
    });

    // Speed steppers
    this.container.querySelector("#btn-speed-minus-1")?.addEventListener("click", () => {
      const newSpd = Math.max(0.0, currentTargetSpeed - 1.0);
      this.handleSimAction("control", { target_speed_knots: newSpd });
    });
    this.container.querySelector("#btn-speed-minus-05")?.addEventListener("click", () => {
      const newSpd = Math.max(0.0, currentTargetSpeed - 0.5);
      this.handleSimAction("control", { target_speed_knots: newSpd });
    });
    this.container.querySelector("#btn-speed-plus-05")?.addEventListener("click", () => {
      const newSpd = Math.min(14.5, currentTargetSpeed + 0.5);
      this.handleSimAction("control", { target_speed_knots: newSpd });
    });
    this.container.querySelector("#btn-speed-plus-1")?.addEventListener("click", () => {
      const newSpd = Math.min(14.5, currentTargetSpeed + 1.0);
      this.handleSimAction("control", { target_speed_knots: newSpd });
    });

    // Heading Slider
    const hdgSlider = this.container.querySelector("#slider-heading");
    hdgSlider?.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      const disp = this.container.querySelector("#disp-heading");
      if (disp) disp.textContent = `${Math.round(val)}° T`;
    });
    hdgSlider?.addEventListener("change", (e) => {
      const val = parseFloat(e.target.value);
      this.handleSimAction("control", { heading_deg: val });
    });

    // Heading steppers
    this.container.querySelector("#btn-hdg-minus-5")?.addEventListener("click", () => {
      const newHdg = (currentHeading - 5.0 + 360.0) % 360.0;
      this.handleSimAction("control", { heading_deg: newHdg });
    });
    this.container.querySelector("#btn-hdg-minus-1")?.addEventListener("click", () => {
      const newHdg = (currentHeading - 1.0 + 360.0) % 360.0;
      this.handleSimAction("control", { heading_deg: newHdg });
    });
    this.container.querySelector("#btn-hdg-corridor")?.addEventListener("click", () => {
      this.handleSimAction("control", { heading_deg: 285.0 });
    });
    this.container.querySelector("#btn-hdg-plus-1")?.addEventListener("click", () => {
      const newHdg = (currentHeading + 1.0) % 360.0;
      this.handleSimAction("control", { heading_deg: newHdg });
    });
    this.container.querySelector("#btn-hdg-plus-5")?.addEventListener("click", () => {
      const newHdg = (currentHeading + 5.0) % 360.0;
      this.handleSimAction("control", { heading_deg: newHdg });
    });

    // Environmental Presets
    this.container.querySelector("#btn-env-auto")?.addEventListener("click", () => {
      this.handleSimAction("control", { environmental_mode: "AUTOMATIC_FORECAST" });
    });
    this.container.querySelector("#btn-env-calm")?.addEventListener("click", () => {
      this.handleSimAction("control", { wave_height_m: 0.8, wind_speed_knots: 8.0, current_speed_knots: 0.4, current_direction_deg: 120.0 });
    });
    this.container.querySelector("#btn-env-moderate")?.addEventListener("click", () => {
      this.handleSimAction("control", { wave_height_m: 1.4, wind_speed_knots: 16.5, current_speed_knots: 0.6, current_direction_deg: 120.0 });
    });
    this.container.querySelector("#btn-env-rough")?.addEventListener("click", () => {
      this.handleSimAction("control", { wave_height_m: 3.2, wind_speed_knots: 30.0, current_speed_knots: 0.8, current_direction_deg: 120.0 });
    });
    this.container.querySelector("#btn-env-current")?.addEventListener("click", () => {
      this.handleSimAction("control", { wave_height_m: 1.5, wind_speed_knots: 15.0, current_speed_knots: 1.5, current_direction_deg: 105.0 });
    });

    // Telemetry Carousel Navigation Controls
    const carouselTrack = this.container.querySelector("#telemetry-carousel-track, .card-slider");
    if (carouselTrack) {
      if (typeof this._savedCarouselScrollLeft === "number" && this._savedCarouselScrollLeft > 0) {
        // Immediate static restoration to prevent any continuous auto-sliding animation during telemetry polls
        carouselTrack.style.scrollBehavior = "auto";
        carouselTrack.scrollLeft = this._savedCarouselScrollLeft;
      }
      carouselTrack.addEventListener("scroll", () => {
        this._savedCarouselScrollLeft = carouselTrack.scrollLeft;
      }, { passive: true });
    }

    this.container.querySelector("#btn-carousel-prev")?.addEventListener("click", () => {
      const card = carouselTrack?.querySelector(".carousel-card-item");
      if (!carouselTrack || !card) return;
      const scrollAmount = card.offsetWidth + 20;
      carouselTrack.scrollBy({ left: -scrollAmount, behavior: "smooth" });
    });

    this.container.querySelector("#btn-carousel-next")?.addEventListener("click", () => {
      const card = carouselTrack?.querySelector(".carousel-card-item");
      if (!carouselTrack || !card) return;
      const scrollAmount = card.offsetWidth + 20;
      carouselTrack.scrollBy({ left: scrollAmount, behavior: "smooth" });
    });

    // Nautical Map Layer Toggle Buttons
    this.container.querySelector("#toggle-corridor-route")?.addEventListener("click", (e) => {
      this.mapLayersState.corridor = !this.mapLayersState.corridor;
      e.currentTarget.classList.toggle("active", this.mapLayersState.corridor);
      e.currentTarget.classList.toggle("inactive", !this.mapLayersState.corridor);
      this.updateMapLayers();
    });

    this.container.querySelector("#toggle-spatial-track")?.addEventListener("click", (e) => {
      this.mapLayersState.track = !this.mapLayersState.track;
      e.currentTarget.classList.toggle("active", this.mapLayersState.track);
      e.currentTarget.classList.toggle("inactive", !this.mapLayersState.track);
      this.updateMapLayers();
    });

    this.container.querySelector("#toggle-live-vector")?.addEventListener("click", (e) => {
      this.mapLayersState.vector = !this.mapLayersState.vector;
      e.currentTarget.classList.toggle("active", this.mapLayersState.vector);
      e.currentTarget.classList.toggle("inactive", !this.mapLayersState.vector);
      this.updateMapLayers();
    });
  }

  updateMapLayers() {
    // Vector SVG map is rendered reactively in render()
  }
}

export function renderExactTimestamp(isoString) {
  if (!isoString) return "N/A";
  return String(isoString);
}

export function renderAuditHistoryTable(records = []) {
  return `
    <div class="dashboard-card telemetry-history-card">
      <div class="card-header">
        <div class="card-title-group">
          <h3>TELEMETRY AUDIT LOG</h3>
          <span class="card-subtitle">Real-time persistent audit snapshots</span>
        </div>
        <span class="meta-tag meta-prov prov-simulated">AUDIT LOG</span>
      </div>
      <div class="card-body">
        <div class="telemetry-history-table-wrapper">
          <table class="telemetry-history-table">
            <thead>
              <tr>
                <th>Record ID / Time (UTC)</th>
                <th>Vessel</th>
                <th>SOG (kn)</th>
                <th>Engine</th>
                <th>Battery SOC (%)</th>
                <th>Quality / Mode</th>
              </tr>
            </thead>
            <tbody>
              ${records && records.length > 0 ? records.map(row => {
                const timeStr = row.time || row.timestamp_utc || "N/A";
                const recId = row.record_id || row.telemetry_id || "";
                const vessel = row.vessel_id || row.vessel || "VESSEL_OSV_01";
                const sogVal = row.sog !== undefined ? row.sog : row.speed_over_ground_knots;
                const engState = row.engine || row.engine_state || "ON";
                const socVal = row.soc !== undefined ? row.soc : row.battery_soc_pct;
                const modeVal = row.mode || "SIMULATED";
                const qualVal = row.quality_state || row.quality || "VALID";

                return `
                  <tr>
                    <td><code>${escapeHtml(recId ? `${recId} | ` : '')}${escapeHtml(renderExactTimestamp(timeStr))}</code></td>
                    <td>${escapeHtml(vessel)}</td>
                    <td>${sogVal !== null && sogVal !== undefined ? `${Number(sogVal).toFixed(1)} kn` : '<span class="val-unavailable">N/A</span>'}</td>
                    <td><span class="status-pill status-${String(engState).toLowerCase()}">${escapeHtml(engState)}</span></td>
                    <td>${socVal !== null && socVal !== undefined ? `${Number(socVal).toFixed(1)}%` : '<span class="val-unavailable">N/A</span>'}</td>
                    <td>
                      <span class="status-pill status-${String(qualVal).toLowerCase()}">${escapeHtml(qualVal)}</span>
                      <span class="meta-tag meta-prov prov-${String(modeVal).toLowerCase()}">${escapeHtml(modeVal)}</span>
                    </td>
                  </tr>
                `;
              }).join("") : `
                <tr>
                  <td colspan="6" class="empty-history-cell">No telemetry records found.</td>
                </tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
