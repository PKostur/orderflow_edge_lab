from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "winner_ema_adversarial_recheck.py"
SPEC = importlib.util.spec_from_file_location("winner_ema_adversarial_recheck", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _frame(start: str, rows: int = 500) -> pd.DataFrame:
    index = pd.date_range(start, periods=rows, freq="8h", tz="UTC")
    close = 100.0 + np.arange(rows) * 0.08 + np.sin(np.arange(rows) / 8.0)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.3
    low = np.minimum(open_, close) - 0.3
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0}, index=index)


class WinnerEmaAdversarialRecheckTests(unittest.TestCase):
    def test_shared_history_uses_latest_listing_start_and_common_end(self):
        early = _frame("2025-01-01", 500)
        late = _frame("2025-01-17", 440)
        aligned, lineage = MODULE.align_shared_history({"EARLY": early, "LATE": late})
        expected_start = max(early.index.min(), late.index.min())
        expected_end = min(early.index.max(), late.index.max())
        self.assertEqual(pd.Timestamp(lineage["shared_start"]), expected_start)
        self.assertEqual(pd.Timestamp(lineage["shared_end"]), expected_end)
        self.assertTrue(all(frame.index.min() == expected_start for frame in aligned.values()))
        self.assertTrue(all(frame.index.max() == expected_end for frame in aligned.values()))

    def test_higher_cost_cannot_improve_same_equal_weight_portfolio(self):
        frames = {"A": _frame("2025-01-01"), "B": _frame("2025-01-01") * 1.01}
        low = MODULE._series_stats(MODULE._portfolio_series(frames, MODULE.PRIMARY, round_trip_cost_bps=12.0)["net"])
        high = MODULE._series_stats(MODULE._portfolio_series(frames, MODULE.PRIMARY, round_trip_cost_bps=40.0)["net"])
        self.assertIsNotNone(low["net_return"])
        self.assertIsNotNone(high["net_return"])
        self.assertLessEqual(high["net_return"], low["net_return"] + 1e-12)

    def test_portfolio_fold_windows_are_non_overlapping(self):
        frames = {f"S{i}": _frame("2025-01-01") for i in range(8)}
        aligned, _ = MODULE.align_shared_history(frames)
        series = MODULE._portfolio_series(aligned, MODULE.PRIMARY, round_trip_cost_bps=20.0)
        folds = MODULE._portfolio_fold_stats(series, fold_days=120)
        starts = [pd.Timestamp(row["fold_start"]) for row in folds]
        self.assertTrue(all((b - a) >= pd.Timedelta(days=120) for a, b in zip(starts, starts[1:])))


if __name__ == "__main__":
    unittest.main()
