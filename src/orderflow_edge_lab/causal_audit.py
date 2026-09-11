"""Audit whether validation-window summaries can be computed causally.

A signal belongs to the sequential validation window containing its event time, but
its realized outcome is not knowable until ``outcome_time``. If the outcome crosses
the end of that window, using it in that window's summary introduces look-ahead.
This module diagnoses that condition without claiming statistical significance or an
edge.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .research import Candidate, parse_utc

UTC = timezone.utc


@dataclass(frozen=True)
class OutcomeMaturityObservation:
    candidate_id: str
    observation_id: str
    event_time: datetime
    outcome_time: datetime
    window_start: datetime
    window_end: datetime
    matured_within_window: bool
    seconds_past_window: float


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_jsonl(path: str | Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"observation line {line_number} must be a JSON object")
        rows.append(parsed)
    return rows


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _window_bounds(candidate: Candidate, event_time: datetime, window_days: int) -> tuple[datetime, datetime]:
    if window_days < 1:
        raise ValueError("window_days must be positive")
    event = parse_utc(event_time)
    boundary = max(candidate.spent_through, candidate.frozen_at).astimezone(UTC)
    first = boundary + timedelta(microseconds=1)
    if event < first:
        raise ValueError(f"{candidate.candidate_id}: event is not strictly future-only")
    width_seconds = timedelta(days=window_days).total_seconds()
    offset_seconds = (event - first).total_seconds()
    index = math.floor(offset_seconds / width_seconds)
    start = first + timedelta(days=index * window_days)
    return start, start + timedelta(days=window_days)


def audit_outcome_maturity(
    registry_path: str | Path,
    observations_path: str | Path,
    *,
    window_days: int = 7,
) -> dict[str, Any]:
    """Return a fail-closed diagnostic for outcome leakage across window boundaries."""
    if window_days < 1:
        raise ValueError("window_days must be positive")

    registry = _load_json(registry_path)
    if not isinstance(registry, dict) or not isinstance(registry.get("candidates"), list):
        raise ValueError("registry must contain a candidates list")

    candidates: dict[str, Candidate] = {}
    for raw in registry["candidates"]:
        candidate = Candidate.from_mapping(raw)
        if candidate.candidate_id in candidates:
            raise ValueError("duplicate candidate ID")
        candidates[candidate.candidate_id] = candidate
    if not candidates:
        raise ValueError("candidate registry is empty")

    rows = _load_jsonl(observations_path)
    seen: set[tuple[str, str]] = set()
    observations: list[OutcomeMaturityObservation] = []

    for row in rows:
        candidate_id = row.get("candidate_id")
        observation_id = row.get("observation_id")
        if not isinstance(candidate_id, str) or candidate_id not in candidates:
            raise ValueError("unknown candidate observation")
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise ValueError("observation_id must be a nonempty string")
        identity = (candidate_id, observation_id)
        if identity in seen:
            raise ValueError("duplicate observation identity")
        seen.add(identity)

        event_time = parse_utc(row["event_time"])
        outcome_time = parse_utc(row["outcome_time"])
        if outcome_time <= event_time:
            raise ValueError("outcome must finish strictly after event time")
        start, end = _window_bounds(candidates[candidate_id], event_time, window_days)
        seconds_past = max(0.0, (outcome_time - end).total_seconds())
        observations.append(
            OutcomeMaturityObservation(
                candidate_id=candidate_id,
                observation_id=observation_id,
                event_time=event_time,
                outcome_time=outcome_time,
                window_start=start,
                window_end=end,
                matured_within_window=outcome_time <= end,
                seconds_past_window=seconds_past,
            )
        )

    per_candidate = []
    for candidate_id in sorted(candidates):
        items = [item for item in observations if item.candidate_id == candidate_id]
        crossings = [item for item in items if not item.matured_within_window]
        per_candidate.append(
            {
                "candidate_id": candidate_id,
                "observations": len(items),
                "matured_within_window": len(items) - len(crossings),
                "cross_window_outcomes": len(crossings),
                "max_seconds_past_window": max((item.seconds_past_window for item in crossings), default=0.0),
                "crossing_observation_ids": [item.observation_id for item in crossings],
            }
        )

    crossing_count = sum(not item.matured_within_window for item in observations)
    return {
        "schema_version": 1,
        "audit_type": "causal_outcome_maturity",
        "registry_sha256": _sha256(registry_path),
        "observations_sha256": _sha256(observations_path),
        "window_days": window_days,
        "observation_count": len(observations),
        "cross_window_outcome_count": crossing_count,
        "causal_window_summaries_safe": crossing_count == 0,
        "candidates": per_candidate,
        "limitations": [
            "This audit checks timing causality only and does not establish profitability, significance, or executable fills.",
            "A cross-window outcome must be excluded from that window's as-of-close summary or carried into a later matured-outcome analysis.",
            "Passing this audit does not prove the source data, prices, costs, or candidate freeze timestamp are authentic.",
        ],
    }
