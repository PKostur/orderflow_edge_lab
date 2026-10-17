"""Leverage bracket engine (synthetic, offline): levels, costs, funding, entries, account, bootstrap, BH, no-overwrite."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from orderflow_edge_lab import leverage_bracket as lb
from orderflow_edge_lab import leverage_bracket_data as bd


def walk(h, lo, c, direction, leverage=10, tp=0.10, stop="S2", **kw):
    kw.setdefault("start_idx", 0)
    return lb.walk_bracket(h, lo, c, np.asarray(direction, dtype=np.int8), leverage, tp, stop, **kw)


def only_first(n, side=1):
    d = np.zeros(n, dtype=np.int8)
    d[0] = side
    return d


def econ(trades, close, leverage=10, tp=0.10, f_idx=None, f_rate=None):
    return lb.trade_economics(trades, np.asarray(close, dtype=float), leverage, tp,
                              np.zeros(0, dtype=np.int64) if f_idx is None else np.asarray(f_idx),
                              np.zeros(0) if f_rate is None else np.asarray(f_rate))


class LevelTests(unittest.TestCase):
    # leverage 10, tp 10% of margin = 1.0% move, S2 stop 5.0%, S1 liquidation 9.5% (1/L - 0.5%)
    def test_take_profit_long_pnl_includes_fees(self):
        c = [100.0, 100.0, 100.0, 100.0]
        h = [100.0, 100.5, 101.5, 100.0]
        lo = [100.0, 99.5, 99.5, 100.0]
        t = walk(h, lo, c, only_first(4), max_hold=3)
        self.assertEqual((t.open_idx.tolist(), t.close_idx.tolist(), t.code.tolist()), ([0], [2], [lb.CODE_TP]))
        e = econ(t, c)
        self.assertAlmostEqual(e["net"][0], 0.10 - 0.0014 * 10)  # +10% of margin minus 14 bps x L

    def test_take_profit_short(self):
        c = [100.0, 100.0, 100.0, 100.0]
        h = [100.0, 100.5, 100.5, 100.0]
        lo = [100.0, 99.5, 98.9, 100.0]
        t = walk(h, lo, c, only_first(4, -1), max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_TP])
        self.assertAlmostEqual(econ(t, c)["net"][0], 0.086)

    def test_half_margin_stop_long_and_short(self):
        c = [100.0] * 4
        t = walk([100, 100, 100, 100], [100, 100, 94.9, 100], c, only_first(4), max_hold=3)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist()), ([lb.CODE_STOP], [2]))
        self.assertAlmostEqual(econ(t, c)["net"][0], -0.5 - 0.014)
        t = walk([100, 100, 105.1, 100], [100, 100, 100, 100], c, only_first(4, -1), max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_STOP])
        self.assertAlmostEqual(econ(t, c)["net"][0], -0.514)

    def test_liquidation_loses_margin_plus_fee_on_notional(self):
        c = [100.0] * 4
        t = walk([100, 100, 100, 100], [100, 100, 90.4, 100], c, only_first(4), stop="S1", max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_LIQ])
        e = econ(t, c)
        self.assertAlmostEqual(e["net"][0], -(1.0 + 0.005 * 10) - 0.0007 * 10)  # + entry half-fee
        # 90.6 is above the liquidation price 90.5: no liquidation, runs to the time stop
        t = walk([100, 100, 100, 100], [100, 100, 90.6, 100], c, only_first(4), stop="S1", max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_TIME])

    def test_s1_has_no_half_margin_stop(self):
        c = [100.0] * 4
        t = walk([100, 100, 100, 100], [100, 100, 94.0, 100], c, only_first(4), stop="S1", max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_TIME])

    def test_time_stop_closes_at_the_close_with_pnl_on_the_move(self):
        c = [100.0, 100.2, 100.4, 100.5, 100.5, 100.5]
        h = [100.0, 100.3, 100.5, 100.6, 100.6, 100.6]
        lo = [100.0, 100.0, 100.3, 100.4, 100.4, 100.4]
        t = walk(h, lo, c, only_first(6), max_hold=4)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist()), ([lb.CODE_TIME], [4]))
        self.assertAlmostEqual(econ(t, c)["net"][0], (100.5 / 100.0 - 1.0) * 10 - 0.014)

    def test_unfinished_trade_at_the_end_of_data_is_dropped(self):
        c = [100.0] * 4
        t = walk(c, c, c, only_first(4), max_hold=10)
        self.assertEqual(len(t), 0)

    def test_same_bar_touch_assumes_the_adverse_level_first(self):
        c = [100.0] * 4
        h = [100, 100, 102.0, 100]
        lo = [100, 100, 94.0, 100]
        t = walk(h, lo, c, only_first(4), max_hold=3)
        self.assertEqual((t.code.tolist(), t.ambiguous.tolist()), ([lb.CODE_STOP], [1]))
        self.assertAlmostEqual(econ(t, c)["net"][0], -0.514)
        # favourable only: not counted as ambiguous
        t = walk([100, 100, 102.0, 100], [100, 100, 99.0, 100], c, only_first(4), max_hold=3)
        self.assertEqual((t.code.tolist(), t.ambiguous.tolist()), ([lb.CODE_TP], [0]))
        # short, same bar
        t = walk([100, 100, 106.0, 100], [100, 100, 98.0, 100], c, only_first(4, -1), max_hold=3)
        self.assertEqual((t.code.tolist(), t.ambiguous.tolist()), ([lb.CODE_STOP], [1]))

    def test_reopen_at_the_close_of_the_closing_bar(self):
        c = [100.0, 100.0, 103.0, 103.0, 103.0, 103.0, 103.0]
        h = [100.0, 100.0, 103.5, 103.0, 103.0, 103.0, 103.0]
        lo = [100.0, 100.0, 99.8, 103.0, 103.0, 103.0, 103.0]
        t = walk(h, lo, c, np.ones(7, dtype=np.int8), max_hold=3)
        self.assertEqual(t.open_idx.tolist()[:2], [0, 2])
        self.assertEqual(t.close_idx.tolist()[0], 2)
        # the second trade's entry is the close of bar 2 (103), its take-profit level 104.03 is not reached
        self.assertEqual(t.code.tolist()[1], lb.CODE_TIME)
        self.assertAlmostEqual(econ(t, c)["gross"][1], 0.0)

    def test_entry_waits_for_a_direction_and_a_valid_close(self):
        c = [100.0, np.nan, 100.0, 100.0, 100.0, 100.0]
        d = np.array([0, 1, 0, 1, 0, 0], dtype=np.int8)
        t = walk(c, c, c, d, max_hold=2)
        self.assertEqual(t.open_idx.tolist(), [3])  # bar 1 has no close
        self.assertEqual(t.close_idx.tolist(), [5])


class FundingTests(unittest.TestCase):
    def test_settlement_in_window_and_sign(self):
        c = [100.0] * 8
        long_t = walk(c, c, c, only_first(8, 1), max_hold=5)
        short_t = walk(c, c, c, only_first(8, -1), max_hold=5)
        self.assertEqual(long_t.close_idx.tolist(), [5])
        # settlements at 0 (not after the open), 3 and 5 (at the close minute: charged), 6 (after the close)
        f_idx, f_rate = [0, 3, 5, 6], [0.01, 0.001, 0.002, 0.5]
        fl = econ(long_t, c, f_idx=f_idx, f_rate=f_rate)
        fs = econ(short_t, c, f_idx=f_idx, f_rate=f_rate)
        self.assertAlmostEqual(fl["funding"][0], 10 * 0.003)  # longs pay positive funding
        self.assertAlmostEqual(fs["funding"][0], -10 * 0.003)  # shorts receive it
        self.assertAlmostEqual(fl["net"][0], 0.0 - 0.014 - 0.03)
        self.assertAlmostEqual(fs["net"][0], 0.0 - 0.014 + 0.03)

    def test_negative_rate_is_paid_by_shorts(self):
        c = [100.0] * 6
        t = walk(c, c, c, only_first(6, -1), max_hold=4)
        e = econ(t, c, f_idx=[2], f_rate=[-0.001])
        self.assertAlmostEqual(e["funding"][0], 10 * 0.001)

    def test_liquidated_trade_pays_entry_fee_and_funding(self):
        c = [100.0] * 6
        lo = [100, 100, 80, 100, 100, 100]
        t = walk(c, lo, c, only_first(6), stop="S1", max_hold=4)
        e = econ(t, c, f_idx=[2], f_rate=[0.01])
        self.assertAlmostEqual(e["funding"][0], 10 * 0.01)
        self.assertAlmostEqual(e["net"][0], -1.05 - 0.007 - 0.10)


class EntryTests(unittest.TestCase):
    def test_e1_with_and_e2_against_the_lookback_move(self):
        close = np.array([100, 101, 102, 101, 99, 99, 100.0])
        d1 = lb.entry_directions("E1", close, symbol_index=0, lookback=3)
        d2 = lb.entry_directions("E2", close, symbol_index=0, lookback=3)
        # t=3: 101 vs 100 up; t=4: 99 vs 101 down; t=5: 99 vs 102 down; t=6: 100 vs 101 down
        self.assertEqual(d1.tolist(), [0, 0, 0, 1, -1, -1, -1])
        self.assertEqual(d2.tolist(), [0, 0, 0, -1, 1, 1, 1])

    def test_e1_exactly_zero_move_is_no_trade(self):
        close = np.array([100, 100, 100, 100.0, 100.0])
        self.assertEqual(lb.entry_directions("E1", close, symbol_index=0, lookback=3).tolist(), [0, 0, 0, 0, 0])

    def test_e1_requires_the_exact_24h_earlier_bar(self):
        close = np.arange(100.0, 100.0 + 3000.0)
        close[560] = np.nan  # a gap
        d = lb.entry_directions("E1", close, symbol_index=0)  # lookback 1440
        self.assertEqual(int(d[1439]), 0)
        self.assertEqual(int(d[1440]), 1)
        self.assertEqual(int(d[560 + 1440]), 0)  # the bar 24h earlier is missing: no trade until available
        self.assertEqual(int(d[560 + 1440 + 1]), 1)
        d2 = lb.entry_directions("E2", close, symbol_index=0)
        self.assertEqual(int(d2[560 + 1440]), 0)
        self.assertEqual(int(d2[2500]), -1)

    def test_e0_is_deterministic_and_seeded_per_symbol(self):
        close = np.ones(5000)
        a = lb.entry_directions("E0", close, symbol_index=3, seed=20261013)
        b = lb.entry_directions("E0", close, symbol_index=3, seed=20261013)
        c = lb.entry_directions("E0", close, symbol_index=4, seed=20261013)
        self.assertTrue(np.array_equal(a, b))
        self.assertFalse(np.array_equal(a, c))
        self.assertEqual(set(a.tolist()), {-1, 1})
        self.assertAlmostEqual(float((a > 0).mean()), 0.5, delta=0.05)


class AccountTests(unittest.TestCase):
    def test_margin_is_two_percent_of_equity_and_closes_settle_before_opens(self):
        # A: open 0 close 10, net +0.5 ; B opens at 10 (the same minute A closes), net -1.0, closes 20
        res = lb.simulate_account(np.array([0, 10]), np.array([10, 20]), np.array([0.5, -1.0]), n_days=2,
                                  sample_start_idx=0, minutes_per_day=15)
        eq_a = 1.0 + 0.02 * 0.5
        eq_b = eq_a - 0.02 * eq_a * 1.0  # B's margin is 2% of the equity AFTER A settled
        self.assertAlmostEqual(res["final_equity"], eq_b)
        self.assertAlmostEqual(res["daily_equity"][0], eq_a)  # day 0 ends at minute 15
        self.assertAlmostEqual(res["daily_equity"][1], eq_b)  # day 1 ends at minute 30

    def test_overlapping_positions_use_equity_at_their_own_open(self):
        res = lb.simulate_account(np.array([0, 5]), np.array([10, 20]), np.array([1.0, 1.0]), n_days=1,
                                  sample_start_idx=0, minutes_per_day=30)
        # both opened at equity 1.0 (A has not settled when B opens): 2% each
        self.assertAlmostEqual(res["final_equity"], 1.0 + 0.02 + 0.02)

    def test_first_below_half_and_drawdown(self):
        net = np.array([-1.0] * 40)
        o = np.arange(40) * 10
        res = lb.simulate_account(o, o + 5, net, n_days=40, sample_start_idx=0, minutes_per_day=10)
        self.assertAlmostEqual(res["final_equity"], 0.98 ** 40)
        self.assertIsNotNone(res["first_below_half_day"])
        self.assertLess(res["max_drawdown"], -0.5)

    def test_daily_returns_roundtrip(self):
        r = lb.daily_returns(np.array([1.1, 0.99]))
        self.assertAlmostEqual(r[0], 0.1)
        self.assertAlmostEqual(r[1], 0.99 / 1.1 - 1)


class StatsTests(unittest.TestCase):
    def test_break_even_arithmetic(self):
        # L=10, tp 10%: win 0.1-0.014, loss 0.5+0.014
        self.assertAlmostEqual(lb.break_even_win_rate(10, 0.10, "S2"), 0.514 / (0.086 + 0.514))
        # S1 L=20, tp 20%: win 0.2-0.028, loss 1+0.1+0.014 (liquidation fee + entry half of the fee)
        self.assertAlmostEqual(lb.break_even_win_rate(20, 0.20, "S1"), 1.114 / (0.172 + 1.114))
        self.assertAlmostEqual(lb.driftless_fair_win_rate(10, 0.10, "S2"), 0.05 / 0.06)
        self.assertAlmostEqual(lb.driftless_fair_win_rate(10, 0.10, "S1"), 0.095 / (0.095 + 0.01))

    def test_bootstrap_is_deterministic_and_brackets_the_mean(self):
        rng = np.random.default_rng(1)
        cnt = rng.integers(1, 20, size=200).astype(float)
        s = cnt * 0.05 + rng.normal(0, 0.5, size=200)
        a = lb.bootstrap_ev(s, cnt)
        b = lb.bootstrap_ev(s, cnt)
        self.assertEqual(a, b)
        self.assertLess(a["lo"], a["ev"])
        self.assertGreater(a["hi"], a["ev"])
        self.assertLess(a["p_one_sided"], 0.05)
        neg = lb.bootstrap_ev(-s, cnt)
        self.assertGreater(neg["p_one_sided"], 0.95)

    def test_ruin_summary_is_deterministic(self):
        r = np.random.default_rng(2).normal(0.0, 0.01, size=400)
        a = lb.ruin_summary(r, paths=300)
        b = lb.ruin_summary(r, paths=300)
        self.assertEqual(a, b)
        self.assertEqual(a["ruin_probability"], 0.0)
        bad = lb.ruin_summary(np.full(400, -0.05), paths=300)
        self.assertEqual(bad["ruin_probability"], 1.0)
        self.assertEqual(bad["median_days_to_ruin"], 14.0)  # 0.95**14 < 0.5

    def test_bh_reading_on_a_toy_family(self):
        def cell(name, p, lo1, lo2, ruin):
            return {"cell": name, "ev_bootstrap": {"full": {"p_one_sided": p}, "half1": {"lo": lo1},
                                                    "half2": {"lo": lo2}}, "account": {"ruin": {"ruin_probability": ruin}}}
        cells = [cell("A", 0.001, 0.1, 0.2, 0.01),   # viable
                 cell("B", 0.001, 0.1, -0.2, 0.01),  # second half lower bound negative
                 cell("C", 0.001, 0.1, 0.2, 0.30),   # ruin too high
                 cell("D", 0.9, 0.1, 0.2, 0.0),      # BH does not reject
                 {"cell": "E", "trades": 0}]
        out = lb.viability_reading(cells)
        self.assertEqual(out["viable_cells"], ["A"])
        self.assertTrue(out["cells"]["B"]["bh_reject"])
        self.assertFalse(out["cells"]["B"]["worth_separate_trial"])
        self.assertFalse(out["cells"]["C"]["ruin_ok"])
        self.assertFalse(out["cells"]["D"]["bh_reject"])

    def test_72_cells(self):
        cells = lb.all_cells()
        self.assertEqual(len(cells), 72)
        self.assertEqual(len({c.name for c in cells}), 72)


class DataTests(unittest.TestCase):
    def test_stale_tail_is_found_only_for_a_trailing_frozen_run(self):
        n = 5000
        c = 100.0 + np.sin(np.arange(n))
        h, lo = c + 0.1, c - 0.1
        self.assertIsNone(bd.stale_tail_start(h, lo, c))
        c2, h2, l2 = c.copy(), h.copy(), lo.copy()
        c2[3000:] = h2[3000:] = l2[3000:] = 77.0
        self.assertEqual(bd.stale_tail_start(h2, l2, c2), 3000)
        # a frozen run shorter than a day is left alone
        c3, h3, l3 = c.copy(), h.copy(), lo.copy()
        c3[4500:] = h3[4500:] = l3[4500:] = 77.0
        self.assertIsNone(bd.stale_tail_start(h3, l3, c3))
        # a frozen run in the middle is not a tail
        c4, h4, l4 = c.copy(), h.copy(), lo.copy()
        c4[1000:2500] = h4[1000:2500] = l4[1000:2500] = 77.0
        self.assertIsNone(bd.stale_tail_start(h4, l4, c4))

    def test_minute_csv_grid_index_is_bar_end(self):
        row = "1704067200000,1,2,0.5,1.5,10,1704067259999,10,5,1,1,0\n"  # 2024-01-01 00:00 open
        frame = bd.parse_minute_csv(row)
        self.assertEqual(int(frame.index[0]), bd.SAMPLE_START_IDX + 1)  # the bar ends at 00:01
        us = "1767225600000000,1,2,0.5,1.5,10,1767225659999999,10,5,1,1,0\n"  # microseconds from 2025/2026
        self.assertEqual(int(bd.parse_minute_csv(us).index[0]) - bd.SAMPLE_START_IDX,
                         (1767225600 - 1704067200) // 60 + 1)


class ReviewFixTests(unittest.TestCase):
    def test_time_stop_on_a_later_bar_checks_levels_on_that_bar(self):
        # L10 S1 long, entry 100 at bar 0; liquidation at 90.5; bar 4 (the time-stop bar) is missing
        nan = np.nan
        c = [100.0, 100.0, 100.0, 100.0, nan, 80.0, 80.0]
        h = [100.0, 100.0, 100.0, 100.0, nan, 100.0, 80.0]
        lo = [100.0, 100.0, 100.0, 100.0, nan, 70.0, 80.0]
        t = walk(h, lo, c, only_first(7), stop="S1", max_hold=4)
        self.assertEqual((t.close_idx.tolist(), t.code.tolist()), ([5], [lb.CODE_LIQ]))
        self.assertEqual(t.ambiguous.tolist(), [0])
        e = lb.trade_economics(t, np.asarray(c), 10, 0.10, np.zeros(0, dtype=np.int64), np.zeros(0), "S1")
        self.assertAlmostEqual(e["net"][0], -1.05 - 0.007)

    def test_mirror_s2_stop_on_the_later_bar_and_short_tp(self):
        nan = np.nan
        c = [100.0, 100.0, 100.0, 100.0, nan, 94.0, 94.0]
        h = [100.0, 100.0, 100.0, 100.0, nan, 100.0, 94.0]
        lo = [100.0, 100.0, 100.0, 100.0, nan, 93.0, 94.0]
        t = walk(h, lo, c, only_first(7), stop="S2", max_hold=4)
        self.assertEqual(t.code.tolist(), [lb.CODE_STOP])
        # short: take-profit touched on the later bar
        c = [100.0, 100.0, 100.0, 100.0, nan, 99.0, 99.0]
        h = [100.0, 100.0, 100.0, 100.0, nan, 100.0, 99.0]
        lo = [100.0, 100.0, 100.0, 100.0, nan, 98.5, 99.0]
        t = walk(h, lo, c, only_first(7, -1), stop="S2", max_hold=4)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist()), ([lb.CODE_TP], [5]))

    def test_short_s1_liquidation(self):
        c = [100.0] * 4
        t = walk([100, 100, 109.6, 100], c, c, only_first(4, -1), stop="S1", max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_LIQ])
        self.assertAlmostEqual(econ(t, c)["net"][0], -1.057)
        t = walk([100, 100, 109.4, 100], c, c, only_first(4, -1), stop="S1", max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_TIME])

    def test_half_split_boundary(self):
        n = lb.half_split_day()
        self.assertEqual(n, 501)
        import pandas as pd
        self.assertEqual(pd.Timestamp("2024-01-01") + pd.Timedelta(days=n - 1), pd.Timestamp("2025-05-15"))
        # exit day 500 is the last day of half 1, day 501 the first of half 2 (2025-05-16)
        day_sum = np.zeros(1004)
        day_cnt = np.zeros(1004)
        day_cnt[[500, 501]] = 1.0
        day_sum[[500, 501]] = [1.0, -1.0]
        from types import SimpleNamespace  # noqa: F401
        net = np.array([1.0, -1.0])
        econ_ = {"net": net, "fee": np.zeros(2), "funding": np.zeros(2), "gross": net}
        out = lb.cell_statistics(lb.Cell("E0", 10, 0.1, "S2"), econ_, np.array([0, 1], dtype=np.int8),
                                 np.zeros(2, dtype=np.int8), np.array([500, 501]), 1004, split_day=n)
        self.assertEqual(out["ev_bootstrap"]["half1"]["trades"], 1)
        self.assertEqual(out["ev_bootstrap"]["half2"]["trades"], 1)
        self.assertEqual(out["ev_bootstrap"]["half1"]["ev"], 1.0)

    def test_load_symbol_trims_the_stale_tail(self):
        n = 6000
        c = 100.0 + np.sin(np.arange(n))
        h, lo = c + 0.1, c - 0.1
        c[4000:] = h[4000:] = lo[4000:] = 55.0
        with tempfile.TemporaryDirectory() as tmp:
            np.save(Path(tmp) / "XUSDT.npy", np.stack([h, lo, c]))
            np.savez(Path(tmp) / "XUSDT_funding.npz", idx=np.zeros(0, dtype=np.int64), rate=np.zeros(0))
            hh, ll, cc, _, _ = bd.load_symbol("XUSDT", Path(tmp), mmap=False)
            self.assertTrue(np.isnan(cc[4000:]).all() and np.isnan(hh[4000:]).all())
            self.assertFalse(np.isnan(cc[:4000]).any())
            _, _, c_raw, _, _ = bd.load_symbol("XUSDT", Path(tmp), mmap=False, trim_stale=False)
            self.assertFalse(np.isnan(c_raw).any())

    def test_four_hour_funding_cadence(self):
        c = [100.0] * 30
        t = walk(c, c, c, only_first(30, 1), max_hold=25)
        # settlements every 4 'units' inside (0, 25]: 4, 8, ..., 24 -> six settlements
        f_idx = list(range(4, 40, 4))
        e = econ(t, c, f_idx=f_idx, f_rate=[0.0001] * len(f_idx))
        self.assertAlmostEqual(e["funding"][0], 10 * 0.0001 * 6)

    def test_manifest_digests_detect_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            c = 100.0 + np.sin(np.arange(3000))
            np.save(d / "XUSDT.npy", np.stack([c + 1, c - 1, c]))
            np.savez(d / "XUSDT_funding.npz", idx=np.zeros(0, dtype=np.int64), rate=np.zeros(0))
            (d / "manifest.json").write_text('{"symbols": [{"symbol": "XUSDT"}]}', encoding="utf-8")
            bd.update_manifest_digests(d)
            bd.verify_manifest_digests(d, ["XUSDT"])
            np.save(d / "XUSDT.npy", np.stack([c + 2, c - 1, c]))
            with self.assertRaises(bd.archive.ArchiveError):
                bd.verify_manifest_digests(d, ["XUSDT"])


class WriteOnceTests(unittest.TestCase):
    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result_v1.json"
            lb.write_result_once(path, {"a": 1})
            self.assertTrue(path.exists())
            with self.assertRaises(FileExistsError):
                lb.write_result_once(path, {"a": 2})
            self.assertIn('"a": 1', path.read_text(encoding="utf-8"))


class DriftlessSanityTests(unittest.TestCase):
    def test_random_walk_ev_is_about_minus_costs_in_every_cell(self):
        rng = np.random.default_rng(7)
        n = 120_000
        vol = 0.0002
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, vol, size=n)))
        open_ = np.concatenate([[100.0], close[:-1]])
        wick = np.abs(rng.normal(0.0, vol * 0.3, size=(2, n)))
        high = np.maximum(open_, close) * (1 + wick[0])
        low = np.minimum(open_, close) * (1 - wick[1])
        direction = lb.entry_directions("E0", close, symbol_index=0)
        for cell in lb.all_cells():
            if cell.entry != "E0":
                continue
            t = lb.walk_bracket(high, low, close, direction, cell.leverage, cell.tp, cell.stop, start_idx=1440)
            self.assertGreater(len(t), 20, cell.name)
            e = lb.trade_economics(t, close, cell.leverage, cell.tp, np.zeros(0, dtype=np.int64), np.zeros(0))
            se = e["net"].std() / np.sqrt(len(t))
            self.assertLess(e["net"].mean(), 4 * se, cell.name)  # no free lunch
            # EV is within a few standard errors of -(mean cost); conservative same-bar rule only pushes it lower
            self.assertGreater(e["net"].mean(), -e["fee"].mean() - 6 * se - 0.03, cell.name)


if __name__ == "__main__":
    unittest.main()
