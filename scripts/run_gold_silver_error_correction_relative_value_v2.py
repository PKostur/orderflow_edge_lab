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


def relationship_states(d: pd.DataFrame, lookback: int, cfg: dict) -> pd.DataFrame:
    lg = np.log(d["gold_close"].to_numpy(float))
    ls = np.log(d["silver_close"].to_numpy(float))
    n = len(d)
    out = pd.DataFrame(index=d.index, columns=["alpha", "beta", "resid", "resid_sd", "z", "phi", "half_life"], dtype=float)
    adm = cfg["relationship_admission"]
    for i in range(lookback - 1, n):
        y = lg[i - lookback + 1 : i + 1]
        x = ls[i - lookback + 1 : i + 1]
        xm = float(np.mean(x))
        ym = float(np.mean(y))
        vx = float(np.sum((x - xm) ** 2))
        if not np.isfinite(vx) or vx <= 0:
            continue
        beta = float(np.sum((x - xm) * (y - ym)) / vx)
        alpha = float(ym - beta * xm)
        r = y - alpha - beta * x
        sd = float(np.std(r, ddof=0))
        if not np.isfinite(sd) or sd <= float(adm["minimum_residual_std"]):
            continue
        r0 = r[:-1]
        r1 = r[1:]
        X = np.column_stack([np.ones(len(r0)), r0])
        try:
            coef, *_ = np.linalg.lstsq(X, r1, rcond=None)
            phi = float(coef[1])
        except np.linalg.LinAlgError:
            continue
        half = float(-math.log(2.0) / math.log(phi)) if 0.0 < phi < 1.0 else float("nan")
        current = float(r[-1])
        out.iloc[i] = [alpha, beta, current, sd, current / sd, phi, half]
    return out


def admitted_state(row: pd.Series, cfg: dict) -> bool:
    adm = cfg["relationship_admission"]
    vals = [row.get("alpha"), row.get("beta"), row.get("resid"), row.get("resid_sd"), row.get("z"), row.get("phi"), row.get("half_life")]
    if not all(np.isfinite(float(v)) for v in vals):
        return False
    return bool(
        float(row["beta"]) > float(adm["beta_gt"])
        and float(row["beta"]) < float(adm["beta_lt"])
        and float(row["phi"]) > float(adm["phi_gt"])
        and float(row["phi"]) < float(adm["phi_lt"])
        and float(row["half_life"]) >= float(adm["half_life_trading_days_gte"])
        and float(row["half_life"]) <= float(adm["half_life_trading_days_lte"])
    )


def state_hypothesis_id(lookback: int, entry_z: float) -> str:
    return f"lookback{lookback}__entryz{str(entry_z).replace('.', 'p')}"


def cell_id(lookback: int, entry_z: float, exit_z: float, max_hold: int) -> str:
    return (
        f"ecm_reversion__lookback{lookback}__entryz{str(entry_z).replace('.', 'p')}"
        f"__exitz{str(exit_z).replace('.', 'p')}__maxhold{max_hold}"
    )


def build_state_hypothesis(d: pd.DataFrame, states: pd.DataFrame, lookback: int, entry_z: float, start_ts: pd.Timestamp, cfg: dict) -> dict:
    h = int(cfg["state_first"]["horizon_trading_bars"])
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    rows = []
    lg = np.log(d["gold_close"].to_numpy(float))
    ls = np.log(d["silver_close"].to_numpy(float))
    for i in range(len(d) - h):
        s = states.iloc[i]
        if not admitted_state(s, cfg) or abs(float(s["z"])) < entry_z:
            continue
        j = i + h
        if fold[j] != fold[i]:
            continue
        alpha = float(s["alpha"])
        beta = float(s["beta"])
        sd = float(s["resid_sd"])
        future_resid = float(lg[j] - alpha - beta * ls[j])
        target = float(-np.sign(float(s["z"])) * (future_resid - float(s["resid"])) / sd)
        rows.append({"i": i, "fold": int(fold[i]), "predictor": abs(float(s["z"])), "target": target})
    f = pd.DataFrame(rows)
    state_rows = []
    min_events = int(cfg["state_first"]["minimum_events_per_state_fold"])
    if not f.empty:
        for fid, g in f.groupby("fold"):
            if len(g) < min_events:
                continue
            r = rho(g["predictor"], g["target"])
            if np.isfinite(r):
                state_rows.append({"fold": int(fid), "rho": float(r), "events": int(len(g))})
    rhos = [x["rho"] for x in state_rows]
    hid = state_hypothesis_id(lookback, entry_z)
    p = sign_flip_pvalue(
        rhos,
        int(cfg["state_first"]["sign_flip_epochs"]),
        stable_seed(int(cfg["state_first"]["sign_flip_seed"]), hid),
    )
    return {
        "state_hypothesis_id": hid,
        "lookback": int(lookback),
        "entry_z": float(entry_z),
        "state_events": int(len(f)),
        "state_folds": int(len(state_rows)),
        "state_fold_rhos": state_rows,
        "state_median_spearman": float(np.median(rhos)) if rhos else np.nan,
        "state_positive_fold_fraction": float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
        "state_sign_flip_p": p,
    }


