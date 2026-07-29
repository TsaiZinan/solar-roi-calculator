#!/usr/bin/env python3
"""Safely append newly published hourly spot prices to the local master CSV."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
from zoneinfo import ZoneInfo


REQUIRED_COLUMNS = ["date", "hour", "realtime_price_yuan_per_MWh"]
HOUR_PATTERN = re.compile(r"^(\d{1,2})(?::(\d{2})(?::\d{2})?)?$")
SHANGHAI = ZoneInfo("Asia/Shanghai")


class SpotPriceError(ValueError):
    """Raised when a spot price update would be unsafe."""


@dataclass(frozen=True)
class UpdatePlan:
    existing_rows: int
    candidate_rows: int
    overlapping_rows: int
    new_rows: int
    new_dates: tuple[str, ...]
    first_date: str | None
    last_date: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "ready" if self.new_rows else "no_new_data",
            "existing_rows": self.existing_rows,
            "candidate_rows": self.candidate_rows,
            "overlapping_rows": self.overlapping_rows,
            "new_rows": self.new_rows,
            "new_dates": list(self.new_dates),
            "first_date": self.first_date,
            "last_date": self.last_date,
        }


def _normalize_hour(value: object) -> str:
    if pd.isna(value):
        raise SpotPriceError("hour contains an empty value")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise SpotPriceError(f"invalid hour value: {value!r}")
        hour = int(numeric)
        minute = 0
    else:
        text = str(value).strip()
        if text.endswith(".0") and text[:-2].isdigit():
            text = text[:-2]
        match = HOUR_PATTERN.fullmatch(text)
        if not match:
            raise SpotPriceError(f"invalid hour value: {value!r}")
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")

    if hour not in range(24) or minute != 0:
        raise SpotPriceError(f"hour must be an exact hourly boundary: {value!r}")
    return f"{hour:02d}:00"


def _normalize_frame(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise SpotPriceError(f"{label} is missing columns: {', '.join(missing)}")

    normalized = frame.loc[:, REQUIRED_COLUMNS].copy()
    parsed_dates = pd.to_datetime(normalized["date"], errors="coerce")
    if parsed_dates.isna().any():
        raise SpotPriceError(f"{label} contains an invalid date")
    normalized["date"] = parsed_dates.dt.strftime("%Y-%m-%d")
    normalized["hour"] = normalized["hour"].map(_normalize_hour)
    normalized["realtime_price_yuan_per_MWh"] = pd.to_numeric(
        normalized["realtime_price_yuan_per_MWh"], errors="coerce"
    )

    invalid_prices = normalized["realtime_price_yuan_per_MWh"].map(
        lambda value: not math.isfinite(float(value)) if pd.notna(value) else True
    )
    if invalid_prices.any():
        raise SpotPriceError(f"{label} contains a non-finite price")

    duplicate_mask = normalized.duplicated(["date", "hour"], keep=False)
    if duplicate_mask.any():
        duplicates = normalized.loc[duplicate_mask, ["date", "hour"]].drop_duplicates()
        first = duplicates.iloc[0]
        raise SpotPriceError(
            f"{label} contains duplicate date+hour: {first['date']} {first['hour']}"
        )

    return normalized.sort_values(["date", "hour"], kind="stable").reset_index(drop=True)


def read_price_csv(path: Path, *, label: str) -> pd.DataFrame:
    if not path.is_file():
        raise SpotPriceError(f"{label} does not exist: {path}")
    if path.stat().st_size <= 0:
        raise SpotPriceError(f"{label} is empty: {path}")
    try:
        frame = pd.read_csv(path)
    except Exception as exc:  # pandas exposes several parser exception types
        raise SpotPriceError(f"{label} cannot be parsed as CSV: {exc}") from exc
    if frame.empty:
        raise SpotPriceError(f"{label} has no data rows")
    return _normalize_frame(frame, label=label)


def _validate_complete_dates(frame: pd.DataFrame, dates: Iterable[str], *, label: str) -> None:
    expected_hours = {f"{hour:02d}:00" for hour in range(24)}
    for date in dates:
        hours = set(frame.loc[frame["date"] == date, "hour"])
        if hours != expected_hours:
            missing = sorted(expected_hours - hours)
            extra = sorted(hours - expected_hours)
            raise SpotPriceError(
                f"{label} date {date} is not a complete 24-hour day "
                f"(missing={missing}, extra={extra})"
            )


def _dates_are_consecutive(dates: list[str]) -> bool:
    parsed = [datetime.strptime(date, "%Y-%m-%d").date() for date in dates]
    return all(current - previous == timedelta(days=1) for previous, current in zip(parsed, parsed[1:]))


def build_update(
    existing: pd.DataFrame, candidate: pd.DataFrame
) -> tuple[UpdatePlan, pd.DataFrame]:
    if existing.empty:
        raise SpotPriceError("main price file must contain at least one existing row")

    latest_existing = str(existing["date"].max())
    _validate_complete_dates(existing, [latest_existing], label="main price file")

    existing_keys = existing.set_index(["date", "hour"])
    candidate_keys = candidate.set_index(["date", "hour"])
    overlap = candidate_keys.index.intersection(existing_keys.index)
    for key in overlap:
        old_price = float(existing_keys.loc[key, "realtime_price_yuan_per_MWh"])
        new_price = float(candidate_keys.loc[key, "realtime_price_yuan_per_MWh"])
        if not math.isclose(old_price, new_price, rel_tol=0.0, abs_tol=1e-9):
            raise SpotPriceError(
                f"candidate conflicts with existing price at {key[0]} {key[1]}"
            )

    new_rows = candidate.loc[candidate["date"] > latest_existing].copy()
    new_dates = sorted(new_rows["date"].unique().tolist())
    if new_dates:
        first_expected = (
            datetime.strptime(latest_existing, "%Y-%m-%d").date() + timedelta(days=1)
        ).isoformat()
        if new_dates[0] != first_expected:
            raise SpotPriceError(
                f"candidate must start at {first_expected}, got {new_dates[0]}"
            )
        if not _dates_are_consecutive(new_dates):
            raise SpotPriceError("candidate new dates are not consecutive")
        _validate_complete_dates(candidate, new_dates, label="candidate price file")

    older_nonoverlap = candidate_keys.index[
        (candidate_keys.index.get_level_values("date") <= latest_existing)
        & ~candidate_keys.index.isin(existing_keys.index)
    ]
    if len(older_nonoverlap):
        date, hour = older_nonoverlap[0]
        raise SpotPriceError(
            f"candidate contains an unexpected historical key: {date} {hour}"
        )

    combined = pd.concat([existing, new_rows], ignore_index=True)
    combined = combined.sort_values(["date", "hour"], kind="stable").reset_index(drop=True)
    if combined.duplicated(["date", "hour"]).any():
        raise SpotPriceError("combined result contains duplicate date+hour rows")

    expected_new_rows = len(new_dates) * 24
    if len(new_rows) != expected_new_rows:
        raise SpotPriceError(
            f"candidate added {len(new_rows)} rows, expected {expected_new_rows}"
        )
    if len(combined) != len(existing) + expected_new_rows:
        raise SpotPriceError("combined row count does not match the expected increase")
    if combined["date"].min() != existing["date"].min():
        raise SpotPriceError("combined earliest date changed unexpectedly")
    if new_dates and combined["date"].max() != new_dates[-1]:
        raise SpotPriceError("combined latest date does not match candidate")
    if not new_dates and combined["date"].max() != existing["date"].max():
        raise SpotPriceError("combined latest date changed without new data")

    plan = UpdatePlan(
        existing_rows=len(existing),
        candidate_rows=len(candidate),
        overlapping_rows=len(overlap),
        new_rows=len(new_rows),
        new_dates=tuple(new_dates),
        first_date=new_dates[0] if new_dates else None,
        last_date=new_dates[-1] if new_dates else None,
    )
    return plan, combined


def _unique_backup_path(backup_dir: Path, main_path: Path) -> Path:
    timestamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
    stem = f"{main_path.stem}_{timestamp}"
    candidate = backup_dir / f"{stem}{main_path.suffix}"
    counter = 1
    while candidate.exists():
        candidate = backup_dir / f"{stem}_{counter}{main_path.suffix}"
        counter += 1
    return candidate


def _write_and_validate_temp(
    combined: pd.DataFrame, main_path: Path, existing: pd.DataFrame, plan: UpdatePlan
) -> Path:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{main_path.stem}.", suffix=".tmp", dir=main_path.parent
    )
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        combined.to_csv(temp_path, index=False, encoding="utf-8", lineterminator="\n")
        with temp_path.open("rb") as handle:
            os.fsync(handle.fileno())

        reread = read_price_csv(temp_path, label="temporary merged price file")
        if len(reread) != len(existing) + plan.new_rows:
            raise SpotPriceError("temporary merged file failed row-count verification")
        if reread["date"].min() != existing["date"].min():
            raise SpotPriceError("temporary merged file moved the earliest date")
        if reread["date"].max() != combined["date"].max():
            raise SpotPriceError("temporary merged file changed the latest date")
        if reread.duplicated(["date", "hour"]).any():
            raise SpotPriceError("temporary merged file contains duplicate keys")
        return temp_path
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def apply_update(
    candidate_path: Path,
    main_path: Path,
    backup_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    existing = read_price_csv(main_path, label="main price file")
    candidate = read_price_csv(candidate_path, label="candidate price file")
    plan, combined = build_update(existing, candidate)
    result = plan.as_dict()
    result["main_path"] = str(main_path.resolve())
    result["candidate_path"] = str(candidate_path.resolve())

    if dry_run or not plan.new_rows:
        result["dry_run"] = dry_run
        result["backup_path"] = None
        return result

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = _unique_backup_path(backup_dir, main_path)
    with main_path.open("rb") as source, backup_path.open("xb") as destination:
        shutil.copyfileobj(source, destination)
        destination.flush()
        os.fsync(destination.fileno())
    shutil.copystat(main_path, backup_path)

    temp_path: Path | None = None
    try:
        temp_path = _write_and_validate_temp(combined, main_path, existing, plan)
        os.replace(temp_path, main_path)
        temp_path = None
        result["status"] = "updated"
        result["backup_path"] = str(backup_path.resolve())
        result["final_rows"] = len(combined)
        result["final_first_date"] = str(combined["date"].min())
        result["final_last_date"] = str(combined["date"].max())
        return result
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    project_root = _default_project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="CSV extracted from the official page")
    parser.add_argument(
        "--main",
        type=Path,
        default=project_root / "数据" / "spot_realtime_prices.csv",
        help="master price CSV",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=project_root / "数据" / "备份",
        help="non-overwriting backup directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and describe the update without writing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = apply_update(
            args.candidate.resolve(),
            args.main.resolve(),
            args.backup_dir.resolve(),
            dry_run=args.dry_run,
        )
    except SpotPriceError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        )
        return 3

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
