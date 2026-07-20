from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook


ROOT = Path("/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算")
SOURCE_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_逐日逐小时.csv"
OUT_HOURLY_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_逐日逐小时_修正后.csv"
OUT_DAILY_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_按天统计.csv"
OUT_HOURLY_XLSX = ROOT / "报告" / "工厂用电拟合_202606_逐日逐小时.xlsx"
OUT_DAILY_XLSX = ROOT / "报告" / "工厂用电拟合_202606_按天统计.xlsx"
OUT_REPORT = ROOT / "报告" / "6月工厂用电新版结论报告.md"

NIGHT_BASELINE_KW = 8.1375
NIGHT_HOURS = set(range(0, 6)) | set(range(18, 24))


def to_float(value):
    if value in (None, "", "-"):
        return 0.0
    return float(value)


def is_night_hour(hour_text: str) -> bool:
    return int(str(hour_text).split(":")[0]) in NIGHT_HOURS


def write_xlsx(path: Path, sheet_name: str, fieldnames, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(list(fieldnames))
    for row in rows:
        ws.append([row[name] for name in fieldnames])
    for col_idx in range(1, len(fieldnames) + 1):
        ws.column_dimensions[chr(64 + col_idx)].width = 18
    wb.save(path)


def main():
    hourly_rows = []
    daily = defaultdict(
        lambda: {
            "总站总负载(度)": 0.0,
            "订单充电量(度)": 0.0,
            "原拟合工厂用电(度)": 0.0,
            "夜间基础负荷封顶值(度)": 0.0,
            "夜间超基线残余(度)": 0.0,
            "新版修正后厂区用电(度)": 0.0,
        }
    )

    total_original = 0.0
    total_baseline_cap = 0.0
    total_night_residual = 0.0
    total_corrected = 0.0
    night_hours_capped = 0

    with open(SOURCE_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row["日期"]
            hour_text = row["小时"]
            site_kwh = to_float(row["总站总负载(度)"])
            order_kwh = to_float(row["订单充电量(度)"])
            original_factory_kwh = to_float(row["拟合工厂用电(度)"])

            baseline_kwh = 0.0
            night_residual_kwh = 0.0
            corrected_factory_kwh = original_factory_kwh

            if is_night_hour(hour_text):
                baseline_kwh = min(original_factory_kwh, NIGHT_BASELINE_KW)
                corrected_factory_kwh = baseline_kwh
                night_residual_kwh = max(0.0, original_factory_kwh - baseline_kwh)
                if night_residual_kwh > 0:
                    night_hours_capped += 1

            hourly_row = {
                "日期": date_str,
                "小时": hour_text,
                "是否夜间": "是" if is_night_hour(hour_text) else "否",
                "总站总负载(度)": round(site_kwh, 4),
                "订单充电量(度)": round(order_kwh, 4),
                "原拟合工厂用电(度)": round(original_factory_kwh, 4),
                "夜间基础负荷封顶值(度)": round(baseline_kwh, 4),
                "夜间超基线残余(度)": round(night_residual_kwh, 4),
                "新版修正后厂区用电(度)": round(corrected_factory_kwh, 4),
            }
            hourly_rows.append(hourly_row)

            daily[date_str]["总站总负载(度)"] += site_kwh
            daily[date_str]["订单充电量(度)"] += order_kwh
            daily[date_str]["原拟合工厂用电(度)"] += original_factory_kwh
            daily[date_str]["夜间基础负荷封顶值(度)"] += baseline_kwh
            daily[date_str]["夜间超基线残余(度)"] += night_residual_kwh
            daily[date_str]["新版修正后厂区用电(度)"] += corrected_factory_kwh

            total_original += original_factory_kwh
            total_baseline_cap += baseline_kwh
            total_night_residual += night_residual_kwh
            total_corrected += corrected_factory_kwh

    hourly_fieldnames = list(hourly_rows[0].keys())
    with open(OUT_HOURLY_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=hourly_fieldnames)
        writer.writeheader()
        writer.writerows(hourly_rows)

    daily_rows = []
    for date_str in sorted(daily):
        row = {"日期": date_str}
        row.update({name: round(value, 4) for name, value in daily[date_str].items()})
        daily_rows.append(row)

    daily_fieldnames = list(daily_rows[0].keys())
    with open(OUT_DAILY_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=daily_fieldnames)
        writer.writeheader()
        writer.writerows(daily_rows)

    write_xlsx(OUT_HOURLY_XLSX, "202606_factory_hourly_v2", hourly_fieldnames, hourly_rows)
    write_xlsx(OUT_DAILY_XLSX, "202606_factory_daily_v2", daily_fieldnames, daily_rows)

    top_days = sorted(daily_rows, key=lambda row: row["新版修正后厂区用电(度)"], reverse=True)[:5]
    low_days = sorted(daily_rows, key=lambda row: row["新版修正后厂区用电(度)"])[:5]

    lines = []
    lines.append("# 6月工厂用电新版结论报告")
    lines.append("")
    lines.append("- 口径更新：不再使用旧版 `固定底损 + 动态损耗` 的整月统一回归扣减。")
    lines.append(f"- 新版夜间基础负荷基线采用：`{NIGHT_BASELINE_KW:.4f} kW`。")
    lines.append("- 夜间定义：`18:00-23:59` 与 `00:00-05:59`。")
    lines.append("- 新版修正规则：夜间小时 `厂区用电 = min(原拟合工厂用电, 夜间基础负荷基线)`；超出基线的部分单列为 `夜间超基线残余`。")
    lines.append("- 白天时段暂保留原拟合值，不再沿用旧回归结果直接扣减。")
    lines.append("")
    lines.append("## 6月总览")
    lines.append(f"- 原拟合工厂用电合计：`{total_original:.2f}` 度")
    lines.append(f"- 夜间基础负荷封顶合计：`{total_baseline_cap:.2f}` 度")
    lines.append(f"- 夜间超基线残余合计：`{total_night_residual:.2f}` 度")
    lines.append(f"- 新版修正后厂区用电合计：`{total_corrected:.2f}` 度")
    lines.append(f"- 被夜间基线封顶的小时数：`{night_hours_capped}`")
    lines.append("")
    lines.append("## 结果解读")
    lines.append("- `新版修正后厂区用电` 更接近厂区生产负荷与宿舍生活负荷本身。")
    lines.append("- `夜间超基线残余` 更像充电相关附加损耗、设备待机异常或其他非厂区背景负荷。")
    lines.append("- 由于白天仍缺少独立工厂电表，白天部分暂不进一步拆分。")
    lines.append("")
    lines.append("## 日用电较高日期 Top 5")
    for row in top_days:
        lines.append(
            f"- `{row['日期']}`：新版厂区用电 `{row['新版修正后厂区用电(度)']:.2f}` 度，夜间超基线残余 `{row['夜间超基线残余(度)']:.2f}` 度"
        )
    lines.append("")
    lines.append("## 日用电较低日期 Top 5")
    for row in low_days:
        lines.append(
            f"- `{row['日期']}`：新版厂区用电 `{row['新版修正后厂区用电(度)']:.2f}` 度，夜间超基线残余 `{row['夜间超基线残余(度)']:.2f}` 度"
        )
    lines.append("")
    lines.append("## 相关文件")
    lines.append("- `报告/工厂用电拟合_202606_逐日逐小时.xlsx`")
    lines.append("- `报告/工厂用电拟合_202606_按天统计.xlsx`")
    lines.append("- `报告/json/工厂用电拟合_202606_逐日逐小时_修正后.csv`")
    lines.append("- `报告/json/工厂用电拟合_202606_按天统计.csv`")
    lines.append("- `报告/6月夜间基础负荷分析.md`")
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    print("hourly_csv", OUT_HOURLY_CSV)
    print("daily_csv", OUT_DAILY_CSV)
    print("hourly_xlsx", OUT_HOURLY_XLSX)
    print("daily_xlsx", OUT_DAILY_XLSX)
    print("report_md", OUT_REPORT)
    print("total_original", round(total_original, 2))
    print("total_night_residual", round(total_night_residual, 2))
    print("total_corrected", round(total_corrected, 2))
    print("night_hours_capped", night_hours_capped)


if __name__ == "__main__":
    main()
