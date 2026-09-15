from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from run_gold_rv_persistence_histdata_replication_v1 import (
    NY,
    anchor_effects,
    build_observations,
    clean,
    daily_effects,
    data_quality_diagnostics,
    load_histdata_zip,
    positive_signflip_p,
    stable_seed,
    verify_archive,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--zip2023", required=True)
    ap.add_argument("--zip2024", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--daily-output")
    ap.add_argument("--anchor-output")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if cfg.get("protocol_status") != "independent_source_later_period_replication_frozen":
        raise SystemExit("2024 replication protocol is not frozen")
    if cfg.get("economic_scoring_enabled") is not False:
        raise SystemExit("economics must remain disabled")
    if cfg["parent_candidate"]["candidate_id"] != "rv_persistence":
        raise SystemExit("unexpected parent candidate")
    if cfg["parent_candidate"]["frozen_sign"] != "positive":
        raise SystemExit("unexpected frozen sign")
    if cfg["replication_classification"]["instrument_independent"] is not False:
        raise SystemExit("HistData 2024 replication must remain same-instrument")
    if cfg["replication_classification"]["historical_oos"] is not True:
        raise SystemExit("2024 period must be classified as later historical OOS")
    if cfg["replication_classification"]["prospective_future_oos"] is not False:
        raise SystemExit("historical 2024 cannot be claimed as prospective future OOS")

    z23 = Path(args.zip2023)
    z24 = Path(args.zip2024)
    v23 = verify_archive(z23, cfg["source"]["warmup_archive"])
    v24 = verify_archive(z24, cfg["source"]["replication_archive"])
    d23, q23 = load_histdata_zip(z23)
    d24, q24 = load_histdata_zip(z24)
    d = pd.concat([d23, d24], axis=0).sort_index()
    d = d[~d.index.duplicated(keep="last")]

    years = set(int(y) for y in d.index.year.unique())
    if not years.issubset({2023, 2024}) or 2024 not in years:
        raise SystemExit(f"unexpected source years: {sorted(years)}")

    raw, obs = build_observations(d, cfg)
    score_local = obs.t0_utc.map(lambda x: pd.Timestamp(x).tz_convert(NY))
    if not all(ts.year == 2024 for ts in score_local):
        raise SystemExit("non-2024 anchor entered replication inference")

    min_anchors = int(cfg["observation_grid"]["minimum_daily_anchor_count_for_inference"])
    daily = daily_effects(obs, "future_rv_ratio", min_anchors)
    secondary = daily_effects(obs, "future_range_ratio", min_anchors)
    if daily.empty:
        raise SystemExit("no scorable HistData 2024 replication dates")

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
    split = pd.Timestamp("2024-07-01")
    first = daily.loc[dates < split, "effect"].to_numpy(float)
    second = daily.loc[dates >= split, "effect"].to_numpy(float)
    first_median = float(np.median(first)) if len(first) else np.nan
    second_median = float(np.median(second)) if len(second) else np.nan

    gate = cfg["replication_gate"]
    anchor_rows = anchor_effects(obs, int(gate["minimum_anchor_slot_observations"]))
    positive_anchor_slots = sum(
        1
        for row in anchor_rows
        if row["eligible"] and np.isfinite(row["effect"]) and row["effect"] > 0
    )

    gate_results = {
        "minimum_scorable_dates": len(daily) >= int(gate["minimum_scorable_dates"]),
        "minimum_median_daily_effect": primary_effect >= float(gate["minimum_median_daily_effect"]),
        "minimum_daily_positive_fraction": positive_fraction >= float(gate["minimum_daily_positive_fraction"]),
        "minimum_positive_anchor_slots": positive_anchor_slots >= int(gate["minimum_positive_anchor_slots"]),
        "first_half_positive": np.isfinite(first_median) and first_median > 0,
        "second_half_positive": np.isfinite(second_median) and second_median > 0,
        "secondary_range_positive": np.isfinite(secondary_median) and secondary_median > 0,
        "primary_p_max": p <= float(gate["primary_p_max"]),
    }
    passed = bool(all(gate_results.values()))

    output = {
        "protocol_id": cfg["protocol_id"],
        "stage": "independent_source_same_instrument_later_historical_state_replication",
        "candidate_id": cfg["parent_candidate"]["candidate_id"],
        "candidate_sign": cfg["parent_candidate"]["frozen_sign"],
        "replication_classification": cfg["replication_classification"],
        "economic_scoring_run": False,
        "directional_scoring_run": False,
        "future_oos_claim": False,
        "prospective_future_oos_claim": False,
        "historical_oos_claim": True,
        "source_verification": {
            "2023_warmup": v23,
            "2024_replication": v24,
            "2023_parse": q23,
            "2024_parse": q24,
        },
        "combined_input_rows": int(len(d)),
        "combined_input_start": d.index.min().isoformat(),
        "combined_input_end": d.index.max().isoformat(),
        "raw_anchor_observations_including_warmup": int(len(raw)),
        "replication_observations": int(len(obs)),
        "first_scorable_anchor_utc": obs.t0_utc.min(),
        "last_scorable_anchor_utc": obs.t0_utc.max(),
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
        "gate_results": gate_results,
        "replication_pass": passed,
        "data_quality_diagnostics": data_quality_diagnostics(d, daily),
        "claim_boundary": {
            "independent_source_later_historical_replication_only": True,
            "prospective_future_oos": False,
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
