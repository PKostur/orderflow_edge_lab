from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from orderflow_edge_lab.state_threshold_freeze_v1 import build_state_threshold_freeze_v1, verify_state_threshold_freeze_v1


def _sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class StateThresholdFreezeV1Tests(unittest.TestCase):
    def _write(self, root: Path, name: str, payload: object) -> Path:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _protocol(self) -> dict:
        return {
            "protocol_name": "state-threshold-freeze-v1",
            "upstream_state_protocol": "regime-research-v1.2",
            "upstream_binding_protocol": "strategy-conditioning-registry-binding-v1",
            "downstream_conditioning_protocol": "strategy-conditioning-v1.1",
            "frozen_after_commit": "abc",
            "threshold_rules": {
                "minimum_independent_dependence_clusters": 5,
                "minimum_valid_observations_per_cluster": 5,
                "lower_quantile": 1 / 3,
                "upper_quantile": 2 / 3,
                "within_cluster_rule": "fixed",
                "across_cluster_rule": "median",
                "association_sign_mapping": {
                    "positive": {"predicted_target_low": "lower", "neutral": "middle", "predicted_target_high": "upper"},
                    "negative": {"predicted_target_low": "upper", "neutral": "middle", "predicted_target_high": "lower"},
                },
            },
            "claims": {"uses_strategy_pnl_for_threshold_selection": False},
        }

    def _binding(self, dominant_sign: str = "positive") -> dict:
        payload = {
            "schema_version": 1,
            "experiment": "strategy_conditioning_registry_binding_v1",
            "protocol_name": "strategy-conditioning-registry-binding-v1",
            "status": "frozen",
            "conditioning_freeze": {
                "protocol_name": "strategy-conditioning-v1.1",
                "state_hypothesis": {
                    "research_family": "liquidity_stability_deterioration",
                    "feature": "spread_bps",
                    "target": "spread_expansion_ratio_60s",
                    "dominant_sign": dominant_sign,
                },
            },
        }
        payload["manifest_sha256"] = _sha(payload)
        return payload

    def _screen(self) -> dict:
        return {
            "experiment": "regime_research_v1_2_market_state_screen",
            "protocol_name": "regime-research-v1.2",
            "dependence_audit": {
                "clusters": [
                    {"representative_batch_id": f"batch_{index}"}
                    for index in range(5)
                ]
            },
        }

    def _report(self, batch_id: str) -> dict:
        return {
            "experiment": "regime_research_v1_market_state_scan",
            "batch_id": batch_id,
            "observations": [
                {
                    "features": {"spread_bps": float(value)},
                    "targets": {"spread_expansion_ratio_60s": float(value + 1)},
                }
                for value in range(7)
            ],
        }

    def test_freezes_equal_weight_cluster_quantiles_without_strategy_pnl(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write(root, "protocol.json", self._protocol())
            binding = self._write(root, "binding.json", self._binding("positive"))
            screen = self._write(root, "screen.json", self._screen())
            reports = [self._write(root, f"batch_{i}.json", self._report(f"batch_{i}")) for i in range(5)]

            result = build_state_threshold_freeze_v1(screen, binding, protocol, reports)

            self.assertEqual(result["status"], "frozen")
            self.assertAlmostEqual(result["thresholds"]["lower"], 2.0)
            self.assertAlmostEqual(result["thresholds"]["upper"], 4.0)
            self.assertEqual(result["thresholds"]["market_state_mapping"]["predicted_target_high"], "upper")
            self.assertFalse(result["claims"]["strategy_favorable_bucket_selected"])
            self.assertTrue(verify_state_threshold_freeze_v1(result))

    def test_negative_association_reverses_state_mapping_not_thresholds(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write(root, "protocol.json", self._protocol())
            binding = self._write(root, "binding.json", self._binding("negative"))
            screen = self._write(root, "screen.json", self._screen())
            reports = [self._write(root, f"batch_{i}.json", self._report(f"batch_{i}")) for i in range(5)]

            result = build_state_threshold_freeze_v1(screen, binding, protocol, reports)

            self.assertEqual(result["thresholds"]["market_state_mapping"]["predicted_target_high"], "lower")
            self.assertAlmostEqual(result["thresholds"]["lower"], 2.0)
            self.assertAlmostEqual(result["thresholds"]["upper"], 4.0)

    def test_waits_when_binding_has_no_frozen_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            protocol = self._write(root, "protocol.json", self._protocol())
            payload = {
                "schema_version": 1,
                "experiment": "strategy_conditioning_registry_binding_v1",
                "protocol_name": "strategy-conditioning-registry-binding-v1",
                "status": "no_locked_candidate",
                "conditioning_freeze": None,
            }
            payload["manifest_sha256"] = _sha(payload)
            binding = self._write(root, "binding.json", payload)
            screen = self._write(root, "screen.json", self._screen())

            result = build_state_threshold_freeze_v1(screen, binding, protocol, [])

            self.assertEqual(result["status"], "waiting_for_frozen_conditioning_candidate")
            self.assertIsNone(result["thresholds"])


if __name__ == "__main__":
    unittest.main()
