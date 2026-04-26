import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd

from calc_revenue import generate_report
from config import DATA_DIR, REPORT_DIR, get_daily_csv_paths
from extract_and_merge_pv import extract_and_merge


IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def find_image_for_date(date_str):
    folder = Path(DATA_DIR) / date_str
    for suffix in IMAGE_SUFFIXES:
        candidate = folder / f"{date_str}{suffix}"
        if candidate.exists():
            return str(candidate)

    for candidate in sorted(folder.iterdir()):
        if candidate.suffix.lower() in IMAGE_SUFFIXES:
            return str(candidate)

    raise FileNotFoundError(f"未找到 {date_str} 对应的光伏截图。")


def compute_pv_total_kwh(csv_path):
    df = pd.read_csv(csv_path)
    if "光伏发电功率(kW)" not in df.columns:
        return None
    pv_series = df["光伏发电功率(kW)"].clip(lower=0)
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
        total_match = re.search(r"含储能经营总收益.*?\*\*([0-9.\-]+)\*\* 元", block, re.S)
        extra_match = re.search(r"(?:实际额外增益|额外创收)\*\* \*\*([0-9.\-]+)\*\* 元", block, re.S)
        factory_match = re.search(r"工厂省电收益.*?\*\*([0-9.\-]+)\*\* 元", block, re.S)

        metrics[price_key] = {
            "with_storage_total": float(total_match.group(1)) if total_match else None,
            "extra_profit": float(extra_match.group(1)) if extra_match else None,
            "factory_savings": float(factory_match.group(1)) if factory_match else None,
        }

    return metrics or None


def collect_baseline():
    baseline = {}
    for csv_path in get_daily_csv_paths():
        date_str = re.search(r"(20\d{6})", csv_path).group(1)
        report_path = os.path.join(REPORT_DIR, f"每日收益分析报告_{date_str}.md")
        baseline[date_str] = {
            "csv_path": csv_path,
            "report_path": report_path,
            "pv_total_kwh": compute_pv_total_kwh(csv_path),
            "report_metrics": parse_daily_report_metrics(report_path),
        }
    return baseline


def build_comparison(before_map, after_map):
    comparison = []
    for date_str in sorted(after_map):
        before = before_map.get(date_str, {})
        after = after_map.get(date_str, {})

        pv_before = before.get("pv_total_kwh")
        pv_after = after.get("pv_total_kwh")
        pv_delta = None
        if pv_before is not None and pv_after is not None:
            pv_delta = round(pv_after - pv_before, 2)

        row = {
            "date": date_str,
            "pv_total_before_kwh": pv_before,
            "pv_total_after_kwh": pv_after,
            "pv_total_delta_kwh": pv_delta,
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


def rounded_delta(before_value, after_value):
    if before_value is None or after_value is None:
        return None
    return round(after_value - before_value, 2)


def is_affected(row):
    if row["pv_total_delta_kwh"] not in (None, 0):
        return True

    for metrics in row["report_changes"].values():
        for key in (
            "with_storage_total_delta",
            "extra_profit_delta",
            "factory_savings_delta",
        ):
            if metrics.get(key) not in (None, 0):
                return True
    return False


def collect_current_state():
    current = {}
    for csv_path in get_daily_csv_paths():
        date_str = re.search(r"(20\d{6})", csv_path).group(1)
        report_path = os.path.join(REPORT_DIR, f"每日收益分析报告_{date_str}.md")
        current[date_str] = {
            "csv_path": csv_path,
            "report_path": report_path,
            "pv_total_kwh": compute_pv_total_kwh(csv_path),
            "report_metrics": parse_daily_report_metrics(report_path),
        }
    return current


def main(use_calibration=False):
    baseline = collect_baseline()

    for date_str, item in sorted(baseline.items()):
        image_path = find_image_for_date(date_str)
        print(f"重识别光伏曲线: {date_str}")
        extract_and_merge(
            image_path,
            item["csv_path"],
            date_str=date_str,
            use_calibration=use_calibration,
        )

    for csv_path in get_daily_csv_paths():
        print(f"重生成收益报告: {csv_path}")
        generate_report(csv_path)

    after = collect_current_state()
    comparison = build_comparison(baseline, after)
    affected = [row for row in comparison if is_affected(row)]

    output_dir = Path(DATA_DIR).parent / ".tmp_compare"
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "ocr_reprocess_comparison.json"
    output_path.write_text(
        json.dumps(
            {
                "affected_dates": [row["date"] for row in affected],
                "comparison": comparison,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"对比结果已写入: {output_path}")
    print("受影响日期:", ", ".join(row["date"] for row in affected) or "无")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="批量重识别历史光伏截图，并可按需启用 数据校准.csv 进行日发电量校准。"
    )
    parser.add_argument(
        "--use-calibration",
        action="store_true",
        help="按需启用 数据/数据校准.csv 中的日发电量校准",
    )
    args = parser.parse_args()
    main(use_calibration=args.use_calibration)
