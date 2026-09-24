from __future__ import annotations

import unittest

from orderflow_edge_lab.jev_research_action import execute_research_action


class JevResearchActionTests(unittest.TestCase):
    def _shadow(self, *, ready: bool = False):
        return {
            "analysis": "universal_session_alignment_prospective_shadow",
            "watch_id": "watch-v1",
            "source": {"symbols": ["BTC_USDT", "ETH_USDT"]},
            "source_sha256": {"BTC_USDT": "a", "ETH_USDT": "b"},
            "evidence_progress": {"all_strategies_ready": ready},
            "claims": {
                "pre_start_entries_excluded_from_scoring": True,
                "terminal_snapshot_liquidations_excluded_from_completed_trade_scoring": True,
                "labels_do_not_gate_trade_generation": True,
                "formal_verdict_withheld_until_review_requirements": True,
                "candidate_promoted": False,
                "session_filter_authorized": False,
                "live_trading_authorized": False,
                "leverage_authorized": False,
                "profitable_edge_established": False,
            },
            "reports": [
                {
                    "audit_id": "DON8",
                    "evidence_progress": {
                        "completed_trade_count": 0,
                        "open_post_start_snapshot_count": 0,
                        "completed_observed_symbol_count": 0,
                    },
                    "hypothesis_sample_progress": [
                        {
                            "hypothesis_id": "H1",
                            "aligned_completed_trade_count": 0,
                            "comparison_completed_trade_count": 0,
                            "paired_observed_symbol_count": 0,
                            "both_states_observed": False,
                        }
                    ],
                }
            ],
        }

    def _decision(self, action: str):
        return {
            "analysis": "jev_research_decision_layer_v1",
            "decision_id": "abc",
            "provider": "offline_deterministic",
            "model": "none",
            "state": {"watch_id": "watch-v1"},
            "policy": {
                "selected_action": action,
                "protocol_breach_reasons": [],
            },
        }

    def test_collect_more_evidence_is_no_change_action(self):
        result = execute_research_action(
            self._shadow(),
            self._decision("collect_more_evidence"),
        )
        self.assertEqual(result["result"]["status"], "ACCUMULATE_UNCHANGED")
        self.assertFalse(result["authority_boundary"]["transmits_orders"])
        self.assertFalse(result["authority_boundary"]["changes_frozen_shadow"])

    def test_state_coverage_is_descriptive(self):
        result = execute_research_action(
            self._shadow(),
            self._decision("inspect_state_coverage"),
        )
        self.assertEqual(result["result"]["status"], "DESCRIPTIVE_INSPECTION_ONLY")
        self.assertEqual(
            result["result"]["hypotheses"][0]["coverage_gap"],
            "NO_COMPLETED_OBSERVATIONS",
        )

    def test_data_quality_checks_hashes_and_integrity_claims(self):
        result = execute_research_action(
            self._shadow(),
            self._decision("inspect_data_quality"),
        )
        self.assertEqual(result["result"]["status"], "NO_OBVIOUS_ISSUE")

    def test_protocol_breach_action_is_blocked(self):
        decision = self._decision("stop_protocol_breach")
        decision["policy"]["protocol_breach_reasons"] = ["fixture_breach"]
        result = execute_research_action(self._shadow(), decision)
        self.assertEqual(result["result"]["status"], "BLOCKED")
        self.assertEqual(
            result["result"]["protocol_breach_reasons"],
            ["fixture_breach"],
        )
        self.assertFalse(result["authority_boundary"]["transmits_orders"])

    def test_prepare_review_is_ready_only_when_shadow_is_ready(self):
        result = execute_research_action(
            self._shadow(ready=True),
            self._decision("prepare_formal_review"),
        )
        self.assertEqual(result["result"]["status"], "READY")
        self.assertTrue(result["result"]["all_strategies_ready"])

    def test_prepare_review_respects_deterministic_readiness(self):
        result = execute_research_action(
            self._shadow(ready=False),
            self._decision("prepare_formal_review"),
        )
        self.assertEqual(result["result"]["status"], "NOT_READY")


if __name__ == "__main__":
    unittest.main()
