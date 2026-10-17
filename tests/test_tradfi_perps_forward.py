"""Offline tests (synthetic data only, no network) for the TradFi perps paper forward watch."""

from __future__ import annotations

from datetime import date
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
from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import near_miss_forward as nmf
from orderflow_edge_lab import tradfi_perps_forward as tpf

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "config" / "tradfi_perps_forward_v1.json").read_text(encoding="utf-8"))
UNIVERSE_PATH = ROOT / "research" / "tradfi_perps_forward" / "universe_v1.json"
START = pd.Timestamp("2026-10-19", tz="UTC")
CLOCK = tpf.Clock.from_config(CONFIG)
N = 22
SYMS = [f"S{i:02d}USDT" for i in range(N)]


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz="UTC")


# ------------------------------------------------------------------------------------------------------- fixtures


def funding_frame(rate: float | dict = 0.0, *, first: str = "2026-10-01", through: str = "2026-10-31 16:00",
                  skip_day: str | None = None) -> pd.DataFrame:
    idx = pd.date_range(first, through, freq="8h", tz="UTC")
    if skip_day:
        idx = idx[idx.normalize() != ts(skip_day)]
    return pd.DataFrame({"rate": float(rate), "interval_hours": 8.0}, index=idx)


def make_market(*, grid_start: str = "2026-10-09", horizon: str = "2026-10-27", as_of: str | None = None,
                price=None, high=None, volume=5e6, funding=None, marks=None, yahoo=None, n: int = N,
                last_bar: dict | None = None, unscored=(), yahoo_failed=None, calendar_pending_after=None) -> tpf.Market:
    """``n`` stock perps on a 15m grid.  ``price(i, index) -> Series`` of closes (default flat 100); ``high(i, index,
    close) -> Series`` of bar highs; ``volume`` daily quote volume per symbol (float or callable of i)."""
    grid = pd.date_range(ts(grid_start) + pd.Timedelta(minutes=15), ts(horizon), freq="15min")
    perp = {}
    for i in range(n):
        close = pd.Series(100.0, index=grid) if price is None else price(i, grid)
        hi = close * 1.001 if high is None else high(i, grid, close)
        v = volume(i) if callable(volume) else volume
        frame = pd.DataFrame({"close": close, "high": hi, "low": close * 0.999, "quote_volume": v / 96.0}, index=grid)
        if last_bar and SYMS[i] in last_bar:
            frame = frame.loc[frame.index <= ts(last_bar[SYMS[i]])]
        perp[SYMS[i]] = frame
    hl = {s: f[["high", "low"]] for s, f in perp.items()}
    mk = lc.mark_with_perp_fallback(marks or {}, hl)
    fund = {s: (funding_frame() if funding is None else funding(s)) for s in perp}
    ys = {}
    days = pd.bdate_range(end="2026-11-30", periods=330, tz="UTC")
    for i in range(n):
        close = pd.Series(100.0 * (1.0 + 0.0004 * i) ** np.arange(len(days)), index=days)
        ys[f"Y{i:02d}"] = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "adjclose": close})
    if yahoo:
        ys.update(yahoo)
    stock = [(SYMS[i], f"Y{i:02d}") for i in range(n)]
    return tpf.Market(CLOCK, START, ts(as_of) if as_of else ts(horizon) + pd.Timedelta(hours=1), ts(horizon), perp, mk,
                      fund, ys, stock, {date.fromisoformat(d) for d in unscored},
                      yahoo_failed=dict(yahoo_failed or {}), calendar_pending_after=calendar_pending_after)


def b2_price(i: int, grid: pd.DatetimeIndex) -> pd.Series:
    """Week of 2026-10-19: Friday close 100 (20:00Z), weekend move 0.2% * (i - 10.5) by the signal bar (13:45Z), +1% at
    the entry bar (14:00Z), exit move at 20:00Z: +2% for the bottom quintile (longs), -2% for the top (shorts)."""
    px = pd.Series(100.0, index=grid)
    px.loc[grid > ts("2026-10-16 20:00")] = 100.0 * (1.0 + 0.002 * (i - 10.5))
    px.loc[grid >= ts("2026-10-19 14:00")] *= 1.01
    if i < 4:
        px.loc[grid >= ts("2026-10-19 20:00")] *= 1.02
    elif i >= N - 4:
        px.loc[grid >= ts("2026-10-19 20:00")] *= 0.98
    return px


def monday_run(market: tpf.Market, level: int) -> tpf.BookRun:
    ev = tpf.b2_event(market, date(2026, 10, 19))
    periods, book_end, _ = tpf.weekly_periods([ev], market.horizon)
    return tpf.simulate_book(periods, level, market, book_end)


def stamp_return(run: tpf.BookRun, day: str) -> float:
    series = tpf.daily_series(run.growth, START + pd.Timedelta(days=1), run.book_end)
    return float(series.loc[ts(day)])


# --------------------------------------------------------------------------------------------------------- clock


class ClockTests(unittest.TestCase):
    def test_edt_and_est_weeks(self):
        self.assertEqual(CLOCK.session_open(date(2026, 10, 19)), ts("2026-10-19 13:30"))   # EDT = UTC-4
        self.assertEqual(CLOCK.session_close(date(2026, 10, 19)), ts("2026-10-19 20:00"))
        self.assertEqual(CLOCK.session_open(date(2026, 11, 2)), ts("2026-11-02 14:30"))    # EST = UTC-5 (DST ended 11-01)
        self.assertEqual(CLOCK.session_close(date(2026, 11, 2)), ts("2026-11-02 21:00"))

    def test_holidays_and_early_closes(self):
        self.assertFalse(CLOCK.is_session(date(2026, 11, 26)))          # Thanksgiving
        self.assertFalse(CLOCK.is_session(date(2026, 12, 25)))
        self.assertFalse(CLOCK.is_session(date(2026, 10, 17)))          # Saturday
        self.assertEqual(CLOCK.session_close(date(2026, 11, 27)), ts("2026-11-27 18:00"))   # 13:00 EST early close
        self.assertEqual(CLOCK.session_close(date(2026, 12, 24)), ts("2026-12-24 18:00"))
        with self.assertRaises(tpf.ClockError):
            CLOCK.session_close(date(2026, 11, 26))

    def test_calendar_expires_loudly(self):
        with self.assertRaises(tpf.ClockError):
            CLOCK.is_session(date(2028, 1, 3))

    def test_holiday_monday_week_starts_on_tuesday(self):
        self.assertEqual(CLOCK.week_first_session(date(2027, 1, 18)), date(2027, 1, 19))
        self.assertEqual(CLOCK.week_first_session(date(2027, 1, 21)), date(2027, 1, 19))
        self.assertEqual(CLOCK.week_first_session(date(2026, 10, 21)), date(2026, 10, 19))
        self.assertEqual(CLOCK.previous_session(date(2027, 1, 19)), date(2027, 1, 15))

    def test_formation_days_first_session_of_month(self):
        got = tpf.formation_sessions(CLOCK, START, ts("2027-01-31"))
        self.assertEqual(got, [date(2026, 10, 19), date(2026, 11, 2), date(2026, 12, 1), date(2027, 1, 4)])

    def test_start_boundary(self):
        self.assertEqual(CLOCK.first_formation_session(START), date(2026, 10, 19))
        # a start after the Monday close moves the first formation to the next session
        self.assertEqual(CLOCK.first_formation_session(ts("2026-10-19 20:30")), date(2026, 10, 20))
        # nothing before the start is a formation or a B2 week; a not yet closed formation day is not due
        self.assertEqual(tpf.formation_sessions(CLOCK, START, ts("2026-10-19 19:59")), [])
        self.assertEqual(tpf.weekend_sessions(CLOCK, START, ts("2026-10-30")), [date(2026, 10, 19), date(2026, 10, 26)])
        self.assertEqual(tpf.weekend_sessions(CLOCK, START, ts("2026-10-18")), [])

    def test_spy_calendar_check_flags_mismatch(self):
        spy = [d for d in CLOCK.sessions_between(date(2026, 10, 19), date(2026, 10, 30)) if d != date(2026, 10, 21)]
        spy.append(date(2026, 10, 24))                                    # a bar on a Saturday
        out = tpf.calendar_check(CLOCK, spy, date(2026, 10, 19), date(2026, 10, 30))
        self.assertEqual(out["sessions_without_bar"], ["2026-10-21"])
        self.assertEqual(out["bars_on_closed_days"], ["2026-10-24"])
        self.assertEqual(out["unscored_sessions"], ["2026-10-21", "2026-10-24"])
        clean = tpf.calendar_check(CLOCK, CLOCK.sessions_between(date(2026, 10, 19), date(2026, 10, 30)),
                                   date(2026, 10, 19), date(2026, 10, 30))
        self.assertEqual(clean["unscored_sessions"], [])

    def test_unscored_session_leaves_the_week_unscored(self):
        mkt = make_market(price=b2_price, unscored=["2026-10-19"])
        ev = tpf.b2_event(mkt, date(2026, 10, 19))
        self.assertEqual(ev.status, "unscored_calendar")
        periods, _, pending = tpf.weekly_periods([ev], mkt.horizon)
        self.assertEqual(periods, [])
        self.assertTrue(pending[0]["unscored"])


