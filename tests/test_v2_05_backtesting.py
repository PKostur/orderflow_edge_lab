from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from orderflow_edge_lab.contracts_v2 import (
    OPEN_CLOSED,
    build_canonical_source_set,
    build_coverage_result,
    build_utc_interval,
    missing_value,
    observed_value,
)
from orderflow_edge_lab.cli.main import available_commands
from orderflow_edge_lab.economics_v2 import (
    ECONOMIC_CALIBRATION_FIXTURE_SCHEMA,
    EXECUTION_ENVELOPE_SCHEMA,
    EconomicsV2Error,
    attach_universe_availability_v2,
    build_economic_calibration_fixture_v2,
    build_economics_qualification_v2,
    build_funding_dataset_v2,
    build_not_calibrated_external_engine_report_v2,
    build_price_dataset_v2,
    build_settlement_coverage_v2,
    build_universe_availability_v2,
    compare_external_engine_calibration_v2,
    evaluate_execution_envelope_v2,
    main,
    read_funding_coverage_v1_v2,
    run_pinned_external_engine_calibration_v2,
    run_validated_accounting_v2,
    run_validated_sweep_v2,
    validate_execution_inputs_v2,
)
from orderflow_edge_lab.universal_backtest import FunctionStrategy, run_backtest


SHA_A = "a" * 64
SHA_B = "b" * 64


def _source_set() -> dict:
    return build_canonical_source_set(
        [{"source_id": "raw-fixture", "size_bytes": 42, "sha256": SHA_A}]
    )


def _interval() -> dict:
    return build_utc_interval("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", convention=OPEN_CLOSED)


def _complete_coverage(value: float = 0.0) -> dict:
    return build_coverage_result(
        "funding_settlements_open_closed_v2",
        _interval(),
        [{"observation_id": "settlement-1", "observation": observed_value(value)}],
    )


def _missing_coverage() -> dict:
    return build_coverage_result(
        "funding_settlements_open_closed_v2",
        _interval(),
        [{"observation_id": "settlement-1", "observation": missing_value("provider_gap")}],
    )


def _envelope(*, slippage: float = 0.0, impact: dict | None = None) -> dict:
    return {
        "schema": EXECUTION_ENVELOPE_SCHEMA,
        "scenario_id": "latency-and-freshness-fixture",
        "decision_to_order_latency_ns": 10,
        "maximum_entry_delay_ns": 20,
        "entry_quote_max_age_ns": 5,
        "exit_quote_max_age_ns": 5,
        "maximum_exit_delay_ns": 20,
        "round_trip_fee_bps": 1.0,
        "additional_slippage_bps": slippage,
        "order_size": 2.0,
        "impact": impact or {"mode": "UNAVAILABLE"},
        "diagnostic_only": False,
        "policy_sha256": SHA_A,
    }


def _fixture() -> dict:
    return {
        "schema": ECONOMIC_CALIBRATION_FIXTURE_SCHEMA,
        "fixture_id": "economic-ledger-fixture-v2",
        "protocol_sha256": SHA_A,
        "source_set": _source_set(),
        "assumptions": {
            "bid_ask": {"entry": "ask", "exit": "bid"},
            "fees": {"round_trip_bps": 2.0},
            "slippage": {"additional_bps": 1.0},
            "funding": {"positive_rate_long_pays": True},
            "terminal_liquidation": {"required": True},
        },
        "expected_ledger": {
            "event_order": ["funding", "exit", "entry", "mark", "terminal_liquidation"],
            "fills": [{"side": "BUY", "price": 101.0, "quantity": 1.0}],
            "cash_flows": [{"kind": "funding", "amount": -0.1}],
            "trades": [{"net_pnl": 3.0}],
            "turnover_units": 2.0,
            "terminal_equity": 1.0003,
        },
        "comparison_tolerance": {"absolute": 1e-10, "relative": 1e-10},
    }


def _engine_spec() -> dict:
    return {
        "engine_name": "external-event-engine",
        "engine_version": "1.2.3",
        "distribution_sha256": SHA_B,
        "runner_protocol_version": "orderflow-external-ledger-v1",
    }


