from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


TZ = "America/New_York"
SETUPS = ("breakout", "celery_booby_trap", "onion", "fade")


def _jsonable(x):
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    return x


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get("state_scoring_enabled") is not True:
        raise SystemExit("state scoring not enabled by frozen config")
    if cfg["historical_splits"].get("validation_opened") is not False:
        raise SystemExit("locked validation flag is not sealed")
    return cfg


def load_standardized(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        d = pd.read_parquet(path)
    else:
        d = pd.read_csv(path)
    rename = {c: c.lower() for c in d.columns}
    d = d.rename(columns=rename)
    ts_col = "timestamp" if "timestamp" in d.columns else "datetime"
    required = {ts_col, "open", "high", "low", "close"}
    missing = required.difference(d.columns)
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    ts = pd.to_datetime(d[ts_col], utc=True, errors="coerce")
    out = pd.DataFrame(
        {
            "timestamp": ts,
            "open": pd.to_numeric(d["open"], errors="coerce"),
            "high": pd.to_numeric(d["high"], errors="coerce"),
            "low": pd.to_numeric(d["low"], errors="coerce"),
            "close": pd.to_numeric(d["close"], errors="coerce"),
        }
    ).dropna()
    out = out.drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    out = out[(out.high >= out[["open", "close"]].max(axis=1)) & (out.low <= out[["open", "close"]].min(axis=1))]
    return out.set_index("timestamp")


def resample_bars(minute: pd.DataFrame, freq: str, min_count: int) -> pd.DataFrame:
    local = minute.copy()
    local.index = local.index.tz_convert(TZ)
    agg = local.resample(freq, label="right", closed="left", origin="start_day").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        m1_count=("close", "count"),
    )
    agg = agg.dropna(subset=["open", "high", "low", "close"])
    agg = agg[agg.m1_count >= min_count].copy()
    agg.index.name = "timestamp"
    return agg


