from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, time
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


def rho(a, b):
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 3:
        return float("nan")
    return float(a[m].rank(method="average").corr(b[m].rank(method="average")))


def stable_seed(base: int, text: str) -> int:
    h = hashlib.sha256(text.encode()).digest()
    return int((base + int.from_bytes(h[:4], "big")) % (2**32 - 1))


def sign_flip_p(values, epochs, seed):
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return float("nan")
    obs = float(np.median(x))
    if obs <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    ax = np.abs(x)
    count = 0
    done = 0
    while done < epochs:
        n = min(2000, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(ax)))
        null = np.median(signs * ax[None, :], axis=1)
        count += int(np.sum(null >= obs))
        done += n
    return float((count + 1) / (epochs + 1))


def bh_qvalues(pvals):
    p = np.asarray(pvals, dtype=float)
    q = np.full(len(p), np.nan)
    valid = np.where(np.isfinite(p))[0]
    if not len(valid):
        return q.tolist()
    order = valid[np.argsort(p[valid])]
    m = len(order)
    raw = np.array([p[idx] * m / rank for rank, idx in enumerate(order, 1)], dtype=float)
    adj = np.minimum.accumulate(raw[::-1])[::-1]
    adj = np.minimum(adj, 1.0)
    for j, idx in enumerate(order):
        q[idx] = adj[j]
    return q.tolist()


def load_m15(path: Path, cfg):
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    req = ["time", "open", "high", "low", "close", "tick_volume"]
    missing = [c for c in req if c not in d.columns]
    if missing:
        raise ValueError(f"missing columns {missing}")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    for c in req[1:]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=req)
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d["tick_volume"] >= int(cfg["data_admission"]["minimum_tick_volume"])]
    return d.drop_duplicates("time", keep="last").set_index("time").sort_index()[req[1:]]


def local_to_utc(date_text: str, hhmm: str):
    hh, mm = map(int, hhmm.split(":"))
    dt = datetime.strptime(date_text, "%Y-%m-%d").date()
    local = datetime.combine(dt, time(hh, mm), tzinfo=ZoneInfo("America/New_York"))
    return pd.Timestamp(local.astimezone(ZoneInfo("UTC")))


def load_events(bls_path: Path, fomc_path: Path, cfg):
    rows = []
    b = pd.read_csv(bls_path)
    for _, r in b.iterrows():
        et = str(r["event_type"])
        if et not in {"cpi", "employment_situation"}:
            continue
        rows.append({"event_type": et, "event_time": local_to_utc(str(r["date"]), str(r["release_time_et"]))})
    f = pd.read_csv(fomc_path)
    for _, r in f.iterrows():
        rows.append({"event_type": "fomc", "event_time": local_to_utc(str(r["decision_date"]), "14:00")})
    e = pd.DataFrame(rows).drop_duplicates(["event_type", "event_time"]).sort_values("event_time")
    start = pd.Timestamp(cfg["periods"]["development"]["start"])
    end = pd.Timestamp(cfg["periods"]["development"]["end_exclusive"])
    return e[(e["event_time"] >= start) & (e["event_time"] < end)].reset_index(drop=True)


def pre_window_rv(d, t0, floor):
    # 16 completed bars ending t0-15m; 17 closes are required for 16 close-to-close returns.
    times = [t0 - pd.Timedelta(minutes=15 * k) for k in range(17, 0, -1)]
    if any(t not in d.index for t in times):
        return None
    c = d.loc[times, "close"].to_numpy(float)
    rets = np.diff(np.log(c))
    rv = float(np.sqrt(np.sum(rets * rets)))
    return max(rv, floor)


def compression_reference(d, t0, floor, minimum_days):
    vals = []
    # Search backwards until 20 admissible weekdays are found, capped at 45 calendar days.
    for k in range(1, 46):
        t = t0 - pd.Timedelta(days=k)
        if t.weekday() > 4:
            continue
        rv = pre_window_rv(d, t, floor)
        if rv is not None:
            vals.append(rv)
            if len(vals) == 20:
                break
    if len(vals) < minimum_days:
        return None
    return float(np.median(vals))


