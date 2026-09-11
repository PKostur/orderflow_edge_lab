from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .execution import StateCorruptionError


def _fail(lineno: int, detail: str) -> None:
    raise StateCorruptionError(f"invalid checkpoint transition at line {lineno}: {detail}")


def _same_number(left: object, right: object) -> bool:
    if type(left) not in (int, float) or type(right) not in (int, float):
        return False
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-9)


def _keys(value: object, *, lineno: int, field: str) -> set[str]:
    if not isinstance(value, dict):
        _fail(lineno, f"{field} is not an object")
    return set(value)


def audit_checkpoint_transitions(records: Sequence[Mapping[str, Any]]) -> int:
    """Validate state deltas between consecutive durable checkpoints.

    The journal hash chain protects byte integrity and the base semantic audit checks
    each checkpoint in isolation. This layer verifies that one committed state can
    legitimately follow the previous committed state for the recorded event. It is
    intentionally conservative and fail-closed for paper deployment readiness.
    """
    previous: Mapping[str, Any] | None = None
    checked = 0

    for lineno, row in enumerate(records, start=1):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        current = payload.get("state_after")
        if not isinstance(current, dict):
            continue
        event_type = row.get("event_type")
        if not isinstance(event_type, str):
            _fail(lineno, "missing event type")

        if previous is None:
            previous = current
            continue

        checked += 1
        prev_pending = _keys(previous.get("pending"), lineno=lineno, field="previous pending")
        curr_pending = _keys(current.get("pending"), lineno=lineno, field="current pending")
        prev_positions = _keys(previous.get("positions"), lineno=lineno, field="previous positions")
        curr_positions = _keys(current.get("positions"), lineno=lineno, field="current positions")
        prev_seen = previous.get("seen_intents")
        curr_seen = current.get("seen_intents")
        if not isinstance(prev_seen, list) or not isinstance(curr_seen, list):
            _fail(lineno, "seen_intents is not a list")

        if "engine_config" in previous and current.get("engine_config") != previous.get("engine_config"):
            _fail(lineno, "persisted engine configuration changed")

        intent_id = payload.get("intent_id")

        if event_type == "intent_submitted":
            if not isinstance(intent_id, str):
                _fail(lineno, "submission lacks intent_id")
            if curr_pending != prev_pending | {intent_id} or intent_id in prev_pending:
                _fail(lineno, "submission did not add exactly one pending intent")
            if curr_seen != [*prev_seen, intent_id]:
                _fail(lineno, "submission did not append exactly one seen intent")
        else:
            if curr_seen != prev_seen:
                _fail(lineno, "seen intents changed outside submission")

        if event_type in {"intent_rejected", "intent_expired"}:
            if not isinstance(intent_id, str) or curr_pending != prev_pending - {intent_id} or intent_id not in prev_pending:
                _fail(lineno, "single pending resolution delta is invalid")
        elif event_type == "pending_intents_expired":
            expired = payload.get("intent_ids")
            if not isinstance(expired, list) or not all(isinstance(x, str) for x in expired):
                _fail(lineno, "expired intent list is invalid")
            expired_set = set(expired)
            if len(expired_set) != len(expired) or not expired_set <= prev_pending:
                _fail(lineno, "expired intent list is duplicate or unknown")
            if curr_pending != prev_pending - expired_set:
                _fail(lineno, "batch expiry removed the wrong pending intents")
        elif event_type == "paper_position_opened":
            opened_id = payload.get("intent_id")
            if not isinstance(opened_id, str) or opened_id not in prev_pending:
                _fail(lineno, "opened position was not pending")
            if curr_pending != prev_pending - {opened_id}:
                _fail(lineno, "open did not remove exactly its pending intent")
        elif event_type == "kill_switch_engaged":
            cancelled = payload.get("cancelled_intents")
            if not isinstance(cancelled, list) or set(cancelled) != prev_pending or len(cancelled) != len(prev_pending):
                _fail(lineno, "kill switch cancellation set does not match pending state")
            if curr_pending:
                _fail(lineno, "kill switch did not clear all pending intents")
        elif event_type not in {"intent_submitted"}:
            if curr_pending != prev_pending:
                _fail(lineno, "pending intents changed for an unrelated event")

        if event_type == "paper_position_opened":
            opened_id = payload.get("intent_id")
            if not isinstance(opened_id, str) or opened_id in prev_positions:
                _fail(lineno, "position open identity is invalid")
            if curr_positions != prev_positions | {opened_id}:
                _fail(lineno, "open did not add exactly one position")
            if current["positions"].get(opened_id) != {k: v for k, v in payload.items() if k != "state_after"}:
                _fail(lineno, "opened position payload differs from committed position")
        elif event_type == "paper_position_closed":
            closed_id = payload.get("intent_id")
            if not isinstance(closed_id, str) or closed_id not in prev_positions:
                _fail(lineno, "position close identity is invalid")
            if curr_positions != prev_positions - {closed_id}:
                _fail(lineno, "close did not remove exactly one position")
        elif curr_positions != prev_positions:
            _fail(lineno, "positions changed for an unrelated event")

        if event_type == "paper_position_closed":
            net_pnl = payload.get("net_pnl")
            if type(net_pnl) not in (int, float) or not math.isfinite(float(net_pnl)):
                _fail(lineno, "close net_pnl is invalid")
            if not _same_number(current.get("equity"), float(previous["equity"]) + float(net_pnl)):
                _fail(lineno, "equity delta does not match close net_pnl")
            if not _same_number(
                current.get("realized_pnl_today"),
                float(previous["realized_pnl_today"]) + float(net_pnl),
            ):
                _fail(lineno, "realized PnL delta does not match close net_pnl")
        else:
            if not _same_number(current.get("equity"), previous.get("equity")):
                _fail(lineno, "equity changed outside a close")
            if event_type == "trading_day_rolled":
                if not _same_number(current.get("realized_pnl_today"), 0.0):
                    _fail(lineno, "day roll did not reset realized PnL")
            elif not _same_number(current.get("realized_pnl_today"), previous.get("realized_pnl_today")):
                _fail(lineno, "realized PnL changed outside close or day roll")

        if event_type == "paper_position_opened":
            if current.get("trades_today") != previous.get("trades_today", 0) + 1:
                _fail(lineno, "trade count did not increment on open")
        elif event_type == "trading_day_rolled":
            if current.get("trades_today") != 0:
                _fail(lineno, "day roll did not reset trade count")
        elif current.get("trades_today") != previous.get("trades_today"):
            _fail(lineno, "trade count changed for an unrelated event")

        if event_type == "trading_day_rolled":
            if current.get("trading_day") == previous.get("trading_day"):
                _fail(lineno, "day roll did not change trading day")
            if not _same_number(current.get("day_start_equity"), previous.get("equity")):
                _fail(lineno, "day-start equity does not match prior equity")
        else:
            if current.get("trading_day") != previous.get("trading_day"):
                _fail(lineno, "trading day changed outside day roll")
            if not _same_number(current.get("day_start_equity"), previous.get("day_start_equity")):
                _fail(lineno, "day-start equity changed outside day roll")

        if event_type == "kill_switch_engaged":
            if current.get("kill_switch") is not True:
                _fail(lineno, "kill switch was not engaged")
        elif event_type == "kill_switch_released":
            if current.get("kill_switch") is not False:
                _fail(lineno, "kill switch was not released")
        elif current.get("kill_switch") != previous.get("kill_switch"):
            _fail(lineno, "kill switch changed for an unrelated event")

        previous = current

    return checked
