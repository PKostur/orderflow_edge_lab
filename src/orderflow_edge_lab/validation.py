"""Audit supplied future observations; never certify an edge or deployment."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import operator
from pathlib import Path

from .research import Candidate, enforce_future_only, oos_summary, parse_utc, sequential_windows, sha256_file


OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}
COST_COMPONENTS = ("fees", "slippage", "spread", "other")
RETURN_PRICE_FIELDS = ("entry_price", "exit_price", "initial_stop_price")
SOURCE_PROVENANCE_FIELDS = ("dataset_sha256", "record_id")


def _number(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("observation values must be finite numbers")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("observation value out of range") from exc
    if not math.isfinite(result):
        raise ValueError("observation values must be finite numbers")
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite JSON constant")


def _json(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)


def _cost_provenance(row):
    model_id = row.get("cost_model_id")
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError("cost_model_id must be a nonempty string")
    components = row.get("cost_components_r")
    if not isinstance(components, dict) or set(components) != set(COST_COMPONENTS):
        raise ValueError("cost_components_r must contain fees, slippage, spread, and other")
    parsed = {name: _number(components[name]) for name in COST_COMPONENTS}
    if any(value < 0 for value in parsed.values()):
        raise ValueError("cost components cannot be negative")
    total = _number(row["cost_r"])
    if total <= 0:
        raise ValueError("real-market evidence requires positive transaction costs")
    if not math.isclose(sum(parsed.values()), total, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("cost_r does not match cost_components_r")
    return model_id.strip(), total


def _return_provenance(row, candidate):
    provenance = row.get("return_provenance")
    if not isinstance(provenance, dict) or set(provenance) != set(RETURN_PRICE_FIELDS):
        raise ValueError("return_provenance must contain entry_price, exit_price, and initial_stop_price")
    prices = {name: _number(provenance[name]) for name in RETURN_PRICE_FIELDS}
    if any(value <= 0 for value in prices.values()):
        raise ValueError("return provenance prices must be positive")
    entry = prices["entry_price"]
    exit_price = prices["exit_price"]
    stop = prices["initial_stop_price"]
    if candidate.direction == "long":
        if stop >= entry:
            raise ValueError("long initial_stop_price must be below entry_price")
        computed = (exit_price - entry) / (entry - stop)
    else:
        if stop <= entry:
            raise ValueError("short initial_stop_price must be above entry_price")
        computed = (entry - exit_price) / (stop - entry)
    reported = _number(row["gross_return_r"])
    if not math.isclose(reported, computed, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("gross_return_r does not match return_provenance prices")
    return computed


def _source_provenance(row):
    provenance = row.get("source_provenance")
    if not isinstance(provenance, dict) or set(provenance) != set(SOURCE_PROVENANCE_FIELDS):
        raise ValueError("source_provenance must contain dataset_sha256 and record_id")
    digest = provenance.get("dataset_sha256")
    record_id = provenance.get("record_id")
    if not isinstance(digest, str):
        raise ValueError("dataset_sha256 must be a 64-character hexadecimal SHA-256")
    digest = digest.strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("dataset_sha256 must be a 64-character hexadecimal SHA-256")
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError("source record_id must be a nonempty string")
    return digest, record_id.strip()


def _dependence_diagnostics(rows):
    """Describe obvious temporal dependence without pretending observations are IID.

    `overlap_count` counts observations whose event occurs before an earlier active
    outcome has completed. `max_concurrent_outcomes` is the largest number of
    simultaneously open observation horizons. Daily means provide a coarse cluster
    summary so a burst of same-day signals cannot masquerade as many independent days.
    """
    if not rows:
        return {
            "active_days": 0,
            "overlap_count": 0,
            "max_concurrent_outcomes": 0,
            "daily_cluster_summary": oos_summary([]),
        }
    ordered = sorted(rows, key=lambda row: (row[0], row[1]))
    active_ends = []
    overlap_count = 0
    max_concurrent = 0
    daily = defaultdict(list)
    for event_time, outcome_time, net in ordered:
        active_ends = [end for end in active_ends if end > event_time]
        if active_ends:
            overlap_count += 1
        active_ends.append(outcome_time)
        max_concurrent = max(max_concurrent, len(active_ends))
        daily[event_time.date().isoformat()].append(net)
    daily_means = [sum(values) / len(values) for _, values in sorted(daily.items())]
    return {
        "active_days": len(daily),
        "overlap_count": overlap_count,
        "max_concurrent_outcomes": max_concurrent,
        "daily_cluster_summary": oos_summary(daily_means),
    }


def _causal_window_report(window, rows, candidate, coverage):
    """Summarize only outcomes that were knowable by a validation window's close.

    Signals are assigned to the window containing their event time. A realized return
    whose outcome_time is after that window's end is deliberately excluded from that
    window rather than being shifted into a later window. The candidate-level summary
    can still include it once it has matured by observed coverage.
    """
    selected = [row for row in rows if window.start <= row[0] < window.end]
    matured = [row for row in selected if row[1] <= window.end]
    matured_active_days = len({event.date() for event, _, _ in matured})
    cross_window = len(selected) - len(matured)
    complete = (
        window.end <= coverage
        and len(matured) >= candidate.minimum_events
        and matured_active_days >= candidate.minimum_active_days
    )
    return {
        **asdict(window),
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "complete": complete,
        "matured_event_count": len(matured),
        "matured_active_days": matured_active_days,
        "cross_window_outcomes_excluded": cross_window,
        "summary": oos_summary([net for _, _, net in matured]),
    }


def build_validation_report(registry_path, observations_path, *, observed_through,
                            now: datetime | None = None, source_files=None) -> dict:
    coverage = parse_utc(observed_through)
    now = parse_utc(now or datetime.now(timezone.utc))
    if coverage > now:
        raise ValueError("coverage cannot be in the future")
    # Hash the exact bytes parsed, avoiding a separate read/hash race.
    registry_bytes = Path(registry_path).read_bytes()
    observation_bytes = Path(observations_path).read_bytes()
    verified_source_hashes = None
    verified_source_files = []
    if source_files is not None:
        paths = [Path(path) for path in source_files]
        if not paths:
            raise ValueError("source_files cannot be empty when source verification is requested")
        verified_source_hashes = set()
        for path in paths:
            digest = sha256_file(path)
            verified_source_hashes.add(digest)
            verified_source_files.append({"path": str(path), "sha256": digest})
    raw_registry = _json(registry_bytes)
    candidates = {}
    for raw in raw_registry["candidates"]:
        candidate = Candidate.from_mapping(raw)
        if candidate.candidate_id in candidates:
            raise ValueError("duplicate candidate ID")
        if any(op not in OPS or not math.isfinite(value) for _, op, value in candidate.numeric_filters):
            raise ValueError("unsupported frozen numeric filter")
        candidates[candidate.candidate_id] = candidate
    if not candidates:
        raise ValueError("candidate registry is empty")
    grouped = {key: [] for key in candidates}
    costs = {key: {"values": [], "model": None} for key in candidates}
    return_counts = {key: 0 for key in candidates}
    source_datasets = {key: set() for key in candidates}
    source_counts = {key: 0 for key in candidates}
    seen = set()
    seen_source = set()
    previous_time = None
    for line in observation_bytes.decode("utf-8").splitlines():
        row = _json(line)
        if not isinstance(row, dict) or row.get("candidate_id") not in candidates:
            raise ValueError("unknown candidate observation")
        candidate = candidates[row["candidate_id"]]
        identity = row.get("observation_id")
        if not isinstance(identity, str) or not identity or (candidate.candidate_id, identity) in seen:
            raise ValueError("missing or duplicate observation identity")
        seen.add((candidate.candidate_id, identity))
        for field in ("timeframe", "setup_family", "direction"):
            if row.get(field) != getattr(candidate, field):
                raise ValueError("observation differs from frozen candidate")
        if row.get("path") != list(candidate.path):
            raise ValueError("observation path differs from frozen candidate")
        filters = [{"field": field, "op": op, "value": value} for field, op, value in candidate.numeric_filters]
        if row.get("numeric_filters") != filters:
            raise ValueError("observation filters differ from frozen candidate")
        features = row.get("features", {})
        for field, op, threshold in candidate.numeric_filters:
            if not OPS[op](_number(features.get(field)), threshold):
                raise ValueError("observation does not satisfy frozen filter")
        event_time = parse_utc(row["event_time"])
        outcome_time = parse_utc(row["outcome_time"])
        enforce_future_only(candidate, [event_time])
        if previous_time is not None and event_time < previous_time:
            raise ValueError("observations must be chronological")
        previous_time = event_time
        if outcome_time <= event_time:
            raise ValueError("outcome must finish strictly after event time")
        if outcome_time > coverage:
            raise ValueError("outcome must finish within observed coverage")
        if row.get("source_kind") != "real_market":
            raise ValueError("synthetic or unspecified source is not future-market evidence")
        dataset_hash, record_id = _source_provenance(row)
        if verified_source_hashes is not None and dataset_hash not in verified_source_hashes:
            raise ValueError("observation dataset_sha256 does not match any supplied source file")
        source_key = (candidate.candidate_id, dataset_hash, record_id)
        if source_key in seen_source:
            raise ValueError("duplicate raw source record for candidate")
        seen_source.add(source_key)
        source_datasets[candidate.candidate_id].add(dataset_hash)
        source_counts[candidate.candidate_id] += 1
        gross = _return_provenance(row, candidate)
        return_counts[candidate.candidate_id] += 1
        model_id, cost = _cost_provenance(row)
        frozen_model = costs[candidate.candidate_id]["model"]
        if frozen_model is None:
            costs[candidate.candidate_id]["model"] = model_id
        elif model_id != frozen_model:
            raise ValueError(
                "candidate observations cannot mix transaction cost models; "
                "create a separately frozen candidate for materially different execution assumptions"
            )
        net = _number(gross - cost)
        grouped[candidate.candidate_id].append((event_time, outcome_time, net))
        costs[candidate.candidate_id]["values"].append(cost)
    reports = []
    total_cross_window = 0
    for key, candidate in candidates.items():
        rows = grouped[key]
        windows = sequential_windows(candidate, [event for event, _, _ in rows], observed_through=coverage)
        window_reports = [_causal_window_report(window, rows, candidate, coverage) for window in windows]
        cross_window_count = sum(window["cross_window_outcomes_excluded"] for window in window_reports)
        total_cross_window += cross_window_count
        cost_values = costs[key]["values"]
        cost_model = costs[key]["model"]
        reports.append({
            "candidate_id": key,
            "windows": window_reports,
            "cross_window_outcome_count": cross_window_count,
            "summary": oos_summary([net for _, _, net in rows]),
            "dependence": _dependence_diagnostics(rows),
            "source_provenance": {
                "dataset_sha256": sorted(source_datasets[key]),
                "unique_records": source_counts[key],
            },
            "return_provenance": {
                "observations_recomputed": return_counts[key],
                "formula": "directional_price_change / abs(entry_price - initial_stop_price)",
            },
            "cost_provenance": {
                "model_ids": [cost_model] if cost_model is not None else [],
                "observations": len(cost_values),
                "min_cost_r": min(cost_values) if cost_values else None,
                "mean_cost_r": sum(cost_values) / len(cost_values) if cost_values else None,
                "max_cost_r": max(cost_values) if cost_values else None,
            },
        })
    source_verification = {
        "verified_against_local_files": verified_source_hashes is not None,
        "files": verified_source_files,
    }
    return {
        "schema_version": 7,
        "audit_status": "supplied_observations_passed_structural_checks",
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "observations_sha256": hashlib.sha256(observation_bytes).hexdigest(),
        "source_verification": source_verification,
        "observed_through": coverage.isoformat(),
        "generated_at": now.isoformat(),
        "observation_count": len(seen),
        "cross_window_outcome_count": total_cross_window,
        "causal_window_summaries": True,
        "candidates": reports,
        "deployment_eligible": False,
        "verified_out_of_sample_evidence": False,
        "limitations": [
            "Source labels, record IDs, coverage, prices, cost model labels, and cost components are caller supplied, not independently verified.",
            "Local file hashing can verify declared dataset hashes against supplied bytes but does not prove export authenticity or completeness.",
            "Registry hashes identify rules but do not prove when rules were frozen.",
            "Per-window summaries include only outcomes known by that window's close; cross-window outcomes are excluded from that window rather than shifted forward.",
            "The candidate-level summary is an as-of-observed-through summary and may include outcomes excluded from their original per-window summary after those outcomes mature.",
            "Event-level summaries do not assume independence; overlap diagnostics and daily clustering are descriptive only.",
            "Gross R is recomputed from supplied prices and initial stop distance, but supplied prices and fill timestamps are not independently verified.",
            "Explicit positive transaction costs reduce frictionless backtest risk but do not prove fills were executable.",
            "Descriptive summaries do not establish independence, significance, or profitability.",
        ],
    }
