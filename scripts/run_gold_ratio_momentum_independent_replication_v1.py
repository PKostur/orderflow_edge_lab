from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

COSTS = (2.0, 5.0, 10.0)
PRIMARY_COST = 5.0
Z_WINDOW = 126
Z_THRESHOLD = 1.0
HOLD = 21
CLUSTER_DAYS = 126


def clean(v):
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    return v


def pf(values) -> float:
    a = np.asarray(values, float)
    pos = a[a > 0].sum()
    neg = -a[a < 0].sum()
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return float(pos / neg)


def rho(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5:
        return float("nan")
    return float(a[m].rank(method="average").corr(b[m].rank(method="average")))


def load_cash(path: Path, prefix: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    if "time" not in d.columns:
        raise ValueError(f"{path}: missing time column")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce").dt.floor("D")
    for c in ("open", "high", "low", "close", "tick_volume"):
        if c not in d.columns:
            raise ValueError(f"{path}: missing {c}")
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["time", "open", "high", "low", "close", "tick_volume"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d["tick_volume"] > 1]
    d = d[d["time"].dt.weekday <= 4]
    d = d.drop_duplicates("time", keep="last").set_index("time").sort_index()
    return d[["open", "high", "low", "close", "tick_volume"]].add_prefix(prefix + "_")


def risk_adjusted_by_fold(frame: pd.DataFrame, value_col: str) -> float:
    vals = []
    for _, g in frame.groupby("fold"):
        x = g[value_col].to_numpy(float)
        if len(x) < 2:
            continue
        sd = float(np.std(x, ddof=1))
        if not np.isfinite(sd) or sd <= 0:
            continue
        vals.append(float(np.mean(x) / sd))
    return float(np.median(vals)) if vals else float("nan")


def directional_stats(tr: pd.DataFrame, net_col: str, side: int) -> dict:
    g = tr[tr["side"] == side]
    if g.empty:
        return {"trades": 0, "mean_net_bps": np.nan, "median_net_bps": np.nan, "win_rate": np.nan}
    x = g[net_col].to_numpy(float)
    return {
        "trades": int(len(g)),
        "mean_net_bps": float(np.mean(x)),
        "median_net_bps": float(np.median(x)),
        "win_rate": float(np.mean(x > 0)),
    }


def evaluate_period(common: pd.DataFrame, start: str, end: str) -> dict:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    d = common.loc[(common.index >= start_ts) & (common.index < end_ts)].copy()
    if len(d) < Z_WINDOW + HOLD + 5:
        return {"start": start, "end_exclusive": end, "rows": int(len(d)), "error": "insufficient rows"}

    ratio = d["gold_close"] / d["silver_close"]
    mu = ratio.rolling(Z_WINDOW, min_periods=Z_WINDOW).mean()
    sd = ratio.rolling(Z_WINDOW, min_periods=Z_WINDOW).std(ddof=0).replace(0, np.nan)
    z = (ratio - mu) / sd
    side = np.sign(z).astype(float)
    active = z.abs() >= Z_THRESHOLD

    entry = d["gold_open"].shift(-1)
    exit_ = d["gold_open"].shift(-(1 + HOLD))
    fwd_bps = (exit_ / entry - 1.0) * 10000.0
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=CLUSTER_DAYS)).astype(int)

    pos = np.arange(len(d))
    exit_pos = pos + 1 + HOLD
    valid = active.to_numpy(bool) & np.isfinite(z.to_numpy(float)) & np.isfinite(fwd_bps.to_numpy(float))
    valid &= exit_pos < len(d)
    safe_exit = np.minimum(exit_pos, len(d) - 1)
    valid &= fold[safe_exit] == fold
    ids = np.where(valid)[0]

    state_rows = []
    for fid in np.unique(fold[ids]):
        ii = ids[fold[ids] == fid]
        if len(ii) < 5:
            continue
        r = rho(z.iloc[ii].to_numpy(float), fwd_bps.iloc[ii].to_numpy(float))
        if np.isfinite(r):
            state_rows.append((int(fid), float(r), int(len(ii))))

    chosen = []
    next_allowed = -1
    for i in ids:
        if i < next_allowed:
            continue
        chosen.append(int(i))
        next_allowed = int(i + 1 + HOLD)

    rows = []
    for i in chosen:
        raw = float(fwd_bps.iloc[i])
        s = int(np.sign(z.iloc[i]))
        rows.append({
            "timestamp": str(d.index[i]),
            "fold": int(fold[i]),
            "z": float(z.iloc[i]),
            "side": s,
            "gold_forward_bps": raw,
            "gross_bps": float(s * raw),
            "benchmark_gross_bps": raw,
        })
    tr = pd.DataFrame(rows)

    out = {
        "start": start,
        "end_exclusive": end,
        "rows": int(len(d)),
        "first_common_bar": str(d.index.min()),
        "last_common_bar": str(d.index.max()),
        "state_events": int(len(ids)),
        "state_folds": int(len(state_rows)),
        "state_fold_rhos": [{"fold": f, "rho": r, "events": n} for f, r, n in state_rows],
        "state_median_spearman": float(np.median([x[1] for x in state_rows])) if state_rows else np.nan,
        "state_positive_fold_fraction": float(np.mean([x[1] > 0 for x in state_rows])) if state_rows else 0.0,
        "trades": int(len(tr)),
    }
    if tr.empty:
        return out

    for cost in COSTS:
        net_col = f"net_{cost:g}"
        bench_col = f"benchmark_net_{cost:g}"
        tr[net_col] = tr["gross_bps"] - cost
        tr[bench_col] = tr["benchmark_gross_bps"] - cost
        fold_exp = tr.groupby("fold")[net_col].mean()
        fold_pf = tr.groupby("fold")[net_col].apply(pf)
        out[f"net_{cost:g}_median_fold_bps"] = float(fold_exp.median())
        out[f"pf_{cost:g}_median_fold"] = float(fold_pf.median())
        out[f"positive_fold_fraction_{cost:g}"] = float((fold_exp > 0).mean())
        out[f"mean_net_{cost:g}_bps"] = float(tr[net_col].mean())
        out[f"benchmark_mean_net_{cost:g}_bps"] = float(tr[bench_col].mean())

    out["reversed_mean_net_5_bps"] = float((-tr["gross_bps"] - PRIMARY_COST).mean())
    out["strategy_median_fold_risk_adjusted_5"] = risk_adjusted_by_fold(tr, "net_5")
    out["benchmark_median_fold_risk_adjusted_5"] = risk_adjusted_by_fold(tr, "benchmark_net_5")
    out["long"] = directional_stats(tr, "net_5", 1)
    out["short"] = directional_stats(tr, "net_5", -1)
    out["trade_rows"] = rows
    return out


