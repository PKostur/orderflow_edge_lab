import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.drawdown_envelopes import bootstrap_envelopes, position_in_envelope

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import build_forward_drawdown_envelopes as builder  # noqa: E402


def synth(n=400, seed=1):
    return np.random.default_rng(seed).normal(0.001, 0.01, n)


class DrawdownEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.env = bootstrap_envelopes(synth(), 60, 800, 20.0, 7, False)

    def test_percentiles_ordered(self):
        e = self.env
        self.assertTrue((e.cum_p5 <= e.cum_p50).all() and (e.cum_p50 <= e.cum_p95).all())
        self.assertTrue((e.mdd_p5 <= e.mdd_p50).all() and (e.mdd_p50 <= e.mdd_p95).all())

    def test_zero_edge_median_near_zero(self):
        e = bootstrap_envelopes(synth(), 60, 3000, 20.0, 7, True)
        self.assertLess(abs(e.cum_p50.iloc[-1]), 0.01)

    def test_mdd_nonpositive_and_monotone_median(self):
        self.assertTrue((self.env.mdd_p50 <= 0).all() and (self.env.mdd_p95 <= 0).all())
        self.assertTrue((self.env.mdd_p50.diff().dropna() <= 1e-12).all())

    def test_reproducible(self):
        again = bootstrap_envelopes(synth(), 60, 800, 20.0, 7, False)
        pd.testing.assert_frame_equal(self.env, again)

    def test_bands(self):
        env = pd.DataFrame({"cum_p5": [-0.1], "cum_p50": [0.0], "cum_p95": [0.1],
                            "mdd_p5": [-0.2], "mdd_p50": [-0.1], "mdd_p95": [-0.02]})
        for r, band in ((-0.15, "below_p5"), (-0.05, "p5_p50"), (0.05, "p50_p95"), (0.2, "above_p95")):
            self.assertEqual(position_in_envelope([r], env)["cum_band"], band)
        p = position_in_envelope([-0.3], env)
        self.assertEqual(p["mdd_band"], "below_p5")
        self.assertLessEqual(p["mdd"], 0)
        self.assertTrue(position_in_envelope([0.0, 0.0], env)["beyond_horizon"])

    def test_builder_refuses_overwrite(self):
        idx = pd.date_range("2024-01-01", periods=200, tz="UTC")
        s = pd.Series(synth(200), index=idx)
        cfg = {"envelope_id": "t", "method": {"horizon_days": 10, "paths": 50, "mean_block_days": 5, "seed": 1},
               "covered": [{"watch_id": "w", "book": "b"}]}
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "sub" / "e.json"
            doc = builder.build({"w": s}, out, cfg)
            self.assertEqual(len(doc["watches"]["w"]["input_sha256"]), 64)
            self.assertEqual(len(json.loads(out.read_text())["watches"]["w"]["variants"]["zero_edge"]["cum_p5"]), 10)
            with self.assertRaises(FileExistsError):
                builder.build({"w": s}, out, cfg)
            self.assertEqual(builder.main(str(out)), 2)


if __name__ == "__main__":
    unittest.main()
