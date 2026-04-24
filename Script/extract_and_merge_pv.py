import cv2
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d

def extract_and_merge(image_path, csv_path, output_csv_path=None, target_generation_kwh=None):
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
    # 根据之前的分析：
    # X轴: 00:00 对应 x=321, 22:00 对应 x=2345.5 -> 比例 92.0227 px/小时
    # Y轴: 0 kW 对应 y=943, 100 kW 对应 138.5 px
    x_start = 321.0
    px_per_hour = 92.0227
    y_zero = 943.0
    px_per_100kw = 138.5

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
    
    # 缩放发电量以匹配目标值
    if target_generation_kwh is not None:
        current_generation = np.sum(p_target) * (5 / 60)
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
    import sys
    target_kwh = None
    if len(sys.argv) >= 3:
        IMAGE_PATH = sys.argv[1]
        CSV_PATH = sys.argv[2]
        if len(sys.argv) >= 4:
            target_kwh = float(sys.argv[3])
    else:
        raise SystemExit("用法: python3 extract_and_merge_pv.py <图片路径> <CSV路径> [目标发电量kWh]")
    
    extract_and_merge(IMAGE_PATH, CSV_PATH, target_generation_kwh=target_kwh)
