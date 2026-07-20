import glob
import os
import csv
from functools import lru_cache


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "数据")
REPORT_DIR = os.path.join(BASE_DIR, "报告")
JSON_DIR = os.path.join(REPORT_DIR, "json")
FACTORY_FIT_HOURLY_PATH = os.path.join(JSON_DIR, "工厂用电拟合_202606_逐日逐小时_修正后.csv")

GRID_PRICING_PATH = os.path.join(DATA_DIR, "电网电价.csv")
EV_PRICING_PATH = os.path.join(DATA_DIR, "充电桩定价.csv")
SPOT_REALTIME_PRICING_PATH = os.path.join(DATA_DIR, "spot_realtime_prices.csv")
SUMMARY_REPORT_PATH = os.path.join(REPORT_DIR, "总收益分析报表.md")
SUMMARY_JSON_PATH = os.path.join(JSON_DIR, "总收益分析报表.json")
PV_EXCEL_PREFIX = "电站能量趋势数据_"

DAILY_REPORT_PREFIX = "每日收益分析报告_"
DAILY_REPORT_PATTERN = os.path.join(REPORT_DIR, f"{DAILY_REPORT_PREFIX}*.md")
DAILY_JSON_PREFIX = "每日收益分析_"
DAILY_JSON_PATTERN = os.path.join(JSON_DIR, f"{DAILY_JSON_PREFIX}*.json")

PV_PRICE_SCENARIOS = [
    ("A", 0.1),
    ("B", 0.2),
    ("C", 0.35),
]

SUMMARY_PRICE_KEYS = [
    ("01", "0.1"),
    ("02", "0.2"),
    ("035", "0.35"),
]

FACTORY_LOAD_WINDOWS = [
    (7, 13, 50.0),
    (13, 18, 50.0),
]
NIGHT_BASELOAD_HOURS = tuple(range(0, 6)) + tuple(range(18, 24))
NIGHT_BASELOAD_KW = 8.1375
LOSS_STATIC_KW = 9.6798
LOSS_DYNAMIC_RATIO = 0.1365
LOAD_SPLIT_RULE_VERSION = "factory-fit-june-loss-v3"

ESS_EFFICIENCY = 0.95
SECOND_ESS_START_DATE = "20260519"

FIRST_ESS = {
    "capacity_kwh": 257.0,
    "max_power_kw": 125.0,
    "efficiency": ESS_EFFICIENCY,
    "label": "当前储能系统(257度)",
}

SECOND_ESS = {
    "capacity_kwh": 257.0,
    "max_power_kw": 125.0,
    "efficiency": ESS_EFFICIENCY,
    "label": "新增第2台储能(257度)",
}

TOTAL_ESS = {
    "capacity_kwh": FIRST_ESS["capacity_kwh"] + SECOND_ESS["capacity_kwh"],
    "max_power_kw": FIRST_ESS["max_power_kw"] + SECOND_ESS["max_power_kw"],
    "efficiency": ESS_EFFICIENCY,
    "label": "当前储能系统(514度)",
}

# Backward-compatible alias used when CSV file names do not expose storage specs.
PRIMARY_ESS = dict(FIRST_ESS)

ANNUAL_PREDICTION_ESS_SETUPS = [
    ("base", 0.0, 0.0),
    ("ess_1", FIRST_ESS["capacity_kwh"], FIRST_ESS["max_power_kw"]),
    ("ess_2", TOTAL_ESS["capacity_kwh"], TOTAL_ESS["max_power_kw"]),
]

ANNUAL_WEATHER_DAY_COUNTS = {
    "sunny": 130,
    "cloudy": 97,
    "rainy": 138,
}

ANNUAL_SAMPLE_DATE_KEYWORDS = {
    "sunny": ["0415", "0416", "0420", "0422"],
    "cloudy": ["0417", "0418"],
    "rainy": ["0419", "0421"],
}

ROI_REPORT_NAME = "项目投资回报率(ROI)分析报告.md"
ROI_INVESTMENT_BASE_WAN = 175.0
ROI_INVESTMENT_ESS_WAN = 22.0


def is_night_baseload_hour(hour):
    return int(hour) in NIGHT_BASELOAD_HOURS


def _normalize_hour_text(hour):
    if isinstance(hour, str):
        return hour if ":" in hour else f"{int(hour):02d}:00"
    return f"{int(hour):02d}:00"


