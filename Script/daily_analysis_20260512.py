import csv
import json
import os
from datetime import datetime
from config import (
    BASE_DIR, DATA_DIR, REPORT_DIR, JSON_DIR,
    GRID_PRICING_PATH, EV_PRICING_PATH,
    get_factory_load, PRIMARY_ESS, PV_PRICE_SCENARIOS,
    SUMMARY_REPORT_PATH, SUMMARY_JSON_PATH, SUMMARY_PRICE_KEYS,
    ensure_report_dir,
)

CSV_PATH = os.path.join(DATA_DIR, "20260512/日报表_广东汕头市雅威机电实业0.12MW#0.257MWh工商储项目_20260513102513.csv")
DATE_STR = "20260512"
DATE_OBJ = datetime.strptime(DATE_STR, "%Y%m%d")
dt_step = 5.0 / 60.0

PERIOD_LABELS = {}

def assign_period_labels(grid_prices):
    target_date = DATE_OBJ.strftime('%Y-%m-%d')
    applicable_prices = None
    for date_str, prices in grid_prices:
        if date_str <= target_date:
            applicable_prices = prices
        else:
            break
    if applicable_prices is None and grid_prices:
        applicable_prices = grid_prices[0][1]
    if applicable_prices is None:
        return {h: "谷" for h in range(24)}
    
    price_values = list(applicable_prices.values())
    min_price = min(price_values)
    max_price = max(price_values)
    price_range = max_price - min_price
    
    peak_threshold = min_price + price_range * 0.66
    flat_threshold = min_price + price_range * 0.33
    
    for h in range(24):
        price = applicable_prices.get(h, min_price)
        if price >= peak_threshold:
            PERIOD_LABELS[h] = "峰"
        elif price >= flat_threshold:
            PERIOD_LABELS[h] = "平"
        else:
            PERIOD_LABELS[h] = "谷"

def load_csv_data():
    rows = []
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row['时间'], '%Y-%m-%d %H:%M:%S')
            rows.append({
                'time': dt,
                'hour': dt.hour,
                'minute': dt.minute,
                'storage_power': float(row['储能有功功率(kW)']),
                'grid_power': float(row['电网功率(kW)']),
                'load_power': float(row['负载功率(kW)']),
                'soc': float(row['SOC(%)']),
                'pv_power': float(row['光伏发电功率(kW)']),
            })
    return rows

