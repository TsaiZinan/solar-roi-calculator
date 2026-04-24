import glob
import os


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "数据")
REPORT_DIR = os.path.join(BASE_DIR, "报告")

GRID_PRICING_PATH = os.path.join(DATA_DIR, "电网电价.csv")
EV_PRICING_PATH = os.path.join(DATA_DIR, "充电桩定价.csv")
SUMMARY_REPORT_PATH = os.path.join(REPORT_DIR, "总收益分析报表.md")

DAILY_REPORT_PREFIX = "每日收益分析报告_"
DAILY_REPORT_PATTERN = os.path.join(REPORT_DIR, f"{DAILY_REPORT_PREFIX}*.md")

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
    (7, 12, 50.0),
    (13, 18, 50.0),
]

PRIMARY_ESS = {
    "capacity_kwh": 257.0,
    "max_power_kw": 120.0,
    "efficiency": 0.95,
    "label": "当前储能系统(250度)",
}

ANNUAL_PREDICTION_ESS_SETUPS = [
    ("base", 0.0, 0.0),
    ("ess_1", 257.0, 120.0),
    ("ess_2", 507.0, 240.0),
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


def get_factory_load(hour):
    for start_hour, end_hour, load_kw in FACTORY_LOAD_WINDOWS:
        if start_hour <= hour < end_hour:
            return load_kw
    return 0.0


def get_daily_report_path(date_str):
    return os.path.join(REPORT_DIR, f"{DAILY_REPORT_PREFIX}{date_str}.md")


def get_daily_report_paths():
    report_paths = glob.glob(DAILY_REPORT_PATTERN)
    report_paths.sort()
    return report_paths


def get_daily_csv_paths():
    csv_paths = glob.glob(os.path.join(DATA_DIR, "20*/*.csv"))
    csv_paths.sort()
    return csv_paths


def ensure_report_dir():
    os.makedirs(REPORT_DIR, exist_ok=True)
