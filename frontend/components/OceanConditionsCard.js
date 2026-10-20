/**
 * frontend/components/OceanConditionsCard.js — Ocean & Environmental Forces Presentation
 * ====================================================================================
 * Displays key live marine and atmospheric environmental conditions acting upon the virtual vessel:
 *   - Key display: Wind Speed, Wave Height, Ocean Current Speed
 *   - Source and Freshness metadata
 *   - Expandable details: Wind direction, wave direction, wave period, temperature, humidity, pressure, current direction
 * 
 * Provenance:
 *   - Clearly tagged with FORECAST / SIMULATED.
 */

import { renderTelemetryField } from "./ProvenanceBadge.js";

export function renderOceanConditionsCard(ocean = null) {
  if (!ocean) {
    return `
      <div class="dashboard-card ocean-conditions-card compact-ocean-card">
        <div class="card-header compact-header">
          <h3>OCEAN CONDITIONS</h3>
          <span class="status-pill status-unknown">Unavailable</span>
        </div>
        <div class="card-body">
          <p class="empty-state-text">No environmental data available.</p>
        </div>
      </div>
    `;
  }

  const windSpd = ocean.wind_speed_knots;
  const windDir = ocean.wind_direction_deg;
  const waveHs = ocean.wave_height_m;
  const waveTp = ocean.wave_period_s;
  const waveDir = ocean.wave_direction_deg;
  const currSpd = ocean.current_speed_knots;
  const currDir = ocean.current_direction_deg;
  const airTemp = ocean.air_temperature_c;
  const humidity = ocean.humidity_pct;
  const pressure = ocean.pressure_hpa;
  const prov = ocean.provenance || "FORECAST";

  const isSevere = (waveHs !== null && waveHs >= 2.5) || (windSpd !== null && windSpd >= 25.0);

  return `
    <div class="dashboard-card ocean-conditions-card compact-ocean-card">
      <div class="card-header compact-header">
        <div class="card-title-group">
          <h3>OCEAN CONDITIONS</h3>
          <span class="card-subtitle">Source: ${escapeHtml(ocean.weather_source || "Open-Meteo API")}${ocean.source_timestamp_utc ? ` | ${escapeHtml(ocean.source_timestamp_utc.slice(11, 19))} UTC` : ''}</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-${prov.toLowerCase()}">${escapeHtml(prov)}</span>
          <span class="status-pill status-${ocean.environmental_mode === 'MANUAL_SCENARIO' ? 'paused' : 'active'}">
            ${ocean.environmental_mode === 'MANUAL_SCENARIO' ? 'MANUAL' : 'AUTO'}
          </span>
          <span class="meta-tag meta-freshness freshness-${(ocean.weather_freshness || 'fresh').toLowerCase()}">
            ${escapeHtml(ocean.weather_freshness || 'FRESH')}
          </span>
          ${isSevere ? '<span class="status-pill status-critical">⚠️ ADVERSE</span>' : '<span class="status-pill status-active">NORMAL</span>'}
        </div>
      </div>

      <div class="card-body compact-card-body card-scrollable-body">
        <!-- Compact 3-Column Environmental Force Grid -->
        <div class="telemetry-grid grid-3col tight-metric-grid">
          ${renderTelemetryField({
            label: "Sustained Wind",
            value: windSpd,
            unit: "kn",
            decimals: 1,
            source: "Marine Forecast",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Significant Wave (Hs)",
            value: waveHs,
            unit: "m",
            decimals: 1,
            source: "Wave Model",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Current Drift Speed",
            value: currSpd,
            unit: "kn",
            decimals: 1,
            source: "Ocean Hydrodynamics",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Wind Direction",
            value: windDir,
            unit: "°",
            decimals: 0,
            source: "Marine Forecast",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Peak Wave Period (Tp)",
            value: waveTp,
            unit: "s",
            decimals: 1,
            source: "Wave Model",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Wave Propagation Dir",
            value: waveDir,
            unit: "°",
            decimals: 0,
            source: "Wave Model",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Current Setting Dir",
            value: currDir,
            unit: "°",
            decimals: 0,
            source: "Ocean Hydrodynamics",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Air Temperature",
            value: airTemp,
            unit: "°C",
            decimals: 1,
            source: "Atmospheric Sensor",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Relative Humidity",
            value: humidity,
            unit: "%",
            decimals: 0,
            source: "Atmospheric Sensor",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Atmospheric Pressure",
            value: pressure,
            unit: "hPa",
            decimals: 0,
            source: "Barometer",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}
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
