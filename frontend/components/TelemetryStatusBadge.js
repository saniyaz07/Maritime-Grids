/**
 * frontend/components/TelemetryStatusBadge.js — Phase 10C.12 / 10C.13 Telemetry Status Indicator
 * ==============================================================================================
 * Renders the top-level stream connection and telemetry data status indicators:
 *   - STREAM: CONNECTED | RECONNECTING | DISCONNECTED | WAITING
 *   - DATA: FRESH | STALE | EXPIRED | UNKNOWN
 *   - PROVENANCE: OBSERVED | SIMULATED
 * 
 * Strict Invariants:
 *   - Clearly separates stream connection state from telemetry data freshness.
 *   - Preserves backward compatibility with single-badge rendering and CSS selectors.
 *   - Derived directly from canonical telemetry contract.
 */

export function renderStreamConnectionBadge(streamState = "CONNECTED") {
  const streamNorm = (streamState || "CONNECTED").toUpperCase();
  let streamClass = "badge-stream-connected";
  if (streamNorm === "DISCONNECTED") streamClass = "badge-stream-disconnected";
  else if (streamNorm === "RECONNECTING" || streamNorm === "WAITING" || streamNorm === "CONNECTING") {
    streamClass = "badge-stream-reconnecting";
  }

  return `
    <div class="telemetry-status-badge stream-badge ${streamClass}" title="SSE Stream State: ${escapeHtml(streamNorm)}">
      <span class="telemetry-label">STREAM: ${escapeHtml(streamNorm)}</span>
      <span class="telemetry-dot ${streamClass}">●</span>
      <span class="telemetry-state-text">${escapeHtml(streamNorm)}</span>
    </div>
  `;
}

export function renderTelemetryFreshnessBadge(freshness = "FRESH", ageSeconds = null) {
  const freshNorm = (freshness || "UNKNOWN").toUpperCase();
  let freshClass = "status-fresh";
  if (freshNorm === "STALE") freshClass = "status-stale";
  else if (freshNorm === "EXPIRED" || freshNorm === "DISCONNECTED") freshClass = "status-expired";

  const ageLabel = ageSeconds !== null && ageSeconds !== undefined
    ? ` (${Math.round(ageSeconds)}s ago)`
    : "";

  return `
    <div class="telemetry-status-badge data-badge ${freshClass}" title="Freshness: ${escapeHtml(freshNorm)}${ageLabel}">
      <span class="telemetry-label">DATA</span>
      <span class="telemetry-dot ${freshClass}">●</span>
      <span class="telemetry-state-text">${escapeHtml(freshNorm)}${escapeHtml(ageLabel)}</span>
    </div>
  `;
}

export function renderTelemetryStatusBadge({
  freshness = "FRESH",
  provenanceMode = "OBSERVED",
  quality = "VALID",
  ageSeconds = null,
  source = null,
  streamState = "CONNECTED",
}) {
  const freshNorm = (freshness || "UNKNOWN").toUpperCase();
  const provNorm = (provenanceMode || "OBSERVED").toUpperCase();
  const qualNorm = (quality || "VALID").toUpperCase();
  const streamNorm = (streamState || "CONNECTED").toUpperCase();

  // Backward compatibility state classes & labels
  let statusClass = "status-live";
  let statusText = "LIVE";

  if (provNorm === "SIMULATED") {
    statusClass = "status-simulated";
    statusText = "SIMULATED";
  } else if (freshNorm === "DISCONNECTED" || qualNorm === "UNAVAILABLE" || streamNorm === "DISCONNECTED") {
    statusClass = "status-disconnected";
    statusText = "DISCONNECTED";
  } else if (freshNorm === "EXPIRED" || qualNorm === "INVALID") {
    statusClass = "status-expired";
    statusText = "EXPIRED";
  } else if (freshNorm === "STALE") {
    statusClass = "status-stale";
    statusText = "STALE";
  }

  const ageLabel = ageSeconds !== null && ageSeconds !== undefined
    ? ` (${Math.round(ageSeconds)}s ago)`
    : "";

  return `
    <div class="telemetry-status-container ${statusClass}">
      <!-- Backward compatibility badge -->
      <div class="telemetry-status-badge ${statusClass}" title="Telemetry Status: ${statusText}">
        <span class="telemetry-label">TELEMETRY</span>
        <span class="telemetry-dot ${statusClass}">●</span>
        <span class="telemetry-state-text">${statusText}${escapeHtml(ageLabel)}</span>
      </div>

      <!-- Real-time SSE Stream Connection Indicator -->
      ${renderStreamConnectionBadge(streamNorm)}

      <!-- Telemetry Data Freshness Indicator -->
      ${renderTelemetryFreshnessBadge(freshNorm, ageSeconds)}

      <!-- Provenance Mode Badge -->
      ${provNorm === "SIMULATED" ? `
        <div class="telemetry-status-badge mode-badge status-simulated" title="Simulated Scenario Data">
          <span class="telemetry-label">MODE</span>
          <span class="telemetry-state-text">SIMULATED</span>
        </div>
      ` : `
        <div class="telemetry-status-badge mode-badge status-observed" title="Observed Physical Telemetry">
          <span class="telemetry-label">MODE</span>
          <span class="telemetry-state-text">OBSERVED</span>
        </div>
      `}
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
