from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .runtime_identity import runtime_identity
from .runtime_snapshot import _load_state, _runtime_blockers, _sha256_payload

UTC = timezone.utc


class SessionAuditError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    supplied = snapshot.get("snapshot_sha256")
    if not isinstance(supplied, str) or len(supplied) != 64:
        raise SessionAuditError("runtime snapshot hash is missing or invalid")
    unsigned = dict(snapshot)
    unsigned.pop("snapshot_sha256", None)
    if _sha256_payload(unsigned) != supplied:
        raise SessionAuditError("runtime snapshot manifest was modified")
    schema = snapshot.get("schema_version")
    if schema not in (1, 2):
        raise SessionAuditError("unsupported runtime snapshot schema")
    boundary = snapshot.get("journal_bytes")
    if isinstance(boundary, bool) or not isinstance(boundary, int) or boundary < 0:
        raise SessionAuditError("runtime snapshot lacks an append-only journal byte boundary")
    if schema == 2:
        identity = snapshot.get("runtime_identity")
        identity_sha = snapshot.get("runtime_identity_sha256")
        if (
            not isinstance(identity, Mapping)
            or not isinstance(identity_sha, str)
            or len(identity_sha) != 64
            or _sha256_payload(identity) != identity_sha
        ):
            raise SessionAuditError("runtime snapshot build identity is invalid")


def _parse_appended_events(raw: bytes) -> tuple[int, dict[str, int]]:
    if not raw:
        return 0, {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SessionAuditError("appended journal bytes are not UTF-8") from exc
    if text and not text.endswith("\n"):
        raise SessionAuditError("journal ends with an incomplete record")
    counts: dict[str, int] = {}
    total = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SessionAuditError(f"invalid appended journal JSON at relative line {line_number}") from exc
        if not isinstance(row, Mapping):
            raise SessionAuditError("appended journal record must be an object")
        event = row.get("event_type", row.get("event", row.get("type", "unknown")))
        key = str(event)
        counts[key] = counts.get(key, 0) + 1
        total += 1
    return total, dict(sorted(counts.items()))


def close_paper_session(
    snapshot: Mapping[str, Any],
    state_path: str | Path,
    journal_path: str | Path,
    *,
    now: datetime | None = None,
    require_flat: bool = True,
) -> dict[str, Any]:
    """Audit a paper session against its immutable pre-session snapshot.

    The closeout proves that journal history present at session start is unchanged and
    reports only records appended after that boundary. Schema v2 snapshots also bind
    the closeout to the exact package source and Python runtime used at session start.
    This does not establish strategy profitability and does not enable live orders.
    """
    if not isinstance(snapshot, Mapping):
        raise SessionAuditError("runtime snapshot must be an object")
    _validate_snapshot(snapshot)

    state_path = Path(state_path)
    journal_path = Path(journal_path)
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    state = _load_state(state_path)
    try:
        journal = journal_path.read_bytes()
    except OSError as exc:
        raise SessionAuditError("paper journal cannot be read") from exc

    boundary = int(snapshot["journal_bytes"])
    blockers: list[str] = []
    if len(journal) < boundary:
        blockers.append("journal_truncated")
        prefix_ok = False
        appended = b""
    else:
        prefix = journal[:boundary]
        prefix_ok = _sha256_bytes(prefix) == snapshot.get("journal_sha256")
        if not prefix_ok:
            blockers.append("journal_history_rewritten")
        appended = journal[boundary:]

    appended_count, event_counts = _parse_appended_events(appended)

    start_revision = snapshot.get("state_revision")
    end_revision = state.get("revision")
    if isinstance(start_revision, bool) or not isinstance(start_revision, int):
        raise SessionAuditError("runtime snapshot state revision is invalid")
    if isinstance(end_revision, bool) or not isinstance(end_revision, int):
        raise SessionAuditError("execution state revision is invalid")
    if end_revision < start_revision:
        blockers.append("state_revision_regressed")

    engine_config = state.get("engine_config")
    if not isinstance(engine_config, Mapping) or _sha256_payload(engine_config) != snapshot.get("engine_config_sha256"):
        blockers.append("engine_config_changed")
    if state.get("trading_day") != snapshot.get("trading_day"):
        blockers.append("trading_day_changed")

    runtime_identity_verified: bool | None = None
    if snapshot.get("schema_version") == 2:
        identity = runtime_identity()
        identity_sha = _sha256_payload(identity)
        runtime_identity_verified = (
            identity == snapshot.get("runtime_identity")
            and identity_sha == snapshot.get("runtime_identity_sha256")
        )
        if not runtime_identity_verified:
            blockers.append("runtime_identity_changed")

    try:
        runtime_blockers = _runtime_blockers(state, state_path, journal_path, current)
    except (OSError, ValueError, TypeError, KeyError):
        runtime_blockers = ["runtime_audit_failed"]
    blockers.extend(runtime_blockers)

    pending_ids = sorted(state.get("pending", {}))
    position_ids = sorted(state.get("positions", {}))
    if require_flat and (pending_ids or position_ids):
        blockers.append("session_ended_active")

    blockers = sorted(set(blockers))
    payload: dict[str, Any] = {
        "schema_version": 2,
        "closed_at": current.isoformat(),
        "start_snapshot_sha256": snapshot["snapshot_sha256"],
        "start_snapshot_schema_version": snapshot.get("schema_version"),
        "start_journal_bytes": boundary,
        "end_journal_bytes": len(journal),
        "end_journal_sha256": _sha256_bytes(journal),
        "journal_prefix_verified": prefix_ok,
        "runtime_identity_verified": runtime_identity_verified,
        "appended_bytes": max(0, len(journal) - boundary),
        "appended_records": appended_count,
        "appended_event_counts": event_counts,
        "start_state_revision": start_revision,
        "end_state_revision": end_revision,
        "state_revision_delta": end_revision - start_revision,
        "end_journal_head": state.get("journal_head"),
        "pending_ids": pending_ids,
        "position_ids": position_ids,
        "require_flat": require_flat,
        "verified": not blockers,
        "blockers": blockers,
        "ready_for_paper": not blockers,
        "ready_for_live": False,
        "live_order_transmission_supported": False,
        "verified_out_of_sample_evidence": False,
        "profitable_edge_established": False,
    }
    payload["closeout_sha256"] = _sha256_payload(payload)
    return payload


def verify_session_closeout(closeout: Mapping[str, Any]) -> bool:
    supplied = closeout.get("closeout_sha256") if isinstance(closeout, Mapping) else None
    if not isinstance(supplied, str) or len(supplied) != 64:
        return False
    unsigned = dict(closeout)
    unsigned.pop("closeout_sha256", None)
    return _sha256_payload(unsigned) == supplied
