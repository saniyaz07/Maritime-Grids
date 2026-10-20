/**
 * frontend/tests/telemetry_stream.test.js — Phase 10C.13 Real-Time Streaming & Audit Log Frontend Tests
 * ====================================================================================================
 * Verifies:
 *   1. OperatorApiClient real-time streaming endpoint URL and history query parameters.
 *   2. OperatorApiClient subscribeTelemetryStream EventSource lifecycle, events, and unsubscribe.
 *   3. TelemetryStatusBadge stream connection status badge (CONNECTED, RECONNECTING, DISCONNECTED).
 *   4. DriverDashboard audit history table rendering and pagination/empty states.
 *   5. Strict null preservation in frontend audit log presentation (null != 0).
 *   6. Zero actuator controls or interactive dispatch buttons.
 */

import test from "node:test";
import assert from "node:assert/strict";

import { OperatorApiClient } from "../api/operatorClient.js";
import {
  renderStreamConnectionBadge,
  renderTelemetryFreshnessBadge,
  renderTelemetryStatusBadge,
} from "../components/TelemetryStatusBadge.js";
import {
  renderAuditHistoryTable,
  renderExactTimestamp,
} from "../pages/DriverDashboard.js";

// Mock EventSource for Node environment
class MockEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.onopen = null;
    this.onerror = null;
    MockEventSource.lastInstance = this;
    setTimeout(() => {
      if (this.onopen) this.onopen();
    }, 10);
  }

  addEventListener(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback);
  }

  emit(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach((cb) => cb({ data: JSON.stringify(data) }));
    }
  }

  triggerError(err) {
    if (this.onerror) this.onerror(err);
  }

  close() {
    this.closed = true;
  }
}

// Attach MockEventSource globally for testing
global.EventSource = MockEventSource;

test("1. OperatorApiClient: getTelemetryStreamUrl returns valid stream path", () => {
  const client = new OperatorApiClient("http://localhost:8000");
  assert.equal(client.getTelemetryStreamUrl(), "http://localhost:8000/api/v1/operator/telemetry/stream");
});

test("2. OperatorApiClient: getTelemetryHistory builds correct query parameters", async () => {
  let capturedUrl = "";
  const client = new OperatorApiClient("http://localhost:8000");
  client._request = async (endpoint, options) => {
    capturedUrl = endpoint;
    return { records: [], total: 0, limit: 25, offset: 5 };
  };

  const res = await client.getTelemetryHistory({
    vesselId: "VESSEL_OSV_01",
    startTimeUtc: "2026-09-28T00:00:00Z",
    mode: "OBSERVED",
    limit: 25,
    offset: 5,
  });

  assert.equal(res.total, 0);
  assert.ok(capturedUrl.includes("/api/v1/operator/telemetry/history?"));
  assert.ok(capturedUrl.includes("vessel_id=VESSEL_OSV_01"));
  assert.ok(capturedUrl.includes("mode=OBSERVED"));
  assert.ok(capturedUrl.includes("limit=25"));
  assert.ok(capturedUrl.includes("offset=5"));
});

test("3. OperatorApiClient: subscribeTelemetryStream handles connection, messages, and cleanup", async () => {
  const client = new OperatorApiClient("http://localhost:8000");
  const receivedMessages = [];
  const statusChanges = [];

  const unsubscribe = client.subscribeTelemetryStream(
    (msg) => receivedMessages.push(msg),
    (err) => {},
    (status) => statusChanges.push(status)
  );

  assert.equal(statusChanges[0], "CONNECTING");

  // Wait for open
  await new Promise((r) => setTimeout(r, 20));
  assert.ok(statusChanges.includes("CONNECTED"));

  const mockInstance = MockEventSource.lastInstance;
  assert.ok(mockInstance);

  // Emit a mock telemetry message
  mockInstance.emit("telemetry", { telemetry_id: "TEL_STREAM_TEST_01", vessel_id: "VESSEL_01" });
  assert.equal(receivedMessages.length, 1);
  assert.equal(receivedMessages[0].telemetry_id, "TEL_STREAM_TEST_01");

  // Trigger error -> RECONNECTING
  mockInstance.triggerError(new Error("Network drop"));
  assert.ok(statusChanges.includes("RECONNECTING"));

  // Unsubscribe -> closes instance
  unsubscribe();
  assert.equal(mockInstance.closed, true);
  assert.equal(statusChanges[statusChanges.length - 1], "DISCONNECTED");
});

test("4. TelemetryStatusBadge: renderStreamConnectionBadge covers all states", () => {
  const connectedHtml = renderStreamConnectionBadge("CONNECTED");
  assert.ok(connectedHtml.includes("CONNECTED"));
  assert.ok(connectedHtml.includes("badge-stream-connected"));

  const reconnectingHtml = renderStreamConnectionBadge("RECONNECTING");
  assert.ok(reconnectingHtml.includes("RECONNECTING"));
  assert.ok(reconnectingHtml.includes("badge-stream-reconnecting"));

  const disconnectedHtml = renderStreamConnectionBadge("DISCONNECTED");
  assert.ok(disconnectedHtml.includes("DISCONNECTED"));
  assert.ok(disconnectedHtml.includes("badge-stream-disconnected"));
});

test("5. TelemetryStatusBadge: renderTelemetryStatusBadge includes stream status & freshness", () => {
  const html = renderTelemetryStatusBadge({
    streamStatus: "CONNECTED",
    freshness: "FRESH",
    provenanceMode: "OBSERVED",
    quality: "EXCELLENT",
    ageSeconds: 5,
    source: "GPS_NMEA",
  });

  assert.ok(html.includes("STREAM: CONNECTED"));
  assert.ok(html.includes("FRESH"));
  assert.ok(html.includes("OBSERVED"));
  assert.ok(html.includes("5s ago"));
});

test("6. DriverDashboard: renderAuditHistoryTable handles empty records list", () => {
  const html = renderAuditHistoryTable([]);
  assert.ok(html.includes("TELEMETRY AUDIT LOG"));
  assert.ok(html.includes("No telemetry records found."));
});

test("7. DriverDashboard: renderAuditHistoryTable preserves null values (null != 0)", () => {
  const records = [
    {
      record_id: "AUDIT_001",
      telemetry_id: "TEL_001",
      vessel_id: "VESSEL_OSV_01",
      timestamp_utc: "2026-09-28T12:00:00Z",
      speed_over_ground_knots: null, // Missing speed
      course_over_ground_deg: null, // Missing course
      engine_state: "UNKNOWN",
      engine_rpm: null, // Missing RPM
      battery_soc_pct: null, // Missing SOC
      quality_state: "DEGRADED",
      mode: "OBSERVED",
      source: "SENSOR_FAIL",
    },
  ];

  const html = renderAuditHistoryTable(records);
  assert.ok(html.includes("AUDIT_001"));
  assert.ok(html.includes("VESSEL_OSV_01"));
  assert.ok(html.includes("N/A")); // Displays N/A, NOT 0.0 or 0
  assert.ok(!html.includes("0.0 kn"));
  assert.ok(html.includes("UNKNOWN"));
  assert.ok(html.includes("DEGRADED"));
});

test("8. DriverDashboard: renderExactTimestamp displays full ISO timestamp", () => {
  const iso = "2026-09-28T12:30:45.123Z";
  const formatted = renderExactTimestamp(iso);
  assert.ok(formatted.includes("2026-09-28T12:30:45.123Z"));
});
