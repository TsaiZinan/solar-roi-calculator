import glob
import os
import shutil
import warnings
from pathlib import Path

import pandas as pd

from config import DATA_DIR, PV_EXCEL_PREFIX


EXCEL_SHEET_NAME = "能量趋势"
TIME_COLUMN = "时间"
PV_COLUMN = "光伏发电功率(kW)"
DAILY_CSV_PREFIX = "日报表_"

warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style, apply openpyxl's default",
    category=UserWarning,
)


def _normalize_header(value):
    return str(value or "").strip().replace(" ", "")


def get_excel_paths(data_dir=DATA_DIR, include_archived=False):
    excel_paths = glob.glob(os.path.join(data_dir, f"{PV_EXCEL_PREFIX}*.xlsx"))
    if include_archived:
        excel_paths.extend(glob.glob(os.path.join(data_dir, "20*", f"{PV_EXCEL_PREFIX}*.xlsx")))
    return sorted(set(excel_paths))


def load_excel_curve(excel_path):
    raw = pd.read_excel(excel_path, sheet_name=EXCEL_SHEET_NAME, header=None)
    if raw.shape[0] < 3:
        raise ValueError(f"Excel 文件结构异常，无法读取光伏功率数据: {excel_path}")

    headers = [_normalize_header(value) for value in raw.iloc[1].tolist()]
    data = raw.iloc[2:].copy()
    data.columns = headers

    if "日期" not in data.columns or PV_COLUMN not in data.columns:
        raise ValueError(
            f"Excel 缺少必要列，期望包含 `日期` 和 `{PV_COLUMN}`: {excel_path}"
        )

    curve_df = data[["日期", PV_COLUMN]].copy()
    curve_df["日期"] = pd.to_datetime(curve_df["日期"], errors="coerce")
    curve_df = curve_df.dropna(subset=["日期"])
    if curve_df.empty:
        raise ValueError(f"Excel 中未找到有效时间序列: {excel_path}")

    curve_df[PV_COLUMN] = pd.to_numeric(curve_df[PV_COLUMN], errors="coerce").fillna(0.0)
    curve_df = curve_df.rename(columns={"日期": TIME_COLUMN})
    curve_df = curve_df.sort_values(TIME_COLUMN).drop_duplicates(subset=[TIME_COLUMN], keep="last")
    curve_df[PV_COLUMN] = curve_df[PV_COLUMN].clip(lower=0.0).round(3)

    date_values = curve_df[TIME_COLUMN].dt.strftime("%Y%m%d").unique().tolist()
    if len(date_values) != 1:
        raise ValueError(f"Excel 中包含多个日期，暂不支持直接处理: {excel_path}")

    return date_values[0], curve_df.reset_index(drop=True)


def infer_excel_date(excel_path):
    date_str, _ = load_excel_curve(excel_path)
    return date_str


def compute_curve_total_kwh(curve_df):
    return round(float(curve_df[PV_COLUMN].clip(lower=0).sum()) * (5 / 60), 2)


def infer_csv_date(csv_path):
    df = pd.read_csv(csv_path, usecols=[TIME_COLUMN], nrows=1)
    if df.empty:
        raise ValueError(f"CSV 不包含有效数据行: {csv_path}")
    timestamp = pd.to_datetime(df.iloc[0][TIME_COLUMN], errors="raise")
    return timestamp.strftime("%Y%m%d")


def find_daily_csv_for_date(date_str, data_dir=DATA_DIR):
    folder = Path(data_dir) / date_str
    folder_candidates = sorted(folder.glob("*.csv"))
    if folder_candidates:
        return str(folder_candidates[0])

    root_candidates = sorted(Path(data_dir).glob(f"{DAILY_CSV_PREFIX}*.csv"))
    for candidate in root_candidates:
        try:
            if infer_csv_date(candidate) == date_str:
                return str(candidate)
        except Exception:
            continue

    raise FileNotFoundError(f"未找到 {date_str} 对应的日度 CSV 文件。")


def _move_to_date_folder(file_path, date_str, data_dir=DATA_DIR):
    if not file_path:
        return None

    src = Path(file_path)
    target_dir = Path(data_dir) / date_str
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / src.name

    if src.resolve() == target_path.resolve():
        return str(target_path)

    if target_path.exists():
        raise FileExistsError(f"目标文件已存在，请先确认是否重复归档: {target_path}")

    shutil.move(str(src), str(target_path))
    return str(target_path)


def archive_daily_inputs(date_str, csv_path, excel_path=None, data_dir=DATA_DIR):
    archived_csv_path = _move_to_date_folder(csv_path, date_str, data_dir=data_dir)
    archived_excel_path = _move_to_date_folder(excel_path, date_str, data_dir=data_dir)
    return archived_csv_path, archived_excel_path


def merge_excel_curve_into_csv(excel_path, csv_path, output_csv_path=None):
    date_str, curve_df = load_excel_curve(excel_path)

    csv_df = pd.read_csv(csv_path)
    if TIME_COLUMN not in csv_df.columns:
        raise ValueError(f"CSV 缺少 `{TIME_COLUMN}` 列: {csv_path}")

    csv_df[TIME_COLUMN] = pd.to_datetime(csv_df[TIME_COLUMN], errors="raise")
    csv_date_values = csv_df[TIME_COLUMN].dt.strftime("%Y%m%d").dropna().unique().tolist()
    if len(csv_date_values) != 1:
        raise ValueError(f"CSV 中包含多个日期，无法与 Excel 对齐: {csv_path}")
    if csv_date_values[0] != date_str:
        raise ValueError(
            f"Excel 日期 {date_str} 与 CSV 日期 {csv_date_values[0]} 不一致: {excel_path} <-> {csv_path}"
        )

    merged_df = csv_df.merge(
        curve_df,
        on=TIME_COLUMN,
        how="left",
        suffixes=("", "__excel"),
    )
    excel_value_col = f"{PV_COLUMN}__excel"
    if excel_value_col in merged_df.columns:
        source_pv_col = excel_value_col
    elif PV_COLUMN in merged_df.columns and PV_COLUMN not in csv_df.columns:
        source_pv_col = PV_COLUMN
    else:
        raise ValueError(
            f"合并后未找到 Excel 光伏功率列，请检查 CSV/Excel 列结构: {excel_path} <-> {csv_path}"
        )

    missing_matches = int(merged_df[source_pv_col].isna().sum())
    if missing_matches:
        raise ValueError(
            f"Excel 与 CSV 时间未完全对齐，存在 {missing_matches} 行缺失: {excel_path} <-> {csv_path}"
        )

    merged_df[PV_COLUMN] = merged_df[source_pv_col].round(3)
    if source_pv_col != PV_COLUMN:
        merged_df = merged_df.drop(columns=[source_pv_col])

    save_path = output_csv_path or csv_path
    merged_df[TIME_COLUMN] = merged_df[TIME_COLUMN].dt.strftime("%Y-%m-%d %H:%M:%S")
    merged_df.to_csv(save_path, index=False)

    return {
        "date": date_str,
        "csv_path": save_path,
        "excel_path": excel_path,
        "csv_rows": len(merged_df),
        "pv_total_kwh": compute_curve_total_kwh(curve_df),
    }
