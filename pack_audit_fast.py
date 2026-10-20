"""
pack_audit_fast.py — Targeted READ-ONLY pack assumption audit.
Searches only project code and docs (19 files). Skips raw data.
No training. No modification.
"""

import os, re, json, time
from pathlib import Path

PROJECT = Path(".")

TARGET_FILES = [
    "b41_check.py",
    "docs/model_c_soc_training_report.md",
    "docs/model_c_soh_audit_report.md",
    "docs/model_c_soh_metrics.json",
    "docs/model_c_soh_training_report.md",
    "docs/phase0_data_acquisition.md",
    "docs/phase1_data_engineering.md",
    "docs/phase2_metrics.json",
    "docs/phase2_modeling_report.md",
    "docs/phase3_output_contract.json",
    "phase2_pipeline.py",
    "soh_audit_D_to_J.py",
    "soh_verify.py",
    "stage2a_weather.py",
    "stage2b_fuel.py",
    "stage2c_soc_preprocessing.py",
    "stage2c_soh_training.py",
    "train_soc_lstm.py",
]

# Also check the data_dictionary and ship profiles (processed, not raw)
EXTRA_FILES = [
    "data/processed/data_dictionary.md",
    "data/reference/ship_profiles.csv",
    "data/processed/battery/soh_split_summary.json",
]
ALL_FILES = TARGET_FILES + EXTRA_FILES

PATTERNS = {
    "96S250P":      re.compile(r'96[Ss]250[Pp]', re.I),
    "PACK_SERIES":  re.compile(r'PACK_SERIES|pack_series', re.I),
    "PACK_PARALLEL":re.compile(r'PACK_PARALLEL|pack_parallel', re.I),
    "series_96":    re.compile(r'\b96\b.*[Ss]eries|[Ss]eries.*\b96\b|[Ss]eries\s*=\s*96', re.I),
    "parallel_250": re.compile(r'\b250\b.*[Pp]arallel|[Pp]arallel.*\b250\b|[Pp]arallel\s*=\s*250', re.I),
    "1200":         re.compile(r'\b1[,_\s]?200\b'),
    "1200kWh":      re.compile(r'1[,_\s]?200\s*k[Ww][Hh]|1200\s*k[Ww][Hh]', re.I),
    "1200000":      re.compile(r'\b1[,_]?200[,_]?000\b|\b1200000\b'),
    "1p2e6":        re.compile(r'1\.2\s*[eE]6|1\.2\s*\*\s*10.*6'),
    "NOMINAL_CAP_2":re.compile(r'NOMINAL_CAP\s*=\s*2|nominal_cap\s*=\s*2|cell_cap.*=.*2\.0|2\.0.*[Aa][Hh]', re.I),
    "2p0_Ah_ctx":   re.compile(r'\b2\.0\b|\b2\s*[Aa][Hh]'),
    "CELL_VOLT_3p6":re.compile(r'3\.6|CELL.*VOLT|cell_voltage', re.I),
    "pack_energy":  re.compile(r'pack.*energy|energy.*pack|pack.*kWh|kWh.*pack', re.I),
    "pack_soh":     re.compile(r'pack.*soh|soh.*pack|pack.*SOH|SOH.*pack', re.I),
    "pack_soc":     re.compile(r'pack.*soc|soc.*pack|pack.*SOC|SOC.*pack', re.I),
    "pack_voltage": re.compile(r'pack.*volt|volt.*pack', re.I),
    "pack_capacity":re.compile(r'pack.*capac|capac.*pack', re.I),
    "pack_calc":    re.compile(r'PACK_|pack_|series_cell|parallel_cell|cell.to.pack|'
                               r'usable_energy|remaining_energy|pack_nominal', re.I),
    "kWh_generic":  re.compile(r'\bkWh\b|\bkwh\b', re.I),
    "345p6":        re.compile(r'\b345\.6\b'),
    "172p8":        re.compile(r'\b172\.8\b'),
    "500Ah":        re.compile(r'\b500\s*[Aa][Hh]\b'),
    "13p89":        re.compile(r'\b13\.8[0-9]\b'),
}

def read_text(path):
    for enc in ('utf-8', 'utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return Path(path).read_text(encoding=enc, errors='replace')
        except Exception:
            pass
    return None

# ── search ───────────────────────────────────────────────────────────────────
hits = {k: [] for k in PATTERNS}
files_inspected = 0
missing_files = []

for fpath in ALL_FILES:
    if not os.path.exists(fpath):
        missing_files.append(fpath)
        continue
    text = read_text(fpath)
    if text is None:
        continue
    files_inspected += 1
    lines = text.splitlines()
    for lno, line in enumerate(lines, 1):
        for name, pat in PATTERNS.items():
            if pat.search(line):
                hits[name].append((fpath, lno, line.strip()))

print(f"Files inspected : {files_inspected}")
print(f"Files missing   : {missing_files}")
print()

# ── print all hits ────────────────────────────────────────────────────────────
print("=" * 72)
print("ALL PATTERN HITS")
print("=" * 72)
total_hits = 0
for name, matches in hits.items():
    if matches:
        print(f"\n{'─'*60}")
        print(f"PATTERN: {name}  ({len(matches)} hits)")
        print(f"{'─'*60}")
        for fpath, lno, line in matches:
            print(f"  {fpath}:{lno}  |  {line[:130]}")
            total_hits += 1
    else:
        print(f"\nPATTERN: {name}  — NO HITS")

print(f"\n{'='*72}")
print(f"TOTAL RELEVANT HITS: {total_hits}")

# ── frozen model integrity check ──────────────────────────────────────────────
print("\n" + "=" * 72)
print("FROZEN MODEL SIZE CHECK")
print("=" * 72)
frozen = [
    "models/weather_final.joblib",
    "models/fuel_xgb.joblib",
    "models/battery_soc_lstm.pt",
    "models/battery_soh_final.joblib",
]
for fp in frozen:
    p = Path(fp)
    if p.exists():
        s = p.stat()
        mt = time.strftime('%Y-%m-%d %H:%M', time.localtime(s.st_mtime))
        print(f"  OK      {fp:<45} {s.st_size:>10,} B   mtime={mt}")
    else:
        print(f"  MISSING {fp}")

# ── mathematical consistency ──────────────────────────────────────────────────
print("\n" + "=" * 72)
print("MATHEMATICAL CONSISTENCY CHECK")
print("=" * 72)
S, P, Vc, Cc = 96, 250, 3.6, 2.0
Vp = S * Vc
Cp = P * Cc
Ep = Vp * Cp / 1000.0
req = 1_200_000 / (S * P * Vc)
print(f"  96 x 3.6 V            = {Vp:.1f} V  (pack voltage)")
print(f"  250 x 2.0 Ah          = {Cp:.1f} Ah (pack capacity)")
print(f"  {Vp:.1f} x {Cp:.1f} / 1000 = {Ep:.1f} kWh (derived pack energy)")
print(f"  Project assumption    = 1200 kWh")
print(f"  Ratio 1200/{Ep:.1f}     = {1200/Ep:.4f}x")
print(f"  Cell Ah for 1200 kWh  = 1,200,000 / (96 x 250 x 3.6) = {req:.2f} Ah")
print(f"  Consistent?           NO — 2.0 Ah cells yield {Ep:.1f} kWh, not 1200 kWh")
