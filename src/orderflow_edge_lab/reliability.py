from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from .execution import HashChainJournal, StateCorruptionError, validate_execution_state

UTC = timezone.utc


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
    return HealthCheck("execution_state", True, "parseable and structurally valid")


def _check_journal(path: Path) -> HealthCheck:
    try:
        HashChainJournal.verify(path)
    except (StateCorruptionError, OSError, ValueError, TypeError, AttributeError) as exc:
        return HealthCheck("journal_chain", False, f"journal verification failed: {type(exc).__name__}")
    return HealthCheck("journal_chain", True, "hash chain valid")


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
    checks = [
        _check_state(Path(state_path)),
        _check_journal(Path(journal_path)),
        _check_fresh_validation(Path(validation_manifest) if validation_manifest else None),
        *additional_checks,
    ]
    operational = all(c.passed for i, c in enumerate(checks) if i != 2)
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