# ---------------------------------------------------------------------------------------------- signals and rules


class SignalTests(unittest.TestCase):
    def test_b1_window_uses_previous_closes_only(self):
        days = pd.bdate_range(end="2026-10-19", periods=300, tz="UTC")       # last bar IS the formation day
        adj = pd.Series(np.arange(1, 301, dtype=float), index=days)
        adj.iloc[-1] = 1e9                                                    # the formation day's own bar must not count
        sig = tpf.momentum_signal(adj, date(2026, 10, 19), date(2026, 10, 16))
        closes = adj.iloc[:-1]                                                # up to 2026-10-16
        self.assertAlmostEqual(sig, closes.iloc[-21] / closes.iloc[-252] - 1.0)
        self.assertAlmostEqual(sig, (299 - 20) / (299 - 251) - 1.0)

    def test_b1_needs_253_closes_and_a_fresh_last_close(self):
        days = pd.bdate_range(end="2026-10-16", periods=253, tz="UTC")
        adj = pd.Series(np.linspace(50, 100, 253), index=days)
        self.assertIsNotNone(tpf.momentum_signal(adj, date(2026, 10, 19), date(2026, 10, 16)))
        self.assertIsNone(tpf.momentum_signal(adj.iloc[1:], date(2026, 10, 19), date(2026, 10, 16)))   # 252 closes
        self.assertIsNone(tpf.momentum_signal(adj.iloc[:-1], date(2026, 10, 19), date(2026, 10, 16)))  # stale last close

    def test_quintiles_equal_weight_half_gross_per_leg(self):
        sig = {f"s{i:02d}": float(i) for i in range(23)}
        bottom, top = tpf.quintile_legs(sig)
        self.assertEqual((len(bottom), len(top)), (4, 4))                    # 23 // 5
        self.assertEqual(top, ["s19", "s20", "s21", "s22"])
        self.assertEqual(bottom, ["s00", "s01", "s02", "s03"])
        w = tpf.leg_weights(top, bottom)
        self.assertAlmostEqual(sum(v for v in w.values() if v > 0), 0.5)
        self.assertAlmostEqual(sum(v for v in w.values() if v < 0), -0.5)
        tied = tpf.quintile_legs({f"t{i}": 1.0 for i in range(10)})          # ties: by symbol, deterministic
        self.assertEqual(tied, (["t0", "t1"], ["t8", "t9"]))

    def test_b1_event_longs_top_quintile_shorts_bottom(self):
        mkt = make_market(horizon="2026-10-27")
        ev = tpf.b1_event(mkt, date(2026, 10, 19))
        self.assertEqual(ev.status, "formed")
        self.assertEqual(ev.detail["long"], SYMS[N - 4:])
        self.assertEqual(ev.detail["short"], SYMS[:4])
        self.assertEqual(ev.entry, ts("2026-10-19 20:00"))
        w = ev.weights[tpf.BOOK_B1]
        self.assertAlmostEqual(sum(abs(v) for v in w.values()), 1.0)
        self.assertEqual(set(ev.weights[tpf.BOOK_B0]), set(SYMS))
        self.assertAlmostEqual(sum(ev.weights[tpf.BOOK_B0].values()), 1.0)

    def test_liquidity_filter_and_minimum_names(self):
        low = lambda k: (lambda i: 5e5 if i < k else 5e6)                    # below 1,000,000 USDT per day
        ev = tpf.b1_event(make_market(volume=low(2)), date(2026, 10, 19))
        self.assertEqual(len(ev.eligible), 20)
        self.assertEqual(len(ev.weights[tpf.BOOK_B0]), 20)                   # exactly 20: the book trades
        ev = tpf.b1_event(make_market(volume=low(3)), date(2026, 10, 19))
        self.assertEqual(len(ev.eligible), 19)
        self.assertEqual(ev.weights[tpf.BOOK_B0], {})                        # 19 < 20: flat
        self.assertEqual(ev.weights[tpf.BOOK_B1], {})
        self.assertTrue(ev.detail["b1_flat_min_names"])

    def test_liquidity_is_the_median_of_the_seven_utc_days_before(self):
        idx = pd.date_range("2026-10-11 00:15", "2026-10-19 00:00", freq="15min", tz="UTC")
        vol = pd.Series(1.0, index=idx)
        daily = [2e6, 2e6, 2e6, 9e5, 9e5, 9e5, 9e9]                          # days Oct 12..18 -> median 2e6 (Oct 11 excluded)
        for k, v in enumerate(daily):
            day = ts("2026-10-12") + pd.Timedelta(days=k)
            m = (idx > day) & (idx <= day + pd.Timedelta(days=1))
            vol.loc[m] = v / 96.0
        frame = pd.DataFrame({"quote_volume": vol}, index=idx)
        self.assertAlmostEqual(tpf.median_daily_quote_volume(frame, date(2026, 10, 19)), 2e6)
        self.assertIsNone(tpf.median_daily_quote_volume(frame.loc[frame.index > ts("2026-10-13 00:00")], date(2026, 10, 19)))


# ---------------------------------------------------------------------------------------- B2 timing, costs, funding


