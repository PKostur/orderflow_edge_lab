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
    x = np.asarray(values, dtype=float)
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


def stable_seed(base_seed: int, text: str) -> int:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return int((base_seed + int.from_bytes(h[:4], "big")) % (2**32 - 1))


def sign_flip_pvalue(fold_rhos: list[float], epochs: int, seed: int) -> float:
    r = np.asarray(fold_rhos, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return float("nan")
    observed = float(np.median(r))
    if observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    ar = np.abs(r)
    count = 0
    done = 0
    while done < epochs:
        n = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(ar)))
        null = np.median(signs * ar[None, :], axis=1)
        count += int(np.sum(null >= observed))
        done += n
    return float((count + 1) / (epochs + 1))


def bh_qvalues(pvals: list[float]) -> list[float]:
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


def load_cash(path: Path, prefix: str, minimum_tick_volume: int) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    required = ["time", "open", "high", "low", "close", "tick_volume"]
    missing = [c for c in required if c not in d.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce").dt.floor("D")
    for c in required[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=required)
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d["tick_volume"] >= minimum_tick_volume]
    d = d[d["time"].dt.weekday <= 4]
    d = d.drop_duplicates("time", keep="last").set_index("time").sort_index()
    return d[["open", "high", "low", "close", "tick_volume"]].add_prefix(prefix + "_")


def load_fred(path: Path, series_id: str) -> pd.Series:
    d = pd.read_csv(path)
    date_col = "observation_date" if "observation_date" in d.columns else "DATE" if "DATE" in d.columns else d.columns[0]
    value_col = series_id if series_id in d.columns else d.columns[-1]
    dt = pd.to_datetime(d[date_col], utc=True, errors="coerce").dt.floor("D")
    val = pd.to_numeric(d[value_col].replace(".", np.nan), errors="coerce")
    s = pd.Series(val.to_numpy(float), index=dt, name=series_id).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def align_macro_to_metals(index: pd.DatetimeIndex, s: pd.Series, lag_bars: int, tolerance_days: int) -> pd.Series:
    # As-of fill only from observations on or before a metals date; then lag one
    # metals trading bar so same-date macro releases can never affect that signal.
    aligned = s.reindex(index, method="ffill", tolerance=pd.Timedelta(days=tolerance_days))
    return aligned.shift(lag_bars)


def median_fold_risk_adjusted(frame: pd.DataFrame, value_col: str) -> float:
    vals = []
    for _, g in frame.groupby("fold"):
        x = g[value_col].to_numpy(float)
        if len(x) < 2:
            continue
        sd = float(np.std(x, ddof=1))
        if np.isfinite(sd) and sd > 0:
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


