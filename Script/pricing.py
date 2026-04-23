import pandas as pd
import os

_pricing_df = None
_grid_pricing_df = None

def get_grid_buy_price(target_date, hour):
    """
    根据给定的日期和小时，从 电网电价.csv 获取电网购电定价。
    如果日期在所有记录之前，取最早的一条。
    如果日期在两条记录之间，取最近且在给定日期之前的那条。
    """
    global _grid_pricing_df
    
    # 查找csv文件
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, '数据', '电网电价.csv')
    
    if not os.path.exists(csv_path):
        # 默认回退价格
        if 0 <= hour < 8: return 0.25
        if 10 <= hour < 12 or 14 <= hour < 19: return 0.95
        return 0.61

    if _grid_pricing_df is None:
        _grid_pricing_df = pd.read_csv(csv_path)
        _grid_pricing_df['记录日期'] = pd.to_datetime(_grid_pricing_df['记录日期'])
        _grid_pricing_df = _grid_pricing_df.sort_values('记录日期').reset_index(drop=True)

    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date)
    
    # 找到所有 <= target_date 的记录
    valid_records = _grid_pricing_df[_grid_pricing_df['记录日期'] <= target_date]
    if valid_records.empty:
        record = _grid_pricing_df.iloc[0]
    else:
        record = valid_records.iloc[-1]
        
    hour_str = f"{hour:02d}:00"
    if hour_str in record:
        return float(record[hour_str])
    
    return 0.61 # fallback

def get_ev_sell_price(target_date, hour):
    """
    根据给定的日期和小时，从 充电桩定价.csv 获取定价。
    如果日期在所有记录之前，取最早的一条。
    如果日期在两条记录之间，取最近且在给定日期之前的那条。
    """
    global _pricing_df
    
    # 查找csv文件
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, '数据', '充电桩定价.csv')
    
    if not os.path.exists(csv_path):
        # 默认回退价格
        if 0 <= hour < 8: return 0.45
        if 10 <= hour < 12 or 14 <= hour < 19: return 0.91
        if 8 <= hour < 10 or 12 <= hour < 14: return 0.62
        return 0.82

    if _pricing_df is None:
        _pricing_df = pd.read_csv(csv_path)
        _pricing_df['记录日期'] = pd.to_datetime(_pricing_df['记录日期'])
        _pricing_df = _pricing_df.sort_values('记录日期').reset_index(drop=True)

    if isinstance(target_date, str):
        target_date = pd.to_datetime(target_date)
    
    # 找到所有 <= target_date 的记录
    valid_records = _pricing_df[_pricing_df['记录日期'] <= target_date]
    if valid_records.empty:
        # 如果给定日期比所有记录都早，就用最早的记录
        record = _pricing_df.iloc[0]
    else:
        # 用最近的记录
        record = valid_records.iloc[-1]
        
    hour_str = f"{hour:02d}:00"
    if hour_str in record:
        return float(record[hour_str])
    
    return 0.82 # fallback
