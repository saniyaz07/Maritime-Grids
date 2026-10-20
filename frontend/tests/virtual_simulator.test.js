/**
 * frontend/tests/virtual_simulator.test.js — Native Virtual Vessel Simulator & Signal Agent Tests
 * ==============================================================================================
 * Comprehensive tests for:
 *   1. VesselControlsCard rendering (controls, transport, sliders, steppers, presets)
 *   2. SignalAgentCard decision support presentation (NORMAL, WEATHER_ALERT, FUEL_ALERT, HUMAN REVIEW REQUIRED)
 *   3. OceanConditionsCard marine forces rendering (Wind, Waves, Currents, Temperature)
 *   4. OperatorApiClient virtual simulator endpoints
 *   5. Non-actuation & Safety verification (Zero external actuators, no port 10111)
 */

import test from "node:test";
import assert from "node:assert/strict";
import { renderVesselControlsCard } from "../components/VesselControlsCard.js";
import { renderSignalAgentCard } from "../components/SignalAgentCard.js";
import { renderOceanConditionsCard } from "../components/OceanConditionsCard.js";
import { OperatorApiClient } from "../api/operatorClient.js";

test("1. VesselControlsCard: renders transport buttons and control displays", () => {
  const html = renderVesselControlsCard({
    status: "RUNNING",
    targetSpeedKnots: 12.0,
    throttlePct: 75.0,
    headingDeg: 285.0,
    speedThroughWaterKnots: 12.0,
    waveHeightM: 1.4,
    windSpeedKnots: 16.5,
    currentSpeedKnots: 0.6,
  });

  assert.ok(html.includes("START VOYAGE"));
  assert.ok(html.includes("PAUSE"));
  assert.ok(html.includes("RESET VOYAGE"));
  assert.ok(html.includes("12.0 kn"));
  assert.ok(html.includes("75%"));
  assert.ok(html.includes("285° T"));
  assert.ok(html.includes("slider-throttle"));
  assert.ok(html.includes("slider-heading"));
  assert.ok(html.includes("btn-env-calm"));
  assert.ok(html.includes("btn-env-rough"));
});

test("2. SignalAgentCard: renders NORMAL status and mandatory HUMAN REVIEW REQUIRED badge", () => {
  const signalAgent = {
    status: "NORMAL",
    severity: "INFO",
    headline: "Vessel operating within normal hydrodynamic parameters.",
    details: [
      "Propulsion speed: 12.0 kn",
      "Calm sea state (Hs: 1.2m)",
      "Battery SOC healthy at 82.0%",
    ],
  };

  const html = renderSignalAgentCard(signalAgent);
  assert.ok(html.includes("NORMAL"));
  assert.ok(html.includes("HUMAN REVIEW REQUIRED"));
  assert.ok(html.includes("Vessel operating within normal hydrodynamic parameters."));
  assert.ok(html.includes("Propulsion speed: 12.0 kn"));
  assert.ok(html.includes("badge-success"));
});

test("3. SignalAgentCard: renders WEATHER_ALERT and FUEL_ALERT with high-visibility badges", () => {
  const weatherAlert = {
    status: "WEATHER_ALERT",
    severity: "WARNING",
    headline: "Adverse sea state encountered. Wave height exceeds 2.5m.",
    details: ["Added wave resistance increases fuel consumption rate to 185.0 L/h."],
  };

  const htmlWeather = renderSignalAgentCard(weatherAlert);
  assert.ok(htmlWeather.includes("WEATHER_ALERT"));
  assert.ok(htmlWeather.includes("badge-warning"));
  assert.ok(htmlWeather.includes("HUMAN REVIEW REQUIRED"));

  const fuelAlert = {
    status: "FUEL_ALERT",
    severity: "CRITICAL",
    headline: "Bunker fuel reserve critically low (< 500 L).",
    details: ["Immediate bunkering or speed reduction recommended."],
  };

  const htmlFuel = renderSignalAgentCard(fuelAlert);
  assert.ok(htmlFuel.includes("FUEL_ALERT"));
  assert.ok(htmlFuel.includes("badge-danger"));
  assert.ok(htmlFuel.includes("HUMAN REVIEW REQUIRED"));
});

test("4. OceanConditionsCard: renders environmental forces with valid units", () => {
  const ocean = {
    wind_speed_knots: 18.2,
    wind_direction_deg: 240.0,
    wave_height_m: 1.8,
    wave_period_s: 6.5,
    wave_direction_deg: 235.0,
    current_speed_knots: 0.7,
    current_direction_deg: 110.0,
    air_temperature_c: 27.5,
    humidity_pct: 82.0,
    pressure_hpa: 1012.0,
    provenance: "FORECAST",
  };

  const html = renderOceanConditionsCard(ocean);
  assert.ok(html.includes("18.2 kn"));
  assert.ok(html.includes("240 °") || html.includes("240°"));
  assert.ok(html.includes("1.8 m"));
  assert.ok(html.includes("6.5 s"));
  assert.ok(html.includes("0.7 kn"));
  assert.ok(html.includes("27.5 °C"));
  assert.ok(html.includes("1012 hPa"));
  assert.ok(html.includes("FORECAST"));
});

test("5. OperatorApiClient: includes all 6 virtual simulator endpoints", () => {
  const client = new OperatorApiClient("http://localhost:8000");
  assert.equal(typeof client.getSimulatorState, "function");
  assert.equal(typeof client.startSimulation, "function");
  assert.equal(typeof client.pauseSimulation, "function");
  assert.equal(typeof client.resetSimulation, "function");
  assert.equal(typeof client.setSimulatorControls, "function");
  assert.equal(typeof client.stepSimulation, "function");
});

test("6. Safety Boundary: Zero external actuators and port 10111 prohibited", () => {
  const controlsHtml = renderVesselControlsCard({});
  const agentHtml = renderSignalAgentCard({ status: "NORMAL" });
  const oceanHtml = renderOceanConditionsCard({});

  const allHtml = controlsHtml + agentHtml + oceanHtml;

  // Verify no forbidden actuation commands
  assert.ok(!allHtml.includes("port 10111"));
  assert.ok(controlsHtml.includes("Port 10111 strictly prohibited"));
  assert.ok(agentHtml.includes("HUMAN REVIEW REQUIRED"));
});
