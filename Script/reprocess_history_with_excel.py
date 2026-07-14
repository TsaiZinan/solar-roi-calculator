import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from calc_revenue import calc_profit_for_price, generate_report, process_data
from config import DATA_DIR
from pv_excel_source import (
    archive_daily_inputs,
    find_daily_csv_for_date,
    get_excel_paths,
    infer_excel_date,
    merge_excel_curve_into_csv,
)


def compute_pv_total_kwh(csv_path):
    df = pd.read_csv(csv_path)
    if "光伏发电功率(kW)" not in df.columns:
        return None
    pv_series = pd.to_numeric(df["光伏发电功率(kW)"], errors="coerce").fillna(0.0).clip(lower=0)
    return round(float(pv_series.sum()) * (5 / 60), 2)


def parse_daily_report_metrics(report_path):
    if not os.path.exists(report_path):
        return None

    text = Path(report_path).read_text(encoding="utf-8")
    metrics = {}
    for price_key, price_label in [("01", "0.1"), ("02", "0.2"), ("035", "0.35")]:
        block_match = re.search(
            r"### 【场景 [A-Z]：光伏上网电价 "
            + re.escape(price_label)
            + r" 元/度】(.*?)(?=\n### 【场景 |\Z)",
            text,
            re.S,
        )
        if not block_match:
            continue

        block = block_match.group(1)
        total_match = re.search(r"经营总收益.*?\*\*([0-9.\-]+)\*\* 元", block, re.S)
        extra_match = re.search(r"上述各项收益中有 \*\*([0-9.\-]+)\*\* 元由", block, re.S)
        factory_match = re.search(r"工厂省电收益.*?\*\*([0-9.\-]+)\*\* 元", block, re.S)

        metrics[price_key] = {
            "with_storage_total": float(total_match.group(1)) if total_match else None,
            "extra_profit": float(extra_match.group(1)) if extra_match else None,
            "factory_savings": float(factory_match.group(1)) if factory_match else None,
        }

    return metrics or None


def collect_baseline():
    baseline = {}
    for date_folder in sorted(Path(DATA_DIR).glob("20*")):
        if not date_folder.is_dir():
            continue
        csv_candidates = sorted(date_folder.glob("*.csv"))
        if not csv_candidates:
            continue
        csv_path = str(csv_candidates[0])
        date_str = date_folder.name
        report_path = str(Path(DATA_DIR).parent / "报告" / f"每日收益分析报告_{date_str}.md")
        baseline[date_str] = {
            "csv_path": csv_path,
            "report_path": report_path,
            "pv_total_kwh": compute_pv_total_kwh(csv_path),
            "report_metrics": parse_daily_report_metrics(report_path),
        }
    return baseline


def simulate_excel_metrics(excel_path, csv_path):
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp_file:
        temp_csv_path = tmp_file.name

    try:
        merge_result = merge_excel_curve_into_csv(excel_path, csv_path, output_csv_path=temp_csv_path)
        date_str, stats = process_data(temp_csv_path)
        report_metrics = {}
        for price_key, price in [("01", 0.1), ("02", 0.2), ("035", 0.35)]:
            result = calc_profit_for_price(date_str, stats, price)
            report_metrics[price_key] = {
                "with_storage_total": round(result["with_storage_total"], 2),
                "extra_profit": round(result["extra_profit"], 2),
                "factory_savings": round(result["factory_savings"], 2),
            }
        return {
            "pv_total_kwh": merge_result["pv_total_kwh"],
            "report_metrics": report_metrics,
        }
    finally:
        if os.path.exists(temp_csv_path):
            os.remove(temp_csv_path)


def rounded_delta(before_value, after_value):
    if before_value is None or after_value is None:
        return None
    return round(after_value - before_value, 2)


