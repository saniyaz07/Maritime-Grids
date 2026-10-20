/**
 * frontend/components/AdvisoryPanel.js — Phase 10C.11A Human-in-the-Loop Advisory Panel
 * =====================================================================================
 * Renders prioritized operational advisories with strict human-in-the-loop governance.
 * 
 * Strict Invariants:
 *   - "HUMAN REVIEW REQUIRED" is visibly rendered for every advisory notice.
 *   - Preserves backend severity (CRITICAL, WARNING, NOTICE, INFO) and priority ordering.
 *   - Displays rule_id, evidence dictionary, and suggested human actions.
 *   - Zero autonomous execution, zero actuation buttons, zero automated control triggers.
 */

export function renderAdvisoryPanel(advisories = [], readinessState = "READY") {
  const count = advisories ? advisories.length : 0;
  const countBadge = `<span class="advisory-count-badge ${count > 0 ? 'has-advisories' : 'zero-advisories'}">${count} Active</span>`;

  if (!advisories || advisories.length === 0) {
    return `
      <div class="dashboard-card advisory-panel">
        <div class="card-header">
          <div class="card-title-group">
            <h3>Bridge Decision Advisories</h3>
            <span class="card-subtitle">Readiness: ${escapeHtml(readinessState)}</span>
          </div>
          <div class="card-status-container">
            ${countBadge}
          </div>
        </div>
        <div class="card-body">
          <div class="empty-advisories-box">
            <span class="shield-icon">🛡️</span>
            <p>No active operational advisories or constraint warnings. Operating within normal decision parameters.</p>
          </div>
        </div>
      </div>
    `;
  }

  const advisoryCardsHtml = advisories.map((adv, idx) => {
    const sev = adv.severity || "INFO";
    const sevClass = `sev-${sev.toLowerCase()}`;
    const ruleId = adv.rule_id || `ADV_${idx + 1}`;
    const category = adv.category || "GENERAL";
    const msg = adv.message || "No message provided";
    const action = adv.suggested_action || null;
    const evidence = adv.evidence ? JSON.stringify(adv.evidence, null, 2) : null;
    const time = adv.timestamp_utc || null;
    const isHumanReview = adv.human_review_required !== false; // Default True

    return `
      <div class="advisory-item ${sevClass}">
        <div class="advisory-header">
          <div class="advisory-title-group">
            <span class="severity-pill ${sevClass}">${escapeHtml(sev)}</span>
            <span class="rule-id-tag">[${escapeHtml(ruleId)}]</span>
            <span class="category-tag">${escapeHtml(category)}</span>
          </div>
          <div class="advisory-badges">
            ${isHumanReview ? '<span class="human-review-badge">👤 HUMAN REVIEW REQUIRED</span>' : ''}
          </div>
        </div>

        <div class="advisory-message">
          ${escapeHtml(msg)}
        </div>

        ${action ? `
          <div class="advisory-action-box">
            <span class="action-icon">👉</span>
            <span class="action-text"><strong>Suggested Operator Action:</strong> ${escapeHtml(action)}</span>
          </div>
        ` : ''}

        ${evidence ? `
          <details class="advisory-evidence-details">
            <summary>View Telemetry Evidence</summary>
            <pre class="evidence-json">${escapeHtml(evidence)}</pre>
          </details>
        ` : ''}

        ${time ? `
          <div class="advisory-footer">
            <span class="advisory-timestamp">Evaluated: ${escapeHtml(time)}</span>
          </div>
        ` : ''}
      </div>
    `;
  }).join("\n");

  return `
    <div class="dashboard-card advisory-panel">
      <div class="card-header">
        <div class="card-title-group">
          <h3>Bridge Decision Advisories</h3>
          <span class="card-subtitle">Decision Readiness: ${escapeHtml(readinessState)}</span>
        </div>
        <div class="card-status-container">
          ${countBadge}
        </div>
      </div>

      <div class="card-body">
        <div class="advisories-list">
          ${advisoryCardsHtml}
        </div>

        <div class="governance-reminder mt-3">
          <span class="gov-icon">⚖️</span>
          <span><strong>Decision Support Notice:</strong> Advisories are deterministic decision-support recommendations for licensed bridge personnel. Autonomous vessel actuation is strictly prohibited.</span>
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
