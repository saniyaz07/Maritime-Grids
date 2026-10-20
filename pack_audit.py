"""
pack_audit.py — READ-ONLY audit of pack assumptions.
No file modification. No model training. No waveform scan.
"""

import os, re, json
from pathlib import Path

PROJECT = Path(".")

# ── directories / extensions to skip ─────────────────────────────────────────
SKIP_DIRS  = {".git", "__pycache__", ".mypy_cache", "node_modules",
              ".ipynb_checkpoints", "data/raw"}  # skip raw NASA waveform dir
SKIP_EXTS  = {".joblib", ".pt", ".pkl", ".npz", ".png", ".jpg", ".gif",
              ".ico", ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin"}
TEXT_EXTS  = {".py", ".ipynb", ".md", ".txt", ".json", ".yaml", ".yml",
              ".csv", ".cfg", ".ini", ".toml", ".rst", ".html", ".js"}

# ── search patterns ──────────────────────────────────────────────────────────
PATTERNS = {
    "96S250P":   re.compile(r'96[Ss]250[Pp]', re.I),
    "96S":       re.compile(r'\b96[Ss]\b', re.I),
    "250P":      re.compile(r'\b250[Pp]\b', re.I),
    "series_96": re.compile(r'\bseries\s*[=:]\s*96\b|\b96\s*series\b|PACK_SERIES\s*=\s*96', re.I),
    "parallel_250": re.compile(r'\bparallel\s*[=:]\s*250\b|\b250\s*parallel\b|PACK_PARALLEL\s*=\s*250', re.I),
    "1200kWh":   re.compile(r'1[,\s]?200\s*k[Ww][Hh]|1200\s*k[Ww][Hh]', re.I),
    "1200_bare": re.compile(r'\b1200\b'),
    "1200000":   re.compile(r'\b1200000\b|\b1_200_000\b'),
    "1p2e6":     re.compile(r'1\.2\s*[eE]\s*6|1\.2\s*\*\s*10\s*\*\*\s*6'),
    "2p0_Ah":    re.compile(r'\b2\.0\s*[Aa][Hh]\b|\b2\s*[Aa][Hh]\b|\bNOMINAL.*2\.0\b|\b2\.0.*[Cc]apacit', re.I),
    "NOMINAL_2": re.compile(r'NOMINAL_CAP\s*=\s*2|nominal_cap\s*=\s*2', re.I),
    "3p6_V":     re.compile(r'\b3\.6\s*[Vv]\b|\b3\.6.*[Vv]olt|[Vv]olt.*3\.6', re.I),
    "NOMINAL_V": re.compile(r'NOMINAL_VOLT\s*=\s*3|cell_voltage\s*=\s*3', re.I),
    "pack_calc": re.compile(r'pack|PACK|series_cell|parallel_cell|pack_energy|pack_soh|'
                            r'pack_soc|pack_capacity|pack_voltage|usable_energy|'
                            r'remaining_energy|cell.to.pack', re.I),
    "kWh":       re.compile(r'\bkWh\b|\bkwh\b', re.I),
    "energy_calc": re.compile(r'energy\s*=.*volt|energy\s*=.*cap|volt.*cap.*1000', re.I),
    "345p6":     re.compile(r'\b345\.6\b'),
    "172p8":     re.compile(r'\b172\.8\b'),
    "500Ah":     re.compile(r'\b500\s*[Aa][Hh]\b|\bpack.*500\b'),
}

# ── collect all searchable files ─────────────────────────────────────────────
def should_skip(path: Path) -> bool:
    for part in path.parts:
        if part in SKIP_DIRS:
            return True
    if path.suffix.lower() in SKIP_EXTS:
        return True
    return False

def read_text(path: Path):
    for enc in ('utf-8', 'utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return path.read_text(encoding=enc, errors='replace')
        except Exception:
            pass
    return None

all_files = []
for p in PROJECT.rglob("*"):
    if p.is_file() and not should_skip(p) and p.suffix.lower() in TEXT_EXTS:
        all_files.append(p)

print(f"Files to search: {len(all_files)}")

# ── run search ───────────────────────────────────────────────────────────────
hits = {k: [] for k in PATTERNS}   # pattern_name -> [(file, lineno, line)]

for fpath in sorted(all_files):
    text = read_text(fpath)
    if text is None:
        continue
    lines = text.splitlines()
    for lno, line in enumerate(lines, 1):
        for name, pat in PATTERNS.items():
            if pat.search(line):
                hits[name].append((str(fpath), lno, line.strip()))

# ── print results ─────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("PACK ASSUMPTION AUDIT — SEARCH RESULTS")
print("=" * 70)

total_hits = 0
for name, matches in hits.items():
    if matches:
        print(f"\n{'─'*60}")
        print(f"PATTERN: {name}  ({len(matches)} hits)")
        print(f"{'─'*60}")
        for fpath, lno, line in matches:
            print(f"  {fpath}:{lno}  |  {line[:120]}")
            total_hits += 1
    else:
        print(f"\nPATTERN: {name}  — no hits")

print(f"\n{'='*70}")
print(f"TOTAL HITS: {total_hits}  across {len(all_files)} files searched")

# ── file size + modification dates for frozen models ─────────────────────────
print("\n" + "=" * 70)
print("FROZEN MODEL INTEGRITY CHECK (size check only, not loaded)")
print("=" * 70)
frozen = [
    "models/weather_final.joblib",
    "models/fuel_xgb.joblib",
    "models/battery_soc_lstm.pt",
    "models/battery_soh_final.joblib",
]
import time
for fpath in frozen:
    p = Path(fpath)
    if p.exists():
        s = p.stat()
        mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.st_mtime))
        print(f"  OK  {fpath:<45} size={s.st_size:>10,} bytes  mtime={mtime}")
    else:
        print(f"  MISSING  {fpath}")

# ── mathematical consistency ──────────────────────────────────────────────────
print("\n" + "=" * 70)
print("MATHEMATICAL CONSISTENCY CHECK")
print("=" * 70)
S = 96; P = 250; V_cell = 3.6; C_cell = 2.0
V_pack = S * V_cell
C_pack_Ah = P * C_cell
E_pack_kWh = V_pack * C_pack_Ah / 1000.0
req_cap_for_1200 = 1_200_000 / (S * P * V_cell)

print(f"  Cell voltage (NASA nominal)  : {V_cell} V")
print(f"  Cell capacity (NASA nominal) : {C_cell} Ah")
print(f"  Pack topology                : {S}S{P}P")
print(f"  Pack voltage (derived)       : {S} x {V_cell} = {V_pack:.1f} V")
print(f"  Pack capacity (derived)      : {P} x {C_cell} = {C_pack_Ah:.1f} Ah")
print(f"  Pack nominal energy (derived): {V_pack:.1f} x {C_pack_Ah:.1f} / 1000 = {E_pack_kWh:.1f} kWh")
print(f"  Existing project assumption  : 1200 kWh")
print(f"  Discrepancy                  : 1200 / {E_pack_kWh:.1f} = {1200/E_pack_kWh:.4f}x")
print(f"  Cell capacity needed for 1200 kWh at 96S250P, 3.6V:")
print(f"    = 1,200,000 / (96 x 250 x 3.6) = {req_cap_for_1200:.2f} Ah")
print(f"  Consistent? {'NO — 1200 kWh requires ' + str(round(req_cap_for_1200,2)) + ' Ah cells, not 2.0 Ah'}")
