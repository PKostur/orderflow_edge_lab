from __future__ import annotations

import json
from pathlib import Path
import unittest

import pandas as pd

from orderflow_edge_lab.forward_formal_review import evaluate


def _cfg() -> dict:
    return json.loads(Path("config/forward_formal_reviews_v1.json").read_text(encoding="utf-8"))


def _spec(watch_id: str) -> dict:
    return next(s for s in _cfg()["reviews"] if s["watch_id"] == watch_id)


def _report(watch_id: str, series: str, returns: list[float], *, funding=None) -> dict:
    idx = pd.date_range("2026-09-30", periods=len(returns), freq="D", tz="UTC")
    r = {"watch_id": watch_id, "prospective_start_utc": "2026-09-29T00:00:00Z",
         "as_of_utc": (idx[-1] + pd.Timedelta(hours=8)).isoformat() if len(idx) else "2026-09-29T08:00:00Z",
         "daily_returns": {series: {t.isoformat(): v for t, v in zip(idx, returns)}}, "forward": {series: {}}}
    if funding is not None:
        r["funding_contribution"] = {"combined": funding}
    return r


class ForwardFormalReviewTests(unittest.TestCase):
    def test_registered_before_any_forward_day_and_authorizes_nothing(self):
        cfg = _cfg()
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_ANY_FORWARD_DAY")
        self.assertFalse(any(cfg["claims"].values()))
        self.assertEqual({s["watch_id"] for s in cfg["reviews"]},
                         {"multi-premia-blend-v1", "multi-premia-human-v1-forward", "crypto-trend-core-v1", "crypto-trend-core-voltarget-v1"})

    def test_not_yet_before_horizon(self):
        out = evaluate(_spec("multi-premia-blend-v1"), _report("multi-premia-blend-v1", "S4_blend", [0.001] * 100), ["success"])
        self.assertEqual(out["verdict"], "NOT_YET")

    def test_blend_pass_and_drawdown_fail(self):
        spec = _spec("multi-premia-blend-v1")
        ok = evaluate(spec, _report(spec["watch_id"], "S4_blend", [0.001, -0.0005] * 91), ["success"] * 182)
        self.assertEqual(ok["verdict"], "PASS_SANITY_GATE")
        crash = [0.002] * 100 + [-0.03] * 10 + [0.002] * 72  # about -26% drawdown
        bad = evaluate(spec, _report(spec["watch_id"], "S4_blend", crash), ["success"] * 182)
        self.assertEqual(bad["criteria"]["max_drawdown"]["status"], "fail")
        self.assertEqual(bad["verdict"], "FAIL")

    def test_failed_run_fails_the_gate(self):
        spec = _spec("multi-premia-blend-v1")
        out = evaluate(spec, _report(spec["watch_id"], "S4_blend", [0.001] * 182), ["success"] * 181 + ["failure"])
        self.assertEqual(out["verdict"], "FAIL")

    def test_trend_core_funding_criterion_is_incomplete_without_an_estimate(self):
        spec = _spec("crypto-trend-core-v1")
        out = evaluate(spec, _report(spec["watch_id"], "combined", [0.001] * 182, funding={"annualized": -0.01, "days": 182}),
                       ["success"] * 182)
        self.assertEqual(out["criteria"]["funding_drag"]["status"], "not_evaluable")
        self.assertEqual(out["verdict"], "INCOMPLETE")
        with_est = _report(spec["watch_id"], "combined", [0.001] * 182,
                           funding={"annualized": -0.01, "estimate_annualized": -0.008, "days": 182})
        self.assertEqual(evaluate(spec, with_est, ["success"] * 182)["verdict"], "PASS_SANITY_GATE")


if __name__ == "__main__":
    unittest.main()