class WeekendFadeTests(unittest.TestCase):
    def test_entry_is_the_bar_after_the_signal_bar(self):
        mkt = make_market(price=b2_price)
        ev = tpf.b2_event(mkt, date(2026, 10, 19))
        self.assertEqual(ev.status, "formed")
        self.assertEqual(ev.detail["signal_bar"], "2026-10-19T13:45:00+00:00")
        self.assertEqual(ev.detail["reference_bar"], "2026-10-16T20:00:00+00:00")
        self.assertEqual(ev.entry, ts("2026-10-19 14:00"))
        self.assertEqual(ev.exit, ts("2026-10-19 20:00"))
        for s in ev.eligible:                                                 # signal price != entry price
            self.assertNotAlmostEqual(mkt.prices.exact(s, ts("2026-10-19 13:45")), mkt.prices.exact(s, ts("2026-10-19 14:00")))
        self.assertEqual(ev.detail["long"], SYMS[:4])                          # fade: long the bottom quintile
        self.assertEqual(ev.detail["short"], SYMS[N - 4:])                     # short the top quintile
        periods, _, _ = tpf.weekly_periods([ev], mkt.horizon)
        self.assertEqual(periods[0].entry, ts("2026-10-19 14:00"))
        # return uses the ENTRY bar price: 1x = 0.5*2% + 0.5*2% - 14 bps
        run = monday_run(mkt, 1)
        self.assertAlmostEqual(stamp_return(run, "2026-10-20"), 0.02 - 0.0014, places=12)

    def test_cost_scales_with_leverage_and_return_is_leveraged(self):
        mkt = make_market(price=b2_price)
        for level in (1, 2, 5):
            run = monday_run(mkt, level)
            self.assertAlmostEqual(stamp_return(run, "2026-10-20"), level * (0.02 - 0.0014), places=12)
            self.assertEqual(run.liquidated, [])
            self.assertLess(run.lev_check_max_abs_diff, 1e-12)               # engine == leverage_sim period result
            self.assertAlmostEqual(run.turnover, level * 2.0)                # round trip on gross 1.0

    def test_dst_and_early_close_and_holiday_monday_timestamps(self):
        est = make_market(grid_start="2026-11-20", horizon="2026-12-03")
        ev = tpf.b2_event(est, date(2026, 11, 30))                            # previous session = early close Fri 11-27
        self.assertEqual(ev.detail["reference_bar"], "2026-11-27T18:00:00+00:00")
        self.assertEqual(ev.detail["signal_bar"], "2026-11-30T14:45:00+00:00")  # EST: 09:45 ET = 14:45Z
        self.assertEqual((ev.entry, ev.exit), (ts("2026-11-30 15:00"), ts("2026-11-30 21:00")))
        hol = make_market(grid_start="2027-01-08", horizon="2027-01-21")
        ev = tpf.b2_event(hol, date(2027, 1, 19))                             # Monday 01-18 is a holiday
        self.assertEqual(ev.detail["reference_bar"], "2027-01-15T21:00:00+00:00")
        self.assertEqual(ev.detail["signal_bar"], "2027-01-19T14:45:00+00:00")
        edt = tpf.b2_event(make_market(price=b2_price), date(2026, 10, 19))
        self.assertEqual(edt.detail["signal_bar"], "2026-10-19T13:45:00+00:00")  # EDT: 09:45 ET = 13:45Z

    def test_funding_arithmetic_on_held_notional(self):
        rate = {s: 0.0001 * (i + 1) for i, s in enumerate(SYMS)}
        mkt = make_market(price=b2_price, funding=lambda s: funding_frame(rate[s]))
        run = monday_run(mkt, 2)
        ev = tpf.b2_event(mkt, date(2026, 10, 19))
        w = ev.weights[tpf.BOOK_B2]
        # one settlement (16:00Z) inside the trade; price then = entry price, so notional = 2 * |w| at entry
        paid = sum(2 * w[s] * rate[s] for s in w)
        self.assertAlmostEqual(run.funding_paid, paid, places=12)
        gross = 2 * (0.02 - 0.0014)
        self.assertAlmostEqual(stamp_return(run, "2026-10-20"), gross - paid, places=12)
        self.assertEqual(run.funding_pending_periods, 0)

    def test_funding_pending_zero_filled_then_replaced_when_published(self):
        rate = 0.002
        unpublished = make_market(price=b2_price, funding=lambda s: funding_frame(rate, first="2026-09-01",
                                                                                   through="2026-09-30 16:00"))
        run0 = monday_run(unpublished, 1)
        self.assertEqual(run0.funding_pending_periods, 1)                    # October not published: flagged
        self.assertAlmostEqual(stamp_return(run0, "2026-10-20"), 0.02 - 0.0014, places=12)   # zero-filled
        self.assertEqual(run0.funding_paid, 0.0)
        self.assertAlmostEqual(stamp_return(tpf.BookRun(run0.growth_clean, run0.growth_clean, run0.book_end, [], 0, 0, 0, 0, 0, 0, [], 0, 0),
                                             "2026-10-20"), 0.0)             # excluded from the clean variant
        published = make_market(price=b2_price, funding=lambda s: funding_frame(rate, through="2026-10-31 16:00"))
        run1 = monday_run(published, 1)
        self.assertEqual(run1.funding_pending_periods, 0)                    # the replay replaces the zeros
        longs_minus_shorts = 0.0                                              # symmetric legs, equal rates: net zero
        self.assertAlmostEqual(run1.funding_paid, longs_minus_shorts, places=12)
        unequal = make_market(price=b2_price, funding=lambda s: funding_frame(rate if s in SYMS[:4] else 0.0))
        run2 = monday_run(unequal, 1)
        self.assertAlmostEqual(run2.funding_paid, 4 * 0.125 * rate, places=12)   # the long leg pays, the short leg is flat
        self.assertAlmostEqual(stamp_return(run2, "2026-10-20"), 0.02 - 0.0014 - 4 * 0.125 * rate, places=12)

    def test_funding_hole_inside_a_published_month_is_flagged(self):
        mkt = make_market(price=b2_price, funding=lambda s: funding_frame(0.0, skip_day="2026-10-19"))
        run = monday_run(mkt, 1)
        self.assertEqual(run.funding_gap_periods, 1)
        self.assertEqual(run.funding_pending_periods, 0)

    def test_liquidation_at_5x_on_a_synthetic_gap_uses_mark_with_perp_fallback(self):
        def spike(i, grid, close):
            hi = close * 1.001
            if i == N - 1:                                                    # a short: +25% wick one hour after entry
                hi.loc[grid == ts("2026-10-19 15:00")] = close.loc[grid == ts("2026-10-19 15:00")] * 1.25
            return hi
        mkt = make_market(price=b2_price, high=spike)                         # no mark bars: perp high / low fallback
        w = tpf.b2_event(mkt, date(2026, 10, 19)).weights[tpf.BOOK_B2]
        self.assertAlmostEqual(w[SYMS[N - 1]], -0.125)
        r1, r2, r5 = (monday_run(mkt, lv) for lv in (1, 2, 5))
        self.assertEqual((len(r1.liquidated), len(r2.liquidated), len(r5.liquidated)), (0, 0, 1))   # threshold 19.5% at 5x
        self.assertEqual(r5.liquidated[0]["symbol"], SYMS[N - 1])
        self.assertEqual(r5.liquidated[0]["liquidated_at"], "2026-10-19T15:00:00+00:00")   # the wick bar's end
        self.assertEqual(r5.ffilled_marks, 0)
        # loss = margin + 0.5% of notional = |w| * (1 + 0.005 * 5); the other 7 positions earn 5 * 0.125 * 2% each
        expected = 7 * 5 * 0.125 * 0.02 - 0.125 * (1 + 0.005 * 5) - 5 * 0.0014
        self.assertAlmostEqual(stamp_return(r5, "2026-10-20"), expected, places=12)
        self.assertLess(r5.lev_check_max_abs_diff, 1e-12)
        # a calm mark-price series for the same symbol overrides the perp wick (mark preferred where a bar exists)
        calm = pd.DataFrame({"high": mkt.perp[SYMS[N - 1]]["close"] * 1.001, "low": mkt.perp[SYMS[N - 1]]["close"] * 0.999})
        marked = make_market(price=b2_price, high=spike, marks={SYMS[N - 1]: calm})
        self.assertEqual(len(monday_run(marked, 5).liquidated), 0)

    def test_per_symbol_lag_is_pending_never_a_stale_price(self):
        lag = {SYMS[0]: "2026-10-19 15:00"}                                   # a held long stops before the exit bar
        mkt = make_market(price=b2_price, last_bar=lag, horizon="2026-10-21")
        self.assertEqual(mkt.prices.at(SYMS[0], ts("2026-10-19 20:00")), (None, False))
        ev = tpf.b2_event(mkt, date(2026, 10, 19))
        self.assertEqual(ev.status, "formed")                                  # the entry bar exists
        periods, book_end, pending = tpf.weekly_periods([ev], mkt.horizon)
        run = tpf.simulate_book(periods, 1, mkt, book_end)
        self.assertEqual(run.stalls[0]["symbols"], [SYMS[0]])
        self.assertEqual(run.book_end, ts("2026-10-19"))                       # the day is not scored
        self.assertTrue(tpf.daily_series(run.growth, START + pd.Timedelta(days=1), run.book_end).empty)
        # a lagging liquid symbol at formation time makes the formation pending (not dropped, not ffilled)
        lag_entry = make_market(price=b2_price, last_bar={SYMS[3]: "2026-10-19 13:45"}, horizon="2026-10-21")
        ev2 = tpf.b2_event(lag_entry, date(2026, 10, 19))
        self.assertEqual(ev2.status, "pending")
        self.assertEqual(ev2.lagging, [SYMS[3]])

    def test_hole_inside_published_data_is_carried_and_counted(self):
        mkt = make_market(price=b2_price, horizon="2026-10-21")
        s = SYMS[5]
        f = mkt.perp[s]
        mkt2 = make_market(price=b2_price, horizon="2026-10-21")
        mkt2.perp[s] = f.drop(index=ts("2026-10-20 00:00"))
        mkt2.prices = tpf.Prices(mkt2.perp)
        v, ff = mkt2.prices.at(s, ts("2026-10-20 00:00"))
        self.assertTrue(ff)
        self.assertEqual(v, float(f["close"].loc[ts("2026-10-19 23:45")]))
        self.assertIsNone(mkt2.prices.exact(s, ts("2026-10-20 00:00")))
        # a held name with the hole at a day-end mark: one carried mark, counted
        ev = tpf.b1_event(mkt2, date(2026, 10, 19))
        periods, be, _ = tpf.monthly_periods([ev], tpf.BOOK_B0, mkt2.horizon)
        self.assertEqual(tpf.simulate_book(periods, 1, mkt2, be).ffilled_marks, 1)


# ------------------------------------------------------------------------------------------------- B0 / B1 books


