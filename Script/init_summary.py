import re
import json
from config import (
    SUMMARY_PRICE_KEYS,
    SUMMARY_REPORT_PATH,
    SUMMARY_JSON_PATH,
    get_daily_report_paths,
    get_daily_json_paths,
)


def build_default_daily_revenue(total_revenue=0.0, storage_total=0.0):
    return {
        'total_revenue': round(float(total_revenue), 4),
        'cash_revenue': 0.0,
        'without_storage_total_revenue': 0.0,
        'photovoltaic_sale_revenue': {
            'total': 0.0,
            'from_storage': 0.0,
        },
        'factory_savings_revenue': {
            'total': 0.0,
            'from_photovoltaic': 0.0,
            'from_storage': 0.0,
        },
        'charging_pile_revenue': {
            'total': 0.0,
            'from_photovoltaic': 0.0,
            'from_grid': 0.0,
            'from_storage': 0.0,
        },
        'grid_purchase_cost': 0.0,
        'storage_contribution': {
            'total': round(float(storage_total), 4),
            'charging_pile_revenue': 0.0,
            'factory_savings_revenue': 0.0,
        },
        'net_revenue_breakdown': {
            'allocation_method': 'strict_accounting',
            'pie_chart_ready': False,
            'items': {
                'photovoltaic_sale': {
                    'amount': 0.0,
                    'share_of_total_revenue': 0.0,
                },
                'factory_savings': {
                    'amount': 0.0,
                    'share_of_total_revenue': 0.0,
                },
                'charging_pile': {
                    'amount': 0.0,
                    'share_of_total_revenue': 0.0,
                },
            },
            'sum_of_items': round(float(total_revenue), 4),
        },
    }


