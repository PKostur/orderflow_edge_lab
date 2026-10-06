"""Development-only event candidates with causal next-quote fills.

This module is deliberately separate from frozen strategy definitions.  It accepts a
local point-in-time JSONL export only, has no networking or order-routing code, and
labels every result as development-only.  The two candidates test distinct dynamic
microstructure mechanisms while reporting their signal overlap as a redundancy
warning rather than selecting a winner by backtest return.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .adapters import attach_prior_bbo
from .data import MarketEvent, Side, normalize_rows

UTC = timezone.utc
NANOSECONDS = 1_000_000_000


class DevelopmentCandidateError(ValueError):
    """Raised when point-in-time data or trial controls are not trustworthy."""


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DevelopmentCandidateError("timestamp must be a nonempty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DevelopmentCandidateError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise DevelopmentCandidateError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _iso_ns(value: int) -> str:
    return datetime.fromtimestamp(value / NANOSECONDS, tz=UTC).isoformat()


def _timestamp_ns_as_iso(value: int) -> str:
    """Represent an integer nanosecond clock without epoch-unit inference."""

    seconds, nanoseconds = divmod(value, NANOSECONDS)
    base = datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{nanoseconds:09d}+00:00"


def _finite_positive(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise DevelopmentCandidateError(f"{field} must be a finite positive number")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise DevelopmentCandidateError(f"{field} must be a finite positive number") from exc
    if not math.isfinite(out) or out <= 0.0:
        raise DevelopmentCandidateError(f"{field} must be a finite positive number")
    return out


def _integer_ns(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise DevelopmentCandidateError(f"{field} must be a positive integer")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise DevelopmentCandidateError(f"{field} must be a positive integer") from exc
    if str(value).strip() != str(out) or out <= 0:
        raise DevelopmentCandidateError(f"{field} must be a positive integer")
    return out


@dataclass(frozen=True)
class Quote:
    """A valid displayed BBO from a quote record in observed-data order."""

    ts_ns: int
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_fraction(self) -> float:
        return (self.ask - self.bid) / self.mid


@dataclass(frozen=True)
class Signal:
    candidate_id: str
    side: int
    ts_ns: int
    reason: str


def _load_json_object(path: str | Path, description: str) -> tuple[bytes, dict[str, Any]]:
    target = Path(path)
    try:
        raw = target.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise DevelopmentCandidateError(f"cannot read {description}: {target}") from exc
    if not isinstance(payload, dict):
        raise DevelopmentCandidateError(f"{description} must be a JSON object")
    return raw, payload


def load_candidate_catalog(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    """Load and validate the additive candidate catalog before any data are read."""

    raw, catalog = _load_json_object(path, "candidate catalog")
    if catalog.get("schema_version") != 1:
        raise DevelopmentCandidateError("candidate catalog schema_version must be 1")
    candidates = catalog.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise DevelopmentCandidateError("candidate catalog must contain candidates")
    ids: set[str] = set()
    known = {"impact_absorption_reversal", "spread_shock_resolution_continuation"}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise DevelopmentCandidateError("candidate catalog contains a non-object candidate")
        candidate_id = candidate.get("candidate_id")
        mechanism = candidate.get("mechanism")
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in ids:
            raise DevelopmentCandidateError("candidate IDs must be nonempty and unique")
        if mechanism not in known:
            raise DevelopmentCandidateError(f"unsupported candidate mechanism: {mechanism}")
        ids.add(candidate_id)
        execution = candidate.get("execution")
        if not isinstance(execution, dict):
            raise DevelopmentCandidateError(f"{candidate_id}: execution must be an object")
        for field in ("decision_latency_ms", "outcome_horizon_ms"):
            if not isinstance(execution.get(field), int) or execution[field] <= 0:
                raise DevelopmentCandidateError(f"{candidate_id}: {field} must be a positive integer")
        for field in ("round_trip_fee_bps", "round_trip_slippage_bps"):
            value = execution.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
                raise DevelopmentCandidateError(f"{candidate_id}: {field} must be finite and strictly positive")
    return raw, catalog


def _catalog_candidates(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = catalog.get("candidates")
    if not isinstance(candidates, list):
        raise DevelopmentCandidateError("candidate catalog has no candidate list")
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]


def build_candidate_spec_freeze(
    catalog_path: str | Path,
    *,
    candidate_ids: Sequence[str] | None = None,
    frozen_at: str,
) -> dict[str, Any]:
    """Create a hash-pinned candidate-specification freeze, not a performance claim.

    The output deliberately does not assign a future-data boundary.  A later
    research-freeze and holdout audit are still required for out-of-sample claims.
    """

    raw, catalog = load_candidate_catalog(catalog_path)
    timestamp = _parse_utc(frozen_at)
    candidates = _catalog_candidates(catalog)
    by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    if candidate_ids is None:
        selected = sorted(by_id)
    else:
        selected = sorted(set(candidate_ids))
        if not selected or len(selected) != len(candidate_ids) or any(candidate_id not in by_id for candidate_id in selected):
            raise DevelopmentCandidateError("candidate_ids must be unique catalog IDs")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "freeze_kind": "development_candidate_specification_only",
        "created_at": timestamp.isoformat(),
        "catalog": {"path": str(Path(catalog_path).resolve()), "sha256": _sha256_bytes(raw)},
        "candidates": [
            {"candidate_id": candidate_id, "spec_sha256": _canonical_sha256(by_id[candidate_id])}
            for candidate_id in selected
        ],
        "constraints": [
            "This freeze is a rule-definition freeze only, not a future-data or holdout freeze.",
            "Every evaluation must use observed_at_ns ordering and next-quote bid/ask fills.",
            "Every attempted candidate evaluation must be appended to the development trial ledger.",
            "A successful development result cannot establish profitability or authorize paper/live execution.",
        ],
        "claims": {
            "candidate_specification_frozen": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def verify_candidate_spec_freeze(manifest: Mapping[str, Any], catalog_path: str | Path | None = None) -> bool:
    """Verify internal integrity and, when available, the referenced catalog bytes."""

    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
        return False
    expected = manifest.get("manifest_sha256")
    if not _is_sha256(expected):
        return False
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    if _canonical_sha256(unsigned) != expected:
        return False
    catalog = manifest.get("catalog")
    candidates = manifest.get("candidates")
    claims = manifest.get("claims")
    if not isinstance(catalog, Mapping) or not _is_sha256(catalog.get("sha256")) or not isinstance(candidates, list) or not candidates:
        return False
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("candidate_id"), str):
            return False
        if candidate["candidate_id"] in seen or not _is_sha256(candidate.get("spec_sha256")):
            return False
        seen.add(candidate["candidate_id"])
    if not isinstance(claims, Mapping) or claims.get("candidate_specification_frozen") is not True:
        return False
    if any(claims.get(key) is not False for key in ("verified_out_of_sample_evidence", "profitable_edge_established", "live_order_transmission_supported")):
        return False
    if catalog_path is None:
        return True
    try:
        raw, payload = load_candidate_catalog(catalog_path)
    except DevelopmentCandidateError:
        return False
    if _sha256_bytes(raw) != catalog.get("sha256"):
        return False
    by_id = {str(candidate["candidate_id"]): candidate for candidate in _catalog_candidates(payload)}
    return all(
        candidate["candidate_id"] in by_id
        and _canonical_sha256(by_id[candidate["candidate_id"]]) == candidate["spec_sha256"]
        for candidate in candidates
    )


def load_point_in_time_jsonl(path: str | Path) -> tuple[list[MarketEvent], list[Quote]]:
    """Load a documented local JSONL schema through the existing causal adapter.

    ``observed_at_ns`` is the only ordering clock.  Source/exchange timestamps
    are intentionally ignored.  Quotes must be complete, and raw records must be
    strictly increasing so equal-time quote/trade ordering cannot create lookahead.
    """

    source_path = Path(path)
    rows: list[dict[str, Any]] = []
    last_observed: int | None = None
    try:
        handle = source_path.open("r", encoding="utf-8")
    except OSError as exc:
        raise DevelopmentCandidateError(f"cannot read point-in-time input: {source_path}") from exc
    with handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DevelopmentCandidateError(f"input line {line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise DevelopmentCandidateError(f"input line {line_number}: record must be an object")
            observed = _integer_ns(row.get("observed_at_ns"), "observed_at_ns")
            if last_observed is not None and observed <= last_observed:
                raise DevelopmentCandidateError("observed_at_ns must be strictly increasing; same-time ordering is ambiguous")
            last_observed = observed
            event_type = str(row.get("event_type", "")).lower()
            if event_type not in {"quote", "trade"}:
                raise DevelopmentCandidateError(f"input line {line_number}: event_type must be quote or trade")
            if not isinstance(row.get("symbol"), str) or not row["symbol"].strip():
                raise DevelopmentCandidateError(f"input line {line_number}: symbol is required")
            if event_type == "quote":
                bid = _finite_positive(row.get("bid"), "bid")
                ask = _finite_positive(row.get("ask"), "ask")
                if bid >= ask:
                    raise DevelopmentCandidateError(f"input line {line_number}: quote must have bid < ask")
            else:
                _finite_positive(row.get("price"), "price")
                _finite_positive(row.get("size"), "size")
            adapted = dict(row)
            adapted["timestamp"] = _timestamp_ns_as_iso(observed)
            adapted["kind"] = event_type.upper()
            rows.append(adapted)
    if not rows:
        raise DevelopmentCandidateError("point-in-time input is empty")
    try:
        bare = normalize_rows(rows, source="development_point_in_time_jsonl", enrich_prior_bbo=False)
        adapted = list(attach_prior_bbo(bare, max_quote_age_seconds=2.0, reject_timestamp_regressions=True).events)
    except ValueError as exc:
        raise DevelopmentCandidateError(f"point-in-time adapter rejected input: {exc}") from exc
    symbols = {event.symbol for event in adapted}
    if len(symbols) != 1:
        raise DevelopmentCandidateError("input must contain exactly one symbol; mixed-symbol BBO histories are not admissible")
    quotes = [Quote(event.ts_ns, float(event.bid), float(event.ask)) for event in adapted if event.kind == "QUOTE"]
    if not quotes:
        raise DevelopmentCandidateError("input has no complete quote records; next-event fills cannot be evaluated")
    return adapted, quotes


def load_input_manifest(path: str | Path, input_path: str | Path) -> tuple[bytes, dict[str, Any]]:
    """Verify byte identity and the no-lookahead point-in-time declaration."""

    raw, manifest = _load_json_object(path, "input manifest")
    if manifest.get("schema_version") != 1:
        raise DevelopmentCandidateError("input manifest schema_version must be 1")
    source_hash = manifest.get("source_sha256")
    if not _is_sha256(source_hash) or _sha256_bytes(Path(input_path).read_bytes()) != source_hash:
        raise DevelopmentCandidateError("input manifest source_sha256 does not match input bytes")
    if manifest.get("point_in_time_clock") != "observed_at_ns":
        raise DevelopmentCandidateError("input manifest must declare point_in_time_clock=observed_at_ns")
    if manifest.get("partition") != "development_only":
        raise DevelopmentCandidateError("input manifest must declare partition=development_only")
    if manifest.get("source_kind") not in {"real_market", "synthetic_test"}:
        raise DevelopmentCandidateError("input manifest source_kind must be real_market or synthetic_test")
    if not isinstance(manifest.get("market_data_visible_during_hypothesis_formation"), bool):
        raise DevelopmentCandidateError("input manifest must state market_data_visible_during_hypothesis_formation")
    if not isinstance(manifest.get("coverage_end_observed_at_ns"), int) or manifest["coverage_end_observed_at_ns"] <= 0:
        raise DevelopmentCandidateError("input manifest must include positive coverage_end_observed_at_ns")
    return raw, manifest


def _quote_before_or_at(quotes: Sequence[Quote], timestamps: Sequence[int], ts_ns: int) -> Quote | None:
    index = bisect_right(timestamps, ts_ns) - 1
    return quotes[index] if index >= 0 else None


def _first_quote_at_or_after(quotes: Sequence[Quote], timestamps: Sequence[int], ts_ns: int) -> Quote | None:
    index = bisect_left(timestamps, ts_ns)
    return quotes[index] if index < len(quotes) else None


def _quotes_between(quotes: Sequence[Quote], timestamps: Sequence[int], start_ns: int, end_ns: int) -> Sequence[Quote]:
    begin = bisect_left(timestamps, start_ns)
    end = bisect_right(timestamps, end_ns)
    return quotes[begin:end]


def _numeric_parameter(candidate: Mapping[str, Any], name: str) -> float:
    params = candidate.get("parameters")
    if not isinstance(params, Mapping):
        raise DevelopmentCandidateError(f"{candidate.get('candidate_id')}: parameters must be an object")
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DevelopmentCandidateError(f"{candidate.get('candidate_id')}: {name} must be finite")
    return float(value)


def _int_parameter(candidate: Mapping[str, Any], name: str) -> int:
    value = _numeric_parameter(candidate, name)
    if not value.is_integer() or value <= 0:
        raise DevelopmentCandidateError(f"{candidate.get('candidate_id')}: {name} must be a positive integer")
    return int(value)


def _impact_absorption_signals(candidate: Mapping[str, Any], events: Sequence[MarketEvent], quotes: Sequence[Quote]) -> list[Signal]:
    lookback_ns = _int_parameter(candidate, "lookback_ms") * 1_000_000
    min_trade_count = _int_parameter(candidate, "min_classified_trade_count")
    min_flow_ratio = _numeric_parameter(candidate, "min_signed_size_ratio")
    max_impact = _numeric_parameter(candidate, "max_signed_mid_impact_spreads")
    cooldown_ns = _int_parameter(candidate, "cooldown_ms") * 1_000_000
    if not 0.0 < min_flow_ratio <= 1.0 or max_impact < 0.0:
        raise DevelopmentCandidateError(f"{candidate['candidate_id']}: invalid impact-absorption thresholds")
    q_ts = [quote.ts_ns for quote in quotes]
    recent: list[MarketEvent] = []
    signals: list[Signal] = []
    last_signal = -10**30
    for event in events:
        if event.kind != "TRADE":
            continue
        recent.append(event)
        cutoff = event.ts_ns - lookback_ns
        recent = [trade for trade in recent if trade.ts_ns >= cutoff]
        classified = [trade for trade in recent if trade.side in {Side.BUY, Side.SELL} and trade.size is not None and trade.size > 0]
        if len(classified) < min_trade_count or event.ts_ns - last_signal < cooldown_ns:
            continue
        if event.bid is None or event.ask is None or not event.bid < event.ask:
            continue
        total_size = sum(float(trade.size) for trade in classified)
        signed_size = sum(float(trade.size) * (1.0 if trade.side is Side.BUY else -1.0) for trade in classified)
        if total_size <= 0.0 or abs(signed_size) / total_size < min_flow_ratio:
            continue
        baseline = _quote_before_or_at(quotes, q_ts, cutoff)
        if baseline is None or baseline.spread_fraction <= 0.0:
            continue
        current_mid = (float(event.bid) + float(event.ask)) / 2.0
        flow_side = 1 if signed_size > 0.0 else -1
        signed_impact = flow_side * (current_mid / baseline.mid - 1.0) / baseline.spread_fraction
        if signed_impact <= max_impact:
            signals.append(Signal(str(candidate["candidate_id"]), -flow_side, event.ts_ns, "flow_absorbed_by_price"))
            last_signal = event.ts_ns
    return signals


def _spread_resolution_signals(candidate: Mapping[str, Any], quotes: Sequence[Quote]) -> list[Signal]:
    baseline_ns = _int_parameter(candidate, "baseline_lookback_ms") * 1_000_000
    shock_ns = _int_parameter(candidate, "shock_window_ms") * 1_000_000
    min_widening = _numeric_parameter(candidate, "min_widening_ratio")
    max_current = _numeric_parameter(candidate, "max_current_spread_ratio")
    min_displacement = _numeric_parameter(candidate, "min_mid_displacement_spreads")
    cooldown_ns = _int_parameter(candidate, "cooldown_ms") * 1_000_000
    if min_widening <= 1.0 or max_current <= 0.0 or min_displacement <= 0.0:
        raise DevelopmentCandidateError(f"{candidate['candidate_id']}: invalid spread-resolution thresholds")
    q_ts = [quote.ts_ns for quote in quotes]
    signals: list[Signal] = []
    last_signal = -10**30
    for quote in quotes:
        if quote.ts_ns - last_signal < cooldown_ns:
            continue
        baseline = _quote_before_or_at(quotes, q_ts, quote.ts_ns - baseline_ns)
        if baseline is None or baseline.spread_fraction <= 0.0:
            continue
        recent = _quotes_between(quotes, q_ts, quote.ts_ns - shock_ns, quote.ts_ns)
        if not recent:
            continue
        widened = max(item.spread_fraction for item in recent) / baseline.spread_fraction
        current_ratio = quote.spread_fraction / baseline.spread_fraction
        displacement = (quote.mid / baseline.mid - 1.0) / baseline.spread_fraction
        if widened >= min_widening and current_ratio <= max_current and abs(displacement) >= min_displacement:
            signals.append(Signal(str(candidate["candidate_id"]), 1 if displacement > 0.0 else -1, quote.ts_ns, "spread_shock_resolved"))
            last_signal = quote.ts_ns
    return signals


def generate_signals(candidate: Mapping[str, Any], events: Sequence[MarketEvent], quotes: Sequence[Quote]) -> list[Signal]:
    """Generate decisions using observations at or before each signal timestamp."""

    mechanism = candidate.get("mechanism")
    if mechanism == "impact_absorption_reversal":
        return _impact_absorption_signals(candidate, events, quotes)
    if mechanism == "spread_shock_resolution_continuation":
        return _spread_resolution_signals(candidate, quotes)
    raise DevelopmentCandidateError(f"unsupported candidate mechanism: {mechanism}")


def _evaluate_signal(signal: Signal, candidate: Mapping[str, Any], quotes: Sequence[Quote], timestamps: Sequence[int]) -> dict[str, Any] | None:
    execution = candidate["execution"]
    decision_latency_ns = int(execution["decision_latency_ms"]) * 1_000_000
    horizon_ns = int(execution["outcome_horizon_ms"]) * 1_000_000
    entry = _first_quote_at_or_after(quotes, timestamps, signal.ts_ns + decision_latency_ns)
    if entry is None:
        return None
    exit_quote = _first_quote_at_or_after(quotes, timestamps, entry.ts_ns + horizon_ns)
    if exit_quote is None:
        return None
    entry_price = entry.ask if signal.side > 0 else entry.bid
    exit_price = exit_quote.bid if signal.side > 0 else exit_quote.ask
    gross_bps = signal.side * (exit_price / entry_price - 1.0) * 10_000.0
    fee_bps = float(execution["round_trip_fee_bps"])
    slippage_bps = float(execution["round_trip_slippage_bps"])
    return {
        "candidate_id": signal.candidate_id,
        "signal_observed_at_ns": signal.ts_ns,
        "signal_observed_at_utc": _iso_ns(signal.ts_ns),
        "signal_side": signal.side,
        "signal_reason": signal.reason,
        "entry_observed_at_ns": entry.ts_ns,
        "entry_observed_at_utc": _iso_ns(entry.ts_ns),
        "entry_price": entry_price,
        "exit_observed_at_ns": exit_quote.ts_ns,
        "exit_observed_at_utc": _iso_ns(exit_quote.ts_ns),
        "exit_price": exit_price,
        "gross_bps": gross_bps,
        "cost_components_bps": {"fees": fee_bps, "slippage": slippage_bps},
        "net_bps": gross_bps - fee_bps - slippage_bps,
    }


def _summary(fills: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    gross = [float(fill["gross_bps"]) for fill in fills]
    net = [float(fill["net_bps"]) for fill in fills]
    wins = [value for value in net if value > 0.0]
    losses = [-value for value in net if value < 0.0]
    return {
        "completed_fills": len(fills),
        "gross_mean_bps": sum(gross) / len(gross),
        "net_mean_bps": sum(net) / len(net),
        "net_total_bps": sum(net),
        "net_win_fraction": len(wins) / len(net),
        "profit_factor": sum(wins) / sum(losses) if losses else ("INF" if wins else None),
        "all_fills_have_nonzero_friction": all(
            float(fill["cost_components_bps"]["fees"]) + float(fill["cost_components_bps"]["slippage"]) > 0.0
            for fill in fills
        ),
    }


def _orthogonality(signals_by_id: Mapping[str, Sequence[Signal]], bucket_ms: int) -> list[dict[str, Any]]:
    if bucket_ms <= 0:
        raise DevelopmentCandidateError("orthogonality bucket must be positive")
    candidate_ids = sorted(signals_by_id)
    out: list[dict[str, Any]] = []
    bucket_ns = bucket_ms * 1_000_000
    for index, left_id in enumerate(candidate_ids):
        left = {signal.ts_ns // bucket_ns: signal.side for signal in signals_by_id[left_id]}
        for right_id in candidate_ids[index + 1:]:
            right = {signal.ts_ns // bucket_ns: signal.side for signal in signals_by_id[right_id]}
            common = set(left) & set(right)
            union = set(left) | set(right)
            agreement = sum(left[key] == right[key] for key in common) / len(common) if common else None
            out.append(
                {
                    "left_candidate_id": left_id,
                    "right_candidate_id": right_id,
                    "time_bucket_ms": bucket_ms,
                    "overlap_buckets": len(common),
                    "signal_jaccard": len(common) / len(union) if union else 0.0,
                    "directional_agreement_on_overlap": agreement,
                }
            )
    return out


def evaluate_catalog(
    catalog: Mapping[str, Any],
    events: Sequence[MarketEvent],
    quotes: Sequence[Quote],
    *,
    input_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate all catalog candidates without selection or promotion logic."""

    candidates = _catalog_candidates(catalog)
    q_ts = [quote.ts_ns for quote in quotes]
    coverage_end = int(input_manifest["coverage_end_observed_at_ns"])
    if coverage_end < q_ts[-1]:
        raise DevelopmentCandidateError("input manifest coverage ends before the final quote")
    reports: list[dict[str, Any]] = []
    signal_map: dict[str, list[Signal]] = {}
    for candidate in candidates:
        signals = generate_signals(candidate, events, quotes)
        signal_map[str(candidate["candidate_id"])] = signals
        fills = [_evaluate_signal(signal, candidate, quotes, q_ts) for signal in signals]
        missing_fills = sum(fill is None for fill in fills)
        completed = [fill for fill in fills if fill is not None]
        report: dict[str, Any] = {
            "candidate_id": candidate["candidate_id"],
            "candidate_spec_sha256": _canonical_sha256(candidate),
            "mechanism": candidate["mechanism"],
            "signals_generated": len(signals),
            "unfilled_signals": missing_fills,
            "execution": dict(candidate["execution"]),
            "fills": completed if missing_fills == 0 else [],
            "summary": _summary(completed) if completed and missing_fills == 0 else None,
            "status": "COMPLETED_DEVELOPMENT_ONLY" if missing_fills == 0 else "INCOMPLETE_MISSING_NEXT_EVENT_FILL",
            "fail_closed": missing_fills > 0,
        }
        reports.append(report)
    orthogonality = _orthogonality(signal_map, int(catalog.get("orthogonality_bucket_ms", 1_000)))
    max_overlap = float(catalog.get("max_signal_jaccard_before_progression", 0.35))
    for row in orthogonality:
        row["progression_blocked_for_redundancy"] = row["signal_jaccard"] > max_overlap
    return {
        "schema_version": 1,
        "evaluation_kind": "development_only_causal_next_quote_fill",
        "causal_clock": "observed_at_ns",
        "exchange_timestamps_used_for_ordering": False,
        "input": {
            "source_kind": input_manifest["source_kind"],
            "partition": input_manifest["partition"],
            "market_data_visible_during_hypothesis_formation": input_manifest["market_data_visible_during_hypothesis_formation"],
            "coverage_end_observed_at_ns": coverage_end,
            "event_count": len(events),
            "quote_count": len(quotes),
        },
        "candidates": reports,
        "orthogonality": {
            "max_signal_jaccard_before_progression": max_overlap,
            "pairs": orthogonality,
            "policy": "No candidate may progress if overlap exceeds the declared limit without a separately specified incremental-information test.",
        },
        "claims": {
            "development_only": True,
            "synthetic_input_is_not_market_evidence": input_manifest["source_kind"] == "synthetic_test",
            "candidate_specification_frozen": False,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }


def new_development_trial_ledger(*, family_name: str, candidate_freeze_sha256: str, created_at: str, alpha: float = 0.05) -> dict[str, Any]:
    if not isinstance(family_name, str) or not family_name.strip():
        raise DevelopmentCandidateError("trial family name must be nonempty")
    if not _is_sha256(candidate_freeze_sha256):
        raise DevelopmentCandidateError("candidate_freeze_sha256 must be a SHA-256")
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not 0.0 < float(alpha) < 1.0:
        raise DevelopmentCandidateError("alpha must be between zero and one")
    timestamp = _parse_utc(created_at)
    ledger: dict[str, Any] = {
        "schema_version": 1,
        "ledger_kind": "development_trial_accounting_only",
        "family_name": family_name.strip(),
        "family_alpha": float(alpha),
        "created_at": timestamp.isoformat(),
        "candidate_freeze_sha256": candidate_freeze_sha256,
        "trials": [],
        "claims": {
            "all_attempts_must_be_counted": True,
            "multiple_testing_adjustment_required": True,
            "development_trials_are_not_holdout_trials": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    ledger["manifest_sha256"] = _canonical_sha256(ledger)
    return ledger


def verify_development_trial_ledger(ledger: Mapping[str, Any]) -> bool:
    if not isinstance(ledger, Mapping) or ledger.get("schema_version") != 1 or ledger.get("ledger_kind") != "development_trial_accounting_only":
        return False
    expected = ledger.get("manifest_sha256")
    if not _is_sha256(expected):
        return False
    unsigned = dict(ledger)
    unsigned.pop("manifest_sha256", None)
    if _canonical_sha256(unsigned) != expected or not _is_sha256(ledger.get("candidate_freeze_sha256")):
        return False
    alpha = ledger.get("family_alpha")
    trials = ledger.get("trials")
    if not isinstance(alpha, (int, float)) or not 0.0 < float(alpha) < 1.0 or not isinstance(trials, list):
        return False
    identities: set[tuple[str, str, str]] = set()
    for number, trial in enumerate(trials, 1):
        if not isinstance(trial, Mapping) or trial.get("trial_number") != number:
            return False
        candidate = trial.get("candidate_id")
        specs = trial.get("candidate_spec_sha256")
        source = trial.get("source_sha256")
        manifest = trial.get("input_manifest_sha256")
        if not isinstance(candidate, str) or not _is_sha256(specs) or not _is_sha256(source) or not _is_sha256(manifest):
            return False
        identity = (candidate, str(specs), str(source))
        if identity in identities:
            return False
        identities.add(identity)
        if abs(float(trial.get("bonferroni_alpha", -1.0)) - float(alpha) / number) > 1e-15:
            return False
    claims = ledger.get("claims")
    return isinstance(claims, Mapping) and claims.get("all_attempts_must_be_counted") is True and all(
        claims.get(key) is False for key in ("verified_out_of_sample_evidence", "profitable_edge_established", "live_order_transmission_supported")
    )


def append_development_trials(
    ledger: Mapping[str, Any],
    evaluation: Mapping[str, Any],
    *,
    source_sha256: str,
    input_manifest_sha256: str,
    candidate_freeze_sha256: str,
    recorded_at: str,
) -> dict[str, Any]:
    if not verify_development_trial_ledger(ledger):
        raise DevelopmentCandidateError("development trial ledger is invalid")
    if ledger.get("candidate_freeze_sha256") != candidate_freeze_sha256:
        raise DevelopmentCandidateError("ledger candidate freeze does not match the evaluation freeze")
    if not all(_is_sha256(value) for value in (source_sha256, input_manifest_sha256, candidate_freeze_sha256)):
        raise DevelopmentCandidateError("trial provenance hashes must be SHA-256 values")
    timestamp = _parse_utc(recorded_at)
    reports = evaluation.get("candidates")
    if not isinstance(reports, list) or not reports:
        raise DevelopmentCandidateError("evaluation contains no candidate reports")
    updated = dict(ledger)
    trials = list(ledger["trials"])
    existing = {(row["candidate_id"], row["candidate_spec_sha256"], row["source_sha256"]) for row in trials}
    for report in reports:
        if not isinstance(report, Mapping) or not isinstance(report.get("candidate_id"), str) or not _is_sha256(report.get("candidate_spec_sha256")):
            raise DevelopmentCandidateError("evaluation candidate report lacks frozen identity")
        identity = (str(report["candidate_id"]), str(report["candidate_spec_sha256"]), source_sha256)
        if identity in existing:
            raise DevelopmentCandidateError(f"development trial already counted: {report['candidate_id']}")
        number = len(trials) + 1
        trials.append(
            {
                "trial_number": number,
                "recorded_at": timestamp.isoformat(),
                "candidate_id": report["candidate_id"],
                "candidate_spec_sha256": report["candidate_spec_sha256"],
                "source_sha256": source_sha256,
                "input_manifest_sha256": input_manifest_sha256,
                "candidate_freeze_sha256": candidate_freeze_sha256,
                "evaluation_status": report.get("status"),
                "bonferroni_alpha": float(ledger["family_alpha"]) / number,
            }
        )
        existing.add(identity)
    updated["trials"] = trials
    updated["manifest_sha256"] = _canonical_sha256({key: value for key, value in updated.items() if key != "manifest_sha256"})
    return updated


def _load_or_create_ledger(path: Path, family_name: str, freeze_sha: str, recorded_at: str) -> dict[str, Any]:
    if path.exists():
        _, payload = _load_json_object(path, "development trial ledger")
        return payload
    return new_development_trial_ledger(family_name=family_name, candidate_freeze_sha256=freeze_sha, created_at=recorded_at)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Development-only causal evaluation of new microstructure candidate specifications.")
    parser.add_argument("--catalog", default="config/development_strategy_candidates_v1.json")
    parser.add_argument("--input", help="Local point-in-time JSONL; no network source is accepted.")
    parser.add_argument("--input-manifest", help="JSON manifest that SHA-256 pins --input and its causal clock.")
    parser.add_argument("--candidate-freeze", help="Hash-pinned development candidate-spec freeze JSON.")
    parser.add_argument("--trial-ledger", help="Append-only development trial ledger JSON.")
    parser.add_argument("--recorded-at", help="Timezone-aware timestamp for deterministic trial accounting.")
    parser.add_argument("--output")
    parser.add_argument("--freeze-output", help="Create a candidate-specification freeze and exit; requires --frozen-at.")
    parser.add_argument("--frozen-at", help="Timezone-aware timestamp used with --freeze-output.")
    args = parser.parse_args(argv)

    if args.freeze_output:
        if not args.frozen_at:
            raise SystemExit("--frozen-at is required with --freeze-output")
        freeze = build_candidate_spec_freeze(args.catalog, frozen_at=args.frozen_at)
        _write_json(Path(args.freeze_output), freeze)
        print(args.freeze_output)
        return 0

    required = ("input", "input_manifest", "candidate_freeze", "trial_ledger", "recorded_at", "output")
    missing = [f"--{name.replace('_', '-')}" for name in required if getattr(args, name) is None]
    if missing:
        parser.error(f"evaluation requires: {', '.join(missing)}")
    catalog_raw, catalog = load_candidate_catalog(args.catalog)
    _, input_manifest = load_input_manifest(args.input_manifest, args.input)
    _, freeze = _load_json_object(args.candidate_freeze, "candidate freeze")
    if not verify_candidate_spec_freeze(freeze, args.catalog):
        raise SystemExit("candidate freeze is invalid or does not match the exact catalog bytes")
    events, quotes = load_point_in_time_jsonl(args.input)
    report = evaluate_catalog(catalog, events, quotes, input_manifest=input_manifest)
    freeze_ids = {row["candidate_id"] for row in freeze["candidates"]}
    report_ids = {row["candidate_id"] for row in report["candidates"]}
    if freeze_ids != report_ids:
        raise SystemExit("candidate freeze must cover exactly the catalog candidates being evaluated")
    source_sha = _sha256_bytes(Path(args.input).read_bytes())
    manifest_raw = Path(args.input_manifest).read_bytes()
    freeze_sha = str(freeze["manifest_sha256"])
    ledger_path = Path(args.trial_ledger)
    ledger = _load_or_create_ledger(ledger_path, str(catalog.get("trial_family", "development-strategy-candidates-v1")), freeze_sha, args.recorded_at)
    ledger = append_development_trials(
        ledger,
        report,
        source_sha256=source_sha,
        input_manifest_sha256=_sha256_bytes(manifest_raw),
        candidate_freeze_sha256=freeze_sha,
        recorded_at=args.recorded_at,
    )
    _write_json(ledger_path, ledger)
    report["catalog"] = {"path": str(Path(args.catalog).resolve()), "sha256": _sha256_bytes(catalog_raw)}
    report["candidate_freeze"] = {"path": str(Path(args.candidate_freeze).resolve()), "sha256": freeze_sha}
    report["trial_ledger"] = {"path": str(ledger_path.resolve()), "manifest_sha256": ledger["manifest_sha256"], "trials_recorded": len(ledger["trials"])}
    report["claims"]["candidate_specification_frozen"] = True
    _write_json(Path(args.output), report)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
