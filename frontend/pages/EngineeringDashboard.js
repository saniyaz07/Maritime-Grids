/**
 * frontend/pages/EngineeringDashboard.js — Phase 10C.11A Engineering Scenario Workbench Page
 * =========================================================================================
 * Connects the Engineering Scenario Workbench UI to the 10 verified backend endpoints.
 */

import { EngineeringApiClient } from "../api/engineeringClient.js";
import { renderEngineeringWorkbench } from "../components/EngineeringWorkbench.js?v=table_v2";

function createBaseCandidate({ solarM2 = 80.0, battKwh = 650.0 } = {}) {
  const capex = solarM2 * 250.0 + battKwh * 300.0;
  return {
    solar_area_m2: solarM2,
    battery_capacity_kwh: battKwh,
    battery_mass_tonnes: Number((battKwh * 0.008).toFixed(3)),
    deck_area_limit_m2: 120.0,
    battery_weight_limit_tonnes: 10.0,
    is_physically_valid: true,
    constraint_violations: [],
    candidate_status: "VALID",
    clean_energy_available_kwh: 350.0,
    clean_energy_utilized_kwh: 200.0,
    curtailed_energy_kwh: 150.0,
    feasibility_status: "FEASIBLE",
    annual_fuel_displaced_L: 15000.0,
    annual_co2_displaced_kg: 39000.0,
    total_initial_capex_usd: capex,
    net_present_value_usd: 45000.0,
    internal_rate_of_return_pct: 14.5,
    irr_status: "IRR_CALCULATED",
    simple_payback_years: 4.8,
    discounted_payback_years: 5.6,
    lcoe_usd_per_kwh: 0.12,
    lcoe_status: "LCOE_CALCULATED",
    objective_value: 45000.0,
  };
}

export class EngineeringDashboardPage {
  constructor(containerId, options = {}) {
    this.container = document.getElementById(containerId);
    this.apiClient = new EngineeringApiClient(options.baseUrl || "");
    this.state = {
      activeOperation: "simulate-voyage",
      loading: false,
      result: null,
      error: null,
    };
  }

  init() {
    this.render();
  }

