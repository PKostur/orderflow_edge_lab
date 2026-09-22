import importlib.util
import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).with_name("h2_shadow_tracker.py")
SPEC = importlib.util.spec_from_file_location("h2_shadow_tracker", MODULE_PATH)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def mkbar(ticker, dt, o=100.0, h=100.1, l=99.9, c=100.0, v=100.0, vw=100.0):
    return m.Bar(
        ticker=ticker,
        ts_ms=int(dt.timestamp() * 1000),
        dt_et=dt,
        o=o,
        h=h,
        l=l,
        c=c,
        v=v,
        vw=vw,
    )


class ShadowTrackerTests(unittest.TestCase):
    def test_exit_bar_high_low_are_not_used_in_mfe_mae(self):
        day = date(2026, 9, 22)
        start = m.minute_dt(day, 9, 30)
        by_time = {}

        for i in range(42):
            dt = start + timedelta(minutes=i)
            by_time[dt] = mkbar("SPY", dt)

        sig = m.minute_dt(day, 9, 50)
        by_time[sig] = mkbar("SPY", sig, o=101.5, h=102.2, l=101.4, c=102.0, v=500.0, vw=99.0)

        entry = m.minute_dt(day, 9, 51)
        by_time[entry] = mkbar("SPY", entry, o=100.0, h=100.4, l=99.8, c=100.2, v=100.0, vw=100.1)
        for minute in range(52, 60):
            dt = m.minute_dt(day, 9, minute)
            by_time[dt] = mkbar("SPY", dt, o=100.2, h=100.8, l=99.7, c=100.3)
        dt1000 = m.minute_dt(day, 10, 0)
        by_time[dt1000] = mkbar("SPY", dt1000, o=100.3, h=101.0, l=99.6, c=100.5)

        exit_dt = m.minute_dt(day, 10, 1)
        by_time[exit_dt] = mkbar("SPY", exit_dt, o=101.0, h=150.0, l=50.0, c=120.0)

        raw = m.find_raw_h2_signal("SPY", day, by_time)
        self.assertIsNotNone(raw)
        assert raw is not None

        self.assertLess(raw.mfe_bps, 200.0)
        self.assertLess(raw.mae_bps, 200.0)
        self.assertAlmostEqual(raw.exit_open, 101.0)

    def test_rolling_filter_uses_strictly_previous_ten_raw_signals(self):
        history_days = [date(2026, 9, 12) + timedelta(days=i) for i in range(11)]
        sessions = {
            "SPY": {d: {m.minute_dt(d, 9, 30): mkbar("SPY", m.minute_dt(d, 9, 30))} for d in history_days},
            "QQQ": {},
            "GLD": {},
            "USO": {},
        }

        values = {}
        for i, d in enumerate(history_days):
            factor = 1.0 if i < 10 else 2.0
            values[d] = m.RawSignal(
                ticker="SPY",
                session_date=d,
                signal_dt=m.minute_dt(d, 10, 0),
                direction=1,
                entry_open=100.0,
                exit_open=100.1,
                gross_bps=10.0,
                net2_bps=8.0,
                net4_bps=6.0,
                vwap_distance_bps=factor,
                signal_range_bps=factor,
                rel_volume20=factor,
                mfe_bps=12.0,
                mae_bps=4.0,
            )

        def fake_find(ticker, day, by_time):
            return values.get(day)

        with patch.object(m, "find_raw_h2_signal", side_effect=fake_find):
            trades = m.build_shadow_trades(sessions, history_days[-1])

        self.assertTrue(all(date.fromisoformat(t.date) >= m.SHADOW_START for t in trades))
        self.assertGreaterEqual(len(trades), 1)
        first = trades[0]
        self.assertAlmostEqual(first.rolling_vwap_distance_mean, 1.0)
        self.assertAlmostEqual(first.rolling_signal_range_mean, 1.0)
        self.assertAlmostEqual(first.rolling_rel_volume20_mean, 1.0)

    def test_four_sleeve_portfolio_math(self):
        trades = [
            m.ShadowTrade(
                date="2026-09-22",
                ticker="SPY",
                signal_et="2026-09-22T10:00:00-04:00",
                direction=1,
                entry_open=100,
                exit_open=101,
                vwap_distance_bps=1,
                rolling_vwap_distance_mean=0,
                signal_range_bps=1,
                rolling_signal_range_mean=0,
                rel_volume20=2,
                rolling_rel_volume20_mean=1,
                net_bps_2=100.0,
                net_bps_4=98.0,
                mfe_bps=120,
                mae_bps=20,
            ),
            m.ShadowTrade(
                date="2026-09-22",
                ticker="QQQ",
                signal_et="2026-09-22T10:01:00-04:00",
                direction=1,
                entry_open=100,
                exit_open=99,
                vwap_distance_bps=1,
                rolling_vwap_distance_mean=0,
                signal_range_bps=1,
                rolling_signal_range_mean=0,
                rel_volume20=2,
                rolling_rel_volume20_mean=1,
                net_bps_2=-100.0,
                net_bps_4=-102.0,
                mfe_bps=10,
                mae_bps=120,
            ),
        ]
        rows = m.equity_rows(trades)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["portfolio_equity"], 1.0, places=12)
        self.assertAlmostEqual(rows[0]["constant_notional_cumulative_bps"], 0.0, places=12)

    def test_profit_factor(self):
        self.assertAlmostEqual(m.profit_factor([10.0, 5.0, -3.0]), 5.0)
        self.assertTrue(math.isinf(m.profit_factor([1.0, 2.0])))


if __name__ == "__main__":
    unittest.main()
