import pandas as pd
import sys
import os
import json
import re
from datetime import datetime
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import (
    PRIMARY_ESS,
    PV_PRICE_SCENARIOS,
    SUMMARY_REPORT_PATH,
    ensure_report_dir,
    get_storage_system_for_date,
    get_daily_report_path,
    get_daily_json_path,
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


def _round_value(value, digits=4):
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, list):
        return [_round_value(item, digits) for item in value]
    if isinstance(value, dict):
        return {key: _round_value(val, digits) for key, val in value.items()}
    return value


def _format_capacity_label(capacity_kwh):
    rounded = round(capacity_kwh)
    if abs(capacity_kwh - rounded) < 1e-9:
        return str(int(rounded))
    return f"{capacity_kwh:.1f}".rstrip('0').rstrip('.')


def infer_storage_system_from_csv_path(csv_path):
    basename = os.path.basename(csv_path)
    match = re.search(r'(\d+(?:\.\d+)?)MW#(\d+(?:\.\d+)?)MWh', basename, re.I)
    date_match = re.search(r'(20\d{6})', csv_path)
    date_str = date_match.group(1) if date_match else ""
    date_based_system = get_storage_system_for_date(date_str)
    if not match:
        return date_based_system

    max_power_kw = float(match.group(1)) * 1000.0
    capacity_kwh = float(match.group(2)) * 1000.0
    label_capacity = _format_capacity_label(capacity_kwh)

    inferred_system = {
        'capacity_kwh': capacity_kwh,
        'max_power_kw': max_power_kw,
        'efficiency': PRIMARY_ESS.get('efficiency', 0.95),
        'label': f"当前储能系统({label_capacity}度)",
    }
    if date_str and date_based_system['capacity_kwh'] != capacity_kwh:
        return date_based_system
    return inferred_system

