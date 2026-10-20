/**
 * frontend/app.js — Application Entrypoint & Global State
 * ========================================================
 * Manages top-level navigation tabs, UTC clock updater,
 * and initializes respective page components.
 */

/**
 * frontend/app.js — Application Entrypoint & Global State
 * ========================================================
 * Manages top-level navigation tabs, UTC clock updater,
 * and initializes respective page components.
 */

async function initApp() {
  const driverViewContainer = document.getElementById("view-driver-dashboard");
  const engineeringViewContainer = document.getElementById("view-engineering-dashboard");
  const tabDriverBtn = document.getElementById("nav-tab-driver");
  const tabEngineeringBtn = document.getElementById("nav-tab-engineering");
  const clockEl = document.getElementById("header-utc-time");

  // Real-time UTC clock updater
  function updateUtcClock() {
    if (clockEl) {
      const now = new Date();
      const h = String(now.getUTCHours()).padStart(2, "0");
      const m = String(now.getUTCMinutes()).padStart(2, "0");
      const s = String(now.getUTCSeconds()).padStart(2, "0");
      clockEl.textContent = `${h}:${m}:${s} UTC`;
    }
  }
  updateUtcClock();
  setInterval(updateUtcClock, 1000);

  try {
    const cacheBust = Date.now();
    const { DriverDashboardPage } = await import(`./pages/DriverDashboard.js?t=${cacheBust}`);
    const { EngineeringDashboardPage } = await import(`./pages/EngineeringDashboard.js?t=${cacheBust}`);

    const driverDashboard = new DriverDashboardPage("view-driver-dashboard");
    const engineeringDashboard = new EngineeringDashboardPage("view-engineering-dashboard");

    // Initialize Driver Dashboard by default
    await driverDashboard.init();
    engineeringDashboard.init();

    function switchTab(activeTab) {
      if (activeTab === "driver") {
        tabDriverBtn?.classList.add("active");
        tabEngineeringBtn?.classList.remove("active");
        if (driverViewContainer) driverViewContainer.style.display = "block";
        if (engineeringViewContainer) engineeringViewContainer.style.display = "none";
        driverDashboard.startPolling();
      } else {
        tabEngineeringBtn?.classList.add("active");
        tabDriverBtn?.classList.remove("active");
        if (driverViewContainer) driverViewContainer.style.display = "none";
        if (engineeringViewContainer) engineeringViewContainer.style.display = "block";
        driverDashboard.stopPolling();
      }
    }

    tabDriverBtn?.addEventListener("click", () => switchTab("driver"));
    tabEngineeringBtn?.addEventListener("click", () => switchTab("engineering"));
  } catch (err) {
    console.error("Dashboard Init Error:", err);
    if (driverViewContainer) {
      driverViewContainer.innerHTML = `
        <div style="padding: 24px; color: #ef4444; background: #162032; border: 1px solid #ef4444; margin: 20px; border-radius: 8px; font-family: monospace;">
          <h3>⚠️ Dashboard Initialization Error</h3>
          <p><strong>Error:</strong> ${err.message}</p>
          <pre style="color: #cbd5e1; margin-top: 10px; font-size: 11px;">${err.stack || String(err)}</pre>
        </div>
      `;
    }
  }
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
}
