from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.etf_history_holdout import adjusted_daily_frame, evaluate


def _cfg() -> dict:
    return json.loads(Path("config/universal_etf_long_history_holdout_v1.json").read_text(encoding="utf-8"))


def _frames(periods: int) -> dict:
    out = {}
    syms = [s for m in _cfg()["universe_rule"]["symbols"].values() for s in m]
    idx = pd.bdate_range("2006-06-01", periods=periods, tz="UTC")
    for k, s in enumerate(syms):
        rng = np.random.default_rng(70 + k)
        vol = 0.05 + 0.02 * k
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, vol / np.sqrt(252), periods)))
        open_ = np.concatenate([[100.0], close[:-1]])
        out[s] = pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.002,
                               "low": np.minimum(open_, close) * 0.998, "close": close}, index=idx)
    return out


class EtfHoldoutTests(unittest.TestCase):
    def test_config_mapping_preserves_calendar_horizon(self):
        cfg = _cfg()
        p = {s["audit_id"]: s["parameters"] for s in cfg["strategies"]}
        self.assertEqual(p["DON8"]["lookback"], round(55 / 3))
        self.assertEqual((p["EMA8"]["fast"], p["EMA8"]["slow"]), (24 // 3, 96 // 3))
        self.assertEqual(p["EMA8"]["atr_period"], round(14 / 3))
        self.assertEqual((p["VOL8"]["lookback"], p["VOL8"]["vol_window"]), (8, 32))
        self.assertEqual(cfg["sizing"]["bars_per_year"], 252)
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_EVALUATION")

    def test_adjustment_scales_ohlc_and_stamps_midnight(self):
        payload = {"chart": {"result": [{
            "timestamp": [1704205800, 1704292200],  # 2024-01-02/03 14:30 UTC
            "indicators": {"quote": [{"open": [10, 11], "high": [12, 12], "low": [9, 10], "close": [11, 11.5]}],
                           "adjclose": [{"adjclose": [5.5, 5.75]}]}}]}}
        f = adjusted_daily_frame(payload)
        self.assertEqual(str(f.index[0]), "2024-01-02 00:00:00+00:00")
        self.assertAlmostEqual(f["open"].iloc[0], 5.0)
        self.assertAlmostEqual(f["high"].iloc[0], 6.0)

    def test_evaluate_runs_and_reports(self):
        report = evaluate(_cfg(), _frames(1200))
        self.assertIn("passed", report["primary"])
        self.assertEqual(set(report["secondary"]["per_asset_class"]), set(_cfg()["universe_rule"]["symbols"]))
        json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
