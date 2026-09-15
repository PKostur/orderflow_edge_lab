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


def stable_seed(base_seed: int, cid: str) -> int:
    h = hashlib.sha256(cid.encode("utf-8")).digest()
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
        n = min(1000, epochs - done)
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


def build_hedges(d: pd.DataFrame, clip_low: float, clip_high: float) -> dict[str, pd.Series]:
    rg = np.log(d["gold_close"]).diff()
    rs = np.log(d["silver_close"]).diff()
    cov = rg.rolling(126, min_periods=126).cov(rs)
    var_s = rs.rolling(126, min_periods=126).var(ddof=1).replace(0, np.nan)
    beta = (cov / var_s).clip(lower=clip_low, upper=clip_high)
    vg = rg.rolling(63, min_periods=63).std(ddof=1)
    vs = rs.rolling(63, min_periods=63).std(ddof=1).replace(0, np.nan)
    vol_ratio = (vg / vs).clip(lower=clip_low, upper=clip_high)
    return {"rolling_return_beta_126": beta, "rolling_vol_ratio_63": vol_ratio}


def candidate_id(mode: str, hedge: str, window: int, threshold: float, hold: int) -> str:
    ztxt = str(threshold).replace(".", "p")
    return f"{mode}__{hedge}__zwin{window}__z{ztxt}__hold{hold}"


