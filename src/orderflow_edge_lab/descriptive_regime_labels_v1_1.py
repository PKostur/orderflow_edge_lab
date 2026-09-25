from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from orderflow_edge_lab.descriptive_regime_labels_v1 import (
    bh,
    build_report,
    holm,
)
from orderflow_edge_lab.universal_existing_validation import load_protocol, load_snapshot


class RegimeV11Error(ValueError):
    pass


def _utc(value: Any) -> pd.Timestamp:
    out = pd.Timestamp(value)
    return out.tz_localize("UTC") if out.tzinfo is None else out.tz_convert("UTC")


def _null_centered_block_p(
    rows: Sequence[Mapping[str, Any]],
    samples: Sequence[Counter[int]],
) -> dict[str, Any]:
    values = np.asarray([float(row["net_bps"]) for row in rows], dtype=float)
    if values.size == 0:
        return {
            "null_centered_two_sided_block_bootstrap_p": None,
            "valid_replicates": 0,
            "observed_expectancy_bps": None,
        }
    observed = float(values.mean())
    residuals = values - observed
    null_stats: list[float] = []
    for weights in samples:
        sampled: list[float] = []
        for row, residual in zip(rows, residuals):
            weight = int(weights.get(int(row["_block_id"]), 0))
            if weight > 0:
                sampled.extend([float(residual)] * weight)
        if sampled:
            null_stats.append(float(np.mean(sampled)))
    if not null_stats:
        return {
            "null_centered_two_sided_block_bootstrap_p": None,
            "valid_replicates": 0,
            "observed_expectancy_bps": observed,
        }
    exceed = sum(abs(value) >= abs(observed) for value in null_stats)
    return {
        "null_centered_two_sided_block_bootstrap_p": float((1 + exceed) / (len(null_stats) + 1)),
        "valid_replicates": len(null_stats),
        "observed_expectancy_bps": observed,
    }


def _samples(blocks: Sequence[int], *, replicates: int, seed: int) -> list[Counter[int]]:
    if not blocks or replicates <= 0:
        return []
    rng = np.random.default_rng(seed)
    arr = np.asarray(blocks, dtype=int)
    return [
        Counter(int(value) for value in rng.choice(arr, size=len(arr), replace=True))
        for _ in range(replicates)
    ]


