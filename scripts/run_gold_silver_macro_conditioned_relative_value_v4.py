from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler


def clean(v):
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, (np.integer,)):
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


def stable_seed(base_seed: int, text: str) -> int:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return int((base_seed + int.from_bytes(h[:4], "big")) % (2**32 - 1))


def sign_flip_pvalue(values: list[float], epochs: int, seed: int) -> float:
    r = np.asarray(values, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return float("nan")
    observed = float(np.median(r))
    if observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    abs_r = np.abs(r)
    count = 0
    done = 0
    while done < epochs:
        n = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(abs_r)))
        null = np.median(signs * abs_r[None, :], axis=1)
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
    for rank, idx in enumerate(order, start=1):
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


def load_fred(path: Path, series_id: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    date_col = next((c for c in d.columns if str(c).upper() in {"DATE", "OBSERVATION_DATE"}), None)
    if date_col is None:
        date_col = d.columns[0]
    value_col = series_id if series_id in d.columns else d.columns[-1]
    out = pd.DataFrame({
        "obs_date": pd.to_datetime(d[date_col], utc=True, errors="coerce").dt.floor("D"),
        "value": pd.to_numeric(d[value_col].replace(".", np.nan), errors="coerce"),
    }).dropna()
    out = out.drop_duplicates("obs_date", keep="last").sort_values("obs_date")
    return out


def align_one_macro(index: pd.DatetimeIndex, raw: pd.DataFrame, cfg: dict, name: str) -> pd.DataFrame:
    left = pd.DataFrame({"time": index}).sort_values("time")
    right = raw.rename(columns={"obs_date": f"{name}_obs_date", "value": name}).sort_values(f"{name}_obs_date")
    joined = pd.merge_asof(
        left,
        right,
        left_on="time",
        right_on=f"{name}_obs_date",
        direction="backward",
        allow_exact_matches=True,
    ).set_index("time")
    lag = int(cfg["data_admission"]["macro_completed_observation_lag_common_bars"])
    joined[name] = joined[name].shift(lag)
    joined[f"{name}_obs_date"] = joined[f"{name}_obs_date"].shift(lag)
    max_stale = int(cfg["data_admission"]["macro_max_staleness_calendar_days"])
    stale = (joined.index.to_series() - joined[f"{name}_obs_date"]).dt.days > max_stale
    joined.loc[stale, name] = np.nan
    return joined


def percentile_last(values: np.ndarray) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float("nan")
    last = x[-1]
    return float(np.mean(x <= last))


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
    P = np.linalg.inv(gram + 1e-8 * np.eye(2)) * float(a["initial_covariance_scale"])
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


def admitted_state(s: pd.Series, cfg: dict) -> bool:
    a = cfg["base_relative_state"]
    vals = [s.get("alpha"), s.get("beta"), s.get("innovation"), s.get("innovation_sd"), s.get("z")]
    if not all(np.isfinite(float(v)) for v in vals):
        return False
    return bool(
        float(s["beta"]) > float(a["beta_gt"])
        and float(s["beta"]) < float(a["beta_lt"])
        and float(s["innovation_sd"]) >= float(a["minimum_innovation_std"])
        and abs(float(s["z"])) >= float(a["entry_abs_innovation_z_gte"])
    )


def add_macro_features(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    f = cfg["macro_features"]
    out = d.copy()
    vwin = int(f["vix_percentile_window_common_bars"])
    out["vix_percentile_252"] = out["VIXCLS"].rolling(vwin, min_periods=vwin).apply(percentile_last, raw=True)
    n = int(f["real_yield_change_common_bars"])
    out["dfii10_change_20"] = out["DFII10"] - out["DFII10"].shift(n)
    n2 = int(f["dollar_log_return_common_bars"])
    out["dtwexbgs_log_return_20"] = np.log(out["DTWEXBGS"] / out["DTWEXBGS"].shift(n2))
    return out


def build_events(d: pd.DataFrame, states: pd.DataFrame, horizon: int, start_ts: pd.Timestamp, cfg: dict) -> pd.DataFrame:
    cluster_days = int(cfg["state_model"]["dependence_cluster_calendar_days"])
    folds = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    feature_names = list(cfg["macro_features"]["feature_vector"])
    rows = []
    for i in range(len(d)):
        s = states.iloc[i]
        if not admitted_state(s, cfg):
            continue
        entry_pos = i + 1
        exit_pos = entry_pos + horizon
        if exit_pos >= len(d):
            continue
        if folds[exit_pos] != folds[i]:
            continue
        side_z = int(np.sign(float(s["z"])))
        trade_side = -side_z
        if trade_side == 0:
            continue
        beta = abs(float(s["beta"]))
        wg = 1.0 / (1.0 + beta)
        ws = beta / (1.0 + beta)
        ge = float(d["gold_open"].iloc[entry_pos]); gx = float(d["gold_open"].iloc[exit_pos])
        se = float(d["silver_open"].iloc[entry_pos]); sx = float(d["silver_open"].iloc[exit_pos])
        gret = gx / ge - 1.0
        sret = sx / se - 1.0
        spread = wg * gret - ws * sret
        gross = float(trade_side * spread * 10000.0)
        row = {
            "signal_pos": int(i),
            "entry_pos": int(entry_pos),
            "exit_pos": int(exit_pos),
            "signal_time": str(d.index[i]),
            "fold": int(folds[i]),
            "side": int(trade_side),
            "innovation_side": int(side_z),
            "abs_innovation_z": abs(float(s["z"])),
            "entry_beta": float(s["beta"]),
            "gross_bps": gross,
            "target": int(gross > 0),
            "unhedged_gold_gross_bps": float(trade_side * gret * 10000.0),
            "static_spread_gross_bps": float(trade_side * (0.5 * gret - 0.5 * sret) * 10000.0),
            "vix_percentile_252": float(d["vix_percentile_252"].iloc[i]),
            "dfii10_change_20": float(d["dfii10_change_20"].iloc[i]),
            "dtwexbgs_log_return_20": float(d["dtwexbgs_log_return_20"].iloc[i]),
        }
        row["innovation_side_x_vix_percentile_252"] = row["innovation_side"] * row["vix_percentile_252"]
        row["innovation_side_x_dfii10_change_20"] = row["innovation_side"] * row["dfii10_change_20"]
        row["innovation_side_x_dtwexbgs_log_return_20"] = row["innovation_side"] * row["dtwexbgs_log_return_20"]
        if all(np.isfinite(float(row[x])) for x in feature_names):
            rows.append(row)
    return pd.DataFrame(rows)


def prequential_score(events: pd.DataFrame, horizon: int, cfg: dict) -> tuple[dict, pd.DataFrame]:
    m = cfg["state_model"]
    feature_names = list(cfg["macro_features"]["feature_vector"])
    scored = []
    fold_rows = []
    coef_rows = []
    if events.empty:
        return {"horizon": horizon, "state_folds": 0}, pd.DataFrame()
    folds = sorted(int(x) for x in events["fold"].unique())
    for fid in folds:
        train = events[events["fold"] < fid].copy()
        test = events[events["fold"] == fid].copy()
        if train["fold"].nunique() < int(m["minimum_prior_training_folds"]):
            continue
        if len(train) < int(m["minimum_prior_training_events"]):
            continue
        if len(test) < int(m["minimum_test_events_per_fold"]):
            continue
        if train["target"].nunique() < 2 or test["target"].nunique() < 2:
            continue
        scaler = StandardScaler().fit(train[feature_names].to_numpy(float))
        Xtr = scaler.transform(train[feature_names].to_numpy(float))
        Xte = scaler.transform(test[feature_names].to_numpy(float))
        model = LogisticRegression(
            penalty="l2",
            C=float(m["C"]),
            solver=str(m["solver"]),
            max_iter=int(m["max_iter"]),
            class_weight=m["class_weight"],
            random_state=0,
        ).fit(Xtr, train["target"].to_numpy(int))
        p = model.predict_proba(Xte)[:, 1]
        y = test["target"].to_numpy(int)
        auc = float(roc_auc_score(y, p))
        brier = float(brier_score_loss(y, p))
        prev = float(train["target"].mean())
        base = float(np.mean((y - prev) ** 2))
        fold_rows.append({
            "fold": fid,
            "events": int(len(test)),
            "auc": auc,
            "auc_excess": auc - 0.5,
            "brier": brier,
            "constant_rate_brier": base,
            "training_events": int(len(train)),
            "training_folds": int(train["fold"].nunique()),
            "training_prevalence": prev,
        })
        coef_rows.append({
            "fold": fid,
            "intercept": float(model.intercept_[0]),
            "coefficients": {k: float(v) for k, v in zip(feature_names, model.coef_[0])},
        })
        tt = test.copy()
        tt["predicted_success_probability"] = p
        tt["training_prevalence"] = prev
        scored.append(tt)
    oof = pd.concat(scored, ignore_index=True) if scored else pd.DataFrame()
    aucs = [x["auc"] for x in fold_rows]
    excess = [x["auc_excess"] for x in fold_rows]
    briers = [x["brier"] for x in fold_rows]
    bases = [x["constant_rate_brier"] for x in fold_rows]
    hid = f"macro_logit_hold{horizon}"
    out = {
        "state_hypothesis_id": hid,
        "horizon": int(horizon),
        "qualifying_events_total": int(len(events)),
        "oof_events": int(len(oof)),
        "state_folds": int(len(fold_rows)),
        "fold_metrics": fold_rows,
        "fold_coefficients": coef_rows,
        "median_fold_auc": float(np.median(aucs)) if aucs else np.nan,
        "positive_auc_fold_fraction": float(np.mean(np.asarray(aucs) > 0.5)) if aucs else 0.0,
        "median_fold_brier": float(np.median(briers)) if briers else np.nan,
        "median_fold_constant_rate_brier": float(np.median(bases)) if bases else np.nan,
        "auc_sign_flip_p": sign_flip_pvalue(
            excess,
            int(m["fold_auc_sign_flip_epochs"]),
            stable_seed(int(m["fold_auc_sign_flip_seed"]), hid),
        ),
    }
    return out, oof


def select_nonoverlap(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    chosen = []
    next_signal_allowed = -1
    for _, r in frame.sort_values(["signal_pos", "fold"]).iterrows():
        if int(r["signal_pos"]) < next_signal_allowed:
            continue
        chosen.append(r)
        next_signal_allowed = int(r["exit_pos"])
    return pd.DataFrame(chosen).reset_index(drop=True) if chosen else frame.iloc[:0].copy()


def evaluate_economics(oof: pd.DataFrame, all_events: pd.DataFrame, horizon: int, cfg: dict) -> dict:
    trans = cfg["economic_translation"]
    gate = cfg["economic_gate"]
    threshold = float(trans["oof_predicted_success_probability_gte"])
    filtered = select_nonoverlap(oof[oof["predicted_success_probability"] >= threshold].copy())
    scored_folds = set(int(x) for x in oof["fold"].unique()) if not oof.empty else set()
    unfiltered = select_nonoverlap(all_events[all_events["fold"].isin(scored_folds)].copy())
    out = {
        "candidate_id": f"macro_filtered_adaptive_reversion_hold{horizon}",
        "state_hypothesis_id": f"macro_logit_hold{horizon}",
        "horizon": int(horizon),
        "probability_threshold": threshold,
        "eligible_oof_events": int(len(oof)),
        "filtered_nonoverlap_trades": int(len(filtered)),
        "unfiltered_control_nonoverlap_trades": int(len(unfiltered)),
    }
    if filtered.empty:
        return out
    costs = [float(x) for x in trans["round_trip_cost_bps_on_total_gross_notional"]]
    primary = float(trans["primary_cost_bps"])
    for cost in costs:
        key = f"{cost:g}"
        col = f"net_{key}"
        filtered[col] = filtered["gross_bps"] - cost
        fn = filtered.groupby("fold")[col].mean()
        fp = filtered.groupby("fold")[col].apply(pf)
        out[f"net_{key}_median_fold_bps"] = float(fn.median())
        out[f"pf_{key}_median_fold"] = float(fp.median())
        out[f"positive_fold_fraction_{key}"] = float((fn > 0).mean())
        out[f"mean_net_{key}_bps"] = float(filtered[col].mean())
    pkey = f"{primary:g}"
    pcol = f"net_{pkey}"
    filtered["unhedged_gold_net_primary"] = filtered["unhedged_gold_gross_bps"] - primary
    filtered["static_spread_net_primary"] = filtered["static_spread_gross_bps"] - primary
    if not unfiltered.empty:
        unfiltered["net_primary"] = unfiltered["gross_bps"] - primary
        out["unfiltered_base_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(unfiltered, "net_primary")
        out["unfiltered_base_mean_net_primary_bps"] = float(unfiltered["net_primary"].mean())
    else:
        out["unfiltered_base_median_fold_risk_adjusted_primary"] = np.nan
        out["unfiltered_base_mean_net_primary_bps"] = np.nan
    out["filtered_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(filtered, pcol)
    out["unhedged_gold_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(filtered, "unhedged_gold_net_primary")
    out["static_spread_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(filtered, "static_spread_net_primary")
    out["reversed_mean_net_primary_bps"] = float((-filtered["gross_bps"] - primary).mean())
    out["long_spread"] = directional_stats(filtered, pcol, 1)
    out["short_spread"] = directional_stats(filtered, pcol, -1)
    if len(filtered) >= 3 and np.std(filtered["gross_bps"]) > 0 and np.std(filtered["unhedged_gold_gross_bps"]) > 0:
        out["trade_return_corr_with_unhedged_gold"] = float(np.corrcoef(filtered["gross_bps"], filtered["unhedged_gold_gross_bps"])[0, 1])
    else:
        out["trade_return_corr_with_unhedged_gold"] = np.nan
    try:
        out["probability_deciles"] = (
            oof.assign(decile=pd.qcut(oof["predicted_success_probability"], 10, labels=False, duplicates="drop"))
            .groupby("decile")
            .agg(events=("target", "size"), realized_success_rate=("target", "mean"), mean_gross_bps=("gross_bps", "mean"), mean_probability=("predicted_success_probability", "mean"))
            .reset_index()
            .to_dict(orient="records")
        )
    except Exception:
        out["probability_deciles"] = []
    out["trade_rows"] = filtered.to_dict(orient="records")
    return out


def apply_state_gates(states: list[dict], cfg: dict) -> None:
    qvals = bh_qvalues([x.get("auc_sign_flip_p", np.nan) for x in states])
    m = cfg["state_model"]
    for s, q in zip(states, qvals):
        s["state_bh_q"] = q
        s["state_pass"] = bool(
            s.get("state_folds", 0) >= int(m["minimum_scorable_oof_folds"])
            and s.get("median_fold_auc", -np.inf) >= float(m["minimum_median_fold_auc"])
            and s.get("positive_auc_fold_fraction", 0.0) >= float(m["minimum_positive_auc_fold_fraction"])
            and s.get("median_fold_brier", np.inf) < s.get("median_fold_constant_rate_brier", -np.inf)
            and s.get("state_bh_q", 1.0) <= float(m["maximum_bh_fdr_q"])
        )


def apply_economic_gates(cells: list[dict], states: list[dict], cfg: dict) -> None:
    state_map = {s["state_hypothesis_id"]: s for s in states}
    e = cfg["economic_gate"]
    trans = cfg["economic_translation"]
    pkey = f"{float(trans['primary_cost_bps']):g}"
    hkey = f"{float(trans['high_cost_bps']):g}"
    for c in cells:
        s = state_map[c["state_hypothesis_id"]]
        c["state_pass"] = bool(s.get("state_pass"))
        c["economic_pass"] = bool(
            c.get("filtered_nonoverlap_trades", 0) >= int(e["minimum_non_overlapping_trades"])
            and c.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(e["minimum_primary_median_fold_net_bps"])
            and c.get(f"pf_{pkey}_median_fold", 0.0) >= float(e["minimum_primary_median_fold_pf"])
            and c.get(f"positive_fold_fraction_{pkey}", 0.0) >= float(e["minimum_primary_positive_fold_fraction"])
            and c.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(e["minimum_high_cost_median_fold_net_bps"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > 0.0
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > c.get("reversed_mean_net_primary_bps", np.inf)
            and np.isfinite(c.get("filtered_median_fold_risk_adjusted_primary", np.nan))
            and np.isfinite(c.get("unfiltered_base_median_fold_risk_adjusted_primary", np.nan))
            and c.get("filtered_median_fold_risk_adjusted_primary", -np.inf) > c.get("unfiltered_base_median_fold_risk_adjusted_primary", np.inf)
            and c.get("long_spread", {}).get("trades", 0) >= int(e["minimum_long_spread_trades"])
            and c.get("short_spread", {}).get("trades", 0) >= int(e["minimum_short_spread_trades"])
            and c.get("long_spread", {}).get("mean_net_bps", -np.inf) > 0.0
            and c.get("short_spread", {}).get("mean_net_bps", -np.inf) > 0.0
        )
        c["pre_family_pass"] = bool(c["state_pass"] and c["economic_pass"])
    by_h = {int(c["horizon"]): c for c in cells}
    for c in cells:
        other = by_h[42 if int(c["horizon"]) == 21 else 21]
        other_state = state_map[other["state_hypothesis_id"]]
        consistent = bool(
            other_state.get("median_fold_auc", -np.inf) >= 0.50
            and other.get(f"net_{pkey}_median_fold_bps", -np.inf) >= 0.0
        )
        c["other_horizon_consistent"] = consistent
        c["full_development_pass"] = bool(c["pre_family_pass"] and consistent)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--silver", required=True)
    ap.add_argument("--vix", required=True)
    ap.add_argument("--real-yield", required=True)
    ap.add_argument("--dollar", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    min_tv = int(cfg["data_admission"]["minimum_tick_volume_each_price_leg"])
    gold = load_cash(Path(args.gold), "gold", min_tv)
    silver = load_cash(Path(args.silver), "silver", min_tv)
    common = gold.join(silver, how="inner").dropna().sort_index()

    dev = cfg["periods"]["development"]
    start_ts = pd.Timestamp(dev["start"], tz="UTC")
    end_ts = pd.Timestamp(dev["end_exclusive"], tz="UTC")
    d = common.loc[(common.index >= start_ts) & (common.index < end_ts)].copy()
    if len(d) < 1000:
        raise SystemExit("insufficient price development rows")

    macro_inputs = {
        "VIXCLS": load_fred(Path(args.vix), "VIXCLS"),
        "DFII10": load_fred(Path(args.real_yield), "DFII10"),
        "DTWEXBGS": load_fred(Path(args.dollar), "DTWEXBGS"),
    }
    for name, raw in macro_inputs.items():
        d = d.join(align_one_macro(d.index, raw, cfg, name)[[name]], how="left")
    d = add_macro_features(d, cfg)
    states = adaptive_states(d, cfg)

    state_results = []
    oof_by_horizon = {}
    events_by_horizon = {}
    for horizon in [int(x) for x in cfg["state_model"]["state_horizons_trading_bars"]]:
        events = build_events(d, states, horizon, start_ts, cfg)
        state_result, oof = prequential_score(events, horizon, cfg)
        events_by_horizon[horizon] = events
        oof_by_horizon[horizon] = oof
        state_results.append(state_result)
    apply_state_gates(state_results, cfg)

    cells = []
    for horizon in [int(x) for x in cfg["economic_translation"]["holds_trading_bars"]]:
        cells.append(evaluate_economics(oof_by_horizon[horizon], events_by_horizon[horizon], horizon, cfg))
    apply_economic_gates(cells, state_results, cfg)

    passed = [c for c in cells if c.get("full_development_pass")]
    state_map = {s["state_hypothesis_id"]: s for s in state_results}
    pkey = f"{float(cfg['economic_translation']['primary_cost_bps']):g}"
    passed.sort(key=lambda c: (
        -float(state_map[c["state_hypothesis_id"]].get("median_fold_auc", -np.inf)),
        -float(c.get(f"positive_fold_fraction_{pkey}", -np.inf)),
        -float(c.get(f"net_{pkey}_median_fold_bps", -np.inf)),
        int(c["horizon"]),
    ))
    selected = passed[: int(cfg["family_consistency_gate"]["maximum_candidates"])]

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "price_source": cfg["price_source"],
        "macro_source": cfg["macro_source"],
        "development_period": dev,
        "data_integrity": {
            "gold_rows_all_source": int(len(gold)),
            "silver_rows_all_source": int(len(silver)),
            "common_price_rows_all_source": int(len(common)),
            "development_rows": int(len(d)),
            "development_first_bar": str(d.index.min()),
            "development_last_bar": str(d.index.max()),
            "development_complete_feature_rows": int(d[list(cfg["macro_features"]["feature_vector"])[2:5]].dropna().shape[0]),
        },
        "grid": {
            "state_hypotheses": int(len(state_results)),
            "state_passes": int(sum(bool(s.get("state_pass")) for s in state_results)),
            "cells_evaluated": int(len(cells)),
            "economic_passes": int(sum(bool(c.get("economic_pass")) for c in cells)),
            "full_development_passes": int(len(passed)),
        },
        "state_hypotheses": state_results,
        "cells": cells,
        "selected_candidates_for_separate_freeze": [c["candidate_id"] for c in selected],
        "locked_internal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean({
        "state_hypotheses": payload["grid"]["state_hypotheses"],
        "state_passes": payload["grid"]["state_passes"],
        "cells": payload["grid"]["cells_evaluated"],
        "economic_passes": payload["grid"]["economic_passes"],
        "full_development_passes": payload["grid"]["full_development_passes"],
        "selected": payload["selected_candidates_for_separate_freeze"],
        "locked_internal_validation_opened": payload["locked_internal_validation_opened"],
    }), indent=2))


if __name__ == "__main__":
    main()
