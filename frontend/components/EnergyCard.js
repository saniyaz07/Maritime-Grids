/**
 * frontend/components/EnergyCard.js — Phase 10C.11B Energy, Fuel & Battery State Cards
 * ====================================================================================
 * Displays detailed fuel telemetry (Remaining, Consumption Rate) and battery telemetry
 * (State of Charge, State of Health, Usable Energy Capacity).
 * 
 * Strict Invariants:
 *   - Null is NEVER rendered as 0 (e.g. fuel = null displays "Unavailable", not "0 L").
 *   - Battery SOC and SOH are displayed as percentages (0.0-100.0%).
 *   - Shows source, provenance, and timestamp.
 */

import { renderTelemetryField } from "./ProvenanceBadge.js";

export function renderFuelCard({
  fuelRemainingLiters = null,
  fuelConsumptionRateLph = null,
  fuelPriceUsdPerLiter = null,
  fuelType = "Diesel",
  provenance = "OBSERVED",
  timestamp = null,
  source = "Flow Meter / Tank Sounding",
  etaUtc = null,
  fuelConsumedLiters = null,
}) {
  const isFuelAvail = fuelRemainingLiters !== null && fuelRemainingLiters !== undefined;

  return `
    <div class="dashboard-card fuel-telemetry-card compact-energy-card">
      <div class="card-header compact-header">
        <div class="card-title-group">
          <h3>FUEL &amp; VOYAGE</h3>
          <span class="card-subtitle">Fuel Grade: ${escapeHtml(fuelType)} | Source: ${escapeHtml(source)}</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-${provenance.toLowerCase()}">${escapeHtml(provenance)}</span>
        </div>
      </div>

      <div class="card-body compact-card-body">
        <div class="telemetry-grid grid-3col">
          <div class="stat-box hero-stat-box">
            <span class="stat-label">Remaining Fuel</span>
            <span class="stat-value ${isFuelAvail ? 'val-active' : 'val-unavailable'}">
              ${isFuelAvail ? `${fuelRemainingLiters.toLocaleString('en-US', { maximumFractionDigits: 1 })} L` : 'Unavailable'}
            </span>
          </div>

          ${renderTelemetryField({
            label: "Consumption Rate",
            value: fuelConsumptionRateLph,
            unit: "L/h",
            decimals: 1,
            source,
            provenance,
            timestamp,
            nullPlaceholder: "Unavailable",
          })}

          <div class="stat-box">
            <span class="stat-label">Estimated Arrival</span>
            <span class="stat-value text-green">${etaUtc ? escapeHtml(etaUtc) : 'In transit'}</span>
          </div>
        </div>

        <!-- Collapsible Details: Consumed Fuel, Financial & Voyage Assumptions -->
        <details class="energy-details-collapsible mt-2">
          <summary class="energy-details-summary">
            <span>📊 Detailed Consumption &amp; Financials</span>
          </summary>
          <div class="telemetry-grid grid-2col mt-2 pt-2 border-top-subtle">
            ${renderTelemetryField({
              label: "Fuel Consumed So Far",
              value: fuelConsumedLiters,
              unit: "L",
              decimals: 1,
              source: "Virtual Energy Estimator",
              provenance: "DERIVED",
              nullPlaceholder: "Unavailable",
            })}

            ${renderTelemetryField({
              label: "Unit Fuel Price",
              value: fuelPriceUsdPerLiter,
              unit: "$/L",
              decimals: 2,
              source: "Financial Baseline",
              provenance: "OBSERVED",
              nullPlaceholder: "Unavailable",
            })}
          </div>
        </details>
      </div>
    </div>
  `;
}

