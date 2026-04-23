import sys
import pandas as pd
import glob

sys.path.append('/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/Script')
from pricing import get_grid_buy_price, get_ev_sell_price

def calc_custom(csv_path, bat_cap, max_power, morning_extra_load):
    df = pd.read_csv(csv_path)
    df['时间'] = pd.to_datetime(df['时间'])
    
    # Add extra load ONLY in the morning peak (10:00-12:00) to simulate discounted charging
    def get_extra_load(t):
        if (10 <= t.hour < 12): return morning_extra_load
        return 0.0
        
    df['额外负载(kW)'] = df['时间'].apply(get_extra_load)
    
    # Factory load is 50kW during 7-12 and 13-18
    def get_factory_load(t):
        if (7 <= t.hour < 12) or (13 <= t.hour < 18): return 50.0
        return 0.0
        
    df['工厂用电(kW)'] = df['时间'].apply(get_factory_load)
    df['真实总负载(kW)'] = df['光伏发电功率(kW)'] - df['负载功率(kW)'] + df['额外负载(kW)']
    
    # EV charging is the remaining load
    df['充电桩用电(kW)'] = (df['真实总负载(kW)'] - df['工厂用电(kW)']).clip(lower=0)
    
    current_energy = (df['SOC(%)'].iloc[0] / 100.0) * bat_cap if bat_cap > 0 else 0
    dt = 5 / 60.0
    profit = 0
    
    for i, row in df.iterrows():
        t = row['时间']
        hour = t.hour
        net_load = row['真实总负载(kW)'] - row['光伏发电功率(kW)']
        
        buy_from_grid = 0.0
        sell_to_grid = 0.0
        
        if 0 <= hour < 8:
            space = bat_cap - current_energy if bat_cap > 0 else 0
            charge = min(max_power, space / dt) if bat_cap > 0 else 0
            current_energy += charge * dt
            if net_load > 0:
                buy_from_grid = net_load + charge
            else:
                buy_from_grid = charge
                sell_to_grid = -net_load
        else:
            if net_load > 0:
                discharge = min(max_power, current_energy / dt) if bat_cap > 0 else 0
                discharge = min(discharge, net_load)
                current_energy -= discharge * dt
                deficit = net_load - discharge
                if deficit > 0: buy_from_grid = deficit
            else:
                space = bat_cap - current_energy if bat_cap > 0 else 0
                charge = min(max_power, space / dt) if bat_cap > 0 else 0
                charge = min(charge, -net_load)
                current_energy += charge * dt
                rem = -net_load - charge
                if rem > 0: sell_to_grid = rem
                    
        grid_buy = get_grid_buy_price(t.strftime('%Y-%m-%d'), hour)
        ev_sell = get_ev_sell_price(t.strftime('%Y-%m-%d'), hour)
        
        # apply discount for morning extra EV charging
        if 10 <= hour < 12:
            ev_sell = 0.60 # discount from 0.91 to 0.60 to attract users
            
        cost = buy_from_grid * dt * grid_buy
        rev = row['充电桩用电(kW)'] * dt * ev_sell + row['工厂用电(kW)'] * dt * grid_buy + sell_to_grid * dt * 0.1
        profit += rev - cost
        
    return profit

files = glob.glob('/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/数据/**/*.csv', recursive=True)
sunny = [f for f in files if any(x in f for x in ['0415','0416','0420','0422'])]

for load in [0, 50, 100, 150, 200, 300]:
    p0 = sum(calc_custom(f, 0, 0, load) for f in sunny) / len(sunny)
    p1 = sum(calc_custom(f, 257.0, 120.0, load) for f in sunny) / len(sunny)
    p2 = sum(calc_custom(f, 514.0, 240.0, load) for f in sunny) / len(sunny)
    
    e1 = (p1 - p0) * 365 / 10000
    e2 = (p2 - p1) * 365 / 10000
    
    print(f"Morning Extra Load: {load}kW | ESS1 ROI: {e1/22*100:.1f}% | ESS2 ROI: {e2/22*100:.1f}%")
