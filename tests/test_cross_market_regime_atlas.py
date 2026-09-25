from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.cross_market_regime_atlas import (
    build_instrument_state_frame,
    build_regime_atlas_report,
)


class CrossMarketRegimeAtlasTests(unittest.TestCase):
    def _config(self):
        return {
            "protocol_name": "fixture-atlas-v1.1",
            "phase": "A_COMMON_STATE_MAP_CRYPTO_REFERENCE",
            "development_data": {
                "market": "crypto_perpetuals",
                "venue": "MEXC",
                "interval": "8h",
                "symbols": ["BTC_USDT", "ETH_USDT"],
                "context_symbol": "BTC_USDT",
            },
            "state_definitions": {
                "trend_efficiency": {
                    "lookback_bars": 20,
                    "rank_history_bars": 60,
                    "minimum_rank_history": 20,
                },
                "realized_volatility": {
                    "lookback_bars": 20,
                    "rank_history_bars": 60,
                    "minimum_rank_history": 20,
                },
                "displacement": {
                    "lookback_bars": 3,
                    "rank_history_bars": 60,
                    "minimum_rank_history": 20,
                },
                "activity": {
                    "rank_history_bars": 60,
                    "minimum_rank_history": 20,
                },
                "btc_correlation": {
                    "lookback_bars": 30,
                    "minimum_observations": 20,
                },
                "direction": {"flat_tolerance_bps": 1.0},
            },
            "raw_future_outcomes": {"horizons_bars": [1, 3, 6]},
            "cell_protocol": {
                "minimum_observations_for_descriptive_cell": 30,
                "minimum_distinct_utc_dates": 10,
                "dimensions": [
                    "utc_time_block",
                    "trend_state",
                    "volatility_state",
                    "displacement_state",
                    "activity_state",
                    "btc_correlation_state",
                    "direction_state",
                    "liquidity_efficiency_state",
                ],
                "interactions": [
                    ["trend_state", "volatility_state"],
                    ["displacement_state", "volatility_state"],
                    ["btc_correlation_state", "volatility_state"],
                ],
            },
            "claims": {
                "development_only": True,
                "state_labels_are_causal": True,
                "strategy_pnl_used_for_state_definition": False,
                "same_period_not_future_oos": True,
                "candidate_promoted": False,
                "profitable_edge_established": False,
                "live_trading_authorized": False,
                "leverage_authorized": False,
            },
        }

    def _frame(self, scale: float = 1.0, *, volume: bool = True) -> pd.DataFrame:
        index = pd.date_range("2025-01-01T00:00:00Z", periods=360, freq="8h")
        t = np.arange(len(index), dtype=float)
        close = scale * (100.0 + 0.08 * t + 3.5 * np.sin(t / 8.0) + 1.2 * np.sin(t / 2.7))
        open_ = np.r_[close[0], close[:-1]]
        frame = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.003,
                "low": np.minimum(open_, close) * 0.997,
                "close": close,
            },
            index=index,
        )
        if volume:
            frame["volume"] = 1000.0 + 100.0 * np.sin(t / 11.0) + t
        return frame

    def test_state_labels_are_prefix_causal(self):
        config = self._config()
        full = self._frame()
        full_state = build_instrument_state_frame(
            full,
            config,
            instrument="BTC_USDT",
            context_frame=full,
        )
        prefix = full.iloc[:280]
        prefix_state = build_instrument_state_frame(
            prefix,
            config,
            instrument="BTC_USDT",
            context_frame=prefix,
        )
        columns = [
            "trend_state",
            "volatility_state",
            "displacement_state",
            "activity_state",
            "btc_correlation_state",
            "direction_state",
        ]
        pd.testing.assert_frame_equal(
            full_state.loc[prefix.index, columns],
            prefix_state.loc[prefix.index, columns],
        )

    def test_missing_volume_is_unknown_not_imputed(self):
        config = self._config()
        frame = self._frame(volume=False)
        state = build_instrument_state_frame(
            frame,
            config,
            instrument="BTC_USDT",
            context_frame=frame,
        )
        self.assertEqual(set(state["activity_state"]), {"UNKNOWN"})

    def test_report_is_raw_behavior_only(self):
        config = self._config()
        frames = {
            "BTC_USDT": self._frame(),
            "ETH_USDT": self._frame(1.7),
        }
        report = build_regime_atlas_report(frames, config)
        self.assertGreater(report["observation_count"], 0)
        self.assertGreater(report["cell_count"], 0)
        self.assertTrue(report["claims"]["raw_market_behavior_only"])
        self.assertFalse(report["claims"]["strategy_overlay_used"])
        self.assertFalse(report["claims"]["atlas_result_can_promote_candidate"])
        self.assertTrue(
            any(
                row["cell_family"] == "trend_state__X__volatility_state"
                for row in report["cells"]
            )
        )
        self.assertTrue(
            any(row["instrument"] == "ETH_USDT" for row in report["cells"])
        )

    def test_future_tail_is_not_fabricated(self):
        config = self._config()
        config["raw_future_outcomes"] = {"horizons_bars": [6]}
        frames = {
            "BTC_USDT": self._frame(),
            "ETH_USDT": self._frame(1.7),
        }
        report = build_regime_atlas_report(frames, config)
        per_instrument = len(self._frame()) - 6
        self.assertEqual(report["observation_count"], per_instrument * 2)
        timestamps = [
            pd.Timestamp(row["timestamp_utc"])
            for row in report["observations"]
            if row["instrument"] == "BTC_USDT"
        ]
        self.assertEqual(max(timestamps), self._frame().index[-7])


if __name__ == "__main__":
    unittest.main()
