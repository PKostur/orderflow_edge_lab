from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable, Mapping, Sequence


UTC = timezone.utc


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone aware")
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    timeframe: str
    setup_family: str
    direction: str
    spent_through: datetime
    frozen_at: datetime
    path: tuple[str, ...] = ()
    numeric_filters: tuple[tuple[str, str, float], ...] = ()
    minimum_events: int = 30
    minimum_active_days: int = 5

    def __post_init__(self) -> None:
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.spent_through.tzinfo is None or self.frozen_at.tzinfo is None:
            raise ValueError("candidate timestamps must be timezone aware")
        if self.minimum_events < 1 or self.minimum_active_days < 1:
            raise ValueError("minimum evidence thresholds must be positive")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Candidate":
        filters = tuple(
            (str(x["field"]), str(x["op"]), float(x["value"]))
            for x in raw.get("numeric_filters", [])
        )
        return cls(
            candidate_id=str(raw["candidate_id"]),
            timeframe=str(raw["timeframe"]),
            setup_family=str(raw["setup_family"]),
            direction=str(raw["direction"]).lower(),
            spent_through=parse_utc(raw["spent_through"]),
            frozen_at=parse_utc(raw["frozen_at"]),
            path=tuple(raw.get("path", [])),
            numeric_filters=filters,
            minimum_events=int(raw.get("minimum_events", 30)),
            minimum_active_days=int(raw.get("minimum_active_days", 5)),
        )


def load_candidates(path: str | Path) -> list[Candidate]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Candidate.from_mapping(x) for x in raw["candidates"]]


def enforce_future_only(candidate: Candidate, event_times: Iterable[datetime]) -> None:
    boundary = candidate.spent_through.astimezone(UTC)
    for ts in event_times:
        ts = parse_utc(ts)
        if ts <= boundary:
            raise ValueError(
                f"{candidate.candidate_id}: event {ts.isoformat()} is not fresh; "
                f"must be strictly after {boundary.isoformat()}"
            )


@dataclass(frozen=True)
class ValidationWindow:
    start: datetime
    end: datetime
    event_count: int
    active_days: int
    complete: bool


def sequential_windows(
    candidate: Candidate,
    event_times: Sequence[datetime],
    *,
    window_days: int = 7,
) -> list[ValidationWindow]:
    if window_days < 1:
        raise ValueError("window_days must be positive")
    times = sorted(parse_utc(x) for x in event_times)
    enforce_future_only(candidate, times)
    if not times:
        return []

    first = candidate.spent_through.astimezone(UTC) + timedelta(microseconds=1)
    cursor = first
    final = times[-1] + timedelta(microseconds=1)
    out: list[ValidationWindow] = []
    while cursor < final:
        end = cursor + timedelta(days=window_days)
        selected = [x for x in times if cursor <= x < end]
        if selected:
            active_days = len({x.date() for x in selected})
            complete = (
                len(selected) >= candidate.minimum_events
                and active_days >= candidate.minimum_active_days
            )
            out.append(
                ValidationWindow(
                    start=cursor,
                    end=end,
                    event_count=len(selected),
                    active_days=active_days,
                    complete=complete,
                )
            )
        cursor = end
    return out


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    if any((not math.isfinite(p)) or p < 0 or p > 1 for p in p_values):
        raise ValueError("p-values must be finite values in [0, 1]")
    m = len(p_values)
    if not m:
        return []
    order = sorted(range(m), key=p_values.__getitem__)
    q = [1.0] * m
    running = 1.0
    for rank_from_end, idx in enumerate(reversed(order), start=1):
        rank = m - rank_from_end + 1
        candidate = p_values[idx] * m / rank
        running = min(running, candidate)
        q[idx] = min(1.0, running)
    return q


def oos_summary(returns_r: Sequence[float]) -> dict[str, float | int | None]:
    values = [float(x) for x in returns_r]
    if any(not math.isfinite(x) for x in values):
        raise ValueError("returns must be finite")
    n = len(values)
    if n == 0:
        return {"n": 0, "mean_r": None, "win_rate": None, "t_like": None}
    avg = mean(values)
    wins = sum(x > 0 for x in values) / n
    if n < 2:
        t_like = None
    else:
        sd = pstdev(values)
        t_like = None if sd == 0 else avg / (sd / math.sqrt(n))
    return {"n": n, "mean_r": avg, "win_rate": wins, "t_like": t_like}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def research_manifest(
    *,
    config: Mapping[str, Any],
    input_files: Sequence[str | Path],
    code_version: str,
    holdout_revealed: bool,
) -> dict[str, Any]:
    safe_config = dict(config)
    if not holdout_revealed:
        for key in list(safe_config):
            lowered = key.lower()
            if "holdout" in lowered or "final_test" in lowered:
                safe_config.pop(key)

    input_hashes = {Path(p).name: sha256_file(p) for p in input_files}
    payload = {
        "config": safe_config,
        "config_sha256": sha256_text(canonical_json(safe_config)),
        "inputs": input_hashes,
        "code_version": code_version,
        "holdout_revealed": bool(holdout_revealed),
    }
    payload["manifest_sha256"] = sha256_text(canonical_json(payload))
    return payload


def partition_records(
    records: Sequence[Mapping[str, Any]],
    *,
    timestamp_key: str,
    discovery_end: datetime,
    validation_end: datetime,
    holdout_end: datetime,
    reveal_holdout: bool = False,
) -> dict[str, list[Mapping[str, Any]] | bool]:
    discovery_end = parse_utc(discovery_end)
    validation_end = parse_utc(validation_end)
    holdout_end = parse_utc(holdout_end)
    if not discovery_end < validation_end < holdout_end:
        raise ValueError("require discovery_end < validation_end < holdout_end")

    discovery, validation, holdout = [], [], []
    for row in records:
        ts = parse_utc(row[timestamp_key])
        if ts < discovery_end:
            discovery.append(row)
        elif ts < validation_end:
            validation.append(row)
        elif ts < holdout_end:
            holdout.append(row)

    result: dict[str, list[Mapping[str, Any]] | bool] = {
        "discovery": discovery,
        "validation": validation,
        "holdout_revealed": bool(reveal_holdout),
    }
    if reveal_holdout:
        result["holdout"] = holdout
    return result
