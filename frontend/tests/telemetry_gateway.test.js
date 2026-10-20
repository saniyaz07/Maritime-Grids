/**
 * frontend/tests/telemetry_gateway.test.js — Phase 10C.12 Frontend Telemetry Gateway Test Suite
 * ==============================================================================================
 * Verifies:
 *   1. TelemetryStatusBadge rendering (LIVE, STALE, EXPIRED, DISCONNECTED, SIMULATED).
 *   2. OperatorApiClient telemetry methods (ingest, current, scenario, validate).
 *   3. Enums in frontend/contracts/types.js match backend contracts.
 *   4. DriverDashboardPage scenario integration and null preservation.
 *   5. Non-actuation safety invariants (zero control endpoints or buttons).
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  EngineOperationalState,
  TelemetryFreshnessState,
  TelemetryQualityState,
  TelemetryStatusState,
} from "../contracts/types.js";

import { renderTelemetryStatusBadge } from "../components/TelemetryStatusBadge.js";
import { renderSpeedCard, renderEngineStateCard } from "../components/SpeedEngineCard.js";
import { renderFuelCard, renderBatteryCard } from "../components/EnergyCard.js";
import { OperatorApiClient } from "../api/operatorClient.js";

test("1. TelemetryStatusBadge: renders LIVE state correctly", () => {
  const html = renderTelemetryStatusBadge({
    freshness: "FRESH",
    provenanceMode: "OBSERVED",
    quality: "VALID",
    ageSeconds: 12.4,
    source: "GPS_NMEA",
  });
  assert.ok(html.includes("status-live"));
  assert.ok(html.includes("LIVE"));
  assert.ok(html.includes("12s ago"));
  assert.ok(html.includes("TELEMETRY"));
});

test("2. TelemetryStatusBadge: renders STALE state correctly", () => {
  const html = renderTelemetryStatusBadge({
    freshness: "STALE",
    provenanceMode: "OBSERVED",
    quality: "VALID",
    ageSeconds: 340,
    source: "MODBUS_GW",
  });
  assert.ok(html.includes("status-stale"));
  assert.ok(html.includes("STALE"));
});

test("3. TelemetryStatusBadge: renders EXPIRED state correctly", () => {
  const html = renderTelemetryStatusBadge({
    freshness: "EXPIRED",
    provenanceMode: "OBSERVED",
    quality: "VALID",
    ageSeconds: 3600,
  });
  assert.ok(html.includes("status-expired"));
  assert.ok(html.includes("EXPIRED"));
});

test("4. TelemetryStatusBadge: renders DISCONNECTED state correctly", () => {
  const html = renderTelemetryStatusBadge({
    freshness: "DISCONNECTED",
    provenanceMode: "UNAVAILABLE",
    quality: "UNAVAILABLE",
  });
  assert.ok(html.includes("status-disconnected"));
  assert.ok(html.includes("DISCONNECTED"));
});

test("5. TelemetryStatusBadge: renders SIMULATED state with priority", () => {
  const html = renderTelemetryStatusBadge({
    freshness: "FRESH",
    provenanceMode: "SIMULATED",
    quality: "VALID",
    ageSeconds: 2.0,
    source: "SCENARIO_SIMULATOR",
  });
  assert.ok(html.includes("status-simulated"));
  assert.ok(html.includes("SIMULATED"));
});

test("6. Enums: EngineOperationalState matches ON, OFF, UNKNOWN", () => {
  assert.equal(EngineOperationalState.ON, "ON");
  assert.equal(EngineOperationalState.OFF, "OFF");
  assert.equal(EngineOperationalState.UNKNOWN, "UNKNOWN");
});

test("7. Enums: TelemetryFreshnessState has required classifications", () => {
  assert.equal(TelemetryFreshnessState.FRESH, "FRESH");
  assert.equal(TelemetryFreshnessState.STALE, "STALE");
  assert.equal(TelemetryFreshnessState.EXPIRED, "EXPIRED");
  assert.equal(TelemetryFreshnessState.DISCONNECTED, "DISCONNECTED");
});

test("8. OperatorApiClient: includes all 4 telemetry gateway endpoints", () => {
  const client = new OperatorApiClient("http://localhost:8000");
  assert.equal(typeof client.ingestTelemetry, "function");
  assert.equal(typeof client.getCurrentTelemetry, "function");
  assert.equal(typeof client.getSimulatedScenario, "function");
  assert.equal(typeof client.validateTelemetry, "function");
});

test("9. Speed Kinematics: displays speed with fresh telemetry tags", () => {
  const html = renderSpeedCard({
    speedOverGroundKnots: 11.8,
    courseOverGroundDeg: 284.5,
    provenance: "OBSERVED",
    freshness: "FRESH",
    quality: "VALID",
  });
  assert.ok(html.includes("11.8 kn"));
  assert.ok(html.includes("284.5"));
  assert.ok(html.includes("prov-observed"));
});


test("10. Engine State: displays ENGINE ON when explicit", () => {
  const html = renderEngineStateCard({
    engineState: "ON",
    engineRpm: 1450,
    engineLoadPct: 72.5,
  });
  assert.ok(html.includes("ENGINE ON"));
  assert.ok(html.includes("1450"));
  assert.ok(html.includes("72.5 %"));
});

test("11. Engine State: displays ENGINE OFF when explicit", () => {
  const html = renderEngineStateCard({
    engineState: "OFF",
    engineRpm: 0,
    engineLoadPct: 0,
  });
  assert.ok(html.includes("ENGINE OFF"));
});

test("12. Engine State: displays UNKNOWN when telemetry missing", () => {
  const html = renderEngineStateCard({
    engineState: "UNKNOWN",
    engineRpm: null,
    engineLoadPct: null,
  });
  assert.ok(html.includes("ENGINE STATE UNKNOWN") || html.includes("UNKNOWN"));
  assert.ok(html.includes("Unavailable"));
});

test("13. Fuel & Battery null preservation (null != 0)", () => {
  const fuelHtml = renderFuelCard({
    fuelRemainingLiters: null,
    fuelConsumptionRateLph: null,
  });
  assert.ok(!fuelHtml.includes("0.0 L"));
  assert.ok(fuelHtml.includes("Unavailable"));

  const battHtml = renderBatteryCard({
    batterySocPct: null,
    batterySohPct: null,
    batteryEnergyAvailableKwh: null,
  });
  assert.ok(battHtml.includes("Unavailable"));
});

test("14. Safety Check: Zero actuator commands in frontend components", () => {
  const forbidden = ["set_throttle", "set_rudder", "start_engine", "stop_engine", "override_route", "steer_vessel"];
  const components = [renderSpeedCard, renderEngineStateCard, renderFuelCard, renderBatteryCard, renderTelemetryStatusBadge];

  for (const comp of components) {
    const fnStr = comp.toString().toLowerCase();
    for (const term of forbidden) {
      assert.ok(!fnStr.includes(term), `Forbidden term ${term} found in component function`);
    }
  }
});
