import glob
import json
import os
import sys
from collections import Counter
from copy import deepcopy
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import JSON_DIR, PV_PRICE_SCENARIOS, REPORT_DIR, ensure_report_dir
from pricing import get_ev_sell_price, get_grid_buy_price


MONTHLY_REPORT_PREFIX = "月度收益分析报告_"
MONTHLY_JSON_PREFIX = "月度收益分析_"
PERIOD_DISPLAY_ORDER = ["尖", "峰", "平", "谷"]

ENERGY_KEYS = [
    "photovoltaic_generation_kwh",
    "storage_charge_kwh",
    "storage_discharge_kwh",
    "factory_load_kwh",
    "charging_pile_load_kwh",
    "grid_purchase_kwh",
    "grid_sale_kwh",
    "factory_savings_revenue",
    "photovoltaic_to_load_kwh",
    "photovoltaic_to_factory_kwh",
    "photovoltaic_to_storage_kwh",
    "photovoltaic_to_grid_kwh",
    "grid_to_load_kwh",
    "grid_to_storage_kwh",
    "profit_w_01",
]


def fmt_number(value):
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def round_nested(value, digits=4):
    if isinstance(value, dict):
        return {key: round_nested(item, digits) for key, item in value.items()}
    if isinstance(value, list):
        return [round_nested(item, digits) for item in value]
    if isinstance(value, float):
        return round(value, digits)
    return value


def normalize_storage_label(storage_system):
    capacity_kwh = storage_system.get("capacity_kwh")
    if isinstance(capacity_kwh, (int, float)) and capacity_kwh > 0:
        rounded = int(round(float(capacity_kwh)))
        return f"当前储能系统({rounded}度)"
    return storage_system.get("label", "未知储能系统")


def get_monthly_report_path(month_str):
    return os.path.join(REPORT_DIR, f"{MONTHLY_REPORT_PREFIX}{month_str}.md")


def get_monthly_json_path(month_str):
    return os.path.join(JSON_DIR, f"{MONTHLY_JSON_PREFIX}{month_str}.json")


def get_daily_json_paths_for_month(month_str):
    pattern = os.path.join(JSON_DIR, f"每日收益分析_{month_str}*.json")
    paths = glob.glob(pattern)
    paths.sort()
    return paths


def load_daily_payloads(month_str):
    payloads = []
    for path in get_daily_json_paths_for_month(month_str):
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payloads.append(payload)
    return payloads


def create_zero_energy_bucket():
    return {key: 0.0 for key in ENERGY_KEYS}