def source_gate(r: dict, cfg: dict) -> bool:
    g = cfg["primary_source_robustness_gate"]
    return bool(
        r.get("state_folds", 0) >= g["minimum_state_folds"]
        and r.get("state_median_spearman") is not None and r["state_median_spearman"] > 0
        and r.get("state_positive_fold_fraction", 0) >= g["positive_state_fold_fraction_gte"]
        and r.get("trades", 0) >= g["minimum_trades"]
        and r.get("net_5_median_fold_bps") is not None and r["net_5_median_fold_bps"] > 0
        and r.get("pf_5_median_fold") is not None and r["pf_5_median_fold"] > 1
        and r.get("positive_fold_fraction_5", 0) >= g["primary_positive_economic_fold_fraction_gte"]
        and r.get("net_10_median_fold_bps") is not None and r["net_10_median_fold_bps"] >= 0
        and r.get("mean_net_5_bps") is not None and r.get("reversed_mean_net_5_bps") is not None
        and r["mean_net_5_bps"] > r["reversed_mean_net_5_bps"]
        and r.get("strategy_median_fold_risk_adjusted_5") is not None
        and r.get("benchmark_median_fold_risk_adjusted_5") is not None
        and r["strategy_median_fold_risk_adjusted_5"] > r["benchmark_median_fold_risk_adjusted_5"]
        and r.get("long", {}).get("trades", 0) >= g["minimum_long_trades"]
        and r.get("short", {}).get("trades", 0) >= g["minimum_short_trades"]
        and r.get("long", {}).get("mean_net_bps") is not None and r["long"]["mean_net_bps"] > 0
        and r.get("short", {}).get("mean_net_bps") is not None and r["short"]["mean_net_bps"] > 0
    )


def extension_gate(r: dict, cfg: dict) -> bool:
    g = cfg["extension_consistency_gate"]
    return bool(
        r.get("trades", 0) >= g["minimum_trades"]
        and r.get("mean_net_5_bps") is not None and r["mean_net_5_bps"] > 0
        and r.get("mean_net_10_bps") is not None and r["mean_net_10_bps"] >= 0
        and r.get("reversed_mean_net_5_bps") is not None
        and r["mean_net_5_bps"] > r["reversed_mean_net_5_bps"]
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--silver", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    gold = load_cash(Path(args.gold), "gold")
    silver = load_cash(Path(args.silver), "silver")
    common = gold.join(silver, how="inner").dropna().sort_index()
    common = common[(common.index >= pd.Timestamp("2010-01-01", tz="UTC")) & (common.index < pd.Timestamp("2026-09-15", tz="UTC"))]

    p1 = cfg["periods"]["source_robustness"]
    p2 = cfg["periods"]["historical_extension"]
    source = evaluate_period(common, p1["start"], p1["end_exclusive"])
    extension = evaluate_period(common, p2["start"], p2["end_exclusive"])
    source["gate_pass"] = source_gate(source, cfg)
    extension["gate_pass"] = extension_gate(extension, cfg)
    final_pass = bool(source["gate_pass"] and extension["gate_pass"])

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "external_source": cfg["external_source"],
        "data_integrity": {
            "gold_rows_admitted": int(len(gold)),
            "silver_rows_admitted": int(len(silver)),
            "common_rows": int(len(common)),
            "common_start": str(common.index.min()) if len(common) else None,
            "common_end": str(common.index.max()) if len(common) else None,
        },
        "candidate": cfg["candidate"],
        "source_robustness": source,
        "historical_extension": extension,
        "independent_source_replication_pass": final_pass,
        "future_shadow_authorized": final_pass,
        "future_shadow_start_not_before": cfg["promotion_boundary"]["future_shadow_start_not_before"] if final_pass else None,
        "leverage_tested": False,
        "claims": {
            "verified_oos": False,
            "profitable_edge_established": False,
            "live_enabled": False,
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean({
        "source_gate": source["gate_pass"],
        "extension_gate": extension["gate_pass"],
        "replication_pass": final_pass,
        "source": {k: source.get(k) for k in ["state_median_spearman", "trades", "net_5_median_fold_bps", "pf_5_median_fold", "positive_fold_fraction_5", "mean_net_5_bps", "reversed_mean_net_5_bps", "long", "short"]},
        "extension": {k: extension.get(k) for k in ["state_median_spearman", "trades", "net_5_median_fold_bps", "mean_net_5_bps", "reversed_mean_net_5_bps", "long", "short"]},
    }), indent=2))


if __name__ == "__main__":
    main()
