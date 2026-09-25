from __future__ import annotations

import itertools
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.descriptive_regime_labels_v1 import build_states, state_at_entry
from orderflow_edge_lab.universal_backtest import ExecutionModel, legacy_strategy, run_canonical_backtest


class RegimeMarginalPairwiseShadowV1Error(ValueError):
    pass


AXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("trend_state", ("CHOP", "MIXED", "TREND")),
    ("volatility_state", ("LOW", "MID", "HIGH")),
    ("coupling_state", ("LOW", "MID", "HIGH")),
    ("shock_state", ("NORMAL", "SHOCK")),
    ("drawdown_state", ("NEAR_HIGH", "CORRECTION", "DEEP_DRAWDOWN")),
)


def _utc(value: Any) -> pd.Timestamp:
    out = pd.Timestamp(value)
    return out.tz_localize("UTC") if out.tzinfo is None else out.tz_convert("UTC")


def all_specs() -> list[dict[str, Any]]:
    marginals = [
        {
            "tier": "marginal",
            "contrast_id": f"MARGINAL|{axis}={state}",
            "axes": [axis],
            "states": [state],
        }
        for axis, states in AXES
        for state in states
    ]
    pairwise: list[dict[str, Any]] = []
    for (left_axis, left_states), (right_axis, right_states) in itertools.combinations(AXES, 2):
        for left_state, right_state in itertools.product(left_states, right_states):
            pairwise.append(
                {
                    "tier": "pairwise",
                    "contrast_id": f"PAIR|{left_axis}={left_state}|{right_axis}={right_state}",
                    "axes": [left_axis, right_axis],
                    "states": [left_state, right_state],
                }
            )
    result = marginals + pairwise
    if len(marginals) != 14 or len(pairwise) != 78 or len(result) != 92:
        raise RegimeMarginalPairwiseShadowV1Error("frozen contrast family changed")
    return result


def _validate_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    as_of: pd.Timestamp,
    interval: pd.Timedelta = pd.Timedelta(hours=8),
) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise RegimeMarginalPairwiseShadowV1Error(f"{symbol}: index must be DatetimeIndex")
    out = frame.copy().sort_index()
    out.index = pd.to_datetime(out.index, utc=True)
    if out.index.has_duplicates:
        raise RegimeMarginalPairwiseShadowV1Error(f"{symbol}: duplicate timestamps")
    required = {"open", "high", "low", "close"}
    if not required.issubset(out.columns):
        raise RegimeMarginalPairwiseShadowV1Error(f"{symbol}: missing OHLC")
    for column in required:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    values = out[list(required)].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise RegimeMarginalPairwiseShadowV1Error(f"{symbol}: invalid OHLC")
    completed = out.index + interval <= as_of
    out = out.loc[completed]
    if len(out) < 650:
        raise RegimeMarginalPairwiseShadowV1Error(
            f"{symbol}: fewer than 650 fully completed warmup bars"
        )
    return out


def classify_ledger_trade(trade: Mapping[str, Any], start: pd.Timestamp) -> str:
    entry = _utc(trade["entry"])
    if entry < start:
        return "PRE_START_EXCLUDED"
    if bool(trade.get("terminal_liquidation")):
        return "OPEN_SNAPSHOT_NOT_SCORED"
    return "COMPLETED_SCORED"


def _bh(values: Sequence[float], multiplier: float = 1.0) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda index: values[index])
    out = [1.0] * n
    running = 1.0
    for reverse_rank, index in enumerate(reversed(order), start=1):
        rank = n - reverse_rank + 1
        running = min(
            running,
            min(1.0, float(values[index]) * n * multiplier / rank),
        )
        out[index] = running
    return out


def _by(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    harmonic = sum(1.0 / k for k in range(1, len(values) + 1))
    return _bh(values, multiplier=harmonic)


def _holm(values: Sequence[float]) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    out = [1.0] * n
    running = 0.0
    for rank, index in enumerate(sorted(range(n), key=lambda i: values[i])):
        running = max(running, min(1.0, (n - rank) * float(values[index])))
        out[index] = running
    return out


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trade_count": 0,
            "expectancy_bps": None,
            "win_rate": None,
            "correct_direction_rate": None,
            "median_mfe_bps": None,
            "median_abs_mae_bps": None,
            "observed_symbol_count": 0,
            "distinct_30d_block_count": 0,
        }
    net = np.asarray([float(row["net_bps"]) for row in rows], dtype=float)
    gross = np.asarray([float(row["gross_bps"]) for row in rows], dtype=float)
    mfe = [float(row["mfe_bps"]) for row in rows if row.get("mfe_bps") is not None]
    mae = [abs(float(row["mae_bps"])) for row in rows if row.get("mae_bps") is not None]
    return {
        "trade_count": len(rows),
        "expectancy_bps": float(net.mean()),
        "win_rate": float(np.mean(net > 0.0)),
        "correct_direction_rate": float(np.mean(gross > 0.0)),
        "median_mfe_bps": float(np.median(mfe)) if mfe else None,
        "median_abs_mae_bps": float(np.median(mae)) if mae else None,
        "observed_symbol_count": len({str(row["symbol"]) for row in rows}),
        "distinct_30d_block_count": len({int(row["_block_id"]) for row in rows}),
    }


