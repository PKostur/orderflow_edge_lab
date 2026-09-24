from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from orderflow_edge_lab.universal_shadow_operational_monitor import (
    build_operational_monitor,
)


class _FakeStrategy:
    warmup_bars = 100

    def __init__(self, target: pd.Series):
        self._target = target

    def generate_target(self, frame, params, context):
        return self._target.reindex(frame.index).fillna(0.0)


class UniversalShadowOperationalMonitorTests(unittest.TestCase):
    def _frame(self):
        idx = pd.date_range("2026-08-20T00:00:00Z", periods=110, freq="8h")
        return pd.DataFrame(
            {
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
            },
            index=idx,
        )

    def _config(self, symbols=("BTC_USDT",)):
        return {
            "watch_id": "fixture-watch",
            "prospective_start_utc": "2026-09-24T00:00:00Z",
            "source": {"interval": "8h", "symbols": list(symbols)},
            "variants": [
                {
                    "audit_id": "DON8",
                    "family": "donchian_breakout",
                    "parameters": {"lookback": 55},
                }
            ],
        }

    def test_carried_pre_start_position_is_not_post_start_change(self):
        frame = self._frame()
        target = pd.Series(1.0, index=frame.index)
        fake = _FakeStrategy(target)
        with patch(
            "orderflow_edge_lab.universal_shadow_operational_monitor.legacy_strategy",
            return_value=fake,
        ):
            result = build_operational_monitor(
                self._config(),
                {"BTC_USDT": frame},
                as_of_utc="2026-09-24T18:00:00Z",
            )
        row = result["strategies"][0]["per_symbol"][0]
        self.assertTrue(row["carried_pre_start_position"])
        self.assertEqual(row["post_start_position_change_count"], 0)
        self.assertEqual(row["current_side"], "LONG")
        self.assertEqual(
            result["execution_boundaries_since_start_including_start"],
            3,
        )

    def test_post_start_target_change_is_reported(self):
        frame = self._frame()
        target = pd.Series(0.0, index=frame.index)
        target.loc[target.index >= pd.Timestamp("2026-09-23T16:00:00Z")] = 1.0
        fake = _FakeStrategy(target)
        with patch(
            "orderflow_edge_lab.universal_shadow_operational_monitor.legacy_strategy",
            return_value=fake,
        ):
            result = build_operational_monitor(
                self._config(),
                {"BTC_USDT": frame},
                as_of_utc="2026-09-24T18:00:00Z",
            )
        strategy = result["strategies"][0]
        self.assertGreaterEqual(strategy["post_start_position_change_count"], 1)
        self.assertEqual(strategy["symbols_with_post_start_change"], ["BTC_USDT"])
        self.assertFalse(strategy["per_symbol"][0]["carried_pre_start_position"])


if __name__ == "__main__":
    unittest.main()
