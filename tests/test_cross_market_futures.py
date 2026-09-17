from __future__ import annotations

import json
from pathlib import Path

import pytest

from orderflow_edge_lab.cross_market_futures import (
    FUTURES_SPECS,
    audit_native_futures_events,
    extra_round_trip_friction_bps,
    futures_spec,
)
from orderflow_edge_lab.data import MarketEvent


def test_frozen_protocol_invariants() -> None:
    cfg = json.loads(Path("config/cross_market_futures_v1.json").read_text())
    assert cfg["status"] == "FROZEN_BEFORE_NON_CRYPTO_RESULTS"
    assert [x["root"] for x in cfg["universe"]] == ["ES", "NQ", "GC", "CL"]
    transfer = cfg["signal_transfer"]
    assert transfer["absolute_aggressive_flow_ratio_threshold"] == 0.25
    assert transfer["absolute_book_imbalance_threshold"] == 0.25
    assert transfer["absolute_microprice_normalized_edge_threshold"] == 0.20
    assert transfer["minimum_trade_prints"] == 5
    assert transfer["same_family_same_direction_cooldown_seconds"] == 2
    assert transfer["forward_horizons_seconds"] == [1, 5, 15, 30]
    assert transfer["market_specific_threshold_tuning"] is False
    assert cfg["economics"]["additional_round_trip_friction_ticks"] == [0.0, 1.0, 2.0]
    assert cfg["economics"]["leverage"] == 1.0
    assert cfg["d0_transfer_survival"]["no_v1_direct_promotion"] is True
    assert cfg["claims"]["candidate_promoted"] is False
    assert cfg["claims"]["live_execution_supported"] is False
    assert cfg["claims"]["leverage_supported"] is False


def test_contract_specs_and_tick_values() -> None:
    assert set(FUTURES_SPECS) == {"ES", "NQ", "GC", "CL"}
    assert futures_spec("es").tick_value_usd == pytest.approx(12.5)
    assert futures_spec("NQ").tick_value_usd == pytest.approx(5.0)
    assert futures_spec("GC").tick_value_usd == pytest.approx(10.0)
    assert futures_spec("CL").tick_value_usd == pytest.approx(10.0)


def test_market_native_tick_stress_converts_to_bps() -> None:
    # At ES 5000, one 0.25-point total round-trip tick is 0.5 bps.
    assert extra_round_trip_friction_bps(root="ES", price=5000.0, total_ticks=1.0) == pytest.approx(0.5)
    assert extra_round_trip_friction_bps(root="ES", price=5000.0, total_ticks=2.0) == pytest.approx(1.0)


def test_native_event_audit_accepts_tick_aligned_single_contract() -> None:
    events = [
        MarketEvent(1_700_000_000_000_000_000, "ESZ26", "QUOTE", bid=5000.00, ask=5000.25),
        MarketEvent(1_700_000_000_100_000_000, "ESZ26", "TRADE", price=5000.25, size=2.0, bid=5000.00, ask=5000.25),
    ]
    report = audit_native_futures_events(events, root="ES")
    assert report["passed"] is True
    assert report["off_tick_prices"] == 0
    assert report["symbols"] == ["ESZ26"]


def test_native_event_audit_rejects_roll_mix_and_off_tick_price() -> None:
    events = [
        MarketEvent(1_700_000_000_000_000_000, "ESZ26", "TRADE", price=5000.25, size=1.0),
        MarketEvent(1_700_000_000_100_000_000, "ESH27", "TRADE", price=5000.10, size=1.0),
    ]
    report = audit_native_futures_events(events, root="ES")
    assert report["passed"] is False
    assert "multiple_native_contract_symbols" in report["failures"]
    assert "off_tick_prices" in report["failures"]
