"""Offline tests (synthetic data, no network) for the near-miss paper forward watch."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock
import urllib.parse
import zipfile

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_spot_archive as bsa
from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import near_miss_forward as nmf
from orderflow_edge_lab import strategy_search_round2 as r2
from orderflow_edge_lab import trend_core_leverage as tcl

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "near_miss_forward_v1.json").read_text(encoding="utf-8"))
ROUND_CFG = json.loads((ROOT / "config" / "strategy_search_v3_round2.json").read_text(encoding="utf-8"))
START = pd.Timestamp("2026-10-15", tz="UTC")


def _utc(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


# ------------------------------------------------------------------------------------------- cascade fixtures


def cascade_universe(funding_through: str = "2026-09-30 16:00", rate: float = 1e-4) -> tuple[dict, pd.Timestamp]:
    """Three contracts, flat prices, hourly bars from 2026-10-07 to 2026-10-21.

    A: crash + OI drop at the start instant (boundary) and again 5h before the data end (pending).
    B: crash + OI drop 3d 06h after the start (the one scored trade).
    C: crash without an OI drop (never an event)."""
    grid = pd.date_range("2026-10-07 01:00", "2026-10-21 00:00", freq="1h", tz="UTC")  # bar ends
    data_end = grid[-1]
    events = {"AAAUSDT": [START, data_end - pd.Timedelta(hours=5)], "BBBUSDT": [START + pd.Timedelta(days=3, hours=6)],
              "CCCUSDT": []}
    perp, oi, funding, mark, perp_hl = {}, {}, {}, {}, {}
    for sym, times in events.items():
        px = pd.Series(100.0, index=grid)
        for t in times:
            px.loc[px.index >= t] *= 0.94
            px.loc[px.index >= t + pd.Timedelta(hours=24)] *= 98.0 / 94.0
        if sym == "CCCUSDT":
            px.loc[px.index >= START + pd.Timedelta(days=2)] *= 0.9
        perp[sym] = pd.DataFrame({"close": px, "quote_volume": 1e6})
        grid5 = pd.date_range(grid[0] - pd.Timedelta(hours=1), grid[-1], freq="5min", tz="UTC")
        o = pd.Series(1000.0, index=grid5)
        for t in times:
            o.loc[o.index >= t - pd.Timedelta(hours=2)] *= 0.9
        oi[sym] = o
        stamps = pd.date_range("2026-10-01 00:00", funding_through, freq="8h", tz="UTC")
        funding[sym] = pd.DataFrame({"rate": rate, "interval_hours": 8.0}, index=stamps)
        hl = pd.DataFrame({"high": px * 1.001, "low": px * 0.999})
        mark[sym] = hl
        perp_hl[sym] = hl
    return {"perp": perp, "oi": oi, "funding": funding, "mark": mark, "perp_hl": perp_hl, "unlisted": []}, data_end


class CascadeSleeveTests(unittest.TestCase):
    def test_trades_equal_the_shared_functions_and_start_is_exclusive(self):
        universe, data_end = cascade_universe()
        books, info = nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
        params = nmf.cascade_params(ROUND_CFG, START - pd.Timedelta(days=nmf.CASCADE_WARMUP_DAYS))
        inputs = lc.make_inputs(universe, max_exit=None)
        direct = lc.build_trades(lc.cascade_weights(inputs.data, params), inputs, None, lc.COST_BPS_ROUND_TRIP)
        self.assertEqual(len(direct), 2)  # A at the start instant and B; A's late entry has no exit bar yet
        scored = direct.loc[(direct["entry_time"] > START) & (direct["exit_time"] < data_end)]
        self.assertEqual([t["symbol"] for t in info["trades"]], list(scored["symbol"]))
        self.assertEqual([t["entry_time"] for t in info["trades"]], [t.isoformat() for t in scored["entry_time"]])
        np.testing.assert_allclose([t["unit_return"] for t in info["trades"]], scored["unit_return"].to_numpy())
        self.assertEqual(info["trades_scored"], 1)
        self.assertEqual(info["trades"][0]["symbol"], "BBBUSDT")
        # the trade entered exactly at the start is replayed but never scored
        self.assertIn(START.isoformat(), [t.isoformat() for t in direct["entry_time"]])
        self.assertNotIn(START.isoformat(), [t["entry_time"] for t in info["trades"]])
        # the trade of the last day is pending (its 24h exit is not published), nothing else
        self.assertEqual([p["symbol"] for p in info["pending_entries"]], ["AAAUSDT"])
        self.assertEqual(info["pending_entries"][0]["reason"], "exit not yet published")
        self.assertEqual(books["cascade_1x"].trades, 1)
        self.assertEqual(books["cascade_1x"].liquidations, 0)

    def test_daily_accounting_and_leverage_levels(self):
        universe, data_end = cascade_universe()
        books, info = nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
        trade = info["trades"][0]
        exit_day = pd.Timestamp(trade["exit_time"]).normalize()
        d1, d2 = books["cascade_1x"].daily, books["cascade_2x"].daily
        self.assertEqual(d1.index[0], START + pd.Timedelta(days=1))
        self.assertEqual(d1.index[-1], data_end - pd.Timedelta(days=1))
        self.assertTrue(all(d1.index > START))
        w, cost = 0.10, 0.10 * lc.COST_BPS_ROUND_TRIP / 1e4
        unit = trade["unit_return"]
        self.assertAlmostEqual(d1.loc[exit_day], w * unit - cost, places=12)
        self.assertAlmostEqual(d2.loc[exit_day], 2 * w * unit - 2 * cost, places=12)
        self.assertEqual(int((d1 != 0).sum()), 1)

    def test_funding_pending_flag_and_replacement_once_the_month_is_published(self):
        pending, data_end = cascade_universe(funding_through="2026-09-30 16:00")
        books, info = nmf.cascade_sleeve(pending, ROUND_CFG, START, data_end)
        self.assertTrue(info["trades"][0]["funding_pending"])
        self.assertEqual(books["cascade_1x"].funding_pending, 1)
        self.assertEqual(books["cascade_1x"].daily_no_pending.abs().sum(), 0.0)
        published, _ = cascade_universe(funding_through="2026-10-31 16:00")
        books2, info2 = nmf.cascade_sleeve(published, ROUND_CFG, START, data_end)
        self.assertFalse(info2["trades"][0]["funding_pending"])
        self.assertEqual(books2["cascade_1x"].funding_pending, 0)
        # three 8h settlements of 1e-4 inside (entry, exit]: the realised funding replaces the zeros
        self.assertAlmostEqual(info["trades"][0]["unit_return"] - info2["trades"][0]["unit_return"], 3e-4, places=12)
        np.testing.assert_allclose(books2["cascade_1x"].daily.to_numpy(), books2["cascade_1x"].daily_no_pending.to_numpy())

    def test_nothing_scored_before_the_first_day_after_the_start(self):
        universe, _ = cascade_universe()
        early_end = START + pd.Timedelta(days=1)  # data through the start day only
        for sym in universe["perp"]:
            for key in ("perp", "mark", "perp_hl"):
                universe[key][sym] = universe[key][sym].loc[lambda f: f.index <= early_end]
            universe["oi"][sym] = universe["oi"][sym].loc[lambda s: s.index <= early_end]
        books, info = nmf.cascade_sleeve(universe, ROUND_CFG, START, early_end)
        self.assertEqual(info["trades_scored"], 0)
        self.assertTrue(all(b.daily.index[0] > START for b in books.values() if len(b.daily)))

    def test_leverage_liquidation_uses_the_shared_mark_logic(self):
        scored = pd.DataFrame({
            "entry_time": [_utc("2026-10-16 00:00")], "exit_time": [_utc("2026-10-17 00:00")], "symbol": ["XUSDT"],
            "mark_key": ["XUSDT"], "weight": [0.1], "entry_price": [100.0], "unit_return": [-0.5], "cost": [0.00014]})
        idx = pd.date_range("2026-10-16 01:00", "2026-10-17 00:00", freq="1h", tz="UTC")
        frames = {"XUSDT": pd.DataFrame({"high": 100.0, "low": 40.0}, index=idx).assign(is_mark=True)}
        first, last = _utc("2026-10-16"), _utc("2026-10-17")
        d1, n1, _ = nmf.cascade_book(scored, frames, 1, first, last)
        d2, n2, liquidated = nmf.cascade_book(scored, frames, 2, first, last)
        self.assertEqual((n1, n2), (0, 1))  # 60% adverse: below 99.5% at 1x, above 49.5% at 2x
        self.assertEqual(len(liquidated), 1)
        self.assertAlmostEqual(d2.loc[last], -0.1 * (1 + 0.005 * 2) - 2 * 0.00014, places=12)
        self.assertAlmostEqual(d1.loc[last], 0.1 * -0.5 - 0.00014, places=12)

    def test_one_symbol_missing_its_last_day_gives_a_pending_trade_and_an_unscored_day(self):
        universe, data_end = cascade_universe()
        cut = START + pd.Timedelta(days=3, hours=16)  # BBB's event (3d06h) entered, its 24h exit is not published
        for key in ("perp", "mark", "perp_hl"):
            universe[key]["BBBUSDT"] = universe[key]["BBBUSDT"].loc[lambda f: f.index <= cut]
        universe["oi"]["BBBUSDT"] = universe["oi"]["BBBUSDT"].loc[lambda s: s.index <= cut]
        books, info = nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
        fresh = info["freshness"]
        self.assertEqual(fresh["lagging_perp_symbols"], ["BBBUSDT"])
        self.assertEqual(fresh["perp_last_bar"]["BBBUSDT"], cut.isoformat())
        self.assertEqual(pd.Timestamp(fresh["effective_end"]), (START + pd.Timedelta(days=3)))
        self.assertEqual(info["trades"], [])  # no stale-price exit score
        self.assertIn("BBBUSDT", [p["symbol"] for p in info["pending_entries"]])
        daily = books["cascade_1x"].daily
        self.assertEqual(daily.index[-1], START + pd.Timedelta(days=2))  # the day BBB is incomplete for is unscored
        self.assertEqual(float(daily.abs().sum()), 0.0)

    def test_open_interest_lag_makes_the_entry_window_not_evaluable(self):
        universe, data_end = cascade_universe()
        cut = START + pd.Timedelta(days=3)  # BBB's metrics stop before its event at 3d06h (OI drop at 3d04h)
        universe["oi"]["BBBUSDT"] = universe["oi"]["BBBUSDT"].loc[lambda s: s.index <= cut]
        books, info = nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
        fresh = info["freshness"]
        self.assertEqual(fresh["lagging_oi_symbols"], ["BBBUSDT"])
        self.assertEqual(fresh["oi_last_record"]["BBBUSDT"], cut.isoformat())
        self.assertEqual(pd.Timestamp(fresh["effective_end"]), START + pd.Timedelta(days=4))
        self.assertEqual(books["cascade_1x"].daily.index[-1], START + pd.Timedelta(days=3))
        self.assertEqual(info["trades"], [])

    def test_fresh_universe_has_no_lagging_symbols_and_reports_a_flat_warmup_window(self):
        universe, data_end = cascade_universe()
        _, info = nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
        self.assertEqual(info["freshness"]["lagging_perp_symbols"], [])
        self.assertEqual(info["freshness"]["lagging_oi_symbols"], [])
        self.assertEqual(pd.Timestamp(info["freshness"]["effective_end"]), data_end)
        self.assertEqual(info["warmup_days"], 7)
        w = info["warmup_flat_window"]
        self.assertGreaterEqual(pd.Timestamp(w["window_start"]), START - pd.Timedelta(days=7) + pd.Timedelta(hours=4))
        self.assertEqual(pd.Timestamp(w["window_end"]) - pd.Timestamp(w["window_start"]), pd.Timedelta(hours=24))

    def test_warmup_window_search_and_extension(self):
        rs = START - pd.Timedelta(days=7)
        dense = [rs + pd.Timedelta(hours=h) for h in range(5, 24 * 7 + 1, 10)]
        self.assertIsNone(nmf.warmup_window(dense, rs, START))
        sparse = dense[:3] + [START - pd.Timedelta(hours=2)]
        w = nmf.warmup_window(sparse, rs, START)
        self.assertIsNotNone(w)
        self.assertEqual(pd.Timestamp(w["window_start"]), sparse[2])
        universe, data_end = cascade_universe()
        with mock.patch.object(nmf, "warmup_window", return_value=None):
            with self.assertRaises(nmf.WarmupNotFlat):
                nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
            asked: list[int] = []

            def loader(rs_: pd.Timestamp):
                asked.append(int((START - rs_).days))
                return universe

            with self.assertRaises(nmf.NearMissError):
                nmf.cascade_sleeve_auto(loader, ROUND_CFG, START, data_end)
            self.assertEqual(asked, [7, 14, 21, 28, 35, 42, 49, 56, 60])  # fails loudly beyond 60 days
        flat = {"window_start": "x", "window_end": "y", "flat_from": "y"}
        asked2: list[int] = []

        def loader2(rs_: pd.Timestamp):
            asked2.append(int((START - rs_).days))
            return universe

        with mock.patch.object(nmf, "warmup_window", side_effect=[None, None, flat]):
            _, info = nmf.cascade_sleeve_auto(loader2, ROUND_CFG, START, data_end)
        self.assertEqual(asked2, [7, 14, 21])
        self.assertEqual(info["warmup_days"], 21)

    def test_funding_gap_inside_a_published_month_is_flagged_separately(self):
        universe, data_end = cascade_universe(funding_through="2026-10-31 16:00")
        _, base = nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
        t = base["trades"][0]
        self.assertFalse(t["funding_pending"] or t["funding_gap_zero_filled"])
        entry, exit_ = pd.Timestamp(t["entry_time"]), pd.Timestamp(t["exit_time"])
        mid = [x for x in universe["funding"]["BBBUSDT"].index if entry < x <= exit_][1]
        universe["funding"]["BBBUSDT"] = universe["funding"]["BBBUSDT"].drop(mid)
        books, info = nmf.cascade_sleeve(universe, ROUND_CFG, START, data_end)
        t2 = info["trades"][0]
        self.assertTrue(t2["funding_gap_zero_filled"])
        self.assertFalse(t2["funding_pending"])
        self.assertEqual(books["cascade_1x"].funding_gap_zero_filled, 1)
        self.assertEqual(books["cascade_1x"].funding_pending, 0)
        np.testing.assert_allclose(books["cascade_1x"].daily.to_numpy(), books["cascade_1x"].daily_no_pending.to_numpy())

    def test_universe_file_is_the_round2_universe(self):
        uni = json.loads((ROOT / nmf.DEFAULT_UNIVERSE).read_text(encoding="utf-8"))
        self.assertEqual(len(uni["symbols"]), 30)
        self.assertEqual(uni["metrics_day"], "2021-12-01")


# --------------------------------------------------------------------------------------------- CTREND sleeve


def ctrend_panel() -> dict:
    days = pd.date_range("2026-08-01", "2026-10-31", freq="D", tz="UTC")
    rng = np.random.default_rng(7)
    close = pd.DataFrame(100.0 * np.cumprod(1 + rng.normal(0, 0.02, (len(days), 4)), axis=0), index=days,
                         columns=["AAA", "BBB", "CCC", "DDD"])
    return {"close": close, "high": close * 1.01, "low": close * 0.99, "dollar_volume": close * 0 + 1e7}


def stub_weights(panel: dict) -> pd.DataFrame:
    idx = panel["close"].index
    out = pd.DataFrame(np.nan, index=idx, columns=panel["close"].columns)
    sundays = idx[idx.dayofweek == 6]
    for k, d in enumerate(sundays):
        out.loc[d] = [0.5, 0.0, 0.0, -0.5] if k % 2 == 0 else [0.0, 0.5, -0.5, 0.0]
    first = sundays[0]
    out.loc[first:] = out.loc[first:].ffill()
    return out


class CtrendSleeveTests(unittest.TestCase):
    def test_calls_shared_weights_and_accounting_and_scores_after_the_first_rebalance(self):
        panel = ctrend_panel()
        weights = stub_weights(panel)
        with mock.patch.object(nmf.ctrend, "ctrend_weights", return_value=weights) as cw:
            books, info = nmf.ctrend_sleeve(panel, START)
        cw.assert_called_once()
        self.assertEqual(cw.call_args[0][1], r2.DEFAULT_PARAMS[r2.CTREND_ID])
        first = _utc("2026-10-18")  # first Sunday strictly after Thursday 2026-10-15
        self.assertEqual(info["first_scored_rebalance"], first.isoformat())
        expected = r2.buy_and_hold_detail(weights, panel["close"], 20.0)["net"]
        expected = expected.loc[expected.index > first]
        pd.testing.assert_series_equal(books["ctrend_1x"].daily, expected)
        self.assertTrue(all(books["ctrend_1x"].daily.index > START))
        self.assertEqual(books["ctrend_1x"].daily.index[0], first + pd.Timedelta(days=1))
        sundays = {d - pd.Timedelta(days=(d.dayofweek + 1) % 7) for d in books["ctrend_1x"].daily.index}
        self.assertEqual(books["ctrend_1x"].trades, len(sundays))

    def test_no_book_formed_before_the_first_rebalance_and_pre_start_nothing(self):
        panel = ctrend_panel()
        panel = {k: v.loc[v.index <= _utc("2026-10-17")] for k, v in panel.items()}  # data ends the Saturday before
        with mock.patch.object(nmf.ctrend, "ctrend_weights", return_value=stub_weights(panel)):
            books, info = nmf.ctrend_sleeve(panel, START)
        self.assertEqual(len(books["ctrend_1x"].daily), 0)
        self.assertFalse(info["book_formed"])
        self.assertEqual(books["ctrend_1x"].trades, 0)
        # data ending on the Sunday itself: the book is decided but has no scored day yet, so it is not counted
        sun = {k: v.loc[v.index <= _utc("2026-10-18")] for k, v in ctrend_panel().items()}
        with mock.patch.object(nmf.ctrend, "ctrend_weights", return_value=stub_weights(sun)):
            books2, _ = nmf.ctrend_sleeve(sun, START)
        self.assertEqual(books2["ctrend_1x"].trades, 0)

    def test_tail_trim_drops_half_published_days(self):
        panel = ctrend_panel()
        close = panel["close"].copy()
        wide = pd.concat([close, pd.DataFrame(np.nan, index=close.index, columns=[f"X{i}" for i in range(40)])], axis=1)
        wide.iloc[:, 4:] = 1.0
        wide.iloc[-1, 4:30] = np.nan  # most coins lack the last day
        trimmed = nmf.trim_incomplete_tail({"close": wide, "high": wide, "low": wide, "dollar_volume": wide})
        self.assertEqual(len(trimmed["close"]), len(wide) - 1)
        self.assertEqual(trimmed["dropped_incomplete_days"], [str(wide.index[-1].date())])


# ------------------------------------------------------------------------------------- trend core fixtures


def trend_data(funding_through: str = "2026-09-30 16:00") -> tuple[dict, dict, pd.Timestamp]:
    core = json.loads((ROOT / "config" / "crypto_trend_core_v1.json").read_text(encoding="utf-8"))
    core = {**core, "groups": {"crypto": ["AAA_USDT", "BBB_USDT"]}}
    idx = pd.date_range("2026-01-01", "2026-10-20", freq="8h", tz="UTC")
    frames, marks, funding = {}, {}, {}
    hours = pd.date_range(idx[0] + pd.Timedelta(hours=1), idx[-1] + pd.Timedelta(hours=8), freq="1h", tz="UTC")
    for seed, sym in ((1, "AAAUSDT"), (2, "BBBUSDT")):
        r = np.random.default_rng(seed)
        ret = r.normal(0.0004, 0.012, len(idx))
        ret[300:500] += 0.006
        ret[500:620] -= 0.008
        c = 100 * np.cumprod(1 + ret)
        o = np.concatenate([[100.0], c[:-1]])
        high = np.maximum(o, c) * (1 + np.abs(r.normal(0, 0.003, len(idx))))
        low = np.minimum(o, c) * (1 - np.abs(r.normal(0, 0.003, len(idx))))
        frames[sym] = pd.DataFrame({"open": o, "high": high, "low": low, "close": c}, index=idx)
        key = (hours - pd.Timedelta(hours=1)).floor("8h")
        marks[sym] = pd.DataFrame({"high": frames[sym]["high"].reindex(key).to_numpy(),
                                   "low": frames[sym]["low"].reindex(key).to_numpy(), "is_mark": True}, index=hours)
        funding[sym] = pd.Series(1e-4, index=pd.date_range("2026-01-01", funding_through, freq="8h", tz="UTC"))
    data = {"frames": frames, "funding_raw": funding, "marks": marks, "missing": [],
            "symbols": {"AAA_USDT": "AAAUSDT", "BBB_USDT": "BBBUSDT"}, "history_start": "2026-01-01"}
    return core, data, idx[-1] + pd.Timedelta(hours=8)


class TrendCoreSleeveTests(unittest.TestCase):
    def test_start_exclusive_stamps_and_funding_pending_flag(self):
        core, data, data_end = trend_data()
        start = _utc("2026-10-01")
        books, info = nmf.trend_core_sleeve(core, data, start, data_end)
        self.assertGreater(info["episodes_total"], info["episodes_scored"])
        for e in info["episodes"]:
            self.assertGreater(pd.Timestamp(e["entry_time"]), start)
            self.assertTrue(e["funding_pending"])  # the October funding file is not published
        self.assertGreater(info["episodes_open_at_start_ignored"], 0)
        for book in books.values():
            self.assertTrue(len(book.daily) and all(book.daily.index > start))
            self.assertEqual(book.daily.index[0], start + pd.Timedelta(days=1))
            self.assertEqual(book.funding_pending, book.trades)
            self.assertAlmostEqual(float(book.daily_no_pending.abs().sum()), 0.0, places=12)
        self.assertIn("AAAUSDT", info["funding_pending_bars"])

    def test_a_lagging_symbol_caps_scoring_at_the_common_last_bar(self):
        core, data, data_end = trend_data(funding_through="2026-10-20 16:00")
        start = _utc("2026-10-01")
        behind = {**data, "frames": {**data["frames"], "BBBUSDT": data["frames"]["BBBUSDT"].iloc[:-6]}}  # two days short
        books, info = nmf.trend_core_sleeve(core, behind, start, data_end)
        common = data["frames"]["BBBUSDT"].index[-7]
        self.assertEqual(pd.Timestamp(info["common_last_bar"]), common)
        self.assertEqual(info["symbols_behind_common_end"], ["AAAUSDT"])
        both = {**data, "frames": {s: f.iloc[:-6] for s, f in data["frames"].items()}}
        books_ref, _ = nmf.trend_core_sleeve(core, both, start, data_end)
        for name in books:
            pd.testing.assert_series_equal(books[name].daily, books_ref[name].daily)
        full, _ = nmf.trend_core_sleeve(core, data, start, data_end)
        self.assertGreater(len(full["trend_core_1x"].daily), len(books["trend_core_1x"].daily))

    def test_funding_gap_inside_a_published_month_is_not_pending(self):
        core, data, data_end = trend_data(funding_through="2026-10-20 16:00")
        start = _utc("2026-10-01")
        _, info = nmf.trend_core_sleeve(core, data, start, data_end)
        ep = info["episodes"][0]
        sym = ep["sleeve"].split(":")[1]
        raw = data["funding_raw"][sym]
        hole = [x for x in raw.index if pd.Timestamp(ep["entry_time"]) < x <= pd.Timestamp(ep["exit_time"])][1]
        data2 = {**data, "funding_raw": {**data["funding_raw"], sym: raw.drop(hole)}}
        books, info2 = nmf.trend_core_sleeve(core, data2, start, data_end)
        flagged = [e for e in info2["episodes"] if e["funding_gap_zero_filled"]]
        self.assertTrue(flagged)
        self.assertTrue(all(not e["funding_pending"] for e in info2["episodes"]))
        self.assertEqual(books["trend_core_1x"].funding_pending, 0)
        self.assertEqual(books["trend_core_1x"].funding_gap_zero_filled, len(flagged))
        self.assertIn(sym, info2["funding_gap_bars_filled_zero"])
        np.testing.assert_allclose(books["trend_core_1x"].daily.to_numpy(), books["trend_core_1x"].daily_no_pending.to_numpy())

    def test_pending_flag_clears_when_the_funding_file_appears(self):
        core, data, data_end = trend_data()
        start = _utc("2026-10-01")
        before, info0 = nmf.trend_core_sleeve(core, data, start, data_end)
        core2, data2, _ = trend_data(funding_through="2026-10-20 16:00")
        after, info1 = nmf.trend_core_sleeve(core2, data2, start, data_end)
        self.assertTrue(all(not e["funding_pending"] for e in info1["episodes"]))
        self.assertEqual(info1["funding_pending_bars"], {})
        self.assertEqual(after["trend_core_1x"].funding_pending, 0)
        # same episodes and the realised funding changes the books
        self.assertEqual([e["entry_time"] for e in info0["episodes"]], [e["entry_time"] for e in info1["episodes"]])
        np.testing.assert_allclose(after["trend_core_1x"].daily.to_numpy(), after["trend_core_1x"].daily_no_pending.to_numpy())
        self.assertFalse(np.allclose(before["trend_core_1x"].daily.to_numpy(), after["trend_core_1x"].daily.to_numpy()))

    def test_neutralised_intervals_partition_the_run_and_keep_all_reproduces_simulate_level(self):
        core, data, data_end = trend_data(funding_through="2026-10-20 16:00")
        symbols = list(data["frames"])
        run_core = {**core, "source": {**core["source"], "symbols": symbols}}
        run = tcl.run_sleeves_detailed(run_core, data["frames"], {s: data["funding_raw"][s] for s in symbols})
        eps = run.episodes
        self.assertGreater(len(eps), 6)
        everything = set(range(len(eps)))
        same = nmf.neutralized_intervals(run.intervals, eps, everything)
        for name, r in run.intervals.items():
            np.testing.assert_allclose(same[name].to_numpy(), r.to_numpy(), rtol=0, atol=0)
        paths = [tcl.episode_adverse_path(e, data["marks"].get(e["symbol"])) for e in eps]
        direct = tcl.simulate_level(run.intervals, eps, paths, 1)["daily"]
        via = tcl.simulate_level(same, eps, paths, 1)["daily"]
        pd.testing.assert_series_equal(direct, via)
        # a partition: the factors of the kept part times the factors of the removed part are the original factors
        kept = {i for i in everything if pd.Timestamp(eps[i]["entry_time"]) > _utc("2026-06-01")}
        removed = everything - kept
        a = nmf.neutralized_intervals(run.intervals, eps, kept)
        b = nmf.neutralized_intervals(run.intervals, eps, removed)
        for name, r in run.intervals.items():
            np.testing.assert_allclose((1 + a[name]).to_numpy() * (1 + b[name]).to_numpy(), (1 + r).to_numpy(), rtol=1e-12)
        none = nmf.neutralized_intervals(run.intervals, eps, set())
        for name in none:
            np.testing.assert_allclose(none[name].to_numpy(), 0.0, atol=1e-12)

    def test_fill_missing_settlements_marks_pending_and_gap_bars(self):
        idx = pd.date_range("2026-09-01", "2026-10-05", freq="8h", tz="UTC")
        stamps = pd.date_range("2026-09-01 08:00", "2026-09-30 16:00", freq="8h", tz="UTC")
        raw = pd.Series(1e-4, index=stamps.delete(10))  # one settlement missing inside the published month
        cover = nmf.month_after_last(pd.DatetimeIndex(raw.index))
        self.assertEqual(cover, _utc("2026-10-01"))
        filled, pending, gaps = nmf.fill_missing_settlements(idx, raw, cover)
        self.assertEqual(gaps, [stamps[10]])
        self.assertTrue(pending and all(t >= cover for t in pending))
        short, _ = tcl.funding_shortfalls(idx, filled, [(0, len(idx) - 1)])
        self.assertEqual([t for t, _, _ in short if idx[t] > stamps[0]], [])
        self.assertEqual(float(filled.loc[filled.index > stamps[-1]].abs().sum()), 0.0)
        # a 4h series keeps its cadence
        raw4 = pd.Series(1e-4, index=pd.date_range("2026-09-01 04:00", "2026-09-30 20:00", freq="4h", tz="UTC"))
        filled4, pend4, gaps4 = nmf.fill_missing_settlements(idx, raw4, nmf.month_after_last(pd.DatetimeIndex(raw4.index)))
        self.assertEqual(gaps4, [])
        short4, _ = tcl.funding_shortfalls(idx, filled4, [(0, len(idx) - 1)])
        self.assertEqual([t for t, _, _ in short4 if idx[t] > raw4.index[0]], [])
        self.assertTrue(pend4)
        # a 4h series missing the earlier of two settlements of a bar: the real later one must not be duplicated
        holes = raw4.drop(pd.Timestamp("2026-09-10 04:00", tz="UTC"))
        filled_h, _, gaps_h = nmf.fill_missing_settlements(idx, holes, nmf.month_after_last(pd.DatetimeIndex(holes.index)))
        self.assertEqual(gaps_h, [_utc("2026-09-10 08:00")])
        short_h, _ = tcl.funding_shortfalls(idx, filled_h, [(0, len(idx) - 1)])
        self.assertEqual([t for t, _, _ in short_h if idx[t] > holes.index[0]], [])


# --------------------------------------------------------------------------------- bands, report, probes


def books_with(daily: dict[str, pd.Series]) -> dict[str, nmf.BookResult]:
    return {name: nmf.BookResult(daily.get(name, pd.Series(dtype=float)), daily.get(name, pd.Series(dtype=float)), 0, 0, 0)
            for name in nmf.BOOKS}


class BandAndReportTests(unittest.TestCase):
    def reference(self):
        rng = np.random.default_rng(11)
        vals = list(rng.normal(0.0008, 0.01, 800))
        return {"series": {name: {"window": ["2023-07-01", "2026-09-30"], "values": vals} for name in nmf.BOOKS}}

    def test_bands_deterministic_and_seeded(self):
        ref = np.asarray(self.reference()["series"]["cascade_1x"]["values"])
        a = nmf.bootstrap_band(ref, 30)
        b = nmf.bootstrap_band(ref, 30)
        np.testing.assert_array_equal(a, b)
        self.assertEqual(a.shape, (nmf.BAND_PATHS,))
        other = nmf.bootstrap_band(ref, 30, seed=nmf.BAND_SEED + 1)
        self.assertFalse(np.array_equal(a, other))
        # same seed: a longer horizon extends the same paths
        idx30 = lev.stationary_bootstrap_indices(len(ref), nmf.BAND_PATHS, 30, nmf.BAND_MEAN_BLOCK, nmf.BAND_SEED)
        idx60 = lev.stationary_bootstrap_indices(len(ref), nmf.BAND_PATHS, 60, nmf.BAND_MEAN_BLOCK, nmf.BAND_SEED)
        np.testing.assert_array_equal(idx30, idx60[:, :30])
        self.assertGreater(float(np.median(a)), float(np.median(nmf.bootstrap_band(ref - ref.mean(), 30))))
        self.assertEqual(nmf.BAND_SEED, 20261013)
        self.assertIn("20261013", CONFIG["scoring"])
        self.assertEqual((nmf.BAND_PATHS, nmf.BAND_MEAN_BLOCK), (5000, 10))

    def test_percentile_position(self):
        sample = np.arange(100, dtype=float)
        self.assertAlmostEqual(nmf.percentile_of(sample, 49.5), 50.0)
        self.assertAlmostEqual(nmf.percentile_of(sample, -1.0), 0.0)
        self.assertAlmostEqual(nmf.percentile_of(sample, 1000.0), 100.0)

    def test_pre_start_report_schema_and_claims(self):
        report = nmf.build_report(CONFIG, books_with({}), {}, self.reference(), as_of="2026-10-13T12:00:00Z",
                                  data_end=_utc("2026-10-12"))
        self.assertEqual(report["status"], "PRE_START")
        self.assertEqual(report["watch_id"], "near-miss-forward-v1")
        self.assertEqual(report["prospective_start_utc"], "2026-10-15T00:00:00+00:00")
        self.assertEqual(report["claims"], CONFIG["claims"])
        self.assertTrue(all(v is False for v in report["claims"].values()))
        self.assertEqual(set(report["forward"]), set(nmf.BOOKS))
        for name in nmf.BOOKS:
            self.assertEqual(report["forward"][name]["days"], 0)
            self.assertEqual(report["forward"][name]["trades"], 0)
            self.assertEqual(report["daily_returns"][name], {})
            self.assertTrue(report["bands"][name]["available"])
        self.assertFalse(report["review_window_open"])
        json.dumps(report, allow_nan=False)

    def test_collecting_report_stamps_after_start_and_band_percentiles(self):
        days = pd.date_range("2026-10-16", "2026-11-14", freq="D", tz="UTC")
        rng = np.random.default_rng(5)
        daily = {name: pd.Series(rng.normal(0.0005, 0.01, len(days)), index=days) for name in nmf.BOOKS}
        report = nmf.build_report(CONFIG, books_with(daily), {}, self.reference(), as_of="2026-11-15", data_end=_utc("2026-11-15"))
        self.assertEqual(report["status"], "COLLECTING")
        for name in nmf.BOOKS:
            stamps = list(report["daily_returns"][name])
            self.assertEqual(len(stamps), 30)
            self.assertTrue(all(t > report["prospective_start_utc"] for t in stamps))
            band = report["bands"][name]
            self.assertEqual(band["forward_days"], 30)
            for label in ("as_backtested", "zero_edge_demeaned"):
                self.assertTrue(0.0 <= band[label]["forward_percentile"] <= 100.0)
                self.assertEqual(set(band[label]["band_quantiles"]), {"p05", "p25", "p50", "p75", "p95"})
        again = nmf.build_report(CONFIG, books_with(daily), {}, self.reference(), as_of="2026-11-15", data_end=_utc("2026-11-15"))
        self.assertEqual(report["bands"], again["bands"])

    def test_reference_file_is_complete_and_matches_the_registered_windows(self):
        ref = json.loads((ROOT / nmf.DEFAULT_REFERENCE).read_text(encoding="utf-8"))
        self.assertTrue(ref["all_checks_match"])
        windows = re.findall(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", CONFIG["scoring"])
        self.assertEqual(len(windows), 3)
        self.assertEqual([list(w) for w in windows],
                         [ref["windows"]["cascade"], ref["windows"]["ctrend"], ref["windows"]["trend_core"]])
        for name in nmf.BOOKS:
            entry = ref["series"][name]
            self.assertEqual(entry["window"], ref["windows"][name.rsplit("_", 1)[0]])
            self.assertEqual(len(entry["stamps"]), len(entry["values"]))
        self.assertTrue(all("match" in c or c["equivalence"]["match"] for c in ref["reproduction_checks"]))
        self.assertEqual(set(ref["code_sha256"]), {"src/orderflow_edge_lab/near_miss_forward.py",
                                                    "scripts/near_miss_forward_reference.py"})

    def test_forward_entry_reports_pending_contribution_and_gaps_separately(self):
        days = pd.date_range("2026-10-16", periods=5, freq="D", tz="UTC")
        daily = {name: pd.Series(0.01, index=days) for name in nmf.BOOKS}
        books = {n: nmf.BookResult(daily[n], daily[n] * 0.5, 3, 0, 2, {}, 1) for n in nmf.BOOKS}
        report = nmf.build_report(CONFIG, books, {}, None, as_of="2026-10-22", data_end=_utc("2026-10-21"))
        entry = report["forward"]["cascade_1x"]
        self.assertIn("pending_trades_contribution", entry)
        self.assertNotIn("funding_pending_effect_on_cumulative", entry)
        self.assertEqual(entry["funding_pending_trades"], 2)
        self.assertEqual(entry["funding_gap_zero_filled_trades"], 1)
        self.assertAlmostEqual(entry["pending_trades_contribution"],
                               entry["cumulative_return"] - entry["cumulative_return_excluding_funding_pending"])

    def test_a_stamp_at_or_before_the_start_is_an_error(self):
        days = pd.date_range("2026-10-15", "2026-10-20", freq="D", tz="UTC")
        daily = {name: pd.Series(0.001, index=days) for name in nmf.BOOKS}
        with self.assertRaises(nmf.NearMissError):
            nmf.build_report(CONFIG, books_with(daily), {}, None, as_of="2026-10-21", data_end=_utc("2026-10-21"))

    def test_wrong_watch_config_rejected(self):
        with self.assertRaises(nmf.NearMissError):
            nmf.build_report({**CONFIG, "watch_id": "other"}, books_with({}), {}, None, as_of="2026-10-13",
                             data_end=_utc("2026-10-12"))


# --------------------------------------------------------------------------------------------- fake archive


class FakeArchive:
    """In-memory data.binance.vision: keys -> bytes, S3 listings and checksums; records every requested URL."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.requests: list[str] = []

    def add_zip(self, key: str, csv: str) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(Path(key).name.replace(".zip", ".csv"), csv)
        self.files[key] = buf.getvalue()

    def __call__(self, url: str) -> bytes:
        self.requests.append(url)
        if url.startswith(bsa.LIST_URL):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            prefix = q["prefix"][0]
            keys = sorted(k for k in self.files if k.startswith(prefix))
            body = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys)
            return f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{body}<IsTruncated>false</IsTruncated></ListBucketResult>'.encode()
        key = urllib.parse.unquote(url[len(bsa.DATA_URL):])
        if key.endswith(".CHECKSUM"):
            real = key[: -len(".CHECKSUM")]
            if real in self.files:
                return (sha256(self.files[real]).hexdigest() + "  " + Path(real).name).encode()
        elif key in self.files:
            return self.files[key]
        raise bsa.ArchiveHTTPError(url, 404)


