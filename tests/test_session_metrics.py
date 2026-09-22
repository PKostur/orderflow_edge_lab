import math
import unittest
from datetime import datetime, timezone

from orderflow_edge_lab.session_metrics import (
    analyze_bar_sessions,
    analyze_trade_sessions,
    session_memberships,
    session_phase_memberships,
    session_regime,
)

UTC = timezone.utc


class SessionMetricTests(unittest.TestCase):
    def test_dst_aware_london_new_york_overlap_summer(self):
        ts = datetime(2026, 7, 15, 13, 30, tzinfo=UTC)
        self.assertEqual(session_memberships(ts), ("LONDON", "NEW_YORK"))
        self.assertEqual(session_regime(ts), "LONDON+NEW_YORK")

    def test_asia_london_overlap_summer(self):
        ts = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
        self.assertEqual(session_memberships(ts), ("ASIA", "LONDON"))
        self.assertEqual(session_regime(ts), "ASIA+LONDON")

    def test_dst_aware_winter(self):
        ts = datetime(2026, 1, 15, 13, 30, tzinfo=UTC)
        self.assertEqual(session_memberships(ts), ("LONDON", "NEW_YORK"))

    def test_neutral_session_phase_thirds(self):
        self.assertEqual(
            session_phase_memberships(datetime(2026, 7, 15, 0, 30, tzinfo=UTC)),
            ("ASIA_OPENING",),
        )
        phases=session_phase_memberships(datetime(2026, 7, 15, 13, 30, tzinfo=UTC))
        self.assertIn("LONDON_LATE", phases)
        self.assertIn("NEW_YORK_OPENING", phases)

    def test_off_session(self):
        ts = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)
        self.assertEqual(session_memberships(ts), ())
        self.assertEqual(session_regime(ts), "OFF_SESSION")

    def test_trade_metrics_keep_overlap_multilabel(self):
        rows = [
            {"timestamp": "2026-07-15T01:00:00+00:00", "net_bps": 10.0},
            {"timestamp": "2026-07-15T08:30:00+00:00", "net_bps": 20.0},
            {"timestamp": "2026-07-15T13:30:00+00:00", "net_bps": -5.0},
            {"timestamp": "2026-07-15T18:00:00+00:00", "net_bps": 15.0},
        ]
        result = analyze_trade_sessions(rows)
        by_session = {row["session"]: row for row in result["by_session_membership"]}
        self.assertEqual(by_session["ASIA"]["observations"], 2)
        self.assertEqual(by_session["LONDON"]["observations"], 2)
        self.assertEqual(by_session["NEW_YORK"]["observations"], 2)

        regimes = {row["regime"]: row for row in result["by_exclusive_regime"]}
        self.assertIn("ASIA", regimes)
        self.assertIn("ASIA+LONDON", regimes)
        self.assertIn("LONDON+NEW_YORK", regimes)
        self.assertIn("NEW_YORK", regimes)

    def test_trade_summary_drawdown_and_profit_factor(self):
        rows = [
            {"timestamp": "2026-07-15T01:00:00+00:00", "net_bps": 10.0},
            {"timestamp": "2026-07-16T01:00:00+00:00", "net_bps": -4.0},
            {"timestamp": "2026-07-17T01:00:00+00:00", "net_bps": 2.0},
        ]
        result = analyze_trade_sessions(rows)
        asia = next(row for row in result["by_session_membership"] if row["session"] == "ASIA")
        self.assertAlmostEqual(asia["net_total_bps"], 8.0)
        self.assertAlmostEqual(asia["profit_factor"], 3.0)
        self.assertAlmostEqual(asia["max_drawdown_bps"], -4.0)

    def test_bar_metrics(self):
        rows = [
            {
                "timestamp": "2026-07-15T00:00:00+00:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 10.0,
            },
            {
                "timestamp": "2026-07-15T00:15:00+00:00",
                "open": 100.5,
                "high": 102.0,
                "low": 100.0,
                "close": 101.0,
                "volume": 20.0,
            },
        ]
        result = analyze_bar_sessions(rows)
        asia = next(row for row in result["by_session_membership"] if row["session"] == "ASIA")
        self.assertEqual(asia["session_days"], 1)
        self.assertGreater(asia["average_range_bps"], 0)
        self.assertGreater(asia["average_realized_vol_bps"], 0)
        self.assertAlmostEqual(asia["average_volume"], 30.0)


if __name__ == "__main__":
    unittest.main()
