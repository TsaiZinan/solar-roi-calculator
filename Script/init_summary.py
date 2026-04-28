import re
from config import SUMMARY_PRICE_KEYS, SUMMARY_REPORT_PATH, get_daily_report_paths


def rebuild_summary_table():
    reports = get_daily_report_paths()

    with open(SUMMARY_REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write("# 总收益分析报表\n\n")
        f.write("| 日期 | 经营总收益(光伏电价0.1元/度) | 储能额外收益(光伏电价0.1元/度) | 经营总收益(光伏电价0.2元/度) | 储能额外收益(光伏电价0.2元/度) | 经营总收益(光伏电价0.35元/度) | 储能额外收益(光伏电价0.35元/度) |\n")
        f.write("|:---|---:|---:|---:|---:|---:|---:|\n")

        for rp in reports:
            date_match = re.search(r'_(\d{8})\.md', rp)
            if not date_match:
                continue
            date_str = date_match.group(1)

            with open(rp, 'r', encoding='utf-8') as report_file:
                content = report_file.read()

            profits = {'01': (0, 0), '02': (0, 0), '035': (0, 0)}

            for price_key, price_str in SUMMARY_PRICE_KEYS:
                scenario_block = re.search(
                    r'### 【场景 [A-Z]：光伏上网电价 ' + price_str + r' 元/度】(.*?)(?=\n### 【场景 |\Z)',
                    content,
                    re.S
                )
                if not scenario_block:
                    continue

                block = scenario_block.group(1)

                m2_total = re.search(r'含储能经营总收益.*?\*\*([0-9.]+)\*\* 元', block, re.S)
                m2_extra = re.search(r'额外创收\*\* \*\*([0-9.]+)\*\* 元', block, re.S)
                if m2_total and m2_extra:
                    profits[price_key] = (float(m2_total.group(1)), float(m2_extra.group(1)))
                    continue

                m2_new = re.search(
                    r'经营总收益.*?\*\*([0-9.]+)\*\* 元.*?上述各项收益中有 \*\*([0-9.]+)\*\* 元由',
                    block,
                    re.S
                )
                if m2_new:
                    profits[price_key] = (float(m2_new.group(1)), float(m2_new.group(2)))
                    continue

                m2_old = re.search(r'额外创收\*\* \*\*([0-9.]+)\*\* 元。\(最终今日实际总利润: \*\*([0-9.]+)\*\* 元\)', block, re.S)
                if m2_old:
                    profits[price_key] = (float(m2_old.group(2)), float(m2_old.group(1)))
                    continue

                m1_total = re.search(r'当光伏上网电价为 ' + price_str + r' 元时，系统预估总净利润: \*\*([0-9.]+)\*\* 元', block)
                m1_extra = re.search(r'带来的\*\*额外净收益\*\* \(电价 ' + price_str + r' 元\): \*\*([0-9.]+)\*\* 元', block)
                if m1_total and m1_extra:
                    profits[price_key] = (float(m1_total.group(1)), float(m1_extra.group(1)))

            if profits['01'][0] == 0 and profits['02'][0] == 0:
                continue

            f.write(f"| {date_str} | {profits['01'][0]:.2f} | {profits['01'][1]:.2f} | {profits['02'][0]:.2f} | {profits['02'][1]:.2f} | {profits['035'][0]:.2f} | {profits['035'][1]:.2f} |\n")

    print("初始化总表完成：", SUMMARY_REPORT_PATH)


def main():
    rebuild_summary_table()


if __name__ == "__main__":
    main()