def choose_exit(d: pd.DataFrame, signal_i: int, s: pd.Series, exit_z: float, max_hold: int, min_hold: int) -> tuple[int, str] | None:
    alpha = float(s["alpha"])
    beta = float(s["beta"])
    sd = float(s["resid_sd"])
    lg = np.log(d["gold_close"].to_numpy(float))
    ls = np.log(d["silver_close"].to_numpy(float))
    entry_pos = signal_i + 1
    max_exit_pos = entry_pos + max_hold
    if max_exit_pos >= len(d):
        return None
    first_check_close = signal_i + min_hold
    last_check_close = max_exit_pos - 1
    for j in range(first_check_close, last_check_close + 1):
        rz = float((lg[j] - alpha - beta * ls[j]) / sd)
        if np.isfinite(rz) and abs(rz) <= exit_z:
            return j + 1, "convergence"
    return max_exit_pos, "max_hold"


def simulate_cell(d: pd.DataFrame, states: pd.DataFrame, lookback: int, entry_z: float, exit_z: float, max_hold: int, start_ts: pd.Timestamp, cfg: dict) -> dict:
    cid = cell_id(lookback, entry_z, exit_z, max_hold)
    cluster_days = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    fold = np.floor((d.index - start_ts) / pd.Timedelta(days=cluster_days)).astype(int)
    min_hold = int(cfg["residual_grid"]["minimum_hold_trading_bars"])
    rows = []
    i = 0
    while i < len(d) - 2:
        s = states.iloc[i]
        if not admitted_state(s, cfg) or abs(float(s["z"])) < entry_z:
            i += 1
            continue
        ex = choose_exit(d, i, s, exit_z, max_hold, min_hold)
        if ex is None:
            break
        exit_pos, exit_reason = ex
        entry_pos = i + 1
        if fold[exit_pos] != fold[i]:
            i += 1
            continue
        beta = abs(float(s["beta"]))
        wg = 1.0 / (1.0 + beta)
        ws = beta / (1.0 + beta)
        side = int(-np.sign(float(s["z"])))
        if side == 0:
            i += 1
            continue
        ge = float(d["gold_open"].iloc[entry_pos])
        gx = float(d["gold_open"].iloc[exit_pos])
        se = float(d["silver_open"].iloc[entry_pos])
        sx = float(d["silver_open"].iloc[exit_pos])
        gret = gx / ge - 1.0
        sret = sx / se - 1.0
        spread = wg * gret - ws * sret
        static = 0.5 * gret - 0.5 * sret
        forced_exit = entry_pos + max_hold
        fgret = float(d["gold_open"].iloc[forced_exit] / ge - 1.0)
        fsret = float(d["silver_open"].iloc[forced_exit] / se - 1.0)
        forced = wg * fgret - ws * fsret
        rows.append({
            "signal_time": str(d.index[i]),
            "entry_time": str(d.index[entry_pos]),
            "exit_time": str(d.index[exit_pos]),
            "fold": int(fold[i]),
            "side": side,
            "entry_z": float(s["z"]),
            "entry_beta": float(s["beta"]),
            "entry_phi": float(s["phi"]),
            "entry_half_life": float(s["half_life"]),
            "holding_bars": int(exit_pos - entry_pos),
            "exit_reason": exit_reason,
            "gross_bps": float(side * spread * 10000.0),
            "unhedged_gold_gross_bps": float(side * gret * 10000.0),
            "static_spread_gross_bps": float(side * static * 10000.0),
            "forced_max_hold_gross_bps": float(side * forced * 10000.0),
        })
        i = exit_pos
    tr = pd.DataFrame(rows)
    out = {
        "candidate_id": cid,
        "state_hypothesis_id": state_hypothesis_id(lookback, entry_z),
        "lookback": int(lookback),
        "entry_z": float(entry_z),
        "exit_z": float(exit_z),
        "max_hold": int(max_hold),
        "trades": int(len(tr)),
    }
    if tr.empty:
        return out
    costs = [float(x) for x in cfg["execution"]["round_trip_cost_bps_on_total_gross_notional"]]
    primary = float(cfg["execution"]["primary_cost_bps"])
    for cost in costs:
        key = f"{cost:g}"
        col = f"net_{key}"
        tr[col] = tr["gross_bps"] - cost
        fold_net = tr.groupby("fold")[col].mean()
        fold_pf = tr.groupby("fold")[col].apply(pf)
        out[f"net_{key}_median_fold_bps"] = float(fold_net.median())
        out[f"pf_{key}_median_fold"] = float(fold_pf.median())
        out[f"positive_fold_fraction_{key}"] = float((fold_net > 0).mean())
        out[f"mean_net_{key}_bps"] = float(tr[col].mean())
    pkey = f"{primary:g}"
    pcol = f"net_{pkey}"
    tr["unhedged_gold_net_primary"] = tr["unhedged_gold_gross_bps"] - primary
    tr["static_spread_net_primary"] = tr["static_spread_gross_bps"] - primary
    tr["forced_max_hold_net_primary"] = tr["forced_max_hold_gross_bps"] - primary
    out["reversed_mean_net_primary_bps"] = float((-tr["gross_bps"] - primary).mean())
    out["strategy_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, pcol)
    out["unhedged_gold_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, "unhedged_gold_net_primary")
    out["static_spread_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, "static_spread_net_primary")
    out["forced_max_hold_median_fold_risk_adjusted_primary"] = median_fold_risk_adjusted(tr, "forced_max_hold_net_primary")
    out["long_spread"] = directional_stats(tr, pcol, 1)
    out["short_spread"] = directional_stats(tr, pcol, -1)
    out["median_holding_bars"] = float(tr["holding_bars"].median())
    out["mean_holding_bars"] = float(tr["holding_bars"].mean())
    out["convergence_exit_fraction"] = float((tr["exit_reason"] == "convergence").mean())
    out["median_entry_beta"] = float(tr["entry_beta"].median())
    out["median_entry_half_life"] = float(tr["entry_half_life"].median())
    if len(tr) >= 3 and np.std(tr["gross_bps"]) > 0 and np.std(tr["unhedged_gold_gross_bps"]) > 0:
        out["trade_return_corr_with_unhedged_gold"] = float(np.corrcoef(tr["gross_bps"], tr["unhedged_gold_gross_bps"])[0, 1])
    else:
        out["trade_return_corr_with_unhedged_gold"] = np.nan
    out["trade_rows"] = rows
    return out


def supporter(a: dict, b: dict, cfg: dict) -> bool:
    grids = cfg["residual_grid"]
    params = [
        ("lookback", list(grids["lookback_trading_days"])),
        ("entry_z", list(grids["entry_abs_z_gte"])),
        ("exit_z", list(grids["exit_abs_z_lte"])),
        ("max_hold", list(grids["max_hold_trading_bars"])),
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
        and b.get(f"mean_net_{pkey}_bps", -np.inf) > float(req["overall_mean_primary_net_bps_gt"])
        and b.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(req["high_cost_median_fold_net_bps_gte"])
    )


def apply_gates(cells: list[dict], hypotheses: list[dict], cfg: dict) -> None:
    qvals = bh_qvalues([h.get("state_sign_flip_p", np.nan) for h in hypotheses])
    hmap = {}
    s = cfg["state_first"]
    for h, q in zip(hypotheses, qvals):
        h["state_bh_q"] = q
        h["state_pass"] = bool(
            h.get("state_folds", 0) >= int(s["minimum_scorable_state_folds"])
            and h.get("state_median_spearman", -np.inf) > float(s["minimum_median_fold_spearman"])
            and h.get("state_positive_fold_fraction", 0.0) >= float(s["minimum_positive_state_fold_fraction"])
            and h.get("state_bh_q", 1.0) <= float(s["maximum_bh_fdr_q"])
        )
        hmap[h["state_hypothesis_id"]] = h

    e = cfg["economic_gate"]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    hkey = f"{float(cfg['execution']['high_cost_bps']):g}"
    for c in cells:
        h = hmap[c["state_hypothesis_id"]]
        for key in ["state_events", "state_folds", "state_median_spearman", "state_positive_fold_fraction", "state_sign_flip_p", "state_bh_q", "state_pass"]:
            c[key] = h.get(key)
        econ = bool(
            c.get("trades", 0) >= int(e["minimum_non_overlapping_trades"])
            and c.get(f"net_{pkey}_median_fold_bps", -np.inf) > float(e["minimum_primary_median_fold_net_bps"])
            and c.get(f"pf_{pkey}_median_fold", 0.0) >= float(e["minimum_primary_median_fold_pf"])
            and c.get(f"positive_fold_fraction_{pkey}", 0.0) >= float(e["minimum_primary_positive_fold_fraction"])
            and c.get(f"net_{hkey}_median_fold_bps", -np.inf) >= float(e["minimum_high_cost_median_fold_net_bps"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > float(e["minimum_overall_mean_primary_net_bps"])
            and c.get(f"mean_net_{pkey}_bps", -np.inf) > c.get("reversed_mean_net_primary_bps", np.inf)
            and np.isfinite(c.get("strategy_median_fold_risk_adjusted_primary", np.nan))
            and c.get("strategy_median_fold_risk_adjusted_primary", -np.inf) > c.get("unhedged_gold_median_fold_risk_adjusted_primary", np.inf)
            and c.get("strategy_median_fold_risk_adjusted_primary", -np.inf) > c.get("static_spread_median_fold_risk_adjusted_primary", np.inf)
            and c.get("long_spread", {}).get("trades", 0) >= int(e["minimum_long_spread_trades"])
            and c.get("short_spread", {}).get("trades", 0) >= int(e["minimum_short_spread_trades"])
            and c.get("long_spread", {}).get("mean_net_bps", -np.inf) > 0
            and c.get("short_spread", {}).get("mean_net_bps", -np.inf) > 0
        )
        c["economic_pass_before_neighborhood"] = econ
        c["pre_neighborhood_pass"] = bool(c.get("state_pass") and econ)

    for a in cells:
        neigh = [b["candidate_id"] for b in cells if b is not a and supporter(a, b, cfg)]
        a["supporting_neighbors"] = sorted(neigh)
        a["neighborhood_support_count"] = len(neigh)
        a["full_development_pass"] = bool(
            a["pre_neighborhood_pass"] and len(neigh) >= int(cfg["neighborhood_gate"]["minimum_supporting_neighbors"])
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
    dev = cfg["periods"]["development"]
    start_ts = pd.Timestamp(dev["start"], tz="UTC")
    end_ts = pd.Timestamp(dev["end_exclusive"], tz="UTC")
    d = common.loc[(common.index >= start_ts) & (common.index < end_ts)].copy()
    if len(d) < 1000:
        raise SystemExit("insufficient development rows")

    grids = cfg["residual_grid"]
    states_by_lookback = {int(lb): relationship_states(d, int(lb), cfg) for lb in grids["lookback_trading_days"]}
    hypotheses = []
    for lb in grids["lookback_trading_days"]:
        for ez in grids["entry_abs_z_gte"]:
            hypotheses.append(build_state_hypothesis(d, states_by_lookback[int(lb)], int(lb), float(ez), start_ts, cfg))

    cells = []
    for lb in grids["lookback_trading_days"]:
        states = states_by_lookback[int(lb)]
        for ez in grids["entry_abs_z_gte"]:
            for xz in grids["exit_abs_z_lte"]:
                for mh in grids["max_hold_trading_bars"]:
                    cells.append(simulate_cell(d, states, int(lb), float(ez), float(xz), int(mh), start_ts, cfg))

    apply_gates(cells, hypotheses, cfg)
    passed = [c for c in cells if c.get("full_development_pass")]
    pkey = f"{float(cfg['execution']['primary_cost_bps']):g}"
    passed.sort(key=lambda c: (
        -float(c.get("state_median_spearman", -np.inf)),
        -float(c.get(f"positive_fold_fraction_{pkey}", -np.inf)),
        -float(c.get(f"net_{pkey}_median_fold_bps", -np.inf)),
        float(c.get("median_holding_bars", np.inf)),
        c["candidate_id"],
    ))
    selected = passed[: int(cfg["candidate_selection"]["maximum_candidates"])]

    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "source": cfg["source"],
        "development_period": dev,
        "data_integrity": {
            "gold_admitted_rows_all_source": int(len(gold)),
            "silver_admitted_rows_all_source": int(len(silver)),
            "common_rows_all_source": int(len(common)),
            "development_rows": int(len(d)),
            "development_first_bar": str(d.index.min()),
            "development_last_bar": str(d.index.max()),
        },
        "grid": {
            "state_hypotheses": int(len(hypotheses)),
            "state_passes": int(sum(bool(h.get("state_pass")) for h in hypotheses)),
            "cells_evaluated": int(len(cells)),
            "economic_passes_before_neighborhood": int(sum(bool(c.get("economic_pass_before_neighborhood")) for c in cells)),
            "pre_neighborhood_passes": int(sum(bool(c.get("pre_neighborhood_pass")) for c in cells)),
            "full_development_passes": int(len(passed)),
        },
        "selected_candidates_for_separate_freeze": [c["candidate_id"] for c in selected],
        "state_hypotheses": hypotheses,
        "cells": cells,
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
        "cells_evaluated": payload["grid"]["cells_evaluated"],
        "economic_passes_before_neighborhood": payload["grid"]["economic_passes_before_neighborhood"],
        "full_development_passes": payload["grid"]["full_development_passes"],
        "selected_candidates_for_separate_freeze": payload["selected_candidates_for_separate_freeze"],
        "locked_internal_validation_opened": payload["locked_internal_validation_opened"],
    }), indent=2))


if __name__ == "__main__":
    main()
