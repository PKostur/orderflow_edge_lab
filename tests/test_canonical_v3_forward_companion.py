from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.canonical_v3_forward_companion import (
    CompanionError,
    build_report,
    completed_frame,
)


def _config() -> dict:
    return json.loads(
        Path("config/universal_canonical_v3_forward_companion_v1.json").read_text(encoding="utf-8")
    )


def _frames(start: str, periods: int, seed: int = 1) -> dict[str, pd.DataFrame]:
    out = {}
    for k, symbol in enumerate(_config()["source"]["symbols"]):
        rng = np.random.default_rng(seed + k)
        idx = pd.date_range(start, periods=periods, freq="8h")
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.03, periods)))
        open_ = np.concatenate([[100.0], close[:-1]])
        out[symbol] = pd.DataFrame(
            {"open": open_, "high": np.maximum(open_, close) * 1.01,
             "low": np.minimum(open_, close) * 0.99, "close": close},
            index=idx,
        )
    return out


class CompanionTests(unittest.TestCase):
    def test_config_is_frozen_before_start_and_non_authorizing(self):
        cfg = _config()
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_PROSPECTIVE_START")
        self.assertEqual(cfg["prospective_start_utc"], "2026-09-27T00:00:00Z")
        self.assertEqual(cfg["economics"]["accounting_versions"], [2, 3])
        for key, value in cfg["claims"].items():
            if key.endswith("_authorized"):
                self.assertFalse(value)

    def test_incomplete_bar_is_dropped(self):
        frame = _frames("2026-06-01T00:00:00Z", 400)["BTC_USDT"]
        as_of = frame.index[-1] + pd.Timedelta(hours=4)
        self.assertEqual(completed_frame(frame, as_of=as_of, minimum=300).index[-1], frame.index[-2])
        with self.assertRaises(CompanionError):
            completed_frame(frame.iloc[:100], as_of=as_of, minimum=300)

    def test_pre_start_report_has_no_scored_trades(self):
        frames = _frames("2026-06-01T00:00:00Z", 350)
        report = build_report(_config(), frames, as_of="2026-09-26T12:00:00Z")
        self.assertEqual(report["status"], "PRE_START")
        for strategy in report["strategies"]:
            self.assertEqual(strategy["completed_trade_count"], 0)

    def test_post_start_trades_scored_under_both_versions_and_longs_match(self):
        frames = _frames("2026-06-01T00:00:00Z", 1100)
        report = build_report(_config(), frames, as_of="2027-06-01T00:00:00Z")
        self.assertEqual(report["status"], "COLLECTING")
        total = 0
        for strategy in report["strategies"]:
            total += strategy["completed_trade_count"]
            for trade in strategy["completed_trades"]:
                self.assertGreaterEqual(trade["entry"], "2026-09-27T00:00:00+00:00")
                if trade["side"] > 0:
                    self.assertAlmostEqual(trade["v2_net_bps"], trade["v3_net_bps"], places=6)
            by = strategy["by_direction"]
            self.assertEqual(set(by), {"ALL", "LONG", "SHORT"})
            self.assertEqual(set(by["ALL"]), {"n", "v2", "v3"})
        self.assertGreater(total, 0)
        self.assertNotIn("p_value", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
