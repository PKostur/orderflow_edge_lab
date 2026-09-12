from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .holdout_audit import verify_holdout_audit

UTC = timezone.utc


class TrialLedgerError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrialLedgerError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise TrialLedgerError(f"JSON must be an object: {path}")
    return value


def new_trial_ledger(*, family_name: str, alpha: float = 0.05, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(family_name, str) or not family_name.strip():
        raise TrialLedgerError("family_name must be nonempty")
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not 0 < float(alpha) < 1:
        raise TrialLedgerError("alpha must be between 0 and 1")
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise TrialLedgerError("timestamp must include timezone")
    ledger: dict[str, Any] = {
        "schema_version": 1,
        "family_name": family_name.strip(),
        "family_alpha": float(alpha),
        "created_at": timestamp.astimezone(UTC).isoformat(),
        "trials": [],
        "claims": {
            "holdout_access_counted": True,
            "multiple_testing_adjustment_required": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    ledger["manifest_sha256"] = _canonical_sha256(ledger)
    return ledger


def verify_trial_ledger(ledger: dict[str, Any]) -> bool:
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1:
        return False
    expected = ledger.get("manifest_sha256")
    if not _valid_sha256(expected):
        return False
    unsigned = dict(ledger)
    unsigned.pop("manifest_sha256", None)
    if _canonical_sha256(unsigned) != expected:
        return False
    alpha = ledger.get("family_alpha")
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not 0 < float(alpha) < 1:
        return False
    trials = ledger.get("trials")
    if not isinstance(trials, list):
        return False
    seen: set[tuple[str, str]] = set()
    for index, trial in enumerate(trials, start=1):
        if not isinstance(trial, dict) or trial.get("trial_number") != index:
            return False
        candidate = trial.get("candidate_id")
        spec = trial.get("candidate_spec_sha256")
        holdout = trial.get("holdout_audit_sha256")
        observations = trial.get("observations_sha256")
        if not isinstance(candidate, str) or not candidate or not _valid_sha256(spec) or not _valid_sha256(holdout) or not _valid_sha256(observations):
            return False
        identity = (str(spec), str(observations))
        if identity in seen:
            return False
        seen.add(identity)
        expected_alpha = float(alpha) / index
        if abs(float(trial.get("bonferroni_alpha", -1)) - expected_alpha) > 1e-15:
            return False
    claims = ledger.get("claims")
    if not isinstance(claims, dict):
        return False
    if claims.get("holdout_access_counted") is not True or claims.get("multiple_testing_adjustment_required") is not True:
        return False
    if any(claims.get(key) is not False for key in ("verified_out_of_sample_evidence", "profitable_edge_established", "live_order_transmission_supported")):
        return False
    return True


def append_holdout_trial(
    ledger: dict[str, Any],
    holdout_audit: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not verify_trial_ledger(ledger):
        raise TrialLedgerError("trial ledger is invalid")
    if not verify_holdout_audit(holdout_audit):
        raise TrialLedgerError("holdout audit is invalid")
    candidate_id = holdout_audit.get("candidate_id")
    spec_sha = holdout_audit.get("candidate_spec_sha256")
    observations = holdout_audit.get("observations")
    obs_sha = observations.get("sha256") if isinstance(observations, dict) else None
    holdout_sha = holdout_audit.get("manifest_sha256")
    if not isinstance(candidate_id, str) or not candidate_id or not _valid_sha256(spec_sha) or not _valid_sha256(obs_sha) or not _valid_sha256(holdout_sha):
        raise TrialLedgerError("holdout audit lacks required provenance")

    existing = list(ledger["trials"])
    identity = (str(spec_sha), str(obs_sha))
    if any((row.get("candidate_spec_sha256"), row.get("observations_sha256")) == identity for row in existing if isinstance(row, dict)):
        raise TrialLedgerError("this candidate specification and observation set were already counted")

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise TrialLedgerError("timestamp must include timezone")
    trial_number = len(existing) + 1
    alpha = float(ledger["family_alpha"])
    row = {
        "trial_number": trial_number,
        "recorded_at": timestamp.astimezone(UTC).isoformat(),
        "candidate_id": candidate_id,
        "candidate_spec_sha256": str(spec_sha),
        "holdout_audit_sha256": str(holdout_sha),
        "observations_sha256": str(obs_sha),
        "bonferroni_alpha": alpha / trial_number,
    }
    updated = dict(ledger)
    updated["trials"] = [*existing, row]
    updated["manifest_sha256"] = _canonical_sha256({k: v for k, v in updated.items() if k != "manifest_sha256"})
    return updated


def append_holdout_trial_files(ledger_path: str | Path, holdout_audit_path: str | Path) -> dict[str, Any]:
    ledger_path = Path(ledger_path)
    holdout_audit_path = Path(holdout_audit_path)
    ledger = _load_object(ledger_path)
    holdout = _load_object(holdout_audit_path)
    return append_holdout_trial(ledger, holdout)
