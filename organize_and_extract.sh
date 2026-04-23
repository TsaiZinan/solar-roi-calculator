#!/bin/bash
cd "/Users/cai/SynologyDrive/Project/#ProjectWork-000000-光伏收益计算"

# Use python from .venv
PYTHON_BIN=".venv/bin/python"

for date in "20260415" "20260416" "20260417" "20260418"; do
  echo "Processing $date..."
  
  new_csv="数据/$date/日报表_广东汕头市雅威机电实业0.12MW#0.257MWh工商储项目_*.csv"
  new_img="数据/$date/${date}.jpg"
  
  # Check if CSV exists and has '光伏发电功率(kW)'
  for f in $new_csv; do
    if [ -f "$f" ]; then
      if ! head -n 1 "$f" | grep -q "光伏发电功率(kW)"; then
        echo "Extracting and merging PV data for $date..."
        $PYTHON_BIN Script/extract_and_merge_pv.py "$(pwd)/$new_img" "$(pwd)/$f"
      else
        echo "PV data already merged for $date."
      fi
    fi
  done
done
