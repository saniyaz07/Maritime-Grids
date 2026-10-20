import sys, csv, re
sys.stdout.reconfigure(encoding='utf-8')

CELL_V = 3.6; CELL_AH = 2.0

rows_data = [
    {'ship': 'Oil Service Boat', 'cfg': '96S120P',  'S': 96, 'P': 120, 'stated_v': 400.0, 'stated_kwh': 650.0},
    {'ship': 'Fishing Trawler',  'cfg': '96S50P',   'S': 96, 'P': 50,  'stated_v': 400.0, 'stated_kwh': 250.0},
    {'ship': 'Surfer Boat',      'cfg': '96S30P',   'S': 96, 'P': 30,  'stated_v': 400.0, 'stated_kwh': 150.0},
    {'ship': 'Tanker Ship',      'cfg': '96S250P',  'S': 96, 'P': 250, 'stated_v': 800.0, 'stated_kwh': 1200.0},
]

print('ANALYSIS OF FIX PATTERN FOR ALL 4 SHIPS')
print('=' * 80)
print('Fixed: CELL_V=3.6V, CELL_AH=2.0Ah (NASA-verified, immutable)')
print('Fix: keep S=96, keep stated kWh design target, solve for P')
print()

fixes = []
for r in rows_data:
    S = r['S']
    target_kwh = r['stated_kwh']
    target_v   = r['stated_v']

    # Path A: keep 96S, solve for P, accept V=345.6
    v_corrected = 96 * CELL_V        # 345.6 V
    req_ah      = target_kwh * 1000 / v_corrected
    req_P       = req_ah / CELL_AH   # may not be integer
    req_P_int   = round(req_P)       # nearest integer
    actual_kwh  = v_corrected * req_P_int * CELL_AH / 1000.0

    # Is 400V bus label compatible with 345.6V actual?
    if abs(target_v - 400.0) < 1:
        bus_compat = '345.6V is within 400V-class range (300-420V) — label acceptable'
    elif abs(target_v - 800.0) < 1:
        bus_compat = '345.6V is NOT within 800V-class range — but spec says keep 96S'

    fixes.append({
        'ship': r['ship'],
        'old_cfg': r['cfg'],
        'old_v': target_v,
        'old_kwh': target_kwh,
        'new_cfg': '96S%dP' % req_P_int,
        'new_v': v_corrected,
        'new_P_exact': req_P,
        'new_P_int': req_P_int,
        'exact_kwh': actual_kwh,
        'bus_note': bus_compat,
    })

    print('Ship: %s' % r['ship'])
    print('  Old: %-10s  V=%.0f  kWh=%.0f' % (r['cfg'], target_v, target_kwh))
    print('  Fix: 96S x 3.6 = 345.6V (corrected bus)')
    print('  Required Ah = %d,000 / 345.6 = %.4f Ah' % (int(target_kwh), req_ah))
    print('  Required P  = %.4f / 2.0 = %.4f (rounded to %d)' % (req_ah, req_P, req_P_int))
    print('  Exact kWh   = 345.6 x %d x 2.0 / 1000 = %.4f kWh' % (req_P_int, actual_kwh))
    print('  New config  : 96S%dP  |  V=345.6  |  kWh=%.4f' % (req_P_int, actual_kwh))
    print('  Bus label   : %s' % bus_compat)
    print()

print()
print('PROPOSED CHANGES TABLE')
print('-' * 80)
print('%-20s %-12s %8s %8s | %-12s %8s %12s' % (
    'Ship', 'Old Config', 'Old V', 'Old kWh', 'New Config', 'New V', 'Exact kWh'))
print('-' * 80)
for f in fixes:
    print('%-20s %-12s %8.1f %8.0f | %-12s %8.1f %12.4f' % (
        f['ship'], f['old_cfg'], f['old_v'], f['old_kwh'],
        f['new_cfg'], f['new_v'], f['exact_kwh']))
