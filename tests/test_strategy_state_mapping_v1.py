from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from orderflow_edge_lab.strategy_state_mapping_v1 import (
    StrategyStateMappingV1Error,
    build_strategy_state_mapping_v1,
    verify_strategy_state_mapping_v1,
)


PROTOCOL = Path("config/strategy_state_mapping_v1.json")


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _threshold_payload(
    *,
    status: str = "frozen",
    research_family: str = "liquidity_stability_deterioration",
    feature: str = "spread_bps",
    target: str = "future_spread_bps_30s",
    dominant_sign: str = "positive",
    market_state_mapping: dict[str, str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "experiment": "state_threshold_freeze_v1",
        "protocol_name": "state-threshold-freeze-v1",
        "status": status,
        "state_hypothesis": {
            "research_family": research_family,
            "feature": feature,
            "target": target,
            "dominant_sign": dominant_sign,
        },
        "thresholds": None,
        "claims": {"uses_strategy_pnl_for_threshold_selection": False},
    }
    if status == "frozen":
        payload["thresholds"] = {
            "lower": 1.0,
            "upper": 3.0,
            "market_state_mapping": market_state_mapping
            or {"predicted_target_low": "lower", "neutral": "middle", "predicted_target_high": "upper"},
        }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


class StrategyStateMappingV1Tests(unittest.TestCase):
    def _run(self, payload: dict[str, object]) -> dict[str, object]:
        with TemporaryDirectory() as tmp:
            threshold_path = Path(tmp) / "threshold.json"
            threshold_path.write_text(json.dumps(payload), encoding="utf-8")
            return build_strategy_state_mapping_v1(threshold_path, PROTOCOL)

    def test_waits_until_threshold_is_frozen(self) -> None:
        result = self._run(_threshold_payload(status="waiting_for_threshold_dependence_clusters"))
        self.assertEqual(result["status"], "waiting_for_frozen_state_threshold")
        self.assertIsNone(result["strategy_state_mapping"])
        self.assertTrue(verify_strategy_state_mapping_v1(result))

    def test_liquidity_selects_predicted_low_target_state(self) -> None:
        result = self._run(_threshold_payload())
        mapping = result["strategy_state_mapping"]
        self.assertEqual(result["status"], "frozen")
        self.assertEqual(mapping["selected_market_state_label"], "predicted_target_low")
        self.assertEqual(mapping["selected_raw_feature_bucket"], "lower")
        self.assertFalse(result["claims"]["bucket_selected_from_strategy_pnl"])
        self.assertTrue(verify_strategy_state_mapping_v1(result))

    def test_semantic_low_target_can_map_to_upper_raw_feature_bucket(self) -> None:
        result = self._run(
            _threshold_payload(
                dominant_sign="negative",
                market_state_mapping={
                    "predicted_target_low": "upper",
                    "neutral": "middle",
                    "predicted_target_high": "lower",
                },
            )
        )
        mapping = result["strategy_state_mapping"]
        self.assertEqual(mapping["selected_market_state_label"], "predicted_target_low")
        self.assertEqual(mapping["selected_raw_feature_bucket"], "upper")
        self.assertIn("spread_bps >=", mapping["bucket_predicate"])

    def test_directionality_selects_predicted_high_target_state(self) -> None:
        result = self._run(
            _threshold_payload(
                research_family="directionality_vs_chop",
                feature="abs_book_imbalance_10",
                target="directionality_efficiency_60s",
            )
        )
        mapping = result["strategy_state_mapping"]
        self.assertEqual(mapping["selected_market_state_label"], "predicted_target_high")
        self.assertEqual(mapping["selected_raw_feature_bucket"], "upper")

    def test_signed_target_requires_separate_side_aware_protocol(self) -> None:
        result = self._run(
            _threshold_payload(
                research_family="signed_direction_or_continuation",
                feature="book_imbalance_10",
                target="signed_return_bps_30s",
            )
        )
        self.assertEqual(result["status"], "unsupported_for_v1_mapping")
        self.assertIsNone(result["strategy_state_mapping"])
        self.assertFalse(result["claims"]["conditioned_pnl_may_run"])
        self.assertTrue(verify_strategy_state_mapping_v1(result))

    def test_rejects_tampered_threshold_manifest(self) -> None:
        payload = _threshold_payload()
        payload["state_hypothesis"]["feature"] = "top_depth_notional"  # type: ignore[index]
        with self.assertRaises(StrategyStateMappingV1Error):
            self._run(payload)


if __name__ == "__main__":
    unittest.main()
