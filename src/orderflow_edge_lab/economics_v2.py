"""Opt-in v2 economic-accounting qualification and execution validation.

This module is intentionally additive.  It neither rewrites legacy/frozen reports
nor starts collectors, schedules, services, or live trading.  Its public results
bind caller-declared source identities and policies, keep missing observations
distinct from observed zero, and retain the foundation's non-authority claims.

``python -m orderflow_edge_lab.economics_v2 --help`` exposes offline JSON
operations.  The package dispatcher/console-script registration is deliberately
left to the integration owner.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    OPEN_CLOSED,
    ContractValidationError,
    build_canonical_source_set,
    build_coverage_result,
    build_manifest_result,
    build_utc_interval,
    canonical_json_bytes,
    canonical_json_sha256,
    interval_contains,
    missing_value,
    non_authority_claims,
    validate_canonical_source_set,
    validate_coverage_result,
    validate_observation_value,
    validate_utc_interval,
)


EXECUTION_POLICY_SCHEMA = "orderflow_edge_lab.execution_policy.v2"
EXECUTION_ENVELOPE_SCHEMA = "orderflow_edge_lab.execution_envelope.v2"
EXECUTION_ENVELOPE_RESULT_SCHEMA = "orderflow_edge_lab.execution_envelope_result.v2"
PRICE_DATASET_SCHEMA = "orderflow_edge_lab.price_dataset.v2"
FUNDING_DATASET_SCHEMA = "orderflow_edge_lab.funding_dataset.v2"
ECONOMICS_QUALIFICATION_SCHEMA = "orderflow_edge_lab.economics_qualification.v2"
SETTLEMENT_COVERAGE_SCHEMA = "orderflow_edge_lab.settlement_coverage.v2"
LEGACY_FUNDING_COVERAGE_READER_SCHEMA = "orderflow_edge_lab.legacy_funding_coverage_reader.v2"
ECONOMIC_CALIBRATION_FIXTURE_SCHEMA = "orderflow_edge_lab.economic_calibration_fixture.v2"
ECONOMIC_CALIBRATION_SCHEMA = "orderflow_edge_lab.economic_calibration.v2"
UNIVERSE_AVAILABILITY_SCHEMA = "orderflow_edge_lab.universe_availability.v2"

_SHA_CHARS = frozenset("0123456789abcdef")
_AVAILABILITY = frozenset({"ELIGIBLE", "INELIGIBLE", "UNAVAILABLE"})
_AVAILABILITY_REASONS = frozenset(
    {"delisted", "fetch_error", "insufficient_warmup", "missing_funding", "invalid_prices"}
)


class EconomicsV2Error(ValueError):
    """Raised when a v2 economics input is malformed or cannot qualify."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise EconomicsV2Error(f"{field} must be an object with string keys")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    present = set(value)
    if present != expected:
        missing = ",".join(sorted(expected - present))
        extra = ",".join(sorted(present - expected))
        detail = "; ".join(part for part in (f"missing={missing}" if missing else "", f"extra={extra}" if extra else "") if part)
        raise EconomicsV2Error(f"{field} has unsupported shape ({detail})")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EconomicsV2Error(f"{field} must be a nonempty string")
    return value.strip()


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in _SHA_CHARS for ch in value.lower()):
        raise EconomicsV2Error(f"{field} must be a 64-character hexadecimal SHA-256")
    return value.lower()


