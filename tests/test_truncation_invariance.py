"""Truncation-invariance (lookahead) checks on the repo's live signal functions.  Offline, synthetic data."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab.multi_premia_human_forward import coin_targets
from orderflow_edge_lab.trend_exits import core_strategy
from orderflow_edge_lab.truncation_check import check_truncation, random_probe_dates
from orderflow_edge_lab.vol_sizing import vol_sized_strategy
from orderflow_edge_lab.xs_premia import carry_score, daily_funding_panel, daily_open_panel, momentum_score

N_COINS, N_DAYS, N_PROBES = 20, 700, 20
CFG = json.loads(Path("config/multi_premia_blend_v1.json").read_text(encoding="utf-8"))


def synthetic(n_coins: int = N_COINS, n_days: int = N_DAYS):
    idx = pd.date_range("2024-01-01T00:00Z", periods=n_days * 3, freq="8h")
    frames, funding = {}, {}
    for k in range(n_coins):
        rng = np.random.default_rng(1000 + k)
        c = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, len(idx))))
        o = np.concatenate([[100.0], c[:-1]])
        hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.005, len(idx))))
        lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.005, len(idx))))
        v = rng.lognormal(10, 0.5, len(idx))
        frames[f"C{k:02d}"] = pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": v}, index=idx)
        funding[f"C{k:02d}"] = pd.Series(rng.normal(0.0001 * (k - n_coins / 2) / n_coins, 0.0002, len(idx)), index=idx)
    return frames, funding


FRAMES, FUNDING = synthetic()
DAYS = pd.DatetimeIndex([t for t in FRAMES["C00"].index if t.hour == 0])
PROBES = random_probe_dates(DAYS[320:-2], N_PROBES, seed=7)  # past warmup, not at the very end


class HarnessTests(unittest.TestCase):
    def test_leaky_function_is_caught_and_honest_passes(self):
        data = {"px": FRAMES["C00"]["close"]}
        leaky = lambda d: d["px"].shift(-1) - d["px"]
        honest = lambda d: d["px"].pct_change().rolling(10).mean()
        r = check_truncation(leaky, data, PROBES)
        self.assertFalse(r["pass"])
        self.assertGreater(len(r["mismatches"]), 0)
        self.assertEqual(r["n_dates"], N_PROBES)
        self.assertTrue(check_truncation(honest, data, PROBES)["pass"])

    def test_full_sample_normalisation_is_caught(self):
        data = {"px": FRAMES["C00"]["close"]}
        self.assertFalse(check_truncation(lambda d: d["px"] / d["px"].mean(), data, PROBES)["pass"])

    def test_nan_equal_and_probe_dates_deterministic(self):
        data = {"px": FRAMES["C00"]["close"]}
        self.assertTrue(check_truncation(lambda d: d["px"].rolling(50).mean(), data, DAYS[:10])["pass"])
        self.assertEqual(random_probe_dates(DAYS, 5, 1), random_probe_dates(DAYS, 5, 1))


def _strategy():
    tr = CFG["legs"]["S1_trend"]
    return vol_sized_strategy(core_strategy(tr["parameters"], exit_window=None), window=int(tr["sizing_window_bars"]),
                              target_vol=float(tr["target_annual_vol"]), cap=1.0, bars_per_year=1095)


class LiveSignalTests(unittest.TestCase):
    def test_trend_core_vol_sized_targets(self):
        strat = _strategy()
        fn = lambda d: pd.DataFrame({s: strat.generate_target(f, {}, None) for s, f in d["frames"].items()}).sort_index()
        r = check_truncation(fn, {"frames": FRAMES}, PROBES)
        self.assertTrue(r["pass"], r["mismatches"])

    def test_xs_momentum_score(self):
        lb = int(CFG["legs"]["S2_xs_momentum"]["lookback_days"])
        fn = lambda d: momentum_score(daily_open_panel(d["frames"]), lb)
        r = check_truncation(fn, {"frames": FRAMES}, PROBES)
        self.assertTrue(r["pass"], r["mismatches"])

    def test_xs_carry_score(self):
        lb = int(CFG["legs"]["S3_xs_carry"]["lookback_days"])

        def fn(d):
            opens = daily_open_panel(d["frames"])
            return carry_score(daily_funding_panel(d["funding"], opens.index), lb)

        r = check_truncation(fn, {"frames": FRAMES, "funding": FUNDING}, PROBES)
        self.assertTrue(r["pass"], r["mismatches"])

    def _coin_targets_check(self, weights, lag_days=0):
        lw = pd.DataFrame({"S1": weights[0], "S2": weights[1], "S3": weights[2]}, index=DAYS)

        def fn(d):
            out = coin_targets(CFG, d["frames"], d["funding"], d["lw"])
            return out.shift(lag_days) if lag_days else out

        dates = [t + pd.Timedelta(days=lag_days) for t in PROBES]
        return check_truncation(fn, {"frames": FRAMES, "funding": FUNDING, "lw": lw}, dates)

    def test_coin_targets_trend_leg_is_causal(self):
        r = self._coin_targets_check((1.0, 0.0, 0.0))
        self.assertTrue(r["pass"], r["mismatches"])

    def test_coin_targets_xs_legs_last_day_finding(self):
        # FINDING (documented, not a lookahead): _xs_weights iterates opens.index[:-1] and requires the
        # next-day open for tradability (multi_premia_human_forward.py:41-44), so on data ending at day d the
        # S2/S3 weights of day d are 0, while with data through d+1 00:00 they are non-zero.
        for weights in ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            r = self._coin_targets_check(weights)
            self.assertFalse(r["pass"])
            self.assertEqual(len(r["mismatches"]), N_PROBES)

    def test_coin_targets_all_legs_causal_once_next_day_bar_exists(self):
        # row d computed with data through d+1 00:00 never changes afterwards (compared via a one-day shift)
        r = self._coin_targets_check((0.5, 0.3, 0.2), lag_days=1)
        self.assertTrue(r["pass"], r["mismatches"])


if __name__ == "__main__":
    unittest.main()
