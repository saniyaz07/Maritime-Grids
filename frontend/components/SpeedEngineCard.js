/**
 * frontend/components/SpeedEngineCard.js — Phase 10C.11B Speed & Engine State Presentation Cards
 * ==============================================================================================
 * Displays vessel kinematics (SOG, COG, Recommended Speed) and Engine Telemetry (Status, RPM, Load).
 * 
 * Strict Safety & Semantic Invariants:
 *   - Engine State: If no live telemetry exists, strictly displays "ENGINE STATE: UNKNOWN".
 *     Does NOT fabricate or infer engine ON/OFF from speed, fuel, or voyage status.
 *   - Current Speed: Displays SOG with provenance/freshness. If missing, displays "Unavailable".
 *   - Recommended Speed: Displays "Not available" (preserves boundary with Phase 9 offline optimizer).
 *   - Zero Actuation: Zero engine control commands (NO engine start/stop/throttle buttons).
 *   - Physical engine ON/OFF control and throttle actuation are NOT implemented.
 */

import { renderTelemetryField, renderProvenanceMetadata } from "./ProvenanceBadge.js";

export function renderSpeedCard({
  speedOverGroundKnots = null,
  courseOverGroundDeg = null,
  designSpeedKnots = null,
  provenance = "OBSERVED",
  freshness = "FRESH",
  quality = "VALID",
  timestamp = null,
  source = "GPS / SOG Telemetry",
}) {
  const isSpeedAvail = speedOverGroundKnots !== null && speedOverGroundKnots !== undefined;
  const isCogAvail = courseOverGroundDeg !== null && courseOverGroundDeg !== undefined;

  return `
    <div class="dashboard-card speed-telemetry-card">
      <div class="card-header">
        <div class="card-title-group">
          <h3>Vessel Speed & Kinematics</h3>
          <span class="card-subtitle">Source: ${escapeHtml(source)}</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-${provenance.toLowerCase()}">${escapeHtml(provenance)}</span>
        </div>
      </div>

      <div class="card-body">
        <!-- Main Speed Hero Display -->
        <div class="hero-metric-box">
          <span class="hero-label">Current Speed Over Ground (SOG)</span>
          <div class="hero-value-row">
            <span class="hero-value ${isSpeedAvail ? 'val-active' : 'val-unavailable'}">
              ${isSpeedAvail ? `${speedOverGroundKnots.toFixed(1)} kn` : 'Unavailable'}
            </span>
          </div>
          ${renderProvenanceMetadata({ source, provenance, quality, freshness, timestamp, compact: true })}
        </div>

        <div class="telemetry-grid grid-2col mt-3">
          ${renderTelemetryField({
            label: "Course Over Ground (COG)",
            value: courseOverGroundDeg,
            unit: "°",
            decimals: 1,
            source,
            provenance,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Design Service Speed",
            value: designSpeedKnots,
            unit: "kn",
            decimals: 1,
            source: "Ship Profile",
            provenance: "OBSERVED",
            nullPlaceholder: "Unavailable",
          })}
        </div>

        <!-- Target / Recommended Speed Field (Offline Tool Boundary) -->
        <div class="recommended-speed-box mt-3">
          <div class="rec-speed-header">
            <span class="rec-label">Recommended Speed:</span>
            <span class="rec-value val-unavailable">Not available</span>
          </div>
          <div class="semantic-boundary-note">
            <span class="info-icon">ℹ️</span>
            <span>Speed co-optimization is an offline planning tool. Real-time dynamic speed steering is not connected.</span>
          </div>
        </div>
      </div>
    </div>
  `;
}

