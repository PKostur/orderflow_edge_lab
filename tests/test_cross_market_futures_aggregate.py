from __future__ import annotations

import unittest

from orderflow_edge_lab.cross_market_futures import futures_spec
from orderflow_edge_lab.cross_market_futures_aggregate import (
    FROZEN_FAMILIES,
    PLACEBO_SHIFTS_SECONDS,
    aggregate_d0,
)


class CrossMarketFuturesAggregateTests(unittest.TestCase):
    @staticmethod
    def _report(
        *,
        root: str,
        native_contract: str,
        source_sha: str,
        signals: int,
        original_value: float,
        reversed_value: float = -1.0,
        drop_last_horizon_for_last_signal: bool = False,
    ) -> dict[str, object]:
        observations: list[dict[str, object]] = []
        base = 1_800_000_000_000_000_000
        for index in range(signals):
            signal_ts = base + (index + 1) * 10_000_000_000
            for control, value in (
                ("original", original_value),
                ("reversed_same_decision", reversed_value),
            ):
                for horizon in (1_000, 5_000, 15_000, 30_000):
                    if (
                        drop_last_horizon_for_last_signal
                        and index == signals - 1
                        and control == "original"
                        and horizon == 30_000
                    ):
                        continue
                    observations.append(
                        {
                            "root": root,
                            "family": "aggressive_flow_ratio",
                            "control": control,
                            "signal_side": 1,
                            "path_side": 1 if control == "original" else -1,
                            "signal_observed_at_ns": signal_ts,
                            "horizon_ms": horizon,
                            "extra_round_trip_ticks": 1.0,
                            "net_bps_before_commission": value,
                        }
                    )
        return {
            "research_id": "cross_market_futures_v1",
            "root": root,
            "source_sha256": source_sha,
            "native_contract_audit": {
                "passed": True,
                "symbols": [native_contract],
            },
            "observations": observations,
        }

    @staticmethod
    def _record(
        *,
        session_id: str,
        root: str,
        native_contract: str,
        source_sha: str,
        signals: int,
        original_value: float,
        drop_last_horizon_for_last_signal: bool = False,
    ) -> dict[str, object]:
        return {
            "session_id": session_id,
            "root": root,
            "native_contract": native_contract,
            "report": CrossMarketFuturesAggregateTests._report(
                root=root,
                native_contract=native_contract,
                source_sha=source_sha,
                signals=signals,
                original_value=original_value,
                drop_last_horizon_for_last_signal=drop_last_horizon_for_last_signal,
            ),
        }

    def test_primary_signal_requires_every_frozen_horizon_for_both_controls(self) -> None:
        record = self._record(
            session_id="S1",
            root="ES",
            native_contract="ESZ26",
            source_sha="sha-1",
            signals=2,
            original_value=3.0,
            drop_last_horizon_for_last_signal=True,
        )
        result = aggregate_d0([record])
        family = result["families"]["aggressive_flow_ratio"]
        self.assertEqual(family["eligible_composite_signals"], 1)
        self.assertEqual(family["pooled_original_composite_net_bps"], 3.0)
        self.assertFalse(family["d0_survives"])

    def test_all_frozen_families_are_reported_even_with_zero_observations(self) -> None:
        record = self._record(
            session_id="S1",
            root="ES",
            native_contract="ESZ26",
            source_sha="sha-1",
            signals=1,
            original_value=1.0,
        )
        result = aggregate_d0([record])
        self.assertEqual(tuple(result["families"]), FROZEN_FAMILIES)
        self.assertEqual(result["families"]["book_imbalance_10"]["eligible_composite_signals"], 0)
        self.assertFalse(result["families"]["book_imbalance_10"]["d0_survives"])

    def test_duplicate_source_hash_is_rejected(self) -> None:
        records = [
            self._record(
                session_id="S1",
                root="ES",
                native_contract="ESZ26",
                source_sha="duplicate",
                signals=1,
                original_value=1.0,
            ),
            self._record(
                session_id="S2",
                root="NQ",
                native_contract="NQZ26",
                source_sha="duplicate",
                signals=1,
                original_value=1.0,
            ),
        ]
        with self.assertRaisesRegex(ValueError, "duplicate source_sha256"):
            aggregate_d0(records)

    @staticmethod
    def _quotes_for_capture(root: str) -> list[dict[str, object]]:
        spec = futures_spec(root)
        midpoint = {
            "ES": 5000.0,
            "NQ": 20000.0,
            "GC": 2500.0,
            "CL": 80.0,
        }[root]
        base = 1_800_000_000_000_000_000
        rows: list[dict[str, object]] = []
        for second in range(-400, 451):
            bid = midpoint
            ask = bid + spec.tick_size
            rows.append(
                {
                    "event_type": "quote",
                    "observed_at_ns": base + second * 1_000_000_000,
                    "best_bid": bid,
                    "best_ask": ask,
                }
            )
        return rows

    def test_d0_and_placebo_use_frozen_dependence_clusters_and_shifts(self) -> None:
        roots = {
            "ES": ("ESZ26", 2.0),
            "NQ": ("NQZ26", 2.0),
            "GC": ("GCZ26", 2.0),
            "CL": ("CLZ26", -1.0),
        }
        records: list[dict[str, object]] = []
        features: dict[str, list[dict[str, object]]] = {}
        counter = 0
        for session_number in range(1, 6):
            session_id = f"S{session_number}"
            for root, (contract, value) in roots.items():
                counter += 1
                records.append(
                    self._record(
                        session_id=session_id,
                        root=root,
                        native_contract=contract,
                        source_sha=f"sha-{counter}",
                        signals=5,
                        original_value=value,
                    )
                )
                capture_key = f"{root}|{contract}|{session_id}"
                features[capture_key] = self._quotes_for_capture(root)

        result = aggregate_d0(records, feature_rows_by_capture=features)
        family = result["families"]["aggressive_flow_ratio"]
        self.assertEqual(family["eligible_composite_signals"], 100)
        self.assertEqual(family["independent_capture_sessions"], 5)
        self.assertEqual(family["markets_with_signals"], 4)
        self.assertEqual(set(family["positive_markets"]), {"ES", "NQ", "GC"})
        self.assertAlmostEqual(family["single_market_positive_pnl_share"], 1 / 3)
        self.assertTrue(family["d0_survives"])
        self.assertTrue(family["session_block_bootstrap"]["eligible"])

        placebo = family["time_shift_placebo"]
        self.assertEqual(
            [row["shift_seconds"] for row in placebo["shifts"]],
            list(PLACEBO_SHIFTS_SECONDS),
        )
        self.assertTrue(placebo["all_shifts_interpretable"])
        self.assertTrue(placebo["passes_candidate_freeze_placebo"])
        self.assertTrue(family["candidate_freeze_eligible"])

    def test_missing_feature_rows_blocks_candidate_freeze_not_d0_accounting(self) -> None:
        records = [
            self._record(
                session_id=f"S{i}",
                root="ES",
                native_contract="ESZ26",
                source_sha=f"sha-{i}",
                signals=20,
                original_value=2.0,
            )
            for i in range(1, 6)
        ]
        result = aggregate_d0(records)
        family = result["families"]["aggressive_flow_ratio"]
        self.assertFalse(family["d0_survives"])  # one market cannot satisfy breadth
        self.assertFalse(family["candidate_freeze_eligible"])
        self.assertEqual(family["time_shift_placebo"]["status"], "NOT_RUN_NO_FEATURE_ROWS")


if __name__ == "__main__":
    unittest.main()
