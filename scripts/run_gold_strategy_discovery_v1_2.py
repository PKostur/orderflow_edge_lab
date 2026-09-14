from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

START = pd.Timestamp("2023-01-01", tz="UTC")
DEV_END = pd.Timestamp("2025-01-01", tz="UTC")
FOLD_DAYS = 42
COSTS = [2.0, 5.0, 10.0]
PRIMARY = 5.0
NY = ZoneInfo("America/New_York")


def load_m1(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    tcol = cols.get("time") or cols.get("date") or df.columns[0]
    df[tcol] = pd.to_datetime(df[tcol], errors="coerce", utc=True)
    df = df.dropna(subset=[tcol]).set_index(tcol).sort_index()
    df.columns = [c.lower() for c in df.columns]
    for c in ["open", "high", "low", "close", "tick_volume", "volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = df.get("tick_volume", 0.0)
    return df[["open", "high", "low", "close", "volume"]].dropna()


def resample_m5(df: pd.DataFrame) -> pd.DataFrame:
    out = df.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df.close.shift(1)
    tr = pd.concat(
        [(df.high - df.low).abs(), (df.high - pc).abs(), (df.low - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def macd_hist(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    m = ema(s, fast) - ema(s, slow)
    sig = m.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return m - sig


def spearman(a, b) -> float:
    a = pd.Series(a, dtype=float)
    b = pd.Series(b, dtype=float)
    m = a.notna() & b.notna() & np.isfinite(a) & np.isfinite(b)
    if m.sum() < 20:
        return np.nan
    return float(a[m].rank(method="average").corr(b[m].rank(method="average")))


def profit_factor(vals) -> float:
    a = np.asarray(vals, dtype=float)
    pos = a[a > 0].sum()
    neg = -a[a < 0].sum()
    if neg <= 0:
        return 999.0 if pos > 0 else 0.0
    return float(pos / neg)


def fold_ids(index: pd.DatetimeIndex) -> np.ndarray:
    return np.floor((index - START) / pd.Timedelta(days=FOLD_DAYS)).astype(int)


def session_mask(index: pd.DatetimeIndex, name: str) -> np.ndarray:
    utc_hour = index.hour
    ny_hour = index.tz_convert(NY).hour
    london = (utc_hour >= 7) & (utc_hour < 11)
    new_york = (ny_hour >= 8) & (ny_hour < 12)
    if name == "london":
        return london
    if name == "new_york":
        return new_york
    if name == "both":
        return london | new_york
    raise ValueError(name)


def score_family(df: pd.DataFrame, family: str, p: dict) -> tuple[pd.Series, pd.Series]:
    c = df.close
    a = atr(df).replace(0, np.nan)
    score = pd.Series(0.0, index=df.index)

    if family == "youtube_ema50_rsi8_macd_proxy":
        e = ema(c, 50)
        x = rsi(c, 8)
        hist = macd_hist(c)
        threshold = float(p["rsi_threshold"])
        touched = (df.low <= e) & (df.high >= e)
        recent_touch = touched.rolling(3, min_periods=1).max().astype(bool)
        long = (c > e) & recent_touch & (c > df.open) & (x >= threshold) & (hist > 0)
        short = (c < e) & recent_touch & (c < df.open) & (x <= 100 - threshold) & (hist < 0)
        raw = (c - e) / a + hist / c.replace(0, np.nan) * 1000
        score[long] = raw[long].abs()
        score[short] = -raw[short].abs()
        return score, score.ne(0) & score.notna()

    if family == "youtube_ema50_100_rsi_proxy":
        e50 = ema(c, 50)
        e100 = ema(c, 100)
        x = rsi(c, 14)
        threshold = float(p["rsi_threshold"])
        raw = (e50 - e100) / a
        long = (raw > 0) & (c > e50) & (x >= threshold)
        short = (raw < 0) & (c < e50) & (x <= 100 - threshold)
        score[long] = raw[long]
        score[short] = raw[short]
        return score, score.ne(0) & score.notna()

    if family == "youtube_ema200_rsi_proxy":
        e = ema(c, 200)
        x = rsi(c, 14)
        threshold = float(p["rsi_threshold"])
        prev_ret = c.shift(1) / c.shift(2) - 1
        resume = np.sign(c - df.open)
        raw = (c - e) / a
        long = (raw > 0) & (prev_ret < 0) & (resume > 0) & (x >= threshold)
        short = (raw < 0) & (prev_ret > 0) & (resume < 0) & (x <= 100 - threshold)
        score[long] = raw[long]
        score[short] = raw[short]
        return score, score.ne(0) & score.notna()

    if family == "reddit_ema9_21_rsi7_session_scalp":
        e9 = ema(c, 9)
        e21 = ema(c, 21)
        x = rsi(c, 7)
        raw = (e9 - e21) / a
        sess = session_mask(df.index, p["session"])
        threshold = float(p["rsi_threshold"])
        long = sess & (raw > 0) & (x >= threshold)
        short = sess & (raw < 0) & (x <= 100 - threshold)
        score[long] = raw[long]
        score[short] = raw[short]
        return score, score.ne(0) & score.notna()

    if family == "smc_session_sweep_displacement_proxy":
        lb = int(p["sweep_lookback"])
        disp_thr = float(p["displacement_atr"])
        prior_hi = df.high.shift(1).rolling(lb).max()
        prior_lo = df.low.shift(1).rolling(lb).min()
        displacement = (c - df.open).abs() / a
        micro_hi = df.high.shift(1).rolling(3).max()
        micro_lo = df.low.shift(1).rolling(3).min()
        sweep_lo = (df.low < prior_lo) & (c > prior_lo)
        sweep_hi = (df.high > prior_hi) & (c < prior_hi)
        london_ny = session_mask(df.index, "both")
        long = london_ny & sweep_lo & (c > micro_hi) & (displacement >= disp_thr)
        short = london_ny & sweep_hi & (c < micro_lo) & (displacement >= disp_thr)
        score[long] = displacement[long]
        score[short] = -displacement[short]
        return score, score.ne(0) & score.notna()

    raise ValueError(family)


def evaluate(df: pd.DataFrame, family: str, params: dict, hold: int) -> dict | None:
    score, eligible = score_family(df, family, params)
    entry = df.open.shift(-1)
    exit_ = df.open.shift(-(1 + hold))
    fwd = exit_ / entry - 1
    x = pd.DataFrame({"score": score, "eligible": eligible, "fwd": fwd}, index=df.index)
    x = x[(x.index >= START) & (x.index < DEV_END) & x.eligible & x.score.notna() & x.fwd.notna()].copy()
    if x.empty:
        return None
    x["fold"] = fold_ids(x.index)
    exit_ts = pd.Series(df.index, index=df.index).shift(-(1 + hold)).reindex(x.index)
    same_fold = []
    for t, et in zip(x.index, exit_ts):
        if pd.isna(et):
            same_fold.append(False)
        else:
            same_fold.append(fold_ids(pd.DatetimeIndex([t]))[0] == fold_ids(pd.DatetimeIndex([et]))[0])
    x = x[same_fold]
    if x.empty:
        return None

    fold_rhos = []
    for _, g in x.groupby("fold"):
        r = spearman(g.score, g.fwd)
        if np.isfinite(r):
            fold_rhos.append(r)
    state_med = float(np.median(fold_rhos)) if fold_rhos else np.nan
    state_pos = float(np.mean(np.asarray(fold_rhos) > 0)) if fold_rhos else 0.0

    rows = []
    next_allowed = pd.Timestamp.min.tz_localize("UTC")
    for t, row in x.iterrows():
        if t < next_allowed:
            continue
        side = 1.0 if row.score > 0 else -1.0
        rows.append((t, int(row["fold"]), side * float(row.fwd) * 10000.0))
        loc = df.index.get_loc(t)
        next_allowed = df.index[min(loc + 1 + hold, len(df) - 1)]
    if not rows:
        return None
    trades = pd.DataFrame(rows, columns=["timestamp", "fold", "gross_bps"]).set_index("timestamp")

    out = {
        "family": family,
        "params": params | {"hold": hold},
        "events": len(x),
        "trades": len(trades),
        "state_folds": len(fold_rhos),
        "state_median_rho": state_med,
        "state_positive_fold_fraction": state_pos,
    }
    for cost in COSTS:
        net = trades.gross_bps - cost
        tmp = trades.assign(net=net)
        fexp = tmp.groupby("fold").net.mean()
        fpf = tmp.groupby("fold").net.apply(profit_factor)
        out[f"net_{cost:g}_median_fold"] = float(fexp.median()) if len(fexp) else np.nan
        out[f"pf_{cost:g}_median_fold"] = float(fpf.median()) if len(fpf) else np.nan
        out[f"posfold_{cost:g}"] = float((fexp > 0).mean()) if len(fexp) else 0.0
        out[f"mean_{cost:g}"] = float(net.mean())
    out["reversed_mean_primary"] = float((-trades.gross_bps - PRIMARY).mean())
    out["dev_prelim_pass"] = bool(
        len(fold_rhos) >= 10
        and state_med > 0
        and state_pos >= 0.60
        and len(trades) >= 150
        and out["net_5_median_fold"] > 0
        and out["pf_5_median_fold"] > 1
        and out["posfold_5"] >= 0.60
        and out["net_10_median_fold"] >= 0
        and out["mean_5"] > out["reversed_mean_primary"]
    )
    return out


def trials():
    for tf, threshold, hold in itertools.product(["M1", "M5"], [50, 55], [3, 5, 10, 20]):
        yield "youtube_ema50_rsi8_macd_proxy", tf, {"rsi_threshold": threshold}, hold
    for threshold, hold in itertools.product([50, 55, 60], [3, 5, 10, 20]):
        yield "youtube_ema50_100_rsi_proxy", "M5", {"rsi_threshold": threshold}, hold
        yield "youtube_ema200_rsi_proxy", "M5", {"rsi_threshold": threshold}, hold
    for threshold, sess, hold in itertools.product([52, 55, 60], ["london", "new_york", "both"], [3, 5, 10, 20]):
        yield "reddit_ema9_21_rsi7_session_scalp", "M5", {"rsi_threshold": threshold, "session": sess}, hold
    for tf, lb, disp, hold in itertools.product(["M1", "M5"], [30, 60, 120], [0.75, 1.25], [3, 5, 10, 20]):
        yield "smc_session_sweep_displacement_proxy", tf, {"sweep_lookback": lb, "displacement_atr": disp}, hold


def clean(v):
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m1", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    m1 = load_m1(Path(args.m1))
    # Deliberately keep the locked 2025+ rows in the immutable input but every evaluator slices < DEV_END.
    m5 = resample_m5(m1)
    frames = {"M1": m1, "M5": m5}
    integrity = {
        tf: {
            "rows": len(df),
            "start": str(df.index.min()),
            "end": str(df.index.max()),
            "development_rows": int(((df.index >= START) & (df.index < DEV_END)).sum()),
            "median_bars_per_day_development": float(
                pd.Series(1, index=df[(df.index >= START) & (df.index < DEV_END)].index)
                .groupby(lambda t: t.floor("D"))
                .sum()
                .median()
            ),
        }
        for tf, df in frames.items()
    }

    results = []
    for family, timeframe, params, hold in trials():
        try:
            row = evaluate(frames[timeframe], family, params, hold)
            if row:
                row["timeframe"] = timeframe
                results.append(row)
        except Exception as exc:
            results.append(
                {
                    "family": family,
                    "timeframe": timeframe,
                    "params": params | {"hold": hold},
                    "error": repr(exc),
                    "dev_prelim_pass": False,
                }
            )

    valid = [r for r in results if "error" not in r]
    valid.sort(
        key=lambda r: (
            r.get("dev_prelim_pass", False),
            r.get("net_5_median_fold", -1e99),
            r.get("state_median_rho", -1e99),
        ),
        reverse=True,
    )
    payload = {
        "schema_version": 1,
        "protocol": "gold-strategy-discovery-v1.2-scalping",
        "trial_count": len(results),
        "error_count": sum("error" in r for r in results),
        "prelim_pass_count": sum(bool(r.get("dev_prelim_pass")) for r in valid),
        "integrity": integrity,
        "top_development": valid[:50],
        "all_trials": results,
        "holdout_opened": False,
        "claims": {"verified_oos": False, "profitable_edge_established": False, "live_enabled": False},
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(payload), indent=2, allow_nan=False), encoding="utf-8")
    print(
        json.dumps(
            clean({k: payload[k] for k in ["trial_count", "error_count", "prelim_pass_count", "integrity", "top_development", "holdout_opened"]}),
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
