import pandas as pd
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    PRIMARY_ESS,
    PV_PRICE_SCENARIOS,
    SUMMARY_REPORT_PATH,
    ensure_report_dir,
    get_daily_report_path,
    get_factory_load,
)
from init_summary import rebuild_summary_table
from pricing import (
    get_ev_sell_price as _get_ev_sell_price,
    get_grid_buy_price as _get_grid_buy_price,
    get_grid_period_map as _get_grid_period_map,
    get_period_display_order as _get_period_display_order,
)

def get_grid_buy_price(date_str, h):
    return _get_grid_buy_price(date_str, h)

def get_ev_sell_price(date_str, h):
    return _get_ev_sell_price(date_str, h)

def get_grid_period_map(date_str):
    return _get_grid_period_map(date_str)

def get_period_display_order(date_str):
    return _get_period_display_order(date_str)

def process_data(csv_path):
    df = pd.read_csv(csv_path)
    df['时间'] = pd.to_datetime(df['时间'])
    dt = 5 / 60.0
    date_str = df['时间'].dt.strftime('%Y%m%d').iloc[0]
    period_map = get_grid_period_map(date_str)
    
    hourly_stats = []
    
    for h in range(24):
        hour_df = df[df['时间'].dt.hour == h]
        if hour_df.empty:
            hourly_stats.append({
                'hour': h, 'period': period_map.get(h, '平'),
                'pv': 0, 'ess_c': 0, 'ess_d': 0, 'fac': 0, 'ev': 0,
                'buy_w': 0, 'sell_w': 0, 'buy_no': 0, 'sell_no': 0,
                'factory_savings': 0,
            })
            continue
            
        pv = 0; ess_c = 0; ess_d = 0; fac = 0; ev = 0
        buy_w = 0; sell_w = 0; buy_no = 0; sell_no = 0
        pv_to_load = 0; pv_to_ess = 0; pv_to_grid = 0
        grid_to_load = 0; grid_to_ess = 0; factory_savings_total = 0
        
        for _, row in hour_df.iterrows():
            r_pv = max(0, row.get('光伏发电功率(kW)', 0))
            
            # 负载功率在表里其实是净功率(正数表示光伏余电，负数表示缺电流入)
            # 真实的系统总负载 = 光伏发电 - 表里的负载功率
            raw_load = row.get('负载功率(kW)', 0)
            r_total_load = max(0, r_pv - raw_load)
            
            r_fac = get_factory_load(h)
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
            factory_savings = r_fac * dt * get_grid_buy_price(date_str, h)
            
            pv_to_load += r_pv_to_load * dt
            pv_to_ess += r_pv_to_ess * dt
            pv_to_grid += r_pv_to_grid * dt
            grid_to_load += r_grid_to_load * dt
            grid_to_ess += r_grid_to_ess * dt
            
            factory_savings_total += factory_savings
            
        hourly_stats.append({
            'hour': h, 'period': period_map.get(h, '平'),
            'pv': pv, 'ess_c': ess_c, 'ess_d': ess_d, 'fac': fac, 'ev': ev,
            'buy_w': buy_w, 'sell_w': sell_w, 'buy_no': buy_no, 'sell_no': sell_no,
            'pv_to_load': pv_to_load, 'pv_to_ess': pv_to_ess, 'pv_to_grid': pv_to_grid,
            'grid_to_load': grid_to_load, 'grid_to_ess': grid_to_ess,
            'factory_savings': factory_savings_total,
        })
        
    return date_str, hourly_stats

def calc_profit_for_price(date_str, stats, pv_price):
    result = {
        'with_storage_total': 0,
        'without_storage_total': 0,
        'with_storage_cash': 0,
        'without_storage_cash': 0,
        'factory_savings': 0,
        'pv_revenue': 0,
    }
    
    for st in stats:
        h = st['hour']
        buy_p = get_grid_buy_price(date_str, h)
        sell_ev_p = get_ev_sell_price(date_str, h)
        
        rev_ev = st['ev'] * sell_ev_p
        rev_fac = st['fac'] * buy_p
        
        cost_w = st['buy_w'] * buy_p
        cash_profit_w = st['sell_w'] * pv_price + rev_ev - cost_w
        profit_w = cash_profit_w + rev_fac
        
        cost_no = st['buy_no'] * buy_p
        cash_profit_no = st['sell_no'] * pv_price + rev_ev - cost_no
        profit_no = cash_profit_no + rev_fac
        
        result['with_storage_total'] += profit_w
        result['without_storage_total'] += profit_no
        result['with_storage_cash'] += cash_profit_w
        result['without_storage_cash'] += cash_profit_no
        result['factory_savings'] += rev_fac
        result['pv_revenue'] += st['pv'] * pv_price
        
    result['extra_profit'] = result['with_storage_total'] - result['without_storage_total']
    return result