class MonthlyBookTests(unittest.TestCase):
    def test_entry_cost_then_mark_to_market(self):
        def drift(i, grid):
            px = pd.Series(100.0, index=grid)
            if i >= N - 4:
                px.loc[grid >= ts("2026-10-21 00:00")] *= 1.01              # the long names +1%
            return px
        mkt = make_market(price=drift, horizon="2026-10-24")
        ev = tpf.b1_event(mkt, date(2026, 10, 19))
        periods, book_end, _ = tpf.monthly_periods([ev], tpf.BOOK_B1, mkt.horizon)
        self.assertAlmostEqual(periods[0].cost_in, 0.0007)                   # 7 bps per side on gross 1.0
        run = tpf.simulate_book(periods, 1, mkt, book_end)
        series = tpf.daily_series(run.growth, START + pd.Timedelta(days=1), run.book_end)
        self.assertEqual(series.index[0], ts("2026-10-20"))                  # every stamp after the start
        self.assertAlmostEqual(series.loc[ts("2026-10-20")], -0.0007, places=12)
        self.assertAlmostEqual(series.loc[ts("2026-10-21")], 0.005 / 0.9993, places=12)   # day 10-20 ends at the 10-21 00:00 bar
        self.assertAlmostEqual(series.loc[ts("2026-10-22")], 0.0, places=12)
        self.assertEqual(run.trades, 8)
        run2 = tpf.simulate_book(periods, 2, mkt, book_end)
        s2 = tpf.daily_series(run2.growth, START + pd.Timedelta(days=1), run2.book_end)
        self.assertAlmostEqual(s2.loc[ts("2026-10-20")], -0.0014, places=12)  # cost scales with leverage

    def test_rebalance_costs_only_the_traded_notional_and_flat_month_exits(self):
        def vol(i):
            return 5e6
        mkt = make_market(horizon="2026-11-05", volume=vol)
        e1, e2 = tpf.b1_event(mkt, date(2026, 10, 19)), tpf.b1_event(mkt, date(2026, 11, 2))
        self.assertEqual(e2.entry, ts("2026-11-02 21:00"))                    # EST close
        periods, _, _ = tpf.monthly_periods([e1, e2], tpf.BOOK_B1, mkt.horizon)
        self.assertEqual(periods[0].exit, e2.entry)
        self.assertAlmostEqual(periods[1].turnover, 0.0)                      # same names, same weights: no trade
        self.assertAlmostEqual(periods[1].cost_in, 0.0)
        # second formation with too few liquid names: flat; the old book is sold (7 bps on gross 1.0)
        flat = make_market(horizon="2026-11-05", volume=lambda i: 5e6)
        for s in SYMS[:5]:
            f = flat.perp[s].copy()
            f.loc[f.index > ts("2026-10-27"), "quote_volume"] = 1.0
            flat.perp[s] = f
        flat.prices = tpf.Prices(flat.perp)
        f1, f2 = tpf.b1_event(flat, date(2026, 10, 19)), tpf.b1_event(flat, date(2026, 11, 2))
        self.assertEqual(f2.weights[tpf.BOOK_B1], {})
        p2, _, _ = tpf.monthly_periods([f1, f2], tpf.BOOK_B1, flat.horizon)
        self.assertAlmostEqual(p2[1].cost_in, 0.0007)
        self.assertEqual(p2[1].weights, {})
        run = tpf.simulate_book(p2, 1, flat, flat.horizon)
        self.assertEqual(run.trades, 8)

    def test_b0_matches_the_equal_weight_basket_and_books_assemble(self):
        mkt = make_market(horizon="2026-10-27", price=b2_price)
        books, info = tpf.compute_books(mkt, CONFIG)
        self.assertEqual(sorted(books), sorted(["B0_equal_weight_long_1x", "B1_xs_momentum_12_1_1x", "B1_xs_momentum_12_1_2x",
                                                 "B2_weekend_fade_1x", "B2_weekend_fade_2x", "B2_weekend_fade_5x"]))
        b2 = books["B2_weekend_fade_1x"].daily
        self.assertAlmostEqual(b2.loc[ts("2026-10-20")], 0.02 - 0.0014, places=12)
        self.assertTrue((b2.index > START).all())
        self.assertEqual(b2.index[-1], ts("2026-10-27"))                      # contiguous, zero-filled, through the data end
        self.assertEqual(len(info["b2_null_inputs"]), 2)                      # Mondays 10-19 and 10-26
        self.assertEqual(sorted(info["b2_null_inputs"][0]["long"]), SYMS[:4])

    def test_pending_formation_stalls_the_book_at_its_day(self):
        mkt = make_market(horizon="2026-10-21", as_of="2026-10-21 01:00", last_bar={SYMS[7]: "2026-10-19 19:00"})
        ev = tpf.b1_event(mkt, date(2026, 10, 19))
        self.assertEqual(ev.status, "pending")
        periods, book_end, pending = tpf.monthly_periods([ev], tpf.BOOK_B1, mkt.horizon)
        self.assertEqual(periods, [])
        self.assertEqual(book_end, ts("2026-10-19"))
        self.assertIn("per-symbol lag", pending[0]["reason"])


# --------------------------------------------------------------------------------------------- report and claims


class ReportTests(unittest.TestCase):
    def test_pre_start_computes_nothing(self):
        mkt = make_market(grid_start="2026-10-05", horizon="2026-10-13", price=lambda i, g: pd.Series(
            100.0 + i + np.arange(len(g)) * 0.01, index=g))
        books, info = tpf.compute_books(mkt, CONFIG)
        self.assertEqual(books, {})
        self.assertEqual(info["events"], {})
        report = tpf.build_report(CONFIG, books, info, as_of="2026-10-13 12:00", data_end=mkt.horizon)
        self.assertEqual(report["status"], "PRE_START")
        self.assertTrue(all(len(v) == 0 for v in report["daily_returns"].values()))
        self.assertTrue(all(v["days"] == 0 and v["cumulative_return"] == 0.0 for v in report["forward"].values()))
        self.assertNotIn("diagnostics", report)

    def test_report_claims_false_and_stamps_after_start(self):
        mkt = make_market(horizon="2026-10-27", price=b2_price)
        books, info = tpf.compute_books(mkt, CONFIG)
        report = tpf.build_report(CONFIG, books, info, as_of="2026-10-27 01:00", data_end=mkt.horizon)
        self.assertEqual(report["status"], "COLLECTING")
        self.assertEqual(report["watch_id"], "tradfi-perps-forward-v1")
        self.assertEqual(report["prospective_start_utc"], "2026-10-19T00:00:00+00:00")
        self.assertTrue(report["claims"])
        self.assertFalse(any(report["claims"].values()))
        stamps = [t for series in report["daily_returns"].values() for t in series]
        self.assertTrue(stamps)
        self.assertTrue(all(t > report["prospective_start_utc"] for t in stamps))
        for key in ("B0_equal_weight_long_1x", "B1_xs_momentum_12_1_1x", "B1_xs_momentum_12_1_2x",
                    "B2_weekend_fade_1x", "B2_weekend_fade_2x", "B2_weekend_fade_5x"):
            self.assertIn(key, report["forward"])
        self.assertIn("beta_to_b0", report["forward"]["B2_weekend_fade_1x"])
        self.assertIn("pending", report)
        json.dumps(report, allow_nan=False, default=nmf._json_default)

    def test_wrong_config_and_scoring_before_the_start_are_rejected(self):
        with self.assertRaises(tpf.TradfiError):
            tpf.build_report({**CONFIG, "watch_id": "other"}, {}, {}, as_of="2026-10-20", data_end=START)
        pre = pd.Series([0.01], index=pd.DatetimeIndex([ts("2026-10-18")]))
        bad = {"B0_equal_weight_long_1x": nmf.BookResult(pre, pre, 1, 0, 0)}
        with self.assertRaises(tpf.TradfiError):
            tpf.build_report(CONFIG, bad, {}, as_of="2026-10-20", data_end=START)


