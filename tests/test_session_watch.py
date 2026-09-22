import unittest
from datetime import datetime, timezone

from orderflow_edge_lab.session_watch import build_session_watch_report


class SessionWatchTests(unittest.TestCase):
    def _row(self, iso, batch, horizon, fee, gross, family="aligned", side=-1):
        dt=datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone(timezone.utc)
        return {
            "batch_id":batch,
            "family":family,
            "side":side,
            "horizon_ms":horizon,
            "fee_bps_round_trip":fee,
            "signal_observed_at_ns":int(dt.timestamp()*1_000_000_000),
            "gross_bps":gross,
            "net_bps":gross-fee,
        }

    def _config(self):
        return {
            "prospective_watch_start_utc":"2026-09-22T15:39:58Z",
            "watches":[
                {
                    "watch_id":"W1",
                    "family":"aligned",
                    "side":-1,
                    "direction":"SHORT",
                    "session_phase":"ASIA_OPENING",
                    "horizons_ms":[5000,15000,30000],
                    "fees_bps_round_trip":[4.0],
                    "development_snapshot_30s_4bps":{},
                }
            ],
            "prospective_review_requirement":{
                "minimum_new_independent_batches":2,
                "minimum_new_calendar_days":2,
            },
        }

    def test_pre_boundary_rows_are_excluded(self):
        rows=[
            self._row("2026-09-22T00:30:00Z","old",30000,4.0,10.0),
            self._row("2026-09-23T00:30:00Z","new",30000,4.0,10.0),
        ]
        result=build_session_watch_report({
            "experiment":"multi_batch_market_condition_aggregate",
            "symbol":"ENA_USDT",
            "context_symbol":"BTC_USDT",
            "enriched_observations":rows,
        },self._config())
        watch=result["watches"][0]
        self.assertEqual(watch["prospective_unique_signals"],1)
        cell=next(c for c in watch["cells"] if c["horizon_ms"]==30000)
        self.assertEqual(cell["observations"],1)
        self.assertAlmostEqual(cell["net_mean_bps"],6.0)

    def test_condition_filtered_watch_uses_its_own_boundary(self):
        cfg=self._config()
        cfg["watches"].append({
            "watch_id":"W3",
            "family":"cvd",
            "side":None,
            "direction":"BOTH",
            "session_phase":None,
            "prospective_watch_start_utc":"2026-09-22T18:10:00Z",
            "conditions":{
                "trading_session_regime":"LONDON+NEW_YORK",
                "spread_bps":"wide>3",
                "range_to_spread_15s":"high>6",
                "btc_flow_alignment":"against",
            },
            "horizons_ms":[30000],
            "fees_bps_round_trip":[4.0],
        })
        def cvd(iso,batch,conditions):
            row=self._row(iso,batch,30000,4.0,12.0,family="cvd",side=1)
            row["conditions"]=conditions
            return row
        good={
            "trading_session_regime":"LONDON+NEW_YORK",
            "spread_bps":"wide>3",
            "range_to_spread_15s":"high>6",
            "btc_flow_alignment":"against",
        }
        wrong={**good,"btc_flow_alignment":"aligned"}
        rows=[
            cvd("2026-09-22T18:00:00Z","pre",good),
            cvd("2026-09-23T13:30:00Z","good",good),
            cvd("2026-09-23T13:31:00Z","wrong",wrong),
        ]
        result=build_session_watch_report({
            "experiment":"multi_batch_market_condition_aggregate",
            "symbol":"ENA_USDT",
            "context_symbol":"BTC_USDT",
            "enriched_observations":rows,
        },cfg)
        w3=next(w for w in result["watches"] if w["watch_id"]=="W3")
        self.assertEqual(w3["prospective_unique_signals"],1)
        self.assertEqual(w3["conditions"]["btc_flow_alignment"],"against")
        self.assertEqual(w3["prospective_watch_start_utc"],"2026-09-22T18:10:00Z")

    def test_readiness_uses_new_batches_and_days(self):
        rows=[]
        for iso,batch in [
            ("2026-09-23T00:30:00Z","a"),
            ("2026-09-24T00:30:00Z","b"),
        ]:
            for horizon,gross in [(5000,1.0),(15000,2.0),(30000,5.0)]:
                rows.append(self._row(iso,batch,horizon,4.0,gross))
        result=build_session_watch_report({
            "experiment":"multi_batch_market_condition_aggregate",
            "symbol":"ENA_USDT",
            "context_symbol":"BTC_USDT",
            "enriched_observations":rows,
        },self._config())
        watch=result["watches"][0]
        self.assertTrue(watch["ready_for_review"])
        self.assertEqual(watch["prospective_independent_batches"],2)
        self.assertEqual(watch["prospective_calendar_days"],2)
        travel=watch["travel_by_fee"][0]
        self.assertTrue(travel["gross_travel_monotonic_non_decreasing"])


if __name__=="__main__":
    unittest.main()
