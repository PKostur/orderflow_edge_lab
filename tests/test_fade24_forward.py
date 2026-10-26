"""Offline tests (synthetic data, no network) for the fade-24h bracket paper forward watch."""

from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.parse
import zipfile

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_spot_archive as bsa
from orderflow_edge_lab import fade24_forward as f24
from orderflow_edge_lab import leverage_bracket as lb
from orderflow_edge_lab import leverage_bracket_v2 as v2

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "fade24_forward_v1.json").read_text(encoding="utf-8"))
START = pd.Timestamp("2026-10-17", tz="UTC")
DAY = 1440


def make_sd(name: str, index: int, grid: f24.Grid, seed: int, *, nan_from: int | None = None, vol: float = 0.002,
            f_idx: np.ndarray | None = None, f_rate: np.ndarray | None = None,
            cover: pd.Timestamp | None = None, holes: list | None = None) -> f24.SymbolData:
    rng = np.random.default_rng(seed)
    n = grid.length
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, vol, n)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.0007, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.0007, n)))
    hlc = np.vstack([high, low, close]).astype(np.float32).astype(np.float64)
    hlc[:, 0] = np.nan  # the first bar of the grid ends at index 1
    if nan_from is not None:
        hlc[:, nan_from:] = np.nan
    return f24.SymbolData(name, index, hlc, np.zeros(0, dtype=np.int64) if f_idx is None else f_idx,
                          np.zeros(0) if f_rate is None else f_rate,
                          cover if cover is not None else START + pd.Timedelta(days=3650), holes or [])


def make_panel(days: int = 25, **kw) -> tuple[dict[str, f24.SymbolData], f24.Grid, pd.Timestamp]:
    data_end = START + pd.Timedelta(days=days)
    grid = f24.make_grid(START, data_end)
    panel = {f"S{i}USDT": make_sd(f"S{i}USDT", i, grid, 100 + i, **kw) for i in range(3)}
    return panel, grid, data_end


class GridAndBoundaryTests(unittest.TestCase):
    def test_grid_starts_two_days_before_the_start_and_first_index_is_strictly_after(self):
        grid = f24.make_grid(START, START + pd.Timedelta(days=5))
        self.assertEqual(grid.origin, START - pd.Timedelta(days=2))
        self.assertEqual(grid.stamp(grid.ref_idx), START)
        self.assertEqual(grid.stamp(grid.first_idx), START + pd.Timedelta(minutes=1))

    def test_no_position_opens_at_or_before_the_start(self):
        panel, grid, data_end = make_panel()
        report = f24.evaluate(CONFIG, panel, grid, data_end, as_of=data_end)
        first_seen = []
        for book in f24.BOOKS:
            for t in report["trades"][book]:
                self.assertGreater(pd.Timestamp(t["open_time"]), START)
            for p in report["open_positions"][book]:
                self.assertGreater(pd.Timestamp(p["entry_time"]), START)
            first_seen += [pd.Timestamp(t["open_time"]) for t in report["trades"][book]]
        # a symbol with a non-zero 24h move opens at the first close after the start
        self.assertIn(START + pd.Timedelta(minutes=1), first_seen)

    def test_a_bar_at_the_start_instant_is_not_a_scored_entry(self):
        panel, grid, _ = make_panel()
        spec = f24.BOOK_SPECS["fade24_F1"]
        direction = lb.entry_directions("E2", panel["S0USDT"].hlc[2], symbol_index=0, seed=f24.SEED)
        self.assertNotEqual(direction[grid.ref_idx], 0)  # the rule has a signal at the start instant ...
        run = f24.run_symbol(spec, panel["S0USDT"], grid)
        self.assertGreaterEqual(int(run.trades.open_idx[0]), grid.first_idx)  # ... but it is not taken


class EngineIdentityTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        self.panel, self.grid, self.data_end = make_panel(days=30)
        sd = self.panel["S0USDT"]
        sd.f_idx = np.arange(480, self.grid.length, 480, dtype=np.int64)
        sd.f_rate = rng.normal(0.0, 1e-4, len(sd.f_idx))

    def test_trades_equal_the_v2_walk_for_every_book(self):
        sd = self.panel["S0USDT"]
        for name, spec in f24.BOOK_SPECS.items():
            with self.subTest(book=name):
                cell = spec.cell
                self.assertEqual(cell.name.rsplit("_", 1)[0], "E2_L2_TP15_S2_T168" if spec.entry == "E2" else
                                 "E0_L2_TP15_S2_T168")
                H, L, C = sd.hlc
                direction = lb.entry_directions(cell.entry, C, symbol_index=0, seed=f24.SEED)
                ref = v2.walk_bracket_v2(H, L, C, direction, cell.leverage, cell.tp, cell.stop,
                                         start_idx=self.grid.first_idx, max_hold=cell.max_hold, through=cell.through)
                mine = f24.run_symbol(spec, sd, self.grid)
                k = len(ref)
                self.assertGreater(k, 0)
                for field in ("open_idx", "close_idx", "side", "code", "ambiguous"):
                    np.testing.assert_array_equal(getattr(mine.trades, field)[:k], getattr(ref, field), err_msg=field)
                # the extra trades are positions the engine drops because their 7-day window is not complete
                extra = mine.trades.open_idx[k:] + cell.max_hold > self.grid.length - 1
                self.assertTrue(extra.all())
                ref_econ = v2.trade_economics_v2(ref, C, cell.leverage, cell.tp, sd.f_idx, sd.f_rate, cell.stop,
                                                 cell.fee)
                for key in ("gross", "fee", "funding", "net"):
                    np.testing.assert_allclose(mine.econ[key][:k], ref_econ[key], err_msg=key)

    def test_mean_net_equals_run_cell_v2_on_stored_float32_arrays(self):
        sd = self.panel["S0USDT"]
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            np.save(d / "S0USDT.npy", sd.hlc.astype(np.float32))
            np.savez(d / "S0USDT_funding.npz", idx=sd.f_idx, rate=sd.f_rate)
            sample = {"start_idx": self.grid.first_idx, "n_days": 30, "split_day": 15}
            for name, spec in f24.BOOK_SPECS.items():
                with self.subTest(book=name):
                    stats = v2.run_cell_v2(spec.cell, d, ["S0USDT"], sample, seed=f24.SEED, do_account=False)
                    mine = f24.run_symbol(spec, sd, self.grid)
                    k = stats["trades"]
                    self.assertGreater(k, 0)
                    self.assertAlmostEqual(float(mine.econ["net"][:k].mean() * 100.0),
                                           stats["net_ev_pct_margin_per_trade"], places=9)

    def test_account_equals_the_v2_account_on_the_scored_trades(self):
        report = f24.evaluate(CONFIG, self.panel, self.grid, self.data_end, as_of=self.data_end)
        spec = f24.BOOK_SPECS["fade24_F1"]
        eff = f24.freshness(self.panel, self.grid.length - 1, self.grid)["effective_end_idx"]
        runs = [f24.run_symbol(spec, sd, self.grid) for sd in self.panel.values()]
        o = np.concatenate([r.trades.open_idx for r in runs])
        c = np.concatenate([r.trades.close_idx for r in runs])
        n = np.concatenate([r.econ["net"] for r in runs])
        keep = c <= eff
        n_days = (eff - self.grid.ref_idx) // DAY
        acct = v2.simulate_account_v2(o[keep], c[keep], n[keep], n_days=n_days, sample_start_idx=self.grid.ref_idx)
        expected = v2.daily_returns_v2(acct["daily_equity"])
        got = list(report["daily_returns"]["fade24_F1"].values())
        np.testing.assert_allclose(got, expected)
        self.assertEqual(report["forward"]["fade24_F1"]["trades"], int(keep.sum()))


class RandomControlTests(unittest.TestCase):
    def test_random_book_uses_the_config_seed_and_symbol_index(self):
        self.assertEqual(f24.SEED, 20261017)
        self.assertIn("20261017", CONFIG["books"]["random_F1"])
        panel, grid, _ = make_panel()
        sd = panel["S2USDT"]
        run = f24.run_symbol(f24.BOOK_SPECS["random_F1"], sd, grid)
        bits = np.random.default_rng([20261017, 2]).integers(0, 2, size=grid.length) * 2 - 1
        np.testing.assert_array_equal(run.trades.side, bits[run.trades.open_idx])
        other = f24.run_symbol(f24.BOOK_SPECS["random_F1"], sd, grid, seed=20261013)  # v1's seed differs
        self.assertFalse(np.array_equal(run.trades.side[:5], other.trades.side[:5]) and
                         np.array_equal(run.trades.open_idx[:5], other.trades.open_idx[:5]))

    def test_trades_do_not_change_when_the_grid_grows(self):
        long_panel, long_grid, _ = make_panel(days=40)
        short_grid = f24.make_grid(START, START + pd.Timedelta(days=22))
        sd = long_panel["S2USDT"]
        cut = f24.SymbolData(sd.name, sd.index, sd.hlc[:, :short_grid.length].copy(), sd.f_idx, sd.f_rate, sd.cover)
        for name in ("random_F1", "fade24_F1"):
            spec = f24.BOOK_SPECS[name]
            short = f24.run_symbol(spec, cut, short_grid).trades
            full = f24.run_symbol(spec, sd, long_grid).trades
            k = len(short)
            self.assertGreater(k, 1)
            for field in ("open_idx", "close_idx", "side", "code"):
                np.testing.assert_array_equal(getattr(short, field), getattr(full, field)[:k], err_msg=field)


