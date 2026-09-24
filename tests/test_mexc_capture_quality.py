from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.mexc_capture_quality import (
    aggregate_capture_quality,
    audit_mexc_feature_capture,
)


class MexcCaptureQualityTests(unittest.TestCase):
    def _config(self):
        return {"expected_symbols":["A","B"],"minimum_valid_book_fraction":0.9}

    def _capture(self,path:Path,gap=False):
        rows=[]
        for symbol in ("A","B"):
            rows.append({"event_type":"snapshot","symbol":symbol,"received_at_ns":1,"best_bid":99,"best_ask":101})
            rows.append({"event_type":"depth","symbol":symbol,"received_at_ns":2,"best_bid":100,"best_ask":101})
        rows.append({
            "record_type":"session_summary",
            "reconnects":0,
            "depth_stats":{
                "A":{"depth_messages_seen":10,"compressed_depth_ranges_seen":1,"true_depth_gaps_seen":1 if gap else 0,"stale_depth_messages_seen":0},
                "B":{"depth_messages_seen":10,"compressed_depth_ranges_seen":0,"true_depth_gaps_seen":0,"stale_depth_messages_seen":1},
            },
        })
        path.write_text("\n".join(json.dumps(r) for r in rows)+"\n",encoding="utf-8")

    def test_audit_passes_clean_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"features.jsonl"
            self._capture(p)
            result=audit_mexc_feature_capture(p,self._config())
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["observed_expected_symbol_count"],2)
        self.assertEqual(result["per_symbol"][0]["valid_book_fraction"],1.0)

    def test_recovered_gap_is_warning_not_retroactive_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"features.jsonl"
            self._capture(p,gap=True)
            result=audit_mexc_feature_capture(p,self._config())
        self.assertEqual(result["status"],"WARN")
        self.assertTrue(any("recovered_depth_gaps" in x for x in result["warning_reasons"]))
        self.assertFalse(result["claims"]["retroactive_evidence_exclusion_authorized"])

    def test_aggregate_preserves_quality_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=[]
            for i,gap in enumerate((False,True)):
                f=root/f"f{i}.jsonl"
                self._capture(f,gap=gap)
                report=audit_mexc_feature_capture(f,self._config())
                p=root/f"r{i}.json"
                p.write_text(json.dumps(report),encoding="utf-8")
                paths.append(p)
            result=aggregate_capture_quality(paths)
        self.assertEqual(result["report_count"],2)
        self.assertEqual(result["status_counts"]["PASS"],1)
        self.assertEqual(result["status_counts"]["WARN"],1)


if __name__=="__main__":
    unittest.main()
