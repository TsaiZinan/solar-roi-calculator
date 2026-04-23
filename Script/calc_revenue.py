import pandas as pd
import numpy as np
import sys
import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from pricing import get_ev_sell_price as _get_ev_sell_price, get_grid_buy_price as _get_grid_buy_price

def get_period_type(h):
    if 0 <= h < 8: return "谷"
    if 10 <= h < 12 or 14 <= h < 19: return "峰"
    return "平"

def get_grid_buy_price(date_str, h):
    return _get_grid_buy_price(date_str, h)

def get_ev_sell_price(date_str, h):
    return _get_ev_sell_price(date_str, h)

def process_data(csv_path):
    df = pd.read_csv(csv_path)
    df['时间'] = pd.to_datetime(df['时间'])
    dt = 5 / 60.0
    
    hourly_stats = []
    
    for h in range(24):
        hour_df = df[df['时间'].dt.hour == h]
        if hour_df.empty:
            hourly_stats.append({
                'hour': h, 'period': get_period_type(h),
                'pv': 0, 'ess_c': 0, 'ess_d': 0, 'fac': 0, 'ev': 0,
                'buy_w': 0, 'sell_w': 0, 'buy_no': 0, 'sell_no': 0
            })
            continue
            
        pv = 0; ess_c = 0; ess_d = 0; fac = 0; ev = 0
        buy_w = 0; sell_w = 0; buy_no = 0; sell_no = 0
        pv_to_load = 0; pv_to_ess = 0; pv_to_grid = 0
        grid_to_load = 0; grid_to_ess = 0
        
        for _, row in hour_df.iterrows():
            r_pv = max(0, row.get('光伏发电功率(kW)', 0))
            
            # 负载功率在表里其实是净功率(正数表示光伏余电，负数表示缺电流入)
            # 真实的系统总负载 = 光伏发电 - 表里的负载功率
            raw_load = row.get('负载功率(kW)', 0)
            r_total_load = max(0, r_pv - raw_load)
            
            r_fac = 50.0 if ((7 <= h < 12) or (13 <= h < 18)) else 0.0
            r_ev = max(0, r_total_load - r_fac)
            
            r_ess = row.get('储能有功功率(kW)', 0)
            r_ess_c = abs(r_ess) if r_ess < 0 else 0
            r_ess_d = r_ess if r_ess > 0 else 0
            
            grid_w = r_total_load - r_pv - r_ess
            grid_no = r_total_load - r_pv
            
            r_buy_w = max(0, grid_w)
            r_sell_w = max(0, -grid_w)
            
            # 流向计算
            # 1. 光伏流向: 优先满足负载，剩余充储能，再剩余上网
            r_pv_to_load = min(r_pv, r_total_load)
            r_pv_to_ess = min(max(0, r_pv - r_pv_to_load), r_ess_c)
            r_pv_to_grid = max(0, r_pv - r_pv_to_load - r_pv_to_ess)
            
            # 2. 电网购电流向: 满足储能充电需求(除去光伏已充部分)，剩余满足负载
            r_grid_to_ess = r_ess_c - r_pv_to_ess
            r_grid_to_load = max(0, r_buy_w - r_grid_to_ess)
            
            pv += r_pv * dt
            ess_c += r_ess_c * dt
            ess_d += r_ess_d * dt
            fac += r_fac * dt
            ev += r_ev * dt
            buy_w += r_buy_w * dt
            sell_w += r_sell_w * dt
            buy_no += max(0, grid_no) * dt
            sell_no += max(0, -grid_no) * dt
            
            pv_to_load += r_pv_to_load * dt
            pv_to_ess += r_pv_to_ess * dt
            pv_to_grid += r_pv_to_grid * dt
            grid_to_load += r_grid_to_load * dt
            grid_to_ess += r_grid_to_ess * dt
            
        hourly_stats.append({
            'hour': h, 'period': get_period_type(h),
            'pv': pv, 'ess_c': ess_c, 'ess_d': ess_d, 'fac': fac, 'ev': ev,
            'buy_w': buy_w, 'sell_w': sell_w, 'buy_no': buy_no, 'sell_no': sell_no,
            'pv_to_load': pv_to_load, 'pv_to_ess': pv_to_ess, 'pv_to_grid': pv_to_grid,
            'grid_to_load': grid_to_load, 'grid_to_ess': grid_to_ess
        })
        
    return df['时间'].dt.strftime('%Y%m%d').iloc[0], hourly_stats

