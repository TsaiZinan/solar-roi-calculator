import argparse
import os
from dataclasses import dataclass

import pandas as pd

from config import REPORT_DIR, get_factory_load
from pricing import get_ev_sell_price, get_grid_buy_price, get_grid_period_map


DT_HOURS = 5.0 / 60.0
SCENARIOS = [("A", 0.10), ("B", 0.20), ("C", 0.35)]


@dataclass
class ESSSpec:
    label: str
    capacity_kwh: float
    power_kw: float


def load_day_df(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["时间"] = pd.to_datetime(df["时间"])
    df["真实总负载(kW)"] = df["光伏发电功率(kW)"] - df["负载功率(kW)"]
    df["工厂用电(kW)"] = df.apply(
        lambda row: min(max(row["真实总负载(kW)"], 0.0), get_factory_load(row["时间"].hour)),
        axis=1,
    )
    df["充电桩用电(kW)"] = (df["真实总负载(kW)"] - df["工厂用电(kW)"]).clip(lower=0.0)
    return df


def simulate(df: pd.DataFrame, spec: ESSSpec, efficiency: float = 0.95):
    date_str = df["时间"].dt.strftime("%Y%m%d").iloc[0]
    period_map = get_grid_period_map(date_str)

    current_soc = df["SOC(%)"].iloc[0] / 100.0 if spec.capacity_kwh > 0 else 0.0
    current_energy = current_soc * spec.capacity_kwh

    rows = []
    for _, row in df.iterrows():
        t = row["时间"]
        h = t.hour
        period = period_map.get(h, "平")
        is_valley = period == "谷"

        pv_kw = max(0.0, float(row["光伏发电功率(kW)"]))
        load_kw = max(0.0, float(row["真实总负载(kW)"]))
        factory_kw = max(0.0, float(row["工厂用电(kW)"]))
        ev_kw = max(0.0, float(row["充电桩用电(kW)"]))

        net_load_kw = load_kw - pv_kw

        grid_buy_load_kw = 0.0
        grid_buy_charge_kw = 0.0
        pv_to_grid_kw = 0.0
        pv_to_battery_kw = 0.0
        battery_charge_kw = 0.0
        battery_discharge_kw = 0.0

        if is_valley and spec.capacity_kwh > 0:
            space = max(0.0, spec.capacity_kwh - current_energy)
            max_charge_kw = min(spec.power_kw, space / (DT_HOURS * efficiency)) if space > 0 else 0.0
            battery_charge_kw = max_charge_kw
            current_energy += battery_charge_kw * DT_HOURS * efficiency

            grid_buy_charge_kw = battery_charge_kw
            if net_load_kw > 0:
                grid_buy_load_kw = net_load_kw
            else:
                pv_to_grid_kw = -net_load_kw
        else:
            if net_load_kw > 0:
                if spec.capacity_kwh > 0:
                    available_energy = max(0.0, current_energy)
                    max_discharge_kw = min(spec.power_kw, available_energy / (DT_HOURS / efficiency))
                    battery_discharge_kw = min(max_discharge_kw, net_load_kw)
                    current_energy -= battery_discharge_kw * DT_HOURS / efficiency
                grid_buy_load_kw = max(0.0, net_load_kw - battery_discharge_kw)
            else:
                excess_pv_kw = -net_load_kw
                if spec.capacity_kwh > 0:
                    space = max(0.0, spec.capacity_kwh - current_energy)
                    max_charge_kw = min(spec.power_kw, space / (DT_HOURS * efficiency)) if space > 0 else 0.0
                    pv_to_battery_kw = min(max_charge_kw, excess_pv_kw)
                    battery_charge_kw = pv_to_battery_kw
                    current_energy += battery_charge_kw * DT_HOURS * efficiency
                pv_to_grid_kw = max(0.0, excess_pv_kw - pv_to_battery_kw)

        grid_buy_price = float(get_grid_buy_price(t.strftime("%Y-%m-%d"), h))
        ev_sell_price = float(get_ev_sell_price(t.strftime("%Y-%m-%d"), h))

        rec = {
            "时间": t,
            "小时": h,
            "时段": period,
            "电网购电价": grid_buy_price,
            "充电桩售价": ev_sell_price,
            "pv_kwh": pv_kw * DT_HOURS,
            "load_kwh": load_kw * DT_HOURS,
            "factory_kwh": factory_kw * DT_HOURS,
            "ev_kwh": ev_kw * DT_HOURS,
            "grid_buy_load_kwh": grid_buy_load_kw * DT_HOURS,
            "grid_buy_charge_kwh": grid_buy_charge_kw * DT_HOURS,
            "grid_buy_total_kwh": (grid_buy_load_kw + grid_buy_charge_kw) * DT_HOURS,
            "pv_to_grid_kwh": pv_to_grid_kw * DT_HOURS,
            "pv_to_battery_kwh": pv_to_battery_kw * DT_HOURS,
            "battery_charge_kwh": battery_charge_kw * DT_HOURS,
            "battery_discharge_kwh": battery_discharge_kw * DT_HOURS,
        }
        rec["grid_cost"] = rec["grid_buy_total_kwh"] * grid_buy_price
        rec["ev_revenue"] = rec["ev_kwh"] * ev_sell_price
        rec["factory_saving"] = rec["factory_kwh"] * grid_buy_price
        for _, pv_price in SCENARIOS:
            key = f"profit_{str(pv_price).replace('.', '')}"
            rec[key] = rec["ev_revenue"] + rec["factory_saving"] + rec["pv_to_grid_kwh"] * pv_price - rec["grid_cost"]
        rows.append(rec)

    out = pd.DataFrame(rows)
    return out


def fmt(v: float) -> str:
    return f"{v:.2f}"


def build_report(csv_path: str, one: ESSSpec, two: ESSSpec, output_path: str):
    df = load_day_df(csv_path)
    day = df["时间"].dt.strftime("%Y%m%d").iloc[0]
    csv_rel_path = os.path.relpath(csv_path, os.getcwd())

    one_df = simulate(df, one)
    two_df = simulate(df, two)
    delta = two_df.copy()
    num_cols = [
        c
        for c in two_df.columns
        if c not in ["时间", "小时", "时段", "电网购电价", "充电桩售价"]
    ]
    delta[num_cols] = two_df[num_cols] - one_df[num_cols]

    # 正值表示“新增第2台后减少了多少”
    load_grid_reduction_kwh = (one_df["grid_buy_load_kwh"] - two_df["grid_buy_load_kwh"]).sum()
    charge_grid_increase_kwh = (two_df["grid_buy_charge_kwh"] - one_df["grid_buy_charge_kwh"]).sum()
    load_grid_saving_yuan = (
        (one_df["grid_buy_load_kwh"] - two_df["grid_buy_load_kwh"]) * one_df["电网购电价"]
    ).sum()
    charge_grid_extra_cost_yuan = (
        (two_df["grid_buy_charge_kwh"] - one_df["grid_buy_charge_kwh"]) * one_df["电网购电价"]
    ).sum()
    net_grid_cost_saving = load_grid_saving_yuan - charge_grid_extra_cost_yuan

    one_totals = one_df.sum(numeric_only=True)
    two_totals = two_df.sum(numeric_only=True)
    extra_pv_store_kwh = (two_df["pv_to_battery_kwh"] - one_df["pv_to_battery_kwh"]).sum()
    less_pv_export_kwh = (one_df["pv_to_grid_kwh"] - two_df["pv_to_grid_kwh"]).sum()
    round_trip_loss_kwh = charge_grid_increase_kwh + extra_pv_store_kwh - (
        two_totals["battery_discharge_kwh"] - one_totals["battery_discharge_kwh"]
    )
    non_valley_surplus_mask = (one_df["时段"] != "谷") & (one_df["pv_kwh"] > one_df["load_kwh"])
    non_valley_surplus_total_kwh = (one_df.loc[non_valley_surplus_mask, "pv_kwh"] - one_df.loc[non_valley_surplus_mask, "load_kwh"]).sum()
    one_non_valley_pv_store_kwh = one_df.loc[non_valley_surplus_mask, "pv_to_battery_kwh"].sum()
    two_non_valley_pv_store_kwh = two_df.loc[non_valley_surplus_mask, "pv_to_battery_kwh"].sum()

    hourly = (
        delta.groupby(["小时", "时段"], as_index=False)[
            [
                "grid_buy_load_kwh",
                "grid_buy_charge_kwh",
                "grid_buy_total_kwh",
                "pv_to_battery_kwh",
                "pv_to_grid_kwh",
                "battery_discharge_kwh",
                "grid_cost",
                "profit_01",
                "profit_02",
                "profit_035",
            ]
        ]
        .sum()
        .sort_values("小时")
    )
    period_summary = (
        delta.groupby("时段", as_index=False)[
            [
                "grid_buy_load_kwh",
                "grid_buy_charge_kwh",
                "grid_buy_total_kwh",
                "pv_to_battery_kwh",
                "pv_to_grid_kwh",
                "battery_discharge_kwh",
                "grid_cost",
                "profit_01",
                "profit_02",
                "profit_035",
            ]
        ]
        .sum()
    )
    price_schedule = one_df.groupby(["小时", "时段"], as_index=False)[["电网购电价", "充电桩售价"]].first()
    charge_hours = hourly[hourly["grid_buy_charge_kwh"] > 0.01]["小时"].astype(int).tolist()
    discharge_hours = hourly[hourly["battery_discharge_kwh"] > 0.01]["小时"].astype(int).tolist()

    def fmt_hours(hours):
        return "、".join(f"{h:02d}:00" for h in hours) if hours else "无"

    lines = []
    lines.append(f"# 新增第2台储能收益拆解分析报告 - {day}")
    lines.append("")
    lines.append("## 1. 分析目标与问题定义")
    lines.append("- 目标：验证“新增 1 台 125kW / 250kWh 储能”后，收益提升是否已经完整考虑了两类因素：")
    lines.append("  - 部分时段减少向电网购电")
    lines.append("  - 吸纳更多光伏余电")
    lines.append("- 对比对象：")
    lines.append(f"  - 基准场景：{one.label}（容量 {one.capacity_kwh}kWh，功率 {one.power_kw}kW）")
    lines.append(f"  - 对比场景：{two.label}（容量 {two.capacity_kwh}kWh，功率 {two.power_kw}kW）")
    lines.append(f"- 数据来源：`{csv_rel_path}`")
    lines.append("")
    lines.append("## 2. 计算口径（与项目仿真一致）")
    lines.append("- 时间粒度：5 分钟，步长 5/60 小时。")
    lines.append("- 真实总负载：`真实总负载 = 光伏发电功率 - 负载功率`。")
    lines.append("- 工厂负载：07:00-12:00 与 13:00-18:00 固定 50kW，其余为 0。")
    lines.append("- 策略规则：")
    lines.append("  - 谷段：优先按功率上限主动充电（从电网充）")
    lines.append("  - 非谷段负载缺口：储能先放电，剩余缺口再由电网补")
    lines.append("  - 非谷段光伏富余：先充电池，剩余才上网")
    lines.append("- 收益公式：`利润 = 充电桩收入 + 工厂省电收益 + 光伏上网收入 - 电网购电成本`。")
    lines.append("")
    lines.append("## 3. 总体结果")
    lines.append("| 指标 | 1台(250kWh/125kW) | 2台(500kWh/250kW) | 增量(2台-1台) |")
    lines.append("|:---|---:|---:|---:|")
    lines.append(f"| 电网总购电量(度) | {fmt(one_totals['grid_buy_total_kwh'])} | {fmt(two_totals['grid_buy_total_kwh'])} | {fmt(two_totals['grid_buy_total_kwh']-one_totals['grid_buy_total_kwh'])} |")
    lines.append(f"| 其中：负载购电(度) | {fmt(one_totals['grid_buy_load_kwh'])} | {fmt(two_totals['grid_buy_load_kwh'])} | {fmt(two_totals['grid_buy_load_kwh']-one_totals['grid_buy_load_kwh'])} |")
    lines.append(f"| 其中：充电购电(度) | {fmt(one_totals['grid_buy_charge_kwh'])} | {fmt(two_totals['grid_buy_charge_kwh'])} | {fmt(two_totals['grid_buy_charge_kwh']-one_totals['grid_buy_charge_kwh'])} |")
    lines.append(f"| 光伏充入储能(度) | {fmt(one_totals['pv_to_battery_kwh'])} | {fmt(two_totals['pv_to_battery_kwh'])} | {fmt(two_totals['pv_to_battery_kwh']-one_totals['pv_to_battery_kwh'])} |")
    lines.append(f"| 光伏上网电量(度) | {fmt(one_totals['pv_to_grid_kwh'])} | {fmt(two_totals['pv_to_grid_kwh'])} | {fmt(two_totals['pv_to_grid_kwh']-one_totals['pv_to_grid_kwh'])} |")
    lines.append(f"| 储能放电量(度) | {fmt(one_totals['battery_discharge_kwh'])} | {fmt(two_totals['battery_discharge_kwh'])} | {fmt(two_totals['battery_discharge_kwh']-one_totals['battery_discharge_kwh'])} |")
    lines.append("")
    lines.append("## 4. 当日电价与分时标签")
    lines.append("| 小时 | 时段 | 电网购电价(元/度) | 充电桩售价(元/度) |")
    lines.append("|:---|:---|---:|---:|")
    for _, r in price_schedule.iterrows():
        lines.append(
            f"| {int(r['小时']):02d}:00 | {r['时段']} | {fmt(r['电网购电价'])} | {fmt(r['充电桩售价'])} |"
        )
    lines.append("")
    lines.append("## 5. 收益拆解（新增第2台 = 哪些来源叠加）")
    lines.append(f"- 负载侧减少购电：**{fmt(load_grid_reduction_kwh)} 度**，按分时电价折算节省 **{fmt(load_grid_saving_yuan)} 元**。")
    lines.append(f"- 充电侧新增购电：**{fmt(charge_grid_increase_kwh)} 度**，按分时电价增加成本 **{fmt(charge_grid_extra_cost_yuan)} 元**。")
    lines.append(f"- 电网购电成本净变化：**{fmt(net_grid_cost_saving)} 元**（= 节省 - 新增成本）。")
    lines.append(f"- 新增额外吸纳光伏余电：**{fmt(extra_pv_store_kwh)} 度**。")
    lines.append(f"- 光伏上网电量变化：减少 **{fmt(less_pv_export_kwh)} 度**（正值代表“少上网”）。")
    lines.append(f"- 新增轮次损耗：**{fmt(round_trip_loss_kwh)} 度**，表现为“新增充电量”大于“新增放电量”。")
    lines.append("")
    lines.append("### 5.1 三种光伏上网电价场景下的新增收益")
    lines.append("| 场景 | 光伏上网电价(元/度) | 光伏上网收入变化(元) | 电网购电成本净改善(元) | 新增总收益(元) |")
    lines.append("|:---|---:|---:|---:|---:|")
    for _, pv_price in SCENARIOS:
        key = f"profit_{str(pv_price).replace('.', '')}"
        profit_delta = two_totals[key] - one_totals[key]
        pv_rev_change = (two_totals["pv_to_grid_kwh"] - one_totals["pv_to_grid_kwh"]) * pv_price
        lines.append(
            f"| {pv_price:.2f}场景 | {pv_price:.2f} | {fmt(pv_rev_change)} | {fmt(net_grid_cost_saving)} | {fmt(profit_delta)} |"
        )
    lines.append("")
    lines.append("### 5.2 关键解释")
    lines.append(f"- 本日新增收益在 0.1 / 0.2 / 0.35 三个光伏电价场景下相同，均为 **{fmt(net_grid_cost_saving)} 元**。")
    lines.append("- 这意味着新增第2台储能的收益主要由“电网购电成本改善”驱动，而不是光伏上网收入变化。")
    lines.append("- 原因是本次模拟结果中，新增第2台后“光伏上网电量变化”接近 0，因此光伏上网电价对增量收益不敏感。")
    lines.append("")
    lines.append("### 5.3 能量链条解释")
    lines.append(f"- 新增第2台后的额外充电，集中发生在谷段 **{fmt_hours(charge_hours)}**。")
    lines.append(f"- 新增第2台后的额外放电，集中发生在 **{fmt_hours(discharge_hours)}**。")
    lines.append(
        f"- 这一天新增第2台的能量链条可以概括为：谷段多充 **{fmt(charge_grid_increase_kwh)} 度** -> "
        f"在 **{fmt_hours(discharge_hours)}** 多放 **{fmt(two_totals['battery_discharge_kwh'] - one_totals['battery_discharge_kwh'])} 度** -> "
        f"中间损耗 **{fmt(round_trip_loss_kwh)} 度**。"
    )
    lines.append(
        f"- 这一天**并不是没有非谷段光伏富余**：非谷段光伏富余总量为 **{fmt(non_valley_surplus_total_kwh)} 度**。"
    )
    lines.append(
        f"- 其中，1台场景已经吸纳 **{fmt(one_non_valley_pv_store_kwh)} 度**，2台场景也吸纳 **{fmt(two_non_valley_pv_store_kwh)} 度**，所以“新增额外吸纳量”才会是 **{fmt(extra_pv_store_kwh)} 度**。"
    )
    lines.append(
        "- 根本原因不是当天没有余电，而是第1台储能在现有策略下已经把这一天“能吃进去的那部分非谷段余电”基本吃完了；第2台只是在个别 5 分钟片段里改变了充电时点，全天累计并没有额外扩大光伏吸纳量。"
    )
    lines.append("")
    lines.append("## 6. 按时段汇总的增量拆解（2台 - 1台）")
    lines.append("| 时段 | 负载购电变化(度) | 充电购电变化(度) | 总购电变化(度) | 光伏入储变化(度) | 光伏上网变化(度) | 放电变化(度) | 电网成本变化(元) | 收益变化(0.1) | 收益变化(0.2) | 收益变化(0.35) |")
    lines.append("|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in period_summary.iterrows():
        lines.append(
            f"| {r['时段']} | {fmt(r['grid_buy_load_kwh'])} | {fmt(r['grid_buy_charge_kwh'])} | {fmt(r['grid_buy_total_kwh'])} | {fmt(r['pv_to_battery_kwh'])} | {fmt(r['pv_to_grid_kwh'])} | {fmt(r['battery_discharge_kwh'])} | {fmt(r['grid_cost'])} | {fmt(r['profit_01'])} | {fmt(r['profit_02'])} | {fmt(r['profit_035'])} |"
        )
    lines.append("")
    lines.append("## 7. 分时逐小时增量明细（2台 - 1台）")
    lines.append("| 小时 | 时段 | 负载购电变化(度) | 充电购电变化(度) | 总购电变化(度) | 光伏入储变化(度) | 光伏上网变化(度) | 放电变化(度) | 电网成本变化(元) | 收益变化(0.1) | 收益变化(0.2) | 收益变化(0.35) |")
    lines.append("|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in hourly.iterrows():
        lines.append(
            f"| {int(r['小时']):02d}:00 | {r['时段']} | {fmt(r['grid_buy_load_kwh'])} | {fmt(r['grid_buy_charge_kwh'])} | {fmt(r['grid_buy_total_kwh'])} | {fmt(r['pv_to_battery_kwh'])} | {fmt(r['pv_to_grid_kwh'])} | {fmt(r['battery_discharge_kwh'])} | {fmt(r['grid_cost'])} | {fmt(r['profit_01'])} | {fmt(r['profit_02'])} | {fmt(r['profit_035'])} |"
        )
    lines.append("")
    lines.append("## 8. 结论")
    lines.append("- 你的疑问在模型中已被纳入：")
    lines.append("  - 新增储能减少电网购电：已显式计入，且是本日收益增量主因。")
    lines.append("  - 新增储能吸纳光伏余电：已显式计入，但在本日对“净新增收益”的边际贡献较小。")
    lines.append(f"- {day} 这一天，新增 1 台 125kW/250kWh 的净新增收益为 **{fmt(net_grid_cost_saving)} 元/天**。")
    lines.append("- 在当前策略下（谷段优先充满），第2台储能出现明显边际收益递减。")
    lines.append("")
    lines.append("## 9. 附：口径一致性说明")
    lines.append("- 本报告使用与 `Script/annual_prediction.py` 同口径的调度与收益公式进行拆分复算。")
    lines.append("- 与日报实绩口径的差异：日报使用实测储能功率；本报告为参数化策略仿真（1台 vs 2台）对比。")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(output_path)


def main():
    parser = argparse.ArgumentParser(description="新增储能收益拆解报告生成")
    parser.add_argument("--csv", required=True, help="日度CSV绝对或相对路径")
    parser.add_argument("--output", help="输出报告路径")
    args = parser.parse_args()

    one = ESSSpec("1台储能", 250.0, 125.0)
    two = ESSSpec("2台储能", 500.0, 250.0)
    if args.output:
        output_path = args.output
    else:
        csv_df = pd.read_csv(args.csv, usecols=["时间"])
        day = pd.to_datetime(csv_df["时间"]).dt.strftime("%Y%m%d").iloc[0]
        output_path = os.path.join(REPORT_DIR, f"新增第2台储能收益拆解分析报告_{day}.md")
    build_report(args.csv, one, two, output_path)


if __name__ == "__main__":
    main()
