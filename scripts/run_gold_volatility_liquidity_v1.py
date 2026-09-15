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
UTC = ZoneInfo("UTC")


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


def bh_qvalues(p_values: list[float]) -> list[float]:
    p = np.asarray(p_values, dtype=float)
    p = np.where(np.isfinite(p), p, 1.0)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0.0, 1.0)
    out = np.empty(n, dtype=float)
    out[order] = q
    return out.tolist()


def signflip_median_p(values: np.ndarray, epochs: int, seed: int) -> float:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return 1.0
    observed = abs(float(np.median(v)))
    rng = np.random.default_rng(seed)
    ge = 0
    done = 0
    chunk = 1000
    while done < epochs:
        n = min(chunk, epochs - done)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(n, len(v)))
        stats = np.abs(np.median(signs * v, axis=1))
        ge += int(np.sum(stats >= observed - 1e-15))
        done += n
    return float((ge + 1) / (epochs + 1))


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x = x[m]
    y = y[m]
    if len(x) < 3 or np.std(x) <= 0 or np.std(y) <= 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    x = pd.Series(np.asarray(x, dtype=float))
    y = pd.Series(np.asarray(y, dtype=float))
    m = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
    if int(m.sum()) < 3:
        return float("nan")
    return pearson(x[m].rank(method="average").to_numpy(float), y[m].rank(method="average").to_numpy(float))