# ------------------------------------------------------------------------------------------------ diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_d1_funding_annualized_only_for_published_post_start_months(self):
        rates = {s: 0.0001 for s in SYMS}
        mkt = make_market(grid_start="2026-10-09", horizon="2026-11-03", funding=lambda s: funding_frame(rates[s]))
        d1 = tpf.d1_funding(mkt, {s: "stock" for s in SYMS}, set(SYMS))
        cell = d1["per_symbol"][SYMS[0]]["months"]["2026-10"]
        self.assertEqual(cell["settlements"], 38)                             # 10-19 08:00 .. 10-31 16:00, strictly after the start
        self.assertAlmostEqual(cell["annualized"], 38 * 0.0001 * 365.0 / 13.0)
        self.assertEqual(d1["per_symbol"][SYMS[0]]["funding_pending_months"], [])
        self.assertAlmostEqual(d1["equal_weighted_by_month"]["2026-10"]["stock_book"], cell["annualized"])
        late = make_market(horizon="2026-12-03", funding=lambda s: funding_frame(rates[s]))
        self.assertIn("2026-11", tpf.d1_funding(late, {}, set())["per_symbol"][SYMS[0]]["funding_pending_months"])

    def test_d2_tracking_deviation_in_bps_on_post_start_sessions(self):
        def px(i, grid):
            p = pd.Series(100.0, index=grid)
            p.loc[grid >= ts("2026-10-19 20:00")] = 101.0                    # perp close at the US close: +100 bps vs Yahoo
            return p
        days = pd.bdate_range("2026-10-12", "2026-10-23", tz="UTC")
        yahoo = {"Y00": pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "adjclose": 100.0}, index=days)}
        mkt = make_market(price=px, horizon="2026-10-22", yahoo=yahoo, n=1)
        out = tpf.d2_tracking(mkt, [(SYMS[0], "Y00", "stock")])
        row = out["per_symbol"][SYMS[0]]
        self.assertGreaterEqual(row["n"], 1)
        self.assertAlmostEqual(row["median_abs_bps"], 100.0, places=6)
        self.assertAlmostEqual(out["pooled"]["stock"]["p95_abs_bps"], 100.0, places=6)

    def test_d3_slope_and_correlation(self):
        days = pd.bdate_range("2026-10-12", "2026-10-23", tz="UTC")
        yahoo = {}
        for i in range(N):
            gap = 0.002 * (i - 10.5) * 0.5                                    # Monday open gap = half the weekend move
            prev_close, d0 = 100.0, ts("2026-10-19")
            frame = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "adjclose": 100.0}, index=days)
            frame.loc[d0, "open"] = prev_close * (1.0 + gap)
            frame.loc[d0, "close"] = prev_close * (1.0 + gap) * (1.0 - 0.5 * gap)    # open-to-close reverses half the gap
            yahoo[f"Y{i:02d}"] = frame
        mkt = make_market(price=b2_price, horizon="2026-10-22", yahoo=yahoo)
        out = tpf.d3_weekend_discovery(mkt, [tpf.b2_event(mkt, date(2026, 10, 19))])
        self.assertEqual(out["observations"], N)
        a = out["weekend_perp_on_monday_open_gap"]
        self.assertAlmostEqual(a["slope"], 2.0, places=6)                     # weekend = 2 * gap
        self.assertAlmostEqual(a["correlation"], 1.0, places=6)
        b = out["weekend_perp_on_first_session_open_to_close"]
        self.assertLess(b["correlation"], 0.0)                                # the weekend move partly reverses in-session

    def test_beta_to_b0(self):
        idx = pd.date_range("2026-10-20", periods=10, freq="D", tz="UTC")
        b0 = pd.Series(np.linspace(-0.02, 0.03, 10), index=idx)
        y = 0.5 * b0 + 0.001
        out = tpf.beta_to_b0(y, b0)
        self.assertAlmostEqual(out["beta"], 0.5)
        self.assertAlmostEqual(out["alpha_daily_bps"], 10.0)
        self.assertIsNone(tpf.beta_to_b0(y, pd.Series(0.0, index=idx)))


# -------------------------------------------------------------------------------------------------------- B2 null


class NullTests(unittest.TestCase):
    def weeks(self, edge: float, n_weeks: int = 12, n: int = 30):
        rng = np.random.default_rng(1)
        out = []
        for _ in range(n_weeks):
            rets = {f"s{j:02d}": float(rng.normal(0, 0.02)) for j in range(n)}
            order = sorted(rets, key=rets.get)
            long, short = order[-5:], order[:5]                              # picks the winners long / losers short: edge
            if edge < 0:
                long, short = order[:5], order[-5:]
            out.append({"returns": rets, "long": long, "short": short})
        return out

    def test_null_places_a_lookahead_book_at_the_top_and_is_deterministic(self):
        weeks = self.weeks(+1.0)
        a, b = tpf.b2_null(weeks, draws=199), tpf.b2_null(weeks, draws=199)
        self.assertEqual(a, b)
        self.assertEqual(a["draws"], 199)
        self.assertGreater(a["observed_percentile"], 95.0)
        lose = tpf.b2_null(self.weeks(-1.0), draws=199)
        self.assertLess(lose["observed_percentile"], 5.0)
        self.assertEqual(tpf.NULL_DRAWS, 999)
        self.assertEqual(tpf.NULL_SEED, 20261013)

    def test_null_matches_action_counts_and_cost(self):
        zero = [{"returns": {f"s{j}": 0.0 for j in range(10)}, "long": ["s0", "s1"], "short": ["s2", "s3"]}] * 3
        out = tpf.b2_null(zero, draws=50)
        expected = (1 - 0.0014) ** 3 - 1
        self.assertAlmostEqual(out["observed_cumulative"], expected)
        self.assertAlmostEqual(out["null_mean"], expected)
        self.assertAlmostEqual(out["observed_percentile"], 50.0)


# ------------------------------------------------------------------------------------------------ loader and run


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
                    "<IsTruncated>false</IsTruncated></ListBucketResult>").encode()
        key = urllib.parse.unquote(url[len(bsa.DATA_URL):])
        if key.endswith(".CHECKSUM"):
            real = key[: -len(".CHECKSUM")]
            if real in self.files:
                return (sha256(self.files[real]).hexdigest() + "  " + Path(real).name).encode()
        elif key in self.files:
            return self.files[key]
        raise bsa.ArchiveHTTPError(url, 404)


def csv15(day: str, base: float, bars: int = 96) -> str:
    t0 = pd.Timestamp(day, tz="UTC")
    rows = []
    for k in range(bars):
        ot = int((t0 + pd.Timedelta(minutes=15 * k)).timestamp() * 1000)
        rows.append(f"{ot},{base},{base * 1.01},{base * 0.99},{base},10,{ot + 899999},1000000,5,1,1,0")
    return "\n".join(rows) + "\n"


