from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.conditioned_experiment_v1 import _canonical_sha256 as conditioned_sha
from orderflow_edge_lab.conditioned_result_aggregate_v1 import (
    ConditionedResultAggregateV1Error,
    build_conditioned_result_aggregate_v1,
    verify_conditioned_result_aggregate_v1,
)


class ConditionedResultAggregateV1Tests(unittest.TestCase):
    def _write(self, root: Path, name: str, payload: dict) -> Path:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _state(self, batch: str, start_ns: int, count: int = 3) -> dict:
        return {
            "experiment": "regime_research_v1_market_state_scan",
            "batch_id": batch,
            "observations": [{"observed_at_ns": start_ns + i * 1_000_000_000} for i in range(count)],
        }

    def _conditioned(self, batch: str, baseline: float, conditioned: float, *, mapping: str = "a" * 64) -> dict:
        def row(value: float, pf: float) -> dict:
            return {
                "family": "flow_imbalance",
                "horizon_ms": 30000,
                "fee_bps_round_trip": 8.0,
                "observations": 10,
                "gross_mean_bps": value + 8.0,
                "net_expectancy_bps": value,
                "net_profit_factor": pf,
                "net_win_rate": 0.5,
                "net_total_bps": value * 10,
            }

        def direction(value: float) -> dict:
            return {
                "family": "flow_imbalance",
                "horizon_ms": 30000,
                "fee_bps_round_trip": 8.0,
                "observations": 10,
                "gross_mean_bps": value + 8.0,
                "net_mean_bps": value,
                "net_win_rate": 0.5,
                "net_total_bps": value * 10,
            }

        def risk(drawdown: float, mae: float, mfe: float, ruined: bool = False) -> dict:
            return {
                "stream": "original",
                "family": "flow_imbalance",
                "rr_target": 2.0,
                "requested_risk_fraction": 0.01,
                "requested_risk_pct": 1.0,
                "fee_bps_round_trip": 8.0,
                "trades": 5,
                "starting_equity": 100.0,
                "ending_equity": 101.0,
                "return_pct": 1.0,
                "max_realized_drawdown_pct": drawdown,
                "profit_factor_on_equity_pnl": 1.1,
                "target_hits": 2,
                "stop_hits": 2,
                "time_exits": 1,
                "mean_mae_bps": mae,
                "mean_mfe_bps": mfe,
                "mean_stop_distance_bps": 10.0,
                "mean_exposure_multiple": 2.0,
                "capped_trades": 0,
                "ruined_on_realized_path": ruined,
            }

        payload = {
            "schema_version": 1,
            "experiment": "strategy_conditioned_experiment_v1",
            "status": "evaluated_research_only",
            "source_sha256": "b" * 64,
            "market_state_file_sha256": "c" * 64,
            "strategy_state_mapping_file_sha256": "d" * 64,
            "strategy_state_mapping_manifest_sha256": mapping,
            "batch_id": batch,
            "state_gate": {"feature": "spread_bps", "raw_bucket": "lower", "lower": 1.0, "upper": 2.0, "max_state_staleness_seconds": 5},
            "signal_counts": {"baseline": 10, "conditioned": 5, "conditioned_fraction": 0.5},
            "baseline": {"summary": [row(baseline, 1.0)]},
            "conditioned": {"summary": [row(conditioned, 1.2)]},
            "original_vs_reversed_control": {
                "baseline_original": [direction(baseline)],
                "baseline_reversed": [direction(-baseline)],
                "conditioned_original": [direction(conditioned)],
                "conditioned_reversed": [direction(-conditioned)],
            },
            "mae_mfe_stop_risk_comparison": {
                "baseline": {"families": ["flow_imbalance"], "summary": [risk(4.0, 8.0, 12.0)]},
                "conditioned": {"families": ["flow_imbalance"], "summary": [risk(3.0, 6.0, 13.0)]},
            },
            "economics": {"fee_bps_round_trip": [8.0], "spread_execution": "same", "additional_slippage_model": None, "additional_latency_model": None},
            "claims": {"research_only": True, "profitable_edge_established": False},
        }
        payload["manifest_sha256"] = conditioned_sha(payload)
        return payload

    def test_overlap_cluster_uses_v12_representative_and_equal_cluster_weight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # v1.2 evidence begins at 2026-09-13 02:00 UTC = 1789264800 seconds.
            base = 1_789_264_800 * 1_000_000_000
            state_paths = [
                self._write(root, "s1.json", self._state("20260913T020100Z_a", base + 60_000_000_000, 5)),
                # Overlaps first interval but has fewer observations, so it must not replace s1.
                self._write(root, "s2.json", self._state("20260913T020101Z_b", base + 61_000_000_000, 2)),
                self._write(root, "s3.json", self._state("20260913T021000Z_c", base + 600_000_000_000, 5)),
            ]
            conditioned_paths = [
                self._write(root, "c1.json", self._conditioned("20260913T020100Z_a", 1.0, 3.0)),
                self._write(root, "c2.json", self._conditioned("20260913T020101Z_b", 100.0, -100.0)),
                self._write(root, "c3.json", self._conditioned("20260913T021000Z_c", 2.0, 1.0)),
            ]
            result = build_conditioned_result_aggregate_v1(
                conditioned_paths,
                state_paths,
                protocol_path="config/conditioned_result_aggregate_v1.json",
                regime_protocol_path="config/regime_research_v1_2.json",
            )
            self.assertTrue(verify_conditioned_result_aggregate_v1(result))
            self.assertEqual(result["dependence"]["eligible_state_cluster_count"], 2)
            self.assertEqual(result["dependence"]["evaluated_representative_cluster_count"], 2)
            reps = result["dependence"]["representatives"]
            self.assertEqual(reps[0]["representative_batch_id"], "20260913T020100Z_a")
            cell = result["strategy_cells"][0]
            # Representative cluster deltas are +2 and -1, equally weighted. The +100/-100 nonrepresentative is ignored.
            self.assertAlmostEqual(cell["median_conditioned_minus_baseline_expectancy_bps"], 0.5)
            self.assertAlmostEqual(cell["positive_delta_cluster_fraction"], 0.5)
            self.assertAlmostEqual(result["risk_path_cells"][0]["median_change_max_realized_drawdown_pct"], -1.0)

    def test_inconsistent_mapping_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = 1_789_264_800 * 1_000_000_000
            states = [
                self._write(root, "s1.json", self._state("20260913T020100Z_a", base + 60_000_000_000)),
                self._write(root, "s2.json", self._state("20260913T021000Z_b", base + 600_000_000_000)),
            ]
            conditioned = [
                self._write(root, "c1.json", self._conditioned("20260913T020100Z_a", 1.0, 2.0, mapping="a" * 64)),
                self._write(root, "c2.json", self._conditioned("20260913T021000Z_b", 1.0, 2.0, mapping="e" * 64)),
            ]
            with self.assertRaises(ConditionedResultAggregateV1Error):
                build_conditioned_result_aggregate_v1(
                    conditioned,
                    states,
                    protocol_path="config/conditioned_result_aggregate_v1.json",
                    regime_protocol_path="config/regime_research_v1_2.json",
                )


if __name__ == "__main__":
    unittest.main()
