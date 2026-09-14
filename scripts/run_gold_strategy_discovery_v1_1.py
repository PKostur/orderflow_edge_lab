from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import run_gold_strategy_discovery_v1 as base

NY = ZoneInfo("America/New_York")


def _session_masks(index: pd.DatetimeIndex):
    utc_hour = index.hour
    ny = index.tz_convert(NY)
    ny_hour = ny.hour
    london = (utc_hour >= 7) & (utc_hour < 11)
    new_york = (ny_hour >= 8) & (ny_hour < 12)
    return london, new_york


def _previous_day_levels(df: pd.DataFrame):
    day = df.index.floor("D")
    daily_high = df.high.groupby(day).max()
    daily_low = df.low.groupby(day).min()
    prev_high = pd.Series(day, index=df.index).map(daily_high.shift(1))
    prev_low = pd.Series(day, index=df.index).map(daily_low.shift(1))
    return prev_high.astype(float), prev_low.astype(float)


def score_extra(df: pd.DataFrame, family: str, p: dict):
    c = df.close
    a = base.atr(df)
    score = pd.Series(0.0, index=df.index)
    eligible = pd.Series(False, index=df.index)

    if family == "youtube_three_am_london_ifvg_proxy":
        lb = int(p["sweep_lookback"])
        prior_hi = df.high.shift(1).rolling(lb).max()
        prior_lo = df.low.shift(1).rolling(lb).min()
        sweep_lo = (df.low < prior_lo) & (c > prior_lo)
        sweep_hi = (df.high > prior_hi) & (c < prior_hi)
        recent_sweep_lo = sweep_lo.rolling(8, min_periods=1).max().astype(bool)
        recent_sweep_hi = sweep_hi.rolling(8, min_periods=1).max().astype(bool)

        bearish_gap_upper = df.low.shift(2).where(df.high < df.low.shift(2)).ffill(limit=8)
        bullish_gap_lower = df.high.shift(2).where(df.low > df.high.shift(2)).ffill(limit=8)
        reclaim_up = (c > bearish_gap_upper) & (c.shift(1) <= bearish_gap_upper.shift(1))
        reclaim_down = (c < bullish_gap_lower) & (c.shift(1) >= bullish_gap_lower.shift(1))

        ny_hour = df.index.tz_convert(NY).hour
        session = (ny_hour >= 3) & (ny_hour < 5)
        long = session & recent_sweep_lo & reclaim_up
        short = session & recent_sweep_hi & reclaim_down
        score[long] = 1.0
        score[short] = -1.0
        eligible = score.ne(0)
        return score, eligible

    if family == "asian_range_london_breakout_retest":
        day = df.index.floor("D")
        hour = df.index.hour
        asian = (hour >= 0) & (hour < 7)
        london = (hour >= 7) & (hour < 11)
        asian_hi = df.high.where(asian).groupby(day).transform("max")
        asian_lo = df.low.where(asian).groupby(day).transform("min")
        up_break = london & (c > asian_hi)
        dn_break = london & (c < asian_lo)
        w = int(p["retest_bars"]) + 1
        recent_up = up_break.rolling(w, min_periods=1).max().astype(bool)
        recent_dn = dn_break.rolling(w, min_periods=1).max().astype(bool)
        long = london & recent_up & (df.low <= asian_hi) & (c > asian_hi)
        short = london & recent_dn & (df.high >= asian_lo) & (c < asian_lo)
        score[long] = 1.0
        score[short] = -1.0
        eligible = score.ne(0)
        return score, eligible

    if family == "tokyo_london_ny_range_push_reversal":
        day = df.index.floor("D")
        hour = df.index.hour
        tokyo = (hour >= 0) & (hour < 7)
        london = (hour >= 7) & (hour < 12)
        ny = (hour >= 12) & (hour < 17)
        tokyo_hi = df.high.where(tokyo).groupby(day).transform("max")
        tokyo_lo = df.low.where(tokyo).groupby(day).transform("min")
        london_swept_hi = (df.high.where(london).groupby(day).transform("max") > tokyo_hi)
        london_swept_lo = (df.low.where(london).groupby(day).transform("min") < tokyo_lo)
        mlb = int(p["micro_break_lookback"])
        micro_hi = df.high.shift(1).rolling(mlb).max()
        micro_lo = df.low.shift(1).rolling(mlb).min()
        long = ny & london_swept_lo & (c > tokyo_lo) & (c > micro_hi)
        short = ny & london_swept_hi & (c < tokyo_hi) & (c < micro_lo)
        score[long] = 1.0
        score[short] = -1.0
        eligible = score.ne(0)
        return score, eligible

    if family == "reddit_ema_21_50_pullback":
        e21 = base.ema(c, 21)
        e50 = base.ema(c, 50)
        x = base.rsi(c, 14)
        trend = np.sign(e21 - e50)
        dist = (c - e21) / a.replace(0, np.nan)
        pull = dist.abs() <= float(p["pullback_atr"])
        candle_dir = np.sign(c - df.open)
        r = float(p["rsi_threshold"])
        long = (trend > 0) & pull & (candle_dir > 0) & (x >= r)
        short = (trend < 0) & pull & (candle_dir < 0) & (x <= 100 - r)
        score[long] = (e21[long] - e50[long]) / a[long]
        score[short] = (e21[short] - e50[short]) / a[short]
        eligible = score.ne(0) & score.notna()
        return score, eligible

    if family == "reddit_session_ema_9_21_rsi7":
        e9 = base.ema(c, 9)
        e21 = base.ema(c, 21)
        x = base.rsi(c, 7)
        raw = (e9 - e21) / a.replace(0, np.nan)
        london, new_york = _session_masks(df.index)
        if p["session"] == "london":
            session = london
        elif p["session"] == "new_york":
            session = new_york
        else:
            session = london | new_york
        r = float(p["rsi_threshold"])
        long = session & (raw > 0) & (x >= r)
        short = session & (raw < 0) & (x <= 100 - r)
        score[long] = raw[long]
        score[short] = raw[short]
        eligible = score.ne(0) & score.notna()
        return score, eligible

    if family == "reddit_fifteen_minute_orb":
        london, new_york = _session_masks(df.index)
        utc_day = df.index.floor("D")
        ny_day = pd.DatetimeIndex(df.index.tz_convert(NY).date)
        if p["session"] == "london":
            session = london
            first = df.index.hour == 7
            key = utc_day
        else:
            session = new_york
            first = df.index.tz_convert(NY).hour == 8
            key = pd.Series(ny_day, index=df.index)
        orb_hi = df.high.where(first).groupby(key).transform("max")
        orb_lo = df.low.where(first).groupby(key).transform("min")
        up = session & (c > orb_hi)
        dn = session & (c < orb_lo)
        if p["entry_mode"] == "direct":
            long, short = up, dn
        else:
            w = int(p["retest_window_bars"]) + 1
            recent_up = up.rolling(w, min_periods=1).max().astype(bool)
            recent_dn = dn.rolling(w, min_periods=1).max().astype(bool)
            long = session & recent_up & (df.low <= orb_hi) & (c > orb_hi)
            short = session & recent_dn & (df.high >= orb_lo) & (c < orb_lo)
        score[long] = 1.0
        score[short] = -1.0
        eligible = score.ne(0)
        return score, eligible

    if family == "previous_day_break_retest":
        prev_hi, prev_lo = _previous_day_levels(df)
        tol = float(p["retest_atr"]) * a
        up_break = c > prev_hi
        dn_break = c < prev_lo
        recent_up = up_break.rolling(5, min_periods=1).max().astype(bool)
        recent_dn = dn_break.rolling(5, min_periods=1).max().astype(bool)
        long = recent_up & (df.low <= prev_hi + tol) & (c > prev_hi)
        short = recent_dn & (df.high >= prev_lo - tol) & (c < prev_lo)
        score[long] = 1.0
        score[short] = -1.0
        eligible = score.ne(0)
        return score, eligible

    raise ValueError(family)


