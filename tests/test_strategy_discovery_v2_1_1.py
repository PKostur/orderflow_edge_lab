from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_strategy_discovery_v2_1_1.py"
SPEC = importlib.util.spec_from_file_location("strategy_discovery_v2_1_1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _frame(periods: int = 220) -> pd.DataFrame:
    index = pd.date_range("2026-03-01", periods=periods, freq="15min", tz="UTC")
    base = np.linspace(100.0, 104.0, periods)
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 0.2,
            "low": base - 0.2,
            "close": base + 0.05,
            "volume": np.linspace(1000.0, 1200.0, periods),
        },
        index=index,
    )


def test_causal_exit_timestamp_is_entry_plus_frozen_hold() -> None:
    frame = _frame()
    exits = MODULE.causal_exit_timestamp(frame, 4)
    assert exits.iloc[10] == frame.index[15]


def test_cross_fold_exits_are_excluded_from_state_observations() -> None:
    frame = _frame()
    score = pd.Series(np.linspace(-1.0, 1.0, len(frame)), index=frame.index)
    eligible = pd.Series(True, index=frame.index)
    data = MODULE.causal_observation_frame(
        frame,
        score,
        eligible,
        hold_bars=8,
        global_start=frame.index[0],
        fold_days=1,
    )
    assert not data.empty
    assert (data["fold"] == data["exit_fold"]).all()
    # 96 15-minute bars per day. Signal bar 90 exits at 99 and must not leak into the next fold.
    assert frame.index[90] not in data.index
    assert frame.index[80] in data.index


def test_all_win_profit_factor_is_finite() -> None:
    value = MODULE.profit_factor([1.0, 2.0, 3.0], 1_000_000.0)
    assert value == 1_000_000.0
    assert np.isfinite(value)


def test_non_overlap_uses_actual_exit_timestamp() -> None:
    source = inspect.getsource(MODULE.run)
    assert 'next_allowed = pd.Timestamp(row["exit_ts"])' in source
    assert "pos + hold" not in source


def test_v2_1_1_preserves_research_grid_and_economics() -> None:
    old = json.loads((ROOT / "config" / "strategy_discovery_v2_1.json").read_text(encoding="utf-8"))
    new = json.loads((ROOT / "config" / "strategy_discovery_v2_1_1.json").read_text(encoding="utf-8"))
    for key in ["data", "economics", "state_screen", "families", "screening_gate", "risk_path", "institutional_label_boundary"]:
        assert new[key] == old[key]
    for key in ["calendar_fold_days", "minimum_folds", "minimum_symbols", "minimum_total_trades", "minimum_positive_fold_fraction", "minimum_positive_symbol_fraction", "trial_unit", "calendar_time_fold_is_dependence_cluster", "all_trials_retained", "no_best_cell_auto_promotion"]:
        assert new["dependence_and_trials"][key] == old["dependence_and_trials"][key]
