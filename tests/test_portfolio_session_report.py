import unittest

from orderflow_edge_lab.portfolio_session_report import build_portfolio_session_report


class PortfolioSessionReportTests(unittest.TestCase):
    def test_groups_completed_8h_intervals_and_excludes_mtm(self):
        report={
            "candidate_id":"c1",
            "status":"collecting",
            "as_of_utc":"2026-09-22T12:00:00Z",
            "portfolio_intervals":[
                {"start":"2026-09-20T00:00:00+00:00","net_return":0.01,"gross_return":0.011,"is_current_mark_to_market_interval":False},
                {"start":"2026-09-20T08:00:00+00:00","net_return":0.02,"gross_return":0.021,"is_current_mark_to_market_interval":False},
                {"start":"2026-09-20T16:00:00+00:00","net_return":-0.005,"gross_return":-0.004,"is_current_mark_to_market_interval":False},
                {"start":"2026-09-21T08:00:00+00:00","net_return":0.03,"gross_return":0.031,"is_current_mark_to_market_interval":True},
            ],
        }
        out=build_portfolio_session_report(report)
        r=out["reports"]["c1"]
        self.assertEqual(r["buckets"]["ASIA_00_08"]["observations"],1)
        self.assertAlmostEqual(r["buckets"]["ASIA_00_08"]["cumulative_net_bps"],100.0)
        self.assertAlmostEqual(r["buckets"]["LONDON_PLUS_OVERLAP_08_16"]["cumulative_net_bps"],200.0)
        self.assertAlmostEqual(r["buckets"]["NY_POST_PLUS_LATE_16_24"]["cumulative_net_bps"],-50.0)

    def test_nested_markov_reports_are_supported(self):
        report={
            "reports":{
                "clone":{
                    "shadow_candidate_id":"clone",
                    "base_candidate_id":"base",
                    "status":"collecting",
                    "portfolio_intervals":[
                        {"start":"2026-09-20T08:00:00+00:00","net_return":0.01,"gross_return":0.01,"is_current_mark_to_market_interval":False},
                        {"start":"2026-09-21T08:00:00+00:00","net_return":-0.002,"gross_return":-0.002,"is_current_mark_to_market_interval":False},
                    ],
                }
            }
        }
        out=build_portfolio_session_report(report)
        cell=out["reports"]["clone"]["buckets"]["LONDON_PLUS_OVERLAP_08_16"]
        self.assertEqual(cell["observations"],2)
        self.assertAlmostEqual(cell["cumulative_net_bps"],80.0)
        self.assertAlmostEqual(cell["win_rate"],0.5)
        self.assertGreater(cell["profit_factor"],1.0)


if __name__=="__main__":
    unittest.main()
