import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.evidence_v2_session_forward import build_forward_session_report


class EvidenceV2SessionForwardTests(unittest.TestCase):
    def _config(self):
        return {
            "watch_id":"test_watch",
            "prospective_start_utc":"2026-09-23T00:00:00Z",
            "source":{"symbols":["A","B"]},
            "economics":{"round_trip_cost_bps":20.0},
            "variants":[{
                "audit_id":"DON8",
                "family":"donchian_breakout",
                "interval":"8h",
                "parameters":{"lookback":2},
                "role":"PRIMARY_SESSION_HYPOTHESIS",
            }],
            "session_buckets":[
                {"name":"ASIA_00_08","start_utc_hour":0,"end_utc_hour":8},
                {"name":"LONDON_PLUS_OVERLAP_08_16","start_utc_hour":8,"end_utc_hour":16},
                {"name":"NY_POST_PLUS_LATE_16_24","start_utc_hour":16,"end_utc_hour":24},
            ],
            "primary_hypothesis":{"strategy":"DON8","statement":"test"},
            "reporting":{"review_after_calendar_days":30},
            "claims":{"candidate_promoted":False,"live_trading_authorized":False,"leverage_authorized":False},
        }

    def _frame(self, scale=1.0):
        idx=pd.date_range("2026-09-15T00:00:00Z",periods=40,freq="8h")
        base=np.linspace(100.0,140.0,len(idx))*scale
        return pd.DataFrame({
            "open":base,
            "high":base*1.01,
            "low":base*0.99,
            "close":base*1.005,
            "volume":1000.0,
        },index=idx)

    def test_post_start_scoring_and_portfolio_reconciliation(self):
        frames={"8h":{"A":self._frame(1.0),"B":self._frame(2.0)}}
        report=build_forward_session_report(
            self._config(),
            frames_by_interval=frames,
            as_of_utc="2026-09-25T00:00:00Z",
        )
        self.assertEqual(report["status"],"ACCUMULATING")
        strategy=report["reports"][0]
        self.assertTrue(strategy["interval_rows"])
        for row in strategy["interval_rows"]:
            self.assertGreaterEqual(pd.Timestamp(row["start"]),pd.Timestamp("2026-09-23T00:00:00Z"))
            self.assertAlmostEqual(
                row["portfolio_net_return"]*10000.0,
                sum(row["symbol_net_contribution_bps"].values()),
                places=9,
            )
        names={x["session_bucket"] for x in strategy["by_session_bucket"]}
        self.assertEqual(names,{"ASIA_00_08","LONDON_PLUS_OVERLAP_08_16","NY_POST_PLUS_LATE_16_24"})

    def test_pre_start_report_scores_zero_intervals(self):
        frames={"8h":{"A":self._frame(1.0),"B":self._frame(2.0)}}
        report=build_forward_session_report(
            self._config(),
            frames_by_interval=frames,
            as_of_utc="2026-09-22T20:00:00Z",
        )
        self.assertEqual(report["status"],"PRE_START")
        self.assertEqual(report["reports"][0]["all_intervals"]["intervals"],0)


if __name__=="__main__":
    unittest.main()
