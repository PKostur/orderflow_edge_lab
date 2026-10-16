import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.xs_premia import momentum_score, run_xs
from orderflow_edge_lab.xs_premia_pit import daily_last_close_panel, run_xs_pit

DAYS = pd.date_range("2026-01-01", periods=90, freq="D", tz="UTC")


def panel(seed=7, n=13):
    rng = np.random.default_rng(seed)
    cols = [f"C{i:02d}" for i in range(n)]
    opens = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (len(DAYS), n)), 0)), index=DAYS, columns=cols)
    last_close = opens.shift(-1) * (1 + rng.normal(0, 0.001, opens.shape))   # last 8h close of day d, near open(d+1)
    return opens, last_close, pd.DataFrame(0.0, index=DAYS, columns=cols)


class PointInTimeTests(unittest.TestCase):
    def test_identical_to_run_xs_when_no_coin_delists(self):
        opens, last_close, fund = panel()
        score = momentum_score(opens, 10)
        a = run_xs(opens, fund, score, rebalance_days=7, q=0.2, cost_bps=20)
        b = run_xs_pit(opens, last_close, fund, score, rebalance_days=7, q=0.2, cost_bps=20)
        pd.testing.assert_series_equal(a["returns"], b["returns"])
        self.assertEqual(b["settlements"], [])

    def test_delisting_coin_is_selectable_and_settles_at_last_close(self):
        opens, last_close, fund = panel()
        opens.iloc[40:, 0] = 100.0
        opens.iloc[30:40, 0] = np.linspace(100, 200, 10)        # strongest momentum into its last day
        opens.iloc[40, 0] = 210.0
        opens.iloc[41:, 0] = np.nan                               # last open is day 40
        last_close.iloc[40, 0] = 105.0                            # settles 50% below the day-40 open
        last_close.iloc[41:, 0] = np.nan
        score = momentum_score(opens, 10)
        d = DAYS[40]
        out = run_xs_pit(opens, last_close, fund, score, rebalance_days=1, q=0.2, cost_bps=0)
        self.assertEqual(out["settlements"], [{"date": d.isoformat(), "symbol": "C00", "price": "last_close"}])
        w = 0.5 / int(np.floor(13 * 0.2))
        others = out["weights"].loc[d].drop("C00")
        expected = w * (105.0 / 210.0 - 1.0) + float((others * (opens.shift(-1) / opens - 1).loc[d].drop("C00").fillna(0)).sum())
        self.assertAlmostEqual(out["returns"].loc[d], expected, places=12)
        self.assertEqual(out["weights"].loc[DAYS[41], "C00"], 0.0)
        # the original excludes the same coin on day 40 because day 41's open is missing
        orig = run_xs(opens, fund, score, rebalance_days=1, q=0.2, cost_bps=0)
        self.assertNotAlmostEqual(orig["returns"].loc[d], out["returns"].loc[d], places=6)

    def test_no_settlement_price_is_flagged_and_earns_zero(self):
        opens, last_close, fund = panel()
        opens.iloc[30:41, 0] = np.linspace(100, 300, 11)          # top momentum on day 40, so it is held
        opens.iloc[41:, 0] = np.nan
        last_close.iloc[40:, 0] = np.nan
        score = momentum_score(opens, 10)
        out = run_xs_pit(opens, last_close, fund, score, rebalance_days=1, q=0.2, cost_bps=0)
        self.assertGreater(out["weights"].loc[DAYS[40], "C00"], 0.0)
        flagged = [s for s in out["settlements"] if s["symbol"] == "C00"]
        self.assertEqual(flagged, [{"date": DAYS[40].isoformat(), "symbol": "C00", "price": "none_zero_return"}])

    def test_weights_on_day_d_use_no_data_after_d(self):
        opens, last_close, fund = panel()
        score = momentum_score(opens, 10)
        full = run_xs_pit(opens, last_close, fund, score, rebalance_days=1, q=0.2, cost_bps=0)["weights"]
        for d in DAYS[20:80:9]:
            cut = run_xs_pit(opens.loc[:d], last_close.loc[:d], fund.loc[:d], score.loc[:d], rebalance_days=1, q=0.2,
                             cost_bps=0)["weights"]
            pd.testing.assert_series_equal(full.loc[d], cut.loc[d], check_names=False)

    def test_last_close_panel_takes_last_bar_of_each_utc_day(self):
        idx = pd.date_range("2026-01-01", periods=6, freq="8h", tz="UTC")
        f = pd.DataFrame({"open": range(6), "close": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=idx)
        lc = daily_last_close_panel({"X": f})
        self.assertEqual(list(lc["X"]), [3.0, 6.0])


if __name__ == "__main__":
    unittest.main()
