from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_best_performer_leverage_diagnostic.py"
SPEC = importlib.util.spec_from_file_location("best_performer_leverage_diagnostic", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def sample_trades() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol":"A","fold":0,"exit_ts":"2026-01-01T01:00:00Z","entry_ts":"2026-01-01T00:00:00Z","net_bps":100.0,"mae_pct":-0.02,"side":1},
            {"symbol":"B","fold":0,"exit_ts":"2026-01-01T01:00:00Z","entry_ts":"2026-01-01T00:00:00Z","net_bps":-50.0,"mae_pct":-0.03,"side":-1},
            {"symbol":"A","fold":1,"exit_ts":"2026-01-02T01:00:00Z","entry_ts":"2026-01-02T00:00:00Z","net_bps":40.0,"mae_pct":-0.11,"side":1},
            {"symbol":"B","fold":1,"exit_ts":"2026-01-02T01:00:00Z","entry_ts":"2026-01-02T00:00:00Z","net_bps":20.0,"mae_pct":-0.01,"side":1},
        ]
    )


def test_linear_leverage_does_not_create_profit_factor_edge():
    trades = sample_trades()
    base_pf = MODULE.profit_factor(trades["net_bps"])
    out = MODULE.leverage_diagnostic(trades, 5.0, epochs=500, seed=7)
    assert out["profit_factor_invariant_under_linear_scaling"] == base_pf
    assert out["scaled_mean_trade_net_bps_on_equity"] == 5.0 * trades["net_bps"].mean()


def test_mae_wipeout_bound_is_detected_without_calling_it_exchange_liquidation():
    trades = sample_trades()
    out = MODULE.leverage_diagnostic(trades, 10.0, epochs=500, seed=11)
    assert out["mae_wipeout_bound_underlying_pct"] == -0.1
    assert out["mae_bound_breach_trades"] == 1
    assert out["mae_breach_bound_portfolio"]["surviving_symbol_sleeves"] == 1


def test_fold_bootstrap_is_deterministic_for_seed():
    trades = sample_trades()
    a = MODULE.bootstrap_terminal(trades, 2.0, epochs=1000, seed=42, enforce_mae_breach=False)
    b = MODULE.bootstrap_terminal(trades, 2.0, epochs=1000, seed=42, enforce_mae_breach=False)
    assert a == b
    assert a["dependence_clusters_per_epoch"] == 2
    assert a["symbol_sleeves"] == 2


def test_config_is_explicitly_post_selection_and_non_promotional():
    cfg = json.loads((ROOT / "config" / "best_performer_leverage_diagnostic_v1.json").read_text(encoding="utf-8"))
    assert cfg["status"] == "post_selection_diagnostic"
    assert cfg["selection"]["outcome_dependent"] is True
    assert cfg["selection"]["can_support_edge_claim"] is False
    assert cfg["claims"]["automatic_promotion"] is False
    assert cfg["claims"]["verified_oos"] is False
    assert cfg["claims"]["live_enabled"] is False
    assert cfg["bootstrap"]["epochs"] >= 100000
    assert cfg["economics"]["requested_primary_leverages"] == [2, 5, 10]
