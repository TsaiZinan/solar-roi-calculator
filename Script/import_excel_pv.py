import argparse
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pv_excel_source import archive_daily_inputs, infer_excel_date, merge_excel_curve_into_csv


def main():
    parser = argparse.ArgumentParser(description="将光伏 Excel 中的 5 分钟功率数据回写到日度 CSV。")
    parser.add_argument("excel_path", help="光伏 Excel 文件路径")
    parser.add_argument("csv_path", help="日度 CSV 文件路径")
    parser.add_argument("--archive", action="store_true", help="按数据日期将 Excel 和 CSV 归档到 数据/YYYYMMDD/ 目录")
    parser.add_argument("--output-csv", help="可选：输出到新 CSV 路径，默认覆盖原 CSV")
    args = parser.parse_args()

    excel_path = args.excel_path
    csv_path = args.csv_path
    date_str = infer_excel_date(excel_path)

    if args.archive:
        csv_path, excel_path = archive_daily_inputs(date_str, csv_path, excel_path)

    result = merge_excel_curve_into_csv(excel_path, csv_path, output_csv_path=args.output_csv)
    print(f"日期: {result['date']}")
    print(f"Excel: {result['excel_path']}")
    print(f"CSV: {result['csv_path']}")
    print(f"行数: {result['csv_rows']}")
    print(f"光伏总发电量: {result['pv_total_kwh']:.2f} kWh")


if __name__ == "__main__":
    main()