export function renderBatteryCard({
  batterySocPct = null,
  batterySohPct = null,
  batteryEnergyAvailableKwh = null,
  nominalCapacityKwh = null,
  provenance = "OBSERVED",
  timestamp = null,
  source = "BMS Telemetry",
}) {
  const isSocAvail = batterySocPct !== null && batterySocPct !== undefined;
  const socDisplay = isSocAvail ? `${batterySocPct.toFixed(1)}%` : "Unavailable";

  // Visual SOC fill color
  let socColorClass = "soc-normal";
  if (isSocAvail) {
    if (batterySocPct < 20.0) socColorClass = "soc-critical";
    else if (batterySocPct < 35.0) socColorClass = "soc-warning";
    else socColorClass = "soc-normal";
  }

  return `
    <div class="dashboard-card battery-telemetry-card compact-energy-card">
      <div class="card-header compact-header">
        <div class="card-title-group">
          <h3>BATTERY &amp; STORAGE</h3>
          <span class="card-subtitle">Source: ${escapeHtml(source)}</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-${provenance.toLowerCase()}">${escapeHtml(provenance)}</span>
        </div>
      </div>

      <div class="card-body compact-card-body">
        <div class="battery-hero-gauge-compact">
          <div class="battery-metric-left">
            <span class="hero-label">State of Charge (SOC)</span>
            <div class="hero-value-row">
              <span class="hero-value ${isSocAvail ? socColorClass : 'val-unavailable'}">
                ${escapeHtml(socDisplay)}
              </span>
            </div>
          </div>
          ${isSocAvail ? `
            <div class="soc-mini-gauge">
              <div class="soc-gauge-bar ${socColorClass}" style="width: ${Math.min(100, Math.max(0, batterySocPct))}%;"></div>
            </div>
          ` : ''}
        </div>

        <div class="telemetry-grid grid-3col mt-2">
          ${renderTelemetryField({
            label: "State of Health (SOH)",
            value: batterySohPct,
            unit: "%",
            decimals: 1,
            source: "Model / Degradation",
            provenance: "MODEL_PREDICTION",
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Usable Stored Energy",
            value: batteryEnergyAvailableKwh,
            unit: "kWh",
            decimals: 1,
            source,
            provenance,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Nominal Pack Capacity",
            value: nominalCapacityKwh,
            unit: "kWh",
            decimals: 0,
            source: "Nameplate Spec",
            provenance: "OBSERVED",
            nullPlaceholder: "Unavailable",
          })}
        </div>
      </div>
    </div>
  `;
}

export function renderEnergyCard(energyState = null) {
  if (!energyState) {
    return `
      <div class="dashboard-card energy-state-card">
        <div class="card-header">
          <h3>ENERGY & FUEL TELEMETRY</h3>
          <span class="status-pill status-unknown">No Telemetry</span>
        </div>
        <div class="card-body">
          <p class="empty-state-text">No energy or fuel telemetry reported.</p>
        </div>
      </div>
    `;
  }

  let soc = energyState.battery_soc_pct;
  if (soc === undefined && energyState.battery_soc !== undefined) {
    soc = energyState.battery_soc !== null ? energyState.battery_soc * (energyState.battery_soc <= 1.0 ? 100.0 : 1.0) : null;
  }
  let soh = energyState.battery_soh_pct;
  if (soh === undefined && energyState.battery_soh !== undefined) {
    soh = energyState.battery_soh !== null ? energyState.battery_soh * (energyState.battery_soh <= 1.0 ? 100.0 : 1.0) : null;
  }
  const usableKwh = energyState.battery_energy_available_kwh;
  const fuelRem = energyState.fuel_remaining_liters;
  let fuelRate = energyState.fuel_consumption_rate_lph;
  if (fuelRate === undefined && energyState.estimated_fuel_consumption_rate_l_per_hour !== undefined) {
    fuelRate = energyState.estimated_fuel_consumption_rate_l_per_hour;
  }
  const prov = energyState.provenance || "OBSERVED";

  return `
    <div class="dashboard-card energy-state-card">
      <div class="card-header">
        <div class="card-title-group">
          <h3>ENERGY & FUEL TELEMETRY</h3>
          <span class="card-subtitle">Powertrain Clean Hybrid Energy State</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-${prov.toLowerCase()}">${escapeHtml(prov)}</span>
        </div>
      </div>

      <div class="card-body">
        <div class="telemetry-grid grid-3col">
          ${renderTelemetryField({
            label: "Battery SOC",
            value: soc,
            unit: "%",
            decimals: 1,
            source: "BMS Telemetry",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Battery SOH",
            value: soh,
            unit: "%",
            decimals: 1,
            source: "BMS Telemetry",
            provenance: prov,
            nullPlaceholder: "No SOH telemetry",
          })}

          ${renderTelemetryField({
            label: "Usable Battery Storage",
            value: usableKwh,
            unit: "kWh",
            decimals: 1,
            source: "BMS Telemetry",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Fuel Remaining",
            value: fuelRem,
            unit: "L",
            decimals: 1,
            source: "Tank Sounding",
            provenance: prov,
            nullPlaceholder: "Unavailable",
          })}

          ${renderTelemetryField({
            label: "Fuel Consumption Rate",
            value: fuelRate,
            unit: "L/h",
            decimals: 1,
            source: "Flow Meter",
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
