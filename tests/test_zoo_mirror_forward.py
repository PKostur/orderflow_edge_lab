from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.zoo_mirror_forward import build_report


def _inputs(n_days=300):
    cfg = json.loads(Path("config/zoo_mirror_forward_v1.json").read_text(encoding="utf-8"))
    frames, funding = {}, {}
    syms = ["BTC_USDT"] + [f"C{i}_USDT" for i in range(11)]
    for k, s in enumerate(syms):
        idx = pd.date_range("2026-01-01T00:00Z", periods=3 * n_days, freq="8h")
        c = 100 * np.exp(np.cumsum(np.random.default_rng(k).normal(0, 0.02, len(idx))))
        o = np.concatenate([[100.0], c[:-1]])
        frames[s] = pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c, "volume": 1.0}, index=idx)
        funding[s] = pd.Series(0.0001, index=idx)
    return cfg, frames, funding


class ZooMirrorForwardTests(unittest.TestCase):
    def test_registered_before_start_and_authorizes_nothing(self):
        cfg = json.loads(Path("config/zoo_mirror_forward_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["prospective_start_utc"], "2026-10-03T00:00:00Z")
        self.assertFalse(any(cfg["claims"].values()))

    def test_pre_start_and_post_start_scoring(self):
        cfg, frames, funding = _inputs()
        pre = build_report(cfg, frames, funding, as_of="2026-10-02T12:00:00Z")
        self.assertEqual(pre["status"], "PRE_START")
        cfg["prospective_start_utc"] = "2026-08-01T00:00:00Z"
        post = build_report(cfg, frames, funding, as_of="2026-09-20T00:00:00Z")
        self.assertEqual(post["status"], "COLLECTING")
        for series in post["daily_returns"].values():
            self.assertTrue(all(pd.Timestamp(t) > pd.Timestamp("2026-08-01T00:00Z") for t in series))
        json.dumps(post, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
