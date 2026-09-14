from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

START = pd.Timestamp("2010-01-01", tz="UTC")
END = pd.Timestamp("2020-01-01", tz="UTC")
CLUSTER_DAYS = 365
COSTS = [2.0, 5.0, 10.0]
PRIMARY = 5.0
PERM_EPOCHS = 20_000

CELLS = [
    {"family": "reddit_h4_bb_rsi_divergence", "lookback": 3, "hold": 6},
    {"family": "reddit_h4_bb_rsi_divergence", "lookback": 6, "hold": 6},
    {"family": "youtube_rsi_divergence_range_reentry", "lookback": 5, "trend_ema": 0, "hold": 8},
    {"family": "youtube_rsi_divergence_range_reentry", "lookback": 10, "trend_ema": 0, "hold": 8},
    {"family": "youtube_rsi_divergence_range_reentry", "lookback": 10, "trend_ema": 0, "hold": 16},
]


def clean(x):
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return x


def load_h4(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    tcol = next((c for c in ["timestamp", "time", "date", "datetime"] if c in df.columns), df.columns[0])
    raw = df[tcol]
    numeric = pd.to_numeric(raw, errors="coerce")
    if numeric.notna().mean() > 0.95:
        med = float(numeric.dropna().median())
        unit = "ms" if med > 1e11 else "s"
        ts = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    else:
        ts = pd.to_datetime(raw, utc=True, errors="coerce")
    df[tcol] = ts
    df = df.dropna(subset=[tcol]).set_index(tcol).sort_index()
    aliases = {"bidopen": "open", "bidhigh": "high", "bidlow": "low", "bidclose": "close"}
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})
    for c in ["open", "high", "low", "close"]:
        if c not in df.columns:
            raise ValueError(f"missing {c}; columns={list(df.columns)}")
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.loc[(df.index >= START) & (df.index < END), ["open", "high", "low", "close"]].dropna()
    return df[~df.index.duplicated(keep="last")]


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def pf(vals) -> float:
    a = np.asarray(vals, float)
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


def cluster_ids(idx: pd.DatetimeIndex) -> np.ndarray:
    return np.floor((idx - START) / pd.Timedelta(days=CLUSTER_DAYS)).astype(int)


def signal(df: pd.DataFrame, cell: dict) -> tuple[pd.Series, pd.Series]:
    c = df["close"]
    x = rsi(c)
    lb = int(cell["lookback"])
    if cell["family"] == "reddit_h4_bb_rsi_divergence":
        mid = c.rolling(120, min_periods=120).mean()
        sd = c.rolling(120, min_periods=120).std(ddof=0)
        z = (c - mid) / sd.replace(0, np.nan)
        bull = (z <= -2.0) & (c < c.shift(lb)) & (x > x.shift(lb))
        bear = (z >= 2.0) & (c > c.shift(lb)) & (x < x.shift(lb))
        score = pd.Series(np.nan, index=df.index, dtype=float)
        score.loc[bull] = (-z + (x - x.shift(lb)) / 20.0).loc[bull]
        score.loc[bear] = -(z + (x.shift(lb) - x) / 20.0).loc[bear]
        return score, bull | bear

    div_bull = (c < c.shift(lb)) & (x > x.shift(lb))
    div_bear = (c > c.shift(lb)) & (x < x.shift(lb))
    recent_bull = div_bull.rolling(3, min_periods=1).max().astype(bool)
    recent_bear = div_bear.rolling(3, min_periods=1).max().astype(bool)
    bull = recent_bull & (x.shift(1) < 30) & (x >= 30)
    bear = recent_bear & (x.shift(1) > 70) & (x <= 70)
    score = pd.Series(np.nan, index=df.index, dtype=float)
    strength = (x - x.shift(lb)).abs() / 20.0 + 1.0
    score.loc[bull] = strength.loc[bull]
    score.loc[bear] = -strength.loc[bear]
    return score, bull | bear


def clustered_permutation_p(scored: list[tuple[np.ndarray, np.ndarray]], observed: float, seed: int) -> float:
    if not scored or not math.isfinite(observed):
        return float("nan")
    rng = np.random.default_rng(seed)
    null = np.empty(PERM_EPOCHS, dtype=float)
    score_ranks = []
    target_ranks = []
    for s, y in scored:
        sr = pd.Series(s).rank(method="average").to_numpy(float)
        yr = pd.Series(y).rank(method="average").to_numpy(float)
        score_ranks.append(sr)
        target_ranks.append(yr)
    for e in range(PERM_EPOCHS):
        vals = []
        for sr, yr in zip(score_ranks, target_ranks):
            yp = rng.permutation(yr)
            if np.std(sr) > 0 and np.std(yp) > 0:
                vals.append(float(np.corrcoef(sr, yp)[0, 1]))
        null[e] = np.median(vals) if vals else np.nan
    valid = np.isfinite(null)
    if not valid.any():
        return float("nan")
    return float((1 + np.sum(null[valid] >= observed)) / (1 + valid.sum()))


