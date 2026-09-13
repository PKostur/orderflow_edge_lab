from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from orderflow_edge_lab.state_candidate_registry_v1 import verify_state_candidate_registry_v1
from orderflow_edge_lab.strategy_conditioning_freeze_v1_1 import build_strategy_conditioning_freeze_v1_1


class StrategyConditioningRegistryBindingV1Error(ValueError):
    pass


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyConditioningRegistryBindingV1Error(f"cannot read JSON object: {source}") from exc
    if not isinstance(value, dict):
        raise StrategyConditioningRegistryBindingV1Error(f"JSON must be an object: {source}")
    return value


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_registry_bound_conditioning_freeze_v1(
    state_screen_path: str | Path,
    registry_path: str | Path,
    binding_protocol_path: str | Path,
    conditioning_protocol_path: str | Path,
) -> dict[str, Any]:
    registry = _load_object(registry_path)
    binding = _load_object(binding_protocol_path)
    if binding.get("protocol_name") != "strategy-conditioning-registry-binding-v1":
        raise StrategyConditioningRegistryBindingV1Error("invalid registry-binding protocol")
    if registry.get("protocol_name") != binding.get("upstream_registry_protocol"):
        raise StrategyConditioningRegistryBindingV1Error("registry protocol mismatch")
    if not verify_state_candidate_registry_v1(registry):
        raise StrategyConditioningRegistryBindingV1Error("registry SHA256 verification failed")
    if registry.get("source_protocol") != binding.get("upstream_state_protocol"):
        raise StrategyConditioningRegistryBindingV1Error("registry state protocol mismatch")
    if registry.get("downstream_conditioning_protocol") != binding.get("downstream_conditioning_protocol"):
        raise StrategyConditioningRegistryBindingV1Error("registry downstream conditioning protocol mismatch")

    locked = registry.get("locked_candidate")
    if locked is None:
        payload = {
            "schema_version": 1,
            "experiment": "strategy_conditioning_registry_binding_v1",
            "protocol_name": binding["protocol_name"],
            "status": "no_locked_candidate",
            "registry_sha256": registry.get("registry_sha256"),
            "conditioning_freeze": None,
            "claims": dict(binding.get("claims", {})),
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload
    if not isinstance(locked, Mapping):
        raise StrategyConditioningRegistryBindingV1Error("locked candidate is invalid")
    if registry.get("locked_candidate_eligible_in_current_report") is not True:
        payload = {
            "schema_version": 1,
            "experiment": "strategy_conditioning_registry_binding_v1",
            "protocol_name": binding["protocol_name"],
            "status": "locked_candidate_not_currently_eligible",
            "registry_sha256": registry.get("registry_sha256"),
            "locked_candidate": dict(locked),
            "conditioning_freeze": None,
            "claims": dict(binding.get("claims", {})),
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload

    frozen = build_strategy_conditioning_freeze_v1_1(
        state_screen_path,
        conditioning_protocol_path,
        research_family=str(locked.get("research_family")),
        feature=str(locked.get("feature")),
        target=str(locked.get("target")),
    )
    payload = {
        "schema_version": 1,
        "experiment": "strategy_conditioning_registry_binding_v1",
        "protocol_name": binding["protocol_name"],
        "status": "frozen",
        "registry_sha256": registry.get("registry_sha256"),
        "registry_file_sha256": hashlib.sha256(Path(registry_path).read_bytes()).hexdigest(),
        "state_screen_file_sha256": hashlib.sha256(Path(state_screen_path).read_bytes()).hexdigest(),
        "locked_candidate": dict(locked),
        "conditioning_freeze": frozen,
        "claims": {
            **dict(binding.get("claims", {})),
            "registry_candidate_bound_before_conditioned_pnl": True,
        },
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def verify_registry_bound_conditioning_freeze_v1(payload: Mapping[str, Any]) -> bool:
    if payload.get("experiment") != "strategy_conditioning_registry_binding_v1":
        return False
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    unsigned = dict(payload)
    unsigned.pop("manifest_sha256", None)
    return _canonical_sha256(unsigned) == expected
