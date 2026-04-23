import sys
import os
import pandas as pd
import glob

sys.path.append('/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/Script')
from annual_prediction import calc_for_file

files = glob.glob('/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/数据/**/*.csv', recursive=True)
sunny_files = [f for f in files if '0415' in f or '0416' in f or '0420' in f or '0422' in f]

def get_sold_pv(csv_path, bat_cap, max_power):
    df = pd.read_csv(csv_path)
    df['时间'] = pd.to_datetime(df['时间'])
    df['真实总负载(kW)'] = df['光伏发电功率(kW)'] - df['负载功率(kW)']
    
    def get_factory_load(t):
        hour = t.hour
        if (7 <= hour < 12) or (13 <= hour < 18): return 50.0
        return 0.0
        
    df['工厂用电(kW)'] = df.apply(lambda row: min(max(row['真实总负载(kW)'], 0), get_factory_load(row['时间'])), axis=1)
    df['充电桩用电(kW)'] = (df['真实总负载(kW)'] - df['工厂用电(kW)']).clip(lower=0)
    
    current_energy = (df['SOC(%)'].iloc[0] / 100.0) * bat_cap if bat_cap > 0 else 0
    dt = 5 / 60.0
    total_sold = 0.0
    total_excess = 0.0
    
    for i, row in df.iterrows():
        t = row['时间']
        hour = t.hour
        load = row['真实总负载(kW)']
        pv = row['光伏发电功率(kW)']
        net_load = load - pv
        
        if 0 <= hour < 8:
            space = bat_cap - current_energy if bat_cap > 0 else 0
            charge = min(max_power, space / dt) if bat_cap > 0 else 0
            current_energy += charge * dt
            if net_load < 0:
                excess = -net_load
                total_excess += excess * dt
                sold = excess - charge
                if sold > 0: total_sold += sold * dt
        else:
            if net_load > 0:
                discharge = min(max_power, current_energy / dt) if bat_cap > 0 else 0
                discharge = min(discharge, net_load)
                current_energy -= discharge * dt
            else:
                excess = -net_load
                total_excess += excess * dt
                space = bat_cap - current_energy if bat_cap > 0 else 0
                charge = min(max_power, space / dt) if bat_cap > 0 else 0
                charge = min(charge, excess)
                current_energy += charge * dt
                sold = excess - charge
                if sold > 0: total_sold += sold * dt
                
    return total_excess, total_sold

for f in sunny_files:
    print(os.path.basename(f))
    ex, s0 = get_sold_pv(f, 0.0, 0.0)
    ex, s1 = get_sold_pv(f, 257.0, 120.0)
    ex, s2 = get_sold_pv(f, 514.0, 240.0)
    print(f"Total excess PV: {ex:.2f} kWh")
    print(f"Sold to grid (0 bat): {s0:.2f} kWh")
    print(f"Sold to grid (1 bat): {s1:.2f} kWh")
    print(f"Sold to grid (2 bat): {s2:.2f} kWh")
    print("---")
