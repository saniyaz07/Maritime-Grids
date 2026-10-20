/**
 * frontend/components/ProvenanceBadge.js — Reusable Provenance & Telemetry Formatter
 * ====================================================================================
 * Renders data points with full provenance traceability:
 *   - Value + Unit
 *   - Provenance tag (OBSERVED, HISTORICAL, FORECAST, MODEL_PREDICTION, SIMULATED, UNAVAILABLE)
 *   - Quality status (VALID, PARTIAL, INVALID, UNAVAILABLE)
 *   - Freshness badge (FRESH, STALE, EXPIRED, UNKNOWN)
 *   - Timestamp (ISO 8601 UTC)
 *   - Source provider
 * 
 * Strict Invariant: null / undefined is NEVER rendered as 0. It is rendered as "Unavailable" / "No telemetry".
 */

export function formatValue(val, unit = "", decimals = 2) {
  if (val === null || val === undefined) {
    return { text: "Unavailable", isAvailable: false };
  }
  if (typeof val === "number") {
    if (!Number.isFinite(val)) {
      return { text: "Invalid (NaN/Inf)", isAvailable: false };
    }
    const formatted = val.toFixed(decimals);
    return { text: unit ? `${formatted} ${unit}` : formatted, isAvailable: true };
  }
  return { text: unit ? `${val} ${unit}` : String(val), isAvailable: true };
}

export function renderProvenanceMetadata({
  source = null,
  provenance = null,
  quality = null,
  freshness = null,
  timestamp = null,
  compact = false,
}) {
  const parts = [];

  if (source) {
    parts.push(`<span class="meta-tag meta-source">Src: ${escapeHtml(source)}</span>`);
  }
  if (provenance) {
    const provClass = `prov-${provenance.toLowerCase()}`;
    parts.push(`<span class="meta-tag meta-prov ${provClass}">${escapeHtml(provenance)}</span>`);
  }
  if (quality) {
    const qClass = `quality-${quality.toLowerCase()}`;
    parts.push(`<span class="meta-tag meta-quality ${qClass}">${escapeHtml(quality)}</span>`);
  }
  if (freshness) {
    const fClass = `freshness-${freshness.toLowerCase()}`;
    parts.push(`<span class="meta-tag meta-freshness ${fClass}">${escapeHtml(freshness)}</span>`);
  }
  if (timestamp) {
    parts.push(`<span class="meta-tag meta-time">${escapeHtml(timestamp)}</span>`);
  }

  if (parts.length === 0) return "";

  return `
    <div class="provenance-metadata-row ${compact ? 'compact' : ''}">
      ${parts.join(" ")}
    </div>
  `;
}

export function renderTelemetryField({
  label,
  value,
  unit = "",
  decimals = 2,
  source = null,
  provenance = null,
  quality = null,
  freshness = null,
  timestamp = null,
  nullPlaceholder = "No telemetry",
}) {
  const isNull = (value === null || value === undefined);
  const displayVal = isNull ? nullPlaceholder : (typeof value === "number" ? `${value.toFixed(decimals)} ${unit}`.trim() : `${value} ${unit}`.trim());
  const valClass = isNull ? "val-unavailable" : "val-active";

  const metaHtml = renderProvenanceMetadata({ source, provenance, quality, freshness, timestamp, compact: true });

  return `
    <div class="telemetry-field-box">
      <div class="telemetry-label">${escapeHtml(label)}</div>
      <div class="telemetry-value ${valClass}">${escapeHtml(displayVal)}</div>
      ${metaHtml}
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
