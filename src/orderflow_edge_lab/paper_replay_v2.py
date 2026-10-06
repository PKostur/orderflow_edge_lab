"""Offline, opt-in v2 crypto paper-replay coverage and immutable bundle support.

This successor intentionally does not import or alter :mod:`paper_account`.  It
accepts already acquired, normalized JSON input snapshots only; it performs no
network access, collection, scheduling, credential use, or order transmission.
Missing held-interval marks/funding are ``DATA_GAP``, while an explicitly
observed funding rate of ``0.0`` remains an ordinary observed value.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from orderflow_edge_lab.contracts_v2 import (
    CLOSED_OPEN,
    ContractValidationError,
    build_coverage_result,
    build_manifest_result,
    build_utc_interval,
    canonical_json_bytes,
    canonical_json_sha256,
    missing_value,
    non_authority_claims,
    observed_value,
    validate_canonical_source_set,
    validate_coverage_result,
    validate_manifest_result,
)

UTC = timezone.utc
REPLAY_SCHEMA = "orderflow_edge_lab.paper_replay_bundle.v2"
COVERAGE_ANALYSIS = "paper_market_coverage_v2"
BUNDLE_ANALYSIS = "paper_replay_bundle_v2"
_HEX = frozenset("0123456789abcdef")


class PaperReplayV2Error(ValueError):
    """Raised when a replay-v2 input or frozen bundle is ambiguous or malformed."""


def _json_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise PaperReplayV2Error(f"{field} must be a JSON object")
    try:
        return json.loads(canonical_json_bytes(dict(value)).decode("utf-8"))
    except ContractValidationError as exc:
        raise PaperReplayV2Error(f"{field} is not canonical JSON") from exc


def _snapshot_mapping(value: object, field: str) -> dict[str, Any]:
    """Make a JSON-safe snapshot while preserving nonfinite data as invalid nulls.

    A provider/parser can hand an API caller a Python ``NaN`` even though that is
    not JSON.  For the coverage gate, retaining a local normalized ``null`` and
    emitting ``invalid_mark``/``invalid_funding`` is safer than raising before a
    caller receives a non-reportable ``DATA_GAP``.  The original raw bytes remain
    caller-bound by the source set; no NaN can enter the frozen bundle itself.
    """

    def sanitize(item: object) -> object:
        if item is None or isinstance(item, (str, bool)) or type(item) is int:
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else None
        if isinstance(item, list):
            return [sanitize(child) for child in item]
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise PaperReplayV2Error(f"{field} has a non-string key")
            return {key: sanitize(child) for key, child in item.items()}
        raise PaperReplayV2Error(f"{field} is not a JSON-shaped value")

    sanitized = sanitize(value)
    if not isinstance(sanitized, dict):
        raise PaperReplayV2Error(f"{field} must be a JSON object")
    return json.loads(canonical_json_bytes(sanitized).decode("utf-8"))


def _finite_number(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PaperReplayV2Error(f"{field} must be finite")
    result = float(value)
    if positive and result <= 0:
        raise PaperReplayV2Error(f"{field} must be positive")
    return result


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in _HEX for char in value.lower()):
        raise PaperReplayV2Error(f"{field} must be a SHA-256")
    return value.lower()


def _utc(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PaperReplayV2Error(f"{field} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaperReplayV2Error(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperReplayV2Error(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sync_parent(path: Path) -> None:
    if os.name == "posix":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _normalise_inputs(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the prospective v2 replay input shape without inferring a schedule.

    ``funding_expectations`` is deliberately caller declared.  The module never
    assumes an exchange cadence or substitutes a missing settlement with zero.
    Target timestamps are the caller-declared rebalance/08:00 mark timestamps.
    """

    raw = _snapshot_mapping(value, "replay_inputs")
    required = {
        "config", "targets", "marks", "funding", "funding_expectations", "specs", "coverage_policy_sha256"
    }
    if set(raw) != required:
        raise PaperReplayV2Error("replay_inputs has unsupported shape")
    config = _json_mapping(raw["config"], "config")
    required_config = {"initial_equity", "start_utc", "as_of_utc", "slippage", "min_fee", "collection_failures"}
    if set(config) != required_config:
        raise PaperReplayV2Error("config has unsupported shape")
    normalized_config = {
        "initial_equity": _finite_number(config["initial_equity"], "config.initial_equity", positive=True),
        "start_utc": _utc(config["start_utc"], "config.start_utc"),
        "as_of_utc": _utc(config["as_of_utc"], "config.as_of_utc"),
        "slippage": _finite_number(config["slippage"], "config.slippage"),
        "min_fee": _finite_number(config["min_fee"], "config.min_fee"),
        "collection_failures": config["collection_failures"],
    }
    if normalized_config["slippage"] < 0 or normalized_config["min_fee"] < 0:
        raise PaperReplayV2Error("config costs cannot be negative")
    if not isinstance(config["collection_failures"], list) or any(
        not isinstance(item, str) or not item.strip() for item in config["collection_failures"]
    ):
        raise PaperReplayV2Error("config.collection_failures must be an array of nonempty strings")
    if normalized_config["as_of_utc"] <= normalized_config["start_utc"]:
        raise PaperReplayV2Error("config.as_of_utc must be after config.start_utc")
    if not all(isinstance(raw[key], list) for key in ("targets", "marks", "funding", "funding_expectations")):
        raise PaperReplayV2Error("targets, marks, funding, and funding_expectations must be arrays")
    if not raw["targets"]:
        raise PaperReplayV2Error("targets must not be empty")
    if not isinstance(raw["specs"], Mapping) or not raw["specs"]:
        raise PaperReplayV2Error("specs must be a nonempty object")
    return {
        "config": normalized_config,
        "targets": raw["targets"],
        "marks": raw["marks"],
        "funding": raw["funding"],
        "funding_expectations": raw["funding_expectations"],
        "specs": _json_mapping(raw["specs"], "specs"),
        "coverage_policy_sha256": _sha256(raw["coverage_policy_sha256"], "coverage_policy_sha256"),
    }


