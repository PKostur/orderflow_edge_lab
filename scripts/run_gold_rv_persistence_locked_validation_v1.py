from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


WARM = Path(__file__).with_name("run_gold_volatility_liquidity_v1_warm.py")
spec = importlib.util.spec_from_file_location("gold_volatility_warm", WARM)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load frozen parent implementation from {WARM}")
warm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(warm)
core = warm.module


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


def runtime_parent_config(cfg: dict) -> dict:
    return {
        "evidence_boundary": {
            "warmup_start": cfg["evidence_boundary"]["warmup_start"],
            "development_start": cfg["evidence_boundary"]["locked_validation_start"],
            "development_end_exclusive": cfg["evidence_boundary"]["locked_validation_end_exclusive"]
        },
        "observation_grid": cfg["observation_grid"]
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("protocol_status") != "candidate_state_validation_frozen":
        raise SystemExit("validation candidate is not frozen")
    if cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("economics must remain disabled")
    if cfg["candidate_freeze"]["candidate_id"] != "rv_persistence":
        raise SystemExit("unexpected candidate")
    if cfg["candidate_freeze"]["frozen_sign"] != "positive":
        raise SystemExit("unexpected candidate sign")

    d = core.load_gold(Path(args.gold))
    validation_start = pd.Timestamp(cfg["evidence_boundary"]["locked_validation_start"], tz="UTC")
    validation_end = pd.Timestamp(cfg["evidence_boundary"]["locked_validation_end_exclusive"], tz="UTC")
    warmup_start = pd.Timestamp(cfg["evidence_boundary"]["warmup_start"], tz="UTC")
    if d.index.min() > warmup_start + pd.Timedelta(days=2):
        raise SystemExit("warmup coverage starts too late")
    if d.index.max() >= validation_end:
        raise SystemExit("input contains post-validation data")
    if d.index.max() < validation_end - pd.Timedelta(days=3):
        raise SystemExit("validation coverage ends too early")

    obs = warm.build_observations_with_warmup(d, runtime_parent_config(cfg))
    if obs.t0_utc.min() < validation_start or obs.t0_utc.max() >= validation_end:
        raise SystemExit("observation boundary violation")

    min_anchors = int(cfg["observation_grid"]["minimum_daily_anchor_count_for_inference"])
    daily = core.daily_effects(obs, "pre_rv_ratio", "future_rv_ratio", None, min_anchors)
    secondary = core.daily_effects(obs, "pre_rv_ratio", "future_range_ratio", None, min_anchors)
    if daily.empty:
        raise SystemExit("no primary daily validation effects")

    effects = daily.effect.to_numpy(float)
    primary_effect = float(np.median(effects))
    positive_fraction = float(np.mean(effects > 0))
    epochs = int(cfg["statistics"]["permutation_epochs"])
    p = positive_signflip_p(
        effects,
        epochs,
        core.stable_seed(cfg["statistics"]["random_seed_namespace"], cfg["candidate_freeze"]["candidate_id"])
    )

    secondary_effects = secondary.effect.to_numpy(float) if len(secondary) else np.array([], dtype=float)
    secondary_median = float(np.median(secondary_effects)) if len(secondary_effects) else np.nan

    date_ts = pd.to_datetime(daily.ny_date)
    first_half = daily.loc[date_ts < pd.Timestamp("2023-07-01"), "effect"].to_numpy(float)
    second_half = daily.loc[date_ts >= pd.Timestamp("2023-07-01"), "effect"].to_numpy(float)
    first_half_median = float(np.median(first_half)) if len(first_half) else np.nan
    second_half_median = float(np.median(second_half)) if len(second_half) else np.nan

    anchor_rows = core.anchor_effects(
        obs,
        "pre_rv_ratio",
        "future_rv_ratio",
        None,
        int(cfg["validation_gate"]["minimum_anchor_slot_observations"])
    )
    positive_anchor_slots = sum(
        1 for r in anchor_rows
        if r["eligible"] and np.isfinite(r["effect"]) and r["effect"] > 0
    )

    gate = cfg["validation_gate"]
    passed = (
        len(daily) >= int(gate["minimum_scorable_dates"])
        and primary_effect >= float(gate["minimum_median_daily_effect"])
        and positive_fraction >= float(gate["minimum_daily_positive_fraction"])
        and positive_anchor_slots >= int(gate["minimum_positive_anchor_slots"])
        and np.isfinite(first_half_median) and first_half_median > 0
        and np.isfinite(second_half_median) and second_half_median > 0
        and np.isfinite(secondary_median) and secondary_median > 0
        and p <= float(gate["primary_p_max"])
    )

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "locked_2023_state_validation",
        "candidate_id": cfg["candidate_freeze"]["candidate_id"],
        "candidate_sign": cfg["candidate_freeze"]["frozen_sign"],
        "development_reused_for_selection": False,
        "economic_scoring_run": False,
        "directional_scoring_run": False,
        "future_oos_claim": False,
        "input_rows": int(len(d)),
        "input_start": d.index.min().isoformat(),
        "input_end": d.index.max().isoformat(),
        "validation_observations": int(len(obs)),
        "scorable_dates": int(len(daily)),
        "primary_median_daily_spearman": primary_effect,
        "daily_positive_fraction": positive_fraction,
        "one_sided_positive_signflip_p": p,
        "first_half_dates": int(len(first_half)),
        "first_half_median_daily_spearman": first_half_median,
        "second_half_dates": int(len(second_half)),
        "second_half_median_daily_spearman": second_half_median,
        "secondary_range_median_daily_spearman": secondary_median,
        "anchor_effects": anchor_rows,
        "positive_anchor_slots": int(positive_anchor_slots),
        "validation_pass": bool(passed),
        "claims": {
            "same_source_locked_state_validation_passed": bool(passed),
            "directional_edge_established": False,
            "executable_edge_established": False,
            "profitable_edge_established": False,
            "independent_replication_complete": False,
            "verified_future_oos": False,
            "leverage_authorized": False,
            "live_enabled": False
        }
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(output), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "scorable_dates": output["scorable_dates"],
        "primary_median_daily_spearman": output["primary_median_daily_spearman"],
        "daily_positive_fraction": output["daily_positive_fraction"],
        "one_sided_positive_signflip_p": output["one_sided_positive_signflip_p"],
        "positive_anchor_slots": output["positive_anchor_slots"],
        "validation_pass": output["validation_pass"]
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
