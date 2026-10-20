/**
 * frontend/components/EngineeringWorkbench.js — Phase 10C.11A Engineering Scenario Workbench
 * =========================================================================================
 * Provides the interactive UI for the 10 verified engineering operations under /api/v1/engineering/*:
 *   1. Voyage Simulation
 *   2. Sizing Evaluation
 *   3. Sizing Optimization
 *   4. Sensitivity Analysis
 *   5. Break-Even Analysis
 *   6. 2D Grid Analysis
 *   7. Speed & Sizing Co-Optimization
 *   8. Fleet Portfolio Optimization
 *   9. CII Trajectory Simulation
 *   10. Scenario Dossier Export
 * 
 * Strict Invariant: Zero duplicated physics in frontend. All computations execute via backend REST API.
 */

export function renderEngineeringWorkbench({
  activeOperation = "simulate-voyage",
  loading = false,
  result = null,
  error = null,
}) {
  const operations = [
    { id: "simulate-voyage", label: "1. Voyage Simulation", desc: "Execute baseline simulation, clean energy displacement, and statutory CII assessment." },
    { id: "evaluate-sizing", label: "2. Sizing Evaluation", desc: "Evaluate techno-economic NPV, IRR, payback, and LCOE for specific solar/battery sizing." },
    { id: "optimize-sizing", label: "3. Sizing Optimization", desc: "Search discrete parameter space for optimal clean-energy retrofit configurations." },
    { id: "speed-cooptimization", label: "4. Speed Co-Optimization", desc: "Simultaneous 3D Pareto optimization over speed, solar area, and battery capacity." },
    { id: "sensitivity-analysis", label: "5. Sensitivity Analysis", desc: "1D parameter sweeps over fuel price, capex, carbon price, and discount rates." },
    { id: "break-even-analysis", label: "6. Break-Even Analysis", desc: "Calculate exact threshold values where lifecycle NPV reaches $0.00." },
    { id: "grid-2d-analysis", label: "7. 2D Grid Analysis", desc: "2D surface exploration across fuel prices and capital expenditures." },
    { id: "portfolio-optimization", label: "8. Fleet Portfolio", desc: "Capital-budgeted multi-vessel clean energy investment allocation." },
    { id: "cii-trajectory", label: "9. CII Trajectory", desc: "Multi-year aging trajectory with battery/solar degradation." },
    { id: "export-dossier", label: "10. Scenario Dossier", desc: "Generate and export comprehensive Markdown engineering dossiers." },
  ];

  const opTabsHtml = operations.map(op => `
    <button class="eng-tab-btn ${op.id === activeOperation ? 'active' : ''}" data-op-id="${op.id}">
      <span class="tab-title">${escapeHtml(op.label)}</span>
    </button>
  `).join("\n");

  const currentOp = operations.find(o => o.id === activeOperation) || operations[0];

  return `
    <div class="dashboard-card engineering-workbench-card">
      <div class="card-header">
        <div class="card-title-group">
          <h3>Engineering Scenario Workbench</h3>
          <span class="card-subtitle">${escapeHtml(currentOp.desc)}</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-model_prediction">Deterministic Core</span>
        </div>
      </div>

      <div class="card-body">
        <div class="engineering-layout">
          <!-- Left: Operation Selector -->
          <div class="operation-selector-panel">
            <h4 class="section-title">Computational Operations</h4>
            <div class="eng-tabs-list">
              ${opTabsHtml}
            </div>
          </div>

          <!-- Right: Scenario Config & Results -->
          <div class="operation-workspace-panel">
            <div class="workspace-header">
              <h4>Scenario Execution: ${escapeHtml(currentOp.label)}</h4>
              <button id="btn-run-operation" class="btn btn-primary" ${loading ? 'disabled' : ''}>
                ${loading ? '<span class="spinner"></span> Executing...' : '▶ Run Simulation'}
              </button>
            </div>

            <!-- Standard Configuration Inputs -->
            <div class="form-grid grid-3col mt-3">
              <div class="form-group">
                <label for="eng-ship-type">Ship Type</label>
                <select id="eng-ship-type" class="form-control">
                  <option value="Oil Service Boat" selected>Oil Service Boat</option>
                  <option value="Fishing Trawler">Fishing Trawler</option>
                  <option value="Surfer Boat">Surfer Boat</option>
                  <option value="Tanker Ship">Tanker Ship</option>
                </select>
              </div>

              <div class="form-group">
                <label for="eng-route-id">Route Corridor</label>
                <select id="eng-route-id" class="form-control">
                  <option value="Escravos-Lagos" selected>Escravos-Lagos (250 nm)</option>
                  <option value="Warri-Bonny">Warri-Bonny (250 nm)</option>
                  <option value="Lagos-Apapa">Lagos-Apapa (120 nm)</option>
                  <option value="Port Harcourt-Lagos">Port Harcourt-Lagos (450 nm)</option>
                </select>
              </div>

              <div class="form-group">
                <label for="eng-speed-knots">Transit Speed (knots)</label>
                <input type="number" id="eng-speed-knots" class="form-control" value="12.0" min="1.0" max="35.0" step="0.5">
              </div>

              <div class="form-group">
                <label for="eng-month">Calendar Month</label>
                <select id="eng-month" class="form-control">
                  <option value="1">January</option>
                  <option value="2">February</option>
                  <option value="3">March</option>
                  <option value="4">April</option>
                  <option value="5">May</option>
                  <option value="6">June</option>
                  <option value="7" selected>July</option>
                  <option value="8">August</option>
                  <option value="9">September</option>
                  <option value="10">October</option>
                  <option value="11">November</option>
                  <option value="12">December</option>
                </select>
              </div>

              <div class="form-group">
                <label for="eng-solar-m2">Solar Array Area (m²)</label>
                <input type="number" id="eng-solar-m2" class="form-control" value="80.0" min="0" step="5">
              </div>

              <div class="form-group">
                <label for="eng-batt-kwh">Battery Capacity (kWh)</label>
                <input type="number" id="eng-batt-kwh" class="form-control" value="650.0" min="0" step="25">
              </div>

              <div class="form-group">
                <label for="eng-fuel-price">Fuel Price (USD/L Override)</label>
                <input type="number" id="eng-fuel-price" class="form-control" placeholder="Default from profile" step="0.05">
              </div>
            </div>

            <!-- Execution Results Area -->
            <div class="results-container mt-4">
              <h4 class="section-title">Execution Results</h4>
              
              ${error ? `
                <div class="error-banner">
                  <span class="error-icon">❌</span>
                  <span><strong>Execution Error:</strong> ${escapeHtml(error.message || JSON.stringify(error))}</span>
                </div>
              ` : ''}

              ${loading ? `
                <div class="loading-state-box">
                  <div class="large-spinner"></div>
                  <p>Running verified backend engineering models...</p>
                </div>
              ` : ''}

              ${!loading && !error && result ? `
                <div class="result-success-box">
                  ${renderHumanReadableEngineeringSummary(result)}
                </div>
              ` : ''}

              ${!loading && !error && !result ? `
                <div class="empty-state-text">Select parameters and click 'Run Simulation' to execute operation against verified backend models.</div>
              ` : ''}
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

function getMonthName(m) {
  if (!m) return "July";
  const num = parseInt(m, 10);
  if (!isNaN(num) && num >= 1 && num <= 12) {
    return MONTH_NAMES[num - 1];
  }
  return String(m);
}

function formatNum(val, decimals = 2, fallback = "—") {
  if (val === null || val === undefined || isNaN(Number(val))) return fallback;
  return Number(val).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/**
 * Converts structured simulation results into clean, table-first representations
 * so non-technical and specialist users alike can immediately inspect voyage outcomes.
 */
export function renderHumanReadableEngineeringSummary(result) {
  if (!result) return "";

  const data = result.data || result;
  const prov = result.provenance || data.provenance || {};
  const req = data.request || {};
  const phase3 = data.phase3_output || {};
  const meta = phase3.voyage_metadata || {};
  const tier1 = data.tier1_predictions || phase3.tier_1_phase2_predictions || {};
  const weather = tier1.weather || {};
  const fuelPred = tier1.fuel_consumption_L || {};
  const co2Pred = tier1.co2_emissions_kg || {};
  const baseMetrics = phase3.tier_2_baseline_metrics || {};
  const cleanFeas = phase3.tier_3_clean_energy_feasibility || {};
  const engScen = phase3.tier_4_engineering_scenario_estimates || {};
  const reg = data.regulatory_assessment || {};

  // 1. Voyage Summary Parameters
  const shipType = meta.ship_type || req.ship_type || prov.vessel_id || "Oil Service Boat";
  const route = req.route_id || "Escravos-Lagos";
  const distanceNm = meta.distance_nm ?? req.distance_nm ?? 250.0;
  const transitSpeed = req.speed_knots ?? 12.0;
  const durationHours = meta.voyage_duration_hours ?? (distanceNm && transitSpeed ? (distanceNm / transitSpeed) : 20.83);
  const calendarMonth = getMonthName(req.month);

  // 2. Fuel and Environmental Impact Parameters
  const baseFuelL = fuelPred.value !== undefined ? Number(fuelPred.value) : (baseMetrics.baseline_fuel_L !== undefined ? Number(baseMetrics.baseline_fuel_L) : null);
  const netFuelL = engScen.net_assisted_fuel_L !== undefined ? Number(engScen.net_assisted_fuel_L) : null;
  const displacedFuelL = engScen.estimated_fuel_displaced_L !== undefined ? Number(engScen.estimated_fuel_displaced_L) : (baseFuelL !== null && netFuelL !== null ? baseFuelL - netFuelL : null);
  const deltaFuelPct = engScen.delta_fuel_pct !== undefined ? Number(engScen.delta_fuel_pct) : (baseFuelL && netFuelL ? ((netFuelL - baseFuelL) / baseFuelL * 100) : null);

  const baseCo2Kg = co2Pred.value !== undefined ? Number(co2Pred.value) : (reg.baseline_co2_kg !== undefined ? Number(reg.baseline_co2_kg) : null);
  const netCo2Kg = engScen.net_assisted_co2_kg !== undefined ? Number(engScen.net_assisted_co2_kg) : (reg.net_assisted_co2_kg !== undefined ? Number(reg.net_assisted_co2_kg) : null);
  const displacedCo2Kg = engScen.estimated_co2_displaced_kg !== undefined ? Number(engScen.estimated_co2_displaced_kg) : (baseCo2Kg !== null && netCo2Kg !== null ? baseCo2Kg - netCo2Kg : null);

  const baseCii = baseMetrics.baseline_operational_cii_gco2_per_dwt_nm !== undefined ? Number(baseMetrics.baseline_operational_cii_gco2_per_dwt_nm) : (reg.baseline_attained_cii !== undefined ? Number(reg.baseline_attained_cii) : null);
  const netCii = engScen.net_assisted_operational_cii_gco2_per_dwt_nm !== undefined ? Number(engScen.net_assisted_operational_cii_gco2_per_dwt_nm) : (reg.assisted_attained_cii !== undefined ? Number(reg.assisted_attained_cii) : null);
  const deltaCiiPct = engScen.delta_cii_pct !== undefined ? Number(engScen.delta_cii_pct) : (baseCii && netCii ? ((netCii - baseCii) / baseCii * 100) : null);

  // 3. Clean Energy Analysis Parameters
  const solarEnergyKwh = cleanFeas.estimated_solar_energy_kwh !== undefined ? Number(cleanFeas.estimated_solar_energy_kwh) : null;
  const usableBatteryKwh = cleanFeas.usable_battery_energy_kwh !== undefined ? Number(cleanFeas.usable_battery_energy_kwh) : null;
  const cleanEnergyAvailKwh = cleanFeas.total_clean_energy_available_kwh !== undefined ? Number(cleanFeas.total_clean_energy_available_kwh) : null;
  const cleanEnergyUtilKwh = cleanFeas.clean_energy_utilized_kwh !== undefined ? Number(cleanFeas.clean_energy_utilized_kwh) : null;
  const energyBalanceKwh = cleanFeas.energy_balance_kwh !== undefined ? Number(cleanFeas.energy_balance_kwh) : null;
  const energyDeficitKwh = cleanFeas.energy_deficit_kwh !== undefined ? Number(cleanFeas.energy_deficit_kwh) : 0.0;
  const feasStatus = cleanFeas.feasibility_status || "FEASIBLE";

  // 4. Regulatory Assessment Parameters
  const evalYear = reg.evaluation_year ?? req.evaluation_year ?? 2026;
  const rawRating = reg.assisted_cii_rating || reg.baseline_cii_rating;
  let ciiRatingText = "NOT ASSESSED";
  let ciiRatingClass = "rating-not-assessed";
  if (rawRating && rawRating !== "NOT_ASSESSED" && rawRating !== "NOT ASSESSED" && reg.cii_assessment_status !== "UNSUPPORTED_VESSEL_CATEGORY_MAPPING") {
    ciiRatingText = rawRating.toUpperCase().startsWith("BAND") ? rawRating : `BAND ${rawRating}`;
    ciiRatingClass = `rating-${rawRating.toLowerCase().replace(/[^a-z0-9]/g, "")}`;
  }
  const assessmentStatusText = reg.cii_assessment_status ? reg.cii_assessment_status.replace(/_/g, " ") : "NOT ASSESSED";
  const regulatoryRefText = reg.source_document || "IMO Resolution MEPC.353(78) & MEPC.354(78)";
  const disclaimerText = reg.disclaimer || "CII rating bands (A-E) apply strictly to qualifying vessel categories under MARPOL Annex VI Reg 28. For non-qualifying vessels, numerical CII is reported as an engineering metric, but statutory rating is NOT_ASSESSED.";

  // Root-Finding Break-Even Analysis Result (if applicable)
  const isBreakEven = data.break_even_value !== undefined || prov.operation === "RUN_BREAK_EVEN_ANALYSIS";
  const breakEvenVal = data.break_even_value !== undefined ? Number(data.break_even_value).toFixed(4) : null;

  return `
    <div class="eng-summary-report">
      ${isBreakEven && breakEvenVal ? `
        <!-- Break-Even Analysis Solution -->
        <div class="eng-table-section break-even-highlight-card" style="border: 1px solid #10b981; background: rgba(16, 185, 129, 0.08);">
          <div class="eng-table-heading">
            <span style="color:#10b981;">★ Break-Even Root-Finding Solution: ${escapeHtml(data.parameter_name || "fuel_price_usd_per_l")}</span>
            <span class="eng-badge-pill badge-success">✓ ${escapeHtml(data.status || "ROOT_FOUND")}</span>
          </div>
          <div class="eng-table-responsive">
            <table class="eng-structured-table">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th class="text-right">Result</th>
                  <th>Unit / Status</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Break-Even Fuel Price Threshold</td>
                  <td class="text-right text-success font-bold">$${breakEvenVal}</td>
                  <td>USD/L (Zero-NPV Point)</td>
                </tr>
                <tr>
                  <td>Target Metric</td>
                  <td class="text-right">${escapeHtml(data.target_metric || "net_present_value_usd")}</td>
                  <td>Target: $${formatNum(data.target_value ?? 0.0, 2)}</td>
                </tr>
                <tr>
                  <td>Search Range</td>
                  <td class="text-right">$${formatNum(data.lower_bound ?? 0.5, 2)} – $${formatNum(data.upper_bound ?? 5.0, 2)}</td>
                  <td>${data.evaluations_used ?? 5} solver iterations</td>
                </tr>
                <tr>
                  <td>Convergence Diagnostic</td>
                  <td class="text-right text-cyan font-bold">${escapeHtml(data.status || "ROOT_FOUND")}</td>
                  <td>${escapeHtml(data.diagnostics || "Converged to root with tolerance 1e-06.")}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      ` : ''}

      <!-- 1. Table: Voyage Summary -->
      <div class="eng-table-section">
        <h5 class="eng-table-heading">1. Voyage Summary</h5>
        <div class="eng-table-responsive">
          <table class="eng-structured-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Result</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Ship Type</td>
                <td><strong>${escapeHtml(shipType)}</strong></td>
                <td>—</td>
              </tr>
              <tr>
                <td>Route</td>
                <td>${escapeHtml(route)}</td>
                <td>—</td>
              </tr>
              <tr>
                <td>Distance</td>
                <td class="text-right">${formatNum(distanceNm, 2)}</td>
                <td>nm</td>
              </tr>
              <tr>
                <td>Transit Speed</td>
                <td class="text-right">${formatNum(transitSpeed, 2)}</td>
                <td>knots</td>
              </tr>
              <tr>
                <td>Voyage Duration</td>
                <td class="text-right">${formatNum(durationHours, 2)}</td>
                <td>hours</td>
              </tr>
              <tr>
                <td>Calendar Month</td>
                <td>${escapeHtml(calendarMonth)}</td>
                <td>—</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 2. Table: Fuel and Environmental Impact -->
      <div class="eng-table-section">
        <h5 class="eng-table-heading">2. Fuel and Environmental Impact</h5>
        <div class="eng-table-responsive">
          <table class="eng-structured-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th class="text-right">Baseline</th>
                <th class="text-right">Clean-Energy Assisted</th>
                <th class="text-right">Improvement</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Fuel Consumption</td>
                <td class="text-right">${baseFuelL !== null ? `${formatNum(baseFuelL, 2)} L` : "—"}</td>
                <td class="text-right text-cyan font-bold">${netFuelL !== null ? `${formatNum(netFuelL, 2)} L` : "—"}</td>
                <td class="text-right text-success font-bold">${deltaFuelPct !== null ? `${formatNum(Math.abs(deltaFuelPct), 2)}% reduction (${formatNum(displacedFuelL, 2)} L)` : "—"}</td>
              </tr>
              <tr>
                <td>CO₂ Emissions</td>
                <td class="text-right">${baseCo2Kg !== null ? `${formatNum(baseCo2Kg, 2)} kg` : "—"}</td>
                <td class="text-right text-cyan font-bold">${netCo2Kg !== null ? `${formatNum(netCo2Kg, 2)} kg` : "—"}</td>
                <td class="text-right text-success font-bold">${displacedCo2Kg !== null ? `${formatNum(displacedCo2Kg, 2)} kg avoided (${formatNum(Math.abs(deltaFuelPct), 2)}%)` : "—"}</td>
              </tr>
              <tr>
                <td>Operational CII</td>
                <td class="text-right">${baseCii !== null ? `${formatNum(baseCii, 2)} gCO₂/(DWT·nm)` : "—"}</td>
                <td class="text-right text-cyan font-bold">${netCii !== null ? `${formatNum(netCii, 2)} gCO₂/(DWT·nm)` : "—"}</td>
                <td class="text-right text-success font-bold">${deltaCiiPct !== null ? `${formatNum(Math.abs(deltaCiiPct), 2)}% reduction` : "—"}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="eng-table-note">
          <small>* Displacements and reductions are engineering scenario estimates derived from auxiliary generator electrical offset.</small>
        </div>
      </div>

      <!-- 3. Table: Clean Energy Analysis -->
      <div class="eng-table-section">
        <h5 class="eng-table-heading">3. Clean Energy Analysis</h5>
        <div class="eng-table-responsive">
          <table class="eng-structured-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th class="text-right">Value</th>
                <th>Unit</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Estimated Solar Energy</td>
                <td class="text-right">${formatNum(solarEnergyKwh, 2)}</td>
                <td>kWh</td>
              </tr>
              <tr>
                <td>Usable Battery Energy</td>
                <td class="text-right">${formatNum(usableBatteryKwh, 2)}</td>
                <td>kWh</td>
              </tr>
              <tr>
                <td>Clean Energy Available</td>
                <td class="text-right">${formatNum(cleanEnergyAvailKwh, 2)}</td>
                <td>kWh</td>
              </tr>
              <tr>
                <td>Clean Energy Utilized</td>
                <td class="text-right text-cyan font-bold">${formatNum(cleanEnergyUtilKwh, 2)}</td>
                <td>kWh</td>
              </tr>
              <tr>
                <td>Energy Balance</td>
                <td class="text-right">${formatNum(energyBalanceKwh, 2)}</td>
                <td>kWh</td>
              </tr>
              <tr>
                <td>Energy Deficit</td>
                <td class="text-right">${formatNum(energyDeficitKwh, 2)}</td>
                <td>kWh</td>
              </tr>
              <tr>
                <td>Fuel Displaced</td>
                <td class="text-right text-success font-bold">${formatNum(displacedFuelL, 2)} (Estimated)</td>
                <td>L</td>
              </tr>
              <tr>
                <td>CO₂ Avoided</td>
                <td class="text-right text-success font-bold">${formatNum(displacedCo2Kg, 2)} (Estimated)</td>
                <td>kg</td>
              </tr>
              <tr>
                <td>Energy Feasibility</td>
                <td class="text-right"><span class="eng-badge-pill ${feasStatus === 'FEASIBLE' ? 'badge-success' : 'badge-warning'}">${escapeHtml(feasStatus)}</span></td>
                <td>—</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 4. Table: Regulatory Assessment -->
      <div class="eng-table-section">
        <h5 class="eng-table-heading">4. Regulatory Assessment</h5>
        <div class="eng-table-responsive">
          <table class="eng-structured-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Evaluation Year</td>
                <td>${escapeHtml(String(evalYear))}</td>
              </tr>
              <tr>
                <td>Baseline Attained CII</td>
                <td>${baseCii !== null ? `${formatNum(baseCii, 2)} gCO₂/(DWT·nm)` : "—"}</td>
              </tr>
              <tr>
                <td>Assisted Attained CII</td>
                <td>${netCii !== null ? `${formatNum(netCii, 2)} gCO₂/(DWT·nm)` : "—"}</td>
              </tr>
              <tr>
                <td>Statutory CII Rating</td>
                <td><span class="cii-rating-tag ${ciiRatingClass}">${escapeHtml(ciiRatingText)}</span></td>
              </tr>
              <tr>
                <td>Assessment Status</td>
                <td>${escapeHtml(assessmentStatusText)}</td>
              </tr>
              <tr>
                <td>Regulatory Reference</td>
                <td>${escapeHtml(regulatoryRefText)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="eng-table-note">
          <small>Statutory Disclaimer: ${escapeHtml(disclaimerText)}</small>
        </div>
      </div>

      <!-- Collapsed Advanced Details / Audit Information -->
      <details class="advanced-details-box">
        <summary class="advanced-details-summary">▶ Advanced Details / Audit Information</summary>
        <div class="advanced-details-content">
          <pre class="raw-json-viewer">${escapeHtml(JSON.stringify(result, null, 2))}</pre>
        </div>
      </details>
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
