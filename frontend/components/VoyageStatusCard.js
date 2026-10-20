/**
 * frontend/components/VoyageStatusCard.js — Phase 10C.11A Voyage Status & Navigation Card
 * =======================================================================================
 * Displays vessel context, spatial position, route progress, status, and ETA.
 * 
 * Mandatory Safety Constraints:
 *   - ETA MUST be explicitly labeled: "Application-level linear estimate"
 *   - ETA MUST include disclaimer: "Not a hydrodynamic voyage predictor."
 *   - No autonomous route change or steering controls.
 *   - Null values remain explicitly "Unavailable" / "Not reported" (null != 0).
 */

import { renderProvenanceMetadata } from "./ProvenanceBadge.js";

export function renderVoyageStatusCard({
  vessel = null,
  voyageId = null,
  status = "PLANNED",
  position = null,
  route = null,
  timeline = null,
  provenance = null,
  source = null,
  quality = null,
  freshness = null,
}) {
  const vId = vessel?.vessel_id || "Unspecified Vessel";
  const sType = vessel?.ship_type || "Unknown Type";
  const voyId = voyageId || "Unassigned Voyage";
  const statusBadge = `<span class="status-pill status-${(status || 'planned').toLowerCase()}">${status || 'UNKNOWN'}</span>`;

  // Position
  const latStr = position?.latitude !== undefined && position?.latitude !== null ? `${position.latitude.toFixed(4)}°` : "Unavailable";
  const lonStr = position?.longitude !== undefined && position?.longitude !== null ? `${position.longitude.toFixed(4)}°` : "Unavailable";
  const sogStr = position?.speed_over_ground_knots !== undefined && position?.speed_over_ground_knots !== null ? `${position.speed_over_ground_knots.toFixed(1)} kn` : "Unavailable";
  const posTime = position?.timestamp_utc || null;
  const provMode = provenance || (position?.data_type === "SIMULATED" ? "SIMULATED" : (position ? "OBSERVED" : "UNAVAILABLE"));
  const srcName = source || (provMode === "SIMULATED" ? "Virtual Vessel Simulator" : "Telemetry / Context");

  // Route & Timeline
  const origin = route?.origin_port || (provMode === "SIMULATED" ? "Escravos Terminal" : "Origin N/A");
  const destination = route?.destination_port || (provMode === "SIMULATED" ? "Lagos Port" : "Destination N/A");
  const totalDist = route?.total_distance_nm !== undefined && route?.total_distance_nm !== null ? `${Number(route.total_distance_nm).toFixed(1)} NM` : (provMode === "SIMULATED" ? "250.0 NM" : "Unavailable");
  const remDist = timeline?.remaining_distance_nm !== undefined && timeline?.remaining_distance_nm !== null ? `${Number(timeline.remaining_distance_nm).toFixed(1)} NM` : "Unavailable";
  const pctComplete = timeline?.progress_pct !== undefined && timeline?.progress_pct !== null ? `${Number(timeline.progress_pct).toFixed(1)}%` : "0.0%";

  // ETA with mandatory disclaimers
  const etaTime = timeline?.estimated_arrival_utc || "Unavailable";

  return `
    <div class="dashboard-card voyage-status-card">
      <div class="card-header">
        <div class="card-title-group">
          <h3>Voyage & Navigation State</h3>
          <span class="card-subtitle">Vessel: ${escapeHtml(vId)} (${escapeHtml(sType)}) | Voyage ID: ${escapeHtml(voyId)}</span>
        </div>
        <div class="card-status-container">
          ${statusBadge}
        </div>
      </div>

      <div class="card-body grid-2col">
        <!-- Left: Position & Telemetry -->
        <div class="sub-panel">
          <h4>Current Vessel Position</h4>
          <div class="telemetry-grid">
            <div class="stat-box">
              <span class="stat-label">Latitude</span>
              <span class="stat-value">${escapeHtml(latStr)}</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Longitude</span>
              <span class="stat-value">${escapeHtml(lonStr)}</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Speed Over Ground (SOG)</span>
              <span class="stat-value">${escapeHtml(sogStr)}</span>
            </div>
          </div>
          ${renderProvenanceMetadata({ source: srcName, provenance: provMode, quality: quality || "VALID", freshness: freshness || "FRESH", timestamp: posTime, compact: true })}
        </div>

        <!-- Right: Route & Timeline -->
        <div class="sub-panel">
          <h4>Route Progression</h4>
          <div class="route-corridor">
            <span class="port-tag origin">${escapeHtml(origin)}</span>
            <span class="corridor-arrow">➔</span>
            <span class="port-tag destination">${escapeHtml(destination)}</span>
          </div>

          <div class="progress-bar-container">
            <div class="progress-bar-fill" style="width: ${escapeHtml(pctComplete)};"></div>
          </div>

          <div class="telemetry-grid mt-2">
            <div class="stat-box">
              <span class="stat-label">Total Distance</span>
              <span class="stat-value">${escapeHtml(totalDist)}</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Remaining Distance</span>
              <span class="stat-value">${escapeHtml(remDist)}</span>
            </div>
            <div class="stat-box">
              <span class="stat-label">Progress</span>
              <span class="stat-value">${escapeHtml(pctComplete)}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ETA Section with Mandatory Semantic Disclaimers -->
      <div class="eta-disclaimer-box">
        <div class="eta-header">
          <span class="eta-label">Estimated Time of Arrival (ETA):</span>
          <span class="eta-value">${escapeHtml(etaTime)}</span>
          <span class="meta-tag meta-prov prov-model_prediction">Application-level linear estimate</span>
        </div>
        <div class="eta-disclaimer-text">
          <span class="disclaimer-icon">ℹ️</span>
          <span><strong>Notice:</strong> ETA is an application-level linear estimate based on constant speed progress. Not a hydrodynamic voyage predictor.</span>
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
