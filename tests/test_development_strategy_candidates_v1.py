from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from orderflow_edge_lab.development_strategy_candidates_v1 import (
    DevelopmentCandidateError,
    append_development_trials,
    build_candidate_spec_freeze,
    evaluate_catalog,
    generate_signals,
    load_candidate_catalog,
    load_input_manifest,
    load_point_in_time_jsonl,
    main,
    new_development_trial_ledger,
    verify_candidate_spec_freeze,
    verify_development_trial_ledger,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "development_strategy_candidates_v1.json"


def _row(ts: int, event_type: str, **values: object) -> dict[str, object]:
    return {"observed_at_ns": ts, "symbol": "ENA_USDT", "event_type": event_type, **values}


def _rows(*, include_exit: bool = True) -> list[dict[str, object]]:
    ns = 1_000_000_000
    rows = [
        _row(1 * ns, "quote", bid=100.00, ask=100.10),
        _row(2 * ns, "quote", bid=100.00, ask=100.10),
        _row(2800 * 1_000_000, "trade", price=100.10, size=1.0, side="BUY"),
        _row(3000 * 1_000_000, "trade", price=100.10, size=1.0, side="BUY"),
        _row(3200 * 1_000_000, "trade", price=100.10, size=1.0, side="BUY"),
        _row(3400 * 1_000_000, "trade", price=100.10, size=1.0, side="BUY"),
        _row(3600 * 1_000_000, "trade", price=100.10, size=1.0, side="BUY"),
        _row(4300 * 1_000_000, "quote", bid=100.00, ask=100.30),
        _row(5 * ns, "quote", bid=100.10, ask=100.20),
        _row(5100 * 1_000_000, "quote", bid=100.15, ask=100.25),
    ]
    if include_exit:
        rows.append(_row(11 * ns, "quote", bid=100.35, ask=100.45))
    return rows


def _write_input(root: Path, rows: list[dict[str, object]], *, source_kind: str = "synthetic_test") -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    input_path = root / "events.jsonl"
    input_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest_path = root / "events.manifest.json"
    manifest = {
        "schema_version": 1,
        "dataset_id": "synthetic-causality-fixture",
        "source_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "source_kind": source_kind,
        "partition": "development_only",
        "point_in_time_clock": "observed_at_ns",
        "market_data_visible_during_hypothesis_formation": True,
        "coverage_end_observed_at_ns": rows[-1]["observed_at_ns"],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return input_path, manifest_path


def _catalog() -> dict[str, object]:
    _, payload = load_candidate_catalog(CATALOG_PATH)
    return payload


class DevelopmentStrategyCandidateTests(unittest.TestCase):
    def test_next_event_fill_has_nonzero_friction_and_synthetic_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, manifest_path = _write_input(root, _rows())
            _, manifest = load_input_manifest(manifest_path, input_path)
            events, quotes = load_point_in_time_jsonl(input_path)
            report = evaluate_catalog(_catalog(), events, quotes, input_manifest=manifest)
            absorption = next(row for row in report["candidates"] if row["candidate_id"] == "DEVQ-IMPACT-ABSORPTION-001")
            self.assertEqual(absorption["status"], "COMPLETED_DEVELOPMENT_ONLY")
            self.assertGreater(absorption["signals_generated"], 0)
            self.assertTrue(absorption["summary"]["all_fills_have_nonzero_friction"])
            fill = absorption["fills"][0]
            self.assertGreater(fill["entry_observed_at_ns"], fill["signal_observed_at_ns"])
            self.assertAlmostEqual(fill["gross_bps"] - fill["net_bps"], 3.0)
            self.assertTrue(report["claims"]["synthetic_input_is_not_market_evidence"])
            self.assertFalse(report["claims"]["profitable_edge_established"])

    def test_future_price_edits_do_not_change_prior_signals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, _ = _write_input(root, _rows())
            events, quotes = load_point_in_time_jsonl(input_path)
            candidate = next(row for row in _catalog()["candidates"] if row["candidate_id"] == "DEVQ-IMPACT-ABSORPTION-001")
            original = generate_signals(candidate, events, quotes)
            changed = deepcopy(_rows())
            changed[-1]["bid"] = 1000.0
            changed[-1]["ask"] = 1000.1
            changed_path, _ = _write_input(root / "changed", changed)
            changed_events, changed_quotes = load_point_in_time_jsonl(changed_path)
            revised = generate_signals(candidate, changed_events, changed_quotes)
            cutoff = 5_100_000_000
            self.assertEqual(
                [(signal.ts_ns, signal.side, signal.reason) for signal in original if signal.ts_ns < cutoff],
                [(signal.ts_ns, signal.side, signal.reason) for signal in revised if signal.ts_ns < cutoff],
            )

    def test_missing_future_quote_is_incomplete_and_discards_partial_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path, manifest_path = _write_input(root, _rows(include_exit=False))
            _, manifest = load_input_manifest(manifest_path, input_path)
            events, quotes = load_point_in_time_jsonl(input_path)
            report = evaluate_catalog(_catalog(), events, quotes, input_manifest=manifest)
            absorption = next(row for row in report["candidates"] if row["candidate_id"] == "DEVQ-IMPACT-ABSORPTION-001")
            self.assertEqual(absorption["status"], "INCOMPLETE_MISSING_NEXT_EVENT_FILL")
            self.assertTrue(absorption["fail_closed"])
            self.assertIsNone(absorption["summary"])
            self.assertEqual(absorption["fills"], [])

    def test_missing_quote_data_and_manifest_hash_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_rows = [_row(1_000_000_000, "trade", price=100.0, size=1.0, side="BUY")]
            input_path, manifest_path = _write_input(root, bad_rows)
            with self.assertRaisesRegex(DevelopmentCandidateError, "no complete quote"):
                load_point_in_time_jsonl(input_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DevelopmentCandidateError, "does not match"):
                load_input_manifest(manifest_path, input_path)
            mixed_rows = _rows()
            mixed_rows[-1]["symbol"] = "BTC_USDT"
            mixed_path, _ = _write_input(root / "mixed", mixed_rows)
            with self.assertRaisesRegex(DevelopmentCandidateError, "exactly one symbol"):
                load_point_in_time_jsonl(mixed_path)

    def test_candidate_freeze_and_trial_ledger_are_hash_pinned_and_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze = build_candidate_spec_freeze(CATALOG_PATH, frozen_at="2026-10-06T00:00:00Z")
            self.assertTrue(verify_candidate_spec_freeze(freeze, CATALOG_PATH))
            with self.assertRaisesRegex(DevelopmentCandidateError, "candidate_ids"):
                build_candidate_spec_freeze(CATALOG_PATH, candidate_ids=["missing"], frozen_at="2026-10-06T00:00:00Z")
            input_path, manifest_path = _write_input(root, _rows())
            manifest_raw, manifest = load_input_manifest(manifest_path, input_path)
            events, quotes = load_point_in_time_jsonl(input_path)
            evaluation = evaluate_catalog(_catalog(), events, quotes, input_manifest=manifest)
            freeze_sha = hashlib.sha256(json.dumps(freeze, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            ledger = new_development_trial_ledger(
                family_name="test-family", candidate_freeze_sha256=freeze_sha, created_at="2026-10-06T00:00:00Z"
            )
            ledger = append_development_trials(
                ledger,
                evaluation,
                source_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
                input_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                candidate_freeze_sha256=freeze_sha,
                recorded_at="2026-10-06T00:00:00Z",
            )
            self.assertTrue(verify_development_trial_ledger(ledger))
            self.assertEqual([trial["trial_number"] for trial in ledger["trials"]], [1, 2])
            self.assertAlmostEqual(ledger["trials"][1]["allocated_alpha"], 0.05 / (2 * 3))
            self.assertNotIn("bonferroni_alpha", ledger["trials"][1])
            with self.assertRaisesRegex(DevelopmentCandidateError, "already counted"):
                append_development_trials(
                    ledger,
                    evaluation,
                    source_sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
                    input_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                    candidate_freeze_sha256=freeze_sha,
                    recorded_at="2026-10-06T00:00:00Z",
                )

    def test_module_cli_freezes_then_runs_and_writes_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze_path = root / "candidate.freeze.json"
            self.assertEqual(
                main(
                    [
                        "--catalog", str(CATALOG_PATH), "--freeze-output", str(freeze_path), "--frozen-at", "2026-10-06T00:00:00Z",
                    ]
                ),
                0,
            )
            input_path, manifest_path = _write_input(root, _rows())
            output = root / "report.json"
            ledger = root / "ledger.json"
            self.assertEqual(
                main(
                    [
                        "--catalog", str(CATALOG_PATH), "--input", str(input_path), "--input-manifest", str(manifest_path),
                        "--candidate-freeze", str(freeze_path), "--trial-ledger", str(ledger), "--recorded-at", "2026-10-06T00:00:00Z",
                        "--output", str(output),
                    ]
                ),
                0,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
            saved_ledger = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertTrue(report["claims"]["candidate_specification_frozen"])
            self.assertEqual(report["trial_ledger"]["trials_recorded"], 2)
            self.assertTrue(verify_development_trial_ledger(saved_ledger))


if __name__ == "__main__":
    unittest.main()
