"""Deterministic, finite, offline-only paper-bot replay v3.

This module is a computational simulation only.  It has no network, broker,
exchange, wallet, credential, account, import-payload, scheduling, or live
mode capability.  A signal creates a *pending simulated target* that is first
eligible on the next valid quote; it never changes a position on its own quote.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any

POLICY_SCHEMA = "orderflow_edge_lab.paper_bot_policy.v3"
CHECKPOINT_SCHEMA = "orderflow_edge_lab.paper_bot_checkpoint.v3"
ARTIFACT_SCHEMA = "orderflow_edge_lab.paper_bot_artifact.v3"
SIMULATED_MODE = "SIMULATED_OFFLINE_ONLY"
GENESIS = "GENESIS"

_LIMITATIONS = (
    "SIMULATED-ONLY: this finite offline replay has no financial external side effect.",
    "Only one caller-declared synthetic linear instrument is supported; quantities are fractional model units.",
    "Funding, borrow charges, interest, liquidation, margin rules, taxes, partial fills, queue position, market impact, and venue outages are not modeled.",
    "Bid/ask and declared slippage/fees are modeled assumptions, not executable prices or a record of any transaction.",
)
_REQUIRED_FRAME_FIELDS = frozenset({"ts_ns", "received_ns", "symbol", "bid", "ask", "close", "source_id", "batch_id"})
_POLICY_FIELDS = frozenset(
    {
        "schema",
        "signal_id",
        "instrument",
        "initial_cash",
        "fee_rate",
        "slippage_bps",
        "max_quote_age_ns",
        "max_position_fraction",
        "max_gross_exposure_fraction",
        "max_loss_fraction",
        "max_drawdown_fraction",
    }
)
_INSTRUMENT_FIELDS = frozenset({"symbol", "contract_multiplier", "instrument_type", "funding_treatment"})
_EVENT_FIELDS = frozenset(
    {
        "sequence",
        "frame_id",
        "event_type",
        "reason",
        "execution",
        "signal",
        "state_sha256",
        "prior_event_sha256",
        "event_sha256",
    }
)
_CHECKPOINT_FIELDS = frozenset(
    {
        "schema",
        "run_id",
        "signal_id",
        "policy_sha256",
        "input_prefix_frame_ids",
        "input_prefix_sha256",
        "next_index",
        "event_chain",
        "event_chain_head",
        "state",
        "state_sha256",
        "status",
        "checkpoint_sha256",
    }
)


class PaperBotV3Error(ValueError):
    """Raised when an offline v3 replay input, checkpoint, or artifact is unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PaperBotV3Error("value is not canonical JSON") from exc


