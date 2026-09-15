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
    if isinstance(v, (np.integer,)):
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


def load_cash(path: Path, prefix: str) -> pd.DataFrame:
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
    d = d[d["tick_volume"] >= 2]
    d = d[d["time"].dt.weekday <= 4]
    d = d.drop_duplicates("time", keep="last").set_index("time").sort_index()
    return d[["open", "high", "low", "close", "tick_volume"]].add_prefix(prefix + "_")


def load_fred(path: Path, series: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip() for c in d.columns]
    date_col = None
    for c in d.columns:
        if c.upper() in {"DATE", "OBSERVATION_DATE"}:
            date_col = c
            break
    if date_col is None:
        date_col = d.columns[0]
    value_col = series if series in d.columns else next((c for c in d.columns if c != date_col), None)
    if value_col is None:
        raise ValueError(f"{path}: cannot identify value column")
    out = pd.DataFrame({
        "time": pd.to_datetime(d[date_col], utc=True, errors="coerce").dt.floor("D"),
        series: pd.to_numeric(d[value_col].replace(".", np.nan), errors="coerce"),
    }).dropna()
    out = out.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)
    return out


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
    gram = (X0.T @ X0) / float(warm)
    P = np.linalg.inv(gram + 1e-8 * np.eye(2)) * float(a["initial_covariance_scale"])
    min_sd = float(a["minimum_innovation_std"])
    for i in range(warm, n):
        xt = np.array([1.0, x[i]], dtype=float)
        innov = float(y[i] - xt @ theta)
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
    return bool(float(s["beta"]) > float(a["beta_gt"]) and float(s["beta"]) < float(a["beta_lt"]))