def load_pricing():
    grid_prices = []
    with open(GRID_PRICING_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row['记录日期']
            prices = {int(h): float(row[f'{h:02d}:00']) for h in range(24)}
            grid_prices.append((date_str, prices))
    grid_prices.sort(key=lambda x: x[0])
    
    ev_prices = []
    with open(EV_PRICING_PATH, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row['记录日期']
            prices = {int(h): float(row[f'{h:02d}:00']) for h in range(24)}
            ev_prices.append((date_str, prices))
    ev_prices.sort(key=lambda x: x[0])
    
    return grid_prices, ev_prices

def get_price_for_datetime(pricing_list, dt):
    target_date = dt.strftime('%Y-%m-%d')
    applicable = None
    for date_str, prices in pricing_list:
        if date_str <= target_date:
            applicable = prices
        else:
            break
    if applicable is None and pricing_list:
        applicable = pricing_list[0][1]
    if applicable is None:
        return 0.0
    return applicable.get(dt.hour, 0.0)

def calculate_energy_flow(rows, grid_prices, ev_prices):
    hourly_stats = {}
    for h in range(24):
        hourly_stats[h] = {
            'hour': f'{h:02d}:00',
            'period': PERIOD_LABELS[h],
            'pv_generation': 0.0,
            'storage_charge': 0.0,
            'storage_discharge': 0.0,
            'factory_load': 0.0,
            'charging_pile_load': 0.0,
            'grid_purchase': 0.0,
            'grid_sale': 0.0,
            'factory_savings_revenue': 0.0,
            'pv_to_load': 0.0,
            'pv_to_factory': 0.0,
            'pv_to_storage': 0.0,
            'pv_to_grid': 0.0,
            'grid_to_load': 0.0,
            'grid_to_storage': 0.0,
        }
    
    for row in rows:
        h = row['hour']
        stats = hourly_stats[h]
        
        pv_power = max(0, row['pv_power'])
        storage_power = row['storage_power']
        grid_power = row['grid_power']
        load_power = row['load_power']
        
        total_load_power = pv_power - load_power
        if total_load_power < 0:
            total_load_power = 0
        
        factory_load = get_factory_load(h)
        charging_pile_load = max(0, total_load_power - factory_load)
        
        if storage_power < 0:
            storage_charge = abs(storage_power)
            storage_discharge = 0
        else:
            storage_charge = 0
            storage_discharge = storage_power
        
        if grid_power < 0:
            grid_purchase = abs(grid_power)
            grid_sale = 0
        else:
            grid_purchase = 0
            grid_sale = grid_power
        
        pv_to_load = min(pv_power, total_load_power)
        pv_remaining = pv_power - pv_to_load
        
        pv_to_factory = min(pv_to_load, factory_load)
        pv_to_charging = pv_to_load - pv_to_factory
        
        if pv_remaining > 0 and storage_charge > 0:
            pv_to_storage = min(pv_remaining, storage_charge)
        else:
            pv_to_storage = 0
        
        pv_to_grid = pv_remaining - pv_to_storage
        if pv_to_grid < 0:
            pv_to_grid = 0
        
        grid_to_load = grid_purchase
        if storage_charge > pv_to_storage:
            grid_to_storage = storage_charge - pv_to_storage
            grid_to_load = grid_purchase - grid_to_storage
        else:
            grid_to_storage = 0
        
        grid_price = get_price_for_datetime(grid_prices, row['time'])
        factory_savings = pv_to_factory * grid_price
        
        stats['pv_generation'] += pv_power * dt_step
        stats['storage_charge'] += storage_charge * dt_step
        stats['storage_discharge'] += storage_discharge * dt_step
        stats['factory_load'] += factory_load * dt_step
        stats['charging_pile_load'] += charging_pile_load * dt_step
        stats['grid_purchase'] += grid_purchase * dt_step
        stats['grid_sale'] += grid_sale * dt_step
        stats['factory_savings_revenue'] += factory_savings * dt_step
        stats['pv_to_load'] += pv_to_load * dt_step
        stats['pv_to_factory'] += pv_to_factory * dt_step
        stats['pv_to_storage'] += pv_to_storage * dt_step
        stats['pv_to_grid'] += pv_to_grid * dt_step
        stats['grid_to_load'] += max(0, grid_to_load) * dt_step
        stats['grid_to_storage'] += grid_to_storage * dt_step
    
    return hourly_stats

def calculate_revenue(hourly_stats, grid_prices, ev_prices, pv_feed_in_price):
    total_pv_to_grid = sum(s['pv_to_grid'] for s in hourly_stats.values())
    
    pv_sale_revenue_grid = total_pv_to_grid * pv_feed_in_price
    pv_sale_revenue_charging = 0
    pv_sale_revenue_factory = 0
    
    for h in range(24):
        stats = hourly_stats[h]
        pv_to_charging = stats['pv_to_load'] - stats['pv_to_factory']
        ev_price = get_price_for_datetime(ev_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
        pv_sale_revenue_charging += pv_to_charging * ev_price
        pv_sale_revenue_factory += stats['pv_to_factory'] * get_price_for_datetime(grid_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
    
    total_pv_revenue = pv_sale_revenue_grid + pv_sale_revenue_factory
    pv_sale_revenue_charging_only = pv_sale_revenue_charging
    
    grid_purchase_cost = 0
    grid_to_charging_revenue = 0
    grid_to_factory_cost = 0
    grid_to_storage_cost = 0
    
    for h in range(24):
        stats = hourly_stats[h]
        grid_price = get_price_for_datetime(grid_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
        ev_price = get_price_for_datetime(ev_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
        
        grid_purchase_cost += stats['grid_purchase'] * grid_price
        grid_to_charging_revenue += stats['grid_to_load'] * ev_price
        grid_to_factory_cost += stats['pv_to_factory'] * 0
        grid_to_storage_cost += stats['grid_to_storage'] * grid_price
    
    storage_discharge_to_charging = 0
    storage_discharge_to_factory = 0
    for h in range(24):
        stats = hourly_stats[h]
        ev_price = get_price_for_datetime(ev_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
        grid_price = get_price_for_datetime(grid_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
        
        if stats['storage_discharge'] > 0:
            discharge = stats['storage_discharge']
            factory_need = stats['factory_load'] - stats['pv_to_factory']
            if factory_need > 0:
                to_factory = min(discharge, factory_need)
                storage_discharge_to_factory += to_factory * grid_price
                discharge -= to_factory
            storage_discharge_to_charging += discharge * ev_price
    
    total_revenue = total_pv_revenue + pv_sale_revenue_charging + grid_to_charging_revenue + storage_discharge_to_charging + storage_discharge_to_factory - grid_purchase_cost
    
    without_storage_revenue = pv_sale_revenue_grid + pv_sale_revenue_factory + pv_sale_revenue_charging - grid_purchase_cost + grid_to_charging_revenue
    
    storage_extra = total_revenue - without_storage_revenue
    
    period_stats = []
    period_order = []
    periods_seen = set()
    
    for h in range(24):
        period = hourly_stats[h]['period']
        if period not in periods_seen:
            periods_seen.add(period)
            period_order.append(period)
    
    for period in period_order:
        period_hours = [h for h in range(24) if hourly_stats[h]['period'] == period]
        
        p_pv_gen = sum(hourly_stats[h]['pv_generation'] for h in period_hours)
        p_storage_charge = sum(hourly_stats[h]['storage_charge'] for h in period_hours)
        p_storage_discharge = sum(hourly_stats[h]['storage_discharge'] for h in period_hours)
        p_factory = sum(hourly_stats[h]['factory_load'] for h in period_hours)
        p_charging = sum(hourly_stats[h]['charging_pile_load'] for h in period_hours)
        p_grid_purchase = sum(hourly_stats[h]['grid_purchase'] for h in period_hours)
        p_grid_sale = sum(hourly_stats[h]['grid_sale'] for h in period_hours)
        p_factory_savings = sum(hourly_stats[h]['factory_savings_revenue'] for h in period_hours)
        p_pv_to_load = sum(hourly_stats[h]['pv_to_load'] for h in period_hours)
        p_pv_to_factory = sum(hourly_stats[h]['pv_to_factory'] for h in period_hours)
        p_pv_to_storage = sum(hourly_stats[h]['pv_to_storage'] for h in period_hours)
        p_pv_to_grid = sum(hourly_stats[h]['pv_to_grid'] for h in period_hours)
        p_grid_to_load = sum(hourly_stats[h]['grid_to_load'] for h in period_hours)
        p_grid_to_storage = sum(hourly_stats[h]['grid_to_storage'] for h in period_hours)
        
        period_revenue = 0
        for h in period_hours:
            stats = hourly_stats[h]
            grid_price = get_price_for_datetime(grid_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
            ev_price = get_price_for_datetime(ev_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
            
            period_revenue += stats['pv_to_grid'] * pv_feed_in_price * dt_step
            period_revenue += (stats['pv_to_load'] - stats['pv_to_factory']) * ev_price * dt_step
            period_revenue += stats['pv_to_factory'] * grid_price * dt_step
            period_revenue -= stats['grid_purchase'] * grid_price * dt_step
            
            if stats['storage_discharge'] > 0:
                discharge = stats['storage_discharge']
                factory_need = stats['factory_load'] - stats['pv_to_factory']
                if factory_need > 0:
                    to_factory = min(discharge, factory_need)
                    period_revenue += to_factory * grid_price * dt_step
                    discharge -= to_factory
                period_revenue += discharge * ev_price * dt_step
        
        period_stats.append({
            'period': period,
            'photovoltaic_generation_kwh': round(p_pv_gen, 4),
            'storage_charge_kwh': round(p_storage_charge, 4),
            'storage_discharge_kwh': round(p_storage_discharge, 4),
            'factory_load_kwh': round(p_factory, 4),
            'charging_pile_load_kwh': round(p_charging, 4),
            'grid_purchase_kwh': round(p_grid_purchase, 4),
            'grid_sale_kwh': round(p_grid_sale, 4),
            'factory_savings_revenue': round(p_factory_savings, 4),
            'photovoltaic_to_load_kwh': round(p_pv_to_load, 4),
            'photovoltaic_to_factory_kwh': round(p_pv_to_factory, 4),
            'photovoltaic_to_storage_kwh': round(p_pv_to_storage, 4),
            'photovoltaic_to_grid_kwh': round(p_pv_to_grid, 4),
            'grid_to_load_kwh': round(p_grid_to_load, 4),
            'grid_to_storage_kwh': round(p_grid_to_storage, 4),
            'period_revenue': round(period_revenue, 4),
        })
    
    hourly_list = []
    for h in range(24):
        stats = hourly_stats[h]
        
        period_revenue_hour = 0
        grid_price = get_price_for_datetime(grid_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
        ev_price = get_price_for_datetime(ev_prices, datetime(DATE_OBJ.year, DATE_OBJ.month, DATE_OBJ.day, h))
        
        period_revenue_hour += stats['pv_to_grid'] * pv_feed_in_price
        period_revenue_hour += (stats['pv_to_load'] - stats['pv_to_factory']) * ev_price
        period_revenue_hour += stats['pv_to_factory'] * grid_price
        period_revenue_hour -= stats['grid_purchase'] * grid_price
        
        if stats['storage_discharge'] > 0:
            discharge = stats['storage_discharge']
            factory_need = stats['factory_load'] - stats['pv_to_factory']
            if factory_need > 0:
                to_factory = min(discharge, factory_need)
                period_revenue_hour += to_factory * grid_price
                discharge -= to_factory
            period_revenue_hour += discharge * ev_price
        
        hourly_list.append({
            'hour': stats['hour'],
            'period': stats['period'],
            'photovoltaic_generation_kwh': round(stats['pv_generation'], 4),
            'storage_charge_kwh': round(stats['storage_charge'], 4),
            'storage_discharge_kwh': round(stats['storage_discharge'], 4),
            'factory_load_kwh': round(stats['factory_load'], 4),
            'charging_pile_load_kwh': round(stats['charging_pile_load'], 4),
            'grid_purchase_kwh': round(stats['grid_purchase'], 4),
            'grid_sale_kwh': round(stats['grid_sale'], 4),
            'factory_savings_revenue': round(stats['factory_savings_revenue'], 4),
            'photovoltaic_to_load_kwh': round(stats['pv_to_load'], 4),
            'photovoltaic_to_factory_kwh': round(stats['pv_to_factory'], 4),
            'photovoltaic_to_storage_kwh': round(stats['pv_to_storage'], 4),
            'photovoltaic_to_grid_kwh': round(stats['pv_to_grid'], 4),
            'grid_to_load_kwh': round(stats['grid_to_load'], 4),
            'grid_to_storage_kwh': round(stats['grid_to_storage'], 4),
            'period_revenue': round(period_revenue_hour, 4),
        })
    
    return {
        'period_stats': period_stats,
        'hourly_stats': hourly_list,
        'summary': {
            'total_revenue': round(total_revenue, 4),
            'cash_revenue': round(total_pv_revenue + storage_discharge_to_charging + storage_discharge_to_factory, 4),
            'without_storage_total_revenue': round(without_storage_revenue, 4),
            'pv_sale_revenue': {
                'total': round(pv_sale_revenue_grid, 4),
                'from_storage': 0.0,
            },
            'factory_savings_revenue': {
                'total': round(pv_sale_revenue_factory, 4),
                'from_photovoltaic': round(pv_sale_revenue_factory, 4),
                'from_storage': round(storage_discharge_to_factory, 4),
            },
            'charging_pile_revenue': {
                'total': round(pv_sale_revenue_charging + grid_to_charging_revenue + storage_discharge_to_charging, 4),
                'from_photovoltaic': round(pv_sale_revenue_charging, 4),
                'from_grid': round(grid_to_charging_revenue, 4),
                'from_storage': round(storage_discharge_to_charging, 4),
            },
            'grid_purchase_cost': round(grid_purchase_cost, 4),
            'storage_contribution': {
                'total': round(storage_extra, 4),
                'charging_pile_revenue': round(storage_discharge_to_charging, 4),
                'factory_savings_revenue': round(storage_discharge_to_factory, 4),
            },
            'grid_to_factory_cost': round(grid_to_factory_cost, 4),
            'grid_to_storage_cost': round(grid_to_storage_cost, 4),
        },
        'period_order': period_order,
    }

def generate_markdown_report(date_str, scenarios_results, hourly_stats, period_order):
    ensure_report_dir()
    
    csv_filename = os.path.basename(CSV_PATH)
    
    lines = []
    lines.append(f"# 每日收益分析报告 - {date_str}\n")
    lines.append(f"**数据文件**: {csv_filename}\n")
    
    for price_key, price_str in SUMMARY_PRICE_KEYS:
        scenario_name = ""
        for sn, sp in PV_PRICE_SCENARIOS:
            if abs(sp - float(price_str)) < 1e-9:
                scenario_name = sn
                break
        
        result = scenarios_results[price_key]
        period_stats = result['period_stats']
        
        lines.append(f"\n## {price_key}. 基础报表 (光伏上网电价 {price_str}元/度)")
        
        lines.append(f"\n### {price_key}.1 分时段汇总 (按电价标签自动分组)")
        lines.append("| 时段 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 工厂省电收益(元) | 向电网买电量(度) | 向电网卖电量(度) | 时段经营收益 |")
        lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        
        for ps in period_stats:
            lines.append(f"| {ps['period']} | {ps['photovoltaic_generation_kwh']:.0f} | {ps['storage_charge_kwh']:.1f} | {ps['storage_discharge_kwh']:.1f} | {ps['factory_load_kwh']:.0f} | {ps['charging_pile_load_kwh']:.0f} | {ps['factory_savings_revenue']:.2f} | {ps['grid_purchase_kwh']:.1f} | {ps['grid_sale_kwh']:.2f} | {ps['period_revenue']:.0f} |")
        
        lines.append(f"\n### {price_key}.2 光伏发电的流向与时间分布")
        lines.append("| 时段 | 光伏总产电(度) | 直接消纳(负载) | 充入储能 | 余电上网(卖电) |")
        lines.append("|:---|---:|---:|---:|---:|")
        
        for ps in period_stats:
            total_pv = ps['photovoltaic_generation_kwh']
            if total_pv > 0:
                direct_pct = ps['photovoltaic_to_load_kwh'] / total_pv * 100
                storage_pct = ps['photovoltaic_to_storage_kwh'] / total_pv * 100
                grid_pct = ps['photovoltaic_to_grid_kwh'] / total_pv * 100
            else:
                direct_pct = storage_pct = grid_pct = 0
            lines.append(f"| {ps['period']} | {total_pv:.2f} | {direct_pct:.1f}% | {storage_pct:.1f}% | {grid_pct:.1f}% |")
        
        lines.append(f"\n### {price_key}.3 电网购电的流向与时间分布")
        lines.append("| 时段 | 电网总购电(度) | 满足负载 | 充入储能 |")
        lines.append("|:---|---:|---:|---:|")
        
        for ps in period_stats:
            total_grid = ps['grid_purchase_kwh']
            if total_grid > 0:
                load_pct = ps['grid_to_load_kwh'] / total_grid * 100
                storage_pct = ps['grid_to_storage_kwh'] / total_grid * 100
            else:
                load_pct = storage_pct = 0
            lines.append(f"| {ps['period']} | {total_grid:.1f} | {load_pct:.1f}% | {storage_pct:.1f}% |")
        
        lines.append(f"\n### {price_key}.4 每小时详细报表")
        lines.append("| 小时 | 时段 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 工厂省电收益(元) | 向电网买电量(度) | 向电网卖电量(度) | 时段经营收益 |")
        lines.append("|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        
        for hs in result['hourly_stats']:
            lines.append(f"| {hs['hour']} | {hs['period']} | {hs['photovoltaic_generation_kwh']:.4f} | {hs['storage_charge_kwh']:.3f} | {hs['storage_discharge_kwh']:.3f} | {hs['factory_load_kwh']:.1f} | {hs['charging_pile_load_kwh']:.4f} | {hs['factory_savings_revenue']:.2f} | {hs['grid_purchase_kwh']:.3f} | {hs['grid_sale_kwh']:.3f} | {hs.get('period_revenue', 0):.4f} |")
    
    lines.append(f"\n## 2. 核心收益结论 (业主视角)\n")
    
    for price_key, price_str in SUMMARY_PRICE_KEYS:
        scenario_name = ""
        for sn, sp in PV_PRICE_SCENARIOS:
            if abs(sp - float(price_str)) < 1e-9:
                scenario_name = sn
                break
        
        result = scenarios_results[price_key]
        summary = result['summary']
        
        pv_sale_total = summary['pv_sale_revenue']['total']
        pv_sale_from_storage = summary['pv_sale_revenue']['from_storage']
        factory_total = summary['factory_savings_revenue']['total']
        factory_pv = summary['factory_savings_revenue']['from_photovoltaic']
        factory_storage = summary['factory_savings_revenue']['from_storage']
        charging_total = summary['charging_pile_revenue']['total']
        charging_pv = summary['charging_pile_revenue']['from_photovoltaic']
        charging_grid = summary['charging_pile_revenue']['from_grid']
        charging_storage = summary['charging_pile_revenue']['from_storage']
        grid_cost = summary['grid_purchase_cost']
        total_rev = summary['total_revenue']
        storage_extra = summary['storage_contribution']['total']
        
        pv_total_revenue = pv_sale_total + factory_pv + charging_pv
        
        scenario_label = {'01': 'A', '02': 'B', '035': 'C'}[price_key]
        
        lines.append(f"### 【场景 {scenario_label}：光伏上网电价 {price_str} 元/度】")
        lines.append(f"1. **光伏发电收益**: 今日光伏发电共实现收益 **{pv_total_revenue:.2f}** 元，其中上网售电收益 **{pv_sale_total:.2f}** 元，供充电桩使用收益 **{charging_pv:.2f}** 元，供厂区自用节省电费 **{factory_pv:.2f}** 元。")
        lines.append(f"2. **电网购电支撑情况**: 今日从电网购电共支出 **{grid_cost:.2f}** 元，其中直接供充电桩形成收入 **{charging_grid:.2f}** 元，直接供厂区对应购电成本 **{summary.get('grid_to_factory_cost', 0):.2f}** 元，另有 **{summary.get('grid_to_storage_cost', 0):.2f}** 元购电用于储能充电。")
        lines.append(f"3. **储能供电支撑情况**: 今日储能放电中，直接供充电桩形成收入 **{charging_storage:.2f}** 元，直接供厂区节省电费 **{factory_storage:.2f}** 元。")
        lines.append(f"4. **经营总收益**: 在当前储能运行结果下，今日实际总收益为 **{total_rev:.2f}** 元，计算式为 **{pv_total_revenue:.2f}（光伏）+ {charging_grid:.2f}（电网供充电桩）+ {charging_storage:.2f}（储能供充电桩）+ {factory_storage:.2f}（储能供厂区）- {grid_cost:.2f}（电网购电）= {total_rev:.2f}**；其中，上述各项收益中有 **{storage_extra:.2f}** 元由当前储能系统(250度)带来。\n")
    
    report_path = os.path.join(REPORT_DIR, f"每日收益分析报告_{date_str}.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"收益报告已生成: {report_path}")
    return report_path

def generate_json_report(date_str, scenarios_results, csv_filename):
    ensure_report_dir()
    
    payload = {
        'date': date_str,
        'source_csv': csv_filename,
        'generated_at': datetime.now().isoformat(),
        'storage_system': {
            'label': PRIMARY_ESS['label'],
            'capacity_kwh': PRIMARY_ESS['capacity_kwh'],
            'max_power_kw': PRIMARY_ESS['max_power_kw'],
        },
        'period_order': scenarios_results['01']['period_order'],
        'period_stats': scenarios_results['01']['period_stats'],
        'hourly_stats': scenarios_results['01']['hourly_stats'],
        'scenarios': {},
    }
    
    for price_key, price_str in SUMMARY_PRICE_KEYS:
        scenario_name = {'01': 'A', '02': 'B', '035': 'C'}[price_key]
        result = scenarios_results[price_key]
        summary = result['summary']
        
        payload['scenarios'][scenario_name] = {
            'scenario_name': scenario_name,
            'pv_feed_in_price': float(price_str),
            'daily_revenue': {
                'total_revenue': summary['total_revenue'],
                'cash_revenue': summary['cash_revenue'],
                'without_storage_total_revenue': summary['without_storage_total_revenue'],
                'photovoltaic_sale_revenue': summary['pv_sale_revenue'],
                'factory_savings_revenue': summary['factory_savings_revenue'],
                'charging_pile_revenue': summary['charging_pile_revenue'],
                'grid_purchase_cost': summary['grid_purchase_cost'],
                'storage_contribution': summary['storage_contribution'],
                'net_revenue_breakdown': {
                    'allocation_method': 'strict_accounting',
                    'pie_chart_ready': True,
                    'items': {
                        'photovoltaic_sale': {
                            'amount': summary['pv_sale_revenue']['total'],
                            'share_of_total_revenue': round(summary['pv_sale_revenue']['total'] / summary['total_revenue'], 6) if summary['total_revenue'] != 0 else 0,
                        },
                        'factory_savings': {
                            'amount': summary['factory_savings_revenue']['from_photovoltaic'],
                            'share_of_total_revenue': round(summary['factory_savings_revenue']['from_photovoltaic'] / summary['total_revenue'], 6) if summary['total_revenue'] != 0 else 0,
                        },
                        'charging_pile': {
                            'amount': summary['total_revenue'] - summary['pv_sale_revenue']['total'] - summary['factory_savings_revenue']['from_photovoltaic'],
                            'share_of_total_revenue': round((summary['total_revenue'] - summary['pv_sale_revenue']['total'] - summary['factory_savings_revenue']['from_photovoltaic']) / summary['total_revenue'], 6) if summary['total_revenue'] != 0 else 0,
                        },
                    },
                    'sum_of_items': summary['total_revenue'],
                },
            },
            'revenue_components': {
                'photovoltaic': {
                    'actual_total': summary['pv_sale_revenue']['total'] + summary['charging_pile_revenue']['from_photovoltaic'] + summary['factory_savings_revenue']['from_photovoltaic'],
                    'to_grid': summary['pv_sale_revenue']['total'],
                    'to_charging_pile': summary['charging_pile_revenue']['from_photovoltaic'],
                    'to_factory_savings': summary['factory_savings_revenue']['from_photovoltaic'],
                },
                'grid': {
                    'purchase_cost': summary['grid_purchase_cost'],
                    'to_factory_cost': summary.get('grid_to_factory_cost', 0),
                    'to_storage_cost': summary.get('grid_to_storage_cost', 0),
                    'to_charging_pile_revenue': summary['charging_pile_revenue']['from_grid'],
                },
                'storage': {
                    'extra_profit': summary['storage_contribution']['total'],
                    'to_factory_savings': summary['storage_contribution']['factory_savings_revenue'],
                    'to_charging_pile_revenue': summary['storage_contribution']['charging_pile_revenue'],
                },
            },
        }
    
    json_path = os.path.join(JSON_DIR, f"每日收益分析_{date_str}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    
    print(f"JSON报告已生成: {json_path}")
    return json_path

def update_summary_table():
    from init_summary import rebuild_summary_table
    rebuild_summary_table()
    print("总收益分析报表已更新")

def main():
    print("开始执行每日收益分析 - 20260512")
    
    rows = load_csv_data()
    print(f"已加载 {len(rows)} 条数据记录")
    
    grid_prices, ev_prices = load_pricing()
    print("已加载电价数据")
    
    assign_period_labels(grid_prices)
    print("已分配时段标签")
    
    hourly_stats = calculate_energy_flow(rows, grid_prices, ev_prices)
    print("能量流计算完成")
    
    scenarios_results = {}
    for price_key, price_str in SUMMARY_PRICE_KEYS:
        pv_feed_in_price = float(price_str)
        result = calculate_revenue(hourly_stats, grid_prices, ev_prices, pv_feed_in_price)
        scenarios_results[price_key] = result
        print(f"场景 {price_key} (光伏电价 {price_str}元/度) 收益计算完成")
    
    generate_markdown_report(DATE_STR, scenarios_results, hourly_stats, scenarios_results['01']['period_order'])
    generate_json_report(DATE_STR, scenarios_results, os.path.basename(CSV_PATH))
    
    update_summary_table()
    
    print("每日收益分析完成!")

if __name__ == "__main__":
    main()
