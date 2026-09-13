from __future__ import annotations

from hashlib import sha256
import json
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.htf_fibonacci_paired_forward import (
    _trade_stats,
    build_paired_report,
)
from orderflow_edge_lab.htf_trend_forward_shadow import HtfTrendForwardError


def _sign(value):
    unsigned = dict(value)
    unsigned.pop("spec_sha256", None)
    raw = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    value["spec_sha256"] = sha256(raw).hexdigest()
    return value


def _candidates(start: pd.Timestamp):
    spec = {
        "venue": "MEXC Futures",
        "symbols": ["A"],
        "interval": "8h",
        "family": "ema_tsmom",
        "fast_ema": 2,
        "slow_ema": 4,
        "atr_period": 2,
        "min_atr_spread": 0.0,
        "position_rule": "test",
        "signal_timing": "completed_8h_close_only",
        "execution_timing": "next_8h_bar_open",
        "portfolio_weighting": "equal_weight_across_active_symbols",
        "gross_portfolio_exposure_cap": 1.0,
        "round_trip_cost_bps": 20.0,
        "funding_accounting": "test",
        "leverage": 1.0,
    }
    protocol = {
        "indicator_warmup_start_utc": "2026-07-01T00:00:00Z",
        "position_state_at_boundary": "flat",
        "no_retuning_after_forward_start": True,
        "minimum_completed_forward_trades_for_edge_review": 20,
        "paper_shadow_only": True,
        "mark_to_market": "current_close",
        "visible_pnl_is_not_statistical_proof": True,
        "no_backfill_before_forward_start": True,
    }
    claims = {
        "candidate_specification_frozen": True,
        "verified_out_of_sample_evidence": False,
        "profitable_edge_established": False,
        "live_order_transmission_supported": False,
    }
    baseline = _sign(
        {
            "schema_version": 1,
            "candidate_id": "baseline",
            "frozen_at_utc": start.isoformat(),
            "forward_signal_start_utc": start.isoformat(),
            "selection_provenance": {},
            "specification": dict(spec),
            "forward_protocol": dict(protocol),
            "claims": dict(claims),
        }
    )
    fib = _sign(
        {
            "schema_version": 1,
            "candidate_id": "fib",
            "frozen_at_utc": start.isoformat(),
            "forward_signal_start_utc": start.isoformat(),
            "selection_provenance": {},
            "specification": dict(spec),
            "fibonacci_overlay": {
                "mode": "entry_transition_gate_only",
                "anchor_lookback_bars": 24,
                "minimum_impulse_atr": 2.0,
                "levels": [0.382, 0.5, 0.618],
                "level_tolerance": 0.025,
            },
            "forward_protocol": dict(protocol),
            "claims": dict(claims),
        }
    )
    return baseline, fib


def _frame(index: pd.DatetimeIndex):
    close = 100.0 * np.exp(np.arange(len(index)) * 0.004)
    open_ = close * 0.999
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) * 1.002,
            "low": np.minimum(open_, close) * 0.998,
            "close": close,
            "volume": 1.0,
        },
        index=index,
    )


class HtfFibonacciPairedForwardTests(unittest.TestCase):
    def test_pair_is_not_reviewable_before_forward_trade_minimum(self):
        idx = pd.date_range("2026-07-01", periods=180, freq="8h", tz="UTC")
        start = idx[130]
        baseline, fib = _candidates(start)
        frames = {"A": _frame(idx)}
        funding = {
            "A": pd.DataFrame(
                columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC")
            )
        }
        report = build_paired_report(
            frames,
            funding,
            baseline,
            fib,
            as_of_utc=idx[140] + pd.Timedelta(hours=1),
        )
        self.assertTrue(report["entry_subset_verified"])
        self.assertFalse(report["paired_reviewable"])
        self.assertFalse(report["claims"]["verified_profitable_edge"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])
        json.dumps(report, allow_nan=False)

    def test_pair_rejects_different_forward_boundary(self):
        idx = pd.date_range("2026-07-01", periods=180, freq="8h", tz="UTC")
        start = idx[130]
        baseline, fib = _candidates(start)
        fib["forward_signal_start_utc"] = (start + pd.Timedelta(hours=8)).isoformat()
        fib = _sign(fib)
        with self.assertRaises(HtfTrendForwardError):
            build_paired_report(
                {"A": _frame(idx)},
                {"A": pd.DataFrame(columns=["funding_rate"], index=pd.DatetimeIndex([], tz="UTC"))},
                baseline,
                fib,
                as_of_utc=idx[140],
            )

    def test_profit_factor_output_is_json_safe_when_no_losing_trades(self):
        stats = _trade_stats([{"net_return": 0.01}, {"net_return": 0.02}])
        self.assertIsNone(stats["profit_factor"])
        self.assertTrue(stats["profit_factor_infinite"])
        json.dumps(stats, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