def partial_spearman(x: np.ndarray, y: np.ndarray, control: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(control, dtype=float)
    m = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x = x[m]
    y = y[m]
    z = z[m]
    if len(x) < 4:
        return float("nan")
    xr = pd.Series(x).rank(method="average").to_numpy(float)
    yr = pd.Series(y).rank(method="average").to_numpy(float)
    zr = pd.Series(z).rank(method="average").to_numpy(float)
    design = np.column_stack([np.ones(len(zr)), zr])
    bx, *_ = np.linalg.lstsq(design, xr, rcond=None)
    by, *_ = np.linalg.lstsq(design, yr, rcond=None)
    rx = xr - design @ bx
    ry = yr - design @ by
    return pearson(rx, ry)


def load_gold(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path)
    d.columns = [str(c).strip().lower() for c in d.columns]
    required = {"time", "open", "high", "low", "close", "spread_bps"}
    missing = required.difference(d.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    d["time"] = pd.to_datetime(d["time"], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close", "spread_bps"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["time", "open", "high", "low", "close", "spread_bps"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[d.spread_bps >= 0]
    d = d[(d.high >= d[["open", "close"]].max(axis=1)) & (d.low <= d[["open", "close"]].min(axis=1))]
    d = d.drop_duplicates("time", keep="last").sort_values("time").set_index("time")
    return d


def exact_window(d: pd.DataFrame, start: pd.Timestamp, periods: int) -> pd.DataFrame | None:
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    x = d.reindex(idx)
    if x[["open", "high", "low", "close", "spread_bps"]].isna().any().any():
        return None
    return x


def realized_vol(prices: np.ndarray) -> tuple[float, np.ndarray]:
    p = np.asarray(prices, dtype=float)
    if len(p) < 2 or np.any(~np.isfinite(p)) or np.any(p <= 0):
        return float("nan"), np.array([], dtype=float)
    r = np.diff(np.log(p))
    rv2 = float(np.sum(r * r))
    if not np.isfinite(rv2) or rv2 <= 0:
        return float("nan"), r
    return float(np.sqrt(rv2)), r


def raw_observation(d: pd.DataFrame, t0: pd.Timestamp) -> dict | None:
    pre = exact_window(d, t0 - pd.Timedelta(minutes=60), 60)
    fut = exact_window(d, t0, 60)
    pre_prices = exact_window(d, t0 - pd.Timedelta(minutes=61), 61)
    if pre is None or fut is None or pre_prices is None:
        return None

    pre_rv, pre_ret = realized_vol(pre_prices.close.to_numpy(float))
    future_prices = np.concatenate([[float(pre.close.iloc[-1])], fut.close.to_numpy(float)])
    future_rv, _ = realized_vol(future_prices)
    if not np.isfinite(pre_rv) or not np.isfinite(future_rv):
        return None

    total_pre_var = float(np.sum(pre_ret * pre_ret))
    neg_var = float(np.sum((pre_ret[pre_ret < 0]) ** 2))
    neg_share = neg_var / total_pre_var if total_pre_var > 0 else np.nan

    pre_range = float(pre.high.max() - pre.low.min())
    future_range = float(fut.high.max() - fut.low.min())
    recent_spread = float(pre.spread_bps.iloc[-15:].median())
    prior_spread = float(pre.spread_bps.iloc[:45].median())
    if pre_range <= 0 or future_range <= 0 or recent_spread <= 0 or prior_spread <= 0:
        return None

    local = t0.tz_convert(NY)
    return {
        "t0_utc": t0,
        "ny_date": str(local.date()),
        "year": int(local.year),
        "anchor_hour": int(local.hour),
        "pre_rv": pre_rv,
        "future_rv": future_rv,
        "pre_range": pre_range,
        "future_range": future_range,
        "pre15_spread": recent_spread,
        "spread_deterioration_ratio": recent_spread / prior_spread,
        "negative_semivariance_share": neg_share,
    }


def build_observations(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    grid = cfg["observation_grid"]
    hours = set(int(x) for x in grid["anchor_hours_local"])
    dev_start = pd.Timestamp(cfg["evidence_boundary"]["development_start"], tz="UTC")
    dev_end = pd.Timestamp(cfg["evidence_boundary"]["development_end_exclusive"], tz="UTC")

    candidates = d.index[(d.index >= dev_start) & (d.index < dev_end)]
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
        raise ValueError("no scorable raw observations")
    raw = raw.sort_values(["anchor_hour", "t0_utc"]).reset_index(drop=True)

    lookback = int(grid["same_clock_baseline_lookback_observations"])
    baseline_map = {
        "pre_rv": "baseline_pre_rv",
        "future_rv": "baseline_future_rv",
        "pre_range": "baseline_pre_range",
        "future_range": "baseline_future_range",
        "pre15_spread": "baseline_pre15_spread",
    }
    for source, dest in baseline_map.items():
        raw[dest] = raw.groupby("anchor_hour", group_keys=False)[source].transform(
            lambda s: s.shift(1).rolling(lookback, min_periods=lookback).median()
        )

    raw["pre_rv_ratio"] = raw.pre_rv / raw.baseline_pre_rv
    raw["future_rv_ratio"] = raw.future_rv / raw.baseline_future_rv
    raw["spread_level_ratio"] = raw.pre15_spread / raw.baseline_pre15_spread
    raw["pre_range_ratio"] = raw.pre_range / raw.baseline_pre_range
    raw["future_range_ratio"] = raw.future_range / raw.baseline_future_range

    ratio_cols = [
        "pre_rv_ratio",
        "future_rv_ratio",
        "spread_level_ratio",
        "spread_deterioration_ratio",
        "pre_range_ratio",
        "future_range_ratio",
        "negative_semivariance_share",
    ]
    raw = raw.replace([np.inf, -np.inf], np.nan)
    raw = raw.dropna(subset=["pre_rv_ratio", "future_rv_ratio", "future_range_ratio"])
    raw = raw[(raw.pre_rv_ratio > 0) & (raw.future_rv_ratio > 0) & (raw.future_range_ratio > 0)]
    for c in ratio_cols:
        if c not in raw.columns:
            raise ValueError(f"missing derived column {c}")
    return raw.sort_values("t0_utc").reset_index(drop=True)


def effect_for_frame(frame: pd.DataFrame, feature: str, target: str, control: str | None) -> float:
    x = pd.to_numeric(frame[feature], errors="coerce").to_numpy(float)
    y = pd.to_numeric(frame[target], errors="coerce").to_numpy(float)
    if control is None:
        return spearman(x, y)
    z = pd.to_numeric(frame[control], errors="coerce").to_numpy(float)
    return partial_spearman(x, y, z)


def daily_effects(obs: pd.DataFrame, feature: str, target: str, control: str | None, min_anchors: int) -> pd.DataFrame:
    rows = []
    for day, g in obs.groupby("ny_date", sort=True):
        cols = [feature, target] + ([control] if control else [])
        q = g.dropna(subset=cols)
        if len(q) < min_anchors:
            continue
        eff = effect_for_frame(q, feature, target, control)
        if np.isfinite(eff):
            rows.append({"ny_date": day, "year": int(str(day)[:4]), "n": int(len(q)), "effect": float(eff)})
    return pd.DataFrame(rows)


def anchor_effects(obs: pd.DataFrame, feature: str, target: str, control: str | None, min_n: int) -> list[dict]:
    out = []
    for hour, g in obs.groupby("anchor_hour", sort=True):
        cols = [feature, target] + ([control] if control else [])
        q = g.dropna(subset=cols)
        eff = effect_for_frame(q, feature, target, control) if len(q) >= min_n else np.nan
        out.append({"anchor_hour": int(hour), "n": int(len(q)), "effect": eff, "eligible": bool(len(q) >= min_n)})
    return out


def hypothesis_result(obs: pd.DataFrame, spec: dict, cfg: dict) -> dict:
    feature = spec["feature"]
    control = spec.get("control")
    min_anchors = int(cfg["observation_grid"]["minimum_daily_anchor_count_for_inference"])
    daily = daily_effects(obs, feature, "future_rv_ratio", control, min_anchors)
    secondary = daily_effects(obs, feature, "future_range_ratio", control, min_anchors)
    effects = daily.effect.to_numpy(float) if len(daily) else np.array([], dtype=float)
    primary = float(np.median(effects)) if len(effects) else np.nan
    sign = int(np.sign(primary)) if np.isfinite(primary) and primary != 0 else 0
    sign_fraction = float(np.mean(np.sign(effects) == sign)) if len(effects) and sign else 0.0

    year_effects = {}
    for year in (2021, 2022):
        q = daily[daily.year == year].effect.to_numpy(float) if len(daily) else np.array([], dtype=float)
        year_effects[str(year)] = {
            "dates": int(len(q)),
            "median_daily_effect": float(np.median(q)) if len(q) else np.nan,
        }

    anchor_rows = anchor_effects(
        obs,
        feature,
        "future_rv_ratio",
        control,
        int(cfg["state_gate"]["minimum_anchor_slot_observations"]),
    )
    agreeing_anchors = sum(
        1
        for r in anchor_rows
        if r["eligible"] and np.isfinite(r["effect"]) and sign != 0 and np.sign(r["effect"]) == sign
    )

    sec_effects = secondary.effect.to_numpy(float) if len(secondary) else np.array([], dtype=float)
    secondary_median = float(np.median(sec_effects)) if len(sec_effects) else np.nan

    epochs = int(cfg["statistics"]["permutation_epochs"])
    seed = stable_seed(cfg["statistics"]["random_seed_namespace"], spec["id"])
    p = signflip_median_p(effects, epochs, seed)

    return {
        "id": spec["id"],
        "feature": feature,
        "control": control,
        "scorable_dates": int(len(daily)),
        "primary_effect": primary,
        "primary_sign": sign,
        "daily_discovered_sign_fraction": sign_fraction,
        "primary_p": p,
        "year_effects": year_effects,
        "anchor_effects": anchor_rows,
        "anchors_with_primary_sign": int(agreeing_anchors),
        "secondary_target_median_daily_effect": secondary_median,
        "secondary_target_dates": int(len(secondary)),
        "reversed_effect_control": -primary if np.isfinite(primary) else np.nan,
    }


def apply_gates(results: list[dict], cfg: dict) -> list[dict]:
    qvals = bh_qvalues([float(r["primary_p"]) for r in results])
    gate = cfg["state_gate"]
    for r, q in zip(results, qvals):
        r["primary_fdr_q"] = float(q)
        sign = int(r["primary_sign"])
        years_agree = sign != 0 and all(
            np.isfinite(r["year_effects"][str(year)]["median_daily_effect"])
            and np.sign(r["year_effects"][str(year)]["median_daily_effect"]) == sign
            for year in (2021, 2022)
        )
        secondary_agrees = (
            sign != 0
            and np.isfinite(r["secondary_target_median_daily_effect"])
            and np.sign(r["secondary_target_median_daily_effect"]) == sign
        )
        r["both_years_share_primary_sign"] = bool(years_agree)
        r["secondary_target_shares_primary_sign"] = bool(secondary_agrees)
        passed = (
            r["scorable_dates"] >= int(gate["minimum_scorable_dates"])
            and abs(float(r["primary_effect"])) >= float(gate["minimum_abs_median_daily_effect"])
            and float(r["daily_discovered_sign_fraction"]) >= float(gate["minimum_daily_discovered_sign_fraction"])
            and r["anchors_with_primary_sign"] >= int(gate["minimum_anchor_slots_with_primary_sign"])
            and years_agree
            and secondary_agrees
            and q <= float(gate["fdr_q_max"])
        )
        r["state_pass"] = bool(passed)
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("state_scoring_enabled") is not True or cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("state/economic gate inconsistent with frozen protocol")
    if cfg["evidence_boundary"].get("validation_opened") is not False:
        raise SystemExit("locked validation is not sealed")

    gold = load_gold(Path(args.gold))
    dev_end = pd.Timestamp(cfg["evidence_boundary"]["development_end_exclusive"], tz="UTC")
    warmup_start = pd.Timestamp(cfg["evidence_boundary"]["warmup_start"], tz="UTC")
    if gold.index.max() >= dev_end:
        raise SystemExit("input contains locked/post-development data")
    if gold.index.min() < warmup_start:
        raise SystemExit("input precedes frozen warmup boundary")

    obs = build_observations(gold, cfg)
    specs = cfg["primary_hypotheses"]
    results = [hypothesis_result(obs, spec, cfg) for spec in specs]
    results = apply_gates(results, cfg)
    candidates = [r["id"] for r in results if r["state_pass"]]

    expected_hours = set(int(x) for x in cfg["observation_grid"]["anchor_hours_local"])
    actual_hours = set(int(x) for x in obs.anchor_hour.unique())
    if not actual_hours.issubset(expected_hours):
        raise SystemExit(f"unexpected anchor hours: {sorted(actual_hours - expected_hours)}")

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "development_volatility_state_only",
        "development_period": [cfg["evidence_boundary"]["development_start"], cfg["evidence_boundary"]["development_end_exclusive"]],
        "locked_validation_period": [cfg["evidence_boundary"]["locked_historical_validation_start"], cfg["evidence_boundary"]["locked_historical_validation_end_exclusive"]],
        "holdout_opened": False,
        "economic_scoring_run": False,
        "directional_scoring_run": False,
        "gold_source": cfg["gold_source"],
        "input_rows": int(len(gold)),
        "input_start": gold.index.min().isoformat(),
        "input_end": gold.index.max().isoformat(),
        "observation_rows": int(len(obs)),
        "observation_dates": int(obs.ny_date.nunique()),
        "anchor_hours_present": sorted(int(x) for x in obs.anchor_hour.unique()),
        "primary_hypothesis_count": int(len(results)),
        "state_pass_count": int(len(candidates)),
        "state_candidates": candidates,
        "hypotheses": results,
        "claims": {
            "volatility_state_edge_established": bool(candidates),
            "directional_edge_established": False,
            "executable_edge_established": False,
            "profitable_edge_established": False,
            "verified_future_oos": False,
            "leverage_authorized": False,
            "live_enabled": False
        }
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(output), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "observation_rows": output["observation_rows"],
        "observation_dates": output["observation_dates"],
        "state_pass_count": output["state_pass_count"],
        "state_candidates": output["state_candidates"]
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
