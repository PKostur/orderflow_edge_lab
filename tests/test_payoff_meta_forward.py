from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_meta_forward import build_forward_snapshot


SYMBOLS = [
    "BTC_USDT",
    "ETH_USDT",
    "SOL_USDT",
    "XRP_USDT",
    "DOGE_USDT",
    "BNB_USDT",
    "ADA_USDT",
    "LINK_USDT",
    "SUI_USDT",
    "ENA_USDT",
]


def _fixtures(days: int = 320):
    idx = pd.date_range("2026-01-01", periods=days, freq="1D", tz="UTC")
    fidx = pd.date_range("2025-12-15", periods=(days + 25) * 3, freq="8h", tz="UTC")
    t = np.arange(days, dtype=float)
    daily = {}
    funding = {}
    for j, symbol in enumerate(SYMBOLS):
        factor = 0.005 * np.sin(t / 6.5) + 0.0025 * np.cos(t / 15.0)
        idio = 0.0075 * np.sin(t / (2.2 + 0.1 * j) + j * 0.8) + 0.003 * np.cos(t / (5.0 + 0.25 * j) + j)
        regime = np.where((t.astype(int) // 30) % 2 == 0, 1.0, -0.55)
        ret = factor * (0.75 + 0.035 * j) + idio * regime + (j - 4.5) * 0.00007
        close = (85.0 + 6.0 * j) * np.cumprod(1.0 + ret)
        open_ = close * (1.0 + 0.0018 * np.sin(t / 3.2 + 0.35 * j))
        daily[symbol] = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.01,
                "low": np.minimum(open_, close) * 0.99,
                "close": close,
            },
            index=idx,
        )
        k = np.arange(len(fidx), dtype=float)
        funding[symbol] = pd.DataFrame(
            {"funding_rate": 1.8e-5 * np.sin(k / (10.0 + j)) + (j - 4.5) * 1.2e-6},
            index=fidx,
        )
    return daily, funding


def test_shadow_contract_is_exact_failed_rule_and_research_only():
    cfg = json.loads(Path("config/dv2_payoff_meta_trend_accel_shadow_v1.json").read_text())
    assert cfg["prospective_start_utc"] == "2026-09-17T00:00:00Z"
    assert cfg["provenance"]["source_rule_status"] == "FALSIFIED_D0_NEAR_SURVIVOR"
    assert cfg["provenance"]["source_rule_promoted"] is False
    assert cfg["provenance"]["not_D4_candidate_validation"] is True
    assert cfg["payoff_model"]["ridge_alpha"] == 10.0
    assert cfg["payoff_model"]["training_window_prior_primary_setups"] == 80
    assert cfg["payoff_model"]["minimum_prior_primary_setups"] == 60
    assert cfg["payoff_model"]["trade_if_predicted_standalone_net_bps_greater_than"] == 0.0
    assert cfg["execution"]["leverage"] == 1.0
    assert cfg["claims"]["candidate_promoted"] is False
    assert cfg["claims"]["D4_validation"] is False


def test_pre_start_snapshot_has_zero_forward_evidence():
    d, f = _fixtures()
    report, tables = build_forward_snapshot(
        d,
        symbols=SYMBOLS,
        funding_frames=f,
        prospective_start_utc="2026-09-17T00:00:00Z",
        as_of_utc="2026-09-16T23:59:59Z",
    )
    assert report["status"] == "PRE_START"
    assert report["completed_forward_setups"] == 0
    assert report["accepted_completed_setups"] == 0
    assert tables == {}
    assert report["claims"]["candidate_promoted"] is False


def test_post_start_ledger_contains_no_pre_start_entries():
    d, f = _fixtures()
    report, tables = build_forward_snapshot(
        d,
        symbols=SYMBOLS,
        funding_frames=f,
        prospective_start_utc="2026-09-17T00:00:00Z",
        as_of_utc="2026-10-25T12:00:00Z",
    )
    assert report["status"] == "FORWARD_RESEARCH_SHADOW"
    ledger = tables["completed_setup_ledger"]
    if len(ledger):
        starts = pd.to_datetime(ledger["start_timestamp"], utc=True)
        assert (starts >= pd.Timestamp("2026-09-17T00:00:00Z")).all()
    assert report["claims"]["candidate_promoted"] is False
    assert report["claims"]["D4_validation"] is False


def test_forward_snapshot_never_uses_leverage_or_prestart_pnl():
    d, f = _fixtures()
    report, tables = build_forward_snapshot(
        d,
        symbols=SYMBOLS,
        funding_frames=f,
        prospective_start_utc="2026-09-17T00:00:00Z",
        as_of_utc="2026-10-25T12:00:00Z",
        side_cost_bps=10.0,
        ridge_alpha=10.0,
        training_window=80,
        minimum_training=60,
        threshold_bps=0.0,
    )
    obs = tables.get("candidate_observations")
    if obs is not None and len(obs):
        assert (pd.to_numeric(obs["active_gross"], errors="coerce") <= 1.0 + 1e-12).all()
        assert (pd.to_datetime(obs.index, utc=True) >= pd.Timestamp("2026-09-17T00:00:00Z")).all()
    assert report["claims"]["leverage_supported"] is False