def _normalise_targets(rows: list[Any]) -> tuple[dict[str, dict[str, float]], list[str], list[str]]:
    by_time: dict[str, dict[str, float]] = {}
    symbols: set[str] = set()
    issues: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"timestamp", "symbol", "weight"}:
            raise PaperReplayV2Error(f"targets[{index}] has unsupported shape")
        timestamp = _utc(row["timestamp"], f"targets[{index}].timestamp")
        symbol = row["symbol"]
        if not isinstance(symbol, str) or not symbol:
            raise PaperReplayV2Error(f"targets[{index}].symbol must be nonempty")
        weight = _finite_number(row["weight"], f"targets[{index}].weight")
        if symbol in by_time.setdefault(timestamp, {}):
            issues.append(f"duplicate_target:{symbol}:{timestamp}")
        by_time[timestamp][symbol] = weight
        symbols.add(symbol)
    return by_time, sorted(symbols), sorted(issues)


def _normalise_marks(rows: list[Any]) -> tuple[dict[tuple[str, str], float], set[tuple[str, str]], list[str]]:
    values: dict[tuple[str, str], float] = {}
    duplicates: set[tuple[str, str]] = set()
    issues: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"timestamp", "symbol", "price"}:
            raise PaperReplayV2Error(f"marks[{index}] has unsupported shape")
        timestamp = _utc(row["timestamp"], f"marks[{index}].timestamp")
        symbol = row["symbol"]
        if not isinstance(symbol, str) or not symbol:
            raise PaperReplayV2Error(f"marks[{index}].symbol must be nonempty")
        key = (symbol, timestamp)
        if key in values:
            duplicates.add(key)
            issues.append(f"duplicate_mark:{symbol}:{timestamp}")
            continue
        try:
            values[key] = _finite_number(row["price"], f"marks[{index}].price", positive=True)
        except PaperReplayV2Error:
            issues.append(f"invalid_mark:{symbol}:{timestamp}")
    return values, duplicates, sorted(issues)


