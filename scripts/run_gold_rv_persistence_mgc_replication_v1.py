from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


NY = ZoneInfo("America/New_York")


def clean(x):
    if x is pd.NaT or x is pd.NA:
        return None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    return x


def stable_seed(namespace: str, key: str) -> int:
    digest = hashlib.sha256(f"{namespace}|{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**32 - 1)


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    xs = pd.Series(np.asarray(x, dtype=float))
    ys = pd.Series(np.asarray(y, dtype=float))
    m = xs.notna() & ys.notna() & np.isfinite(xs) & np.isfinite(ys)
    if int(m.sum()) < 3:
        return float("nan")
    xr = xs[m].rank(method="average")
    yr = ys[m].rank(method="average")
    return float(xr.corr(yr))


def positive_signflip_p(values: np.ndarray, epochs: int, seed: int) -> float:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return 1.0
    observed = float(np.median(v))
    if observed <= 0:
        return 1.0
    rng = np.random.default_rng(seed)
    ge = 0
    done = 0
    chunk = 1000
    while done < epochs:
        n = min(chunk, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(v)))
        stats = np.median(signs * v, axis=1)
        ge += int(np.sum(stats >= observed - 1e-15))
        done += n
    return float((ge + 1) / (epochs + 1))


def load_mgc(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(d.columns)
    if missing:
        raise ValueError(f"missing MGC columns: {sorted(missing)}")
    d["time"] = pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    if "volume" in d.columns:
        d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
    d = d.dropna(subset=["time", "open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[(d.high >= d[["open", "close"]].max(axis=1)) & (d.low <= d[["open", "close"]].min(axis=1))]
    d = d.drop_duplicates("time", keep="last").sort_values("time").set_index("time")
    return d


def exact_window(d: pd.DataFrame, start: pd.Timestamp, periods: int) -> pd.DataFrame | None:
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    x = d.reindex(idx)
    if x[["open", "high", "low", "close"]].isna().any().any():
        return None
    return x


def realized_vol(prices: np.ndarray) -> float:
    p = np.asarray(prices, dtype=float)
    if len(p) < 2 or np.any(~np.isfinite(p)) or np.any(p <= 0):
        return float("nan")
    r = np.diff(np.log(p))
    rv2 = float(np.sum(r * r))
    if not np.isfinite(rv2) or rv2 <= 0:
        return float("nan")
    return float(np.sqrt(rv2))


def raw_observation(d: pd.DataFrame, t0: pd.Timestamp) -> dict | None:
    pre = exact_window(d, t0 - pd.Timedelta(minutes=60), 60)
    fut = exact_window(d, t0, 60)
    pre_prices = exact_window(d, t0 - pd.Timedelta(minutes=61), 61)
    if pre is None or fut is None or pre_prices is None:
        return None

    pre_rv = realized_vol(pre_prices.close.to_numpy(float))
    future_prices = np.concatenate([[float(pre.close.iloc[-1])], fut.close.to_numpy(float)])
    future_rv = realized_vol(future_prices)
    future_range = float(fut.high.max() - fut.low.min())
    if not np.isfinite(pre_rv) or not np.isfinite(future_rv) or future_range <= 0:
        return None

    local = t0.tz_convert(NY)
    return {
        "t0_utc": t0,
        "ny_date": str(local.date()),
        "anchor_hour": int(local.hour),
        "pre_rv": pre_rv,
        "future_rv": future_rv,
        "future_range": future_range,
    }


def build_observations(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    grid = cfg["observation_grid"]
    hours = set(int(x) for x in grid["anchor_hours_local"])
    start = pd.Timestamp(cfg["source"]["available_start"], tz="UTC")
    end = pd.Timestamp(cfg["source"]["replication_end_exclusive"], tz="UTC")

    candidates = d.index[(d.index >= start) & (d.index < end)]
    local = candidates.tz_convert(NY)
    mask = (
        (local.weekday < 5)
        & (local.minute == int(grid["anchor_minute"]))
        & (local.second == 0)
        & np.isin(local.hour, list(hours))
    )
    anchors = candidates[mask]

    rows = []
    for t0 in anchors:
        obs = raw_observation(d, pd.Timestamp(t0))
        if obs is not None:
            rows.append(obs)
    raw = pd.DataFrame(rows)
    if raw.empty:
        raise ValueError("no valid raw MGC anchor observations")
    raw = raw.sort_values(["anchor_hour", "t0_utc"]).reset_index(drop=True)

    lookback = int(grid["same_clock_baseline_lookback_observations"])
    for source, dest in (
        ("pre_rv", "baseline_pre_rv"),
        ("future_rv", "baseline_future_rv"),
        ("future_range", "baseline_future_range"),
    ):
        raw[dest] = raw.groupby("anchor_hour", group_keys=False)[source].transform(
            lambda s: s.shift(1).rolling(lookback, min_periods=lookback).median()
        )

    raw["pre_rv_ratio"] = raw.pre_rv / raw.baseline_pre_rv
    raw["future_rv_ratio"] = raw.future_rv / raw.baseline_future_rv
    raw["future_range_ratio"] = raw.future_range / raw.baseline_future_range
    raw = raw.replace([np.inf, -np.inf], np.nan)
    raw = raw.dropna(subset=["pre_rv_ratio", "future_rv_ratio", "future_range_ratio"])
    raw = raw[(raw.pre_rv_ratio > 0) & (raw.future_rv_ratio > 0) & (raw.future_range_ratio > 0)]
    if raw.empty:
        raise ValueError("no MGC observations after causal same-clock baseline warmup")
    return raw.sort_values("t0_utc").reset_index(drop=True)


def daily_effects(obs: pd.DataFrame, target: str, min_anchors: int) -> pd.DataFrame:
    rows = []
    for day, g in obs.groupby("ny_date", sort=True):
        q = g.dropna(subset=["pre_rv_ratio", target])
        if len(q) < min_anchors:
            continue
        eff = spearman(q.pre_rv_ratio.to_numpy(float), q[target].to_numpy(float))
        if np.isfinite(eff):
            rows.append({"ny_date": day, "n": int(len(q)), "effect": float(eff)})
    return pd.DataFrame(rows)


def anchor_effects(obs: pd.DataFrame, min_n: int) -> list[dict]:
    rows = []
    for hour, g in obs.groupby("anchor_hour", sort=True):
        q = g.dropna(subset=["pre_rv_ratio", "future_rv_ratio"])
        eff = spearman(q.pre_rv_ratio.to_numpy(float), q.future_rv_ratio.to_numpy(float)) if len(q) >= min_n else np.nan
        rows.append({
            "anchor_hour": int(hour),
            "n": int(len(q)),
            "effect": eff,
            "eligible": bool(len(q) >= min_n),
        })
    return rows


def roll_diagnostics(d: pd.DataFrame, daily: pd.DataFrame) -> dict:
    work = d[["close"]].copy()
    work["prev_time"] = work.index.to_series().shift(1)
    work["prev_close"] = work.close.shift(1)
    one_minute = (work.index.to_series() - work.prev_time) == pd.Timedelta(minutes=1)
    work["abs_log_return"] = np.where(
        one_minute & (work.prev_close > 0) & (work.close > 0),
        np.abs(np.log(work.close / work.prev_close)),
        np.nan,
    )
    top = work.dropna(subset=["abs_log_return"]).nlargest(5, "abs_log_return")
    daily_map = daily.set_index("ny_date")["effect"].to_dict() if len(daily) else {}
    rows = []
    for ts, r in top.iterrows():
        ny_date = str(pd.Timestamp(ts).tz_convert(NY).date())
        rows.append({
            "timestamp_utc": pd.Timestamp(ts),
            "ny_date": ny_date,
            "abs_log_return": float(r.abs_log_return),
            "daily_primary_effect_if_scorable": daily_map.get(ny_date),
        })
    return {
        "max_abs_one_minute_log_return": float(top.abs_log_return.max()) if len(top) else np.nan,
        "top_five": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--mgc", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("protocol_status") != "independent_instrument_replication_frozen":
        raise SystemExit("replication protocol is not frozen")
    if cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("economics must remain disabled")
    if cfg["parent_candidate"]["candidate_id"] != "rv_persistence":
        raise SystemExit("unexpected parent candidate")
    if cfg["parent_candidate"]["frozen_sign"] != "positive":
        raise SystemExit("unexpected frozen sign")

    d = load_mgc(Path(args.mgc))
    source_start = pd.Timestamp(cfg["source"]["available_start"], tz="UTC")
    source_end = pd.Timestamp(cfg["source"]["replication_end_exclusive"], tz="UTC")
    if d.index.min() < source_start:
        raise SystemExit("input contains pre-frozen-source-start data")
    if d.index.max() >= source_end:
        raise SystemExit("input contains post-2023 data")
    if d.index.max() < pd.Timestamp("2023-12-28T00:00:00Z"):
        raise SystemExit("2023 MGC coverage ends too early")

    obs = build_observations(d, cfg)
    min_anchors = int(cfg["observation_grid"]["minimum_daily_anchor_count_for_inference"])
    daily = daily_effects(obs, "future_rv_ratio", min_anchors)
    secondary = daily_effects(obs, "future_range_ratio", min_anchors)
    if daily.empty:
        raise SystemExit("no scorable replication dates")

    effects = daily.effect.to_numpy(float)
    primary_effect = float(np.median(effects))
    positive_fraction = float(np.mean(effects > 0))
    p = positive_signflip_p(
        effects,
        int(cfg["statistics"]["permutation_epochs"]),
        stable_seed(cfg["statistics"]["random_seed_namespace"], cfg["parent_candidate"]["candidate_id"]),
    )

    secondary_effects = secondary.effect.to_numpy(float) if len(secondary) else np.array([], dtype=float)
    secondary_median = float(np.median(secondary_effects)) if len(secondary_effects) else np.nan

    dates = pd.to_datetime(daily.ny_date)
    first = daily.loc[dates < pd.Timestamp("2023-07-01"), "effect"].to_numpy(float)
    second = daily.loc[dates >= pd.Timestamp("2023-07-01"), "effect"].to_numpy(float)
    first_median = float(np.median(first)) if len(first) else np.nan
    second_median = float(np.median(second)) if len(second) else np.nan

    anchor_rows = anchor_effects(obs, int(cfg["replication_gate"]["minimum_anchor_slot_observations"]))
    positive_anchor_slots = sum(
        1 for r in anchor_rows if r["eligible"] and np.isfinite(r["effect"]) and r["effect"] > 0
    )

    gate = cfg["replication_gate"]
    passed = (
        len(daily) >= int(gate["minimum_scorable_dates"])
        and primary_effect >= float(gate["minimum_median_daily_effect"])
        and positive_fraction >= float(gate["minimum_daily_positive_fraction"])
        and positive_anchor_slots >= int(gate["minimum_positive_anchor_slots"])
        and np.isfinite(first_median) and first_median > 0
        and np.isfinite(second_median) and second_median > 0
        and np.isfinite(secondary_median) and secondary_median > 0
        and p <= float(gate["primary_p_max"])
    )

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "independent_source_instrument_state_replication",
        "candidate_id": cfg["parent_candidate"]["candidate_id"],
        "candidate_sign": cfg["parent_candidate"]["frozen_sign"],
        "replication_classification": cfg["replication_classification"],
        "economic_scoring_run": False,
        "directional_scoring_run": False,
        "future_oos_claim": False,
        "input_rows": int(len(d)),
        "input_start": d.index.min().isoformat(),
        "input_end": d.index.max().isoformat(),
        "first_scorable_anchor_utc": obs.t0_utc.min(),
        "last_scorable_anchor_utc": obs.t0_utc.max(),
        "replication_observations": int(len(obs)),
        "scorable_dates": int(len(daily)),
        "primary_median_daily_spearman": primary_effect,
        "daily_positive_fraction": positive_fraction,
        "one_sided_positive_signflip_p": p,
        "first_half_dates": int(len(first)),
        "first_half_median_daily_spearman": first_median,
        "second_half_dates": int(len(second)),
        "second_half_median_daily_spearman": second_median,
        "secondary_range_median_daily_spearman": secondary_median,
        "anchor_effects": anchor_rows,
        "positive_anchor_slots": int(positive_anchor_slots),
        "roll_and_data_quality_diagnostics": roll_diagnostics(d, daily),
        "replication_pass": bool(passed),
        "claims": {
            "independent_source_instrument_state_replication_passed": bool(passed),
            "directional_edge_established": False,
            "executable_edge_established": False,
            "profitable_edge_established": False,
            "verified_future_oos": False,
            "leverage_authorized": False,
            "live_enabled": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(output), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "first_scorable_anchor_utc": clean(output["first_scorable_anchor_utc"]),
        "replication_observations": output["replication_observations"],
        "scorable_dates": output["scorable_dates"],
        "primary_median_daily_spearman": output["primary_median_daily_spearman"],
        "daily_positive_fraction": output["daily_positive_fraction"],
        "one_sided_positive_signflip_p": output["one_sided_positive_signflip_p"],
        "positive_anchor_slots": output["positive_anchor_slots"],
        "replication_pass": output["replication_pass"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
