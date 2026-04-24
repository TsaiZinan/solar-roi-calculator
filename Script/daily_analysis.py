#!/usr/bin/env python
# -*- coding: utf-8 -*-

import csv
import os
from datetime import datetime

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from pricing import get_ev_sell_price, get_grid_buy_price

CSV_PATH = "/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/数据/20260421/日报表_广东汕头市雅威机电实业0.12MW#0.257MWh工商储项目_20260421152008.csv"
MODEL_NAME = "Qwen3.6"
REPORT_DIR = "/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/报告"

def get_tariff_period(hour, minute=0):
    t = hour + minute / 60.0
    if 0 <= t < 8:
        return "谷"
    elif (10 <= t < 12) or (14 <= t < 19):
        return "峰"
    else:
        return "平"

def get_grid_price(ts, hour):
    # 这里我们只用时段来调用，不需要 ts，但因为有 pricing.py 我们先保留原逻辑
    # 实际上，如果定价有变化，这里需要调用正确的函数
    return get_grid_buy_price(ts.strftime('%Y-%m-%d'), hour)

def get_charging_price(ts, hour, minute=0):
    return get_ev_sell_price(ts.strftime('%Y-%m-%d'), hour)

def get_factory_load(hour, minute=0):
    t = hour + minute / 60.0
    if (7 <= t < 12) or (13 <= t < 18):
        return 50.0
    return 0.0

def read_csv(path):
    data = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = datetime.strptime(row["时间"], "%Y-%m-%d %H:%M:%S")
            storage = float(row["储能有功功率(kW)"])
            grid = float(row["电网功率(kW)"])
            load = float(row["负载功率(kW)"])
            soc = float(row["SOC(%)"])
            pv = float(row["光伏发电功率(kW)"])
            data.append({
                "timestamp": ts,
                "hour": ts.hour,
                "minute": ts.minute,
                "storage": storage,
                "grid": grid,
                "load": load,
                "soc": soc,
                "pv": pv,
            })
    return data

def simulate_with_storage(data):
    results = []
    dt = 5.0 / 60.0
    STORAGE_EFFICIENCY = 0.95  # 充放电单向效率
    
    for row in data:
        period = get_tariff_period(row["hour"], row["minute"])
        grid_price = get_grid_price(row["timestamp"], row["hour"])
        charging_price = get_charging_price(row["timestamp"], row["hour"], row["minute"])
        
        grid_power = row["grid"]
        pv_power = row["pv"]
        storage_power = row["storage"]
        
        # 修复: 原始 CSV 中的 load 数据没有包含光伏的影响（只是单纯的 电网-储能）
        # 真实的负载消耗 = 光伏发电 + 储能放电 - 电网输出(卖电为正，买电为负)
        total_load_kw = pv_power + storage_power - grid_power
        total_load = max(0, total_load_kw)
        
        factory = get_factory_load(row["hour"], row["minute"])
        charging_load_kw = max(0, total_load - factory)
        
        grid_import_kw = max(0, -grid_power)
        grid_export_kw = max(0, grid_power)
        
        storage_charging_kw = max(0, -storage_power)
        storage_discharging_kw = max(0, storage_power)
        
        grid_cost = grid_import_kw * dt * grid_price
        charging_revenue = charging_load_kw * dt * charging_price
        pv_grid_revenue = grid_export_kw * dt * 0.10
        
        net_profit = charging_revenue + pv_grid_revenue - grid_cost
        
        pv_to_load = min(pv_power, total_load)
        pv_surplus = max(0, pv_power - total_load)
        pv_to_storage = min(pv_surplus, storage_charging_kw)
        pv_to_grid = max(0, pv_surplus - storage_charging_kw)
        
        grid_to_load = max(0, total_load - pv_to_load - storage_discharging_kw)
        grid_to_storage = max(0, storage_charging_kw - pv_to_storage)

        results.append({
            "timestamp": row["timestamp"],
            "hour": row["hour"],
            "period": period,
            "pv": pv_power * dt,
            "storage_charging": storage_charging_kw * dt,
            "storage_discharging": storage_discharging_kw * dt,
            "factory_load": factory * dt,
            "charging_load": charging_load_kw * dt,
            "grid_import": grid_import_kw * dt,
            "grid_export": grid_export_kw * dt,
            "grid_cost": grid_cost,
            "charging_revenue": charging_revenue,
            "pv_grid_revenue": pv_grid_revenue,
            "net_profit": net_profit,
            "pv_to_load": pv_to_load * dt,
            "pv_to_storage": pv_to_storage * dt,
            "pv_to_grid": pv_to_grid * dt,
            "grid_to_load": grid_to_load * dt,
            "grid_to_storage": grid_to_storage * dt,
        })
    return results

