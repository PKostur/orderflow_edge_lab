from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.pre_window_holdout import HoldoutError, clip_to_window, evaluate


def _cfg() -> dict:
    return json.loads(Path("config/universal_pre_window_crypto_holdout_v1.json").read_text(encoding="utf-8"))


def _frames(start: str, periods: int) -> dict[str, pd.DataFrame]:
    out = {}
    for k, s in enumerate(_cfg()["source"]["symbols"]):
        rng = np.random.default_rng(40 + k)
        idx = pd.date_range(start, periods=periods, freq="8h")
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.03, periods)))
        open_ = np.concatenate([[100.0], close[:-1]])
        out[s] = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.01,
                               "low": np.minimum(open_, close) * 0.99, "close": close}, index=idx)
    return out


class HoldoutTests(unittest.TestCase):
    def test_config_is_frozen_and_window_precedes_development(self):
        cfg = _cfg()
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_EVALUATION")
        self.assertEqual(cfg["window"]["end_exclusive"], "2024-01-01T00:00:00Z")
        self.assertEqual(cfg["hypotheses"]["primary"]["pass_rule"], "mean > 0 and t >= 2.0")
        self.assertNotIn("ENA_USDT", cfg["source"]["symbols"])

    def test_clip_drops_development_window_bars(self):
        frames = _frames("2023-12-01T00:00:00Z", 200)  # runs into 2024
        clipped = clip_to_window(frames, _cfg()["window"])
        for f in clipped.values():
            self.assertLess(f.index.max(), pd.Timestamp("2024-01-01T00:00:00Z"))

    def test_clip_rejects_window_that_overlaps(self):
        bad = {"start": "2023-06-01T00:00:00Z", "end_exclusive": "2024-06-01T00:00:00Z"}
        with self.assertRaises(HoldoutError):
            clip_to_window(_frames("2023-12-01T00:00:00Z", 200), bad)

    def test_evaluate_produces_primary_verdict_and_secondaries(self):
        report = evaluate(_cfg(), _frames("2020-06-05T00:00:00Z", 1500))
        self.assertIn("passed", report["primary"])
        self.assertEqual(set(report["secondary"]["per_strategy"]), {"DON8", "EMA8", "VOL8"})
        self.assertTrue(report["data_hash"])
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
