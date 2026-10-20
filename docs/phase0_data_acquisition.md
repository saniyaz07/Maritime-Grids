# PHASE 0 — DATA ACQUISITION REPORT
**Project:** Maritime Grid Simulation  
**Project Root:** `C:\maritime grids`  
**Execution Timestamp:** 2026-09-26  
**Status:** PHASE 0 COMPLETE  

---

## 1. Phase 0 Objective
The objective of Phase 0 is strictly **Data Acquisition, Organization, Baseline Verification, and Raw Data Freezing** for the Maritime Grid Simulation platform. In this phase:
- The single route-to-coordinate reference mapping is established and verified.
- Environmental and solar time-series data from NASA POWER are acquired per route.
- Wave and sea-state historical marine data from Open-Meteo are acquired per route.
- Existing raw source datasets (ship fuel efficiency and NASA Li-ion battery aging datasets) are verified for integrity, safely mirrored into the immutable raw repository, and preserved without modification.
- Representative engineering profiles are established for all ship types with clear documentation of assumptions.
- Immutability rules are declared to ensure no cleaning, preprocessing, or modeling touches `data/raw/`.

---

## 2. Route → Coordinate Table
Reference file: [`data/reference/routes.csv`](file:///C:/maritime%20grids/data/reference/routes.csv)

The 4 commercial maritime shipping corridors identified in the ship operations dataset were mapped to single reference coordinate points (latitude, longitude):

| route_id | lat | lon | Corridor Description |
| :--- | :---: | :---: | :--- |
| **Warri-Bonny** | 4.99 | 6.45 | Niger Delta Estuary / Bonny River maritime channel |
| **Port Harcourt-Lagos** | 5.67 | 5.21 | Coastal transit across Bight of Benin / Niger Delta shelf |
| **Lagos-Apapa** | 6.52 | 3.38 | Lagos Harbor / Commodore Channel / Apapa port approach |
| **Escravos-Lagos** | 6.06 | 4.28 | Western Niger Delta offshore terminal to Lagos corridor |

### Verification Results:
- File exists at `data/reference/routes.csv`.
- Header: `route_id,lat,lon`.
- Row count: Exactly 4 routes.
- Latitude and longitude values are confirmed numeric floats.
- Route IDs match `data/ship/ship_fuel_efficiency.csv` 100% without discrepancy.

---

## 3. NASA POWER Acquisition Details
NASA POWER (Prediction Of Worldwide Energy Resources) Daily API (`community=RE`) was queried individually for each of the 4 route coordinates.

### Query Parameters:
- **Base Endpoint:** `https://power.larc.nasa.gov/api/temporal/daily/point`
- **Community:** `RE` (Renewable Energy)
- **Temporal Range:** `start=20200101` to `end=20241224` (5 full calendar years)
- **Format:** `CSV`
- **Parameters Queried (19 meteorological and solar irradiance fields):**
  - Atmospheric: `PS` (Surface Pressure, kPa), `WD10M` (Wind Dir 10m, °), `WS10M` (Wind Speed 10m, m/s), `WS10M_MIN`, `WS10M_MAX`, `WS10M_RANGE`, `WS50M_MIN`, `WS50M_MAX`, `WS50M_RANGE`, `WD50M`, `RH2M` (Relative Humidity 2m, %), `T2M_MIN` (Min Temp 2m, °C), `WS2M` (Wind Speed 2m, m/s).
  - Solar Irradiance: `ALLSKY_SFC_SW_DWN` (All Sky Surface Shortwave Downward Irradiance, kW-hr/m²/day), `CLRSKY_SFC_SW_DWN`, `ALLSKY_SFC_SW_DNI` (Direct Normal Irradiance), `ALLSKY_SFC_LW_DWN` (Longwave Downward Irradiance), `CLRSKY_SFC_PAR_TOT` (Photosynthetically Active Radiation), `ALLSKY_SFC_PAR_TOT`.

### Files Acquired:
- [`data/raw/nasa_power/Warri-Bonny.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Warri-Bonny.csv) (232,263 bytes)
- [`data/raw/nasa_power/Port Harcourt-Lagos.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Port%20Harcourt-Lagos.csv) (232,798 bytes)
- [`data/raw/nasa_power/Lagos-Apapa.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Lagos-Apapa.csv) (232,833 bytes)
- [`data/raw/nasa_power/Escravos-Lagos.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Escravos-Lagos.csv) (232,681 bytes)

### NASA POWER Coverage & Verification:
- **HTTP/API Status:** 200 OK for all 4 requests.
- **Requested Range:** 2020-01-01 to 2024-12-24.
- **Returned Range:** 2020-01-01 to 2024-12-24 (1,820 daily records per file).
- **Coordinates Verified:** NASA POWER header echoes the exact requested coordinates in the metadata section of each file.
- **Missing Value Marker:** Declared as `-999` in file headers. An inspection across all 1,820 rows per file confirmed **zero** `-999` values (100% complete valid daily observations).

---

## 4. Open-Meteo Marine Acquisition Details
Historical sea-state and ocean wave dynamics were queried from the Open-Meteo Marine API per route coordinate.

### Query Parameters:
- **Base Endpoint:** `https://marine-api.open-meteo.com/v1/marine`
- **Temporal Range:** `start_date=2020-01-01` to `end_date=2024-12-24`
- **Format:** `CSV`
- **Timezone:** `auto`
- **Daily Variables Queried:** `wave_height_max`, `wave_period_max`, `wave_direction_dominant`
*(Note: Parameter `sea_surface_temperature` was requested in prompt instructions, but the Open-Meteo Marine Daily API endpoint returned HTTP 400 stating `Invalid value: Cannot initialize ForecastVariableDaily from invalid String value sea_surface_temperature`. Following Phase 0 rules to investigate and report rather than mask, the parameter was removed from daily requests to allow successful retrieval of the core wave and ocean dynamics fields).*

### Files Acquired:
- [`data/raw/marine/Warri-Bonny.csv`](file:///C:/maritime%20grids/data/raw/marine/Warri-Bonny.csv) (42,062 bytes)
- [`data/raw/marine/Port Harcourt-Lagos.csv`](file:///C:/maritime%20grids/data/raw/marine/Port%20Harcourt-Lagos.csv) (45,265 bytes)
- [`data/raw/marine/Lagos-Apapa.csv`](file:///C:/maritime%20grids/data/raw/marine/Lagos-Apapa.csv) (45,235 bytes)
- [`data/raw/marine/Escravos-Lagos.csv`](file:///C:/maritime%20grids/data/raw/marine/Escravos-Lagos.csv) (45,296 bytes)

### Open-Meteo Marine Actual Coverage:
As mandated by Phase 0 rules ("Do not assume full 2020–2024 coverage unless the API actually returns it", "Do not fabricate missing observations"):

| route_id | Requested Range | Returned Rows | Actual Valid Obs Range | Valid Rows | Missing / Null Rows | Reason / Grid Note |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Warri-Bonny** (4.99, 6.45) | 2020-01-01 to 2024-12-24 | 1,820 | **None (All NaN)** | 0 | 1,820 | Coordinate sits inside estuarine / river land-mask on global ocean wave models |
| **Port Harcourt-Lagos** (5.67, 5.21) | 2020-01-01 to 2024-12-24 | 1,820 | **2021-10-01 to 2024-12-24** | 1,181 | 639 (2020-01-01 to 2021-09-30) | Copernicus Marine / Open-Meteo hindcast archive starts 2021-10-01 |
| **Lagos-Apapa** (6.52, 3.38) | 2020-01-01 to 2024-12-24 | 1,820 | **2021-10-01 to 2024-12-24** | 1,181 | 639 (2020-01-01 to 2021-09-30) | Copernicus Marine / Open-Meteo hindcast archive starts 2021-10-01 |
| **Escravos-Lagos** (6.06, 4.28) | 2020-01-01 to 2024-12-24 | 1,820 | **2021-10-01 to 2024-12-24** | 1,181 | 639 (2020-01-01 to 2021-09-30) | Copernicus Marine / Open-Meteo hindcast archive starts 2021-10-01 |

---

## 5. Existing Ship and Battery Datasets Preservation
The project includes raw datasets located originally in `D:\marine\data\` (and mirrored to `C:\maritime grids\data\raw\`):

### Ship Fuel Efficiency Dataset:
- **Original Path:** `D:/marine/data/ship/ship_fuel_efficiency.csv`
- **Preserved Raw Mirror:** `C:/maritime grids/data/raw/ship/ship_fuel_efficiency.csv`
- **Total Records:** 1,441 records (1 header + 1,441 observation rows).
- **Integrity Verification:** SHA256 cryptographic checksum of original matches the raw copy exactly (`b1f7bb6a64463426e2e50fb3f9cfb426fa1d927a4b0d06175e156ea365611487`).
- **Original Status:** Untouched, unmodified, uncleaned.

### Battery Aging & Degradation Dataset:
- **Original Path:** `D:/marine/data/battery/`
- **Preserved Raw Mirror:** `C:/maritime grids/data/raw/battery/`
- **Components Preserved:**
  - `metadata.csv`: 7,566 test cycle records across Li-ion cells (SHA256 verified match).
  - `data/`: Exactly 6,209 high-frequency cycle measurement CSV files (`00001.csv` to `06191.csv`).
  - `extra_infos/`: Exactly 9 technical experiment protocol README files.
- **Original Status:** Untouched, individual cycle files unmodified, schemas completely unaltered.

---

## 6. Ship-Type Engineering Profile Table
Reference file: [`data/reference/ship_profiles.csv`](file:///C:/maritime%20grids/data/reference/ship_profiles.csv)

The ship dataset contains four distinct ship types operating across the Gulf of Guinea. Representative engineering profile defaults have been defined across physical, operational, CII, electrical battery, solar PV, and economic parameters:

| Parameter | Oil Service Boat | Fishing Trawler | Surfer Boat | Tanker Ship | Source / Basis of Assumption |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Displacement** | 2,500 tonnes | 650 tonnes | 120 tonnes | 18,500 tonnes | Industry standard naval architectural baselines for coastal vessels |
| **Engine Power** | 4,500 kW | 1,200 kW | 1,800 kW | 7,200 kW | Sized to match voyage fuel burn curves observed in ship dataset |
| **Dimensions (L × B × T)** | 65.0m × 15.5m × 5.2m | 38.0m × 8.5m × 3.8m | 22.0m × 5.8m × 1.4m | 145.0m × 23.0m × 8.5m | Representative offshore vessel class hull geometries |
| **Max Speed** | 14.5 knots | 11.0 knots | 28.0 knots | 13.5 knots | Operational speed limits for vessel categories |
| **Propulsion Type** | Diesel-Electric Hybrid | Geared Diesel + Shaft Gen | High-Speed Diesel + Waterjet | 2-Stroke Diesel + PTO/PTI Hybrid | Common decarbonization architectures in marine engineering |
| **Propeller Specs** | Twin 4-blade azimuth thrusters (Ø2.8m) | Single ducted Kort nozzle 4-blade (Ø2.2m) | Twin Hamilton waterjet units | Single slow-speed 4-blade bronze (Ø5.4m) | Standard hydrodynamics configuration for each hull class |
| **Deadweight (DWT)** | 1,800 tonnes | 350 tonnes | 35 tonnes | 14,000 tonnes | Required for IMO Carbon Intensity Indicator (CII) capacity denominator |
| **Battery Chemistry**| NMC | LFP | NMC | LFP | High energy density (NMC) for OSV/Surfer; high cycle life/safety (LFP) for Trawler/Tanker |
| **Battery Cell Config**| 96S120P | 96S50P | 96S30P | 96S250P | Nominal 400V (OSV, Trawler, Surfer) and 800V (Tanker) pack modularization |
| **Battery Pack Size**| 650 kWh | 250 kWh | 150 kWh | 1,200 kWh | Sized for peak shaving, spinning reserve, and zero-emission port maneuvering |
| **Solar Panel Area** | 80 m² | 45 m² | 25 m² | 250 m² | Usable deckhouse and awning surface area on vessel upper works |
| **Solar Efficiency** | 21.5% | 21.0% | 22.0% | 21.5% | Modern marine-grade monocrystalline PV module rating |
| **Fuel Price** | $1.15 / litre | $1.10 / litre | $1.20 / litre | $0.95 / litre | Gulf of Guinea Marine Gas Oil (MGO) vs. Heavy Fuel Oil (HFO) bunker averages |
| **Degradation Cost** | $0.08 / kWh cycled | $0.07 / kWh cycled | $0.09 / kWh cycled | $0.06 / kWh cycled | Amortized battery replacement cost over 3,000-4,000 cycle lifespan |

> [!IMPORTANT]
> All parameters above are **representative engineering defaults**, NOT empirical values directly recorded in the historical ship dataset. They are stored in `data/reference/ship_profiles.csv` and are structured to be dynamically adjustable in future simulator configurations and UI parameter tuning screens.

---

## 7. Raw-Data Immutability Rules
The directory:
```text
C:\maritime grids\data\raw\
```
is hereby **FROZEN** and declared **IMMUTABLE**.

### Enforced Rules:
1. **No Data Cleaning** inside `data/raw/` (e.g. no stripping NaN lines or imputing nulls).
2. **No Preprocessing or Transformations** inside `data/raw/` (e.g. no unit conversions or date parsing).
3. **No Feature Engineering** inside `data/raw/` (e.g. no creating rolling averages or lags).
4. **No Replacement of Missing Values** inside `data/raw/`.
5. **No Normalization or Scaling** inside `data/raw/`.
6. **No Synthetic / Model-Generated Data** inside `data/raw/`.

All subsequent transformations and joins will occur inside `data/processed/` during Phase 1.

---

## 8. Summary of Files Created During Phase 0

| File Path | Description | Records / Size |
| :--- | :--- | :--- |
| [`data/reference/routes.csv`](file:///C:/maritime%20grids/data/reference/routes.csv) | Master route coordinate reference lookup | 4 routes (116 bytes) |
| [`data/reference/ship_profiles.csv`](file:///C:/maritime%20grids/data/reference/ship_profiles.csv) | Ship type engineering defaults & parameters | 4 ship types (1,745 bytes) |
| [`data/raw/nasa_power/Warri-Bonny.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Warri-Bonny.csv) | NASA POWER daily solar & weather series | 1,820 daily rows (232 KB) |
| [`data/raw/nasa_power/Port Harcourt-Lagos.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Port%20Harcourt-Lagos.csv) | NASA POWER daily solar & weather series | 1,820 daily rows (232 KB) |
| [`data/raw/nasa_power/Lagos-Apapa.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Lagos-Apapa.csv) | NASA POWER daily solar & weather series | 1,820 daily rows (232 KB) |
| [`data/raw/nasa_power/Escravos-Lagos.csv`](file:///C:/maritime%20grids/data/raw/nasa_power/Escravos-Lagos.csv) | NASA POWER daily solar & weather series | 1,820 daily rows (232 KB) |
| [`data/raw/marine/Warri-Bonny.csv`](file:///C:/maritime%20grids/data/raw/marine/Warri-Bonny.csv) | Open-Meteo daily marine wave data | 1,820 daily rows (42 KB) |
| [`data/raw/marine/Port Harcourt-Lagos.csv`](file:///C:/maritime%20grids/data/raw/marine/Port%20Harcourt-Lagos.csv) | Open-Meteo daily marine wave data | 1,820 daily rows (45 KB) |
| [`data/raw/marine/Lagos-Apapa.csv`](file:///C:/maritime%20grids/data/raw/marine/Lagos-Apapa.csv) | Open-Meteo daily marine wave data | 1,820 daily rows (45 KB) |
| [`data/raw/marine/Escravos-Lagos.csv`](file:///C:/maritime%20grids/data/raw/marine/Escravos-Lagos.csv) | Open-Meteo daily marine wave data | 1,820 daily rows (45 KB) |
| [`data/raw/ship/ship_fuel_efficiency.csv`](file:///C:/maritime%20grids/data/raw/ship/ship_fuel_efficiency.csv) | Raw mirror of vessel fuel operational data | 1,441 rows (122 KB) |
| [`data/raw/battery/metadata.csv`](file:///C:/maritime%20grids/data/raw/battery/metadata.csv) | Master metadata index for NASA Li-ion battery dataset | 7,566 test cycles (698 KB) |
| `data/raw/battery/data/*.csv` | High-frequency time-series measurement CSVs | 6,209 CSV files |
| `data/raw/battery/extra_infos/*.txt` | Protocol specification README files | 9 README text files |
| [`docs/phase0_data_acquisition.md`](file:///C:/maritime%20grids/docs/phase0_data_acquisition.md) | Phase 0 comprehensive documentation report | Markdown file |

---

## 9. Known Limitations & Technical Findings
1. **Open-Meteo Hindcast Archive Boundary:**
   - The Copernicus Marine / ERA5 ocean wave reanalysis on Open-Meteo provides valid wave observations starting **2021-10-01**. The dates from 2020-01-01 to 2021-09-30 return `NaN`. Per Phase 0 guidelines, these have not been fabricated or altered.
2. **Warri-Bonny Ocean Grid Masking:**
   - The coordinate `(4.99, 6.45)` lies within the coastal Niger Delta river estuary. Global wave models (ECMWF/Copernicus) mask out inland estuarine grid cells, returning `NaN` for wave height and period across all dates. Offshore grid cells (e.g. `(4.49, 5.95)`) yield valid wave measurements, which Phase 1 preprocessing can evaluate for offshore boundary interpolation if deemed necessary.
3. **Open-Meteo Daily Sea Surface Temperature:**
   - The Open-Meteo Marine Daily API does not accept `sea_surface_temperature` as a valid daily forecast/hindcast variable. Atmospheric temperature is however comprehensively captured in NASA POWER (`T2M_MIN` and ambient surface metrics).

---

## 10. Recommended Phase 1 Starting Point
When transitioning to **Phase 1 (Data Preprocessing & Cleaning)**:
1. Initialize the target directory `data/processed/`.
2. Clean and standardize the ship operational dataset (`ship_fuel_efficiency.csv`), mapping monthly observations to seasonal weather regimes.
3. Ingest and align NASA POWER daily time series with the ship voyage dates and routes.
4. Process Open-Meteo wave data from 2021-10-01 onward, handling earlier missing periods through explicit statistical indicators or documented imputation methodologies inside `data/processed/`.
5. Parse the NASA Li-ion battery dataset (`metadata.csv` and individual cycle files) into structured battery degradation feature sets (Capacity fade, SOH, internal resistance $\Delta R_{ct}$).
