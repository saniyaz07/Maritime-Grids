import pandas as pd
import numpy as np

df = pd.read_csv('data/processed/battery/battery_discharge_soh.csv')
df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
df = df.sort_values(['battery_id', 'timestamp_dt']).reset_index(drop=True)
df['cycle_num'] = df.groupby('battery_id').cumcount() + 1

b41 = df[df['battery_id']=='B0041'].sort_values('cycle_num')[['cycle_num','filename','Capacity_numeric','SOH']].reset_index(drop=True)
print('All B0041 cycles:')
print(b41.to_string(index=False))

print()
calib = b41[b41['Capacity_numeric'] < 0.5]
normal = b41[b41['Capacity_numeric'] >= 0.5]
print('Calibration cycles (cap < 0.5 Ah):', sorted(calib['cycle_num'].tolist()))
print('Normal cycles (cap >= 0.5 Ah): first=%d last=%d count=%d' % (normal['cycle_num'].min(), normal['cycle_num'].max(), len(normal)))
print('Calibration count:', len(calib))
print('Calibration cycle range: %d to %d' % (calib['cycle_num'].min(), calib['cycle_num'].max()))
print('Cap stats calibration: mean=%.4f min=%.4f max=%.4f' % (calib['Capacity_numeric'].mean(), calib['Capacity_numeric'].min(), calib['Capacity_numeric'].max()))
print('Cap stats normal: mean=%.4f min=%.4f max=%.4f' % (normal['Capacity_numeric'].mean(), normal['Capacity_numeric'].min(), normal['Capacity_numeric'].max()))
