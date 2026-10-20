/**
 * frontend/api/operatorClient.js — Phase 10C.11A Operator API Transport Client
 * =============================================================================
 * Consumes verified REST endpoints under /api/v1/operator/*:
 *   - POST /api/v1/operator/state
 *   - POST /api/v1/operator/state/from-voyage
 *   - POST /api/v1/operator/state/from-telemetry
 *   - GET  /api/v1/operator/health
 *   - POST /api/v1/operator/voyages
 *   - GET  /api/v1/operator/voyages
 *   - GET  /api/v1/operator/voyages/{voyage_id}
 *   - PUT  /api/v1/operator/voyages/{voyage_id}
 *   - DELETE /api/v1/operator/voyages/{voyage_id}
 */

export class OperatorApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async _request(path, options = {}) {
    const url = `${this.baseUrl}${path}`;
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...options.headers,
    };

    try {
      const response = await fetch(url, { ...options, headers });
      if (!response.ok) {
        let errorData = null;
        try {
          errorData = await response.json();
        } catch (e) {
          errorData = { message: response.statusText };
        }
        return {
          success: false,
          status: response.status,
          error: errorData,
        };
      }

      if (response.status === 204) {
        return { success: true, status: 204, data: null };
      }

      const data = await response.json();
      return { success: true, status: response.status, data };
    } catch (err) {
      return {
        success: false,
        status: 0,
        error: {
          error_type: "NETWORK_ERROR",
          message: err.message || "Failed to communicate with Operator API",
        },
      };
    }
  }

  async getHealth() {
    return this._request("/api/v1/operator/health", { method: "GET" });
  }

  async getOperatorState(requestPayload) {
    return this._request("/api/v1/operator/state", {
      method: "POST",
      body: JSON.stringify(requestPayload),
    });
  }

  async getOperatorStateFromVoyage(voyagePayload) {
    return this._request("/api/v1/operator/state/from-voyage", {
      method: "POST",
      body: JSON.stringify(voyagePayload),
    });
  }

  async getOperatorStateFromTelemetry(telemetryPayload) {
    return this._request("/api/v1/operator/state/from-telemetry", {
      method: "POST",
      body: JSON.stringify(telemetryPayload),
    });
  }

  async listVoyages(limit = 100, offset = 0) {
    return this._request(`/api/v1/operator/voyages?limit=${limit}&offset=${offset}`, {
      method: "GET",
    });
  }

  async getVoyage(voyageId) {
    return this._request(`/api/v1/operator/voyages/${encodeURIComponent(voyageId)}`, {
      method: "GET",
    });
  }

  async createVoyage(voyageState) {
    return this._request("/api/v1/operator/voyages", {
      method: "POST",
      body: JSON.stringify(voyageState),
    });
  }

  async updateVoyage(voyageId, updatePayload) {
    return this._request(`/api/v1/operator/voyages/${encodeURIComponent(voyageId)}`, {
      method: "PUT",
      body: JSON.stringify(updatePayload),
    });
  }

  async deleteVoyage(voyageId) {
    return this._request(`/api/v1/operator/voyages/${encodeURIComponent(voyageId)}`, {
      method: "DELETE",
    });
  }

  // =================================================================
  // TELEMETRY GATEWAY CLIENT METHODS (PHASE 10C.12)
  // =================================================================

  async ingestTelemetry(rawPayload, source = "WEB_CLIENT", mode = "OBSERVED") {
    return this._request(`/api/v1/operator/telemetry/ingest?source=${encodeURIComponent(source)}&mode=${encodeURIComponent(mode)}`, {
      method: "POST",
      body: JSON.stringify(rawPayload),
    });
  }

  async getCurrentTelemetry(referenceTimeUtc = null) {
    const qs = referenceTimeUtc ? `?reference_time_utc=${encodeURIComponent(referenceTimeUtc)}` : "";
    return this._request(`/api/v1/operator/telemetry/current${qs}`, {
      method: "GET",
    });
  }

  async getSimulatedScenario(scenarioId) {
    return this._request(`/api/v1/operator/telemetry/simulated/${encodeURIComponent(scenarioId)}`, {
      method: "GET",
    });
  }

  async validateTelemetry(rawPayload, source = "VALIDATOR", mode = "OBSERVED") {
    return this._request(`/api/v1/operator/telemetry/validate?source=${encodeURIComponent(source)}&mode=${encodeURIComponent(mode)}`, {
      method: "POST",
      body: JSON.stringify(rawPayload),
    });
  }

  async getRouteWeatherLookahead(lookaheadPayload) {
    return this._request("/api/v1/operator/weather/lookahead", {
      method: "POST",
      body: JSON.stringify(lookaheadPayload),
    });
  }

  // =================================================================
  // REAL-TIME STREAMING & AUDIT LOG CLIENT METHODS (PHASE 10C.13)
  // =================================================================

  getTelemetryStreamUrl() {
    return `${this.baseUrl}/api/v1/operator/telemetry/stream`;
  }

  async getTelemetryHistory({
    vesselId = null,
    startTimeUtc = null,
    endTimeUtc = null,
    source = null,
    mode = null,
    quality = null,
    limit = 100,
    offset = 0,
  } = {}) {
    const params = new URLSearchParams();
    if (vesselId) params.append("vessel_id", vesselId);
    if (startTimeUtc) params.append("start_time_utc", startTimeUtc);
    if (endTimeUtc) params.append("end_time_utc", endTimeUtc);
    if (source) params.append("source", source);
    if (mode) params.append("mode", mode);
    if (quality) params.append("quality", quality);
    params.append("limit", String(limit));
    params.append("offset", String(offset));

    return this._request(`/api/v1/operator/telemetry/history?${params.toString()}`, {
      method: "GET",
    });
  }

  subscribeTelemetryStream(onMessage, onError = null, onStatusChange = null) {
    const streamUrl = this.getTelemetryStreamUrl();
    let eventSource = null;
    let isClosed = false;

    const connect = () => {
      if (isClosed) return;
      if (onStatusChange) onStatusChange("CONNECTING");

      try {
        eventSource = new EventSource(streamUrl);

        eventSource.onopen = () => {
          if (onStatusChange) onStatusChange("CONNECTED");
        };

        eventSource.addEventListener("telemetry", (event) => {
          try {
            const parsed = JSON.parse(event.data);
            if (onMessage) onMessage(parsed);
          } catch (err) {
            if (onError) onError({ message: "Malformed SSE telemetry payload", error: err });
          }
        });

        eventSource.onerror = (err) => {
          if (onStatusChange) onStatusChange("RECONNECTING");
          if (onError) onError({ message: "SSE stream connection interrupted", error: err });
        };
      } catch (err) {
        if (onStatusChange) onStatusChange("DISCONNECTED");
        if (onError) onError({ message: "Failed to initialize EventSource", error: err });
      }
    };

    connect();

    return () => {
      isClosed = true;
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (onStatusChange) onStatusChange("DISCONNECTED");
    };
  }

  // =================================================================
  // NATIVE VIRTUAL VESSEL SIMULATOR CLIENT METHODS
  // =================================================================

  async getSimulatorState() {
    return this._request("/api/v1/operator/simulator/state", {
      method: "GET",
    });
  }

  async startSimulation() {
    return this._request("/api/v1/operator/simulator/start", {
      method: "POST",
    });
  }

  async pauseSimulation() {
    return this._request("/api/v1/operator/simulator/pause", {
      method: "POST",
    });
  }

  async resetSimulation() {
    return this._request("/api/v1/operator/simulator/reset", {
      method: "POST",
    });
  }

  async setSimulatorControls(controls) {
    return this._request("/api/v1/operator/simulator/control", {
      method: "POST",
      body: JSON.stringify(controls),
    });
  }

  async stepSimulation(dtSeconds = 1.0) {
    return this._request(`/api/v1/operator/simulator/step?dt_seconds=${dtSeconds}`, {
      method: "POST",
    });
  }

  async refreshSimulatorWeather() {
    return this._request("/api/v1/operator/simulator/weather/refresh", {
      method: "POST",
    });
  }
}