def event_features(d, t0, cfg):
    em = cfg["event_measurement"]
    floor = float(em["volatility_floor"])
    t15 = t0 + pd.Timedelta(minutes=15)
    entry = t0 + pd.Timedelta(minutes=30)
    exit_t = t0 + pd.Timedelta(minutes=210)
    tpre = t0 - pd.Timedelta(minutes=240)
    needed = [t0, t15, entry, exit_t, tpre]
    if any(t not in d.index for t in needed):
        return None
    rv = pre_window_rv(d, t0, floor)
    if rv is None:
        return None
    event_open = float(d.at[t0, "open"])
    reaction_close = float(d.at[t15, "close"])
    entry_open = float(d.at[entry, "open"])
    exit_open = float(d.at[exit_t, "open"])
    pre_open = float(d.at[tpre, "open"])
    reaction = float(math.log(reaction_close / event_open))
    if reaction == 0 or not np.isfinite(reaction):
        return None
    future = float(math.log(exit_open / entry_open))
    drift = float(math.log(event_open / pre_open))
    comp_ref = compression_reference(
        d, t0, floor, int(em["compression_minimum_reference_days"])
    )
    shock = abs(reaction) / rv
    align = math.copysign(1.0, reaction) * drift / rv
    compression = float(-math.log(rv / comp_ref)) if comp_ref and comp_ref > 0 else np.nan
    return {
        "initial_reaction": reaction,
        "future_return": future,
        "pre_event_drift": drift,
        "pre_event_rv": rv,
        "compression_reference": comp_ref if comp_ref is not None else np.nan,
        "shock_exhaustion": shock,
        "drift_alignment_exhaustion": align,
        "compression_continuation": compression,
        "aligned_shock_exhaustion": shock * align,
        "reversal_target": -math.copysign(1.0, reaction) * future,
        "continuation_target": math.copysign(1.0, reaction) * future,
    }


def build_event_frame(d, events, cfg):
    rows = []
    for _, er in events.iterrows():
        f = event_features(d, er["event_time"], cfg)
        if f is None:
            continue
        rows.append({"event_type": er["event_type"], "event_time": er["event_time"], **f})
    return pd.DataFrame(rows).sort_values("event_time").reset_index(drop=True)


def fold_rows(g, predictor, target, cfg, start):
    cluster = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    minimum = int(cfg["state_first"]["minimum_events_per_scorable_fold"])
    gg = g.copy()
    gg["fold"] = np.floor((gg["event_time"] - start) / pd.Timedelta(days=cluster)).astype(int)
    rows = []
    for fid, x in gg.groupby("fold"):
        x = x[np.isfinite(x[predictor]) & np.isfinite(x[target])]
        if len(x) < minimum:
            continue
        r = rho(x[predictor], x[target])
        if np.isfinite(r):
            rows.append({"fold": int(fid), "events": int(len(x)), "rho": float(r)})
    return rows


def year_rows(g, predictor, target):
    rows = []
    gg = g.copy()
    gg["year"] = gg["event_time"].dt.year
    for year, x in gg.groupby("year"):
        x = x[np.isfinite(x[predictor]) & np.isfinite(x[target])]
        if len(x) < 5:
            continue
        r = rho(x[predictor], x[target])
        if np.isfinite(r):
            rows.append({"year": int(year), "events": int(len(x)), "rho": float(r)})
    return rows


