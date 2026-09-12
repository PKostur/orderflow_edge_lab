from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .execution import StateCorruptionError, _canonical, validate_execution_state
from .reliability import deployment_readiness

UTC = timezone.utc


class RuntimeSnapshotError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise RuntimeSnapshotError(f"required runtime file missing: {path}")
    return _sha256_bytes(path.read_bytes())


def _sha256_payload(value: object) -> str:
    return _sha256_bytes(_canonical(value).encode("utf-8"))


def _load_state(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        validate_execution_state(raw)
    except (OSError, ValueError, TypeError, KeyError, StateCorruptionError) as exc:
        raise RuntimeSnapshotError("execution state is not valid") from exc
    if not isinstance(raw, dict):
        raise RuntimeSnapshotError("execution state must be an object")
    return raw


def _runtime_blockers(
    state: Mapping[str, Any],
    state_path: Path,
    journal_path: Path,
    current: datetime,
) -> list[str]:
    readiness = deployment_readiness(state_path, journal_path)
    blockers: list[str] = []
    if not readiness.ready_for_paper:
        blockers.append("base_readiness_failed")
    if state.get("kill_switch") is True:
        blockers.append("kill_switch_engaged")
    now_epoch = current.timestamp()
    for pending in state.get("pending", {}).values():
        expiry = pending.get("expires_at")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
            blockers.append("invalid_pending_expiry")
            break
        if float(expiry) <= now_epoch:
            blockers.append("expired_pending_intents")
            break
    return blockers


def create_runtime_snapshot(
    state_path: str | Path,
    journal_path: str | Path,
    *,
    now: datetime | None = None,
    require_flat: bool = True,
) -> dict[str, Any]:
    """Freeze exact paper runtime bytes before a controlled paper session.

    This is operational provenance only. It does not establish an out-of-sample edge
    and it never enables broker or exchange transmission.
    """
    state_path = Path(state_path)
    journal_path = Path(journal_path)
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    state = _load_state(state_path)
    blockers = _runtime_blockers(state, state_path, journal_path, current)
    if blockers:
        raise RuntimeSnapshotError("runtime audit failed: " + ",".join(blockers))

    pending_ids = sorted(state["pending"])
    position_ids = sorted(state["positions"])
    if require_flat and (pending_ids or position_ids):
        raise RuntimeSnapshotError("clean session snapshot requires no pending proposals or open positions")

    engine_config = state.get("engine_config")
    if not isinstance(engine_config, Mapping):
        raise RuntimeSnapshotError("execution configuration is not bound")

    journal_bytes = journal_path.read_bytes()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": current.isoformat(),
        "state_sha256": _sha256_file(state_path),
        "journal_sha256": _sha256_bytes(journal_bytes),
        "journal_bytes": len(journal_bytes),
        "state_revision": state.get("revision"),
        "journal_head": state.get("journal_head"),
        "engine_config_sha256": _sha256_payload(engine_config),
        "trading_day": state["trading_day"],
        "pending_ids": pending_ids,
        "position_ids": position_ids,
        "require_flat": require_flat,
        "ready_for_paper": True,
        "ready_for_live": False,
        "live_order_transmission_supported": False,
        "verified_out_of_sample_evidence": False,
        "profitable_edge_established": False,
    }
    payload["snapshot_sha256"] = _sha256_payload(payload)
    return payload


def verify_runtime_snapshot(
    snapshot: Mapping[str, Any],
    state_path: str | Path,
    journal_path: str | Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify that runtime files still match a previously frozen snapshot."""
    if not isinstance(snapshot, Mapping):
        raise RuntimeSnapshotError("runtime snapshot must be an object")
    supplied = snapshot.get("snapshot_sha256")
    if not isinstance(supplied, str) or len(supplied) != 64:
        raise RuntimeSnapshotError("runtime snapshot hash is missing or invalid")
    unsigned = dict(snapshot)
    unsigned.pop("snapshot_sha256", None)
    if _sha256_payload(unsigned) != supplied:
        raise RuntimeSnapshotError("runtime snapshot manifest was modified")
    if snapshot.get("schema_version") != 1:
        raise RuntimeSnapshotError("unsupported runtime snapshot schema")

    state_path = Path(state_path)
    journal_path = Path(journal_path)
    state = _load_state(state_path)
    current = (now or datetime.now(tz=UTC)).astimezone(UTC)
    blockers = _runtime_blockers(state, state_path, journal_path, current)

    engine_config = state.get("engine_config")
    checks = {
        "state_sha256": _sha256_file(state_path) == snapshot.get("state_sha256"),
        "journal_sha256": _sha256_file(journal_path) == snapshot.get("journal_sha256"),
        "state_revision": state.get("revision") == snapshot.get("state_revision"),
        "journal_head": state.get("journal_head") == snapshot.get("journal_head"),
        "engine_config_sha256": isinstance(engine_config, Mapping)
        and _sha256_payload(engine_config) == snapshot.get("engine_config_sha256"),
        "pending_ids": sorted(state["pending"]) == list(snapshot.get("pending_ids", [])),
        "position_ids": sorted(state["positions"]) == list(snapshot.get("position_ids", [])),
        "runtime_operational": not blockers,
    }
    if "journal_bytes" in snapshot:
        checks["journal_bytes"] = journal_path.stat().st_size == snapshot.get("journal_bytes")
    if snapshot.get("require_flat") is True:
        checks["flat_runtime"] = not state["pending"] and not state["positions"]

    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": 1,
        "verified_at": current.isoformat(),
        "snapshot_sha256": supplied,
        "verified": not failed,
        "failed_checks": failed,
        "runtime_blockers": blockers,
        "checks": checks,
        "ready_for_live": False,
        "live_order_transmission_supported": False,
        "profitable_edge_established": False,
    }
