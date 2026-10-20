/**
 * frontend/api/engineeringClient.js — Phase 10C.11A Engineering API Transport Client
 * =================================================================================
 * Consumes verified REST endpoints under /api/v1/engineering/*:
 *   - POST /api/v1/engineering/simulate-voyage
 *   - POST /api/v1/engineering/evaluate-sizing
 *   - POST /api/v1/engineering/optimize-sizing
 *   - POST /api/v1/engineering/sensitivity-analysis
 *   - POST /api/v1/engineering/break-even-analysis
 *   - POST /api/v1/engineering/grid-2d-analysis
 *   - POST /api/v1/engineering/speed-cooptimization
 *   - POST /api/v1/engineering/portfolio-optimization
 *   - POST /api/v1/engineering/cii-trajectory
 *   - POST /api/v1/engineering/export-dossier
 */

export class EngineeringApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async _request(path, payload) {
    const url = `${this.baseUrl}${path}`;
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        let errData = null;
        try {
          errData = await response.json();
        } catch (e) {
          errData = { message: response.statusText };
        }
        return { success: false, status: response.status, error: errData };
      }

      const data = await response.json();
      return { success: true, status: response.status, data };
    } catch (err) {
      return {
        success: false,
        status: 0,
        error: {
          error_type: "NETWORK_ERROR",
          message: err.message || "Failed to communicate with Engineering API",
        },
      };
    }
  }

  simulateVoyage(payload) {
    return this._request("/api/v1/engineering/simulate-voyage", payload);
  }

  evaluateSizing(payload) {
    return this._request("/api/v1/engineering/evaluate-sizing", payload);
  }

  optimizeSizing(payload) {
    return this._request("/api/v1/engineering/optimize-sizing", payload);
  }

  runSensitivityAnalysis(payload) {
    return this._request("/api/v1/engineering/sensitivity-analysis", payload);
  }

  runBreakEvenAnalysis(payload) {
    return this._request("/api/v1/engineering/break-even-analysis", payload);
  }

  run2DGridAnalysis(payload) {
    return this._request("/api/v1/engineering/grid-2d-analysis", payload);
  }

  optimizeSpeedAndSizing(payload) {
    return this._request("/api/v1/engineering/speed-cooptimization", payload);
  }

  optimizeFleetPortfolio(payload) {
    return this._request("/api/v1/engineering/portfolio-optimization", payload);
  }

  simulateCIITrajectory(payload) {
    return this._request("/api/v1/engineering/cii-trajectory", payload);
  }

  exportScenarioDossier(payload) {
    return this._request("/api/v1/engineering/export-dossier", payload);
  }
}
