from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry import (
    _cell_definitions,
    _summary,
    enrich_trade_geometry,
)


def _frame(periods: int = 260) -> pd.DataFrame:
    idx = pd.date_range("2025-12-01T00:00:00Z", periods=periods, freq="8h")
    t = np.arange(periods, dtype=float)
    returns = 0.0015 * np.sin(t / 6.0) + 0.0008 * np.cos(t / 15.0)
    open_ = 100.0 * np.cumprod(1.0 + returns)
    close = open_ * (1.0 + 0.001 * np.sin(t / 4.0))
    high = np.maximum(open_, close) * (1.0 + 0.006 + 0.002 * np.sin(t / 9.0) ** 2)
    low = np.minimum(open_, close) * (1.0 - 0.005 - 0.002 * np.cos(t / 11.0) ** 2)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=idx,
    )


def _config() -> dict:
    return json.loads(Path("config/payoff_geometry_v1.json").read_text(encoding="utf-8"))


def test_geometry_emits_capture_time_and_causal_volatility_state():
    frame = _frame()
    entry = frame.index[180]
    exit_ = frame.index[186]
    held = frame.loc[entry:frame.index[185]]
    entry_price = float(frame.loc[entry, "open"])
    mfe = max(0.0, float(held["high"].max()) / entry_price - 1.0) * 10_000.0
    mae = min(0.0, float(held["low"].min()) / entry_price - 1.0) * 10_000.0
    trade = {
        "entry": entry.isoformat(),
        "exit": exit_.isoformat(),
        "side": 1,
        "bars_held": 6,
        "gross_bps": 35.0,
        "net_bps": 15.0,
        "mfe_bps": mfe,
        "mae_bps": mae,
        "terminal_liquidation": False,
    }
    row = enrich_trade_geometry(
        trade,
        frame,
        strategy_id="DON8",
        symbol="BTC_USDT",
        cost_bps=20.0,
        btc_frame=frame,
        volatility_config=_config()["pre_entry_volatility_state"],
    )
    assert row["outcome_label"] == "CORRECT"
    assert row["side_label"] == "LONG"
    assert row["pre_entry_volatility_state"] in {"LOW", "MID", "HIGH", "UNKNOWN"}
    assert row["gross_to_mfe_ratio"] is not None
    assert row["time_to_mfe_hours"] is not None
    assert row["abs_mae_bps"] >= 0.0


def test_predeclared_cell_set_contains_outcome_side_volatility_and_empty_cells():
    cfg = _config()
    cells = _cell_definitions(cfg)
    names = [name for name, _ in cells]
    assert "OUTCOME=CORRECT" in names
    assert "OUTCOME=INCORRECT" in names
    assert "SIDE=LONG" in names
    assert "SIDE=SHORT" in names
    assert "PRE_ENTRY_VOLATILITY=LOW" in names
    assert "PRE_ENTRY_VOLATILITY=MID" in names
    assert "PRE_ENTRY_VOLATILITY=HIGH" in names
    assert "PRE_ENTRY_VOLATILITY=UNKNOWN" in names
    assert cfg["cell_grid"]["emit_empty_cells"] is True
    one_row = {
        "outcome_label": "CORRECT",
        "side_label": "LONG",
        "pre_entry_volatility_state": "LOW",
        "session_regime": "ASIA",
        "btc_prior_bar_direction": "ALIGNED",
        "own_prior_3bar_direction": "ALIGNED",
    }
    empty = [name for name, predicate in cells if not predicate(one_row)]
    assert len(empty) > 0


def test_summary_reports_requested_distribution_quantiles_and_capture_median():
    rows = [
        {
            "symbol": "BTC_USDT",
            "entry": f"2026-01-0{i+1}T00:00:00+00:00",
            "net_bps": float(i * 10 - 10),
            "gross_bps": float(i * 12 - 8),
            "mfe_bps": float(30 + i * 10),
            "abs_mae_bps": float(15 + i * 4),
            "gross_to_mfe_ratio": float((i * 12 - 8) / (30 + i * 10)),
            "winner_gross_to_mfe_ratio": (
                float((i * 12 - 8) / (30 + i * 10)) if i >= 1 else None
            ),
            "time_to_mfe_hours": float(i * 8),
            "time_to_mae_hours": float((3 - i) * 8),
            "duration_hours": 32.0,
            "mfe_to_abs_mae_ratio": float((30 + i * 10) / (15 + i * 4)),
            "correct_direction": i >= 1,
        }
        for i in range(4)
    ]
    summary = _summary(rows, [0.10, 0.25, 0.50, 0.75, 0.90])
    assert summary["median_gross_to_mfe_ratio"] is not None
    for field in ("mfe_bps", "abs_mae_bps", "gross_to_mfe_ratio", "time_to_mfe_hours"):
        assert set(summary["distributions"][field]) == {"p10", "p25", "p50", "p75", "p90"}


def test_multiple_testing_is_reserved_for_later_decision_affecting_claims():
    cfg = _config()
    policy = cfg["multiplicity_policy"]
    assert policy["diagnostics_are_non_gating"] is True
    assert policy["cell_selection_after_results_prohibited"] is True
    reserved = " ".join(policy["decision_affecting_claims_require_later_correction"])
    assert "Reality Check" in reserved
    assert "SPA" in reserved
    assert "Deflated Sharpe" in reserved
    assert "Backtest Overfitting" in reserved
    amendment = cfg["preregistration_amendment"]
    assert amendment["recorded_before_first_diagnostic_run"] is True
    assert amendment["results_observed_before_amendment"] is False
