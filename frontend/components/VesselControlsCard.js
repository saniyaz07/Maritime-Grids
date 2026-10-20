/**
 * frontend/components/VesselControlsCard.js — Native Virtual Vessel Operator Controls
 * ===================================================================================
 * Interactive driver cockpit panel for commanding virtual vessel kinematics:
 *   - Simulation lifecycle controls: START (▶), PAUSE (⏸), RESET (↻)
 *   - Target Speed & Propulsion Throttle slider and step controls (-1.0, -0.5, +0.5, +1.0 kn)
 *   - Compass Heading panel with quick-adjust stepper (-5°, -1°, Corridor 285°, +1°, +5°)
 *   - Environmental scenario condition toggles (Calm, Moderate, Rough Weather, Opposing Current)
 * 
 * Strict Safety Invariant:
 *   - Purely internal virtual simulator control. Zero external actuator outputs.
 *   - Port 10111 strictly prohibited.
 */

export function renderVesselControlsCard({
  status = "IDLE", // IDLE, RUNNING, PAUSED
  targetSpeedKnots = 12.0,
  throttlePct = 75.0,
  headingDeg = 285.0,
  speedThroughWaterKnots = 12.0,
  waveHeightM = 1.4,
  windSpeedKnots = 16.5,
  currentSpeedKnots = 0.6,
  environmentalMode = "AUTOMATIC_FORECAST",
  disabled = false,
} = {}) {
  const isRunning = status === "RUNNING";
  const isPaused = status === "PAUSED";
  const isIdle = status === "IDLE";

  return `
    <div class="dashboard-card vessel-controls-card primary-control-hub">
      <div class="card-header control-hub-header">
        <div class="card-title-group">
          <div class="card-title-row">
            <span class="control-hub-icon">🕹️</span>
            <h3>VIRTUAL VESSEL CONTROLS &amp; FLIGHT DECK</h3>
          </div>
          <span class="card-subtitle">Primary Interactive Control Hub — Real-Time Powertrain &amp; Kinematics</span>
        </div>
        <div class="card-status-container">
          <span class="meta-tag meta-prov prov-simulated">MODE: SIMULATOR</span>
          <span class="status-pill status-${isRunning ? 'active' : (isPaused ? 'paused' : 'unknown')}">
            ${isRunning ? '● RUNNING' : (isPaused ? '⏸ PAUSED' : '○ READY')}
          </span>
        </div>
      </div>

      <div class="card-body control-hub-body">
        <!-- Top Command Strip: Transport Lifecycle + Quick Status -->
        <div class="command-strip-row">
          <div class="controls-transport-bar">
            <button id="btn-sim-start" class="btn btn-action btn-start ${isRunning ? 'active-running' : ''}" ${isRunning ? 'disabled' : ''}>
              ▶ START VOYAGE
            </button>
            <button id="btn-sim-pause" class="btn btn-action btn-pause ${isPaused ? 'active-paused' : ''}" ${!isRunning ? 'disabled' : ''}>
              ⏸ PAUSE
            </button>
            <button id="btn-sim-reset" class="btn btn-action btn-reset">
              ↻ RESET VOYAGE
            </button>
          </div>

          <div class="command-strip-pills">
            <div class="kinematic-pill">
              <span class="k-label">COMMANDED SPEED</span>
              <span class="k-val text-cyan" id="disp-target-speed">${targetSpeedKnots.toFixed(1)} kn (${throttlePct.toFixed(0)}%)</span>
            </div>
            <div class="kinematic-pill">
              <span class="k-label">COMPASS HEADING</span>
              <span class="k-val text-amber" id="disp-heading">${Math.round(headingDeg)}° T</span>
            </div>
            <div class="kinematic-pill">
              <span class="k-label">STW PHYSICS</span>
              <span class="k-val text-green">${speedThroughWaterKnots.toFixed(1)} kn</span>
            </div>
          </div>
        </div>

        <!-- 2-Column Primary Control Grid: Throttle & Heading -->
        <div class="controls-grid grid-2col mt-3">
          <!-- 1. Speed & Throttle Lever Card -->
          <div class="control-box speed-control-box">
            <div class="control-box-header">
              <label for="slider-throttle" class="control-label">Propulsion Throttle / Target Speed</label>
              <span class="control-subtext-inline">Max Rating: 14.5 kn | Continuous Service: 12.0 kn</span>
            </div>
            
            <div class="slider-wrapper mt-2">
              <input type="range" id="slider-throttle" class="control-slider" min="0" max="100" step="1" value="${Math.round(throttlePct)}">
            </div>

            <div class="speed-stepper-row mt-2">
              <button id="btn-speed-minus-1" class="btn btn-step">-1.0 kn</button>
              <button id="btn-speed-minus-05" class="btn btn-step">-0.5 kn</button>
              <button id="btn-speed-plus-05" class="btn btn-step">+0.5 kn</button>
              <button id="btn-speed-plus-1" class="btn btn-step">+1.0 kn</button>
            </div>
          </div>

          <!-- 2. Compass Heading Control Card -->
          <div class="control-box heading-control-box">
            <div class="control-box-header">
              <label for="slider-heading" class="control-label">Compass Heading Control Panel</label>
              <span class="control-subtext-inline">Escravos ➔ Lagos Transit Corridor: 285°</span>
            </div>

            <div class="slider-wrapper mt-2">
              <input type="range" id="slider-heading" class="control-slider" min="0" max="359" step="1" value="${Math.round(headingDeg)}">
            </div>

            <div class="heading-stepper-row mt-2">
              <button id="btn-hdg-minus-5" class="btn btn-step">◀ -5°</button>
              <button id="btn-hdg-minus-1" class="btn btn-step">◀ -1°</button>
              <button id="btn-hdg-corridor" class="btn btn-step btn-preset">Corridor (285°)</button>
              <button id="btn-hdg-plus-1" class="btn btn-step">+1° ▶</button>
              <button id="btn-hdg-plus-5" class="btn btn-step">+5° ▶</button>
            </div>
          </div>
        </div>

        <!-- Environmental Ocean Force Presets (Weather & Resistance Coupling) -->
        <div class="env-presets-section mt-3">
          <div class="env-presets-header d-flex justify-content-between align-items-center">
            <span class="env-presets-label">🌊 Environmental Ocean Scenario Selectors (Hydrodynamic Coupling):</span>
            <span class="meta-tag ${environmentalMode === 'AUTOMATIC_FORECAST' ? 'prov-forecast' : 'prov-simulated'}">
              MODE: ${environmentalMode === 'AUTOMATIC_FORECAST' ? 'AUTO (OPEN-METEO FORECAST)' : 'MANUAL SCENARIO PRESET'}
            </span>
          </div>
          <div class="env-presets-button-row mt-2">
            <button id="btn-env-auto" class="btn btn-env-preset btn-env-auto ${environmentalMode === 'AUTOMATIC_FORECAST' ? 'active' : ''}">
              🌐 Auto Forecast (Open-Meteo)
            </button>
            <button id="btn-env-calm" class="btn btn-env-preset ${environmentalMode === 'MANUAL_SCENARIO' && waveHeightM <= 1.0 && windSpeedKnots <= 10.0 && currentSpeedKnots < 1.0 ? 'active' : ''}">
              🌊 Calm Sea (0.8m, 8kn)
            </button>
            <button id="btn-env-moderate" class="btn btn-env-preset ${environmentalMode === 'MANUAL_SCENARIO' && waveHeightM > 1.0 && waveHeightM <= 2.0 && currentSpeedKnots < 1.0 ? 'active' : ''}">
              💨 Moderate (1.4m, 16kn)
            </button>
            <button id="btn-env-rough" class="btn btn-env-preset ${environmentalMode === 'MANUAL_SCENARIO' && waveHeightM >= 2.5 ? 'active' : ''}">
              ⚠️ Rough Weather (3.2m, 30kn)
            </button>
            <button id="btn-env-current" class="btn btn-env-preset ${environmentalMode === 'MANUAL_SCENARIO' && currentSpeedKnots >= 1.2 ? 'active' : ''}">
              🔄 Opposing Current (1.5kn)
            </button>
          </div>
        </div>

        <!-- Safety Notice -->
        <div class="controls-safety-notice mt-2">
          <span class="shield-icon">🛡️</span>
          <span><strong>Safety Policy:</strong> Control inputs actuate virtual simulation state only. Zero external actuator commands. Port 10111 strictly prohibited.</span>
        </div>
      </div>
    </div>
  `;
}
