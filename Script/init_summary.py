import os
import glob
import re

REPORT_DIR = "/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算/报告"
SUMMARY_PATH = os.path.join(REPORT_DIR, "总收益分析报表.md")

reports = glob.glob(os.path.join(REPORT_DIR, "每日收益分析报告_2026*.md"))
reports.sort()

with open(SUMMARY_PATH, 'w', encoding='utf-8') as f:
    f.write("# 总收益分析报表\n\n")
    f.write("| 日期 | 总收益(光伏电价0.1元/度) | 储能额外收益(光伏电价0.1元/度) | 总收益(光伏电价0.2元/度) | 储能额外收益(光伏电价0.2元/度) | 总收益(光伏电价0.35元/度) | 储能额外收益(光伏电价0.35元/度) |\n")
    f.write("|:---|---:|---:|---:|---:|---:|---:|\n")
    
    for rp in reports:
        date_match = re.search(r'_(\d{8})\.md', rp)
        if not date_match:
            continue
        date_str = date_match.group(1)
        
        content = open(rp, 'r', encoding='utf-8').read()
        
        profits = {'01': (0,0), '02': (0,0), '035': (0,0)}
        
        for price_key, price_str in [('01', '0.1'), ('02', '0.2'), ('035', '0.35')]:
            # 格式2: calc_revenue
            m2_total = re.search(r'场景 [A-Z]：光伏上网电价 ' + price_str + r' 元/度.*?\*\*额外创收\*\* \*\*([0-9.]+)\*\* 元。\(最终今日实际总利润: \*\*([0-9.]+)\*\* 元\)', content, re.S)
            if m2_total:
                profits[price_key] = (float(m2_total.group(2)), float(m2_total.group(1)))
            else:
                # 格式1: daily_analysis
                m1_total = re.search(r'当光伏上网电价为 ' + price_str + r' 元时，系统预估总净利润: \*\*([0-9.]+)\*\* 元', content)
                m1_extra = re.search(r'带来的\*\*额外净收益\*\* \(电价 ' + price_str + r' 元\): \*\*([0-9.]+)\*\* 元', content)
                if m1_total and m1_extra:
                    profits[price_key] = (float(m1_total.group(1)), float(m1_extra.group(1)))
        
        if profits['01'][0] == 0 and profits['02'][0] == 0:
            continue
            
        f.write(f"| {date_str} | {profits['01'][0]:.2f} | {profits['01'][1]:.2f} | {profits['02'][0]:.2f} | {profits['02'][1]:.2f} | {profits['035'][0]:.2f} | {profits['035'][1]:.2f} |\n")

print("初始化总表完成：", SUMMARY_PATH)
