"""Causal, fail-closed, no-network tests for the public strategy shadow lane."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orderflow_edge_lab.public_strategy_shadow import (
    PublicShadowError,
    build_report,
    is_signal,
    main,
    read_bars,
    validate_spec,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "config/public_strategy_shadow_v1.json").read_text(encoding="utf-8"))
STEP = timedelta(hours=8)
START = datetime(2026, 9, 1, tzinfo=timezone.utc)
AS_OF = (START + STEP * 80).isoformat().replace("+00:00", "Z")


def fixture_rows(symbol: str) -> list[dict[str, str]]:
    rows = []
    for i in range(80):
        opening = 100.0 + 0.01 * i if symbol == "BTC_USDT" else 100.0
        closing = opening + 0.1
        high, low, volume = opening + 1, opening - 1, 10.0
        if symbol != "BTC_USDT":
            if i == 35:
                opening, high, low, closing, volume = 100.0, 106.0, 99.0, 105.0, 50.0
            if i == 36:
                opening, high, low, closing = 106.0, 107.0, 99.0, 100.1
            if i == 39:
                opening, high, low, closing = 108.0, 109.0, 99.0, 100.1
            if i == 45:
                opening, high, low, closing = 100.0, 101.0, 90.0, 100.5
            if i == 55:
                opening, high, low, closing = 92.0, 95.0, 91.0, 94.0
        rows.append({
            "timestamp": (START + STEP * i).isoformat().replace("+00:00", "Z"),
            "open": str(opening), "high": str(high), "low": str(low),
            "close": str(closing), "volume": str(volume),
        })
    return rows


class PublicStrategyShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.data = self.folder / "data"
        self.data.mkdir()
        for symbol in [SPEC["benchmark_symbol"], *SPEC["symbols"]]:
            self.write_symbol(symbol, fixture_rows(symbol))

    def write_symbol(self, symbol, rows):
        with (self.data / f"{symbol}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
            writer.writeheader()
            writer.writerows(rows)

    def test_draft_runs_development_and_never_claims_evidence(self):
        report = build_report(SPEC, self.data, as_of=AS_OF)
        self.assertEqual(report["status"], "DEVELOPMENT_SPENT_DATA")
        self.assertFalse(report["verified_out_of_sample_evidence"])
        self.assertFalse(report["deployment_eligible"])
        self.assertFalse(report["order_transmission_supported"])
        self.assertEqual(report["round_trip_cost_bps"], 20)
        self.assertEqual(len(report["source_sha256"]), 4)
        self.assertEqual(len(report["experiments"]), 3)
        self.assertTrue(all(e["summary"]["verdict"] == "DESCRIPTIVE_ONLY_NOT_VERIFIED_OOS"
                            for e in report["experiments"]))
        self.assertTrue(all(not e["summary"]["minimum_review_sample_reached"]
                            for e in report["experiments"]))

    def test_volume_signal_and_exact_next_open_costs(self):
        report = build_report(SPEC, self.data, as_of=AS_OF)
        experiment = report["experiments"][0]
        trades = [e for e in experiment["events"] if e["symbol"] == "ETH_USDT" and
                  e["signal_time"] == (START + STEP * 36).isoformat().replace("+00:00", "Z")]
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade["status"], "completed")
        self.assertEqual(trade["entry_open"], 106)
        self.assertEqual(trade["exit_open"], 108)
        self.assertAlmostEqual(trade["net_bps"], (108 / 106 - 1) * 10_000 - 20)
        self.assertAlmostEqual(trade["double_cost_net_bps"], (108 / 106 - 1) * 10_000 - 40)
        self.assertAlmostEqual(trade["excess_vs_btc_bps"],
                               trade["gross_bps"] - (trade["btc_matched_net_bps"] + 20))

    def test_three_distinct_signals_without_future_candles(self):
        bars = read_bars(self.data / "ETH_USDT.csv", 480,
                         START + STEP * 80)
        self.assertTrue(is_signal(bars, 35, SPEC["experiments"][0]))
        self.assertTrue(is_signal(bars, 45, SPEC["experiments"][1]))
        self.assertTrue(is_signal(bars, 55, SPEC["experiments"][2]))
        altered = list(bars)
        altered[36:] = []
        self.assertEqual(is_signal(bars, 35, SPEC["experiments"][0]),
                         is_signal(altered, 35, SPEC["experiments"][0]))

    def test_prospective_requires_actual_freeze_declaration(self):
        with self.assertRaisesRegex(PublicShadowError, "draft/unfrozen"):
            build_report(SPEC, self.data, as_of=AS_OF, mode="prospective")
        future = deepcopy(SPEC)
        future.update(status="FROZEN_BEFORE_PROSPECTIVE_START",
                      freeze_commit="a" * 40, frozen_at_utc="2026-09-02T00:00:00Z",
                      prospective_start_utc="2026-09-14T00:00:00Z")
        report = build_report(future, self.data, as_of=AS_OF, mode="prospective")
        self.assertEqual(report["status"], "OPERATOR_DECLARED_PROSPECTIVE_UNVERIFIED")
        self.assertFalse(report["freeze_provenance_independently_verified"])
        self.assertFalse(report["verified_out_of_sample_evidence"])
        for experiment in report["experiments"]:
            for event in experiment["events"]:
                self.assertGreaterEqual(event["signal_time"], "2026-09-14T00:00:00Z")
        future["prospective_start_utc"] = "2026-09-01T00:00:00Z"
        with self.assertRaisesRegex(PublicShadowError, "strictly after freeze"):
            build_report(future, self.data, as_of=AS_OF, mode="prospective")

    def test_partial_bar_and_future_data_fail_closed(self):
        with self.assertRaisesRegex(PublicShadowError, "not closed"):
            build_report(SPEC, self.data, as_of="2026-09-27T15:59:59Z")
        rows = fixture_rows("ETH_USDT")
        rows[5]["timestamp"] = "2026-09-02T17:00:00Z"
        self.write_symbol("ETH_USDT", rows)
        with self.assertRaisesRegex(PublicShadowError, "interval-aligned"):
            build_report(SPEC, self.data, as_of=AS_OF)

    def test_gap_duplicate_and_mismatched_grids_fail_closed(self):
        rows = fixture_rows("ETH_USDT")
        self.write_symbol("ETH_USDT", rows[:9] + rows[10:])
        with self.assertRaisesRegex(PublicShadowError, "missing, duplicated"):
            build_report(SPEC, self.data, as_of=AS_OF)
        self.write_symbol("ETH_USDT", rows)
        self.write_symbol("SOL_USDT", rows + [rows[-1]])
        with self.assertRaisesRegex(PublicShadowError, "missing, duplicated"):
            build_report(SPEC, self.data, as_of=AS_OF)

    def test_invalid_ohlcv_and_zero_cost_rejected(self):
        rows = fixture_rows("ETH_USDT")
        rows[0]["high"] = "0"
        self.write_symbol("ETH_USDT", rows)
        with self.assertRaisesRegex(PublicShadowError, "invalid OHLCV"):
            build_report(SPEC, self.data, as_of=AS_OF)
        self.write_symbol("ETH_USDT", fixture_rows("ETH_USDT"))
        spec = deepcopy(SPEC)
        spec["costs_bps"] = {name: 0 for name in spec["costs_bps"]}
        with self.assertRaisesRegex(PublicShadowError, "positive transaction costs"):
            validate_spec(spec, prospective=False)

    def test_unknown_parameters_rejected(self):
        spec = deepcopy(SPEC)
        spec["experiments"][0]["parameters"]["unregistered"] = 1
        with self.assertRaisesRegex(PublicShadowError, "unregistered"):
            validate_spec(spec, prospective=False)

    def test_pending_outcomes_are_not_counted(self):
        report = build_report(SPEC, self.data, as_of=AS_OF)
        for experiment in report["experiments"]:
            self.assertEqual(experiment["summary"]["completed"],
                             sum(e["status"] == "completed" for e in experiment["events"]))
            self.assertEqual(experiment["summary"]["pending"],
                             sum(e["status"] == "pending" for e in experiment["events"]))

    def test_cli_exclusive_create_does_not_overwrite(self):
        config = self.folder / "config.json"
        config.write_text(json.dumps(SPEC), encoding="utf-8")
        output = self.folder / "report.json"
        args = ["--config", str(config), "--data-dir", str(self.data),
                "--as-of", AS_OF, "--output", str(output)]
        self.assertEqual(main(args), 0)
        initial = output.read_bytes()
        with self.assertRaises(SystemExit) as caught:
            main(args)
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(output.read_bytes(), initial)


if __name__ == "__main__":
    unittest.main()
