/**
 * frontend/components/SolarCard.js — Phase 10C.11A Solar Clean Energy Feasibility Card
 * ====================================================================================
 * Displays climatological solar generation scenario estimates.
 * 
 * Mandatory Semantic Invariants:
 *   - MUST be explicitly labeled: "CLIMATOLOGICAL SCENARIO ESTIMATE"
 *   - MUST display diurnal uncertainty flag if duration > 24 hours.
 *   - Prohibits labeling as "real-time solar generation", "measured solar output",
 *     or "instantaneous solar power".
 */

import { renderTelemetryField, renderProvenanceMetadata } from "./ProvenanceBadge.js";

export function renderSolarCard({
  estimatedSolarKwh = null,
  panelSizeM2 = null,
  panelEfficiencyPct = null,
  dailyGhiKwhM2 = null,
  diurnalUncertaintyFlag = false,
  provenance = "CLIMATOLOGICAL_ESTIMATE",
  source = "NASA POWER Climatology",
  timestamp = null,
}) {
  const isAvailable = estimatedSolarKwh !== null && estimatedSolarKwh !== undefined;

  return `
    <div class="dashboard-card solar-card">
      <div class="card-header">
        <div class="card-title-group">
          <h3>Solar Clean Energy Generation</h3>
          <span class="card-subtitle">Source: ${escapeHtml(source)}</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-climatological">CLIMATOLOGICAL SCENARIO ESTIMATE</span>
          ${diurnalUncertaintyFlag ? '<span class="meta-tag meta-warning">Diurnal Uncertainty Flag</span>' : ''}
        </div>
      </div>

      <div class="card-body">
        <div class="solar-hero-display">
          <div class="hero-metric-box">
            <span class="hero-label">Estimated Solar Generation (Voyage Budget)</span>
            <div class="hero-value-row">
              <span class="hero-value ${isAvailable ? 'val-active' : 'val-unavailable'}">
                ${isAvailable ? `${estimatedSolarKwh.toFixed(1)} kWh` : 'Unavailable'}
              </span>
            </div>
          </div>
        </div>

        <div class="telemetry-grid grid-3col mt-3">
          ${renderTelemetryField({
            label: "Solar Array Surface Area",
            value: panelSizeM2,
            unit: "m²",
            decimals: 1,
            source: "Ship Specification",
            provenance: "OBSERVED",
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Panel Efficiency",
            value: panelEfficiencyPct,
            unit: "%",
            decimals: 1,
            source: "Hardware Spec",
            provenance: "OBSERVED",
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Monthly Average Daily GHI",
            value: dailyGhiKwhM2,
            unit: "kWh/m²/day",
            decimals: 2,
            source: "NASA POWER",
            provenance: "CLIMATOLOGICAL_ESTIMATE",
            nullPlaceholder: "Unavailable",
          })}
        </div>

        ${diurnalUncertaintyFlag ? `
          <div class="uncertainty-alert-box mt-3">
            <span class="alert-icon">⚠️</span>
            <span><strong>Diurnal Uncertainty Notice:</strong> Voyage duration exceeds 24.0 hours. Climatological daily average scaling assumes uniform daily insolation distribution.</span>
          </div>
        ` : ''}

        <div class="semantic-boundary-note mt-3">
          <span class="info-icon">ℹ️</span>
          <span><strong>Semantic Limitation:</strong> Solar metrics represent climatological scenario estimates derived from monthly NASA POWER averages. Not an hourly dynamic solar simulator.</span>
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
