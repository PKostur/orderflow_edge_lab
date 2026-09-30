"""Prospective review clock: elapsed-time observability for preregistered watches.

This module is an **observability layer only**. It computes calendar facts
(elapsed days since a frozen prospective boundary, remaining days to a
predeclared review gate) and nothing else. It never inspects strategy PnL,
never computes pass/fail verdicts, and never gates merges by itself: verdicts
remain the exclusive responsibility of the frozen per-watch workflows.

See ``config/prospective_review_clock_v1.json`` for the frozen watch list.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = Path("config/prospective_review_clock_v1.json")


class ReviewClockError(ValueError):
    """Raised when the clock configuration is malformed."""


def _require(value: Any, key: str, context: str) -> Any:
    if not isinstance(value, dict) or key not in value:
        raise ReviewClockError(f"{context}: missing key {key!r}")
    return value[key]


def parse_utc(value: str, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ReviewClockError(f"{context}: invalid UTC timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise ReviewClockError(f"{context}: timestamp must carry a UTC offset")
    return parsed.astimezone(timezone.utc)


def load_clock_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewClockError(f"clock config is not valid JSON: {exc}") from exc
    _require(payload, "watches", "clock config")
    watches = payload["watches"]
    if not isinstance(watches, list) or not watches:
        raise ReviewClockError("clock config: 'watches' must be a non-empty list")
    for index, watch in enumerate(watches):
        context = f"clock config watch[{index}]"
        _require(watch, "watch_id", context)
        _require(watch, "prospective_start_utc", context)
        gate = _require(watch, "review_gate", context)
        _require(gate, "type", context)
    return payload


def review_target(watch: dict[str, Any]) -> datetime | None:
    """Return the earliest calendar time the review gate may mature, if derivable.

    Only gates with a pure calendar-days definition produce a derivable target.
    Batch/signal-count gates mature when the frozen batch pipeline observes the
    required independent counts, which this module deliberately cannot compute.
    """

    gate = watch.get("review_gate", {})
    if gate.get("type") != "calendar_days":
        return None
    minimum_days = gate.get("minimum_days")
    if not isinstance(minimum_days, int) or minimum_days < 0:
        raise ReviewClockError(
            f"{watch.get('watch_id', '?')}: calendar_days gate needs a non-negative integer minimum_days"
        )
    start = parse_utc(watch["prospective_start_utc"], watch["watch_id"])
    from datetime import timedelta

    return start + timedelta(days=minimum_days)


def clock_report(
    config_path: Path | str = DEFAULT_CONFIG,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic, hash-free descriptive report of watch clocks."""

    payload = load_clock_config(config_path)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    watches: list[dict[str, Any]] = []
    for watch in payload["watches"]:
        watch_id = watch["watch_id"]
        start = parse_utc(watch["prospective_start_utc"], watch_id)
        target = review_target(watch)
        elapsed_days = (moment - start).total_seconds() / 86400.0

        entry: dict[str, Any] = {
            "watch_id": watch_id,
            "priority": watch.get("priority"),
            "terminal_state": watch.get("terminal_state"),
            "terminal_review_utc": watch.get("terminal_review_utc"),
            "terminal_note": watch.get("terminal_note"),
            "open_watch": watch.get("terminal_state") is None,
            "family": watch.get("family"),
            "prospective_start_utc": start.isoformat().replace("+00:00", "Z"),
            "elapsed_days": round(elapsed_days, 4),
            "started": moment >= start,
            "review_gate": watch.get("review_gate", {}),
            "review_gate_type": watch.get("review_gate", {}).get("type"),
            "counting_authority": watch.get(
                "batch_counting", "frozen per-watch forward workflow"
            ),
            "canonical_artifacts": watch.get("canonical_artifacts", []),
        }
        if target is not None:
            entry["earliest_review_utc"] = target.isoformat().replace("+00:00", "Z")
            entry["days_until_earliest_review"] = round(
                max(0.0, (target - moment).total_seconds() / 86400.0), 4
            )
            entry["review_window_matured"] = moment >= target
        else:
            entry["earliest_review_utc"] = None
            entry["review_window_matured"] = None
            entry["note"] = (
                "gate requires frozen-pipeline batch/signal counts; this clock "
                "reports calendar facts only"
            )
        watches.append(entry)

    derivable = [w for w in watches if w["review_window_matured"] is not None]
    open_watches = [w for w in watches if w["open_watch"]]
    return {
        "schema_version": 1,
        "protocol_name": payload.get("protocol_name", "prospective-review-clock"),
        "status": "observability_only",
        "generated_at_utc": moment.isoformat().replace("+00:00", "Z"),
        "watch_count": len(watches),
        "watches": watches,
        "summary": {
            "open_watch_count": len(open_watches),
            "terminal_watch_count": len(watches) - len(open_watches),
            "watches_with_derivable_review_target": len(derivable),
            "watches_with_matured_review_window": sum(
                1 for w in derivable if w["review_window_matured"]
            ),
            "all_windows_still_accumulating": not any(
                w["review_window_matured"] for w in derivable
            ),
            "all_open_windows_still_accumulating": not any(
                w["review_window_matured"] for w in derivable if w["open_watch"]
            ),
        },
        "claims": {
            "computes_strategy_verdicts": False,
            "inspects_strategy_pnl": False,
            "promotes_any_strategy": False,
            "live_order_transmission_supported": False,
        },
    }