class ScoringTests(unittest.TestCase):
    def test_open_positions_are_listed_outside_the_scored_series(self):
        panel, grid, data_end = make_panel(days=25)
        report = f24.evaluate(CONFIG, panel, grid, data_end, as_of=data_end)
        for book in f24.BOOKS:
            opens = report["open_positions"][book]
            self.assertTrue(opens)  # every symbol has a position that needs unpublished bars
            open_times = {(p["symbol"], p["entry_time"]) for p in opens}
            scored = {(t["symbol"], t["open_time"]) for t in report["trades"][book]}
            self.assertFalse(open_times & scored)
            self.assertEqual(report["forward"][book]["trades"], len(report["trades"][book]))
            for p in opens:
                self.assertIn("unrealized_gross_pct_margin", p)
            self.assertEqual(report["forward"][book]["open_positions"], len(opens))

    def test_a_resolved_position_is_scored_before_its_time_stop_window_is_complete(self):
        grid = f24.make_grid(START, START + pd.Timedelta(days=4))
        n = grid.length
        close = np.full(n, 100.0)
        close[: grid.ref_idx + 1] = np.linspace(105.0, 100.0, grid.ref_idx + 1)  # falling 24h before: E2 goes long
        close[grid.first_idx + 300:] = 110.0  # +10% >= take-profit (7.5% of price)
        hlc = np.vstack([close * 1.0001, close * 0.9999, close])
        hlc[:, 0] = np.nan
        sd = f24.SymbolData("AAAUSDT", 0, hlc, np.zeros(0, dtype=np.int64), np.zeros(0), START + pd.Timedelta(days=99))
        run = f24.run_symbol(f24.BOOK_SPECS["fade24_F1"], sd, grid)
        self.assertEqual(int(run.trades.code[0]), lb.CODE_TP)
        self.assertEqual(int(run.trades.side[0]), 1)
        self.assertLess(int(run.trades.close_idx[0]) - int(run.trades.open_idx[0]), 10080)

    def test_trade_rows_and_day_blocks_are_consistent(self):
        panel, grid, data_end = make_panel()
        report = f24.evaluate(CONFIG, panel, grid, data_end, as_of=data_end)
        for book in f24.BOOKS:
            fwd = report["forward"][book]
            rows = report["trades"][book]
            self.assertAlmostEqual(fwd["mean_net_pct_margin_per_trade"], np.mean([r["net_pct_margin"] for r in rows]))
            self.assertAlmostEqual(fwd["take_profit_share"] + fwd["stop_share"] + fwd["time_stop_share"] +
                                   fwd["liquidation_share"], 1.0)
            lo, hi = fwd["ev_ci95_pct_margin"]
            self.assertLessEqual(lo, hi)


