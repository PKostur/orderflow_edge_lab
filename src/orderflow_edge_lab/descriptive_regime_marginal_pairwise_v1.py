from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.descriptive_regime_labels_v1 import build_states, state_at_entry
from orderflow_edge_lab.universal_backtest import ExecutionModel, legacy_strategy, run_canonical_backtest
from orderflow_edge_lab.universal_existing_validation import load_protocol, load_snapshot


class RegimeMarginalPairwiseV1Error(ValueError):
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


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def marginal_specs() -> list[dict[str, Any]]:
    return [
        {
            "tier": "marginal",
            "contrast_id": f"MARGINAL|{axis}={state}",
            "axes": [axis],
            "states": [state],
        }
        for axis, states in AXES
        for state in states
    ]


def pairwise_specs() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for (left_axis, left_states), (right_axis, right_states) in itertools.combinations(AXES, 2):
        for left_state, right_state in itertools.product(left_states, right_states):
            result.append(
                {
                    "tier": "pairwise",
                    "contrast_id": (
                        f"PAIR|{left_axis}={left_state}|{right_axis}={right_state}"
                    ),
                    "axes": [left_axis, right_axis],
                    "states": [left_state, right_state],
                }
            )
    return result


def all_specs() -> list[dict[str, Any]]:
    return marginal_specs() + pairwise_specs()


def _bh(values: Sequence[float], multiplier: float = 1.0) -> list[float]:
    n = len(values)
    if n == 0:
        return []
    ordered = sorted(range(n), key=lambda i: values[i])
    out = [1.0] * n
    running = 1.0
    for reverse_rank, index in enumerate(reversed(ordered), start=1):
        rank = n - reverse_rank + 1
        running = min(
            running,
            min(1.0, float(values[index]) * n * multiplier / rank),
        )
        out[index] = running
    return out


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


def _by(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    harmonic = sum(1.0 / k for k in range(1, len(values) + 1))
    return _bh(values, multiplier=harmonic)


def _rows(
    source: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    label_config: Mapping[str, Any],
    cost_bps: float,
) -> dict[str, list[dict[str, Any]]]:
    states = build_states(frames, label_config)
    result: dict[str, list[dict[str, Any]]] = {}
    for spec in source["strategies"]:
        strategy_id = str(spec["audit_id"])
        family = str(spec["family"])
        strategy_rows: list[dict[str, Any]] = []
        for symbol in sorted(frames):
            canonical = run_canonical_backtest(
                frames[symbol],
                legacy_strategy(family),
                dict(spec["parameters"]),
                ExecutionModel(round_trip_cost_bps=cost_bps),
            )
            for trade in canonical.get("trades_ledger") or []:
                if trade.get("terminal_liquidation"):
                    continue
                entry = _utc(trade["entry"])
                strategy_rows.append(
                    {
                        "strategy_id": strategy_id,
                        "symbol": symbol,
                        "entry": entry.isoformat(),
                        "exit": str(trade["exit"]),
                        "net_bps": float(trade["net_bps"]),
                        "gross_bps": float(trade["gross_bps"]),
                        "mfe_bps": _finite(trade.get("mfe_bps")),
                        "mae_bps": _finite(trade.get("mae_bps")),
                        **state_at_entry(states[symbol], entry),
                    }
                )
        result[strategy_id] = strategy_rows
    return result


def _summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trade_count": 0,
            "expectancy_bps": None,
            "median_net_bps": None,
            "win_rate": None,
            "correct_direction_rate": None,
            "median_mfe_bps": None,
            "median_abs_mae_bps": None,
            "observed_symbol_count": 0,
            "distinct_30d_block_count": 0,
        }
    net = np.asarray([float(row["net_bps"]) for row in rows], dtype=float)
    gross = np.asarray([float(row["gross_bps"]) for row in rows], dtype=float)
    mfe = [float(row["mfe_bps"]) for row in rows if _finite(row.get("mfe_bps")) is not None]
    mae = [abs(float(row["mae_bps"])) for row in rows if _finite(row.get("mae_bps")) is not None]
    return {
        "trade_count": len(rows),
        "expectancy_bps": float(net.mean()),
        "median_net_bps": float(np.median(net)),
        "win_rate": float(np.mean(net > 0.0)),
        "correct_direction_rate": float(np.mean(gross > 0.0)),
        "median_mfe_bps": float(np.median(mfe)) if mfe else None,
        "median_abs_mae_bps": float(np.median(mae)) if mae else None,
        "observed_symbol_count": len({str(row["symbol"]) for row in rows}),
        "distinct_30d_block_count": len({int(row["_block_id"]) for row in rows}),
    }