class LoaderAndRunTests(unittest.TestCase):
    def test_15m_loader_index_is_the_bar_end_and_is_incremental(self):
        arch = FakeArchive()
        tmp = Path(tempfile.mkdtemp())
        base = "data/futures/um/{k}/AAAUSDT/15m/AAAUSDT-15m-{d}.zip"
        arch.add_zip("data/futures/um/monthly/klines/AAAUSDT/15m/AAAUSDT-15m-2026-09.zip", csv15("2026-09-30", 5.0))
        for d in ("2026-10-08", "2026-10-09"):
            arch.add_zip(base.format(k="daily/klines", d=d), csv15(d, 7.0))
            arch.add_zip(base.format(k="daily/markPriceKlines", d=d), csv15(d, 7.0))
        arch.add_zip("data/futures/um/monthly/klines/AAAUSDT/1h/AAAUSDT-1h-2026-09.zip", csv15("2026-09-30", 1.0))
        frame = tpf.load_klines_15m("perp15", "AAAUSDT", end="2026-10-09", start="2026-10-01", fetch=arch, directory=tmp)
        self.assertEqual(frame.index[0], ts("2026-10-08 00:15"))              # open + 15 minutes
        self.assertEqual(frame.index[-1], ts("2026-10-10 00:00"))
        self.assertEqual(len(frame), 192)
        self.assertTrue(set(frame["close"]) == {7.0})                         # September month filtered out
        mark = tpf.load_klines_15m("mark15", "AAAUSDT", end="2026-10-09", start="2026-10-01", fetch=arch, directory=tmp)
        self.assertEqual(len(mark), 192)
        n = len(arch.requests)
        tpf.load_klines_15m("perp15", "AAAUSDT", end="2026-10-09", start="2026-10-01", fetch=arch, directory=tmp)
        self.assertEqual([u for u in arch.requests[n:] if u.startswith(bsa.DATA_URL)], [])   # cached, only listings
        self.assertFalse(any("/1h/" in u for u in arch.requests))             # the hourly datasets are untouched
        self.assertEqual(list(tpf.load_klines_15m("perp15", "NOPEUSDT", end="2026-10-09", fetch=arch, directory=tmp).index), [])

    def test_latest_published_day_needs_perp_and_mark(self):
        arch = FakeArchive()
        for day in ("2026-10-10", "2026-10-11"):
            for key in tpf.probe_keys("XAUUSDT", day).values():
                arch.add_zip(key, "x\n")
        arch.add_zip(tpf.probe_keys("XAUUSDT", "2026-10-12")["perp15"], "x\n")
        self.assertEqual(tpf.latest_published_day(ts("2026-10-13 10:00"), "XAUUSDT", arch), ts("2026-10-11"))
        with self.assertRaises(tpf.TradfiError):
            tpf.latest_published_day(ts("2026-10-13"), "XAUUSDT", FakeArchive(), max_back=2)

    def test_live_style_run_before_the_start_reports_pre_start_with_coverage_only(self):
        arch = FakeArchive()
        tmp = Path(tempfile.mkdtemp())
        universe = {"watch_id": tpf.WATCH_ID, "symbols": [
            {"symbol": "AAAUSDT", "group": "stock", "stock_book": True, "yahoo_symbol": "AAA"},
            {"symbol": "ETFUSDT", "group": "etf", "stock_book": False, "yahoo_symbol": "ETF"},
            {"symbol": "XAUUSDT", "group": "commodity", "stock_book": False, "yahoo_symbol": "GC=F"},
            {"symbol": "OUTUSDT", "group": "excluded", "stock_book": False, "yahoo_symbol": None}]}
        for d in ("2026-10-11", "2026-10-12"):
            for sym in ("AAAUSDT", "ETFUSDT", "XAUUSDT"):
                arch.add_zip(f"data/futures/um/daily/klines/{sym}/15m/{sym}-15m-{d}.zip", csv15(d, 50.0))
            for sym in ("AAAUSDT", "XAUUSDT"):
                arch.add_zip(f"data/futures/um/daily/markPriceKlines/{sym}/15m/{sym}-15m-{d}.zip", csv15(d, 50.0))

        def yahoo(symbol, a, b):
            days = pd.bdate_range("2025-09-01", "2026-10-12", tz="UTC")
            c = pd.Series(10.0 + np.arange(len(days)), index=days)
            return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "adjclose": c})

        report = tpf.run(CONFIG, universe, as_of="2026-10-13 09:00", fetch=arch, yahoo=yahoo, cache_root=tmp, workers=2)
        self.assertEqual(report["status"], "PRE_START")
        self.assertEqual(report["data_end_utc"], "2026-10-13T00:00:00+00:00")
        self.assertTrue(all(v["days"] == 0 for v in report["forward"].values()))
        self.assertTrue(all(len(v) == 0 for v in report["daily_returns"].values()))
        self.assertEqual(report["coverage"]["perp_15m_symbols_with_data"], 2)      # stock + ETF; commodity needs no perp
        self.assertEqual(report["coverage"]["yahoo_stock_symbols_with_253_closes"], 1)
        self.assertEqual(report["diagnostics"].keys(), {"note"})                    # no D1..D3 before the start
        self.assertEqual(report["pending"], [])
        self.assertEqual(report["freshness"]["perp_last_bar"], "withheld until the start (coverage counts above)")
        self.assertEqual(report["yahoo_failed"], {})
        self.assertEqual(report["b2_null_inputs"], [])
        self.assertFalse(any(report["claims"].values()))
        text = json.dumps(report, default=nmf._json_default)
        self.assertNotIn("D1_funding", text)


# ------------------------------------------------------------------------------------------------------ universe


class UniverseFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.universe = tpf.load_universe(UNIVERSE_PATH)
        cls.rows = {e["symbol"]: e for e in cls.universe["symbols"]}

    def test_no_etf_or_unmapped_symbol_enters_the_stock_books(self):
        book = tpf.stock_book(self.universe)
        self.assertGreaterEqual(len(book), tpf.MIN_NAMES)
        for e in book:
            self.assertEqual(e["quote_type"], "EQUITY", e["symbol"])
            self.assertEqual(e["underlying_type"], "EQUITY")
            self.assertEqual(e["quote_asset"], "USDT")
            self.assertEqual(e["group"], "stock")
            self.assertIsNone(e["exclusion_reason"])
        for sym in ("SPYUSDT", "QQQUSDT", "SOXLUSDT", "TQQQUSDT", "SQQQUSDT", "UVXYUSDT", "IWMUSDT", "EWJUSDT"):
            self.assertFalse(self.rows[sym]["stock_book"], sym)
            self.assertEqual(self.rows[sym]["quote_type"], "ETF")
            self.assertIn("ETF", self.rows[sym]["exclusion_reason"])
        self.assertTrue(all(e["quote_type"] != "ETF" for e in book))

    def test_every_non_member_has_an_exclusion_reason_and_groups_are_consistent(self):
        for e in self.universe["symbols"]:
            if not e["stock_book"]:
                self.assertTrue(e["exclusion_reason"], e["symbol"])
            self.assertIn(e["group"], ("stock", "etf", "commodity", "excluded"))
            self.assertEqual(e["stock_book"], e["group"] == "stock")
        counts = self.universe["counts"]
        self.assertEqual(counts["stock_book"], sum(e["stock_book"] for e in self.universe["symbols"]))
        self.assertEqual(counts["etf"], sum(e["group"] == "etf" for e in self.universe["symbols"]))
        self.assertEqual(counts["unmapped"],
                         sum((e["exclusion_reason"] or "").startswith("unmapped") for e in self.universe["symbols"]))
        for sym in ("XAUUSDT", "CLUSDT", "COPPERUSDT"):
            self.assertEqual(self.rows[sym]["group"], "commodity")
            self.assertFalse(self.rows[sym]["stock_book"])

    def test_mapping_duplicate_spcx_and_out_of_scope_underlyings(self):
        self.assertEqual(self.rows["BRKBUSDT"]["yahoo_symbol"], "BRK-B")
        self.assertEqual({k: tpf.yahoo_symbol(k, "COMMODITY") for k in tpf.COMMODITY_MAP}, tpf.COMMODITY_MAP)
        self.assertEqual(tpf.COMMODITY_MAP, {"XAU": "GC=F", "XAG": "SI=F", "XPT": "PL=F", "XPD": "PA=F", "CL": "CL=F",
                                              "BZ": "BZ=F", "NATGAS": "NG=F", "COPPER": "HG=F"})
        self.assertEqual(self.universe["duplicate_base_assets"], ["SPCX"])
        self.assertTrue(self.rows["SPCXUSDT"]["stock_book"])
        self.assertFalse(self.rows["SPCXUSD1"]["stock_book"])
        self.assertIn("USD1", self.rows["SPCXUSD1"]["exclusion_reason"])
        for e in self.universe["symbols"]:
            if e["underlying_type"] in ("HK_EQUITY", "KR_EQUITY", "CN_EQUITY", "PREMARKET", "FX"):
                self.assertFalse(e["stock_book"])
                self.assertIn(e["underlying_type"], e["exclusion_reason"])

    def test_universe_is_built_from_the_committed_snapshot_without_prices(self):
        snap = ROOT / "research" / "tradfi_perps_forward" / "exchangeInfo_2026-10-13.json"
        self.assertEqual(self.universe["inputs"]["exchange_info_sha256"], sha256(snap.read_bytes()).hexdigest())
        allowed = {"symbol", "base_asset", "underlying_type", "quote_asset", "status", "onboard_date", "yahoo_symbol",
                   "quote_type", "exchange", "long_name", "group", "stock_book", "exclusion_reason"}
        for e in self.universe["symbols"]:
            self.assertEqual(set(e), allowed)
        tradfi = [r for r in json.loads(snap.read_text(encoding="utf-8"))["symbols"] if r["contractType"] == "TRADIFI_PERPETUAL"]
        self.assertEqual(len(tradfi), len(self.universe["symbols"]))


class ConfigTests(unittest.TestCase):
    def test_levels_costs_and_constants_follow_the_registration(self):
        self.assertEqual(tpf.book_levels(CONFIG), {tpf.BOOK_B0: [1], tpf.BOOK_B1: [1, 2], tpf.BOOK_B2: [1, 2, 5]})
        self.assertEqual(tpf.ROUND_TRIP_BPS, 14.0)
        self.assertEqual(tpf.MIN_NAMES, 20)
        self.assertEqual(tpf.MIN_VOLUME_USDT, 1_000_000.0)
        self.assertEqual(CONFIG["prospective_start_utc"], "2026-10-19T00:00:00Z")
        self.assertEqual(CONFIG["watch_id"], tpf.WATCH_ID)
        self.assertEqual(CONFIG["reporting"]["at_review"].count("999 draws, seed 20261013"), 1)


