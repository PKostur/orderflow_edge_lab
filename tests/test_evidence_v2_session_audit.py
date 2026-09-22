import unittest
import pandas as pd

from orderflow_edge_lab.evidence_v2_session_audit import _bucket_name, _summarize


class EvidenceV2SessionAuditTests(unittest.TestCase):
    def test_bucket_mapping(self):
        buckets=[
            {"name":"ASIA_00_08","start_utc_hour":0,"end_utc_hour":8},
            {"name":"LONDON_PLUS_OVERLAP_08_16","start_utc_hour":8,"end_utc_hour":16},
            {"name":"NY_POST_PLUS_LATE_16_24","start_utc_hour":16,"end_utc_hour":24},
        ]
        self.assertEqual(_bucket_name(0,buckets),"ASIA_00_08")
        self.assertEqual(_bucket_name(7,buckets),"ASIA_00_08")
        self.assertEqual(_bucket_name(8,buckets),"LONDON_PLUS_OVERLAP_08_16")
        self.assertEqual(_bucket_name(15,buckets),"LONDON_PLUS_OVERLAP_08_16")
        self.assertEqual(_bucket_name(16,buckets),"NY_POST_PLUS_LATE_16_24")
        self.assertEqual(_bucket_name(23,buckets),"NY_POST_PLUS_LATE_16_24")

    def test_summary_tracks_symbol_fold_year_and_excursion(self):
        start=pd.Timestamp("2024-01-01T00:00:00Z")
        rows=[
            {
                "symbol":"A","entry":"2024-01-02T08:00:00+00:00","entry_epoch_ns":int(pd.Timestamp("2024-01-02T08:00:00Z").value),
                "entry_year":2024,"entry_hour_utc":8,"session_bucket":"LONDON_PLUS_OVERLAP_08_16",
                "side":1,"bars_held":2,"gross_bps":14.0,"net_bps":10.0,"mfe_bps":20.0,"mae_bps":-5.0,
            },
            {
                "symbol":"B","entry":"2024-01-03T08:00:00+00:00","entry_epoch_ns":int(pd.Timestamp("2024-01-03T08:00:00Z").value),
                "entry_year":2024,"entry_hour_utc":8,"session_bucket":"LONDON_PLUS_OVERLAP_08_16",
                "side":-1,"bars_held":3,"gross_bps":0.0,"net_bps":-4.0,"mfe_bps":8.0,"mae_bps":-9.0,
            },
            {
                "symbol":"A","entry":"2024-05-05T08:00:00+00:00","entry_epoch_ns":int(pd.Timestamp("2024-05-05T08:00:00Z").value),
                "entry_year":2024,"entry_hour_utc":8,"session_bucket":"LONDON_PLUS_OVERLAP_08_16",
                "side":1,"bars_held":1,"gross_bps":9.0,"net_bps":5.0,"mfe_bps":12.0,"mae_bps":-3.0,
            },
        ]
        s=_summarize(rows,fold_start=start,fold_days=120)
        self.assertEqual(s["trades"],3)
        self.assertAlmostEqual(s["cumulative_net_bps"],11.0)
        self.assertEqual(s["symbols"],2)
        self.assertEqual(s["folds"],2)
        self.assertAlmostEqual(s["positive_120d_fold_fraction"],1.0)
        self.assertAlmostEqual(s["median_mfe_bps"],12.0)
        self.assertAlmostEqual(s["median_mae_bps"],-5.0)
        self.assertIn("2024",s["year_expectancy_bps"])


if __name__=="__main__":
    unittest.main()
