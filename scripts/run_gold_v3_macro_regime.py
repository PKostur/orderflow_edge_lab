from __future__ import annotations

import argparse
import io
import itertools
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

DEV_START = pd.Timestamp("2010-01-01", tz="UTC")
DEV_END = pd.Timestamp("2024-01-01", tz="UTC")
FOLD_DAYS = 126
COSTS = [2.0, 5.0, 10.0]
PRIMARY = 5.0

GOLD_URL = "https://raw.githubusercontent.com/simom1/XAUUSD-history/main/Gold-Cash/XAUUSD/XAUUSD_D1_2010_2026.csv"
FRED = {
    "real": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10",
    "nominal": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
    "usd": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS",
}


def get_csv(url: str) -> pd.DataFrame:
    req = urllib.request.Request(url, headers={"User-Agent": "orderflow-edge-lab/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return pd.read_csv(io.BytesIO(raw))


def load_gold() -> pd.DataFrame:
    d = get_csv(GOLD_URL)
    tcol = "time" if "time" in d.columns else d.columns[0]
    d[tcol] = pd.to_datetime(d[tcol], utc=True, errors="coerce")
    d = d.dropna(subset=[tcol]).set_index(tcol).sort_index()
    for c in ["open", "high", "low", "close"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d[["open", "high", "low", "close"]].dropna()


def load_fred(series: str, url: str) -> pd.Series:
    d = get_csv(url)
    date_col = "observation_date" if "observation_date" in d.columns else "DATE"
    value_cols = [c for c in d.columns if c != date_col]
    if len(value_cols) != 1:
        raise ValueError(f"Unexpected FRED columns for {series}: {list(d.columns)}")
    vcol = value_cols[0]
    d[date_col] = pd.to_datetime(d[date_col], utc=True, errors="coerce")
    d[vcol] = pd.to_numeric(d[vcol].replace(".", np.nan), errors="coerce")
    s = d.dropna(subset=[date_col]).set_index(date_col)[vcol].sort_index()
    return s.rename(series)


def fold_ids(idx: pd.DatetimeIndex) -> np.ndarray:
    return np.floor((idx - DEV_START) / pd.Timedelta(days=FOLD_DAYS)).astype(int)


def zscore(s: pd.Series, n: int = 252) -> pd.Series:
    m = s.rolling(n, min_periods=n).mean()
    sd = s.rolling(n, min_periods=n).std(ddof=0)
    return (s - m) / sd.replace(0, np.nan)


def pf(vals) -> float:
    a = np.asarray(vals, float)
    pos = a[a > 0].sum()
    neg = -a[a < 0].sum()
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return float(pos / neg)


def spearman(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if int(m.sum()) < 10:
        return np.nan
    return float(a[m].rank().corr(b[m].rank()))


def prepare() -> tuple[pd.DataFrame, dict]:
    gold = load_gold()
    real = load_fred("real", FRED["real"])
    nominal = load_fred("nominal", FRED["nominal"])
    usd = load_fred("usd", FRED["usd"])

    idx = gold.index
    # Forward-fill only observations already dated at or before the gold bar,
    # then lag one completed gold bar to prevent same-day macro leakage.
    macro = pd.concat([real, nominal, usd], axis=1).sort_index().reindex(idx).ffill().shift(1)
    d = gold.join(macro, how="left")
    d["breakeven"] = d["nominal"] - d["real"]
    manifest = {
        "gold_rows": int(len(gold)),
        "gold_start": str(gold.index.min()),
        "gold_end": str(gold.index.max()),
        "fred_non_null": {c: int(d[c].notna().sum()) for c in ["real", "nominal", "usd", "breakeven"]},
        "macro_lag_gold_bars": 1,
    }
    return d, manifest


def make_score(d: pd.DataFrame, family: str, lb: int) -> pd.Series:
    real_imp = d["real"] - d["real"].shift(lb)
    usd_imp = np.log(d["usd"] / d["usd"].shift(lb))
    be_imp = d["breakeven"] - d["breakeven"].shift(lb)
    zr = zscore(real_imp)
    zu = zscore(usd_imp)
    zb = zscore(be_imp)
    if family == "real_yield_change":
        return -zr
    if family == "broad_usd_change":
        return -zu
    if family == "breakeven_change":
        return zb
    if family == "combined_real_yield_usd":
        return -(zr + zu) / math.sqrt(2.0)
    if family == "real_yield_usd_agreement":
        same = np.sign(real_imp) == np.sign(usd_imp)
        nonzero = (np.sign(real_imp) != 0) & (np.sign(usd_imp) != 0)
        mag = pd.concat([zr.abs(), zu.abs()], axis=1).min(axis=1)
        common_sign = np.sign(real_imp)
        out = -common_sign * mag
        return out.where(same & nonzero)
    raise ValueError(family)


def evaluate(d: pd.DataFrame, family: str, lb: int, threshold: float, hold: int) -> dict | None:
    score = make_score(d, family, lb)
    entry = d["open"].shift(-1)
    exit_ = d["open"].shift(-(1 + hold))
    raw = exit_ / entry - 1.0
    exit_ts = pd.Series(d.index, index=d.index).shift(-(1 + hold))
    x = pd.DataFrame({"score": score, "raw": raw, "exit_ts": exit_ts}, index=d.index)
    x = x[(x.index >= DEV_START) & (x.index < DEV_END) & x.score.notna() & x.raw.notna() & x.exit_ts.notna()]
    x = x[x.score.abs() >= threshold].copy()
    if x.empty:
        return None
    x["fold"] = fold_ids(x.index)
    exit_fold = fold_ids(pd.DatetimeIndex(x.exit_ts))
    x = x[x["fold"].to_numpy() == np.asarray(exit_fold)]
    if x.empty:
        return None

    rhos = []
    for _, g in x.groupby("fold"):
        r = spearman(g.score, g.raw)
        if np.isfinite(r):
            rhos.append(float(r))
    state_med = float(np.median(rhos)) if rhos else np.nan
    state_pos = float(np.mean(np.asarray(rhos) > 0)) if rhos else 0.0

    rows = []
    next_allowed = pd.Timestamp.min.tz_localize("UTC")
    for t, r in x.iterrows():
        if t < next_allowed:
            continue
        side = 1 if r.score > 0 else -1
        rows.append((t, int(r["fold"]), side * float(r.raw) * 1e4))
        next_allowed = r.exit_ts
    if not rows:
        return None
    tr = pd.DataFrame(rows, columns=["t", "fold", "gross"]).set_index("t")
    out = {
        "family": family,
        "lookback_business_days": lb,
        "entry_abs_z": threshold,
        "hold_trading_days": hold,
        "events": int(len(x)),
        "trades": int(len(tr)),
        "state_folds": int(len(rhos)),
        "state_median_spearman": state_med,
        "state_positive_fold_fraction": state_pos,
    }
    for cost in COSTS:
        net = tr.gross - cost
        means, pfs = [], []
        for _, g in tr.assign(net=net).groupby("fold"):
            means.append(float(g.net.mean()))
            pfs.append(pf(g.net))
        k = str(int(cost))
        out[f"net_{k}_median_fold"] = float(np.median(means)) if means else np.nan
        out[f"pf_{k}_median_fold"] = float(np.median(pfs)) if pfs else np.nan
        out[f"posfold_{k}"] = float(np.mean(np.asarray(means) > 0)) if means else 0.0
        out[f"mean_{k}"] = float(net.mean())
    out["reversed_mean_primary"] = float((-tr.gross - PRIMARY).mean())
    out["prelim_pass"] = bool(
        len(rhos) >= 12
        and np.isfinite(state_med)
        and state_med > 0
        and state_pos >= 0.60
        and len(tr) >= 50
        and out["net_5_median_fold"] > 0
        and out["pf_5_median_fold"] > 1
        and out["posfold_5"] >= 0.60
        and out["net_10_median_fold"] >= 0
        and out["mean_5"] > out["reversed_mean_primary"]
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    d, manifest = prepare()
    results = []
    families = [
        "real_yield_change",
        "broad_usd_change",
        "breakeven_change",
        "combined_real_yield_usd",
        "real_yield_usd_agreement",
    ]
    for fam, lb, z, hold in itertools.product(families, [5, 20, 60], [0.5, 1.0, 1.5], [5, 20, 60]):
        try:
            r = evaluate(d, fam, lb, z, hold)
            if r is not None:
                results.append(r)
        except Exception as e:
            results.append({"family": fam, "lookback_business_days": lb, "entry_abs_z": z, "hold_trading_days": hold, "error": repr(e), "prelim_pass": False})
    valid = [r for r in results if "error" not in r]
    valid.sort(key=lambda r: (r.get("prelim_pass", False), r.get("net_5_median_fold", -1e99), r.get("state_median_spearman", -1e99)), reverse=True)
    out = {
        "schema_version": 1,
        "protocol": "gold-v3-macro-regime",
        "data_manifest": manifest,
        "trial_count": len(results),
        "error_count": sum("error" in r for r in results),
        "prelim_pass_count": sum(bool(r.get("prelim_pass")) for r in valid),
        "top_development": valid[:50],
        "all_trials": results,
        "validation_opened": False,
        "claims": {"verified_oos": False, "profitable_edge_established": False, "live_enabled": False},
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"trial_count": out["trial_count"], "error_count": out["error_count"], "prelim_pass_count": out["prelim_pass_count"], "top": valid[:10]}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
