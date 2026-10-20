# PHASE 1 — DATA ENGINEERING VALIDATION REPORT
**Project:** Maritime Grid Simulation  
**Project Root:** `C:\maritime grids`  
**Execution Timestamp:** 2026-09-26  
**Status:** PHASE 1 COMPLETE — WAITING FOR REVIEW  

---

## 1. Executive Summary & Objective
Phase 1 (Data Engineering) of the Maritime Grid Simulation platform systematically validates, cleans, transforms, and combines the raw data assets acquired during Phase 0 into structured, leak-free, analysis-ready datasets under `data/processed/`.

### Core Highlights:
- **Zero Raw Data Mutation:** All operations read from `data/raw/` as read-only source-of-truth. No files in `data/raw/` were modified, overwritten, or deleted.
- **Warri-Bonny Marine Resolution:** Candidate 1 `(4.20° N, 7.25° E)` was successfully tested and selected as a representative open-water sampling point, yielding 1,181 valid daily wave observations matching the Copernicus Marine archive window. The official reference route coordinate in `data/reference/routes.csv` remains strictly untouched at `(4.99° N, 6.45° E)`.
- **Climatological Join Solution:** Because the ship dataset records operational month without a calendar year, 5-year NASA POWER meteorological/solar climatology (2020–2024) and 3.25-year Open-Meteo ocean wave climatology (2021–2024) were constructed by `[route_id, month]`.
- **Battery SOH Trajectories:** 7,565 test cycles across 34 commercial 18650 Li-ion cells were chronologically sorted using robust sub-second timestamp parsing, generating SOH labels for all 2,769 valid discharge cycles using cell-specific initial capacities.
- **Master Training Table Integrity:** All 1,440 valid vessel voyage records from `ship_fuel_efficiency.csv` were preserved through sequential left joins without row duplication, record drops, or null values across all 47 columns.

---

## 2. Ship Dataset Validation
**Source File:** `data/raw/ship/ship_fuel_efficiency.csv`

| Metric / Check | Specification / Validation Rule | Actual Result | Status |
| :--- | :--- | :--- | :--- |
| **Total Lines in File** | CSV file lines | 1,441 lines (1 header line + 1,440 data lines) | **PASSED** |
| **Observation Row Count** | Expected data rows | 1,440 rows (120 ships × 12 calendar months) | **PASSED** |
| **Retained Row Count** | Valid records retained in processed table | 1,440 rows (0 records removed) | **PASSED** |
| **Missing Values** | Null / NaN count | 0 missing values across all columns | **PASSED** |
| **Duplicate Records** | Duplicate vessel voyages | 0 duplicate records (`ship_id + month` is unique) | **PASSED** |
| **Distance Traveled** | Rule: `distance > 0` | Min: 20.08, Max: 498.55, Mean: 147.28 | **PASSED** |
| **Engine Efficiency** | Rule: `0 <= engine_efficiency <= 100` | Min: 70.01%, Max: 94.98%, Mean: 82.50% | **PASSED** |
| **Fuel Consumption** | Rule: `fuel_consumption > 0` | Min: 237.88, Max: 24,648.52, Mean: 4,778.36 | **PASSED** |
| **CO₂ Emissions** | Empirical mass emitted (kg) | Min: 615.68, Max: 71,871.21, Mean: 13,447.88 | **PASSED** |
| **Ship Categories** | Rule: `ship_type ∈ {Oil Service Boat, Fishing Trawler, Surfer Boat, Tanker Ship}` | 4 unique categories present; 0 invalid categories | **PASSED** |
| **Route Identifiers** | Rule: `route_id ∈ routes.csv` | Exactly matches the 4 routes in `routes.csv` | **PASSED** |

> [!NOTE]
> **Row Count Reconciliation:** Phase 0 documentation referenced 1,441 records (reflecting the 1,441 lines in the raw CSV). Validation confirms that line 1 is the header row, and lines 2–1,441 comprise exactly 1,440 valid operational voyage observations (120 unique vessels from NG001 to NG120, each observed across all 12 calendar months). Exactly 1,440 valid records were loaded, validated, and retained in the master training table (0 dropped, 0 duplicated).

---

## 3. NASA POWER Processing & Validation
**Source Directory:** `data/raw/nasa_power/`  
**Processed Target:** `data/processed/nasa_power/`

