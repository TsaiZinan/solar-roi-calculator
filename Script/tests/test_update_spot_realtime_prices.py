from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "update_spot_realtime_prices.py"
SPEC = importlib.util.spec_from_file_location("update_spot_realtime_prices", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_day(day: str, *, offset: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [day] * 24,
            "hour": [f"{hour:02d}:00" for hour in range(24)],
            "realtime_price_yuan_per_MWh": [
                round(offset + hour - 3.5, 2) for hour in range(24)
            ],
        }
    )


class UpdateSpotRealtimePricesTests(unittest.TestCase):
    def test_single_day_append(self) -> None:
        existing = make_day("2026-07-14")
        candidate = make_day("2026-07-15", offset=100)
        plan, combined = MODULE.build_update(existing, candidate)
        self.assertEqual(plan.new_rows, 24)
        self.assertEqual(plan.new_dates, ("2026-07-15",))
        self.assertEqual(len(combined), 48)

    def test_multi_day_append(self) -> None:
        existing = make_day("2026-07-14")
        candidate = pd.concat(
            [
                make_day("2026-07-15", offset=100),
                make_day("2026-07-16", offset=200),
                make_day("2026-07-17", offset=300),
            ],
            ignore_index=True,
        )
        plan, combined = MODULE.build_update(existing, candidate)
        self.assertEqual(plan.new_rows, 72)
        self.assertEqual(combined["date"].max(), "2026-07-17")

    def test_identical_overlap_is_no_new_data(self) -> None:
        existing = make_day("2026-07-14")
        plan, combined = MODULE.build_update(existing, existing.copy())
        self.assertEqual(plan.new_rows, 0)
        self.assertEqual(plan.overlapping_rows, 24)
        pd.testing.assert_frame_equal(existing, combined)

    def test_conflicting_overlap_is_rejected(self) -> None:
        existing = make_day("2026-07-14")
        candidate = existing.copy()
        candidate.loc[0, "realtime_price_yuan_per_MWh"] += 0.01
        with self.assertRaisesRegex(MODULE.SpotPriceError, "conflicts"):
            MODULE.build_update(existing, candidate)

    def test_gap_is_rejected(self) -> None:
        existing = make_day("2026-07-14")
        candidate = make_day("2026-07-16")
        with self.assertRaisesRegex(MODULE.SpotPriceError, "must start"):
            MODULE.build_update(existing, candidate)

    def test_incomplete_day_is_rejected(self) -> None:
        existing = make_day("2026-07-14")
        candidate = make_day("2026-07-15").iloc[:-1]
        with self.assertRaisesRegex(MODULE.SpotPriceError, "complete 24-hour"):
            MODULE.build_update(existing, candidate)

    def test_zero_and_negative_prices_are_valid(self) -> None:
        existing = make_day("2026-07-14")
        candidate = make_day("2026-07-15")
        candidate.loc[0, "realtime_price_yuan_per_MWh"] = 0
        candidate.loc[1, "realtime_price_yuan_per_MWh"] = -500
        plan, _ = MODULE.build_update(existing, candidate)
        self.assertEqual(plan.new_rows, 24)

    def test_non_hour_boundary_is_rejected(self) -> None:
        candidate = make_day("2026-07-15")
        candidate.loc[0, "hour"] = "00:15"
        with self.assertRaisesRegex(MODULE.SpotPriceError, "hourly boundary"):
            MODULE._normalize_frame(candidate, label="candidate")

    def test_apply_update_creates_backup_and_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            main_path = root / "spot_realtime_prices.csv"
            candidate_path = root / "candidate.csv"
            backup_dir = root / "backups"
            existing = pd.concat(
                [make_day("2026-07-13", offset=10), make_day("2026-07-14", offset=20)],
                ignore_index=True,
            )
            candidate = make_day("2026-07-15", offset=30)
            existing.to_csv(main_path, index=False)
            candidate.to_csv(candidate_path, index=False)

            result = MODULE.apply_update(candidate_path, main_path, backup_dir)
            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["final_rows"], 72)
            backups = list(backup_dir.glob("*.csv"))
            self.assertEqual(len(backups), 1)
            pd.testing.assert_frame_equal(pd.read_csv(backups[0]), existing)

            merged = MODULE.read_price_csv(main_path, label="merged")
            historical = merged.loc[merged["date"] <= "2026-07-14"].reset_index(drop=True)
            expected = MODULE._normalize_frame(existing, label="existing")
            pd.testing.assert_frame_equal(historical, expected)


if __name__ == "__main__":
    unittest.main()