class ExecutionValidationTests(unittest.TestCase):
    def test_f1_rejects_invalid_costs_and_preserves_valid_legacy_result(self) -> None:
        invalids = [
            {"round_trip_cost_bps": -1.0, "slippage_bps_per_turnover_unit": 0.0, "max_abs_position": 1.0},
            {"round_trip_cost_bps": math.nan, "slippage_bps_per_turnover_unit": 0.0, "max_abs_position": 1.0},
            {"round_trip_cost_bps": 0.0, "slippage_bps_per_turnover_unit": math.inf, "max_abs_position": 1.0},
            {"round_trip_cost_bps": 0.0, "slippage_bps_per_turnover_unit": 0.0, "max_abs_position": 0.0},
        ]
        for execution in invalids:
            with self.subTest(execution=execution):
                with self.assertRaisesRegex(EconomicsV2Error, "finite|non-negative|positive"):
                    validate_execution_inputs_v2(execution)

        index = pd.date_range("2026-01-01T00:00:00Z", periods=5, freq="h")
        frame = pd.DataFrame(
            {"open": [100, 101, 102, 103, 104], "high": [101, 102, 103, 104, 105],
             "low": [99, 100, 101, 102, 103], "close": [100, 101, 102, 103, 104]}, index=index
        )
        strategy = FunctionStrategy("fixed", lambda _frame, _params: pd.Series([1, 1, 0, 0, 0], index=_frame.index), warmup_bars=3)
        execution = {"round_trip_cost_bps": 2.0, "slippage_bps_per_turnover_unit": 1.0, "max_abs_position": 1.0}
        legacy = run_backtest(frame, strategy, {}, execution=type("E", (), execution)())
        wrapped = run_validated_accounting_v2(
            frame, strategy, {}, execution, accounting_mode="legacy_compatible", source_set=_source_set(), policy_sha256=SHA_A
        )
        self.assertEqual(wrapped["engine_result"], legacy)
        self.assertEqual(wrapped["execution_policy"]["validation"], "finite_nonnegative_costs_and_positive_size_v2")
        for mode in ("legacy_compatible", "canonical_v2", "canonical_v3", "audit"):
            with self.subTest(mode=mode), self.assertRaises(EconomicsV2Error):
                run_validated_accounting_v2(
                    frame, strategy, {}, invalids[0], accounting_mode=mode, source_set=_source_set(), policy_sha256=SHA_A
                )
        with self.assertRaises(EconomicsV2Error):
            run_validated_sweep_v2(
                {"BTC_USDT": frame}, strategy, {}, [-1.0], slippage_bps_per_turnover_unit=0.0,
                source_set=_source_set(), policy_sha256=SHA_A,
            )
        sweep = run_validated_sweep_v2(
            {"BTC_USDT": frame}, strategy, {}, [2.0], slippage_bps_per_turnover_unit=1.0,
            source_set=_source_set(), policy_sha256=SHA_A,
        )
        self.assertEqual(sweep["engine_result"]["results"][0]["round_trip_cost_bps"], 2.0)


