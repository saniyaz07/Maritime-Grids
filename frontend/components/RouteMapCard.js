/**
 * frontend/components/RouteMapCard.js — Maritime Nautical Route & Spatial Map Card
 * =================================================================================
 * High-performance, fully self-contained vector SVG Nautical Map displaying:
 *   1. Spatial voyage route corridor (10 explicit West African routes)
 *   2. Route waypoints with coordinates and sequence tags
 *   3. Traveled track vs remaining planned corridor
 *   4. Instantaneous vessel position with radar pulse and course heading orientation
 *   5. Integrated Nautical KPI Header (Position, SOG, COG, Distance, Progress, ETA)
 *   6. Route selection dropdown supporting 10 active West African corridors
 *   7. Strict non-actuation and read-only decision support semantics.
 */

// 10 Explicit West African Maritime Transit Corridors (Cotonou, Benin to Calabar, Nigeria)
export const MARITIME_ROUTES_CATALOG = {
  "ESC_LOS_01": {
    route_id: "ESC_LOS_01",
    name: "Escravos Fairway ➔ Lagos Port",
    origin: "Escravos Offshore Fairway",
    destination: "Lagos Port Entrance Channel",
    distance_nm: 250.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Escravos Offshore Fairway", latitude: 5.5000, longitude: 5.0800, seq: 1 },
      { waypoint_id: "WP2", name: "Mid-Offshore Marine Channel", latitude: 5.7500, longitude: 4.3000, seq: 2 },
      { waypoint_id: "WP3", name: "Lagos Approach Fairway", latitude: 6.3500, longitude: 3.4500, seq: 3 },
      { waypoint_id: "WP4", name: "Lagos Port Entrance Channel", latitude: 6.4000, longitude: 3.3900, seq: 4 },
    ]
  },
  "BON_LOS_02": {
    route_id: "BON_LOS_02",
    name: "Bonny Island LNG ➔ Lagos Port",
    origin: "Bonny LNG Terminal",
    destination: "Lagos Port Entrance Channel",
    distance_nm: 315.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Bonny LNG Terminal", latitude: 4.4300, longitude: 7.2300, seq: 1 },
      { waypoint_id: "WP2", name: "Delta Open Water Bypass", latitude: 4.2500, longitude: 6.0000, seq: 2 },
      { waypoint_id: "WP3", name: "Bight of Benin Transit", latitude: 5.8000, longitude: 4.1000, seq: 3 },
      { waypoint_id: "WP4", name: "Lagos Port Entrance Channel", latitude: 6.4000, longitude: 3.3900, seq: 4 },
    ]
  },
  "ESC_BON_03": {
    route_id: "ESC_BON_03",
    name: "Escravos Fairway ➔ Bonny Island",
    origin: "Escravos Offshore Fairway",
    destination: "Bonny LNG Terminal",
    distance_nm: 135.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Escravos Offshore Fairway", latitude: 5.5000, longitude: 5.0800, seq: 1 },
      { waypoint_id: "WP2", name: "Cape Formosa Turning Point", latitude: 4.1500, longitude: 5.9500, seq: 2 },
      { waypoint_id: "WP3", name: "Bonny LNG Terminal", latitude: 4.4300, longitude: 7.2300, seq: 3 },
    ]
  },
  "PHC_ESC_04": {
    route_id: "PHC_ESC_04",
    name: "Port Harcourt ➔ Escravos Fairway",
    origin: "Port Harcourt Channel",
    destination: "Escravos Offshore Fairway",
    distance_nm: 110.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Port Harcourt Channel", latitude: 4.6800, longitude: 7.0200, seq: 1 },
      { waypoint_id: "WP2", name: "Sombreiro River Outflow", latitude: 4.3000, longitude: 6.5000, seq: 2 },
      { waypoint_id: "WP3", name: "Escravos Offshore Fairway", latitude: 5.5000, longitude: 5.0800, seq: 3 },
    ]
  },
  "CAL_BON_05": {
    route_id: "CAL_BON_05",
    name: "Calabar Fairway ➔ Bonny Island",
    origin: "Calabar River Fairway",
    destination: "Bonny LNG Terminal",
    distance_nm: 95.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Calabar River Fairway", latitude: 4.4500, longitude: 8.3000, seq: 1 },
      { waypoint_id: "WP2", name: "Kwa Ibo Sea Buoy", latitude: 4.3200, longitude: 7.9900, seq: 2 },
      { waypoint_id: "WP3", name: "Bonny LNG Terminal", latitude: 4.4300, longitude: 7.2300, seq: 3 },
    ]
  },
  "LOS_COT_06": {
    route_id: "LOS_COT_06",
    name: "Lagos Port ➔ Cotonou Offshore",
    origin: "Lagos Port Entrance Channel",
    destination: "Cotonou Anchor Fairway",
    distance_nm: 60.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Lagos Port Entrance Channel", latitude: 6.4000, longitude: 3.3900, seq: 1 },
      { waypoint_id: "WP2", name: "Badagry Border Corridor", latitude: 6.3300, longitude: 2.8800, seq: 2 },
      { waypoint_id: "WP3", name: "Cotonou Anchor Fairway", latitude: 6.2800, longitude: 2.4500, seq: 3 },
    ]
  },
  "FOR_LOS_07": {
    route_id: "FOR_LOS_07",
    name: "Forcados Terminal ➔ Lagos Port",
    origin: "Forcados Loading Platform",
    destination: "Lagos Port Entrance Channel",
    distance_nm: 230.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Forcados Loading Platform", latitude: 5.4000, longitude: 5.3000, seq: 1 },
      { waypoint_id: "WP2", name: "Mid-Offshore Marine Channel", latitude: 5.7500, longitude: 4.3000, seq: 2 },
      { waypoint_id: "WP3", name: "Lagos Port Entrance Channel", latitude: 6.4000, longitude: 3.3900, seq: 3 },
    ]
  },
  "PEN_BON_08": {
    route_id: "PEN_BON_08",
    name: "Pennington Terminal ➔ Bonny Island",
    origin: "Pennington Marine Terminal",
    destination: "Bonny LNG Terminal",
    distance_nm: 120.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Pennington Marine Terminal", latitude: 4.7500, longitude: 5.6000, seq: 1 },
      { waypoint_id: "WP2", name: "Brass River Approach", latitude: 4.2000, longitude: 6.2500, seq: 2 },
      { waypoint_id: "WP3", name: "Bonny LNG Terminal", latitude: 4.4300, longitude: 7.2300, seq: 3 },
    ]
  },
  "BRA_LOS_09": {
    route_id: "BRA_LOS_09",
    name: "Brass Terminal ➔ Lagos Port",
    origin: "Brass Crude Export Terminal",
    destination: "Lagos Port Entrance Channel",
    distance_nm: 290.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Brass Crude Export Terminal", latitude: 4.3000, longitude: 6.2000, seq: 1 },
      { waypoint_id: "WP2", name: "Ramos River Deepwater Pass", latitude: 5.0000, longitude: 5.1000, seq: 2 },
      { waypoint_id: "WP3", name: "Bight of Benin Transit", latitude: 5.8000, longitude: 4.1000, seq: 3 },
      { waypoint_id: "WP4", name: "Lagos Port Entrance Channel", latitude: 6.4000, longitude: 3.3900, seq: 4 },
    ]
  },
  "QIT_COT_10": {
    route_id: "QIT_COT_10",
    name: "Qua Iboe ➔ Cotonou Offshore",
    origin: "Qua Iboe Terminal (QIT)",
    destination: "Cotonou Anchor Fairway",
    distance_nm: 420.0,
    waypoints: [
      { waypoint_id: "WP1", name: "Qua Iboe Terminal (QIT)", latitude: 4.5000, longitude: 7.9000, seq: 1 },
      { waypoint_id: "WP2", name: "Delta Outer Ridge Channel", latitude: 4.0500, longitude: 6.0000, seq: 2 },
      { waypoint_id: "WP3", name: "Lagos Deep Water Anchor", latitude: 6.1000, longitude: 3.5000, seq: 3 },
      { waypoint_id: "WP4", name: "Cotonou Anchor Fairway", latitude: 6.2800, longitude: 2.4500, seq: 4 },
    ]
  }
};

