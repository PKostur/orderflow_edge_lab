from __future__ import annotations

"""Diagnostics for accounting consistency in the Universal Backtest Framework.

The compatibility runner intentionally preserves the legacy engine's reported
metrics.  This module exposes the accounting differences that must be resolved
before those metrics are treated as canonical economic performance, without
silently changing the compatibility path.
"""

from typing import Any, Mapping

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_backtest import (
    ExecutionModel,
    StrategyPlugin,
    _extract_trades,
    _validate_frame,
)


def audit_accounting(
    frame: pd.DataFrame,
    strategy: StrategyPlugin,
    params: Mapping[str, Any],
    execution: ExecutionModel = ExecutionModel(),
) -> dict[str, Any]:
    """Report differences between path turnover costs and the trade ledger.

    ``run_backtest`` reports total return through the last observable open,
    which excludes the final unobservable next-bar return.  The audit therefore
    compares path costs through ``position.iloc[:-1]`` with the legacy ledger's
    fixed round-trip cost per extracted trade.  A nonzero delta is diagnostic,
    not a corrected performance result.
    """

    frame = _validate_frame(frame)
    if len(frame) < max(3, int(strategy.warmup_bars)):
        return {
            "status": "insufficient_warmup",
            "strategy_id": strategy.strategy_id,
            "bars": len(frame),
            "warmup_bars": int(strategy.warmup_bars),
            "claims": {
                "diagnostic_only": True,
                "canonical_economic_accounting_established": False,
            },
        }

    target = strategy.generate_target(frame, params).reindex(frame.index).fillna(0.0)
    if not np.isfinite(target.to_numpy(dtype=float)).all():
        raise ValueError("strategy target contains non-finite values")
    target = target.clip(-float(execution.max_abs_position), float(execution.max_abs_position))
    position = target.shift(1).fillna(0.0)
    turnover = (position - position.shift(1).fillna(0.0)).abs()
    per_turnover_cost = (
        float(execution.round_trip_cost_bps) / 2.0
        + float(execution.slippage_bps_per_turnover_unit)
    ) / 10_000.0
    evaluated_turnover = turnover.iloc[:-1] if len(turnover) > 1 else turnover.iloc[0:0]
    path_cost_bps = float(evaluated_turnover.sum() * per_turnover_cost * 10_000.0)
    trades = _extract_trades(frame, position, execution)
    ledger_cost_bps = float(
        len(trades)
        * (float(execution.round_trip_cost_bps) + 2.0 * float(execution.slippage_bps_per_turnover_unit))
    )
    terminal_position = float(position.iloc[-2]) if len(position) > 1 else 0.0
    terminal_exit_cost_bps = float(abs(terminal_position) * per_turnover_cost * 10_000.0)
    values = position.to_numpy(dtype=float)
    fractional_position_detected = bool(
        np.any(
            (np.abs(values) > 1e-12)
            & (~np.isclose(np.abs(values), 1.0, rtol=0.0, atol=1e-12))
        )
    )
    ledger_cost_delta_bps = ledger_cost_bps - path_cost_bps
    issues: list[str] = []
    if abs(ledger_cost_delta_bps) > 1e-9:
        issues.append("trade_ledger_and_vectorized_path_costs_differ")
    if fractional_position_detected:
        issues.append("fractional_position_ledger_cost_is_fixed_per_trade")
    if abs(terminal_position) > 1e-12:
        issues.append("terminal_open_position_has_no_vectorized_exit_cost")
    return {
        "status": "accounting_mismatch" if issues else "accounting_consistent",
        "strategy_id": strategy.strategy_id,
        "bars": len(frame),
        "trades": len(trades),
        "round_trip_cost_bps": float(execution.round_trip_cost_bps),
        "slippage_bps_per_turnover_unit": float(execution.slippage_bps_per_turnover_unit),
        "path_turnover_units_evaluated": float(evaluated_turnover.sum()),
        "path_cost_bps": path_cost_bps,
        "ledger_cost_bps": ledger_cost_bps,
        "ledger_cost_delta_bps": ledger_cost_delta_bps,
        "terminal_position": terminal_position,
        "terminal_exit_cost_bps_if_liquidated": terminal_exit_cost_bps,
        "fractional_position_detected": fractional_position_detected,
        "issues": issues,
        "claims": {
            "diagnostic_only": True,
            "legacy_compatible_accounting_preserved": True,
            "canonical_economic_accounting_established": False,
        },
    }
