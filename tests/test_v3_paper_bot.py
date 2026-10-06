from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orderflow_edge_lab.cli.paper_bot_v3 import _signal_fingerprint, main as cli_main
from orderflow_edge_lab.paper_bot_v3 import (
    POLICY_SCHEMA,
    PaperBotV3Error,
    _sha256,
    run_paper_bot_v3,
    validate_paper_bot_artifact_v3,
    verify_paper_bot_artifact_file_v3,
    write_paper_bot_artifact_v3,
)


def policy(**changes):
    value = {
        "schema": POLICY_SCHEMA,
        "signal_id": "test-signal-v1",
        "signal_fingerprint": "5ef570fe5c2e6a32745b9eb6fa80f010a00bc9b0a528e3a7bf7a4da15aa153ef",
        "instrument": {
            "symbol": "TEST-USD",
            "contract_multiplier": 1.0,
            "instrument_type": "synthetic_linear",
            "funding_treatment": "not_modeled",
        },
        "initial_cash": 1_000.0,
        "fee_rate": 0.001,
        "slippage_bps": 1.0,
        "max_quote_age_ns": 10,
        "max_position_fraction": 0.5,
        "max_gross_exposure_fraction": 0.5,
        "max_loss_fraction": 0.5,
        "max_drawdown_fraction": 0.5,
    }
    value.update(changes)
    return value


def frame(ts: int, *, bid: float = 99.0, ask: float = 101.0, received: int | None = None, close: float | None = None):
    return {
        "ts_ns": ts,
        "received_ns": ts if received is None else received,
        "symbol": "TEST-USD",
        "bid": bid,
        "ask": ask,
        "close": (bid + ask) / 2 if close is None else close,
        "source_id": "fixture",
        "batch_id": "batch-1",
        "extra_causal_feature": ts,
    }