def simulate_no_storage(data):
    results = []
    dt = 5.0 / 60.0
    
    for row in data:
        period = get_tariff_period(row["hour"], row["minute"])
        grid_price = get_grid_price(row["timestamp"], row["hour"])
        charging_price = get_charging_price(row["timestamp"], row["hour"], row["minute"])
        
        pv_power = row["pv"]
        # 在真实数据中，电网功率 = 负载功率 + 储能功率 - 光伏功率
        # 如果没有储能，负载功率保持不变，储能功率为0
        # 那么，无储能的电网功率应该 = 负载功率 - 光伏功率
        # 由于原数据中 load 为负数表示耗电，grid 为负数表示买电
        # total_load_power = max(0, -row["load"])
        # 所以网电 = pv_power - total_load_power
        # 但有些时候还有损耗，为了更精确，无储能时的购电量 = 真实买电量 - 储能充电量 + 储能放电量
        # 或者说无储能电网买电量：
        
        storage_power = row["storage"]
        grid_power = row["grid"]
        
        # 移除储能的影响
        # 如果 storage_power < 0，代表储能在充电，这部分电是从电网买的或者光伏充的，如果没有储能，这部分就不会消耗。
        # 如果 storage_power > 0，代表储能在放电，如果没有储能，这部分就需要从电网买。
        # 因此，无储能时的电网功率： grid_power_no_storage = grid_power - storage_power
        grid_power_no_storage = grid_power - storage_power
        
        # 如果 grid_power_no_storage < 0，表示从电网买电
        grid_needed_kw = max(0, -grid_power_no_storage)
        # 如果 grid_power_no_storage > 0，表示余电上网
        pv_surplus_kw = max(0, grid_power_no_storage)
        
        # 修复: 真实的负载消耗 = 光伏发电 + 储能放电 - 电网输出
        total_load_kw = pv_power + storage_power - grid_power
        total_load = max(0, total_load_kw)
        
        factory = get_factory_load(row["hour"], row["minute"])
        charging_load_kw = max(0, total_load - factory)
        
        grid_cost = grid_needed_kw * dt * grid_price
        charging_revenue = charging_load_kw * dt * charging_price
        pv_grid_revenue = pv_surplus_kw * dt * 0.10
        
        net_profit = charging_revenue + pv_grid_revenue - grid_cost
        
        results.append({
            "timestamp": row["timestamp"],
            "hour": row["hour"],
            "period": period,
            "pv": pv_power * dt,
            "factory_load": factory * dt,
            "charging_load": charging_load_kw * dt,
            "grid_import": grid_needed_kw * dt,
            "pv_surplus": pv_surplus_kw * dt,
            "grid_cost": grid_cost,
            "charging_revenue": charging_revenue,
            "pv_grid_revenue": pv_grid_revenue,
            "net_profit": net_profit,
        })
    return results

def aggregate_by_period(results):
    periods = {"谷": {}, "平": {}, "峰": {}}
    for key in ["pv", "storage_charging", "storage_discharging", "factory_load", "charging_load", "grid_import", "grid_export", "grid_cost", "charging_revenue", "pv_grid_revenue", "net_profit", "pv_to_load", "pv_to_storage", "pv_to_grid", "grid_to_load", "grid_to_storage"]:
        periods["谷"][key] = 0
        periods["平"][key] = 0
        periods["峰"][key] = 0
    
    for r in results:
        p = r["period"]
        for key in periods[p]:
            periods[p][key] += r.get(key, 0)
    return periods

def aggregate_by_hour(results):
    hours = {}
    for h in range(24):
        hours[h] = {"pv": 0, "storage_charging": 0, "storage_discharging": 0, "factory_load": 0, "charging_load": 0, "grid_import": 0, "grid_export": 0, "grid_cost": 0, "charging_revenue": 0, "pv_grid_revenue": 0, "net_profit": 0, "pv_to_load": 0, "pv_to_storage": 0, "pv_to_grid": 0, "grid_to_load": 0, "grid_to_storage": 0}
    
    for r in results:
        h = r["hour"]
        for key in hours[h]:
            hours[h][key] += r.get(key, 0)
    return hours