class ExecutionEnvelopeTests(unittest.TestCase):
    def test_f2_dispatcher_discovers_owned_cli_delegator(self) -> None:
        self.assertEqual(
            available_commands()["orderflow-economics-v2"],
            "economics_v2",
        )

    def test_f2_latency_stale_timeout_and_adverse_monotonicity(self) -> None:
        signals = [{"signal_id": "s1", "signal_at_ns": 100, "side": 1, "exit_maturity_ns": 50}]
        quotes = [
            {"quote_id": "before-latency", "received_at_ns": 105, "quote_at_ns": 105, "bid": 99.0, "ask": 100.0},
            {"quote_id": "entry", "received_at_ns": 111, "quote_at_ns": 110, "bid": 100.0, "ask": 101.0},
            {"quote_id": "exit", "received_at_ns": 151, "quote_at_ns": 150, "bid": 103.0, "ask": 104.0},
        ]
        result = evaluate_execution_envelope_v2(signals, quotes, _envelope(), _source_set())
        record = result["records"][0]
        self.assertEqual(record["disposition"], "FILLED")
        self.assertEqual(record["entry"]["quote_id"], "entry")
        self.assertGreaterEqual(record["entry"]["received_at_ns"], 110)
        self.assertEqual(result["disposition_counts"]["FILLED"], 1)
        self.assertEqual(result["source_set_sha256"], _source_set()["source_set_sha256"])
        self.assertEqual(result["capabilities"]["depth_impact"], "UNAVAILABLE")
        short = evaluate_execution_envelope_v2(
            [{"signal_id": "short", "signal_at_ns": 100, "side": -1, "exit_maturity_ns": 50}], quotes, _envelope(), _source_set()
        )
        self.assertEqual(short["records"][0]["entry"]["fill_price"], 100.0)
        self.assertEqual(short["records"][0]["exit"]["fill_price"], 104.0)

        stale_quotes = [
            {"quote_id": "stale-entry", "received_at_ns": 111, "quote_at_ns": 0, "bid": 100.0, "ask": 101.0},
        ]
        stale = evaluate_execution_envelope_v2(signals, stale_quotes, _envelope(), _source_set())
        self.assertEqual(stale["records"][0]["disposition"], "ENTRY_STALE")
        timeout_quotes = quotes[:2] + [
            {"quote_id": "late-exit", "received_at_ns": 171, "quote_at_ns": 170, "bid": 103.0, "ask": 104.0}
        ]
        timeout = evaluate_execution_envelope_v2(signals, timeout_quotes, _envelope(), _source_set())
        self.assertEqual(timeout["records"][0]["disposition"], "EXIT_TIMEOUT")

        worse = evaluate_execution_envelope_v2(signals, quotes, _envelope(slippage=10.0), _source_set())
        self.assertEqual(worse["records"][0]["disposition"], "FILLED")
        self.assertLessEqual(worse["records"][0]["net_bps"], result["records"][0]["net_bps"])
        with self.assertRaisesRegex(EconomicsV2Error, "unsupported shape"):
            evaluate_execution_envelope_v2(
                signals, quotes, _envelope(impact={"mode": "DISPLAYED_DEPTH_LINEAR", "depth_field": "depth", "impact_bps_per_depth_fraction": 1.0}), _source_set()
            )

    def test_f2_cli_is_executable_for_evaluate_envelope(self) -> None:
        request = {
            "signals": [{"signal_id": "s", "signal_at_ns": 0, "side": -1, "exit_maturity_ns": 2}],
            "quotes": [
                {"quote_id": "e", "received_at_ns": 10, "quote_at_ns": 10, "bid": 99, "ask": 100},
                {"quote_id": "x", "received_at_ns": 20, "quote_at_ns": 20, "bid": 98, "ask": 99},
            ],
            "envelope": {**_envelope(), "decision_to_order_latency_ns": 0, "maximum_entry_delay_ns": 10, "maximum_exit_delay_ns": 30},
            "source_set": _source_set(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "request.json"
            path.write_text(json.dumps(request), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["evaluate-envelope", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["analysis"], "quote_receipt_execution_envelope_v2")


class FundingQualificationAndSettlementTests(unittest.TestCase):
    def _datasets(self, *, funding_venue: str = "MEXC", funding_coverage: dict | None = None) -> tuple[dict, dict]:
        price = build_price_dataset_v2(
            leg_id="trend", symbol="BTC_USDT", venue="MEXC", contract_id="BTC_USDT_PERP",
            retrieval_interval=_interval(), source_set=_source_set(), coverage=_complete_coverage(), policy_sha256=SHA_A,
        )
        funding = build_funding_dataset_v2(
            leg_id="trend", symbol="BTC_USDT", venue=funding_venue, contract_id="BTC_USDT_PERP",
            rate_convention="positive_rate_long_pays", settlement_schedule={"frequency": "8h"},
            settlement_interval_convention=OPEN_CLOSED, retrieval_interval=_interval(), source_set=_source_set(),
            coverage=funding_coverage or _complete_coverage(0.0), policy_sha256=SHA_A,
        )
        return price, funding

    def test_f3_venue_and_missing_funding_are_not_qualified_and_zero_is_complete(self) -> None:
        with self.assertRaisesRegex(EconomicsV2Error, "funding coverage"):
            build_funding_dataset_v2(
                leg_id="trend", symbol="BTC_USDT", venue="MEXC", contract_id="BTC_USDT_PERP",
                rate_convention="positive_rate_long_pays", settlement_schedule={"frequency": "8h"},
                settlement_interval_convention=OPEN_CLOSED, retrieval_interval=_interval(), source_set=_source_set(),
                coverage=build_coverage_result("unrelated_coverage", _interval(), [{"observation_id": "x", "observation": observed_value(0.0)}]),
                policy_sha256=SHA_A,
            )
        price, mismatch_funding = self._datasets(funding_venue="Binance")
        mismatch = build_economics_qualification_v2(price, mismatch_funding, qualification_policy_sha256=SHA_B)
        self.assertEqual(mismatch["qualification_status"], "descriptive_incomplete_economics")
        self.assertFalse(mismatch["qualification_checks"]["venue_match"])
        self.assertEqual(mismatch["manifest"]["outcome"], "INCOMPLETE")

        price, matching = self._datasets()
        qualified = build_economics_qualification_v2(price, matching, qualification_policy_sha256=SHA_B)
        self.assertEqual(qualified["qualification_status"], "venue_consistent_complete")
        self.assertEqual(qualified["per_leg_coverage"]["funding"]["coverage_status"], "COMPLETE")
        self.assertEqual(qualified["funding_dataset"]["coverage"]["observations"][0]["observation"]["value"], 0.0)

        price, incomplete = self._datasets(funding_coverage=_missing_coverage())
        rejected = build_economics_qualification_v2(price, incomplete, qualification_policy_sha256=SHA_B)
        self.assertEqual(rejected["qualification_status"], "descriptive_incomplete_economics")
        self.assertFalse(rejected["qualification_checks"]["funding_coverage_complete"])

    def test_f4_endpoint_settlements_match_open_closed_cashflow_and_missing_fails_closed(self) -> None:
        day_one = build_utc_interval("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", convention=OPEN_CLOSED)
        day_two = build_utc_interval("2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z", convention=OPEN_CLOSED)
        result = build_settlement_coverage_v2(
            [{"leg_id": "carry", "interval_id": "d1", "interval": day_one}, {"leg_id": "carry", "interval_id": "d2", "interval": day_two}],
            [
                {"leg_id": "carry", "settlement_id": "d1-interior", "timestamp_utc": "2026-01-01T12:00:00Z", "observation": observed_value(0.0005)},
                {"leg_id": "carry", "settlement_id": "at-d1-end", "timestamp_utc": "2026-01-02T00:00:00Z", "observation": observed_value(0.0)},
                {"leg_id": "carry", "settlement_id": "at-d2-end", "timestamp_utc": "2026-01-03T00:00:00Z", "observation": observed_value(0.001)},
            ],
        )
        self.assertEqual(result["coverage"]["status"], "COMPLETE")
        self.assertEqual(result["per_held_interval"][0]["applied_settlement_ids"], ["d1-interior", "at-d1-end"])
        self.assertEqual(result["cashflow_settlements"][1]["rate"], 0.0)
        missing = build_settlement_coverage_v2(
            [{"leg_id": "carry", "interval_id": "d1", "interval": day_one}],
            [{"leg_id": "carry", "settlement_id": "missing-end", "timestamp_utc": "2026-01-02T00:00:00Z", "observation": missing_value("provider_gap")}],
        )
        self.assertEqual(missing["coverage"]["status"], "INCOMPLETE")
        self.assertEqual(missing["cashflow_settlements"], [])
        with self.assertRaisesRegex(EconomicsV2Error, "exactly one"):
            build_settlement_coverage_v2(
                [{"leg_id": "carry", "interval_id": "d1", "interval": day_one}],
                [{"leg_id": "carry", "settlement_id": "at-start", "timestamp_utc": "2026-01-01T00:00:00Z", "observation": observed_value(0.01)}],
            )
        legacy = read_funding_coverage_v1_v2({"schema_version": 1, "analysis": "cross_sectional_funding_coverage_audit_v1", "status": "FUNDING_COVERAGE_INCOMPLETE"})
        self.assertEqual(legacy["legacy_interval_rule"], "strict_inside_preserved_unmodified")


class CalibrationAndAvailabilityTests(unittest.TestCase):
    def test_f5_external_engine_harness_detects_drift_and_never_claims_calibration(self) -> None:
        fixture = _fixture()
        engine = _engine_spec()
        expected = build_economic_calibration_fixture_v2(fixture)["expected_ledger"]
        matched = compare_external_engine_calibration_v2(fixture, engine, {"engine_identity": engine, "ledger": expected})
        self.assertTrue(matched["ledger_match"])
        self.assertEqual(matched["status"], "ENGINE_LEDGER_MATCHED_NOT_EXTERNALLY_VERIFIED")
        self.assertFalse(matched["non_authority_claims"]["independent_engine_calibration_verified"])
        wrong = json.loads(json.dumps(expected))
        wrong["cash_flows"][0]["amount"] = 0.1
        mismatch = compare_external_engine_calibration_v2(fixture, engine, {"engine_identity": engine, "ledger": wrong})
        self.assertFalse(mismatch["ledger_match"])
        self.assertTrue(mismatch["differences"])
        unavailable = build_not_calibrated_external_engine_report_v2(fixture, engine, reason="engine_not_installed")
        self.assertEqual(unavailable["status"], "NOT_CALIBRATED_ENGINE_UNAVAILABLE")
        runner_unavailable = run_pinned_external_engine_calibration_v2(fixture, engine, ["definitely-no-engine-binary"])
        self.assertEqual(runner_unavailable["status"], "NOT_CALIBRATED_ENGINE_UNAVAILABLE")

    def test_f6_frozen_universe_sidecar_records_attrition_and_reconstructs_denominator(self) -> None:
        universe = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        records = [
            {"symbol": "AAA", "date_utc": "2026-01-02", "leg": "S1", "availability": "ELIGIBLE", "reason": None, "input_manifest_sha256": SHA_A, "active_side": "LONG"},
            {"symbol": "BBB", "date_utc": "2026-01-02", "leg": "S1", "availability": "UNAVAILABLE", "reason": "delisted", "input_manifest_sha256": SHA_A, "active_side": "NONE"},
            {"symbol": "CCC", "date_utc": "2026-01-02", "leg": "S1", "availability": "INELIGIBLE", "reason": "insufficient_warmup", "input_manifest_sha256": SHA_A, "active_side": "NONE"},
            {"symbol": "DDD", "date_utc": "2026-01-02", "leg": "S1", "availability": "UNAVAILABLE", "reason": "missing_funding", "input_manifest_sha256": SHA_A, "active_side": "NONE"},
            {"symbol": "EEE", "date_utc": "2026-01-02", "leg": "S1", "availability": "UNAVAILABLE", "reason": "fetch_error", "input_manifest_sha256": SHA_A, "active_side": "NONE"},
        ]
        sidecar = build_universe_availability_v2(
            universe, records, source_set=_source_set(), policy_sha256=SHA_A, minimum_names_by_leg={"S1": 2}
        )
        summary = sidecar["daily_leg_summary"][0]
        self.assertEqual(summary["frozen_universe_count"], 5)
        self.assertEqual(summary["eligible_count"], 1)
        self.assertEqual(summary["minimum_name_status"], "DECLARED_NOT_MET")
        self.assertTrue(summary["subset_based"])
        self.assertEqual({record["reason"] for record in sidecar["records"] if record["reason"]}, {"delisted", "insufficient_warmup", "missing_funding", "fetch_error"})
        linked = attach_universe_availability_v2({"schema_version": 1, "watch_id": "multi-premia-blend-v1"}, sidecar)
        self.assertFalse(linked["claims"]["legacy_v1_report_mutated"])
        with self.assertRaisesRegex(EconomicsV2Error, "cover every frozen"):
            build_universe_availability_v2(universe, records[:-1], source_set=_source_set(), policy_sha256=SHA_A)


if __name__ == "__main__":
    unittest.main()