### Processing Performed:
1. **Dynamic Header Detection:** Programmatically located the line beginning with `YEAR,` (line index 27) across all route files to ensure robustness against variable metadata lengths.
2. **Sentinel Conversion:** Evaluated all columns for the NASA sentinel missing-value marker `-999`. Confirmed 0 instances of `-999` across all files.
3. **Date Standardization:** Parsed `YEAR`, `MO`, `DY` into an ISO-8601 date string `date` (`YYYY-MM-DD`).
4. **Wind Profile Derivation:** Calculated `WS50M` bounds and preserved `WS10M`, `WS10M_MAX`, `WS10M_MIN`, `WS50M_MAX`, `WS50M_MIN`.
5. **Solar Units Verification:** Verified CERES SYN1deg downward shortwave irradiance (`ALLSKY_SFC_SW_DWN`, `CLRSKY_SFC_SW_DWN`, `ALLSKY_SFC_SW_DNI`) in units of `kW-hr/m²/day`. Daily values represent average daily irradiation energy per unit area. Taking the mean over all days in each calendar month across 2020–2024 yields the typical daily solar insolation rate for that month.

### Validation Summary by Route:

| Route ID | Coordinates (lat, lon) | Raw Rows | Cleaned Rows | Date Range | Sentinel / Missing Count | Cleaned File Path |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Warri-Bonny** | 4.99, 6.45 | 1,820 | 1,820 | 2020-01-01 → 2024-12-24 | 0 | [`data/processed/nasa_power/Warri-Bonny.csv`](file:///C:/maritime%20grids/data/processed/nasa_power/Warri-Bonny.csv) |
| **Port Harcourt-Lagos** | 5.67, 5.21 | 1,820 | 1,820 | 2020-01-01 → 2024-12-24 | 0 | [`data/processed/nasa_power/Port%20Harcourt-Lagos.csv`](file:///C:/maritime%20grids/data/processed/nasa_power/Port%20Harcourt-Lagos.csv) |
| **Lagos-Apapa** | 6.52, 3.38 | 1,820 | 1,820 | 2020-01-01 → 2024-12-24 | 0 | [`data/processed/nasa_power/Lagos-Apapa.csv`](file:///C:/maritime%20grids/data/processed/nasa_power/Lagos-Apapa.csv) |
| **Escravos-Lagos** | 6.06, 4.28 | 1,820 | 1,820 | 2020-01-01 → 2024-12-24 | 0 | [`data/processed/nasa_power/Escravos-Lagos.csv`](file:///C:/maritime%20grids/data/processed/nasa_power/Escravos-Lagos.csv) |

### NASA Monthly Climatology Table:
- **File:** [`data/processed/nasa_power/nasa_monthly_climatology.csv`](file:///C:/maritime%20grids/data/processed/nasa_power/nasa_monthly_climatology.csv)
- **Dimensions:** Exactly 48 rows (4 routes × 12 calendar months).
- **Aggregations:** Mean computed across 2020–2024 for `PS`, `WS10M`, `WS10M_MAX`, `WS10M_MIN`, `WS50M_MAX`, `WS50M_MIN`, `RH2M`, `T2M_MIN`, `ALLSKY_SFC_SW_DWN`, `CLRSKY_SFC_SW_DWN`, `ALLSKY_SFC_SW_DNI`, `ALLSKY_SFC_LW_DWN`, `ALLSKY_SFC_PAR_TOT`, `CLRSKY_SFC_PAR_TOT`.

---

## 4. Marine Data Processing & Warri-Bonny Resolution
**Source Directory:** `data/raw/marine/`  
**Processed Target:** `data/processed/marine/`

### 4.1 Warri-Bonny Open-Water Candidate Testing:
In Phase 0, the official coordinate `(4.99° N, 6.45° E)` for Warri-Bonny returned 100% NaN for wave data because global hydrodynamic ocean models mask out internal river channels and deltas as land.

Per Step 1.1 protocol, candidate open-water sampling points were evaluated in order:
1. **Candidate 1 (4.20° N, 7.25° E):** HTTP 200 OK. Returned **1,181 valid daily wave observations** spanning 2021-10-01 to 2024-12-24 (First valid: 1.24m on 2021-10-01; Last valid: 0.84m on 2024-12-24).
2. **Result:** Candidate 1 succeeded immediately and was selected. Further candidates were not required.
3. **Reference Route Preservation:** The official route coordinate in `data/reference/routes.csv` was preserved untouched at `(4.99, 6.45)`. Candidate 1 is strictly treated as a representative open-water offshore wave proxy for the corridor.

> [!IMPORTANT]
> **Domain Observation & Route Context:** The Warri–Bonny route transits largely through sheltered estuarine creeks, barrier islands, and the Bonny River channel rather than open ocean. Consequently, open-ocean swell and wave dynamics are substantially attenuated in reality and may be less governing for vessel resistance on this route than wind and tidal currents. Open-Meteo marine wave data for Warri–Bonny is therefore designated as **supplementary proxy data**.

### 4.2 Historical Window Harmonization:
- **Copernicus Marine Archive Window:** 2021-10-01 to 2024-12-24 (3.25 years; 1,181 valid daily rows per route).
- **NASA POWER Window:** 2020-01-01 to 2024-12-24 (5.00 years; 1,820 daily rows per route).
- **Handling:** Prior to 2021-10-01, wave models do not provide hindcasts in this API; these rows were discarded from daily cleaned files rather than fabricating synthetic observations. Climatological monthly means represent average wave conditions during the available 3.25-year hindcast window.

### Validation Summary by Route:

| Route ID | Selected Marine Coordinate | Valid Daily Obs Range | Valid Rows | Climatology Months | Output Path |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Port Harcourt-Lagos** | 5.67° N, 5.21° E (direct) | 2021-10-01 → 2024-12-24 | 1,181 | 12 | [`data/processed/marine/Port Harcourt-Lagos.csv`](file:///C:/maritime%20grids/data/processed/marine/Port%20Harcourt-Lagos.csv) |
| **Lagos-Apapa** | 6.52° N, 3.38° E (direct) | 2021-10-01 → 2024-12-24 | 1,181 | 12 | [`data/processed/marine/Lagos-Apapa.csv`](file:///C:/maritime%20grids/data/processed/marine/Lagos-Apapa.csv) |
| **Escravos-Lagos** | 6.06° N, 4.28° E (direct) | 2021-10-01 → 2024-12-24 | 1,181 | 12 | [`data/processed/marine/Escravos-Lagos.csv`](file:///C:/maritime%20grids/data/processed/marine/Escravos-Lagos.csv) |
| **Warri-Bonny** | 4.20° N, 7.25° E (open-water proxy) | 2021-10-01 → 2024-12-24 | 1,181 | 12 | [`data/processed/marine/Warri-Bonny.csv`](file:///C:/maritime%20grids/data/processed/marine/Warri-Bonny.csv) |

### Marine Monthly Climatology Table:
- **File:** [`data/processed/marine/marine_monthly_climatology.csv`](file:///C:/maritime%20grids/data/processed/marine/marine_monthly_climatology.csv)
- **Dimensions:** Exactly 48 rows (4 routes × 12 calendar months).
- **Aggregations:** Mean computed across valid hindcast dates for `wave_height_max` (m), `wave_period_max` (s), and `wave_direction_dominant` (°).

---

## 5. Battery Dataset Cleaning & SOH Trajectories
**Source File:** `data/raw/battery/metadata.csv` (7,565 cycle records across 34 commercial Li-ion cells)  
**Processed Target:** `data/processed/battery/`

### 5.1 Timestamp Parsing:
The raw metadata stores start times as MATLAB vectors formatted as strings (e.g. `[2010. 7. 21. 15. 0. 35.093]` or `[2.0100e+03 7.0000e+00 ...]`).
- Naive integer rounding failed on fractional seconds exceeding 59.5 (throwing out-of-bounds `second=60` errors).
- A robust regex parser extracting scientific and float representations combined with `pd.Timedelta(seconds=sec)` was implemented.
- **Failures:** Exactly **0 parsing failures** across all 7,565 records.

### 5.2 Capacity & SOH Computation:
- Total battery cells: 34 unique cells (`B0005` to `B0056`).
- Total discharge cycles: 2,794 cycles.
- Valid numeric capacity values: 2,769 cycles (25 cycles in cells `B0050` and `B0052` contain empty brackets `[]` representing unrecorded capacity).
- State-of-Health formulation:
  $$\text{SOH}_i = \frac{\text{Capacity}_i}{\text{Capacity}_{\text{first discharge}}}$$
  computed independently per cell using that specific battery's initial discharge capacity.
- Records receiving SOH labels: Exactly **2,769 records**.
- **Anomalous Baseline Observation:** Batteries `B0033`, `B0039`, and `B0041` commenced their test protocol with partial calibration discharge pulses (e.g., initial capacity of 0.068 Ah for `B0033` and 0.055 Ah for `B0041`). As subsequent full-depth discharge cycles measured nominal capacities (~1.2–1.5 Ah), raw mathematical ratios exceed 1.0 (reaching up to 27.5x). These known experimental artifacts are preserved faithfully with numeric capacity retained, enabling Phase 2 modelers to apply cell-specific filtering.

### 5.3 Impedance Complex-Number Parsing:
Electrochemical Impedance Spectroscopy (EIS) parameter extraction ($R_e$, $R_{ct}$) is **intentionally deferred** as permitted by Phase 1 instructions, since primary battery degradation and SOH feature modeling prioritize direct ampere-hour capacity fade.

### Processed Files Created:
1. [`data/processed/battery/battery_cycle_summary.csv`](file:///C:/maritime%20grids/data/processed/battery/battery_cycle_summary.csv) (7,565 rows): Full chronological log with parsed timestamps, test IDs, cycle types, and SOH labels.
2. [`data/processed/battery/battery_discharge_soh.csv`](file:///C:/maritime%20grids/data/processed/battery/battery_discharge_soh.csv) (2,769 rows): Filtered discharge training dataset for SOH regression.

---

## 6. Master Training Table Integration
**Target File:** [`data/processed/master_training_table.csv`](file:///C:/maritime%20grids/data/processed/master_training_table.csv)

### Join Architecture:
```text
ship_fuel_efficiency.csv (1,440 rows)
        │
        │ LEFT JOIN on [route_id, month]
        ↓
nasa_monthly_climatology.csv (48 rows)
        │
        │ LEFT JOIN on [route_id, month]
        ↓
marine_monthly_climatology.csv (48 rows)
        │
        │ LEFT JOIN on [ship_type]
        ↓
ship_profiles.csv (4 rows)
        │
        ↓
master_training_table.csv (1,440 rows, 47 columns)
```

### Join Validation & Quality Checks:
- **Input Ship Records:** 1,440
- **Final Master Table Records:** 1,440
- **Duplicate Records:** 0
- **Join Match Rate:** 100.0% (all 1,440 records matched NASA climatology, Marine climatology, and Ship Profiles).
- **Missing / Null Values:** **0 nulls across all 47 columns**.
- **Metadata Traceability:**
  - `marine_data_available`: `True` across all rows.
  - `marine_data_source`: `'direct_route_coordinate'` for 1,080 rows (75%); `'representative_open_water_point_4.20N_7.25E'` for 360 rows (25%, Warri-Bonny voyages).

---

## 7. Raw Data Immutability & Reference Verification
- **`data/raw/` Integrity:** Cryptographic SHA256 hashes of `data/raw/ship/ship_fuel_efficiency.csv` and `data/raw/battery/metadata.csv` match their original source datasets in `D:\marine\` with 100% precision.
- **Reference Table Integrity:**
  - `data/reference/routes.csv`: Preserves the 4 original route definitions without modification.
  - `data/reference/ship_profiles.csv`: Preserves all 4 vessel class engineering defaults.

---

## 8. Directory & File Manifest

```text
C:\maritime grids\
├── data\
│   ├── processed\
│   │   ├── master_training_table.csv            [1,440 rows x 47 cols]
│   │   ├── data_dictionary.md                   [Full schema documentation]
│   │   ├── nasa_power\
│   │   │   ├── Warri-Bonny.csv                  [1,820 daily cleaned rows]
│   │   │   ├── Port Harcourt-Lagos.csv          [1,820 daily cleaned rows]
│   │   │   ├── Lagos-Apapa.csv                  [1,820 daily cleaned rows]
│   │   │   ├── Escravos-Lagos.csv               [1,820 daily cleaned rows]
│   │   │   └── nasa_monthly_climatology.csv     [48 monthly climatology rows]
│   │   ├── marine\
│   │   │   ├── Warri-Bonny.csv                  [1,181 daily cleaned rows]
│   │   │   ├── Port Harcourt-Lagos.csv          [1,181 daily cleaned rows]
│   │   │   ├── Lagos-Apapa.csv                  [1,181 daily cleaned rows]
│   │   │   ├── Escravos-Lagos.csv               [1,181 daily cleaned rows]
│   │   │   ├── Warri-Bonny_representative_raw.csv [Preserved candidate response]
│   │   │   └── marine_monthly_climatology.csv   [48 monthly climatology rows]
│   │   └── battery\
│   │       ├── battery_cycle_summary.csv        [7,565 cycle records]
│   │       └── battery_discharge_soh.csv        [2,769 SOH discharge records]
│   └── raw\                                     [IMMUTABLE - UNTOUCHED]
└── docs\
    ├── phase0_data_acquisition.md               [Phase 0 audit log]
    └── phase1_data_engineering.md               [Phase 1 validation report]
```
