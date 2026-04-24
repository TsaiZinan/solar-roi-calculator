import pandas as pd
from config import EV_PRICING_PATH, GRID_PRICING_PATH

_pricing_df = None
_grid_pricing_df = None

def _load_grid_pricing_df():
    global _grid_pricing_df

    if _grid_pricing_df is None:
        if not GRID_PRICING_PATH or not pd.io.common.file_exists(GRID_PRICING_PATH):
            return None

        _grid_pricing_df = pd.read_csv(GRID_PRICING_PATH)
        _grid_pricing_df['记录日期'] = pd.to_datetime(_grid_pricing_df['记录日期'])
        _grid_pricing_df = _grid_pricing_df.sort_values('记录日期').reset_index(drop=True)

    return _grid_pricing_df


def _load_ev_pricing_df():
    global _pricing_df

    if _pricing_df is None:
        if not EV_PRICING_PATH or not pd.io.common.file_exists(EV_PRICING_PATH):
            return None

        _pricing_df = pd.read_csv(EV_PRICING_PATH)
        _pricing_df['记录日期'] = pd.to_datetime(_pricing_df['记录日期'])
        _pricing_df = _pricing_df.sort_values('记录日期').reset_index(drop=True)

    return _pricing_df


def _normalize_target_date(target_date):
    if isinstance(target_date, str):
        return pd.to_datetime(target_date)
    return target_date


def _get_latest_record(df, target_date):
    target_date = _normalize_target_date(target_date)
    valid_records = df[df['记录日期'] <= target_date]
    if valid_records.empty:
        return df.iloc[0]
    return valid_records.iloc[-1]


def _get_default_grid_buy_price(hour):
    if 0 <= hour < 8:
        return 0.25
    if 10 <= hour < 12 or 14 <= hour < 19:
        return 0.95
    return 0.61


def _get_default_ev_sell_price(hour):
    if 0 <= hour < 8:
        return 0.45
    if 10 <= hour < 12:
        return 0.91
    if 14 <= hour < 19:
        return 0.92
    if 8 <= hour < 10 or 12 <= hour < 14:
        return 0.62
    return 0.82


def get_grid_price_schedule(target_date):
    """
    返回目标日期对应的 24 小时电网购电价格。
    """
    df = _load_grid_pricing_df()
    if df is None:
        return {hour: _get_default_grid_buy_price(hour) for hour in range(24)}

    record = _get_latest_record(df, target_date)
    return {
        hour: float(record.get(f"{hour:02d}:00", _get_default_grid_buy_price(hour)))
        for hour in range(24)
    }


def get_grid_period_map(target_date):
    """
    基于目标日期的电网购电价格档位，自动映射出谷/平/峰/尖标签。
    """
    schedule = get_grid_price_schedule(target_date)
    unique_prices = sorted(set(schedule.values()))

    if len(unique_prices) <= 1:
        price_to_period = {unique_prices[0]: '平'} if unique_prices else {}
    elif len(unique_prices) == 2:
        price_to_period = {
            unique_prices[0]: '谷',
            unique_prices[1]: '峰',
        }
    elif len(unique_prices) == 3:
        price_to_period = {
            unique_prices[0]: '谷',
            unique_prices[1]: '平',
            unique_prices[2]: '峰',
        }
    elif len(unique_prices) == 4:
        price_to_period = {
            unique_prices[0]: '谷',
            unique_prices[1]: '平',
            unique_prices[2]: '峰',
            unique_prices[3]: '尖',
        }
    else:
        price_to_period = {
            unique_prices[0]: '谷',
            unique_prices[1]: '平',
            unique_prices[-1]: '尖',
        }
        for price in unique_prices[2:-1]:
            price_to_period[price] = '峰'

    return {hour: price_to_period[price] for hour, price in schedule.items()}


def get_grid_period_type(target_date, hour):
    return get_grid_period_map(target_date).get(hour, '平')


def get_period_display_order(target_date):
    labels = set(get_grid_period_map(target_date).values())
    return [label for label in ['尖', '峰', '平', '谷'] if label in labels]

def get_grid_buy_price(target_date, hour):
    """
    根据给定的日期和小时，从 电网电价.csv 获取电网购电定价。
    如果日期在所有记录之前，取最早的一条。
    如果日期在两条记录之间，取最近且在给定日期之前的那条。
    """
    return get_grid_price_schedule(target_date).get(hour, _get_default_grid_buy_price(hour))

def get_ev_sell_price(target_date, hour):
    """
    根据给定的日期和小时，从 充电桩定价.csv 获取定价。
    如果日期在所有记录之前，取最早的一条。
    如果日期在两条记录之间，取最近且在给定日期之前的那条。
    """
    df = _load_ev_pricing_df()
    if df is None:
        return _get_default_ev_sell_price(hour)

    record = _get_latest_record(df, target_date)
    hour_str = f"{hour:02d}:00"
    if hour_str in record:
        return float(record[hour_str])

    return _get_default_ev_sell_price(hour)