def _canonical_copy(value: Any) -> Any:
    return json.loads(_canonical_bytes(value).decode("utf-8"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_json(value: Any) -> Any:
    """Represent malformed Python input deterministically so a halt can be recorded."""

    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            return {"__nonfinite_float__": "NaN"}
        return {"__nonfinite_float__": "Infinity" if value > 0 else "-Infinity"}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            return {"__unsupported_mapping_keys__": type(value).__name__}
        return {key: _safe_json(item) for key, item in value.items()}
    return {"__unsupported_type__": type(value).__name__}


def _frame_id(frame: Any) -> str:
    return _sha256(_safe_json(frame))


def _finite_number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PaperBotV3Error(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise PaperBotV3Error(f"{field} must be finite" + (" and positive" if positive else ""))
    return result


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise PaperBotV3Error(f"{field} must be a positive integer")
    return value


def _normalise_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(policy, Mapping) or set(policy) != _POLICY_FIELDS:
        raise PaperBotV3Error("policy has unsupported shape")
    if policy.get("schema") != POLICY_SCHEMA:
        raise PaperBotV3Error("policy schema is invalid")
    signal_id = policy.get("signal_id")
    if not isinstance(signal_id, str) or not signal_id.strip():
        raise PaperBotV3Error("policy.signal_id must be a nonempty stable caller identifier")
    instrument = policy.get("instrument")
    if not isinstance(instrument, Mapping) or set(instrument) != _INSTRUMENT_FIELDS:
        raise PaperBotV3Error("policy.instrument has unsupported shape")
    symbol = instrument.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise PaperBotV3Error("policy.instrument.symbol must be nonempty")
    if instrument.get("instrument_type") != "synthetic_linear":
        raise PaperBotV3Error("only instrument_type synthetic_linear is supported")
    if instrument.get("funding_treatment") != "not_modeled":
        raise PaperBotV3Error("funding_treatment must explicitly be not_modeled")
    initial_cash = _finite_number(policy.get("initial_cash"), "policy.initial_cash", positive=True)
    fee_rate = _finite_number(policy.get("fee_rate"), "policy.fee_rate", positive=True)
    slippage_bps = _finite_number(policy.get("slippage_bps"), "policy.slippage_bps", positive=True)
    if fee_rate >= 1.0 or slippage_bps >= 10_000.0:
        raise PaperBotV3Error("policy fee_rate/slippage_bps are outside conservative bounds")
    max_position = _finite_number(policy.get("max_position_fraction"), "policy.max_position_fraction", positive=True)
    max_gross = _finite_number(
        policy.get("max_gross_exposure_fraction"), "policy.max_gross_exposure_fraction", positive=True
    )
    max_loss = _finite_number(policy.get("max_loss_fraction"), "policy.max_loss_fraction", positive=True)
    max_drawdown = _finite_number(policy.get("max_drawdown_fraction"), "policy.max_drawdown_fraction", positive=True)
    if max_position > 1.0 or max_gross > 1.0 or max_loss >= 1.0 or max_drawdown >= 1.0:
        raise PaperBotV3Error("policy exposure/loss fractions must be in their documented conservative ranges")
    return {
        "schema": POLICY_SCHEMA,
        "signal_id": signal_id,
        "instrument": {
            "symbol": symbol,
            "contract_multiplier": _finite_number(
                instrument.get("contract_multiplier"), "policy.instrument.contract_multiplier", positive=True
            ),
            "instrument_type": "synthetic_linear",
            "funding_treatment": "not_modeled",
        },
        "initial_cash": initial_cash,
        "fee_rate": fee_rate,
        "slippage_bps": slippage_bps,
        "max_quote_age_ns": _positive_int(policy.get("max_quote_age_ns"), "policy.max_quote_age_ns"),
        "max_position_fraction": max_position,
        "max_gross_exposure_fraction": max_gross,
        "max_loss_fraction": max_loss,
        "max_drawdown_fraction": max_drawdown,
    }


def _normalise_frame(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not _REQUIRED_FRAME_FIELDS.issubset(raw) or not all(isinstance(key, str) for key in raw):
        raise PaperBotV3Error("frame is not a standardized quote mapping")
    frame = _canonical_copy(dict(raw))
    for field in ("ts_ns", "received_ns"):
        if type(frame[field]) is not int or frame[field] <= 0:
            raise PaperBotV3Error(f"frame.{field} must be a positive integer nanosecond timestamp")
    for field in ("symbol", "source_id", "batch_id"):
        if not isinstance(frame[field], str) or not frame[field].strip():
            raise PaperBotV3Error(f"frame.{field} must be a nonempty string")
    bid = _finite_number(frame["bid"], "frame.bid", positive=True)
    ask = _finite_number(frame["ask"], "frame.ask", positive=True)
    _finite_number(frame["close"], "frame.close", positive=True)
    if bid > ask:
        raise PaperBotV3Error("frame bid exceeds ask")
    return frame


def _initial_state(policy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cash": float(policy["initial_cash"]),
        "quantity": 0.0,
        "last_mid": None,
        "peak_equity": float(policy["initial_cash"]),
        "halted": False,
        "halt_reason": None,
        "pending": None,
        "history": [],
        "seen_frame_ids": [],
        "last_ts_ns": None,
        "last_received_ns": None,
        "fees_paid": 0.0,
        "traded_notional": 0.0,
        "fill_count": 0,
    }


def _validate_state(state: Any) -> dict[str, Any]:
    expected = {
        "cash", "quantity", "last_mid", "peak_equity", "halted", "halt_reason", "pending", "history", "seen_frame_ids",
        "last_ts_ns", "last_received_ns", "fees_paid", "traded_notional", "fill_count",
    }
    if not isinstance(state, Mapping) or set(state) != expected:
        raise PaperBotV3Error("checkpoint state has unsupported shape")
    result = _canonical_copy(dict(state))
    for field in ("cash", "quantity", "peak_equity", "fees_paid", "traded_notional"):
        _finite_number(result[field], f"checkpoint.state.{field}")
    if result["last_mid"] is not None:
        _finite_number(result["last_mid"], "checkpoint.state.last_mid", positive=True)
    if type(result["halted"]) is not bool or (result["halt_reason"] is not None and not isinstance(result["halt_reason"], str)):
        raise PaperBotV3Error("checkpoint halt state is invalid")
    if result["halted"] != (result["halt_reason"] is not None):
        raise PaperBotV3Error("checkpoint halt state is inconsistent")
    if result["pending"] is not None:
        pending = result["pending"]
        if not isinstance(pending, Mapping) or set(pending) != {"signal_event_id", "target_fraction", "effective_target_fraction"}:
            raise PaperBotV3Error("checkpoint pending target has unsupported shape")
        if not isinstance(pending["signal_event_id"], str):
            raise PaperBotV3Error("checkpoint pending target identity is invalid")
        for field in ("target_fraction", "effective_target_fraction"):
            value = _finite_number(pending[field], f"checkpoint.pending.{field}")
            if not -1.0 <= value <= 1.0:
                raise PaperBotV3Error("checkpoint pending target is outside [-1, 1]")
    if not isinstance(result["history"], list) or not isinstance(result["seen_frame_ids"], list):
        raise PaperBotV3Error("checkpoint history has invalid shape")
    if len(set(result["seen_frame_ids"])) != len(result["seen_frame_ids"]) or not all(
        isinstance(value, str) and len(value) == 64 for value in result["seen_frame_ids"]
    ):
        raise PaperBotV3Error("checkpoint seen frame identities are invalid")
    for field in ("last_ts_ns", "last_received_ns"):
        if result[field] is not None and (type(result[field]) is not int or result[field] <= 0):
            raise PaperBotV3Error(f"checkpoint.state.{field} is invalid")
    if type(result["fill_count"]) is not int or result["fill_count"] < 0:
        raise PaperBotV3Error("checkpoint fill_count is invalid")
    return result


def _equity(state: Mapping[str, Any], mid: float, multiplier: float) -> float:
    return float(state["cash"]) + float(state["quantity"]) * mid * multiplier


def _risk_reason(state: Mapping[str, Any], policy: Mapping[str, Any], mid: float) -> str | None:
    multiplier = float(policy["instrument"]["contract_multiplier"])
    equity = _equity(state, mid, multiplier)
    peak = max(float(state["peak_equity"]), equity)
    state["peak_equity"] = peak
    if equity <= 0.0:
        return "equity_nonpositive"
    initial = float(policy["initial_cash"])
    if (initial - equity) / initial >= float(policy["max_loss_fraction"]):
        return "max_loss_budget_breached"
    if (peak - equity) / peak >= float(policy["max_drawdown_fraction"]):
        return "max_drawdown_budget_breached"
    gross = abs(float(state["quantity"])) * mid * multiplier
    if gross > equity * float(policy["max_gross_exposure_fraction"]) + 1e-8:
        return "gross_exposure_limit_breached"
    return None


def _project_trade(
    state: Mapping[str, Any], policy: Mapping[str, Any], mid: float, bid: float, ask: float, new_quantity: float
) -> tuple[float, float, float, float, float]:
    """Return cash, equity, fee, execution price, and traded notional for a proposed quantity."""

    old_quantity = float(state["quantity"])
    delta = new_quantity - old_quantity
    multiplier = float(policy["instrument"]["contract_multiplier"])
    if abs(delta) <= 1e-14:
        equity = _equity(state, mid, multiplier)
        return float(state["cash"]), equity, 0.0, mid, 0.0
    slip = float(policy["slippage_bps"]) / 10_000.0
    execution_price = ask * (1.0 + slip) if delta > 0.0 else bid * (1.0 - slip)
    if execution_price <= 0.0 or not math.isfinite(execution_price):
        raise PaperBotV3Error("declared slippage makes simulated execution price invalid")
    traded_notional = abs(delta) * execution_price * multiplier
    fee = traded_notional * float(policy["fee_rate"])
    cash = float(state["cash"]) - delta * execution_price * multiplier - fee
    equity = cash + new_quantity * mid * multiplier
    return cash, equity, fee, execution_price, traded_notional


def _is_safe_quantity(
    state: Mapping[str, Any], policy: Mapping[str, Any], mid: float, bid: float, ask: float, quantity: float
) -> bool:
    cash, equity, _, _, _ = _project_trade(state, policy, mid, bid, ask, quantity)
    if cash < -1e-9 or equity <= 0.0:
        return False
    gross = abs(quantity) * mid * float(policy["instrument"]["contract_multiplier"])
    return gross <= equity * float(policy["max_gross_exposure_fraction"]) + 1e-9


def _execute_pending(
    state: dict[str, Any], policy: Mapping[str, Any], frame: Mapping[str, Any], frame_id: str
) -> dict[str, Any]:
    """Apply only a prior event's target using this quote's conservative bid/ask."""

    pending = state["pending"]
    if not isinstance(pending, Mapping):
        raise PaperBotV3Error("internal pending target is invalid")
    mid = (float(frame["bid"]) + float(frame["ask"])) / 2.0
    bid, ask = float(frame["bid"]), float(frame["ask"])
    multiplier = float(policy["instrument"]["contract_multiplier"])
    equity_before = _equity(state, mid, multiplier)
    effective_target = float(pending["effective_target_fraction"])
    desired_quantity = effective_target * equity_before / (mid * multiplier)
    old_quantity = float(state["quantity"])
    chosen_quantity = desired_quantity
    capped_by_limits = False
    if not _is_safe_quantity(state, policy, mid, bid, ask, chosen_quantity):
        # Existing exposure was already checked before this point.  A bisection
        # between it and the requested target therefore finds the largest safe
        # model quantity without borrowing cash or exceeding gross exposure.
        low, high = 0.0, 1.0
        for _ in range(70):
            trial_fraction = (low + high) / 2.0
            trial = old_quantity + (desired_quantity - old_quantity) * trial_fraction
            if _is_safe_quantity(state, policy, mid, bid, ask, trial):
                low = trial_fraction
            else:
                high = trial_fraction
        chosen_quantity = old_quantity + (desired_quantity - old_quantity) * low
        capped_by_limits = True
    cash, equity_after, fee, execution_price, traded_notional = _project_trade(
        state, policy, mid, bid, ask, chosen_quantity
    )
    delta = chosen_quantity - old_quantity
    executed = abs(delta) > 1e-12
    state["cash"] = cash
    state["quantity"] = chosen_quantity
    state["fees_paid"] = float(state["fees_paid"]) + fee
    state["traded_notional"] = float(state["traded_notional"]) + traded_notional
    if executed:
        state["fill_count"] = int(state["fill_count"]) + 1
    state["pending"] = None
    return {
        "kind": "SIMULATED_NEXT_EVENT_BID_ASK",
        "executed": executed,
        "signal_event_id": pending["signal_event_id"],
        "fill_event_id": frame_id,
        "target_fraction": pending["target_fraction"],
        "effective_target_fraction": effective_target,
        "old_quantity": old_quantity,
        "new_quantity": chosen_quantity,
        "delta_quantity": delta,
        "reference_bid": bid,
        "reference_ask": ask,
        "fill_price": execution_price,
        "fee_rate": float(policy["fee_rate"]),
        "slippage_bps": float(policy["slippage_bps"]),
        "fee": fee,
        "traded_notional": traded_notional,
        "cash_after": cash,
        "equity_after": equity_after,
        "capped_by_cash_or_exposure": capped_by_limits,
    }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _signal_target(signal_fn: Callable[[tuple[Mapping[str, Any], ...]], Any], state: dict[str, Any]) -> tuple[float | None, str | None]:
    history = tuple(_freeze(deepcopy(frame)) for frame in state["history"])
    try:
        value = signal_fn(history)
    except Exception as exc:  # Signal exceptions are fail-closed and never retried.
        return None, f"signal_fn_error:{type(exc).__name__}"
    try:
        target = _finite_number(value, "signal_fn result")
    except PaperBotV3Error:
        return None, "invalid_signal_target"
    if not -1.0 <= target <= 1.0:
        return None, "invalid_signal_target"
    return target, None


def _event(
    events: list[dict[str, Any]], frame_id: str, event_type: str, reason: str | None, execution: Mapping[str, Any] | None,
    signal: Mapping[str, Any] | None, state: Mapping[str, Any],
) -> dict[str, Any]:
    prior = GENESIS if not events else events[-1]["event_sha256"]
    unsigned = {
        "sequence": len(events) + 1,
        "frame_id": frame_id,
        "event_type": event_type,
        "reason": reason,
        "execution": _canonical_copy(execution) if execution is not None else None,
        "signal": _canonical_copy(signal) if signal is not None else None,
        "state_sha256": _sha256(state),
        "prior_event_sha256": prior,
    }
    result = {**unsigned, "event_sha256": _sha256(unsigned)}
    events.append(result)
    return result


def _validate_event_chain(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        raise PaperBotV3Error("checkpoint event_chain must be an array")
    result = _canonical_copy(events)
    prior = GENESIS
    for index, event in enumerate(result, start=1):
        if not isinstance(event, Mapping) or set(event) != _EVENT_FIELDS or event.get("sequence") != index:
            raise PaperBotV3Error("checkpoint event chain has unsupported shape")
        if event.get("prior_event_sha256") != prior or not isinstance(event.get("frame_id"), str):
            raise PaperBotV3Error("checkpoint event chain linkage is invalid")
        unsigned = {key: event[key] for key in event if key != "event_sha256"}
        if event.get("event_sha256") != _sha256(unsigned):
            raise PaperBotV3Error("checkpoint event hash mismatch")
        prior = event["event_sha256"]
    return result


def _checkpoint(
    *, run_id: str, policy: Mapping[str, Any], state: Mapping[str, Any], events: list[dict[str, Any]],
    frame_ids: list[str], next_index: int, status: str,
) -> dict[str, Any]:
    chain_head = GENESIS if not events else events[-1]["event_sha256"]
    unsigned = {
        "schema": CHECKPOINT_SCHEMA,
        "run_id": run_id,
        "signal_id": policy["signal_id"],
        "policy_sha256": _sha256(policy),
        "input_prefix_frame_ids": frame_ids[:next_index],
        "input_prefix_sha256": _sha256(frame_ids[:next_index]),
        "next_index": next_index,
        "event_chain": _canonical_copy(events),
        "event_chain_head": chain_head,
        "state": _canonical_copy(state),
        "state_sha256": _sha256(state),
        "status": status,
    }
    return {**unsigned, "checkpoint_sha256": _sha256(unsigned)}


def _validate_checkpoint(
    checkpoint: Mapping[str, Any], *, policy: Mapping[str, Any], run_id: str, frames: list[Any], frame_ids: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    if not isinstance(checkpoint, Mapping) or set(checkpoint) != _CHECKPOINT_FIELDS:
        raise PaperBotV3Error("checkpoint has unsupported shape")
    candidate = _canonical_copy(dict(checkpoint))
    if candidate.get("schema") != CHECKPOINT_SCHEMA or candidate.get("run_id") != run_id:
        raise PaperBotV3Error("checkpoint schema or run identity mismatch")
    if candidate.get("signal_id") != policy["signal_id"] or candidate.get("policy_sha256") != _sha256(policy):
        raise PaperBotV3Error("checkpoint policy or signal identity mismatch")
    next_index = candidate.get("next_index")
    if type(next_index) is not int or not 0 <= next_index <= len(frames):
        raise PaperBotV3Error("checkpoint next_index is invalid")
    expected_ids = frame_ids[:next_index]
    if candidate.get("input_prefix_frame_ids") != expected_ids or candidate.get("input_prefix_sha256") != _sha256(expected_ids):
        raise PaperBotV3Error("checkpoint recording prefix mismatch")
    events = _validate_event_chain(candidate["event_chain"])
    if len(events) != next_index or any(event["frame_id"] != expected_ids[index] for index, event in enumerate(events)):
        raise PaperBotV3Error("checkpoint event identities do not match recording prefix")
    chain_head = GENESIS if not events else events[-1]["event_sha256"]
    if candidate.get("event_chain_head") != chain_head:
        raise PaperBotV3Error("checkpoint chain head mismatch")
    state = _validate_state(candidate["state"])
    if candidate.get("state_sha256") != _sha256(state):
        raise PaperBotV3Error("checkpoint state hash mismatch")
    unsigned = {key: candidate[key] for key in candidate if key != "checkpoint_sha256"}
    if candidate.get("checkpoint_sha256") != _sha256(unsigned):
        raise PaperBotV3Error("checkpoint hash mismatch")
    if candidate.get("status") not in {"PARTIAL", "COMPLETE", "HALTED"}:
        raise PaperBotV3Error("checkpoint status is invalid")
    return state, events, next_index


def _halt(state: dict[str, Any], reason: str) -> None:
    state["halted"] = True
    state["halt_reason"] = reason


def _quote_problem(state: Mapping[str, Any], policy: Mapping[str, Any], frame: Mapping[str, Any], frame_id: str) -> str | None:
    if frame_id in state["seen_frame_ids"]:
        return "duplicate_quote"
    if frame["symbol"] != policy["instrument"]["symbol"]:
        return "instrument_mismatch"
    if int(frame["ts_ns"]) > int(frame["received_ns"]):
        return "future_quote"
    if int(frame["received_ns"]) - int(frame["ts_ns"]) > int(policy["max_quote_age_ns"]):
        return "stale_quote"
    last_ts, last_received = state["last_ts_ns"], state["last_received_ns"]
    if (last_ts is not None and int(frame["ts_ns"]) <= int(last_ts)) or (
        last_received is not None and int(frame["received_ns"]) < int(last_received)
    ):
        return "out_of_order_quote"
    return None


def _summary(state: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    multiplier = float(policy["instrument"]["contract_multiplier"])
    mark = state["last_mid"]
    equity = float(policy["initial_cash"]) if mark is None else _equity(state, float(mark), multiplier)
    gross = 0.0 if mark is None else abs(float(state["quantity"])) * float(mark) * multiplier
    return {
        "cash": float(state["cash"]),
        "quantity": float(state["quantity"]),
        "last_mid": mark,
        "equity": equity,
        "gross_exposure": gross,
        "gross_exposure_fraction": 0.0 if equity <= 0.0 else gross / equity,
        "fees_paid": float(state["fees_paid"]),
        "traded_notional": float(state["traded_notional"]),
        "fill_count": int(state["fill_count"]),
        "peak_equity": float(state["peak_equity"]),
        "loss_fraction": max(0.0, (float(policy["initial_cash"]) - equity) / float(policy["initial_cash"])),
        "drawdown_fraction": 0.0
        if float(state["peak_equity"]) <= 0.0
        else max(0.0, (float(state["peak_equity"]) - equity) / float(state["peak_equity"])),
        "pending_target": _canonical_copy(state["pending"]) if state["pending"] is not None else None,
        "halt_reason": state["halt_reason"],
    }


def run_paper_bot_v3(
    frames: Iterable[Mapping[str, Any]],
    signal_fn: Callable[[tuple[Mapping[str, Any], ...]], Any],
    policy: Mapping[str, Any],
    *,
    checkpoint: Mapping[str, Any] | None = None,
    run_id: str = "paper-bot-v3",
    mode: str = "offline",
    max_events: int | None = None,
    synthetic_demo: bool = False,
) -> dict[str, Any]:
    """Run a deterministic finite replay with no external capability.

    ``signal_fn`` receives an immutable tuple of accepted normalized frames ending
    at the current quote (never a later quote), and returns one signed target
    fraction in ``[-1, 1]``.  That target is recorded as pending and can only be
    modeled against the next valid quote.  Passing a returned checkpoint together
    with the same full recording resumes byte-equivalently when ``signal_fn`` is
    deterministic and has the same caller-declared ``policy.signal_id``.
    """

    if mode != "offline":
        raise PaperBotV3Error("live, network, and persistent modes are rejected; only mode='offline' is supported")
    if not isinstance(run_id, str) or not run_id.strip():
        raise PaperBotV3Error("run_id must be a nonempty local identifier")
    if max_events is not None and (type(max_events) is not int or max_events < 0):
        raise PaperBotV3Error("max_events must be a nonnegative integer or None")
    if type(synthetic_demo) is not bool:
        raise PaperBotV3Error("synthetic_demo must be boolean")
    normalized_policy = _normalise_policy(policy)
    if not callable(signal_fn):
        raise PaperBotV3Error("signal_fn must be callable")
    raw_frames = list(frames)
    safe_frames = [_safe_json(frame) for frame in raw_frames]
    frame_ids = [_frame_id(frame) for frame in raw_frames]
    if checkpoint is None:
        state, events, start_index = _initial_state(normalized_policy), [], 0
    else:
        state, events, start_index = _validate_checkpoint(
            checkpoint, policy=normalized_policy, run_id=run_id, frames=safe_frames, frame_ids=frame_ids
        )
    if state["halted"]:
        stop_index = start_index
    else:
        available = len(raw_frames) - start_index
        count = available if max_events is None else min(available, max_events)
        stop_index = start_index + count
        for index in range(start_index, stop_index):
            raw, frame_id = raw_frames[index], frame_ids[index]
            try:
                frame = _normalise_frame(raw)
            except PaperBotV3Error:
                _halt(state, "malformed_quote")
                _event(events, frame_id, "quote_rejected_halt", "malformed_quote", None, None, state)
                stop_index = index + 1
                break
            problem = _quote_problem(state, normalized_policy, frame, frame_id)
            if problem is not None:
                _halt(state, problem)
                _event(events, frame_id, "quote_rejected_halt", problem, None, None, state)
                stop_index = index + 1
                break
            state["history"].append(frame)
            state["seen_frame_ids"].append(frame_id)
            state["last_ts_ns"] = int(frame["ts_ns"])
            state["last_received_ns"] = int(frame["received_ns"])
            mid = (float(frame["bid"]) + float(frame["ask"])) / 2.0
            state["last_mid"] = mid
            reason = _risk_reason(state, normalized_policy, mid)
            execution: dict[str, Any] | None = None
            signal: dict[str, Any] | None = None
            event_type = "quote_accepted"
            if reason is not None:
                _halt(state, reason)
                event_type = "risk_budget_halt"
            else:
                if state["pending"] is not None:
                    execution = _execute_pending(state, normalized_policy, frame, frame_id)
                    reason = _risk_reason(state, normalized_policy, mid)
                    if reason is not None:
                        _halt(state, reason)
                        event_type = "risk_budget_halt"
                if not state["halted"]:
                    target, signal_problem = _signal_target(signal_fn, state)
                    if signal_problem is not None:
                        reason = signal_problem
                        _halt(state, reason)
                        event_type = "signal_halt"
                    else:
                        assert target is not None
                        cap = min(
                            float(normalized_policy["max_position_fraction"]),
                            float(normalized_policy["max_gross_exposure_fraction"]),
                        )
                        effective = max(-cap, min(cap, target))
                        state["pending"] = {
                            "signal_event_id": frame_id,
                            "target_fraction": target,
                            "effective_target_fraction": effective,
                        }
                        signal = {
                            "signal_event_id": frame_id,
                            "target_fraction": target,
                            "effective_target_fraction": effective,
                            "capped_by_exposure_policy": effective != target,
                        }
            _event(events, frame_id, event_type, reason, execution, signal, state)
    if state["halted"]:
        status = "HALTED"
    elif stop_index < len(raw_frames):
        status = "PARTIAL"
    else:
        status = "COMPLETE"
    generated_checkpoint = _checkpoint(
        run_id=run_id,
        policy=normalized_policy,
        state=state,
        events=events,
        frame_ids=frame_ids,
        next_index=stop_index,
        status=status,
    )
    unsigned = {
        "schema": ARTIFACT_SCHEMA,
        "mode": SIMULATED_MODE,
        "run_id": run_id,
        "signal_id": normalized_policy["signal_id"],
        "synthetic_demo": synthetic_demo,
        "status": status,
        "policy": normalized_policy,
        "policy_sha256": _sha256(normalized_policy),
        "input_frames": safe_frames,
        "input_frames_sha256": _sha256(safe_frames),
        "event_chain": _canonical_copy(events),
        "event_chain_head": GENESIS if not events else events[-1]["event_sha256"],
        "checkpoint": generated_checkpoint,
        "summary": _summary(state, normalized_policy),
        "limitations": list(_LIMITATIONS),
    }
    return {**unsigned, "artifact_sha256": _sha256(unsigned)}


def validate_paper_bot_artifact_v3(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Validate immutable local replay identities without contacting any provider."""

    expected = {
        "schema", "mode", "run_id", "signal_id", "synthetic_demo", "status", "policy", "policy_sha256", "input_frames",
        "input_frames_sha256", "event_chain", "event_chain_head", "checkpoint", "summary", "limitations", "artifact_sha256",
    }
    if not isinstance(artifact, Mapping) or set(artifact) != expected:
        raise PaperBotV3Error("artifact has unsupported shape")
    candidate = _canonical_copy(dict(artifact))
    if candidate.get("schema") != ARTIFACT_SCHEMA or candidate.get("mode") != SIMULATED_MODE:
        raise PaperBotV3Error("artifact is not a simulated v3 artifact")
    if type(candidate.get("synthetic_demo")) is not bool or candidate.get("status") not in {"PARTIAL", "COMPLETE", "HALTED"}:
        raise PaperBotV3Error("artifact status is invalid")
    policy = _normalise_policy(candidate["policy"])
    if candidate.get("policy_sha256") != _sha256(policy) or candidate.get("signal_id") != policy["signal_id"]:
        raise PaperBotV3Error("artifact policy identity mismatch")
    if not isinstance(candidate.get("input_frames"), list) or candidate.get("input_frames_sha256") != _sha256(candidate["input_frames"]):
        raise PaperBotV3Error("artifact input recording identity mismatch")
    frame_ids = [_frame_id(frame) for frame in candidate["input_frames"]]
    state, events, next_index = _validate_checkpoint(
        candidate["checkpoint"], policy=policy, run_id=candidate["run_id"], frames=candidate["input_frames"], frame_ids=frame_ids
    )
    if candidate["checkpoint"]["status"] != candidate["status"] or candidate["event_chain"] != events:
        raise PaperBotV3Error("artifact/checkpoint replay state mismatch")
    chain_head = GENESIS if not events else events[-1]["event_sha256"]
    if candidate.get("event_chain_head") != chain_head or next_index != len(events):
        raise PaperBotV3Error("artifact event chain head mismatch")
    if candidate["status"] == "COMPLETE" and next_index != len(candidate["input_frames"]):
        raise PaperBotV3Error("complete artifact has an incomplete checkpoint")
    if candidate["status"] == "HALTED" and not state["halted"]:
        raise PaperBotV3Error("halted artifact has an unlatched state")
    if candidate["status"] != "HALTED" and state["halted"]:
        raise PaperBotV3Error("unhalted artifact has a latched state")
    unsigned = {key: candidate[key] for key in candidate if key != "artifact_sha256"}
    if candidate.get("artifact_sha256") != _sha256(unsigned):
        raise PaperBotV3Error("artifact hash mismatch")
    return candidate


def _sync_parent(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_paper_bot_artifact_v3(path: str | Path, artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically publish one verified local artifact without overwriting an existing path."""

    normalized = validate_paper_bot_artifact_v3(artifact)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(normalized) + b"\n"
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{normalized['artifact_sha256'][:12]}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # link() is an atomic create-if-absent operation on this local POSIX filesystem.
        os.link(temporary, target)
        _sync_parent(target)
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {"path": str(target), "size_bytes": len(payload), "artifact_sha256": normalized["artifact_sha256"]}


def verify_paper_bot_artifact_file_v3(path: str | Path) -> dict[str, Any]:
    """Read-only local verification for an immutable simulated artifact."""

    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        artifact = validate_paper_bot_artifact_v3(data)
    except (OSError, json.JSONDecodeError, PaperBotV3Error, ValueError) as exc:
        return {"schema": "orderflow_edge_lab.paper_bot_verification.v3", "status": "INVALID", "path": str(target), "error": f"{type(exc).__name__}: {exc}"}
    return {
        "schema": "orderflow_edge_lab.paper_bot_verification.v3",
        "status": "VERIFIED_SIMULATED_LOCAL_REPLAY",
        "path": str(target),
        "artifact_sha256": artifact["artifact_sha256"],
        "replay_status": artifact["status"],
        "verification_scope": "local_frozen_bytes_hash_chain_checkpoint_and_offline_replay_identity_only",
    }