def evaluate_cell(d, start_ts, cfg, mode, hedge_name, hedge, window, threshold, hold) -> dict:
    cid = candidate_id(mode, hedge_name, window, threshold, hold)
    ratio = d["gold_close"] / d["silver_close"]
    mu = ratio.rolling(window, min_periods=window).mean()
    sd = ratio.rolling(window, min_periods=window).std(ddof=0).replace(0, np.nan)
    z = (ratio - mu) / sd
    predictor = z if mode == "momentum" else -z

    gold_entry = d["gold_open"].shift(-1)
    silver_entry = d["silver_open"].shift(-1)
    gold_exit = d["gold_open"].shift(-(1 + hold))
    silver_exit = d["silver_open"].shift(-(1 + hold))
    gret = gold_exit / gold_entry - 1.0
    sret = silver_exit / silver_entry - 1.0
    wg = 1.0 / (1.0 + hedge)
    ws = hedge / (1.0 + hedge)
    spread_ret = wg * gret - ws * sret
    static_ret = 0.5 * gret - 0.5 * sret

    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    pos = np.arange(len(d))
    exit_pos = pos + 1 + hold
    safe_exit = np.minimum(exit_pos, len(d) - 1)

    valid = z.abs().to_numpy(float) >= threshold
    for s in (z, predictor, hedge, gret, sret, spread_ret):
        valid &= np.isfinite(s.to_numpy(float))
    valid &= exit_pos < len(d)
    valid &= fold[safe_exit] == fold
    ids = np.where(valid)[0]

    min_events = int(cfg["state_first"]["minimum_events_per_state_fold"])
    state_rows = []
    for fid in np.unique(fold[ids]):
        ii = ids[fold[ids] == fid]
        if len(ii) < min_events:
            continue
        r = rho(predictor.iloc[ii].to_numpy(float), spread_ret.iloc[ii].to_numpy(float))
        if np.isfinite(r):
            state_rows.append({"fold": int(fid), "rho": float(r), "events": int(len(ii))})
    rhos = [x["rho"] for x in state_rows]
    p = sign_flip_pvalue(
        rhos,
        int(cfg["state_first"]["sign_flip_epochs"]),
        stable_seed(int(cfg["state_first"]["sign_flip_seed"]), cid),
    )

    chosen = []
    next_allowed = -1
    for i in ids:
        if i < next_allowed:
            continue
        chosen.append(int(i))
        next_allowed = int(i + 1 + hold)

    rows = []
    for i in chosen:
        direction = int(np.sign(float(predictor.iloc[i])))
        if direction == 0:
            continue
        spread_bps = float(spread_ret.iloc[i] * 10000.0)
        gold_bps = float(gret.iloc[i] * 10000.0)
        static_bps = float(static_ret.iloc[i] * 10000.0)
        rows.append({
            "timestamp": str(d.index[i]),
            "fold": int(fold[i]),
            "side": direction,
            "z": float(z.iloc[i]),
            "hedge_ratio": float(hedge.iloc[i]),
            "gross_bps": float(direction * spread_bps),
            "unhedged_gold_gross_bps": float(direction * gold_bps),
            "static_equal_dollar_spread_gross_bps": float(direction * static_bps),
        })
    tr = pd.DataFrame(rows)

    out = {
        "candidate_id": cid,
        "mode": mode,
        "hedge_method": hedge_name,
        "z_window": int(window),
        "z_threshold": float(threshold),
        "hold": int(hold),
        "state_events": int(len(ids)),
        "state_folds": int(len(state_rows)),
        "state_fold_rhos": state_rows,
        "state_median_spearman": float(np.median(rhos)) if rhos else np.nan,
        "state_positive_fold_fraction": float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
        "state_sign_flip_p": p,
        "trades": int(len(tr)),
    }
    if tr.empty:
        return out

    costs = [float(x) for x in cfg["execution"]["round_trip_cost_bps_on_total_gross_notional"]]
    primary = float(cfg["execution"]["primary_cost_bps"])
    for cost in costs:
        key = f"{cost:g}"
        net_col = f"net_{key}"
        tr[net_col] = tr["gross_bps"] - cost
        fold_net = tr.groupby("fold")[net_col].mean()
        fold_pf = tr.groupby("fold")[net_col].apply(pf)
        out[f"net_{key}_median_fold_bps"] = float(fold_net.median())
        out[f"pf_{key}_median_fold"] = float(fold_pf.median())
        out[f"positive_fold_fraction_{key}"] = float((fold_net > 0).mean())
        out[f"mean_net_{key}_bps"] = float(tr[net_col].mean())

    pkey = f"{primary:g}"
    pcol = f"net_{pkey}"
    tr["unhedged_gold_net_primary"] = tr["unhedged_gold_gross_bps"] - primary
    tr["static_spread_net_primary"] = tr["static_equal_dollar_spread_gross_bps"] - primary
    out["reversed_mean_net_primary_bps"] = float((-tr["gross_bps"] - primary).mean())
    out["strategy_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, pcol)
    out["unhedged_gold_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, "unhedged_gold_net_primary")
    out["static_spread_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, "static_spread_net_primary")
    if len(tr) >= 3 and np.std(tr["gross_bps"]) > 0 and np.std(tr["unhedged_gold_gross_bps"]) > 0:
        out["trade_return_corr_with_unhedged_gold"] = float(
            np.corrcoef(tr["gross_bps"], tr["unhedged_gold_gross_bps"])[0, 1]
        )
    else:
        out["trade_return_corr_with_unhedged_gold"] = np.nan
    out["long_spread"] = directional_stats(tr, pcol, 1)
    out["short_spread"] = directional_stats(tr, pcol, -1)
    out["trade_rows"] = rows
    return out


def supporter(a: dict, b: dict, cfg: dict) -> bool:
    if a["mode"] != b["mode"] or a["hedge_method"] != b["hedge_method"]:
        return False
    grids = cfg["signal_grid"]
    params = [
        ("z_window", list(grids["rolling_z_windows_trading_days"])),
        ("z_threshold", list(grids["activation_abs_z_gte"])),
        ("hold", list(grids["hold_trading_bars"])),
    ]
    diffs = 0
    for key, vals in params:
        if a[key] == b[key]:
            continue
        try:
            ia = vals.index(a[key])
            ib = vals.index(b[key])
        except ValueError:
            return False
        if abs(ia - ib) != 1:
            return False
        diffs += 1
    if diffs != 1:
        return False
    req = cfg["neighborhood_gate"]["supporter_requires"]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['execution']['high_cost_bps']):g}"
    return bool(
        b.get("state_bh_q", 1.0) <= float(req["state_bh_q_lte"])
        and b.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(req["primary_median_fold_net_bps_gt"])
        and b.get(f"pf_{pkey}_median_fold", 0.0) > float(req["primary_median_fold_pf_gt"])
        and b.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(req["high_cost_median_fold_net_bps_gte"])
    )


def apply_gates(cells: list[dict], cfg: dict) -> None:
    qvals = bh_qvalues([c.get("state_sign_flip_p", np.nan) for c in cells])
    for c, q in zip(cells, qvals):
        c["state_bh_q"] = q

    s = cfg["state_first"]
    e = cfg["economic_gate"]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['execution']['high_cost_bps']):g}"
    for c in cells:
        state_pass = bool(
            c.get("state_folds", 0) >= int(s["minimum_scorable_state_folds"])
            and c.get("state_median_spearman", -np.inf) > float(s["minimum_median_fold_spearman"])
            and c.get("state_positive_fold_fraction", 0.0) >= float(s["minimum_positive_state_fold_fraction"])
            and c.get("state_bh_q", 1.0) <= float(s["maximum_bh_fdr_q"])
        )
        c["state_pass"] = state_pass
        econ_pass = bool(
            c.get("trades", 0) >= int(e["minimum_non_overlapping_trades"])
            and c.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(e["minimum_primary_median_fold_net_bps"])
            and c.get(f"pf_{pkey}_median_fold", 0.0) >= float(e["minimum_primary_median_fold_pf"])
            and c.get(f"positive_fold_fraction_{pkey}", 0.0) >= float(e["minimum_primary_positive_fold_fraction"])
            and c.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(e["minimum_high_cost_median_fold_net_bps"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > c.get("reversed_mean_net_primary_bps", np.inf)
            and np.isfinite(c.get("strategy_median_fold_risk_adjusted_primary", np.nan))
            and np.isfinite(c.get("unhedged_gold_median_fold_risk_adjusted_primary", np.nan))
            and c.get("strategy_median_fold_risk_adjusted_primary", -np.inf)
            > c.get("unhedged_gold_median_fold_risk_adjusted_primary", np.inf)
            and c.get("long_spread", {}).get("trades", 0) >= int(e["minimum_long_spread_trades"])
            and c.get("short_spread", {}).get("trades", 0) >= int(e["minimum_short_spread_trades"])
            and c.get("long_spread", {}).get("mean_net_bps", -np.inf) > 0
            and c.get("short_spread", {}).get("mean_net_bps", -np.inf) > 0
        )
        c["economic_pass_before_neighborhood"] = econ_pass
        c["pre_neighborhood_pass"] = bool(state_pass and econ_pass)

    for a in cells:
        neigh = [b["candidate_id"] for b in cells if b is not a and supporter(a, b, cfg)]
        a["supporting_neighbors"] = sorted(neigh)
        a["neighborhood_support_count"] = len(neigh)
        a["full_development_pass"] = bool(
            a["pre_neighborhood_pass"]
            and len(neigh) >= int(cfg["neighborhood_gate"]["minimum_supporting_neighbors"])
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--silver", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    min_tv = int(cfg["data_admission"]["minimum_tick_volume_each_leg"])
    gold = load_cash(Path(args.gold), "gold", min_tv)
    silver = load_cash(Path(args.silver), "silver", min_tv)
    common = gold.join(silver, how="inner").dropna().sort_index()

    dev_cfg = cfg["periods"]["development"]
    start_ts = pd.Timestamp(dev_cfg["start"], tz="UTC")
    end_ts = pd.Timestamp(dev_cfg["end_exclusive"], tz="UTC")
    d = common.loc[(common.index >= start_ts) & (common.index < end_ts)].copy()
    if len(d) < 500:
        raise SystemExit("insufficient development rows")

    clip_low, clip_high = map(float, cfg["hedge_grid"]["hedge_ratio_clip"])
    hedges = build_hedges(d, clip_low, clip_high)
    cells = []
    sg = cfg["signal_grid"]
    for mode in sg["modes"]:
        for hedge_name in [x["name"] for x in cfg["hedge_grid"]["methods"]]:
            h = hedges[hedge_name]
            for window in sg["rolling_z_windows_trading_days"]:
                for threshold in sg["activation_abs_z_gte"]:
                    for hold in sg["hold_trading_bars"]:
                        cells.append(
                            evaluate_cell(
                                d,
                                start_ts,
                                cfg,
                                str(mode),
                                hedge_name,
                                h,
                                int(window),
                                float(threshold),
                                int(hold),
                            )
                        )

    apply_gates(cells, cfg)
    passed = [c for c in cells if c.get("full_development_pass")]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    passed.sort(
        key=lambda c: (
            -float(c.get("state_median_spearman", -np.inf)),
            -float(c.get(f"positive_fold_fraction_{pkey}", -np.inf)),
            -float(c.get(f"net_{pkey}_median_fold_bps", -np.inf)),
            c["candidate_id"],
        )
    )
    selected = passed[: int(cfg["candidate_selection"]["maximum_candidates"])]

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "source": cfg["source"],
        "development_period": dev_cfg,
        "data_integrity": {
            "gold_admitted_rows_all_source": int(len(gold)),
            "silver_admitted_rows_all_source": int(len(silver)),
            "common_rows_all_source": int(len(common)),
            "development_rows": int(len(d)),
            "development_first_bar": str(d.index.min()),
            "development_last_bar": str(d.index.max()),
        },
        "grid": {
            "cells_evaluated": int(len(cells)),
            "state_passes": int(sum(bool(c.get("state_pass")) for c in cells)),
            "economic_passes_before_neighborhood": int(
                sum(bool(c.get("economic_pass_before_neighborhood")) for c in cells)
            ),
            "pre_neighborhood_passes": int(sum(bool(c.get("pre_neighborhood_pass")) for c in cells)),
            "full_development_passes": int(len(passed)),
        },
        "selected_candidates_for_separate_freeze": [c["candidate_id"] for c in selected],
        "locked_internal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
        "cells": cells,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(
        json.dumps(
            clean(
                {
                    "cells": payload["grid"]["cells_evaluated"],
                    "state_passes": payload["grid"]["state_passes"],
                    "economic_passes_before_neighborhood": payload["grid"]["economic_passes_before_neighborhood"],
                    "full_development_passes": payload["grid"]["full_development_passes"],
                    "selected_candidates_for_separate_freeze": payload["selected_candidates_for_separate_freeze"],
                    "locked_internal_validation_opened": payload["locked_internal_validation_opened"],
                }
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
