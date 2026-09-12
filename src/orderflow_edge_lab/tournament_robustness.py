from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from statistics import median
from typing import Any, Mapping


@dataclass(frozen=True)
class SymbolBreadthGate:
    minimum_symbol_observations: int = 8
    minimum_positive_expectancy_fraction: float = 0.60
    minimum_profit_factor_gt_one_fraction: float = 0.60
    require_positive_median_expectancy: bool = True
    require_median_profit_factor_gt_one: bool = True


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _profit_factor(value: Any) -> float | None:
    if value == "INF":
        return math.inf
    return _finite(value)


def _fraction(count: int, denominator: int) -> float | None:
    return count / denominator if denominator else None


def apply_symbol_breadth_gate(
    leaderboard: Mapping[str, Any],
    gate: SymbolBreadthGate = SymbolBreadthGate(),
) -> dict[str, Any]:
    if gate.minimum_symbol_observations <= 0:
        raise ValueError("minimum_symbol_observations must be positive")
    if not 0.0 <= gate.minimum_positive_expectancy_fraction <= 1.0:
        raise ValueError("minimum_positive_expectancy_fraction must be in [0, 1]")
    if not 0.0 <= gate.minimum_profit_factor_gt_one_fraction <= 1.0:
        raise ValueError("minimum_profit_factor_gt_one_fraction must be in [0, 1]")

    output = deepcopy(dict(leaderboard))
    rows = output.get("leaderboard", [])
    if not isinstance(rows, list):
        raise ValueError("leaderboard must contain a list")

    robust_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        per_symbol = row.get("per_symbol", [])
        if not isinstance(per_symbol, list):
            per_symbol = []

        expectancy_rows: list[tuple[str, float]] = []
        pf_rows: list[tuple[str, float]] = []
        for item in per_symbol:
            if not isinstance(item, Mapping):
                continue
            trades = int(item.get("trades") or 0)
            if trades <= 0:
                continue
            symbol = str(item.get("symbol") or "")
            expectancy = _finite(item.get("expectancy_bps"))
            if expectancy is not None:
                expectancy_rows.append((symbol, expectancy))
            pf = _profit_factor(item.get("profit_factor"))
            if pf is not None:
                pf_rows.append((symbol, pf))

        expectancy_values = [value for _, value in expectancy_rows]
        pf_values = [value for _, value in pf_rows]
        expectancy_observations = len(expectancy_values)
        pf_observations = len(pf_values)
        positive_expectancy_symbols = sum(value > 0.0 for value in expectancy_values)
        pf_gt_one_symbols = sum(value > 1.0 for value in pf_values)
        positive_expectancy_fraction = _fraction(positive_expectancy_symbols, expectancy_observations)
        pf_gt_one_fraction = _fraction(pf_gt_one_symbols, pf_observations)
        median_expectancy = median(expectancy_values) if expectancy_values else None
        median_pf = median(pf_values) if pf_values else None

        fail_reasons: list[str] = []
        if expectancy_observations < gate.minimum_symbol_observations:
            fail_reasons.append(
                f"expectancy_symbol_observations {expectancy_observations}/{gate.minimum_symbol_observations}"
            )
        if pf_observations < gate.minimum_symbol_observations:
            fail_reasons.append(f"pf_symbol_observations {pf_observations}/{gate.minimum_symbol_observations}")
        if positive_expectancy_fraction is None or positive_expectancy_fraction < gate.minimum_positive_expectancy_fraction:
            fail_reasons.append(f"positive_expectancy_symbol_fraction {positive_expectancy_fraction}")
        if pf_gt_one_fraction is None or pf_gt_one_fraction < gate.minimum_profit_factor_gt_one_fraction:
            fail_reasons.append(f"profit_factor_gt_one_symbol_fraction {pf_gt_one_fraction}")
        if gate.require_positive_median_expectancy and (median_expectancy is None or median_expectancy <= 0.0):
            fail_reasons.append(f"median_symbol_expectancy_bps {median_expectancy}")
        if gate.require_median_profit_factor_gt_one and (median_pf is None or median_pf <= 1.0):
            fail_reasons.append(f"median_symbol_profit_factor {median_pf}")

        breadth_eligible = not fail_reasons
        robust_screening_eligible = bool(row.get("screening_eligible")) and breadth_eligible
        if robust_screening_eligible:
            robust_count += 1

        row["symbol_breadth"] = {
            "expectancy_symbol_observations": expectancy_observations,
            "profit_factor_symbol_observations": pf_observations,
            "positive_expectancy_symbols": positive_expectancy_symbols,
            "positive_expectancy_symbol_fraction": positive_expectancy_fraction,
            "profit_factor_gt_one_symbols": pf_gt_one_symbols,
            "profit_factor_gt_one_symbol_fraction": pf_gt_one_fraction,
            "median_symbol_expectancy_bps": median_expectancy,
            "median_symbol_profit_factor": median_pf,
        }
        row["breadth_eligible"] = breadth_eligible
        row["breadth_fail_reasons"] = fail_reasons
        row["robust_screening_eligible"] = robust_screening_eligible

    output["symbol_breadth_gate"] = {
        "minimum_symbol_observations": gate.minimum_symbol_observations,
        "minimum_positive_expectancy_fraction": gate.minimum_positive_expectancy_fraction,
        "minimum_profit_factor_gt_one_fraction": gate.minimum_profit_factor_gt_one_fraction,
        "require_positive_median_expectancy": gate.require_positive_median_expectancy,
        "require_median_profit_factor_gt_one": gate.require_median_profit_factor_gt_one,
        "status": "development_adversarial_filter_added_after_initial_historical_screen",
    }
    output["robust_eligible_count"] = robust_count
    claims = output.setdefault("claims", {})
    claims["symbol_breadth_filter_is_final_oos"] = False
    claims["symbol_breadth_filter_can_establish_profitable_edge"] = False
    claims["historical_results_were_seen_before_symbol_breadth_filter"] = True
    return output
