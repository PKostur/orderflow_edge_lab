from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.chop_candidates import TEXTBOOK, cross_sectional_reversal, family_target, funding_carry


def _f(seed, n=400):
    idx = pd.date_range("2024-01-01T00:00Z", periods=n, freq="8h")
    c = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0, 0.02, n)))
    o = np.concatenate([[100.0], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c}, index=idx)


class ChopCandidateTests(unittest.TestCase):
    def test_textbook_families_run(self):
        f = _f(0)
        for name in TEXTBOOK:
            t = family_target(f, name)
            self.assertTrue(set(t.unique()) <= {-1.0, 0.0, 1.0})

    def test_cross_sectional_is_market_neutral_among_eligible(self):
        frames = {f"C{k}": _f(k) for k in range(8)}
        elig = {s: pd.Series(True, index=f.index) for s, f in frames.items()}
        out = cross_sectional_reversal(frames, elig)
        tot = pd.DataFrame(out).sum(axis=1)
        self.assertTrue((tot.abs() < 1e-9).all())
        none = cross_sectional_reversal(frames, {s: pd.Series(False, index=f.index) for s, f in frames.items()})
        self.assertTrue(all((v == 0).all() for v in none.values()))

    def test_funding_carry_takes_receiving_side(self):
        f = _f(1, 50)
        pos = funding_carry(f, pd.Series(0.0005, index=pd.date_range("2023-12-25T00:00Z", periods=100, freq="8h")))
        self.assertTrue((pos.iloc[10:] == -1.0).all())


if __name__ == "__main__":
    unittest.main()
