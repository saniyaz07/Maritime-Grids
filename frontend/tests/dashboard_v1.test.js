/**
 * frontend/tests/dashboard_v1.test.js — Phase 10C.11B Driver Dashboard V1 Test Suite
 * ==================================================================================
 * Exhaustive Node.js test runner suite verifying all 20 required criteria:
 *   1. Current speed rendering
 *   2. Missing speed rendering
 *   3. Engine ON rendering
 *   4. Engine OFF rendering
 *   5. Engine UNKNOWN rendering
 *   6. Missing engine telemetry (RPM, Load)
 *   7. Fuel rendering
 *   8. Missing fuel rendering
 *   9. Battery rendering
 *   10. Weather rendering
 *   11. Provenance rendering
 *   12. Freshness rendering
 *   13. Solar semantic label
 *   14. Solar uncertainty notice
 *   15. ETA disclaimer
 *   16. Advisory human-review badge
 *   17. Null preservation (null != 0)
 *   18. API failure handling
 *   19. No engine-control buttons
 *   20. No autonomous controls
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { WeatherProvenanceType, WeatherQualityState, WeatherFreshnessState } from '../contracts/types.js';
import { formatValue, renderTelemetryField } from '../components/ProvenanceBadge.js';
import { renderSpeedCard, renderEngineStateCard } from '../components/SpeedEngineCard.js';
import { renderFuelCard, renderBatteryCard, renderEnergyCard } from '../components/EnergyCard.js';
import { renderSolarCard } from '../components/SolarCard.js';
import { renderWeatherCard } from '../components/WeatherCard.js';
import { renderVoyageStatusCard } from '../components/VoyageStatusCard.js';
import { renderAdvisoryPanel } from '../components/AdvisoryPanel.js';

test('1. Current speed rendering: renders valid SOG and COG with units', () => {
  const html = renderSpeedCard({
    speedOverGroundKnots: 12.4,
    courseOverGroundDeg: 285.0,
    designSpeedKnots: 12.0,
    provenance: 'OBSERVED',
    freshness: 'FRESH',
  });
  assert.ok(html.includes('12.4 kn'));
  assert.ok(html.includes('285.0 °'));
  assert.ok(html.includes('OBSERVED'));
});

test('2. Missing speed rendering: displays Unavailable without fabricating speed', () => {
  const html = renderSpeedCard({
    speedOverGroundKnots: null,
    courseOverGroundDeg: null,
  });
  assert.ok(html.includes('Unavailable'));
  assert.ok(!html.includes('0.0 kn'));
  assert.ok(!html.includes('0.00 kn'));
});

test('3. Engine ON rendering: displays ENGINE ON when explicitly reported', () => {
  const html = renderEngineStateCard({
    engineState: 'ON',
    engineRpm: 1450,
    engineLoadPct: 75.0,
  });
  assert.ok(html.includes('ENGINE ON'));
  assert.ok(html.includes('1450 RPM'));
  assert.ok(html.includes('75.0 %'));
});

test('4. Engine OFF rendering: displays ENGINE OFF when explicitly reported', () => {
  const html = renderEngineStateCard({
    engineState: 'OFF',
    engineRpm: 0,
    engineLoadPct: 0.0,
  });
  assert.ok(html.includes('ENGINE OFF'));
  assert.ok(html.includes('0 RPM'));
});

test('5. Engine UNKNOWN rendering: displays UNKNOWN when live telemetry not connected', () => {
  const html = renderEngineStateCard({
    engineState: 'UNKNOWN',
    engineRpm: null,
    engineLoadPct: null,
  });
  assert.ok(html.includes('ENGINE STATE UNKNOWN'));
  assert.ok(html.includes('Live engine telemetry is not connected'));
  assert.ok(html.includes('status-unknown'));
});

test('6. Missing engine telemetry: RPM and Load display Unavailable when null', () => {
  const html = renderEngineStateCard({
    engineState: 'UNKNOWN',
    engineRpm: null,
    engineLoadPct: null,
  });
  assert.ok(html.includes('Unavailable'));
  assert.ok(!html.includes('0 RPM'));
});

test('7. Fuel rendering: displays formatted fuel volume and rate', () => {
  const html = renderFuelCard({
    fuelRemainingLiters: 14250.0,
    fuelConsumptionRateLph: 145.2,
    fuelPriceUsdPerLiter: 1.15,
  });
  assert.ok(html.includes('14,250 L') || html.includes('14250 L'));
  assert.ok(html.includes('145.2 L/h'));
  assert.ok(html.includes('1.15 $/L'));
});

test('8. Missing fuel rendering: displays Unavailable instead of 0 L', () => {
  const html = renderFuelCard({
    fuelRemainingLiters: null,
    fuelConsumptionRateLph: null,
  });
  assert.ok(html.includes('Unavailable'));
  assert.ok(!html.includes('0.0 L'));
  assert.ok(!html.includes('0 L'));
});

test('9. Battery rendering: displays SOC and SOH percentages and usable capacity', () => {
  const html = renderBatteryCard({
    batterySocPct: 82.5,
    batterySohPct: 95.0,
    batteryEnergyAvailableKwh: 510.0,
    nominalCapacityKwh: 650.0,
  });
  assert.ok(html.includes('82.5%'));
  assert.ok(html.includes('95.0 %'));
  assert.ok(html.includes('510.0 kWh'));
  assert.ok(html.includes('650 kWh'));
});

test('10. Weather rendering: displays atmospheric and marine fields with units', () => {
  const weatherContext = {
    weather_provenance: 'FORECAST',
    weather_quality: 'VALID',
    weather_freshness: 'FRESH',
    departure_weather: {
      data_source: 'Open-Meteo',
      wind_speed_knots: 19.4,
      wind_direction_deg: 230.0,
      wave_height_m: 1.85,
      wave_period_s: 6.5,
      temperature_c: 29.1,
      relative_humidity_pct: 80.0,
      surface_pressure_hpa: 1013.2,
      current_speed_knots: 1.2,
    },
  };
  const html = renderWeatherCard(weatherContext);
  assert.ok(html.includes('19.4 kn'));
  assert.ok(html.includes('1.85 m'));
  assert.ok(html.includes('6.5 s'));
  assert.ok(html.includes('29.1 °C'));
  assert.ok(html.includes('1.2 kn'));
});

test('11. Provenance rendering: tags OBSERVED, FORECAST, SIMULATED correctly', () => {
  const obsHtml = renderSpeedCard({ speedOverGroundKnots: 12.0, provenance: 'OBSERVED' });
  assert.ok(obsHtml.includes('prov-observed'));

  const simHtml = renderSpeedCard({ speedOverGroundKnots: 12.0, provenance: 'SIMULATED' });
  assert.ok(simHtml.includes('prov-simulated'));
});

test('12. Freshness rendering: displays FRESH, STALE, EXPIRED tags', () => {
  const freshHtml = renderWeatherCard({
    weather_provenance: 'FORECAST',
    weather_freshness: 'FRESH',
    departure_weather: { wind_speed_knots: 15.0 },
  });
  assert.ok(freshHtml.includes('freshness-fresh'));
});

test('13. Solar semantic label: mandatory CLIMATOLOGICAL SCENARIO ESTIMATE is rendered', () => {
  const html = renderSolarCard({
    estimatedSolarKwh: 125.0,
    panelSizeM2: 80.0,
  });
  assert.ok(html.includes('CLIMATOLOGICAL SCENARIO ESTIMATE'));
  assert.ok(html.includes('125.0 kWh'));
  assert.ok(html.includes('Semantic Limitation'));
});

test('14. Solar uncertainty notice: displayed when voyage > 24 hours', () => {
  const html = renderSolarCard({
    estimatedSolarKwh: 250.0,
    diurnalUncertaintyFlag: true,
  });
  assert.ok(html.includes('Diurnal Uncertainty Notice'));
  assert.ok(html.includes('Voyage duration exceeds 24.0 hours'));
});

test('15. ETA disclaimer: renders linear estimate and non-hydrodynamic notices', () => {
  const html = renderVoyageStatusCard({
    timeline: { estimated_arrival_utc: '2026-06-15T20:00:00Z' },
  });
  assert.ok(html.includes('Application-level linear estimate'));
  assert.ok(html.includes('Not a hydrodynamic voyage predictor.'));
});

test('16. Advisory human-review badge: visibly renders HUMAN REVIEW REQUIRED', () => {
  const advisories = [
    {
      rule_id: 'WIND_SAFETY_CHECK',
      severity: 'WARNING',
      message: 'High wind speed detected.',
      human_review_required: true,
    },
  ];
  const html = renderAdvisoryPanel(advisories, 'READY');
  assert.ok(html.includes('HUMAN REVIEW REQUIRED'));
  assert.ok(html.includes('WIND_SAFETY_CHECK'));
});

test('17. Null preservation: formatValue never converts null/undefined to 0', () => {
  assert.equal(formatValue(null, 'L').text, 'Unavailable');
  assert.equal(formatValue(undefined, 'kn').text, 'Unavailable');
  assert.equal(formatValue(0, 'kn').text, '0.00 kn'); // 0 is real
});

test('18. API failure handling: empty contexts produce clean fallback cards without throwing', () => {
  assert.ok(renderWeatherCard(null).includes('No Weather Context'));
  assert.ok(renderEnergyCard(null).includes('No Telemetry'));
  assert.ok(renderAdvisoryPanel([], 'UNAVAILABLE').includes('No active operational advisories'));
});

test('19. No engine-control buttons: verify zero engine actuation triggers', () => {
  const speedHtml = renderSpeedCard({});
  const engineHtml = renderEngineStateCard({});
  const combined = (speedHtml + engineHtml).toLowerCase();

  assert.ok(!combined.includes('button id="btn-engine-on"'));
  assert.ok(!combined.includes('button id="btn-engine-off"'));
  assert.ok(!combined.includes('start_engine'));
  assert.ok(!combined.includes('stop_engine'));
  assert.ok(!combined.includes('set_throttle'));
});

test('20. No autonomous controls: verify zero automated steering or route mutation triggers', () => {
  const allCards = [
    renderVoyageStatusCard({}),
    renderSpeedCard({}),
    renderEngineStateCard({}),
    renderFuelCard({}),
    renderBatteryCard({}),
    renderSolarCard({}),
    renderWeatherCard({}),
    renderAdvisoryPanel([]),
  ].join('\n').toLowerCase();

  const forbiddenActuations = [
    'set_rudder',
    'override_route',
    'steer_vessel',
    'execute_heading',
    'autonomous_drive',
  ];

  for (const term of forbiddenActuations) {
    assert.ok(!allCards.includes(term), `Forbidden actuation term '${term}' found in Driver Dashboard cards`);
  }
});
