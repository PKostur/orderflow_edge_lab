import unittest

import pandas as pd

from orderflow_edge_lab.daily_portfolio_session import build_daily_portfolio_session_report


class DailyPortfolioSessionTests(unittest.TestCase):
    def test_three_buckets_reconcile_daily_gross_and_funding(self):
        idx=pd.to_datetime([
            "2026-09-14T00:00:00Z",
            "2026-09-14T08:00:00Z",
            "2026-09-14T16:00:00Z",
            "2026-09-15T00:00:00Z",
        ])
        bars={
            "A":pd.DataFrame({"open":[100.0,102.0,101.0,104.0]},index=idx),
            "B":pd.DataFrame({"open":[200.0,198.0,202.0,196.0]},index=idx),
        }
        funding={
            "A":pd.DataFrame({"funding_rate":[0.001,0.002,0.003]},index=pd.to_datetime([
                "2026-09-14T08:00:00Z","2026-09-14T16:00:00Z","2026-09-15T00:00:00Z"
            ])),
            "B":pd.DataFrame({"funding_rate":[0.0,0.0,0.0]},index=pd.to_datetime([
                "2026-09-14T08:00:00Z","2026-09-14T16:00:00Z","2026-09-15T00:00:00Z"
            ])),
        }
        weights={"A":0.5,"B":-0.5}
        gross=0.5*(104/100-1)-0.5*(196/200-1)
        fund=-0.5*(0.001+0.002+0.003)
        report={
            "candidate_id":"xs",
            "as_of_utc":"2026-09-15T01:00:00Z",
            "current_weights":weights,
            "rebalance_events":[{"execution_time":"2026-09-14T00:00:00Z","weights":weights}],
            "portfolio_intervals":[{
                "start":"2026-09-14T00:00:00Z",
                "end":"2026-09-15T00:00:00Z",
                "is_current_mark_to_market_interval":False,
                "gross_return":gross,
                "funding_return":fund,
                "trading_cost_return":-0.001,
            }],
        }
        out=build_daily_portfolio_session_report(report,bars_8h=bars,funding=funding)
        self.assertTrue(out["reconciliation"]["passed"])
        self.assertLess(out["reconciliation"]["max_abs_gross_error_bps"],1e-8)
        self.assertLess(out["reconciliation"]["max_abs_funding_error_bps"],1e-8)
        total=sum(out["metrics"][name]["cumulative_contribution_bps"] for name in out["metrics"])
        self.assertAlmostEqual(total,(gross+fund)*10000.0)


if __name__=="__main__":
    unittest.main()
