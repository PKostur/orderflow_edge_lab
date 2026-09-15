from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


BREAKOUT_MODULE = Path(__file__).with_name("run_gold_high_vol_breakout_state_v1.py")
spec = importlib.util.spec_from_file_location("gold_high_vol_breakout_parent", BREAKOUT_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load breakout parent from {BREAKOUT_MODULE}")
breakout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(breakout)
core = breakout.core


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


def failed_breakout_event(d: pd.DataFrame, ev: pd.Series, cfg: dict) -> dict | None:
    tb = pd.Timestamp(ev.breakout_time_utc)
    search_n = int(cfg["failure_definition"]["search_minutes_after_breakout_confirmation"])
    search = core.exact_window(d, tb + pd.Timedelta(minutes=1), search_n)
    if search is None:
        return None

    pre_high = float(ev.pre_high)
    pre_low = float(ev.pre_low)
    pre_range = float(ev.pre_range)
    direction = int(ev.direction)
    if direction not in (-1, 1) or not np.isfinite(pre_range) or pre_range <= 0:
        return None

    tf = None
    pf = None
    for ts, row in search.iterrows():
        close = float(row.close)
        if pre_low <= close <= pre_high:
            tf = pd.Timestamp(ts)
            pf = close
            break
    if tf is None or pf is None:
        return None

    scores = {}
    for h in cfg["state_score"]["horizons_minutes_after_failure_confirmation"]:
        future_ts = tf + pd.Timedelta(minutes=int(h))
        if future_ts not in d.index:
            return None
        future_close = float(d.at[future_ts, "close"])
        scores[f"score_{int(h)}m"] = (-direction) * (future_close - pf) / pre_range

    return {
        "t0_utc": pd.Timestamp(ev.t0_utc),
        "ny_date": str(ev.ny_date),
        "year": int(ev.year),
        "anchor_hour": int(ev.anchor_hour),
        "pre_rv_ratio": float(ev.pre_rv_ratio),
        "pre_range": pre_range,
        "pre_high": pre_high,
        "pre_low": pre_low,
        "breakout_time_utc": tb,
        "breakout_confirmation_close": float(ev.breakout_confirmation_close),
        "original_breakout_direction": direction,
        "failure_time_utc": tf,
        "failure_confirmation_close": pf,
        "minutes_to_failure": int((tf - tb) / pd.Timedelta(minutes=1)),
        **scores,
    }


def build_failed_events(d: pd.DataFrame, parent_vol_cfg: dict, breakout_cfg: dict, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    confirmed = breakout.build_events(d, parent_vol_cfg, breakout_cfg)
    rows = []
    for _, ev in confirmed.iterrows():
        out = failed_breakout_event(d, ev, cfg)
        if out is not None:
            rows.append(out)
    failed = pd.DataFrame(rows)
    if failed.empty:
        raise ValueError("no failed-breakout events")
    return confirmed.sort_values("t0_utc").reset_index(drop=True), failed.sort_values("t0_utc").reset_index(drop=True)


def group_masks(events: pd.DataFrame, cfg: dict, high_threshold: float) -> tuple[pd.Series, pd.Series]:
    activation = cfg["state_activation"]
    high = events.pre_rv_ratio >= float(high_threshold)
    normal = (
        (events.pre_rv_ratio >= float(activation["normal_control_rv_ratio_gte"]))
        & (events.pre_rv_ratio < float(activation["normal_control_rv_ratio_lt"]))
    )
    return high, normal


def daily_contrasts(events: pd.DataFrame, cfg: dict, high_threshold: float, horizon: int) -> pd.DataFrame:
    high, normal = group_masks(events, cfg, high_threshold)
    score_col = f"score_{int(horizon)}m"
    rows = []
    for day, g in events.groupby("ny_date", sort=True):
        hi = pd.to_numeric(g.loc[high.loc[g.index], score_col], errors="coerce").dropna().to_numpy(float)
        no = pd.to_numeric(g.loc[normal.loc[g.index], score_col], errors="coerce").dropna().to_numpy(float)
        if len(hi) == 0 or len(no) == 0:
            continue
        rows.append({
            "ny_date": day,
            "year": int(str(day)[:4]),
            "high_events": int(len(hi)),
            "normal_events": int(len(no)),
            "contrast": float(np.median(hi) - np.median(no)),
        })
    return pd.DataFrame(rows)


def threshold_summary(events: pd.DataFrame, cfg: dict, threshold: float) -> dict:
    primary_h = int(cfg["state_score"]["primary_horizon_minutes"])
    high, normal = group_masks(events, cfg, threshold)
    contrasts = daily_contrasts(events, cfg, threshold, primary_h)
    vals = contrasts.contrast.to_numpy(float) if len(contrasts) else np.array([], dtype=float)
    effect = float(np.median(vals)) if len(vals) else np.nan
    sign = int(np.sign(effect)) if np.isfinite(effect) and effect != 0 else 0
    return {
        "threshold": float(threshold),
        "high_failed_events": int(high.sum()),
        "normal_failed_events": int(normal.sum()),
        "daily_contrast_dates": int(len(contrasts)),
        "median_daily_contrast": effect,
        "daily_contrast_sign_fraction": float(np.mean(np.sign(vals) == sign)) if len(vals) and sign else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--breakout-config", required=True)
    ap.add_argument("--parent-vol-config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    breakout_cfg = json.loads(Path(args.breakout_config).read_text(encoding="utf-8"))
    parent_vol_cfg = json.loads(Path(args.parent_vol_config).read_text(encoding="utf-8"))

    if cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("economics must remain disabled")
    if cfg["evidence_boundary"].get("validation_opened") is not False:
        raise SystemExit("locked validation is open")
    if breakout_cfg["protocol_id"] != "gold-high-vol-breakout-state-v1":
        raise SystemExit("unexpected breakout parent")
    if parent_vol_cfg["protocol_id"] != "gold-volatility-liquidity-v1":
        raise SystemExit("unexpected volatility parent")

    d = core.load_gold(Path(args.gold))
    dev_end = pd.Timestamp(cfg["evidence_boundary"]["development_end_exclusive"], tz="UTC")
    if d.index.max() >= dev_end:
        raise SystemExit("input contains locked/post-development data")

    confirmed, events = build_failed_events(d, parent_vol_cfg, breakout_cfg, cfg)
    activation = cfg["state_activation"]
    primary_threshold = float(activation["primary_high_rv_ratio_gte"])
    primary_h = int(cfg["state_score"]["primary_horizon_minutes"])
    high_mask, normal_mask = group_masks(events, cfg, primary_threshold)
    high = events.loc[high_mask].copy()
    normal = events.loc[normal_mask].copy()

    confirmed_high, confirmed_normal = breakout.group_masks(confirmed, breakout_cfg, primary_threshold)
    high_failure_rate = float(len(high) / int(confirmed_high.sum())) if int(confirmed_high.sum()) else np.nan
    normal_failure_rate = float(len(normal) / int(confirmed_normal.sum())) if int(confirmed_normal.sum()) else np.nan

    contrasts = daily_contrasts(events, cfg, primary_threshold, primary_h)
    vals = contrasts.contrast.to_numpy(float) if len(contrasts) else np.array([], dtype=float)
    primary_effect = float(np.median(vals)) if len(vals) else np.nan
    primary_sign = int(np.sign(primary_effect)) if np.isfinite(primary_effect) and primary_effect != 0 else 0
    sign_fraction = float(np.mean(np.sign(vals) == primary_sign)) if len(vals) and primary_sign else 0.0
    p = core.signflip_median_p(
        vals,
        int(cfg["statistics"]["permutation_epochs"]),
        core.stable_seed(cfg["statistics"]["random_seed_namespace"], cfg["primary_hypothesis"]["id"]),
    )

    year_effects = {}
    for year in (2021, 2022):
        y = contrasts.loc[contrasts.year == year, "contrast"].to_numpy(float) if len(contrasts) else np.array([], dtype=float)
        year_effects[str(year)] = {
            "dates": int(len(y)),
            "median_daily_contrast": float(np.median(y)) if len(y) else np.nan,
        }

    horizon_effects = {}
    agreeing_horizons = 0
    for h in cfg["state_score"]["horizons_minutes_after_failure_confirmation"]:
        dc = daily_contrasts(events, cfg, primary_threshold, int(h))
        v = dc.contrast.to_numpy(float) if len(dc) else np.array([], dtype=float)
        eff = float(np.median(v)) if len(v) else np.nan
        horizon_effects[str(int(h))] = {"dates": int(len(v)), "median_daily_contrast": eff}
        if primary_sign and np.isfinite(eff) and np.sign(eff) == primary_sign:
            agreeing_horizons += 1

    score_col = f"score_{primary_h}m"
    high_scores = high[score_col].to_numpy(float)
    high_median = float(np.median(high_scores)) if len(high_scores) else np.nan
    high_positive_fraction = float(np.mean(high_scores > 0)) if len(high_scores) else 0.0

    direction_audit = {}
    for direction, label in ((1, "original_long_breakout"), (-1, "original_short_breakout")):
        q = high.loc[high.original_breakout_direction == direction, score_col].to_numpy(float)
        direction_audit[label] = {
            "events": int(len(q)),
            "median_reversal": float(np.median(q)) if len(q) else np.nan,
            "positive_fraction": float(np.mean(q > 0)) if len(q) else 0.0,
        }

    robustness = []
    robustness_agree = True
    for threshold in activation["robustness_high_rv_thresholds"]:
        s = threshold_summary(events, cfg, float(threshold))
        robustness.append(s)
        if not primary_sign or not np.isfinite(s["median_daily_contrast"]) or np.sign(s["median_daily_contrast"]) != primary_sign:
            robustness_agree = False

    gate = cfg["state_gate"]
    years_agree = primary_sign != 0 and all(
        np.isfinite(year_effects[str(year)]["median_daily_contrast"])
        and np.sign(year_effects[str(year)]["median_daily_contrast"]) == primary_sign
        for year in (2021, 2022)
    )
    direction_breadth = all(
        direction_audit[label]["events"] >= int(gate["minimum_failed_breakout_events_each_original_direction"])
        and np.isfinite(direction_audit[label]["median_reversal"])
        and direction_audit[label]["median_reversal"] > 0
        for label in ("original_long_breakout", "original_short_breakout")
    )

    passed = (
        len(high) >= int(gate["minimum_high_failed_breakout_events"])
        and len(normal) >= int(gate["minimum_normal_failed_breakout_events"])
        and len(contrasts) >= int(gate["minimum_daily_contrast_dates"])
        and np.isfinite(primary_effect)
        and primary_effect > 0
        and abs(primary_effect) >= float(gate["minimum_abs_median_daily_contrast"])
        and sign_fraction >= float(gate["minimum_daily_primary_sign_fraction"])
        and np.isfinite(high_median)
        and high_median >= float(gate["minimum_high_state_median_reversal"])
        and high_positive_fraction >= float(gate["minimum_high_state_positive_fraction"])
        and direction_breadth
        and years_agree
        and agreeing_horizons >= int(gate["minimum_horizons_sharing_primary_sign"])
        and robustness_agree
        and p <= float(gate["primary_p_max"])
    )

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "post_observation_failed_breakout_reversal_state_development",
        "evidence_class": cfg["parent_observation"]["evidence_class"],
        "holdout_opened": False,
        "economic_scoring_run": False,
        "costs_scored": False,
        "confirmed_breakout_events": int(len(confirmed)),
        "failed_breakout_events": int(len(events)),
        "failed_breakout_dates": int(events.ny_date.nunique()),
        "primary_threshold": primary_threshold,
        "high_failed_breakout_events": int(len(high)),
        "normal_failed_breakout_events": int(len(normal)),
        "high_failed_breakout_rate_given_confirmation": high_failure_rate,
        "normal_failed_breakout_rate_given_confirmation": normal_failure_rate,
        "daily_contrast_dates": int(len(contrasts)),
        "primary_effect": primary_effect,
        "primary_sign": primary_sign,
        "daily_primary_sign_fraction": sign_fraction,
        "primary_p": float(p),
        "high_state_median_reversal": high_median,
        "high_state_positive_fraction": high_positive_fraction,
        "year_effects": year_effects,
        "horizon_effects": horizon_effects,
        "horizons_sharing_primary_sign": int(agreeing_horizons),
        "direction_audit": direction_audit,
        "robustness_thresholds": robustness,
        "robustness_thresholds_share_primary_sign": bool(robustness_agree),
        "state_pass": bool(passed),
        "state_candidate": cfg["primary_hypothesis"]["id"] if passed else None,
        "claims": {
            "reversal_state_edge_established_in_development": bool(passed),
            "independent_confirmation": False,
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
        "confirmed_breakout_events": output["confirmed_breakout_events"],
        "failed_breakout_events": output["failed_breakout_events"],
        "high_failed_breakout_events": output["high_failed_breakout_events"],
        "normal_failed_breakout_events": output["normal_failed_breakout_events"],
        "daily_contrast_dates": output["daily_contrast_dates"],
        "primary_effect": output["primary_effect"],
        "primary_p": output["primary_p"],
        "state_pass": output["state_pass"]
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
