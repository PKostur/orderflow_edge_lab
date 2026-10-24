import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.carry import Costs, daily_close, daily_funding, funding_filter, hedge_daily, summarize

DAYS = pd.date_range("2024-01-01", periods=60, freq="D", tz="UTC")


def hourly_frame(daily_prices):
    """Hourly bars indexed by bar end; the bar ending at day d 00:00 closes at daily_prices[d], others at -1."""
    idx = pd.date_range(DAYS[0] - pd.Timedelta(hours=23), DAYS[-1], freq="h", tz="UTC")
    close = pd.Series(-1.0, index=idx)
    close.loc[DAYS] = daily_prices
    return pd.DataFrame({"close": close})


class CarryTests(unittest.TestCase):
    def test_daily_close_takes_the_bar_ending_at_midnight(self):
        f = hourly_frame(np.linspace(100, 159, 60))
        c = daily_close(f)
        self.assertEqual(c.index[0], DAYS[0])
        self.assertAlmostEqual(c.iloc[1], 101.0)

    def test_funding_settled_at_midnight_belongs_to_the_day_ending_then(self):
        r = pd.Series([0.0001, 0.0002, 0.0003], index=pd.to_datetime(
            ["2024-01-01 08:00", "2024-01-01 16:00", "2024-01-02 00:00"], utc=True))
        d = daily_funding(r)
        self.assertEqual(list(d.index), [pd.Timestamp("2024-01-02", tz="UTC")])
        self.assertAlmostEqual(d.iloc[0], 0.0006)

    def test_flat_basis_constant_funding_earns_funding_minus_entry_and_exit(self):
        px = pd.Series(100.0, index=DAYS)
        fund = pd.Series(0.0003, index=DAYS)
        c = Costs(spot_taker_bps=10, perp_taker_bps=5, slippage_bps_per_leg=2)
        out = hedge_daily(px, px, fund, costs=c)
        self.assertFalse(out["active"].iloc[0])                    # entered at the first close, earns from day 2
        self.assertAlmostEqual(out["funding"].sum(), 0.0003 * 59)
        self.assertAlmostEqual(out["cost"].sum(), 2 * 19e-4)        # entry + exit, 19 bp per pair
        self.assertAlmostEqual(out["net"].sum(), 0.0003 * 59 - 38e-4)

    def test_basis_drift_is_charged_at_month_end(self):
        spot = pd.Series(100.0, index=DAYS)
        perp = spot.copy()
        perp.loc[DAYS[10]:] = 99.0                                  # perp cheapens 1% once, stays
        out = hedge_daily(spot, perp, pd.Series(0.0, index=DAYS), costs=Costs(10, 5, 2))
        self.assertAlmostEqual(out["basis"].sum(), 0.0 - (99.0 / 100.0 - 1))
        month_reset = out.loc[pd.Timestamp("2024-02-01", tz="UTC"), "cost"]
        self.assertAlmostEqual(month_reset, 2 * 9.5e-4 * 0.01, places=9)   # 2 legs x 9.5 bp x 1% drift

    def test_filter_switches_off_on_negative_funding_and_pays_each_switch(self):
        fund = pd.Series(0.0003, index=DAYS)
        fund.iloc[20:35] = -0.0005
        on = funding_filter(fund, 7)
        px = pd.Series(100.0, index=DAYS)
        out = hedge_daily(px, px, fund, costs=Costs(10, 5, 2), active=on)
        self.assertLess(out["funding"][out["funding"] < 0].sum(), 0)    # pays a few days before it reacts
        self.assertTrue((~out["active"].iloc[30:36]).any())
        switches = out["active"].astype(int).diff().abs().sum()
        self.assertAlmostEqual(out["cost"].sum(), (switches + 1) * 19e-4, places=9)

    def test_summary_reports_negative_funding_runs(self):
        fund = pd.Series(0.0003, index=DAYS)
        fund.iloc[5:9] = -0.0001
        px = pd.Series(100.0, index=DAYS)
        s = summarize(hedge_daily(px, px, fund)["net"], fund)
        self.assertEqual(s["longest_negative_funding_days"], 4)
        self.assertGreater(s["annual_return"], 0)


if __name__ == "__main__":
    unittest.main()
