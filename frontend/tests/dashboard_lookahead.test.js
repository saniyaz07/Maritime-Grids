/**
 * frontend/tests/dashboard_lookahead.test.js — Phase 10C.13D Look-Ahead Integration Tests
 * =========================================================================================
 * Tests:
 *   1. OperatorApiClient: getRouteWeatherLookahead calls POST /api/v1/operator/weather/lookahead.
 *   2. WeatherCard: renderLookaheadTable renders waypoint distances, forecast wind/waves, and ETAs.
 *   3. WeatherCard: renderLookaheadTable renders adverse warning banner when severe conditions present.
 *   4. WeatherCard: renderLookaheadTable renders empty placeholder when no lookahead context.
 *   5. DriverDashboard: shouldRefreshLookahead enforces throttling (60s, 0.5 NM movement, 1.0 kn SOG change).
 *   6. Stationary and missing speed handling: renders N/A (Stationary) without fabricating ETAs.
 *   7. Non-actuation: verify zero simulator or engine control triggers.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { OperatorApiClient } from "../api/operatorClient.js";
import { renderLookaheadTable, renderWeatherCard } from "../components/WeatherCard.js";
import { DriverDashboardPage } from "../pages/DriverDashboard.js";

test("1. OperatorApiClient: getRouteWeatherLookahead sends correct POST request", async () => {
  let capturedUrl = "";
  let capturedBody = null;
  const client = new OperatorApiClient("http://localhost:8000");
  client._request = async (endpoint, options) => {
    capturedUrl = endpoint;
    capturedBody = JSON.parse(options.body);
    return { success: true, status: 200, data: { route_id: "ESCRAVOS_LAGOS", waypoints: [] } };
  };

  const payload = {
    position: { latitude: 5.58, longitude: 5.18, speed_over_ground_knots: 12.0 },
    route: { route_id: "ESCRAVOS_LAGOS", origin_port: "Escravos", destination_port: "Lagos", waypoints: [] },
  };

  const res = await client.getRouteWeatherLookahead(payload);
  assert.equal(capturedUrl, "/api/v1/operator/weather/lookahead");
  assert.equal(capturedBody.position.latitude, 5.58);
  assert.equal(res.success, true);
});

test("2. WeatherCard: renderLookaheadTable renders waypoint distances, forecast wind/waves, and ETAs", () => {
  const lookaheadData = {
    route_id: "ESCRAVOS_LAGOS",
    timing_status: "ESTIMATED",
    summary: {
      total_lookahead_distance_nm: 125.4,
      total_lookahead_hours: 10.4,
      max_wind_knots: 18.5,
      max_wave_height_m: 1.8,
      has_adverse_conditions: false,
      adverse_condition_reasons: [],
    },
    waypoints: [
      {
        waypoint_id: "WP_ESCRAVOS",
        distance_from_vessel_nm: 0.0,
        hours_ahead: 0.0,
        estimated_arrival_utc: "2026-06-15T12:00:00Z",
        weather: { wind_speed_knots: 12.0, wave_height_m: 1.2 },
        high_wind_warning: false,
        rough_sea_warning: false,
      },
      {
        waypoint_id: "WP_MID",
        distance_from_vessel_nm: 45.0,
        hours_ahead: 3.75,
        estimated_arrival_utc: "2026-06-15T15:45:00Z",
        weather: { wind_speed_knots: 18.5, wave_height_m: 1.8 },
        high_wind_warning: false,
        rough_sea_warning: false,
      },
    ],
  };

  const html = renderLookaheadTable(lookaheadData);
  assert.ok(html.includes("ROUTE WEATHER SPACETIME LOOK-AHEAD"));
  assert.ok(html.includes("WP_ESCRAVOS"));
  assert.ok(html.includes("WP_MID"));
  assert.ok(html.includes("45.0 NM"));
  assert.ok(html.includes("+3.8h"));
  assert.ok(html.includes("18.5 kn"));
  assert.ok(html.includes("1.80 m"));
  assert.ok(html.includes("FAVORABLE"));
});

test("3. WeatherCard: renderLookaheadTable renders adverse warning banner when severe conditions present", () => {
  const adverseData = {
    route_id: "ESCRAVOS_LAGOS",
    timing_status: "ESTIMATED",
    summary: {
      total_lookahead_distance_nm: 125.4,
      total_lookahead_hours: 10.4,
      max_wind_knots: 32.0,
      max_wave_height_m: 3.5,
      has_adverse_conditions: true,
      adverse_condition_reasons: ["High wind ahead (32.0 kn > 25.0 kn) at WP_STORM (+4.2h)"],
    },
    waypoints: [
      {
        waypoint_id: "WP_STORM",
        distance_from_vessel_nm: 50.0,
        hours_ahead: 4.2,
        estimated_arrival_utc: "2026-06-15T16:12:00Z",
        weather: { wind_speed_knots: 32.0, wave_height_m: 3.5 },
        high_wind_warning: true,
        rough_sea_warning: true,
      },
    ],
  };

  const html = renderLookaheadTable(adverseData);
  assert.ok(html.includes("ADVERSE WEATHER PROJECTED AHEAD"));
  assert.ok(html.includes("High wind ahead"));
  assert.ok(html.includes("32.0 kn"));
  assert.ok(html.includes("HIGH WIND"));
  assert.ok(html.includes("ROUGH SEAS"));
});

test("4. WeatherCard: renderLookaheadTable renders empty placeholder when no lookahead context", () => {
  const html = renderLookaheadTable(null);
  assert.ok(html.includes("Route weather spacetime look-ahead will update as vessel progresses"));
});

test("5. DriverDashboard: shouldRefreshLookahead enforces throttling", () => {
  const page = new DriverDashboardPage("dummy");
  // 1. First call without previous timestamp -> must refresh
  assert.equal(page.shouldRefreshLookahead({ latitude: 5.58, longitude: 5.18, speed_over_ground_knots: 12.0 }), true);

  // Set initial recorded state
  page.lastLookaheadQuery = {
    lat: 5.58,
    lon: 5.18,
    sog: 12.0,
    timestamp: Date.now(),
  };

  // 2. Immediate second call with identical position and speed -> should NOT refresh (throttled)
  assert.equal(page.shouldRefreshLookahead({ latitude: 5.58, longitude: 5.18, speed_over_ground_knots: 12.0 }), false);

  // 3. Minor movement (< 0.1 NM) and same speed -> should NOT refresh
  assert.equal(page.shouldRefreshLookahead({ latitude: 5.581, longitude: 5.181, speed_over_ground_knots: 12.1 }), false);

  // 4. Significant movement (> 0.5 NM, e.g. 0.01 deg lat = 0.6 NM) -> MUST refresh
  assert.equal(page.shouldRefreshLookahead({ latitude: 5.595, longitude: 5.18, speed_over_ground_knots: 12.0 }), true);

  // 5. Significant SOG change (> 1.0 kn, e.g. 12.0 -> 14.5 kn) -> MUST refresh
  assert.equal(page.shouldRefreshLookahead({ latitude: 5.58, longitude: 5.18, speed_over_ground_knots: 14.5 }), true);

  // 6. Elapsed time (> 60s) -> MUST refresh
  page.lastLookaheadQuery.timestamp = Date.now() - 65000;
  assert.equal(page.shouldRefreshLookahead({ latitude: 5.58, longitude: 5.18, speed_over_ground_knots: 12.0 }), true);
});

test("6. Stationary and missing speed handling: renders N/A (Stationary) without fabricating ETAs", () => {
  const stationaryLookahead = {
    route_id: "ESCRAVOS_LAGOS",
    timing_status: "STATIONARY",
    summary: {
      total_lookahead_distance_nm: 125.4,
      total_lookahead_hours: null,
      max_wind_knots: 10.0,
      max_wave_height_m: 0.8,
      has_adverse_conditions: false,
      adverse_condition_reasons: [],
    },
    waypoints: [
      {
        waypoint_id: "WP_ESCRAVOS",
        distance_from_vessel_nm: 0.0,
        hours_ahead: null,
        estimated_arrival_utc: null,
        weather: { wind_speed_knots: 10.0, wave_height_m: 0.8 },
        high_wind_warning: false,
        rough_sea_warning: false,
      },
    ],
  };

  const html = renderLookaheadTable(stationaryLookahead);
  assert.ok(html.includes("STATIONARY"));
  assert.ok(html.includes("N/A (Stationary)"));
  assert.ok(!html.includes("NaN"));
  assert.ok(!html.includes("undefined"));
});

test("7. Safety Check: Zero actuator commands or control triggers in lookahead components", () => {
  const lookaheadData = {
    route_id: "ESCRAVOS_LAGOS",
    timing_status: "ESTIMATED",
    summary: { total_lookahead_distance_nm: 10.0, has_adverse_conditions: false, adverse_condition_reasons: [] },
    waypoints: [],
  };
  const html = renderLookaheadTable(lookaheadData);
  const forbidden = ["set_throttle", "set_rudder", "engage_autopilot", "send_command", "control_mode"];
  for (const term of forbidden) {
    assert.ok(!html.includes(term), `Forbidden actuator term found: ${term}`);
  }
});
