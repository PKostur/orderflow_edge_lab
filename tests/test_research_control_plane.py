from __future__ import annotations

import unittest

from orderflow_edge_lab.research_control_plane import build_control_plane_status


class ResearchControlPlaneTests(unittest.TestCase):
    def _fixture(self, *, completed=0, open_count=0, changes=0, ready=False):
        shadow = {
            "analysis": "universal_session_alignment_prospective_shadow",
            "watch_id": "watch",
            "status": "READY_FOR_REVIEW" if ready else "ACCUMULATING",
            "prospective_start_utc": "2026-09-24T00:00:00+00:00",
            "as_of_utc": "2026-09-24T18:00:00+00:00",
            "evidence_progress": {"all_strategies_ready": ready},
            "reports": [
                {
                    "audit_id": "DON8",
                    "ready_for_review": ready,
                    "evidence_progress": {
                        "completed_trade_count": completed,
                        "open_post_start_snapshot_count": open_count,
                        "completed_observed_symbol_count": 1 if completed else 0,
                    },
                }
            ],
        }
        decision = {
            "analysis": "jev_research_decision_layer_v1",
            "decision_id": "d1",
            "provider": "offline_deterministic",
            "provider_resolution": "auto_offline_no_api_key",
            "model": "none",
            "state": {"watch_id": "watch"},
            "policy": {
                "selected_action": "prepare_formal_review" if ready else "collect_more_evidence",
                "selection_source": "offline_bounded_choice",
            },
        }
        action = {
            "analysis": "jev_research_action_v1",
            "watch_id": "watch",
            "decision_id": "d1",
            "authority_boundary": {
                "changes_frozen_shadow": False,
                "changes_strategy_rules": False,
                "changes_positions": False,
                "transmits_orders": False,
                "authorizes_promotion": False,
                "authorizes_leverage": False,
            },
            "result": {"status": "READY" if ready else "ACCUMULATE_UNCHANGED"},
        }
        operational = {
            "analysis": "universal_shadow_operational_monitor_v1",
            "watch_id": "watch",
            "latest_execution_boundary_utc": "2026-09-24T16:00:00+00:00",
            "execution_boundaries_since_start_including_start": 3,
            "claims": {"not_prospective_evidence": True},
            "strategies": [
                {
                    "audit_id": "DON8",
                    "current_long_symbol_count": 1,
                    "current_short_symbol_count": 0,
                    "current_flat_symbol_count": 0,
                    "carried_pre_start_position_count": 1,
                    "post_start_position_change_count": changes,
                    "median_position_age_hours": 72.0,
                    "symbols_with_post_start_change": ["BTC_USDT"] if changes else [],
                }
            ],
        }
        return shadow, decision, action, operational

    def test_waiting_for_first_change(self):
        result = build_control_plane_status(*self._fixture())
        self.assertEqual(result["stage"], "WAITING_FOR_FIRST_POST_START_CHANGE")

    def test_waiting_for_completion_after_target_change(self):
        result = build_control_plane_status(*self._fixture(changes=1))
        self.assertEqual(result["stage"], "WAITING_FOR_COMPLETIONS")

    def test_accumulating_completed_evidence(self):
        result = build_control_plane_status(*self._fixture(completed=2))
        self.assertEqual(result["stage"], "ACCUMULATING_COMPLETED_EVIDENCE")

    def test_ready_for_review(self):
        result = build_control_plane_status(*self._fixture(completed=20, ready=True))
        self.assertEqual(result["stage"], "READY_FOR_REVIEW")


if __name__ == "__main__":
    unittest.main()
