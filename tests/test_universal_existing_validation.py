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

    def test_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_snapshot(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            manifest["files"][0]["sha256"] = "0" * 64
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(UniversalExistingValidationError):
                build_report(self._protocol(root), root)

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
