from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


class StateCandidateRegistryV1Error(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateCandidateRegistryV1Error(f"cannot read JSON object: {source}") from exc
    if not isinstance(value, dict):
        raise StateCandidateRegistryV1Error(f"JSON must be an object: {source}")
    return value


def _candidate_identity(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "research_family": str(row.get("research_family")),
        "feature": str(row.get("feature")),
        "target": str(row.get("target")),
    }


def _identity_tuple(candidate: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate.get("research_family")),
        str(candidate.get("feature")),
        str(candidate.get("target")),
    )


def _prior_locked_candidate(prior_registries: Iterable[Mapping[str, Any]]) -> dict[str, str] | None:
    locked: set[tuple[str, str, str]] = set()
    for registry in prior_registries:
        if registry.get("experiment") != "state_candidate_registry_v1":
            raise StateCandidateRegistryV1Error("prior registry is not state-candidate-registry-v1")
        candidate = registry.get("locked_candidate")
        if candidate is None:
            continue
        if not isinstance(candidate, Mapping):
            raise StateCandidateRegistryV1Error("prior locked candidate is invalid")
        locked.add(_identity_tuple(candidate))
    if len(locked) > 1:
        raise StateCandidateRegistryV1Error("conflicting prior candidate locks detected")
    if not locked:
        return None
    family, feature, target = next(iter(locked))
    return {"research_family": family, "feature": feature, "target": target}


def build_state_candidate_registry_v1(
    promotion_report: Mapping[str, Any],
    protocol: Mapping[str, Any],
    *,
    prior_registries: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if protocol.get("protocol_name") != "state-candidate-registry-v1":
        raise StateCandidateRegistryV1Error("not a state-candidate-registry-v1 protocol")
    if promotion_report.get("experiment") != protocol.get("upstream_promotion_experiment"):
        raise StateCandidateRegistryV1Error("promotion report experiment mismatch")
    if promotion_report.get("source_protocol") != protocol.get("upstream_state_protocol"):
        raise StateCandidateRegistryV1Error("promotion report state protocol mismatch")

    selection = protocol.get("selection")
    if not isinstance(selection, Mapping):
        raise StateCandidateRegistryV1Error("registry protocol lacks selection rules")
    if int(selection.get("maximum_locked_candidates") or 0) != 1:
        raise StateCandidateRegistryV1Error("state-candidate-registry-v1 supports exactly one locked candidate")
    eligibility_field = str(selection.get("eligibility_field"))

    eligible_rows = [
        row
        for row in promotion_report.get("candidates", [])
        if isinstance(row, Mapping) and row.get(eligibility_field) is True
    ]
    eligible_identities = sorted((_candidate_identity(row) for row in eligible_rows), key=_identity_tuple)

    prior_locked = _prior_locked_candidate(prior_registries)
    newly_locked = False
    locked_candidate = prior_locked
    if locked_candidate is None and eligible_identities:
        locked_candidate = dict(eligible_identities[0])
        newly_locked = True

    eligible_now = False
    if locked_candidate is not None:
        locked_tuple = _identity_tuple(locked_candidate)
        eligible_now = any(_identity_tuple(candidate) == locked_tuple for candidate in eligible_identities)

    payload: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "state_candidate_registry_v1",
        "protocol_name": protocol["protocol_name"],
        "frozen_after_commit": protocol.get("frozen_after_commit"),
        "source_protocol": promotion_report.get("source_protocol"),
        "source_screen_ready": bool(promotion_report.get("screen_ready")),
        "source_independent_dependence_cluster_count": int(
            promotion_report.get("independent_dependence_cluster_count") or 0
        ),
        "eligible_candidate_count": len(eligible_identities),
        "eligible_candidates_lexical": eligible_identities,
        "locked_candidate": locked_candidate,
        "selection_newly_locked": newly_locked,
        "locked_candidate_eligible_in_current_report": eligible_now,
        "selection_rule": (
            "preserve the first prior lock; if none exists, lock the lexically first eligible "
            "(research_family, feature, target) identity without using association magnitude or strategy PnL"
        ),
        "downstream_conditioning_protocol": protocol.get("downstream_conditioning_protocol"),
        "claims": dict(protocol.get("claims", {})),
    }
    payload["registry_sha256"] = _canonical_sha256(payload)
    return payload


def build_state_candidate_registry_v1_from_paths(
    promotion_report_path: str | Path,
    protocol_path: str | Path,
    *,
    prior_registry_paths: Iterable[str | Path] = (),
) -> dict[str, Any]:
    promotion_report = _load_object(promotion_report_path)
    protocol = _load_object(protocol_path)
    prior = [_load_object(path) for path in prior_registry_paths]
    return build_state_candidate_registry_v1(promotion_report, protocol, prior_registries=prior)


def verify_state_candidate_registry_v1(payload: Mapping[str, Any]) -> bool:
    if payload.get("experiment") != "state_candidate_registry_v1":
        return False
    expected = payload.get("registry_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("registry_sha256", None)
    return _canonical_sha256(unsigned) == expected
