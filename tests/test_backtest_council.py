from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.backtest_council import (
    FAIL,
    PASS,
    REJECT,
    SHADOW_ELIGIBLE,
    CouncilInputs,
    _funding_crossings,
    concentration_prosecutor,
    load_thresholds,
    render_markdown,
    run_council,
    verify_council_report,
)
from orderflow_edge_lab.universal_backtest import ExecutionModel, FunctionStrategy, legacy_strategy


def random_walk(seed: int, n: int = 3000, vol: float = 0.004) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))
    open_ = np.r_[close[0], close[:-1]]
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.001,
                         "low": np.minimum(open_, close) * 0.999, "close": close}, index=idx)


def momentum_market(seed: int, n: int = 3000) -> pd.DataFrame:
    """Open-to-open returns with genuine positive autocorrelation."""
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    eps = rng.normal(0, 0.003, n)
    for i in range(1, n):
        r[i] = 0.6 * r[i - 1] + eps[i]
    open_ = 100 * np.exp(np.cumsum(r))
    close = np.r_[open_[1:], open_[-1]]
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.0005,
                         "low": np.minimum(open_, close) * 0.9995, "close": close}, index=idx)


def momentum_strategy() -> FunctionStrategy:
    # Uses only the latest completed open-to-open return, known at bar close.
    def target(frame, _params):
        last = frame["close"] / frame["open"] - 1.0
        return np.sign(last).fillna(0.0)
    return FunctionStrategy("fixture_momentum", target, warmup_bars=5)


def member(report, name):
    return next(m for m in report["members"] if m["member"] == name)


FAST = {"null_draws": 200, "bootstrap_resamples": 300, "lookahead_cut_points": 6}


class BacktestCouncilTests(unittest.TestCase):
    def test_lookahead_strategy_is_rejected_even_with_perfect_statistics(self):
        frames = {"A": random_walk(1), "B": random_walk(2)}
        leak = FunctionStrategy(
            "leak", lambda f, _p: np.sign(f["open"].shift(-2) - f["open"].shift(-1)).fillna(0.0), warmup_bars=5
        )
        report = run_council(CouncilInputs(frames, leak, {}, ExecutionModel(10.0)), FAST)
        self.assertEqual(member(report, "lookahead_auditor")["status"], FAIL)
        self.assertEqual(report["judgement"]["verdict"], REJECT)
        self.assertEqual(report["judgement"]["deciding_member"], "lookahead_auditor")

    def test_full_sample_normalization_is_flagged_as_lookahead(self):
        frames = {"A": random_walk(3)}
        def zscore_full(f, _p):
            z = (f["close"] - f["close"].mean()) / f["close"].std()
            return pd.Series(np.where(z < -0.5, 1.0, np.where(z > 0.5, -1.0, 0.0)), index=f.index)
        s = FunctionStrategy("global_z", zscore_full, warmup_bars=5)
        report = run_council(CouncilInputs(frames, s, {}, ExecutionModel(10.0)), FAST)
        self.assertEqual(member(report, "lookahead_auditor")["status"], FAIL)

    def test_causal_legacy_family_passes_lookahead(self):
        report = run_council(CouncilInputs({"A": random_walk(4)}, legacy_strategy("donchian_breakout"),
                                           {"lookback": 20}, ExecutionModel(10.0)), FAST)
        self.assertEqual(member(report, "lookahead_auditor")["status"], PASS)

    def test_noise_strategy_on_random_walk_is_rejected(self):
        frames = {f"S{i}": random_walk(10 + i) for i in range(3)}
        report = run_council(CouncilInputs(frames, legacy_strategy("donchian_breakout"), {"lookback": 20},
                                           ExecutionModel(10.0), parameter_grid={"lookback": [10, 20, 55]}), FAST)
        self.assertEqual(report["judgement"]["verdict"], REJECT)

    def test_planted_edge_is_not_rejected(self):
        frames = {f"S{i}": momentum_market(20 + i) for i in range(3)}
        report = run_council(CouncilInputs(frames, momentum_strategy(), {}, ExecutionModel(4.0), trial_count=5), FAST)
        self.assertEqual(member(report, "lookahead_auditor")["status"], PASS)
        self.assertEqual(member(report, "null_examiner")["status"], PASS)
        self.assertEqual(report["judgement"]["verdict"], SHADOW_ELIGIBLE, render_markdown(report))

    def test_single_lucky_day_is_prosecuted(self):
        trades = [{"entry": f"2024-01-{d:02d}T00:00:00+00:00", "exit": f"2024-01-{d:02d}T01:00:00+00:00",
                   "net_bps": -2.0, "gross_bps": 0.0, "side": 1, "mfe_bps": 0.0, "mae_bps": 0.0} for d in range(1, 29)]
        trades.append({"entry": "2024-01-29T00:00:00+00:00", "exit": "2024-01-29T01:00:00+00:00",
                       "net_bps": 500.0, "gross_bps": 502.0, "side": 1, "mfe_bps": 0.0, "mae_bps": 0.0})
        finding = concentration_prosecutor(trades, load_thresholds())
        self.assertEqual(finding.status, FAIL)
        self.assertEqual(finding.evidence["best_day"], "2024-01-29")

    def test_high_leverage_liquidations_are_counted(self):
        frames = {"A": random_walk(5, vol=0.01)}
        report = run_council(CouncilInputs(frames, legacy_strategy("donchian_breakout"), {"lookback": 20},
                                           ExecutionModel(10.0), leverage=100.0), FAST)
        risk = member(report, "risk_path_auditor")
        self.assertGreater(risk["evidence"]["liquidated_trades"], 0)
        self.assertAlmostEqual(risk["evidence"]["liquidation_distance_bps"], 60.0)

    def test_funding_crossings(self):
        t = pd.Timestamp
        self.assertEqual(_funding_crossings(t("2024-01-01T07:00Z"), t("2024-01-01T07:59Z"), 8), 0)
        self.assertEqual(_funding_crossings(t("2024-01-01T07:00Z"), t("2024-01-01T08:00Z"), 8), 1)
        self.assertEqual(_funding_crossings(t("2024-01-01T08:00Z"), t("2024-01-02T08:00Z"), 8), 3)

    def test_report_hash_and_claims_are_tamper_evident(self):
        report = run_council(CouncilInputs({"A": random_walk(6)}, legacy_strategy("donchian_breakout"),
                                           {"lookback": 20}, ExecutionModel(10.0)), FAST)
        self.assertTrue(verify_council_report(report))
        self.assertFalse(report["claims"]["profitable_edge_established"])
        forged = dict(report)
        forged["judgement"] = {**report["judgement"], "verdict": SHADOW_ELIGIBLE}
        self.assertFalse(verify_council_report(forged))

    def test_report_is_deterministic(self):
        inputs = CouncilInputs({"A": random_walk(7)}, legacy_strategy("donchian_breakout"),
                               {"lookback": 20}, ExecutionModel(10.0))
        self.assertEqual(run_council(inputs, FAST)["report_sha256"], run_council(inputs, FAST)["report_sha256"])

    def test_frozen_config_loads(self):
        th = load_thresholds("config/backtest_council_v1.json")
        self.assertEqual(th["cost_stress_multiplier"], 1.5)


if __name__ == "__main__":
    unittest.main()
