# DATA DICTIONARY — PROCESSED DATASETS
**Project:** Maritime Grid Simulation  
**Dataset:** `data/processed/master_training_table.csv`  
**Generated Date:** 2026-09-26  
**Status:** PHASE 1 PROCESSED  

---

## Overview
This document specifies the schema, definitions, measurement units, provenance, categorization, and limitations for all 47 attributes in `master_training_table.csv`.

Every variable is classified into one of three strict categories:
1. **`OBSERVED`**: Direct empirical records originating from primary vessel logs or sensor measurements.
2. **`DERIVED`**: Computed, transformed, aggregated, or climatologically joined values derived from empirical time series.
3. **`ASSUMED / ENGINEERING DEFAULT`**: Representative naval architecture, techno-economic, and battery/solar parameters populated from industry standards for simulation prototyping. Fully editable in future simulation UIs.

---

## Variable Specifications

| Column Name | Category | Data Type | Units | Source | Description & Processing | Limitations & Assumptions |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `ship_id` | **`OBSERVED`** | String | None | `ship_fuel_efficiency.csv` | Unique vessel identifier (NG001 to NG120). | 120 unique vessels operating in Nigerian coastal waters. |
| `ship_type` | **`OBSERVED`** | String | None | `ship_fuel_efficiency.csv` | Vessel operational class: `Oil Service Boat`, `Fishing Trawler`, `Surfer Boat`, or `Tanker Ship`. | Categorical grouping across 4 distinct hull designs. |
| `route_id` | **`OBSERVED`** | String | None | `ship_fuel_efficiency.csv` | Master shipping corridor name matching `routes.csv`. | 4 commercial corridors in Gulf of Guinea. |
| `month` | **`OBSERVED`** | String | None | `ship_fuel_efficiency.csv` | Calendar month of voyage observation (`January` through `December`). | Does not record voyage year; climatology join key. |
| `distance` | **`OBSERVED`** | Float | Nautical miles / km | `ship_fuel_efficiency.csv` | Total voyage distance traveled. | Valid range: 20.08 to 498.55. |
| `fuel_type` | **`OBSERVED`** | String | None | `ship_fuel_efficiency.csv` | Primary bunker fuel consumed: `HFO` (Heavy Fuel Oil) or `Diesel` (Marine Gas Oil). | Binary categorical indicator. |
| `fuel_consumption` | **`OBSERVED`** | Float | Liters (L) [Inferred] | `ship_fuel_efficiency.csv` | Total fuel burned during the transit. | Valid range: 237.88 to 24,648.52. Physical Unit Note: The original raw source ship_fuel_efficiency.csv and DATASET_EXPLANATION.txt did not explicitly annotate a physical unit for fuel_consumption. A physical and engineering consistency audit therefore classifies the unit as Liters (L) per voyage, Evidence Level B — Strongly Inferred. The classification is supported by the empirical CO2_emissions/fuel_consumption ratio (~2.750 kg CO2/L for Marine Diesel and ~2.754 kg CO2/L for HFO), consistency with standard marine fuel emission factors, and vessel engine-power/voyage plausibility checks. This is an engineering inference, not an explicitly sourced unit. |
| `CO2_emissions` | **`OBSERVED`** | Float | kg CO₂ | `ship_fuel_efficiency.csv` | Total mass of carbon dioxide emitted during voyage. | Valid range: 615.68 to 71,871.21. |
| `weather_conditions` | **`OBSERVED`** | String | None | `ship_fuel_efficiency.csv` | Qualitative sea state logged by shipmaster: `Calm`, `Moderate`, or `Stormy`. | Discrete subjective log entry. |
| `engine_efficiency` | **`OBSERVED`** | Float | % | `ship_fuel_efficiency.csv` | Operational thermal/mechanical efficiency of propulsion engine. | Valid range: 70.01% to 94.98%. |
| `PS` | **`DERIVED`** | Float | kPa | `nasa_power/*.csv` | Surface barometric pressure; 5-year route monthly climatological mean. | Derived from daily MERRA-2 assimilation (2020–2024). |
| `WS10M` | **`DERIVED`** | Float | m/s | `nasa_power/*.csv` | Mean wind speed at 10 meters elevation above sea level. | Monthly average across 2020–2024. |
| `WS10M_MAX` | **`DERIVED`** | Float | m/s | `nasa_power/*.csv` | Maximum wind speed at 10 meters elevation. | Climatological mean of daily maxima. |
| `WS10M_MIN` | **`DERIVED`** | Float | m/s | `nasa_power/*.csv` | Minimum wind speed at 10 meters elevation. | Climatological mean of daily minima. |
| `WS50M_MAX` | **`DERIVED`** | Float | m/s | `nasa_power/*.csv` | Maximum wind speed at 50 meters elevation (relevant for offshore wind/tall superstructures). | Climatological mean of daily maxima. |
| `WS50M_MIN` | **`DERIVED`** | Float | m/s | `nasa_power/*.csv` | Minimum wind speed at 50 meters elevation. | Climatological mean of daily minima. |
| `RH2M` | **`DERIVED`** | Float | % | `nasa_power/*.csv` | Relative humidity at 2 meters elevation. | Monthly mean across 2020–2024. |
| `T2M_MIN` | **`DERIVED`** | Float | °C | `nasa_power/*.csv` | Minimum daily ambient air temperature at 2 meters elevation. | Climatological mean of daily minimums. |
| `ALLSKY_SFC_SW_DWN` | **`DERIVED`** | Float | kW-hr/m²/day | `nasa_power/*.csv` | All-Sky Surface Shortwave Downward Irradiance (GHI). | Represents typical daily solar irradiation available per m² in that month. |
| `CLRSKY_SFC_SW_DWN` | **`DERIVED`** | Float | kW-hr/m²/day | `nasa_power/*.csv` | Clear-Sky Surface Shortwave Downward Irradiance. | Theoretical clear-sky baseline. |
| `ALLSKY_SFC_SW_DNI` | **`DERIVED`** | Float | kW-hr/m²/day | `nasa_power/*.csv` | Direct Normal Irradiance under all sky conditions. | Key input for concentrated/tracking solar models. |
| `ALLSKY_SFC_LW_DWN` | **`DERIVED`** | Float | kW-hr/m²/day | `nasa_power/*.csv` | Surface Longwave Downward Irradiance (thermal infrared radiation). | Useful for vessel hull thermal balance calculations. |
| `ALLSKY_SFC_PAR_TOT` | **`DERIVED`** | Float | kW-hr/m²/day | `nasa_power/*.csv` | All-Sky Surface Total Photosynthetically Active Radiation. | Surface radiation metric (400–700 nm). |
| `CLRSKY_SFC_PAR_TOT` | **`DERIVED`** | Float | kW-hr/m²/day | `nasa_power/*.csv` | Clear-Sky Surface Total Photosynthetically Active Radiation. | Surface radiation metric (400–700 nm). |
| `wave_height_max` | **`DERIVED`** | Float | meters (m) | `marine/*.csv` | Maximum significant wave height; monthly mean over valid hindcast window (2021-10-01 to 2024-12-24). | Derived from Open-Meteo Copernicus Marine model. |
| `wave_period_max` | **`DERIVED`** | Float | seconds (s) | `marine/*.csv` | Peak wave period; monthly mean over valid hindcast window. | Associated with ocean swell and wave encounters. |
| `wave_direction_dominant` | **`DERIVED`** | Float | degrees (°) | `marine/*.csv` | Dominant wave direction; monthly circular mean over valid hindcast window. | 0° = North, 90° = East, 180° = South, 270° = West. |
| `displacement_tonnes` | **`ASSUMED / ENGINEERING DEFAULT`** | Integer | Tonnes | `ship_profiles.csv` | Total vessel displacement (weight of water displaced at design waterline). | Benchmark: OSV=2500t, Trawler=650t, Surfer=120t, Tanker=18500t. |
| `engine_power_kw` | **`ASSUMED / ENGINEERING DEFAULT`** | Integer | kW | `ship_profiles.csv` | Total installed propulsion prime mover power capacity. | Sized to voyage fuel burn: OSV=4500kW, Trawler=1200kW, Surfer=1800kW, Tanker=7200kW. |
| `hull_length_m` | **`ASSUMED / ENGINEERING DEFAULT`** | Float | meters (m) | `ship_profiles.csv` | Vessel length overall (LOA). | Representative hull dimension: OSV=65m, Trawler=38m, Surfer=22m, Tanker=145m. |
| `hull_beam_m` | **`ASSUMED / ENGINEERING DEFAULT`** | Float | meters (m) | `ship_profiles.csv` | Maximum hull width at waterline. | Representative: OSV=15.5m, Trawler=8.5m, Surfer=5.8m, Tanker=23.0m. |
| `hull_draft_m` | **`ASSUMED / ENGINEERING DEFAULT`** | Float | meters (m) | `ship_profiles.csv` | Design loaded draft (depth below waterline). | Representative: OSV=5.2m, Trawler=3.8m, Surfer=1.4m, Tanker=8.5m. |
| `max_speed_knots` | **`ASSUMED / ENGINEERING DEFAULT`** | Float | knots (kt) | `ship_profiles.csv` | Design maximum vessel operational speed. | Class defaults: OSV=14.5kt, Trawler=11.0kt, Surfer=28.0kt, Tanker=13.5kt. |
| `propulsion_type` | **`ASSUMED / ENGINEERING DEFAULT`** | String | None | `ship_profiles.csv` | Primary vessel propulsion architecture. | Hybridization scheme: Diesel-Electric, Mechanical Geared, Waterjet, 2-Stroke PTO/PTI. |
| `propeller_specs` | **`ASSUMED / ENGINEERING DEFAULT`** | String | None | `ship_profiles.csv` | Propeller configuration and dimensions. | Controllable pitch, Kort nozzle, waterjet, fixed pitch. |
| `dwt_tonnes` | **`ASSUMED / ENGINEERING DEFAULT`** | Integer | Tonnes | `ship_profiles.csv` | Deadweight Tonnage (cargo, fuel, ballast, crew carrying capacity). | Mandatory capacity metric for IMO Carbon Intensity Indicator (CII). |
| `battery_cell_config` | **`ASSUMED / ENGINEERING DEFAULT`** | String | None | `ship_profiles.csv` | Pack series/parallel cell configuration. | e.g., 96S120P (nominal 400V) or 96S250P (nominal 800V). |
| `battery_pack_capacity_kwh` | **`ASSUMED / ENGINEERING DEFAULT`** | Integer | kWh | `ship_profiles.csv` | Total onboard energy storage system (BESS) capacity. | Sized for peak-shaving & port maneuvering: OSV=650kWh, Trawler=250kWh, Surfer=150kWh, Tanker=1200kWh. |
| `nominal_voltage_v` | **`ASSUMED / ENGINEERING DEFAULT`** | Integer | Volts (V) | `ship_profiles.csv` | DC bus / battery system nominal operational voltage. | Standard marine DC microgrid voltage: 400V / 800V. |
| `battery_chemistry` | **`ASSUMED / ENGINEERING DEFAULT`** | String | None | `ship_profiles.csv` | Electrochemical cell chemistry: Lithium Nickel Manganese Cobalt (`NMC`) or Lithium Iron Phosphate (`LFP`). | NMC for high energy density; LFP for high cycle life and thermal runaway tolerance. |
| `solar_panel_size_m2` | **`ASSUMED / ENGINEERING DEFAULT`** | Integer | m² | `ship_profiles.csv` | Usable deckhouse, wheelhouse roof, and canopy solar PV aperture area. | OSV=80m², Trawler=45m², Surfer=25m², Tanker=250m². |
| `solar_panel_efficiency_pct` | **`ASSUMED / ENGINEERING DEFAULT`** | Float | % | `ship_profiles.csv` | Rated photovoltaic module conversion efficiency at STC. | High-efficiency marine monocrystalline solar panels (21.0% to 22.0%). |
| `fuel_price_per_litre` | **`ASSUMED / ENGINEERING DEFAULT`** | Float | USD / Litre | `ship_profiles.csv` | Delivered marine bunker fuel cost. | Baseline: HFO ≈ $0.95–$1.10/L, MGO/Diesel ≈ $1.15–$1.20/L. |
| `battery_degradation_cost_per_kwh_cycled` | **`ASSUMED / ENGINEERING DEFAULT`** | Float | USD / kWh cycled | `ship_profiles.csv` | Amortized battery replacement wear-cost per throughput cycle. | Estimated levelized storage wear cost ($0.06 to $0.09 / kWh cycled). |
| `notes_assumptions` | **`ASSUMED / ENGINEERING DEFAULT`** | String | None | `ship_profiles.csv` | Design notes and operational context for assumed values. | Text documentation confirming user editability in future UI. |
| `marine_data_available` | **`DERIVED`** | Boolean | None | Pipeline derivation | Flag indicating whether marine wave data was successfully integrated. | Always `True` in processed table. |
| `marine_data_source` | **`DERIVED`** | String | None | Pipeline derivation | Identifies origin coordinate of marine wave features. | `'direct_route_coordinate'` (3 routes) or `'representative_open_water_point_4.20N_7.25E'` (Warri-Bonny). |