  async runOperation() {
    this.state.loading = true;
    this.state.error = null;
    this.state.result = null;
    this.render();

    const shipType = this.container.querySelector("#eng-ship-type")?.value || "Oil Service Boat";
    const routeId = this.container.querySelector("#eng-route-id")?.value || "Escravos-Lagos";
    const speedKnots = parseFloat(this.container.querySelector("#eng-speed-knots")?.value || "12.0");
    const month = parseInt(this.container.querySelector("#eng-month")?.value || "7", 10);
    const solarM2 = parseFloat(this.container.querySelector("#eng-solar-m2")?.value || "80.0");
    const battKwh = parseFloat(this.container.querySelector("#eng-batt-kwh")?.value || "650.0");
    const fuelPriceStr = this.container.querySelector("#eng-fuel-price")?.value;
    const fuelPrice = fuelPriceStr ? parseFloat(fuelPriceStr) : null;

    try {
      let res;
      switch (this.state.activeOperation) {
        case "simulate-voyage":
          res = await this.apiClient.simulateVoyage({
            ship_type: shipType,
            route_id: routeId,
            speed_knots: speedKnots,
            month: month,
            solar_area_m2: solarM2,
            battery_capacity_kwh: battKwh,
            ...(fuelPrice ? { fuel_price_usd_per_mt: fuelPrice * 1176.0 } : {}),
          });
          break;
        case "evaluate-sizing":
          res = await this.apiClient.evaluateSizing({
            ship_type: shipType,
            solar_area_m2: solarM2,
            battery_capacity_kwh: battKwh,
            deck_area_limit_m2: 120.0,
            battery_weight_limit_tonnes: 10.0,
            predicted_soh: 0.95,
            auxiliary_energy_demand_kwh: 200.0,
            voyage_duration_hours: 20.8,
            predicted_fuel_consumption_L: 2400.0,
            predicted_CO2_kg: 6350.0,
            daily_ghi_kwh_per_m2: 4.5,
            annual_voyages: 52,
            fuel_price_usd_per_l: fuelPrice || 1.0,
          });
          break;
        case "optimize-sizing":
          res = await this.apiClient.optimizeSizing({
            ship_type: shipType,
            min_solar_area_m2: 0.0,
            max_solar_area_m2: 120.0,
            step_solar_area_m2: 20.0,
            min_battery_capacity_kwh: 0.0,
            max_battery_capacity_kwh: 800.0,
            step_battery_capacity_kwh: 100.0,
            objective: "MAX_NPV",
          });
          break;
        case "speed-cooptimization":
          res = await this.apiClient.optimizeSpeedAndSizing({
            ship_type: shipType,
            route_id: routeId,
            vmin: 8.0,
            vmax: 14.0,
            v_step: 1.0,
            apv_min: 0.0,
            apv_max: 100.0,
            apv_step: 20.0,
            ebatt_min: 0.0,
            ebatt_max: 600.0,
            ebatt_step: 100.0,
            objective: "PARETO_FRONTIER",
          });
          break;
        case "sensitivity-analysis": {
          const baseCand = createBaseCandidate({ solarM2, battKwh });
          res = await this.apiClient.runSensitivityAnalysis({
            base_candidate: baseCand,
            parameter_name: "fuel_price_usd_per_l",
            metric_name: "net_present_value_usd",
            ship_type: shipType,
            sweep_bounds: { parameter_name: "fuel_price_usd_per_l", min_value: 0.5, max_value: 2.5, step: 0.25 },
          });
          break;
        }
        case "break-even-analysis": {
          const baseCand = createBaseCandidate({ solarM2, battKwh });
          res = await this.apiClient.runBreakEvenAnalysis({
            base_candidate: baseCand,
            parameter_name: "fuel_price_usd_per_l",
            metric_name: "net_present_value_usd",
            target_value: 0.0,
            lower_bound: 0.5,
            upper_bound: 5.0,
            ship_type: shipType,
          });
          break;
        }
        case "grid-2d-analysis": {
          const baseCand = createBaseCandidate({ solarM2, battKwh });
          res = await this.apiClient.run2DGridAnalysis({
            base_candidate: baseCand,
            parameter_x_name: "fuel_price_usd_per_l",
            parameter_y_name: "discount_rate",
            metric_name: "net_present_value_usd",
            sweep_bounds_x: { parameter_name: "fuel_price_usd_per_l", min_value: 0.8, max_value: 1.8, step: 0.2 },
            sweep_bounds_y: { parameter_name: "discount_rate", min_value: 0.05, max_value: 0.15, step: 0.02 },
            ship_type: shipType,
          });
          break;
        }
        case "portfolio-optimization":
          res = await this.apiClient.optimizeFleetPortfolio({
            total_portfolio_capex_budget_usd: 500000.0,
            portfolio_items: [
              {
                vessel_id: "VESSEL_OSV_01",
                candidate: createBaseCandidate({ solarM2: 80.0, battKwh: 400.0 }),
                ship_type: "Oil Service Boat",
                route_id: "Escravos-Lagos",
              },
              {
                vessel_id: "VESSEL_TRAWLER_02",
                candidate: createBaseCandidate({ solarM2: 50.0, battKwh: 200.0 }),
                ship_type: "Fishing Trawler",
                route_id: "Escravos-Lagos",
              },
            ],
          });
          break;
        case "cii-trajectory":
          res = await this.apiClient.simulateCIITrajectory({
            vessel_id: "VESSEL_01",
            ship_type: "Tanker Ship",
            dwt_tonnes: 5000.0,
            route_id: routeId,
            voyage_distance_nm: 250.0,
            baseline_single_voyage_fuel_L: 3200.0,
            baseline_single_voyage_co2_kg: 8500.0,
            start_year: 2023,
            end_year: 2026,
            annual_fuel_displaced_L: 25000.0,
            annual_co2_displaced_kg: 66000.0,
          });
          break;
        case "export-dossier":
          res = await this.apiClient.exportScenarioDossier({
            scenario_name: "Retrofit_Analysis_2026",
            vessel_id: "VESSEL_OSV_01",
            ship_type: shipType,
            route_id: routeId,
            export_formats: ["ALL"],
          });
          break;
        default:
          throw new Error(`Unknown operation: ${this.state.activeOperation}`);
      }

      if (res.success && res.data) {
        this.state.result = res.data;
      } else {
        this.state.error = res.error || { message: `Execution failed with HTTP ${res.status}` };
      }
    } catch (err) {
      this.state.error = { message: err.message || "Execution exception occurred" };
    } finally {
      this.state.loading = false;
      this.render();
    }
  }

  render() {
    if (!this.container) return;

    this.container.innerHTML = renderEngineeringWorkbench({
      activeOperation: this.state.activeOperation,
      loading: this.state.loading,
      result: this.state.result,
      error: this.state.error,
    });

    // Bind operation tabs
    const tabBtns = this.container.querySelectorAll(".eng-tab-btn");
    tabBtns.forEach(btn => {
      btn.addEventListener("click", (e) => {
        const opId = btn.getAttribute("data-op-id");
        if (opId && opId !== this.state.activeOperation) {
          this.state.activeOperation = opId;
          this.state.result = null;
          this.state.error = null;
          this.render();
        }
      });
    });

    // Bind run button
    const runBtn = this.container.querySelector("#btn-run-operation");
    if (runBtn) {
      runBtn.addEventListener("click", () => this.runOperation());
    }
  }
}