def calc_profit_for_price(date_str, stats, pv_price):
    total_w = 0
    total_no = 0
    total_pv_rev = 0
    
    for st in stats:
        h = st['hour']
        buy_p = get_grid_buy_price(date_str, h)
        sell_ev_p = get_ev_sell_price(date_str, h)
        
        rev_ev = st['ev'] * sell_ev_p
        rev_fac = st['fac'] * buy_p
        
        cost_w = st['buy_w'] * buy_p
        rev_w = st['sell_w'] * pv_price + rev_ev + rev_fac
        profit_w = rev_w - cost_w
        
        cost_no = st['buy_no'] * buy_p
        rev_no = st['sell_no'] * pv_price + rev_ev + rev_fac
        profit_no = rev_no - cost_no
        
        total_w += profit_w
        total_no += profit_no
        total_pv_rev += st['pv'] * pv_price
        
    return total_w, total_no, total_pv_rev

def generate_report(csv_path):
    date_str, stats = process_data(csv_path)
    
    # Calculate base profit (0.1) for tables
    for st in stats:
        h = st['hour']
        buy_p = get_grid_buy_price(date_str, h)
        sell_ev_p = get_ev_sell_price(date_str, h)
        
        rev_ev = st['ev'] * sell_ev_p
        rev_fac = st['fac'] * buy_p
        cost_w = st['buy_w'] * buy_p
        rev_w = st['sell_w'] * 0.1 + rev_ev + rev_fac
        st['profit_w_01'] = rev_w - cost_w

    # Group by period
    periods = {'峰': {}, '平': {}, '谷': {}}
    for p in periods:
        periods[p] = {k: 0 for k in ['pv', 'ess_c', 'ess_d', 'fac', 'ev', 'buy_w', 'sell_w', 'profit_w_01',
                                     'pv_to_load', 'pv_to_ess', 'pv_to_grid', 'grid_to_load', 'grid_to_ess']}
        
    for st in stats:
        if 'pv_to_load' not in st:
            continue
        p = st['period']
        for k in periods[p].keys():
            periods[p][k] += st.get(k, 0)
            
    # Markdown Generation
    lines = []
    lines.append(f"# 每日收益分析报告 - {date_str}")
    lines.append("")
    lines.append("## 1. 基础报表 (光伏上网电价 0.1元/度)")
    lines.append("### 1.1 分时段汇总 (峰/平/谷)")
    lines.append("| 时段 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 向电网买电量(度) | 向电网卖电量(度) | 时段净利润(0.1元) |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p in ['峰', '平', '谷']:
        d = periods[p]
        lines.append(f"| {p} | {d['pv']:.4g} | {d['ess_c']:.4g} | {d['ess_d']:.4g} | {d['fac']:.4g} | {d['ev']:.4g} | {d['buy_w']:.4g} | {d['sell_w']:.4g} | {d['profit_w_01']:.4g} |")
        
    lines.append("\n### 1.2 光伏发电的流向与时间分布")
    lines.append("| 时段 | 光伏总产电(度) | 直接消纳(负载) | 充入储能 | 余电上网(卖电) |")
    lines.append("|:---|---:|---:|---:|---:|")
    for p in ['峰', '平', '谷']:
        d = periods[p]
        pv_tot = d['pv']
        if pv_tot > 0:
            pct_load = d['pv_to_load'] / pv_tot * 100
            pct_ess = d['pv_to_ess'] / pv_tot * 100
            pct_grid = d['pv_to_grid'] / pv_tot * 100
            lines.append(f"| {p} | {pv_tot:.4g} | {pct_load:.1f}% | {pct_ess:.1f}% | {pct_grid:.1f}% |")
        else:
            lines.append(f"| {p} | {pv_tot:.4g} | 0.0% | 0.0% | 0.0% |")

    lines.append("\n### 1.3 电网购电的流向与时间分布")
    lines.append("| 时段 | 电网总购电(度) | 满足负载 | 充入储能 |")
    lines.append("|:---|---:|---:|---:|")
    for p in ['峰', '平', '谷']:
        d = periods[p]
        buy_tot = d['buy_w']
        if buy_tot > 0:
            pct_load = d['grid_to_load'] / buy_tot * 100
            pct_ess = d['grid_to_ess'] / buy_tot * 100
            lines.append(f"| {p} | {buy_tot:.4g} | {pct_load:.1f}% | {pct_ess:.1f}% |")
        else:
            lines.append(f"| {p} | {buy_tot:.4g} | 0.0% | 0.0% |")

    lines.append("\n### 1.4 每小时详细报表")
    lines.append("| 小时 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 向电网买电量(度) | 向电网卖电量(度) | 时段净利润(0.1元) |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for st in stats:
        lines.append(f"| {st['hour']:02d}:00 | {st['pv']:.4g} | {st['ess_c']:.4g} | {st['ess_d']:.4g} | {st['fac']:.4g} | {st['ev']:.4g} | {st['buy_w']:.4g} | {st['sell_w']:.4g} | {st['profit_w_01']:.4g} |")
        
    lines.append("\n## 2. 核心收益结论 (业主视角)")
    
    scenarios = [
        ('A', 0.1),
        ('B', 0.2),
        ('C', 0.35)
    ]
    
    for name, price in scenarios:
        tot_w, tot_no, pv_rev = calc_profit_for_price(date_str, stats, price)
        extra = tot_w - tot_no
        
        lines.append(f"\n### 【场景 {name}：光伏上网电价 {price} 元/度】")
        lines.append(f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 今日理论可产生 **{pv_rev:.2f}** 元。")
        lines.append(f"2. **光伏+充电站原有收益** (无储能情况): 光伏直发直用叠加充电站及工厂省电，今日基础总利润为 **{tot_no:.2f}** 元。")
        lines.append(f"3. **当前储能系统(250度)实际额外增益**: 本套正在运行的储能系统通过峰谷套利及减少弃光，今日实际为您**额外创收** **{extra:.2f}** 元。(最终今日实际总利润: **{tot_w:.2f}** 元)")
        
        # 保存用于总表的变量
        if price == 0.1:
            total_01 = tot_w
            extra_01 = extra
        elif price == 0.2:
            total_02 = tot_w
            extra_02 = extra
        elif price == 0.35:
            total_035 = tot_w
            extra_035 = extra
        
    out_path = f"报告/每日收益分析报告_{date_str}.md"
    with open(out_path, 'w') as f:
        f.write('\n'.join(lines))
        
    print(out_path)

    # 更新总表
    summary_path = "报告/总收益分析报表.md"
    file_exists = os.path.exists(summary_path)
    
    with open(summary_path, 'a' if file_exists else 'w', encoding='utf-8') as f:
        if not file_exists:
            f.write("# 总收益分析报表\n\n")
            f.write("| 日期 | 总收益(光伏电价0.1元/度) | 储能额外收益(光伏电价0.1元/度) | 总收益(光伏电价0.2元/度) | 储能额外收益(光伏电价0.2元/度) | 总收益(光伏电价0.35元/度) | 储能额外收益(光伏电价0.35元/度) |\n")
            f.write("|:---|---:|---:|---:|---:|---:|---:|\n")
            
        f.write(f"| {date_str} | {total_01:.2f} | {extra_01:.2f} | {total_02:.2f} | {extra_02:.2f} | {total_035:.2f} | {extra_035:.2f} |\n")
    print(summary_path)

if __name__ == "__main__":
    csv_file = sys.argv[1]
    os.makedirs("报告", exist_ok=True)
    generate_report(csv_file)
