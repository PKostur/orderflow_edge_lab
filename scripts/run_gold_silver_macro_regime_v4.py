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


def load_fred(path: Path, series: str) -> pd.Series:
    d = pd.read_csv(path)
    if d.shape[1] < 2:
        raise ValueError(f"{path}: expected at least two columns")
    date_col = d.columns[0]
    value_col = series if series in d.columns else d.columns[1]
    dates = pd.to_datetime(d[date_col], utc=True, errors="coerce").dt.floor("D")
    values = pd.to_numeric(d[value_col].replace(".", np.nan), errors="coerce")
    s = pd.Series(values.to_numpy(float), index=dates, name=series).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def rolling_z(s: pd.Series, window: int) -> pd.Series:
    mu = s.rolling(window, min_periods=window).mean()
    sd = s.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
    return (s - mu) / sd


def build_macro_features(index: pd.DatetimeIndex, real_yield: pd.Series, vix: pd.Series, cfg: dict):
    lag = int(cfg["macro_source"]["causal_lag_trading_days"])
    m = pd.DataFrame(index=index)
    m["DFII10"] = real_yield.reindex(index, method="ffill").shift(lag)
    m["VIXCLS"] = vix.reindex(index, method="ffill").shift(lag)
    w = int(cfg["macro_features"]["rolling_standardization_window_trading_days"])
    ry_level = -rolling_z(m["DFII10"], w)
    ry_change21 = -rolling_z(m["DFII10"].diff(21), w)
    vix_level = rolling_z(m["VIXCLS"], w)
    vix_change21 = rolling_z(m["VIXCLS"].diff(21), w)
    f = pd.DataFrame(index=index)
    f["real_yield_level_gold_favorability"] = ry_level
    f["real_yield_change21_gold_favorability"] = ry_change21
    f["vix_level_gold_favorability"] = vix_level
    f["vix_change21_gold_favorability"] = vix_change21
    f["safe_haven_composite"] = pd.concat([ry_change21, vix_level], axis=1).mean(axis=1, skipna=False)
    f["stress_shift_composite"] = pd.concat([ry_change21, vix_change21], axis=1).mean(axis=1, skipna=False)
    integrity = {
        "real_yield_first": str(real_yield.index.min()),
        "real_yield_last": str(real_yield.index.max()),
        "vix_first": str(vix.index.min()),
        "vix_last": str(vix.index.max()),
        "lag_trading_days": lag,
    }
    return f, integrity


