"""Audit supplied future observations; never certify an edge or deployment."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import operator
from pathlib import Path

from .research import Candidate, enforce_future_only, oos_summary, parse_utc, sequential_windows


OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}


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


def build_validation_report(registry_path, observations_path, *, observed_through,
                            now: datetime | None = None) -> dict:
    coverage = parse_utc(observed_through)
    now = parse_utc(now or datetime.now(timezone.utc))
    if coverage > now:
        raise ValueError("coverage cannot be in the future")
    # Hash the exact bytes parsed, avoiding a separate read/hash race.
    registry_bytes = Path(registry_path).read_bytes()
    observation_bytes = Path(observations_path).read_bytes()
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
    seen = set()
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
        if not event_time <= outcome_time <= coverage:
            raise ValueError("outcome must finish within observed coverage")
        if row.get("source_kind") != "real_market":
            raise ValueError("synthetic or unspecified source is not future-market evidence")
        gross, costs = _number(row["gross_return_r"]), _number(row["cost_r"])
        if costs < 0:
            raise ValueError("costs cannot be negative")
        net = _number(gross - costs)
        grouped[candidate.candidate_id].append((event_time, outcome_time, net))
    reports = []
    for key, candidate in candidates.items():
        rows = grouped[key]
        windows = sequential_windows(candidate, [event for event, _, _ in rows], observed_through=coverage)
        reports.append({
            "candidate_id": key,
            "windows": [{**asdict(window), "start": window.start.isoformat(), "end": window.end.isoformat(),
                         "summary": oos_summary([net for event, _, net in rows if window.start <= event < window.end])}
                        for window in windows],
            "summary": oos_summary([net for _, _, net in rows]),
            "dependence": _dependence_diagnostics(rows),
        })
    return {
        "schema_version": 1,
        "audit_status": "supplied_observations_passed_structural_checks",
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "observations_sha256": hashlib.sha256(observation_bytes).hexdigest(),
        "observed_through": coverage.isoformat(),
        "generated_at": now.isoformat(),
        "observation_count": len(seen),
        "candidates": reports,
        "deployment_eligible": False,
        "verified_out_of_sample_evidence": False,
        "limitations": [
            "Source labels, coverage, returns, and costs are caller supplied, not independently verified.",
            "Registry hashes identify rules but do not prove when rules were frozen.",
            "Event-level summaries do not assume independence; overlap diagnostics and daily clustering are descriptive only.",
            "Descriptive summaries do not establish independence, significance, or profitability.",
        ],
    }