def build_report_v1_1(
    source: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if config.get("protocol_name") != "universal-descriptive-regime-labels-v1.1":
        raise RegimeV11Error("wrong v1.1 protocol")
    inherited = config.get("inherits")
    if not isinstance(inherited, Mapping) or inherited.get("label_protocol") != "universal-descriptive-regime-labels-v1":
        raise RegimeV11Error("v1.1 must inherit the frozen v1 label protocol")

    v1_config = dict(config["frozen_v1_label_contract"])
    v1_config["protocol_name"] = "universal-descriptive-regime-labels-v1"
    base = build_report(source, frames, v1_config)

    bootstrap = config["inference"]["bootstrap"]
    minimum_trades = int(config["inference"]["minimum_trades_for_hypothesis_test"])
    if minimum_trades < 2:
        raise RegimeV11Error("minimum tested cell size must be >= 2")

    all_rows: list[dict[str, Any]] = []
    for strategy in base["strategies"]:
        all_rows.extend(strategy["trades"])
    if all_rows:
        origin = min(_utc(row["entry"]) for row in all_rows).normalize()
        block = pd.Timedelta(days=int(bootstrap["block_days"]))
        for row in all_rows:
            row["_block_id"] = int((_utc(row["entry"]) - origin) // block)
        blocks = sorted({int(row["_block_id"]) for row in all_rows})
    else:
        origin = None
        blocks = []
    samples = _samples(
        blocks,
        replicates=int(bootstrap["replicates"]),
        seed=int(bootstrap["seed"]),
    )

    alpha = float(config["inference"]["multiplicity"]["alpha"])
    strategy_audits: list[dict[str, Any]] = []
    for strategy in base["strategies"]:
        trade_rows = strategy["trades"]
        by_cell: dict[str, list[dict[str, Any]]] = {}
        for row in trade_rows:
            keys = (
                row.get("trend_state"),
                row.get("volatility_state"),
                row.get("coupling_state"),
                row.get("shock_state"),
                row.get("drawdown_state"),
            )
            if any(value in (None, "UNKNOWN") for value in keys):
                continue
            cell_id = "|".join(
                (
                    f"TREND={keys[0]}",
                    f"VOL={keys[1]}",
                    f"COUPLING={keys[2]}",
                    f"SHOCK={keys[3]}",
                    f"DRAWDOWN={keys[4]}",
                )
            )
            by_cell.setdefault(cell_id, []).append(row)

        positions: list[int] = []
        p_values: list[float] = []
        invalid_v1_flag_count = 0
        for index, cell in enumerate(strategy["joint_cells"]):
            cell["v1_bootstrap_p_invalidated"] = cell["bootstrap_expectancy"].get(
                "two_sided_centered_bootstrap_p"
            ) is not None
            invalid_v1_flag_count += int(cell["v1_bootstrap_p_invalidated"])
            cell["bootstrap_expectancy"].pop("two_sided_centered_bootstrap_p", None)
            cell["bh_fdr_q"] = None
            cell["holm_fwer_p"] = None
            cell["bh_fdr_10pct"] = False
            cell["holm_fwer_10pct"] = False
            cell_rows = by_cell.get(cell["cell_id"], [])
            cell["hypothesis_test_eligible"] = len(cell_rows) >= minimum_trades
            cell["v1_1_null_test"] = {
                "null_centered_two_sided_block_bootstrap_p": None,
                "valid_replicates": 0,
                "observed_expectancy_bps": cell.get("expectancy_bps"),
            }
            if not cell["hypothesis_test_eligible"]:
                continue
            result = _null_centered_block_p(cell_rows, samples)
            cell["v1_1_null_test"] = result
            p = result["null_centered_two_sided_block_bootstrap_p"]
            if p is not None:
                positions.append(index)
                p_values.append(float(p))

        q_values = bh(p_values)
        holm_values = holm(p_values)
        for index, q_value, holm_value in zip(positions, q_values, holm_values):
            cell = strategy["joint_cells"][index]
            cell["bh_fdr_q"] = float(q_value)
            cell["holm_fwer_p"] = float(holm_value)
            cell["bh_fdr_10pct"] = bool(q_value <= alpha)
            cell["holm_fwer_10pct"] = bool(holm_value <= alpha)

        strategy_audits.append(
            {
                "audit_id": strategy["audit_id"],
                "nonempty_joint_cell_count": sum(cell["trade_count"] > 0 for cell in strategy["joint_cells"]),
                "tested_joint_cell_count": len(positions),
                "v1_invalid_p_value_cell_count": invalid_v1_flag_count,
                "bh_fdr_discovery_count_at_alpha": sum(cell["bh_fdr_10pct"] for cell in strategy["joint_cells"]),
                "holm_fwer_discovery_count_at_alpha": sum(cell["holm_fwer_10pct"] for cell in strategy["joint_cells"]),
            }
        )

    base.update(
        {
            "analysis": "universal_descriptive_regime_labels_v1_1",
            "protocol_name": config["protocol_name"],
            "v1_label_contract_unchanged": True,
            "v1_inference_status": "invalidated_due_to_null_bootstrap_implementation_error",
            "v1_inference_failure_mode": (
                "v1 compared abs(bootstrap_mean-observed_mean) with abs(observed_mean) "
                "without resampling under the zero-mean null; sparse cells could therefore "
                "receive spuriously tiny p-values, including one-trade cells."
            ),
            "v1_1_inference": {
                **config["inference"],
                "calendar_block_origin": origin.isoformat() if origin is not None else None,
                "calendar_block_count": len(blocks),
                "shared_block_draws_across_symbols_strategies_and_cells": True,
                "strategy_audit": strategy_audits,
            },
            "claims": dict(config["claims"]),
        }
    )
    base["bootstrap"] = {
        **base["bootstrap"],
        "v1_percentile_confidence_intervals_retained_as_descriptive_intervals": True,
        "v1_raw_p_values_and_adjusted_flags_invalidated": True,
    }
    return base


def run_from_paths_v1_1(
    source_protocol_path: str | Path,
    regime_config_path: str | Path,
    data_dir: str | Path,
) -> dict[str, Any]:
    source = load_protocol(source_protocol_path)
    config = json.loads(Path(regime_config_path).read_text(encoding="utf-8"))
    frames, snapshot = load_snapshot(source, data_dir)
    report = build_report_v1_1(source, frames, config)
    report["source_snapshot"] = snapshot
    report["source_protocol_sha256"] = hashlib.sha256(Path(source_protocol_path).read_bytes()).hexdigest()
    report["regime_config_sha256"] = hashlib.sha256(Path(regime_config_path).read_bytes()).hexdigest()
    return report