def adaptive_states(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    a = cfg["relationship_model"]
    warm = int(a["initial_warmup_trading_days"])
    lam = float(a["forgetting_factor"])
    y = np.log(d["gold_close"].to_numpy(float))
    x = np.log(d["silver_close"].to_numpy(float))
    out = pd.DataFrame(index=d.index, columns=["alpha", "beta", "innovation", "innovation_sd", "z"], dtype=float)
    X0 = np.column_stack([np.ones(warm), x[:warm]])
    y0 = y[:warm]
    theta, *_ = np.linalg.lstsq(X0, y0, rcond=None)
    resid0 = y0 - X0 @ theta
    var = float(np.var(resid0, ddof=0))
    if not np.isfinite(var) or var <= 0:
        raise ValueError("invalid warmup innovation variance")
    gram = (X0.T @ X0) / float(warm)
    P = np.linalg.inv(gram + 1e-8 * np.eye(2))
    min_sd = float(a["minimum_innovation_std"])
    for i in range(warm, len(d)):
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
    a = cfg["relationship_model"]
    vals = [s.get("alpha"), s.get("beta"), s.get("innovation"), s.get("innovation_sd"), s.get("z")]
    if not all(np.isfinite(float(v)) for v in vals):
        return False
    return bool(float(s["beta"]) > float(a["beta_gt"]) and float(s["beta"]) < float(a["beta_lt"]))


def hypothesis_id(side: str, feature: str) -> str:
    return f"{side}__{feature}"


def evaluate_hypothesis(events: pd.DataFrame, side: str, feature: str, cfg: dict) -> dict:
    g = events[events["side"] == side].copy()
    hid = hypothesis_id(side, feature)
    if g.empty:
        return {"hypothesis_id": hid, "side": side, "feature": feature, "events": 0, "state_folds": 0}
    align = 1.0 if side == "long_spread" else -1.0
    g["predictor"] = align * g[feature]
    g = g[np.isfinite(g["predictor"]) & np.isfinite(g["target"])].copy()
    min_events = int(cfg["state_first"]["minimum_events_per_state_fold"])
    fold_rows = []
    for fid, f in g.groupby("fold"):
        if len(f) < min_events:
            continue
        r = rho(f["predictor"], f["target"])
        if not np.isfinite(r):
            continue
        fold_rows.append({
            "fold": int(fid),
            "events": int(len(f)),
            "rho": float(r),
            "median_target": float(f["target"].median()),
            "mean_target": float(f["target"].mean()),
        })
    rhos = [x["rho"] for x in fold_rows]
    med_targets = [x["median_target"] for x in fold_rows]
    return {
        "hypothesis_id": hid,
        "side": side,
        "feature": feature,
        "events": int(len(g)),
        "state_folds": int(len(fold_rows)),
        "folds": fold_rows,
        "median_fold_spearman": float(np.median(rhos)) if rhos else np.nan,
        "positive_spearman_fold_fraction": float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
        "median_fold_target": float(np.median(med_targets)) if med_targets else np.nan,
        "positive_target_fold_fraction": float(np.mean(np.asarray(med_targets) > 0)) if med_targets else 0.0,
        "sign_flip_p": sign_flip_pvalue(
            rhos,
            int(cfg["state_first"]["sign_flip_epochs"]),
            stable_seed(int(cfg["state_first"]["sign_flip_seed"]), hid),
        ),
        "reversed_feature_median_fold_spearman": float(-np.median(rhos)) if rhos else np.nan,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--silver", required=True)
    ap.add_argument("--real-yield", required=True)
    ap.add_argument("--vix", required=True)
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

    real_yield = load_fred(Path(args.real_yield), "DFII10")
    vix = load_fred(Path(args.vix), "VIXCLS")
    features, macro_integrity = build_macro_features(d.index, real_yield, vix, cfg)
    coverage = float(features.notna().all(axis=1).mean())
    if coverage < float(cfg["data_admission"]["minimum_macro_coverage_fraction"]):
        raise SystemExit(f"macro feature coverage {coverage:.4f} below frozen minimum")

    states = adaptive_states(d, cfg)
    lg = np.log(d["gold_close"].to_numpy(float))
    ls = np.log(d["silver_close"].to_numpy(float))
    h = int(cfg["state_target"]["horizon_trading_bars"])
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    entry_z = float(cfg["relationship_model"]["entry_abs_innovation_z_gte"])

    rows = []
    for i in range(len(d) - h):
        s = states.iloc[i]
        if not state_admitted(s, cfg) or abs(float(s["z"])) < entry_z:
            continue
        j = i + h
        if fold[j] != fold[i]:
            continue
        side = "long_spread" if float(s["z"]) < 0 else "short_spread"
        frozen_future_resid = float(lg[j] - float(s["alpha"]) - float(s["beta"]) * ls[j])
        current_resid = float(s["innovation"])
        sd = float(s["innovation_sd"])
        target = ((frozen_future_resid - current_resid) / sd) if side == "long_spread" else ((current_resid - frozen_future_resid) / sd)
        row = {"timestamp": str(d.index[i]), "fold": int(fold[i]), "side": side, "entry_z": float(s["z"]), "target": float(target)}
        for col in features.columns:
            row[col] = float(features[col].iloc[i]) if np.isfinite(features[col].iloc[i]) else np.nan
        rows.append(row)
    events = pd.DataFrame(rows)

    feature_names = [x["name"] for x in cfg["macro_features"]["features"]]
    hypotheses = [evaluate_hypothesis(events, str(side), feature, cfg) for side in cfg["state_first"]["sides"] for feature in feature_names]
    if len(hypotheses) != int(cfg["state_first"]["unique_hypotheses"]):
        raise AssertionError("hypothesis count differs from frozen protocol")

    qvals = bh_qvalues([h.get("sign_flip_p", np.nan) for h in hypotheses])
    sf = cfg["state_first"]
    for item, q in zip(hypotheses, qvals):
        item["bh_fdr_q"] = q
        item["state_pass"] = bool(
            item.get("state_folds", 0) >= int(sf["minimum_scorable_state_folds"])
            and item.get("median_fold_spearman", -np.inf) > float(sf["minimum_median_fold_spearman"])
            and item.get("positive_spearman_fold_fraction", 0.0) >= float(sf["minimum_positive_state_fold_fraction"])
            and item.get("bh_fdr_q", 1.0) <= float(sf["maximum_bh_fdr_q"])
            and (not bool(sf["require_positive_median_fold_target"]) or item.get("median_fold_target", -np.inf) > 0)
        )

    baseline = {}
    if not events.empty:
        for side, g in events.groupby("side"):
            fold_targets = g.groupby("fold")["target"].median()
            baseline[str(side)] = {
                "events": int(len(g)),
                "folds": int(len(fold_targets)),
                "median_fold_target": float(fold_targets.median()),
                "positive_target_fold_fraction": float((fold_targets > 0).mean()),
            }

    passed = [x for x in hypotheses if x.get("state_pass")]
    passed.sort(key=lambda x: (
        float(x.get("bh_fdr_q", 1.0)),
        -float(x.get("median_fold_spearman", -np.inf)),
        -float(x.get("positive_spearman_fold_fraction", 0.0)),
        -float(x.get("median_fold_target", -np.inf)),
        x["hypothesis_id"],
    ))
    selected = passed[: int(sf["maximum_state_conditioners_to_freeze"])]

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "development_period": dev,
        "data_integrity": {
            "common_price_rows_all_source": int(len(common)),
            "development_price_rows": int(len(d)),
            "development_first_bar": str(d.index.min()),
            "development_last_bar": str(d.index.max()),
            "macro_complete_feature_coverage_fraction": coverage,
            **macro_integrity,
        },
        "relationship_model": cfg["relationship_model"],
        "event_count": int(len(events)),
        "side_baseline": baseline,
        "grid": {"hypotheses": int(len(hypotheses)), "state_passes": int(sum(bool(x.get("state_pass")) for x in hypotheses))},
        "selected_state_conditioners_for_separate_freeze": [x["hypothesis_id"] for x in selected],
        "conditioned_pnl_tested": False,
        "locked_internal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
        "hypotheses": hypotheses,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean({
        "events": payload["event_count"],
        "hypotheses": payload["grid"]["hypotheses"],
        "state_passes": payload["grid"]["state_passes"],
        "selected": payload["selected_state_conditioners_for_separate_freeze"],
        "conditioned_pnl_tested": payload["conditioned_pnl_tested"],
        "locked_internal_validation_opened": payload["locked_internal_validation_opened"],
    }), indent=2))


if __name__ == "__main__":
    main()
