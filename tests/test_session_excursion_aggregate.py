import json
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.session_excursion_aggregate import aggregate_session_excursions


class SessionExcursionAggregateTests(unittest.TestCase):
    def test_joins_conditions_and_risk_path_by_signal(self):
        with tempfile.TemporaryDirectory() as td:
            batch=Path(td)/"batch1"
            batch.mkdir()
            ns=1788958800000000000  # 2026-09-09 13:00 UTC, London+New York
            conditions={
                "enriched_observations":[{
                    "family":"aligned",
                    "signal_observed_at_ns":ns,
                    "horizon_ms":30000,
                    "fee_bps_round_trip":4.0,
                    "gross_bps":6.0,
                    "net_bps":2.0,
                    "batch_id":"batch_1:test",
                    "conditions":{
                        "btc_flow_alignment":"against",
                        "signal_strength_multiple":"medium1.5-2.5",
                        "spread_bps":"narrow<=1",
                        "range_to_spread_15s":"high>6",
                        "rolling_trade_count_10s":"intense>=9"
                    }
                }]
            }
            stop={
                "trades":[{
                    "stream":"original",
                    "family":"aligned",
                    "signal_observed_at_ns":ns,
                    "rr_target":3.0,
                    "requested_risk_fraction":0.0025,
                    "fee_bps_round_trip":4.0,
                    "mfe_bps":20.0,
                    "mae_bps":5.0,
                    "status":"time"
                }]
            }
            (batch/"conditions.json").write_text(json.dumps(conditions),encoding="utf-8")
            (batch/"stop_risk.json").write_text(json.dumps(stop),encoding="utf-8")
            report=aggregate_session_excursions(td)

        self.assertEqual(report["joined_observations"],1)
        row=report["by_family_session"][0]
        self.assertEqual(row["session_regime"],"LONDON+NEW_YORK")
        self.assertAlmostEqual(row["mfe_median_bps"],20.0)
        self.assertAlmostEqual(row["mae_median_bps"],5.0)
        context=report["by_family_session_btc_strength"]
        self.assertEqual(context,[])  # context rows require at least 10 observations

    def test_movement_context_rows_are_emitted_after_ten_observations(self):
        with tempfile.TemporaryDirectory() as td:
            batch=Path(td)/"batch1"
            batch.mkdir()
            observations=[]
            trades=[]
            base_ns=1788958800000000000
            for i in range(10):
                ns=base_ns+i*1_000_000
                observations.append({
                    "family":"cvd","signal_observed_at_ns":ns,"horizon_ms":30000,
                    "fee_bps_round_trip":4.0,"gross_bps":10.0,"net_bps":6.0,
                    "batch_id":"batch_1:test",
                    "conditions":{
                        "spread_bps":"wide>3",
                        "range_to_spread_15s":"high>6",
                        "btc_flow_alignment":"against",
                        "signal_strength_multiple":"strong>=2.5",
                        "rolling_trade_count_10s":"intense>=9"
                    }
                })
                trades.append({
                    "stream":"original","family":"cvd","signal_observed_at_ns":ns,
                    "rr_target":3.0,"requested_risk_fraction":0.0025,
                    "fee_bps_round_trip":4.0,"mfe_bps":20.0+i,"mae_bps":5.0,"status":"time"
                })
            (batch/"conditions.json").write_text(json.dumps({"enriched_observations":observations}),encoding="utf-8")
            (batch/"stop_risk.json").write_text(json.dumps({"trades":trades}),encoding="utf-8")
            report=aggregate_session_excursions(td)
        rows=report["by_family_session_spread_range_btc"]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["family"],"cvd")
        self.assertEqual(rows[0]["btc_flow_alignment"],"against")
        self.assertEqual(rows[0]["observations"],10)

    def test_duplicate_risk_sizing_rows_do_not_duplicate_signal(self):
        with tempfile.TemporaryDirectory() as td:
            batch=Path(td)/"batch1"
            batch.mkdir()
            ns=1788958800000000000
            (batch/"conditions.json").write_text(json.dumps({"enriched_observations":[{
                "family":"aligned","signal_observed_at_ns":ns,"horizon_ms":30000,
                "fee_bps_round_trip":4.0,"gross_bps":1.0,"net_bps":-3.0,
                "batch_id":"batch_1:test","conditions":{}
            }]}),encoding="utf-8")
            trade={"stream":"original","family":"aligned","signal_observed_at_ns":ns,
                   "rr_target":3.0,"requested_risk_fraction":0.0025,
                   "fee_bps_round_trip":4.0,"mfe_bps":3.0,"mae_bps":2.0,"status":"time"}
            (batch/"stop_risk.json").write_text(json.dumps({"trades":[trade,dict(trade)]}),encoding="utf-8")
            report=aggregate_session_excursions(td)
        self.assertEqual(report["joined_observations"],1)


if __name__=="__main__":
    unittest.main()
