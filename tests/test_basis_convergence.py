from __future__ import annotations

from http.client import IncompleteRead
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from orderflow_edge_lab import basis_convergence
from orderflow_edge_lab.basis_convergence import BasisVariant, evaluate_basis_grid, prepare_basis_frame, simulate_basis_convergence


def _frames():
    idx = pd.date_range("2026-01-01", periods=10, freq="h", tz="UTC")
    spot = pd.DataFrame(
        {
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.0] * 10,
            "volume": [1.0] * 10,
        },
        index=idx,
    )
    perp_close = [100.0, 101.0, 101.0, 100.8, 100.4, 100.1, 100.05, 100.0, 100.0, 100.0]
    perp_open = [100.0, 100.0, 101.0, 101.0, 100.8, 100.4, 100.1, 100.05, 100.0, 100.0]
    perp = pd.DataFrame(
        {
            "open": perp_open,
            "high": [max(v, 100.0) + 0.1 for v in perp_close],
            "low": [min(v, 100.0) - 0.1 for v in perp_close],
            "close": perp_close,
            "volume": [1.0] * 10,
        },
        index=idx,
    )
    funding = pd.DataFrame(
        {"funding_rate": [0.001]},
        index=pd.DatetimeIndex([idx[4]], name="timestamp"),
    )
    return spot, perp, funding


class BasisConvergenceTests(unittest.TestCase):
    def test_basis_signal_executes_on_next_open_and_includes_held_funding(self):
        spot, perp, funding = _frames()
        basis = prepare_basis_frame(spot, perp)
        trades = simulate_basis_convergence(
            basis,
            funding,
            BasisVariant(upper_entry_bps=50.0, lower_exit_bps=20.0, round_trip_pair_cost_bps=20.0),
        )
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade["entry_time"], basis.index[2].isoformat())
        self.assertEqual(trade["exit_time"], basis.index[6].isoformat())
        self.assertEqual(trade["funding_rate_sum"], 0.001)
        self.assertGreater(trade["net_return"], 0)

    def test_grid_keeps_all_trials_and_never_claims_oos_or_profitability(self):
        spot, perp, funding = _frames()
        basis = prepare_basis_frame(spot, perp)
        report = evaluate_basis_grid(
            {"BTC_USDT": (basis, funding), "ETH_USDT": (basis, funding), "BNB_USDT": (basis, funding)},
            entry_thresholds=[50.0, 100.0],
            exit_thresholds=[0.0, 20.0],
            cost_cases=[20.0, 40.0],
            fold_days=2,
            minimum_trades=1,
            minimum_folds=1,
            minimum_positive_fold_fraction=0.0,
            minimum_positive_symbol_fraction=0.0,
        )
        self.assertEqual(report["variant_count"], 8)
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["verified_out_of_sample_evidence"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])

    def test_public_json_fetch_retries_incomplete_chunk_without_changing_payload(self):
        broken = MagicMock()
        broken.__enter__.return_value = broken
        broken.status = 200
        broken.read.side_effect = IncompleteRead(b'{"ok":')
        good = MagicMock()
        good.__enter__.return_value = good
        good.status = 200
        good.read.return_value = b'{"ok": true, "value": 7}'
        with patch.object(basis_convergence, "urlopen", side_effect=[broken, good]) as mocked, patch.object(basis_convergence.time, "sleep") as sleep:
            payload = basis_convergence._get_json("https://example.invalid/data", attempts=2)
        self.assertEqual(payload, {"ok": True, "value": 7})
        self.assertEqual(mocked.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_public_json_fetch_fails_closed_after_retry_budget(self):
        broken = MagicMock()
        broken.__enter__.return_value = broken
        broken.status = 200
        broken.read.side_effect = IncompleteRead(b"")
        with patch.object(basis_convergence, "urlopen", side_effect=[broken, broken]), patch.object(basis_convergence.time, "sleep"):
            with self.assertRaisesRegex(basis_convergence.BasisConvergenceError, "failed after 2 attempts"):
                basis_convergence._get_json("https://example.invalid/data", attempts=2)


if __name__ == "__main__":
    unittest.main()
