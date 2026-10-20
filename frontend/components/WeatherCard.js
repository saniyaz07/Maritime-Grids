/**
 * frontend/components/WeatherCard.js — Phase 10C.11A Operational Weather State Card
 * ==================================================================================
 * Displays normalized weather telemetry (wind, waves, atmospheric, currents).
 * 
 * Strict Invariants:
 *   - Null / missing fields visibly remain "Unavailable" (null != 0).
 *   - Displays Value, Unit, Source, Provenance, Quality, Freshness, Timestamp.
 *   - Distinguishes FORECAST from OBSERVED.
 *   - Clearly states that continuous wind/wave telemetry feeds the operational advisory
 *     system and does NOT directly alter the discrete Phase 2 fuel_xgb model.
 */

import { renderTelemetryField, renderProvenanceMetadata } from "./ProvenanceBadge.js";

export function renderWeatherCard(weatherContext = null) {
  if (!weatherContext) {
    return `
      <div class="dashboard-card weather-card">
        <div class="card-header">
          <h3>Operational Route Weather</h3>
          <span class="status-pill quality-unavailable">No Weather Context</span>
        </div>
        <div class="card-body">
          <p class="empty-state-text">No active weather telemetry or forecast profile available for this context.</p>
        </div>
      </div>
    `;
  }

  // Determine primary point weather (departure, arrival, or direct ocean fields)
  const weatherPoint = weatherContext.departure_weather || weatherContext.arrival_weather || weatherContext.current_weather || (weatherContext.wind_speed_knots !== undefined ? weatherContext : null);
  const prov = weatherContext.weather_provenance || weatherPoint?.provenance || "UNAVAILABLE";
  const qual = weatherContext.weather_quality || weatherPoint?.quality || "VALID";
  const fresh = weatherContext.weather_freshness || weatherPoint?.freshness || "FRESH";
  const time = weatherContext.weather_timestamp_utc || weatherPoint?.timestamp_utc || null;
  const source = weatherPoint?.data_source || weatherContext.data_source || "Open-Meteo / Climatology";

  // Individual variables
  const windSpd = weatherPoint?.wind_speed_knots;
  const windDir = weatherPoint?.wind_direction_deg;
  const waveHgt = weatherPoint?.wave_height_m;
  const waveDir = weatherPoint?.wave_direction_deg;
  const wavePer = weatherPoint?.wave_period_s;
  const tempC = weatherPoint?.temperature_c !== undefined ? weatherPoint.temperature_c : weatherPoint?.air_temperature_c;
  const relHum = weatherPoint?.relative_humidity_pct !== undefined ? weatherPoint.relative_humidity_pct : weatherPoint?.humidity_pct;
  const pressHpa = weatherPoint?.surface_pressure_hpa !== undefined ? weatherPoint.surface_pressure_hpa : weatherPoint?.pressure_hpa;
  const currSpd = weatherPoint?.current_speed_knots;
  const currDir = weatherPoint?.current_direction_deg;

  const lat = weatherContext.vessel_latitude ?? weatherPoint?.latitude ?? null;
  const lon = weatherContext.vessel_longitude ?? weatherPoint?.longitude ?? null;
  const locStr = (lat !== null && lon !== null) ? ` • Location: ${lat.toFixed(2)}°N, ${lon.toFixed(2)}°E` : "";
  const isManual = weatherContext.environmental_mode === "MANUAL_SCENARIO" || String(source).includes("Manual");

  return `
    <div class="dashboard-card weather-card">
      <div class="card-header">
        <div class="card-title-group">
          <h3>Local Vessel Environmental Telemetry</h3>
          <span class="card-subtitle">Source: ${escapeHtml(source)}${locStr}${time ? ` • Observation/Model Time: ${escapeHtml(time)}` : ''}</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-${prov.toLowerCase()}">${escapeHtml(prov)}</span>
          ${isManual ? '<span class="status-pill status-paused">MANUAL SCENARIO</span>' : '<span class="status-pill status-active">LOCAL CONDITIONS</span>'}
          <span class="meta-tag meta-quality quality-${qual.toLowerCase()}">${escapeHtml(qual)}</span>
          <span class="meta-tag meta-freshness freshness-${fresh.toLowerCase()}">${escapeHtml(fresh)}</span>
        </div>
      </div>

      <div class="card-body">
        <div class="telemetry-grid grid-4col">
          ${renderTelemetryField({
            label: "Wind Speed",
            value: windSpd,
            unit: "kn",
            decimals: 1,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Wind Direction",
            value: windDir,
            unit: "°",
            decimals: 0,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Wave Height (Significant)",
            value: waveHgt,
            unit: "m",
            decimals: 2,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Wave Period",
            value: wavePer,
            unit: "s",
            decimals: 1,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Wave Direction",
            value: waveDir,
            unit: "°",
            decimals: 0,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Ambient Temperature",
            value: tempC,
            unit: "°C",
            decimals: 1,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Relative Humidity",
            value: relHum,
            unit: "%",
            decimals: 0,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Surface Pressure",
            value: pressHpa,
            unit: "hPa",
            decimals: 1,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Ocean Current Speed",
            value: currSpd,
            unit: "kn",
            decimals: 1,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}

          ${renderTelemetryField({
            label: "Ocean Current Direction",
            value: currDir,
            unit: "°",
            decimals: 0,
            source,
            provenance: prov,
            quality: qual,
            freshness: fresh,
            timestamp: time,
          })}
        </div>

        ${weatherContext?.lookahead ? renderLookaheadTable(weatherContext.lookahead, weatherContext) : ''}

        <div class="semantic-boundary-note mt-3">
          <span class="info-icon">ℹ️</span>
          <span><strong>Semantic Boundary:</strong> Live atmospheric telemetry feeds operational bridge advisories. Continuous wind/wave data does not directly alter discrete Phase 2 fuel model coefficients.</span>
        </div>
      </div>
    </div>
  `;
}

