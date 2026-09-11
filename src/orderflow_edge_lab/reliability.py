from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Iterable

from .execution import (
    HashChainJournal,
    StateCorruptionError,
    _canonical,
    validate_execution_state,
    reconcile_execution,
)

UTC = timezone.utc
ADMINISTRATIVE_EVENTS = {"engine_initialized", "legacy_state_migrated", "configuration_bound"}


@dataclass(frozen=True)
class HealthCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    ready_for_paper: bool
    ready_for_live: bool
    checks: tuple[HealthCheck, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "ready_for_paper": self.ready_for_paper,
            "ready_for_live": self.ready_for_live,
            "checks": [c.__dict__ for c in self.checks],
        }


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise StateCorruptionError("journal timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateCorruptionError("journal timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise StateCorruptionError("journal timestamp must be timezone aware")
    return parsed.astimezone(UTC)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _sha256_payload(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def audit_journal_semantics(path: str | Path) -> dict[str, int]:
    """Validate event ordering and event-to-state invariants in a durable paper journal.

    The hash chain proves bytes were not silently changed after the fact. This audit
    adds a separate semantic layer so a cryptographically valid but internally
    implausible event history still fails deployment readiness.
    """
    records = HashChainJournal.records(path)
    if not records:
        raise StateCorruptionError("journal has no durable checkpoints")

    previous_time: datetime | None = None
    previous_revision = 0
    checked = 0

    for lineno, row in enumerate(records, start=1):
        event_type = row.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise StateCorruptionError(f"journal event type missing at line {lineno}")
        when = _parse_utc(row.get("timestamp"))
        if event_type not in ADMINISTRATIVE_EVENTS:
            if previous_time is not None and when < previous_time:
                raise StateCorruptionError(f"journal timestamp regression at line {lineno}")
            previous_time = when

        payload = row.get("payload")
        if not isinstance(payload, dict):
            raise StateCorruptionError(f"journal payload must be an object at line {lineno}")
        state = payload.get("state_after")
        if state is None:
            if previous_revision:
                raise StateCorruptionError(f"event lacks checkpoint after checkpoint history at line {lineno}")
            continue
        validate_execution_state(state)
        revision = state.get("revision")
        if revision != previous_revision + 1:
            raise StateCorruptionError(f"nonconsecutive state revision at line {lineno}")
        previous_revision = revision

        seen = state["seen_intents"]
        if len(seen) != len(set(seen)):
            raise StateCorruptionError(f"duplicate seen intent at line {lineno}")

        intent_id = payload.get("intent_id")
        if event_type == "intent_submitted":
            if not isinstance(intent_id, str) or intent_id not in state["pending"] or intent_id not in seen:
                raise StateCorruptionError(f"submitted intent not represented in state at line {lineno}")
        elif event_type in {"intent_rejected", "intent_expired"}:
            if not isinstance(intent_id, str) or intent_id in state["pending"]:
                raise StateCorruptionError(f"resolved intent remains pending at line {lineno}")
        elif event_type == "pending_intents_expired":
            intent_ids = payload.get("intent_ids")
            if not isinstance(intent_ids, list) or not all(isinstance(x, str) for x in intent_ids):
                raise StateCorruptionError(f"invalid expired intent list at line {lineno}")
            if any(x in state["pending"] for x in intent_ids):
                raise StateCorruptionError(f"expired intent remains pending at line {lineno}")
        elif event_type == "paper_position_opened":
            opened_id = payload.get("intent_id")
            if not isinstance(opened_id, str) or opened_id not in state["positions"] or opened_id in state["pending"]:
                raise StateCorruptionError(f"opened position not represented in state at line {lineno}")
            if opened_id not in seen:
                raise StateCorruptionError(f"opened position has no seen intent at line {lineno}")
        elif event_type == "paper_position_closed":
            closed_id = payload.get("intent_id")
            if not isinstance(closed_id, str) or closed_id in state["positions"]:
                raise StateCorruptionError(f"closed position remains open at line {lineno}")
        elif event_type == "kill_switch_engaged":
            if state["kill_switch"] is not True:
                raise StateCorruptionError(f"kill switch event/state mismatch at line {lineno}")
            cancelled = payload.get("cancelled_intents", [])
            if not isinstance(cancelled, list) or any(x in state["pending"] for x in cancelled):
                raise StateCorruptionError(f"kill switch left cancelled intents pending at line {lineno}")
        elif event_type == "kill_switch_released":
            if state["kill_switch"] is not False:
                raise StateCorruptionError(f"kill switch release/state mismatch at line {lineno}")
        elif event_type == "trading_day_rolled":
            if payload.get("trading_day") != state["trading_day"]:
                raise StateCorruptionError(f"trading day event/state mismatch at line {lineno}")

        checked += 1

    return {"records": len(records), "checkpoints": checked, "last_revision": previous_revision}


def _check_state(path: Path) -> HealthCheck:
    if not path.exists():
        return HealthCheck("execution_state", False, "state file missing")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return HealthCheck("execution_state", False, f"unreadable: {type(exc).__name__}")
    try:
        validate_execution_state(state)
    except StateCorruptionError as exc:
        return HealthCheck("execution_state", False, str(exc))
    if state["kill_switch"] or state["equity"] <= 0:
        return HealthCheck("execution_state", False, "execution halted by kill switch or nonpositive equity")
    if "engine_config" not in state:
        return HealthCheck("execution_state", False, "execution configuration is not bound; explicit migration required")
    return HealthCheck("execution_state", True, "parseable and structurally valid")


def _check_pending_approval_bindings(path: Path) -> HealthCheck:
    """Fail paper readiness when any pending proposal is not fully approval-bound."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        validate_execution_state(state)
        engine_config_sha256 = _sha256_payload(state["engine_config"])
        for intent_id, pending in state["pending"].items():
            token = pending.get("approval_token")
            binding = pending.get("approval_binding")
            if not _is_sha256(token) or not isinstance(binding, dict):
                raise ValueError(f"pending proposal {intent_id} lacks approval binding")
            if _sha256_payload(binding) != token:
                raise ValueError(f"pending proposal {intent_id} has corrupt approval token")
            if binding.get("intent_id") != intent_id:
                raise ValueError(f"pending proposal {intent_id} binding identity mismatch")
            for field in ("intent", "contracts", "submitted_at", "expires_at"):
                if binding.get(field) != pending.get(field):
                    raise ValueError(f"pending proposal {intent_id} binding terms mismatch")
            if not _is_sha256(binding.get("evidence_sha256")):
                raise ValueError(f"pending proposal {intent_id} evidence digest invalid")
            if binding.get("engine_config_sha256") != engine_config_sha256:
                raise ValueError(f"pending proposal {intent_id} configuration digest mismatch")
            market = binding.get("submitted_market")
            if not isinstance(market, dict) or set(market) != {"symbol", "bid", "ask", "timestamp"}:
                raise ValueError(f"pending proposal {intent_id} market binding invalid")
            if market.get("symbol") != pending["intent"].get("symbol"):
                raise ValueError(f"pending proposal {intent_id} market symbol mismatch")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StateCorruptionError) as exc:
        return HealthCheck("approval_bindings", False, f"approval binding verification failed: {type(exc).__name__}: {exc}")
    return HealthCheck("approval_bindings", True, "all pending proposals are fully approval-bound")


def _check_journal(path: Path) -> HealthCheck:
    try:
        HashChainJournal.verify(path)
    except (StateCorruptionError, OSError, ValueError, TypeError, AttributeError) as exc:
        return HealthCheck("journal_chain", False, f"journal verification failed: {type(exc).__name__}")
    return HealthCheck("journal_chain", True, "hash chain valid")


def _check_journal_semantics(path: Path) -> HealthCheck:
    try:
        stats = audit_journal_semantics(path)
    except (StateCorruptionError, OSError, ValueError, TypeError, AttributeError) as exc:
        return HealthCheck("journal_semantics", False, f"semantic audit failed: {type(exc).__name__}: {exc}")
    return HealthCheck(
        "journal_semantics",
        True,
        f"event ordering and state invariants valid across {stats['records']} records",
    )


def _check_checkpoint(state_path: Path, journal_path: Path) -> HealthCheck:
    try:
        _, recovery = reconcile_execution(state_path, journal_path)
        if recovery:
            return HealthCheck("state_journal_checkpoint", False, "verified journal ahead; restart engine to recover")
    except (StateCorruptionError, OSError, ValueError, TypeError, AttributeError) as exc:
        return HealthCheck("state_journal_checkpoint", False, f"checkpoint verification failed: {type(exc).__name__}")
    return HealthCheck("state_journal_checkpoint", True, "state matches durable journal checkpoint")


def _check_fresh_validation(manifest_path: Path | None) -> HealthCheck:
    if manifest_path is None or not manifest_path.exists():
        return HealthCheck("out_of_sample_evidence", False, "no validation manifest supplied")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return HealthCheck("out_of_sample_evidence", False, f"manifest unreadable: {type(exc).__name__}")
    if not isinstance(data, dict):
        return HealthCheck("out_of_sample_evidence", False, "manifest must be an object")
    required = {"dataset_sha256", "config_sha256", "period_start", "period_end", "frozen_before_period"}
    missing = sorted(required - set(data))
    if missing:
        return HealthCheck("out_of_sample_evidence", False, "manifest missing: " + ",".join(missing))
    if data.get("frozen_before_period") is not True:
        return HealthCheck("out_of_sample_evidence", False, "parameters were not certified frozen before validation")
    return HealthCheck("out_of_sample_evidence", False,
                       "manifest assertions alone cannot verify dataset freshness, freeze provenance, or an edge")


def deployment_readiness(
    state_path: str | Path,
    journal_path: str | Path,
    *,
    validation_manifest: str | Path | None = None,
    additional_checks: Iterable[HealthCheck] = (),
) -> ReadinessReport:
    state = Path(state_path)
    journal = Path(journal_path)
    checks = [
        _check_state(state),
        _check_pending_approval_bindings(state),
        _check_journal(journal),
        _check_journal_semantics(journal),
        _check_fresh_validation(Path(validation_manifest) if validation_manifest else None),
        _check_checkpoint(state, journal),
        *additional_checks,
    ]
    operational = all(c.passed for c in checks if c.name != "out_of_sample_evidence")
    # Live remains deliberately impossible in this repository. A future broker
    # adapter requires a separate, explicit design and reconciliation gate.
    return ReadinessReport(ready_for_paper=operational, ready_for_live=False, checks=tuple(checks))


def write_readiness_report(report: ReadinessReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **report.as_dict(),
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }
    tmp = target.with_suffix(target.suffix + ".partial")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(target)
