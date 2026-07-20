from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path("/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算")
DAY_HOUR_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_逐日逐小时.csv"
DETAIL_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_5分钟明细.csv"


def to_float(value: str) -> float:
    if value in ("", None):
        return 0.0
    return float(value)


def mean(values):
    return sum(values) / len(values) if values else 0.0


def corr(xs, ys):
    if not xs or len(xs) != len(ys):
        return 0.0
    mx = mean(xs)
    my = mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def linear_fit(xs, ys):
    if not xs or len(xs) != len(ys):
        return 0.0, 0.0
    mx = mean(xs)
    my = mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    intercept = my - slope * mx
    return slope, intercept


def main():
    night_hours = {0, 1, 2, 3, 4, 5, 6}

    hour_rows = []
    with open(DAY_HOUR_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hour = int(row["小时"].split(":")[0])
            if hour not in night_hours:
                continue
            order_kwh = to_float(row["订单充电量(度)"])
            factory_kwh = to_float(row["拟合工厂用电(度)"])
            site_kwh = to_float(row["总站总负载(度)"])
            ratio = factory_kwh / order_kwh if order_kwh > 0 else 0.0
            hour_rows.append(
                {
                    "date": row["日期"],
                    "hour": hour,
                    "order_kwh": order_kwh,
                    "factory_kwh": factory_kwh,
                    "site_kwh": site_kwh,
                    "ratio": ratio,
                }
            )

    order_vals = [row["order_kwh"] for row in hour_rows]
    factory_vals = [row["factory_kwh"] for row in hour_rows]
    slope, intercept = linear_fit(order_vals, factory_vals)
    correlation = corr(order_vals, factory_vals)

    by_hour = defaultdict(lambda: {"order": [], "factory": [], "ratio": []})
    for row in hour_rows:
        by_hour[row["hour"]]["order"].append(row["order_kwh"])
        by_hour[row["hour"]]["factory"].append(row["factory_kwh"])
        if row["order_kwh"] > 0:
            by_hour[row["hour"]]["ratio"].append(row["ratio"])

    detail_rows = []
    clipped_night = 0
    total_night = 0
    with open(DETAIL_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hour = int(row["时间"][11:13])
            if hour not in night_hours:
                continue
            total_night += 1
            site_kw = to_float(row["总站总负载(kW)"])
            order_kw = to_float(row["订单折算充电功率(kW)"])
            factory_kw = to_float(row["拟合工厂功率(kW)"])
            if factory_kw == 0 and order_kw > site_kw:
                clipped_night += 1
            detail_rows.append((hour, site_kw, order_kw, factory_kw))

    out_md = ROOT / "报告" / "6月凌晨负载与线损规律分析.md"
    lines = []
    lines.append("# 6月凌晨负载与线损规律分析")
    lines.append("")
    lines.append("- 研究时段：`00:00-06:59`，按每小时汇总。")
    lines.append("- 目标：判断凌晨拟合出的“工厂负载”更像固定底损、随充电量变化的线损，还是两者叠加。")
    lines.append(f"- 夜间样本数：`{len(hour_rows)}` 个小时点")
    lines.append(f"- 5分钟夜间样本数：`{total_night}`")
    lines.append(f"- 夜间被截断为 0 的 5 分钟点数：`{clipped_night}`")
    lines.append("")
    lines.append("## 整体拟合关系")
    lines.append(f"- 线性关系：`拟合负载 ≈ {slope:.4f} * 订单充电量 + {intercept:.4f}`")
    lines.append(f"- 相关系数：`{correlation:.4f}`")
    lines.append("- 解读：斜率可近似理解为随充电量变化的附加损耗比例；截距可近似理解为夜间固定底损。")
    lines.append("")
    lines.append("## 按小时统计")
    for hour in sorted(by_hour):
        avg_order = mean(by_hour[hour]["order"])
        avg_factory = mean(by_hour[hour]["factory"])
        avg_ratio = mean(by_hour[hour]["ratio"])
        lines.append(
            f"- `{hour:02d}:00`: 平均订单 `{avg_order:.2f}` 度，平均拟合负载 `{avg_factory:.2f}` 度，平均比值 `{avg_ratio:.3f}`"
        )

    lines.append("")
    lines.append("## 夜间高负载样本 Top 20")
    top_rows = sorted(hour_rows, key=lambda row: row["factory_kwh"], reverse=True)[:20]
    for row in top_rows:
        lines.append(
            f"- `{row['date']} {row['hour']:02d}:00`: 订单 `{row['order_kwh']:.2f}`，拟合负载 `{row['factory_kwh']:.2f}`，比值 `{row['ratio']:.3f}`"
        )

    out_md.write_text("\n".join(lines), encoding="utf-8")

    print("report_md", out_md)
    print("samples", len(hour_rows))
    print("clipped_night", clipped_night)
    print("linear_fit", round(slope, 4), round(intercept, 4))
    print("corr", round(correlation, 4))
    for hour in sorted(by_hour):
        print(
            "hour",
            f"{hour:02d}",
            "avg_order",
            round(mean(by_hour[hour]["order"]), 2),
            "avg_factory",
            round(mean(by_hour[hour]["factory"]), 2),
            "avg_ratio",
            round(mean(by_hour[hour]["ratio"]), 3),
        )


if __name__ == "__main__":
    main()
