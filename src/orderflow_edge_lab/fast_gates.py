"""fast-gates-v1 (config/fast_gates_v1.json): early, narrow answers about the 70-coin blend. Descriptive only.

G1 implementation: paper account vs theoretical V_ALL (checkpoints at 30 and 60 scored days).
G2 breakage alarm: S4 blend drawdown and rolling 60-day return against bootstrap thresholds (180 days).
G3 venue replication: one-off historical result, read from research/fast_gates/venue_replication.json.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

WATCH_ID = "fast-gates-v1"


def _series(d: Mapping[str, float] | None) -> pd.Series:
    if not d:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    s = pd.Series({pd.Timestamp(k).floor("D"): float(v) for k, v in d.items()}, dtype=float)
    return s.groupby(level=0).sum().sort_index()


def implementation_gate(paper: pd.Series, v_all: pd.Series, coins: int | None, *, start: pd.Timestamp, as_of: pd.Timestamp,
                        th: Mapping[str, Any], checkpoints: list[int]) -> dict[str, Any]:
    # the first paper day carries the one-off cost of building the book from cash; calibration excluded it too
    paper = paper[paper.index > start + pd.Timedelta(days=1)]
    common = paper.index.intersection(v_all.index)
    diff = (paper.loc[common] - v_all.loc[common]).dropna()
    first = start + pd.Timedelta(days=2)
    expected = max(0, (as_of.floor("D") - first).days)  # dates whose 08:00 close has certainly passed
    out: dict[str, Any] = {"days": int(len(diff)), "expected_days": int(expected),
                           "cum_diff": float(diff.sum()) if len(diff) else 0.0,
                           "te_annualized": float(diff.std(ddof=1) * math.sqrt(365.0)) if len(diff) > 1 else None,
                           "checkpoints": {}}
    for n in checkpoints:
        if len(diff) < n:
            continue
        x = diff.iloc[:n]
        centre = float(th["mean_daily_diff"]) * n
        half = 3.0 * float(th["sd_rolling_sum"][str(n)])
        te = float(x.std(ddof=1) * math.sqrt(365.0))
        missing = max(0, (x.index[-1] - first).days + 1 - n)
        rules = {"data": bool(missing <= int(th["max_missing_days"]) and (coins or 0) >= int(th["min_coins"])),
                 "band": bool(abs(float(x.sum()) - centre) <= half),
                 "tracking_error": bool(te <= float(th["max_te_annualized"]))}
        ok = all(rules.values())
        final = n == max(checkpoints)
        out["checkpoints"][str(n)] = {"cum_diff": float(x.sum()), "band": [centre - half, centre + half], "te_annualized": te,
                                      "missing_days": int(missing), "rules": rules,
                                      "verdict": ("PASS" if ok else "FAIL") if final else ("ON_TRACK" if ok else "OFF_TRACK")}
    done = [out["checkpoints"][str(n)]["verdict"] for n in checkpoints if str(n) in out["checkpoints"]]
    out["status"] = done[-1] if done else ("PRE_START" if not len(diff) else "COLLECTING")
    return out


def breakage_alarm(s4: pd.Series, *, start: pd.Timestamp, th: Mapping[str, Any], window: int) -> dict[str, Any]:
    x = s4[s4.index > start].iloc[:window]
    if not len(x):
        return {"days": 0, "status": "PRE_START"}
    eq = (1.0 + x).cumprod()
    peak = pd.concat([pd.Series([1.0]), eq.reset_index(drop=True)]).cummax().iloc[1:].to_numpy()
    mdd = float((eq.to_numpy() / peak - 1.0).min())
    roll = (1.0 + x).rolling(60).apply(lambda w: w.prod(), raw=True).dropna() - 1.0
    min60 = float(roll.min()) if len(roll) else None
    hit_dd = mdd < float(th["max_drawdown_alarm"])
    hit_60 = min60 is not None and min60 < float(th["min_rolling_60d_alarm"])
    status = "ALARM" if (hit_dd or hit_60) else ("CLOSED_OK" if len(x) >= window else "OK")
    return {"days": int(len(x)), "cum": float(eq.iloc[-1] - 1.0), "max_drawdown": mdd, "min_rolling_60d": min60,
            "thresholds": {"max_drawdown": th["max_drawdown_alarm"], "min_rolling_60d": th["min_rolling_60d_alarm"]},
            "rules_hit": {"drawdown": bool(hit_dd), "rolling_60d": bool(hit_60)}, "status": status}


def build_report(cfg: Mapping[str, Any], reports: Mapping[str, Mapping[str, Any] | None], venue: Mapping[str, Any] | None,
                 *, as_of: Any) -> dict[str, Any]:
    if cfg.get("watch_id") != WATCH_ID or not cfg.get("thresholds"):
        raise ValueError("expects the frozen fast-gates-v1 config with thresholds")
    as_of_ts = pd.Timestamp(as_of)
    as_of_ts = as_of_ts.tz_localize("UTC") if as_of_ts.tzinfo is None else as_of_ts.tz_convert("UTC")
    start = pd.Timestamp(cfg["prospective_start_utc"])
    th, g = cfg["thresholds"], cfg["gates"]
    paper_r, human_r, blend_r = reports.get("paper") or {}, reports.get("human") or {}, reports.get("blend") or {}
    g1 = implementation_gate(_series((paper_r.get("daily_returns") or {}).get("paper")),
                             _series((human_r.get("daily_returns") or {}).get("V_ALL")), paper_r.get("coins_with_data"),
                             start=start, as_of=as_of_ts, th=th["G1_implementation"],
                             checkpoints=[int(n) for n in g["G1_implementation"]["checkpoints_days"]])
    g2 = breakage_alarm(_series((blend_r.get("daily_returns") or {}).get("S4_blend")), start=start,
                        th=th["G2_breakage_alarm"], window=int(g["G2_breakage_alarm"]["window_days"]))
    g3 = {"status": venue.get("verdict", "PENDING"), "venues": {k: {"passes": v.get("passes"), "coins": v.get("coins"),
                                                                    "sharpe": v["venue"]["S4"]["sharpe"], "t": v["venue"]["S4"]["t"],
                                                                    "mexc_sharpe": v["mexc_reference"]["S4"]["sharpe"]}
                                                                for k, v in (venue.get("venues") or {}).items()}} if venue else {"status": "PENDING"}
    started = as_of_ts >= start
    rows = [{"audit_id": "G1_implementation", "status": g1["status"], "days": g1["days"], "cum_diff": g1["cum_diff"]},
            {"audit_id": "G2_breakage_alarm", "status": g2["status"], "days": g2["days"], "max_drawdown": g2.get("max_drawdown"),
             "alarm_at": th["G2_breakage_alarm"]["max_drawdown_alarm"]},
            {"audit_id": "G3_venue_replication", "status": g3["status"]}]
    return {"schema_version": 1, "watch_id": WATCH_ID, "status": "COLLECTING" if started else "PRE_START",
            "as_of_utc": as_of_ts.isoformat(), "prospective_start_utc": start.isoformat(),
            "calendar_days_elapsed": max(0, (as_of_ts - start).days) if started else 0,
            "gates": {"G1_implementation": g1, "G2_breakage_alarm": g2, "G3_venue_replication": g3},
            "strategies": [{k: v for k, v in r.items() if v is not None} for r in rows],
            "claims": dict(cfg["claims"])}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Evaluate fast-gates-v1 from the blend workflow's reports. Descriptive only.")
    p.add_argument("--config", default="config/fast_gates_v1.json")
    p.add_argument("--dir", default="artifacts/multi_premia_blend")
    p.add_argument("--venue", default="research/fast_gates/venue_replication.json")
    p.add_argument("--output", required=True)
    a = p.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))

    def read(path: Path):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    d = Path(a.dir)
    reports = {"blend": read(d / "report.json"), "human": read(d / "human_report.json"), "paper": read(d / "paper_account_report.json")}
    report = build_report(cfg, reports, read(Path(a.venue)), as_of=pd.Timestamp.now(tz="UTC"))
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({r["audit_id"]: r["status"] for r in report["strategies"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
