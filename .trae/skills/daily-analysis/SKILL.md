---
name: "daily-analysis"
description: "执行光伏储能每日收益分析。当用户要求进行每日收益分析或生成日报时调用。执行后必须自动更新总收益报表并推送到 GitHub。"
---

# 每日分析 (daily-analysis)

当用户要求进行“每日分析”或“生成每日收益报告”时，请执行以下标准操作流程：

1. **执行数据分析**：
   运行相关的 Python 脚本或 shell 脚本（如 `check_excess_pv.py`, `check_soc.py`, `test_two_cycles.py`, `organize_and_extract.sh` 等），处理 `数据/` 目录下的最新数据。

2. **生成或更新报告**：
   将分析结果输出到 `报告/` 目录下的 Markdown 文件中。

3. **同步更新总收益报表**：
   每次生成每日收益分析报告时，需将核心利润和增益数据自动同步更新到 `报告/总收益分析报表.md` 中。
   - 表头必须严格使用：`总收益(光伏电价X元/度)` 和 `储能额外收益(光伏电价X元/度)`。

4. **自动推送到 GitHub**：
   在完成上述分析和报表更新后，必须自动执行以下 Git 命令，将结果上传到 GitHub 仓库：
   ```bash
   git add 报告/ 数据/
   git commit -m "docs: 自动更新每日收益分析报告和数据"
   git push origin main
   ```