---

## Secondary Processed Datasets

### 1. `data/processed/nasa_power/nasa_monthly_climatology.csv`
Contains 48 rows (4 routes × 12 months) of climatological monthly averages for surface pressure, wind speed profiles (10m, 50m, min, max), ambient temperature, relative humidity, and solar radiation (GHI, DNI, PAR, LW).

### 2. `data/processed/marine/marine_monthly_climatology.csv`
Contains 48 rows (4 routes × 12 months) of monthly average maximum wave height, maximum wave period, and dominant wave direction derived strictly from non-null hindcast observations (2021-10-01 to 2024-12-24).

### 3. `data/processed/battery/battery_cycle_summary.csv`
Contains all 7,565 raw battery test cycles with parsed ISO timestamps (`timestamp`), chronologically sorted per cell, with numeric capacities, battery-specific reference capacities, and calculated SOH labels.

### 4. `data/processed/battery/battery_discharge_soh.csv`
Contains the 2,769 valid discharge cycles across 34 commercial Li-ion cells annotated with capacity and SOH degradation trajectory data.


---

## Stage 2D Pack Topology Reconciliation (2026-09-27)

All four ship type battery pack configurations in `data/reference/ship_profiles.csv`
were revised to make `battery_cell_config`, `nominal_voltage_v`, and
`battery_pack_capacity_kwh` mutually consistent using NASA-verified cell parameters:

- **Cell nominal voltage:** 3.6 V (NASA 18650 specification, immutable)
- **Cell nominal capacity:** 2.0 Ah (NASA discharge dataset, immutable)
- **Series count (S):** kept at 96 for all ship types
- **Fix:** solved for parallel count P using the stated kWh design target
- **Corrected bus voltage:** 96 × 3.6 = 345.6 V for all ship types

| Ship Type | Old Config | Old Voltage | Old kWh | New Config | New Voltage | Exact kWh |
|-----------|-----------|-------------|---------|-----------|-------------|-----------|
| Oil Service Boat | 96S120P | 400 V | 650 | 96S940P | 345.6 V | 649.7280 |
| Fishing Trawler | 96S50P | 400 V | 250 | 96S362P | 345.6 V | 250.2144 |
| Surfer Boat | 96S30P | 400 V | 150 | 96S217P | 345.6 V | 149.9904 |
| Tanker Ship | 96S250P | 800 V | 1200 | 96S1736P | 345.6 V | 1199.9232 |

See `docs/pack_assumption_audit_report.md` for the original inconsistency findings.
The 400 V and 800 V labels were nominal bus class labels, not computed from the 96S cell
topology. The kWh design targets (operational requirements) are preserved; only the
series/parallel count encoding is corrected.

