"""Trend-core leverage study: 8h bars, symbol mapping, position book, multi-day liquidation, L=1 identity (synthetic)."""

from __future__ import annotations

import io
import json
from pathlib import Path
import urllib.parse
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd

from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import trend_core_leverage as tcl
from orderflow_edge_lab.trend_portfolio_forward import sleeve_daily_returns


def ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def hourly(n_hours: int, start: str = "2024-01-01 01:00", drop: set[int] | None = None) -> pd.DataFrame:
    """1h bars indexed by END time; bar k has open=100+k, high=101+k, low=99+k, close=100.5+k."""
    index = pd.date_range(start, periods=n_hours, freq="1h", tz="UTC")
    k = np.arange(n_hours, dtype=float)
    frame = pd.DataFrame({"open": 100 + k, "high": 101 + k, "low": 99 + k, "close": 100.5 + k}, index=index)
    if drop:
        frame = frame.drop(frame.index[sorted(drop)])
    return frame


def synthetic_8h(n: int, seed: int, drift: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(drift + 0.015 * rng.standard_normal(n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    index = pd.date_range("2022-01-01", periods=n, freq="8h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


CORE = {
    "source": {"symbols": ["AAAUSDT", "BBBUSDT"]},
    "economics": {"round_trip_cost_bps": 20, "max_abs_position": 1},
    "sizing": {"method": "entry_inverse_vol", "window_bars": 180, "target_annual_vol": 0.15, "cap": 1.0,
               "bars_per_year": 1095},
    "strategies": [{"audit_id": "DON8", "family": "donchian_breakout", "parameters": {"lookback": 55}},
                   {"audit_id": "EMA8", "family": "ema_tsmom",
                    "parameters": {"fast": 24, "slow": 96, "min_atr_spread": 0.25}}],
}


class BarTests(unittest.TestCase):
    def test_8h_bars_from_1h(self):
        # first 1h bar ENDS 01:00 (opens 00:00): 16 hourly bars -> bars opening 00:00 and 08:00
        bars, dropped = tcl.build_8h_bars(hourly(16))
        self.assertEqual(dropped, 0)
        self.assertEqual(list(bars.index), [ts("2024-01-01 00:00"), ts("2024-01-01 08:00")])
        first = bars.iloc[0]
        self.assertEqual((first["open"], first["high"], first["low"], first["close"]), (100.0, 108.0, 99.0, 107.5))
        self.assertEqual(bars.iloc[1]["open"], 108.0)

    def test_incomplete_bar_is_dropped_and_counted(self):
        bars, dropped = tcl.build_8h_bars(hourly(24, drop={9}))
        self.assertEqual(dropped, 1)
        self.assertEqual(list(bars.index), [ts("2024-01-01 00:00"), ts("2024-01-01 16:00")])

    def test_bars_open_at_00_08_16(self):
        bars, _ = tcl.build_8h_bars(hourly(48, start="2024-01-01 06:00"))
        self.assertTrue(set(bars.index.hour) <= {0, 8, 16})


class SymbolTests(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(tcl.binance_symbol("BTC_USDT"), "BTCUSDT")
        self.assertEqual(tcl.binance_symbol("ENA_USDT"), "ENAUSDT")

    def test_available_and_unavailable_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "perp" / "monthly" / "BTCUSDT"
            folder.mkdir(parents=True)
            (folder / "BTCUSDT-1h-2024-01.zip").write_bytes(b"x")
            available, missing = tcl.split_symbols(["BTC_USDT", "ZZZ_USDT"], Path(tmp))
        self.assertEqual(available, {"BTC_USDT": "BTCUSDT"})
        self.assertEqual(missing, ["ZZZ_USDT"])

    def test_loader_reads_ohlc_from_cached_zip(self):
        rows = "1704067200000,100,105,99,104,10,1704070799999,1000,5,0,0,0\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", rows)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "perp" / "monthly" / "AAAUSDT"
            folder.mkdir(parents=True)
            (folder / "AAAUSDT-1h-2024-01.zip").write_bytes(buf.getvalue())
            frame = tcl.load_hourly("AAAUSDT", "perp", directory=Path(tmp))
        self.assertEqual(list(frame.index), [ts("2024-01-01 01:00")])
        self.assertEqual((frame["open"].iloc[0], frame["high"].iloc[0], frame["low"].iloc[0]), (100.0, 105.0, 99.0))


class BookTests(unittest.TestCase):
    def test_position_book_from_known_episode(self):
        episodes = [{"sleeve": "DON8:AAAUSDT", "symbol": "AAAUSDT", "entry_time": ts("2024-01-01 08:00"),
                     "exit_time": ts("2024-01-05 00:00"), "side": -1, "weight": -0.5, "entry_price": 100.0,
                     "net_return": 0.02, "terminal": False}]
        book = tcl.position_book(episodes, n_sleeves=4)
        row = book.iloc[0]
        self.assertAlmostEqual(row["weight"], -0.125)
        self.assertAlmostEqual(row["unit_return"], -0.04)
        self.assertEqual(row["mark_key"], "AAAUSDT")
        self.assertGreater((row["exit_time"] - row["entry_time"]).days, 1)

    def test_run_sleeves_matches_repo_sleeve_daily_returns_and_ledger(self):
        frames = {"AAAUSDT": synthetic_8h(900, 1), "BBBUSDT": synthetic_8h(900, 2, drift=-0.002)}
        sleeves, episodes = tcl.run_sleeves(CORE, frames, None)
        expected = sleeve_daily_returns(CORE, frames, None)
        pd.testing.assert_frame_equal(sleeves, expected)
        self.assertGreater(len(episodes), 0)
        for e in episodes:
            self.assertEqual(e["side"], int(np.sign(e["weight"])))
            self.assertGreater(e["exit_time"], e["entry_time"])
            self.assertEqual(e["entry_price"], frames[e["symbol"]].loc[e["entry_time"], "open"])


class LiquidationTests(unittest.TestCase):
    def episode(self, side=1):
        return {"sleeve": "S", "symbol": "X", "entry_time": ts("2024-01-01 00:00"), "exit_time": ts("2024-01-06 00:00"),
                "side": side, "weight": 1.0 if side > 0 else -1.0, "entry_price": 100.0, "net_return": 0.0,
                "terminal": False}

    def mark(self, low_on_day3: float) -> pd.DataFrame:
        index = pd.date_range("2024-01-01 01:00", "2024-01-06 00:00", freq="1h", tz="UTC")
        low = np.full(len(index), 99.0)
        high = np.full(len(index), 101.0)
        low[index.get_loc(ts("2024-01-03 12:00"))] = low_on_day3
        return pd.DataFrame({"high": high, "low": low}, index=index)

    def test_liquidation_inside_multi_day_hold_triggers_at_threshold(self):
        # L=10: threshold 9.5%.  Low 90.5 is exactly 9.5% below the entry fill; 90.6 is not enough.
        t, adv = tcl.episode_adverse_path(self.episode(), self.mark(90.5))
        self.assertEqual(tcl.liquidation_time(t, adv, 10), ts("2024-01-03 12:00"))
        t, adv = tcl.episode_adverse_path(self.episode(), self.mark(90.6))
        self.assertIsNone(tcl.liquidation_time(t, adv, 10))
        self.assertEqual(tcl.liquidation_time(t, adv, 5), None)  # 5x threshold is 19.5%
        self.assertEqual(tcl.liquidation_time(t, adv, 20), ts("2024-01-03 12:00"))  # 4.5% threshold, 9.4% move

    def test_short_uses_high(self):
        index = pd.date_range("2024-01-01 01:00", "2024-01-06 00:00", freq="1h", tz="UTC")
        high = np.full(len(index), 101.0)
        high[100] = 110.0
        frame = pd.DataFrame({"high": high, "low": np.full(len(index), 99.0)}, index=index)
        t, adv = tcl.episode_adverse_path(self.episode(side=-1), frame)
        self.assertEqual(tcl.liquidation_time(t, adv, 10), index[100])

    def test_simulate_level_wipes_margin_on_liquidation_interval_and_zeroes_rest(self):
        # 8h intervals stamped at the closing open: 2024-01-01 08:00 ... ; episode S: entry 01-01 00:00, exit 01-06 00:00
        stamps = pd.date_range("2024-01-01 08:00", "2024-01-07 00:00", freq="8h", tz="UTC")
        series = pd.Series(0.001, index=stamps)
        series.loc[ts("2024-01-06 08:00")] = 0.999 - 1.0  # exit interval: exit cost only
        series.loc[series.index > ts("2024-01-06 08:00")] = 0.0  # flat after the exit
        ep = self.episode()
        ep["net_return"] = 1.001 ** 15 * 0.999 - 1.0  # 15 own intervals, then the exit factor 0.999
        path = tcl.episode_adverse_path(ep, self.mark(80.0))
        out = tcl.simulate_level({"S": series}, [ep], [path], 10)
        self.assertEqual(len(out["liquidations"]), 1)
        daily = out["daily"]
        # liquidation at 01-03 12:00 -> interval stamped 01-03 16:00 -> day stamp 01-04
        self.assertAlmostEqual(daily[ts("2024-01-03")], 1.01 ** 3 - 1.0)
        # day 01-04: intervals stamped 01-03 08:00 (own, removed), 16:00 (loss > margin -> floor), 01-04 00:00 (zero)
        self.assertEqual(daily[ts("2024-01-04")], -1.0)
        self.assertTrue(np.allclose(daily[daily.index > ts("2024-01-04")], 0.0, atol=1e-12))

    def test_leverage_one_reproduces_unlevered_account_return(self):
        frames = {"AAAUSDT": synthetic_8h(900, 3), "BBBUSDT": synthetic_8h(900, 4)}
        run = tcl.run_sleeves_detailed(CORE, frames, None)
        marks = {s: pd.DataFrame({"high": f["high"].to_numpy(), "low": f["low"].to_numpy()},
                                 index=f.index + pd.Timedelta(hours=8)) for s, f in frames.items()}
        paths = [tcl.episode_adverse_path(e, marks[e["symbol"]]) for e in run.episodes]
        out = tcl.simulate_level(run.intervals, run.episodes, paths, 1)
        self.assertEqual(out["liquidations"], [])
        pd.testing.assert_series_equal(out["daily"], run.daily.mean(axis=1).clip(lower=-1.0), check_freq=False)

    def test_exit_factors_are_exit_costs_on_engine_data(self):
        # no funding: X is exactly 1 - |position at exit| x 10 bps, so in [0.999, 1]; a wrong split would drift away
        frames = {"AAAUSDT": synthetic_8h(900, 7), "BBBUSDT": synthetic_8h(900, 8, drift=-0.002)}
        run = tcl.run_sleeves_detailed(CORE, frames, None)
        checked = flips = 0
        for name, r in run.intervals.items():
            stamps = pd.DatetimeIndex(r.index)
            eps = sorted((e for e in run.episodes if e["sleeve"] == name), key=lambda e: e["entry_time"])
            pos = [tcl.episode_positions(stamps, e) for e in eps]
            xs = tcl.episode_exit_factors(1.0 + r.to_numpy(), pos, [e["net_return"] for e in eps])
            flips += sum(a[1] == b[0] for a, b in zip(pos, pos[1:]))
            for x in xs:
                if x is not None:
                    self.assertGreaterEqual(x, 0.999 - 1e-9)
                    self.assertLessEqual(x, 1.0 + 1e-12)
                    checked += 1
        self.assertGreater(checked, 5)
        self.assertGreater(flips, 0)  # the shared exit/entry interval is exercised

    def test_every_leverage_level_runs_on_engine_data_and_stays_in_bounds(self):
        frames = {"AAAUSDT": synthetic_8h(900, 9), "BBBUSDT": synthetic_8h(900, 10, drift=-0.002)}
        run = tcl.run_sleeves_detailed(CORE, frames, None)
        marks = {s: pd.DataFrame({"high": f["high"].to_numpy(), "low": f["low"].to_numpy()},
                                 index=f.index + pd.Timedelta(hours=8)) for s, f in frames.items()}
        paths = [tcl.episode_adverse_path(e, marks[e["symbol"]]) for e in run.episodes]
        counts = []
        for level in (1, 2, 5, 10, 20):
            out = tcl.simulate_level(run.intervals, run.episodes, paths, level)
            self.assertGreaterEqual(out["daily"].min(), -1.0)
            counts.append(len(out["liquidations"]))
        self.assertEqual(counts, sorted(counts))
        self.assertGreater(counts[-1], 0)

    def test_assess_small_run_is_consistent(self):
        frames = {"AAAUSDT": synthetic_8h(900, 5), "BBBUSDT": synthetic_8h(900, 6)}
        marks = {s: pd.DataFrame({"high": f["high"].to_numpy(), "low": f["low"].to_numpy()},
                                 index=f.index + pd.Timedelta(hours=8)) for s, f in frames.items()}
        cfg = lev.LeverageConfig(paths=200, horizon_days=60)
        res = tcl.assess(CORE, frames, None, marks, samples={"whole": ("2022-01-01", "2022-12-31"),
                                                              "from_2023": ("2022-06-01", "2022-12-31")}, config=cfg)
        one = res["levels"]["whole"]["1"]
        self.assertEqual(one["n_liquidations"], 0)
        self.assertAlmostEqual(one["final_equity"], res["unlevered_check_final_equity"], places=9)
        liqs = [res["levels"]["whole"][str(L)]["n_liquidations"] for L in cfg.levels]
        self.assertEqual(liqs, sorted(liqs))  # more leverage never means fewer liquidations


class EpisodeBookkeepingTests(unittest.TestCase):
    """Liquidations of several episodes of one sleeve on the 8h grid.  Bar k opens at 2024-01-01 00:00 + 8k h; interval k
    (bar k open -> bar k+1 open) is stamped at the open of bar k+1.  Daily stamps: 00:00, i.e. every third interval."""

    L = 10

    @staticmethod
    def bar(k: int) -> pd.Timestamp:
        return ts("2024-01-01 00:00") + pd.Timedelta(hours=8 * k)

    def stamps(self, n: int) -> pd.DatetimeIndex:
        return pd.DatetimeIndex([self.bar(k + 1) for k in range(n)])

    def episode(self, entry_bar: int, exit_bar: int, net: float, weight: float = 0.5) -> dict:
        return {"sleeve": "S", "symbol": "X", "entry_time": self.bar(entry_bar), "exit_time": self.bar(exit_bar),
                "side": 1, "weight": weight, "entry_price": 100.0, "net_return": net, "terminal": False}

    @staticmethod
    def mark(crashes: list[str], start="2024-01-01 01:00", end="2024-01-07 00:00") -> pd.DataFrame:
        index = pd.date_range(start, end, freq="1h", tz="UTC")
        low = np.full(len(index), 99.0)
        for when in crashes:
            low[index.get_loc(ts(when))] = 90.0  # 10% below the entry fill 100: liquidates 10x (threshold 9.5%)
        return pd.DataFrame({"high": np.full(len(index), 101.0), "low": low}, index=index)

    def simulate(self, factors: list[float], episodes: list[dict], crashes: list[str], other: float = 0.001):
        stamps = self.stamps(len(factors))
        intervals = {"S": pd.Series(np.array(factors) - 1.0, index=stamps),
                     "T": pd.Series(other, index=stamps)}  # a second sleeve that no liquidation touches
        mark = self.mark(crashes)
        paths = [tcl.episode_adverse_path(e, mark) for e in episodes]
        return tcl.simulate_level(intervals, episodes, paths, self.L)

    def test_two_liquidated_episodes_same_day_both_losses_booked(self):
        # A: bars 6..7 (01-03 00:00 -> 08:00), liquidated 04:00; B: bars 7..9 (01-03 08:00 -> 01-04 00:00), liquidated
        # 12:00.  Intervals 6, 7, 8 are all stamped in (01-03 00:00, 01-04 00:00] -> one daily stamp 01-04.
        xa, xb, a_first, b_first, f8 = 0.999, 0.999, 1.01, 0.99, 1.02
        factors = [1.0] * 6 + [a_first, xa * b_first, f8, xb, 1.0, 1.0]
        net_a = a_first * xa - 1.0
        net_b = b_first * f8 * xb - 1.0
        episodes = [self.episode(6, 7, net_a), self.episode(7, 9, net_b)]
        out = self.simulate(factors, episodes, ["2024-01-03 04:00", "2024-01-03 12:00"])
        self.assertEqual(len(out["liquidations"]), 2)
        keep = 1.0 - 0.5 * (1.0 + 0.005 * self.L)  # 0.475 of the sleeve capital at entry survives
        day = out["daily"][ts("2024-01-04")]
        sleeve_s = keep * keep - 1.0  # both losses, nothing divided out; interval 8 (B's own) is 0
        sleeve_t = 1.01 ** 3 - 1.0  # the untouched sleeve: 3 intervals x 10 x 0.1%
        self.assertAlmostEqual(day, (sleeve_s + sleeve_t) / 2.0, places=12)
        # interval 9 (B's exit cost) is removed, the sleeve is flat: only the other sleeve earns on 01-05
        self.assertAlmostEqual(out["daily"][ts("2024-01-05")], (0.0 + (1.01 ** 3 - 1.0)) / 2.0, places=12)

    def test_exit_at_0800_then_new_episode_keeps_first_day_pnl_and_entry_cost(self):
        # A: bars 3..7, liquidated 01-02 12:00 (interval 4), scheduled exit 01-03 08:00 (bar 7).  B enters at that same
        # open (bar 7, entry cost inside its first interval), runs to bar 10 (01-04 08:00), never liquidated.
        a_first, f4, f5, f6, xa = 1.01, 0.98, 1.0, 1.005, 0.999
        b_first, f8, f9, xb = 0.9985, 1.01, 0.995, 0.999  # b_first includes B's entry cost (15 bps) and its return
        factors = [1.0] * 3 + [a_first, f4, f5, f6, xa * b_first, f8, f9, xb, 1.0]
        net_a = a_first * f4 * f5 * f6 * xa - 1.0
        net_b = b_first * f8 * f9 * xb - 1.0
        episodes = [self.episode(3, 7, net_a), self.episode(7, 10, net_b)]
        out = self.simulate(factors, episodes, ["2024-01-02 12:00"])
        self.assertEqual(len(out["liquidations"]), 1)
        keep = 1.0 - 0.5 * (1.0 + 0.005 * self.L)
        t_day = 1.01 ** 3 - 1.0
        # group 01-03: intervals 3, 4, 5 -> A's interval 3 -> 0, interval 4 -> loss, interval 5 -> 0
        self.assertAlmostEqual(out["daily"][ts("2024-01-03")], ((keep - 1.0) + t_day) / 2.0, places=12)
        # group 01-04: interval 6 -> 0 (A flat); interval 7 -> ONLY B's first part, levered (entry cost survives, A's exit
        # cost is gone); interval 8 -> B levered
        b_day = (1.0 + self.L * (b_first - 1.0)) * (1.0 + self.L * (f8 - 1.0)) - 1.0
        self.assertAlmostEqual(out["daily"][ts("2024-01-04")], (b_day + t_day) / 2.0, places=12)
        # group 01-05: interval 9 and 10 (B's exit cost, levered)
        b_next = (1.0 + self.L * (f9 - 1.0)) * (1.0 + self.L * (xb - 1.0)) - 1.0
        self.assertAlmostEqual(out["daily"][ts("2024-01-05")], (b_next + t_day) / 2.0, places=12)

    def test_liquidation_on_exit_day_then_new_episode(self):
        # A: bars 6..8 (01-03 00:00 -> 16:00), liquidated 01-03 12:00 (the last interval before its exit); B enters at
        # the exit open (bar 8) and holds to bar 10.  Intervals 6, 7, 8 share the daily stamp 01-04.
        a6, a7, xa, b_first, b9, xb = 1.004, 0.997, 0.999, 1.012, 1.003, 0.999
        factors = [1.0] * 6 + [a6, a7, xa * b_first, b9, xb, 1.0, 1.0]
        net_a = a6 * a7 * xa - 1.0
        net_b = b_first * b9 * xb - 1.0
        episodes = [self.episode(6, 8, net_a), self.episode(8, 10, net_b)]
        out = self.simulate(factors, episodes, ["2024-01-03 12:00"])
        self.assertEqual(len(out["liquidations"]), 1)
        keep = 1.0 - 0.5 * (1.0 + 0.005 * self.L)
        t_day = 1.01 ** 3 - 1.0
        s_day = 1.0 * keep * (1.0 + self.L * (b_first - 1.0)) - 1.0  # interval 6: 0, 7: loss, 8: B first part
        self.assertAlmostEqual(out["daily"][ts("2024-01-04")], (s_day + t_day) / 2.0, places=12)
        # next stamp: B's second interval and exit cost, levered
        s_next = (1.0 + self.L * (b9 - 1.0)) * (1.0 + self.L * (xb - 1.0)) - 1.0
        self.assertAlmostEqual(out["daily"][ts("2024-01-05")], (s_next + t_day) / 2.0, places=12)

    def test_non_liquidated_episode_is_just_the_scaled_intervals(self):
        factors = [1.0] * 6 + [1.01, 0.99, 1.02, 0.999, 1.0, 1.0]
        episodes = [self.episode(6, 9, 1.01 * 0.99 * 1.02 * 0.999 - 1.0)]
        out = self.simulate(factors, episodes, [])
        self.assertEqual(out["liquidations"], [])
        s_day = (1.0 + self.L * 0.01) * (1.0 + self.L * -0.01) * (1.0 + self.L * 0.02) - 1.0
        self.assertAlmostEqual(out["daily"][ts("2024-01-04")], (s_day + 1.01 ** 3 - 1.0) / 2.0, places=12)

    def test_overlapping_episodes_of_one_sleeve_raise(self):
        factors = [1.0] * 12
        episodes = [self.episode(2, 6, 0.0), self.episode(4, 8, 0.0)]
        with self.assertRaises(tcl.TrendCoreLeverageError):
            self.simulate(factors, episodes, ["2024-01-02 04:00"])


class MarkAndFundingTests(unittest.TestCase):
    def test_mark_fallback_fills_holes_after_first_bar_and_counts(self):
        perp = hourly(10, start="2024-01-01 01:00")
        mark = perp.iloc[3:].drop(perp.index[6])  # first mark bar = perp bar 3; a hole at bar 6
        mark = mark.assign(high=mark["high"] + 0.5)
        frame, first, counts = tcl.mark_with_fallback(mark, perp)
        self.assertEqual(first, perp.index[3])
        self.assertEqual(len(frame), 10)
        self.assertEqual(counts, {"before_first_mark": 3, "holes_after_first_mark": 1})
        self.assertEqual(int(frame["is_mark"].sum()), 6)
        self.assertEqual(frame.loc[perp.index[6], "high"], perp.loc[perp.index[6], "high"])  # perp stands in
        self.assertEqual(frame.loc[perp.index[4], "high"], perp.loc[perp.index[4], "high"] + 0.5)  # mark wins

    def test_mark_fallback_with_empty_archive(self):
        perp = hourly(4)
        frame, first, counts = tcl.mark_with_fallback(perp.iloc[0:0], perp)
        self.assertIsNone(first)
        self.assertEqual(counts["before_first_mark"], 4)
        self.assertFalse(frame["is_mark"].any())

    def test_episode_mark_coverage_counts_missing_and_fallback_hours(self):
        perp = hourly(10, start="2024-01-01 01:00")
        mark = perp.iloc[4:].drop([perp.index[5], perp.index[7]])
        frame, _, _ = tcl.mark_with_fallback(mark, perp.drop(perp.index[7]))
        episode = {"entry_time": ts("2024-01-01 00:00"), "exit_time": ts("2024-01-01 08:00")}
        cov = tcl.episode_mark_coverage(episode, frame)
        self.assertEqual(cov["expected"], 8)
        self.assertEqual(cov["present"], 7)  # the perp bar 7 is missing from both archives
        self.assertEqual(cov["fallback"], 5)  # perp bars 0-3 before the first mark bar and the hole at 5

    def test_funding_rule_on_engine_data(self):
        frames = {"AAAUSDT": synthetic_8h(400, 11), "BBBUSDT": synthetic_8h(400, 12)}
        full = {s: pd.Series(0.0001, index=f.index[1:]) for s, f in frames.items()}
        run = tcl.run_sleeves_detailed(CORE, frames, full)  # normal data passes
        self.assertEqual(set(run.funding_coverage), {"DON8:AAAUSDT", "DON8:BBBUSDT", "EMA8:AAAUSDT", "EMA8:BBBUSDT"})
        self.assertGreater(sum(c["held_bar_opens"] for c in run.funding_coverage.values()), 0)
        held: dict[str, set[pd.Timestamp]] = {s: set() for s in frames}
        for e in run.episodes:
            idx = frames[e["symbol"]].index
            held[e["symbol"]].update(idx[idx.get_loc(e["entry_time"]) + 1:idx.get_loc(e["exit_time"]) + 1])
        flat = [x for x in frames["AAAUSDT"].index[1:] if x not in held["AAAUSDT"]]
        self.assertTrue(flat and held["AAAUSDT"] and held["BBBUSDT"])
        tcl.run_sleeves_detailed(CORE, frames, {**full, "AAAUSDT": full["AAAUSDT"].drop(flat[:5])})  # hole while flat
        victim = sorted(held["AAAUSDT"])[3]
        with self.assertRaises(tcl.TrendCoreLeverageError) as ctx:
            tcl.run_sleeves_detailed(CORE, frames, {**full, "AAAUSDT": full["AAAUSDT"].drop(victim)})
        self.assertIn(victim.isoformat(), str(ctx.exception))
        with self.assertRaises(tcl.TrendCoreLeverageError):  # no funding series at all for a symbol with positions
            tcl.run_sleeves_detailed(CORE, frames, {"AAAUSDT": full["AAAUSDT"]})
        # late-starting funding history while positions are held: the engine's own coverage would pass this
        cut = sorted(held["AAAUSDT"])[len(held["AAAUSDT"]) // 2]
        late = full["AAAUSDT"].loc[full["AAAUSDT"].index >= cut]
        with self.assertRaises(tcl.TrendCoreLeverageError):
            tcl.run_sleeves_detailed(CORE, frames, {**full, "AAAUSDT": late})


class FundingGapRuleTests(unittest.TestCase):
    index = pd.date_range("2024-01-01 00:00", periods=30, freq="8h", tz="UTC")

    @staticmethod
    def series(start: str, periods: int, freq: str) -> pd.Series:
        return pd.Series(0.0001, index=pd.date_range(start, periods=periods, freq=freq, tz="UTC"))

    def test_normal_8h_data_passes(self):
        raw = self.series("2024-01-01 08:00", 29, "8h")
        self.assertEqual(tcl.funding_gaps(self.index, raw, [(2, 20)]), ([], 18))

    def test_leading_gap_while_held_fails(self):
        raw = self.series("2024-01-03 00:00", 24, "8h")  # first cached settlement = bar 6, position held from bar 2
        missing, n = tcl.funding_gaps(self.index, raw, [(2, 20)])
        self.assertEqual(n, 18)
        self.assertEqual(len(missing), 3)  # opens 3, 4, 5
        self.assertIn(self.index[3].isoformat(), missing[0])

    def test_hole_while_flat_passes(self):
        raw = self.series("2024-01-01 08:00", 29, "8h").drop(self.index[8:12])
        self.assertEqual(tcl.funding_gaps(self.index, raw, [(2, 7), (12, 20)])[0], [])

    def test_hole_inside_a_held_stretch_fails(self):
        raw = self.series("2024-01-01 08:00", 29, "8h").drop(self.index[9])
        missing, _ = tcl.funding_gaps(self.index, raw, [(2, 20)])
        self.assertEqual(len(missing), 1)
        self.assertIn(self.index[9].isoformat(), missing[0])

    def test_terminal_bar_is_checked(self):
        raw = self.series("2024-01-01 08:00", 28, "8h")  # no settlement at the last open (index 29)
        self.assertEqual(len(tcl.funding_gaps(self.index, raw, [(25, 29)])[0]), 1)

    def test_4h_symbol_missing_one_of_two_settlements_fails(self):
        raw = self.series("2024-01-01 04:00", 58, "4h")
        self.assertEqual(tcl.funding_gaps(self.index, raw, [(2, 20)])[0], [])
        gappy = raw.drop(pd.Timestamp("2024-01-02 12:00", tz="UTC"))  # the 4h settlement inside bar (08:00, 16:00]
        missing, _ = tcl.funding_gaps(self.index, gappy, [(2, 20)])
        self.assertEqual(len(missing), 1)
        self.assertIn("1 of 2", missing[0])

    def test_1h_symbol_expects_eight_per_bar(self):
        raw = self.series("2024-01-01 01:00", 8 * 29, "1h")
        self.assertEqual(tcl.funding_gaps(self.index, raw, [(2, 20)])[0], [])
        missing, _ = tcl.funding_gaps(self.index, raw.drop(raw.index[40]), [(2, 20)])
        self.assertEqual(len(missing), 1)


class HighLowValidationTests(unittest.TestCase):
    def test_nan_or_non_positive_or_inverted_values_fail(self):
        good = hourly(5)
        tcl.validate_high_low(good, "x")
        for column, value in (("high", np.nan), ("low", 0.0), ("low", -1.0), ("high", np.inf)):
            bad = good.copy()
            bad.iloc[2, bad.columns.get_loc(column)] = value
            with self.assertRaises(tcl.TrendCoreLeverageError):
                tcl.validate_high_low(bad, "x")
        inverted = good.copy()
        inverted.iloc[1, inverted.columns.get_loc("high")] = 1.0
        with self.assertRaises(tcl.TrendCoreLeverageError):
            tcl.validate_high_low(inverted, "x")
        with self.assertRaises(tcl.TrendCoreLeverageError):
            tcl.mark_with_fallback(good.iloc[0:0], good.assign(low=np.nan))

    def test_loader_validates(self):
        rows = "1704067200000,100,NaN,99,104,10,1704070799999,1000,5,0,0,0\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", rows)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "mark" / "monthly" / "AAAUSDT"
            folder.mkdir(parents=True)
            (folder / "AAAUSDT-1h-2024-01.zip").write_bytes(buf.getvalue())
            with self.assertRaises(tcl.TrendCoreLeverageError):
                tcl.load_hourly("AAAUSDT", "mark", directory=Path(tmp))


class DescriptiveDiagnosticsTests(unittest.TestCase):
    def test_mark_perp_divergence(self):
        perp = hourly(6)
        mark = perp.copy()
        mark.iloc[3, mark.columns.get_loc("high")] = perp["high"].iloc[3] * 1.05
        out = tcl.mark_perp_divergence(mark, perp)
        self.assertAlmostEqual(out["max_rel_diff_high"], 0.05)
        self.assertEqual(out["at_high"], perp.index[3].isoformat())
        self.assertEqual(out["max_rel_diff_low"], 0.0)
        self.assertEqual(tcl.mark_perp_divergence(perp.iloc[0:0], perp)["bars_compared"], 0)

    def test_top_adverse_excursions_sorted_and_capped(self):
        episodes = [{"sleeve": "S", "symbol": "X", "entry_time": ts("2024-01-01"), "exit_time": ts("2024-01-02"),
                     "side": 1} for _ in range(12)]
        paths = [(np.array([1, 2]), np.array([0.01 * k, 0.01 * (k + 1)])) for k in range(12)]
        cov = [{"fallback": k} for k in range(12)]
        rows = tcl.top_adverse_excursions(episodes, paths, cov)["X"]
        self.assertEqual(len(rows), 10)
        self.assertAlmostEqual(rows[0]["max_adverse_excursion"], 0.12)
        self.assertEqual(rows[0]["perp_fallback_bars"], 11)
        values = [r["max_adverse_excursion"] for r in rows]
        self.assertEqual(values, sorted(values, reverse=True))


class FakeRest:
    """Mock of the public fundingRate endpoint: ``data`` maps symbol -> {settlement time: rate}."""

    def __init__(self, data: dict[str, dict[pd.Timestamp, float]] | None = None, *, error: Exception | None = None,
                 jitter_ms: int = 0):
        self.data, self.error, self.jitter_ms, self.urls = data or {}, error, jitter_ms, []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if self.error is not None:
            raise self.error
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        start, end = int(query["startTime"][0]), int(query["endTime"][0])
        rows = []
        for when, rate in sorted(self.data.get(query["symbol"][0], {}).items()):
            ms = int(when.value // 1_000_000) + self.jitter_ms
            if start <= ms <= end:
                rows.append({"symbol": query["symbol"][0], "fundingTime": ms, "fundingRate": f"{rate:.8f}",
                             "markPrice": "1.0"})
        return json.dumps(rows).encode()


class FundingRestTests(unittest.TestCase):
    """Short held bars are verified on the public REST endpoint (mocked here)."""

    def setUp(self):
        self.frames = {"AAAUSDT": synthetic_8h(400, 11), "BBBUSDT": synthetic_8h(400, 12)}
        idx = self.frames["AAAUSDT"].index
        self.full8 = {s: pd.Series(0.0001, index=f.index[1:]) for s, f in self.frames.items()}
        self.full4_a = pd.Series(0.0001, index=pd.date_range(idx[0] + pd.Timedelta(hours=4), idx[-1], freq="4h"))
        base = tcl.run_sleeves_detailed(CORE, self.frames, self.full8)
        held: set[pd.Timestamp] = set()
        for e in base.episodes:
            if e["symbol"] == "AAAUSDT":
                held.update(idx[idx.get_loc(e["entry_time"]) + 1:idx.get_loc(e["exit_time"]) + 1])
        self.open = sorted(held)[5]  # a held open
        self.half = self.open - pd.Timedelta(hours=4)  # its 4h settlement at the half bar
        self.funding4 = {**self.full8, "AAAUSDT": self.full4_a}

    def test_normal_data_does_not_touch_the_network(self):
        rest = FakeRest()
        run = tcl.run_sleeves_detailed(CORE, self.frames, self.funding4, rest_fetch=rest)
        self.assertEqual(rest.urls, [])
        self.assertEqual(run.funding_rest, {})

    def test_rest_confirmed_skip_passes_and_is_recorded(self):
        # the exchange skipped one 4h settlement: archive and REST both lack it
        archive_series = self.full4_a.drop(self.half)
        rest = FakeRest({"AAAUSDT": {self.open: 0.0001}})
        run = tcl.run_sleeves_detailed(CORE, self.frames, {**self.funding4, "AAAUSDT": archive_series}, rest_fetch=rest)
        entry = run.funding_rest["AAAUSDT"]
        self.assertEqual(entry["repaired_from_rest"], [])
        self.assertEqual([c["open"] for c in entry["confirmed_by_rest"]], [self.open.isoformat()])
        self.assertEqual(entry["confirmed_by_rest"][0]["settlements_present"], 1)
        self.assertEqual(entry["confirmed_by_rest"][0]["settlements_from_interval"], 2)
        self.assertEqual(entry["confirmed_by_rest"][0]["settlements_on_rest"], 1)
        self.assertNotIn("BBBUSDT", run.funding_rest)
        # the account is the one of the archive as it is (nothing invented for the skipped settlement)
        self.assertIn("symbol=AAAUSDT", rest.urls[0])

    def test_rest_supplies_the_missing_settlement_and_the_sleeves_are_rerun_with_it(self):
        reference = tcl.run_sleeves_detailed(CORE, self.frames, self.funding4)
        archive_series = self.full4_a.drop(self.half)
        rest = FakeRest({"AAAUSDT": {k: 0.0001 for k in self.full4_a.index}})
        run = tcl.run_sleeves_detailed(CORE, self.frames, {**self.funding4, "AAAUSDT": archive_series}, rest_fetch=rest)
        entry = run.funding_rest["AAAUSDT"]
        self.assertEqual(entry["confirmed_by_rest"], [])
        self.assertEqual(entry["repaired_from_rest"], [{"settlement": self.half.isoformat(), "rate": 0.0001}])
        for name, series in reference.intervals.items():
            pd.testing.assert_series_equal(run.intervals[name], series)
        # the repaired settlement is not re-queried by the other sleeve of the symbol (its series is already merged)
        self.assertEqual(len(rest.urls), len(set(rest.urls)))

    def test_rest_unreachable_fails(self):
        archive_series = self.full4_a.drop(self.half)
        for error in (OSError("connection refused"), ValueError("bad json")):
            with self.assertRaises(tcl.TrendCoreLeverageError):
                tcl.run_sleeves_detailed(CORE, self.frames, {**self.funding4, "AAAUSDT": archive_series},
                                         rest_fetch=FakeRest(error=error))

    def test_rest_garbage_payload_fails(self):
        with self.assertRaises(tcl.TrendCoreLeverageError):
            tcl.rest_funding("AAAUSDT", self.open - pd.Timedelta(hours=8), self.open, lambda url: b'{"code": -1121}')

    def test_no_rest_configured_fails_as_before(self):
        with self.assertRaises(tcl.TrendCoreLeverageError):
            tcl.run_sleeves_detailed(CORE, self.frames, {**self.funding4, "AAAUSDT": self.full4_a.drop(self.half)})

    def test_zero_settlement_bar_with_empty_rest_fails(self):
        archive_series = self.full4_a.drop([self.half, self.open])
        with self.assertRaises(tcl.TrendCoreLeverageError) as ctx:
            tcl.run_sleeves_detailed(CORE, self.frames, {**self.funding4, "AAAUSDT": archive_series},
                                     rest_fetch=FakeRest({"AAAUSDT": {}}))
        self.assertIn(self.open.isoformat(), str(ctx.exception))

    def test_zero_settlement_bar_is_repaired_when_rest_has_it(self):
        archive_series = self.full4_a.drop([self.half, self.open])
        rest = FakeRest({"AAAUSDT": {k: 0.0001 for k in self.full4_a.index}})
        run = tcl.run_sleeves_detailed(CORE, self.frames, {**self.funding4, "AAAUSDT": archive_series}, rest_fetch=rest)
        times = [r["settlement"] for r in run.funding_rest["AAAUSDT"]["repaired_from_rest"]]
        self.assertEqual(times, [self.half.isoformat(), self.open.isoformat()])

    def test_rest_funding_window_and_jitter(self):
        open_ = ts("2024-01-02 08:00")
        data = {"AAAUSDT": {open_ - pd.Timedelta(hours=8): 0.0002, open_: 0.0003, open_ + pd.Timedelta(hours=8): 0.0004}}
        out = tcl.rest_funding("AAAUSDT", open_ - pd.Timedelta(hours=8), open_, FakeRest(data, jitter_ms=5))
        self.assertEqual(list(out.index), [open_])  # (after, until]: the earlier and later settlements are outside
        self.assertAlmostEqual(out.iloc[0], 0.0003)


class OutputTests(unittest.TestCase):
    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out" / "assessment.json"
            tcl.write_result(path, {"a": 1, "t": pd.Timestamp("2024-01-01", tz="UTC")})
            with self.assertRaises(FileExistsError):
                tcl.write_result(path, {"a": 2})
            self.assertIn('"a": 1', path.read_text(encoding="utf-8"))

    def test_serialization_error_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out" / "assessment.json"
            with self.assertRaises(ValueError):
                tcl.write_result(path, {"a": float("nan")})
            with self.assertRaises(TypeError):
                tcl.write_result(path, {"a": object()})
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
