import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from calc_revenue import generate_report
from config import ensure_report_dir, get_daily_csv_paths


def main():
    ensure_report_dir()
    csv_paths = get_daily_csv_paths()

    if not csv_paths:
        raise FileNotFoundError("未找到可用于重生成日报的日度 CSV 文件。")

    for csv_path in csv_paths:
        print(f"重生成日报: {csv_path}")
        generate_report(csv_path)


if __name__ == "__main__":
    main()