def _normalise_funding(rows: list[Any]) -> tuple[dict[tuple[str, str], float], set[tuple[str, str]], list[str]]:
    values: dict[tuple[str, str], float] = {}
    duplicates: set[tuple[str, str]] = set()
    issues: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"timestamp", "symbol", "rate"}:
            raise PaperReplayV2Error(f"funding[{index}] has unsupported shape")
        timestamp = _utc(row["timestamp"], f"funding[{index}].timestamp")
        symbol = row["symbol"]
        if not isinstance(symbol, str) or not symbol:
            raise PaperReplayV2Error(f"funding[{index}].symbol must be nonempty")
        key = (symbol, timestamp)
        if key in values:
            duplicates.add(key)
            issues.append(f"duplicate_funding:{symbol}:{timestamp}")
            continue
        try:
            # A finite exact 0.0 is intentionally accepted and stored as observed.
            values[key] = _finite_number(row["rate"], f"funding[{index}].rate")
        except PaperReplayV2Error:
            issues.append(f"invalid_funding:{symbol}:{timestamp}")
    return values, duplicates, sorted(issues)


def _normalise_expectations(rows: list[Any]) -> tuple[dict[str, list[str]], set[tuple[str, str]], list[str]]:
    expected: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    duplicates: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"timestamp", "symbol"}:
            raise PaperReplayV2Error(f"funding_expectations[{index}] has unsupported shape")
        timestamp = _utc(row["timestamp"], f"funding_expectations[{index}].timestamp")
        symbol = row["symbol"]
        if not isinstance(symbol, str) or not symbol:
            raise PaperReplayV2Error(f"funding_expectations[{index}].symbol must be nonempty")
        key = (symbol, timestamp)
        if key in seen:
            duplicates.add(key)
            # Retain a single expected observation.  The duplicate remains a
            # coverage-visible input issue rather than making the generic
            # coverage builder fail for duplicate observation IDs.
            continue
        seen.add(key)
        expected.setdefault(symbol, []).append(timestamp)
    for symbol in expected:
        expected[symbol].sort()
    return expected, duplicates, [f"duplicate_funding_expectation:{s}:{t}" for s, t in sorted(duplicates)]


def _normalise_specs(raw: Mapping[str, Any]) -> tuple[dict[str, dict[str, float | int]], list[str]]:
    specs: dict[str, dict[str, float | int]] = {}
    issues: list[str] = []
    for symbol, spec in raw.items():
        if not isinstance(symbol, str) or not symbol or not isinstance(spec, Mapping):
            raise PaperReplayV2Error("specs must map nonempty symbols to objects")
        if set(spec) != {"contract_size", "min_contracts", "taker_fee_rate"}:
            raise PaperReplayV2Error(f"specs.{symbol} has unsupported shape")
        contract_size = _finite_number(spec["contract_size"], f"specs.{symbol}.contract_size", positive=True)
        fee = _finite_number(spec["taker_fee_rate"], f"specs.{symbol}.taker_fee_rate")
        minimum = spec["min_contracts"]
        if type(minimum) is not int or minimum < 1 or fee < 0:
            issues.append(f"invalid_spec:{symbol}")
            continue
        specs[symbol] = {"contract_size": contract_size, "min_contracts": minimum, "taker_fee_rate": fee}
    return specs, sorted(issues)