def evaluate(df: pd.DataFrame, family: str, params: dict, hold: int):
    score, eligible = score_extra(df, family, params)
    entry = df.open.shift(-1)
    exit_ = df.open.shift(-(1 + hold))
    fwd = exit_ / entry - 1.0
    x = pd.DataFrame({"score": score, "eligible": eligible, "fwd": fwd}, index=df.index)
    start = pd.Timestamp(base.START, tz="UTC")
    end = pd.Timestamp(base.DEV_END, tz="UTC")
    x = x[(x.index >= start) & (x.index < end) & x.eligible & x.score.notna() & x.fwd.notna()].copy()
    x["fold"] = base.fold_ids(x.index)
    exit_ts = pd.Series(df.index, index=df.index).shift(-(1 + hold)).reindex(x.index)
    same = [
        base.fold_ids(pd.DatetimeIndex([t]))[0] == base.fold_ids(pd.DatetimeIndex([et]))[0]
        for t, et in zip(x.index, exit_ts)
    ]
    x = x[same]

    fold_rho = []
    for _, g in x.groupby("fold"):
        r = base.spearman(g.score, g.fwd)
        if np.isfinite(r):
            fold_rho.append(r)
    state_med = float(np.median(fold_rho)) if fold_rho else np.nan
    state_pos = float(np.mean(np.asarray(fold_rho) > 0)) if fold_rho else 0.0

    trades = []
    next_allowed = pd.Timestamp.min.tz_localize("UTC")
    for t, row in x.iterrows():
        if t < next_allowed:
            continue
        side = 1.0 if row.score > 0 else -1.0
        trades.append((t, int(row["fold"]), side * float(row.fwd) * 10000.0))
        loc = df.index.get_loc(t)
        next_allowed = df.index[min(loc + 1 + hold, len(df) - 1)]
    if not trades:
        return None

    tr = pd.DataFrame(trades, columns=["t", "fold", "gross"]).set_index("t")
    out = {
        "family": family,
        "params": params | {"hold": hold},
        "events": len(x),
        "trades": len(tr),
        "state_folds": len(fold_rho),
        "state_median_rho": state_med,
        "state_positive_fold_fraction": state_pos,
    }
    for cost in base.COSTS:
        vals = tr.gross - cost
        exps, pfs = [], []
        for _, g in tr.assign(net=vals).groupby("fold"):
            exps.append(float(g.net.mean()))
            pfs.append(base.pf(g.net))
        out[f"net_{cost:g}_median_fold"] = float(np.median(exps)) if exps else np.nan
        out[f"pf_{cost:g}_median_fold"] = float(np.median(pfs)) if pfs else np.nan
        out[f"posfold_{cost:g}"] = float(np.mean(np.asarray(exps) > 0)) if exps else 0.0
        out[f"mean_{cost:g}"] = float(vals.mean())
    out["reversed_mean_primary"] = float((-tr.gross - base.PRIMARY).mean())
    out["dev_prelim_pass"] = bool(
        len(fold_rho) >= 12
        and state_med > 0
        and state_pos >= 0.60
        and len(tr) >= 80
        and out["net_5_median_fold"] > 0
        and out["pf_5_median_fold"] > 1
        and out["posfold_5"] >= 0.60
        and out["net_10_median_fold"] >= 0
        and out["mean_5"] > out["reversed_mean_primary"]
    )
    return out