def merge_numeric_dict(target, source):
    for key, value in source.items():
        if isinstance(value, dict):
            child = target.setdefault(key, {})
            merge_numeric_dict(child, value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            target[key] = target.get(key, 0.0) + float(value)
    return target


def build_net_revenue_breakdown(total_revenue, photovoltaic_sale, factory_savings):
    charging_pile = total_revenue - photovoltaic_sale - factory_savings

    def build_item(amount):
        share = amount / total_revenue if total_revenue else 0.0
        return {
            "amount": amount,
            "share_of_total_revenue": share,
        }

    items = {
        "photovoltaic_sale": build_item(photovoltaic_sale),
        "factory_savings": build_item(factory_savings),
        "charging_pile": build_item(charging_pile),
    }
    pie_chart_ready = total_revenue > 0 and all(item["amount"] >= 0 for item in items.values())
    return {
        "allocation_method": "strict_accounting",
        "pie_chart_ready": pie_chart_ready,
        "items": items,
        "sum_of_items": photovoltaic_sale + factory_savings + charging_pile,
    }


def aggregate_storage_summary(payloads):
    label_counter = Counter()
    for payload in payloads:
        label = normalize_storage_label(payload.get("storage_system", {}))
        label_counter[label] += 1

    if not label_counter:
        return "未知储能系统"
    if len(label_counter) == 1:
        return next(iter(label_counter))

    parts = [f"{label}({count}天)" for label, count in label_counter.items()]
    return "月内储能系统切换: " + " / ".join(parts)


def aggregate_month_data(payloads):
    period_buckets = {}
    hour_buckets = {f"{hour:02d}:00": create_zero_energy_bucket() for hour in range(24)}
    hour_period_counts = {f"{hour:02d}:00": Counter() for hour in range(24)}
    scenario_totals = {}
    period_set = set()

    for payload in payloads:
        date_str = payload["date"]
        for period in payload.get("period_order", []):
            period_set.add(period)

        for row in payload.get("hourly_stats", []):
            hour_str = row["hour"]
            hour_int = int(hour_str[:2])
            period = row["period"]
            period_set.add(period)

            buy_price = get_grid_buy_price(date_str, hour_int)
            sell_ev_price = get_ev_sell_price(date_str, hour_int)
            profit_w_01 = (
                float(row.get("grid_sale_kwh", 0.0)) * 0.1
                + float(row.get("charging_pile_load_kwh", 0.0)) * sell_ev_price
                - float(row.get("grid_purchase_kwh", 0.0)) * buy_price
                + float(row.get("factory_savings_revenue", 0.0))
            )

            bucket = {
                "photovoltaic_generation_kwh": float(row.get("photovoltaic_generation_kwh", 0.0)),
                "storage_charge_kwh": float(row.get("storage_charge_kwh", 0.0)),
                "storage_discharge_kwh": float(row.get("storage_discharge_kwh", 0.0)),
                "factory_load_kwh": float(row.get("factory_load_kwh", 0.0)),
                "charging_pile_load_kwh": float(row.get("charging_pile_load_kwh", 0.0)),
                "grid_purchase_kwh": float(row.get("grid_purchase_kwh", 0.0)),
                "grid_sale_kwh": float(row.get("grid_sale_kwh", 0.0)),
                "factory_savings_revenue": float(row.get("factory_savings_revenue", 0.0)),
                "photovoltaic_to_load_kwh": float(row.get("photovoltaic_to_load_kwh", 0.0)),
                "photovoltaic_to_factory_kwh": float(row.get("photovoltaic_to_factory_kwh", 0.0)),
                "photovoltaic_to_storage_kwh": float(row.get("photovoltaic_to_storage_kwh", 0.0)),
                "photovoltaic_to_grid_kwh": float(row.get("photovoltaic_to_grid_kwh", 0.0)),
                "grid_to_load_kwh": float(row.get("grid_to_load_kwh", 0.0)),
                "grid_to_storage_kwh": float(row.get("grid_to_storage_kwh", 0.0)),
                "profit_w_01": profit_w_01,
            }

            if period not in period_buckets:
                period_buckets[period] = create_zero_energy_bucket()
            for key, value in bucket.items():
                period_buckets[period][key] += value
                hour_buckets[hour_str][key] += value
            hour_period_counts[hour_str][period] += 1

        for scenario_name, scenario_payload in payload.get("scenarios", {}).items():
            if scenario_name not in scenario_totals:
                scenario_totals[scenario_name] = deepcopy(scenario_payload)
                scenario_totals[scenario_name]["daily_revenue"] = {}
                scenario_totals[scenario_name]["revenue_components"] = {}
            merge_numeric_dict(scenario_totals[scenario_name]["daily_revenue"], scenario_payload.get("daily_revenue", {}))
            merge_numeric_dict(
                scenario_totals[scenario_name]["revenue_components"],
                scenario_payload.get("revenue_components", {}),
            )
            scenario_totals[scenario_name]["scenario_name"] = scenario_payload.get("scenario_name", scenario_name)
            scenario_totals[scenario_name]["pv_feed_in_price"] = scenario_payload.get("pv_feed_in_price", 0.0)

    for scenario_name, scenario_payload in scenario_totals.items():
        total_revenue = float(scenario_payload["daily_revenue"].get("total_revenue", 0.0))
        photovoltaic_sale = float(
            scenario_payload["revenue_components"].get("photovoltaic", {}).get("to_grid", 0.0)
        )
        factory_savings = float(
            scenario_payload["revenue_components"].get("photovoltaic", {}).get("to_factory_savings", 0.0)
        )
        scenario_payload["daily_revenue"]["net_revenue_breakdown"] = build_net_revenue_breakdown(
            total_revenue=total_revenue,
            photovoltaic_sale=photovoltaic_sale,
            factory_savings=factory_savings,
        )

    period_order = [period for period in PERIOD_DISPLAY_ORDER if period in period_set]
    hourly_stats = []
    for hour in range(24):
        hour_str = f"{hour:02d}:00"
        period_counts = hour_period_counts[hour_str]
        if not period_counts:
            period_display = "平"
        else:
            ordered = [period for period in PERIOD_DISPLAY_ORDER if period_counts.get(period)]
            period_display = "/".join(ordered)
        hourly_stats.append(
            {
                "hour": hour_str,
                "period": period_display,
                **hour_buckets[hour_str],
            }
        )

    return {
        "period_order": period_order,
        "period_stats": period_buckets,
        "hourly_stats": hourly_stats,
        "scenarios": round_nested(scenario_totals),
    }


def build_monthly_payload(month_str, payloads, aggregated):
    storage_labels = sorted(
        {normalize_storage_label(payload.get("storage_system", {})) for payload in payloads}
    )
    return round_nested(
        {
            "month": month_str,
            "start_date": payloads[0]["date"],
            "end_date": payloads[-1]["date"],
            "days": len(payloads),
            "source_daily_json_count": len(payloads),
            "source_daily_json_files": [f"每日收益分析_{payload['date']}.json" for payload in payloads],
            "storage_labels": storage_labels,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "period_order": aggregated["period_order"],
            "period_stats": [
                {"period": period, **aggregated["period_stats"][period]}
                for period in aggregated["period_order"]
            ],
            "hourly_stats": aggregated["hourly_stats"],
            "scenarios": aggregated["scenarios"],
        }
    )


def render_period_distribution_lines(period_order, period_stats):
    lines = []
    lines.append("### 1.2 光伏发电的流向与时间分布")
    lines.append("| 时段 | 光伏总产电(度) | 直接消纳(负载) | 充入储能 | 余电上网(卖电) |")
    lines.append("|:---|---:|---:|---:|---:|")
    for period in period_order:
        row = period_stats[period]
        pv_total = row["photovoltaic_generation_kwh"]
        if pv_total > 0:
            pct_load = row["photovoltaic_to_load_kwh"] / pv_total * 100
            pct_storage = row["photovoltaic_to_storage_kwh"] / pv_total * 100
            pct_grid = row["photovoltaic_to_grid_kwh"] / pv_total * 100
            lines.append(
                f"| {period} | {fmt_number(pv_total)} | {pct_load:.1f}% | {pct_storage:.1f}% | {pct_grid:.1f}% |"
            )
        else:
            lines.append(f"| {period} | 0 | 0.0% | 0.0% | 0.0% |")
    return lines


def render_grid_distribution_lines(period_order, period_stats):
    lines = []
    lines.append("### 1.3 电网购电的流向与时间分布")
    lines.append("| 时段 | 电网总购电(度) | 满足负载 | 充入储能 |")
    lines.append("|:---|---:|---:|---:|")
    for period in period_order:
        row = period_stats[period]
        buy_total = row["grid_purchase_kwh"]
        if buy_total > 0:
            pct_load = row["grid_to_load_kwh"] / buy_total * 100
            pct_storage = row["grid_to_storage_kwh"] / buy_total * 100
            lines.append(
                f"| {period} | {fmt_number(buy_total)} | {pct_load:.1f}% | {pct_storage:.1f}% |"
            )
        else:
            lines.append(f"| {period} | 0 | 0.0% | 0.0% |")
    return lines


def render_report(month_str, payloads, aggregated):
    start_date = payloads[0]["date"]
    end_date = payloads[-1]["date"]
    storage_summary = aggregate_storage_summary(payloads)
    period_order = aggregated["period_order"]
    period_stats = aggregated["period_stats"]

    lines = []
    lines.append(f"# 月度收益分析报告 - {month_str}")
    lines.append("")
    lines.append(f"**数据范围**: {start_date} - {end_date}")
    lines.append(f"**覆盖天数**: {len(payloads)} 天")
    lines.append(f"**储能口径**: {storage_summary}")
    lines.append("")
    lines.append("## 1. 基础报表 (光伏上网电价 0.1元/度)")
    lines.append("### 1.1 分时段汇总 (按电价标签自动分组)")
    lines.append("| 时段 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 工厂省电收益(元) | 向电网买电量(度) | 向电网卖电量(度) | 时段经营收益(0.1元) |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for period in period_order:
        row = period_stats[period]
        lines.append(
            f"| {period} | {fmt_number(row['photovoltaic_generation_kwh'])} | {fmt_number(row['storage_charge_kwh'])} | "
            f"{fmt_number(row['storage_discharge_kwh'])} | {fmt_number(row['factory_load_kwh'])} | "
            f"{fmt_number(row['charging_pile_load_kwh'])} | {fmt_number(row['factory_savings_revenue'])} | "
            f"{fmt_number(row['grid_purchase_kwh'])} | {fmt_number(row['grid_sale_kwh'])} | {fmt_number(row['profit_w_01'])} |"
        )

    lines.append("")
    lines.extend(render_period_distribution_lines(period_order, period_stats))
    lines.append("")
    lines.extend(render_grid_distribution_lines(period_order, period_stats))
    lines.append("")
    lines.append("### 1.4 每小时详细报表")
    lines.append("| 小时 | 时段 | 光伏产电量(度) | 储能充电量(度) | 储能放电量(度) | 工厂用电量(度) | 充电桩用电量(度) | 工厂省电收益(元) | 向电网买电量(度) | 向电网卖电量(度) | 时段经营收益(0.1元) |")
    lines.append("|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in aggregated["hourly_stats"]:
        lines.append(
            f"| {row['hour']} | {row['period']} | {fmt_number(row['photovoltaic_generation_kwh'])} | "
            f"{fmt_number(row['storage_charge_kwh'])} | {fmt_number(row['storage_discharge_kwh'])} | "
            f"{fmt_number(row['factory_load_kwh'])} | {fmt_number(row['charging_pile_load_kwh'])} | "
            f"{fmt_number(row['factory_savings_revenue'])} | {fmt_number(row['grid_purchase_kwh'])} | "
            f"{fmt_number(row['grid_sale_kwh'])} | {fmt_number(row['profit_w_01'])} |"
        )

    lines.append("")
    lines.append("## 2. 核心收益结论 (业主视角)")

    storage_tail = storage_summary if storage_summary.startswith("月内储能系统切换") else storage_summary
    for scenario_name, price in PV_PRICE_SCENARIOS:
        scenario = aggregated["scenarios"].get(scenario_name, {})
        daily_revenue = scenario.get("daily_revenue", {})
        revenue_components = scenario.get("revenue_components", {})
        photovoltaic = revenue_components.get("photovoltaic", {})
        grid = revenue_components.get("grid", {})
        storage = revenue_components.get("storage", {})

        lines.append("")
        lines.append(f"### 【场景 {scenario_name}：光伏上网电价 {price} 元/度】")
        lines.append(
            f"1. **光伏发电收益**: 本月光伏发电共实现收益 **{float(photovoltaic.get('actual_total', 0.0)):.2f}** 元，"
            f"其中上网售电收益 **{float(photovoltaic.get('to_grid', 0.0)):.2f}** 元，"
            f"供充电桩使用收益 **{float(photovoltaic.get('to_charging_pile', 0.0)):.2f}** 元，"
            f"供厂区自用节省电费 **{float(photovoltaic.get('to_factory_savings', 0.0)):.2f}** 元。"
        )
        lines.append(
            f"2. **电网购电支撑情况**: 本月从电网购电共支出 **{float(grid.get('purchase_cost', 0.0)):.2f}** 元，"
            f"其中直接供充电桩形成收入 **{float(grid.get('to_charging_pile_revenue', 0.0)):.2f}** 元，"
            f"直接供厂区对应购电成本 **{float(grid.get('to_factory_cost', 0.0)):.2f}** 元，"
            f"另有 **{float(grid.get('to_storage_cost', 0.0)):.2f}** 元购电用于储能充电。"
        )
        lines.append(
            f"3. **储能供电支撑情况**: 本月储能放电中，直接供充电桩形成收入 **{float(storage.get('to_charging_pile_revenue', 0.0)):.2f}** 元，"
            f"直接供厂区节省电费 **{float(storage.get('to_factory_savings', 0.0)):.2f}** 元。"
        )
        total_revenue = float(daily_revenue.get("total_revenue", 0.0))
        pv_actual_total = float(photovoltaic.get("actual_total", 0.0))
        grid_to_ev_revenue = float(grid.get("to_charging_pile_revenue", 0.0))
        storage_to_ev_revenue = float(storage.get("to_charging_pile_revenue", 0.0))
        grid_purchase_cost = float(grid.get("purchase_cost", 0.0))
        storage_factory_savings = float(storage.get("to_factory_savings", 0.0))
        extra_profit = float(storage.get("extra_profit", 0.0))
        lines.append(
            f"4. **经营总收益**: 在本月储能运行结果下，本月实际总收益为 **{total_revenue:.2f}** 元，"
            f"计算式为 **{pv_actual_total:.2f} + {grid_to_ev_revenue:.2f} + {storage_to_ev_revenue:.2f} - {grid_purchase_cost:.2f} = {total_revenue:.2f}**；"
            f"其中，储能供厂区节省电费 **{storage_factory_savings:.2f}** 元已体现在电网购电成本下降中；"
            f"其中，上述各项收益中有 **{extra_profit:.2f}** 元由{storage_tail}带来。"
        )

    return "\n".join(lines)


def generate_monthly_report(month_str):
    payloads = load_daily_payloads(month_str)
    if not payloads:
        raise FileNotFoundError(f"未找到 {month_str} 对应的每日报告 JSON 数据。")

    payloads.sort(key=lambda item: item["date"])
    aggregated = aggregate_month_data(payloads)
    monthly_payload = build_monthly_payload(month_str, payloads, aggregated)
    report_content = render_report(month_str, payloads, aggregated)

    report_path = get_monthly_report_path(month_str)
    json_path = get_monthly_json_path(month_str)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(monthly_payload, f, ensure_ascii=False, indent=2)

    print(report_path)
    print(json_path)


def main(months):
    ensure_report_dir()
    for month_str in months:
        if len(month_str) != 6 or not month_str.isdigit():
            raise ValueError(f"月份格式错误: {month_str}，应为 YYYYMM。")
        generate_monthly_report(month_str)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("用法: python3 Script/generate_monthly_report.py YYYYMM [YYYYMM ...]")
    main(sys.argv[1:])