def evaluate(df: pd.DataFrame, cell: dict, cell_index: int) -> dict:
    hold = int(cell["hold"])
    score, eligible = signal(df, cell)
    entry = df["open"].shift(-1)
    exit_ = df["open"].shift(-(1 + hold))
    fwd = exit_ / entry - 1.0
    idx = df.index
    fold = cluster_ids(idx)
    sc = score.to_numpy(float)
    el = eligible.fillna(False).to_numpy(bool)
    fw = fwd.to_numpy(float)
    pos = np.where(el & np.isfinite(sc) & np.isfinite(fw))[0]
    exit_pos = pos + 1 + hold
    ok = exit_pos < len(df)
    pos, exit_pos = pos[ok], exit_pos[ok]
    ok = fold[pos] == fold[exit_pos]
    pos = pos[ok]

    cluster_rhos = []
    scored = []
    for cid in np.unique(fold[pos]):
        pp = pos[fold[pos] == cid]
        if len(pp) < 5:
            continue
        r = rho(sc[pp], fw[pp])
        if math.isfinite(r):
            cluster_rhos.append(r)
            scored.append((sc[pp], fw[pp]))
    state_med = float(np.median(cluster_rhos)) if cluster_rhos else float("nan")
    state_pos = float(np.mean(np.asarray(cluster_rhos) > 0)) if cluster_rhos else 0.0
    perm_p = clustered_permutation_p(scored, state_med, 20260914 + cell_index)

    chosen = []
    next_pos = -1
    for p in pos:
        if p < next_pos:
            continue
        chosen.append(p)
        next_pos = p + 1 + hold
    chosen = np.asarray(chosen, dtype=int)
    gross = np.sign(sc[chosen]) * fw[chosen] * 10000.0 if len(chosen) else np.asarray([])
    cf = fold[chosen] if len(chosen) else np.asarray([], dtype=int)

    out = dict(cell)
    out.update(
        events=int(len(pos)),
        trades=int(len(chosen)),
        state_scorable_clusters=int(len(cluster_rhos)),
        state_median_cluster_spearman=state_med,
        state_positive_cluster_fraction=state_pos,
        state_permutation_p=perm_p,
    )
    for cost in COSTS:
        net = gross - cost
        exps, pfs = [], []
        for cid in np.unique(cf):
            vals = net[cf == cid]
            exps.append(float(vals.mean()))
            pfs.append(pf(vals))
        out[f"net_{cost:g}_median_cluster_bps"] = float(np.median(exps)) if exps else float("nan")
        out[f"pf_{cost:g}_median_cluster"] = float(np.median(pfs)) if pfs else float("nan")
        out[f"positive_cluster_fraction_{cost:g}"] = float(np.mean(np.asarray(exps) > 0)) if exps else 0.0
        out[f"mean_net_{cost:g}_bps"] = float(net.mean()) if len(net) else float("nan")
    out["reversed_mean_net_5_bps"] = float((-gross - PRIMARY).mean()) if len(gross) else float("nan")
    out["state_pass"] = bool(
        out["state_scorable_clusters"] >= 8
        and math.isfinite(state_med)
        and state_med > 0
        and state_pos >= 0.60
        and math.isfinite(perm_p)
        and perm_p <= 0.01
    )
    out["replication_pass"] = bool(
        out["state_pass"]
        and out["trades"] >= 80
        and out["net_5_median_cluster_bps"] > 0
        and out["pf_5_median_cluster"] > 1
        and out["positive_cluster_fraction_5"] >= 0.60
        and out["net_10_median_cluster_bps"] >= 0
        and out["mean_net_5_bps"] > out["reversed_mean_net_5_bps"]
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    df = load_h4(Path(args.data))
    daily_counts = pd.Series(1, index=df.index).groupby(df.index.floor("D")).sum()
    yearly = pd.Series(1, index=df.index).groupby(df.index.year).sum().to_dict()
    integrity = {
        "rows": int(len(df)),
        "start": str(df.index.min()),
        "end": str(df.index.max()),
        "median_bars_per_active_day": float(daily_counts.median()) if len(daily_counts) else 0.0,
        "yearly_rows": {str(k): int(v) for k, v in yearly.items()},
    }
    if integrity["median_bars_per_active_day"] < 4.0:
        raise SystemExit(f"invalid H4 density: {integrity}")
    results = [evaluate(df, cell, i) for i, cell in enumerate(CELLS)]
    payload = {
        "schema_version": 1,
        "protocol": "gold-h4-divergence-historical-replication-v1",
        "integrity": integrity,
        "cells": results,
        "replication_pass_count": sum(bool(x["replication_pass"]) for x in results),
        "holdout_opened": False,
        "claims": {"verified_oos": False, "profitable_edge_established": False, "live_enabled": False},
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2), encoding="utf-8")
    print(json.dumps(clean(payload), indent=2))


if __name__ == "__main__":
    main()
