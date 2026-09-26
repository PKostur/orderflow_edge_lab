from __future__ import annotations

import hashlib
import json
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.funding_coverage import build_funding_coverage_report


class FundingCoverageTests(unittest.TestCase):
    def _candidate(self):
        payload = {
            "schema_version": 1,
            "candidate_id": "fixture",
            "specification": {
                "symbols": ["A", "B", "C", "D"],
                "lookback_days": 30,
                "holding_days": 7,
                "quantile_fraction": 0.25,
                "variant": "dollar_neutral_top_bottom",
                "round_trip_cost_bps": 20.0,
            },
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload["spec_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        return payload

    def _prices(self):
        idx = pd.date_range("2025-01-01", periods=260, freq="1D", tz="UTC")
        frames = {}
        for j, symbol in enumerate(("A", "B", "C", "D")):
            close = 100.0 * np.exp(np.linspace(0.0, (j - 1.5) * 0.25, len(idx)))
            frames[symbol] = pd.DataFrame({"close": close}, index=idx)
        return frames

    def _funding(self, *, start="2025-01-01"):
        idx = pd.date_range(start, "2025-09-17", freq="8h", tz="UTC", inclusive="left")
        return {
            symbol: pd.DataFrame({"funding_rate": 0.00001}, index=idx)
            for symbol in ("A", "B", "C", "D")
        }

    def _config(self):
        return {
            "audit_id": "cross-sectional-okx-funding-coverage-audit-v1",
            "source": "fixture",
            "symbols": ["A", "B", "C", "D"],
            "window": {
                "start": "2025-01-01T00:00:00Z",
                "end_exclusive": "2025-09-18T00:00:00Z",
            },
        }

    def test_complete_funding_is_admissible(self):
        report = build_funding_coverage_report(
            self._candidate(),
            self._prices(),
            self._funding(),
            self._config(),
        )
        self.assertGreater(report["required_held_intervals"], 0)
        self.assertEqual(report["coverage_fraction"], 1.0)
        self.assertTrue(report["funding_economics_admissible"])
        self.assertEqual(report["status"], "FUNDING_COVERAGE_COMPLETE")
        self.assertEqual(report["missing_held_intervals"], 0)

    def test_late_funding_history_fails_closed(self):
        report = build_funding_coverage_report(
            self._candidate(),
            self._prices(),
            self._funding(start="2025-07-01"),
            self._config(),
        )
        self.assertGreater(report["required_held_intervals"], 0)
        self.assertLess(report["coverage_fraction"], 1.0)
        self.assertFalse(report["funding_economics_admissible"])
        self.assertEqual(report["status"], "FUNDING_COVERAGE_INCOMPLETE")
        self.assertGreater(report["missing_held_intervals"], 0)
        self.assertTrue(report["missing_interval_examples"])

    def test_audit_never_authorizes_trading(self):
        report = build_funding_coverage_report(
            self._candidate(),
            self._prices(),
            self._funding(),
            self._config(),
        )
        claims = report["claims"]
        self.assertFalse(claims["candidate_promoted"])
        self.assertFalse(claims["profitable_edge_established"])
        self.assertFalse(claims["live_trading_authorized"])
        self.assertFalse(claims["leverage_authorized"])
        self.assertFalse(claims["historical_economic_result_repaired"])


if __name__ == "__main__":
    unittest.main()
