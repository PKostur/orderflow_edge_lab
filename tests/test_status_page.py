from __future__ import annotations

import json
from pathlib import Path
import unittest

from orderflow_edge_lab.status_page import BEGIN, END, render_table, update_status, watch_rows


def _clock() -> dict:
    return json.loads(Path("config/prospective_review_clock_v1.json").read_text(encoding="utf-8"))


class StatusPageTests(unittest.TestCase):
    def test_rows_cover_calendar_watches_with_workflows_and_review_dates(self):
        rows = {r["watch_id"]: r for r in watch_rows(_clock())}
        self.assertEqual(rows["multi-premia-blend-v1"]["review"], "2027-03-28")
        self.assertEqual(rows["universal-trend-portfolio-forward-v1"]["review"], "2027-09-28")
        self.assertNotIn("SESSION_W3_CVD_LNY_WIDE_RANGE_BTC_AGAINST_V1", rows)  # batch gate, not calendar

    def test_snapshot_status_is_copied_not_computed(self):
        snap = {"items": [{"watch_id": "multi-premia-blend-v1", "status": "COLLECTING", "days": 4}]}
        row = next(r for r in watch_rows(_clock(), snap) if r["watch_id"] == "multi-premia-blend-v1")
        self.assertEqual((row["status"], row["scored_days"]), ("COLLECTING", 4))

    def test_update_replaces_only_the_marked_block_and_is_idempotent(self):
        block = render_table(watch_rows(_clock()), "t0")
        text = "# Status\n\nhand-written\n\n## Research stop rule (active)\n\nrules\n"
        once = update_status(text, block)
        self.assertIn(BEGIN, once)
        self.assertIn("hand-written", once)
        self.assertLess(once.index(END), once.index("## Research stop rule"))
        self.assertEqual(update_status(once, block), once)
        newer = update_status(once, render_table(watch_rows(_clock()), "t1"))
        self.assertEqual(newer.count(BEGIN), 1)
        self.assertIn("t1", newer)


if __name__ == "__main__":
    unittest.main()