# ------------------------------------------------------------------------------------- review fixes (blockers 1-6)


class MidnightStallTests(unittest.TestCase):
    def test_stall_at_a_day_end_mark_does_not_score_that_day(self):
        def drift(i, grid):
            px = pd.Series(100.0, index=grid)
            if i >= N - 4:
                px.loc[grid >= ts("2026-10-21 12:00")] *= 1.01
            return px
        lag = make_market(price=drift, horizon="2026-10-22", last_bar={SYMS[21]: "2026-10-21 00:00"})
        ev = tpf.b1_event(lag, date(2026, 10, 19))
        periods, be, _ = tpf.monthly_periods([ev], tpf.BOOK_B1, lag.horizon)
        run = tpf.simulate_book(periods, 1, lag, be)
        self.assertEqual(run.stalls[0]["stall_at"], "2026-10-22T00:00:00+00:00")      # exactly 00:00Z
        self.assertEqual(run.book_end, ts("2026-10-21"))
        series = tpf.daily_series(run.growth, START + pd.Timedelta(days=1), run.book_end)
        self.assertEqual(list(series.index), [ts("2026-10-20"), ts("2026-10-21")])    # the 10-22 stamp is not scored
        self.assertNotIn(ts("2026-10-22"), series.index)
        # a mid-day mark still belongs to its own day
        self.assertEqual(tpf._day_of(ts("2026-10-20 12:00")), ts("2026-10-20"))
        self.assertEqual(tpf._day_of(ts("2026-10-21 00:00")), ts("2026-10-20"))


class YahooResilienceTests(unittest.TestCase):
    def failing(self, symbol, a, b):
        raise tpf.YahooError(f"{symbol}: HTTP 500")

    def test_failed_fetch_with_a_covering_cache_gives_identical_results(self):
        base = make_market(horizon="2026-10-27")
        books0, info0 = tpf.compute_books(base, CONFIG)
        tmp = Path(tempfile.mkdtemp())
        names = list(base.yahoo)
        ok_frames, failed0 = tpf.load_yahoo(names, lambda s, a, b: base.yahoo[s], START, ts("2026-10-27"), cache_dir=tmp)
        self.assertEqual(failed0, {})
        self.assertTrue((tmp / "Y05.csv").exists())                           # persisted
        frames, failed = tpf.load_yahoo(names, self.failing, START, ts("2026-10-27"), cache_dir=tmp)
        self.assertEqual(set(failed), set(names))
        self.assertTrue(all(v["used_cache"] for v in failed.values()))
        mkt = make_market(horizon="2026-10-27", yahoo=frames, yahoo_failed={k: v["error"] for k, v in failed.items()})
        books1, info1 = tpf.compute_books(mkt, CONFIG)
        for k in books0:
            pd.testing.assert_series_equal(books0[k].daily, books1[k].daily, check_exact=False, rtol=1e-12)
        self.assertEqual([e["status"] for e in info1["events"]["B1"]], ["formed"])
        self.assertEqual(info1["events"]["B1"][0]["long"], info0["events"]["B1"][0]["long"])

    def test_failed_fetch_without_cache_makes_b1_pending_from_the_first_affected_formation(self):
        base = make_market(horizon="2026-11-05")
        short = base.yahoo["Y05"].loc[base.yahoo["Y05"].index <= ts("2026-10-16")]    # cache covers formation 10-19 only
        ys = dict(base.yahoo)
        ys["Y05"] = short
        mkt = make_market(horizon="2026-11-05", yahoo=ys, yahoo_failed={"Y05": "boom"})
        books, info = tpf.compute_books(mkt, CONFIG)
        statuses = {e["session"]: e for e in info["events"]["B1"]}
        self.assertEqual(statuses["2026-10-19"]["b1_yahoo_blocked"], [])
        self.assertEqual(statuses["2026-11-02"]["b1_yahoo_blocked"], ["yahoo_unavailable:Y05"])
        pend = [p for p in info["pending"] if p["book"] == tpf.BOOK_B1]
        self.assertEqual(pend[0]["event"], "2026-11-02")
        self.assertEqual(pend[0]["reason"], "yahoo_unavailable:Y05")
        b1 = books["B1_xs_momentum_12_1_1x"]
        self.assertEqual(b1.detail["scored_through"], "2026-11-02T00:00:00+00:00")       # formation day not scored
        self.assertEqual(books["B0_equal_weight_long_1x"].detail["scored_through"], "2026-11-05T00:00:00+00:00")
        self.assertEqual(statuses["2026-11-02"]["b1_flat_min_names"], False)
        # no cache at all: pending from the first formation, B1 has no scored day
        gone = {k: v for k, v in base.yahoo.items() if k != "Y05"}
        mkt2 = make_market(horizon="2026-11-05", yahoo=gone, yahoo_failed={"Y05": "boom"})
        mkt2.yahoo.pop("Y05")
        books2, info2 = tpf.compute_books(mkt2, CONFIG)
        self.assertEqual(len(books2["B1_xs_momentum_12_1_1x"].daily), 0)
        self.assertEqual([p["event"] for p in info2["pending"] if p["book"] == tpf.BOOK_B1][0], "2026-10-19")
        # a never-eligible symbol (fewer than 253 closes, fetch fine) stays excluded as before, without pending
        thin = dict(base.yahoo)
        thin["Y05"] = base.yahoo["Y05"].iloc[-100:]
        mkt3 = make_market(horizon="2026-10-27", yahoo=thin)
        ev = tpf.b1_event(mkt3, date(2026, 10, 19))
        self.assertEqual(ev.status, "formed")
        self.assertNotIn(SYMS[5], ev.signal)
        self.assertEqual(ev.yahoo_blocked, [])

    def test_spy_failure_makes_the_calendar_pending_not_passed(self):
        failed = {"SPY": {"error": "boom", "used_cache": False, "cache_last_date": None}}
        cal, after = tpf.resolve_calendar(CLOCK, {}, failed, START, ts("2026-10-27"), ts("2026-10-27 01:00"))
        self.assertEqual(cal["status"], "pending")
        self.assertIn("SPY", cal["reason"])
        self.assertEqual(after, date(2026, 10, 18))
        mkt = make_market(price=b2_price, calendar_pending_after=after)
        ev1, ev2 = tpf.b1_event(mkt, date(2026, 10, 19)), tpf.b2_event(mkt, date(2026, 10, 19))
        self.assertEqual((ev1.status, ev2.status), ("pending", "pending"))
        self.assertIn("calendar_pending", ev1.reason)
        books, info = tpf.compute_books(mkt, CONFIG)
        self.assertTrue(all(len(b.daily) == 0 for b in books.values()))
        # a cached SPY series covers the sessions up to its last bar only
        days = [pd.Timestamp(d, tz="UTC") for d in CLOCK.sessions_between(date(2026, 10, 19), date(2026, 10, 22))]
        spy = pd.DataFrame({"close": 1.0}, index=pd.DatetimeIndex(days))
        cal2, after2 = tpf.resolve_calendar(CLOCK, {"SPY": spy}, failed, START, ts("2026-10-27"), ts("2026-10-27 01:00"))
        self.assertEqual(cal2["status"], "pending")
        self.assertEqual(after2, date(2026, 10, 22))
        self.assertEqual(cal2["sessions_without_bar"], [])
        # a fresh fetch passes
        cal3, after3 = tpf.resolve_calendar(CLOCK, {"SPY": spy}, {}, START, ts("2026-10-23"), ts("2026-10-23 01:00"))
        self.assertEqual((cal3["status"], after3), ("checked", None))

    def test_run_reports_yahoo_failed_at_the_top_level_and_persists_the_cache(self):
        arch = FakeArchive()
        tmp = Path(tempfile.mkdtemp())
        universe = {"watch_id": tpf.WATCH_ID, "symbols": [
            {"symbol": "AAAUSDT", "group": "stock", "stock_book": True, "yahoo_symbol": "AAA"},
            {"symbol": "XAUUSDT", "group": "commodity", "stock_book": False, "yahoo_symbol": "GC=F"}]}
        for d in ("2026-10-11", "2026-10-12"):
            for sym in ("AAAUSDT", "XAUUSDT"):
                arch.add_zip(f"data/futures/um/daily/klines/{sym}/15m/{sym}-15m-{d}.zip", csv15(d, 50.0))
                arch.add_zip(f"data/futures/um/daily/markPriceKlines/{sym}/15m/{sym}-15m-{d}.zip", csv15(d, 50.0))
        days = pd.bdate_range("2025-09-01", "2026-10-12", tz="UTC")
        c = pd.Series(10.0 + np.arange(len(days)), index=days)
        frame = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "adjclose": c})
        tpf.run(CONFIG, universe, as_of="2026-10-13 09:00", fetch=arch, yahoo=lambda s, a, b: frame, cache_root=tmp, workers=2)
        self.assertTrue((tmp / "yahoo_daily" / "AAA.csv").exists())
        report = tpf.run(CONFIG, universe, as_of="2026-10-13 09:00", fetch=arch,
                         yahoo=lambda s, a, b: (_ for _ in ()).throw(tpf.YahooError("down")), cache_root=tmp, workers=2)
        self.assertEqual(set(report["yahoo_failed"]), {"AAA", "SPY"})
        self.assertTrue(report["yahoo_failed"]["AAA"]["used_cache"])
        self.assertEqual(report["coverage"]["yahoo_stock_symbols_with_253_closes"], 1)     # never dropped