def _symbol_breadth(
    group: Sequence[Mapping[str, Any]],
    complement: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    left: dict[str, list[float]] = {}
    right: dict[str, list[float]] = {}
    for row in group:
        left.setdefault(str(row["symbol"]), []).append(float(row["net_bps"]))
    for row in complement:
        right.setdefault(str(row["symbol"]), []).append(float(row["net_bps"]))
    diffs = {
        symbol: float(np.mean(left[symbol]) - np.mean(right[symbol]))
        for symbol in sorted(set(left) & set(right))
    }
    values = list(diffs.values())
    return {
        "comparable_symbol_count": len(values),
        "per_symbol_expectancy_difference_bps": diffs,
        "median_symbol_expectancy_difference_bps": (
            float(np.median(values)) if values else None
        ),
        "positive_symbol_difference_fraction": (
            sum(value > 0.0 for value in values) / len(values)
            if values
            else None
        ),
    }


def _bootstrap_weights(block_count: int, replicates: int, seed: int) -> np.ndarray:
    if block_count <= 0:
        return np.zeros((0, 0), dtype=np.int32)
    rng = np.random.default_rng(seed)
    weights = np.zeros((replicates, block_count), dtype=np.int32)
    for index in range(replicates):
        draw = rng.integers(0, block_count, size=block_count)
        weights[index] = np.bincount(draw, minlength=block_count)
    return weights


def _contrast_bootstrap(
    pool: Sequence[Mapping[str, Any]],
    group_flags: np.ndarray,
    weights: np.ndarray,
    block_count: int,
) -> dict[str, Any]:
    if not pool or not group_flags.any() or group_flags.all():
        return {
            "observed_difference_bps": None,
            "null_centered_two_sided_block_bootstrap_p": None,
            "valid_replicates": 0,
        }
    values = np.asarray([float(row["net_bps"]) for row in pool], dtype=float)
    blocks = np.asarray([int(row["_block_index"]) for row in pool], dtype=int)
    comp_flags = ~group_flags
    group_mean = float(values[group_flags].mean())
    comp_mean = float(values[comp_flags].mean())
    observed = group_mean - comp_mean
    pooled_mean = float(values.mean())
    null_values = values.copy()
    null_values[group_flags] = values[group_flags] - group_mean + pooled_mean
    null_values[comp_flags] = values[comp_flags] - comp_mean + pooled_mean

    def block_parts(v: np.ndarray, flags: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        counts = np.bincount(blocks[flags], minlength=block_count).astype(float)
        sums = np.bincount(
            blocks[flags],
            weights=v[flags],
            minlength=block_count,
        ).astype(float)
        return counts, sums

    gc, _ = block_parts(values, group_flags)
    cc, _ = block_parts(values, comp_flags)
    ngc, ngs = block_parts(null_values, group_flags)
    ncc, ncs = block_parts(null_values, comp_flags)
    sample_gc = weights @ ngc
    sample_cc = weights @ ncc
    valid = (sample_gc > 0.0) & (sample_cc > 0.0)
    if not valid.any():
        return {
            "observed_difference_bps": observed,
            "null_centered_two_sided_block_bootstrap_p": None,
            "valid_replicates": 0,
        }
    null_diff = (
        (weights @ ngs)[valid] / sample_gc[valid]
        - (weights @ ncs)[valid] / sample_cc[valid]
    )
    exceed = int(np.sum(np.abs(null_diff) >= abs(observed)))
    return {
        "observed_difference_bps": observed,
        "null_centered_two_sided_block_bootstrap_p": float(
            (1 + exceed) / (1 + len(null_diff))
        ),
        "valid_replicates": int(len(null_diff)),
    }


def _apply_adjustments(contrasts: list[dict[str, Any]], alpha: float) -> dict[str, Any]:
    eligible = [
        index
        for index, row in enumerate(contrasts)
        if row["bootstrap"]["null_centered_two_sided_block_bootstrap_p"] is not None
    ]
    values = [
        float(contrasts[index]["bootstrap"]["null_centered_two_sided_block_bootstrap_p"])
        for index in eligible
    ]
    bh = _bh(values)
    by = _by(values)
    holm = _holm(values)
    for index, bh_value, by_value, holm_value in zip(eligible, bh, by, holm):
        contrasts[index]["global_multiplicity"] = {
            "bh_fdr_q": bh_value,
            "by_dependency_robust_fdr_q": by_value,
            "holm_fwer_p": holm_value,
            "bh_fdr_10pct": bh_value <= alpha,
            "by_fdr_10pct": by_value <= alpha,
            "holm_fwer_10pct": holm_value <= alpha,
        }
    for row in contrasts:
        row.setdefault(
            "global_multiplicity",
            {
                "bh_fdr_q": None,
                "by_dependency_robust_fdr_q": None,
                "holm_fwer_p": None,
                "bh_fdr_10pct": False,
                "by_fdr_10pct": False,
                "holm_fwer_10pct": False,
            },
        )
    return {
        "eligible_test_count": len(eligible),
        "bh_fdr_discovery_count": sum(value <= alpha for value in bh),
        "by_fdr_discovery_count": sum(value <= alpha for value in by),
        "holm_fwer_discovery_count": sum(value <= alpha for value in holm),
    }


def _known(row: Mapping[str, Any], axis: str) -> bool:
    allowed = dict(AXES)[axis]
    return str(row.get(axis)) in allowed


def _matches(row: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    return all(
        str(row.get(axis)) == state
        for axis, state in zip(spec["axes"], spec["states"])
    )


def _anchor_map(binding: Mapping[str, Any]) -> dict[str, dict[str, Mapping[str, Any]]]:
    result: dict[str, dict[str, Mapping[str, Any]]] = {}
    for strategy_id, payload in binding["per_strategy"].items():
        result[str(strategy_id)] = {
            str(anchor["contrast_id"]): anchor
            for anchor in payload.get("anchors", [])
        }
    return result


def build_shadow_report(
    config: Mapping[str, Any],
    anchor_binding: Mapping[str, Any],
    label_config: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    as_of_utc: str | pd.Timestamp,
) -> dict[str, Any]:
    if config.get("watch_id") != "universal-regime-marginal-pairwise-shadow-v1":
        raise RegimeMarginalPairwiseShadowV1Error("wrong watch config")
    if anchor_binding.get("watch_id") != config["watch_id"]:
        raise RegimeMarginalPairwiseShadowV1Error("anchor binding watch mismatch")
    if label_config.get("protocol_name") != config["inherited_labels"]["protocol"]:
        raise RegimeMarginalPairwiseShadowV1Error("label protocol mismatch")
    if label_config.get("implementation_freeze_commit") != config["inherited_labels"]["implementation_freeze_commit"]:
        raise RegimeMarginalPairwiseShadowV1Error("label implementation freeze mismatch")

    start = _utc(config["prospective_start_utc"])
    as_of = _utc(as_of_utc)
    symbols = [str(symbol) for symbol in config["source"]["symbols"]]
    missing = [symbol for symbol in symbols if symbol not in frames]
    if missing:
        raise RegimeMarginalPairwiseShadowV1Error(f"missing frames: {missing}")
    clean = {
        symbol: _validate_frame(frames[symbol], symbol=symbol, as_of=as_of)
        for symbol in symbols
    }
    state_frames = build_states(clean, label_config)
    cost = float(config["economics"]["round_trip_cost_bps"])

    rows_by_strategy: dict[str, list[dict[str, Any]]] = {}
    open_by_strategy: dict[str, list[dict[str, Any]]] = {}
    for variant in config["variants"]:
        audit_id = str(variant["audit_id"])
        completed: list[dict[str, Any]] = []
        open_snapshots: list[dict[str, Any]] = []
        for symbol in symbols:
            result = run_canonical_backtest(
                clean[symbol],
                legacy_strategy(str(variant["family"])),
                dict(variant["parameters"]),
                ExecutionModel(
                    round_trip_cost_bps=cost,
                    max_abs_position=float(config["economics"]["max_abs_position"]),
                ),
            )
            for trade in result.get("trades_ledger") or []:
                classification = classify_ledger_trade(trade, start)
                if classification == "PRE_START_EXCLUDED":
                    continue
                annotated = {
                    "audit_id": audit_id,
                    "symbol": symbol,
                    "entry": _utc(trade["entry"]).isoformat(),
                    "exit": str(trade["exit"]),
                    "net_bps": float(trade["net_bps"]),
                    "gross_bps": float(trade["gross_bps"]),
                    "mfe_bps": (
                        float(trade["mfe_bps"])
                        if trade.get("mfe_bps") is not None
                        else None
                    ),
                    "mae_bps": (
                        float(trade["mae_bps"])
                        if trade.get("mae_bps") is not None
                        else None
                    ),
                    "terminal_liquidation": bool(trade.get("terminal_liquidation")),
                    **state_at_entry(state_frames[symbol], trade["entry"]),
                }
                if classification == "COMPLETED_SCORED":
                    completed.append(annotated)
                else:
                    open_snapshots.append(annotated)
        rows_by_strategy[audit_id] = completed
        open_by_strategy[audit_id] = open_snapshots

    all_completed = [row for rows in rows_by_strategy.values() for row in rows]
    block_days = int(config["prospective_reporting"]["bootstrap"]["block_days"])
    delta = pd.Timedelta(days=block_days)
    for row in all_completed:
        row["_block_id"] = int((_utc(row["entry"]) - start) // delta)
    unique_blocks = sorted({int(row["_block_id"]) for row in all_completed})
    lookup = {value: index for index, value in enumerate(unique_blocks)}
    for row in all_completed:
        row["_block_index"] = lookup[int(row["_block_id"])]

    days_elapsed = (
        max(0, int((as_of - start).total_seconds() // 86400))
        if as_of >= start
        else 0
    )
    review_days = int(config["prospective_reporting"]["review_after_calendar_days"])
    inferential_window_open = days_elapsed >= review_days
    bootstrap_cfg = config["prospective_reporting"]["bootstrap"]
    weights = (
        _bootstrap_weights(
            len(unique_blocks),
            int(bootstrap_cfg["replicates"]),
            int(bootstrap_cfg["seed"]),
        )
        if inferential_window_open and unique_blocks
        else np.zeros((0, len(unique_blocks)), dtype=np.int32)
    )

    eligibility = config["prospective_reporting"]["contrast_eligibility"]
    minimum_group = int(eligibility["minimum_group_trades"])
    minimum_complement = int(eligibility["minimum_complement_trades"])
    minimum_symbols = int(eligibility["minimum_group_symbols"])
    minimum_group_blocks = int(eligibility["minimum_group_blocks"])
    minimum_complement_blocks = int(eligibility["minimum_complement_blocks"])
    minimum_valid = int(eligibility["minimum_valid_bootstrap_replicates"])
    alpha = float(config["prospective_reporting"]["multiplicity"]["alpha"])
    specs = all_specs()
    anchors = _anchor_map(anchor_binding)

    strategy_reports: list[dict[str, Any]] = []
    for variant in config["variants"]:
        audit_id = str(variant["audit_id"])
        rows = rows_by_strategy[audit_id]
        contrasts: list[dict[str, Any]] = []
        for spec in specs:
            pool = [
                row
                for row in rows
                if all(_known(row, axis) for axis in spec["axes"])
            ]
            group = [row for row in pool if _matches(row, spec)]
            complement = [row for row in pool if not _matches(row, spec)]
            group_summary = _summary(group)
            complement_summary = _summary(complement)
            breadth = bool(
                group_summary["trade_count"] >= minimum_group
                and complement_summary["trade_count"] >= minimum_complement
                and group_summary["observed_symbol_count"] >= minimum_symbols
                and group_summary["distinct_30d_block_count"] >= minimum_group_blocks
                and complement_summary["distinct_30d_block_count"] >= minimum_complement_blocks
            )
            bootstrap = {
                "observed_difference_bps": (
                    float(group_summary["expectancy_bps"] - complement_summary["expectancy_bps"])
                    if group_summary["expectancy_bps"] is not None
                    and complement_summary["expectancy_bps"] is not None
                    else None
                ),
                "null_centered_two_sided_block_bootstrap_p": None,
                "valid_replicates": 0,
            }
            if inferential_window_open and breadth and len(unique_blocks) > 0:
                flags = np.asarray([_matches(row, spec) for row in pool], dtype=bool)
                bootstrap = _contrast_bootstrap(
                    pool,
                    flags,
                    weights,
                    len(unique_blocks),
                )
            inference_eligible = bool(
                inferential_window_open
                and breadth
                and bootstrap["valid_replicates"] >= minimum_valid
                and bootstrap["null_centered_two_sided_block_bootstrap_p"] is not None
            )
            if not inference_eligible:
                bootstrap["null_centered_two_sided_block_bootstrap_p"] = None

            contrasts.append(
                {
                    **spec,
                    "pool_trade_count": len(pool),
                    "group": group_summary,
                    "complement": complement_summary,
                    "expectancy_difference_bps": bootstrap["observed_difference_bps"],
                    "symbol_breadth": _symbol_breadth(group, complement),
                    "breadth_eligible": breadth,
                    "inferential_window_open": inferential_window_open,
                    "inference_eligible": inference_eligible,
                    "bootstrap": bootstrap,
                }
            )

        multiplicity = (
            _apply_adjustments(contrasts, alpha)
            if inferential_window_open
            else {
                "eligible_test_count": 0,
                "bh_fdr_discovery_count": 0,
                "by_fdr_discovery_count": 0,
                "holm_fwer_discovery_count": 0,
            }
        )
        if not inferential_window_open:
            for row in contrasts:
                row["global_multiplicity"] = {
                    "bh_fdr_q": None,
                    "by_dependency_robust_fdr_q": None,
                    "holm_fwer_p": None,
                    "bh_fdr_10pct": False,
                    "by_fdr_10pct": False,
                    "holm_fwer_10pct": False,
                }

        anchor_results: list[dict[str, Any]] = []
        contrast_by_id = {row["contrast_id"]: row for row in contrasts}
        for contrast_id, anchor in anchors.get(audit_id, {}).items():
            row = contrast_by_id.get(contrast_id)
            if row is None:
                raise RegimeMarginalPairwiseShadowV1Error(
                    f"missing frozen anchor contrast: {audit_id}/{contrast_id}"
                )
            historical_direction = int(anchor["historical_direction"])
            prospective_difference = row["expectancy_difference_bps"]
            same_sign = (
                prospective_difference is not None
                and prospective_difference != 0.0
                and (1 if prospective_difference > 0.0 else -1) == historical_direction
            )
            holm = row["global_multiplicity"]["holm_fwer_p"]
            if not inferential_window_open or not row["inference_eligible"]:
                verdict = "WITHHELD"
            elif same_sign and holm is not None and float(holm) <= alpha:
                verdict = "REPLICATED_DESCRIPTIVELY"
            else:
                verdict = "NOT_REPLICATED"
            anchor_results.append(
                {
                    "contrast_id": contrast_id,
                    "historical_direction": historical_direction,
                    "prospective_expectancy_difference_bps": prospective_difference,
                    "direction_matches": bool(same_sign),
                    "prospective_global_holm_fwer_p": holm,
                    "verdict": verdict,
                }
            )

        strategy_reports.append(
            {
                "audit_id": audit_id,
                "family": variant["family"],
                "parameters": variant["parameters"],
                "completed_post_start_trade_count": len(rows),
                "open_post_start_snapshot_count": len(open_by_strategy[audit_id]),
                "fixed_contrast_count": len(contrasts),
                "multiplicity_audit": multiplicity,
                "historical_anchor_count": len(anchors.get(audit_id, {})),
                "anchor_replications": anchor_results,
                "contrasts": contrasts,
                "completed_trades": [
                    {k: v for k, v in row.items() if not k.startswith("_")}
                    for row in sorted(rows, key=lambda item: (item["entry"], item["symbol"]))
                ],
                "open_terminal_snapshots_not_scored": [
                    {k: v for k, v in row.items() if not k.startswith("_")}
                    for row in sorted(
                        open_by_strategy[audit_id],
                        key=lambda item: (item["entry"], item["symbol"]),
                    )
                ],
            }
        )

    if as_of < start:
        status = "PRE_START"
    elif days_elapsed < review_days:
        status = "ACCUMULATING"
    else:
        status = "READY_FOR_FORMAL_REVIEW"

    return {
        "schema_version": 1,
        "analysis": "universal_regime_marginal_pairwise_prospective_shadow_v1",
        "watch_id": config["watch_id"],
        "status": status,
        "prospective_start_utc": start.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "calendar_days_elapsed": days_elapsed,
        "review_after_calendar_days": review_days,
        "inferential_window_open": inferential_window_open,
        "historical_anchor_count": int(anchor_binding["total_anchor_count"]),
        "historical_anchor_binding_id": anchor_binding["binding_id"],
        "source": config["source"],
        "economics": config["economics"],
        "reports": strategy_reports,
        "claims": {
            **dict(config["claims"]),
            "pre_start_entries_excluded": True,
            "terminal_snapshot_liquidations_not_scored": True,
            "incomplete_8h_bars_excluded": True,
            "early_inferential_p_values_withheld": True,
            "formal_anchor_verdicts_withheld_before_review_window": True,
            "verified_out_of_sample_evidence": False,
        },
    }
