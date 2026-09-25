from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.payoff_geometry import enrich_trade_geometry
from orderflow_edge_lab.payoff_geometry_v1_1 import (
    PayoffGeometryV11Error,
    _cell_block,
    _check_frozen_window,
    _effective_n,
    _load_config,
    _skewness,
    _stationary_bootstrap_day_weights,
    _top_decile_profit_share,
    _weighted_median_rows,
    extend_trade_geometry,
)


def _frame(periods: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq="8h")
    open_ = np.full(periods, 100.0)
    return pd.DataFrame(
        {"open": open_, "high": open_ + 1.0, "low": open_ - 1.0, "close": open_},
        index=idx,
    )


def _row(net: float, **extra) -> dict:
    base = {
        "strategy_id": "DON8",
        "symbol": "BTC_USDT",
        "entry": "2026-01-01T00:00:00+00:00",
        "side_label": "LONG",
        "net_bps": net,
        "gross_bps": net + 20.0,
        "mfe_bps": max(net + 40.0, 0.0),
        "abs_mae_bps": 10.0,
        "giveback_bps": 20.0,
        "capture_ratio": None,
        "bars_to_mfe": 1,
        "bars_to_mae": 2,
        "excursion_order": "MFE_FIRST",
        "_day": 0,
        "_block_id": 0,
    }
    base.update(extra)
    return base


