"""Offline only. Optional native tests become REQUIRED with CI's env flag.

ORDERFLOW_NAUTILUS_WHEEL points to authentic pinned wheel (not auto-downloaded).
ORDERFLOW_REQUIRE_INDEPENDENT_ENGINE=1 prevents skipped native tests in dedicated CI.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from orderflow_edge_lab.contracts_v2 import (
    build_canonical_source_set, canonical_json_bytes, non_authority_claims,
)
from orderflow_edge_lab.economics_v2 import (
    EconomicsV2Error, _ledger_differences, compare_external_engine_calibration_v2,
    run_nautilus_economic_calibration_v2, run_pinned_external_engine_calibration_v2,
)
from orderflow_edge_lab.independent_calibration_v2 import (
    BASE_NS, ENGINE_SPEC, STEP_NS, TOLERANCE, IndependentCalibrationUnavailable,
    canonical_quote_ledger_v2, run_fixture, run_frozen_v3_diagnostic,
    validate_quote_case, verify_engine_wheel,
)

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "v2_13_independent_calibration.json"
SUITE = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
FIXTURES = SUITE["fixtures"]


def _rebind_case(fixture: dict) -> dict:
    raw = canonical_json_bytes(fixture["assumptions"]["quote_case"])
    fixture["source_set"] = build_canonical_source_set([{
        "source_id": "synthetic_quote_case:" + fixture["fixture_id"],
        "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
    }])
    return fixture


class CanonicalQuoteCalibrationTests(unittest.TestCase):
    def test_all_eight_frozen_reference_ledgers(self) -> None:
        self.assertEqual(len(FIXTURES), 8)
        for fixture in FIXTURES:
            with self.subTest(case=fixture["fixture_id"]):
                ledger = canonical_quote_ledger_v2(fixture["assumptions"]["quote_case"])
                self.assertEqual(_ledger_differences(fixture["expected_ledger"], ledger, TOLERANCE), [])
                self.assertEqual(ledger["final_position"], 0)
                self.assertEqual(ledger["terminal_equity"], round(10000 + sum(t["net_pnl"] for t in ledger["trades"]), 8))

    def test_cash_numeric_constants_are_frozen(self) -> None:
        expected = [9999.596, 9991.596, 9992.978, 9992.778, 9998.992, 9991.392, 9993.085, 9995.594]
        self.assertEqual([f["expected_ledger"]["terminal_equity"] for f in FIXTURES], expected)

    def test_predetermined_tolerance_and_nanosecond_exactness(self) -> None:
        fixture = FIXTURES[0]
        shifted = copy.deepcopy(fixture["expected_ledger"])
        shifted["fills"][0]["timestamp_ns"] += 1
        report = compare_external_engine_calibration_v2(fixture, ENGINE_SPEC, {"engine_identity": ENGINE_SPEC, "ledger": shifted})
        self.assertEqual(report["status"], "ENGINE_LEDGER_MISMATCH")
        self.assertTrue(any(d["path"].endswith("timestamp_ns") for d in report["differences"]))
        changed = copy.deepcopy(fixture)
        changed["comparison_tolerance"] = {"absolute": 10000, "relative": 1}
        with self.assertRaisesRegex(EconomicsV2Error, "freezes tolerance"):
            run_nautilus_economic_calibration_v2(changed, wheel_path="missing.whl")

    def test_engine_unavailable_cannot_pass(self) -> None:
        result = run_nautilus_economic_calibration_v2(FIXTURES[0], wheel_path="missing.whl")
        self.assertEqual(result["status"], "NOT_CALIBRATED_ENGINE_UNAVAILABLE")
        self.assertIsNone(result["ledger_match"])
        self.assertEqual(result["non_authority_claims"], non_authority_claims())
        self.assertIn("native_runtime_unavailable", result["not_calibrated_reason"])

    def test_synthetic_source_hash_must_bind_actual_runtime_input(self) -> None:
        altered = copy.deepcopy(FIXTURES[0])
        altered["assumptions"]["quote_case"]["taker_fee"] = 0.002
        with self.assertRaisesRegex(EconomicsV2Error, "hash-bound"):
            run_nautilus_economic_calibration_v2(altered, wheel_path="missing.whl")

    def test_incompatible_uninstalled_or_modified_distribution_rejected(self) -> None:
        with patch("platform.python_implementation", return_value="PyPy"):
            with self.assertRaisesRegex(IndependentCalibrationUnavailable, "CPython 3.12"):
                verify_engine_wheel("irrelevant")
        with tempfile.TemporaryDirectory() as tmp:
            wheel = Path(tmp) / "fake.whl"
            wheel.write_bytes(b"not an authentic engine")
            with self.assertRaises(IndependentCalibrationUnavailable):
                verify_engine_wheel(wheel)

    def test_invalid_or_unsupported_inputs_not_calibrated(self) -> None:
        for field, value in (("taker_fee", -0.1), ("slippage_ticks", 1), ("initial_cash", float("nan"))):
            bad = copy.deepcopy(FIXTURES[0]["assumptions"]["quote_case"])
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(EconomicsV2Error):
                validate_quote_case(bad)
        bad = copy.deepcopy(FIXTURES[0]["assumptions"]["quote_case"])
        bad["steps"][-1]["target"] = 1
        with self.assertRaisesRegex(EconomicsV2Error, "liquidate"):
            validate_quote_case(bad)
        bad["steps"] = [{"bid": 99.0, "ask": 101.0, "target": 0, "funding_rate": None}] * 2
        with self.assertRaisesRegex(EconomicsV2Error, "nonzero held"):
            validate_quote_case(bad)
        bad["steps"][0] = "malformed"
        with self.assertRaisesRegex(EconomicsV2Error, "object"):
            validate_quote_case(bad)

    def test_original_v3_runs_all_cases_without_false_equivalence(self) -> None:
        for fixture in FIXTURES:
            with self.subTest(case=fixture["fixture_id"]):
                diagnostic = run_frozen_v3_diagnostic(fixture["assumptions"]["quote_case"])
                self.assertEqual(diagnostic["status"], "NOT_CALIBRATED_DIFFERENT_SEMANTICS")
                self.assertTrue(diagnostic["result"]["accounting"]["ledger_equity_reconciled"])
                self.assertNotAlmostEqual(diagnostic["initial_equity_mapped_terminal_cash"], fixture["expected_ledger"]["terminal_equity"], places=7)


class NativeIndependentCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.wheel = os.environ.get("ORDERFLOW_NAUTILUS_WHEEL", "")
        try:
            cls.runtime = verify_engine_wheel(cls.wheel)
        except IndependentCalibrationUnavailable as exc:
            if os.environ.get("ORDERFLOW_REQUIRE_INDEPENDENT_ENGINE") == "1":
                raise AssertionError(f"required independent engine unavailable: {exc}") from exc
            raise unittest.SkipTest(f"optional native engine unavailable: {exc}") from exc

    def test_all_eight_real_engine_ledgers_and_local_status(self) -> None:
        for fixture in FIXTURES:
            with self.subTest(case=fixture["fixture_id"]):
                result = run_nautilus_economic_calibration_v2(fixture, wheel_path=self.wheel)
                self.assertEqual(result["status"], "LOCAL_INDEPENDENT_CALIBRATION_PASSED_PARTIAL_MECHANISMS")
                self.assertTrue(result["local_independent_calibration_evidence"])
                self.assertTrue(result["ledger_match"])
                self.assertTrue(result["native_pnl_cash_reconciled"])
                self.assertEqual(result["non_authority_claims"], non_authority_claims())
                self.assertFalse(result["claims"]["external_engine_provenance_verified"])
                self.assertIn("NOT_CALIBRATED", result["coverage_disposition"]["proportional_bps_slippage"])
                self.assertGreater(result["runtime_evidence"]["runtime"]["installed_files_verified"], 10)
                self.assertEqual(result["runtime_evidence"]["audit"]["open_positions"], 0)
                audit = result["runtime_evidence"]["audit"]
                self.assertLessEqual(abs(audit["native_pnl_cash_residual"]), TOLERANCE["absolute"])
                self.assertTrue(audit["native_order_filled_events"])
                self.assertTrue(all(p["ts_closed"] for p in audit["native_positions"]))

    def test_funding_settlements_are_native_and_old_position_at_boundary(self) -> None:
        fixture = FIXTURES[6]
        output = run_fixture(fixture, self.wheel)
        actual = output["ledger"]["cash_flows"]
        self.assertEqual([x["amount"] for x in actual], [0.0, -0.303, 0.204, 0.206])
        self.assertEqual(len(output["runtime_evidence"]["audit"]["native_funding_adjustments"]), 4)
        self.assertTrue(all(a["type"] == "PositionAdjusted" and a["adjustment_type"] == "FUNDING"
                            for a in output["runtime_evidence"]["audit"]["native_funding_adjustments"]))
        self.assertEqual(actual[-1]["timestamp_ns"], BASE_NS + 4 * STEP_NS)
        self.assertEqual(output["ledger"]["fills"][-1]["timestamp_ns"], actual[-1]["timestamp_ns"] + 1)

    def test_adapter_never_reads_expected_or_calls_reference_calculator(self) -> None:
        wrong = copy.deepcopy(FIXTURES[0])
        wrong["expected_ledger"] = {"pretend_equity": -999}
        with patch("orderflow_edge_lab.independent_calibration_v2.canonical_quote_ledger_v2", side_effect=AssertionError("inhouse formula used")):
            actual = run_fixture(wrong, self.wheel)
        self.assertEqual(actual["ledger"], FIXTURES[0]["expected_ledger"])

    def test_intentional_economic_perturbations_fail_actual_engine_reconciliation(self) -> None:
        changes = ("fee", "funding", "bbo", "slippage", "resize", "reversal")
        for change in changes:
            fixture = copy.deepcopy(FIXTURES[6] if change == "funding" else FIXTURES[3])
            case = fixture["assumptions"]["quote_case"]
            if change == "fee":
                case["taker_fee"] *= 2
            elif change == "funding":
                case["steps"][-1]["funding_rate"] *= -1
            elif change == "bbo":
                case["steps"][0]["ask"] += 0.5
            elif change == "slippage":
                case["slippage_ticks"] = 0
            elif change == "resize":
                case["steps"][1]["target"] = 4
            else:
                case["steps"][-2]["target"] = 2
            result = run_nautilus_economic_calibration_v2(_rebind_case(fixture), wheel_path=self.wheel)
            with self.subTest(change=change):
                self.assertEqual(result["status"], "ENGINE_LEDGER_MISMATCH")
                self.assertFalse(result["local_independent_calibration_evidence"])
                self.assertTrue(result["differences"])

    def test_generic_external_runner_executes_real_adapter_without_promoting_external_claim(self) -> None:
        source = str(Path(__file__).resolve().parents[1] / "src")
        bootstrap = f"import sys;sys.path.insert(0,{source!r});from orderflow_edge_lab.independent_calibration_v2 import main;raise SystemExit(main())"
        result = run_pinned_external_engine_calibration_v2(
            FIXTURES[3], ENGINE_SPEC,
            [sys.executable, "-c", bootstrap, "--wheel", self.wheel],
        )
        self.assertEqual(result["status"], "ENGINE_LEDGER_MATCHED_NOT_EXTERNALLY_VERIFIED")
        self.assertFalse(result["non_authority_claims"]["independent_engine_calibration_verified"])

    def test_real_economics_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(json.dumps({"fixture": FIXTURES[4], "wheel_path": self.wheel}) + "\n", encoding="utf-8")
            completed = subprocess.run([sys.executable, "-m", "orderflow_edge_lab.economics_v2", "calibrate-nautilus", str(request)],
                                       capture_output=True, text=True, check=False, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "LOCAL_INDEPENDENT_CALIBRATION_PASSED_PARTIAL_MECHANISMS")
        self.assertEqual(result["engine_ledger"]["terminal_equity"], 9998.992)


if __name__ == "__main__":
    unittest.main()
