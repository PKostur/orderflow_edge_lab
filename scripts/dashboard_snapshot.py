"""Build the monitoring-dashboard documents from the latest GitHub Actions runs. Descriptive only.

Writes three JSON documents into an output directory (default artifacts/dashboard):
  summary.json  - generation time, branch heads, open PRs, static research ledger
  watches.json  - one entry per forward watch: status, per-book stats, cumulative series, latest human book
  runs.json     - latest run of every workflow (name, branch, time, conclusion, url)
The Claude monitor writes these to the dashboard artifact's db (collection `dash`).
Needs `gh` on PATH and an authenticated session.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys
import tempfile

REPO = "PKostur/orderflow_edge_lab"
BRANCH = "research/payoff-geometry-v1-1"

# (workflow file, report file name, display name, group, primary book, review horizon days)
WATCHES = [
    ("multi-premia-blend-v1.yml", "report.json", "Multi-premia blend", "Lead candidate", "S4_blend", 180),
    ("multi-premia-blend-v1.yml", "human_report.json", "Multi-premia, 5-coin human book", "Lead candidate", "H5", 180),
    ("crypto-trend-core-v1.yml", "report.json", "Crypto trend core", "Trend", "combined", 180),
    ("crypto-trend-core-voltarget-v1.yml", "report.json", "Crypto trend core + vol target", "Trend", "core_voltarget", 180),
    ("trend-portfolio-forward-v1.yml", "report.json", "Trend portfolio (10 coins)", "Trend", "plain", 180),
    ("cross-asset-trend-forward-v1.yml", "report.json", "Cross-asset trend", "Cross-asset", "combined", 180),
    ("cross-asset-trend-invvol-forward-v1.yml", "report.json", "Cross-asset trend, inverse-vol", "Cross-asset", "combined", 180),
    ("multi-premia-blend-v1.yml", "zoo_mirror_report.json", "Zoo mirrors (BTC shock reversal, lottery momentum)", "Forward-only candidates", "M4_lottery_momentum", 180),
    ("canonical-v3-forward-companion-v1.yml", "report.json", "Canonical v3 companion", "Accounting", None, None),
]

LEDGER = [
    {"name": "Multi-premia blend, 60 untouched coins", "kind": "holdout", "verdict": "pass", "sharpe": 1.39, "t": 3.16, "note": "DD −11%, halves 1.41 / 1.37"},
    {"name": "Multi-premia blend, development (70 coins)", "kind": "development", "verdict": "pass", "sharpe": 2.09, "t": 4.48, "note": "robust to neighbours 1.6–2.2"},
    {"name": "5-coin human book, 60 untouched coins", "kind": "holdout", "verdict": "fail", "sharpe": 0.60, "t": 1.40, "note": "concentration is the weak link"},
    {"name": "Trend core, pre-window 2020–23", "kind": "holdout", "verdict": "pass", "sharpe": 1.76, "t": 3.13, "note": "2021-heavy"},
    {"name": "Trend core, 53 untouched coins", "kind": "holdout", "verdict": "pass", "sharpe": 0.91, "t": 2.00, "note": "marginal"},
    {"name": "Trend core, 7 untouched coins", "kind": "holdout", "verdict": "fail", "sharpe": 0.76, "t": 1.87, "note": "narrow fail"},
    {"name": "Trend rules on 20 ETFs", "kind": "holdout", "verdict": "fail", "sharpe": -0.31, "t": -1.25, "note": "rules are crypto-specific"},
    {"name": "XS low-vol leg", "kind": "holdout", "verdict": "fail", "sharpe": 0.15, "t": 0.35, "note": "lowers the blend"},
    {"name": "D4 volatility-state replication", "kind": "formal review", "verdict": "fail", "sharpe": None, "t": None, "note": "not replicated directionally"},
    {"name": "Session watches W1, W2", "kind": "formal review", "verdict": "fail", "sharpe": None, "t": None, "note": "falsified 2026-09-29"},
]


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True, check=True).stdout


def latest_run(workflow: str) -> dict | None:
    # gh resolves workflow file names only for files on the default branch, so use the workflow's display name
    wf_file = pathlib.Path(".github/workflows") / workflow
    name = workflow
    if wf_file.exists():
        for line in wf_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"')
                break
    # latest completed run: an in-progress run has no report artifact yet
    out = json.loads(gh("run", "list", "-w", name, "-b", BRANCH, "-s", "completed", "-L", "1",
                        "--json", "databaseId,conclusion,status,createdAt,url"))
    return out[0] if out else None


def cumulative(series: dict[str, float], keep: int = 400) -> list[list]:
    items = sorted(series.items())[-keep:]
    out, eq = [], 1.0
    for t, r in items:
        eq *= 1.0 + float(r)
        out.append([t[:10], round(eq - 1.0, 6)])
    return out


def watch_entry(spec, cache: dict[int, pathlib.Path]) -> dict:
    wf, fname, name, group, primary, horizon = spec
    e = {"id": wf.removesuffix(".yml") + ("" if fname == "report.json" else "-" + fname.removesuffix("_report.json")), "name": name, "group": group,
         "workflow": wf, "primary": primary, "review_days": horizon}
    clock = json.loads(pathlib.Path("config/prospective_review_clock_v1.json").read_text(encoding="utf-8"))
    run = latest_run(wf)
    if not run:
        e["status"] = "NO_RUNS"
        return e
    e.update(run_id=run["databaseId"], run_time=run["createdAt"], run_url=run["url"],
             run_conclusion=run["conclusion"] or run["status"])
    rid = run["databaseId"]
    if rid not in cache:
        d = pathlib.Path(tempfile.mkdtemp())
        subprocess.run(["gh", "run", "download", str(rid), "-D", str(d), "-R", REPO], capture_output=True)
        cache[rid] = d
    found = list(cache[rid].rglob(fname))
    if not found:
        e["status"] = "NO_REPORT"
        return e
    r = json.loads(found[0].read_text(encoding="utf-8"))
    gate = next((w["review_gate"] for w in clock["watches"] if w["watch_id"] == r.get("watch_id")), {})
    if gate.get("type") == "calendar_days":
        e["review_days"] = int(gate["minimum_days"])  # the registered gate, not the display default
    e.update(watch_id=r.get("watch_id"), status=r.get("status"), as_of=r.get("as_of_utc"),
             start=(r.get("prospective_start_utc") or "")[:10], review_open=bool(r.get("review_window_open")))
    books = {}
    for k, s in (r.get("forward") or {}).items():
        books[k] = {"days": s.get("days"), "sharpe": s.get("annualized_sharpe"), "t": s.get("newey_west_t"),
                    "cum": s.get("cumulative_return"), "mdd": s.get("max_drawdown"), "mean_bps": s.get("mean_daily_bps"),
                    "series": cumulative((r.get("daily_returns") or {}).get(k) or {})}
    e["books"] = books
    if "strategies" in r:
        e["days"] = r.get("calendar_days_elapsed")
        e["strategies"] = {str(s.get("audit_id") or s.get("strategy_id") or i): {kk: vv for kk, vv in s.items() if isinstance(vv, (int, float, str))}
                           for i, s in enumerate(r["strategies"])} if isinstance(r["strategies"], list) else {}
    else:
        e["days"] = (books.get(primary) or {}).get("days") or 0
    if "latest_book" in r:
        e["latest_book"] = r["latest_book"]
    return e


def main(out_dir: str = "artifacts/dashboard") -> int:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cache: dict[int, pathlib.Path] = {}
    watches = [watch_entry(s, cache) for s in WATCHES]
    runs_raw = json.loads(gh("run", "list", "-L", "150", "--json", "workflowName,headBranch,createdAt,conclusion,status,url,event"))
    latest: dict[str, dict] = {}
    for r in runs_raw:
        latest.setdefault(r["workflowName"], r)
    runs = [{"name": k, "branch": v["headBranch"], "time": v["createdAt"], "event": v["event"],
             "conclusion": v["conclusion"] or v["status"], "url": v["url"]} for k, v in latest.items()]
    runs.sort(key=lambda x: x["time"], reverse=True)
    prs = json.loads(gh("pr", "list", "--state", "open", "--json", "number,title,isDraft,url,headRefName"))
    heads = {}
    for b in (BRANCH, "main", "fix/universal-existing-validation"):
        c = json.loads(subprocess.run(["gh", "api", f"repos/{REPO}/commits/{b}", "--jq",
                                       "{sha: .sha[0:7], date: .commit.committer.date, msg: .commit.message}"],
                                      capture_output=True, text=True, check=True).stdout)
        c["msg"] = c["msg"].splitlines()[0][:100]
        heads[b] = c
    failed = [r for r in runs if r["conclusion"] in ("failure", "timed_out", "startup_failure")]
    summary = {"generated_utc": now, "heads": heads, "open_prs": prs, "ledger": LEDGER,
               "counts": {"watches": len(watches), "runs": len(runs), "failed_latest": len(failed)},
               "boundary": {"live_order_transmission": False, "profitable_edge_established": False, "promotion": False}}
    for name, doc in (("summary", summary), ("watches", {"generated_utc": now, "items": watches}),
                      ("runs", {"generated_utc": now, "items": runs})):
        (out / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")
    print(json.dumps({"generated": now, "watches": [(w["name"], w.get("status"), w.get("days")) for w in watches],
                      "failed_latest": [r["name"] for r in failed]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
