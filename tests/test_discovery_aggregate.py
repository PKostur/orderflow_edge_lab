from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.discovery_aggregate import DiscoveryAggregateError, aggregate, verify_manifest
from orderflow_edge_lab.orderflow_backtest import BacktestConfig


CONFIG = {
    "symbol": "ENA_USDT",
    "context_symbol": "BTC_USDT",
    "horizons_ms": [1000, 5000, 15000, 30000],
    "fee_bps_round_trip": [0.0, 4.0, 8.0],
    "min_trade_count": 5,
    "min_trade_flow_ratio": 0.25,
    "min_book_imbalance": 0.25,
    "min_microprice_edge": 0.2,
    "cooldown_ms": 2000,
}


class DiscoveryAggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.protocol = self.root / "protocol.json"
        self.protocol.write_text(json.dumps({
            "schema_version": 1,
            "protocol_id": "test-v1",
            "backtest_config": CONFIG,
            "research_rules": {"minimum_batches_before_inference": 3},
        }), encoding="utf-8")

    def _report(self, name, source, net, observations=4, *, config=None):
        path = self.root / name
        path.write_text(json.dumps({
            "schema_version": 1,
            "source_sha256": source,
            "config": CONFIG if config is None else config,
            "feature_rows": 100,
            "signals": 5,
            "summary": [{
                "family": "microprice",
                "horizon_ms": 5000,
                "fee_bps_round_trip": 4.0,
                "observations": observations,
                "gross_mean_bps": net + 4.0,
                "net_mean_bps": net,
                "net_win_rate": 0.5,
                "net_total_bps": net * observations,
            }],
            "claims": {
                "exploratory_only": True,
                "verified_out_of_sample_evidence": False,
                "profitable_edge_established": False,
                "live_order_transmission_supported": False,
            },
        }), encoding="utf-8")
        return path

    def test_repository_protocol_matches_backtest_defaults(self):
        cfg = BacktestConfig()
        actual = {
            "symbol": cfg.symbol,
            "context_symbol": cfg.context_symbol,
            "horizons_ms": list(cfg.horizons_ms),
            "fee_bps_round_trip": list(cfg.fee_bps_round_trip),
            "min_trade_count": cfg.min_trade_count,
            "min_trade_flow_ratio": cfg.min_trade_flow_ratio,
            "min_book_imbalance": cfg.min_book_imbalance,
            "min_microprice_edge": cfg.min_microprice_edge,
            "cooldown_ms": cfg.cooldown_ms,
        }
        repository_protocol = Path(__file__).resolve().parents[1] / "config" / "orderflow_discovery_v1.json"
        protocol = json.loads(repository_protocol.read_text(encoding="utf-8"))
        self.assertEqual(protocol["backtest_config"], actual)

    def test_uses_batches_as_primary_unit(self):
        a = self._report("a.json", "a" * 64, 1.0, 100)
        b = self._report("b.json", "b" * 64, -1.0, 1)
        report = aggregate([a, b], self.protocol)
        row = report["summary"][0]
        self.assertAlmostEqual(row["batch_mean_net_bps"], 0.0)
        self.assertGreater(row["event_weighted_net_mean_bps_descriptive"], 0.9)
        self.assertEqual(row["batches_with_observations"], 2)
        self.assertFalse(row["inference_ready"])
        self.assertTrue(verify_manifest(report))
        self.assertFalse(report["claims"]["profitable_edge_established"])

    def test_rejects_duplicate_source_capture(self):
        a = self._report("a.json", "a" * 64, 1.0)
        b = self._report("b.json", "a" * 64, 2.0)
        with self.assertRaises(DiscoveryAggregateError):
            aggregate([a, b], self.protocol)

    def test_rejects_protocol_drift(self):
        a = self._report("a.json", "a" * 64, 1.0, config={**CONFIG, "min_book_imbalance": 0.1})
        with self.assertRaises(DiscoveryAggregateError):
            aggregate([a], self.protocol)

    def test_manifest_detects_tampering(self):
        a = self._report("a.json", "a" * 64, 1.0)
        report = aggregate([a], self.protocol)
        report["signals_total"] += 1
        self.assertFalse(verify_manifest(report))


if __name__ == "__main__":
    unittest.main()
