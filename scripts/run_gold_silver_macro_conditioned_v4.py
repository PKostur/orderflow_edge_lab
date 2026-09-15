from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

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
    x = np.asarray(values, float)
    pos = float(x[x > 0].sum())
    neg = float(-x[x < 0].sum())
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return pos / neg


def rho(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 5:
        return float("nan")
    return float(a[m].rank(method="average").corr(b[m].rank(method="average")))


def load_cash(path: Path, prefix: str, min_tick: int) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    need = ["time", "open", "high", "low", "close", "tick_volume"]
    if any(c not in d.columns for c in need):
        raise ValueError(f"{path}: missing expected columns")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce").dt.floor("D")
    for c in need[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=need)
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d["tick_volume"] >= min_tick]
    d = d[d["time"].dt.weekday <= 4]
    d = d.drop_duplicates("time", keep="last").set_index("time").sort_index()
    return d[["open", "high", "low", "close", "tick_volume"]].add_prefix(prefix + "_")


def load_macro(path: Path, series: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    if d.shape[1] < 2:
        raise ValueError(f"{path}: malformed macro file")
    date_col = d.columns[0]
    value_col = series if series in d.columns else d.columns[1]
    out = pd.DataFrame({
        "macro_time": pd.to_datetime(d[date_col], utc=True, errors="coerce").dt.floor("D"),
        series: pd.to_numeric(d[value_col].replace(".", pd.NA), errors="coerce"),
    }).dropna().sort_values("macro_time")
    return out.drop_duplicates("macro_time", keep="last")


def attach_strictly_lagged_macro(index: pd.DatetimeIndex, macro: pd.DataFrame, series: str) -> pd.Series:
    left = pd.DataFrame({"time": index}).sort_values("time")
    m = pd.merge_asof(
        left,
        macro.sort_values("macro_time"),
        left_on="time",
        right_on="macro_time",
        direction="backward",
        allow_exact_matches=False,
    )
    return pd.Series(m[series].to_numpy(float), index=index, name=series)


def prior_zscore(raw: pd.Series, window: int) -> pd.Series:
    hist = raw.shift(1)
    mu = hist.rolling(window, min_periods=window).mean()
    sd = hist.rolling(window, min_periods=window).std(ddof=0)
    return (raw - mu) / sd.replace(0.0, np.nan)


def macro_scores(d: pd.DataFrame, macro_inputs: dict[str, pd.DataFrame], cfg: dict) -> pd.DataFrame:
    idx = d.index
    ry = attach_strictly_lagged_macro(idx, macro_inputs["DFII10"], "DFII10")
    ny = attach_strictly_lagged_macro(idx, macro_inputs["DGS10"], "DGS10")
    usd = attach_strictly_lagged_macro(idx, macro_inputs["DTWEXBGS"], "DTWEXBGS")
    h = int(cfg["macro_features"]["raw_change_horizon_trading_days"])
    w = int(cfg["macro_features"]["standardization_window_trading_days"])
    raw_real = ry - ry.shift(h)
    raw_usd = np.log(usd / usd.shift(h))
    breakeven = ny - ry
    raw_be = breakeven - breakeven.shift(h)
    s_real = -prior_zscore(raw_real, w)
    s_usd = -prior_zscore(raw_usd, w)
    s_be = prior_zscore(raw_be, w)
    scores = pd.DataFrame(index=idx)
    scores["falling_real_yield_support"] = s_real
    scores["weaker_usd_support"] = s_usd
    scores["rising_breakeven_support"] = s_be
    scores["equal_weight_macro_support"] = pd.concat([s_real, s_usd, s_be], axis=1).mean(axis=1, skipna=False)
    return scores


def adaptive_states(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    m = cfg["pair_event_model"]
    warm = int(m["initial_warmup_trading_days"])
    lam = float(m["forgetting_factor"])
    y = np.log(d["gold_close"].to_numpy(float))
    x = np.log(d["silver_close"].to_numpy(float))
    out = pd.DataFrame(index=d.index, columns=["alpha", "beta", "innovation", "innovation_sd", "z"], dtype=float)
    X0 = np.column_stack([np.ones(warm), x[:warm]])
    theta, *_ = np.linalg.lstsq(X0, y[:warm], rcond=None)
    resid = y[:warm] - X0 @ theta
    var = float(np.var(resid, ddof=0))
    gram = (X0.T @ X0) / warm
    P = np.linalg.inv(gram + 1e-8 * np.eye(2))
    for i in range(warm, len(d)):
        xt = np.array([1.0, x[i]])
        pred = float(xt @ theta)
        innov = float(y[i] - pred)
        sd = float(math.sqrt(max(var, 1e-12)))
        out.iloc[i] = [float(theta[0]), float(theta[1]), innov, sd, innov / sd]
        Px = P @ xt
        denom = float(lam + xt @ Px)
        K = Px / denom
        theta = theta + K * innov
        P = (P - np.outer(K, xt) @ P) / lam
        P = 0.5 * (P + P.T)
        var = float(lam * var + (1.0 - lam) * innov * innov)
    return out


def admitted_pair_state(s: pd.Series, cfg: dict) -> bool:
    m = cfg["pair_event_model"]
    vals = [s.get("alpha"), s.get("beta"), s.get("innovation"), s.get("innovation_sd"), s.get("z")]
    if not all(np.isfinite(float(v)) for v in vals):
        return False
    return bool(float(s["beta"]) > float(m["beta_gt"]) and float(s["beta"]) < float(m["beta_lt"]))


def stable_seed(base: int, text: str) -> int:
    return int((base + int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")) % (2**32 - 1))


def sign_flip_pvalue(rhos: list[float], epochs: int, seed: int) -> float:
    r = np.asarray(rhos, float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return float("nan")
    obs = float(np.median(r))
    if obs <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    abs_r = np.abs(r)
    count = 0
    done = 0
    while done < epochs:
        n = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(abs_r)))
        count += int(np.sum(np.median(signs * abs_r[None, :], axis=1) >= obs))
        done += n
    return float((count + 1) / (epochs + 1))


def bh_qvalues(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, float)
    q = np.full(len(p), np.nan)
    valid = np.where(np.isfinite(p))[0]
    if len(valid) == 0:
        return q.tolist()
    order = valid[np.argsort(p[valid])]
    m = len(order)
    raw = np.array([p[idx] * m / rank for rank, idx in enumerate(order, 1)])
    adj = np.minimum.accumulate(raw[::-1])[::-1]
    for j, idx in enumerate(order):
        q[idx] = min(float(adj[j]), 1.0)
    return q.tolist()


def fold_risk_adjusted(frame: pd.DataFrame, col: str) -> float:
    vals = []
    for _, g in frame.groupby("fold"):
        x = g[col].to_numpy(float)
        if len(x) < 2:
            continue
        sd = float(np.std(x, ddof=1))
        if sd > 0 and np.isfinite(sd):
            vals.append(float(np.mean(x) / sd))
    return float(np.median(vals)) if vals else float("nan")


def side_stats(tr: pd.DataFrame, col: str, side: int) -> dict:
    g = tr[tr["side"] == side]
    if g.empty:
        return {"trades": 0, "mean_net_bps": np.nan, "median_net_bps": np.nan, "win_rate": np.nan}
    x = g[col].to_numpy(float)
    return {"trades": int(len(g)), "mean_net_bps": float(np.mean(x)), "median_net_bps": float(np.median(x)), "win_rate": float(np.mean(x > 0))}


def pair_return(d: pd.DataFrame, i: int, j: int, beta: float, use_open: bool = False) -> tuple[float, float, float]:
    prefix = "open" if use_open else "close"
    g0 = float(d[f"gold_{prefix}"].iloc[i]); g1 = float(d[f"gold_{prefix}"].iloc[j])
    s0 = float(d[f"silver_{prefix}"].iloc[i]); s1 = float(d[f"silver_{prefix}"].iloc[j])
    gr = g1 / g0 - 1.0; sr = s1 / s0 - 1.0
    b = abs(beta); wg = 1.0 / (1.0 + b); ws = b / (1.0 + b)
    return float(wg * gr - ws * sr), float(gr), float(0.5 * gr - 0.5 * sr)


def build_state_results(d: pd.DataFrame, states: pd.DataFrame, scores: pd.DataFrame, start_ts: pd.Timestamp, cfg: dict) -> list[dict]:
    sf = cfg["state_first"]
    h = int(sf["horizon_trading_bars"])
    cluster_days = int(sf["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    entry_z = float(cfg["pair_event_model"]["entry_abs_innovation_z_gte"])
    out = []
    for feature in cfg["macro_features"]["features"].keys():
        rows = []
        for i in range(len(d) - h):
            s = states.iloc[i]
            score = scores[feature].iloc[i]
            if not admitted_pair_state(s, cfg) or abs(float(s["z"])) < entry_z or not np.isfinite(score):
                continue
            j = i + h
            if fold[j] != fold[i]:
                continue
            pr, _, _ = pair_return(d, i, j, float(s["beta"]), use_open=False)
            rows.append({"fold": int(fold[i]), "score": float(score), "target": pr})
        f = pd.DataFrame(rows)
        fold_rows = []
        if not f.empty:
            for fid, g in f.groupby("fold"):
                if len(g) < int(sf["minimum_events_per_fold"]):
                    continue
                r = rho(g["score"], g["target"])
                if np.isfinite(r):
                    fold_rows.append({"fold": int(fid), "rho": float(r), "events": int(len(g))})
        rhos = [x["rho"] for x in fold_rows]
        positive_frac = float((f["score"] > 0).mean()) if not f.empty else 0.0
        negative_frac = float((f["score"] < 0).mean()) if not f.empty else 0.0
        out.append({
            "feature": feature,
            "events": int(len(f)),
            "positive_score_event_fraction": positive_frac,
            "negative_score_event_fraction": negative_frac,
            "scorable_folds": int(len(fold_rows)),
            "fold_rhos": fold_rows,
            "median_fold_spearman": float(np.median(rhos)) if rhos else np.nan,
            "positive_fold_fraction": float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
            "sign_flip_p": sign_flip_pvalue(rhos, int(sf["sign_flip_epochs"]), stable_seed(int(sf["sign_flip_seed"]), feature)),
        })
    q = bh_qvalues([x["sign_flip_p"] for x in out])
    for x, qv in zip(out, q):
        x["bh_q"] = qv
        x["state_pass"] = bool(
            x["events"] >= int(sf["minimum_total_events"])
            and x["scorable_folds"] >= int(sf["minimum_scorable_folds"])
            and x["positive_score_event_fraction"] >= float(sf["minimum_positive_score_event_fraction"])
            and x["negative_score_event_fraction"] >= float(sf["minimum_negative_score_event_fraction"])
            and x["median_fold_spearman"] > float(sf["minimum_median_fold_spearman"])
            and x["positive_fold_fraction"] >= float(sf["minimum_positive_fold_fraction"])
            and x["bh_q"] <= float(sf["maximum_bh_fdr_q"])
        )
    return out


def simulate_macro_only(d: pd.DataFrame, states: pd.DataFrame, score: pd.Series, threshold: float, hold: int, start_ts: pd.Timestamp, cfg: dict) -> pd.DataFrame:
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    rows = []
    i = 0
    while i + hold + 1 < len(d):
        s = states.iloc[i]; sc = score.iloc[i]
        if not admitted_pair_state(s, cfg) or not np.isfinite(sc) or abs(float(sc)) < threshold or float(sc) == 0:
            i += 1; continue
        entry = i + 1; exitp = entry + hold
        if fold[exitp] != fold[i]:
            i += 1; continue
        side = 1 if sc > 0 else -1
        pr, _, _ = pair_return(d, entry, exitp, float(s["beta"]), use_open=True)
        rows.append({"fold": int(fold[i]), "gross_bps": float(side * pr * 10000.0)})
        i = exitp
    return pd.DataFrame(rows)


def simulate_cell(d: pd.DataFrame, states: pd.DataFrame, scores: pd.DataFrame, feature: str, threshold: float, hold: int, start_ts: pd.Timestamp, state_pass: bool, cfg: dict) -> dict:
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    event_z = float(cfg["pair_event_model"]["entry_abs_innovation_z_gte"])
    rows = []
    i = 0
    while i + hold + 1 < len(d):
        s = states.iloc[i]; sc = scores[feature].iloc[i]
        if not admitted_pair_state(s, cfg) or abs(float(s["z"])) < event_z or not np.isfinite(sc) or abs(float(sc)) < threshold or float(sc) == 0:
            i += 1; continue
        entry = i + 1; exitp = entry + hold
        if fold[exitp] != fold[i]:
            i += 1; continue
        side = 1 if sc > 0 else -1
        pair, gold, static = pair_return(d, entry, exitp, float(s["beta"]), use_open=True)
        mr_side = int(-np.sign(float(s["z"])))
        rows.append({
            "fold": int(fold[i]), "side": side, "score": float(sc), "entry_z": float(s["z"]), "entry_beta": float(s["beta"]),
            "gross_bps": float(side * pair * 10000.0),
            "reversed_macro_gross_bps": float(-side * pair * 10000.0),
            "mean_reversion_control_gross_bps": float(mr_side * pair * 10000.0),
            "static_pair_gross_bps": float(side * static * 10000.0),
            "unhedged_gold_gross_bps": float(side * gold * 10000.0),
        })
        i = exitp
    tr = pd.DataFrame(rows)
    cid = f"macro_{feature}__threshold{str(threshold).replace('.', 'p')}__hold{hold}"
    out = {"candidate_id": cid, "feature": feature, "macro_threshold": float(threshold), "hold": int(hold), "state_pass": bool(state_pass), "trades": int(len(tr))}
    if tr.empty:
        out["economic_pass_before_neighborhood"] = False
        return out
    costs = [float(x) for x in cfg["economic_translation"]["round_trip_cost_bps_on_total_gross_notional"]]
    primary = float(cfg["economic_translation"]["primary_cost_bps"])
    for cost in costs:
        key = f"{cost:g}"; col = f"net_{key}"
        tr[col] = tr["gross_bps"] - cost
        fold_net = tr.groupby("fold")[col].mean(); fold_pf = tr.groupby("fold")[col].apply(pf)
        out[f"net_{key}_median_fold_bps"] = float(fold_net.median())
        out[f"pf_{key}_median_fold"] = float(fold_pf.median())
        out[f"positive_fold_fraction_{key}"] = float((fold_net > 0).mean())
        out[f"mean_net_{key}_bps"] = float(tr[col].mean())
    pkey = f"{primary:g}"; pcol = f"net_{pkey}"
    for name in ["reversed_macro", "mean_reversion_control", "static_pair", "unhedged_gold"]:
        tr[f"{name}_net_primary"] = tr[f"{name}_gross_bps"] - primary
    macro_only = simulate_macro_only(d, states, scores[feature], threshold, hold, start_ts, cfg)
    if not macro_only.empty:
        macro_only["net_primary"] = macro_only["gross_bps"] - primary
        out["macro_only_trades"] = int(len(macro_only))
        out["macro_only_median_fold_risk_adjusted_primary"] = fold_risk_adjusted(macro_only, "net_primary")
        out["macro_only_mean_net_primary_bps"] = float(macro_only["net_primary"].mean())
    else:
        out["macro_only_trades"] = 0
        out["macro_only_median_fold_risk_adjusted_primary"] = np.nan
        out["macro_only_mean_net_primary_bps"] = np.nan
    out["reversed_macro_mean_net_primary_bps"] = float(tr["reversed_macro_net_primary"].mean())
    out["strategy_median_fold_risk_adjusted_primary"] = fold_risk_adjusted(tr, pcol)
    out["mean_reversion_control_median_fold_risk_adjusted_primary"] = fold_risk_adjusted(tr, "mean_reversion_control_net_primary")
    out["static_pair_median_fold_risk_adjusted_primary"] = fold_risk_adjusted(tr, "static_pair_net_primary")
    out["unhedged_gold_median_fold_risk_adjusted_primary"] = fold_risk_adjusted(tr, "unhedged_gold_net_primary")
    out["long_spread"] = side_stats(tr, pcol, 1)
    out["short_spread"] = side_stats(tr, pcol, -1)
    if len(tr) >= 3 and np.std(tr["gross_bps"]) > 0 and np.std(tr["unhedged_gold_gross_bps"]) > 0:
        out["trade_return_corr_with_unhedged_gold"] = float(np.corrcoef(tr["gross_bps"], tr["unhedged_gold_gross_bps"])[0, 1])
    else:
        out["trade_return_corr_with_unhedged_gold"] = np.nan
    e = cfg["economic_gate"]; hkey = f"{float(cfg['economic_translation']['high_cost_bps']):g}"
    out["economic_pass_before_neighborhood"] = bool(
        state_pass
        and len(tr) >= int(e["minimum_non_overlapping_trades"])
        and out.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(e["minimum_primary_median_fold_net_bps"])
        and out.get(f"pf_{pkey}_median_fold", 0.0) >= float(e["minimum_primary_median_fold_pf"])
        and out.get(f"positive_fold_fraction_{pkey}", 0.0) >= float(e["minimum_primary_positive_fold_fraction"])
        and out.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(e["minimum_high_cost_median_fold_net_bps"])
        and out.get(f"mean_net_{pkey}_bps", -np.inf) > float(e["minimum_overall_mean_primary_net_bps"])
        and out.get(f"mean_net_{pkey}_bps", -np.inf) > out.get("reversed_macro_mean_net_primary_bps", np.inf)
        and np.isfinite(out.get("strategy_median_fold_risk_adjusted_primary", np.nan))
        and out["strategy_median_fold_risk_adjusted_primary"] > out.get("mean_reversion_control_median_fold_risk_adjusted_primary", np.inf)
        and out["strategy_median_fold_risk_adjusted_primary"] > out.get("static_pair_median_fold_risk_adjusted_primary", np.inf)
        and out["strategy_median_fold_risk_adjusted_primary"] > out.get("macro_only_median_fold_risk_adjusted_primary", np.inf)
        and out["long_spread"]["trades"] >= int(e["minimum_long_spread_trades"])
        and out["short_spread"]["trades"] >= int(e["minimum_short_spread_trades"])
        and out["long_spread"]["mean_net_bps"] > 0
        and out["short_spread"]["mean_net_bps"] > 0
    )
    out["trade_rows"] = rows
    return out


def is_neighbor(a: dict, b: dict) -> bool:
    if a["feature"] != b["feature"]:
        return False
    diffs = int(a["macro_threshold"] != b["macro_threshold"]) + int(a["hold"] != b["hold"])
    return diffs == 1


def supporter(c: dict, cfg: dict) -> bool:
    req = cfg["neighborhood_gate"]["supporter_requires"]
    pkey = f"{float(cfg['economic_translation']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['economic_translation']['high_cost_bps']):g}"
    return bool(
        c.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(req["primary_median_fold_net_bps_gt"])
        and c.get(f"pf_{pkey}_median_fold", 0.0) > float(req["primary_median_fold_pf_gt"])
        and c.get(f"mean_net_{pkey}_bps", -np.inf) > float(req["overall_mean_primary_net_bps_gt"])
        and c.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(req["high_cost_median_fold_net_bps_gte"])
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    for arg in ["config", "gold", "silver", "dfii10", "dgs10", "dtwexbgs", "output"]:
        ap.add_argument(f"--{arg}", required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    min_tick = int(cfg["data_admission"]["minimum_tick_volume_each_price_leg"])
    gold = load_cash(Path(args.gold), "gold", min_tick); silver = load_cash(Path(args.silver), "silver", min_tick)
    common = gold.join(silver, how="inner").dropna().sort_index()
    dev = cfg["periods"]["development"]; start = pd.Timestamp(dev["start"], tz="UTC"); end = pd.Timestamp(dev["end_exclusive"], tz="UTC")
    d = common.loc[(common.index >= start) & (common.index < end)].copy()
    macro_inputs = {
        "DFII10": load_macro(Path(args.dfii10), "DFII10"),
        "DGS10": load_macro(Path(args.dgs10), "DGS10"),
        "DTWEXBGS": load_macro(Path(args.dtwexbgs), "DTWEXBGS"),
    }
    scores = macro_scores(d, macro_inputs, cfg)
    states = adaptive_states(d, cfg)
    state_results = build_state_results(d, states, scores, start, cfg)
    state_map = {x["feature"]: bool(x["state_pass"]) for x in state_results}
    cells = []
    for feature in cfg["macro_features"]["features"].keys():
        for threshold in cfg["economic_translation"]["minimum_abs_macro_score"]:
            for hold in cfg["economic_translation"]["hold_trading_bars"]:
                cells.append(simulate_cell(d, states, scores, feature, float(threshold), int(hold), start, state_map[feature], cfg))
    for c in cells:
        neigh = [x["candidate_id"] for x in cells if x is not c and is_neighbor(c, x) and supporter(x, cfg)]
        c["supporting_neighbors"] = sorted(neigh)
        c["neighborhood_support_count"] = len(neigh)
        c["full_development_pass"] = bool(c.get("economic_pass_before_neighborhood") and len(neigh) >= int(cfg["neighborhood_gate"]["minimum_supporting_neighbors"]))
    passed = [c for c in cells if c.get("full_development_pass")]
    pkey = f"{float(cfg['economic_translation']['primary_cost_bps']):g}"
    state_by_feature = {x["feature"]: x for x in state_results}
    passed.sort(key=lambda c: (-float(state_by_feature[c["feature"]].get("median_fold_spearman", -np.inf)), -float(c.get(f"positive_fold_fraction_{pkey}", -np.inf)), -float(c.get(f"net_{pkey}_median_fold_bps", -np.inf)), c["candidate_id"]))
    selected = passed[: int(cfg["candidate_selection"]["maximum_candidates"])]
    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "development_period": dev,
        "data_integrity": {
            "common_price_rows_all_source": int(len(common)),
            "development_rows": int(len(d)),
            "development_first_bar": str(d.index.min()),
            "development_last_bar": str(d.index.max()),
            "macro_non_null_scores": {c: int(scores[c].notna().sum()) for c in scores.columns},
        },
        "grid": {
            "state_hypotheses": int(len(state_results)),
            "state_passes": int(sum(bool(x["state_pass"]) for x in state_results)),
            "economic_cells": int(len(cells)),
            "economic_passes_before_neighborhood": int(sum(bool(x.get("economic_pass_before_neighborhood")) for x in cells)),
            "full_development_passes": int(len(passed)),
        },
        "state_results": state_results,
        "cells": cells,
        "selected_candidates_for_separate_freeze": [x["candidate_id"] for x in selected],
        "locked_internal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2))
    print(json.dumps(clean({"grid": payload["grid"], "selected": payload["selected_candidates_for_separate_freeze"], "validation_opened": False}), indent=2))


if __name__ == "__main__":
    main()
