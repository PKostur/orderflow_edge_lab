import json
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.condition_aggregate import aggregate_condition_reports
from orderflow_edge_lab.market_conditions import CONDITION_PROTOCOL
from orderflow_edge_lab.session_strategy_report import build_session_strategy_report


class SessionConditionAggregateTests(unittest.TestCase):
    def _write(self, root:Path, name:str, payload:dict)->Path:
        path=root/name
        path.write_text(json.dumps(payload),encoding="utf-8")
        return path

    def test_legacy_condition_protocol_backfills_named_session(self):
        legacy={k:v for k,v in CONDITION_PROTOCOL.items() if k!="trading_session_regime"}
        row={
            "batch_id":"batch_1:abc",
            "family":"aligned",
            "horizon_ms":15000,
            "fee_bps_round_trip":4.0,
            "signal_observed_at_ns":1788958800000000000,  # 2026-09-09 13:00 UTC, London+NY
            "net_bps":5.0,
            "gross_bps":9.0,
            "conditions":{"utc_session":"08-16"},
            "spread_bps":1.0,
            "local_range_15s_bps":5.0,
            "signal_strength_multiple":2.0,
        }
        report={
            "experiment":"pre_registered_market_condition_stratification",
            "symbol":"ENA_USDT",
            "context_symbol":"BTC_USDT",
            "condition_protocol":legacy,
            "horizons_ms":[15000],
            "fees_bps_round_trip":[4.0],
            "sources":[{"source_sha256":"a"*64}],
            "enriched_observations":[row],
        }
        with tempfile.TemporaryDirectory() as td:
            path=self._write(Path(td),"legacy.json",report)
            agg=aggregate_condition_reports([path])
        enriched=agg["enriched_observations"][0]
        self.assertIn("trading_session_regime",enriched["conditions"])
        self.assertEqual(enriched["conditions"]["trading_session_regime"],"LONDON+NEW_YORK")
        self.assertTrue(agg["historical_protocol_migration"]["named_session_condition_backfilled_from_signal_observed_at_ns"])

    def test_session_strategy_report_metrics(self):
        observations=[]
        for i,(regime,net,batch) in enumerate([
            ("ASIA",10.0,"a"),
            ("ASIA",-2.0,"b"),
            ("LONDON+NEW_YORK",4.0,"a"),
            ("LONDON+NEW_YORK",-8.0,"b"),
        ]):
            observations.append({
                "batch_id":batch,
                "family":"aligned",
                "horizon_ms":15000,
                "fee_bps_round_trip":4.0,
                "signal_observed_at_ns":1_000_000_000+i,
                "gross_bps":net+4.0,
                "net_bps":net,
                "side":-1,
                "conditions":{"trading_session_regime":regime},
                "spread_bps":1.0,
                "local_range_15s_bps":5.0,
                "signal_strength_multiple":2.0,
            })
        aggregate={
            "experiment":"multi_batch_market_condition_aggregate",
            "symbol":"ENA_USDT",
            "context_symbol":"BTC_USDT",
            "enriched_observations":observations,
        }
        result=build_session_strategy_report(aggregate)
        rows={(r["session_regime"]):r for r in result["rows"]}
        self.assertAlmostEqual(rows["ASIA"]["cumulative_net_bps"],8.0)
        self.assertAlmostEqual(rows["ASIA"]["net_mean_bps"],4.0)
        self.assertAlmostEqual(rows["ASIA"]["profit_factor"],5.0)
        self.assertAlmostEqual(rows["LONDON+NEW_YORK"]["max_drawdown_bps"],-8.0)
        self.assertTrue(rows["ASIA"]["sample_warning"])
        direction={(r["session_regime"],r["side"]):r for r in result["direction_rows"]}
        self.assertIn(("ASIA",-1),direction)
        self.assertEqual(direction[("ASIA",-1)]["direction"],"SHORT")

    def test_travel_profile_detects_non_decreasing_gross_path(self):
        observations=[]
        for horizon,gross in ((5000,1.0),(15000,2.0),(30000,5.0)):
            observations.append({
                "batch_id":"a",
                "family":"aligned_btc",
                "horizon_ms":horizon,
                "fee_bps_round_trip":4.0,
                "signal_observed_at_ns":1_000_000_000+horizon,
                "gross_bps":gross,
                "net_bps":gross-4.0,
                "side":-1,
                "conditions":{"trading_session_regime":"ASIA"},
                "spread_bps":1.0,
                "local_range_15s_bps":5.0,
                "signal_strength_multiple":2.0,
            })
        result=build_session_strategy_report({
            "experiment":"multi_batch_market_condition_aggregate",
            "symbol":"ENA_USDT",
            "context_symbol":"BTC_USDT",
            "enriched_observations":observations,
        })
        profile=next(p for p in result["travel_profiles"] if p["family"]=="aligned_btc")
        self.assertTrue(profile["gross_travel_monotonic_non_decreasing"])
        self.assertEqual([h["horizon_ms"] for h in profile["horizons"]],[5000,15000,30000])


if __name__=="__main__":
    unittest.main()
