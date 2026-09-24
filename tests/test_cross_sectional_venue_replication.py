from __future__ import annotations

import json
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_sectional_venue_replication import (
    build_venue_replication_report,
)


class CrossSectionalVenueReplicationTests(unittest.TestCase):
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
        import hashlib
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        payload["spec_sha256"] = hashlib.sha256(raw.encode()).hexdigest()
        return payload

    def _frames(self, perturb=0.0):
        idx = pd.date_range("2025-01-01", periods=260, freq="1D", tz="UTC")
        out = {}
        for j, symbol in enumerate(("A", "B", "C", "D")):
            trend = np.linspace(0, (j - 1.5) * 0.35, len(idx))
            close = 100.0 * np.exp(trend + perturb * np.sin(np.arange(len(idx)) / (4+j)))
            open_ = close * (1.0 + 0.0005 * np.cos(np.arange(len(idx)) / (5+j)))
            out[symbol] = pd.DataFrame(
                {"open": open_, "high": np.maximum(open_, close), "low": np.minimum(open_, close), "close": close},
                index=idx,
            )
        return out

    def _funding(self):
        idx = pd.date_range("2025-01-01T08:00:00Z", periods=780, freq="8h")
        return {
            symbol: pd.DataFrame({"funding_rate": 0.00001}, index=idx)
            for symbol in ("A", "B", "C", "D")
        }

    def test_identical_venues_have_exact_weight_agreement(self):
        candidate = self._candidate()
        frames = self._frames()
        funding = self._funding()
        config = {
            "symbols": ["A", "B", "C", "D"],
            "window": {"start": "2025-01-01", "end_exclusive": "2025-09-18"},
            "fold_days": 60,
            "replication_venue": "fixture independent venue",
            "replication_funding_description": "fixture funding",
        }
        result = build_venue_replication_report(
            candidate, frames, funding, frames, funding, config
        )
        self.assertEqual(result["signal_agreement"]["exact_weight_agreement_fraction"], 1.0)
        self.assertAlmostEqual(result["mexc"]["net_return"], result["independent_venue"]["net_return"])
        self.assertEqual(result["formal_verdict"], "DESCRIPTIVE_TRANSFER_ONLY")
        self.assertFalse(result["claims"]["same_historical_period_is_future_oos"])

    def test_same_calendar_is_forced_across_venues(self):
        candidate = self._candidate()
        mexc = self._frames()
        independent = self._frames(perturb=0.003)
        independent["A"] = independent["A"].iloc[5:].copy()
        funding = self._funding()
        config = {
            "symbols": ["A", "B", "C", "D"],
            "window": {"start": "2025-01-01", "end_exclusive": "2025-09-18"},
            "fold_days": 60,
            "replication_venue": "fixture independent venue",
            "replication_funding_description": "fixture funding",
        }
        result = build_venue_replication_report(
            candidate, mexc, funding, independent, funding, config
        )
        self.assertEqual(result["shared_daily_observations"], 255)
        self.assertTrue(result["claims"]["same_calendar_enforced"])


if __name__ == "__main__":
    unittest.main()