// Kept for backwards compatibility fallback stability
export const GULF_OF_GUINEA_CORRIDOR = MARITIME_ROUTES_CATALOG["ESC_LOS_01"].waypoints;

/**
 * Ensures coordinates maintain safe, realistic maritime clearance away
 * from the Nigerian mainland and coastline.
 */
export function getMaritimeSafeCoordinates(lat, lon) {
  if (lat === null || lat === undefined || lon === null || lon === undefined) {
    return [5.5000, 5.0800];
  }
  let safeLat = Number(lat);
  let safeLon = Number(lon);

  // If near the Escravos river bar / delta mangrove coast, place safely in open-water fairway
  if (safeLat >= 5.56 && safeLon >= 5.15 && safeLon <= 5.30) {
    safeLat = 5.5000;
    safeLon = 5.0800;
  }

  // Coastline boundary buffer: Ensure vessel remains south of mainland coast near Lagos
  if (safeLon <= 4.8 && safeLon >= 4.0 && safeLat > 5.95) {
    safeLat = 5.8500;
  }
  if (safeLon <= 4.0 && safeLon >= 3.5 && safeLat > 6.35) {
    safeLat = 6.3000;
  }

  return [safeLat, safeLon];
}

export function renderRouteMapCard({
  vessel = null,
  position = null,
  route = null,
  lookahead = null,
  recentHistory = [],
  travelledTrack = [],
  timeline = null,
  activeRouteId = "ESC_LOS_01",
} = {}) {
  // Map Projection Constants scaled from Cotonou, Benin (2.00°E) to Calabar, Nigeria (8.80°E)
  const minLat = 3.80;
  const maxLat = 6.80;
  const minLon = 2.00;
  const maxLon = 8.80;
  const width = 800;
  const height = 360;
  const padX = 40;
  const padY = 30;

  // Dynamically resolve active route object and its waypoints
  const currentRouteObj = MARITIME_ROUTES_CATALOG[activeRouteId] || MARITIME_ROUTES_CATALOG["ESC_LOS_01"];
  const waypoints = currentRouteObj.waypoints || [];

  function project(lat, lon) {
    if (lat === null || lat === undefined || lon === null || lon === undefined) {
      return { x: 0, y: 0, valid: false };
    }
    const clampedLat = Math.max(minLat, Math.min(maxLat, Number(lat)));
    const clampedLon = Math.max(minLon, Math.min(maxLon, Number(lon)));
    const x = padX + ((clampedLon - minLon) / (maxLon - minLon)) * (width - 2 * padX);
    const y = padY + ((maxLat - clampedLat) / (maxLat - minLat)) * (height - 2 * padY);
    return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, valid: true };
  }

  const rawLat = position?.latitude ?? waypoints[0]?.latitude ?? 5.50;
  const rawLon = position?.longitude ?? waypoints[0]?.longitude ?? 5.08;
  const [curLat, curLon] = getMaritimeSafeCoordinates(rawLat, rawLon);

  const curSog = position?.speed_over_ground_knots ?? null;
  const curCog = position?.course_over_ground_deg ?? position?.heading_deg ?? 285.0;
  const vPos = project(curLat, curLon);

  const distRemaining = timeline?.remaining_distance_nm !== undefined && timeline?.remaining_distance_nm !== null
    ? `${Number(timeline.remaining_distance_nm).toFixed(1)} NM`
    : `${Number(currentRouteObj.distance_nm).toFixed(1)} NM`;
  const progressPct = timeline?.progress_pct !== undefined && timeline?.progress_pct !== null
    ? Number(timeline.progress_pct)
    : 0.0;
  const etaUtc = timeline?.estimated_arrival_utc || "Calculating...";

  const projectedWaypoints = waypoints.map((wp, idx) => ({
    ...wp,
    ...project(wp.latitude, wp.longitude),
    index: idx + 1,
  }));

  const fullRoutePath = projectedWaypoints
    .map((wp, i) => `${i === 0 ? "M" : "L"} ${wp.x} ${wp.y}`)
    .join(" ");

  // Traveled Track
  let safeTrackPts = [];
  if (travelledTrack && travelledTrack.length > 0) {
    safeTrackPts = travelledTrack.map(pt => {
      const lat = Array.isArray(pt) ? pt[0] : (pt.latitude || pt.lat);
      const lon = Array.isArray(pt) ? pt[1] : (pt.longitude || pt.lon);
      const [sLat, sLon] = getMaritimeSafeCoordinates(lat, lon);
      return project(sLat, sLon);
    });
  } else if (recentHistory && recentHistory.length > 1) {
    safeTrackPts = recentHistory
      .filter(r => r.lat !== undefined && r.lon !== undefined && r.lat !== null && r.lon !== null)
      .map(r => {
        const [sLat, sLon] = getMaritimeSafeCoordinates(r.lat, r.lon);
        return project(sLat, sLon);
      });
  }

  let traveledPath = "";
  if (safeTrackPts.length > 1) {
    traveledPath = safeTrackPts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`).join(" ");
  } else if (projectedWaypoints.length > 0) {
    const startWp = projectedWaypoints[0];
    traveledPath = `M ${startWp.x} ${startWp.y} L ${vPos.x} ${vPos.y}`;
  }

  return `
    <div class="dashboard-card route-map-card nautical-chart-panel">
      <div class="card-header chart-panel-header">
        <div class="card-title-group">
          <div class="card-title-row">
            <span class="chart-header-icon">🧭</span>
            <h3>NAUTICAL CHART &amp; SPATIAL VOYAGE CORRIDOR</h3>
          </div>
          <span class="card-subtitle">Gulf of Guinea Marine Transit | <strong>${escapeHtml(currentRouteObj.name)}</strong> (${currentRouteObj.distance_nm} NM)</span>
        </div>
        <div class="card-status-container" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
          <div class="route-selector-inline" style="display:flex; align-items:center; gap:6px;">
            <label for="select-active-route" style="font-size:11px; font-weight:700; color:#94a3b8; font-family:monospace;">ROUTE:</label>
            <select id="select-active-route" class="route-select-dropdown" style="background:#070e1b; color:#38bdf8; border:1px solid #0284c7; border-radius:4px; padding:4px 8px; font-size:11px; font-weight:600; font-family:monospace; cursor:pointer;">
              ${Object.keys(MARITIME_ROUTES_CATALOG).map(rId => {
                const r = MARITIME_ROUTES_CATALOG[rId];
                const isSelected = rId === activeRouteId ? "selected" : "";
                return `<option value="${rId}" ${isSelected} style="background:#0f172a; color:#f8fafc;">${escapeHtml(r.name)} (${r.distance_nm} NM)</option>`;
              }).join("")}
            </select>
          </div>
          <span class="meta-tag meta-prov prov-observed">SPATIAL TRACK</span>
          <span class="meta-tag meta-freshness freshness-fresh">LIVE VECTOR</span>
        </div>
      </div>

      <div class="card-body map-card-body">
        <!-- Integrated Nautical KPI Header -->
        <div class="vessel-route-kpi-bar">
          <div class="kpi-item">
            <span class="kpi-label">Position</span>
            <span class="kpi-val" id="kpi-vessel-pos">${curLat.toFixed(3)}°N, ${curLon.toFixed(3)}°E</span>
          </div>
          <div class="kpi-item">
            <span class="kpi-label">Speed Over Ground (SOG)</span>
            <span class="kpi-val text-cyan" id="kpi-vessel-sog">${curSog !== null ? `${Number(curSog).toFixed(1)} kn` : '0.0 kn'}</span>
          </div>
          <div class="kpi-item">
            <span class="kpi-label">Course / Heading</span>
            <span class="kpi-val" id="kpi-vessel-cog">${Math.round(curCog)}° COG</span>
          </div>
          <div class="kpi-item">
            <span class="kpi-label">Distance Remaining</span>
            <span class="kpi-val" id="kpi-vessel-dist">${distRemaining}</span>
          </div>
          <div class="kpi-item progress-kpi-item">
            <div class="progress-label-row">
              <span class="kpi-label">Corridor Progress</span>
              <span class="kpi-pct" id="kpi-vessel-prog">${progressPct.toFixed(1)}%</span>
            </div>
            <div class="mini-progress-bar">
              <div class="mini-progress-fill" id="kpi-vessel-prog-fill" style="width: ${Math.min(100, Math.max(0, progressPct))}%;"></div>
            </div>
          </div>
          <div class="kpi-item">
            <span class="kpi-label">Dynamic ETA</span>
            <span class="kpi-val text-green" id="kpi-vessel-eta">${escapeHtml(etaUtc)}</span>
          </div>
        </div>

        <div class="nautical-chart-wrapper">
          <svg class="nautical-chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
            <defs>
              <pattern id="nautical-grid-pattern" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(56, 189, 248, 0.08)" stroke-width="1" />
              </pattern>
              <filter id="glow-cyan" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>

            <!-- Ocean Background & Grid -->
            <rect width="${width}" height="${height}" fill="#070e1b" />
            <rect width="${width}" height="${height}" fill="url(#nautical-grid-pattern)" />

            <!-- Latitude & Longitude Graticules -->
            <g class="coordinate-graticules" stroke="rgba(56, 189, 248, 0.15)" stroke-dasharray="3,3" stroke-width="0.7">
              <!-- Parallels: 6°30'N, 6°00'N, 5°30'N, 5°00'N, 4°30'N, 4°00'N -->
              <line x1="0" y1="${project(6.5, 4.0).y}" x2="${width}" y2="${project(6.5, 4.0).y}" />
              <text x="8" y="${project(6.5, 4.0).y - 4}" fill="#64748b" font-size="10" font-family="monospace">6°30'N</text>

              <line x1="0" y1="${project(6.0, 4.0).y}" x2="${width}" y2="${project(6.0, 4.0).y}" />
              <text x="8" y="${project(6.0, 4.0).y - 4}" fill="#64748b" font-size="10" font-family="monospace">6°00'N</text>

              <line x1="0" y1="${project(5.5, 4.0).y}" x2="${width}" y2="${project(5.5, 4.0).y}" />
              <text x="8" y="${project(5.5, 4.0).y - 4}" fill="#64748b" font-size="10" font-family="monospace">5°30'N</text>

              <line x1="0" y1="${project(5.0, 4.0).y}" x2="${width}" y2="${project(5.0, 4.0).y}" />
              <text x="8" y="${project(5.0, 4.0).y - 4}" fill="#64748b" font-size="10" font-family="monospace">5°00'N</text>

              <line x1="0" y1="${project(4.5, 4.0).y}" x2="${width}" y2="${project(4.5, 4.0).y}" />
              <text x="8" y="${project(4.5, 4.0).y - 4}" fill="#64748b" font-size="10" font-family="monospace">4°30'N</text>

              <line x1="0" y1="${project(4.0, 4.0).y}" x2="${width}" y2="${project(4.0, 4.0).y}" />
              <text x="8" y="${project(4.0, 4.0).y - 4}" fill="#64748b" font-size="10" font-family="monospace">4°00'N</text>

              <!-- Meridians: 3°30'E through 5°00'E plus West African corridor boundaries -->
              <line x1="${project(6.0, 3.0).x}" y1="0" x2="${project(6.0, 3.0).x}" y2="${height}" />
              <text x="${project(6.0, 3.0).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">3°00'E</text>

              <line x1="${project(6.0, 3.5).x}" y1="0" x2="${project(6.0, 3.5).x}" y2="${height}" />
              <text x="${project(6.0, 3.5).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">3°30'E</text>

              <line x1="${project(6.0, 4.0).x}" y1="0" x2="${project(6.0, 4.0).x}" y2="${height}" />
              <text x="${project(6.0, 4.0).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">4°00'E</text>

              <line x1="${project(6.0, 4.5).x}" y1="0" x2="${project(6.0, 4.5).x}" y2="${height}" />
              <text x="${project(6.0, 4.5).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">4°30'E</text>

              <line x1="${project(6.0, 5.0).x}" y1="0" x2="${project(6.0, 5.0).x}" y2="${height}" />
              <text x="${project(6.0, 5.0).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">5°00'E</text>

              <line x1="${project(6.0, 6.0).x}" y1="0" x2="${project(6.0, 6.0).x}" y2="${height}" />
              <text x="${project(6.0, 6.0).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">6°00'E</text>

              <line x1="${project(6.0, 7.0).x}" y1="0" x2="${project(6.0, 7.0).x}" y2="${height}" />
              <text x="${project(6.0, 7.0).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">7°00'E</text>

              <line x1="${project(6.0, 8.0).x}" y1="0" x2="${project(6.0, 8.0).x}" y2="${height}" />
              <text x="${project(6.0, 8.0).x + 4}" y="${height - 8}" fill="#64748b" font-size="10" font-family="monospace">8°00'E</text>
            </g>

            <!-- West African Mainland Coastline Silhouette (Benin to Calabar across 2.00°E - 8.80°E scale) -->
            <path d="M 0,75 L 40,75 Q 188,68 305,110 Q 379,160 464,285 Q 591,265 675,255 L 760,250 L 800,250 L 800,0 L 0,0 Z" fill="rgba(17, 27, 43, 0.88)" stroke="#1e293b" stroke-width="1.5" />
            <text x="660" y="32" fill="#475569" font-size="11" font-weight="700" letter-spacing="1">WEST AFRICAN COASTLINE</text>
            <text x="260" y="340" fill="rgba(56, 189, 248, 0.22)" font-size="11" font-weight="700" letter-spacing="2">GULF OF GUINEA (MARITIME TRANSIT CORRIDOR)</text>

            <!-- Planned Route Corridor (Dashed Amber) -->
            <path d="${fullRoutePath}" fill="none" stroke="#f59e0b" stroke-width="3" stroke-dasharray="6,5" opacity="0.85" />

            <!-- Traveled Track (Solid Cyan Glow) -->
            <path d="${traveledPath}" fill="none" stroke="#38bdf8" stroke-width="3.5" filter="url(#glow-cyan)" />

            <!-- Waypoint Markers & Labels -->
            ${projectedWaypoints.map(wp => {
              const color = wp.index === 1 ? "#10b981" : (wp.index === projectedWaypoints.length ? "#a855f7" : "#38bdf8");
              return `
                <g class="map-waypoint-group" transform="translate(${wp.x}, ${wp.y})">
                  <circle r="7" fill="#0b132b" stroke="${color}" stroke-width="2" />
                  <text y="3.5" text-anchor="middle" fill="${color}" font-size="9" font-weight="bold">${wp.index}</text>
                  <text y="-12" text-anchor="middle" fill="#f8fafc" font-size="10" font-weight="600" class="map-wp-label">${escapeHtml(wp.name || wp.waypoint_id)}</text>
                  <text y="18" text-anchor="middle" fill="#94a3b8" font-size="8" font-family="monospace">${wp.latitude.toFixed(2)}°N, ${wp.longitude.toFixed(2)}°E</text>
                </g>
              `;
            }).join("")}

            <!-- Active Vessel OSV-01 Indicator -->
            ${vPos.valid ? `
              <g class="map-active-vessel-group" transform="translate(${vPos.x}, ${vPos.y})">
                <circle r="18" fill="none" stroke="rgba(56, 189, 248, 0.4)" stroke-width="1.5" stroke-dasharray="2,2" class="vessel-pulse-ring" />
                <circle r="10" fill="rgba(56, 189, 248, 0.25)" stroke="#38bdf8" stroke-width="1.5" />
                <g transform="rotate(${curCog - 90})">
                  <polygon points="10,0 -7,-6 -3,0 -7,6" fill="#10b981" stroke="#ffffff" stroke-width="1.2" />
                </g>
                <rect x="14" y="-20" width="140" height="34" rx="4" fill="rgba(11, 19, 43, 0.95)" stroke="#38bdf8" stroke-width="1" />
                <text x="20" y="-7" fill="#38bdf8" font-size="10" font-weight="bold">OSV-01 | ${curSog !== null ? `${Number(curSog).toFixed(1)} kn` : '0.0 kn'}</text>
                <text x="20" y="7" fill="#94a3b8" font-size="8.5" font-family="monospace">${curLat.toFixed(3)}°N, ${curLon.toFixed(3)}°E</text>
              </g>
            ` : ''}
          </svg>
        </div>

        <!-- Chart Legend Bar -->
        <div class="nautical-chart-legend">
          <div class="legend-item"><span class="legend-swatch swatch-vessel"></span> OSV-01 (Oriented COG Vector)</div>
          <div class="legend-item"><span class="legend-swatch swatch-traveled"></span> Traveled Track</div>
          <div class="legend-item"><span class="legend-swatch swatch-route"></span> Planned Corridor</div>
          <div class="legend-item"><span class="legend-swatch swatch-wp"></span> Waypoints (WP1 - WP${projectedWaypoints.length})</div>
          <div class="legend-item"><span class="legend-swatch swatch-adverse"></span> Open Water Maritime Corridor</div>
        </div>
      </div>
    </div>
  `;
}

export function initOrUpdateLeafletMap() {
  // Safe no-op retained for backwards compatibility
  return null;
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
