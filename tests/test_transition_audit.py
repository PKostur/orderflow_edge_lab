from __future__ import annotations

from copy import deepcopy

import pytest

from orderflow_edge_lab.execution import StateCorruptionError
from orderflow_edge_lab.transition_audit import audit_checkpoint_transitions


def _state() -> dict:
    return {
        "engine_config": {"policy": {"x": 1}, "instruments": {"NQ": {"x": 1}}},
        "equity": 10_000.0,
        "day_start_equity": 10_000.0,
        "realized_pnl_today": 0.0,
        "trading_day": "2026-09-11",
        "trades_today": 0,
        "kill_switch": False,
        "pending": {},
        "positions": {},
        "seen_intents": [],
    }


def _row(event_type: str, payload: dict, state: dict) -> dict:
    return {"event_type": event_type, "payload": {**payload, "state_after": state}}


def test_valid_submit_open_close_sequence_passes_transition_audit():
    initial = _state()

    submitted = deepcopy(initial)
    submitted["pending"]["abc"] = {"intent": {"symbol": "NQ"}}
    submitted["seen_intents"].append("abc")

    opened = deepcopy(submitted)
    opened["pending"].pop("abc")
    position = {
        "intent_id": "abc",
        "strategy_id": "s1",
        "symbol": "NQ",
        "side": "LONG",
        "contracts": 1,
        "entry_fill": 100.0,
        "stop": 99.0,
        "target": 102.0,
        "opened_at": "2026-09-11T20:00:01+00:00",
    }
    opened["positions"]["abc"] = position
    opened["trades_today"] = 1

    closed = deepcopy(opened)
    closed["positions"].pop("abc")
    closed["equity"] = 10_050.0
    closed["realized_pnl_today"] = 50.0

    records = [
        _row("engine_initialized", {}, initial),
        _row("intent_submitted", {"intent_id": "abc"}, submitted),
        _row("paper_position_opened", position, opened),
        _row("paper_position_closed", {**position, "net_pnl": 50.0}, closed),
    ]

    assert audit_checkpoint_transitions(records) == 3


def test_rejects_equity_change_outside_close_event():
    initial = _state()
    corrupt = deepcopy(initial)
    corrupt["equity"] = 11_000.0

    with pytest.raises(StateCorruptionError, match="equity changed outside a close"):
        audit_checkpoint_transitions([
            _row("engine_initialized", {}, initial),
            _row("approval_token_rejected", {"intent_id": "abc"}, corrupt),
        ])


def test_rejects_kill_switch_that_does_not_account_for_all_pending_intents():
    initial = _state()
    initial["pending"] = {"a": {}, "b": {}}
    initial["seen_intents"] = ["a", "b"]
    killed = deepcopy(initial)
    killed["kill_switch"] = True
    killed["pending"] = {}

    with pytest.raises(StateCorruptionError, match="cancellation set"):
        audit_checkpoint_transitions([
            _row("engine_initialized", {}, initial),
            _row("kill_switch_engaged", {"cancelled_intents": ["a"]}, killed),
        ])


def test_rejects_close_when_equity_delta_disagrees_with_reported_pnl():
    initial = _state()
    initial["positions"] = {"abc": {"intent_id": "abc"}}
    initial["seen_intents"] = ["abc"]
    closed = deepcopy(initial)
    closed["positions"] = {}
    closed["equity"] = 10_025.0
    closed["realized_pnl_today"] = 25.0

    with pytest.raises(StateCorruptionError, match="equity delta"):
        audit_checkpoint_transitions([
            _row("engine_initialized", {}, initial),
            _row("paper_position_closed", {"intent_id": "abc", "net_pnl": 50.0}, closed),
        ])