def atr14(d: pd.DataFrame) -> pd.Series:
    prev = d.close.shift(1)
    tr = pd.concat(
        [
            d.high - d.low,
            (d.high - prev).abs(),
            (d.low - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(14, min_periods=14).mean()


def build_context(minute: pd.DataFrame, exec_freq: str, exec_min_count: int) -> pd.DataFrame:
    e = resample_bars(minute, exec_freq, exec_min_count)
    h4 = resample_bars(minute, "4h", 120)
    day = resample_bars(minute, "1D", 600)

    e["atr"] = atr14(e)
    e["body_frac"] = (e.close - e.open).abs() / (e.high - e.low).replace(0, np.nan)

    h4["h4_dir"] = np.sign(h4.close - h4.open).astype(float)
    h4["h4_roll20_high"] = h4.high.rolling(20, min_periods=20).max()
    h4["h4_roll20_low"] = h4.low.rolling(20, min_periods=20).min()
    day["day_dir"] = np.sign(day.close - day.open).astype(float)

    er = e.reset_index().sort_values("timestamp")
    hr = h4.reset_index()[["timestamp", "h4_dir", "h4_roll20_high", "h4_roll20_low"]].sort_values("timestamp")
    dr = day.reset_index()[["timestamp", "day_dir"]].sort_values("timestamp")
    er = pd.merge_asof(er, hr, on="timestamp", direction="backward", allow_exact_matches=True)
    er = pd.merge_asof(er, dr, on="timestamp", direction="backward", allow_exact_matches=True)
    er["bias"] = np.where(
        (er.day_dir == 1) & (er.h4_dir == 1),
        1,
        np.where((er.day_dir == -1) & (er.h4_dir == -1), -1, 0),
    )
    er["ny_date"] = er.timestamp.dt.date.astype(str)
    er["ny_time"] = er.timestamp.dt.strftime("%H:%M")
    return er.set_index("timestamp")


def session_mask(d: pd.DataFrame, start: str, end: str) -> pd.Series:
    return (d.ny_time >= start) & (d.ny_time <= end) & (d.index.dayofweek < 5)


def range_fields(d: pd.DataFrame, lookback: int) -> pd.DataFrame:
    x = pd.DataFrame(index=d.index)
    x["range_high"] = d.high.shift(1).rolling(lookback, min_periods=lookback).max()
    x["range_low"] = d.low.shift(1).rolling(lookback, min_periods=lookback).min()
    x["range_body_frac_median"] = d.body_frac.shift(1).rolling(lookback, min_periods=lookback).median()
    x["range_width"] = x.range_high - x.range_low
    return x


def event_masks(d: pd.DataFrame, cfg: dict, lookback: int | None) -> dict[str, pd.Series]:
    sess = session_mask(
        d,
        cfg["sessions"]["state_operationalization"]["start"],
        cfg["sessions"]["state_operationalization"]["end"],
    )
    eligible = sess & (d.bias != 0) & d.atr.notna()
    masks: dict[str, pd.Series] = {}

    if lookback is not None:
        rf = range_fields(d, lookback)
        max_width = next(
            x["max_width_atr"]
            for x in cfg["state_operationalization"]["range_proxy_grid"]
            if int(x["lookback_bars"]) == int(lookback)
        )
        width_ok = rf.range_width <= max_width * d.atr
        wick_ok = rf.range_body_frac_median <= cfg["state_operationalization"]["range_wickiness_filter"]["max_median_body_fraction"]
        range_ok = width_ok & wick_ok
        breakout_long = eligible & (d.bias == 1) & range_ok & (d.close > rf.range_high)
        breakout_short = eligible & (d.bias == -1) & range_ok & (d.close < rf.range_low)
        breakout = breakout_long | breakout_short
        masks["breakout"] = breakout

        prior_break = breakout.shift(1, fill_value=False)
        prior_bias = d.bias.shift(1)
        same_bias = d.bias == prior_bias
        prior_rf = rf.shift(1)
        celery_long = eligible & prior_break & same_bias & (d.bias == 1) & (d.close > prior_rf.range_high)
        celery_short = eligible & prior_break & same_bias & (d.bias == -1) & (d.close < prior_rf.range_low)
        masks["celery_booby_trap"] = celery_long | celery_short

    bullish = d.close > d.open
    bearish = d.close < d.open
    impulse_long = bullish.shift(3, fill_value=False) & bullish.shift(2, fill_value=False)
    impulse_short = bearish.shift(3, fill_value=False) & bearish.shift(2, fill_value=False)
    onion_long = (
        eligible
        & (d.bias == 1)
        & impulse_long
        & bearish.shift(1, fill_value=False)
        & bullish
        & (d.low <= d.low.shift(1))
        & (d.low <= d.low.shift(2))
    )
    onion_short = (
        eligible
        & (d.bias == -1)
        & impulse_short
        & bullish.shift(1, fill_value=False)
        & bearish
        & (d.high >= d.high.shift(1))
        & (d.high >= d.high.shift(2))
    )
    masks["onion"] = onion_long | onion_short

    proximity = 0.15 * d.atr
    fade_short = (
        eligible
        & (d.bias == 1)
        & d.h4_roll20_high.notna()
        & ((d.close - d.h4_roll20_high).abs() <= proximity)
        & (d.high <= d.high.shift(1))
        & bearish
    )
    fade_long = (
        eligible
        & (d.bias == -1)
        & d.h4_roll20_low.notna()
        & ((d.close - d.h4_roll20_low).abs() <= proximity)
        & (d.low >= d.low.shift(1))
        & bullish
    )
    masks["fade"] = fade_short | fade_long
    return masks


def family_direction(d: pd.DataFrame, setup: str) -> pd.Series:
    return -d.bias if setup == "fade" else d.bias


def forward_state(d: pd.DataFrame, direction: pd.Series, horizon: int) -> pd.Series:
    return direction * (d.close.shift(-horizon) - d.close) / d.atr


def signflip_p(values: np.ndarray, epochs: int, seed: int) -> float:
    v = values[np.isfinite(values)]
    if len(v) == 0:
        return 1.0
    observed = float(np.mean(v))
    if observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    ge = 0
    chunk = 2000
    done = 0
    while done < epochs:
        n = min(chunk, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(v)))
        null = (signs * v).mean(axis=1)
        ge += int(np.sum(null >= observed))
        done += n
    return (ge + 1.0) / (epochs + 1.0)


def bh_qvalues(pvals: Iterable[float]) -> np.ndarray:
    p = np.asarray(list(pvals), dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0, 1)
    out = np.empty(n, dtype=float)
    out[order] = q
    return out


def score_cell(
    d: pd.DataFrame,
    mask: pd.Series,
    setup: str,
    symbol: str,
    timeframe: str,
    lookback: int | None,
    cfg: dict,
) -> dict:
    direction = family_direction(d, setup)
    horizons = [int(x) for x in cfg["state_targets"]["forward_horizons_execution_bars"]]
    event_idx = d.index[mask.fillna(False)]
    result = {
        "cell_id": f"{symbol}|{timeframe}|{setup}|range={lookback if lookback is not None else 'na'}",
        "symbol": symbol,
        "timeframe": timeframe,
        "setup": setup,
        "range_lookback": lookback,
        "events": int(len(event_idx)),
        "active_days": int(d.loc[event_idx, "ny_date"].nunique()) if len(event_idx) else 0,
        "horizons": {},
    }
    epochs = int(cfg["state_gate"]["permutation_epochs"])

    for h in horizons:
        all_state = forward_state(d, direction, h)
        bench_frame = pd.DataFrame(
            {
                "ny_date": d.ny_date,
                "bias": d.bias,
                "eligible": session_mask(
                    d,
                    cfg["sessions"]["state_operationalization"]["start"],
                    cfg["sessions"]["state_operationalization"]["end"],
                ) & (d.bias != 0) & d.atr.notna(),
                "state": all_state,
            },
            index=d.index,
        )
        eligible_bench = bench_frame[bench_frame.eligible].dropna(subset=["state"])
        daily_bench = eligible_bench.groupby(["ny_date", "bias"], sort=False).state.median()

        events = pd.DataFrame(
            {
                "ny_date": d.loc[event_idx, "ny_date"],
                "bias": d.loc[event_idx, "bias"],
                "event_state": all_state.loc[event_idx],
            },
            index=event_idx,
        ).dropna(subset=["event_state"])
        if events.empty:
            daily = pd.Series(dtype=float)
        else:
            keys = list(zip(events.ny_date, events.bias))
            events["benchmark"] = [daily_bench.get(k, np.nan) for k in keys]
            events["excess"] = events.event_state - events.benchmark
            daily = events.dropna(subset=["excess"]).groupby("ny_date").excess.mean()

        seed = int.from_bytes(hashlib.sha256(f"{result['cell_id']}|{h}".encode()).digest()[:8], "big") % (2**32 - 1)
        p = signflip_p(daily.to_numpy(float), epochs, seed)
        result["horizons"][str(h)] = {
            "event_count_scorable": int(events.event_state.notna().sum()),
            "active_days_scorable": int(len(daily)),
            "mean_daily_excess": float(daily.mean()) if len(daily) else np.nan,
            "median_daily_excess": float(daily.median()) if len(daily) else np.nan,
            "positive_day_fraction": float((daily > 0).mean()) if len(daily) else np.nan,
            "signflip_p": float(p),
            "reverse_control_mean_daily_excess": float((-daily).mean()) if len(daily) else np.nan,
        }
    return result


def apply_gate(cells: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    primary_h = str(cfg["state_targets"]["primary_fdr_horizon_execution_bars"])
    q = bh_qvalues(c["horizons"][primary_h]["signflip_p"] for c in cells)
    for c, qi in zip(cells, q):
        c["primary_fdr_q"] = float(qi)
        positive_h = sum(
            1
            for m in c["horizons"].values()
            if np.isfinite(m["median_daily_excess"]) and m["median_daily_excess"] > 0
        )
        primary = c["horizons"][primary_h]
        c["positive_horizons"] = int(positive_h)
        c["raw_state_pass"] = bool(
            c["events"] >= cfg["state_gate"]["minimum_events"]
            and c["active_days"] >= cfg["state_gate"]["minimum_active_days"]
            and primary["median_daily_excess"] is not None
            and np.isfinite(primary["median_daily_excess"])
            and primary["median_daily_excess"] > 0
            and primary["positive_day_fraction"] >= cfg["state_gate"]["minimum_positive_day_fraction"]
            and positive_h >= cfg["state_gate"]["minimum_positive_horizons"]
            and c["primary_fdr_q"] <= cfg["state_gate"]["fdr_q_max"]
        )

    candidates: list[dict] = []
    for c in cells:
        if not c["raw_state_pass"] or c["timeframe"] != cfg["timeframes"]["execution_primary"]:
            c["state_candidate"] = False
            continue
        peers = [
            p
            for p in cells
            if p["symbol"] == c["symbol"]
            and p["setup"] == c["setup"]
            and p["range_lookback"] == c["range_lookback"]
            and p["timeframe"] in cfg["timeframes"]["execution_robustness"]
        ]
        robust = any(
            np.isfinite(p["horizons"][primary_h]["median_daily_excess"])
            and p["horizons"][primary_h]["median_daily_excess"] > 0
            for p in peers
        )
        c["robustness_positive"] = bool(robust)
        c["state_candidate"] = bool(robust)
        if robust:
            candidates.append(c)
    return cells, candidates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/time_to_eat_nick_stewart_v1.json")
    ap.add_argument("--xau", required=True)
    ap.add_argument("--nq", required=True)
    ap.add_argument("--es", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    paths = {"XAUUSD": Path(args.xau), "NQ": Path(args.nq), "ES": Path(args.es)}
    freq_map = {"15m": ("15min", 8), "30m": ("30min", 15), "1H": ("1h", 30)}
    cells: list[dict] = []
    data_summary = {}

    for symbol, path in paths.items():
        minute = load_standardized(path)
        data_summary[symbol] = {
            "rows": int(len(minute)),
            "start": minute.index.min().isoformat(),
            "end": minute.index.max().isoformat(),
        }
        for tf in [cfg["timeframes"]["execution_primary"], *cfg["timeframes"]["execution_robustness"]]:
            freq, min_count = freq_map[tf]
            d = build_context(minute, freq, min_count)

            for rg in cfg["state_operationalization"]["range_proxy_grid"]:
                lookback = int(rg["lookback_bars"])
                masks = event_masks(d, cfg, lookback)
                for setup in ("breakout", "celery_booby_trap"):
                    cells.append(score_cell(d, masks[setup], setup, symbol, tf, lookback, cfg))

            base_masks = event_masks(d, cfg, None)
            for setup in ("onion", "fade"):
                cells.append(score_cell(d, base_masks[setup], setup, symbol, tf, None, cfg))

    cells, candidates = apply_gate(cells, cfg)
    result = {
        "protocol_id": cfg["protocol_id"],
        "stage": "development_state_only",
        "development_period": cfg["historical_splits"]["development_open"],
        "locked_validation_period": cfg["historical_splits"]["locked_historical_validation"],
        "holdout_opened": False,
        "economic_scoring_run": False,
        "data_summary": data_summary,
        "cell_count": len(cells),
        "raw_state_pass_count": int(sum(bool(c["raw_state_pass"]) for c in cells)),
        "state_candidate_count": len(candidates),
        "state_candidates": [c["cell_id"] for c in candidates],
        "cells": cells,
        "claims": {
            "claimed_75pct_win_rate_verified": False,
            "profitable_edge_established": False,
            "verified_future_oos": False,
            "leverage_authorized": False,
            "live_enabled": False,
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("cell_count", "raw_state_pass_count", "state_candidate_count", "state_candidates")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