export function renderEngineStateCard({
  engineState = "UNKNOWN", // "ON", "OFF", or "UNKNOWN"
  engineRpm = null,
  engineLoadPct = null,
  installedPowerKw = null,
  shaftPowerKw = null,
  shaftPowerDemandKw = null,
  propulsionType = null,
  provenance = "UNAVAILABLE",
  timestamp = null,
}) {
  const stateNormalized = (engineState || "UNKNOWN").toUpperCase();
  const isStateKnown = stateNormalized === "ON" || stateNormalized === "OFF";
  const isSim = provenance === "SIMULATED";
  const actualDemand = shaftPowerDemandKw !== null ? shaftPowerDemandKw : shaftPowerKw;
  const isOverloaded = (engineLoadPct !== null && engineLoadPct > 100.0) ||
                       (actualDemand !== null && installedPowerKw !== null && actualDemand > installedPowerKw);

  let statusBadgeClass = "status-unknown";
  let statusText = "ENGINE STATE UNKNOWN";
  if (stateNormalized === "ON") {
    statusBadgeClass = "status-active";
    statusText = isSim ? "PROPULSION: ACTIVE" : "ENGINE ON";
  } else if (stateNormalized === "OFF") {
    statusBadgeClass = "status-paused";
    statusText = isSim ? "ENGINE: OFF" : "ENGINE OFF";
  }

  const descText = isSim
    ? (isStateKnown ? "Simulated powertrain state derived from virtual vessel physics." : "Simulated engine state unavailable.")
    : (isStateKnown ? "Live engine telemetry reported from engine management gateway." : "Live engine telemetry is not connected. State cannot be inferred without dedicated sensors.");

  const sensorSource = isSim
    ? "Virtual Propulsion Model"
    : (isStateKnown ? "Tachometer" : "No Engine Sensor Connected");

  const controllerSource = isSim
    ? "Virtual Powertrain Model"
    : (isStateKnown ? "Engine Controller" : "No Engine Sensor Connected");

  const fieldProv = isSim
    ? "SIMULATED"
    : (isStateKnown ? "OBSERVED" : "UNAVAILABLE");

  return `
    <div class="dashboard-card engine-state-card compact-engine-card">
      <div class="card-header compact-header">
        <div class="card-title-group">
          <h3>ENGINE &amp; PROPULSION</h3>
          <span class="card-subtitle">${escapeHtml(propulsionType || "Diesel-Mechanical + Clean Auxiliary Hybrid")}</span>
        </div>
        <div class="card-status-container">
          <span class="status-pill ${statusBadgeClass}">${escapeHtml(statusText)}</span>
          ${isOverloaded ? '<span class="status-pill status-critical">⚠️ OVERLOAD</span>' : ''}
        </div>
      </div>

      <div class="card-body compact-card-body">
        <!-- Engine Status Hero Display -->
        <div class="engine-status-hero">
          <div class="engine-indicator-ring ${statusBadgeClass}">
            <span class="engine-icon">⚙️</span>
          </div>
          <div class="engine-status-details">
            <div class="engine-state-title ${statusBadgeClass}">${escapeHtml(statusText)}</div>
            <div class="engine-state-desc">
              ${escapeHtml(descText)}
            </div>
          </div>
        </div>

        <div class="telemetry-grid grid-4col mt-2">
          ${renderTelemetryField({
            label: "Shaft Power Demand",
            value: actualDemand,
            unit: "kW",
            decimals: 0,
            source: isSim ? "Hydrodynamic Demand" : (isStateKnown ? "Torsion Meter" : "No Sensor Connected"),
            provenance: fieldProv,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "MCR Load",
            value: engineLoadPct,
            unit: "%",
            decimals: 1,
            source: controllerSource,
            provenance: fieldProv,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Shaft Speed",
            value: engineRpm,
            unit: "RPM",
            decimals: 0,
            source: sensorSource,
            provenance: fieldProv,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Rated Continuous MCR",
            value: installedPowerKw,
            unit: "kW",
            decimals: 0,
            source: "Design Spec (MCR)",
            provenance: isSim ? "SIMULATED" : "OBSERVED",
            nullPlaceholder: "Unavailable",
          })}
        </div>

        ${isOverloaded ? `
          <div class="alert-banner alert-warning mt-2">
            <span class="alert-icon">⚠️</span>
            <div class="alert-content">
              <strong>ENGINE OVERLOAD WARNING:</strong> Shaft power demand (${actualDemand ? actualDemand.toFixed(0) : ''} kW) exceeds rated engine MCR (${installedPowerKw ? installedPowerKw.toFixed(0) : ''} kW). Delivered power capped at 4500 kW. Recommend speed reduction.
            </div>
          </div>
        ` : ''}

        <!-- Strict Non-Actuation & Safety Notice -->
        <div class="engine-safety-notice mt-2">
          <span class="shield-icon">🛡️</span>
          <span><strong>Safety Policy:</strong> Throttle/actuator commands not connected. Read-only decision support.</span>
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
