from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from run_gold_rv_persistence_histdata_replication_v1 import (
    NY,
    anchor_effects,
    clean,
    daily_effects,
    data_quality_diagnostics,
    positive_signflip_p,
    raw_observation,
    stable_seed,
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_dukascopy_csv(path: Path) -> tuple[pd.DataFrame, dict]:
    d = pd.read_csv(path)
    expected = ["timestamp", "open", "high", "low", "close"]
    if list(d.columns) != expected:
        raise ValueError(f"unexpected Dukascopy CSV schema: {list(d.columns)}")

    raw_rows = int(len(d))
    ts = pd.to_numeric(d["timestamp"], errors="coerce")
    if ts.isna().any():
        raise ValueError("non-numeric Dukascopy timestamp")
    d["time"] = pd.to_datetime(ts.astype("int64"), unit="ms", utc=True, errors="coerce")
    if d["time"].isna().any():
        raise ValueError("failed Unix-millisecond timestamp parse")

    for c in ("open", "high", "low", "close"):
        d[c] = pd.to_numeric(d[c], errors="coerce")

    d = d.dropna(subset=["time", "open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d = d[
        (d.high >= d[["open", "close"]].max(axis=1))
        & (d.low <= d[["open", "close"]].min(axis=1))
        & (d.high >= d.low)
    ]
    d = d.drop_duplicates("time", keep="last").sort_values("time").set_index("time")
    if d.empty:
        raise ValueError("no valid Dukascopy rows")

    return d, {
        "path": str(path),
        "raw_rows": raw_rows,
        "valid_rows": int(len(d)),
        "first_utc": d.index.min(),
        "last_utc": d.index.max(),
        "size_bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
    }


def completed_ny_cutoff(asof_utc: pd.Timestamp) -> pd.Timestamp:
    if asof_utc.tzinfo is None:
        raise ValueError("as-of timestamp must be timezone-aware")
    local = asof_utc.tz_convert(NY)
    current_local_midnight = pd.Timestamp(local.date(), tz=NY)
    return current_local_midnight.tz_convert("UTC")


def build_shadow_observations(
    d: pd.DataFrame,
    cfg: dict,
    cutoff_utc: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    grid = cfg["observation_grid"]
    src = cfg["source"]
    hours = set(int(x) for x in grid["anchor_hours_local"])
    warmup_start = pd.Timestamp(src["warmup_acquisition_start_utc"])
    shadow_start = pd.Timestamp(cfg["evidence_classification"]["shadow_start_utc"])

    local_idx = d.index.tz_convert(NY)
    mask = (
        (d.index >= warmup_start)
        & (d.index < cutoff_utc)
        & (local_idx.weekday < 5)
        & (local_idx.minute == int(grid["anchor_minute"]))
        & (local_idx.second == 0)
        & np.isin(local_idx.hour, list(hours))
    )

    rows: list[dict] = []
    for t0 in d.index[mask]:
        obs = raw_observation(d, pd.Timestamp(t0))
        if obs is not None:
            rows.append(obs)

    if not rows:
        return pd.DataFrame(), pd.DataFrame()

    raw = pd.DataFrame(rows).sort_values(["anchor_hour", "t0_utc"]).reset_index(drop=True)
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

    score_mask = (raw.t0_utc >= shadow_start) & (raw.t0_utc < cutoff_utc)
    scored = raw.loc[score_mask].copy()
    scored = scored.dropna(subset=["pre_rv_ratio", "future_rv_ratio", "future_range_ratio"])
    scored = scored[
        (scored.pre_rv_ratio > 0)
        & (scored.future_rv_ratio > 0)
        & (scored.future_range_ratio > 0)
    ]

    if len(scored):
        if pd.Timestamp(scored.t0_utc.min()) < shadow_start:
            raise ValueError("pre-shadow anchor entered prospective inference")
        scored_local = scored.t0_utc.map(lambda x: pd.Timestamp(x).tz_convert(NY))
        if any(ts.date() >= cutoff_utc.tz_convert(NY).date() for ts in scored_local):
            raise ValueError("incomplete New York date entered prospective inference")

    return (
        raw.sort_values("t0_utc").reset_index(drop=True),
        scored.sort_values("t0_utc").reset_index(drop=True),
    )


def chronological_halves(daily: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    if daily.empty:
        return np.array([], dtype=float), np.array([], dtype=float)
    x = daily.sort_values("ny_date").effect.to_numpy(float)
    split = len(x) // 2
    if split == 0:
        return np.array([], dtype=float), x
    return x[:split], x[split:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--asof-utc", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--daily-output")
    ap.add_argument("--anchor-output")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("protocol_status") != "prospective_state_shadow_frozen":
        raise SystemExit("prospective shadow protocol is not frozen")
    if cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("economics must remain disabled")
    if cfg.get("directional_scoring_enabled") is not False:
        raise SystemExit("directional scoring must remain disabled")
    if cfg["parent_candidate"]["candidate_id"] != "rv_persistence":
        raise SystemExit("unexpected parent candidate")
    if cfg["parent_candidate"]["frozen_sign"] != "positive":
        raise SystemExit("unexpected candidate sign")

    asof = pd.Timestamp(args.asof_utc)
    if asof.tzinfo is None:
        raise SystemExit("--asof-utc must include timezone")
    asof = asof.tz_convert("UTC")
    cutoff = completed_ny_cutoff(asof)
    shadow_start = pd.Timestamp(cfg["evidence_classification"]["shadow_start_utc"])

    src_path = Path(args.csv)
    d, source_info = load_dukascopy_csv(src_path)
    raw, obs = build_shadow_observations(d, cfg, cutoff)

    min_anchors = int(cfg["observation_grid"]["minimum_daily_anchor_count_for_inference"])
    if obs.empty:
        daily = pd.DataFrame(columns=["ny_date", "n", "effect"])
        secondary = pd.DataFrame(columns=["ny_date", "n", "effect"])
    else:
        daily = daily_effects(obs, "future_rv_ratio", min_anchors)
        secondary = daily_effects(obs, "future_range_ratio", min_anchors)

    effects = daily.effect.to_numpy(float) if len(daily) else np.array([], dtype=float)
    secondary_effects = secondary.effect.to_numpy(float) if len(secondary) else np.array([], dtype=float)
    primary_median = float(np.median(effects)) if len(effects) else np.nan
    positive_fraction = float(np.mean(effects > 0)) if len(effects) else np.nan
    secondary_median = float(np.median(secondary_effects)) if len(secondary_effects) else np.nan
    p = (
        positive_signflip_p(
            effects,
            int(cfg["statistics"]["permutation_epochs"]),
            stable_seed(cfg["statistics"]["random_seed_namespace"], cfg["parent_candidate"]["candidate_id"]),
        )
        if len(effects)
        else np.nan
    )

    first, second = chronological_halves(daily)
    first_median = float(np.median(first)) if len(first) else np.nan
    second_median = float(np.median(second)) if len(second) else np.nan

    gate = cfg["full_shadow_gate"]
    anchor_rows = anchor_effects(obs, int(gate["minimum_anchor_slot_observations"])) if len(obs) else []
    positive_anchor_slots = sum(
        1
        for row in anchor_rows
        if row["eligible"] and np.isfinite(row["effect"]) and row["effect"] > 0
    )

    full_eligible = len(daily) >= int(gate["minimum_scorable_dates"])
    gate_results = {
        "minimum_scorable_dates": full_eligible,
        "minimum_median_daily_effect": bool(np.isfinite(primary_median) and primary_median >= float(gate["minimum_median_daily_effect"])),
        "minimum_daily_positive_fraction": bool(np.isfinite(positive_fraction) and positive_fraction >= float(gate["minimum_daily_positive_fraction"])),
        "minimum_positive_anchor_slots": positive_anchor_slots >= int(gate["minimum_positive_anchor_slots"]),
        "first_chronological_half_positive": bool(np.isfinite(first_median) and first_median > 0),
        "second_chronological_half_positive": bool(np.isfinite(second_median) and second_median > 0),
        "secondary_range_positive": bool(np.isfinite(secondary_median) and secondary_median > 0),
        "primary_p_max": bool(np.isfinite(p) and p <= float(gate["primary_p_max"])),
    }
    full_pass = bool(full_eligible and all(gate_results.values()))

    checkpoints = sorted(int(x) for x in cfg["monitoring_checkpoints"]["informational_only_scorable_dates"])
    reached = [x for x in checkpoints if len(daily) >= x]
    next_checkpoint = next((x for x in checkpoints if len(daily) < x), int(gate["minimum_scorable_dates"]))

    if not len(daily):
        status = "pre_start_or_no_scorable_dates"
    elif not full_eligible:
        status = "monitoring_only"
    elif full_pass:
        status = "full_shadow_pass"
    else:
        status = "full_shadow_fail"

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "prospective_state_shadow",
        "candidate_id": cfg["parent_candidate"]["candidate_id"],
        "candidate_sign": cfg["parent_candidate"]["frozen_sign"],
        "asof_utc": asof,
        "last_complete_new_york_cutoff_utc": cutoff,
        "shadow_start_utc": shadow_start,
        "source": {
            **source_info,
            "provider": cfg["source"]["provider"],
            "acquisition_client": cfg["source"]["acquisition_client"],
            "acquisition_client_version": cfg["source"]["acquisition_client_version"],
            "instrument": cfg["source"]["instrument"],
            "price_type": cfg["source"]["price_type"],
            "timeframe": cfg["source"]["timeframe"],
        },
        "raw_anchor_observations_including_warmup": int(len(raw)),
        "prospective_anchor_observations": int(len(obs)),
        "first_prospective_anchor_utc": obs.t0_utc.min() if len(obs) else None,
        "last_prospective_anchor_utc": obs.t0_utc.max() if len(obs) else None,
        "scorable_dates": int(len(daily)),
        "primary_median_daily_spearman": primary_median,
        "daily_positive_fraction": positive_fraction,
        "one_sided_positive_signflip_p": p,
        "first_chronological_half_dates": int(len(first)),
        "first_chronological_half_median_daily_spearman": first_median,
        "second_chronological_half_dates": int(len(second)),
        "second_chronological_half_median_daily_spearman": second_median,
        "secondary_range_median_daily_spearman": secondary_median,
        "anchor_effects": anchor_rows,
        "positive_anchor_slots": int(positive_anchor_slots),
        "monitoring": {
            "status": status,
            "reached_informational_checkpoints": reached,
            "next_informational_or_full_checkpoint": next_checkpoint,
            "checkpoint_can_promote": False,
            "full_shadow_decision_eligible": full_eligible,
        },
        "gate_results": gate_results,
        "full_shadow_pass": full_pass,
        "economic_scoring_run": False,
        "directional_scoring_run": False,
        "data_quality_diagnostics": data_quality_diagnostics(d, daily),
        "claim_boundary": {
            "prospective_state_shadow_only": True,
            "directional_edge": False,
            "economic_edge": False,
            "leverage_authorized": False,
            "live_enabled": False,
        },
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean(output), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.daily_output:
        pth = Path(args.daily_output)
        pth.parent.mkdir(parents=True, exist_ok=True)
        daily.to_csv(pth, index=False)
    if args.anchor_output:
        pth = Path(args.anchor_output)
        pth.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(anchor_rows).to_csv(pth, index=False)

    print(json.dumps(clean(output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
