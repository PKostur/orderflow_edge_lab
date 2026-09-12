from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from orderflow_edge_lab.ena_forward_shadow import (
    build_forward_report,
    build_forward_target,
    simulate_forward_shadow,
    verify_candidate_spec,
)


def _candidate(start: str = "2026-01-02T00:00:00Z") -> dict:
    payload = {
        "schema_version": 1,
        "candidate_id": "test",
        "status": "frozen_for_forward_paper_shadow",
        "candidate_scope": "ENA_USDT only",
        "freeze_effective_utc": start,
        "forward_signal_start_utc": start,
        "specification": {
            "symbol": "ENA_USDT",
            "interval": "1h",
            "signal_family": "bb_mean_reversion",
            "bollinger_period": 40,
            "bollinger_std": 2.0,
            "rsi_period": 14,
            "rsi_long_threshold": 25.0,
            "rsi_short_threshold": 75.0,
            "max_hold_bars": 20,
            "entry_execution": "next_bar_open_after_completed_signal_bar",
            "long_exit": "mid",
            "short_exit": "mid",
            "atr_period": 14,
            "hard_stop_atr_multiple": 1.5,
            "fixed_profit_target": None,
            "after_hard_stop": "remain_flat_until_signal_state_resets_or_reverses",
            "same_bar_stop_target_ambiguity": "stop_first",
            "round_trip_cost_bps": 20.0,
            "pyramiding": False,
        },
        "development_evidence": {},
        "forward_protocol": {
            "indicator_warmup_start_utc": "2026-01-01T00:00:00Z",
            "use_pre_freeze_bars_for_indicator_warmup_only": True,
            "reset_position_state_flat_at_forward_signal_start": True,
            "score_only_trades_triggered_by_signal_bars_at_or_after_forward_signal_start": True,
            "closed_candles_only": True,
            "no_retuning_after_forward_start": True,
            "minimum_completed_forward_trades_for_any_edge_review": 20,
            "paper_shadow_only": True,
        },
        "claims": {
            "candidate_specification_frozen": True,
            "development_only_until_forward_evidence": True,
            "cross_symbol_portfolio_robustness_established": False,
            "verified_out_of_sample_evidence": False,
            "profitable_edge_established": False,
            "live_order_transmission_supported": False,
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    payload["spec_sha256"] = sha256(raw).hexdigest()
    return payload


def _frame(rows: int = 100) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="1h", tz="UTC")
    close = 100.0 + np.sin(np.arange(rows) / 6.0)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1000.0},
        index=index,
    )


class EnaForwardShadowTests(unittest.TestCase):
    def test_candidate_hash_detects_tampering(self):
        candidate = _candidate()
        self.assertTrue(verify_candidate_spec(candidate))
        tampered = deepcopy(candidate)
        tampered["specification"]["hard_stop_atr_multiple"] = 2.0
        self.assertFalse(verify_candidate_spec(tampered))

    def test_forward_target_resets_state_at_freeze_boundary(self):
        frame = _frame()
        candidate = _candidate("2026-01-02T00:00:00Z")

        def stateful(long_entry, short_entry, long_exit, short_exit, max_hold):
            self.assertGreaterEqual(long_entry.index.min(), pd.Timestamp("2026-01-02T00:00:00Z"))
            return pd.Series(1.0, index=long_entry.index)

        with patch(
            "orderflow_edge_lab.ena_forward_shadow._stateful_events",
            side_effect=stateful,
        ):
            target = build_forward_target(frame, candidate)
        self.assertTrue((target[target.index < pd.Timestamp("2026-01-02T00:00:00Z")] == 0).all())
        self.assertTrue((target[target.index >= pd.Timestamp("2026-01-02T00:00:00Z")] == 1).all())

    def test_open_forward_position_is_not_forced_closed_at_end_of_data(self):
        frame = _frame()
        candidate = _candidate("2026-01-02T00:00:00Z")
        target = pd.Series(0.0, index=frame.index)
        start = pd.Timestamp("2026-01-02T00:00:00Z")
        target.loc[target.index >= start] = 1.0
        with patch(
            "orderflow_edge_lab.ena_forward_shadow.build_forward_target",
            return_value=target,
        ):
            result = simulate_forward_shadow(frame, candidate)
        self.assertEqual(result["completed_trades"], [])
        self.assertIsNotNone(result["open_position"])
        self.assertGreater(pd.Timestamp(result["open_position"]["entry_time"]), start)

    def test_report_never_auto_promotes_edge_or_live(self):
        frame = _frame()
        candidate = _candidate("2026-01-02T00:00:00Z")
        target = pd.Series(0.0, index=frame.index)
        with patch(
            "orderflow_edge_lab.ena_forward_shadow.build_forward_target",
            return_value=target,
        ):
            report = build_forward_report(
                frame,
                candidate,
                as_of_utc="2026-01-05T04:00:00Z",
            )
        self.assertFalse(report["claims"]["verified_out_of_sample_evidence"])
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])
        self.assertTrue(report["claims"]["paper_shadow_only"])


if __name__ == "__main__":
    unittest.main()