class PaperBotV3Tests(unittest.TestCase):
    def _rehash_checkpoint(self, checkpoint):
        """Model an attacker who can recompute every local self-hash."""

        events = checkpoint["event_chain"]
        prior = "GENESIS"
        for event in events:
            event["prior_event_sha256"] = prior
            event["event_sha256"] = _sha256({key: event[key] for key in event if key != "event_sha256"})
            prior = event["event_sha256"]
        checkpoint["event_chain_head"] = prior
        checkpoint["state_sha256"] = _sha256(checkpoint["state"])
        checkpoint["checkpoint_sha256"] = _sha256({key: checkpoint[key] for key in checkpoint if key != "checkpoint_sha256"})

    def test_signal_is_causal_and_only_the_next_quote_can_fill_with_declared_costs(self):
        frames = [frame(1), frame(2, bid=100.0, ask=101.0), frame(3, bid=100.0, ask=101.0)]
        observed = []

        def signal(history):
            observed.append([item["ts_ns"] for item in history])
            return 0.5

        artifact = run_paper_bot_v3(frames, signal, policy())
        self.assertEqual(artifact["status"], "COMPLETE")
        self.assertEqual(observed, [[1], [1, 2], [1, 2, 3]])
        first, second = artifact["event_chain"][:2]
        self.assertIsNone(first["execution"])
        self.assertEqual(first["signal"]["target_fraction"], 0.5)
        self.assertEqual(second["execution"]["signal_event_id"], first["frame_id"])
        self.assertEqual(second["execution"]["fill_event_id"], second["frame_id"])
        self.assertAlmostEqual(second["execution"]["fill_price"], 101.0 * 1.0001)
        self.assertGreater(second["execution"]["fee"], 0.0)
        self.assertGreater(artifact["summary"]["fees_paid"], 0.0)
        self.assertEqual(artifact["mode"], "SIMULATED_OFFLINE_ONLY")
        self.assertIn("Funding", " ".join(artifact["limitations"]))

    def test_bad_quotes_latch_without_flatten_or_same_event_fill(self):
        cases = {
            "stale_quote": frame(2, received=20),
            "future_quote": frame(2, received=1),
            "out_of_order_quote": frame(1, bid=100.0, ask=102.0),
            "duplicate_quote": frame(1),
            "malformed_quote": {**frame(2), "bid": float("nan")},
        }
        for expected, bad in cases.items():
            with self.subTest(expected=expected):
                artifact = run_paper_bot_v3([frame(1), bad, frame(3)], lambda _: 0.5, policy())
                self.assertEqual(artifact["status"], "HALTED")
                self.assertEqual(artifact["summary"]["halt_reason"], expected)
                self.assertEqual(artifact["summary"]["quantity"], 0.0)
                self.assertIsNotNone(artifact["summary"]["pending_target"])
                self.assertIsNone(artifact["event_chain"][-1]["execution"])
                self.assertTrue(artifact["checkpoint"]["state"]["halted"])

    def test_adjacent_nanosecond_quotes_remain_causal_and_next_quote_only(self):
        artifact = run_paper_bot_v3([frame(100), frame(101), frame(102)], lambda _: 0.5, policy())
        self.assertEqual(artifact["status"], "COMPLETE")
        self.assertIsNone(artifact["event_chain"][0]["execution"])
        self.assertEqual(artifact["event_chain"][1]["execution"]["signal_event_id"], artifact["event_chain"][0]["frame_id"])
        self.assertEqual(artifact["event_chain"][1]["execution"]["fill_event_id"], artifact["event_chain"][1]["frame_id"])

    def test_loss_budget_latches_and_preserves_existing_position_and_pending_target(self):
        constrained = policy(max_loss_fraction=0.20, max_drawdown_fraction=0.20)
        artifact = run_paper_bot_v3(
            [frame(1), frame(2), frame(3, bid=49.0, ask=51.0)], lambda _: 0.5, constrained
        )
        self.assertEqual(artifact["status"], "HALTED")
        self.assertIn(artifact["summary"]["halt_reason"], {"max_loss_budget_breached", "max_drawdown_budget_breached"})
        self.assertGreater(artifact["summary"]["quantity"], 0.0)
        self.assertIsNotNone(artifact["summary"]["pending_target"])
        self.assertIsNone(artifact["event_chain"][-1]["execution"])

    def test_restart_is_equivalent_and_checkpoint_corruption_or_prefix_replay_fails_closed(self):
        frames = [frame(1), frame(2), frame(3), frame(4)]
        signal = lambda _: 0.25
        uninterrupted = run_paper_bot_v3(frames, signal, policy(), run_id="restart")
        partial = run_paper_bot_v3(frames, signal, policy(), run_id="restart", max_events=2)
        self.assertEqual(partial["status"], "PARTIAL")
        resumed = run_paper_bot_v3(frames, signal, policy(), run_id="restart", checkpoint=partial["checkpoint"])
        self.assertEqual(resumed, uninterrupted)
        self.assertEqual(validate_paper_bot_artifact_v3(resumed)["artifact_sha256"], uninterrupted["artifact_sha256"])

        corrupt = deepcopy(partial["checkpoint"])
        corrupt["state"]["cash"] += 1.0
        with self.assertRaises(PaperBotV3Error):
            run_paper_bot_v3(frames, signal, policy(), run_id="restart", checkpoint=corrupt)
        changed_prefix = deepcopy(frames)
        changed_prefix[0]["close"] = 999.0
        with self.assertRaises(PaperBotV3Error):
            run_paper_bot_v3(changed_prefix, signal, policy(), run_id="restart", checkpoint=partial["checkpoint"])

    def test_semantic_replay_rejects_rehashed_cash_history_final_state_and_status_forgery(self):
        frames = [frame(1), frame(2), frame(3), frame(4)]
        partial = run_paper_bot_v3(frames, lambda _: 0.25, policy(), run_id="semantic", max_events=2)
        cash = deepcopy(partial["checkpoint"])
        cash["state"]["cash"] += 17.0
        cash["event_chain"][-1]["state_sha256"] = _sha256(cash["state"])
        self._rehash_checkpoint(cash)
        with self.assertRaisesRegex(PaperBotV3Error, "semantic replay"):
            run_paper_bot_v3(frames, lambda _: 0.25, policy(), run_id="semantic", checkpoint=cash)

        history = deepcopy(partial["checkpoint"])
        history["state"]["history"][0]["close"] = 123.0
        history["event_chain"][-1]["state_sha256"] = _sha256(history["state"])
        self._rehash_checkpoint(history)
        with self.assertRaisesRegex(PaperBotV3Error, "semantic replay"):
            run_paper_bot_v3(frames, lambda _: 0.25, policy(), run_id="semantic", checkpoint=history)

        status = deepcopy(partial["checkpoint"])
        status["status"] = "COMPLETE"
        self._rehash_checkpoint(status)
        with self.assertRaisesRegex(PaperBotV3Error, "status does not match semantic replay"):
            run_paper_bot_v3(frames, lambda _: 0.25, policy(), run_id="semantic", checkpoint=status)

        final_binding = deepcopy(partial["checkpoint"])
        final_binding["event_chain"][-1]["state_sha256"] = "0" * 64
        self._rehash_checkpoint(final_binding)
        with self.assertRaisesRegex(PaperBotV3Error, "semantic replay"):
            run_paper_bot_v3(frames, lambda _: 0.25, policy(), run_id="semantic", checkpoint=final_binding)

    def test_post_cost_position_cap_and_artifact_summary_are_semantically_bound(self):
        constrained = policy(max_position_fraction=0.5, max_gross_exposure_fraction=1.0)
        artifact = run_paper_bot_v3([frame(1), frame(2)], lambda _: 0.5, constrained)
        execution = artifact["event_chain"][1]["execution"]
        self.assertTrue(execution["capped_by_cash_or_exposure"])
        self.assertLessEqual(execution["post_cost_position_fraction"], constrained["max_position_fraction"] + 1e-9)
        self.assertLessEqual(execution["post_cost_gross_exposure_fraction"], constrained["max_gross_exposure_fraction"] + 1e-9)

        halted = run_paper_bot_v3([frame(1), frame(2, received=20)], lambda _: 0.5, policy())
        forged = deepcopy(halted)
        forged["summary"]["halt_reason"] = None
        forged["artifact_sha256"] = _sha256({key: forged[key] for key in forged if key != "artifact_sha256"})
        with self.assertRaisesRegex(PaperBotV3Error, "summary does not match semantic replay"):
            validate_paper_bot_artifact_v3(forged)

    def test_signal_fingerprint_and_non_posix_publication_fail_closed(self):
        bad_policy = policy(signal_fingerprint="not-a-sha256")
        with self.assertRaisesRegex(PaperBotV3Error, "signal_fingerprint"):
            run_paper_bot_v3([frame(1)], lambda _: 0.0, bad_policy)
        artifact = run_paper_bot_v3([frame(1)], lambda _: 0.0, policy())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "unsupported.json"
            with patch("orderflow_edge_lab.paper_bot_v3.os.name", "nt"):
                with self.assertRaisesRegex(PaperBotV3Error, "requires POSIX"):
                    write_paper_bot_artifact_v3(target, artifact)

    def test_deterministic_idempotence_signal_failure_and_atomic_write_failure(self):
        frames = [frame(1), frame(2), frame(3)]
        left = run_paper_bot_v3(frames, lambda _: -0.25, policy())
        right = run_paper_bot_v3(frames, lambda _: -0.25, policy())
        self.assertEqual(left, right)
        failed_signal = run_paper_bot_v3([frame(1)], lambda _: (_ for _ in ()).throw(RuntimeError("injected")), policy())
        self.assertEqual(failed_signal["status"], "HALTED")
        self.assertEqual(failed_signal["summary"]["halt_reason"], "signal_fn_error:RuntimeError")
        self.assertEqual(failed_signal["summary"]["quantity"], 0.0)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "simulated.json"
            with patch("orderflow_edge_lab.paper_bot_v3.os.link", side_effect=OSError("injected link failure")):
                with self.assertRaises(OSError):
                    write_paper_bot_artifact_v3(output, left)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            write_paper_bot_artifact_v3(output, left)
            self.assertEqual(verify_paper_bot_artifact_file_v3(output)["status"], "VERIFIED_SIMULATED_LOCAL_REPLAY")
            with self.assertRaises(FileExistsError):
                write_paper_bot_artifact_v3(output, left)
            output.write_text(output.read_text(encoding="utf-8").replace("SIMULATED", "SIMULAT3D", 1), encoding="utf-8")
            self.assertEqual(verify_paper_bot_artifact_file_v3(output)["status"], "INVALID")

    def test_cli_synthetic_only_and_live_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / "demo.json")
            self.assertEqual(cli_main(["--synthetic-demo", "--output", output]), 0)
            self.assertEqual(cli_main(["--synthetic-demo", "--output", output]), 2)
            flat_output = Path(directory) / "flat.json"
            self.assertEqual(cli_main(["--synthetic-demo", "--signal", "flat", "--output", str(flat_output)]), 0)
            self.assertEqual(json.loads(flat_output.read_text(encoding="utf-8"))["policy"]["signal_fingerprint"], _signal_fingerprint("flat"))
            mismatched_policy = Path(directory) / "mismatched-policy.json"
            mismatched_policy.write_text(json.dumps(policy()), encoding="utf-8")
            self.assertEqual(
                cli_main(["--synthetic-demo", "--policy", str(mismatched_policy), "--output", str(Path(directory) / "bad.json")]),
                2,
            )
            live_output = str(Path(directory) / "live.json")
            self.assertEqual(cli_main(["--synthetic-demo", "--mode", "live", "--output", live_output]), 2)
            self.assertFalse(Path(live_output).exists())


if __name__ == "__main__":
    unittest.main()
