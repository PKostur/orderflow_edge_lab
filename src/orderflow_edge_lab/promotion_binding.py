from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .candidate_freeze import reverify_candidate_freeze, verify_candidate_freeze
from .holdout_audit import verify_holdout_audit
from .promotion import PromotionAssessment, assess_candidate_promotion_files
from .trial_ledger import verify_trial_ledger


def _load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload


def _trial_ledger_binding_reasons(
    ledger: dict[str, Any],
    holdout: dict[str, Any],
    candidate_id: str,
) -> tuple[str, ...]:
    if not verify_trial_ledger(ledger):
        return ("trial_ledger_manifest_invalid",)

    observations = holdout.get("observations")
    observation_sha = observations.get("sha256") if isinstance(observations, dict) else None
    candidate_spec_sha = holdout.get("candidate_spec_sha256")
    holdout_sha = holdout.get("manifest_sha256")

    trials = ledger.get("trials")
    if not isinstance(trials, list):
        return ("trial_ledger_trials_missing",)

    matching = [
        row
        for row in trials
        if isinstance(row, dict)
        and row.get("candidate_id") == candidate_id
        and row.get("candidate_spec_sha256") == candidate_spec_sha
        and row.get("holdout_audit_sha256") == holdout_sha
        and row.get("observations_sha256") == observation_sha
    ]
    if len(matching) != 1:
        return ("holdout_trial_not_uniquely_counted",)

    row = matching[0]
    trial_number = row.get("trial_number")
    family_alpha = ledger.get("family_alpha")
    bonferroni_alpha = row.get("bonferroni_alpha")
    if (
        not isinstance(trial_number, int)
        or trial_number <= 0
        or not isinstance(family_alpha, (int, float))
        or isinstance(family_alpha, bool)
        or not isinstance(bonferroni_alpha, (int, float))
        or isinstance(bonferroni_alpha, bool)
        or abs(float(bonferroni_alpha) - float(family_alpha) / trial_number) > 1e-15
    ):
        return ("trial_ledger_adjustment_invalid",)

    return ()


def assess_bound_promotion(
    validation_report_path: str | Path,
    candidate_id: str,
    economics_path: str | Path,
    candidate_freeze_path: str | Path,
    holdout_audit_path: str | Path,
    trial_ledger_path: str | Path,
) -> tuple[PromotionAssessment, tuple[str, ...]]:
    """Run promotion plus immutable holdout and trial-accounting bindings.

    A structurally positive validation report is not sufficient by itself. The exact
    observation bytes must be proven to lie inside the predeclared holdout interval,
    belong to the exact registry frozen before holdout inspection, and be recorded
    exactly once in the experiment-family trial ledger used for multiple-testing
    accounting.
    """
    assessment = assess_candidate_promotion_files(
        validation_report_path,
        candidate_id,
        economics_path,
    )
    reasons = list(assessment.reasons)

    report = _load_object(validation_report_path, "validation report")
    candidate_freeze = _load_object(candidate_freeze_path, "candidate freeze")
    holdout = _load_object(holdout_audit_path, "holdout audit")
    trial_ledger = _load_object(trial_ledger_path, "trial ledger")

    if not verify_candidate_freeze(candidate_freeze):
        reasons.append("candidate_freeze_manifest_invalid")
    else:
        ok, freeze_reasons = reverify_candidate_freeze(candidate_freeze)
        if not ok:
            reasons.extend(freeze_reasons)

    if not verify_holdout_audit(holdout):
        reasons.append("holdout_audit_manifest_invalid")
    else:
        if holdout.get("candidate_id") != candidate_id:
            reasons.append("holdout_candidate_mismatch")
        holdout_freeze = holdout.get("candidate_freeze")
        if not isinstance(holdout_freeze, dict):
            reasons.append("holdout_candidate_freeze_missing")
        else:
            if holdout_freeze.get("manifest_sha256") != candidate_freeze.get("manifest_sha256"):
                reasons.append("holdout_candidate_freeze_mismatch")
            registry = candidate_freeze.get("registry")
            registry_sha = registry.get("sha256") if isinstance(registry, dict) else None
            if holdout_freeze.get("registry_sha256") != registry_sha:
                reasons.append("holdout_registry_sha256_mismatch")
            if report.get("registry_sha256") != registry_sha:
                reasons.append("validation_registry_sha256_mismatch")

        observations = holdout.get("observations")
        if not isinstance(observations, dict):
            reasons.append("holdout_observations_missing")
        elif observations.get("sha256") != report.get("observations_sha256"):
            reasons.append("validation_observations_sha256_mismatch")

        frozen_rows = candidate_freeze.get("candidates")
        matches = [
            row for row in frozen_rows
            if isinstance(frozen_rows, list)
            and isinstance(row, dict)
            and row.get("candidate_id") == candidate_id
        ] if isinstance(frozen_rows, list) else []
        if len(matches) != 1:
            reasons.append("candidate_not_uniquely_frozen")
        elif holdout.get("candidate_spec_sha256") != matches[0].get("spec_sha256"):
            reasons.append("holdout_candidate_spec_mismatch")

        claims = holdout.get("claims")
        if not isinstance(claims, dict) or claims.get("holdout_partition_respected") is not True:
            reasons.append("holdout_partition_not_verified")
        if not isinstance(claims, dict) or claims.get("source_bytes_reverified") is not True:
            reasons.append("holdout_source_bytes_not_reverified")

    reasons.extend(_trial_ledger_binding_reasons(trial_ledger, holdout, candidate_id))

    unique = tuple(dict.fromkeys(reasons))
    return assessment, unique
