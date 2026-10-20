/**
 * frontend/tests/engineering_summary.test.js — Engineering Workbench Structured Tables Tests
 * =========================================================================================
 * Verifies that structured simulation outputs are automatically formatted into the 4 clear
 * tables specified by the user without open raw JSON blocks.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { renderEngineeringWorkbench, renderHumanReadableEngineeringSummary } from "../components/EngineeringWorkbench.js";

// Real Oil Service Boat / Escravos-Lagos sample scenario output returned by backend
const oilServiceBoatScenario = {
  provenance: {
    operation: "SIMULATE_VOYAGE",
    underlying_phase: "Phase 6",
    status: "SUCCESS",
    vessel_id: "Oil Service Boat",
  },
  data: {
    request: {
      ship_type: "Oil Service Boat",
      route_id: "Escravos-Lagos",
      month: 7,
      speed_knots: 12.0,
      initial_soc: 0.9,
      evaluation_year: 2026,
    },
    tier1_predictions: {
      weather: {
        temperature_c: 25.88,
        wind_speed_knots: 4.36,
        significant_wave_height_m: 1.77,
      },
      fuel_consumption_L: {
        value: 8011.9,
        unit: "Liters",
      },
      co2_emissions_kg: {
        value: 22032.4,
        unit: "kg",
      },
      battery_health: {
        predicted_soh: 0.7387,
      },
      battery_operation: {
        predicted_soc_end_of_voyage: 0.5292,
      },
    },
    phase3_output: {
      voyage_metadata: {
        ship_type: "Oil Service Boat",
        distance_nm: 250.0,
        voyage_duration_hours: 20.833333333333332,
        deadweight_tonnes: 1800.0,
      },
      tier_2_baseline_metrics: {
        baseline_fuel_cost_usd: 9213.69,
        baseline_operational_cii_gco2_per_dwt_nm: 48.96088888888889,
        fuel_price_usd_per_l: 1.15,
      },
      tier_3_clean_energy_feasibility: {
        auxiliary_energy_demand_kwh: 180.0,
        usable_battery_energy_kwh: 335.96785151999995,
        estimated_solar_energy_kwh: 46.28493365815412,
        total_clean_energy_available_kwh: 382.25278517815406,
        clean_energy_utilized_kwh: 180.0,
        energy_balance_kwh: 202.25278517815406,
        energy_deficit_kwh: 0.0,
        feasibility_status: "FEASIBLE",
      },
      tier_4_engineering_scenario_estimates: {
        estimated_fuel_displaced_L: 46.58823529411765,
        estimated_co2_displaced_kg: 123.3144,
        net_assisted_fuel_L: 7965.311764705882,
        net_assisted_co2_kg: 21909.0856,
        net_assisted_fuel_cost_usd: 9160.11,
        net_assisted_operational_cii_gco2_per_dwt_nm: 48.68685688888889,
        delta_fuel_pct: -0.5814879778094837,
        delta_cii_pct: -0.5596957208474757,
      },
    },
    regulatory_assessment: {
      vessel_category: null,
      evaluation_year: 2026,
      capacity_dwt: 1800.0,
      distance_nm: 250.0,
      baseline_attained_cii: 48.96088888888889,
      assisted_attained_cii: 48.68685688888889,
      baseline_cii_rating: "NOT_ASSESSED",
      assisted_cii_rating: "NOT_ASSESSED",
      cii_assessment_status: "UNSUPPORTED_VESSEL_CATEGORY_MAPPING",
      source_document: "IMO Resolution MEPC.353(78) & MEPC.354(78)",
      disclaimer: "CII rating bands (A-E) apply strictly to qualifying vessel categories under MARPOL Annex VI Reg 28. For non-qualifying vessels, numerical CII is reported as an engineering metric, but statutory rating is NOT_ASSESSED.",
    },
  },
};

test("1. Table: Voyage Summary renders actual vessel, route, distance, speed, duration, and month", () => {
  const html = renderHumanReadableEngineeringSummary(oilServiceBoatScenario);
  assert.ok(html.includes("1. Voyage Summary"));
  assert.ok(html.includes("Ship Type"));
  assert.ok(html.includes("Oil Service Boat"));
  assert.ok(html.includes("Route"));
  assert.ok(html.includes("Escravos-Lagos"));
  assert.ok(html.includes("250.00")); // Distance
  assert.ok(html.includes("12.00"));  // Speed
  assert.ok(html.includes("20.83"));  // Duration
  assert.ok(html.includes("July"));   // Month
});

test("2. Table: Fuel and Environmental Impact matches actual test references", () => {
  const html = renderHumanReadableEngineeringSummary(oilServiceBoatScenario);
  assert.ok(html.includes("2. Fuel and Environmental Impact"));
  assert.ok(html.includes("8,011.90 L")); // Baseline fuel
  assert.ok(html.includes("7,965.31 L")); // Assisted fuel
  assert.ok(html.includes("46.59 L"));    // Estimated fuel displaced
  assert.ok(html.includes("22,032.40 kg")); // Baseline CO2
  assert.ok(html.includes("123.31 kg avoided")); // Estimated CO2 avoided
  assert.ok(html.includes("48.96 gCO₂/(DWT·nm)")); // Baseline CII
  assert.ok(html.includes("48.69 gCO₂/(DWT·nm)")); // Assisted CII
});

test("3. Table: Clean Energy Analysis renders all 9 required parameters with explicit units", () => {
  const html = renderHumanReadableEngineeringSummary(oilServiceBoatScenario);
  assert.ok(html.includes("3. Clean Energy Analysis"));
  assert.ok(html.includes("Estimated Solar Energy"));
  assert.ok(html.includes("46.28"));
  assert.ok(html.includes("Usable Battery Energy"));
  assert.ok(html.includes("335.97"));
  assert.ok(html.includes("Clean Energy Available"));
  assert.ok(html.includes("382.25"));
  assert.ok(html.includes("Clean Energy Utilized"));
  assert.ok(html.includes("180.00")); // Clean energy utilized
  assert.ok(html.includes("Energy Balance"));
  assert.ok(html.includes("202.25"));
  assert.ok(html.includes("Energy Deficit"));
  assert.ok(html.includes("0.00"));
  assert.ok(html.includes("46.59 (Estimated)"));
  assert.ok(html.includes("123.31 (Estimated)"));
  assert.ok(html.includes("FEASIBLE"));
});

test("4. Table: Regulatory Assessment renders NOT ASSESSED for unsupported vessel category (never default to A)", () => {
  const html = renderHumanReadableEngineeringSummary(oilServiceBoatScenario);
  assert.ok(html.includes("4. Regulatory Assessment"));
  assert.ok(html.includes("Evaluation Year"));
  assert.ok(html.includes("2026"));
  assert.ok(html.includes("NOT ASSESSED"));
  assert.ok(!html.includes("BAND A")); // Never default to A for unsupported vessel
  assert.ok(html.includes("UNSUPPORTED VESSEL CATEGORY MAPPING"));
  assert.ok(html.includes("IMO Resolution MEPC.353(78) &amp; MEPC.354(78)"));
});

test("5. Collapsed Advanced Details / Audit Information section hides raw JSON", () => {
  const html = renderEngineeringWorkbench({
    activeOperation: "simulate-voyage",
    loading: false,
    result: oilServiceBoatScenario,
    error: null,
  });
  // Check that <details> is present and NOT open by default
  assert.ok(html.includes('<details class="advanced-details-box">'));
  assert.ok(!html.includes('<details class="advanced-details-box" open>'));
  assert.ok(html.includes("Advanced Details / Audit Information"));
  assert.ok(html.includes("raw-json-viewer"));
});