def process_data(csv_path):
    df = pd.read_csv(csv_path)
    df['时间'] = pd.to_datetime(df['时间'])
    numeric_columns = [
        '储能有功功率(kW)',
        '电网功率(kW)',
        '负载功率(kW)',
        'SOC(%)',
        '光伏发电功率(kW)',
    ]
    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors='coerce').fillna(0.0)
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
        pv_to_load = 0; pv_to_ess = 0; pv_to_grid = 0; pv_to_factory = 0; pv_to_ev = 0
        ess_to_factory = 0; ess_to_ev = 0; ess_to_grid = 0
        grid_to_load = 0; grid_to_ess = 0; grid_to_factory = 0; grid_to_ev = 0
        factory_savings_total = 0
        
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
            # 1. 光伏优先满足厂区与充电桩负载，剩余部分再充储能或上网
            r_factory_load = min(r_fac, r_total_load)
            r_pv_to_factory = min(r_pv, r_factory_load)
            r_pv_to_ev = min(max(0, r_pv - r_pv_to_factory), r_ev)
            r_pv_to_load = r_pv_to_factory + r_pv_to_ev
            r_pv_to_ess = min(max(0, r_pv - r_pv_to_load), r_ess_c)
            r_pv_to_grid = max(0, r_pv - r_pv_to_load - r_pv_to_ess)

            # 2. 储能放电优先补足厂区与充电桩剩余负载，若仍有剩余则记为上网
            r_factory_after_pv = max(0, r_factory_load - r_pv_to_factory)
            r_ev_after_pv = max(0, r_ev - r_pv_to_ev)
            r_ess_to_factory = min(r_ess_d, r_factory_after_pv)
            r_ess_to_ev = min(max(0, r_ess_d - r_ess_to_factory), r_ev_after_pv)
            r_ess_to_grid = max(0, r_ess_d - r_ess_to_factory - r_ess_to_ev)

            # 3. 电网购电补足剩余负载，并承担光伏未覆盖的储能充电电量
            r_grid_to_factory = max(0, r_factory_after_pv - r_ess_to_factory)
            r_grid_to_ev = max(0, r_ev_after_pv - r_ess_to_ev)
            r_grid_to_load = r_grid_to_factory + r_grid_to_ev
            r_grid_to_ess = max(0, r_ess_c - r_pv_to_ess)
            
            pv += r_pv * dt
            ess_c += r_ess_c * dt
            ess_d += r_ess_d * dt
            fac += r_fac * dt
            ev += r_ev * dt
            buy_w += r_buy_w * dt
            sell_w += r_sell_w * dt
            buy_no += max(0, grid_no) * dt
            sell_no += max(0, -grid_no) * dt
            factory_savings = r_pv_to_factory * dt * get_grid_buy_price(date_str, h)
            
            pv_to_load += r_pv_to_load * dt
            pv_to_factory += r_pv_to_factory * dt
            pv_to_ev += r_pv_to_ev * dt
            pv_to_ess += r_pv_to_ess * dt
            pv_to_grid += r_pv_to_grid * dt
            ess_to_factory += r_ess_to_factory * dt
            ess_to_ev += r_ess_to_ev * dt
            ess_to_grid += r_ess_to_grid * dt
            grid_to_load += r_grid_to_load * dt
            grid_to_ess += r_grid_to_ess * dt
            grid_to_factory += r_grid_to_factory * dt
            grid_to_ev += r_grid_to_ev * dt
            
            factory_savings_total += factory_savings
            
        hourly_stats.append({
            'hour': h, 'period': period_map.get(h, '平'),
            'pv': pv, 'ess_c': ess_c, 'ess_d': ess_d, 'fac': fac, 'ev': ev,
            'buy_w': buy_w, 'sell_w': sell_w, 'buy_no': buy_no, 'sell_no': sell_no,
            'pv_to_load': pv_to_load, 'pv_to_factory': pv_to_factory, 'pv_to_ev': pv_to_ev,
            'pv_to_ess': pv_to_ess, 'pv_to_grid': pv_to_grid,
            'ess_to_factory': ess_to_factory, 'ess_to_ev': ess_to_ev, 'ess_to_grid': ess_to_grid,
            'grid_to_load': grid_to_load, 'grid_to_ess': grid_to_ess,
            'grid_to_factory': grid_to_factory, 'grid_to_ev': grid_to_ev,
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
        'pv_to_grid_revenue': 0,
        'pv_to_ev_revenue': 0,
        'pv_to_factory_savings': 0,
        'grid_purchase_cost': 0,
        'grid_to_ev_revenue': 0,
        'ess_to_ev_revenue': 0,
        'ess_to_factory_savings': 0,
        'grid_to_factory_cost': 0,
        'grid_to_ess_cost': 0,
        'charging_pile_service_fee': 0,
    }
    
    for st in stats:
        h = st['hour']
        buy_p = get_grid_buy_price(date_str, h)
        sell_ev_p = get_ev_sell_price(date_str, h)
        service_fee_per_kwh = sell_ev_p - buy_p
        
        rev_ev = st['ev'] * sell_ev_p
        rev_fac = st['factory_savings']
        
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
        result['pv_to_grid_revenue'] += st.get('pv_to_grid', 0) * pv_price
        result['pv_to_ev_revenue'] += st.get('pv_to_ev', 0) * sell_ev_p
        result['pv_to_factory_savings'] += st.get('pv_to_factory', 0) * buy_p
        result['grid_purchase_cost'] += st['buy_w'] * buy_p
        result['grid_to_ev_revenue'] += st.get('grid_to_ev', 0) * sell_ev_p
        result['ess_to_ev_revenue'] += st.get('ess_to_ev', 0) * sell_ev_p
        result['ess_to_factory_savings'] += st.get('ess_to_factory', 0) * buy_p
        result['grid_to_factory_cost'] += st.get('grid_to_factory', 0) * buy_p
        result['grid_to_ess_cost'] += st.get('grid_to_ess', 0) * buy_p
        result['charging_pile_service_fee'] += st.get('ev', 0) * service_fee_per_kwh
        
    result['extra_profit'] = result['with_storage_total'] - result['without_storage_total']
    result['pv_actual_total'] = (
        result['pv_to_grid_revenue']
        + result['pv_to_ev_revenue']
        + result['pv_to_factory_savings']
    )
    return result


def build_period_stats(stats, period_order):
    periods = {}
    metric_keys = [
        'pv', 'ess_c', 'ess_d', 'fac', 'ev', 'buy_w', 'sell_w', 'profit_w_01',
        'factory_savings', 'pv_to_load', 'pv_to_factory', 'pv_to_ess', 'pv_to_grid',
        'grid_to_load', 'grid_to_ess',
    ]

    for period in period_order:
        periods[period] = {key: 0 for key in metric_keys}

    for st in stats:
        if 'pv_to_load' not in st:
            continue
        period = st['period']
        if period not in periods:
            periods[period] = {key: 0 for key in metric_keys}
        for key in metric_keys:
            periods[period][key] += st.get(key, 0)

    return periods


def build_net_revenue_breakdown(result):
    total_revenue = round(result['with_storage_total'], 4)
    photovoltaic_sale = round(result['pv_to_grid_revenue'], 4)
    factory_savings = round(result['pv_to_factory_savings'], 4)
    charging_pile = round(total_revenue - photovoltaic_sale - factory_savings, 4)

    def build_item(amount):
        share = amount / total_revenue if total_revenue else 0.0
        return {
            'amount': amount,
            'share_of_total_revenue': share,
        }

    items = {
        'photovoltaic_sale': build_item(photovoltaic_sale),
        'factory_savings': build_item(factory_savings),
        'charging_pile': build_item(charging_pile),
    }
    pie_chart_ready = total_revenue > 0 and all(item['amount'] >= 0 for item in items.values())

    return {
        'allocation_method': 'strict_accounting',
        'pie_chart_ready': pie_chart_ready,
        'items': items,
        'sum_of_items': round(photovoltaic_sale + factory_savings + charging_pile, 4),
    }


def build_daily_json_payload(csv_path, date_str, stats, period_order, periods, scenario_results):
    storage_system = infer_storage_system_from_csv_path(csv_path)
    scenarios = {}
    for scenario in scenario_results:
        result = scenario['result']
        charging_total = (
            result['pv_to_ev_revenue']
            + result['grid_to_ev_revenue']
            + result['ess_to_ev_revenue']
        )
        factory_total = result['pv_to_factory_savings'] + result['ess_to_factory_savings']
        net_revenue_breakdown = build_net_revenue_breakdown(result)
        scenarios[scenario['name']] = {
            'scenario_name': scenario['name'],
            'pv_feed_in_price': scenario['price'],
            'daily_revenue': {
                'total_revenue': result['with_storage_total'],
                'cash_revenue': result['with_storage_cash'],
                'without_storage_total_revenue': result['without_storage_total'],
                'photovoltaic_sale_revenue': {
                    'total': result['pv_to_grid_revenue'],
                    'from_storage': 0.0,
                },
                'factory_savings_revenue': {
                    'total': factory_total,
                    'from_photovoltaic': result['pv_to_factory_savings'],
                    'from_storage': result['ess_to_factory_savings'],
                },
                'charging_pile_revenue': {
                    'total': charging_total,
                    'from_photovoltaic': result['pv_to_ev_revenue'],
                    'from_grid': result['grid_to_ev_revenue'],
                    'from_storage': result['ess_to_ev_revenue'],
                    'service_fee': result['charging_pile_service_fee'],
                },
                'grid_purchase_cost': result['grid_purchase_cost'],
                'storage_contribution': {
                    'total': result['extra_profit'],
                    'charging_pile_revenue': result['ess_to_ev_revenue'],
                    'factory_savings_revenue': result['ess_to_factory_savings'],
                },
                'net_revenue_breakdown': net_revenue_breakdown,
            },
            'revenue_components': {
                'photovoltaic': {
                    'actual_total': result['pv_actual_total'],
                    'to_grid': result['pv_to_grid_revenue'],
                    'to_charging_pile': result['pv_to_ev_revenue'],
                    'to_factory_savings': result['pv_to_factory_savings'],
                },
                'grid': {
                    'purchase_cost': result['grid_purchase_cost'],
                    'to_factory_cost': result['grid_to_factory_cost'],
                    'to_storage_cost': result['grid_to_ess_cost'],
                    'to_charging_pile_revenue': result['grid_to_ev_revenue'],
                },
                'storage': {
                    'extra_profit': result['extra_profit'],
                    'to_factory_savings': result['ess_to_factory_savings'],
                    'to_charging_pile_revenue': result['ess_to_ev_revenue'],
                },
            },
        }

    hourly_stats = []
    for st in stats:
        hourly_stats.append({
            'hour': f"{st['hour']:02d}:00",
            'period': st['period'],
            'photovoltaic_generation_kwh': st['pv'],
            'storage_charge_kwh': st['ess_c'],
            'storage_discharge_kwh': st['ess_d'],
            'factory_load_kwh': st['fac'],
            'charging_pile_load_kwh': st['ev'],
            'grid_purchase_kwh': st['buy_w'],
            'grid_sale_kwh': st['sell_w'],
            'factory_savings_revenue': st['factory_savings'],
            'photovoltaic_to_load_kwh': st.get('pv_to_load', 0),
            'photovoltaic_to_factory_kwh': st.get('pv_to_factory', 0),
            'photovoltaic_to_storage_kwh': st.get('pv_to_ess', 0),
            'photovoltaic_to_grid_kwh': st.get('pv_to_grid', 0),
            'grid_to_load_kwh': st.get('grid_to_load', 0),
            'grid_to_storage_kwh': st.get('grid_to_ess', 0),
        })

    period_stats = []
    for period in period_order:
        data = periods.get(period, {})
        period_stats.append({
            'period': period,
            'photovoltaic_generation_kwh': data.get('pv', 0),
            'storage_charge_kwh': data.get('ess_c', 0),
            'storage_discharge_kwh': data.get('ess_d', 0),
            'factory_load_kwh': data.get('fac', 0),
            'charging_pile_load_kwh': data.get('ev', 0),
            'grid_purchase_kwh': data.get('buy_w', 0),
            'grid_sale_kwh': data.get('sell_w', 0),
            'factory_savings_revenue': data.get('factory_savings', 0),
            'photovoltaic_to_load_kwh': data.get('pv_to_load', 0),
            'photovoltaic_to_factory_kwh': data.get('pv_to_factory', 0),
            'photovoltaic_to_storage_kwh': data.get('pv_to_ess', 0),
            'photovoltaic_to_grid_kwh': data.get('pv_to_grid', 0),
            'grid_to_load_kwh': data.get('grid_to_load', 0),
            'grid_to_storage_kwh': data.get('grid_to_ess', 0),
        })

    payload = {
        'date': date_str,
        'source_csv': os.path.basename(csv_path),
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'storage_system': {
            'label': storage_system['label'],
            'capacity_kwh': storage_system['capacity_kwh'],
            'max_power_kw': storage_system['max_power_kw'],
        },
        'period_order': period_order,
        'period_stats': period_stats,
        'hourly_stats': hourly_stats,
        'scenarios': scenarios,
    }
    return _round_value(payload)

def generate_report(csv_path):
    date_str, stats = process_data(csv_path)
    storage_system = infer_storage_system_from_csv_path(csv_path)
    period_order = get_period_display_order(date_str)
    
    # Calculate base profit (0.1) for tables
    for st in stats:
        h = st['hour']
        buy_p = get_grid_buy_price(date_str, h)
        sell_ev_p = get_ev_sell_price(date_str, h)
        
        rev_ev = st['ev'] * sell_ev_p
        rev_fac = st['factory_savings']
        cost_w = st['buy_w'] * buy_p
        st['cash_profit_w_01'] = st['sell_w'] * 0.1 + rev_ev - cost_w
        st['profit_w_01'] = st['cash_profit_w_01'] + rev_fac
        st['factory_savings'] = rev_fac

    periods = build_period_stats(stats, period_order)
            
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
    
    scenario_results = []
    for name, price in PV_PRICE_SCENARIOS:
        result = calc_profit_for_price(date_str, stats, price)
        scenario_results.append({
            'name': name,
            'price': price,
            'result': result,
        })
        
        lines.append(f"\n### 【场景 {name}：光伏上网电价 {price} 元/度】")
        lines.append(
            f"1. **光伏发电收益**: 今日光伏发电共实现收益 **{result['pv_actual_total']:.2f}** 元，"
            f"其中上网售电收益 **{result['pv_to_grid_revenue']:.2f}** 元，"
            f"供充电桩使用收益 **{result['pv_to_ev_revenue']:.2f}** 元，"
            f"供厂区自用节省电费 **{result['pv_to_factory_savings']:.2f}** 元。"
        )
        lines.append(
            f"2. **电网购电支撑情况**: 今日从电网购电共支出 **{result['grid_purchase_cost']:.2f}** 元，"
            f"其中直接供充电桩形成收入 **{result['grid_to_ev_revenue']:.2f}** 元，"
            f"直接供厂区对应购电成本 **{result['grid_to_factory_cost']:.2f}** 元，"
            f"另有 **{result['grid_to_ess_cost']:.2f}** 元购电用于储能充电。"
        )
        lines.append(
            f"3. **储能供电支撑情况**: 今日储能放电中，直接供充电桩形成收入 **{result['ess_to_ev_revenue']:.2f}** 元，"
            f"直接供厂区节省电费 **{result['ess_to_factory_savings']:.2f}** 元。"
        )
        lines.append(
            f"4. **经营总收益**: 在当前储能运行结果下，今日实际总收益为 **{result['with_storage_total']:.2f}** 元，"
            f"计算式为 **{result['pv_actual_total']:.2f} + {result['grid_to_ev_revenue']:.2f} + {result['ess_to_ev_revenue']:.2f} - {result['grid_purchase_cost']:.2f} = {result['with_storage_total']:.2f}**；"
            f"其中，储能供厂区节省电费 **{result['ess_to_factory_savings']:.2f}** 元已体现在电网购电成本下降中；"
            f"其中，上述各项收益中有 **{result['extra_profit']:.2f}** 元由{storage_system['label']}带来。"
        )
        
    out_path = get_daily_report_path(date_str)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    daily_json_path = get_daily_json_path(date_str)
    daily_json_payload = build_daily_json_payload(
        csv_path=csv_path,
        date_str=date_str,
        stats=stats,
        period_order=period_order,
        periods=periods,
        scenario_results=scenario_results,
    )
    with open(daily_json_path, 'w', encoding='utf-8') as f:
        json.dump(daily_json_payload, f, ensure_ascii=False, indent=2)
        
    print(out_path)
    print(daily_json_path)
    rebuild_summary_table()
    print(SUMMARY_REPORT_PATH)

if __name__ == "__main__":
    csv_file = sys.argv[1]
    ensure_report_dir()
    generate_report(csv_file)