def generate_report(data, report_path, model_name, date_str):
    with_storage_results = simulate_with_storage(data)
    no_storage_results = simulate_no_storage(data)
    
    with_storage_periods = aggregate_by_period(with_storage_results)
    no_storage_periods = aggregate_by_period(no_storage_results)
    
    with_storage_hourly = aggregate_by_hour(with_storage_results)
    
    total_pv = sum(r["pv"] for r in with_storage_results)
    total_storage_charging = sum(r["storage_charging"] for r in with_storage_results)
    total_storage_discharging = sum(r["storage_discharging"] for r in with_storage_results)
    total_grid_import = sum(r["grid_import"] for r in with_storage_results)
    total_grid_export = sum(r["grid_export"] for r in with_storage_results)
    
    total_net_profit_01 = sum(r["net_profit"] for r in with_storage_results)
    total_charging_revenue = sum(r["charging_revenue"] for r in with_storage_results)
    total_pv_grid_revenue_01 = sum(r["pv_grid_revenue"] for r in with_storage_results)
    total_grid_cost = sum(r["grid_cost"] for r in with_storage_results)
    
    pv_grid_revenues_02 = total_grid_export * 0.20
    pv_grid_revenues_035 = total_grid_export * 0.35
    
    total_net_profit_02 = total_charging_revenue + pv_grid_revenues_02 - total_grid_cost
    total_net_profit_035 = total_charging_revenue + pv_grid_revenues_035 - total_grid_cost
    
    no_storage_net_profit = sum(r["net_profit"] for r in no_storage_results)
    no_storage_pv_surplus = sum(r["pv_surplus"] for r in no_storage_results)
    no_storage_charging_revenue = sum(r["charging_revenue"] for r in no_storage_results)
    no_storage_grid_cost = sum(r["grid_cost"] for r in no_storage_results)
    
    # 无储能情况下的基础利润实际上是：充电桩收入 + 光伏余电上网收入 - 从电网买电的成本
    # 之前这里是直接使用了各个部分重新计算，但对于不同电价，应该只调整光伏余电上网的电价
    no_storage_net_profit_02 = no_storage_charging_revenue + no_storage_pv_surplus * 0.20 - no_storage_grid_cost
    no_storage_net_profit_035 = no_storage_charging_revenue + no_storage_pv_surplus * 0.35 - no_storage_grid_cost
    
    storage_gain_01 = total_net_profit_01 - no_storage_net_profit
    storage_gain_02 = total_net_profit_02 - no_storage_net_profit_02
    storage_gain_035 = total_net_profit_035 - no_storage_net_profit_035
    
    lines = []
    lines.append(f"# 每日收益分析报告")
    lines.append(f"")
    lines.append(f"**分析日期**: {date_str}")
    lines.append(f"**数据文件**: 日报表_0.12MW#0.257MWh工商储项目_{date_str}.csv")
    lines.append(f"")
    
    lines.append("## 1. 基础报表 (光伏上网电价 0.1元/度)")
    lines.append(f"### 1.1 分时段汇总 (峰/平/谷)")
    lines.append(f"")
    lines.append(f"| 时段   |   光伏产电量(度) |   储能充电量(度) |   储能放电量(度) |   工厂用电量(度) |   充电桩用电量(度) |   向电网买电量(度) |   向电网卖电量(度) |   时段净利润(0.1元) |")
    lines.append(f"|:-----|-----------:|-----------:|-----------:|-----------:|------------:|------------:|------------:|--------------:|")
    for period in ["峰", "平", "谷"]:
        p = with_storage_periods[period]
        lines.append(f"| {period}    |   {p['pv']:.3f}   |   {p['storage_charging']:.3f}  |    {p['storage_discharging']:.3f} |        {p['factory_load']:.0f} |     {p['charging_load']:.3f} |     {p['grid_import']:.3f} |   {p['grid_export']:.3f}   |      {p['net_profit']:.3f}  |")
    lines.append(f"")
    
    lines.append("### 1.2 光伏发电的流向与时间分布")
    lines.append(f"")
    lines.append(f"| 时段 | 光伏总产电(度) | 直接消纳(度) | 充入储能(度) | 余电上网(度) |")
    lines.append(f"|:---|---:|---:|---:|---:|")
    for period in ["峰", "平", "谷"]:
        p = with_storage_periods[period]
        lines.append(f"| {period} | {p['pv']:.3f} | {p['pv_to_load']:.3f} | {p['pv_to_storage']:.3f} | {p['pv_to_grid']:.3f} |")
    lines.append(f"")

    lines.append("### 1.3 电网购电的流向与时间分布")
    lines.append(f"")
    lines.append(f"| 时段 | 电网总购电(度) | 满足负载(度) | 充入储能(度) |")
    lines.append(f"|:---|---:|---:|---:|")
    for period in ["峰", "平", "谷"]:
        p = with_storage_periods[period]
        lines.append(f"| {period} | {p['grid_import']:.3f} | {p['grid_to_load']:.3f} | {p['grid_to_storage']:.3f} |")
    lines.append(f"")
    
    lines.append("### 1.4 每小时详细报表")
    lines.append(f"")
    lines.append(f"| 小时    |   光伏产电量(度) |   储能充电量(度) |   储能放电量(度) |   工厂用电量(度) |   充电桩用电量(度) |   向电网买电量(度) |   向电网卖电量(度) |   时段净利润(0.1元) |")
    lines.append(f"|:------|-----------:|-----------:|-----------:|-----------:|------------:|------------:|------------:|--------------:|")
    for h in range(24):
        hr = with_storage_hourly[h]
        lines.append(f"| {h:02d}:00 |   {hr['pv']:.3f}    |  {hr['storage_charging']:.3f}   |    {hr['storage_discharging']:.3f}   |          {hr['factory_load']:.0f} |    {hr['charging_load']:.3f}  |  {hr['grid_import']:.3f}    |     {hr['grid_export']:.3f}      |      {hr['net_profit']:.3f} |")
    lines.append(f"")
    
    lines.append("## 2. 核心收益结论 (业主视角)")
    lines.append(f"")
    
    # 计算光伏纯卖电收益
    pv_total_gen = sum(h["pv"] for h in with_storage_hourly.values())
    pv_sell_01 = pv_total_gen * 0.1
    pv_sell_02 = pv_total_gen * 0.2
    pv_sell_035 = pv_total_gen * 0.35
    
    lines.append("### 【场景 A：光伏上网电价 0.1 元/度】")
    lines.append(f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 今日理论可产生 **{pv_sell_01:.2f}** 元。")
    lines.append(f"2. **光伏+充电站原有收益** (无储能情况): 光伏直发直用叠加充电站及工厂省电，今日基础总利润为 **{no_storage_net_profit:.2f}** 元。")
    lines.append(f"3. **当前储能系统(250度)实际额外增益**: 本套正在运行的储能系统通过峰谷套利及减少弃光，今日实际为您**额外创收** **{storage_gain_01:.2f}** 元。(最终今日实际总利润: **{total_net_profit_01:.2f}** 元)")
    lines.append(f"")
    
    lines.append("### 【场景 B：光伏上网电价 0.2 元/度】")
    lines.append(f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 今日理论可产生 **{pv_sell_02:.2f}** 元。")
    lines.append(f"2. **光伏+充电站原有收益** (无储能情况): 光伏直发直用叠加充电站及工厂省电，今日基础总利润为 **{no_storage_net_profit:.2f}** 元。")
    lines.append(f"3. **当前储能系统(250度)实际额外增益**: 本套正在运行的储能系统通过峰谷套利及减少弃光，今日实际为您**额外创收** **{storage_gain_02:.2f}** 元。(最终今日实际总利润: **{total_net_profit_02:.2f}** 元)")
    lines.append(f"")
    
    lines.append("### 【场景 C：光伏上网电价 0.35 元/度】")
    lines.append(f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 今日理论可产生 **{pv_sell_035:.2f}** 元。")
    lines.append(f"2. **光伏+充电站原有收益** (无储能情况): 光伏直发直用叠加充电站及工厂省电，今日基础总利润为 **{no_storage_net_profit:.2f}** 元。")
    lines.append(f"3. **当前储能系统(250度)实际额外增益**: 本套正在运行的储能系统通过峰谷套利及减少弃光，今日实际为您**额外创收** **{storage_gain_035:.2f}** 元。(最终今日实际总利润: **{total_net_profit_035:.2f}** 元)")
    lines.append(f"")
    
    lines.append("---")
    lines.append(f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        
    # 更新总表
    summary_path = os.path.join(REPORT_DIR, "总收益分析报表.md")
    file_exists = os.path.exists(summary_path)
    
    with open(summary_path, 'a' if file_exists else 'w', encoding='utf-8') as f:
        if not file_exists:
            f.write("# 总收益分析报表\n\n")
            f.write("| 日期 | 总收益(光伏电价0.1元/度) | 储能额外收益(光伏电价0.1元/度) | 总收益(光伏电价0.2元/度) | 储能额外收益(光伏电价0.2元/度) | 总收益(光伏电价0.35元/度) | 储能额外收益(光伏电价0.35元/度) |\n")
            f.write("|:---|---:|---:|---:|---:|---:|---:|\n")
            
        f.write(f"| {date_str} | {total_net_profit_01:.2f} | {storage_gain_01:.2f} | {total_net_profit_02:.2f} | {storage_gain_02:.2f} | {total_net_profit_035:.2f} | {storage_gain_035:.2f} |\n")
    
    return report_path

def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    
    if len(sys.argv) > 2:
        csv_path = sys.argv[1]
        date_str = sys.argv[2]
    else:
        csv_path = CSV_PATH
        date_str = "20260421"
    
    data = read_csv(csv_path)
    
    report_filename = f"每日收益分析报告_{date_str}.md"
    report_path = os.path.join(REPORT_DIR, report_filename)
    
    generate_report(data, report_path, MODEL_NAME, date_str)
    
    print(f"报告已生成：{report_path}")

if __name__ == "__main__":
    main()
