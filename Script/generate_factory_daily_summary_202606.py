from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook


ROOT = Path("/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算")
SOURCE_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_逐日逐小时_修正后.csv"
OUT_CSV = ROOT / "报告" / "json" / "工厂用电拟合_202606_按天统计.csv"
OUT_XLSX = ROOT / "报告" / "工厂用电拟合_202606_按天统计.xlsx"


FIELDNAMES = [
    "日期",
    "总站总负载(度)",
    "订单充电量(度)",
    "原拟合工厂用电(度)",
    "固定底损(度)",
    "动态损耗(度)",
    "总扣减(度)",
    "修正后真实工厂用电(度)",
]


def main():
    aggregated = defaultdict(lambda: {name: 0.0 for name in FIELDNAMES[1:]})

    with open(SOURCE_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row["日期"]
            for field in FIELDNAMES[1:]:
                aggregated[date_str][field] += float(row[field])

    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for date_str in sorted(aggregated):
            row = {"日期": date_str}
            for field in FIELDNAMES[1:]:
                row[field] = round(aggregated[date_str][field], 4)
            writer.writerow(row)

    wb = Workbook()
    ws = wb.active
    ws.title = "202606_daily"
    ws.append(FIELDNAMES)
    for date_str in sorted(aggregated):
        ws.append([date_str] + [round(aggregated[date_str][field], 4) for field in FIELDNAMES[1:]])
    for col in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        ws.column_dimensions[col].width = 20
    wb.save(OUT_XLSX)

    print("out_csv", OUT_CSV)
    print("out_xlsx", OUT_XLSX)


if __name__ == "__main__":
    main()