def build_comparison(before_map, after_map):
    comparison = []
    for date_str in sorted(after_map):
        before = before_map.get(date_str, {})
        after = after_map.get(date_str, {})

        pv_before = before.get("pv_total_kwh")
        pv_after = after.get("pv_total_kwh")
        row = {
            "date": date_str,
            "pv_total_before_kwh": pv_before,
            "pv_total_after_kwh": pv_after,
            "pv_total_delta_kwh": rounded_delta(pv_before, pv_after),
            "report_changes": {},
        }

        for price_key in ("01", "02", "035"):
            old_metrics = (before.get("report_metrics") or {}).get(price_key) or {}
            new_metrics = (after.get("report_metrics") or {}).get(price_key) or {}
            row["report_changes"][price_key] = {
                "with_storage_total_before": old_metrics.get("with_storage_total"),
                "with_storage_total_after": new_metrics.get("with_storage_total"),
                "with_storage_total_delta": rounded_delta(
                    old_metrics.get("with_storage_total"),
                    new_metrics.get("with_storage_total"),
                ),
                "extra_profit_before": old_metrics.get("extra_profit"),
                "extra_profit_after": new_metrics.get("extra_profit"),
                "extra_profit_delta": rounded_delta(
                    old_metrics.get("extra_profit"),
                    new_metrics.get("extra_profit"),
                ),
                "factory_savings_before": old_metrics.get("factory_savings"),
                "factory_savings_after": new_metrics.get("factory_savings"),
                "factory_savings_delta": rounded_delta(
                    old_metrics.get("factory_savings"),
                    new_metrics.get("factory_savings"),
                ),
            }

        comparison.append(row)

    return comparison


def is_affected(row):
    if row["pv_total_delta_kwh"] not in (None, 0):
        return True
    for metrics in row["report_changes"].values():
        for key in ("with_storage_total_delta", "extra_profit_delta", "factory_savings_delta"):
            if metrics.get(key) not in (None, 0):
                return True
    return False


def compare_history():
    baseline = collect_baseline()
    excel_map = {}
    missing_csv_dates = []
    duplicate_dates = {}

    for excel_path in get_excel_paths(include_archived=True):
        date_str = infer_excel_date(excel_path)
        if date_str in excel_map:
            duplicate_dates.setdefault(date_str, []).append(excel_path)
            continue
        excel_map[date_str] = excel_path

    after = {}
    for date_str, excel_path in sorted(excel_map.items()):
        try:
            csv_path = find_daily_csv_for_date(date_str)
        except FileNotFoundError:
            missing_csv_dates.append(date_str)
            continue
        after[date_str] = simulate_excel_metrics(excel_path, csv_path)

    comparison = build_comparison(baseline, after)
    affected = [row for row in comparison if is_affected(row)]

    output_dir = Path(DATA_DIR).parent / ".tmp_compare"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "excel_reprocess_comparison.json"
    output_payload = {
        "affected_dates": [row["date"] for row in affected],
        "missing_csv_dates": missing_csv_dates,
        "duplicate_excel_dates": duplicate_dates,
        "comparison": comparison,
    }
    output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"对比结果已写入: {output_path}")
    print("受影响日期:", ", ".join(output_payload["affected_dates"]) or "无")
    if missing_csv_dates:
        print("缺少 CSV 的日期:", ", ".join(missing_csv_dates))


def apply_history():
    excel_paths = get_excel_paths(include_archived=False)
    if not excel_paths:
        raise FileNotFoundError("未找到待归档的光伏 Excel 文件。")

    touched_dates = []
    skipped_dates = []
    for excel_path in excel_paths:
        date_str = infer_excel_date(excel_path)
        try:
            csv_path = find_daily_csv_for_date(date_str)
        except FileNotFoundError:
            skipped_dates.append(date_str)
            print(f"跳过 {date_str}: 未找到对应 CSV，暂不更新该日期。")
            continue
        archived_csv_path, archived_excel_path = archive_daily_inputs(date_str, csv_path, excel_path)
        merge_result = merge_excel_curve_into_csv(archived_excel_path, archived_csv_path)
        touched_dates.append(date_str)
        print(
            f"已同步 {merge_result['date']} 光伏数据: "
            f"{merge_result['pv_total_kwh']:.2f} kWh -> {merge_result['csv_path']}"
        )

    for date_str in sorted(set(touched_dates)):
        csv_path = find_daily_csv_for_date(date_str)
        print(f"重生成收益报告: {csv_path}")
        generate_report(csv_path)

    if skipped_dates:
        print("以下日期缺少 CSV，未执行正式更新:", ", ".join(sorted(set(skipped_dates))))


def main():
    parser = argparse.ArgumentParser(
        description="将历史光伏发电量数据源切换为 Excel。默认只生成新旧差异对比，确认后可加 --apply 正式写回 CSV 并重生成报告。"
    )
    parser.add_argument("--apply", action="store_true", help="正式写回 CSV、归档 Excel，并重生成日报/总表")
    args = parser.parse_args()

    if args.apply:
        apply_history()
        return

    compare_history()


if __name__ == "__main__":
    main()
