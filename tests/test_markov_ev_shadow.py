from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.markov_ev_shadow import (
    MarkovRewardFit,
    _filter_side_series,
    assess_entry,
    fit_markov_reward,
)
from orderflow_edge_lab.markov_price_diagnostics import STATE_ORDER, MarkovStateSpec


class MarkovEVShadowTests(unittest.TestCase):
    def test_post_freeze_prices_do_not_change_fitted_chain_or_rewards(self) -> None:
        rng = np.random.default_rng(7)
        index = pd.date_range("2026-01-01", periods=240, freq="h", tz="UTC")
        returns = rng.normal(0.0, 0.002, size=len(index))
        close = 100.0 * np.exp(np.cumsum(returns))
        frame = pd.DataFrame({"close": close}, index=index)
        cutoff = index[180]
        spec = MarkovStateSpec()

        fit_a = fit_markov_reward(
            frame,
            training_end_exclusive_utc=cutoff.isoformat(),
            state_spec=spec,
        )
        changed = frame.copy()
        changed.loc[changed.index >= cutoff, "close"] *= np.linspace(1.0, 4.0, int((changed.index >= cutoff).sum()))
        fit_b = fit_markov_reward(
            changed,
            training_end_exclusive_utc=cutoff.isoformat(),
            state_spec=spec,
        )

        pd.testing.assert_frame_equal(fit_a.counts, fit_b.counts)
        pd.testing.assert_frame_equal(fit_a.transition, fit_b.transition)
        np.testing.assert_allclose(fit_a.reward_bps, fit_b.reward_bps)
        np.testing.assert_allclose(fit_a.reward_se_bps, fit_b.reward_se_bps)

    def _manual_fit(self, reward_bps: float, transition_count: int = 30) -> MarkovRewardFit:
        labels = list(STATE_ORDER)
        counts = pd.DataFrame(0, index=labels, columns=labels, dtype=int)
        counts.loc["UP|NORMAL", "UP|NORMAL"] = transition_count
        transition = pd.DataFrame(np.eye(len(labels)), index=labels, columns=labels)
        rewards = np.zeros(len(labels), dtype=float)
        ses = np.zeros(len(labels), dtype=float)
        i = labels.index("UP|NORMAL")
        rewards[i] = reward_bps
        ses[i] = 1.0
        index = pd.date_range("2026-09-15T00:00:00Z", periods=6, freq="h")
        states = pd.DataFrame(
            {
                "state": ["UP|NORMAL"] * len(index),
                "log_return": [0.001] * len(index),
                "direction_z": [1.0] * len(index),
                "volatility_ratio": [1.0] * len(index),
                "close": np.arange(len(index), dtype=float) + 100.0,
            },
            index=index,
        )
        return MarkovRewardFit(
            states=states,
            training_states=states.copy(),
            counts=counts,
            transition=transition,
            reward_bps=rewards,
            reward_se_bps=ses,
            reward_observations={label: transition_count if label == "UP|NORMAL" else 0 for label in labels},
        )

    def test_only_same_side_positive_conservative_ev_passes(self) -> None:
        fit = self._manual_fit(15.0)
        timestamp = fit.states.index[-1]
        long_decision = assess_entry(
            fit,
            state_timestamp_utc=timestamp,
            side=1.0,
            horizon_bars=3,
            round_trip_cost_bps=20.0,
            minimum_state_transitions=20,
            conservative_score_z=1.0,
        )
        short_decision = assess_entry(
            fit,
            state_timestamp_utc=timestamp,
            side=-1.0,
            horizon_bars=3,
            round_trip_cost_bps=20.0,
            minimum_state_transitions=20,
            conservative_score_z=1.0,
        )
        self.assertEqual(long_decision["decision"], "PASS")
        self.assertEqual(short_decision["decision"], "VETO")
        self.assertGreater(long_decision["conservative_score_bps"], 0.0)

    def test_sparse_state_fails_closed(self) -> None:
        fit = self._manual_fit(50.0, transition_count=5)
        decision = assess_entry(
            fit,
            state_timestamp_utc=fit.states.index[-1],
            side=1.0,
            horizon_bars=1,
            round_trip_cost_bps=0.0,
            minimum_state_transitions=20,
            conservative_score_z=0.0,
        )
        self.assertEqual(decision["decision"], "VETO")
        self.assertEqual(decision["state_reliability"], "sparse")

    def test_veto_is_not_retried_until_base_state_resets(self) -> None:
        fit = self._manual_fit(-10.0)
        index = fit.states.index[:4]
        base = pd.Series([1.0, 1.0, 0.0, 1.0], index=index)
        filtered, decisions = _filter_side_series(
            base,
            fit,
            execution_start=index[0],
            signal_lag=pd.Timedelta(0),
            horizon_bars=1,
            round_trip_cost_bps=0.0,
            minimum_state_transitions=20,
            conservative_score_z=0.0,
        )
        self.assertTrue((filtered == 0.0).all())
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(item["decision"] == "VETO" for item in decisions))


if __name__ == "__main__":
    unittest.main()