def rebuild_summary_table():
    reports = get_daily_report_paths()
    summary_json_by_date = {}

    with open(SUMMARY_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("# 总收益分析报表\n\n")
        f.write("| 日期 | 经营总收益(光伏电价0.1元/度) | 储能额外收益(光伏电价0.1元/度) | 经营总收益(光伏电价0.2元/度) | 储能额外收益(光伏电价0.2元/度) | 经营总收益(光伏电价0.35元/度) | 储能额外收益(光伏电价0.35元/度) |\n")
        f.write("|:---|---:|---:|---:|---:|---:|---:|\n")

        for rp in reports:
            date_match = re.search(r'_(\d{8})\.md', rp)
            if not date_match:
                continue
            date_str = date_match.group(1)

            with open(rp, 'r', encoding='utf-8') as report_file:
                content = report_file.read()

            profits = {'01': (0, 0), '02': (0, 0), '035': (0, 0)}

            for price_key, price_str in SUMMARY_PRICE_KEYS:
                scenario_block = re.search(
                    r'### 【场景 [A-Z]：光伏上网电价 ' + price_str + r' 元/度】(.*?)(?=\n### 【场景 |\Z)',
                    content,
                    re.S
                )
                if not scenario_block:
                    continue

                block = scenario_block.group(1)

                m2_total = re.search(r'含储能经营总收益.*?\*\*([0-9.]+)\*\* 元', block, re.S)
                m2_extra = re.search(r'额外创收\*\* \*\*([0-9.]+)\*\* 元', block, re.S)
                if m2_total and m2_extra:
                    profits[price_key] = (float(m2_total.group(1)), float(m2_extra.group(1)))
                    continue

                m2_new = re.search(
                    r'经营总收益.*?\*\*([0-9.]+)\*\* 元.*?上述各项收益中有 \*\*([0-9.]+)\*\* 元由',
                    block,
                    re.S
                )
                if m2_new:
                    profits[price_key] = (float(m2_new.group(1)), float(m2_new.group(2)))
                    continue

                m2_old = re.search(r'额外创收\*\* \*\*([0-9.]+)\*\* 元。\(最终今日实际总利润: \*\*([0-9.]+)\*\* 元\)', block, re.S)
                if m2_old:
                    profits[price_key] = (float(m2_old.group(2)), float(m2_old.group(1)))
                    continue

                m1_total = re.search(r'当光伏上网电价为 ' + price_str + r' 元时，系统预估总净利润: \*\*([0-9.]+)\*\* 元', block)
                m1_extra = re.search(r'带来的\*\*额外净收益\*\* \(电价 ' + price_str + r' 元\): \*\*([0-9.]+)\*\* 元', block)
                if m1_total and m1_extra:
                    profits[price_key] = (float(m1_total.group(1)), float(m1_extra.group(1)))

            if profits['01'][0] == 0 and profits['02'][0] == 0:
                continue

            f.write(f"| {date_str} | {profits['01'][0]:.2f} | {profits['01'][1]:.2f} | {profits['02'][0]:.2f} | {profits['02'][1]:.2f} | {profits['035'][0]:.2f} | {profits['035'][1]:.2f} |\n")
            summary_json_by_date[date_str] = {
                'date': date_str,
                'scenarios': {
                    '01': {
                        'scenario_name': 'A',
                        'pv_feed_in_price': 0.1,
                        'total_revenue': round(profits['01'][0], 4),
                        'storage_contribution': round(profits['01'][1], 4),
                        'daily_revenue': build_default_daily_revenue(profits['01'][0], profits['01'][1]),
                    },
                    '02': {
                        'scenario_name': 'B',
                        'pv_feed_in_price': 0.2,
                        'total_revenue': round(profits['02'][0], 4),
                        'storage_contribution': round(profits['02'][1], 4),
                        'daily_revenue': build_default_daily_revenue(profits['02'][0], profits['02'][1]),
                    },
                    '035': {
                        'scenario_name': 'C',
                        'pv_feed_in_price': 0.35,
                        'total_revenue': round(profits['035'][0], 4),
                        'storage_contribution': round(profits['035'][1], 4),
                        'daily_revenue': build_default_daily_revenue(profits['035'][0], profits['035'][1]),
                    },
                },
            }

    for json_path in get_daily_json_paths():
        with open(json_path, 'r', encoding='utf-8') as json_file:
            payload = json.load(json_file)

        date_str = payload.get('date')
        scenarios = payload.get('scenarios', {})
        if not date_str or not scenarios:
            continue

        row = summary_json_by_date.get(date_str, {'date': date_str, 'scenarios': {}})
        for price_key, price_str in SUMMARY_PRICE_KEYS:
            if price_key not in row['scenarios']:
                row['scenarios'][price_key] = {
                    'scenario_name': '',
                    'pv_feed_in_price': float(price_str),
                    'total_revenue': 0.0,
                    'storage_contribution': 0.0,
                    'daily_revenue': build_default_daily_revenue(),
                }

        for scenario_key, scenario_payload in scenarios.items():
            pv_price = scenario_payload.get('pv_feed_in_price')
            matched_price_key = None
            for price_key, price_str in SUMMARY_PRICE_KEYS:
                if abs(float(price_str) - float(pv_price)) < 1e-9:
                    matched_price_key = price_key
                    break
            if matched_price_key is None:
                continue

            daily_revenue = scenario_payload.get('daily_revenue', {})
            storage_contribution = daily_revenue.get('storage_contribution', {})
            row['scenarios'][matched_price_key] = {
                'scenario_name': scenario_key,
                'pv_feed_in_price': pv_price,
                'total_revenue': round(float(daily_revenue.get('total_revenue', 0.0)), 4),
                'storage_contribution': round(float(storage_contribution.get('total', 0.0)), 4),
                'daily_revenue': {
                    'total_revenue': round(float(daily_revenue.get('total_revenue', 0.0)), 4),
                    'cash_revenue': round(float(daily_revenue.get('cash_revenue', 0.0)), 4),
                    'without_storage_total_revenue': round(float(daily_revenue.get('without_storage_total_revenue', 0.0)), 4),
                    'photovoltaic_sale_revenue': {
                        'total': round(float(daily_revenue.get('photovoltaic_sale_revenue', {}).get('total', 0.0)), 4),
                        'from_storage': round(float(daily_revenue.get('photovoltaic_sale_revenue', {}).get('from_storage', 0.0)), 4),
                    },
                    'factory_savings_revenue': {
                        'total': round(float(daily_revenue.get('factory_savings_revenue', {}).get('total', 0.0)), 4),
                        'from_photovoltaic': round(float(daily_revenue.get('factory_savings_revenue', {}).get('from_photovoltaic', 0.0)), 4),
                        'from_storage': round(float(daily_revenue.get('factory_savings_revenue', {}).get('from_storage', 0.0)), 4),
                    },
                    'charging_pile_revenue': {
                        'total': round(float(daily_revenue.get('charging_pile_revenue', {}).get('total', 0.0)), 4),
                        'from_photovoltaic': round(float(daily_revenue.get('charging_pile_revenue', {}).get('from_photovoltaic', 0.0)), 4),
                        'from_grid': round(float(daily_revenue.get('charging_pile_revenue', {}).get('from_grid', 0.0)), 4),
                        'from_storage': round(float(daily_revenue.get('charging_pile_revenue', {}).get('from_storage', 0.0)), 4),
                    },
                    'grid_purchase_cost': round(float(daily_revenue.get('grid_purchase_cost', 0.0)), 4),
                    'storage_contribution': {
                        'total': round(float(storage_contribution.get('total', 0.0)), 4),
                        'charging_pile_revenue': round(float(storage_contribution.get('charging_pile_revenue', 0.0)), 4),
                        'factory_savings_revenue': round(float(storage_contribution.get('factory_savings_revenue', 0.0)), 4),
                    },
                    'net_revenue_breakdown': {
                        'allocation_method': daily_revenue.get('net_revenue_breakdown', {}).get('allocation_method', 'strict_accounting'),
                        'pie_chart_ready': bool(daily_revenue.get('net_revenue_breakdown', {}).get('pie_chart_ready', False)),
                        'items': {
                            'photovoltaic_sale': {
                                'amount': round(float(daily_revenue.get('net_revenue_breakdown', {}).get('items', {}).get('photovoltaic_sale', {}).get('amount', 0.0)), 4),
                                'share_of_total_revenue': round(float(daily_revenue.get('net_revenue_breakdown', {}).get('items', {}).get('photovoltaic_sale', {}).get('share_of_total_revenue', 0.0)), 6),
                            },
                            'factory_savings': {
                                'amount': round(float(daily_revenue.get('net_revenue_breakdown', {}).get('items', {}).get('factory_savings', {}).get('amount', 0.0)), 4),
                                'share_of_total_revenue': round(float(daily_revenue.get('net_revenue_breakdown', {}).get('items', {}).get('factory_savings', {}).get('share_of_total_revenue', 0.0)), 6),
                            },
                            'charging_pile': {
                                'amount': round(float(daily_revenue.get('net_revenue_breakdown', {}).get('items', {}).get('charging_pile', {}).get('amount', 0.0)), 4),
                                'share_of_total_revenue': round(float(daily_revenue.get('net_revenue_breakdown', {}).get('items', {}).get('charging_pile', {}).get('share_of_total_revenue', 0.0)), 6),
                            },
                        },
                        'sum_of_items': round(float(daily_revenue.get('net_revenue_breakdown', {}).get('sum_of_items', 0.0)), 4),
                    },
                },
            }

        summary_json_by_date[date_str] = row

    summary_json_rows = [summary_json_by_date[date] for date in sorted(summary_json_by_date)]
    summary_payload = {
        'reports': summary_json_rows,
        'generated_from': 'daily_reports_and_daily_json_files',
    }
    with open(SUMMARY_JSON_PATH, 'w', encoding='utf-8') as json_file:
        json.dump(summary_payload, json_file, ensure_ascii=False, indent=2)

    print("初始化总表完成：", SUMMARY_REPORT_PATH)
    print("初始化总表 JSON 完成：", SUMMARY_JSON_PATH)


def main():
    rebuild_summary_table()


if __name__ == "__main__":
    main()