def _number(value: object, field: str, *, nonnegative: bool = False, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EconomicsV2Error(f"{field} must be a finite numeric value")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise EconomicsV2Error(f"{field} must be finite")
    if nonnegative and parsed < 0.0:
        raise EconomicsV2Error(f"{field} must be non-negative")
    if positive and parsed <= 0.0:
        raise EconomicsV2Error(f"{field} must be positive")
    return parsed


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise EconomicsV2Error(f"{field} must be a non-negative integer")
    return value


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise EconomicsV2Error(f"{field} must be a positive integer")
    return value


def _json_copy(value: object, field: str) -> Any:
    try:
        return json.loads(canonical_json_bytes(value).decode("utf-8"))
    except ContractValidationError as exc:
        raise EconomicsV2Error(f"{field} must be ordinary finite JSON") from exc


def _contract(callable_: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return callable_(*args, **kwargs)
    except ContractValidationError as exc:
        raise EconomicsV2Error(str(exc)) from exc


def _self_hash(unsigned: Mapping[str, Any], hash_field: str) -> dict[str, Any]:
    return {**unsigned, hash_field: canonical_json_sha256(unsigned)}


def _verify_hash(raw: Mapping[str, Any], unsigned: Mapping[str, Any], hash_field: str, field: str) -> dict[str, Any]:
    if _sha256(raw.get(hash_field), f"{field}.{hash_field}") != canonical_json_sha256(unsigned):
        raise EconomicsV2Error(f"{field}.{hash_field} does not match canonical object")
    return _self_hash(unsigned, hash_field)


def _utc_ns(value: object, field: str) -> int:
    return _nonnegative_int(value, field)


def _normalize_execution_mapping(execution: Mapping[str, Any] | object) -> Mapping[str, Any]:
    if isinstance(execution, Mapping):
        return execution
    try:
        return {
            "round_trip_cost_bps": getattr(execution, "round_trip_cost_bps"),
            "slippage_bps_per_turnover_unit": getattr(execution, "slippage_bps_per_turnover_unit"),
            "max_abs_position": getattr(execution, "max_abs_position"),
        }
    except AttributeError as exc:
        raise EconomicsV2Error("execution must be a mapping or an ExecutionModel-like object") from exc


def validate_execution_inputs_v2(execution: Mapping[str, Any] | object) -> dict[str, Any]:
    """Normalize finite non-negative costs and a finite positive position limit.

    This is the single validation surface used by the opt-in accounting wrapper;
    it fails rather than clamps and never changes legacy runner behavior.
    """

    raw = _mapping(_normalize_execution_mapping(execution), "execution")
    _exact_keys(
        raw,
        {"round_trip_cost_bps", "slippage_bps_per_turnover_unit", "max_abs_position"},
        "execution",
    )
    return {
        "round_trip_cost_bps": _number(raw["round_trip_cost_bps"], "execution.round_trip_cost_bps", nonnegative=True),
        "slippage_bps_per_turnover_unit": _number(
            raw["slippage_bps_per_turnover_unit"], "execution.slippage_bps_per_turnover_unit", nonnegative=True
        ),
        "max_abs_position": _number(raw["max_abs_position"], "execution.max_abs_position", positive=True),
    }


def build_execution_policy_v2(execution: Mapping[str, Any] | object, *, policy_sha256: str) -> dict[str, Any]:
    """Build hash-bound normalized execution inputs for a successor caller."""

    unsigned = {
        "schema": EXECUTION_POLICY_SCHEMA,
        "analysis": "validated_execution_inputs_v2",
        "execution": validate_execution_inputs_v2(execution),
        "units": {
            "round_trip_cost_bps": "basis_points_per_round_trip",
            "slippage_bps_per_turnover_unit": "basis_points_per_turnover_unit",
            "max_abs_position": "absolute_position_units",
        },
        "validation": "finite_nonnegative_costs_and_positive_size_v2",
        "policy_sha256": _sha256(policy_sha256, "policy_sha256"),
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "execution_policy_sha256")


def run_validated_accounting_v2(
    frame: Any,
    strategy: Any,
    params: Mapping[str, Any],
    execution: Mapping[str, Any] | object,
    *,
    accounting_mode: str,
    source_set: Mapping[str, Any],
    policy_sha256: str,
    context: Mapping[str, Any] | None = None,
    funding: Any = None,
) -> dict[str, Any]:
    """Run an existing accounting engine only after v2 execution validation.

    ``legacy_compatible`` preserves legacy valid numerical results exactly; the
    wrapper adds a separately named successor envelope.  ``canonical_v2``,
    ``canonical_v3`` and ``audit`` are also routed through the same validator.
    No result is a venue/funding-qualified economic claim until
    :func:`build_economics_qualification_v2` succeeds separately.
    """

    normalized = validate_execution_inputs_v2(execution)
    normalized_sources = _contract(validate_canonical_source_set, source_set)
    policy = build_execution_policy_v2(normalized, policy_sha256=policy_sha256)
    from orderflow_edge_lab.universal_backtest import ExecutionModel, run_backtest, run_canonical_backtest

    model = ExecutionModel(**normalized)
    if accounting_mode == "legacy_compatible":
        result = run_backtest(frame, strategy, params, model, context=context)
    elif accounting_mode == "canonical_v2":
        result = run_canonical_backtest(frame, strategy, params, model, context=context)
    elif accounting_mode == "canonical_v3":
        from orderflow_edge_lab.canonical_v3 import run_canonical_backtest_v3

        result = run_canonical_backtest_v3(frame, strategy, params, model, context=context, funding=funding)
    elif accounting_mode == "audit":
        from orderflow_edge_lab.universal_accounting_audit import audit_accounting

        if context is not None or funding is not None:
            raise EconomicsV2Error("audit mode does not accept context or funding")
        result = audit_accounting(frame, strategy, params, model)
    else:
        raise EconomicsV2Error("accounting_mode must be legacy_compatible, canonical_v2, canonical_v3, or audit")
    unsigned = {
        "schema": "orderflow_edge_lab.validated_accounting_result.v2",
        "analysis": "validated_accounting_wrapper_v2",
        "accounting_mode": accounting_mode,
        "source_set": normalized_sources,
        "execution_policy": policy,
        "engine_result": _json_copy(result, "engine_result"),
        "economics_qualification": "NOT_EVALUATED",
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "result_sha256")


def run_validated_sweep_v2(
    frames: Mapping[str, Any],
    strategy: Any,
    parameter_grid: Mapping[str, Sequence[Any]],
    cost_cases_bps: Sequence[float],
    *,
    slippage_bps_per_turnover_unit: float,
    source_set: Mapping[str, Any],
    policy_sha256: str,
) -> dict[str, Any]:
    """Run the frozen-compatible sweep only after validating every cost cell.

    ``run_sweep`` has no position-size parameter, so this successor wrapper
    validates each public cost/slippage cell and records the normalized policy
    family.  Valid legacy sweep output is returned unchanged under a new v2
    envelope; invalid cost cells fail before any result can be reported.
    """

    if not isinstance(cost_cases_bps, Sequence) or isinstance(cost_cases_bps, (str, bytes)):
        raise EconomicsV2Error("cost_cases_bps must be a numeric sequence")
    normalized_cases = [
        validate_execution_inputs_v2(
            {
                "round_trip_cost_bps": cost,
                "slippage_bps_per_turnover_unit": slippage_bps_per_turnover_unit,
                "max_abs_position": 1.0,
            }
        )
        for cost in cost_cases_bps
    ]
    normalized_sources = _contract(validate_canonical_source_set, source_set)
    from orderflow_edge_lab.universal_backtest import run_sweep

    result = run_sweep(
        frames,
        strategy,
        parameter_grid,
        [cell["round_trip_cost_bps"] for cell in normalized_cases],
        slippage_bps_per_turnover_unit=normalized_cases[0]["slippage_bps_per_turnover_unit"] if normalized_cases else _number(
            slippage_bps_per_turnover_unit, "slippage_bps_per_turnover_unit", nonnegative=True
        ),
    )
    unsigned = {
        "schema": "orderflow_edge_lab.validated_sweep_result.v2",
        "analysis": "validated_execution_sweep_wrapper_v2",
        "source_set": normalized_sources,
        "execution_policies": [
            build_execution_policy_v2(cell, policy_sha256=policy_sha256) for cell in normalized_cases
        ],
        "engine_result": _json_copy(result, "engine_result"),
        "economics_qualification": "NOT_EVALUATED",
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "result_sha256")


def _validate_impact(value: object) -> dict[str, Any]:
    raw = _mapping(value, "envelope.impact")
    mode = raw.get("mode")
    if mode == "UNAVAILABLE":
        _exact_keys(raw, {"mode"}, "envelope.impact")
        return {"mode": "UNAVAILABLE"}
    if mode == "DISPLAYED_DEPTH_LINEAR":
        _exact_keys(raw, {"mode", "depth_field", "impact_bps_per_depth_fraction"}, "envelope.impact")
        return {
            "mode": "DISPLAYED_DEPTH_LINEAR",
            "depth_field": _string(raw["depth_field"], "envelope.impact.depth_field"),
            "impact_bps_per_depth_fraction": _number(
                raw["impact_bps_per_depth_fraction"],
                "envelope.impact.impact_bps_per_depth_fraction",
                nonnegative=True,
            ),
        }
    raise EconomicsV2Error("envelope.impact.mode must be UNAVAILABLE or DISPLAYED_DEPTH_LINEAR")


def validate_execution_envelope_v2(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an explicit latency/freshness/impact execution scenario.

    The caller must name and hash the scenario.  No impact is synthesized when
    depth is absent: ``UNAVAILABLE`` is a valid capability declaration, while a
    depth-linear scenario requires usable depth on every selected fill.
    """

    raw = _mapping(envelope, "envelope")
    _exact_keys(
        raw,
        {
            "schema",
            "scenario_id",
            "decision_to_order_latency_ns",
            "maximum_entry_delay_ns",
            "entry_quote_max_age_ns",
            "exit_quote_max_age_ns",
            "maximum_exit_delay_ns",
            "round_trip_fee_bps",
            "additional_slippage_bps",
            "order_size",
            "impact",
            "diagnostic_only",
            "policy_sha256",
        },
        "envelope",
    )
    if raw["schema"] != EXECUTION_ENVELOPE_SCHEMA:
        raise EconomicsV2Error("envelope.schema is unsupported")
    diagnostic = raw["diagnostic_only"]
    if type(diagnostic) is not bool:
        raise EconomicsV2Error("envelope.diagnostic_only must be boolean")
    normalized = {
        "schema": EXECUTION_ENVELOPE_SCHEMA,
        "scenario_id": _string(raw["scenario_id"], "envelope.scenario_id"),
        "decision_to_order_latency_ns": _utc_ns(raw["decision_to_order_latency_ns"], "envelope.decision_to_order_latency_ns"),
        "maximum_entry_delay_ns": _utc_ns(raw["maximum_entry_delay_ns"], "envelope.maximum_entry_delay_ns"),
        "entry_quote_max_age_ns": _utc_ns(raw["entry_quote_max_age_ns"], "envelope.entry_quote_max_age_ns"),
        "exit_quote_max_age_ns": _utc_ns(raw["exit_quote_max_age_ns"], "envelope.exit_quote_max_age_ns"),
        "maximum_exit_delay_ns": _utc_ns(raw["maximum_exit_delay_ns"], "envelope.maximum_exit_delay_ns"),
        "round_trip_fee_bps": _number(raw["round_trip_fee_bps"], "envelope.round_trip_fee_bps", nonnegative=True),
        "additional_slippage_bps": _number(
            raw["additional_slippage_bps"], "envelope.additional_slippage_bps", nonnegative=True
        ),
        "order_size": _number(raw["order_size"], "envelope.order_size", positive=True),
        "impact": _validate_impact(raw["impact"]),
        "diagnostic_only": diagnostic,
        "policy_sha256": _sha256(raw["policy_sha256"], "envelope.policy_sha256"),
    }
    if normalized["scenario_id"] == "zero_latency_displayed_bbo":
        zero_fields = (
            "decision_to_order_latency_ns",
            "maximum_entry_delay_ns",
            "entry_quote_max_age_ns",
            "exit_quote_max_age_ns",
            "maximum_exit_delay_ns",
            "round_trip_fee_bps",
            "additional_slippage_bps",
        )
        if not diagnostic or any(normalized[field] != 0 for field in zero_fields) or normalized["impact"]["mode"] != "UNAVAILABLE":
            raise EconomicsV2Error("zero_latency_displayed_bbo is permitted only as an explicit zero-cost diagnostic")
    return normalized


def _validate_signal(signal: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(signal, "signal")
    _exact_keys(raw, {"signal_id", "signal_at_ns", "side", "exit_maturity_ns"}, "signal")
    side = raw["side"]
    if type(side) is not int or side not in {-1, 1}:
        raise EconomicsV2Error("signal.side must be -1 or 1")
    return {
        "signal_id": _string(raw["signal_id"], "signal.signal_id"),
        "signal_at_ns": _utc_ns(raw["signal_at_ns"], "signal.signal_at_ns"),
        "side": side,
        "exit_maturity_ns": _positive_int(raw["exit_maturity_ns"], "signal.exit_maturity_ns"),
    }


def _validate_quote(quote: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(quote, "quote")
    expected = {"quote_id", "received_at_ns", "quote_at_ns", "bid", "ask"}
    impact = envelope["impact"]
    if impact["mode"] == "DISPLAYED_DEPTH_LINEAR":
        expected.add(impact["depth_field"])
    _exact_keys(raw, expected, "quote")
    received = _utc_ns(raw["received_at_ns"], "quote.received_at_ns")
    quoted = _utc_ns(raw["quote_at_ns"], "quote.quote_at_ns")
    if quoted > received:
        raise EconomicsV2Error("quote.quote_at_ns cannot be after quote.received_at_ns")
    bid = _number(raw["bid"], "quote.bid", positive=True)
    ask = _number(raw["ask"], "quote.ask", positive=True)
    if ask <= bid:
        raise EconomicsV2Error("quote.ask must exceed quote.bid")
    normalized: dict[str, Any] = {
        "quote_id": _string(raw["quote_id"], "quote.quote_id"),
        "received_at_ns": received,
        "quote_at_ns": quoted,
        "bid": bid,
        "ask": ask,
    }
    if impact["mode"] == "DISPLAYED_DEPTH_LINEAR":
        depth_field = impact["depth_field"]
        normalized[depth_field] = _number(raw[depth_field], f"quote.{depth_field}", positive=True)
    return normalized


def _quote_age(quote: Mapping[str, Any]) -> int:
    return int(quote["received_at_ns"]) - int(quote["quote_at_ns"])


def _adverse_fill_price(quote: Mapping[str, Any], side: int, *, is_entry: bool, envelope: Mapping[str, Any]) -> tuple[float, float]:
    base = float(quote["ask"] if (side > 0) == is_entry else quote["bid"])
    bps = float(envelope["additional_slippage_bps"])
    impact = envelope["impact"]
    if impact["mode"] == "DISPLAYED_DEPTH_LINEAR":
        depth = float(quote[impact["depth_field"]])
        bps += float(impact["impact_bps_per_depth_fraction"]) * float(envelope["order_size"]) / depth
    factor = 1.0 + (bps / 10_000.0 if (side > 0) == is_entry else -bps / 10_000.0)
    price = base * factor
    if not math.isfinite(price) or price <= 0.0:
        raise EconomicsV2Error("execution envelope creates a non-positive fill price")
    return price, bps


def evaluate_execution_envelope_v2(
    signals: Sequence[Mapping[str, Any]],
    quotes: Sequence[Mapping[str, Any]],
    envelope: Mapping[str, Any],
    source_set: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate causal bid/ask receipt events against a v2 execution envelope.

    Entry is the first fresh quote received after decision-to-order latency and
    before the entry deadline.  Exit is a *later* fresh quote received after the
    signal maturity and entry receipt, bounded by the declared exit delay.  A
    stale or unavailable quote becomes an explicit exclusion, never a favorable
    same-row fill or an implicit price.
    """

    normalized_envelope = validate_execution_envelope_v2(envelope)
    normalized_sources = _contract(validate_canonical_source_set, source_set)
    normalized_signals = [_validate_signal(item) for item in signals]
    signal_ids = [item["signal_id"] for item in normalized_signals]
    if len(signal_ids) != len(set(signal_ids)):
        raise EconomicsV2Error("signals.signal_id values must be unique")
    normalized_quotes = [_validate_quote(item, normalized_envelope) for item in quotes]
    quote_ids = [item["quote_id"] for item in normalized_quotes]
    if len(quote_ids) != len(set(quote_ids)):
        raise EconomicsV2Error("quotes.quote_id values must be unique")
    if any(
        normalized_quotes[index]["received_at_ns"] > normalized_quotes[index + 1]["received_at_ns"]
        for index in range(len(normalized_quotes) - 1)
    ):
        raise EconomicsV2Error("quotes must be ordered by nondecreasing received_at_ns")

    records: list[dict[str, Any]] = []
    for signal in normalized_signals:
        order_at = signal["signal_at_ns"] + normalized_envelope["decision_to_order_latency_ns"]
        entry_deadline = order_at + normalized_envelope["maximum_entry_delay_ns"]
        entry: tuple[int, dict[str, Any]] | None = None
        entry_stale = False
        for index, quote in enumerate(normalized_quotes):
            received = quote["received_at_ns"]
            if received < order_at:
                continue
            if received > entry_deadline:
                break
            if _quote_age(quote) > normalized_envelope["entry_quote_max_age_ns"]:
                entry_stale = True
                continue
            entry = (index, quote)
            break
        base = {
            "signal_id": signal["signal_id"],
            "side": signal["side"],
            "signal_at_ns": signal["signal_at_ns"],
            "order_at_ns": order_at,
            "exit_maturity_at_ns": signal["signal_at_ns"] + signal["exit_maturity_ns"],
        }
        if entry is None:
            records.append(
                {
                    **base,
                    "disposition": "ENTRY_STALE" if entry_stale else "ENTRY_TIMEOUT",
                    "entry": None,
                    "exit": None,
                    "gross_bps": None,
                    "net_bps": None,
                }
            )
            continue
        entry_index, entry_quote = entry
        maturity = max(base["exit_maturity_at_ns"], entry_quote["received_at_ns"])
        exit_deadline = maturity + normalized_envelope["maximum_exit_delay_ns"]
        exit_quote: dict[str, Any] | None = None
        exit_stale = False
        for quote in normalized_quotes[entry_index + 1 :]:
            received = quote["received_at_ns"]
            if received < maturity:
                continue
            if received > exit_deadline:
                break
            if _quote_age(quote) > normalized_envelope["exit_quote_max_age_ns"]:
                exit_stale = True
                continue
            exit_quote = quote
            break
        entry_price, entry_bps = _adverse_fill_price(entry_quote, signal["side"], is_entry=True, envelope=normalized_envelope)
        entry_record = {
            "quote_id": entry_quote["quote_id"],
            "received_at_ns": entry_quote["received_at_ns"],
            "quote_at_ns": entry_quote["quote_at_ns"],
            "quote_age_ns": _quote_age(entry_quote),
            "fill_price": entry_price,
            "adverse_bps": entry_bps,
        }
        if exit_quote is None:
            records.append(
                {
                    **base,
                    "disposition": "EXIT_STALE" if exit_stale else "EXIT_TIMEOUT",
                    "entry": entry_record,
                    "exit": None,
                    "gross_bps": None,
                    "net_bps": None,
                }
            )
            continue
        exit_price, exit_bps = _adverse_fill_price(exit_quote, signal["side"], is_entry=False, envelope=normalized_envelope)
        gross = signal["side"] * (exit_price / entry_price - 1.0) * 10_000.0
        records.append(
            {
                **base,
                "disposition": "FILLED",
                "entry": entry_record,
                "exit": {
                    "quote_id": exit_quote["quote_id"],
                    "received_at_ns": exit_quote["received_at_ns"],
                    "quote_at_ns": exit_quote["quote_at_ns"],
                    "quote_age_ns": _quote_age(exit_quote),
                    "fill_price": exit_price,
                    "adverse_bps": exit_bps,
                },
                "gross_bps": gross,
                "net_bps": gross - normalized_envelope["round_trip_fee_bps"],
            }
        )
    counts = {name: sum(record["disposition"] == name for record in records) for name in ("FILLED", "ENTRY_STALE", "ENTRY_TIMEOUT", "EXIT_STALE", "EXIT_TIMEOUT")}
    filled = [record for record in records if record["disposition"] == "FILLED"]
    unsigned = {
        "schema": EXECUTION_ENVELOPE_RESULT_SCHEMA,
        "analysis": "quote_receipt_execution_envelope_v2",
        "scenario_id": normalized_envelope["scenario_id"],
        "source_set": normalized_sources,
        "source_set_sha256": normalized_sources["source_set_sha256"],
        "execution_envelope": normalized_envelope,
        "capabilities": {
            "depth_impact": (
                "DISPLAYED_DEPTH_SUPPORTED"
                if normalized_envelope["impact"]["mode"] == "DISPLAYED_DEPTH_LINEAR"
                else "UNAVAILABLE"
            )
        },
        "records": records,
        "disposition_counts": counts,
        "attempted_signals": len(records),
        "filled_signals": len(filled),
        "mean_net_bps_for_filled": (sum(float(record["net_bps"]) for record in filled) / len(filled)) if filled else None,
        "claims": {
            "zero_latency_displayed_bbo_is_diagnostic_only": True,
            "depth_impact_invented_when_unavailable": False,
            "economics_qualified": False,
        },
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "result_sha256")


def _validate_dataset_base(
    raw_dataset: Mapping[str, Any],
    *,
    schema: str,
    analysis: str,
    extra_fields: set[str],
    hash_field: str,
) -> dict[str, Any]:
    raw = _mapping(raw_dataset, "dataset")
    base_fields = {
        "schema",
        "analysis",
        "leg_id",
        "symbol",
        "venue",
        "contract_id",
        "retrieval_interval",
        "source_set",
        "coverage",
        "policy_sha256",
        "non_authority_claims",
        hash_field,
    }
    _exact_keys(raw, base_fields | extra_fields, "dataset")
    if raw["schema"] != schema or raw["analysis"] != analysis:
        raise EconomicsV2Error("dataset schema or analysis is unsupported")
    normalized = {
        "schema": schema,
        "analysis": analysis,
        "leg_id": _string(raw["leg_id"], "dataset.leg_id"),
        "symbol": _string(raw["symbol"], "dataset.symbol"),
        "venue": _string(raw["venue"], "dataset.venue"),
        "contract_id": _string(raw["contract_id"], "dataset.contract_id"),
        "retrieval_interval": _contract(validate_utc_interval, raw["retrieval_interval"]),
        "source_set": _contract(validate_canonical_source_set, raw["source_set"]),
        "coverage": _contract(validate_coverage_result, raw["coverage"]),
        "policy_sha256": _sha256(raw["policy_sha256"], "dataset.policy_sha256"),
        "non_authority_claims": non_authority_claims(),
    }
    if raw["non_authority_claims"] != non_authority_claims():
        raise EconomicsV2Error("dataset.non_authority_claims must retain exact false foundation claims")
    return normalized


def build_price_dataset_v2(
    *,
    leg_id: str,
    symbol: str,
    venue: str,
    contract_id: str,
    retrieval_interval: Mapping[str, Any],
    source_set: Mapping[str, Any],
    coverage: Mapping[str, Any],
    policy_sha256: str,
) -> dict[str, Any]:
    """Bind a price dataset to venue/contract, bytes, interval, and coverage."""

    unsigned = {
        "schema": PRICE_DATASET_SCHEMA,
        "analysis": "price_dataset_v2",
        "leg_id": _string(leg_id, "leg_id"),
        "symbol": _string(symbol, "symbol"),
        "venue": _string(venue, "venue"),
        "contract_id": _string(contract_id, "contract_id"),
        "retrieval_interval": _contract(validate_utc_interval, retrieval_interval),
        "source_set": _contract(validate_canonical_source_set, source_set),
        "coverage": _contract(validate_coverage_result, coverage),
        "policy_sha256": _sha256(policy_sha256, "policy_sha256"),
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "price_dataset_sha256")


def validate_price_dataset_v2(dataset: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_dataset_base
    normalized = _validate_dataset_base(
        dataset,
        schema=PRICE_DATASET_SCHEMA,
        analysis="price_dataset_v2",
        extra_fields=set(),
        hash_field="price_dataset_sha256",
    )
    return _verify_hash(dataset, normalized, "price_dataset_sha256", "price_dataset")


def build_funding_dataset_v2(
    *,
    leg_id: str,
    symbol: str,
    venue: str,
    contract_id: str,
    rate_convention: str,
    settlement_schedule: Mapping[str, Any],
    settlement_interval_convention: str,
    retrieval_interval: Mapping[str, Any],
    source_set: Mapping[str, Any],
    coverage: Mapping[str, Any],
    policy_sha256: str,
) -> dict[str, Any]:
    """Bind realized funding observations to contract, schedule, and coverage.

    Funding rates remain values of the supplied coverage observations; callers
    must use ``missing_value`` for an unknown scheduled settlement.  This
    builder never inserts a zero rate for a missing observation.
    """

    if settlement_interval_convention not in {OPEN_CLOSED, CLOSED_OPEN}:
        raise EconomicsV2Error("settlement_interval_convention must be OPEN_CLOSED or CLOSED_OPEN")
    schedule = _mapping(settlement_schedule, "settlement_schedule")
    if not schedule:
        raise EconomicsV2Error("settlement_schedule must not be empty")
    normalized_coverage = _contract(validate_coverage_result, coverage)
    if (
        normalized_coverage["coverage_kind"] != "funding_settlements_open_closed_v2"
        or normalized_coverage["interval"]["convention"] != settlement_interval_convention
    ):
        raise EconomicsV2Error(
            "funding coverage must be funding_settlements_open_closed_v2 with the declared settlement interval convention"
        )
    unsigned = {
        "schema": FUNDING_DATASET_SCHEMA,
        "analysis": "funding_dataset_v2",
        "leg_id": _string(leg_id, "leg_id"),
        "symbol": _string(symbol, "symbol"),
        "venue": _string(venue, "venue"),
        "contract_id": _string(contract_id, "contract_id"),
        "rate_convention": _string(rate_convention, "rate_convention"),
        "settlement_schedule": _json_copy(dict(schedule), "settlement_schedule"),
        "settlement_interval_convention": settlement_interval_convention,
        "retrieval_interval": _contract(validate_utc_interval, retrieval_interval),
        "source_set": _contract(validate_canonical_source_set, source_set),
        "coverage": normalized_coverage,
        "policy_sha256": _sha256(policy_sha256, "policy_sha256"),
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "funding_dataset_sha256")


def validate_funding_dataset_v2(dataset: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _validate_dataset_base(
        dataset,
        schema=FUNDING_DATASET_SCHEMA,
        analysis="funding_dataset_v2",
        extra_fields={"rate_convention", "settlement_schedule", "settlement_interval_convention"},
        hash_field="funding_dataset_sha256",
    )
    raw = _mapping(dataset, "funding_dataset")
    convention = raw["settlement_interval_convention"]
    if convention not in {OPEN_CLOSED, CLOSED_OPEN}:
        raise EconomicsV2Error("funding_dataset.settlement_interval_convention is unsupported")
    schedule = _mapping(raw["settlement_schedule"], "funding_dataset.settlement_schedule")
    if not schedule:
        raise EconomicsV2Error("funding_dataset.settlement_schedule must not be empty")
    if (
        normalized["coverage"]["coverage_kind"] != "funding_settlements_open_closed_v2"
        or normalized["coverage"]["interval"]["convention"] != convention
    ):
        raise EconomicsV2Error(
            "funding_dataset coverage must use the declared settlement interval convention"
        )
    unsigned = {
        **normalized,
        "rate_convention": _string(raw["rate_convention"], "funding_dataset.rate_convention"),
        "settlement_schedule": _json_copy(dict(schedule), "funding_dataset.settlement_schedule"),
        "settlement_interval_convention": convention,
    }
    # Reorder the fields to the builder's canonical semantic layout.
    unsigned = {
        "schema": unsigned["schema"],
        "analysis": unsigned["analysis"],
        "leg_id": unsigned["leg_id"],
        "symbol": unsigned["symbol"],
        "venue": unsigned["venue"],
        "contract_id": unsigned["contract_id"],
        "rate_convention": unsigned["rate_convention"],
        "settlement_schedule": unsigned["settlement_schedule"],
        "settlement_interval_convention": unsigned["settlement_interval_convention"],
        "retrieval_interval": unsigned["retrieval_interval"],
        "source_set": unsigned["source_set"],
        "coverage": unsigned["coverage"],
        "policy_sha256": unsigned["policy_sha256"],
        "non_authority_claims": unsigned["non_authority_claims"],
    }
    return _verify_hash(dataset, unsigned, "funding_dataset_sha256", "funding_dataset")


def _combined_source_set(price: Mapping[str, Any], funding: Mapping[str, Any]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for prefix, dataset in (("price", price), ("funding", funding)):
        for source in dataset["source_set"]["sources"]:
            records.append(
                {
                    "source_id": f"{prefix}:{source['source_id']}",
                    "size_bytes": source["size_bytes"],
                    "sha256": source["sha256"],
                }
            )
    return _contract(build_canonical_source_set, records)


def build_economics_qualification_v2(
    price_dataset: Mapping[str, Any],
    funding_dataset: Mapping[str, Any],
    *,
    qualification_policy_sha256: str,
) -> dict[str, Any]:
    """Produce a venue/contract/coverage-gated economics qualification result.

    A mismatch or incomplete coverage is represented visibly as
    ``descriptive_incomplete_economics`` rather than being zero-filled or
    labelled as venue-consistent.  The qualification is still non-authoritative:
    local source hashes do not prove provider completeness or calibration.
    """

    price = validate_price_dataset_v2(price_dataset)
    funding = validate_funding_dataset_v2(funding_dataset)
    same_leg = price["leg_id"] == funding["leg_id"] and price["symbol"] == funding["symbol"]
    same_venue = price["venue"] == funding["venue"]
    same_contract = price["contract_id"] == funding["contract_id"]
    price_complete = price["coverage"]["status"] == "COMPLETE"
    funding_complete = funding["coverage"]["status"] == "COMPLETE"
    convention_is_declared = funding["settlement_interval_convention"] in {OPEN_CLOSED, CLOSED_OPEN}
    qualified = all((same_leg, same_venue, same_contract, price_complete, funding_complete, convention_is_declared))
    status = "venue_consistent_complete" if qualified else "descriptive_incomplete_economics"
    source_set = _combined_source_set(price, funding)
    generic_manifest = _contract(
        build_manifest_result,
        "economics_qualification_v2",
        source_set,
        "COMPLETE" if qualified else "INCOMPLETE",
        coverage=funding["coverage"],
        policy_sha256=_sha256(qualification_policy_sha256, "qualification_policy_sha256"),
        attributes={
            "qualification_status": status,
            "price_coverage_complete": price_complete,
            "funding_coverage_complete": funding_complete,
            "venue_match": same_venue,
            "contract_match": same_contract,
            "leg_match": same_leg,
        },
    )
    unsigned = {
        "schema": ECONOMICS_QUALIFICATION_SCHEMA,
        "analysis": "venue_contract_funding_qualification_v2",
        "leg_id": price["leg_id"],
        "symbol": price["symbol"],
        "price_dataset": price,
        "funding_dataset": funding,
        "source_set": source_set,
        "coverage": funding["coverage"],
        "per_leg_coverage": {
            "price": {
                "coverage_status": price["coverage"]["status"],
                "coverage_sha256": price["coverage"]["coverage_sha256"],
                "missing_observation_ids": price["coverage"]["missing_observation_ids"],
            },
            "funding": {
                "coverage_status": funding["coverage"]["status"],
                "coverage_sha256": funding["coverage"]["coverage_sha256"],
                "missing_observation_ids": funding["coverage"]["missing_observation_ids"],
                "settlement_interval_convention": funding["settlement_interval_convention"],
            },
        },
        "qualification_checks": {
            "leg_and_symbol_match": same_leg,
            "venue_match": same_venue,
            "contract_match": same_contract,
            "price_coverage_complete": price_complete,
            "funding_coverage_complete": funding_complete,
            "settlement_convention_declared": convention_is_declared,
        },
        "qualification_status": status,
        "qualification_policy_sha256": _sha256(qualification_policy_sha256, "qualification_policy_sha256"),
        "manifest": generic_manifest,
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "qualification_sha256")


def _normalize_held_interval(item: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(item, "held_interval")
    _exact_keys(raw, {"leg_id", "interval_id", "interval"}, "held_interval")
    interval = _contract(validate_utc_interval, raw["interval"])
    if interval["convention"] != OPEN_CLOSED:
        raise EconomicsV2Error("held_interval.interval must declare OPEN_CLOSED settlement semantics")
    return {
        "leg_id": _string(raw["leg_id"], "held_interval.leg_id"),
        "interval_id": _string(raw["interval_id"], "held_interval.interval_id"),
        "interval": interval,
    }


def _normalize_settlement(item: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(item, "settlement")
    _exact_keys(raw, {"leg_id", "settlement_id", "timestamp_utc", "observation"}, "settlement")
    timestamp = _parse_utc_string(raw["timestamp_utc"], "settlement.timestamp_utc")
    return {
        "leg_id": _string(raw["leg_id"], "settlement.leg_id"),
        "settlement_id": _string(raw["settlement_id"], "settlement.settlement_id"),
        "timestamp_utc": timestamp,
        "observation": _contract(validate_observation_value, raw["observation"]),
    }


def _parse_utc_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EconomicsV2Error(f"{field} must be an ISO-8601 timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise EconomicsV2Error(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EconomicsV2Error(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_settlement_coverage_v2(
    held_intervals: Sequence[Mapping[str, Any]],
    settlements: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build OPEN_CLOSED funding coverage from the very settlements cash flow uses.

    Every settlement rate scheduled inside a held interval becomes a coverage
    observation and an observed rate becomes an applied cash-flow record.  An
    endpoint settlement is included; a start-boundary settlement belongs to a
    preceding interval, never the new one.  An interval with no caller-declared
    expected settlement fails closed rather than assuming an implicit zero.
    """

    normalized_intervals = [_normalize_held_interval(item) for item in held_intervals]
    if not normalized_intervals:
        raise EconomicsV2Error("held_intervals must contain at least one interval")
    keys = [(item["leg_id"], item["interval_id"]) for item in normalized_intervals]
    if len(keys) != len(set(keys)):
        raise EconomicsV2Error("held intervals must have unique leg_id/interval_id pairs")
    normalized_intervals.sort(key=lambda item: (item["leg_id"], item["interval"]["start_utc"], item["interval_id"]))
    for left, right in zip(normalized_intervals, normalized_intervals[1:]):
        if left["leg_id"] != right["leg_id"]:
            continue
        if left["interval"]["end_utc"] > right["interval"]["start_utc"]:
            raise EconomicsV2Error("held intervals for a leg may not overlap")
    normalized_settlements = [_normalize_settlement(item) for item in settlements]
    settlement_ids = [item["settlement_id"] for item in normalized_settlements]
    if len(settlement_ids) != len(set(settlement_ids)):
        raise EconomicsV2Error("settlement_id values must be globally unique")
    assigned: dict[tuple[str, str], list[dict[str, Any]]] = {key: [] for key in keys}
    for settlement in normalized_settlements:
        candidates = [
            interval
            for interval in normalized_intervals
            if interval["leg_id"] == settlement["leg_id"]
            and _contract(interval_contains, settlement["timestamp_utc"], interval["interval"])
        ]
        if len(candidates) != 1:
            raise EconomicsV2Error(
                f"settlement {settlement['settlement_id']} must belong to exactly one declared OPEN_CLOSED held interval"
            )
        assigned[(candidates[0]["leg_id"], candidates[0]["interval_id"])].append(settlement)
    coverage_observations: list[dict[str, Any]] = []
    cashflow_settlements: list[dict[str, Any]] = []
    per_interval: list[dict[str, Any]] = []
    for interval in normalized_intervals:
        key = (interval["leg_id"], interval["interval_id"])
        observations = sorted(assigned[key], key=lambda item: (item["timestamp_utc"], item["settlement_id"]))
        if not observations:
            observation_id = f"{interval['leg_id']}:{interval['interval_id']}:no_declared_expected_settlement"
            coverage_observations.append(
                {"observation_id": observation_id, "observation": missing_value("no_declared_expected_settlement")}
            )
            per_interval.append({
                **interval,
                "expected_settlement_ids": [],
                "applied_settlement_ids": [],
                "coverage_status": "INCOMPLETE",
            })
            continue
        applied: list[str] = []
        for settlement in observations:
            observation_id = f"{interval['leg_id']}:{interval['interval_id']}:{settlement['settlement_id']}"
            coverage_observations.append({"observation_id": observation_id, "observation": settlement["observation"]})
            if settlement["observation"]["availability"] == "OBSERVED":
                applied.append(settlement["settlement_id"])
                cashflow_settlements.append({
                    "leg_id": interval["leg_id"],
                    "interval_id": interval["interval_id"],
                    "settlement_id": settlement["settlement_id"],
                    "timestamp_utc": settlement["timestamp_utc"],
                    "rate": settlement["observation"]["value"],
                })
        per_interval.append({
            **interval,
            "expected_settlement_ids": [item["settlement_id"] for item in observations],
            "applied_settlement_ids": applied,
            "coverage_status": "COMPLETE" if len(applied) == len(observations) else "INCOMPLETE",
        })
    starts = [item["interval"]["start_utc"] for item in normalized_intervals]
    ends = [item["interval"]["end_utc"] for item in normalized_intervals]
    enclosing = _contract(build_utc_interval, min(starts), max(ends), convention=OPEN_CLOSED)
    coverage = _contract(
        build_coverage_result,
        "funding_settlements_open_closed_v2",
        enclosing,
        coverage_observations,
    )
    unsigned = {
        "schema": SETTLEMENT_COVERAGE_SCHEMA,
        "analysis": "settlement_coverage_from_cashflow_v2",
        "settlement_interval_convention": OPEN_CLOSED,
        "coverage": coverage,
        "held_intervals": normalized_intervals,
        "per_held_interval": per_interval,
        "cashflow_settlements": cashflow_settlements,
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "settlement_coverage_sha256")


def read_funding_coverage_v1_v2(legacy_report: Mapping[str, Any]) -> dict[str, Any]:
    """Read, label, and preserve a v1 strict-inside funding audit without changing it."""

    raw = _mapping(legacy_report, "legacy_funding_coverage_report")
    if raw.get("schema_version") != 1 or raw.get("analysis") != "cross_sectional_funding_coverage_audit_v1":
        raise EconomicsV2Error("unsupported legacy funding coverage report")
    preserved = _json_copy(dict(raw), "legacy_funding_coverage_report")
    unsigned = {
        "schema": LEGACY_FUNDING_COVERAGE_READER_SCHEMA,
        "analysis": "legacy_funding_coverage_v1_reader",
        "legacy_schema_version": 1,
        "legacy_interval_rule": "strict_inside_preserved_unmodified",
        "legacy_report": preserved,
        "migration_status": "legacy_v1_not_reclassified; use settlement_coverage_from_cashflow_v2 for successor work",
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "reader_sha256")


def _validate_tolerance(value: object) -> dict[str, float]:
    raw = _mapping(value, "comparison_tolerance")
    _exact_keys(raw, {"absolute", "relative"}, "comparison_tolerance")
    return {
        "absolute": _number(raw["absolute"], "comparison_tolerance.absolute", nonnegative=True),
        "relative": _number(raw["relative"], "comparison_tolerance.relative", nonnegative=True),
    }


def build_economic_calibration_fixture_v2(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a frozen cost/funding fixture without executing an engine formula.

    The expected ledger is caller-frozen, hash-bound test data.  It is not
    generated by a second copy of the production formula, which prevents this
    harness from manufacturing an "independent" parity claim.
    """

    raw = _mapping(fixture, "fixture")
    _exact_keys(
        raw,
        {
            "schema",
            "fixture_id",
            "protocol_sha256",
            "source_set",
            "assumptions",
            "expected_ledger",
            "comparison_tolerance",
        },
        "fixture",
    )
    if raw["schema"] != ECONOMIC_CALIBRATION_FIXTURE_SCHEMA:
        raise EconomicsV2Error("fixture.schema is unsupported")
    assumptions = _mapping(raw["assumptions"], "fixture.assumptions")
    required_assumptions = {"bid_ask", "fees", "slippage", "funding", "terminal_liquidation"}
    missing_assumptions = required_assumptions - set(assumptions)
    if missing_assumptions:
        raise EconomicsV2Error("fixture.assumptions missing " + ",".join(sorted(missing_assumptions)))
    ledger = _mapping(raw["expected_ledger"], "fixture.expected_ledger")
    required_ledger = {"event_order", "fills", "cash_flows", "trades", "turnover_units", "terminal_equity"}
    missing_ledger = required_ledger - set(ledger)
    if missing_ledger:
        raise EconomicsV2Error("fixture.expected_ledger missing " + ",".join(sorted(missing_ledger)))
    if not isinstance(ledger["fills"], list) or not isinstance(ledger["cash_flows"], list) or not isinstance(ledger["trades"], list):
        raise EconomicsV2Error("fixture expected fills, cash_flows, and trades must be arrays")
    _number(ledger["turnover_units"], "fixture.expected_ledger.turnover_units", nonnegative=True)
    _number(ledger["terminal_equity"], "fixture.expected_ledger.terminal_equity", positive=True)
    unsigned = {
        "schema": ECONOMIC_CALIBRATION_FIXTURE_SCHEMA,
        "fixture_id": _string(raw["fixture_id"], "fixture.fixture_id"),
        "protocol_sha256": _sha256(raw["protocol_sha256"], "fixture.protocol_sha256"),
        "source_set": _contract(validate_canonical_source_set, raw["source_set"]),
        "assumptions": _json_copy(dict(assumptions), "fixture.assumptions"),
        "expected_ledger": _json_copy(dict(ledger), "fixture.expected_ledger"),
        "comparison_tolerance": _validate_tolerance(raw["comparison_tolerance"]),
    }
    return _self_hash(unsigned, "fixture_sha256")


def _validate_engine_spec(engine_spec: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(engine_spec, "engine_spec")
    _exact_keys(raw, {"engine_name", "engine_version", "distribution_sha256", "runner_protocol_version"}, "engine_spec")
    return {
        "engine_name": _string(raw["engine_name"], "engine_spec.engine_name"),
        "engine_version": _string(raw["engine_version"], "engine_spec.engine_version"),
        "distribution_sha256": _sha256(raw["distribution_sha256"], "engine_spec.distribution_sha256"),
        "runner_protocol_version": _string(raw["runner_protocol_version"], "engine_spec.runner_protocol_version"),
    }


def _numeric_close(left: float, right: float, *, absolute: float, relative: float) -> bool:
    return abs(left - right) <= absolute + relative * max(abs(left), abs(right))


def _ledger_differences(expected: object, observed: object, tolerance: Mapping[str, float], path: str = "ledger") -> list[dict[str, Any]]:
    if isinstance(expected, bool) or isinstance(observed, bool):
        return [] if expected is observed else [{"path": path, "expected": expected, "observed": observed, "kind": "value"}]
    if isinstance(expected, (int, float)) and isinstance(observed, (int, float)):
        _number(expected, f"{path}.expected")
        _number(observed, f"{path}.observed")
        # Preserve integer nanosecond differences above float's 2**53 limit.
        left, right = expected, observed
        return [] if _numeric_close(left, right, absolute=tolerance["absolute"], relative=tolerance["relative"]) else [
            {"path": path, "expected": left, "observed": right, "kind": "numeric"}
        ]
    if isinstance(expected, list) and isinstance(observed, list):
        differences: list[dict[str, Any]] = []
        if len(expected) != len(observed):
            differences.append({"path": path, "expected": len(expected), "observed": len(observed), "kind": "length"})
        for index, (left, right) in enumerate(zip(expected, observed)):
            differences.extend(_ledger_differences(left, right, tolerance, f"{path}[{index}]"))
        return differences
    if isinstance(expected, Mapping) and isinstance(observed, Mapping):
        differences = []
        if set(expected) != set(observed):
            differences.append(
                {"path": path, "expected_keys": sorted(expected), "observed_keys": sorted(observed), "kind": "keys"}
            )
        for key in sorted(set(expected) & set(observed)):
            differences.extend(_ledger_differences(expected[key], observed[key], tolerance, f"{path}.{key}"))
        return differences
    return [] if expected == observed else [{"path": path, "expected": expected, "observed": observed, "kind": "value"}]


def _validate_engine_output(engine_output: Mapping[str, Any], expected_engine: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(engine_output, "engine_output")
    if set(raw) - {"engine_identity", "ledger", "runtime_evidence"} or not {"engine_identity", "ledger"}.issubset(raw):
        raise EconomicsV2Error("engine_output has unsupported shape")
    identity = _validate_engine_spec(raw["engine_identity"])
    if identity != expected_engine:
        raise EconomicsV2Error("engine_output.engine_identity does not match pinned engine_spec")
    ledger = _mapping(raw["ledger"], "engine_output.ledger")
    return {"engine_identity": identity, "ledger": _json_copy(dict(ledger), "engine_output.ledger")}


def compare_external_engine_calibration_v2(
    fixture: Mapping[str, Any], engine_spec: Mapping[str, Any], engine_output: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare a pinned *external* engine ledger to a frozen economic fixture.

    A matching local file is deliberately not an external-provenance proof, so
    the result keeps ``independent_engine_calibration_verified`` false.  The
    report is useful CI evidence only after an operator supplies a maintained
    independent engine and its pinned distribution hash.
    """

    normalized_fixture = build_economic_calibration_fixture_v2(fixture)
    normalized_engine = _validate_engine_spec(engine_spec)
    output = _validate_engine_output(engine_output, normalized_engine)
    differences = _ledger_differences(
        normalized_fixture["expected_ledger"], output["ledger"], normalized_fixture["comparison_tolerance"]
    )
    unsigned = {
        "schema": ECONOMIC_CALIBRATION_SCHEMA,
        "analysis": "external_engine_economic_ledger_calibration_v2",
        "fixture_id": normalized_fixture["fixture_id"],
        "fixture_sha256": normalized_fixture["fixture_sha256"],
        "protocol_sha256": normalized_fixture["protocol_sha256"],
        "source_set": normalized_fixture["source_set"],
        "assumptions": normalized_fixture["assumptions"],
        "engine_identity": normalized_engine,
        "comparison_tolerance": normalized_fixture["comparison_tolerance"],
        "ledger_match": not differences,
        "differences": differences,
        "status": "ENGINE_LEDGER_MATCHED_NOT_EXTERNALLY_VERIFIED" if not differences else "ENGINE_LEDGER_MISMATCH",
        "claims": {
            "engineering_calibration_only": True,
            "profitability_or_promotion_verdict": False,
            "external_engine_provenance_verified": False,
        },
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "calibration_sha256")


def build_not_calibrated_external_engine_report_v2(
    fixture: Mapping[str, Any], engine_spec: Mapping[str, Any], *, reason: str
) -> dict[str, Any]:
    """Record missing/failed independent-engine availability without fake parity."""

    normalized_fixture = build_economic_calibration_fixture_v2(fixture)
    normalized_engine = _validate_engine_spec(engine_spec)
    unsigned = {
        "schema": ECONOMIC_CALIBRATION_SCHEMA,
        "analysis": "external_engine_economic_ledger_calibration_v2",
        "fixture_id": normalized_fixture["fixture_id"],
        "fixture_sha256": normalized_fixture["fixture_sha256"],
        "protocol_sha256": normalized_fixture["protocol_sha256"],
        "source_set": normalized_fixture["source_set"],
        "assumptions": normalized_fixture["assumptions"],
        "engine_identity": normalized_engine,
        "comparison_tolerance": normalized_fixture["comparison_tolerance"],
        "ledger_match": None,
        "differences": [],
        "status": "NOT_CALIBRATED_ENGINE_UNAVAILABLE",
        "not_calibrated_reason": _string(reason, "reason"),
        "claims": {
            "engineering_calibration_only": True,
            "profitability_or_promotion_verdict": False,
            "external_engine_provenance_verified": False,
        },
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "calibration_sha256")


def run_pinned_external_engine_calibration_v2(
    fixture: Mapping[str, Any],
    engine_spec: Mapping[str, Any],
    runner_command: Sequence[str],
    *,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Invoke an operator-supplied offline external-engine adapter and compare output.

    The adapter receives ``--fixture <path> --output <path>`` and must emit the
    documented engine-output JSON.  This module neither downloads an engine nor
    supplies an in-house formula as a substitute.  A missing/nonzero runner is a
    ``NOT_CALIBRATED_ENGINE_UNAVAILABLE`` report rather than a passed parity.
    """

    normalized_fixture = build_economic_calibration_fixture_v2(fixture)
    normalized_engine = _validate_engine_spec(engine_spec)
    if type(timeout_seconds) is not int or timeout_seconds <= 0 or timeout_seconds > 300:
        raise EconomicsV2Error("timeout_seconds must be an integer from 1 through 300")
    if not isinstance(runner_command, Sequence) or isinstance(runner_command, (str, bytes)) or not runner_command:
        raise EconomicsV2Error("runner_command must be a nonempty command sequence")
    command = [_string(item, "runner_command item") for item in runner_command]
    with tempfile.TemporaryDirectory(prefix="orderflow-economic-calibration-") as temporary:
        fixture_path = Path(temporary) / "fixture.json"
        output_path = Path(temporary) / "engine-output.json"
        fixture_path.write_text(json.dumps(normalized_fixture, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        environment = {"ORDERFLOW_CALIBRATION_OFFLINE": "1", "NO_PROXY": "*"}
        try:
            completed = subprocess.run(
                [*command, "--fixture", str(fixture_path), "--output", str(output_path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return build_not_calibrated_external_engine_report_v2(
                fixture, engine_spec, reason=f"runner_unavailable:{type(exc).__name__}"
            )
        if completed.returncode != 0 or not output_path.is_file():
            return build_not_calibrated_external_engine_report_v2(
                fixture,
                engine_spec,
                reason=f"runner_failed_or_no_output:exit_{completed.returncode}",
            )
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return build_not_calibrated_external_engine_report_v2(fixture, engine_spec, reason=f"runner_invalid_output:{type(exc).__name__}")
    return compare_external_engine_calibration_v2(fixture, engine_spec, output)


def run_nautilus_economic_calibration_v2(
    fixture: Mapping[str, Any], *, wheel_path: str | Path,
) -> dict[str, Any]:
    """Run real local pinned native-engine evidence, not a supplied-ledger claim.

    Explicitly calibrates the additive fixed-contract quote ledger only. Frozen
    v3 compounding, v2 proportional-bps slippage, depth impact and realistic
    liquidity/latency are NOT declared calibrated by this synthetic protocol.
    """
    from orderflow_edge_lab.independent_calibration_v2 import (
        ENGINE_SPEC, TOLERANCE, IndependentCalibrationUnavailable,
        canonical_quote_ledger_v2, run_fixture,
    )

    normalized = build_economic_calibration_fixture_v2(fixture)
    if normalized["comparison_tolerance"] != TOLERANCE:
        raise EconomicsV2Error("native quote protocol freezes tolerance at absolute=1e-7, relative=0")
    case = normalized["assumptions"].get("quote_case")
    if not isinstance(case, Mapping):
        raise EconomicsV2Error("native quote protocol requires assumptions.quote_case")
    case_bytes = canonical_json_bytes(case)
    if not any(source["sha256"] == canonical_json_sha256(case) and source["size_bytes"] == len(case_bytes)
               for source in normalized["source_set"]["sources"]):
        raise EconomicsV2Error("native quote_case must match a hash-bound synthetic source record")
    canonical = canonical_quote_ledger_v2(case)
    canonical_differences = _ledger_differences(normalized["expected_ledger"], canonical, TOLERANCE)
    try:
        output = run_fixture(normalized, wheel_path)
    except (IndependentCalibrationUnavailable, ImportError, RuntimeError) as exc:
        return build_not_calibrated_external_engine_report_v2(
            fixture, ENGINE_SPEC, reason=f"native_runtime_unavailable:{type(exc).__name__}:{exc}",
        )
    comparison = compare_external_engine_calibration_v2(fixture, ENGINE_SPEC, output)
    passed = comparison["ledger_match"] and not canonical_differences
    audit = output["runtime_evidence"]["audit"]
    reconciled = abs(audit["native_pnl_cash_residual"]) <= TOLERANCE["absolute"] and audit["open_positions"] == 0
    passed = bool(passed and reconciled)
    targets = [step["target"] for step in case["steps"]]
    resize = any(left * right > 0 and left != right for left, right in zip(targets, targets[1:]))
    reversal = any(left * right < 0 for left, right in zip(targets, targets[1:]))
    unsigned = {key: value for key, value in comparison.items() if key != "calibration_sha256"}
    unsigned.update({
        "status": "LOCAL_INDEPENDENT_CALIBRATION_PASSED_PARTIAL_MECHANISMS" if passed else "ENGINE_LEDGER_MISMATCH",
        "local_independent_calibration_evidence": passed,
        "canonical_model": "canonical_quote_fixed_contract_v2_not_frozen_v3",
        "canonical_ledger": canonical,
        "canonical_fixture_differences": canonical_differences,
        "engine_ledger": output["ledger"],
        "native_pnl_cash_reconciled": reconciled,
        "runtime_evidence": output["runtime_evidence"],
        "coverage_disposition": {
            "bid_ask": "NATIVE_L1_SYNTHETIC_BBO",
            "fees": "NATIVE_TAKER_PERCENT_OF_EXECUTED_NOTIONAL" if case["taker_fee"] else "ZERO_FEE_CASE",
            "slippage": "NATIVE_RC5_ONE_TICK_MODEL_OBSERVED_TWO_TICK_DISPLACEMENT" if case["slippage_ticks"] else "ZERO_ADDITIONAL_SLIPPAGE_CASE",
            "funding": "NATIVE_FUNDING_RATE_UPDATE_SETTLEMENT_AND_POSITION_ADJUSTED_AUDITED" if audit["native_funding_adjustments"] else "NOT_EXERCISED_NO_HELD_POSITION_SETTLEMENT",
            "resize": "NATIVE_NETTING_WEIGHTED_AVERAGE_COST" if resize else "NOT_EXERCISED",
            "reversal": "NATIVE_NETTING_CLOSE_AND_REOPEN_EVENTS" if reversal else "NOT_EXERCISED",
            "terminal_liquidation": "EXPLICIT_NATIVE_FINAL_MARKET_FILL_AND_ZERO_OPEN_POSITIONS",
            "proportional_bps_slippage": "NOT_CALIBRATED_UNSUPPORTED_BY_THIS_NATIVE_MODEL",
            "displayed_depth_linear_impact": "NOT_CALIBRATED_UNSUPPORTED_BY_THIS_NATIVE_MODEL",
            "frozen_canonical_v3": "NOT_CALIBRATED_DIFFERENT_WEIGHT_COMPOUNDING_AND_COST_SEMANTICS",
        },
    })
    return _self_hash(unsigned, "calibration_sha256")


def _normalize_availability_record(item: Mapping[str, Any], frozen: set[str]) -> dict[str, Any]:
    raw = _mapping(item, "availability_record")
    _exact_keys(
        raw,
        {"symbol", "date_utc", "leg", "availability", "reason", "input_manifest_sha256", "active_side"},
        "availability_record",
    )
    symbol = _string(raw["symbol"], "availability_record.symbol")
    if symbol not in frozen:
        raise EconomicsV2Error(f"availability record symbol is outside frozen universe: {symbol}")
    date = raw["date_utc"]
    if not isinstance(date, str):
        raise EconomicsV2Error("availability_record.date_utc must be YYYY-MM-DD")
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise EconomicsV2Error("availability_record.date_utc must be YYYY-MM-DD") from exc
    availability = raw["availability"]
    if availability not in _AVAILABILITY:
        raise EconomicsV2Error("availability_record.availability is unsupported")
    reason = raw["reason"]
    if availability == "ELIGIBLE":
        if reason is not None:
            raise EconomicsV2Error("eligible availability record reason must be null")
    else:
        if reason not in _AVAILABILITY_REASONS:
            raise EconomicsV2Error("ineligible/unavailable record requires a declared availability reason")
    active_side = raw["active_side"]
    if active_side not in {"LONG", "SHORT", "NONE"}:
        raise EconomicsV2Error("availability_record.active_side must be LONG, SHORT, or NONE")
    if availability != "ELIGIBLE" and active_side != "NONE":
        raise EconomicsV2Error("ineligible/unavailable records must have active_side NONE")
    return {
        "symbol": symbol,
        "date_utc": parsed.strftime("%Y-%m-%d"),
        "leg": _string(raw["leg"], "availability_record.leg"),
        "availability": availability,
        "reason": reason,
        "input_manifest_sha256": _sha256(raw["input_manifest_sha256"], "availability_record.input_manifest_sha256"),
        "active_side": active_side,
    }


def build_universe_availability_v2(
    frozen_universe: Sequence[str],
    records: Sequence[Mapping[str, Any]],
    *,
    source_set: Mapping[str, Any],
    policy_sha256: str,
    minimum_names_by_leg: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Build an append-only frozen-universe availability/delisting sidecar.

    The function does not calculate or alter returns.  It forces a record for
    every frozen symbol/date/leg and exposes active breadth and caller-declared
    minimum-name status for a successor report.
    """

    if not isinstance(frozen_universe, Sequence) or isinstance(frozen_universe, (str, bytes)) or not frozen_universe:
        raise EconomicsV2Error("frozen_universe must be a nonempty symbol sequence")
    normalized_universe = [_string(symbol, "frozen_universe symbol") for symbol in frozen_universe]
    if len(normalized_universe) != len(set(normalized_universe)):
        raise EconomicsV2Error("frozen_universe symbols must be unique")
    frozen = set(normalized_universe)
    normalized_records = [_normalize_availability_record(item, frozen) for item in records]
    if not normalized_records:
        raise EconomicsV2Error("records must contain availability evidence")
    record_keys = [(item["symbol"], item["date_utc"], item["leg"]) for item in normalized_records]
    if len(record_keys) != len(set(record_keys)):
        raise EconomicsV2Error("availability records must be unique by symbol/date/leg")
    dates = sorted({item["date_utc"] for item in normalized_records})
    legs = sorted({item["leg"] for item in normalized_records})
    expected = {(symbol, date, leg) for symbol in frozen for date in dates for leg in legs}
    present = set(record_keys)
    if present != expected:
        missing = sorted(expected - present)
        extra = sorted(present - expected)
        raise EconomicsV2Error(f"availability records must cover every frozen symbol/date/leg (missing={missing[:3]}, extra={extra[:3]})")
    minimums_raw = _mapping(minimum_names_by_leg or {}, "minimum_names_by_leg")
    if set(minimums_raw) - set(legs):
        raise EconomicsV2Error("minimum_names_by_leg contains an undeclared leg")
    minimums = {leg: _positive_int(value, f"minimum_names_by_leg.{leg}") for leg, value in minimums_raw.items()}
    normalized_records.sort(key=lambda item: (item["date_utc"], item["leg"], item["symbol"]))
    day_leg_summary: list[dict[str, Any]] = []
    for date in dates:
        for leg in legs:
            group = [item for item in normalized_records if item["date_utc"] == date and item["leg"] == leg]
            eligible = [item for item in group if item["availability"] == "ELIGIBLE"]
            minimum = minimums.get(leg)
            day_leg_summary.append(
                {
                    "date_utc": date,
                    "leg": leg,
                    "frozen_universe_count": len(normalized_universe),
                    "eligible_count": len(eligible),
                    "ineligible_count": sum(item["availability"] == "INELIGIBLE" for item in group),
                    "unavailable_count": sum(item["availability"] == "UNAVAILABLE" for item in group),
                    "frozen_universe_fraction": len(eligible) / len(normalized_universe),
                    "long_breadth": sum(item["active_side"] == "LONG" for item in eligible),
                    "short_breadth": sum(item["active_side"] == "SHORT" for item in eligible),
                    "minimum_names_declared": minimum,
                    "minimum_name_status": (
                        "NOT_DECLARED" if minimum is None else ("DECLARED_MET" if len(eligible) >= minimum else "DECLARED_NOT_MET")
                    ),
                    "subset_based": len(eligible) != len(normalized_universe),
                }
            )
    unsigned = {
        "schema": UNIVERSE_AVAILABILITY_SCHEMA,
        "analysis": "frozen_universe_availability_sidecar_v2",
        "frozen_universe": normalized_universe,
        "frozen_universe_sha256": canonical_json_sha256(normalized_universe),
        "source_set": _contract(validate_canonical_source_set, source_set),
        "policy_sha256": _sha256(policy_sha256, "policy_sha256"),
        "minimum_names_by_leg": minimums,
        "records": normalized_records,
        "daily_leg_summary": day_leg_summary,
        "claims": {
            "legacy_v1_universe_or_return_calculation_changed": False,
            "availability_is_descriptive_sidecar_only": True,
            "pass_fail_rule_created": False,
        },
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "availability_sha256")


def attach_universe_availability_v2(report: Mapping[str, Any], sidecar: Mapping[str, Any]) -> dict[str, Any]:
    """Create a newly named report link without mutating a v1 forward report."""

    availability = _mapping(sidecar, "sidecar")
    expected_keys = {
        "schema", "analysis", "frozen_universe", "frozen_universe_sha256", "source_set", "policy_sha256",
        "minimum_names_by_leg", "records", "daily_leg_summary", "claims", "non_authority_claims", "availability_sha256",
    }
    _exact_keys(availability, expected_keys, "sidecar")
    rebuilt = build_universe_availability_v2(
        availability["frozen_universe"], availability["records"], source_set=availability["source_set"],
        policy_sha256=availability["policy_sha256"], minimum_names_by_leg=availability["minimum_names_by_leg"],
    )
    if rebuilt != dict(availability):
        raise EconomicsV2Error("sidecar availability hash or content is invalid")
    report_copy = _json_copy(dict(_mapping(report, "report")), "report")
    unsigned = {
        "schema": "orderflow_edge_lab.forward_report_with_availability.v2",
        "analysis": "forward_report_availability_link_v2",
        "legacy_report": report_copy,
        "availability_sidecar_sha256": rebuilt["availability_sha256"],
        "frozen_universe_sha256": rebuilt["frozen_universe_sha256"],
        "subset_based_days": [
            {"date_utc": item["date_utc"], "leg": item["leg"]}
            for item in rebuilt["daily_leg_summary"] if item["subset_based"]
        ],
        "claims": {
            "legacy_v1_report_mutated": False,
            "return_calculation_reweighted": False,
            "availability_link_is_descriptive": True,
        },
        "non_authority_claims": non_authority_claims(),
    }
    return _self_hash(unsigned, "linked_report_sha256")


def _load_object(path: str | Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EconomicsV2Error(f"cannot read JSON object from {path}") from exc
    return _mapping(raw, f"JSON at {path}")


def _emit(value: Mapping[str, Any], output: str | None) -> None:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    if output is None:
        print(encoded, end="")
    else:
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Run offline v2 economics operations on caller-supplied JSON only."""

    parser = argparse.ArgumentParser(description="Offline Orderflow Edge Lab economic-accounting v2 tools.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate-envelope", "validate an execution-envelope JSON object"),
        ("evaluate-envelope", "evaluate signals/quote receipt events under an envelope"),
        ("qualify-economics", "build a venue/contract/funding qualification result"),
        ("settlement-coverage", "build OPEN_CLOSED settlement coverage from expected settlements"),
        ("availability", "build a frozen-universe availability sidecar"),
        ("calibrate", "compare a pinned external-engine ledger or record an unavailable engine"),
        ("calibrate-nautilus", "execute authentic pinned Nautilus on offline synthetic quote fixtures"),
    ):
        sub = subcommands.add_parser(name, help=help_text)
        sub.add_argument("input", help="JSON request object")
        sub.add_argument("--output", help="new JSON output path; stdout when omitted")
    args = parser.parse_args(argv)
    try:
        request = _load_object(args.input)
        if args.command == "validate-envelope":
            result = validate_execution_envelope_v2(request)
        elif args.command == "evaluate-envelope":
            _exact_keys(request, {"signals", "quotes", "envelope", "source_set"}, "evaluate-envelope request")
            result = evaluate_execution_envelope_v2(request["signals"], request["quotes"], request["envelope"], request["source_set"])
        elif args.command == "qualify-economics":
            _exact_keys(request, {"price_dataset", "funding_dataset", "qualification_policy_sha256"}, "qualify-economics request")
            result = build_economics_qualification_v2(
                request["price_dataset"], request["funding_dataset"],
                qualification_policy_sha256=request["qualification_policy_sha256"],
            )
        elif args.command == "settlement-coverage":
            _exact_keys(request, {"held_intervals", "settlements"}, "settlement-coverage request")
            result = build_settlement_coverage_v2(request["held_intervals"], request["settlements"])
        elif args.command == "availability":
            allowed = {"frozen_universe", "records", "source_set", "policy_sha256", "minimum_names_by_leg"}
            if set(request) - allowed or not {"frozen_universe", "records", "source_set", "policy_sha256"}.issubset(request):
                raise EconomicsV2Error("availability request has unsupported shape")
            result = build_universe_availability_v2(
                request["frozen_universe"], request["records"], source_set=request["source_set"],
                policy_sha256=request["policy_sha256"], minimum_names_by_leg=request.get("minimum_names_by_leg"),
            )
        elif args.command == "calibrate-nautilus":
            _exact_keys(request, {"fixture", "wheel_path"}, "calibrate-nautilus request")
            result = run_nautilus_economic_calibration_v2(request["fixture"], wheel_path=request["wheel_path"])
        else:
            allowed = {"fixture", "engine_spec", "engine_output"}
            if set(request) - allowed or not {"fixture", "engine_spec"}.issubset(request):
                raise EconomicsV2Error("calibrate request has unsupported shape")
            if "engine_output" in request:
                result = compare_external_engine_calibration_v2(request["fixture"], request["engine_spec"], request["engine_output"])
            else:
                result = build_not_calibrated_external_engine_report_v2(
                    request["fixture"], request["engine_spec"], reason="no_external_engine_output_or_runner_supplied"
                )
        _emit(result, args.output)
        return 0
    except (EconomicsV2Error, ContractValidationError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INVALID", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
