from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .research_protocol import ResearchProtocolError, verify_freeze

UTC = timezone.utc


class CandidateFreezeError(ValueError):
    pass


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _load_json_bytes(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateFreezeError(f"cannot read JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CandidateFreezeError(f"JSON must be an object: {path}")
    return raw, payload


def build_candidate_freeze(
    registry_path: str | Path,
    research_freeze_path: str | Path,
    *,
    candidate_ids: list[str] | tuple[str, ...] | None = None,
    protocol_note: str = "candidate specification frozen before holdout inspection",
    now: datetime | None = None,
) -> dict[str, Any]:
    registry_path = Path(registry_path)
    research_freeze_path = Path(research_freeze_path)
    registry_raw, registry = _load_json_bytes(registry_path)
    _, research_freeze = _load_json_bytes(research_freeze_path)
    if not verify_freeze(research_freeze):
        raise CandidateFreezeError("research freeze manifest hash is invalid")

    raw_candidates = registry.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise CandidateFreezeError("candidate registry must contain a nonempty candidates list")

    by_id: dict[str, dict[str, Any]] = {}
    for row in raw_candidates:
        if not isinstance(row, dict):
            raise CandidateFreezeError("candidate registry contains a malformed candidate")
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise CandidateFreezeError("candidate_id must be a nonempty string")
        candidate_id = candidate_id.strip()
        if candidate_id in by_id:
            raise CandidateFreezeError("candidate registry contains duplicate candidate_id")
        by_id[candidate_id] = row

    if candidate_ids is None:
        selected_ids = sorted(by_id)
    else:
        selected_ids = []
        seen: set[str] = set()
        for value in candidate_ids:
            if not isinstance(value, str) or not value.strip():
                raise CandidateFreezeError("candidate IDs must be nonempty strings")
            candidate_id = value.strip()
            if candidate_id in seen:
                raise CandidateFreezeError("candidate IDs must be unique")
            if candidate_id not in by_id:
                raise CandidateFreezeError(f"candidate not found in registry: {candidate_id}")
            seen.add(candidate_id)
            selected_ids.append(candidate_id)
        selected_ids.sort()
        if not selected_ids:
            raise CandidateFreezeError("at least one candidate must be selected")

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise CandidateFreezeError("freeze timestamp must include timezone")
    timestamp = timestamp.astimezone(UTC)

    partition_policy = research_freeze.get("partition_policy")
    if not isinstance(partition_policy, dict):
        raise CandidateFreezeError("research freeze lacks partition policy")
    holdout_start = partition_policy.get("holdout_start_exclusive")
    holdout_end = partition_policy.get("holdout_end")
    if not isinstance(holdout_start, str) or not isinstance(holdout_end, str):
        raise CandidateFreezeError("research freeze lacks holdout boundaries")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "created_at": timestamp.isoformat(),
        "protocol_note": str(protocol_note),
        "research_freeze": {
            "path": str(research_freeze_path),
            "manifest_sha256": research_freeze.get("manifest_sha256"),
            "holdout_start_exclusive": holdout_start,
            "holdout_end": holdout_end,
        },
        "registry": {
            "path": str(registry_path),
            "sha256": _sha256_bytes(registry_raw),
        },
        "candidates": [
            {
                "candidate_id": candidate_id,
                "spec_sha256": _canonical_sha256(by_id[candidate_id]),
            }
            for candidate_id in selected_ids
        ],
        "claims": {
            "candidate_specification_frozen": True,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    return manifest


def verify_candidate_freeze(manifest: dict[str, Any]) -> bool:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return False
    expected = manifest.get("manifest_sha256")
    if not _valid_sha256(expected):
        return False
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    if _canonical_sha256(unsigned) != expected:
        return False
    research = manifest.get("research_freeze")
    registry = manifest.get("registry")
    candidates = manifest.get("candidates")
    claims = manifest.get("claims")
    if not isinstance(research, dict) or not _valid_sha256(research.get("manifest_sha256")):
        return False
    if not isinstance(registry, dict) or not _valid_sha256(registry.get("sha256")):
        return False
    if not isinstance(candidates, list) or not candidates:
        return False
    ids: set[str] = set()
    for row in candidates:
        if not isinstance(row, dict):
            return False
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id or candidate_id in ids:
            return False
        if not _valid_sha256(row.get("spec_sha256")):
            return False
        ids.add(candidate_id)
    if not isinstance(claims, dict):
        return False
    if claims.get("candidate_specification_frozen") is not True:
        return False
    if claims.get("verified_out_of_sample_evidence") is not False:
        return False
    if claims.get("profitable_edge_established") is not False:
        return False
    if claims.get("live_order_transmission_supported") is not False:
        return False
    return True


def reverify_candidate_freeze(manifest: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if not verify_candidate_freeze(manifest):
        return False, ("candidate_freeze_manifest_invalid",)

    research = manifest["research_freeze"]
    registry = manifest["registry"]
    try:
        research_path = Path(research["path"])
        _, research_manifest = _load_json_bytes(research_path)
        if not verify_freeze(research_manifest):
            reasons.append("research_freeze_manifest_invalid")
        elif research_manifest.get("manifest_sha256") != research.get("manifest_sha256"):
            reasons.append("research_freeze_manifest_mismatch")
    except (CandidateFreezeError, KeyError, TypeError):
        reasons.append("research_freeze_not_reverifiable")

    try:
        registry_path = Path(registry["path"])
        registry_raw, registry_payload = _load_json_bytes(registry_path)
        if _sha256_bytes(registry_raw) != registry.get("sha256"):
            reasons.append("candidate_registry_sha256_mismatch")
        raw_candidates = registry_payload.get("candidates")
        if not isinstance(raw_candidates, list):
            reasons.append("candidate_registry_not_reverifiable")
        else:
            by_id = {
                row.get("candidate_id"): row
                for row in raw_candidates
                if isinstance(row, dict) and isinstance(row.get("candidate_id"), str)
            }
            for frozen in manifest["candidates"]:
                row = by_id.get(frozen["candidate_id"])
                if row is None:
                    reasons.append("frozen_candidate_missing_from_registry")
                elif _canonical_sha256(row) != frozen["spec_sha256"]:
                    reasons.append("frozen_candidate_spec_mismatch")
    except (CandidateFreezeError, KeyError, TypeError):
        reasons.append("candidate_registry_not_reverifiable")

    unique = tuple(dict.fromkeys(reasons))
    return not unique, unique
