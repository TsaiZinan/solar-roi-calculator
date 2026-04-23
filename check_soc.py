import sys
import os
import pandas as pd

sys.path.append('/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/Script')

def check_soc(csv_path, bat_cap, max_power):
    df = pd.read_csv(csv_path)
    df['时间'] = pd.to_datetime(df['时间'])
    df['真实总负载(kW)'] = df['光伏发电功率(kW)'] - df['负载功率(kW)']
    
    def get_factory_load(t):
        hour = t.hour
        if (7 <= hour < 12) or (13 <= hour < 18): return 50.0
        return 0.0
        
    df['工厂用电(kW)'] = df.apply(lambda row: min(max(row['真实总负载(kW)'], 0), get_factory_load(row['时间'])), axis=1)
    
    current_energy = 0
    dt = 5 / 60.0
    
    for i, row in df.iterrows():
        t = row['时间']
        hour = t.hour
        load = row['真实总负载(kW)']
        pv = row['光伏发电功率(kW)']
        net_load = load - pv
        
        if 0 <= hour < 8:
            space = bat_cap - current_energy
            charge = min(max_power, space / dt)
            current_energy += charge * dt
        else:
            if net_load > 0:
                discharge = min(max_power, current_energy / dt)
                discharge = min(discharge, net_load)
                current_energy -= discharge * dt
            else:
                excess = -net_load
                space = bat_cap - current_energy
                charge = min(max_power, space / dt)
                charge = min(charge, excess)
                current_energy += charge * dt
                
        if t.hour == 12 and t.minute == 0:
            print(f"12:00 SOC: {current_energy / bat_cap * 100:.1f}% (Energy: {current_energy:.1f} kWh)")
        if t.hour == 14 and t.minute == 0:
            print(f"14:00 SOC: {current_energy / bat_cap * 100:.1f}% (Energy: {current_energy:.1f} kWh)")
        if t.hour == 8 and t.minute == 0:
            print(f"08:00 SOC: {current_energy / bat_cap * 100:.1f}% (Energy: {current_energy:.1f} kWh)")

print("For 1 battery:")
check_soc('/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/数据/20260420/日报表_广东汕头市雅威机电实业0.12MW#0.257MWh工商储项目_20260421152008.csv', 257.0, 120.0)
print("For 2 batteries:")
check_soc('/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/数据/20260420/日报表_广东汕头市雅威机电实业0.12MW#0.257MWh工商储项目_20260421152008.csv', 514.0, 240.0)
