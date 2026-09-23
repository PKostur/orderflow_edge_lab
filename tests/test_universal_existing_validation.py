from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from orderflow_edge_lab.universal_existing_validation import (
    UniversalExistingValidationError,
    build_report,
)


def _fixture(rows: int = 400) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="8h", tz="UTC")
    close = 100.0 + np.arange(rows, dtype=float) * 0.05 + np.sin(np.arange(rows) / 5.0)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.2,
            "low": np.minimum(open_, close) - 0.2,
            "close": close,
            "volume": 1_000.0,
        },
        index=index,
    )


def _write_snapshot(root: Path, *, rows: int = 400) -> None:
    frame = _fixture(rows)
    path = root / "BTC_USDT_8h.csv"
    frame.to_csv(path, index_label="timestamp")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "files": [{
            "symbol": "BTC_USDT",
            "path": path.name,
            "rows": len(frame),
            "sha256": digest,
        }],
        "failures": [],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class UniversalExistingValidationTests(unittest.TestCase):
    def _protocol(self, root: Path) -> Path:
        value = {
            "protocol_name": "fixture",
            "data": {
                "source": "MEXC public futures klines",
                "interval": "8h",
                "start": "2024-01-01T00:00:00Z",
                "end_exclusive": "2024-05-13T08:00:00Z",
                "symbols": ["BTC_USDT"],
                "coverage": {"full_window_symbols": ["BTC_USDT"], "allow_leading_missing_symbols": [], "minimum_rows": 100},
            },
            "costs_bps": [12.0, 20.0],
            "fold_days": 120,
            "strategies": [{
                "audit_id": "DON8",
                "family": "donchian_breakout",
                "parameters": {"lookback": 55},
            }],
        }
        path = root / "protocol.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_report_requires_complete_hashed_snapshot_and_passes_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_snapshot(root)
            report = build_report(self._protocol(root), root)
            self.assertTrue(report["compatibility_pass"])
            self.assertEqual(report["status"], "compatibility_pass")
            self.assertTrue(report["claims"]["folds_are_descriptive_cold_start_diagnostics"])
            accounting = report["strategies"][0]["cost_cases"][0]["symbols"][0]["accounting_audit"]
            self.assertEqual(accounting["status"], "accounting_mismatch")
            self.assertTrue(report["claims"]["accounting_audit_included"])
            canonical = report["strategies"][0]["cost_cases"][0]["symbols"][0]["canonical"]
            self.assertEqual(canonical["accounting"]["mode"], "canonical_turnover_path")
            session_diagnostics = report["strategies"][0]["cost_cases"][0]["symbols"][0]["session_diagnostics"]
            self.assertEqual(session_diagnostics["analysis"], "universal_session_diagnostics")
            self.assertTrue(session_diagnostics["baseline_reconciles_to_canonical_total_return"])
            self.assertFalse(report["claims"]["session_diagnostics_affect_compatibility_pass"])
            self.assertTrue(report["strategies"][0]["cost_cases"][1]["canonical_cost_monotonic_vs_previous"])
            self.assertFalse(report["claims"]["canonical_economic_accounting_established"])

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_snapshot(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["files"][0]["sha256"] = "0" * 64
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UniversalExistingValidationError):
                build_report(self._protocol(root), root)

    def test_declared_leading_availability_gap_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = _fixture()
            frame = frame.iloc[40:]
            path = root / "BTC_USDT_8h.csv"
            frame.to_csv(path, index_label="timestamp")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            (root / "manifest.json").write_text(
                json.dumps({
                    "interval": "8h",
                    "start": "2024-01-01",
                    "end_exclusive": "2024-05-13T08:00:00Z",
                    "files": [{"symbol": "BTC_USDT", "path": path.name, "rows": len(frame), "sha256": digest}],
                    "failures": [],
                }),
                encoding="utf-8",
            )
            protocol = json.loads(self._protocol(root).read_text(encoding="utf-8"))
            protocol["data"]["coverage"] = {
                "full_window_symbols": [],
                "allow_leading_missing_symbols": ["BTC_USDT"],
                "minimum_rows": 100,
            }
            protocol_path = root / "protocol.json"
            protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
            report = build_report(protocol_path, root)
            checked = report["data"]["snapshot"]["files"][0]
            self.assertFalse(checked["full_requested_window"])
            self.assertTrue(report["claims"]["leading_listing_gaps_are_not_silent"])

    def test_coverage_classification_must_be_disjoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = _fixture()
            path = root / "BTC_USDT_8h.csv"
            frame.to_csv(path, index_label="timestamp")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            (root / "manifest.json").write_text(
                json.dumps({
                    "interval": "8h",
                    "start": "2024-01-01T00:00:00Z",
                    "end_exclusive": "2024-05-13T08:00:00Z",
                    "files": [{"symbol": "BTC_USDT", "path": path.name, "rows": len(frame), "sha256": digest}],
                    "failures": [],
                }),
                encoding="utf-8",
            )
            protocol = json.loads(self._protocol(root).read_text(encoding="utf-8"))
            protocol["data"]["coverage"]["allow_leading_missing_symbols"] = ["BTC_USDT"]
            protocol_path = root / "protocol.json"
            protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
            with self.assertRaises(UniversalExistingValidationError):
                build_report(protocol_path, root)

    def test_out_of_order_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_snapshot(root)
            path = root / "BTC_USDT_8h.csv"
            frame = pd.read_csv(path)
            frame = frame.iloc[[1, 0, *range(2, len(frame))]]
            frame.to_csv(path, index=False)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["files"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UniversalExistingValidationError):
                build_report(self._protocol(root), root)


if __name__ == "__main__":
    unittest.main()
