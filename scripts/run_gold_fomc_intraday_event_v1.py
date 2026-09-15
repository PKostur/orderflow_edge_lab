from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


def clean(v):
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def pf(values) -> float:
    x = np.asarray(values, dtype=float)
    pos = float(x[x > 0].sum())
    neg = float(-x[x < 0].sum())
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return pos / neg


def risk_adjusted(values) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return float("nan")
    sd = float(np.std(x, ddof=1))
    return float(np.mean(x) / sd) if sd > 0 else float("nan")


def rho(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 5:
        return float("nan")
    return float(a[m].rank(method="average").corr(b[m].rank(method="average")))


def stable_seed(base_seed: int, text: str) -> int:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return int((base_seed + int.from_bytes(h[:4], "big")) % (2**32 - 1))


def permutation_pvalue(predictor, target, epochs: int, seed: int) -> float:
    predictor = np.asarray(predictor, dtype=float)
    target = np.asarray(target, dtype=float)
    observed = rho(predictor, target)
    if not np.isfinite(observed) or observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    count = 0
    for _ in range(epochs):
        r = rho(predictor, rng.permutation(target))
        if np.isfinite(r) and r >= observed:
            count += 1
    return float((count + 1) / (epochs + 1))


def bh_qvalues(pvals):
    p = np.asarray(pvals, dtype=float)
    q = np.full(len(p), np.nan, dtype=float)
    valid = np.where(np.isfinite(p))[0]
    if len(valid) == 0:
        return q.tolist()
    order = valid[np.argsort(p[valid])]
    m = len(order)
    raw = np.empty(m, dtype=float)
    for rank, idx in enumerate(order, 1):
        raw[rank - 1] = p[idx] * m / rank
    adj = np.minimum.accumulate(raw[::-1])[::-1]
    adj = np.minimum(adj, 1.0)
    for j, idx in enumerate(order):
        q[idx] = adj[j]
    return q.tolist()


def load_m15(path: Path, min_tick_volume: int) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    required = ["time", "open", "high", "low", "close", "tick_volume"]
    missing = [c for c in required if c not in d.columns]
    if missing:
        raise ValueError(f"missing M15 columns: {missing}")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    for c in required[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=required)
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d["tick_volume"] >= min_tick_volume]
    d = d.drop_duplicates("time", keep="last").set_index("time").sort_index()
    return d[["open", "high", "low", "close", "tick_volume"]]


def load_calendar(path: Path) -> pd.DataFrame:
    c = pd.read_csv(path, dtype=str)
    required = ["decision_date", "release_time_local", "timezone", "period", "source_url"]
    missing = [x for x in required if x not in c.columns]
    if missing:
        raise ValueError(f"calendar missing columns: {missing}")
    c["decision_date"] = pd.to_datetime(c["decision_date"], errors="raise").dt.date
    return c


def release_utc(row) -> pd.Timestamp:
    hh, mm = map(int, str(row["release_time_local"]).split(":"))
    local = pd.Timestamp(year=row["decision_date"].year, month=row["decision_date"].month, day=row["decision_date"].day, hour=hh, minute=mm, tz=ZoneInfo(str(row["timezone"])))
    return local.tz_convert("UTC")


