from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.markov_price_diagnostics import MarkovStateSpec, analyze_symbol


class MarkovPriceDiagnosticsTests(unittest.TestCase):
    def _frame(self, periods: int = 260) -> pd.DataFrame:
        index = pd.date_range("2026-01-01", periods=periods, freq="h", tz="UTC")
        x = np.arange(periods, dtype=float)
        returns = 0.0015 * np.sin(x / 5.0) + 0.0007 * np.cos(x / 11.0)
        close = 1.0 * np.exp(np.cumsum(returns))
        return pd.DataFrame({"close": close}, index=index)

    def test_transition_rows_sum_to_one(self) -> None:
        frame = self._frame()
        report = analyze_symbol(
            frame,
            training_end_exclusive_utc="2026-01-09T00:00:00Z",
            forecast_steps=[1, 3],
            spec=MarkovStateSpec(),
        )
        for row in report["transition_probabilities"].values():
            self.assertAlmostEqual(sum(row.values()), 1.0, places=10)

    def test_post_freeze_prices_do_not_refit_transition_matrix(self) -> None:
        frame = self._frame()
        cutoff = "2026-01-09T00:00:00Z"
        base = analyze_symbol(
            frame,
            training_end_exclusive_utc=cutoff,
            forecast_steps=[1],
            spec=MarkovStateSpec(),
        )

        modified = frame.copy()
        modified.loc[modified.index >= pd.Timestamp(cutoff), "close"] *= np.exp(
            np.linspace(0.0, 1.5, int((modified.index >= pd.Timestamp(cutoff)).sum()))
        )
        changed = analyze_symbol(
            modified,
            training_end_exclusive_utc=cutoff,
            forecast_steps=[1],
            spec=MarkovStateSpec(),
        )
        self.assertEqual(base["transition_counts"], changed["transition_counts"])
        self.assertEqual(base["transition_probabilities"], changed["transition_probabilities"])


if __name__ == "__main__":
    unittest.main()