def trials():
    for lb, h in itertools.product([16, 32], [4, 8, 12]):
        yield "youtube_three_am_london_ifvg_proxy", "M15", {"sweep_lookback": lb}, h
    for r, h in itertools.product([1, 2, 4], [4, 8, 16]):
        yield "asian_range_london_breakout_retest", "M15", {"retest_bars": r}, h
    for m, h in itertools.product([2, 4], [4, 8, 16]):
        yield "tokyo_london_ny_range_push_reversal", "M15", {"micro_break_lookback": m}, h
    for tf, pa, r, h in itertools.product(["M15", "H1"], [0.25, 0.5, 1.0], [50, 55], [4, 8, 16]):
        yield "reddit_ema_21_50_pullback", tf, {"pullback_atr": pa, "rsi_threshold": r}, h
    for r, s, h in itertools.product([52, 55, 60], ["london", "new_york", "both"], [4, 8]):
        yield "reddit_session_ema_9_21_rsi7", "M15", {"rsi_threshold": r, "session": s}, h
    for session, h in itertools.product(["london", "new_york"], [4, 8, 16]):
        yield "reddit_fifteen_minute_orb", "M15", {"session": session, "entry_mode": "direct", "retest_window_bars": 1}, h
    for session, rw, h in itertools.product(["london", "new_york"], [1, 2, 4], [4, 8, 16]):
        yield "reddit_fifteen_minute_orb", "M15", {"session": session, "entry_mode": "retest", "retest_window_bars": rw}, h
    for tf, tol, h in itertools.product(["M15", "H1"], [0.1, 0.25, 0.5], [4, 8, 16]):
        yield "previous_day_break_retest", tf, {"retest_atr": tol}, h


def clean(value):
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    d = Path(args.data_dir)
    frames = {
        tf: base.load_csv(d / f"XAUUSD_{tf}_2010_2026.csv")
        for tf in ["M15", "H1"]
    }
    integrity = {
        tf: {
            "rows": len(df),
            "start": str(df.index.min()),
            "end": str(df.index.max()),
            "median_bars_per_day": float(pd.Series(1, index=df.index).groupby(df.index.floor("D")).sum().median()),
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
            results.append({
                "family": family,
                "timeframe": timeframe,
                "params": params | {"hold": hold},
                "error": repr(exc),
                "dev_prelim_pass": False,
            })

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
        "protocol": "gold-strategy-discovery-v1.1-community",
        "trial_count": len(results),
        "error_count": sum("error" in r for r in results),
        "prelim_pass_count": sum(bool(r.get("dev_prelim_pass")) for r in valid),
        "integrity": integrity,
        "top_development": valid[:50],
        "all_trials": results,
        "holdout_opened": False,
        "claims": {"verified_oos": False, "profitable_edge_established": False, "live_enabled": False},
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(clean(payload), indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(clean({k: payload[k] for k in ["trial_count", "error_count", "prelim_pass_count", "integrity", "top_development", "holdout_opened"]}), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
