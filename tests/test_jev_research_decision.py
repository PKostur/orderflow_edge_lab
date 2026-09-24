from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from orderflow_edge_lab.jev_research_decision import (
    apply_policy,
    build_research_state,
    decide_sync,
    JevResearchDecisionError,
    offline_judgments,
)


class JevResearchDecisionTests(unittest.TestCase):
    def _shadow(
        self,
        *,
        ready: bool = False,
        breach: bool = False,
        completed: int | None = None,
        open_count: int = 1,
    ):
        completed = (24 if ready else 4) if completed is None else int(completed)
        return {
            "analysis": "universal_session_alignment_prospective_shadow",
            "watch_id": "shadow-v1",
            "status": "READY_FOR_REVIEW" if ready else "ACCUMULATING",
            "prospective_start_utc": "2026-09-24T00:00:00+00:00",
            "as_of_utc": "2026-10-25T00:00:00+00:00",
            "calendar_days_elapsed": 31 if ready else 4,
            "evidence_progress": {
                "strategy_count": 3,
                "ready_strategy_count": 3 if ready else 0,
                "all_strategies_ready": ready,
            },
            "claims": {
                "candidate_promoted": breach,
                "session_filter_authorized": False,
                "live_trading_authorized": False,
                "leverage_authorized": False,
                "profitable_edge_established": False,
                "labels_do_not_gate_trade_generation": True,
                "formal_verdict_withheld_until_review_requirements": True,
                "pre_start_entries_excluded_from_scoring": True,
                "terminal_snapshot_liquidations_excluded_from_completed_trade_scoring": True,
            },
            "reports": [
                {
                    "audit_id": audit_id,
                    "formal_verdict": "WITHHELD",
                    "ready_for_review": ready,
                    "evidence_progress": {
                        "completed_trade_count": completed,
                        "open_post_start_snapshot_count": open_count,
                        "completed_observed_symbol_count": 7,
                        "completed_symbol_coverage_fraction": 0.7,
                    },
                    "summary": {
                        "equal_weight_symbol_sleeve_completed_trade_return": 0.03,
                        "equal_weight_symbol_sleeve_max_drawdown": -0.02,
                        "expectancy_bps": 11.0,
                        "win_rate": 0.45,
                        "correct_direction_rate": 0.52,
                    },
                    "hypothesis_sample_progress": [
                        {
                            "hypothesis_id": f"{audit_id}_H1",
                            "aligned_completed_trade_count": 3,
                            "comparison_completed_trade_count": 1,
                            "paired_observed_symbol_count": 1,
                            "both_states_observed": True,
                        }
                    ],
                }
                for audit_id in ("DON8", "EMA8", "VOL8")
            ],
        }

    def test_auto_without_api_key_resolves_explicitly_offline(self):
        with patch.dict(os.environ, {}, clear=True):
            result = decide_sync(
                self._shadow(completed=0, open_count=0),
                provider="auto",
            )
        self.assertEqual(result["provider"], "offline_deterministic")
        self.assertEqual(
            result["provider_resolution"],
            "auto_offline_no_api_key",
        )

    def test_explicit_jev_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(JevResearchDecisionError):
                decide_sync(
                    self._shadow(completed=0, open_count=0),
                    provider="jev",
                )

    def test_zero_observations_collect_more_evidence(self):
        result = decide_sync(
            self._shadow(completed=0, open_count=0),
            provider="offline",
        )
        self.assertEqual(result["policy"]["selected_action"], "collect_more_evidence")
        self.assertEqual(result["policy"]["selection_source"], "offline_bounded_choice")
        self.assertEqual(
            result["judgments"]["dominant_uncertainty"]["choice"],
            "sample_size",
        )
        self.assertEqual(result["state"]["total_completed_trade_count"], 0)
        self.assertEqual(result["state"]["total_open_post_start_snapshot_count"], 0)
        self.assertFalse(result["state"]["has_any_post_start_observation"])
        self.assertNotIn(
            "inspect_state_coverage",
            result["policy"]["allowed_actions"],
        )

    def test_open_only_observations_still_collect_more_evidence(self):
        result = decide_sync(
            self._shadow(completed=0, open_count=2),
            provider="offline",
        )
        self.assertEqual(result["policy"]["selected_action"], "collect_more_evidence")
        self.assertTrue(result["state"]["has_any_post_start_observation"])
        self.assertEqual(result["state"]["total_completed_trade_count"], 0)
        self.assertNotIn(
            "inspect_state_coverage",
            result["policy"]["allowed_actions"],
        )

    def test_accumulating_shadow_cannot_be_promoted_or_sent_live(self):
        result = decide_sync(self._shadow(), provider="offline")
        self.assertIn(
            result["policy"]["selected_action"],
            {"collect_more_evidence", "inspect_state_coverage", "inspect_data_quality"},
        )
        self.assertEqual(
            result["policy"]["selection_source"],
            "offline_bounded_choice",
        )
        self.assertFalse(
            result["policy"]["hard_vetoes"]["strategy_promotion_authorized"]
        )
        self.assertFalse(result["policy"]["hard_vetoes"]["live_trading_authorized"])
        self.assertFalse(result["policy"]["hard_vetoes"]["leverage_authorized"])

    def test_ready_shadow_can_prepare_review_but_not_promote(self):
        result = decide_sync(self._shadow(ready=True), provider="offline")
        self.assertEqual(result["policy"]["selected_action"], "prepare_formal_review")
        self.assertTrue(result["state"]["all_strategies_ready"])
        self.assertFalse(
            result["claims"]["jev_cannot_promote_strategy"] is False
        )

    def test_protocol_breach_forces_stop(self):
        shadow = self._shadow(breach=True)
        state = build_research_state(shadow)
        judgments = offline_judgments(state)
        policy = apply_policy(state, judgments)
        self.assertEqual(policy["selected_action"], "stop_protocol_breach")
        self.assertEqual(policy["selection_source"], "hard_protocol_veto")
        self.assertTrue(policy["protocol_breach_reasons"])

    def test_low_confidence_choice_falls_back_deterministically(self):
        state = build_research_state(self._shadow())
        judgments = offline_judgments(state)
        judgments["research_action"] = {
            "choice": "inspect_data_quality",
            "confidence": 0.2,
            "probabilities": {"inspect_data_quality": 0.2},
        }
        policy = apply_policy(state, judgments, min_choice_confidence=0.65)
        self.assertEqual(policy["selected_action"], "collect_more_evidence")
        self.assertEqual(policy["selection_source"], "deterministic_fallback")


if __name__ == "__main__":
    unittest.main()