def build_event_table(m15: pd.DataFrame, cal: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    pre_n = int(cfg["state_signal"]["minimum_pre_event_bars"])
    horizons = [int(x) for x in cfg["state_signal"]["forward_horizons_minutes_after_entry"]]
    rows = []
    log_cc = np.log(m15["close"]).diff()
    for _, erow in cal.iterrows():
        rel = release_utc(erow)
        entry = rel + pd.Timedelta(minutes=15)
        needed = [rel, entry] + [entry + pd.Timedelta(minutes=h) for h in horizons]
        if any(t not in m15.index for t in needed):
            rows.append({
                "decision_date": str(erow["decision_date"]), "period": erow["period"], "release_utc": str(rel),
                "complete": False, "missing_required_bar": True,
            })
            continue
        rel_pos = int(m15.index.get_loc(rel))
        if rel_pos < pre_n + 1:
            rows.append({"decision_date": str(erow["decision_date"]), "period": erow["period"], "release_utc": str(rel), "complete": False, "missing_required_bar": False, "insufficient_pre_event_bars": True})
            continue
        pre = log_cc.iloc[rel_pos - pre_n:rel_pos].dropna()
        if len(pre) < pre_n:
            rows.append({"decision_date": str(erow["decision_date"]), "period": erow["period"], "release_utc": str(rel), "complete": False, "missing_required_bar": False, "insufficient_pre_event_bars": True})
            continue
        pre_sd = float(pre.std(ddof=1))
        if not np.isfinite(pre_sd) or pre_sd <= 0:
            continue
        rb = m15.loc[rel]
        impulse = float(math.log(float(rb["close"]) / float(rb["open"])))
        normalized = impulse / pre_sd
        out = {
            "decision_date": str(erow["decision_date"]),
            "year": int(erow["decision_date"].year),
            "period": str(erow["period"]),
            "release_utc": str(rel),
            "entry_utc": str(entry),
            "release_impulse": impulse,
            "pre_event_volatility": pre_sd,
            "normalized_impulse": normalized,
            "complete": True,
        }
        entry_open = float(m15.loc[entry, "open"])
        for h in horizons:
            exit_t = entry + pd.Timedelta(minutes=h)
            exit_open = float(m15.loc[exit_t, "open"])
            out[f"ret_{h}m"] = exit_open / entry_open - 1.0
            out[f"exit_{h}m_utc"] = str(exit_t)
        rows.append(out)
    return pd.DataFrame(rows)


def hypothesis_id(mode: str, threshold: float, horizon: int) -> str:
    return f"{mode}__impulse{str(threshold).replace('.', 'p')}__h{horizon}m"


def year_state_breadth(g: pd.DataFrame, predictor_col: str, target_col: str) -> tuple[float, dict]:
    stats = {}
    signs = []
    for year, y in g.groupby("year"):
        aligned = np.sign(y[predictor_col].to_numpy(float)) * y[target_col].to_numpy(float)
        val = float(np.mean(aligned)) if len(aligned) else float("nan")
        stats[str(int(year))] = {"events": int(len(y)), "mean_direction_aligned_return": val}
        if np.isfinite(val):
            signs.append(val > 0)
    return (float(np.mean(signs)) if signs else 0.0), stats


def summarize_economics(g: pd.DataFrame, predictor_col: str, target_col: str, cfg: dict) -> dict:
    tr = g.copy()
    tr["side"] = np.sign(tr[predictor_col]).astype(int)
    tr = tr[tr["side"] != 0].copy()
    tr["gross_bps"] = tr["side"] * tr[target_col] * 10000.0
    tr["equal_timing_long_gold_gross_bps"] = tr[target_col] * 10000.0
    out = {"trades": int(len(tr))}
    costs = [float(x) for x in cfg["execution"]["round_trip_cost_bps"]]
    primary = float(cfg["execution"]["primary_cost_bps"])
    for cost in costs:
        key = f"{cost:g}"
        col = f"net_{key}"
        tr[col] = tr["gross_bps"] - cost
        out[f"mean_net_{key}_bps"] = float(tr[col].mean()) if len(tr) else np.nan
        out[f"profit_factor_{key}"] = pf(tr[col]) if len(tr) else np.nan
        year_means = tr.groupby("year")[col].mean() if len(tr) else pd.Series(dtype=float)
        out[f"positive_calendar_year_fraction_{key}"] = float((year_means > 0).mean()) if len(year_means) else 0.0
        out[f"year_mean_net_{key}_bps"] = {str(int(y)): float(v) for y, v in year_means.items()}
    pkey = f"{primary:g}"
    pcol = f"net_{pkey}"
    tr["equal_timing_long_gold_net_primary"] = tr["equal_timing_long_gold_gross_bps"] - primary
    out["reversed_mean_net_primary_bps"] = float((-tr["gross_bps"] - primary).mean()) if len(tr) else np.nan
    out["strategy_risk_adjusted_primary"] = risk_adjusted(tr[pcol]) if len(tr) else np.nan
    out["equal_timing_long_gold_risk_adjusted_primary"] = risk_adjusted(tr["equal_timing_long_gold_net_primary"]) if len(tr) else np.nan
    long = tr[tr["side"] > 0]
    short = tr[tr["side"] < 0]
    out["long"] = {"trades": int(len(long)), "mean_net_bps": float(long[pcol].mean()) if len(long) else np.nan}
    out["short"] = {"trades": int(len(short)), "mean_net_bps": float(short[pcol].mean()) if len(short) else np.nan}
    pos_imp = tr[tr["normalized_impulse"] > 0]
    neg_imp = tr[tr["normalized_impulse"] < 0]
    out["positive_release_impulse"] = {"trades": int(len(pos_imp)), "mean_net_bps": float(pos_imp[pcol].mean()) if len(pos_imp) else np.nan}
    out["negative_release_impulse"] = {"trades": int(len(neg_imp)), "mean_net_bps": float(neg_imp[pcol].mean()) if len(neg_imp) else np.nan}
    out["trade_rows"] = tr[["decision_date", "year", "normalized_impulse", predictor_col, target_col, "side", "gross_bps", pcol]].to_dict(orient="records")
    return out


def evaluate_hypothesis(events: pd.DataFrame, cfg: dict, mode: str, threshold: float, horizon: int) -> dict:
    hid = hypothesis_id(mode, threshold, horizon)
    g = events[(events["period"] == "development") & (events["complete"] == True)].copy()
    g = g[np.abs(g["normalized_impulse"]) >= threshold].copy()
    predictor_col = "predictor"
    target_col = f"ret_{horizon}m"
    g[predictor_col] = g["normalized_impulse"] if mode == "continuation" else -g["normalized_impulse"]
    obs_rho = rho(g[predictor_col], g[target_col]) if len(g) else np.nan
    p = permutation_pvalue(
        g[predictor_col].to_numpy(float), g[target_col].to_numpy(float),
        int(cfg["state_first"]["permutation_epochs"]), stable_seed(int(cfg["state_first"]["permutation_seed"]), hid)
    ) if len(g) >= 5 else 1.0
    year_frac, year_state = year_state_breadth(g, predictor_col, target_col)
    econ = summarize_economics(g, predictor_col, target_col, cfg)
    out = {
        "hypothesis_id": hid, "mode": mode, "threshold": float(threshold), "horizon_minutes": int(horizon),
        "state_events": int(len(g)), "calendar_years_represented": int(g["year"].nunique()) if len(g) else 0,
        "state_spearman": obs_rho, "state_permutation_p": p,
        "state_positive_calendar_year_fraction": year_frac, "state_year_diagnostics": year_state,
    }
    out.update(econ)
    return out


def apply_gates(cells, cfg):
    qvals = bh_qvalues([c["state_permutation_p"] for c in cells])
    s = cfg["state_first"]
    e = cfg["economic_gate"]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['execution']['high_cost_bps']):g}"
    for c, q in zip(cells, qvals):
        c["state_bh_q"] = q
        c["state_pass"] = bool(
            c["state_events"] >= int(s["minimum_events"])
            and c["calendar_years_represented"] >= int(s["minimum_calendar_years_represented"])
            and c.get("state_spearman", -np.inf) > float(s["minimum_median_spearman"])
            and c["state_positive_calendar_year_fraction"] >= float(s["minimum_positive_calendar_year_fraction"])
            and q <= float(s["maximum_bh_fdr_q"])
        )
        c["economic_pass"] = bool(
            c["state_pass"]
            and c["trades"] >= int(e["minimum_trades"])
            and c["positive_release_impulse"]["trades"] >= int(e["minimum_positive_impulse_side_trades"])
            and c["negative_release_impulse"]["trades"] >= int(e["minimum_negative_impulse_side_trades"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > float(e["minimum_primary_mean_net_bps"])
            and c.get(f"profit_factor_{pkey}", 0.0) >= float(e["minimum_primary_profit_factor"])
            and c.get(f"positive_calendar_year_fraction_{pkey}", 0.0) >= float(e["minimum_positive_calendar_year_fraction"])
            and c.get(f"mean_net_{hkey}_bps", -np.inf) >= float(e["minimum_high_cost_mean_net_bps"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > c.get("reversed_mean_net_primary_bps", np.inf)
            and np.isfinite(c.get("strategy_risk_adjusted_primary", np.nan))
            and np.isfinite(c.get("equal_timing_long_gold_risk_adjusted_primary", np.nan))
            and c["strategy_risk_adjusted_primary"] > c["equal_timing_long_gold_risk_adjusted_primary"]
            and c["long"]["trades"] >= int(e["minimum_positive_impulse_side_trades"])
            and c["short"]["trades"] >= int(e["minimum_negative_impulse_side_trades"])
            and c["long"]["mean_net_bps"] > 0
            and c["short"]["mean_net_bps"] > 0
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--calendar", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    cal = load_calendar(Path(args.calendar))
    expected_dev = int(cfg["event_universe"]["development_regular_decisions_expected"])
    expected_val = int(cfg["event_universe"]["validation_regular_decisions_expected"])
    if int((cal["period"] == "development").sum()) != expected_dev:
        raise SystemExit("development calendar count mismatch")
    if int((cal["period"] == "locked_internal_validation").sum()) != expected_val:
        raise SystemExit("validation calendar count mismatch")

    m15 = load_m15(Path(args.gold), int(cfg["data_admission"]["minimum_tick_volume_per_required_bar"]))
    events = build_event_table(m15, cal, cfg)
    dev_complete = events[(events["period"] == "development") & (events["complete"] == True)]
    if len(dev_complete) < int(cfg["data_admission"]["minimum_development_events_with_complete_bars"]):
        raise SystemExit(f"insufficient complete development events: {len(dev_complete)}")

    cells = []
    for mode in cfg["state_signal"]["modes"]:
        for threshold in cfg["state_signal"]["absolute_thresholds"]:
            for horizon in cfg["state_signal"]["forward_horizons_minutes_after_entry"]:
                cells.append(evaluate_hypothesis(events, cfg, str(mode), float(threshold), int(horizon)))
    apply_gates(cells, cfg)
    passed = [c for c in cells if c["economic_pass"]]
    passed.sort(key=lambda c: (float(c.get("state_bh_q", 1.0)), -float(c.get("state_spearman", -np.inf)), -float(c.get("mean_net_5_bps", -np.inf)), c["hypothesis_id"]))
    selected = passed[: int(cfg["candidate_selection"]["maximum_candidates"])]

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "calendar_integrity": {
            "development_rows": expected_dev,
            "locked_validation_rows": expected_val,
            "complete_development_events": int(len(dev_complete)),
            "complete_locked_validation_events_not_scored": int(len(events[(events["period"] == "locked_internal_validation") & (events["complete"] == True)])),
        },
        "data_integrity": {
            "m15_rows": int(len(m15)), "first_bar": str(m15.index.min()), "last_bar": str(m15.index.max()),
        },
        "grid": {
            "hypotheses": int(len(cells)), "state_passes": int(sum(bool(c["state_pass"]) for c in cells)),
            "economic_passes": int(sum(bool(c["economic_pass"]) for c in cells)),
        },
        "selected_candidates_for_separate_freeze": [c["hypothesis_id"] for c in selected],
        "cells": cells,
        "event_integrity_rows": events[[c for c in ["decision_date", "year", "period", "release_utc", "entry_utc", "complete", "missing_required_bar", "insufficient_pre_event_bars"] if c in events.columns]].to_dict(orient="records"),
        "locked_internal_validation_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean({
        "complete_development_events": payload["calendar_integrity"]["complete_development_events"],
        "hypotheses": payload["grid"]["hypotheses"],
        "state_passes": payload["grid"]["state_passes"],
        "economic_passes": payload["grid"]["economic_passes"],
        "selected": payload["selected_candidates_for_separate_freeze"],
        "validation_opened": False,
    }), indent=2))


if __name__ == "__main__":
    main()