def hourly_csv(day: str, base: float, hours: int = 24) -> str:
    t0 = pd.Timestamp(day, tz="UTC")
    rows = []
    for h in range(hours):
        ot = int((t0 + pd.Timedelta(hours=h)).timestamp() * 1000)
        rows.append(f"{ot},{base},{base * 1.01},{base * 0.99},{base},10,{ot + 3599999},1000000,5,1,1,0")
    return "\n".join(rows) + "\n"


def daily_csv(day: str, base: float) -> str:
    ot = int(pd.Timestamp(day, tz="UTC").timestamp() * 1000)
    return f"{ot},{base},{base * 1.02},{base * 0.98},{base},10,{ot + 86399999},2000000,5,1,1,0\n"


class ProbeAndLoaderTests(unittest.TestCase):
    def test_latest_published_day_walks_back_to_the_last_complete_day(self):
        arch = FakeArchive()
        for day in ("2026-10-10", "2026-10-11"):
            for key in nmf.probe_keys(day).values():
                arch.add_zip(key, "x\n")
        arch.add_zip(nmf.probe_keys("2026-10-12")["spot"], "x\n")  # a day published in one family only
        self.assertEqual(nmf.latest_published_day(_utc("2026-10-13 10:00"), arch), _utc("2026-10-11"))
        with self.assertRaises(nmf.NearMissError):
            nmf.latest_published_day(_utc("2026-10-13"), FakeArchive(), max_back=3)

    def test_spot_loader_downloads_only_months_from_the_start(self):
        arch = FakeArchive()
        arch.add_zip("data/spot/monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2024-12.zip", daily_csv("2024-12-31", 1.0))
        arch.add_zip("data/spot/monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2026-08.zip", daily_csv("2026-08-31", 2.0))
        for d in ("2026-09-01", "2026-09-02"):
            arch.add_zip(f"data/spot/daily/klines/AAAUSDT/1d/AAAUSDT-1d-{d}.zip", daily_csv(d, 3.0))
        arch.add_zip("data/spot/daily/klines/AAAUSDT/1d/AAAUSDT-1d-2026-08-30.zip", daily_csv("2026-08-30", 9.0))
        with self.subTest("frame"):
            with_dir = Path(tempfile.mkdtemp())
            frame = nmf.load_symbol_daily_from("AAAUSDT", start="2025-01-01", end="2026-09-02", fetch=arch, directory=with_dir)
            self.assertEqual(list(frame.index.strftime("%Y-%m-%d")), ["2026-08-31", "2026-09-01", "2026-09-02"])
            self.assertFalse(any("2024-12" in u for u in arch.requests))
            self.assertFalse(any("2026-08-30" in u for u in arch.requests))  # a daily file of a published month
            again = len(arch.requests)
            nmf.load_symbol_daily_from("AAAUSDT", start="2025-01-01", end="2026-09-02", fetch=arch, directory=with_dir)
            downloads = [u for u in arch.requests[again:] if u.startswith(bsa.DATA_URL)]
            self.assertEqual(downloads, [])  # incremental: everything cached
            clipped = nmf.load_symbol_daily_from("AAAUSDT", start="2025-01-01", end="2026-09-01", fetch=arch,
                                                 directory=with_dir)
            self.assertEqual(clipped.index[-1], _utc("2026-09-01"))

    def test_cascade_loader_start_month_and_unlisted(self):
        arch = FakeArchive()
        tmp = Path(tempfile.mkdtemp())
        for month, day in (("2026-09", "2026-09-30"), ("2026-08", "2026-08-31")):
            arch.add_zip(f"data/futures/um/monthly/klines/AAAUSDT/1h/AAAUSDT-1h-{month}.zip", hourly_csv(day, 10.0))
        for d in ("2026-10-08", "2026-10-09"):
            arch.add_zip(f"data/futures/um/daily/klines/AAAUSDT/1h/AAAUSDT-1h-{d}.zip", hourly_csv(d, 11.0))
            arch.add_zip(f"data/futures/um/daily/markPriceKlines/AAAUSDT/1h/AAAUSDT-1h-{d}.zip", hourly_csv(d, 11.0))
            arch.add_zip(f"data/futures/um/daily/metrics/AAAUSDT/AAAUSDT-metrics-{d}.zip",
                         "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
                         "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
                         f"{d} 00:00:00,AAAUSDT,100,1000,1,1,1,1\n")
        arch.add_zip("data/futures/um/monthly/fundingRate/AAAUSDT/AAAUSDT-fundingRate-2026-09.zip",
                     "calc_time,funding_interval_hours,last_funding_rate\n1790000000000,8,0.0001\n")
        data = nmf.load_cascade_data(["AAAUSDT", "GONEUSDT"], replay_start=_utc("2026-10-08"), end="2026-10-09",
                                     fetch=arch, futures_dir=tmp / "f", metrics_dir=tmp / "m", workers=2)
        self.assertEqual(data["unlisted"], ["GONEUSDT"])
        self.assertEqual(list(data["perp"]), ["AAAUSDT"])
        self.assertGreaterEqual(data["perp"]["AAAUSDT"].index[0], _utc("2026-10-07"))
        downloaded = [u for u in arch.requests if u.startswith(bsa.DATA_URL) and u.endswith(".zip")]
        self.assertTrue(downloaded)
        self.assertFalse([u for u in downloaded if "2026-08" in u or "-2026-09.zip" in u])  # months before the start
        self.assertEqual(len(data["oi"]["AAAUSDT"]), 2)
        self.assertEqual(len(data["funding"]["AAAUSDT"]), 0)  # the start month's funding file is not published yet
        self.assertEqual(nmf.covered_through(data["funding"])["AAAUSDT"], nmf.EPOCH)


if __name__ == "__main__":
    unittest.main()