@lru_cache(maxsize=1)
def _load_factory_fit_hourly_map():
    mapping = {}
    if not os.path.exists(FACTORY_FIT_HOURLY_PATH):
        return mapping
    with open(FACTORY_FIT_HOURLY_PATH, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row.get("日期", "")
            hour_text = row.get("小时", "")
            try:
                corrected_kwh = float(row.get("新版修正后厂区用电(度)", 0) or 0)
            except Exception:
                corrected_kwh = 0.0
            mapping[(date_str, hour_text)] = corrected_kwh
    return mapping


def get_factory_fit_load_for_june(date_str, hour):
    hour_text = _normalize_hour_text(hour)
    return _load_factory_fit_hourly_map().get((str(date_str), hour_text))


def get_factory_load(date_or_hour, hour=None, total_load_kw=None):
    if hour is None:
        date_str = None
        hour = int(date_or_hour)
    else:
        date_str = str(date_or_hour) if date_or_hour is not None else None
        hour = int(hour)

    load_kw = 0.0
    fitted_kw = None
    if date_str and date_str.startswith("202606"):
        fitted_kw = get_factory_fit_load_for_june(date_str, hour)
    if fitted_kw is not None and fitted_kw > 0:
        load_kw = fitted_kw
    else:
        for start_hour, end_hour, window_load_kw in FACTORY_LOAD_WINDOWS:
            if start_hour <= hour < end_hour:
                load_kw = window_load_kw
                break
        else:
            if is_night_baseload_hour(hour):
                load_kw = NIGHT_BASELOAD_KW

    if total_load_kw is None:
        return load_kw
    return min(max(float(total_load_kw), 0.0), load_kw)


def split_ev_and_loss_load(total_load_kw, factory_load_kw):
    remaining_kw = max(0.0, float(total_load_kw) - float(factory_load_kw))
    if remaining_kw <= 0:
        return 0.0, 0.0
    if remaining_kw <= LOSS_STATIC_KW:
        return 0.0, remaining_kw
    ev_kw = max(0.0, (remaining_kw - LOSS_STATIC_KW) / (1.0 + LOSS_DYNAMIC_RATIO))
    loss_kw = max(0.0, remaining_kw - ev_kw)
    return ev_kw, loss_kw


def get_load_split_rule_payload():
    return {
        "version": LOAD_SPLIT_RULE_VERSION,
        "day_factory_windows": [
            {
                "start_hour": start_hour,
                "end_hour": end_hour,
                "factory_load_kw": load_kw,
            }
            for start_hour, end_hour, load_kw in FACTORY_LOAD_WINDOWS
        ],
        "night_baseload_hours": [f"{hour:02d}:00" for hour in NIGHT_BASELOAD_HOURS],
        "night_baseload_kw": NIGHT_BASELOAD_KW,
        "june_daytime_factory_fit_source": os.path.basename(FACTORY_FIT_HOURLY_PATH),
        "summary": (
            "2026年6月白天 07:00-12:00、13:00-18:00 工厂负荷按 6 月拟合逐日逐小时数据估算；"
            "其他日期白天仍按 50kW 估算；"
            "夜间 18:00-05:59 工厂基础负荷按 8.1375kW 估算；"
            "各时段工厂负荷均不超过该时段真实总负载。"
        ),
    }


def get_loss_model_payload():
    return {
        "static_loss_kw": LOSS_STATIC_KW,
        "dynamic_loss_ratio": LOSS_DYNAMIC_RATIO,
        "formula": "站内损耗 = 静态损耗 + 动态损耗；动态损耗 = 可计费充电负荷 * 0.1365",
        "summary": (
            "充电、变压和储能损耗按静态损耗 9.6798kW 与动态损耗 "
            "0.1365 * 可计费充电负荷 计算。"
        ),
    }


def get_storage_system_for_date(date_str):
    if date_str and date_str >= SECOND_ESS_START_DATE:
        return dict(TOTAL_ESS)
    return dict(FIRST_ESS)


def get_daily_report_path(date_str):
    return os.path.join(REPORT_DIR, f"{DAILY_REPORT_PREFIX}{date_str}.md")


def get_daily_json_path(date_str):
    return os.path.join(JSON_DIR, f"{DAILY_JSON_PREFIX}{date_str}.json")


def get_daily_report_paths():
    report_paths = glob.glob(DAILY_REPORT_PATTERN)
    report_paths.sort()
    return report_paths


def get_daily_json_paths():
    json_paths = glob.glob(DAILY_JSON_PATTERN)
    json_paths.sort()
    return json_paths


def get_daily_csv_paths():
    csv_paths = glob.glob(os.path.join(DATA_DIR, "日报表_*.csv"))
    csv_paths.extend(glob.glob(os.path.join(DATA_DIR, "20*", "日报表_*.csv")))
    csv_paths = sorted(set(csv_paths))
    return csv_paths


def get_daily_excel_paths(include_archived=False):
    excel_paths = glob.glob(os.path.join(DATA_DIR, f"{PV_EXCEL_PREFIX}*.xlsx"))
    if include_archived:
        excel_paths.extend(glob.glob(os.path.join(DATA_DIR, "20*", f"{PV_EXCEL_PREFIX}*.xlsx")))
    excel_paths = sorted(set(excel_paths))
    return excel_paths


def ensure_report_dir():
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(JSON_DIR, exist_ok=True)
