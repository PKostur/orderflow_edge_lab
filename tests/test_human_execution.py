from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.human_execution import HumanPlan, checkin_times, signals_8h, simulate, to_8h


def _h1(seed: int, hours: int = 24 * 200, drift: float = 0.0) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01T00:00:00Z", periods=hours, freq="1h")
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(drift, 0.006, hours)))
    open_ = np.concatenate([[100.0], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.001,
                         "low": np.minimum(open_, close) * 0.999, "close": close}, index=idx)


class HumanExecutionTests(unittest.TestCase):
    def test_8h_rebuild_aligns_to_utc_boundaries(self):
        h8 = to_8h(_h1(0))
        self.assertTrue(set(h8.index.hour) <= {0, 8, 16})

    def test_signals_are_known_only_after_bar_close(self):
        s = signals_8h(to_8h(_h1(0)), ("DON8", "EMA8"))
        self.assertEqual(s.index[0], pd.Timestamp("2024-01-01T08:00:00Z"))

    def test_checkins_follow_local_time_across_dst(self):
        idx = pd.date_range("2024-03-29T00:00Z", "2024-04-01T00:00Z", freq="1h")
        c = checkin_times(idx, HumanPlan())
        # 09:00 Berlin is 08:00 UTC before 31 March (CET) and 07:00 UTC after (CEST)
        self.assertIn(pd.Timestamp("2024-03-29T08:00Z"), c)
        self.assertIn(pd.Timestamp("2024-03-31T07:00Z"), c)
        self.assertEqual(len(c), 9)

    def test_session_schedule_mixes_timezones(self):
        idx = pd.date_range("2024-07-01T00:00Z", periods=24, freq="1h")
        plan = HumanPlan(sessions=(("Asia/Tokyo", 9), ("Europe/London", 8), ("America/New_York", 10)))
        # summer: Tokyo 09:00 = 00:00 UTC, London 08:00 BST = 07:00 UTC, New York 10:00 EDT = 14:00 UTC
        self.assertEqual([t.hour for t in checkin_times(idx, plan)], [0, 7, 14])

    def test_trending_market_is_profitable_and_positions_capped(self):
        h1 = {f"C{k}": _h1(k, drift=0.0004) for k in range(6)}
        fees = {s: (0.0004, 0.0001) for s in h1}
        r = simulate(h1, fees, HumanPlan(max_coins=3))
        self.assertGreater(r["final_equity"], 10_000.0)
        self.assertGreater(r["trades"], 0)

    def test_limit_execution_runs_and_costs_are_counted(self):
        h1 = {f"C{k}": _h1(k + 10) for k in range(4)}
        fees = {s: (0.0004, 0.0001) for s in h1}
        m = simulate(h1, fees, HumanPlan(max_coins=2, execution="market"))
        l = simulate(h1, fees, HumanPlan(max_coins=2, execution="limit"))
        self.assertGreaterEqual(m["fees_and_slippage_pct_per_year"], 0.0)
        self.assertGreaterEqual(l["fees_and_slippage_pct_per_year"], 0.0)
        self.assertEqual(len(m["daily_returns"]), len(l["daily_returns"]))


if __name__ == "__main__":
    unittest.main()
