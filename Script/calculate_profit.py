import pandas as pd
import numpy as np
import sys
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from pricing import get_ev_sell_price, get_grid_buy_price

def calculate_profit(csv_path, model_name=""):
    df = pd.read_csv(csv_path)
    df['时间'] = pd.to_datetime(df['时间'])
    date_str = df['时间'].iloc[0].strftime('%Y%m%d')
    
    df['真实总负载(kW)'] = df['光伏发电功率(kW)'] - df['负载功率(kW)']
    
    def get_factory_load(t):
        hour = t.hour
        if (7 <= hour < 12) or (13 <= hour < 18):
            return 50.0
        return 0.0
        
    df['工厂用电(kW)'] = df.apply(lambda row: min(max(row['真实总负载(kW)'], 0), get_factory_load(row['时间'])), axis=1)
    df['充电桩用电(kW)'] = df['真实总负载(kW)'] - df['工厂用电(kW)']
    df['充电桩用电(kW)'] = df['充电桩用电(kW)'].clip(lower=0)
    
    BATTERY_CAPACITY = 257.0
    MAX_POWER = 120.0
    STORAGE_EFFICIENCY = 0.95  # 充放电单向效率（假设双向综合效率约90%）
    
    current_soc = df['SOC(%)'].iloc[0] / 100.0
    current_energy = current_soc * BATTERY_CAPACITY
    
    dt = 5 / 60.0
    
    results = []
    
    for i, row in df.iterrows():
        t = row['时间']
        hour = t.hour
        pv = row['光伏发电功率(kW)']
        load = row['真实总负载(kW)']
        
        buy_from_grid = 0.0
        sell_to_grid = 0.0
        battery_charge = 0.0
        battery_discharge = 0.0
        
        is_valley = (0 <= hour < 8)
        is_peak = (10 <= hour < 12) or (14 <= hour < 19)
        
        grid_buy_price = get_grid_buy_price(t.strftime('%Y-%m-%d'), hour)
            
        ev_sell_price = get_ev_sell_price(t.strftime('%Y-%m-%d'), hour)
                
        net_load = load - pv
        
        # 有储能系统的情形
        if is_valley:
            space = BATTERY_CAPACITY - current_energy
            max_charge = min(MAX_POWER, space / (dt * STORAGE_EFFICIENCY))
            battery_charge = max_charge
            current_energy += battery_charge * dt * STORAGE_EFFICIENCY
            
            if net_load > 0:
                buy_from_grid = net_load + battery_charge
            else:
                excess_pv = -net_load
                buy_from_grid = battery_charge
                sell_to_grid = excess_pv
        else:
            if net_load > 0:
                available_energy = current_energy
                max_discharge = min(MAX_POWER, available_energy / (dt / STORAGE_EFFICIENCY))
                max_discharge = min(max_discharge, net_load)
                
                battery_discharge = max_discharge
                current_energy -= battery_discharge * dt / STORAGE_EFFICIENCY
                
                deficit = net_load - battery_discharge
                if deficit > 0:
                    buy_from_grid = deficit
            else:
                excess_pv = -net_load
                space = BATTERY_CAPACITY - current_energy
                max_charge = min(MAX_POWER, space / (dt * STORAGE_EFFICIENCY))
                max_charge = min(max_charge, excess_pv)
                
                battery_charge = max_charge
                current_energy += battery_charge * dt * STORAGE_EFFICIENCY
                
                remaining_pv = excess_pv - battery_charge
                if remaining_pv > 0:
                    sell_to_grid = remaining_pv
                    
        cost_grid = buy_from_grid * dt * grid_buy_price
        rev_grid_01 = sell_to_grid * dt * 0.10
        rev_grid_02 = sell_to_grid * dt * 0.20
        rev_grid_035 = sell_to_grid * dt * 0.35
        rev_ev = row['充电桩用电(kW)'] * dt * ev_sell_price
        rev_factory = row['工厂用电(kW)'] * dt * grid_buy_price
        
        # 无储能系统的情形 (baseline)
        no_ess_buy_from_grid = 0.0
        no_ess_sell_to_grid = 0.0
        if net_load > 0:
            no_ess_buy_from_grid = net_load
        else:
            no_ess_sell_to_grid = -net_load
            
        no_ess_cost = no_ess_buy_from_grid * dt * grid_buy_price
        no_ess_rev_grid_01 = no_ess_sell_to_grid * dt * 0.10
        no_ess_rev_grid_02 = no_ess_sell_to_grid * dt * 0.20
        no_ess_rev_grid_035 = no_ess_sell_to_grid * dt * 0.35
        
        results.append({
            '时间': t,
            '时段': '谷' if is_valley else ('峰' if is_peak else '平'),
            '光伏产电量(度)': pv * dt,
            '工厂用电量(度)': row['工厂用电(kW)'] * dt,
            '充电桩用电量(度)': row['充电桩用电(kW)'] * dt,
            '储能充电量(度)': battery_charge * dt,
            '储能放电量(度)': battery_discharge * dt,
            '向电网买电量(度)': buy_from_grid * dt,
            '向电网卖电量(度)': sell_to_grid * dt,
            '买电成本(元)': cost_grid,
            '充电桩收入(元)': rev_ev,
            '卖光伏电收入(0.1元)': rev_grid_01,
            '卖光伏电收入(0.2元)': rev_grid_02,
            '卖光伏电收入(0.35元)': rev_grid_035,
            '工厂省电收益(元)': rev_factory,
            '无储能_买电成本': no_ess_cost,
            '无储能_卖光伏收入(0.1元)': no_ess_rev_grid_01,
            '无储能_卖光伏收入(0.2元)': no_ess_rev_grid_02,
            '无储能_卖光伏收入(0.35元)': no_ess_rev_grid_035
        })
        
    res_df = pd.DataFrame(results)
    
    # 净利润计算
    res_df['时段净利润(0.1元)'] = res_df['充电桩收入(元)'] + res_df['卖光伏电收入(0.1元)'] + res_df['工厂省电收益(元)'] - res_df['买电成本(元)']
    res_df['时段净利润(0.2元)'] = res_df['充电桩收入(元)'] + res_df['卖光伏电收入(0.2元)'] + res_df['工厂省电收益(元)'] - res_df['买电成本(元)']
    res_df['时段净利润(0.35元)'] = res_df['充电桩收入(元)'] + res_df['卖光伏电收入(0.35元)'] + res_df['工厂省电收益(元)'] - res_df['买电成本(元)']
    
    res_df['无储能净利润(0.1元)'] = res_df['充电桩收入(元)'] + res_df['无储能_卖光伏收入(0.1元)'] + res_df['工厂省电收益(元)'] - res_df['无储能_买电成本']
    res_df['无储能净利润(0.2元)'] = res_df['充电桩收入(元)'] + res_df['无储能_卖光伏收入(0.2元)'] + res_df['工厂省电收益(元)'] - res_df['无储能_买电成本']
    res_df['无储能净利润(0.35元)'] = res_df['充电桩收入(元)'] + res_df['无储能_卖光伏收入(0.35元)'] + res_df['工厂省电收益(元)'] - res_df['无储能_买电成本']
    
    cols_to_sum = ['光伏产电量(度)', '储能充电量(度)', '储能放电量(度)', '工厂用电量(度)', '充电桩用电量(度)', '向电网买电量(度)', '向电网卖电量(度)', '时段净利润(0.1元)']
    summary = res_df.groupby('时段')[cols_to_sum].sum().reset_index()
    
    order = {'峰': 0, '平': 1, '谷': 2}
    summary['order'] = summary['时段'].map(order)
    summary = summary.sort_values('order').drop(columns=['order'])
    
    # 每小时汇总表
    res_df['小时'] = res_df['时间'].dt.hour.apply(lambda x: f"{x:02d}:00")
    hourly_summary = res_df.groupby('小时')[cols_to_sum].sum().reset_index()
    
    total_profit_01 = res_df['时段净利润(0.1元)'].sum()
    total_profit_02 = res_df['时段净利润(0.2元)'].sum()
    total_profit_035 = res_df['时段净利润(0.35元)'].sum()
    
    baseline_profit_01 = res_df['无储能净利润(0.1元)'].sum()
    baseline_profit_02 = res_df['无储能净利润(0.2元)'].sum()
    baseline_profit_035 = res_df['无储能净利润(0.35元)'].sum()
    
    ess_extra_profit_01 = total_profit_01 - baseline_profit_01
    ess_extra_profit_02 = total_profit_02 - baseline_profit_02
    ess_extra_profit_035 = total_profit_035 - baseline_profit_035
    
    report_content = f"# 每日收益分析报告"
    if model_name:
        report_content += f" ({model_name})"
    report_content += f" - {date_str}\n\n"
    
    report_content += "## 1. 基础报表 (光伏上网电价 0.1元/度)\n"
    report_content += "### 1.1 分时段汇总 (峰/平/谷)\n"
    report_content += summary.to_markdown(index=False) + "\n\n"
    
    report_content += "### 1.2 每小时详细报表\n"
    report_content += hourly_summary.to_markdown(index=False) + "\n\n"
    
    total_pv_gen = res_df['光伏产电量(度)'].sum()
    all_sell_01 = total_pv_gen * 0.10
    all_sell_02 = total_pv_gen * 0.20
    
    report_content += f"## 2. 核心收益结论 (业主视角)\n\n"
    
    report_content += f"### 【场景 A：光伏上网电价 0.1 元/度】\n"
    report_content += f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 每日可产生 **{all_sell_01:.2f}** 元。\n"
    report_content += f"2. **光伏+充电站原有收益** (无储能情况): 光伏直发直用叠加充电站及工厂省电，每日总利润提升至 **{baseline_profit_01:.2f}** 元。\n"
    report_content += f"3. **加装 250度 储能后的额外增益**: 储能系统通过峰谷套利及减少弃光，每日能让你**额外多赚** **{ess_extra_profit_01:.2f}** 元。(最终每日总利润: **{total_profit_01:.2f}** 元)\n\n"
    
    report_content += f"### 【场景 B：光伏上网电价 0.2 元/度】\n"
    report_content += f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 每日可产生 **{all_sell_02:.2f}** 元。\n"
    report_content += f"2. **光伏+充电站原有收益** (无储能情况): 光伏直发直用叠加充电站及工厂省电，每日总利润提升至 **{baseline_profit_02:.2f}** 元。\n"
    report_content += f"3. **加装 250度 储能后的额外增益**: 储能系统通过峰谷套利及减少弃光，每日能让你**额外多赚** **{ess_extra_profit_02:.2f}** 元。(最终每日总利润: **{total_profit_02:.2f}** 元)\n\n"
    
    report_content += f"### 【场景 C：光伏上网电价 0.35 元/度】\n"
    report_content += f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 每日可产生 **{all_sell_02 * (0.35/0.20) if all_sell_02 > 0 else 0:.2f}** 元。\n"
    report_content += f"2. **光伏+充电站原有收益** (无储能情况): 光伏直发直用叠加充电站及工厂省电，每日总利润提升至 **{baseline_profit_035:.2f}** 元。\n"
    report_content += f"3. **加装 250度 储能后的额外增益**: 储能系统通过峰谷套利及减少弃光，每日能让你**额外多赚** **{ess_extra_profit_035:.2f}** 元。(最终每日总利润: **{total_profit_035:.2f}** 元)\n\n"
    
    print(report_content)
    
    # 写入文件
    report_dir = "/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/报告"
    os.makedirs(report_dir, exist_ok=True)
    if model_name:
        report_filename = f"每日收益分析报告_{model_name}_{date_str}.md"
    else:
        report_filename = f"每日收益分析报告_{date_str}.md"
    report_path = os.path.join(report_dir, report_filename)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
        
    print(f"\n>> 报告已生成并保存至: {report_path}")

    # 更新总表
    summary_path = os.path.join(report_dir, "总收益分析报表.md")
    file_exists = os.path.exists(summary_path)
    
    with open(summary_path, 'a' if file_exists else 'w', encoding='utf-8') as f:
        if not file_exists:
            f.write("# 总收益分析报表\n\n")
            f.write("| 日期 | 总收益(光伏电价0.1元/度) | 储能额外收益(光伏电价0.1元/度) | 总收益(光伏电价0.2元/度) | 储能额外收益(光伏电价0.2元/度) | 总收益(光伏电价0.35元/度) | 储能额外收益(光伏电价0.35元/度) |\n")
            f.write("|:---|---:|---:|---:|---:|---:|---:|\n")
            
        f.write(f"| {date_str} | {total_profit_01:.2f} | {ess_extra_profit_01:.2f} | {total_profit_02:.2f} | {ess_extra_profit_02:.2f} | {total_profit_035:.2f} | {ess_extra_profit_035:.2f} |\n")
    print(f">> 汇总结果已更新至: {summary_path}")

if __name__ == '__main__':
    csv_path = sys.argv[1] if len(sys.argv) > 1 else '/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/数据/20260421/日报表_广东汕头市雅威机电实业0.12MW#0.257MWh工商储项目_20260421152008.csv'
    model_name = sys.argv[2] if len(sys.argv) > 2 else ""
    calculate_profit(csv_path, model_name)
