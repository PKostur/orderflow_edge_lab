import unittest

import pandas as pd

from orderflow_edge_lab.carry import Costs
from orderflow_edge_lab.carry_rotation import rotation_book

DAYS = pd.date_range("2024-01-01", periods=35, freq="D", tz="UTC")   # 2024-01-01 is a Monday
COINS = ["A", "B", "C", "D", "E", "F", "G"]


def frames(fund_by_coin):
    px = pd.DataFrame(100.0, index=DAYS, columns=COINS)
    f = pd.DataFrame({c: fund_by_coin.get(c, 0.0001) for c in COINS}, index=DAYS)
    return px, px.copy(), f


class RotationTests(unittest.TestCase):
    def test_picks_the_top_funding_coins_and_skips_negative_ones(self):
        spot, perp, fund = frames({"A": 0.002, "B": 0.0015, "C": 0.001, "D": 0.0008, "E": 0.0006, "F": -0.001})
        out = rotation_book(spot, perp, fund, top_n=5, lookback_days=7)
        first = out["picks"]["2024-01-08T00:00:00+00:00"]
        self.assertEqual(first, ["A", "B", "C", "D", "E"])
        self.assertTrue(all("F" not in v for v in out["picks"].values()))

    def test_weights_apply_from_the_day_after_the_rebalance(self):
        spot, perp, fund = frames({"A": 0.002})
        out = rotation_book(spot, perp, fund, top_n=5, lookback_days=7)
        w = out["weights"]
        self.assertEqual(w.loc["2024-01-08", "A"], 0.0)
        self.assertAlmostEqual(w.loc["2024-01-09", "A"], 0.2)

    def test_flat_prices_earn_held_funding_minus_entry_and_exit(self):
        spot, perp, fund = frames({c: 0.001 for c in COINS[:5]} | {"F": 0.0, "G": 0.0})
        c = Costs(10, 5, 2)
        out = rotation_book(spot, perp, fund, top_n=5, lookback_days=7, costs=c)
        held_days = int((out["weights"].sum(axis=1) > 0).sum())
        self.assertAlmostEqual(out["funding"].sum(), 0.001 * held_days)
        self.assertAlmostEqual(out["cost"].sum(), 2 * 19e-4)          # one entry, one exit, same book throughout
        self.assertAlmostEqual(out["net"].sum(), 0.001 * held_days - 2 * 19e-4)

    def test_no_positive_funding_means_cash(self):
        spot, perp, fund = frames({c: -0.0005 for c in COINS})
        out = rotation_book(spot, perp, fund, top_n=5, lookback_days=7)
        self.assertEqual(float(out["weights"].abs().sum().sum()), 0.0)
        self.assertEqual(float(out["net"].abs().sum()), 0.0)


if __name__ == "__main__":
    unittest.main()
