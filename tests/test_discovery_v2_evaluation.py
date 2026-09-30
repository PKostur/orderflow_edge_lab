from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.discovery_v2_evaluation import (
    build_evidence_vector,
    concentration_diagnostics,
    cost_surface,
    cscv_pbo,
    deflated_sharpe_probability,
    moving_block_bootstrap_mean,
    white_style_reality_check,
)


def _methodology() -> dict:
    return json.loads(Path("config/discovery_v2_evaluation_v1.json").read_text(encoding="utf-8"))


def test_block_bootstrap_detects_large_stable_positive_mean() -> None:
    rng = np.random.default_rng(1)
    values = 8.0 + rng.normal(0.0, 2.0, 300)
    result = moving_block_bootstrap_mean(values, block_length=5, resamples=1000, confidence=0.95)
    assert result.mean > 7.0
    assert result.lower > 0.0


def test_cost_surface_reports_break_even_and_stress() -> None:
    result = cost_surface([30.0, 20.0, 10.0], [10.0, 10.0, 10.0], [1.0, 1.5, 2.0])
    assert result["break_even_round_trip_cost_bps"] == 20.0
    assert result["break_even_to_base_cost_ratio"] == 2.0
    assert result["cases"]["1.0"]["mean_net_bps"] == 10.0
    assert result["cases"]["2.0"]["mean_net_bps"] == 0.0


def test_concentration_exposes_single_symbol_dependence() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=20, freq="D", tz="UTC"),
            "symbol": ["A"] * 10 + ["B"] * 10,
            "net_return_bps": [20.0] * 10 + [-1.0] * 10,
            "side": ["LONG"] * 20,
        }
    )
    result = concentration_diagnostics(frame)
    assert result["best_symbol_positive_pnl_share"] == 1.0
    assert result["minimum_leave_one_symbol_out_mean_bps"] < 0.0


def test_pbo_is_bounded_and_has_splits() -> None:
    rng = np.random.default_rng(3)
    data = pd.DataFrame({
        "v0": rng.normal(0.10, 1.0, 160),
        "v1": rng.normal(0.05, 1.0, 160),
        "v2": rng.normal(0.00, 1.0, 160),
        "v3": rng.normal(-0.05, 1.0, 160),
    })
    result = cscv_pbo(data, partitions=8)
    assert 0.0 <= result["pbo"] <= 1.0
    assert result["splits"] == 70


def test_deflated_sharpe_probability_is_bounded() -> None:
    rng = np.random.default_rng(5)
    returns = rng.normal(0.2, 1.0, 250)
    result = deflated_sharpe_probability(returns, [0.05, 0.08, 0.10, 0.12, 0.15])
    assert 0.0 <= result["probability"] <= 1.0
    assert result["expected_max_sharpe"] >= 0.05


def test_reality_check_penalizes_large_strategy_family_under_null() -> None:
    rng = np.random.default_rng(7)
    family = pd.DataFrame(rng.normal(0.0, 1.0, size=(200, 20)))
    result = white_style_reality_check(family, block_length=5, resamples=800)
    assert 0.0 <= result["bootstrap_p_value"] <= 1.0


def test_evidence_vector_never_emits_single_composite_score_or_auto_promotes() -> None:
    rng = np.random.default_rng(11)
    n = 120
    obs = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC"),
            "symbol": np.resize(np.array(["A", "B", "C", "D"]), n),
            "side": np.resize(np.array(["LONG", "SHORT"]), n),
            "gross_return_bps": 25.0 + rng.normal(0.0, 8.0, n),
            "cost_bps": np.full(n, 8.0),
        }
    )
    trials = pd.DataFrame({f"v{i}": rng.normal(0.1 + i * 0.01, 1.0, n) for i in range(6)})
    vector = build_evidence_vector(
        obs,
        trial_returns=trials,
        methodology=_methodology(),
        independence_level="D0",
        validity_flags={"chronology": True, "no_leakage": True, "manifest_bound": True},
    )
    assert vector["promotion"]["single_composite_score"] is None
    assert vector["promotion"]["eligible"] is False
    assert vector["independence"]["pass_for_live_review"] is False
    assert vector["claims"]["live_order_transmission_supported"] is False