def make_macro_features(real_yield: pd.DataFrame, usd: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    ry = real_yield.copy()
    ux = usd.copy()
    ryn = int(cfg["macro_features"]["real_yield_change_trading_bars"])
    usdn = int(cfg["macro_features"]["broad_usd_log_return_trading_bars"])
    ry["real_yield_63d_change"] = ry["DFII10"].diff(ryn)
    ux["broad_usd_63d_log_return"] = np.log(ux["DTWEXBGS"]).diff(usdn)
    return ry[["time", "real_yield_63d_change"]].dropna(), ux[["time", "broad_usd_63d_log_return"]].dropna()


def attach_asof(events: pd.DataFrame, feature_frame: pd.DataFrame, feature_col: str) -> pd.DataFrame:
    left = events.sort_values("time").copy()
    right = feature_frame.sort_values("time").copy()
    right = right.rename(columns={"time": feature_col + "_obs_time"})
    merged = pd.merge_asof(
        left,
        right,
        left_on="time",
        right_on=feature_col + "_obs_time",
        direction="backward",
        allow_exact_matches=False,
        tolerance=pd.Timedelta(days=5),
    )
    return merged


def build_events(d: pd.DataFrame, states: pd.DataFrame, cfg: dict, ry: pd.DataFrame, usd: pd.DataFrame) -> pd.DataFrame:
    a = cfg["base_relative_state"]
    h = int(a["state_horizon_trading_bars"])
    threshold = float(a["event_abs_innovation_z_gte"])
    lg = np.log(d["gold_close"].to_numpy(float))
    ls = np.log(d["silver_close"].to_numpy(float))
    rows = []
    for i in range(len(d) - h):
        s = states.iloc[i]
        if not admitted_state(s, cfg) or abs(float(s["z"])) < threshold:
            continue
        j = i + h
        future_resid = float(lg[j] - float(s["alpha"]) - float(s["beta"]) * ls[j])
        target = float(-np.sign(float(s["z"])) * (future_resid - float(s["innovation"])) / float(s["innovation_sd"]))
        rows.append({
            "time": d.index[i],
            "target_complete_time": d.index[j],
            "target": target,
            "abs_innovation_z": abs(float(s["z"])),
            "innovation_sign": float(np.sign(float(s["z"]))),
            "entry_beta": float(s["beta"]),
        })
    e = pd.DataFrame(rows)
    if e.empty:
        return e
    e = attach_asof(e, ry, "real_yield_63d_change")
    e = attach_asof(e, usd, "broad_usd_63d_log_return")
    e = e.dropna(subset=["real_yield_63d_change", "broad_usd_63d_log_return"]).copy()
    e["innovation_sign_x_real_yield_change"] = e["innovation_sign"] * e["real_yield_63d_change"]
    e["innovation_sign_x_broad_usd_return"] = e["innovation_sign"] * e["broad_usd_63d_log_return"]
    return e.sort_values("time").reset_index(drop=True)


def ridge_predict(train: pd.DataFrame, row: pd.Series, features: list[str], ycol: str, alpha: float) -> float:
    X = train[features].to_numpy(float)
    y = train[ycol].to_numpy(float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0)
    sd = np.where(np.isfinite(sd) & (sd > 1e-12), sd, 1.0)
    Xs = (X - mu) / sd
    xs = (row[features].to_numpy(float) - mu) / sd
    A = np.column_stack([np.ones(len(Xs)), Xs])
    R = np.eye(A.shape[1]) * alpha
    R[0, 0] = 0.0
    coef = np.linalg.solve(A.T @ A + R, A.T @ y)
    return float(np.r_[1.0, xs] @ coef)


def walk_forward_predictions(events: pd.DataFrame, cfg: dict, macro_override: np.ndarray | None = None) -> pd.DataFrame:
    wf = cfg["walk_forward_model"]
    baseline_features = list(wf["baseline_features"])
    macro_features = list(wf["macro_model_features"])
    alpha = float(wf["ridge_alpha"])
    minimum = int(wf["minimum_completed_training_events"])
    e = events.copy()
    macro_only = [x for x in macro_features if x not in baseline_features]
    if macro_override is not None:
        if macro_override.shape != (len(e), len(macro_only)):
            raise ValueError("macro_override shape mismatch")
        e.loc[:, macro_only] = macro_override
    rows = []
    for i, row in e.iterrows():
        eligible = e[(e["target_complete_time"] < row["time"])].copy()
        if len(eligible) < minimum:
            continue
        bp = ridge_predict(eligible, row, baseline_features, "target", alpha)
        mp = ridge_predict(eligible, row, macro_features, "target", alpha)
        rows.append({
            "event_index": int(i),
            "time": row["time"],
            "target": float(row["target"]),
            "innovation_sign": float(row["innovation_sign"]),
            "baseline_prediction": bp,
            "macro_prediction": mp,
            "training_events": int(len(eligible)),
        })
    return pd.DataFrame(rows)


def fold_metrics(scored: pd.DataFrame, start_ts: pd.Timestamp, cfg: dict) -> dict:
    ev = cfg["evaluation"]
    cluster_days = int(ev["dependence_cluster_calendar_days"])
    minimum = int(ev["minimum_events_per_fold"])
    s = scored.copy()
    s["fold"] = np.floor((s["time"] - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    rows = []
    for fid, g in s.groupby("fold"):
        if len(g) < minimum:
            continue
        br = rho(g["baseline_prediction"], g["target"])
        mr = rho(g["macro_prediction"], g["target"])
        if np.isfinite(br) and np.isfinite(mr):
            rows.append({"fold": int(fid), "events": int(len(g)), "baseline_rho": br, "macro_rho": mr, "incremental_rho": mr - br})
    r = pd.DataFrame(rows)
    if r.empty:
        return {"fold_rows": []}
    return {
        "fold_rows": rows,
        "scorable_folds": int(len(r)),
        "baseline_median_fold_rho": float(r["baseline_rho"].median()),
        "macro_median_fold_rho": float(r["macro_rho"].median()),
        "macro_positive_fold_fraction": float((r["macro_rho"] > 0).mean()),
        "median_incremental_rho": float(r["incremental_rho"].median()),
        "positive_incremental_fold_fraction": float((r["incremental_rho"] > 0).mean()),
    }


def paired_sign_flip_p(deltas: list[float], epochs: int, seed: int) -> float:
    x = np.asarray(deltas, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float("nan")
    obs = float(np.median(x))
    if obs <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    count = 0
    done = 0
    ax = np.abs(x)
    while done < epochs:
        n = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(ax)))
        null = np.median(signs * ax[None, :], axis=1)
        count += int(np.sum(null >= obs))
        done += n
    return float((count + 1) / (epochs + 1))


def side_report(scored: pd.DataFrame) -> dict:
    out = {}
    for name, sign in [("positive_innovation", 1.0), ("negative_innovation", -1.0)]:
        g = scored[scored["innovation_sign"] == sign]
        out[name] = {
            "events": int(len(g)),
            "baseline_rho": rho(g["baseline_prediction"], g["target"]) if len(g) >= 5 else np.nan,
            "macro_rho": rho(g["macro_prediction"], g["target"]) if len(g) >= 5 else np.nan,
            "mean_target": float(g["target"].mean()) if len(g) else np.nan,
            "mean_macro_prediction": float(g["macro_prediction"].mean()) if len(g) else np.nan,
        }
    return out


def macro_permutation_p(events: pd.DataFrame, observed_scored: pd.DataFrame, observed_metric: float, start_ts: pd.Timestamp, cfg: dict) -> tuple[float, dict]:
    ev = cfg["evaluation"]
    epochs = int(ev["macro_permutation_epochs"])
    seed = int(ev["macro_permutation_seed"])
    rng = np.random.default_rng(seed)
    baseline_features = set(cfg["walk_forward_model"]["baseline_features"])
    macro_features = [x for x in cfg["walk_forward_model"]["macro_model_features"] if x not in baseline_features]
    base = events[macro_features].to_numpy(float)
    years = events["time"].dt.year.to_numpy()
    groups = [np.where(years == y)[0] for y in sorted(set(years))]
    count = 0
    vals = []
    for _ in range(epochs):
        perm = base.copy()
        for idx in groups:
            perm[idx] = base[rng.permutation(idx)]
        sc = walk_forward_predictions(events, cfg, macro_override=perm)
        fm = fold_metrics(sc, start_ts, cfg)
        m = fm.get("median_incremental_rho", np.nan)
        if np.isfinite(m):
            vals.append(float(m))
            if m >= observed_metric:
                count += 1
    n = len(vals)
    p = float((count + 1) / (n + 1)) if n else float("nan")
    diag = {
        "epochs_requested": epochs,
        "epochs_scored": n,
        "null_median_incremental_rho_median": float(np.median(vals)) if vals else np.nan,
        "null_median_incremental_rho_p95": float(np.quantile(vals, 0.95)) if vals else np.nan,
    }
    return p, diag


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--silver", required=True)
    ap.add_argument("--real-yield", required=True)
    ap.add_argument("--usd", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    gold = load_cash(Path(args.gold), "gold")
    silver = load_cash(Path(args.silver), "silver")
    common = gold.join(silver, how="inner").dropna().sort_index()
    dev = cfg["periods"]["development"]
    start_ts = pd.Timestamp(dev["start"], tz="UTC")
    end_ts = pd.Timestamp(dev["end_exclusive"], tz="UTC")
    d = common.loc[(common.index >= start_ts) & (common.index < end_ts)].copy()
    if len(d) < 500:
        raise SystemExit("insufficient development price rows")

    ry = load_fred(Path(args.real_yield), "DFII10")
    usd = load_fred(Path(args.usd), "DTWEXBGS")
    ryf, usdf = make_macro_features(ry, usd, cfg)
    states = adaptive_states(d, cfg)
    events = build_events(d, states, cfg, ryf, usdf)
    if len(events) < int(cfg["walk_forward_model"]["minimum_completed_training_events"]) + 20:
        raise SystemExit(f"insufficient admissible macro-state events: {len(events)}")

    scored = walk_forward_predictions(events, cfg)
    fm = fold_metrics(scored, start_ts, cfg)
    deltas = [x["incremental_rho"] for x in fm.get("fold_rows", [])]
    sign_p = paired_sign_flip_p(deltas, int(cfg["evaluation"]["paired_sign_flip_epochs"]), int(cfg["evaluation"]["paired_sign_flip_seed"]))
    observed_increment = float(fm.get("median_incremental_rho", np.nan))
    perm_p, perm_diag = macro_permutation_p(events, scored, observed_increment, start_ts, cfg)
    sides = side_report(scored)

    e = cfg["evaluation"]
    state_pass = bool(
        fm.get("scorable_folds", 0) >= int(e["minimum_scorable_folds"])
        and fm.get("macro_median_fold_rho", -np.inf) > float(e["minimum_macro_median_fold_rho"])
        and fm.get("macro_positive_fold_fraction", 0.0) >= float(e["minimum_macro_positive_fold_fraction"])
        and fm.get("median_incremental_rho", -np.inf) >= float(e["minimum_median_incremental_rho"])
        and fm.get("positive_incremental_fold_fraction", 0.0) >= float(e["minimum_positive_incremental_fold_fraction"])
        and sign_p <= float(e["maximum_incremental_sign_flip_p"])
        and perm_p <= float(e["maximum_macro_permutation_p"])
        and sides["positive_innovation"]["events"] >= 20
        and sides["negative_innovation"]["events"] >= 20
    )

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "development_period": dev,
        "data_integrity": {
            "price_rows": int(len(d)),
            "price_first": str(d.index.min()),
            "price_last": str(d.index.max()),
            "real_yield_rows_source": int(len(ry)),
            "usd_rows_source": int(len(usd)),
            "admissible_relative_state_events_with_macro": int(len(events)),
            "walk_forward_scored_events": int(len(scored)),
        },
        "state_result": {
            **fm,
            "paired_incremental_sign_flip_p": sign_p,
            "macro_permutation_p": perm_p,
            "macro_permutation_diagnostics": perm_diag,
            "side_report": sides,
            "state_pass": state_pass,
        },
        "economic_translation_evaluated": False,
        "locked_internal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "promotion": {
            "freeze_separate_v4_1_economic_protocol": bool(state_pass),
            "open_locked_validation": False,
        },
        "claims": cfg["claims"],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean({
        "events": len(events),
        "scored_events": len(scored),
        "scorable_folds": fm.get("scorable_folds"),
        "baseline_median_fold_rho": fm.get("baseline_median_fold_rho"),
        "macro_median_fold_rho": fm.get("macro_median_fold_rho"),
        "median_incremental_rho": fm.get("median_incremental_rho"),
        "positive_incremental_fold_fraction": fm.get("positive_incremental_fold_fraction"),
        "paired_sign_flip_p": sign_p,
        "macro_permutation_p": perm_p,
        "state_pass": state_pass,
        "locked_internal_validation_opened": False,
    }), indent=2))


if __name__ == "__main__":
    main()
