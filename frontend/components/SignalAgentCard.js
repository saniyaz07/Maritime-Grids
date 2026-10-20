/**
 * frontend/components/SignalAgentCard.js — Signal Agent Decision Support Component
 * ===============================================================================
 * Interprets physical simulation facts (speed, fuel, battery, weather, route ETA)
 * and presents concise, actionable operational advice to the bridge driver.
 * 
 * Strict Invariant:
 *   - Decision support ONLY. Never commands actuators or modifies vessel control.
 *   - Every advisory displays "HUMAN REVIEW REQUIRED".
 */

export function renderSignalAgentCard(signalAgent = null) {
  if (!signalAgent) {
    return `
      <div class="dashboard-card signal-agent-card compact-signal-card">
        <div class="card-header compact-header">
          <div class="card-title-group">
            <h3>SIGNAL AGENT DECISION SUPPORT</h3>
            <span class="card-subtitle">Autonomous Decision-Support Interpreter</span>
          </div>
          <span class="status-pill status-unknown">IDLE</span>
        </div>
        <div class="card-body">
          <p class="empty-state-text">Signal Agent listening for virtual vessel state...</p>
        </div>
      </div>
    `;
  }

  const status = signalAgent.status || "NORMAL";
  const severity = (signalAgent.severity || "INFO").toUpperCase();
  const headline = signalAgent.headline || "Vessel operating within normal limits.";
  const details = signalAgent.details || [];

  let badgeClass = "badge-info";
  let cardBorderClass = "border-info";
  let statusIcon = "ℹ️";

  if (status === "WEATHER_ALERT" || severity === "WARNING") {
    badgeClass = "badge-warning";
    cardBorderClass = "border-warning";
    statusIcon = "⚠️";
  } else if (status === "ENGINE_OVERLOAD") {
    badgeClass = "badge-warning";
    cardBorderClass = "border-warning";
    statusIcon = "⚠️";
  } else if (status === "FUEL_ALERT" || severity === "CRITICAL") {
    badgeClass = "badge-danger";
    cardBorderClass = "border-danger";
    statusIcon = "🚨";
  } else if (status === "BATTERY_ALERT") {
    badgeClass = "badge-notice";
    cardBorderClass = "border-notice";
    statusIcon = "🔋";
  } else {
    badgeClass = "badge-success";
    cardBorderClass = "border-success";
    statusIcon = "✅";
  }

  // Identify highest priority alert and required operator action
  let operatorAction = "Maintain commanded speed and corridor heading.";
  if (status === "ENGINE_OVERLOAD") {
    operatorAction = "Reduce speed to design rating (12.0 kn) to relieve engine continuous overload and thermal stress.";
  } else if (status === "FUEL_ALERT") {
    operatorAction = "Drastic speed reduction or immediate bunkering required to preserve reserve margin.";
  } else if (status === "WEATHER_ALERT") {
    operatorAction = "Reduce speed to 10.0–11.0 kn to ease slamming and reduce hydrodynamic power demand.";
  } else if (status === "BATTERY_ALERT") {
    operatorAction = "Monitor auxiliary battery draw; main diesel generator currently supporting hotel load.";
  }

  return `
    <div class="dashboard-card signal-agent-card compact-signal-card ${cardBorderClass}">
      <div class="card-header compact-header">
        <div class="card-title-group">
          <h3>SIGNAL AGENT DECISION SUPPORT</h3>
          <span class="card-subtitle">Real-Time Operational Assessment &amp; Decision Advice</span>
        </div>
        <div class="card-status-container">
          <span class="signal-agent-status-badge ${badgeClass}">${statusIcon} ${escapeHtml(status)}</span>
        </div>
      </div>

      <div class="card-body compact-card-body">
        <!-- Headline Message Banner (Highest-Priority Warning / Recommendation) -->
        <div class="agent-headline-box ${badgeClass}">
          <span class="agent-headline-text">${escapeHtml(headline)}</span>
        </div>

        <!-- Required Operator Action Box -->
        <div class="agent-action-box">
          <span class="action-label">REQUIRED OPERATOR ACTION:</span>
          <span class="action-text">${escapeHtml(operatorAction)}</span>
        </div>

        <!-- Collapsible Operational Details & Explanation -->
        <details class="agent-details-collapsible mt-2">
          <summary class="agent-details-summary">
            <span>🔍 View Detailed Decision Context (${details.length} facts)</span>
          </summary>
          <div class="agent-details-list mt-2">
            ${details.map(item => `
              <div class="agent-detail-item">
                <span class="bullet-arrow">▸</span>
                <span class="detail-text">${escapeHtml(item)}</span>
              </div>
            `).join("")}
          </div>
        </details>

        <!-- Human in the loop disclaimer -->
        <div class="agent-footer-banner mt-2">
          <span class="human-review-tag">🛡️ HUMAN REVIEW REQUIRED</span>
          <span class="footer-desc">Advisories inform bridge driver. Vessel commands remain strictly under operator control.</span>
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
