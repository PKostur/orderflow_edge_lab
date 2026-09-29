"""Mechanical 180-day reviews for the research-branch forward watches (config/forward_formal_reviews_v1.json).

The evaluator reads a frozen watch report and returns a verdict from criteria registered before any
forward day existed. It chooses nothing at review time and authorizes nothing.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_CONFIG = Path("config/forward_formal_reviews_v1.json")


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _max_drawdown(returns: list[float]) -> float:
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        eq *= 1.0 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1.0)
    return mdd


def evaluate(spec: Mapping[str, Any], report: Mapping[str, Any], run_conclusions: Iterable[str],
             *, as_of: str | None = None) -> dict[str, Any]:
    if report.get("watch_id") != spec["watch_id"]:
        raise ValueError(f"report is for {report.get('watch_id')!r}, review is for {spec['watch_id']!r}")
    start = _utc(report["prospective_start_utc"])
    now = _utc(as_of or report["as_of_utc"])
    elapsed = (now - start).total_seconds() / 86400.0
    series = (report.get("daily_returns") or {}).get(spec["series"]) or {}
    returns = [float(v) for _, v in sorted(series.items())]
    out: dict[str, Any] = {"watch_id": spec["watch_id"], "series": spec["series"], "scored_days": len(returns),
                           "elapsed_calendar_days": round(elapsed, 3), "horizon_days": spec["horizon_days"],
                           "criteria": {}, "descriptive": dict((report.get("forward") or {}).get(spec["series"]) or {})}
    if elapsed < spec["horizon_days"]:
        out["verdict"] = "NOT_YET"
        return out
    c = spec["criteria"]
    res = out["criteria"]
    mean = sum(returns) / len(returns) if returns else math.nan
    if "mean_daily_return_gt" in c:
        res["mean_daily_return"] = {"value": mean, "threshold": c["mean_daily_return_gt"],
                                    "status": "not_evaluable" if not returns else ("pass" if mean > c["mean_daily_return_gt"] else "fail")}
    if "max_drawdown_not_worse_than" in c:
        mdd = _max_drawdown(returns) if returns else math.nan
        res["max_drawdown"] = {"value": mdd, "threshold": c["max_drawdown_not_worse_than"],
                               "status": "not_evaluable" if not returns else ("pass" if mdd >= c["max_drawdown_not_worse_than"] else "fail")}
    if "funding_drag_within_ratio_of_estimate" in c:
        fc = (report.get("funding_contribution") or {}).get(spec["series"]) or (report.get("funding_contribution") or {}).get("combined") or {}
        realized, estimate = fc.get("annualized"), fc.get("estimate_annualized")
        if realized is None or estimate in (None, 0):
            res["funding_drag"] = {"status": "not_evaluable",
                                   "reason": "the frozen report carries no forward-period funding estimate to compare with"}
        else:
            ratio = abs(float(realized)) / abs(float(estimate))
            res["funding_drag"] = {"realized": realized, "estimate": estimate, "ratio": ratio,
                                   "status": "pass" if ratio <= c["funding_drag_within_ratio_of_estimate"] else "fail"}
    if c.get("all_runs_succeeded"):
        runs = list(run_conclusions)
        bad = [r for r in runs if r != "success"]
        res["all_runs_succeeded"] = {"runs": len(runs), "not_success": len(bad),
                                     "status": "not_evaluable" if not runs else ("pass" if not bad else "fail")}
    states = [v["status"] for v in res.values()]
    out["verdict"] = "FAIL" if "fail" in states else ("INCOMPLETE" if "not_evaluable" in states else "PASS_SANITY_GATE")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Evaluate a registered forward formal review from a frozen watch report.")
    p.add_argument("--watch-id", required=True)
    p.add_argument("--report", required=True, help="the watch's report JSON at or after the horizon")
    p.add_argument("--run-conclusions", required=True, help="JSON list of every scheduled run conclusion in the window")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--output", required=True)
    a = p.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    spec = next(s for s in cfg["reviews"] if s["watch_id"] == a.watch_id)
    report = json.loads(Path(a.report).read_text(encoding="utf-8"))
    runs = json.loads(Path(a.run_conclusions).read_text(encoding="utf-8"))
    result = evaluate(spec, report, runs)
    result["claims"] = cfg["claims"]
    Path(a.output).write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps({"watch_id": a.watch_id, "verdict": result["verdict"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
