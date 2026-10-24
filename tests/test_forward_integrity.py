import json
import tempfile
import unittest
from pathlib import Path

from orderflow_edge_lab.forward_integrity import build_integrity_report


def write_run(root: Path, aid: int, created: str, files: dict, name: str = "multi-premia-blend-v1") -> dict:
    rel = Path(name) / created[:10] / f"{900 + aid}-{aid}"
    (root / rel).mkdir(parents=True, exist_ok=True)
    for fn, payload in files.items():
        (root / rel / fn).write_text(json.dumps(payload), encoding="utf-8")
    return {"artifact_id": aid, "name": name, "created_at": created, "path": str(rel), "run_id": 900 + aid}


def report(values: dict, coins: int = 70, missing=None, book: str = "S4_blend") -> dict:
    return {"coins_with_data": coins, "missing_symbols": missing or [],
            "daily_returns": {book: {f"2026-10-{d:02d}T00:00:00+00:00": v for d, v in values.items()}}}


WATCHES = [("Multi-premia blend", "multi-premia-blend-v1", "report.json", "S4_blend")]


class IntegrityTests(unittest.TestCase):
    def build(self, runs):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        rows = [write_run(root, *r) for r in runs]
        (root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return build_integrity_report(root, WATCHES)

    def test_revision_and_dropped_coin_are_flagged(self):
        out = self.build([
            (1, "2026-10-14T01:00:00Z", {"report.json": report({12: 0.010, 13: 0.020})}),
            (2, "2026-10-14T20:00:00Z", {"report.json": report({12: 0.011, 13: 0.020}, coins=69, missing=["PHA_USDT"])}),
            (3, "2026-10-15T01:00:00Z", {"report.json": report({12: 0.010, 13: 0.020, 14: -0.01})}),
        ])
        w = out["watches"]["Multi-premia blend"]
        self.assertEqual(w["revised_stamps"], 1)
        rev = w["revisions"][0]
        self.assertEqual(rev["stamp"], "2026-10-12T00:00:00+00:00")
        self.assertAlmostEqual(rev["range_bps"], 10.0)
        self.assertTrue(rev["latest_equals_first"])
        self.assertEqual(w["coverage_drops"], [{"artifact": 2, "created_at": "2026-10-14T20:00:00Z", "coins_with_data": 69,
                                                "expected": 70, "missing_symbols": ["PHA_USDT"]}])
        self.assertEqual(w["stamp_times_utc"], ["00:00"])
        self.assertEqual(out["summary"]["watches_with_revisions"], ["Multi-premia blend"])
        self.assertEqual(out["summary"]["runs_with_coverage_drops"], 1)

    def test_clean_history_reports_nothing(self):
        out = self.build([
            (1, "2026-10-14T01:00:00Z", {"report.json": report({12: 0.01})}),
            (2, "2026-10-15T01:00:00Z", {"report.json": report({12: 0.01, 13: 0.02})}),
        ])
        w = out["watches"]["Multi-premia blend"]
        self.assertEqual((w["revised_stamps"], w["coverage_drops"]), (0, []))
        self.assertEqual(out["summary"]["watches_with_revisions"], [])

    def test_missing_report_file_and_unknown_watch_do_not_crash(self):
        out = self.build([(1, "2026-10-14T01:00:00Z", {"other.json": {}})])
        self.assertEqual(out["watches"]["Multi-premia blend"]["artifacts_with_series"], 0)


if __name__ == "__main__":
    unittest.main()
