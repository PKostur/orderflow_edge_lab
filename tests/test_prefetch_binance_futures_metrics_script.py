"""Prefetch script for the round-2 futures metrics: universe file handling (network mocked)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location("prefetch_binance_futures_metrics",
                                                  ROOT / "scripts" / "prefetch_binance_futures_metrics.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def definition(symbols, size=3, metrics_day="2021-12-01"):
    return {"symbols": symbols, "size": size, "metrics_day": metrics_day, "candidates_ranked": 9, "skipped_no_metrics": []}


class UniverseFileTests(unittest.TestCase):
    def setUp(self):
        self.module = load_script()

    def test_short_universe_is_refused_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u.json"
            with mock.patch.object(self.module.bfm, "build_universe", return_value=definition(["BTCUSDT"])), \
                    mock.patch.object(self.module.lc, "load_data", side_effect=AssertionError("no download")):
                code = self.module.main(["--universe-only", "--universe-file", str(path)])
            self.assertEqual(code, 3)
            self.assertFalse(path.exists())

    def test_full_universe_is_written_once_and_an_existing_file_is_only_compared(self):
        full = definition(["A", "B", "C"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "u.json"
            with mock.patch.object(self.module.bfm, "build_universe", return_value=full) as build:
                self.assertEqual(self.module.main(["--universe-only", "--universe-file", str(path)]), 0)
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["symbols"], ["A", "B", "C"])
                before = path.read_text(encoding="utf-8")
                self.assertEqual(self.module.main(["--universe-only", "--universe-file", str(path)]), 0)
                self.assertEqual(path.read_text(encoding="utf-8"), before)
                self.assertEqual(build.call_args.kwargs["metrics_day"], "2021-12-01")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["metrics_day"], "2021-12-01")
            with mock.patch.object(self.module.bfm, "build_universe", return_value=definition(["A", "B", "D"])):
                self.assertEqual(self.module.main(["--universe-only", "--universe-file", str(path)]), 2)
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            # the same symbols under a different criterion do not match the registered file
            with mock.patch.object(self.module.bfm, "build_universe",
                                   return_value=definition(["A", "B", "C"], metrics_day="2021-01-01")):
                self.assertEqual(self.module.main(["--universe-only", "--universe-file", str(path)]), 2)

    def test_defaults_are_the_amended_registration(self):
        self.assertEqual(self.module.bfm.DATA_START, "2021-12-01")
        self.assertEqual(self.module.bfm.OI_LOAD_START, "2021-11-30")


if __name__ == "__main__":
    unittest.main()