def _per_symbol_difference(
    group: Sequence[Mapping[str, Any]],
    complement: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    g: dict[str, list[float]] = {}
    c: dict[str, list[float]] = {}
    for row in group:
        g.setdefault(str(row["symbol"]), []).append(float(row["net_bps"]))
    for row in complement:
        c.setdefault(str(row["symbol"]), []).append(float(row["net_bps"]))
    diffs = {
        symbol: float(np.mean(g[symbol]) - np.mean(c[symbol]))
        for symbol in sorted(set(g) & set(c))
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
    if block_count <= 0 or replicates <= 0:
        return np.zeros((0, max(0, block_count)), dtype=np.int32)
    rng = np.random.default_rng(seed)
    weights = np.zeros((replicates, block_count), dtype=np.int32)
    for i in range(replicates):
        draw = rng.integers(0, block_count, size=block_count)
        weights[i] = np.bincount(draw, minlength=block_count)
    return weights


def _contrast_bootstrap(
    pool: Sequence[Mapping[str, Any]],
    group_flags: np.ndarray,
    weights: np.ndarray,
    block_count: int,
    confidence_interval: Sequence[float],
) -> dict[str, Any]:
    if not pool or not group_flags.any() or group_flags.all():
        return {
            "observed_difference_bps": None,
            "raw_bootstrap_ci_lower_bps": None,
            "raw_bootstrap_ci_upper_bps": None,
            "null_centered_two_sided_block_bootstrap_p": None,
            "valid_replicates": 0,
        }

    y = np.asarray([float(row["net_bps"]) for row in pool], dtype=float)
    block_index = np.asarray([int(row["_block_index"]) for row in pool], dtype=int)
    comp_flags = ~group_flags
    group_mean = float(y[group_flags].mean())
    comp_mean = float(y[comp_flags].mean())
    observed = group_mean - comp_mean
    pooled_mean = float(y.mean())

    null_y = y.copy()
    null_y[group_flags] = y[group_flags] - group_mean + pooled_mean
    null_y[comp_flags] = y[comp_flags] - comp_mean + pooled_mean

    def per_block(values: np.ndarray, flags: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        counts = np.bincount(block_index[flags], minlength=block_count).astype(float)
        sums = np.bincount(
            block_index[flags],
            weights=values[flags],
            minlength=block_count,
        ).astype(float)
        return counts, sums

    gc, gs = per_block(y, group_flags)
    cc, cs = per_block(y, comp_flags)
    ngc, ngs = per_block(null_y, group_flags)
    ncc, ncs = per_block(null_y, comp_flags)

    sample_gc = weights @ gc
    sample_cc = weights @ cc
    valid = (sample_gc > 0.0) & (sample_cc > 0.0)
    if not valid.any():
        return {
            "observed_difference_bps": observed,
            "raw_bootstrap_ci_lower_bps": None,
            "raw_bootstrap_ci_upper_bps": None,
            "null_centered_two_sided_block_bootstrap_p": None,
            "valid_replicates": 0,
        }

    raw_diff = (
        (weights @ gs)[valid] / sample_gc[valid]
        - (weights @ cs)[valid] / sample_cc[valid]
    )
    null_diff = (
        (weights @ ngs)[valid] / sample_gc[valid]
        - (weights @ ncs)[valid] / sample_cc[valid]
    )
    lower, upper = (float(value) for value in confidence_interval)
    p = (1 + int(np.sum(np.abs(null_diff) >= abs(observed)))) / (1 + len(null_diff))
    return {
        "observed_difference_bps": observed,
        "raw_bootstrap_ci_lower_bps": float(np.quantile(raw_diff, lower)),
        "raw_bootstrap_ci_upper_bps": float(np.quantile(raw_diff, upper)),
        "null_centered_two_sided_block_bootstrap_p": float(p),
        "valid_replicates": int(len(null_diff)),
    }


def _known(row: Mapping[str, Any], axis: str, states: Sequence[str]) -> bool:
    return str(row.get(axis)) in set(states)


def _matching(row: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    return all(
        str(row.get(axis)) == state
        for axis, state in zip(spec["axes"], spec["states"])
    )


def _apply_adjustments(
    contrasts: list[dict[str, Any]],
    *,
    alpha: float,
) -> dict[str, Any]:
    eligible = [
        i
        for i, row in enumerate(contrasts)
        if row["bootstrap"]["null_centered_two_sided_block_bootstrap_p"] is not None
    ]
    global_p = [
        float(contrasts[i]["bootstrap"]["null_centered_two_sided_block_bootstrap_p"])
        for i in eligible
    ]
    global_bh = _bh(global_p)
    global_by = _by(global_p)
    global_holm = _holm(global_p)
    for index, q_bh, q_by, p_holm in zip(
        eligible, global_bh, global_by, global_holm
    ):
        row = contrasts[index]
        row["global_multiplicity"] = {
            "bh_fdr_q": q_bh,
            "by_dependency_robust_fdr_q": q_by,
            "holm_fwer_p": p_holm,
            "bh_fdr_10pct": q_bh <= alpha,
            "by_fdr_10pct": q_by <= alpha,
            "holm_fwer_10pct": p_holm <= alpha,
        }

    tier_summary: dict[str, Any] = {}
    for tier in ("marginal", "pairwise"):
        indices = [
            i
            for i in eligible
            if contrasts[i]["tier"] == tier
        ]
        ps = [
            float(contrasts[i]["bootstrap"]["null_centered_two_sided_block_bootstrap_p"])
            for i in indices
        ]
        bh = _bh(ps)
        by = _by(ps)
        holm = _holm(ps)
        for index, q_bh, q_by, p_holm in zip(indices, bh, by, holm):
            contrasts[index]["tier_multiplicity"] = {
                "bh_fdr_q": q_bh,
                "by_dependency_robust_fdr_q": q_by,
                "holm_fwer_p": p_holm,
                "bh_fdr_10pct": q_bh <= alpha,
                "by_fdr_10pct": q_by <= alpha,
                "holm_fwer_10pct": p_holm <= alpha,
            }
        tier_summary[tier] = {
            "eligible_test_count": len(indices),
            "bh_fdr_discovery_count": sum(q <= alpha for q in bh),
            "by_fdr_discovery_count": sum(q <= alpha for q in by),
            "holm_fwer_discovery_count": sum(p <= alpha for p in holm),
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
        row.setdefault(
            "tier_multiplicity",
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
        "global_eligible_test_count": len(eligible),
        "global_bh_fdr_discovery_count": sum(q <= alpha for q in global_bh),
        "global_by_fdr_discovery_count": sum(q <= alpha for q in global_by),
        "global_holm_fwer_discovery_count": sum(p <= alpha for p in global_holm),
        "tiers": tier_summary,
    }


def build_report(
    source: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    label_config: Mapping[str, Any],
    analysis_config: Mapping[str, Any],
) -> dict[str, Any]:
    if label_config.get("protocol_name") != "universal-descriptive-regime-labels-v1":
        raise RegimeMarginalPairwiseV1Error("wrong inherited label protocol")
    if analysis_config.get("protocol_name") != "universal-descriptive-regime-marginal-pairwise-v1":
        raise RegimeMarginalPairwiseV1Error("wrong marginal/pairwise protocol")
    expected_freeze = str(analysis_config["inherits"]["label_implementation_freeze_commit"])
    if str(label_config.get("implementation_freeze_commit")) != expected_freeze:
        raise RegimeMarginalPairwiseV1Error("inherited v1 label implementation freeze mismatch")

    specs = all_specs()
    if len(marginal_specs()) != 14 or len(pairwise_specs()) != 78 or len(specs) != 92:
        raise RegimeMarginalPairwiseV1Error("fixed contrast family changed")

    cost_bps = float(analysis_config["primary_cost_bps"])
    rows_by_strategy = _rows(source, frames, label_config, cost_bps)
    all_rows = [row for rows in rows_by_strategy.values() for row in rows]
    bootstrap_cfg = analysis_config["bootstrap"]
    block_days = int(bootstrap_cfg["block_days"])

    if all_rows:
        origin = min(_utc(row["entry"]) for row in all_rows).normalize()
        delta = pd.Timedelta(days=block_days)
        for row in all_rows:
            row["_block_id"] = int((_utc(row["entry"]) - origin) // delta)
        unique_blocks = sorted({int(row["_block_id"]) for row in all_rows})
        block_lookup = {value: index for index, value in enumerate(unique_blocks)}
        for row in all_rows:
            row["_block_index"] = block_lookup[int(row["_block_id"])]
    else:
        origin = None
        unique_blocks = []

    weights = _bootstrap_weights(
        len(unique_blocks),
        int(bootstrap_cfg["replicates"]),
        int(bootstrap_cfg["seed"]),
    )
    rules = analysis_config["eligibility"]
    minimum_group = int(rules["minimum_group_trades"])
    minimum_complement = int(rules["minimum_complement_trades"])
    minimum_symbols = int(rules["minimum_group_symbols"])
    minimum_blocks = int(rules["minimum_group_blocks"])
    minimum_complement_blocks = int(rules["minimum_complement_blocks"])
    minimum_valid = int(rules["minimum_valid_bootstrap_replicates"])
    alpha = float(analysis_config["multiplicity"]["alpha"])

    strategy_reports: list[dict[str, Any]] = []
    for source_spec in source["strategies"]:
        strategy_id = str(source_spec["audit_id"])
        rows = rows_by_strategy[strategy_id]
        contrasts: list[dict[str, Any]] = []
        for spec in specs:
            axes = list(spec["axes"])
            axis_state_map = dict(AXES)
            pool = [
                row
                for row in rows
                if all(_known(row, axis, axis_state_map[axis]) for axis in axes)
            ]
            group = [row for row in pool if _matching(row, spec)]
            complement = [row for row in pool if not _matching(row, spec)]
            group_summary = _summary(group)
            complement_summary = _summary(complement)
            breadth_eligible = bool(
                group_summary["trade_count"] >= minimum_group
                and complement_summary["trade_count"] >= minimum_complement
                and group_summary["observed_symbol_count"] >= minimum_symbols
                and group_summary["distinct_30d_block_count"] >= minimum_blocks
                and complement_summary["distinct_30d_block_count"] >= minimum_complement_blocks
            )
            group_ids = {id(row) for row in group}
            flags = np.asarray([id(row) in group_ids for row in pool], dtype=bool)
            bootstrap = (
                _contrast_bootstrap(
                    pool,
                    flags,
                    weights,
                    len(unique_blocks),
                    bootstrap_cfg["confidence_interval"],
                )
                if breadth_eligible
                else {
                    "observed_difference_bps": (
                        float(group_summary["expectancy_bps"] - complement_summary["expectancy_bps"])
                        if group_summary["expectancy_bps"] is not None
                        and complement_summary["expectancy_bps"] is not None
                        else None
                    ),
                    "raw_bootstrap_ci_lower_bps": None,
                    "raw_bootstrap_ci_upper_bps": None,
                    "null_centered_two_sided_block_bootstrap_p": None,
                    "valid_replicates": 0,
                }
            )
            inference_eligible = bool(
                breadth_eligible
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
                    "expectancy_difference_bps": (
                        float(group_summary["expectancy_bps"] - complement_summary["expectancy_bps"])
                        if group_summary["expectancy_bps"] is not None
                        and complement_summary["expectancy_bps"] is not None
                        else None
                    ),
                    "symbol_breadth": _per_symbol_difference(group, complement),
                    "breadth_eligible": breadth_eligible,
                    "inference_eligible": inference_eligible,
                    "bootstrap": bootstrap,
                }
            )

        multiplicity_audit = _apply_adjustments(contrasts, alpha=alpha)
        strategy_reports.append(
            {
                "audit_id": strategy_id,
                "family": str(source_spec["family"]),
                "parameters": dict(source_spec["parameters"]),
                "completed_nonterminal_trade_count": len(rows),
                "contrast_count": len(contrasts),
                "marginal_contrast_count": sum(row["tier"] == "marginal" for row in contrasts),
                "pairwise_contrast_count": sum(row["tier"] == "pairwise" for row in contrasts),
                "multiplicity_audit": multiplicity_audit,
                "contrasts": contrasts,
            }
        )

    contract = {
        "axes": [{"axis": axis, "states": list(states)} for axis, states in AXES],
        "contrast_ids": [spec["contrast_id"] for spec in specs],
        "hierarchy": analysis_config["hierarchy"],
    }
    contract_hash = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    return {
        "schema_version": 1,
        "analysis": "universal_descriptive_regime_marginal_pairwise_v1",
        "protocol_name": analysis_config["protocol_name"],
        "source_protocol_name": source["protocol_name"],
        "inherited_label_protocol": label_config["protocol_name"],
        "inherited_label_implementation_freeze_commit": expected_freeze,
        "primary_cost_bps": cost_bps,
        "fixed_marginal_contrast_count_per_strategy": 14,
        "fixed_pairwise_contrast_count_per_strategy": 78,
        "fixed_total_contrast_count_per_strategy": 92,
        "contrast_contract_sha256": contract_hash,
        "bootstrap": {
            **dict(bootstrap_cfg),
            "calendar_block_origin": origin.isoformat() if origin is not None else None,
            "calendar_block_count": len(unique_blocks),
            "shared_block_draws_across_symbols_strategies_and_contrasts": True,
        },
        "eligibility": dict(rules),
        "hierarchy": analysis_config["hierarchy"],
        "multiplicity": analysis_config["multiplicity"],
        "strategies": strategy_reports,
        "claims": analysis_config["claims"],
        "literature_basis": analysis_config.get("literature_basis", []),
    }


def run_from_paths(
    source_protocol_path: str | Path,
    label_config_path: str | Path,
    analysis_config_path: str | Path,
    data_dir: str | Path,
) -> dict[str, Any]:
    source = load_protocol(source_protocol_path)
    label_config = json.loads(Path(label_config_path).read_text(encoding="utf-8"))
    analysis_config = json.loads(Path(analysis_config_path).read_text(encoding="utf-8"))
    frames, snapshot = load_snapshot(source, data_dir)
    report = build_report(source, frames, label_config, analysis_config)
    report["source_snapshot"] = snapshot
    report["source_protocol_sha256"] = hashlib.sha256(Path(source_protocol_path).read_bytes()).hexdigest()
    report["label_config_sha256"] = hashlib.sha256(Path(label_config_path).read_bytes()).hexdigest()
    report["analysis_config_sha256"] = hashlib.sha256(Path(analysis_config_path).read_bytes()).hexdigest()
    return report
