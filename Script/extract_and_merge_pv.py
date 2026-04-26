import argparse
import cv2
import numpy as np
import pandas as pd
import os
import re
import shutil
import subprocess
import tempfile
from scipy.interpolate import interp1d

from config import PV_CALIBRATION_PATH

DEFAULT_X_START = 321.0
DEFAULT_PX_PER_HOUR = 92.0227
DEFAULT_Y_ZERO = 943.0
DEFAULT_PX_PER_100KW = 138.5
OCR_UPSCALE = 2
OCR_MIN_CONFIDENCE = 50.0


def _parse_tesseract_tsv(tsv_text):
    lines = tsv_text.splitlines()
    if not lines:
        return []

    entries = []
    for line in lines[1:]:
        parts = line.split('\t')
        if len(parts) < 12:
            continue

        text = parts[11].strip()
        if not text:
            continue

        try:
            entries.append({
                'left': int(parts[6]),
                'top': int(parts[7]),
                'width': int(parts[8]),
                'height': int(parts[9]),
                'conf': float(parts[10]),
                'text': text,
            })
        except ValueError:
            continue

    return entries


def _detect_y_axis_scale_with_ocr(img):
    tesseract_bin = shutil.which("tesseract")
    if not tesseract_bin:
        return None

    height, width = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(
        gray, None, fx=OCR_UPSCALE, fy=OCR_UPSCALE, interpolation=cv2.INTER_CUBIC
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        temp_path = tmp_file.name

    try:
        cv2.imwrite(temp_path, enlarged)
        result = subprocess.run(
            [tesseract_bin, temp_path, "stdout", "--psm", "11", "tsv"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None

        numeric_entries = []
        for entry in _parse_tesseract_tsv(result.stdout):
            if entry['conf'] < OCR_MIN_CONFIDENCE:
                continue

            text = entry['text'].replace("O", "0").replace("o", "0")
            if not text.isdigit():
                continue

            value = int(text)
            if value <= 0 or value > 1000:
                continue

            center_x = (entry['left'] + entry['width'] / 2) / OCR_UPSCALE
            center_y = (entry['top'] + entry['height'] / 2) / OCR_UPSCALE

            # 纵轴刻度通常位于左侧区域，且不会落在图例底部。
            if center_x > width * 0.18:
                continue
            if center_y < height * 0.05 or center_y > height * 0.8:
                continue

            numeric_entries.append({
                'value': value,
                'x': center_x,
                'y': center_y,
                'conf': entry['conf'],
            })

        if len(numeric_entries) < 2:
            return None

        best_by_value = {}
        for entry in numeric_entries:
            current = best_by_value.get(entry['value'])
            if current is None or entry['conf'] > current['conf']:
                best_by_value[entry['value']] = entry

        points = list(best_by_value.values())
        if len(points) < 2:
            return None

        values = np.array([p['value'] for p in points], dtype=float)
        y_centers = np.array([p['y'] for p in points], dtype=float)

        slope, intercept = np.polyfit(values, y_centers, 1)
        if slope >= 0:
            return None

        y_zero = float(intercept)
        px_per_100kw = float(abs(slope) * 100.0)
        if px_per_100kw <= 0:
            return None

        recognized_values = sorted(int(v) for v in values)
        return {
            'y_zero': y_zero,
            'px_per_100kw': px_per_100kw,
            'recognized_values': recognized_values,
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _normalize_date_str(date_str):
    if date_str is None:
        return None

    if isinstance(date_str, (int, np.integer)):
        digits = str(int(date_str))
    elif isinstance(date_str, (float, np.floating)):
        if not np.isfinite(date_str):
            raise ValueError(f"无法识别日期格式: {date_str}")
        rounded = int(round(float(date_str)))
        if abs(float(date_str) - rounded) > 1e-6:
            raise ValueError(f"无法识别日期格式: {date_str}")
        digits = str(rounded)
    else:
        raw_text = str(date_str).strip()
        if raw_text.endswith(".0"):
            raw_text = raw_text[:-2]
        digits = re.sub(r"\D", "", raw_text)

    if len(digits) != 8:
        raise ValueError(f"无法识别日期格式: {date_str}")
    return digits


def _infer_date_from_paths(*paths):
    for path in paths:
        if not path:
            continue
        match = re.search(r"(20\d{6})", str(path))
        if match:
            return match.group(1)
    return None


def load_calibration_map(calibration_csv_path=PV_CALIBRATION_PATH):
    if not os.path.exists(calibration_csv_path):
        raise FileNotFoundError(f"未找到校准文件: {calibration_csv_path}")

    df = pd.read_csv(calibration_csv_path)
    if df.empty:
        return {}

    if {"日期", "每日光伏总发电量"}.issubset(df.columns):
        date_col = "日期"
        total_col = "每日光伏总发电量"
    elif len(df.columns) >= 2:
        date_col = df.columns[0]
        total_col = df.columns[1]
    else:
        raise ValueError("数据校准.csv 至少需要两列：日期、每日光伏总发电量")

    calibration_map = {}
    for _, row in df.iterrows():
        raw_date = row.get(date_col)
        raw_total = row.get(total_col)
        if pd.isna(raw_date) or pd.isna(raw_total):
            continue

        date_str = _normalize_date_str(raw_date)
        try:
            total_kwh = float(raw_total)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"数据校准.csv 中 {date_str} 的每日光伏总发电量不是有效数字: {raw_total}"
            ) from exc

        if total_kwh < 0:
            raise ValueError(f"数据校准.csv 中 {date_str} 的每日光伏总发电量不能为负数")

        calibration_map[date_str] = total_kwh

    return calibration_map


def resolve_calibration_target(
    image_path,
    csv_path,
    date_str=None,
    calibration_csv_path=PV_CALIBRATION_PATH,
):
    resolved_date = _normalize_date_str(date_str) if date_str else _infer_date_from_paths(image_path, csv_path)
    if not resolved_date:
        print("未能从图片或 CSV 路径推断日期，跳过校准。")
        return None

    calibration_map = load_calibration_map(calibration_csv_path)
    target_kwh = calibration_map.get(resolved_date)
    if target_kwh is None:
        print(f"校准文件中未配置 {resolved_date} 的每日光伏总发电量，跳过校准。")
        return None

    print(f"启用校准: {resolved_date} -> 目标日发电量 {target_kwh:.2f} kWh")
    return target_kwh


def extract_and_merge(
    image_path,
    csv_path,
    output_csv_path=None,
    target_generation_kwh=None,
    date_str=None,
    use_calibration=False,
    calibration_csv_path=PV_CALIBRATION_PATH,
):
    if output_csv_path is None:
        output_csv_path = csv_path

    print(f"Reading image: {image_path}")
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Could not read image at {image_path}")

    # 1. 提取曲线的像素坐标
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # 定义绿色的HSV范围 (根据原图颜色调整)
    lower_green = (40, 50, 50)
    upper_green = (90, 255, 255)
    
    # 提取绿色部分
    mask = cv2.inRange(hsv, lower_green, upper_green)
    y_coords, x_coords = np.where(mask > 0)
    
    if len(x_coords) == 0:
        raise ValueError("No green pixels found in the image.")

    # 对每个 X 坐标，取 Y 坐标的平均值（曲线有一定的宽度）
    unique_x = np.unique(x_coords)
    avg_y = [np.mean(y_coords[x_coords == x]) for x in unique_x]
    
    df_pixels = pd.DataFrame({'x': unique_x, 'y': avg_y})
    
    # 过滤掉底部图例部分 (y > 1000)
    df_pixels = df_pixels[df_pixels['y'] < 1000].copy()

    # 2. 坐标轴映射
    # X 轴仍沿用当前样图标定参数，Y 轴优先通过 OCR 自动识别刻度。
    x_start = DEFAULT_X_START
    px_per_hour = DEFAULT_PX_PER_HOUR
    y_zero = DEFAULT_Y_ZERO
    px_per_100kw = DEFAULT_PX_PER_100KW

    ocr_scale = _detect_y_axis_scale_with_ocr(img)
    if ocr_scale:
        y_zero = ocr_scale['y_zero']
        px_per_100kw = ocr_scale['px_per_100kw']
        print(
            "Detected Y-axis scale via OCR:",
            f"labels={ocr_scale['recognized_values']},",
            f"y_zero={y_zero:.2f},",
            f"px_per_100kw={px_per_100kw:.2f}",
        )
    else:
        print(
            "Y-axis OCR unavailable or failed, fallback to defaults:",
            f"y_zero={y_zero:.2f}, px_per_100kw={px_per_100kw:.2f}",
        )

    # 转换为实际的物理单位
    df_pixels['hours'] = (df_pixels['x'] - x_start) / px_per_hour
    df_pixels['kW'] = (y_zero - df_pixels['y']) / px_per_100kw * 100
    df_pixels['kW'] = df_pixels['kW'].clip(lower=0)  # 发电功率不能为负

    # 3. 数据插值
    hours = df_pixels['hours'].values
    kw = df_pixels['kW'].values

    # 在两端补0，代表夜间没有光伏发电
    t = np.concatenate(([0.0], hours, [24.0]))
    p = np.concatenate(([0.0], kw, [0.0]))

    # 去重，确保插值函数可用
    t_unique, indices = np.unique(t, return_index=True)
    p_unique = p[indices]

    # 创建线性插值函数
    f = interp1d(t_unique, p_unique, kind='linear', fill_value=0, bounds_error=False)

    # 4. 生成目标时间点的数据 (每5分钟一次 = 5/60 小时)
    t_target = np.arange(0, 24, 5/60)
    p_target = f(t_target)
    p_target = np.clip(p_target, 0, None) # 确保没有负值

    if target_generation_kwh is None and use_calibration:
        target_generation_kwh = resolve_calibration_target(
            image_path=image_path,
            csv_path=csv_path,
            date_str=date_str,
            calibration_csv_path=calibration_csv_path,
        )

    # 缩放发电量以匹配目标值
    current_generation = np.sum(p_target) * (5 / 60)
    print(f"当前图片识别的日发电量: {current_generation:.2f} kWh")
    if target_generation_kwh is not None:
        if current_generation > 0:
            scale_factor = target_generation_kwh / current_generation
            p_target = p_target * scale_factor
            print(f"Scaled PV generation from {current_generation:.2f} kWh to {target_generation_kwh:.2f} kWh (factor: {scale_factor:.4f})")

    # 5. 读取并更新 CSV
    print(f"Reading CSV: {csv_path}")
    df_csv = pd.read_csv(csv_path)
    
    # 将新数据作为新列追加
    df_csv['光伏发电功率(kW)'] = np.round(p_target, 3)

    # 覆盖原文件或另存为新文件
    df_csv.to_csv(output_csv_path, index=False)
    print(f"Successfully integrated PV power data and saved to {output_csv_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="从光伏图片提取曲线并回写 CSV，可按需启用数据校准.csv 中的日发电量校准。"
    )
    parser.add_argument("image_path", help="图片路径")
    parser.add_argument("csv_path", help="CSV 路径")
    parser.add_argument("target_generation_kwh", nargs="?", type=float, help="可选：手工指定目标日发电量(kWh)")
    parser.add_argument("--date", dest="date_str", help="可选：指定日期，格式如 20260425")
    parser.add_argument(
        "--use-calibration",
        action="store_true",
        help="按需启用 数据/数据校准.csv 中的日发电量校准",
    )
    parser.add_argument(
        "--calibration-file",
        default=PV_CALIBRATION_PATH,
        help="校准文件路径，默认为 数据/数据校准.csv",
    )
    args = parser.parse_args()

    extract_and_merge(
        args.image_path,
        args.csv_path,
        target_generation_kwh=args.target_generation_kwh,
        date_str=args.date_str,
        use_calibration=args.use_calibration,
        calibration_csv_path=args.calibration_file,
    )