export function renderLookaheadTable(lookahead = null, weatherContext = null) {
  if (!lookahead || !lookahead.waypoints || lookahead.waypoints.length === 0) {
    return `
      <div class="lookahead-empty-state mt-3">
        <p class="text-muted">Route weather spacetime look-ahead will update as vessel progresses along route.</p>
      </div>
    `;
  }

  const summary = lookahead.summary || {};
  const waypoints = lookahead.waypoints;
  const isManual = weatherContext?.environmental_mode === "MANUAL_SCENARIO";
  const localWind = weatherContext?.departure_weather?.wind_speed_knots ?? null;
  const localWave = weatherContext?.departure_weather?.wave_height_m ?? null;

  return `
    <div class="lookahead-section mt-4">
      <div class="lookahead-header d-flex justify-content-between align-items-center mb-2">
        <h4 class="m-0">ROUTE WEATHER SPACETIME LOOK-AHEAD</h4>
        <div class="lookahead-badges">
          <span class="meta-tag meta-prov prov-forecast">FORECAST</span>
          <span class="status-pill status-${String(lookahead.timing_status).toLowerCase()}">${escapeHtml(lookahead.timing_status)}</span>
        </div>
      </div>

      <div class="lookahead-context-desc text-muted mb-2" style="font-size: 0.85rem;">
        <span><strong>Forecast Horizon:</strong> Spacetime forecast queried at planned corridor waypoints (WP1 → WP3) for future arrival times (ETA UTC) via Open-Meteo API. Distinct from immediate vessel local conditions.</span>
      </div>

      ${isManual ? `
        <div class="alert-banner alert-info mb-3">
          <span class="alert-icon">ℹ️</span>
          <div class="alert-content">
            <strong>LOCAL MANUAL SCENARIO ACTIVE:</strong> Immediate vessel physics are currently driven by manual scenario settings (Wind: ${localWind !== null ? `${localWind.toFixed(1)} kn` : 'N/A'}, Waves: ${localWave !== null ? `${localWave.toFixed(1)} m` : 'N/A'}). The forward waypoint table below shows the external meteorological forecast along the corridor.
          </div>
        </div>
      ` : ''}

      ${summary.has_adverse_conditions ? `
        <div class="alert-banner alert-warning mb-3">
          <span class="alert-icon">⚠️</span>
          <div class="alert-content">
            <strong>ADVERSE WEATHER PROJECTED AHEAD:</strong>
            ${summary.adverse_condition_reasons ? summary.adverse_condition_reasons.map(r => `<div>• ${escapeHtml(r)}</div>`).join("") : ''}
          </div>
        </div>
      ` : ''}

      <div class="lookahead-summary-strip mb-3">
        <span><strong>Coverage:</strong> ${summary.total_lookahead_distance_nm !== undefined ? `${summary.total_lookahead_distance_nm.toFixed(1)} NM` : 'N/A'}</span>
        <span><strong>Duration:</strong> ${summary.total_lookahead_hours !== null && summary.total_lookahead_hours !== undefined ? `+${summary.total_lookahead_hours.toFixed(1)}h` : 'N/A (Stationary)'}</span>
        <span><strong>Max Wind Ahead:</strong> ${summary.max_wind_knots !== null && summary.max_wind_knots !== undefined ? `${summary.max_wind_knots.toFixed(1)} kn` : 'N/A'}</span>
        <span><strong>Max Waves Ahead:</strong> ${summary.max_wave_height_m !== null && summary.max_wave_height_m !== undefined ? `${summary.max_wave_height_m.toFixed(2)} m` : 'N/A'}</span>
      </div>

      <div class="telemetry-history-table-wrapper">
        <table class="telemetry-history-table lookahead-table">
          <thead>
            <tr>
              <th>Waypoint</th>
              <th>Distance Ahead</th>
              <th>ETA (UTC)</th>
              <th>Forecast Wind</th>
              <th>Forecast Waves</th>
              <th>Alerts</th>
            </tr>
          </thead>
          <tbody>
            ${waypoints.map(wp => {
              const wx = wp.weather || {};
              const etaStr = wp.estimated_arrival_utc ? (wp.hours_ahead !== null && wp.hours_ahead !== undefined ? `+${wp.hours_ahead.toFixed(1)}h (${wp.estimated_arrival_utc.slice(11, 16)}Z)` : wp.estimated_arrival_utc) : 'N/A (Stationary)';
              const windStr = wx.wind_speed_knots !== null && wx.wind_speed_knots !== undefined ? `${wx.wind_speed_knots.toFixed(1)} kn` : 'N/A';
              const waveStr = wx.wave_height_m !== null && wx.wave_height_m !== undefined ? `${wx.wave_height_m.toFixed(2)} m` : 'N/A';

              return `
                <tr class="${wp.high_wind_warning || wp.rough_sea_warning ? 'table-row-warning' : ''}">
                  <td><strong>${escapeHtml(wp.waypoint_id)}</strong></td>
                  <td>${wp.distance_from_vessel_nm !== undefined ? `${wp.distance_from_vessel_nm.toFixed(1)} NM` : 'N/A'}</td>
                  <td><code>${escapeHtml(etaStr)}</code></td>
                  <td>${escapeHtml(windStr)}</td>
                  <td>${escapeHtml(waveStr)}</td>
                  <td>
                    ${wp.high_wind_warning ? '<span class="status-pill status-warning">HIGH WIND</span>' : ''}
                    ${wp.rough_sea_warning ? '<span class="status-pill status-warning">ROUGH SEAS</span>' : ''}
                    ${!wp.high_wind_warning && !wp.rough_sea_warning ? '<span class="status-pill status-normal">FAVORABLE</span>' : ''}
                  </td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
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
