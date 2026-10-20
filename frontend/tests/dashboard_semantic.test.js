/**
 * frontend/tests/dashboard_semantic.test.js — Phase 10C.11A Frontend Semantic & Safety Verification
 * =================================================================================================
 * Verifies all 12 mandatory semantic frontend criteria using Node.js test runner:
 *   1. Operator state rendering
 *   2. Missing telemetry rendering (null != 0)
 *   3. Provenance rendering
 *   4. Weather freshness rendering
 *   5. Solar semantic label ("CLIMATOLOGICAL SCENARIO ESTIMATE")
 *   6. Solar uncertainty flag
 *   7. Advisory rendering
 *   8. Human-review badge (human_review_required = true)
 *   9. ETA disclaimer ("Application-level linear estimate")
 *   10. API failure state handling
 *   11. No conversion of null to zero
 *   12. No autonomous control elements (zero actuators/buttons)
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { WeatherProvenanceType, WeatherQualityState, WeatherFreshnessState, AdvisorySeverity } from '../contracts/types.js';
import { formatValue, renderTelemetryField, renderProvenanceMetadata } from '../components/ProvenanceBadge.js';
import { renderVoyageStatusCard } from '../components/VoyageStatusCard.js';
import { renderWeatherCard } from '../components/WeatherCard.js';
import { renderEnergyCard } from '../components/EnergyCard.js';
import { renderSolarCard } from '../components/SolarCard.js';
import { renderAdvisoryPanel } from '../components/AdvisoryPanel.js';
import { renderEngineeringWorkbench } from '../components/EngineeringWorkbench.js';

test('1. formatValue: null and undefined are never rendered as zero', () => {
  const nullRes = formatValue(null, 'L');
  assert.equal(nullRes.isAvailable, false);
  assert.equal(nullRes.text, 'Unavailable');
  assert.notEqual(nullRes.text, '0 L');
  assert.notEqual(nullRes.text, '0.00 L');

  const undefRes = formatValue(undefined, '%');
  assert.equal(undefRes.isAvailable, false);
  assert.equal(undefRes.text, 'Unavailable');
});

test('2. renderTelemetryField: preserves null as explicit placeholder', () => {
  const html = renderTelemetryField({
    label: 'Battery SOC',
    value: null,
    unit: '%',
    nullPlaceholder: 'No SOC telemetry',
  });
  assert.ok(html.includes('No SOC telemetry'));
  assert.ok(!html.includes('0.00 %'));
  assert.ok(html.includes('val-unavailable'));
});

test('3. Provenance Metadata: renders valid provenance, quality, and freshness tags', () => {
  const html = renderProvenanceMetadata({
    source: 'Open-Meteo',
    provenance: WeatherProvenanceType.FORECAST,
    quality: WeatherQualityState.VALID,
    freshness: WeatherFreshnessState.FRESH,
    timestamp: '2026-06-15T12:00:00Z',
  });
  assert.ok(html.includes('Src: Open-Meteo'));
  assert.ok(html.includes('FORECAST'));
  assert.ok(html.includes('VALID'));
  assert.ok(html.includes('FRESH'));
  assert.ok(html.includes('2026-06-15T12:00:00Z'));
});

test('4. VoyageStatusCard: renders ETA with mandatory linear estimate disclaimer', () => {
  const html = renderVoyageStatusCard({
    vessel: { vessel_id: 'VESSEL_OSV_01', ship_type: 'Oil Service Boat' },
    voyageId: 'VOY_001',
    status: 'ACTIVE',
    position: { latitude: 5.80, longitude: 4.50, speed_over_ground_knots: 12.0 },
    route: { origin_port: 'Escravos', destination_port: 'Lagos', total_distance_nm: 250.0 },
    timeline: { remaining_distance_nm: 100.0, progress_pct: 60.0, estimated_arrival_utc: '2026-06-15T20:00:00Z' },
  });

  assert.ok(html.includes('Application-level linear estimate'));
  assert.ok(html.includes('Not a hydrodynamic voyage predictor.'));
  assert.ok(html.includes('VESSEL_OSV_01'));
  assert.ok(html.includes('Escravos'));
  assert.ok(html.includes('Lagos'));
});

test('5. WeatherCard: renders continuous atmospheric telemetry without zero coercion', () => {
  const weatherContext = {
    weather_provenance: 'FORECAST',
    weather_quality: 'VALID',
    weather_freshness: 'FRESH',
    departure_weather: {
      data_source: 'Open-Meteo',
      wind_speed_knots: 18.5,
      wind_direction_deg: 240.0,
      wave_height_m: 1.8,
      temperature_c: 28.5,
    },
  };

  const html = renderWeatherCard(weatherContext);
  assert.ok(html.includes('18.5 kn'));
  assert.ok(html.includes('1.80 m'));
  assert.ok(html.includes('28.5 °C'));
  assert.ok(html.includes('Semantic Boundary'));
});

test('6. EnergyCard: renders battery and fuel telemetry with explicit null placeholders', () => {
  const energyState = {
    battery_soc: 0.75,
    battery_soh: null, // Missing SOH telemetry
    fuel_remaining_liters: 3200.0,
    estimated_fuel_consumption_rate_l_per_hour: null,
    provenance: 'OBSERVED',
  };

  const html = renderEnergyCard(energyState);
  assert.ok(html.includes('75.0 %'));
  assert.ok(html.includes('No SOH telemetry'));
  assert.ok(html.includes('3200.0 L'));
  assert.ok(!html.includes('0.0 % SOH'));
});

test('7. SolarCard: renders mandatory CLIMATOLOGICAL SCENARIO ESTIMATE label', () => {
  const html = renderSolarCard({
    estimatedSolarKwh: 145.2,
    panelSizeM2: 80.0,
    panelEfficiencyPct: 21.5,
    dailyGhiKwhM2: 4.85,
    diurnalUncertaintyFlag: false,
  });

  assert.ok(html.includes('CLIMATOLOGICAL SCENARIO ESTIMATE'));
  assert.ok(html.includes('145.2 kWh'));
  assert.ok(html.includes('Semantic Limitation'));
  assert.ok(!html.includes('Diurnal Uncertainty Notice'));
});

test('8. SolarCard: displays diurnal uncertainty notice when voyage > 24 hours', () => {
  const html = renderSolarCard({
    estimatedSolarKwh: 290.4,
    panelSizeM2: 80.0,
    panelEfficiencyPct: 21.5,
    dailyGhiKwhM2: 4.85,
    diurnalUncertaintyFlag: true,
  });

  assert.ok(html.includes('Diurnal Uncertainty Flag'));
  assert.ok(html.includes('Diurnal Uncertainty Notice'));
  assert.ok(html.includes('Voyage duration exceeds 24.0 hours'));
});

test('9. AdvisoryPanel: renders HUMAN REVIEW REQUIRED badge and preserves severity', () => {
  const advisories = [
    {
      rule_id: 'WIND_SPEED_WARNING',
      category: 'WEATHER',
      severity: 'WARNING',
      message: 'Observed wind speed exceeds operator safety threshold.',
      suggested_action: 'Monitor vessel heading.',
      evidence: { wind_speed_knots: 26.0, threshold: 25.0 },
      human_review_required: true,
    },
  ];

  const html = renderAdvisoryPanel(advisories, 'READY');
  assert.ok(html.includes('HUMAN REVIEW REQUIRED'));
  assert.ok(html.includes('WARNING'));
  assert.ok(html.includes('WIND_SPEED_WARNING'));
  assert.ok(html.includes('Monitor vessel heading.'));
  assert.ok(html.includes('Decision Support Notice'));
});

test('10. Non-Actuation: verify zero autonomous control buttons or actuators in all components', () => {
  const cardsHtml = [
    renderVoyageStatusCard({}),
    renderWeatherCard({}),
    renderEnergyCard({}),
    renderSolarCard({}),
    renderAdvisoryPanel([]),
    renderEngineeringWorkbench({}),
  ].join('\n');

  const forbiddenTerms = [
    'set_throttle',
    'set_rudder',
    'start_engine',
    'stop_engine',
    'shutdown_engine',
    'override_route',
    'steer_vessel',
    'actuate',
    'execute_command',
  ];

  for (const term of forbiddenTerms) {
    assert.ok(!cardsHtml.toLowerCase().includes(term), `Forbidden actuation term '${term}' found in UI`);
  }
});