def generate_report(csv_path):
    date_str, stats = process_data(csv_path)
    period_order = get_period_display_order(date_str)
    
    # Calculate base profit (0.1) for tables
    for st in stats:
        h = st['hour']
        buy_p = get_grid_buy_price(date_str, h)
        sell_ev_p = get_ev_sell_price(date_str, h)
        
        rev_ev = st['ev'] * sell_ev_p
        rev_fac = st['fac'] * buy_p
        cost_w = st['buy_w'] * buy_p
        st['cash_profit_w_01'] = st['sell_w'] * 0.1 + rev_ev - cost_w
        st['profit_w_01'] = st['cash_profit_w_01'] + rev_fac
        st['factory_savings'] = rev_fac

    # Group by period
    periods = {}
    for p in period_order:
        periods[p] = {k: 0 for k in ['pv', 'ess_c', 'ess_d', 'fac', 'ev', 'buy_w', 'sell_w', 'profit_w_01',
                                     'factory_savings', 'pv_to_load', 'pv_to_ess', 'pv_to_grid', 'grid_to_load', 'grid_to_ess']}
        
    for st in stats:
        if 'pv_to_load' not in st:
            continue
        p = st['period']
        if p not in periods:
            periods[p] = {k: 0 for k in ['pv', 'ess_c', 'ess_d', 'fac', 'ev', 'buy_w', 'sell_w', 'profit_w_01',
                                         'factory_savings', 'pv_to_load', 'pv_to_ess', 'pv_to_grid', 'grid_to_load', 'grid_to_ess']}
        for k in periods[p].keys():
            periods[p][k] += st.get(k, 0)
            
    # Markdown Generation
    lines = []
    lines.append(f"# 每日收益分析报告 - {date_str}")
    lines.append("")
    lines.append(f"**数据文件**: {os.path.basename(csv_path)}")
    lines.append("")
    lines.append("## 1. 基础报表 (光伏上网电价 0.1元/度)")
    lines.append("### 1.1 分时段汇总 (按电价标签自动分组)")
    lines.append("| 时段 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 工厂省电收益(元) | 向电网买电量(度) | 向电网卖电量(度) | 时段经营收益(0.1元) |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p in period_order:
        d = periods[p]
        lines.append(f"| {p} | {d['pv']:.4g} | {d['ess_c']:.4g} | {d['ess_d']:.4g} | {d['fac']:.4g} | {d['ev']:.4g} | {d['factory_savings']:.4g} | {d['buy_w']:.4g} | {d['sell_w']:.4g} | {d['profit_w_01']:.4g} |")
        
    lines.append("\n### 1.2 光伏发电的流向与时间分布")
    lines.append("| 时段 | 光伏总产电(度) | 直接消纳(负载) | 充入储能 | 余电上网(卖电) |")
    lines.append("|:---|---:|---:|---:|---:|")
    for p in period_order:
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
    for p in period_order:
        d = periods[p]
        buy_tot = d['buy_w']
        if buy_tot > 0:
            pct_load = d['grid_to_load'] / buy_tot * 100
            pct_ess = d['grid_to_ess'] / buy_tot * 100
            lines.append(f"| {p} | {buy_tot:.4g} | {pct_load:.1f}% | {pct_ess:.1f}% |")
        else:
            lines.append(f"| {p} | {buy_tot:.4g} | 0.0% | 0.0% |")

    lines.append("\n### 1.4 每小时详细报表")
    lines.append("| 小时 | 时段 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 工厂省电收益(元) | 向电网买电量(度) | 向电网卖电量(度) | 时段经营收益(0.1元) |")
    lines.append("|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for st in stats:
        lines.append(f"| {st['hour']:02d}:00 | {st['period']} | {st['pv']:.4g} | {st['ess_c']:.4g} | {st['ess_d']:.4g} | {st['fac']:.4g} | {st['ev']:.4g} | {st['factory_savings']:.4g} | {st['buy_w']:.4g} | {st['sell_w']:.4g} | {st['profit_w_01']:.4g} |")
        
    lines.append("\n## 2. 核心收益结论 (业主视角)")
    
    for name, price in PV_PRICE_SCENARIOS:
        result = calc_profit_for_price(date_str, stats, price)
        
        lines.append(f"\n### 【场景 {name}：光伏上网电价 {price} 元/度】")
        lines.append(f"1. **光伏纯卖电收益** (假设光伏全额卖给电网): 今日理论可产生 **{result['pv_revenue']:.2f}** 元。")
        lines.append(f"2. **现金类收益(无储能)**: 充电桩收入叠加光伏上网收入并扣除购电成本，今日合计 **{result['without_storage_cash']:.2f}** 元。")
        lines.append(f"3. **工厂省电收益**: 光伏直发直用替代工厂购电，今日合计 **{result['factory_savings']:.2f}** 元。")
        lines.append(f"4. **经营总收益(无储能)**: 现金类收益加工厂省电收益后，今日合计 **{result['without_storage_total']:.2f}** 元。")
        lines.append(f"5. **{PRIMARY_ESS['label']}实际额外增益**: 本套正在运行的储能系统通过峰谷套利及减少弃光，今日实际为您**额外创收** **{result['extra_profit']:.2f}** 元。")
        lines.append(f"6. **含储能经营总收益**: 在当前储能运行结果下，今日实际总收益为 **{result['with_storage_total']:.2f}** 元。")
        
    out_path = get_daily_report_path(date_str)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
        
    print(out_path)
    rebuild_summary_table()
    print(SUMMARY_REPORT_PATH)

if __name__ == "__main__":
    csv_file = sys.argv[1]
    ensure_report_dir()
    generate_report(csv_file)
