from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any


class CrossPairError(ValueError):
    pass


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CrossPairError(f"{path}: expected JSON object")
    return payload


def _profit_factor(values: list[float]) -> float | str | None:
    profit = sum(value for value in values if value > 0)
    loss = -sum(value for value in values if value < 0)
    if loss > 0:
        return profit / loss
    return "INF" if profit > 0 else None


def _group_observations(observations: list[dict[str, Any]]) -> dict[tuple[str, int, float], list[dict[str, Any]]]:
    groups: dict[tuple[str, int, float], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        groups[(str(row["family"]), int(row["horizon_ms"]), float(row["fee_bps_round_trip"]))].append(row)
    return groups


def aggregate_cross_pair(screen_path: str | Path, results_dir: str | Path) -> dict[str, Any]:
    screen = _load_json(screen_path)
    selected = screen.get("selected")
    if not isinstance(selected, list) or not selected:
        raise CrossPairError("pair screen contains no selected pairs")
    metadata = {str(row.get("symbol")): row for row in selected if isinstance(row, dict) and row.get("symbol")}
    root = Path(results_dir)
    pair_rows: list[dict[str, Any]] = []
    condition_rows: list[dict[str, Any]] = []
    missing: list[str] = []

    for symbol in screen.get("selected_symbols", []):
        symbol = str(symbol)
        direction_path = root / f"direction_pair_{symbol}.json"
        conditions_path = root / f"conditions_{symbol}.json"
        if not direction_path.exists() or not conditions_path.exists():
            missing.append(symbol)
            continue
        direction = _load_json(direction_path)
        conditions = _load_json(conditions_path)
        original = _group_observations(direction["streams"]["original"]["observations"])
        reversed_groups = _group_observations(direction["streams"]["reversed"]["observations"])
        if original.keys() != reversed_groups.keys():
            raise CrossPairError(f"{symbol}: original/reversed group keys diverged")
        market = metadata.get(symbol, {})
        for key in sorted(original):
            family, horizon, fee = key
            orig_values = [float(row["net_bps"]) for row in original[key]]
            rev_values = [float(row["net_bps"]) for row in reversed_groups[key]]
            orig_mean = sum(orig_values) / len(orig_values) if orig_values else None
            rev_mean = sum(rev_values) / len(rev_values) if rev_values else None
            pair_rows.append({
                "symbol": symbol,
                "family": family,
                "horizon_ms": horizon,
                "fee_bps_round_trip": fee,
                "observations": len(orig_values),
                "original_net_profit_factor": _profit_factor(orig_values),
                "reversed_net_profit_factor": _profit_factor(rev_values),
                "original_net_mean_bps": orig_mean,
                "reversed_net_mean_bps": rev_mean,
                "original_minus_reversed_net_mean_bps": (
                    orig_mean - rev_mean if orig_mean is not None and rev_mean is not None else None
                ),
                "original_net_win_rate": sum(value > 0 for value in orig_values) / len(orig_values) if orig_values else None,
                "screen_spread_bps": market.get("spread_bps"),
                "screen_amount24_usdt": market.get("amount24_usdt"),
                "screen_range24_bps": market.get("range24_bps"),
                "screen_funding_rate": market.get("funding_rate"),
                "screen_btc_correlation": market.get("btc_correlation"),
                "screen_btc_correlation_samples": market.get("btc_correlation_samples"),
                "screen_btc_correlation_bucket": market.get("btc_correlation_bucket"),
                "screen_panel_selection_reason": market.get("panel_selection_reason"),
                "api_allowed": market.get("api_allowed"),
            })
        for row in conditions.get("condition_summary", []):
            if not isinstance(row, dict):
                continue
            condition_rows.append({"symbol": symbol, **row})

    ready_conditions = [row for row in condition_rows if row.get("screening_condition_ready") is True]
    selection_rule = screen.get("selection_rule")
    return {
        "schema_version": 1,
        "experiment": "unchanged_cross_pair_transfer_test",
        "pair_screen": {
            "source_experiment": screen.get("experiment"),
            "selection_rule": selection_rule,
            "selected_symbols": screen.get("selected_symbols"),
        },
        "pair_summary": pair_rows,
        "condition_summary": condition_rows,
        "screening_conditions_ready_across_pair_runs": ready_conditions,
        "missing_pairs": missing,
        "claims": {
            "exploratory_transfer_only": True,
            "pair_selection_used_strategy_pnl": False,
            "per_pair_threshold_tuning_performed": False,
            "verified_out_of_sample_edge": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