def _coverage_parts(inputs: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = _normalise_inputs(inputs)
    targets, symbols, target_issues = _normalise_targets(normalized["targets"])
    marks, mark_duplicates, mark_issues = _normalise_marks(normalized["marks"])
    funding, funding_duplicates, funding_issues = _normalise_funding(normalized["funding"])
    expected, expectation_duplicates, expectation_issues = _normalise_expectations(normalized["funding_expectations"])
    specs, spec_issues = _normalise_specs(normalized["specs"])
    times = [time for time in sorted(targets) if normalized["config"]["start_utc"] <= time <= normalized["config"]["as_of_utc"]]
    if not times:
        raise PaperReplayV2Error("no target timestamp falls in declared replay interval")

    observations: list[dict[str, Any]] = []
    issues = target_issues + mark_issues + funding_issues + expectation_issues + spec_issues
    # This is deliberately conservative: a nonzero target requires its 08:00 mark,
    # even if subsequent lot rounding would turn it into zero contracts.
    previously_targeted: set[str] = set()
    for offset, timestamp in enumerate(times):
        target_symbols = {symbol for symbol in symbols if targets[timestamp].get(symbol, 0.0) != 0.0}
        required_marks = target_symbols | previously_targeted
        for symbol in sorted(required_marks):
            observation_id = f"mark:{symbol}:{timestamp}"
            key = (symbol, timestamp)
            if symbol not in specs:
                observations.append({"observation_id": observation_id, "observation": missing_value("missing_or_invalid_spec")})
                continue
            if key in mark_duplicates:
                observations.append({"observation_id": observation_id, "observation": missing_value("duplicate_mark")})
            elif key not in marks:
                observations.append({"observation_id": observation_id, "observation": missing_value("missing_mark")})
            else:
                observations.append({"observation_id": observation_id, "observation": observed_value(marks[key])})
        if offset:
            previous = times[offset - 1]
            for symbol in sorted(previously_targeted):
                scheduled = [stamp for stamp in expected.get(symbol, []) if previous < stamp <= timestamp]
                if not scheduled:
                    observations.append({
                        "observation_id": f"funding_schedule:{symbol}:{previous}:{timestamp}",
                        "observation": missing_value("funding_schedule_not_declared"),
                    })
                for settlement in scheduled:
                    observation_id = f"funding:{symbol}:{settlement}"
                    key = (symbol, settlement)
                    if key in funding_duplicates or key in expectation_duplicates:
                        observations.append({"observation_id": observation_id, "observation": missing_value("duplicate_funding")})
                    elif key not in funding:
                        observations.append({"observation_id": observation_id, "observation": missing_value("missing_funding")})
                    else:
                        observations.append({"observation_id": observation_id, "observation": observed_value(funding[key])})
        previously_targeted = target_symbols

    # A malformed duplicate target must have a coverage-visible missing observation.
    if previously_targeted and times[-1] < normalized["config"]["as_of_utc"]:
        for symbol in sorted(previously_targeted):
            observations.append({
                "observation_id": f"terminal_held_interval:{symbol}:{times[-1]}:{normalized['config']['as_of_utc']}",
                "observation": missing_value("explicit_terminal_target_and_held_interval_coverage_required"),
            })
    if not observations and not issues:
        observations.append({"observation_id": "no_held_market_exposure", "observation": observed_value(1)})
    for issue in issues:
        observations.append({"observation_id": f"input_issue:{issue}", "observation": missing_value(issue)})
    interval = build_utc_interval(
        normalized["config"]["start_utc"], normalized["config"]["as_of_utc"], convention=CLOSED_OPEN
    )
    coverage = build_coverage_result("paper_replay_held_interval_market_funding_v2", interval, observations)
    details = {
        "normalized_inputs": normalized,
        "targets": targets,
        "symbols": symbols,
        "marks": marks,
        "funding": funding,
        "expected": expected,
        "specs": specs,
        "times": times,
        "issues": sorted(issues),
    }
    return coverage, details


def validate_paper_market_coverage_v2(replay_inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Return a hash-bound coverage result for held crypto replay intervals.

    A status of ``DATA_GAP`` is not a normal replay/report outcome.  The returned
    coverage retains every missing ID and reason so a caller can repair a saved
    input snapshot without guessing whether a genuine zero was observed.
    """

    coverage, details = _coverage_parts(replay_inputs)
    return {
        "schema": "orderflow_edge_lab.paper_market_coverage.v2",
        "analysis": COVERAGE_ANALYSIS,
        "status": "COMPLETE" if coverage["status"] == "COMPLETE" else "DATA_GAP",
        "coverage": coverage,
        "input_issues": details["issues"],
        "coverage_policy_sha256": details["normalized_inputs"]["coverage_policy_sha256"],
        "non_authority_claims": non_authority_claims(),
    }


def validate_approval_terms_v2(terms: Mapping[str, Any]) -> dict[str, Any]:
    """Expose the stage's manual approval-terms contract without legacy rewrites.

    The implementation lives with the approval-bound engine successor.  A lazy
    import keeps crypto bundle construction independent of manual-engine state.
    """

    from orderflow_edge_lab.paper_execution_v2 import validate_approval_terms_v2 as validate_terms

    return validate_terms(terms)


def _contracts_for(weight: float, equity: float, price: float, spec: Mapping[str, float | int]) -> int:
    if weight == 0.0:
        return 0
    quantity = int(round(weight * equity / (price * float(spec["contract_size"]))))
    return 0 if abs(quantity) < int(spec["min_contracts"]) else quantity


def _simulate(details: Mapping[str, Any], coverage: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = details["normalized_inputs"]["config"]
    symbols = details["symbols"]
    marks = details["marks"]
    funding = details["funding"]
    specs = details["specs"]
    targets = details["targets"]
    expected = details["expected"]
    times = details["times"]
    equity = float(config["initial_equity"])
    quantity = {symbol: 0 for symbol in symbols}
    totals = {"fees": 0.0, "funding": 0.0, "traded_notional": 0.0, "mark_pnl": 0.0}
    lifecycle: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []

    for offset, timestamp in enumerate(times):
        if offset:
            previous = times[offset - 1]
            mark_pnl = 0.0
            mark_rows = []
            for symbol in symbols:
                held = quantity[symbol]
                if not held:
                    continue
                prior_price = marks[(symbol, previous)]
                current_price = marks[(symbol, timestamp)]
                pnl = held * float(specs[symbol]["contract_size"]) * (current_price - prior_price)
                mark_pnl += pnl
                mark_rows.append({"symbol": symbol, "contracts": held, "previous_mark": prior_price,
                                  "current_mark": current_price, "pnl": pnl})
            equity += mark_pnl
            totals["mark_pnl"] += mark_pnl
            lifecycle.append({"event_type": "interval_mark", "timestamp": timestamp,
                              "from_timestamp": previous, "marks": mark_rows, "pnl": mark_pnl,
                              "equity_after": equity})
            funding_total = 0.0
            funding_rows = []
            for symbol in symbols:
                held = quantity[symbol]
                if not held:
                    continue
                for settlement in [stamp for stamp in expected.get(symbol, []) if previous < stamp <= timestamp]:
                    rate = funding[(symbol, settlement)]
                    cashflow = -held * float(specs[symbol]["contract_size"]) * marks[(symbol, previous)] * rate
                    funding_total += cashflow
                    funding_rows.append({"symbol": symbol, "settlement_timestamp": settlement, "contracts": held,
                                         "rate": rate, "reference_mark": marks[(symbol, previous)], "cashflow": cashflow})
            equity += funding_total
            totals["funding"] += funding_total
            lifecycle.append({"event_type": "funding_settlement", "timestamp": timestamp,
                              "from_timestamp": previous, "settlements": funding_rows, "cashflow": funding_total,
                              "equity_after": equity})

        fills = []
        fees = 0.0
        notional = 0.0
        for symbol in symbols:
            price = marks[(symbol, timestamp)] if (symbol, timestamp) in marks else None
            desired = _contracts_for(targets[timestamp].get(symbol, 0.0), equity, price, specs[symbol]) if price else 0
            delta = desired - quantity[symbol]
            if delta:
                trade_notional = abs(delta) * float(specs[symbol]["contract_size"]) * float(price)
                fee_rate = max(float(specs[symbol]["taker_fee_rate"]), float(config["min_fee"])) + float(config["slippage"])
                fee = trade_notional * fee_rate
                equity -= fee
                fees += fee
                notional += trade_notional
                fills.append({"symbol": symbol, "old_contracts": quantity[symbol], "new_contracts": desired,
                              "delta_contracts": delta, "mark": price, "notional": trade_notional,
                              "fee_rate": fee_rate, "fee": fee})
                quantity[symbol] = desired
        totals["fees"] += fees
        totals["traded_notional"] += notional
        lifecycle.append({"event_type": "rebalance_fill", "timestamp": timestamp, "targets": {
            symbol: targets[timestamp].get(symbol, 0.0) for symbol in symbols}, "fills": fills, "fees": fees,
            "traded_notional": notional, "equity_after": equity})
        curve.append({"timestamp": timestamp, "equity": equity})

    final_time = times[-1]
    positions = [
        {"symbol": symbol, "contracts": quantity[symbol], "mark": marks[(symbol, final_time)],
         "notional": quantity[symbol] * float(specs[symbol]["contract_size"]) * marks[(symbol, final_time)]}
        for symbol in symbols if quantity[symbol]
    ]
    positions.sort(key=lambda row: (-abs(float(row["notional"])), str(row["symbol"])))
    summary = {
        "status": "COMPLETE",
        "days": len(times),
        "initial_equity": float(config["initial_equity"]),
        "ending_equity": equity,
        "curve": curve,
        "positions": positions,
        "gross_exposure": sum(abs(float(row["notional"])) for row in positions),
        "totals": totals,
        "coverage_sha256": coverage["coverage_sha256"],
    }
    return lifecycle, summary


def _input_hashes(inputs: Mapping[str, Any]) -> dict[str, str]:
    return {key: canonical_json_sha256(inputs[key]) for key in sorted(inputs)}


def build_replay_bundle_v2(replay_inputs: Mapping[str, Any], source_set: Mapping[str, Any]) -> dict[str, Any]:
    """Build an immutable, replayable v2 bundle from pre-acquired normalized data.

    The result embeds frozen input snapshots and a complete self-financing
    mark/funding/fill lifecycle.  Collection failures and coverage gaps produce
    an incomplete bundle with *no performance summary*.
    """

    coverage, details = _coverage_parts(replay_inputs)
    inputs = details["normalized_inputs"]
    sources = validate_canonical_source_set(source_set)
    collection_failures = list(inputs["config"]["collection_failures"])
    if collection_failures:
        status = "INCOMPLETE_INPUT"
    elif coverage["status"] != "COMPLETE":
        status = "DATA_GAP"
    else:
        status = "COMPLETE"
    lifecycle: list[dict[str, Any]] = []
    summary: dict[str, Any] | None = None
    if status == "COMPLETE":
        lifecycle, summary = _simulate(details, coverage)
    manifest = build_manifest_result(
        BUNDLE_ANALYSIS,
        sources,
        "COMPLETE" if status == "COMPLETE" else "INCOMPLETE",
        coverage=coverage,
        policy_sha256=inputs["coverage_policy_sha256"],
        attributes={"replay_status": status, "collection_failures": collection_failures},
    )
    unsigned = {
        "schema": REPLAY_SCHEMA,
        "analysis": BUNDLE_ANALYSIS,
        "status": status,
        "source_set": sources,
        "coverage": coverage,
        "coverage_policy_sha256": inputs["coverage_policy_sha256"],
        "input_snapshot": inputs,
        "input_hashes": _input_hashes(inputs),
        "collection_failures": collection_failures,
        "lifecycle": lifecycle,
        "lifecycle_sha256": canonical_json_sha256(lifecycle),
        "summary": summary,
        "manifest": manifest,
        "non_authority_claims": non_authority_claims(),
    }
    return {**unsigned, "bundle_sha256": canonical_json_sha256(unsigned)}


def validate_replay_bundle_v2(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Read-only validation and deterministic replay of a saved v2 bundle."""

    raw = _json_mapping(bundle, "bundle")
    expected = {
        "schema", "analysis", "status", "source_set", "coverage", "coverage_policy_sha256", "input_snapshot",
        "input_hashes", "collection_failures", "lifecycle", "lifecycle_sha256", "summary", "manifest",
        "non_authority_claims", "bundle_sha256",
    }
    if set(raw) != expected or raw.get("schema") != REPLAY_SCHEMA or raw.get("analysis") != BUNDLE_ANALYSIS:
        raise PaperReplayV2Error("bundle has unsupported shape or schema")
    sources = validate_canonical_source_set(raw["source_set"])
    coverage = validate_coverage_result(raw["coverage"])
    # The builder is the authoritative deterministic recomputation.  It also validates
    # all cached hashes, lifecycle totals, coverage and normal-report suppression.
    rebuilt = build_replay_bundle_v2(raw["input_snapshot"], sources)
    if canonical_json_bytes(raw) != canonical_json_bytes(rebuilt):
        raise PaperReplayV2Error("bundle mutation or deterministic replay mismatch")
    if raw["bundle_sha256"] != canonical_json_sha256({key: raw[key] for key in raw if key != "bundle_sha256"}):
        raise PaperReplayV2Error("bundle_sha256 mismatch")
    if raw["lifecycle_sha256"] != canonical_json_sha256(raw["lifecycle"]):
        raise PaperReplayV2Error("lifecycle_sha256 mismatch")
    validate_manifest_result(raw["manifest"])
    return rebuilt


def write_replay_bundle_v2(path: str | Path, bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Exclusive-create a verified local bundle; existing artifacts are never replaced."""

    normalized = validate_replay_bundle_v2(bundle)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(normalized) + b"\n"
    with target.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_parent(target)
    return {"path": str(target), "size_bytes": len(payload), "bundle_sha256": normalized["bundle_sha256"]}


def verify_replay_bundle_file_v2(path: str | Path) -> dict[str, Any]:
    """Verify an immutable local bundle without writing it or contacting a provider."""

    target = Path(path)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        bundle = validate_replay_bundle_v2(data)
    except (OSError, json.JSONDecodeError, PaperReplayV2Error, ContractValidationError) as exc:
        return {
            "schema": "orderflow_edge_lab.paper_replay_verification.v2",
            "status": "INVALID",
            "path": str(target),
            "error": f"{type(exc).__name__}: {exc}",
            "non_authority_claims": non_authority_claims(),
        }
    return {
        "schema": "orderflow_edge_lab.paper_replay_verification.v2",
        "status": "VERIFIED_LOCAL_REPLAY",
        "path": str(target),
        "bundle_sha256": bundle["bundle_sha256"],
        "replay_status": bundle["status"],
        "summary": bundle["summary"],
        "verification_scope": "local_frozen_bytes_and_deterministic_offline_replay_only",
        "non_authority_claims": non_authority_claims(),
    }


def _load_object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperReplayV2Error(f"cannot read JSON from {path}") from exc
    return _json_mapping(value, path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the offline replay-v2 developer CLI (not a collector or live path)."""

    parser = argparse.ArgumentParser(description="Offline v2 paper replay coverage and immutable-bundle tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    coverage_parser = commands.add_parser("coverage", help="validate held-interval marks/funding without replaying")
    coverage_parser.add_argument("--inputs", required=True)
    build_parser = commands.add_parser("build-bundle", help="build an exclusive immutable offline replay bundle")
    build_parser.add_argument("--inputs", required=True)
    build_parser.add_argument("--source-set", required=True)
    build_parser.add_argument("--output", required=True)
    verify_parser = commands.add_parser("verify-bundle", help="read-only verify a saved replay bundle")
    verify_parser.add_argument("--bundle", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "coverage":
            result = validate_paper_market_coverage_v2(_load_object(args.inputs))
            print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
            return 0 if result["status"] == "COMPLETE" else 2
        if args.command == "build-bundle":
            bundle = build_replay_bundle_v2(_load_object(args.inputs), _load_object(args.source_set))
            result = write_replay_bundle_v2(args.output, bundle)
            result["status"] = bundle["status"]
            print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
            return 0 if bundle["status"] == "COMPLETE" else 2
        result = verify_replay_bundle_file_v2(args.bundle)
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0 if result["status"] == "VERIFIED_LOCAL_REPLAY" else 2
    except (PaperReplayV2Error, ContractValidationError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "INVALID", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