class NullInputsTests(unittest.TestCase):
    def test_week_with_a_stalled_leg_is_not_a_null_input(self):
        mkt = make_market(price=b2_price, last_bar={SYMS[0]: "2026-10-19 15:00"}, horizon="2026-10-21")
        books, info = tpf.compute_books(mkt, CONFIG)
        self.assertEqual(books["B2_weekend_fade_1x"].detail["scored_through"], "2026-10-19T00:00:00+00:00")
        self.assertEqual(info["b2_null_inputs"], [])
        tpf.b2_null(info["b2_null_inputs"], draws=5)                       # an empty list is handled, nothing is half-built

    def test_every_leg_name_needs_a_return(self):
        mkt = make_market(price=b2_price, horizon="2026-10-21")
        books, info = tpf.compute_books(mkt, CONFIG)
        week = info["b2_null_inputs"][0]
        self.assertTrue(all(s in week["returns"] for s in week["long"] + week["short"]))


class DelistedTests(unittest.TestCase):
    def test_held_symbol_stale_for_more_than_three_days_exits_at_its_last_close(self):
        mkt = make_market(horizon="2026-11-10", last_bar={SYMS[21]: "2026-10-20 12:00"})
        books, info = tpf.compute_books(mkt, CONFIG)
        for k in ("B0_equal_weight_long_1x", "B1_xs_momentum_12_1_1x"):
            self.assertEqual(books[k].detail["scored_through"], "2026-11-10T00:00:00+00:00")   # the book continues
            self.assertEqual(books[k].detail["delisted_exit_count"], 1)
            flag = books[k].detail["delisted_exit_at_last_close"][0]
            self.assertEqual((flag["symbol"], flag["last_bar"], flag["flag"]),
                             (SYMS[21], "2026-10-20T12:00:00+00:00", "delisted_exit_at_last_close"))
        self.assertEqual([e["status"] for e in info["events"]["B1"]], ["formed", "formed"])
        self.assertNotIn(SYMS[21], info["events"]["B1"][1]["long"])         # ineligible at the next formation
        self.assertEqual(info["pending"], [])
        report = tpf.build_report(CONFIG, books, info, as_of="2026-11-10 01:00", data_end=mkt.horizon)
        self.assertEqual(report["forward"]["B1_xs_momentum_12_1_1x"]["delisted_exit_count"], 1)

    def test_delisted_position_is_frozen_at_the_last_close(self):
        def px(i, grid):
            p = pd.Series(100.0, index=grid)
            if i == 21:
                p.loc[grid > ts("2026-10-20 12:00")] = 100.0 * 0.0                  # never used (no bars after the last)
                p.loc[grid <= ts("2026-10-20 12:00")] = 100.0
                p.loc[grid >= ts("2026-10-20 00:00")] = 110.0                       # last close 110 (+10%)
            return p
        mkt = make_market(price=px, horizon="2026-11-05", last_bar={SYMS[21]: "2026-10-20 12:00"})
        ev = tpf.b1_event(mkt, date(2026, 10, 19))
        periods, be, _ = tpf.monthly_periods([ev], tpf.BOOK_B1, mkt.horizon)
        res = tpf.simulate_period(periods[0], 1, mkt)
        self.assertEqual(res.delisted, {SYMS[21]: ts("2026-10-20 12:00")})
        self.assertIsNone(res.stall)
        # +10% on a 0.125 weight, frozen: the day-end marks after the last bar do not move
        g = {d: f for d, f in res.segments}
        self.assertAlmostEqual(g[ts("2026-10-21")], 1.0, places=12)


class LeverageReportingTests(unittest.TestCase):
    def test_min_equity_and_ruin_flag_per_leverage(self):
        def crash(i, grid):
            p = b2_price(i, grid)
            entry = p.loc[grid == ts("2026-10-19 14:00")].iloc[0]                  # both legs lose 15% after entry
            p.loc[grid >= ts("2026-10-19 20:00")] = entry * (0.85 if i < 4 else 1.15 if i >= N - 4 else 1.0)
            return p
        mkt = make_market(price=crash, horizon="2026-10-21")
        books, _ = tpf.compute_books(mkt, CONFIG)
        d1, d5 = books["B2_weekend_fade_1x"].detail, books["B2_weekend_fade_5x"].detail
        self.assertFalse(d1["ruin"])
        self.assertGreater(d1["min_equity"], 0.5)
        self.assertLess(d5["min_equity"], 0.5)
        self.assertAlmostEqual(d5["min_equity"], 1 - 5 * 0.15 - 5 * 0.0014, places=9)
        self.assertTrue(d5["ruin"] is (d5["min_equity"] < 0.5))
        report = tpf.build_report(CONFIG, books, {}, as_of="2026-10-21 01:00", data_end=mkt.horizon)
        self.assertIn("min_equity", report["forward"]["B2_weekend_fade_5x"])

    def test_disagreement_with_leverage_sim_raises(self):
        mkt = make_market(price=b2_price)
        real = tpf.lev.simulate_leverage

        def broken(*a, **k):
            out = real(*a, **k)
            out["period_returns"] = out["period_returns"] + 1e-6
            return out
        tpf.lev.simulate_leverage = broken
        try:
            with self.assertRaises(tpf.TradfiError):
                monday_run(mkt, 1)
        finally:
            tpf.lev.simulate_leverage = real

    def test_counters_cover_scored_periods_only(self):
        mkt = make_market(price=b2_price, last_bar={SYMS[0]: "2026-10-19 15:00"}, horizon="2026-10-21")
        run = monday_run(mkt, 5)
        self.assertEqual((run.periods, run.trades, run.turnover, run.funding_pending_periods), (0, 0, 0.0, 0))


class UniverseHashTests(unittest.TestCase):
    def test_committed_universe_matches_the_constant_and_a_changed_file_raises(self):
        self.assertEqual(tpf.universe_sha256(UNIVERSE_PATH), tpf.UNIVERSE_SHA256)
        tpf.load_universe(UNIVERSE_PATH)
        tmp = Path(tempfile.mkdtemp()) / "universe.json"
        tmp.write_text(UNIVERSE_PATH.read_text(encoding="utf-8").replace('"XAUUSDT"', '"XAUUSDX"', 1), encoding="utf-8")
        with self.assertRaises(tpf.TradfiError):
            tpf.load_universe(tmp)
        crlf = Path(tempfile.mkdtemp()) / "u.json"
        crlf.write_bytes(UNIVERSE_PATH.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.assertEqual(tpf.universe_sha256(crlf), tpf.UNIVERSE_SHA256)       # line endings are normalised


class YahooParseTests(unittest.TestCase):
    def test_only_the_close_is_required(self):
        payload = {"chart": {"result": [{"timestamp": [1760000000, 1760086400, 1760172800],
                                         "indicators": {"quote": [{"open": [None, 10.0, 11.0], "high": [10, 10, 11],
                                                                   "low": [10, 10, 11], "close": [10.0, 10.5, None]}],
                                                        "adjclose": [{"adjclose": [None, 10.5, None]}]}}]}}
        frame = tpf.parse_yahoo_chart(payload)
        self.assertEqual(len(frame), 2)                                      # the row without a close is dropped
        self.assertTrue(np.isnan(frame["open"].iloc[0]))                      # a missing open does not drop the row
        self.assertTrue(np.isnan(frame["adjclose"].iloc[0]))


if __name__ == "__main__":
    unittest.main()