def permutation_p(g, predictor, target, observed, cfg, hid):
    pc = cfg["state_first"]["permutation_control"]
    epochs = int(pc["epochs"])
    rng = np.random.default_rng(stable_seed(int(pc["seed"]), hid))
    base = g[["event_time", predictor, target]].dropna().copy()
    base["year"] = base["event_time"].dt.year
    groups = [idx.to_numpy() for _, idx in base.groupby("year").groups.items()]
    start = pd.Timestamp(cfg["periods"]["development"]["start"])
    cluster = int(cfg["state_first"]["dependence_cluster_calendar_days"])
    minimum = int(cfg["state_first"]["minimum_events_per_scorable_fold"])
    base["fold"] = np.floor((base["event_time"] - start) / pd.Timedelta(days=cluster)).astype(int)
    pvals = base[predictor].to_numpy(float)
    targets = base[target].to_numpy(float)
    folds = base["fold"].to_numpy(int)
    count = 0
    scored = 0
    for _ in range(epochs):
        pp = pvals.copy()
        for idx in groups:
            pp[idx] = pp[rng.permutation(idx)]
        rs = []
        for fid in np.unique(folds):
            m = folds == fid
            if int(m.sum()) < minimum:
                continue
            r = rho(pp[m], targets[m])
            if np.isfinite(r):
                rs.append(r)
        if rs:
            null = float(np.median(rs))
            scored += 1
            if null >= observed:
                count += 1
    return float((count + 1) / (scored + 1)) if scored else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--bls", required=True)
    ap.add_argument("--fomc", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    d = load_m15(Path(args.gold), cfg)
    events = load_events(Path(args.bls), Path(args.fomc), cfg)
    ef = build_event_frame(d, events, cfg)
    start = pd.Timestamp(cfg["periods"]["development"]["start"])

    hypotheses = []
    specs = {
        "shock_exhaustion": ("shock_exhaustion", "reversal_target"),
        "drift_alignment_exhaustion": ("drift_alignment_exhaustion", "reversal_target"),
        "compression_continuation": ("compression_continuation", "continuation_target"),
        "aligned_shock_exhaustion": ("aligned_shock_exhaustion", "reversal_target"),
    }
    for event_type in cfg["state_first"]["event_types"]:
        g = ef[ef["event_type"] == event_type].copy()
        for name, (pred, target) in specs.items():
            hid = f"{event_type}__{name}"
            fr = fold_rows(g, pred, target, cfg, start)
            yr = year_rows(g, pred, target)
            rhos = [x["rho"] for x in fr]
            med = float(np.median(rhos)) if rhos else np.nan
            hypotheses.append({
                "hypothesis_id": hid,
                "event_type": event_type,
                "mechanism": name,
                "predictor": pred,
                "target": target,
                "events": int(np.sum(np.isfinite(g[pred]) & np.isfinite(g[target]))),
                "state_folds": int(len(fr)),
                "folds": fr,
                "median_fold_spearman": med,
                "positive_fold_fraction": float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0,
                "years": yr,
                "years_scorable": int(len(yr)),
                "positive_year_fraction": float(np.mean(np.asarray([x["rho"] for x in yr]) > 0)) if yr else 0.0,
                "sign_flip_p": sign_flip_p(rhos, int(cfg["state_first"]["fold_sign_flip_epochs"]), stable_seed(int(cfg["state_first"]["fold_sign_flip_seed"]), hid)),
            })

    qvals = bh_qvalues([h["sign_flip_p"] for h in hypotheses])
    s = cfg["state_first"]
    for h, q in zip(hypotheses, qvals):
        h["bh_fdr_q"] = q
        h["permutation_p"] = permutation_p(
            ef[ef["event_type"] == h["event_type"]].copy(),
            h["predictor"], h["target"], h["median_fold_spearman"], cfg, h["hypothesis_id"]
        ) if np.isfinite(h["median_fold_spearman"]) and h["median_fold_spearman"] > 0 else 1.0
        h["state_pass"] = bool(
            h["state_folds"] >= int(s["minimum_scorable_folds"])
            and h["median_fold_spearman"] > float(s["minimum_median_fold_spearman"])
            and h["positive_fold_fraction"] >= float(s["minimum_positive_fold_fraction"])
            and h["years_scorable"] >= int(s["minimum_years_with_at_least_5_events"])
            and h["positive_year_fraction"] >= float(s["minimum_positive_year_fraction"])
            and h["bh_fdr_q"] <= float(s["maximum_bh_fdr_q"])
            and h["permutation_p"] <= float(s["permutation_control"]["maximum_p"])
        )

    passed = [h for h in hypotheses if h["state_pass"]]
    passed.sort(key=lambda h: (h["bh_fdr_q"], h["permutation_p"], -h["median_fold_spearman"], -h["positive_fold_fraction"], h["hypothesis_id"]))
    selected = passed[: int(cfg["selection"]["maximum_state_hypotheses_for_temporal_validation"])]
    counts = {k: int((events["event_type"] == k).sum()) for k in cfg["state_first"]["event_types"]}
    admitted = {k: int((ef["event_type"] == k).sum()) for k in cfg["state_first"]["event_types"]}
    payload = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "evidence_class": cfg["evidence_class"],
        "data_integrity": {
            "gold_rows_source": int(len(d)),
            "scheduled_event_counts": counts,
            "admitted_event_counts": admitted,
            "admitted_events_total": int(len(ef)),
        },
        "grid": {
            "hypotheses": int(len(hypotheses)),
            "state_passes": int(len(passed)),
        },
        "selected_state_hypotheses_for_separate_temporal_freeze": [h["hypothesis_id"] for h in selected],
        "hypotheses": hypotheses,
        "pnl_tested": False,
        "temporal_validation_opened": False,
        "retrospective_extension_opened": False,
        "leverage_tested": False,
        "claims": cfg["claims"],
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2))
    print(json.dumps(clean({
        "admitted_events": admitted,
        "hypotheses": len(hypotheses),
        "state_passes": len(passed),
        "selected": payload["selected_state_hypotheses_for_separate_temporal_freeze"],
        "pnl_tested": False,
        "temporal_validation_opened": False
    }), indent=2))


if __name__ == "__main__":
    main()