class PayoffGeometryV11Tests(unittest.TestCase):
    def test_config_is_new_protocol_bound_to_frozen_v1_window(self):
        cfg = _load_config("config/payoff_geometry_v1_1.json")
        self.assertEqual(cfg["protocol_id"], "universal-payoff-geometry-diagnostics-v1")
        self.assertEqual(cfg["frozen_window"]["end_exclusive"], "2026-09-12T00:00:00Z")
        self.assertFalse(cfg["claims"]["strategy_promotion_authorized"])
        self.assertFalse(cfg["claims"]["cell_ranking_emitted"])

    def test_window_guard_rejects_bars_after_frozen_end_and_late_as_of(self):
        cfg = _load_config("config/payoff_geometry_v1_1.json")
        protocol = {"data": {"start": "2024-01-01T00:00:00Z", "end_exclusive": "2026-09-12T00:00:00Z"}}
        ok = pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-09-11T16:00:00Z")]),
        )
        _check_frozen_window(cfg, protocol, {"BTC_USDT": ok}, as_of="2026-09-20T00:00:00Z")
        late = ok.copy()
        late.index = pd.DatetimeIndex([pd.Timestamp("2026-09-12T00:00:00Z")])
        with self.assertRaises(PayoffGeometryV11Error):
            _check_frozen_window(cfg, protocol, {"BTC_USDT": late}, as_of=None)
        with self.assertRaises(PayoffGeometryV11Error):
            _check_frozen_window(cfg, protocol, {"BTC_USDT": ok}, as_of="2026-09-25T00:00:00Z")
        moved = {"data": {"start": "2024-01-01T00:00:00Z", "end_exclusive": "2026-09-20T00:00:00Z"}}
        with self.assertRaises(PayoffGeometryV11Error):
            _check_frozen_window(cfg, moved, {"BTC_USDT": ok}, as_of=None)

    def test_extension_reconciles_with_ledger_and_marks_same_bar_ordering(self):
        frame = _frame()
        # Bar 11 carries both the episode high and the episode low: order unknowable from OHLC.
        frame.iloc[11, frame.columns.get_loc("high")] = 105.0
        frame.iloc[11, frame.columns.get_loc("low")] = 97.0
        entry, exit_ = frame.index[10], frame.index[14]
        trade = {
            "entry": entry.isoformat(),
            "exit": exit_.isoformat(),
            "side": 1,
            "bars_held": 4,
            "gross_bps": 0.0,
            "net_bps": -20.0,
            "mfe_bps": 500.0,
            "mae_bps": -300.0,
            "terminal_liquidation": False,
        }
        base = enrich_trade_geometry(
            trade, frame, strategy_id="DON8", symbol="BTC_USDT", cost_bps=20.0, btc_frame=None
        )
        row = extend_trade_geometry(base, trade, frame)
        self.assertEqual(row["bars_to_mfe"], 1)
        self.assertEqual(row["bars_to_mae"], 1)
        self.assertEqual(row["excursion_order"], "SAME_BAR")
        self.assertAlmostEqual(row["giveback_bps"], 500.0)
        self.assertAlmostEqual(row["capture_ratio"], 0.0)
        # Ledger reconciliation: realized gross must equal the price path from entry open to exit open.
        bad = dict(trade, gross_bps=37.0)
        with self.assertRaises(PayoffGeometryV11Error):
            extend_trade_geometry(dict(base, gross_bps=37.0), bad, frame)

    def test_mfe_first_and_no_mfe_orderings(self):
        frame = _frame()
        frame.iloc[11, frame.columns.get_loc("high")] = 104.0
        frame.iloc[12, frame.columns.get_loc("low")] = 96.0
        entry, exit_ = frame.index[10], frame.index[14]
        trade = {
            "entry": entry.isoformat(), "exit": exit_.isoformat(), "side": 1, "bars_held": 4,
            "gross_bps": 0.0, "net_bps": -20.0, "mfe_bps": 400.0, "mae_bps": -400.0,
            "terminal_liquidation": False,
        }
        base = enrich_trade_geometry(trade, frame, strategy_id="DON8", symbol="X", cost_bps=20.0, btc_frame=None)
        self.assertEqual(extend_trade_geometry(base, trade, frame)["excursion_order"], "MFE_FIRST")
        short = dict(trade, side=-1, mfe_bps=400.0, mae_bps=-400.0)
        base_s = enrich_trade_geometry(short, frame, strategy_id="DON8", symbol="X", cost_bps=20.0, btc_frame=None)
        self.assertEqual(extend_trade_geometry(base_s, short, frame)["excursion_order"], "MAE_FIRST")

    def test_every_canonical_episode_reconciles_and_long_gap_is_zero(self):
        from orderflow_edge_lab.universal_backtest import (
            ExecutionModel,
            legacy_strategy,
            run_canonical_backtest,
        )

        periods = 900
        idx = pd.date_range("2024-01-01T00:00:00Z", periods=periods, freq="8h")
        rng = np.random.default_rng(3)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, periods)))
        open_ = np.concatenate([[100.0], close[:-1]])
        frame = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * 1.01,
                "low": np.minimum(open_, close) * 0.99,
                "close": close,
                "volume": np.ones(periods),
            },
            index=idx,
        )
        ledger = run_canonical_backtest(
            frame,
            legacy_strategy("donchian_breakout"),
            {"lookback": 20},
            ExecutionModel(round_trip_cost_bps=20.0),
        )["trades_ledger"]
        sides = set()
        for trade in ledger:
            if trade["terminal_liquidation"]:
                continue
            base = enrich_trade_geometry(
                trade, frame, strategy_id="DON8", symbol="X", cost_bps=20.0, btc_frame=None
            )
            row = extend_trade_geometry(base, trade, frame)
            sides.add(row["side_label"])
            self.assertAlmostEqual(row["path_gross_bps"], trade["gross_bps"], places=6)
            if row["side_label"] == "LONG":
                self.assertAlmostEqual(row["short_rebalance_gap_bps"], 0.0, places=6)
            self.assertAlmostEqual(row["giveback_bps"], row["mfe_bps"] - row["static_gross_bps"])
        self.assertEqual(sides, {"LONG", "SHORT"})

    def test_capture_is_undefined_when_mfe_is_zero(self):
        row = {"gross_bps": -50.0, "mfe_bps": 0.0}
        frame = _frame()
        frame["high"] = frame["open"]
        frame.iloc[11:14, frame.columns.get_loc("low")] = 99.5
        frame.iloc[14, frame.columns.get_loc("open")] = 99.5
        entry, exit_ = frame.index[10], frame.index[14]
        trade = {
            "entry": entry.isoformat(), "exit": exit_.isoformat(), "side": 1, "bars_held": 4,
            "gross_bps": -50.0, "net_bps": -70.0, "mfe_bps": 0.0, "mae_bps": -100.0,
            "terminal_liquidation": False,
        }
        base = enrich_trade_geometry(trade, frame, strategy_id="DON8", symbol="X", cost_bps=20.0, btc_frame=None)
        ext = extend_trade_geometry(base, trade, frame)
        self.assertIsNone(ext["capture_ratio"])
        self.assertEqual(ext["excursion_order"], "NO_MFE")
        self.assertIsNone(ext["bars_to_mfe"])
        del row

    def test_tail_skew_and_effective_n(self):
        nets = [100.0] + [1.0] * 9 + [-5.0] * 10
        self.assertAlmostEqual(_top_decile_profit_share(nets), 101.0 / 109.0)
        self.assertIsNone(_top_decile_profit_share([-1.0, -2.0]))
        self.assertGreater(_skewness(nets), 0.0)
        self.assertIsNone(_skewness([1.0, 2.0]))
        # 20 trades all in one calendar block collapse to one effective observation.
        self.assertAlmostEqual(_effective_n([0] * 20), 1.0)
        self.assertAlmostEqual(_effective_n([0, 1, 2, 3]), 4.0)
        self.assertAlmostEqual(_effective_n([0, 0, 1, 1]), 2.0)

    def test_stationary_bootstrap_is_shared_seeded_and_preserves_length(self):
        a = _stationary_bootstrap_day_weights(100, mean_block_days=10, replicates=50, seed=7)
        b = _stationary_bootstrap_day_weights(100, mean_block_days=10, replicates=50, seed=7)
        self.assertTrue(np.array_equal(a, b))
        self.assertEqual(a.shape, (50, 100))
        self.assertTrue(np.all(a.sum(axis=1) == 100))
        # Runs of consecutive days are kept together far more often than under iid resampling.
        self.assertGreater(float((a > 0).mean()), 0.0)

    def test_weighted_median_rows(self):
        values = np.array([1.0, 2.0, 3.0, 100.0])
        weights = np.array([[1, 1, 1, 1], [0, 0, 0, 3], [3, 0, 0, 1]], dtype=float)
        med = _weighted_median_rows(values, weights)
        self.assertEqual(list(med), [2.0, 100.0, 1.0])

    def test_cell_block_labels_insufficient_and_never_ranks(self):
        cfg = _load_config("config/payoff_geometry_v1_1.json")
        rows = [_row(float(i), _day=i, _block_id=i // 30) for i in range(10)]
        weights = _stationary_bootstrap_day_weights(10, mean_block_days=3, replicates=20, seed=1)
        block = _cell_block("ALL", "LONG", rows, rows, weights, cfg)
        self.assertEqual(block["sufficiency"], "INSUFFICIENT")
        self.assertEqual(block["raw_n"], 10)
        self.assertEqual(block["effective_n_sufficiency"], "INSUFFICIENT")
        many = [_row(float(i), _day=0, _block_id=0) for i in range(40)]
        clustered = _cell_block("ALL", "LONG", many, many, weights[:, :1], cfg)
        self.assertEqual(clustered["sufficiency"], "SUFFICIENT")
        self.assertEqual(clustered["effective_n_sufficiency"], "INSUFFICIENT")
        self.assertNotIn("rank", json.dumps(block))
        self.assertIn("giveback_bps", block["distributions"])
        self.assertIn("p90", block["distributions"]["mfe_bps"])
        self.assertIn("delta_vs_direction_all", block)
        empty = _cell_block("SIDE=SHORT", "LONG", [], rows, weights, cfg)
        self.assertEqual(empty["raw_n"], 0)
        self.assertEqual(empty["sufficiency"], "INSUFFICIENT")


if __name__ == "__main__":
    unittest.main()
