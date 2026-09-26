from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3 import align_funding, run_canonical_backtest_v3
from orderflow_edge_lab.universal_backtest import ExecutionModel, FunctionStrategy, legacy_strategy
from tests.test_canonical_v3 import _fixed, _frame


def _flat(periods: int = 10) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq="8h")
    o = np.full(periods, 100.0)
    return pd.DataFrame({"open": o, "high": o * 1.01, "low": o * 0.99, "close": o}, index=idx)


class FundingTests(unittest.TestCase):
    def test_no_funding_is_identical_to_v3(self):
        frame = _frame()
        strat = legacy_strategy("donchian_breakout")
        ex = ExecutionModel(round_trip_cost_bps=20.0)
        a = run_canonical_backtest_v3(frame, strat, {"lookback": 20}, ex)
        zero = pd.Series(0.0, index=frame.index)
        b = run_canonical_backtest_v3(frame, strat, {"lookback": 20}, ex, funding=zero)
        self.assertEqual(a["accounting"]["version"], 3)
        self.assertEqual(b["accounting"]["version"], "3.1")
        self.assertAlmostEqual(a["total_return"], b["total_return"], places=12)

    def test_long_pays_and_short_receives_positive_funding(self):
        frame = _flat()
        rate = pd.Series(0.001, index=frame.index)  # 10 bps per 8h settlement
        # target at bars 0..2 -> held over intervals 1..3; settlements at opens 2,3 and exit open 4
        long = run_canonical_backtest_v3(frame, _fixed([1.0, 1.0, 1.0]), {}, ExecutionModel(), funding=rate)
        short = run_canonical_backtest_v3(frame, _fixed([-1.0, -1.0, -1.0]), {}, ExecutionModel(), funding=rate)
        lt, st = long["trades_ledger"][0], short["trades_ledger"][0]
        self.assertAlmostEqual(lt["gross_bps"], 0.0)
        self.assertAlmostEqual(lt["funding_bps"], -30.0, places=6)
        self.assertAlmostEqual(st["funding_bps"], 30.0, places=6)
        self.assertAlmostEqual(lt["net_bps"], ((1 - 0.001) ** 3 - 1) * 1e4, places=6)
        self.assertAlmostEqual(st["net_bps"], ((1 + 0.001) ** 3 - 1) * 1e4, places=6)
        self.assertTrue(long["accounting"]["ledger_equity_reconciled"])

    def test_funding_at_entry_open_is_not_paid_by_new_position(self):
        frame = _flat()
        rate = pd.Series(0.0, index=frame.index)
        rate.iloc[1] = 0.01  # settles exactly at the entry open (bar 1)
        r = run_canonical_backtest_v3(frame, _fixed([1.0, 1.0, 0.0]), {}, ExecutionModel(), funding=rate)
        self.assertAlmostEqual(r["trades_ledger"][0]["funding_bps"], 0.0)

    def test_align_sums_sub_interval_settlements_and_reports_coverage(self):
        idx = pd.date_range("2026-01-01T00:00:00Z", periods=4, freq="8h")
        raw = pd.Series(
            [0.001, 0.002, 0.003],
            index=pd.DatetimeIndex(["2026-01-01T04:00:00Z", "2026-01-01T08:00:00Z", "2026-01-01T16:00:00Z"]),
        )
        aligned, coverage = align_funding(raw, idx)
        # (00:00, 08:00] gets 0.001 + 0.002; (08:00, 16:00] gets 0.003
        self.assertEqual(list(aligned), [0.0, 0.003, 0.003, 0.0])
        self.assertAlmostEqual(coverage, 2 / 3)

    def test_reconciles_on_random_path_with_random_funding(self):
        frame = _frame()
        rng = np.random.default_rng(9)
        rate = pd.Series(rng.normal(0.0001, 0.0003, len(frame)), index=frame.index)
        r = run_canonical_backtest_v3(
            frame, legacy_strategy("ema_tsmom"), {"fast": 12, "slow": 48, "min_atr_spread": 0.1},
            ExecutionModel(round_trip_cost_bps=20.0), funding=rate,
        )
        self.assertTrue(r["accounting"]["ledger_equity_reconciled"])
        self.assertGreater(r["trades"], 3)


if __name__ == "__main__":
    unittest.main()
