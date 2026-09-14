from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_strategy_discovery_v2_1_2.py"
SPEC = importlib.util.spec_from_file_location("strategy_discovery_v2_1_2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PATCHED = MODULE.namespace


def _frame(periods: int = 240) -> pd.DataFrame:
    index = pd.date_range("2026-03-01", periods=periods, freq="15min", tz="UTC")
    base = np.linspace(100.0, 104.0, periods)
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 0.2,
            "low": base - 0.2,
            "close": base + 0.05,
            "volume": np.linspace(1000.0, 1300.0, periods),
        },
        index=index,
    )


def test_adapter_declares_v2_1_2_protocol() -> None:
    assert PATCHED["run"].__globals__["__name__"] == "strategy_discovery_v2_1_2_patched"
    assert callable(PATCHED["main"])
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'strategy-discovery-v2.1.2-low-turnover' in source


def test_exit_fold_values_keep_signal_index() -> None:
    frame = _frame()
    start = frame.index[0]
    hold = 8
    exits = PATCHED["exit_timestamp"](frame.index, hold)
    exit_folds = pd.Series(np.nan, index=frame.index, dtype=float)
    mask = exits.notna()
    delta = (pd.DatetimeIndex(exits.loc[mask]) - start) / pd.Timedelta(days=1)
    exit_folds.loc[mask] = np.floor(delta).astype(int)
    assert exit_folds.index.equals(frame.index)
    assert exit_folds.loc[frame.index[80]] == 0
    assert exit_folds.loc[frame.index[90]] == 1


def test_cross_fold_signal_is_excluded_with_aligned_exit_fold() -> None:
    frame = _frame()
    start = frame.index[0]
    hold = 8
    score = pd.Series(1.0, index=frame.index)
    eligible = pd.Series(True, index=frame.index)
    fr = PATCHED["forward_return"](frame, hold)
    exits = PATCHED["exit_timestamp"](frame.index, hold)
    folds = PATCHED["fold_labels"](frame.index, start, 1)
    exit_folds = pd.Series(np.nan, index=frame.index, dtype=float)
    mask = exits.notna()
    delta = (pd.DatetimeIndex(exits.loc[mask]) - start) / pd.Timedelta(days=1)
    exit_folds.loc[mask] = np.floor(delta).astype(int)
    data = pd.DataFrame(
        {
            "score": score,
            "eligible": eligible,
            "fwd": fr,
            "fold": folds,
            "exit_fold": exit_folds,
            "exit_ts": exits,
        },
        index=frame.index,
    )
    data = data[
        data["eligible"]
        & data["fwd"].notna()
        & data["exit_ts"].notna()
        & (data["exit_fold"] == data["fold"])
    ]
    assert frame.index[80] in data.index
    assert frame.index[90] not in data.index


def test_amendment_preserves_base_research_semantics() -> None:
    amendment = json.loads(
        (ROOT / "config" / "strategy_discovery_v2_1_2_amendment.json").read_text(encoding="utf-8")
    )
    assert amendment["outcomes_inspected_before_amendment"] is False
    assert amendment["base_config"] == "config/strategy_discovery_v2_1.json"
    assert amendment["changes_only"] == [
        "compute exit dependence-cluster labels from exit timestamp values while preserving the originating signal-row index"
    ]


def test_v2_1_base_has_finite_pf_and_actual_exit_cooldown() -> None:
    source = (ROOT / "scripts" / "run_strategy_discovery_v2_1.py").read_text(encoding="utf-8")
    assert "PF_ALL_WIN_SENTINEL" in source
    assert 'next_allowed = pd.Timestamp(row["exit_ts"])' in source
    assert "exit_timestamp(f.index, hold)" in source
