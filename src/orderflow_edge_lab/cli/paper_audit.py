from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from orderflow_edge_lab.execution import StateCorruptionError, validate_execution_state
from orderflow_edge_lab.reliability import audit_journal_semantics, deployment_readiness


UTC = timezone.utc


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_expiry(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateCorruptionError("pending expiry must be numeric")
    return float(value)


def audit_paper_runtime(
    state_path: Path,
    journal_path: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Produce a read-only operational audit for approval-bound paper execution."""
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    readiness = deployment_readiness(state_path, journal_path)
    result: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": current.isoformat(),
        "ready_for_paper_base": readiness.ready_for_paper,
        "ready_for_live": False,
        "readiness": readiness.as_dict(),
        "state_sha256": _sha256_file(state_path),
        "journal_sha256": _sha256_file(journal_path),
        "live_order_transmission_supported": False,
    }

    if not state_path.exists():
        result.update(
            operational_ready=False,
            blockers=["state_file_missing"],
            pending_count=0,
            position_count=0,
        )
        return result

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        validate_execution_state(state)
        journal_stats = audit_journal_semantics(journal_path)
    except (OSError, ValueError, TypeError, KeyError, StateCorruptionError) as exc:
        result.update(
            operational_ready=False,
            blockers=["state_or_journal_invalid"],
            audit_error=f"{type(exc).__name__}: {exc}",
        )
        return result

    now_epoch = current.timestamp()
    expired: list[str] = []
    seconds_remaining: dict[str, float] = {}
    for intent_id, pending in state["pending"].items():
        expiry = _parse_expiry(pending.get("expires_at"))
        remaining = expiry - now_epoch
        seconds_remaining[intent_id] = remaining
        if remaining <= 0:
            expired.append(intent_id)

    blockers: list[str] = []
    if not readiness.ready_for_paper:
        blockers.append("base_readiness_failed")
    if expired:
        blockers.append("expired_pending_intents")
    if state["kill_switch"]:
        blockers.append("kill_switch_engaged")

    result.update(
        operational_ready=not blockers,
        blockers=blockers,
        kill_switch=state["kill_switch"],
        equity=state["equity"],
        realized_pnl_today=state["realized_pnl_today"],
        trades_today=state["trades_today"],
        trading_day=state["trading_day"],
        revision=state.get("revision"),
        journal_head=state.get("journal_head"),
        pending_count=len(state["pending"]),
        pending_ids=sorted(state["pending"]),
        expired_pending_ids=sorted(expired),
        approval_seconds_remaining=seconds_remaining,
        position_count=len(state["positions"]),
        position_ids=sorted(state["positions"]),
        journal_stats=journal_stats,
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only operational audit for the local approval-bound paper engine. "
            "Checks durable state, journal semantics, approval expiry and kill-switch state."
        )
    )
    parser.add_argument("--state", default="runtime/paper-state.json")
    parser.add_argument("--journal", default="runtime/paper-journal.jsonl")
    parser.add_argument("--output", help="Optional JSON audit artifact")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit_paper_runtime(Path(args.state), Path(args.journal))
    except (OSError, ValueError, TypeError, KeyError, StateCorruptionError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2
    payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report.get("operational_ready") else 2


if __name__ == "__main__":
    raise SystemExit(main())