---

## Phase 3 Integration: Fuel Unit, OPEX, and CII Contract Conventions

### 1. Fuel Consumption Physical Unit
- **Status:** **Evidence Level B — Strongly Inferred as Liters (L) per voyage.**
- **Provenance:** The original raw source ship_fuel_efficiency.csv and DATASET_EXPLANATION.txt did not explicitly annotate a physical unit for uel_consumption.
- **Engineering Justification:**
  - Empirical ratio: $\\frac{\\text{CO2\\_emissions (kg)}}{\\text{fuel\\_consumption}} \\approx 2.750\\text{ kg CO}_2\\text{/L}$ for Marine Diesel and $\\approx 2.754\\text{ kg CO}_2\\text{/L}$ for HFO, matching standard IMO volumetric diesel combustion factors (.206\\text{ kg CO}_2\\text{/kg} \\times 0.858\\text{ kg/L} = 2.750\\text{ kg CO}_2\\text{/L}$) within 0.1%.
  - Vessel power plausibility: Mean voyage consumption (,619\\text{ L}$ for OSV, ,780\\text{ L}$ for Tanker) aligns with standard Specific Fuel Oil Consumption (–210\\text{ g/kWh}$) under typical operating loads (–45\\%$).
  - **Constraint:** This is an engineering inference, not an explicitly sourced unit.

### 2. OPEX Input Convention
\\text{OPEX}_{\\text{fuel}} = \\text{fuel\\_consumption\\_L} \\times \\text{fuel\\_price\\_per\\_litre\\_USD\\_per\\_L}
- uel_consumption: Liters (L) per voyage (strongly inferred).
- uel_price_per_litre: USD / Litre (explicitly sourced from ship_profiles.csv).
- **Operational Status:** Operationally usable for Phase 3 dispatch because the inferred volumetric unit matches the explicitly defined price denominator, while preserving the caveat that the underlying fuel unit remains an engineering inference.

### 3. CII (Carbon Intensity Indicator) Input Contract
\\text{Attained CII} = \\frac{\\text{predicted\\_CO2\\_kg} \\times 1000}{\\text{dwt\\_tonnes} \\times \\text{distance\\_nm}} \\quad \\left[\\frac{\\text{g CO}_2}{\\text{dwt} \\cdot \\text{nm}}\\right]
- **Governing Standard:** IMO Resolution MEPC.352(78).
- **Inputs:**
  - predicted_CO2_kg: Total voyage $\\text{CO}_2$ emissions in $\\text{kg CO}_2$ (converted to grams via $\\times 1000$).
  - dwt_tonnes: Deadweight tonnage in metric tonnes (from ship_profiles.csv).
  - distance_nm: Voyage distance in nautical miles (from route/voyage specification).
- **Decoupling from Fuel-Unit Ambiguity:** The CII calculation from predicted_CO2 is based directly on $\\text{CO}_2$ mass; therefore, the raw fuel-volume ambiguity does not enter the final CII formula once predicted_CO2 is available (though the upstream fuel-to-$\\text{CO}_2$ relationship reflects the volumetric inference).