def adaptive_states(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    a = cfg["base_relative_state"]
    warm = int(a["initial_warmup_trading_days"])
    lam = float(a["forgetting_factor"])
    y = np.log(d["gold_close"].to_numpy(float))
    x = np.log(d["silver_close"].to_numpy(float))
    n = len(d)
    out = pd.DataFrame(index=d.index, columns=["alpha", "beta", "innovation", "innovation_sd", "z"], dtype=float)
    X0 = np.column_stack([np.ones(warm), x[:warm]])
    y0 = y[:warm]
    theta, *_ = np.linalg.lstsq(X0, y0, rcond=None)
    resid0 = y0 - X0 @ theta
    var = float(np.var(resid0, ddof=0))
    if not np.isfinite(var) or var <= 0:
        raise ValueError("invalid warmup innovation variance")
    gram = (X0.T @ X0) / float(warm)
    P = np.linalg.inv(gram + 1e-8 * np.eye(2)) * 100.0
    min_sd = float(a["minimum_innovation_std"])
    for i in range(warm, n):
        xt = np.array([1.0, x[i]], dtype=float)
        pred = float(xt @ theta)
        innov = float(y[i] - pred)
        sd = float(math.sqrt(max(var, min_sd**2)))
        out.iloc[i] = [float(theta[0]), float(theta[1]), innov, sd, innov / sd]
        Px = P @ xt
        denom = float(lam + xt @ Px)
        if not np.isfinite(denom) or denom <= 0:
            raise ValueError("invalid RLS denominator")
        K = Px / denom
        theta = theta + K * innov
        P = (P - np.outer(K, xt) @ P) / lam
        P = 0.5 * (P + P.T)
        var = float(lam * var + (1.0 - lam) * innov * innov)
    return out


def state_admitted(s: pd.Series, cfg: dict) -> bool:
    a = cfg["base_relative_state"]
    vals = [s.get("alpha"), s.get("beta"), s.get("innovation"), s.get("innovation_sd"), s.get("z")]
    if not all(np.isfinite(float(v)) for v in vals):
        return False
    return bool(
        float(s["beta"]) > float(a["beta_gt"])
        and float(s["beta"]) < float(a["beta_lt"])
        and float(s["innovation_sd"]) >= float(a["minimum_innovation_std"])
    )


def build_macro_features(d: pd.DataFrame, vix: pd.Series, usd: pd.Series, ry: pd.Series, cfg: dict) -> pd.DataFrame:
    lag = int(cfg["data_admission"]["macro_observation_lag_trading_bars"])
    tol = int(cfg["data_admission"]["macro_asof_forward_fill_max_calendar_days"])
    look = int(cfg["macro_state"]["lookback_trading_bars"])
    x = pd.DataFrame(index=d.index)
    x["vix"] = align_macro_to_metals(d.index, vix, lag, tol)
    x["usd"] = align_macro_to_metals(d.index, usd, lag, tol)
    x["ry"] = align_macro_to_metals(d.index, ry, lag, tol)
    x["vix_change"] = x["vix"] / x["vix"].shift(look) - 1.0
    x["usd_change"] = np.log(x["usd"] / x["usd"].shift(look))
    x["ry_change"] = x["ry"] - x["ry"].shift(look)
    x["vix_component"] = np.where(x["vix_change"] > 0, 1.0, -1.0)
    x["usd_component"] = np.where(x["usd_change"] > 0, 1.0, -1.0)
    x["ry_component"] = np.where(x["ry_change"] < 0, 1.0, -1.0)
    valid = x[["vix_change", "usd_change", "ry_change"]].notna().all(axis=1)
    x.loc[~valid, ["vix_component", "usd_component", "ry_component"]] = np.nan
    x["risk_off_score"] = x[["vix_component", "usd_component", "ry_component"]].sum(axis=1, min_count=3)
    return x


def build_state_rows(d: pd.DataFrame, states: pd.DataFrame, macro: pd.DataFrame, start_ts: pd.Timestamp, cfg: dict) -> tuple[pd.DataFrame, np.ndarray]:
    h = int(cfg["state_first"]["horizon_trading_bars"])
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    lg = np.log(d["gold_close"].to_numpy(float))
    ls = np.log(d["silver_close"].to_numpy(float))
    threshold = float(cfg["base_relative_state"]["entry_abs_innovation_z_gte"])
    rows = []
    for i in range(len(d) - h):
        s = states.iloc[i]
        m = macro.iloc[i]
        if not state_admitted(s, cfg) or abs(float(s["z"])) < threshold:
            continue
        if not np.isfinite(float(m["risk_off_score"])):
            continue
        j = i + h
        if fold[j] != fold[i]:
            continue
        side = int(-np.sign(float(s["z"])))
        if side == 0:
            continue
        future_resid = float(lg[j] - float(s["alpha"]) - float(s["beta"]) * ls[j])
        target = float(side * (future_resid - float(s["innovation"])) / float(s["innovation_sd"]))
        rows.append({
            "timestamp": str(d.index[i]),
            "fold": int(fold[i]),
            "side": side,
            "target": target,
            "composite_alignment_score": float(side * m["risk_off_score"]),
            "vix_alignment": float(side * m["vix_component"]),
            "usd_alignment": float(side * m["usd_component"]),
            "real_yield_alignment": float(side * m["ry_component"]),
        })
    return pd.DataFrame(rows), fold


def evaluate_state_hypotheses(rows: pd.DataFrame, cfg: dict) -> list[dict]:
    out = []
    s = cfg["state_first"]
    min_events = int(s["minimum_events_per_state_fold"])
    for name in s["hypotheses"]:
        fold_rows = []
        if not rows.empty:
            for fid, g in rows.groupby("fold"):
                if len(g) < min_events:
                    continue
                r = rho(g[name], g["target"])
                if np.isfinite(r):
                    fold_rows.append({"fold": int(fid), "rho": float(r), "events": int(len(g))})
        rhos = [x["rho"] for x in fold_rows]
        p = sign_flip_pvalue(rhos, int(s["sign_flip_epochs"]), stable_seed(int(s["sign_flip_seed"]), name))
        out.append({
            "hypothesis": name,
            "events": int(len(rows)),
            "state_folds": int(len(fold_rows)),
            "fold_rhos": fold_rows,
            "median_fold_spearman": float(np.median(rhos)) if rhos else np.nan,
            "positive_fold_fraction": float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
            "sign_flip_p": p,
        })
    qvals = bh_qvalues([x["sign_flip_p"] for x in out])
    for x, q in zip(out, qvals):
        x["bh_q"] = q
        x["state_pass"] = bool(
            x["state_folds"] >= int(s["minimum_scorable_state_folds"])
            and x["median_fold_spearman"] > float(s["minimum_composite_median_fold_spearman"])
            and x["positive_fold_fraction"] >= float(s["minimum_composite_positive_fold_fraction"])
            and x["bh_q"] <= float(s["maximum_bh_fdr_q"])
        )
    return out


def simulate(d: pd.DataFrame, states: pd.DataFrame, macro: pd.DataFrame, fold: np.ndarray, align_threshold: int, max_hold: int, cfg: dict, conditioned: bool) -> pd.DataFrame:
    entry_z = float(cfg["base_relative_state"]["entry_abs_innovation_z_gte"])
    min_hold = int(cfg["execution"]["minimum_hold_trading_bars"])
    exit_z = float(cfg["execution"]["adaptive_exit_abs_innovation_z_lte"])
    rows = []
    i = 0
    while i < len(d) - 2:
        s = states.iloc[i]
        m = macro.iloc[i]
        if not state_admitted(s, cfg) or abs(float(s["z"])) < entry_z:
            i += 1
            continue
        if not np.isfinite(float(m["risk_off_score"])):
            i += 1
            continue
        side = int(-np.sign(float(s["z"])))
        if side == 0:
            i += 1
            continue
        alignment = float(side * m["risk_off_score"])
        if conditioned and alignment < align_threshold:
            i += 1
            continue
        entry_pos = i + 1
        max_exit_pos = entry_pos + max_hold
        if max_exit_pos >= len(d):
            break
        exit_pos = max_exit_pos
        exit_reason = "max_hold"
        for j in range(i + min_hold, max_exit_pos):
            sj = states.iloc[j]
            if state_admitted(sj, cfg) and abs(float(sj["z"])) <= exit_z:
                exit_pos = j + 1
                exit_reason = "adaptive_normalization"
                break
        if fold[exit_pos] != fold[i]:
            i += 1
            continue
        beta = abs(float(s["beta"]))
        wg = 1.0 / (1.0 + beta)
        ws = beta / (1.0 + beta)
        ge = float(d["gold_open"].iloc[entry_pos]); gx = float(d["gold_open"].iloc[exit_pos])
        se = float(d["silver_open"].iloc[entry_pos]); sx = float(d["silver_open"].iloc[exit_pos])
        gret = gx / ge - 1.0
        sret = sx / se - 1.0
        spread = wg * gret - ws * sret
        static = 0.5 * gret - 0.5 * sret
        rows.append({
            "signal_time": str(d.index[i]),
            "entry_time": str(d.index[entry_pos]),
            "exit_time": str(d.index[exit_pos]),
            "fold": int(fold[i]),
            "side": side,
            "alignment_score": alignment,
            "risk_off_score": float(m["risk_off_score"]),
            "entry_z": float(s["z"]),
            "entry_beta": float(s["beta"]),
            "holding_bars": int(exit_pos - entry_pos),
            "exit_reason": exit_reason,
            "gross_bps": float(side * spread * 10000.0),
            "unhedged_gold_gross_bps": float(side * gret * 10000.0),
            "static_spread_gross_bps": float(side * static * 10000.0),
        })
        i = exit_pos
    return pd.DataFrame(rows)


def summarize_cell(tr: pd.DataFrame, align_threshold: int, max_hold: int, control_ra: float, cfg: dict) -> dict:
    out = {"alignment_threshold": int(align_threshold), "max_hold": int(max_hold), "trades": int(len(tr))}
    if tr.empty:
        return out
    costs = [float(x) for x in cfg["execution"]["round_trip_cost_bps_on_total_gross_notional"]]
    primary = float(cfg["execution"]["primary_cost_bps"])
    for cost in costs:
        key = f"{cost:g}"
        col = f"net_{key}"
        tr[col] = tr["gross_bps"] - cost
        fn = tr.groupby("fold")[col].mean()
        fp = tr.groupby("fold")[col].apply(pf)
        out[f"net_{key}_median_fold_bps"] = float(fn.median())
        out[f"pf_{key}_median_fold"] = float(fp.median())
        out[f"positive_fold_fraction_{key}"] = float((fn > 0).mean())
        out[f"mean_net_{key}_bps"] = float(tr[col].mean())
    pkey = f"{primary:g}"
    pcol = f"net_{pkey}"
    tr["unhedged_gold_net_primary"] = tr["unhedged_gold_gross_bps"] - primary
    tr["static_spread_net_primary"] = tr["static_spread_gross_bps"] - primary
    out["reversed_mean_net_primary_bps"] = float((-tr["gross_bps"] - primary).mean())
    out["strategy_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, pcol)
    out["unconditioned_v3_median_fold_risk_adjusted_primary"] = float(control_ra)
    out["unhedged_gold_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, "unhedged_gold_net_primary")
    out["static_spread_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, "static_spread_net_primary")
    out["long_spread"] = directional_stats(tr, pcol, 1)
    out["short_spread"] = directional_stats(tr, pcol, -1)
    out["trade_rows"] = tr.to_dict(orient="records")
    return out


def apply_economic_gate(c: dict, composite_pass: bool, cfg: dict) -> None:
    e = cfg["economic_gate"]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['execution']['high_cost_bps']):g}"
    c["economic_pass"] = bool(
        composite_pass
        and c.get("trades", 0) >= int(e["minimum_non_overlapping_trades"])
        and c.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(e["minimum_primary_median_fold_net_bps"])
        and c.get(f"pf_{pkey}_median_fold", 0.0) >= float(e["minimum_primary_median_fold_pf"])
        and c.get(f"positive_fold_fraction_{pkey}", 0.0) >= float(e["minimum_primary_positive_fold_fraction"])
        and c.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(e["minimum_high_cost_median_fold_net_bps"])
        and c.get(f"mean_net_{pkey}_bps", -np.inf) > float(e["minimum_overall_mean_primary_net_bps"])
        and c.get(f"mean_net_{pkey}_bps", -np.inf) > c.get("reversed_mean_net_primary_bps", np.inf)
        and np.isfinite(c.get("strategy_median_fold_risk_adjusted_primary", np.nan))
        and np.isfinite(c.get("unconditioned_v3_median_fold_risk_adjusted_primary", np.nan))
        and c.get("strategy_median_fold_risk_adjusted_primary", -np.inf) > c.get("unconditioned_v3_median_fold_risk_adjusted_primary", np.inf)
        and c.get("long_spread", {}).get("trades", 0) >= int(e["minimum_long_spread_trades"])
        and c.get("short_spread", {}).get("trades", 0) >= int(e["minimum_short_spread_trades"])
        and c.get("long_spread", {}).get("mean_net_bps", -np.inf) > 0
        and c.get("short_spread", {}).get("mean_net_bps", -np.inf) > 0
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--silver", required=True)
    ap.add_argument("--vix", required=True)
    ap.add_argument("--usd", required=True)
    ap.add_argument("--real-yield", required=True, dest="real_yield")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    min_tv = int(cfg["data_admission"]["minimum_tick_volume_each_leg"])
    gold = load_cash(Path(args.gold), "gold", min_tv)
    silver = load_cash(Path(args.silver), "silver", min_tv)
    common = gold.join(silver, how="inner").dropna().sort_index()
    dev = cfg["periods"]["development"]
    start_ts = pd.Timestamp(dev["start"], tz="UTC")
    end_ts = pd.Timestamp(dev["end_exclusive"], tz="UTC")
    d = common.loc[(common.index >= start_ts) & (common.index < end_ts)].copy()
    if len(d) < 1000:
        raise SystemExit("insufficient development rows")

    vix = load_fred(Path(args.vix), "VIXCLS")
    usd = load_fred(Path(args.usd), "DTWEXBGS")
    ry = load_fred(Path(args.real_yield), "DFII10")
    states = adaptive_states(d, cfg)
    macro = build_macro_features(d, vix, usd, ry, cfg)
    state_rows, fold = build_state_rows(d, states, macro, start_ts, cfg)
    state_hypotheses = evaluate_state_hypotheses(state_rows, cfg)
    composite = next(x for x in state_hypotheses if x["hypothesis"] == "composite_alignment_score")
    composite_pass = bool(composite["state_pass"])

    controls = {}
    for mh in cfg["execution"]["maximum_hold_trading_bars"]:
        ctr = simulate(d, states, macro, fold, 0, int(mh), cfg, conditioned=False)
        if ctr.empty:
            controls[str(mh)] = {"trades": 0, "median_fold_risk_adjusted_primary": np.nan, "mean_net_primary_bps": np.nan}
        else:
            primary = float(cfg["execution"]["primary_cost_bps"])
            ctr["net_primary"] = ctr["gross_bps"] - primary
            controls[str(mh)] = {
                "trades": int(len(ctr)),
                "median_fold_risk_adjusted_primary": median_fold_risk_adjusted(ctr, "net_primary"),
                "mean_net_primary_bps": float(ctr["net_primary"].mean()),
            }

    cells = []
    for at in cfg["economic_grid"]["alignment_thresholds"]:
        for mh in cfg["economic_grid"]["maximum_hold_trading_bars"]:
            tr = simulate(d, states, macro, fold, int(at), int(mh), cfg, conditioned=True)
            c = summarize_cell(tr, int(at), int(mh), controls[str(mh)]["median_fold_risk_adjusted_primary"], cfg)
            apply_economic_gate(c, composite_pass, cfg)
            cells.append(c)

    passed = [c for c in cells if c.get("economic_pass")]
    passed.sort(key=lambda c: (-c.get("net_10_median_fold_bps", -np.inf), -c.get("mean_net_10_bps", -np.inf), c["alignment_threshold"], c["max_hold"]))
    selected = passed[: int(cfg["candidate_selection"]["maximum_candidates"])]

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "source": cfg["source"],
        "development_period": dev,
        "data_integrity": {
            "development_rows": int(len(d)),
            "development_first_bar": str(d.index.min()),
            "development_last_bar": str(d.index.max()),
            "state_rows": int(len(state_rows)),
            "macro_complete_rows": int(macro[["risk_off_score"]].notna().all(axis=1).sum()),
        },
        "state_hypotheses": state_hypotheses,
        "composite_state_pass": composite_pass,
        "unconditioned_controls": controls,
        "grid": {
            "state_hypotheses": int(len(state_hypotheses)),
            "state_passes": int(sum(bool(x["state_pass"]) for x in state_hypotheses)),
            "economic_cells": int(len(cells)),
            "economic_passes": int(len(passed)),
        },
        "cells": cells,
        "selected_candidates_for_separate_freeze": [
            {"alignment_threshold": c["alignment_threshold"], "max_hold": c["max_hold"]} for c in selected
        ],
        "locked_internal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean({
        "composite_state_pass": composite_pass,
        "state_passes": payload["grid"]["state_passes"],
        "economic_passes": payload["grid"]["economic_passes"],
        "selected": payload["selected_candidates_for_separate_freeze"],
        "validation_opened": False,
    }), indent=2))


if __name__ == "__main__":
    main()