class PendingTests(unittest.TestCase):
    def test_a_lagging_symbol_makes_the_books_pending_from_its_last_day(self):
        full, grid, data_end = make_panel(days=25)
        end_idx = grid.length - 1
        lag_from = end_idx - int(1.5 * DAY)
        panel = dict(full)
        panel["S1USDT"] = make_sd("S1USDT", 1, grid, 101, nan_from=lag_from)
        report = f24.evaluate(CONFIG, panel, grid, data_end, as_of=data_end)
        base = f24.evaluate(CONFIG, full, grid, data_end, as_of=data_end)
        self.assertEqual(report["pending"]["lagging_symbols"], ["S1USDT"])
        self.assertEqual(report["pending"]["stalled_or_delisted_symbols"], [])
        eff = (lag_from - 1) // DAY * DAY
        self.assertEqual(report["freshness"]["effective_end_idx"], eff)
        self.assertEqual(len(report["daily_returns"]["fade24_F1"]), (eff - grid.ref_idx) // DAY)
        self.assertLess(len(report["daily_returns"]["fade24_F1"]), len(base["daily_returns"]["fade24_F1"]))
        limit = grid.stamp(eff)
        for book in f24.BOOKS:
            for t in report["trades"][book]:
                self.assertLessEqual(pd.Timestamp(t["close_time"]), limit)

    def test_an_old_gap_is_a_stopped_contract_not_pending(self):
        full, grid, data_end = make_panel(days=25)
        end_idx = grid.length - 1
        panel = dict(full)
        panel["S1USDT"] = make_sd("S1USDT", 1, grid, 101, nan_from=end_idx - 5 * DAY)
        report = f24.evaluate(CONFIG, panel, grid, data_end, as_of=data_end)
        base = f24.evaluate(CONFIG, full, grid, data_end, as_of=data_end)
        self.assertEqual(report["pending"]["lagging_symbols"], [])
        self.assertEqual(report["pending"]["stalled_or_delisted_symbols"], ["S1USDT"])
        self.assertEqual(len(report["daily_returns"]["fade24_F1"]), len(base["daily_returns"]["fade24_F1"]))

    def test_funding_pending_flags_trades_in_an_unpublished_month_and_the_replay_clears_them(self):
        grid = f24.make_grid(START, START + pd.Timedelta(days=30))
        f_idx = np.arange(480, grid.length, 480, dtype=np.int64)
        rate = np.full(len(f_idx), 3e-4)
        cut = grid.ref_idx + 12 * DAY
        pub = f_idx < cut  # settlements of a published first part only
        mk = lambda keep, cover: {  # noqa: E731
            "S0USDT": make_sd("S0USDT", 0, grid, 100, f_idx=f_idx[keep], f_rate=rate[keep], cover=cover)}
        data_end = grid.stamp(grid.length - 1)
        early = f24.evaluate(CONFIG, mk(pub, grid.stamp(cut)), grid, data_end, as_of=data_end)
        later = f24.evaluate(CONFIG, mk(np.ones(len(f_idx), bool), START + pd.Timedelta(days=3650)), grid, data_end,
                             as_of=data_end)
        rows_e, rows_l = early["trades"]["fade24_F1"], later["trades"]["fade24_F1"]
        self.assertEqual([(r["open_time"], r["close_time"]) for r in rows_e],
                         [(r["open_time"], r["close_time"]) for r in rows_l])
        self.assertTrue(any(r["funding_pending"] for r in rows_e))
        self.assertTrue(any(not r["funding_pending"] for r in rows_e))
        self.assertFalse(any(r["funding_pending"] for r in rows_l))
        self.assertEqual(early["forward"]["fade24_F1"]["funding_pending_trades"],
                         sum(r["funding_pending"] for r in rows_e))
        for a, b in zip(rows_e, rows_l):
            if a["funding_pending"]:
                self.assertNotEqual(a["net_pct_margin"], b["net_pct_margin"])  # zeros replaced by the real rates
            else:
                self.assertAlmostEqual(a["net_pct_margin"], b["net_pct_margin"])

    def test_funding_gap_zero_filled_flag(self):
        grid = f24.make_grid(START, START + pd.Timedelta(days=30))
        hole = (grid.stamp(grid.ref_idx + 5 * DAY), grid.stamp(grid.ref_idx + 6 * DAY))
        sd = make_sd("S0USDT", 0, grid, 100, holes=[hole])
        report = f24.evaluate(CONFIG, {"S0USDT": sd}, grid, grid.stamp(grid.length - 1), as_of=START)
        for r in report["trades"]["fade24_F1"]:
            overlaps = pd.Timestamp(r["close_time"]) > hole[0] and pd.Timestamp(r["open_time"]) < hole[1]
            self.assertEqual(r["funding_gap_zero_filled"], overlaps)


def with_hole(sd: f24.SymbolData, a: int, b: int) -> f24.SymbolData:
    hlc = sd.hlc.copy()
    hlc[:, a:b + 1] = np.nan
    return f24.SymbolData(sd.name, sd.index, hlc, sd.f_idx, sd.f_rate, sd.cover, sd.holes)


class HoleTests(unittest.TestCase):
    def setUp(self):
        self.panel, self.grid, self.data_end = make_panel(days=30)
        self.end_idx = self.grid.length - 1

    def test_a_recent_hole_caps_scoring_like_a_lag(self):
        a = self.end_idx - int(1.5 * DAY)  # inside the 3-day window
        panel = dict(self.panel)
        panel["S1USDT"] = with_hole(self.panel["S1USDT"], a, a + DAY - 1)
        report = f24.evaluate(CONFIG, panel, self.grid, self.data_end, as_of=self.data_end)
        self.assertEqual(report["pending"]["hole_pending_symbols"], ["S1USDT"])
        self.assertEqual(report["freshness"]["effective_end_idx"], (a - 1) // DAY * DAY)
        self.assertEqual(report["pending"]["holes"]["S1USDT"][0]["status"], "pending")
        for book in f24.BOOKS:
            for t in report["trades"][book]:
                self.assertLessEqual(pd.Timestamp(t["close_time"]), self.grid.stamp(a - 1))
                self.assertFalse(t["bars_missing_in_window"])

    def test_an_old_hole_is_permanent_and_flags_trades_over_it(self):
        a = self.grid.ref_idx + 6 * DAY + 1
        panel = dict(self.panel)
        for name in panel:
            panel[name] = with_hole(panel[name], a, a + DAY - 1)
        report = f24.evaluate(CONFIG, panel, self.grid, self.data_end, as_of=self.data_end)
        base = f24.evaluate(CONFIG, self.panel, self.grid, self.data_end, as_of=self.data_end)
        self.assertEqual(report["pending"]["hole_pending_symbols"], [])
        self.assertEqual(report["pending"]["holes"]["S0USDT"][0]["status"], "permanent")
        self.assertEqual(report["freshness"]["effective_end_idx"], base["freshness"]["effective_end_idx"])
        lo, hi = self.grid.stamp(a), self.grid.stamp(a + DAY - 1)
        flagged = 0
        for t in report["trades"]["fade24_F1"]:
            over = pd.Timestamp(t["close_time"]) >= lo and pd.Timestamp(t["open_time"]) - pd.Timedelta(minutes=1440) <= hi
            self.assertEqual(t["bars_missing_in_window"], over)
            flagged += over
        self.assertGreater(flagged, 0)
        self.assertEqual(report["forward"]["fade24_F1"]["trades_bars_missing_in_window"], flagged)

    def test_late_publication_of_a_missing_day_changes_no_scored_trade(self):
        a = self.end_idx - int(1.5 * DAY)
        holed = dict(self.panel)
        for name in ("S0USDT", "S2USDT"):
            holed[name] = with_hole(self.panel[name], a, a + DAY - 1)
        before = f24.evaluate(CONFIG, holed, self.grid, self.data_end, as_of=self.data_end)
        after = f24.evaluate(CONFIG, self.panel, self.grid, self.data_end, as_of=self.data_end)
        for book in f24.BOOKS:
            kept = {(t["symbol"], t["open_time"]): t for t in after["trades"][book]}
            self.assertTrue(before["trades"][book])
            for t in before["trades"][book]:
                self.assertEqual(kept[(t["symbol"], t["open_time"])], t)
            for k, v in before["daily_returns"][book].items():
                self.assertAlmostEqual(after["daily_returns"][book][k], v, places=12)


class GridGrowthTests(unittest.TestCase):
    def test_scored_trades_and_daily_returns_never_change_as_the_grid_grows(self):
        full_grid = f24.make_grid(START, START + pd.Timedelta(days=40))
        full = {f"S{i}USDT": make_sd(f"S{i}USDT", i, full_grid, 300 + i) for i in range(3)}
        hole_a = full_grid.ref_idx + 9 * DAY + 5  # a day-long hole inside S1's span
        full["S1USDT"] = with_hole(full["S1USDT"], hole_a, hole_a + DAY - 1)
        prev = None
        for days in (8, 13, 19, 26, 33, 40):
            end = START + pd.Timedelta(days=days)
            grid = f24.make_grid(START, end)
            panel = {k: f24.SymbolData(v.name, v.index, v.hlc[:, :grid.length].copy(), v.f_idx, v.f_rate, v.cover)
                     for k, v in full.items()}
            rep = f24.evaluate(CONFIG, panel, grid, end, as_of=end)
            if prev is not None:
                for book in f24.BOOKS:
                    now = {(t["symbol"], t["open_time"]): t for t in rep["trades"][book]}
                    for t in prev["trades"][book]:
                        self.assertEqual(now.get((t["symbol"], t["open_time"])), t, (days, book))
                    for k, v in prev["daily_returns"][book].items():
                        self.assertAlmostEqual(rep["daily_returns"][book][k], v, places=12)
            prev = rep
        self.assertTrue(prev["trades"]["fade24_F1"])


class InterimFieldTests(unittest.TestCase):
    def test_interim_fields(self):
        panel, grid, data_end = make_panel(days=30)
        report = f24.evaluate(CONFIG, panel, grid, data_end, as_of=data_end)
        self.assertEqual(report["interim_biased_until"], "2026-10-27T00:00:00+00:00")
        self.assertIn("fast take-profits", report["interim_censoring_note"])
        eff = pd.Timestamp(report["freshness"]["effective_end"])
        for book in f24.BOOKS:
            fwd = report["forward"][book]
            mature = fwd["matured_entry_cohort"]
            self.assertLessEqual(mature["n"], fwd["trades"])
            if mature["n"]:
                lo, hi = mature["ev_ci95_pct_margin"]
                self.assertLessEqual(lo, hi)
            mtm = fwd["open_positions_mark_to_market"]
            self.assertEqual(mtm["n"], len(report["open_positions"][book]))
            self.assertAlmostEqual(mtm["sum_unrealized_net_pct_margin"],
                                   sum(p["unrealized_gross_pct_margin"] - 0.28 for p in report["open_positions"][book]))
            for row in report["closed_not_yet_scored"][book]:
                self.assertGreater(pd.Timestamp(row["close_time"]), eff)
            self.assertEqual(len(report["closed_not_yet_scored"][book]), fwd["closed_trades_not_yet_scored"])

    def test_a_scored_trade_at_or_before_the_start_is_an_error(self):
        panel, grid, data_end = make_panel()
        fresh = f24.freshness(panel, grid.length - 1, grid)
        books = {n: f24.run_book(f24.BOOK_SPECS[n], panel, grid, fresh) for n in f24.BOOKS}
        books["random_F1"].trades[0]["open_time"] = START.isoformat()
        with self.assertRaises(f24.Fade24Error):
            f24.build_report(CONFIG, books, fresh, as_of=data_end, data_end=data_end)


class ChainCohortDigestTests(unittest.TestCase):
    def setUp(self):
        self.panel, self.grid, self.data_end = make_panel(days=40)
        self.a = self.grid.ref_idx + 8 * DAY + 5
        self.b = self.a + DAY - 1
        self.holed = dict(self.panel)
        self.holed["S1USDT"] = with_hole(self.panel["S1USDT"], self.a, self.b)

    def test_chain_flag_marks_every_later_trade_of_the_symbol(self):
        rep = f24.evaluate(CONFIG, self.holed, self.grid, self.data_end, as_of=self.data_end)
        a_time = self.grid.stamp(self.a)
        for book in f24.BOOKS:
            rows = rep["trades"][book]
            for t in rows:
                expect = t["symbol"] == "S1USDT" and pd.Timestamp(t["open_time"]) > a_time
                self.assertEqual(t["chain_after_permanent_hole"], expect)
            self.assertEqual(rep["forward"][book]["trades_chain_after_permanent_hole"],
                             sum(t["chain_after_permanent_hole"] for t in rows))
            self.assertGreater(rep["forward"][book]["trades_chain_after_permanent_hole"], 0)

    def test_a_recent_hole_does_not_set_the_chain_flag(self):
        a = self.grid.length - 1 - int(1.5 * DAY)
        panel = dict(self.panel)
        panel["S1USDT"] = with_hole(self.panel["S1USDT"], a, a + DAY - 1)
        rep = f24.evaluate(CONFIG, panel, self.grid, self.data_end, as_of=self.data_end)
        self.assertFalse(any(t["chain_after_permanent_hole"] for t in rep["trades"]["fade24_F1"]))

    def test_matured_cohort_excludes_entries_by_entry_time_only(self):
        rep = f24.evaluate(CONFIG, self.holed, self.grid, self.data_end, as_of=self.data_end)
        eff = pd.Timestamp(rep["freshness"]["effective_end"])
        lo = self.grid.stamp(self.a) - pd.Timedelta(minutes=10080)
        hi = self.grid.stamp(self.b) + pd.Timedelta(minutes=1440)
        for book in f24.BOOKS:
            expected = 0
            for t in rep["trades"][book]:
                o = pd.Timestamp(t["open_time"])
                in_zone = t["symbol"] == "S1USDT" and lo <= o <= hi
                expected += (o <= eff - pd.Timedelta(minutes=10080)) and not in_zone
            cohort = rep["forward"][book]["matured_entry_cohort"]
            self.assertEqual(cohort["n"], expected)
            self.assertIn("omitted_matured_age_entries_closed_after_scoring_end", cohort)
            self.assertIn("omitted_matured_age_entries_still_open_or_stalled", cohort)
            self.assertIn("stalled", cohort["definition"])
        clean = f24.evaluate(CONFIG, self.panel, self.grid, self.data_end, as_of=self.data_end)
        self.assertLess(rep["forward"]["fade24_F1"]["matured_entry_cohort"]["n"],
                        clean["forward"]["fade24_F1"]["matured_entry_cohort"]["n"])

    def test_note_points_to_the_matured_cohort(self):
        rep = f24.evaluate(CONFIG, self.panel, self.grid, self.data_end, as_of=self.data_end)
        self.assertIn("matured_entry_cohort", rep["interim_censoring_note"])
        self.assertIn("at any date", rep["interim_censoring_note"])

    def test_digests_are_stable_and_old_days_survive_growth(self):
        one = f24.evaluate(CONFIG, self.holed, self.grid, self.data_end, as_of=self.data_end)
        two = f24.evaluate(CONFIG, self.holed, self.grid, self.data_end, as_of=self.data_end)
        self.assertEqual(one["scored_day_digests"], two["scored_day_digests"])
        for book in f24.BOOKS:
            self.assertEqual(set(one["scored_day_digests"][book]), set(one["daily_returns"][book]))
        end = START + pd.Timedelta(days=30)
        grid = f24.make_grid(START, end)
        cut = {k: f24.SymbolData(v.name, v.index, v.hlc[:, :grid.length].copy(), v.f_idx, v.f_rate, v.cover)
               for k, v in self.holed.items()}
        early = f24.evaluate(CONFIG, cut, grid, end, as_of=end)
        self.assertEqual(f24.compare_digests(early["scored_day_digests"], one["scored_day_digests"]),
                         {b: [] for b in f24.BOOKS})

    def test_compare_digests_flags_changed_days_only(self):
        prev = {"b": {"d1": "x", "d2": "y"}}
        self.assertEqual(f24.compare_digests(prev, {"b": {"d1": "x", "d2": "z", "d3": "n"}}), {"b": ["d2"]})
        self.assertEqual(f24.compare_digests(None, {"b": {"d1": "x"}}), {"b": []})
        self.assertEqual(f24.compare_digests(prev, {"c": {"d1": "x"}}), {"c": []})

    def test_a_late_file_after_a_permanent_hole_changes_a_digest_and_the_dashboard_logs_it(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("dashboard_snapshot", ROOT / "scripts" / "dashboard_snapshot.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        before = f24.evaluate(CONFIG, self.holed, self.grid, self.data_end, as_of=self.data_end)
        after = f24.evaluate(CONFIG, self.panel, self.grid, self.data_end, as_of=self.data_end)  # file arrived late
        self.assertTrue(any(f24.compare_digests(before["scored_day_digests"], after["scored_day_digests"]).values()))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            row1 = {"watch_id": "fade24-forward-v1", "run_id": 1, "scored_day_digests": before["scored_day_digests"]}
            mod.track_revisions([row1], out, "t1")
            self.assertEqual(row1["revised_days"], {b: [] for b in f24.BOOKS})
            self.assertNotIn("scored_day_digests", row1)
            self.assertFalse((out / "fade24_revision_log.jsonl").exists())
            row2 = {"watch_id": "fade24-forward-v1", "run_id": 2, "scored_day_digests": after["scored_day_digests"]}
            mod.track_revisions([row2], out, "t2")
            self.assertTrue(any(row2["revised_days"].values()))
            lines = (out / "fade24_revision_log.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["run_id"], 2)
            row3 = {"watch_id": "fade24-forward-v1", "run_id": 3, "scored_day_digests": after["scored_day_digests"]}
            mod.track_revisions([row3], out, "t3")  # stored digests are the latest: no new revision
            self.assertFalse(any(row3["revised_days"].values()))
            self.assertEqual(len((out / "fade24_revision_log.jsonl").read_text(encoding="utf-8").splitlines()), 1)


class ReportTests(unittest.TestCase):
    def test_pre_start_report_has_no_scored_day(self):
        grid = f24.make_grid(START, START - pd.Timedelta(days=1))
        report = f24.evaluate(CONFIG, {}, grid, START - pd.Timedelta(days=1), as_of="2026-10-14")
        self.assertEqual(report["status"], "PRE_START")
        for book in f24.BOOKS:
            self.assertEqual(report["daily_returns"][book], {})
            self.assertEqual(report["forward"][book]["days"], 0)
            self.assertEqual(report["forward"][book]["trades"], 0)
        self.assertIsNone(report["review"]["reading"])

    def test_all_stamps_are_after_the_start_and_claims_are_false(self):
        panel, grid, data_end = make_panel()
        report = f24.evaluate(CONFIG, panel, grid, data_end, as_of=data_end)
        self.assertEqual(report["status"], "COLLECTING")
        self.assertEqual(report["prospective_start_utc"], "2026-10-17T00:00:00+00:00")
        self.assertEqual(report["watch_id"], "fade24-forward-v1")
        stamps = [t for series in report["daily_returns"].values() for t in series]
        self.assertTrue(stamps)
        self.assertTrue(all(t > report["prospective_start_utc"] for t in stamps))
        first = sorted(report["daily_returns"]["fade24_F1"])[0]
        self.assertEqual(first, "2026-10-18T00:00:00+00:00")  # the realized day 10-17 is stamped 10-18
        self.assertTrue(report["claims"])
        self.assertFalse(any(report["claims"].values()))
        self.assertEqual(report["claims"], CONFIG["claims"])
        json.dumps(report, allow_nan=False, default=f24._json_default)

    def test_a_stamp_at_or_before_the_start_is_an_error(self):
        panel, grid, data_end = make_panel()
        fresh = f24.freshness(panel, grid.length - 1, grid)
        books = {n: f24.run_book(f24.BOOK_SPECS[n], panel, grid, fresh) for n in f24.BOOKS}
        books["fade24_F1"].daily.index = books["fade24_F1"].daily.index - pd.Timedelta(days=1)
        with self.assertRaises(f24.Fade24Error):
            f24.build_report(CONFIG, books, fresh, as_of=data_end, data_end=data_end)
        with self.assertRaises(f24.Fade24Error):
            f24.build_report({**CONFIG, "watch_id": "other"}, books, fresh, as_of=data_end, data_end=data_end)

    def test_review_reading_needs_180_scored_days_and_180_days_since_start(self):
        panel, grid, data_end = make_panel()  # 25 scored days only
        late = f24.evaluate(CONFIG, panel, grid, data_end, as_of=START + pd.Timedelta(days=200))
        self.assertTrue(late["review_window_open"])
        self.assertEqual(late["review"]["scored_days"], 25)
        self.assertEqual(late["review"]["as_of_days_since_start"], 200)
        self.assertIsNone(late["review"]["reading"])
        data_end = START + pd.Timedelta(days=185)
        grid = f24.make_grid(START, data_end)
        panel = {"S0USDT": make_sd("S0USDT", 0, grid, 100)}
        early = f24.evaluate(CONFIG, panel, grid, data_end, as_of=START + pd.Timedelta(days=179))
        full = f24.evaluate(CONFIG, panel, grid, data_end, as_of=START + pd.Timedelta(days=180))
        self.assertFalse(early["review_window_open"])
        self.assertIsNone(early["review"]["reading"])
        self.assertTrue(full["review_window_open"])
        self.assertGreaterEqual(full["review"]["scored_days"], 180)
        self.assertIn(full["review"]["reading"], ("not contradicted", "contradicted"))

    def test_review_reading_function(self):
        self.assertEqual(f24.review_reading(-0.5, 1.2), "not contradicted")
        self.assertEqual(f24.review_reading(0.66, 1.2), "not contradicted")
        self.assertEqual(f24.review_reading(0.67, 1.2), "contradicted")
        self.assertEqual(f24.review_reading(-1.0, 0.65), "contradicted")
        self.assertIsNone(f24.review_reading(None, None))


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_is_deterministic_and_seed_dependent(self):
        rng = np.random.default_rng(3)
        cnt = rng.integers(0, 6, 60).astype(float)
        total = cnt * rng.normal(0.01, 0.1, 60)
        a, b = f24.day_block_ev(total, cnt), f24.day_block_ev(total, cnt)
        self.assertEqual(a, b)
        self.assertNotEqual(a, f24.day_block_ev(total, cnt, seed=1))
        self.assertAlmostEqual(a["ev"], total.sum() / cnt.sum() * 100.0)
        self.assertLess(a["lo"], a["hi"])
        self.assertTrue(a["lo"] <= a["ev"] <= a["hi"])
        other = rng.normal(0.0, 0.1, 60) * cnt
        d1, d2 = f24.day_block_diff(total, cnt, other, cnt), f24.day_block_diff(total, cnt, other, cnt)
        self.assertEqual(d1, d2)
        self.assertAlmostEqual(d1["diff"], (total.sum() - other.sum()) / cnt.sum() * 100.0)
        self.assertLessEqual(d1["lo"], d1["hi"])

    def test_bootstrap_parameters_follow_the_config(self):
        scoring = CONFIG["scoring"]
        self.assertIn("mean block 10", scoring)
        self.assertIn("2000 draws", scoring)
        self.assertIn("seed 20261017", scoring)
        self.assertEqual((f24.BOOTSTRAP_BLOCK, f24.BOOTSTRAP_DRAWS, f24.SEED), (10, 2000, 20261017))

    def test_empty_inputs(self):
        z = np.zeros(0)
        self.assertIsNone(f24.day_block_ev(z, z)["ev"])
        self.assertIsNone(f24.day_block_diff(z, z, z, z)["diff"])


# --------------------------------------------------------------------------------------------- fake archive


class FakeArchive:
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
            keys = sorted(k for k in self.files if k.startswith(q["prefix"][0]))
            body = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys)
            return (f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{body}'
                    f"<IsTruncated>false</IsTruncated></ListBucketResult>").encode()
        key = urllib.parse.unquote(url[len(bsa.DATA_URL):])
        if key.endswith(".CHECKSUM"):
            real = key[: -len(".CHECKSUM")]
            if real in self.files:
                return (sha256(self.files[real]).hexdigest() + "  " + Path(real).name).encode()
        elif key in self.files:
            return self.files[key]
        raise bsa.ArchiveHTTPError(url, 404)


def minute_csv(day: str, base: float, minutes: int = DAY) -> str:
    t0 = pd.Timestamp(day, tz="UTC")
    rows = []
    for m in range(minutes):
        ot = int((t0 + pd.Timedelta(minutes=m)).timestamp() * 1000)
        px = base + 0.001 * m
        rows.append(f"{ot},{px},{px + 0.01},{px - 0.01},{px},10,{ot + 59999},1000,5,1,1,0")
    return "\n".join(rows) + "\n"


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.arch = FakeArchive()
        for day in ("2026-10-15", "2026-10-16", "2026-10-17"):
            self.arch.add_zip(f24.kline_key("BTCUSDT", day), minute_csv(day, 100.0))
        for day in ("2026-10-15", "2026-10-17"):  # AAA misses 10-16
            self.arch.add_zip(f24.kline_key("AAAUSDT", day), minute_csv(day, 10.0))
        self.start = START

    def test_latest_published_day_walks_back(self):
        self.assertEqual(f24.latest_published_day(pd.Timestamp("2026-10-19 10:00", tz="UTC"), self.arch),
                         pd.Timestamp("2026-10-17", tz="UTC"))
        with self.assertRaises(f24.Fade24Error):
            f24.latest_published_day(pd.Timestamp("2026-10-19", tz="UTC"), f24.CountingFetch(FakeArchive()),
                                     max_back=2)

    def test_run_loads_daily_files_into_the_grid_and_records_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {**CONFIG, "prospective_start_utc": "2026-10-17T00:00:00Z"}
            fetch = f24.CountingFetch(self.arch)
            report = f24.run(cfg, as_of=pd.Timestamp("2026-10-17 12:00", tz="UTC"), fetch=fetch,
                             symbols=["BTCUSDT", "AAAUSDT", "GONEUSDT"], cache_root=Path(tmp), workers=2)
            cov = report["data"]["coverage"]
            self.assertEqual(report["data"]["latest_published_day"], "2026-10-17")
            self.assertEqual(report["data_end_utc"], "2026-10-18T00:00:00+00:00")
            self.assertEqual(cov["BTCUSDT"]["bars"], 3 * DAY)
            self.assertEqual(cov["AAAUSDT"]["days_missing"], ["2026-10-16"])
            self.assertEqual(cov["AAAUSDT"]["bars"], 2 * DAY)
            self.assertEqual(cov["GONEUSDT"]["bars"], 0)
            self.assertEqual(cov["BTCUSDT"]["funding_covered_through"], "1970-01-01T00:00:00+00:00")
            # AAA misses the whole day 10-16 inside its published span: a recent hole is pending like a lag, so
            # nothing from 10-16 on is scored (the start 10-17 is therefore not scored yet)
            self.assertEqual(report["status"], "PRE_START")
            self.assertEqual(report["pending"]["hole_pending_symbols"], ["AAAUSDT"])
            self.assertEqual(report["pending"]["holes"]["AAAUSDT"][0]["status"], "pending")
            self.assertEqual(report["pending"]["lagging_symbols"], [])
            n_first = fetch.requests
            zips_first = sum(1 for u in self.arch.requests if u.endswith(".zip"))
            f24.run(cfg, as_of=pd.Timestamp("2026-10-17 12:00", tz="UTC"), fetch=f24.CountingFetch(self.arch),
                    symbols=["BTCUSDT", "AAAUSDT"], cache_root=Path(tmp), workers=2)
            self.assertEqual(sum(1 for u in self.arch.requests if u.endswith(".zip")), zips_first)  # cache reused
            self.assertGreater(n_first, 0)

    def test_run_before_any_bars_is_pre_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {**CONFIG, "prospective_start_utc": "2026-10-20T00:00:00Z"}
            fetch = f24.CountingFetch(self.arch)
            report = f24.run(cfg, as_of=pd.Timestamp("2026-10-17 12:00", tz="UTC"), fetch=fetch,
                             symbols=["BTCUSDT", "AAAUSDT"], cache_root=Path(tmp), workers=2)
            self.assertEqual(report["status"], "PRE_START")
            self.assertEqual(report["data"]["symbols_loaded"], 0)
            self.assertEqual(report["daily_returns"]["fade24_F1"], {})

    def test_stale_tail_is_trimmed_and_float32_is_used(self):
        grid = f24.make_grid(START, START + pd.Timedelta(days=4))
        n = grid.length
        px = 100.0 + np.sin(np.arange(n) / 50.0)
        frame = pd.DataFrame({"open": px, "high": px + 0.1, "low": px - 0.1, "close": px},
                             index=pd.Index(np.arange(n), dtype="int64"))
        frame.iloc[n - 2000:, :] = float(px[n - 2001])  # frozen placeholder bars
        hlc = f24.to_hlc([frame.iloc[1:]], n)
        self.assertTrue(np.isnan(hlc[:, 0]).all())
        trimmed, start = f24.trim_stale(hlc)
        self.assertEqual(start, n - 2000)
        self.assertTrue(np.isnan(trimmed[2, n - 2000:]).all())
        self.assertEqual(float(hlc[2, 10]), float(np.float32(px[10])))


if __name__ == "__main__":
    unittest.main()
