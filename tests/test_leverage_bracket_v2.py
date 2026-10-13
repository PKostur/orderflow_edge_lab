"""Leverage bracket v2 (synthetic, offline): F2 maker take-profit, 168h time stop, low leverage, ruin-at-zero, daily-return
guards, v1 bit-identity, sample boundaries, BH reading, data safeguards and the runner's refusals."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from orderflow_edge_lab import leverage_bracket as lb
from orderflow_edge_lab import leverage_bracket_data as bd
from orderflow_edge_lab import leverage_bracket_v2 as lb2
from orderflow_edge_lab import leverage_bracket_v2_data as bd2

ROOT = Path(__file__).resolve().parents[1]


def walk2(h, lo, c, side=1, leverage=10, tp=0.10, stop="S2", through=lb2.THROUGH, **kw):
    n = len(c)
    d = np.zeros(n, dtype=np.int8)
    d[0] = side
    kw.setdefault("start_idx", 0)
    kw.setdefault("max_hold", n - 1)
    return lb2.walk_bracket_v2(h, lo, c, d, leverage, tp, stop, through=through, **kw)


def econ2(t, c, leverage=10, tp=0.10, stop=None, fee="F2", f_idx=None, f_rate=None):
    return lb2.trade_economics_v2(t, np.asarray(c, dtype=float), leverage, tp,
                                  np.zeros(0, dtype=np.int64) if f_idx is None else np.asarray(f_idx),
                                  np.zeros(0) if f_rate is None else np.asarray(f_rate), stop, fee)


FLAT = [100.0] * 5


class F2FillTests(unittest.TestCase):
    # L=10, tp 10% of margin = 1.0% move: take-profit price 101.0, through-fill threshold 101.01; S2 stop 95.0

    def test_through_fill_long_pays_maker_exit(self):
        t = walk2([100, 100, 101.02, 100, 100], [100, 100, 100, 100, 100], FLAT)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist(), t.touch_only.tolist()), ([lb.CODE_TP], [2], [0]))
        e = econ2(t, FLAT)
        self.assertAlmostEqual(e["fee"][0], 0.0009 * 10)  # entry 7 bps + maker 2 bps, on notional
        self.assertAlmostEqual(e["net"][0], 0.10 - 0.009)

    def test_touch_only_does_not_fill_and_exact_touch_does_not_either(self):
        for high in (101.0, 101.005, 101.0099):
            t = walk2([100, 100, high, 100, 100], [100] * 5, FLAT)
            self.assertEqual(t.code.tolist(), [lb.CODE_TIME], high)  # still open: closes at the time stop
            self.assertEqual(t.touch_only.tolist(), [1])

    def test_f1_fills_on_a_touch_as_in_v1(self):
        t = walk2([100, 100, 101.0, 100, 100], [100] * 5, FLAT, through=0.0)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist()), ([lb.CODE_TP], [2]))
        self.assertAlmostEqual(econ2(t, FLAT, fee="F1")["net"][0], 0.10 - 0.014)

    def test_short_through_fill_and_touch_only(self):
        # short take-profit 99.0, threshold 99.0 * 0.9999 = 98.9901
        t = walk2([100] * 5, [100, 100, 98.98, 100, 100], FLAT, side=-1)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist()), ([lb.CODE_TP], [2]))
        self.assertAlmostEqual(econ2(t, FLAT)["net"][0], 0.091)
        t = walk2([100] * 5, [100, 100, 98.995, 100, 100], FLAT, side=-1)
        self.assertEqual((t.code.tolist(), t.touch_only.tolist()), ([lb.CODE_TIME], [1]))

    def test_touch_only_position_later_hits_the_stop(self):
        c = [100.0] * 6
        t = walk2([100, 100, 101.005, 100, 100, 100], [100, 100, 100, 100, 94.9, 100], c)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist(), t.touch_only.tolist()), ([lb.CODE_STOP], [4], [1]))
        e = econ2(t, c)
        self.assertAlmostEqual(e["net"][0], -0.5 - 0.014)  # stop exits are taker 7 bps both sides

    def test_touch_only_position_later_fills_on_a_through_bar(self):
        c = [100.0] * 6
        t = walk2([100, 100, 101.005, 100, 101.5, 100], [100] * 6, c)
        self.assertEqual((t.code.tolist(), t.close_idx.tolist(), t.touch_only.tolist()), ([lb.CODE_TP], [4], [1]))

    def test_touch_only_then_time_stop_is_taker_and_gross_slack_is_accepted(self):
        # touch bar then a close between the take-profit price and the through threshold (101.005): gross 10.05% > tp
        c = [100.0, 100.0, 100.0, 101.005]
        h = [100.0, 100.0, 101.005, 101.005]
        t = walk2(h, [100.0] * 4, c, max_hold=3)
        self.assertEqual(t.code.tolist(), [lb.CODE_TIME])
        e = econ2(t, c, stop="S2")  # must not trip the time-stop-inside-levels assertion
        self.assertAlmostEqual(e["gross"][0], 0.1005)
        self.assertAlmostEqual(e["fee"][0], 0.014)
        with self.assertRaises(AssertionError):  # F1 keeps the strict assertion
            lb2.trade_economics_v2(t, np.asarray(c), 10, 0.10, np.zeros(0, dtype=np.int64), np.zeros(0), "S2", "F1")

    def test_adverse_first_rule_and_ambiguity_with_through(self):
        c = [100.0] * 4
        t = walk2([100, 100, 101.5, 100], [100, 100, 94.0, 100], c)  # both levels, through
        self.assertEqual((t.code.tolist(), t.ambiguous.tolist()), ([lb.CODE_STOP], [1]))
        t = walk2([100, 100, 101.005, 100], [100, 100, 94.0, 100], c)  # only a touch of the take-profit price
        self.assertEqual((t.code.tolist(), t.ambiguous.tolist()), ([lb.CODE_STOP], [0]))

    def test_liquidation_and_stop_fees_are_unchanged_in_f2(self):
        c = [100.0] * 4
        t = walk2([100] * 4, [100, 100, 90.0, 100], c, stop="S1")
        self.assertEqual(t.code.tolist(), [lb.CODE_LIQ])
        self.assertAlmostEqual(econ2(t, c, stop="S1")["net"][0], -1.057)
        self.assertAlmostEqual(econ2(t, c, stop="S1", fee="F1")["net"][0], -1.057)

    def test_landing_bar_after_a_gap_uses_the_through_rule(self):
        nan = np.nan
        for high, expect in ((101.02, lb.CODE_TP), (101.005, lb.CODE_TIME)):
            c = [100.0, 100.0, 100.0, nan, 100.5, 100.0]
            h = [100.0, 100.0, 100.0, nan, high, 100.0]
            lo = [100.0, 100.0, 100.0, nan, 100.0, 100.0]
            t = walk2(h, lo, c, max_hold=3)
            self.assertEqual((t.code.tolist(), t.close_idx.tolist()), ([expect], [4]))

    def test_break_even_f2_uses_the_cheaper_take_profit(self):
        self.assertAlmostEqual(lb2.break_even_win_rate(10, 0.10, "S2", "F2"), 0.514 / (0.091 + 0.514))
        self.assertAlmostEqual(lb2.break_even_win_rate(10, 0.10, "S2", "F1"), lb.break_even_win_rate(10, 0.10, "S2"))
        self.assertAlmostEqual(lb2.break_even_win_rate(2, 0.20, "S1", "F2"), (1 + 0.0057 * 2) / (0.2 - 0.0018 + 1.0114))


class TimeStopAndLeverageTests(unittest.TestCase):
    def test_168h_time_stop_closes_at_10080_bars_and_24h_at_1440(self):
        n = 10100
        c = np.full(n, 100.0)
        d = np.zeros(n, dtype=np.int8)
        d[0] = 1
        for hours, bar in ((24, 1440), (168, 10080)):
            t = lb2.walk_bracket_v2(c, c, c, d, 5, 0.10, "S2", start_idx=0, max_hold=hours * 60, through=lb2.THROUGH)
            self.assertEqual((t.code.tolist(), t.close_idx.tolist()), ([lb.CODE_TIME], [bar]), hours)
        cell = lb2.Cell2("E0", 5, 0.10, "S2", 168, "F2")
        self.assertEqual(cell.max_hold, 10080)
        self.assertEqual(cell.through, lb2.THROUGH)
        self.assertEqual(lb2.Cell2("E0", 5, 0.10, "S2", 24, "F1").through, 0.0)

    def test_168h_trade_unfinished_at_the_data_end_is_dropped(self):
        c = np.full(10000, 100.0)
        d = np.zeros(10000, dtype=np.int8)
        d[0] = 1
        t = lb2.walk_bracket_v2(c, c, c, d, 5, 0.10, "S2", start_idx=0, max_hold=10080, through=0.0)
        self.assertEqual(len(t), 0)

    def test_low_leverage_liquidation_level(self):
        self.assertAlmostEqual(lb.adverse_distance(2, "S1"), 0.5 - 0.005)
        self.assertAlmostEqual(lb.adverse_distance(2, "S2"), 0.25)
        c = [100.0] * 4
        t = walk2([100] * 4, [100, 100, 50.6, 100], c, leverage=2, stop="S1", through=0.0)
        self.assertEqual(t.code.tolist(), [lb.CODE_TIME])  # 50.6 is above the liquidation price 50.5
        t = walk2([100] * 4, [100, 100, 50.4, 100], c, leverage=2, stop="S1", through=0.0)
        self.assertEqual(t.code.tolist(), [lb.CODE_LIQ])
        self.assertAlmostEqual(econ2(t, c, leverage=2, stop="S1", fee="F1")["net"][0], -(1 + 0.0057 * 2))
        t = walk2([100] * 4, [100, 100, 74.9, 100], c, leverage=2, stop="S2", through=0.0)
        self.assertEqual(t.code.tolist(), [lb.CODE_STOP])
        self.assertAlmostEqual(econ2(t, c, leverage=2, stop="S2", fee="F1")["net"][0], -0.5 - 0.0028)

    def test_288_cells(self):
        cells = lb2.all_cells()
        self.assertEqual(len(cells), 288)
        self.assertEqual(len({c.name for c in cells}), 288)
        self.assertEqual({c.leverage for c in cells}, {2, 3, 5, 10})
        self.assertEqual({c.time_hours for c in cells}, {24, 168})


class RuinTests(unittest.TestCase):
    def test_equity_at_or_below_zero_is_ruin_with_its_day(self):
        # margin 100% of equity, loss 150% of margin -> equity -0.5 at the first close (minute 25, day 2)
        res = lb2.simulate_account_v2(np.array([0, 30]), np.array([25, 40]), np.array([-1.5, 0.5]), n_days=6,
                                      sample_start_idx=0, minutes_per_day=10, margin_fraction=1.0)
        self.assertTrue(res["ruined"])
        self.assertEqual(res["ruin_day"], 2)
        self.assertEqual(res["trades"], 2)
        self.assertEqual(res["daily_equity"].tolist(), [1.0, 1.0, 0.0, 0.0, 0.0, 0.0])  # clipped at 0, stays ruined
        self.assertEqual(res["final_equity"], 0.0)
        out = lb2.ruin_statistic(res, ruin_indices=None)
        self.assertEqual((out["ruin_probability"], out["historical_ruin"], out["ruin_day"]), (1.0, True, 2))
        exact = lb2.simulate_account_v2(np.array([0]), np.array([5]), np.array([-1.0]), n_days=1, sample_start_idx=0,
                                        minutes_per_day=10, margin_fraction=1.0)
        self.assertTrue(exact["ruined"])  # exactly zero counts

    def test_a_positive_path_uses_the_bootstrap(self):
        o = np.arange(40) * 10
        res = lb2.simulate_account_v2(o, o + 5, np.full(40, 0.01), n_days=40, sample_start_idx=0, minutes_per_day=10)
        self.assertFalse(res["ruined"])
        out = lb2.ruin_statistic(res, ruin_indices=None)
        self.assertFalse(out["historical_ruin"])
        self.assertEqual(out["ruin_probability"], 0.0)
        self.assertIsNone(out["ruin_day"])

    def test_below_half_without_zero_is_not_historical_ruin(self):
        o = np.arange(40) * 10
        res = lb2.simulate_account_v2(o, o + 5, np.full(40, -1.0), n_days=40, sample_start_idx=0, minutes_per_day=10)
        self.assertFalse(res["ruined"])
        self.assertIsNotNone(res["first_below_half_day"])

    def test_account_matches_v1_when_not_ruined(self):
        rng = np.random.default_rng(3)
        n = 300
        o = np.sort(rng.integers(0, 4000, size=n))
        cl = o + rng.integers(1, 60, size=n)
        net = rng.normal(0.0, 0.3, size=n)
        a = lb.simulate_account(o, cl, net, n_days=40, sample_start_idx=100, minutes_per_day=100)
        b = lb2.simulate_account_v2(o, cl, net, n_days=40, sample_start_idx=100, minutes_per_day=100)
        self.assertFalse(b["ruined"])
        for key in a:
            if isinstance(a[key], np.ndarray):
                np.testing.assert_array_equal(a[key], b[key])
            else:
                self.assertEqual(a[key], b[key], key)

    def test_daily_return_guards(self):
        with np.errstate(all="raise"):
            r = lb2.daily_returns_v2(np.array([0.5, 0.0, 0.3, 0.0]))
            self.assertEqual(r.tolist(), [-0.5, -1.0, 0.0, -1.0])
            r = lb2.daily_returns_v2(np.array([-0.2, 0.5, 0.0]))  # negative equity clipped to 0; no division by it
            self.assertEqual(r.tolist(), [-1.0, 0.0, -1.0])
            r = lb2.daily_returns_v2(np.array([1.1, 0.99]))
        np.testing.assert_allclose(r, lb.daily_returns(np.array([1.1, 0.99])))
        self.assertEqual(len(lb2.daily_returns_v2(np.zeros(0))), 0)


def _series(n, seed, vol=0.002):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, vol, size=n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    wick = np.abs(rng.normal(0.0, vol * 0.5, size=(2, n)))
    high = np.maximum(open_, close) * (1 + wick[0])
    low = np.minimum(open_, close) * (1 - wick[1])
    return high, low, close


class V1IdentityTests(unittest.TestCase):
    def test_walk_and_economics_equal_v1_for_f1_24h(self):
        for seed in (1, 2):
            high, low, close = _series(9000, seed)
            close = close.copy()
            close[2500:2520] = high[2500:2520] = low[2500:2520] = np.nan  # a gap
            for entry in ("E0", "E1", "E2"):
                d = lb.entry_directions(entry, np.nan_to_num(close, nan=100.0), symbol_index=seed)
                for lev, tp, stop in ((10, 0.10, "S2"), (10, 0.20, "S1"), (20, 0.15, "S2"), (50, 0.10, "S1")):
                    a = lb.walk_bracket(high, low, close, d, lev, tp, stop, start_idx=1440)
                    b = lb2.walk_bracket_v2(high, low, close, d, lev, tp, stop, start_idx=1440,
                                            max_hold=lb.MAX_HOLD, through=0.0)
                    self.assertGreater(len(a), 3)
                    for f in ("open_idx", "close_idx", "side", "code", "ambiguous"):
                        np.testing.assert_array_equal(getattr(a, f), getattr(b, f))
                    f_idx = np.arange(480, 9000, 480)
                    f_rate = np.full(len(f_idx), 0.0001)
                    ea = lb.trade_economics(a, close, lev, tp, f_idx, f_rate, stop)
                    eb = lb2.trade_economics_v2(b, close, lev, tp, f_idx, f_rate, stop, "F1")
                    for key in ea:
                        np.testing.assert_array_equal(ea[key], eb[key])

    def test_summarised_cell_equals_v1_through_the_v2_path(self):
        n, start = 12000, 1440
        n_days = (n - 1 - start) // 1440
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for k in range(2):
                h, lo, c = _series(n, 10 + k)
                np.save(d / f"S{k}USDT.npy", np.stack([h, lo, c]))
                np.savez(d / f"S{k}USDT_funding.npz", idx=np.arange(480, n, 480).astype(np.int64),
                         rate=np.full(len(np.arange(480, n, 480)), 0.0001))
            syms = ["S0USDT", "S1USDT"]
            for lev, tp, stop in ((10, 0.10, "S2"), (20, 0.20, "S1")):
                v1 = lb.run_cell(lb.Cell("E0", lev, tp, stop), d, syms, n_days=n_days, start_idx=start)
                v2 = lb2.run_cell_v2(lb2.Cell2("E0", lev, tp, stop, 24, "F1"), d, syms,
                                     {"start_idx": start, "n_days": n_days, "split_day": lb.half_split_day()})
                self.assertGreater(v1["trades"], 20)
                self.assertEqual(v2["cell"], f"E0_L{lev}_TP{int(tp * 100)}_{stop}_T24_F1")
                for key, val in v1.items():
                    if key == "cell":
                        continue
                    if key == "account":
                        for k2, v_ in val.items():
                            if k2 == "ruin":
                                for k3, w in v_.items():
                                    self.assertEqual(w, v2["account"]["ruin"][k3], k3)
                            else:
                                self.assertEqual(v_, v2["account"][k2], k2)
                    else:
                        self.assertEqual(val, v2[key], key)


class SampleTests(unittest.TestCase):
    def test_primary_grid_and_halves(self):
        self.assertEqual(bd2.SAMPLE_START_IDX, 1440)
        self.assertEqual(bd2.PRIMARY_DAYS, 1095)  # 2021, 2022, 2023: 365 days each
        self.assertEqual(bd2.GRID_LEN, 1440 + 1095 * 1440 + 1)
        s = bd2.primary_sample()
        self.assertEqual((s["start_idx"], s["n_days"], s["split_day"]), (1440, 1095, 546))
        self.assertEqual(pd.Timestamp("2021-01-01") + pd.Timedelta(days=545), pd.Timestamp("2022-06-30"))
        self.assertEqual(pd.Timestamp("2021-01-01") + pd.Timedelta(days=1094), pd.Timestamp("2023-12-31"))
        c = bd2.consistency_sample()
        self.assertEqual((c["start_idx"], c["n_days"]), (bd.SAMPLE_START_IDX, 1004))

    def test_exit_day_assignment_at_the_boundaries(self):
        start = bd2.SAMPLE_START_IDX
        day = lambda i: (i - start - 1) // 1440  # noqa: E731  (the formula used by summarize_cell_v2)
        self.assertEqual(day(start + 1), 0)  # bar ending 2021-01-01 00:01
        self.assertEqual(day(start + 1440), 0)  # bar ending 2021-01-02 00:00 is still 2021-01-01's last bar
        self.assertEqual(day(start + 1441), 1)
        self.assertEqual(day(bd2.GRID_LEN - 1), 1094)  # last bar: 2023-12-31
        split = bd2.primary_sample()["split_day"]
        first_h2_bar = start + split * 1440 + 1  # bar ending 2022-07-01 00:01
        self.assertEqual(day(first_h2_bar), split)
        self.assertEqual(day(first_h2_bar - 1), split - 1)

    def test_entries_start_at_the_first_bar_with_24h_of_history(self):
        n = 5000
        h, lo, c = _series(n, 5)
        d = lb.entry_directions("E0", c, symbol_index=0)
        t = lb2.walk_bracket_v2(h, lo, c, d, 10, 0.10, "S2", start_idx=1440, max_hold=1440, through=0.0)
        self.assertEqual(int(t.open_idx[0]), 1440)
        e1 = lb.entry_directions("E1", c, symbol_index=0)
        self.assertEqual(int(e1[1439]), 0)  # no 24h history before bar 1440

    def test_parse_minute_csv_maps_to_the_v2_grid(self):
        row = "1609459200000,1,2,0.5,1.5,10,1609459259999,10,5,1,1,0\n"  # 2021-01-01 00:00 open
        self.assertEqual(int(bd2.parse_minute_csv(row).index[0]), bd2.SAMPLE_START_IDX + 1)
        row = "1609372800000,1,2,0.5,1.5,10,1609372859999,10,5,1,1,0\n"  # 2020-12-31 00:00 open
        self.assertEqual(int(bd2.parse_minute_csv(row).index[0]), 1)

    def test_bar_outside_the_grid_is_dropped(self):
        frame = pd.DataFrame({"open": [1.0, 1.0], "high": [2.0, 2.0], "low": [0.5, 0.5], "close": [1.5, 1.5]},
                             index=pd.Index([5, bd2.GRID_LEN + 3]))
        grid, stats = bd2.to_grid(frame)
        self.assertEqual(stats["bars"], 1)
        self.assertEqual(stats["ohlc_violations"], 0)


class ReadingTests(unittest.TestCase):
    def test_bh_reading_on_a_toy_family(self):
        def cell(name, p, lo1, lo2, ruin):
            return {"cell": name, "ev_bootstrap": {"full": {"p_one_sided": p}, "half1": {"lo": lo1},
                                                    "half2": {"lo": lo2}}, "account": {"ruin": {"ruin_probability": ruin}}}
        primary = [cell("A", 0.001, 0.1, 0.2, 0.01), cell("B", 0.001, 0.1, -0.2, 0.01),
                   cell("C", 0.001, 0.1, 0.2, 0.30), cell("D", 0.9, 0.1, 0.2, 0.0),
                   cell("F", 0.001, 0.1, 0.2, 0.0), cell("G", 0.001, 0.1, 0.2, 0.0), {"cell": "E", "trades": 0}]
        consistency = [{"cell": n, "net_ev_pct_margin_per_trade": 0.5} for n in "ABCD"]
        consistency += [{"cell": "F", "net_ev_pct_margin_per_trade": -0.1}, {"cell": "E", "trades": 0}]  # G missing
        out = lb2.viability_reading_v2(primary, consistency)
        self.assertEqual(out["viable_cells"], ["A"])
        self.assertTrue(out["cells"]["F"]["bh_reject"] and not out["cells"]["F"]["consistency_ev_positive"])
        self.assertFalse(out["cells"]["G"]["consistency_ev_positive"])
        self.assertTrue(out["cells"]["B"]["bh_reject"] and not out["cells"]["B"]["viable"])
        self.assertFalse(out["cells"]["C"]["ruin_ok"])
        self.assertFalse(out["cells"]["D"]["bh_reject"])
        self.assertEqual(out["n_cells"], 7)

    def test_p_values_use_the_full_family(self):
        def cell(name, p):
            return {"cell": name, "ev_bootstrap": {"full": {"p_one_sided": p}, "half1": {"lo": 1.0},
                                                    "half2": {"lo": 1.0}}, "account": {"ruin": {"ruin_probability": 0.0}}}
        # one small p among 288 cells does not survive BH at q = 0.10 when the rest are 1.0 (0.01 * 288 > 0.10)
        primary = [cell("A", 0.01)] + [cell(f"X{i}", 1.0) for i in range(287)]
        cons = [{"cell": "A", "net_ev_pct_margin_per_trade": 1.0}]
        out = lb2.viability_reading_v2(primary, cons)
        self.assertEqual(out["viable_cells"], [])


class DataSafeguardTests(unittest.TestCase):
    def test_float32_effect_reports_error_collapse_and_tail(self):
        rng = np.random.default_rng(0)
        c = 50000.0 * np.exp(np.cumsum(rng.normal(0, 0.001, size=5000)))
        h, lo = c * 1.0005, c * 0.9995
        eff = bd2.float32_effect(np.stack([h, lo, c]))
        self.assertLess(eff["max_rel_error"], 6.0e-8 + 1e-12)
        self.assertEqual((eff["range_collapsed_bars"], eff["high_below_low_after"]), (0, 0))
        self.assertTrue(eff["stale_tail_unchanged"])
        # float32 error is far below the smallest distances the study tests (0.01% through-fill, 1% take-profit)
        self.assertLess(eff["max_rel_error"], 1e-4 / 1000)
        h2, lo2 = c.copy(), c.copy()
        h2[10] = c[10] * (1 + 1e-9)
        lo2[10] = c[10]
        eff = bd2.float32_effect(np.stack([h2, lo2, c]))
        self.assertEqual(eff["range_collapsed_bars"], 1)
        self.assertEqual(eff["high_below_low_after"], 0)

    def test_free_space_guard(self):
        with mock.patch.object(bd2.shutil, "disk_usage", return_value=mock.Mock(free=1_200_000_000)):
            with self.assertRaises(bd2.DiskSpaceLow):
                bd2.check_free(Path("."), need=300_000_000)  # 1.2 GB - 0.3 GB < 1.0 GB
            self.assertEqual(bd2.check_free(Path("."), need=100_000_000), 1_200_000_000)

    def test_download_universe_stops_cleanly_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)

            def fake(sym, out_dir, **kw):
                if sym == "BBBUSDT":
                    raise bd2.DiskSpaceLow("free space 0.9 GB")
                h = np.stack([np.ones(5), np.ones(5), np.ones(5)]).astype(np.float32)
                np.save(out_dir / f"{sym}.npy", h)
                np.savez(out_dir / f"{sym}_funding.npz", idx=np.zeros(0, dtype=np.int64), rate=np.zeros(0))
                (out_dir / "_entries").mkdir(exist_ok=True)
                entry = {"symbol": sym, "files": [], "zip_bytes": 0, "bars": 5}
                (out_dir / "_entries" / f"{sym}.json").write_text(json.dumps(entry), encoding="utf-8")
                return entry
            with mock.patch.object(bd2, "download_symbol", side_effect=fake):
                m = bd2.download_universe(["AAAUSDT", "BBBUSDT", "CCCUSDT"], out, workers=1)
            self.assertFalse(m["complete"])
            self.assertIn("BBBUSDT", m["stopped_reason"])
            self.assertEqual([e["symbol"] for e in m["symbols"]], ["AAAUSDT"])  # CCC never started
            self.assertIn("AAAUSDT", m["array_digests"])

    def test_zip_is_deleted_after_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            key = "data/futures/um/monthly/klines/XUSDT/1m/XUSDT-1m-2021-01.zip"
            seen = []

            def fake_download(url, target, fetch=None):
                target.write_bytes(b"zip")
                target.with_name(target.name + ".CHECKSUM").write_bytes(b"c")
                return b"zip"
            with (mock.patch.object(bd2, "list_all", side_effect=lambda prefix, fetch=None: (None, [key] if "monthly" in prefix else []))
                  , mock.patch.object(bd2, "download_verified", side_effect=fake_download),
                  mock.patch.object(bd2.archive, "_month_of", side_effect=lambda k, kind: "2021-01")):
                for name, digest, _ in bd2.iter_kline_zips("XUSDT", d, free_check=lambda: seen.append(1)):
                    self.assertEqual(name, "XUSDT-1m-2021-01.zip")
                    self.assertEqual(len(digest), 64)
                self.assertEqual(list(d.iterdir()), [])
            self.assertEqual(seen, [1])

    def test_coverage_report_and_digests_on_a_float32_cache(self):
        n = 6000
        c = 100.0 + np.sin(np.arange(n))
        h, lo = c + 0.1, c - 0.1
        c[4000:] = h[4000:] = lo[4000:] = 55.0
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            np.save(d / "XUSDT.npy", np.stack([h, lo, c]).astype(np.float32))
            np.savez(d / "XUSDT_funding.npz", idx=np.zeros(0, dtype=np.int64), rate=np.zeros(0))
            np.save(d / "YUSDT.npy", np.full((3, 10), np.nan, dtype=np.float32))
            np.savez(d / "YUSDT_funding.npz", idx=np.zeros(0, dtype=np.int64), rate=np.zeros(0))
            (d / "manifest.json").write_text(json.dumps({"symbols": [{"symbol": "XUSDT"}, {"symbol": "YUSDT"}]}),
                                             encoding="utf-8")
            m = bd2.update_manifest_digests(d)
            self.assertEqual(m["stale_tail_start"]["YUSDT"], "no bars in sample")
            self.assertTrue(m["stale_tail_start"]["XUSDT"].startswith("2021-01-02 18:40"))  # grid index 4000
            bd.verify_manifest_digests(d, ["XUSDT", "YUSDT"])
            rows = bd2.coverage_report(d, ["XUSDT", "YUSDT"])
            self.assertEqual(rows[0]["bars_trimmed"], 2000)
            self.assertEqual(rows[0]["bars_tradable"], 4000)
            self.assertEqual(rows[1]["note"], "no bars in sample")
            hh, ll, cc, _, _ = bd.load_symbol("XUSDT", d, mmap=False)
            self.assertEqual(cc.dtype, np.float32)
            self.assertTrue(np.isnan(cc[4000:]).all())
            np.save(d / "XUSDT.npy", np.stack([h + 1, lo, c]).astype(np.float32))
            with self.assertRaises(bd.archive.ArchiveError):
                bd.verify_manifest_digests(d, ["XUSDT"])

    def _fill_setup(self, tmp, daily_days):
        """hlc with monthly bars everywhere except minutes 2000-2009 (day of bar-open minute index 1999..2008)."""
        n = 4000
        c = 100.0 + np.arange(n) * 0.001
        hlc = np.full((3, bd2.GRID_LEN), np.nan)  # the daily grid is full-length
        hlc[:, :n] = np.stack([c + 0.1, c - 0.1, c])
        hlc[:, 2000:2010] = np.nan
        day = str((bd2.GRID_START + pd.Timedelta(minutes=1999)).date())
        key = f"data/futures/um/daily/klines/XUSDT/1m/XUSDT-1m-{day}.zip"
        idx = np.arange(1990, 2020)
        daily = pd.DataFrame({"open": 7.0, "high": 8.0, "low": 6.0, "close": 7.0}, index=pd.Index(idx))
        # one overlapping bar differs from the monthly value (idx 1995), the rest of the overlap is identical
        for i in idx:
            if i < 2000 or i >= 2010:
                daily.loc[i] = [hlc[2, i], hlc[0, i], hlc[1, i], hlc[2, i]]
        daily.loc[1995] = [1.0, 9.0, 0.5, 1.0]
        listing = (None, [key] if daily_days else [])
        return hlc, day, daily, listing

    def test_daily_fill_fills_only_missing_minutes_and_counts_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            hlc, day, daily, listing = self._fill_setup(tmp, True)
            before = hlc.copy()
            with (mock.patch.object(bd2, "list_all", return_value=listing),
                  mock.patch.object(bd2, "download_verified", return_value=b"zip"),
                  mock.patch.object(bd2, "parse_minute_zip", return_value=daily)):
                out, info, files = bd2.fill_from_daily(hlc, "XUSDT", Path(tmp) / "z")
            self.assertEqual(info["minutes_filled"], 10)
            self.assertEqual(info["conflicting_minutes"], 1)
            self.assertEqual(info["days_filled"], [day])
            self.assertEqual(info["remaining_gaps"], [])
            self.assertEqual(out[:, 2000:2010].tolist(), [[8.0] * 10, [6.0] * 10, [7.0] * 10])
            keep = np.ones(bd2.GRID_LEN, dtype=bool)
            keep[2000:2010] = False
            np.testing.assert_array_equal(out[:, keep], before[:, keep])  # present bars never overwritten
            self.assertEqual(len(files), 1)

    def test_daily_fill_leaves_a_hole_without_a_daily_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            hlc, day, daily, listing = self._fill_setup(tmp, False)
            with mock.patch.object(bd2, "list_all", return_value=listing):
                out, info, _ = bd2.fill_from_daily(hlc, "XUSDT", Path(tmp) / "z")
            self.assertEqual((info["minutes_filled"], info["days_without_file"]), (0, [day]))
            self.assertTrue(np.isnan(out[2, 2000:2010]).all())
            self.assertEqual(info["remaining_gaps"][0]["minutes"], 10)

    def test_max_move_flag_skips_moves_across_a_gap(self):
        n = 4000
        c = np.full(n, 100.0)
        c[2000:] = 200.0  # a 100% jump ...
        h, lo = c.copy(), c.copy()
        for a in (h, lo, c):
            a[1990:2000] = np.nan  # ... only visible across a gap
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            np.save(d / "XUSDT.npy", np.stack([h, lo, c]).astype(np.float32))
            row = bd2.coverage_report(d, ["XUSDT"])[0]
        self.assertEqual(row["max_abs_1m_close_move"], 0.0)

    def test_float32_data_run_through_the_engine(self):
        high, low, close = _series(20000, 4)
        d = lb.entry_directions("E0", close, symbol_index=1)
        h32, l32, c32 = (x.astype(np.float32).astype(np.float64) for x in (high, low, close))
        for lev, stop, fee in ((10, "S2", "F2"), (5, "S1", "F2"), (3, "S2", "F1")):
            thr = lb2.THROUGH if fee == "F2" else 0.0
            a = lb2.walk_bracket_v2(high, low, close, d, lev, 0.10, stop, start_idx=1440, max_hold=1440, through=thr)
            b = lb2.walk_bracket_v2(h32, l32, c32, d, lev, 0.10, stop, start_idx=1440, max_hold=1440, through=thr)
            self.assertGreater(len(a), 10)
            for f in ("open_idx", "close_idx", "side", "code", "ambiguous", "touch_only"):
                np.testing.assert_array_equal(getattr(a, f), getattr(b, f), f)
            z = (np.zeros(0, dtype=np.int64), np.zeros(0))
            ea = lb2.trade_economics_v2(a, close, lev, 0.10, *z, stop, fee)
            eb = lb2.trade_economics_v2(b, c32, lev, 0.10, *z, stop, fee)
            np.testing.assert_allclose(ea["net"], eb["net"], atol=1e-5)  # float32 relative error 6e-8 x leverage

    def _repair_cache(self, tmp):
        d = Path(tmp)
        hlc, day, daily, listing = self._fill_setup(tmp, True)
        np.save(d / "XUSDT.npy", hlc.astype(np.float32))
        np.savez(d / "XUSDT_funding.npz", idx=np.zeros(0, dtype=np.int64), rate=np.zeros(0))
        (d / "_entries").mkdir()
        entry = {"symbol": "XUSDT", "files": [], "zip_bytes": 0, "bars": 1, "float32": {}}
        (d / "_entries" / "XUSDT.json").write_text(json.dumps(entry), encoding="utf-8")
        return d, hlc, day, daily, listing

    def test_repair_symbol_and_universe_fill_only_missing_minutes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, hlc, day, daily, listing = self._repair_cache(tmp)
            before = np.load(d / "XUSDT.npy")
            with (mock.patch.object(bd2, "list_all", return_value=listing),
                  mock.patch.object(bd2, "download_verified", return_value=b"zip"),
                  mock.patch.object(bd2, "parse_minute_zip", return_value=daily)):
                m = bd2.repair_universe(["XUSDT"], d, workers=1)
            after = np.load(d / "XUSDT.npy")
            self.assertEqual(after.dtype, np.float32)
            keep = np.ones(after.shape[1], dtype=bool)
            keep[2000:2010] = False
            np.testing.assert_array_equal(np.nan_to_num(after[:, keep], nan=-1), np.nan_to_num(before[:, keep], nan=-1))
            self.assertEqual(after[2, 2000:2010].tolist(), [7.0] * 10)
            fill = m["symbols"][0]["daily_fill"]
            self.assertEqual((fill["minutes_filled"], fill["conflicting_minutes"], fill["remaining_gaps"]), (10, 1, []))
            self.assertEqual(m["symbols"][0]["missing_inside_span"], 0)
            self.assertEqual(len(m["symbols"][0]["daily_files"]), 1)
            bd.verify_manifest_digests(d, ["XUSDT"])  # digests refreshed for the new array
            self.assertTrue(m["complete"])

    def test_repair_symbol_without_a_daily_file_leaves_the_array_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            d, hlc, day, daily, listing = self._repair_cache(tmp)
            raw = (d / "XUSDT.npy").read_bytes()
            with mock.patch.object(bd2, "list_all", return_value=(None, [])):
                entry = bd2.repair_symbol("XUSDT", d)
            self.assertEqual((d / "XUSDT.npy").read_bytes(), raw)
            self.assertEqual(entry["daily_fill"]["days_without_file"], [day])
            self.assertEqual(entry["daily_fill"]["remaining_gaps"][0]["minutes"], 10)


def _load_runner():
    spec = importlib.util.spec_from_file_location("lb2_runner", ROOT / "scripts" / "leverage_bracket_v2_study.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.runner = _load_runner()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.universe = self.root / "universe.json"
        self.universe.write_text(json.dumps({"symbols": ["AUSDT"]}), encoding="utf-8")
        self.out = self.root / "out"

    def run_main(self, **extra):
        argv = ["--out-dir", str(self.out), "--universe", str(self.universe),
                "--data-dir-primary", str(self.root / "p"), "--data-dir-consistency", str(self.root / "c")]
        # isolate from the real single-look sentinel (the committed result lives at the default OUT_DIR)
        with mock.patch.object(self.runner, "dirty_files", return_value=extra.get("dirty", [])), \
                mock.patch.object(self.runner, "OUT_DIR", self.root / "default_out"):
            return self.runner.main(argv)

    def test_refuses_when_a_result_exists(self):
        self.out.mkdir()
        (self.out / "result_v2.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.run_main()
        self.assertIn("refusing to run", str(cm.exception))
        (self.out / "result_v2.json").unlink()
        (self.out / "RESULT.md").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_main()

    def test_refuses_with_dirty_study_files(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_main(dirty=[" M scripts/leverage_bracket_v2_study.py"])
        self.assertIn("uncommitted", str(cm.exception))
        self.assertFalse(self.out.exists())

    def test_refuses_an_incomplete_primary_cache(self):
        (self.root / "p").mkdir()
        (self.root / "p" / "manifest.json").write_text(json.dumps({"complete": False, "symbols": []}), encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.run_main()
        self.assertIn("not complete", str(cm.exception))

    def test_refuses_on_a_digest_mismatch(self):
        for name in ("p", "c"):
            d = self.root / name
            d.mkdir()
            np.save(d / "AUSDT.npy", np.stack([np.ones(5), np.ones(5), np.ones(5)]).astype(np.float32))
            np.savez(d / "AUSDT_funding.npz", idx=np.zeros(0, dtype=np.int64), rate=np.zeros(0))
            (d / "manifest.json").write_text(json.dumps({"complete": True, "symbols": [{"symbol": "AUSDT"}]}),
                                             encoding="utf-8")
            bd2.update_manifest_digests(d)
        np.save(self.root / "c" / "AUSDT.npy", np.stack([np.ones(5) * 2, np.ones(5), np.ones(5)]).astype(np.float32))
        with self.assertRaises(bd.archive.ArchiveError):
            self.run_main()
        self.assertFalse(self.out.exists())

    def test_trims_must_match_amendment_1(self):
        with self.assertRaises(SystemExit):
            self.runner.check_consistency_trims({"WAVESUSDT": "2024-06-12", "SXPUSDT": "2025-12-05"})
        self.runner.check_consistency_trims({"WAVESUSDT": "2024-06-11", "SXPUSDT": "2025-12-05", "YFIIUSDT": "no bars in sample",
                                             "BTCUSDT": None})

    def test_markdown_is_built_before_any_file_is_written(self):
        for name in ("p", "c"):
            d = self.root / name
            d.mkdir()
            (d / "manifest.json").write_text(json.dumps({"complete": True}), encoding="utf-8")
        with (mock.patch.object(self.runner.bdata, "verify_manifest_digests"),
              mock.patch.object(self.runner.bdata2, "stale_tail_dates", return_value={}),
              mock.patch.object(self.runner.bdata, "stale_tail_dates", return_value={}),
              mock.patch.object(self.runner, "check_consistency_trims"),
              mock.patch.object(self.runner, "check_primary_cache"),
              mock.patch.object(self.runner, "provenance", return_value={}),
              mock.patch.object(self.runner.lb2, "run_study_v2", return_value={"viability": {"viable_cells": []}}),
              mock.patch.object(self.runner, "markdown", side_effect=RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                self.run_main()
        self.assertFalse((self.out / "result_v2.json").exists())
        self.assertFalse((self.out / "RESULT.md").exists())

    def _prov_cache(self, name):
        d = self.root / name
        d.mkdir(exist_ok=True)
        entry = {"symbol": "AUSDT", "files": [{"file": "m.zip", "sha256": "a" * 64}],
                 "daily_files": [{"file": "d.zip", "sha256": "b" * 64}], "daily_fill": {"minutes_filled": 3}}
        (d / "manifest.json").write_text(json.dumps({"symbols": [entry], "array_digests": {"AUSDT": {}}}), encoding="utf-8")
        return d

    def test_provenance_records_both_amendments_both_configs_and_daily_zips(self):
        prov = self.runner.provenance(["AUSDT"], self.runner.CONFIG, 1, {}, {}, self._prov_cache("c"), self._prov_cache("p"))
        for key in ("config_sha256", "v1_config_sha256", "amendment_sha256", "amendment_v2_sha256"):
            self.assertEqual(len(prov[key]), 64, key)
        self.assertNotEqual(prov["amendment_sha256"], prov["amendment_v2_sha256"])
        self.assertEqual(prov["primary"]["daily_zip_sha256"], {"AUSDT": [["d.zip", "b" * 64]]})
        self.assertEqual(prov["primary"]["kline_zip_sha256"], {"AUSDT": [["m.zip", "a" * 64]]})
        self.assertIn("config/leverage_bracket_study_v2_amendment_1.json", self.runner.STUDY_PATHS)
        self.assertEqual(len(prov["git_commit"]), 40)

    def test_git_failures_fail_closed(self):
        bad = mock.Mock(returncode=128, stdout="", stderr="fatal: not a git repository")
        with mock.patch.object(self.runner.subprocess, "run", return_value=bad):
            with self.assertRaises(SystemExit):
                self.runner.dirty_files()
            with self.assertRaises(SystemExit):
                self.runner.git_head()
            with self.assertRaises(SystemExit):  # main refuses before touching anything
                self.runner.main(["--out-dir", str(self.out), "--universe", str(self.universe)])
        empty = mock.Mock(returncode=0, stdout="\n", stderr="")
        with mock.patch.object(self.runner.subprocess, "run", return_value=empty):
            with self.assertRaises(SystemExit):
                self.runner.git_head()
        with mock.patch.object(self.runner.subprocess, "run", side_effect=OSError("no git")):
            with self.assertRaises(SystemExit):
                self.runner.dirty_files()
        self.assertFalse(self.out.exists())

    def test_primary_cache_constants_and_trims_are_asserted(self):
        good = {"grid_len": bd2.GRID_LEN, "sample_start_idx": bd2.SAMPLE_START_IDX, "dtype": "float32",
                "grid_start": str(bd2.GRID_START)}
        self.runner.check_primary_cache(good, {"A": None, "B": None})
        with self.assertRaises(SystemExit):
            self.runner.check_primary_cache({**good, "dtype": "float64"}, {})
        with self.assertRaises(SystemExit):
            self.runner.check_primary_cache({**good, "grid_len": 5}, {})
        with self.assertRaises(SystemExit):
            self.runner.check_primary_cache(good, {"A": "2022-01-01 00:00:00+00:00"})
        with self.assertRaises(SystemExit):
            self.runner.check_primary_cache(good, {"A": "no bars in sample"})

    def test_json_is_serialized_before_any_file_is_opened(self):
        for name in ("p", "c"):
            d = self.root / name
            d.mkdir(exist_ok=True)
            (d / "manifest.json").write_text(json.dumps({"complete": True}), encoding="utf-8")
        study = {"viability": {"viable_cells": []}, "x": object()}
        with (mock.patch.object(self.runner.bdata, "verify_manifest_digests"),
              mock.patch.object(self.runner.bdata2, "stale_tail_dates", return_value={}),
              mock.patch.object(self.runner.bdata, "stale_tail_dates", return_value={}),
              mock.patch.object(self.runner, "check_consistency_trims"),
              mock.patch.object(self.runner, "check_primary_cache"),
              mock.patch.object(self.runner, "provenance", return_value={}),
              mock.patch.object(self.runner.lb2, "run_study_v2", return_value=study),
              mock.patch.object(self.runner, "markdown", return_value="md")):
            with self.assertRaises(TypeError):
                self.run_main()
        self.assertFalse((self.out / "result_v2.json").exists())
        self.assertFalse((self.out / "RESULT.md").exists())

    def test_markdown_renders_separate_tables(self):
        def cell(name, ev, ruined):
            return {"cell": name, "trades": 10, "win_rate": 0.5, "take_profit_rate": 0.4, "break_even_win_rate": 0.6,
                    "driftless_fair_win_rate": 0.7, "liquidation_rate": 0.0, "stop_rate": 0.1, "time_stop_rate": 0.1,
                    "same_bar_ambiguous": 1, "trades_with_touch_only_bar": 2, "fees_pct_margin_per_trade": 1.0,
                    "funding_pct_margin_per_trade": 0.01, "net_ev_pct_margin_per_trade": ev,
                    "ev_bootstrap": {"full": {"lo": -0.1, "hi": 0.1}},
                    "account": {"final_equity": 0.0 if ruined else 1.0, "max_drawdown": -0.2,
                                "ruin": {"ruin_probability": 1.0 if ruined else 0.0, "ruin_day": 7 if ruined else None}}}
        prov = {"primary": {"stale_tail_trim_start": {}, "no_bars_in_sample": []},
                "consistency": {"stale_tail_trim_start": {}, "no_bars_in_sample": []}}
        res = {"viability": {"n_cells": 1, "viable_cells": [], "cells": {"P": {"q_value": 0.5}}}, "provenance": prov,
               "primary": {"cells": [cell("P", -1.0, True)]}, "consistency": {"cells": [cell("P", 0.5, False)]}}
        text = self.runner.markdown(res)
        self.assertIn("## Primary sample", text)
        self.assertIn("## Consistency check", text)
        self.assertLess(text.index("## Primary"), text.index("## Consistency"))
        self.assertIn("| 100.0 | 7 | 0.500 |", text)


if __name__ == "__main__":
    unittest.main()
