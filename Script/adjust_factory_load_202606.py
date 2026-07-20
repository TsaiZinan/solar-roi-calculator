from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook


ROOT = Path("/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算")
SOURCE_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_逐日逐小时.csv"
OUT_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_逐日逐小时_修正后.csv"
OUT_XLSX = ROOT / "报告" / "工厂用电拟合_202606_逐日逐小时.xlsx"
OUT_MD = ROOT / "报告" / "6月工厂用电拟合修正说明.md"

# Inferred from the 00:00-06:59 non-working-period regression:
# residual_load ~= dynamic_ratio * order_kwh + fixed_loss_kwh_per_hour
FIXED_LOSS_KWH_PER_HOUR = 9.6798
DYNAMIC_LOSS_RATIO = 0.1365


def to_float(value):
    if value in (None, "", "-"):
        return 0.0
    return float(value)


def main():
    rows = []
    total_original_factory = 0.0
    total_fixed_loss = 0.0
    total_dynamic_loss = 0.0
    total_corrected_factory = 0.0
    zeroed_rows = 0

    with open(SOURCE_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            order_kwh = to_float(row["订单充电量(度)"])
            original_factory_kwh = to_float(row["拟合工厂用电(度)"])

            fixed_loss_kwh = FIXED_LOSS_KWH_PER_HOUR
            dynamic_loss_kwh = order_kwh * DYNAMIC_LOSS_RATIO
            total_loss_kwh = fixed_loss_kwh + dynamic_loss_kwh
            corrected_factory_kwh = max(0.0, original_factory_kwh - total_loss_kwh)
            if corrected_factory_kwh == 0.0 and original_factory_kwh > 0:
                zeroed_rows += 1

            rows.append(
                {
                    "日期": row["日期"],
                    "小时": row["小时"],
                    "总站总负载(度)": round(to_float(row["总站总负载(度)"]), 4),
                    "订单充电量(度)": round(order_kwh, 4),
                    "原拟合工厂用电(度)": round(original_factory_kwh, 4),
                    "固定底损(度)": round(fixed_loss_kwh, 4),
                    "动态损耗(度)": round(dynamic_loss_kwh, 4),
                    "总扣减(度)": round(total_loss_kwh, 4),
                    "修正后真实工厂用电(度)": round(corrected_factory_kwh, 4),
                }
            )

            total_original_factory += original_factory_kwh
            total_fixed_loss += fixed_loss_kwh
            total_dynamic_loss += dynamic_loss_kwh
            total_corrected_factory += corrected_factory_kwh

    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    wb = Workbook()
    ws = wb.active
    ws.title = "202606_factory_hourly"
    ws.append(list(rows[0].keys()))
    for row in rows:
        ws.append(list(row.values()))
    for col in ["A", "B", "C", "D", "E", "F", "G", "H", "I"]:
        ws.column_dimensions[col].width = 18
    wb.save(OUT_XLSX)

    md_lines = []
    md_lines.append("# 6月工厂用电拟合修正说明")
    md_lines.append("")
    md_lines.append("- 修正公式：`修正后真实工厂用电 = max(0, 原拟合工厂用电 - 固定底损 - 动态损耗)`")
    md_lines.append(f"- 固定底损：`{FIXED_LOSS_KWH_PER_HOUR:.4f}` 度/小时")
    md_lines.append(f"- 动态损耗：`订单充电量 * {DYNAMIC_LOSS_RATIO:.4f}`")
    md_lines.append("")
    md_lines.append(f"- 原拟合工厂用电合计：`{total_original_factory:.2f}` 度")
    md_lines.append(f"- 固定底损合计：`{total_fixed_loss:.2f}` 度")
    md_lines.append(f"- 动态损耗合计：`{total_dynamic_loss:.2f}` 度")
    md_lines.append(f"- 修正后真实工厂用电合计：`{total_corrected_factory:.2f}` 度")
    md_lines.append(f"- 被扣减到 0 的小时点数：`{zeroed_rows}`")
    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8")

    print("out_csv", OUT_CSV)
    print("out_xlsx", OUT_XLSX)
    print("out_md", OUT_MD)
    print("total_original_factory", round(total_original_factory, 2))
    print("total_fixed_loss", round(total_fixed_loss, 2))
    print("total_dynamic_loss", round(total_dynamic_loss, 2))
    print("total_corrected_factory", round(total_corrected_factory, 2))
    print("zeroed_rows", zeroed_rows)


if __name__ == "__main__":
    main()
