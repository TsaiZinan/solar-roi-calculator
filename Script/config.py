import glob
import os


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "数据")
REPORT_DIR = os.path.join(BASE_DIR, "报告")
JSON_DIR = os.path.join(REPORT_DIR, "json")

GRID_PRICING_PATH = os.path.join(DATA_DIR, "电网电价.csv")
EV_PRICING_PATH = os.path.join(DATA_DIR, "充电桩定价.csv")
PV_CALIBRATION_PATH = os.path.join(DATA_DIR, "数据校准.csv")
SUMMARY_REPORT_PATH = os.path.join(REPORT_DIR, "总收益分析报表.md")
SUMMARY_JSON_PATH = os.path.join(JSON_DIR, "总收益分析报表.json")

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
    (7, 12, 50.0),
    (13, 18, 50.0),
]

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


def get_factory_load(hour):
    for start_hour, end_hour, load_kw in FACTORY_LOAD_WINDOWS:
        if start_hour <= hour < end_hour:
            return load_kw
    return 0.0


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
    csv_paths = glob.glob(os.path.join(DATA_DIR, "20*/*.csv"))
    csv_paths.sort()
    return csv_paths


def ensure_report_dir():
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs(JSON_DIR, exist_ok=True)
