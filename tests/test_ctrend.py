"""CTREND (strategy-search-v1 round 2, R2C1): indicators, ranks, models, portfolio construction and causality.

All tests are offline and use synthetic data.  Green tests mean the code does what the registration says, not that the
strategy has an edge.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from orderflow_edge_lab import ctrend
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2

ROOT = Path(__file__).resolve().parents[1]
SMALL = {"rolling_window_weeks": 10, "_min_bars": 100, "_min_dollar_volume": 0.0, "_min_cross_section": 10}


def frame_1col(values, name="X") -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({name: np.asarray(values, dtype=float)}, index=idx)


def indicators_of(close, high=None, low=None, volume=None, scale=1.0) -> dict[str, pd.DataFrame]:
    c = frame_1col(close)
    h = c if high is None else frame_1col(high)
    lo = c if low is None else frame_1col(low)
    v = frame_1col([1.0] * len(close) if volume is None else volume)
    return dict(ctrend.indicator_frames(c, h, lo, v, scale))


def planted_panel(n_coins=60, days=900, seed=3, phi=0.97, amp=0.004) -> dict[str, pd.DataFrame]:
    """Coins whose returns carry a slowly varying latent factor, so trailing prices forecast the next week."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=days, freq="D", tz="UTC")
    f = np.zeros((days, n_coins))
    e = rng.normal(0.0, 1.0, (days, n_coins))
    for t in range(1, days):
        f[t] = phi * f[t - 1] + math.sqrt(1 - phi ** 2) * e[t]
    r = rng.normal(0.0, 0.04, (days, n_coins)) + amp * f
    cols = [f"C{i:03d}USDT" for i in range(n_coins)]
    close = pd.DataFrame(100.0 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=cols)
    high = close * (1 + np.abs(rng.normal(0, 0.01, close.shape)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, close.shape)))
    dv = pd.DataFrame(np.exp(rng.normal(15, 1, close.shape)), index=idx, columns=cols)
    return {"close": close, "high": high, "low": low, "dollar_volume": dv}


class IndicatorTests(unittest.TestCase):
    def test_there_are_28_unique_indicators(self):
        self.assertEqual(ctrend.N_INDICATORS, 28)
        self.assertEqual(len(set(ctrend.INDICATOR_NAMES)), 28)
        close = np.linspace(100, 130, 260) + np.sin(np.arange(260))
        names = [n for n, _ in ctrend.indicator_frames(frame_1col(close), frame_1col(close + 1), frame_1col(close - 1),
                                                       frame_1col(np.arange(1, 261.0)))]
        self.assertEqual(tuple(names), ctrend.INDICATOR_NAMES)

    def test_ema_uses_alpha_one_over_one_plus_length(self):
        x = frame_1col([1.0, 2.0, 3.0])
        np.testing.assert_allclose(ctrend.ema(x, 1)["X"].to_numpy(), [1.0, 1.5, 2.25])  # alpha 1/2, first = first obs
        np.testing.assert_allclose(ctrend.ema(x, 3)["X"].to_numpy(), [1.0, 1.25, 1.6875])  # alpha 1/4

    def test_scaled_window_rounds_half_up_with_minimum_two(self):
        self.assertEqual(ctrend.scaled_window(14, 1.0), 14)
        self.assertEqual([ctrend.scaled_window(n, 0.8) for n in (3, 5, 12, 14, 26, 200)], [2, 4, 10, 11, 21, 160])
        self.assertEqual([ctrend.scaled_window(n, 1.2) for n in (3, 5, 12, 14, 26, 200)], [4, 6, 14, 17, 31, 240])
        self.assertEqual(ctrend.scaled_window(1, 0.5), 2)

    def test_rsi_simple_average_of_gains_and_losses(self):
        close = [100.0]
        for _ in range(7):  # 14 changes: +2, -1 repeated: mean gain 1.0, mean loss 0.5
            close += [close[-1] + 2.0, close[-1] + 1.0]
        ind = indicators_of(close)
        self.assertTrue(np.isnan(ind["rsi"]["X"].iloc[13]))  # only 13 changes so far
        self.assertAlmostEqual(ind["rsi"]["X"].iloc[14], 100 - 100 / (1 + 1.0 / 0.5), places=9)
        rising = indicators_of(np.arange(1.0, 40.0))
        self.assertAlmostEqual(rising["rsi"]["X"].iloc[-1], 100.0)  # no losses: ratio infinite -> 100

    def test_stochastic_family(self):
        close = np.arange(1.0, 31.0)
        ind = indicators_of(close)
        self.assertAlmostEqual(ind["stochK"]["X"].iloc[-1], 1.0)  # at the 14-day high, high=low=close
        self.assertAlmostEqual(ind["stochD"]["X"].iloc[-1], 1.0)
        # stochK of a hand series: close 5 in a 14-day range [1, 9] -> (5-1)/(9-1)
        high = np.full(14, 9.0)
        low = np.full(14, 1.0)
        c = np.full(14, 3.0)
        c[-1] = 5.0
        ind = indicators_of(c, high=high, low=low)
        self.assertAlmostEqual(ind["stochK"]["X"].iloc[-1], 0.5)
        # stochRSI is (rsi - min rsi)/(max rsi - min rsi) over 14 rsi values: reference loop
        rng = np.random.default_rng(1)
        px = 100 + np.cumsum(rng.normal(0, 1, 60))
        got = indicators_of(px)["stochRSI"]["X"].iloc[-1]
        d = np.diff(px)
        rsi = []
        for t in range(13, len(d)):
            g = np.maximum(d[t - 13:t + 1], 0).mean()
            l_ = np.maximum(-d[t - 13:t + 1], 0).mean()
            rsi.append(100 - 100 / (1 + g / l_))
        last = rsi[-14:]
        self.assertAlmostEqual(got, (last[-1] - min(last)) / (max(last) - min(last)), places=9)

    def test_cci_uses_mean_absolute_deviation_and_constant_0_015(self):
        ind = indicators_of(np.arange(1.0, 21.0))  # tp = 1..20, sma 10.5, mean abs deviation 5
        self.assertAlmostEqual(ind["cci"]["X"].iloc[-1], (20 - 10.5) / (0.015 * 5.0), places=9)

    def test_sma_ratios_and_volume_ratios(self):
        close = np.arange(1.0, 61.0)
        ind = indicators_of(close, volume=np.arange(1.0, 61.0))
        self.assertAlmostEqual(ind["sma_3d"]["X"].iloc[-1], 59.0 / 60.0)
        self.assertAlmostEqual(ind["sma_50d"]["X"].iloc[-1], np.mean(close[-50:]) / 60.0)
        self.assertAlmostEqual(ind["volsma_3d"]["X"].iloc[4], 4.0 / 5.0)  # (3+4+5)/3 / 5
        self.assertTrue(np.isnan(ind["sma_100d"]["X"].iloc[-1]))  # not enough history
        self.assertTrue(np.isnan(ind["volsma_200d"]["X"].iloc[-1]))

    def test_macd_family_and_signal_line(self):
        flat = indicators_of(np.full(50, 7.0), volume=np.full(50, 3.0))
        for name in ("macd", "macd_diff_signal", "volmacd", "volmacd_diff_signal"):
            self.assertAlmostEqual(flat[name]["X"].iloc[-1], 0.0, places=12)
        px = 50 + np.cumsum(np.random.default_rng(2).normal(0, 1, 80))
        got = indicators_of(px)
        a12, a26, a9 = 1 / 13, 1 / 27, 1 / 10
        e12 = e26 = px[0]
        macd = []
        for p in px:
            e12 = a12 * p + (1 - a12) * e12
            e26 = a26 * p + (1 - a26) * e26
            macd.append((e12 - e26) / e12)
        sig = macd[0]
        for m in macd:
            sig = a9 * m + (1 - a9) * sig
        self.assertAlmostEqual(got["macd"]["X"].iloc[-1], macd[-1], places=12)
        self.assertAlmostEqual(got["macd_diff_signal"]["X"].iloc[-1], macd[-1] - sig, places=12)

    def test_chaikin_is_21_day_money_flow_ratio(self):
        n = 25
        high, low = np.full(n, 12.0), np.full(n, 8.0)
        v = np.arange(1.0, n + 1)
        full = indicators_of(high, high=high, low=low, volume=v)  # close at the high: money flow multiplier +1
        self.assertAlmostEqual(full["chaikin"]["X"].iloc[-1], 1.0)
        mid = indicators_of(np.full(n, 10.0), high=high, low=low, volume=v)  # close mid-range: multiplier 0
        self.assertAlmostEqual(mid["chaikin"]["X"].iloc[-1], 0.0)
        self.assertTrue(np.isnan(mid["chaikin"]["X"].iloc[19]))  # fewer than 21 bars
        flat = indicators_of(np.full(n, 10.0), high=np.full(n, 10.0), low=np.full(n, 10.0), volume=v)
        self.assertAlmostEqual(flat["chaikin"]["X"].iloc[-1], 0.0)  # H = L contributes 0, not NaN

    def test_bollinger_uses_population_sd(self):
        ind = indicators_of(np.arange(1.0, 21.0))
        sd = math.sqrt((20 ** 2 - 1) / 12.0)  # population sd of 1..20
        self.assertAlmostEqual(ind["boll_mid"]["X"].iloc[-1], 10.5 / 20.0)
        self.assertAlmostEqual(ind["boll_low"]["X"].iloc[-1], (10.5 - 2 * sd) / 20.0)
        self.assertAlmostEqual(ind["boll_high"]["X"].iloc[-1], (10.5 + 2 * sd) / 20.0)
        self.assertAlmostEqual(ind["boll_width"]["X"].iloc[-1], 4 * sd / 10.5)

    def test_indicator_window_scale_changes_every_window(self):
        px = 100 + np.cumsum(np.random.default_rng(5).normal(0, 1, 60))
        base, shrunk = indicators_of(px, scale=1.0), indicators_of(px, scale=0.8)
        # sma_5d at scale 0.8 is a 4-day average
        self.assertAlmostEqual(shrunk["sma_5d"]["X"].iloc[-1], np.mean(px[-4:]) / px[-1], places=12)
        self.assertAlmostEqual(base["sma_5d"]["X"].iloc[-1], np.mean(px[-5:]) / px[-1], places=12)


class RankAndModelTests(unittest.TestCase):
    def test_rank_mapping_to_half_interval(self):
        vals = np.array([[10.0, 30.0, 20.0, np.nan, 5.0]])
        elig = np.array([[True, True, True, True, False]])
        got = ctrend.rank_to_unit(vals, elig)[0]
        np.testing.assert_allclose(got[:4], [-0.5, 0.5, 0.0, 0.0])  # NaN indicator of an eligible coin ranks 0
        self.assertTrue(np.isnan(got[4]))  # ineligible
        tie = ctrend.rank_to_unit(np.array([[1.0, 1.0, 2.0]]), np.array([[True, True, True]]))[0]
        np.testing.assert_allclose(tie, [-0.25, -0.25, 0.5])  # average rank 1.5, 1.5, 3
        one = ctrend.rank_to_unit(np.array([[4.0, np.nan]]), np.array([[True, False]]))[0]
        self.assertEqual(one[0], 0.0)

    def test_wls_matches_sqrt_weight_least_squares(self):
        rng = np.random.default_rng(0)
        z = rng.uniform(-0.5, 0.5, (3, 40))
        y = 0.3 * z[1] + rng.normal(0, 0.1, 40) + 0.02
        w = rng.uniform(1.0, 10.0, 40)
        a, b = ctrend.wls_univariate(z, y, w)
        for m in range(3):
            design = np.column_stack([np.ones(40), z[m]]) * np.sqrt(w)[:, None]
            coef = np.linalg.lstsq(design, y * np.sqrt(w), rcond=None)[0]
            self.assertAlmostEqual(a[m], coef[0], places=10)
            self.assertAlmostEqual(b[m], coef[1], places=10)
        # a degenerate indicator (no cross-sectional variation) gets slope 0 and the weighted mean as intercept
        a0, b0 = ctrend.wls_univariate(np.zeros((1, 40)), y, w)
        self.assertEqual(b0[0], 0.0)
        self.assertAlmostEqual(a0[0], float((w * y).sum() / w.sum()), places=12)

    def test_aicc_lambda_selection_finds_known_sparse_model(self):
        rng = np.random.default_rng(11)
        n, p = 400, 28
        q, _ = np.linalg.qr(rng.normal(size=(n, p + 1)))
        x = q[:, :p] * math.sqrt(n)  # orthogonal, unit variance columns (zero mean after centring below)
        x -= x.mean(axis=0)
        noise = rng.normal(size=n)
        noise -= x @ np.linalg.lstsq(x, noise, rcond=None)[0]  # orthogonal to every column
        noise -= noise.mean()
        y = 2.0 * x[:, 0] + 1.0 * x[:, 3] + 0.3 * noise
        fit = ctrend.enet_aicc_path(x, y, 0.5)
        support = set(np.flatnonzero(fit["coef"]))
        self.assertEqual(support, {0, 3})
        self.assertAlmostEqual(fit["coef"][0], 2.0, delta=0.15)
        self.assertAlmostEqual(fit["coef"][3], 1.0, delta=0.15)
        self.assertEqual(len(fit["alphas"]), 100)
        self.assertAlmostEqual(fit["alphas"][-1] / fit["alphas"][0], 1e-3, places=6)  # sklearn default path, eps 1e-3
        # the chosen lambda minimises the AICc computed independently from the path
        xc, yc = x - x.mean(axis=0), y - y.mean()
        values = []
        for col in range(fit["coefs"].shape[1]):
            beta = fit["coefs"][:, col]
            rss = float(((yc - xc @ beta) ** 2).sum())
            k = int((beta != 0).sum()) + 1
            values.append(n * math.log(rss / n) + 2 * k + 2 * k * (k + 1) / (n - k - 1))
        np.testing.assert_allclose(fit["aicc"], values, rtol=1e-9)
        self.assertEqual(fit["best"], int(np.argmin(values)))

    def test_aicc_degenerate_target_selects_nothing(self):
        rng = np.random.default_rng(4)
        degenerate = ctrend.enet_aicc_path(rng.normal(size=(50, 5)), np.full(50, 0.1), 0.5)
        self.assertEqual(int((degenerate["coef"] != 0).sum()), 0)

    def test_quintile_value_weighted_long_short(self):
        signal = np.array([5.0, 1.0, 9.0, 3.0, 7.0, 2.0, 8.0, 4.0, 6.0, 0.0])
        size = np.arange(1.0, 11.0)
        w = ctrend.quintile_weights(signal, size, 5, min_names=5)
        long_idx, short_idx = [2, 6], [9, 1]  # top two signals (9, 8) and bottom two (0, 1)
        self.assertTrue(set(np.flatnonzero(w > 0)) == set(long_idx))
        self.assertTrue(set(np.flatnonzero(w < 0)) == set(short_idx))
        self.assertAlmostEqual(w[w > 0].sum(), 0.5)
        self.assertAlmostEqual(w[w < 0].sum(), -0.5)
        self.assertAlmostEqual(w[2] / w[6], size[2] / size[6])  # value-weighted by the size proxy
        self.assertAlmostEqual(w[9] / w[1], size[9] / size[1])
        self.assertAlmostEqual(np.abs(w).sum(), 1.0)

    def test_quantile_parameter_changes_leg_size(self):
        rng = np.random.default_rng(8)
        signal, size = rng.normal(size=60), rng.uniform(1, 5, 60)
        for q in (4, 5, 6):
            w = ctrend.quintile_weights(signal, size, q, min_names=10)
            self.assertEqual(int((w > 0).sum()), 60 // q)
            self.assertEqual(int((w < 0).sum()), 60 // q)
        thin = ctrend.quintile_weights(signal[:8], size[:8], 5, min_names=10)
        self.assertEqual(float(np.abs(thin).sum()), 0.0)  # too few names: no book

    def test_nan_signals_and_sizes_are_skipped(self):
        signal = np.array([1.0, np.nan, 3.0, 2.0, 5.0, 4.0, 0.5, 6.0, 7.0, 8.0])
        size = np.array([1.0, 1.0, 1.0, np.nan, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        w = ctrend.quintile_weights(signal, size, 4, min_names=4)
        self.assertEqual(w[1], 0.0)
        self.assertEqual(w[3], 0.0)
        self.assertAlmostEqual(np.abs(w).sum(), 1.0)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = planted_panel()
        cls.params = {**ctrend.DEFAULT_PARAMS, **SMALL}
        cls.engine = ctrend.CTrendEngine(cls.data, min_bars=100, min_dollar_volume=0.0, min_cross_section=10)

    def test_eligibility_needs_bars_and_dollar_volume(self):
        idx = pd.date_range("2020-01-01", periods=300, freq="D", tz="UTC")
        base = pd.DataFrame({"A": np.linspace(10, 20, 300), "B": np.linspace(10, 20, 300), "C": np.linspace(10, 20, 300)},
                            index=idx)
        base.loc[idx[:150], "B"] = np.nan  # B has only 150 bars
        dv = pd.DataFrame(2e6, index=idx, columns=base.columns)
        dv["C"] = 5e5  # C never reaches 1,000,000 of mean dollar volume
        eng = ctrend.CTrendEngine({"close": base, "high": base, "low": base, "dollar_volume": dv})
        self.assertEqual(eng.columns, ["A"])  # B and C are never eligible in this sample
        self.assertTrue(eng.eligible[-1, 0])
        first_eligible_week = int(np.argmax(eng.eligible[:, 0]))
        self.assertGreaterEqual(int((eng.weeks[first_eligible_week] - idx[0]).days) + 1, 200)  # >= 200 daily bars

    def test_weekly_forward_return_is_sunday_to_sunday(self):
        eng = self.engine
        close = self.data["close"]
        k = 20
        sunday, nxt = eng.weeks[k], eng.weeks[k + 1]
        self.assertEqual(sunday.dayofweek, 6)
        self.assertEqual((nxt - sunday).days, 7)
        col = eng.columns[0]
        expect = close.loc[nxt, col] / close.loc[sunday, col] - 1.0
        self.assertAlmostEqual(eng.ret_fwd[k, 0], expect, places=12)
        self.assertTrue(np.isnan(eng.ret_fwd[-1]).all())

    def test_indicators_use_only_data_up_to_the_sunday_close(self):
        eng = self.engine
        k = 40
        sunday = eng.weeks[k]
        changed = {key: frame.copy() for key, frame in self.data.items()}
        for key in ("close", "high", "low", "dollar_volume"):
            changed[key].loc[changed[key].index > sunday] *= 3.7
        eng2 = ctrend.CTrendEngine(changed, min_bars=100, min_dollar_volume=0.0, min_cross_section=10)
        z1, z2 = eng.ranks(1.0), eng2.ranks(1.0)
        np.testing.assert_array_equal(z1[:, :k + 1, :], z2[:, :k + 1, :])

    def test_first_signal_needs_full_windows_and_ranks_are_bounded(self):
        sig = self.engine.signals(self.params)
        valid = np.flatnonzero(sig["valid"])
        self.assertGreater(len(valid), 10)
        # single trailing window: `window` weekly regressions give the averaged coefficients, the in-window fit follows
        first_regression = int(np.flatnonzero(np.isfinite(self.engine.regressions(1.0)[0]).all(axis=1))[0])
        self.assertEqual(int(valid[0]), first_regression + self.params["rolling_window_weeks"] - 1)
        z = self.engine.ranks(1.0)
        finite = z[np.isfinite(z)]
        self.assertGreaterEqual(finite.min(), -0.5)
        self.assertLessEqual(finite.max(), 0.5)

    def test_signal_uses_one_trailing_window_with_window_averaged_coefficients(self):
        eng, params = self.engine, self.params
        window = params["rolling_window_weeks"]
        sig = eng.signals(params)
        k = int(np.flatnonzero(sig["valid"])[3])
        a, b = eng.regressions(1.0)
        abar, bbar = a[k - window + 1:k + 1].mean(axis=0), b[k - window + 1:k + 1].mean(axis=0)  # weeks k-M+1..k
        z = eng.ranks(1.0)
        xs, ys = [], []
        for j in range(k - window, k):  # ranks at S_j with the return of week j+1: all realised by S_k
            y = eng.ret_fwd[j]
            mask = eng.eligible[j] & np.isfinite(y)
            xs.append((abar[:, None] + bbar[:, None] * z[:, j, :])[:, mask].T)
            ys.append(y[mask])
        fit = ctrend.enet_aicc_path(np.vstack(xs), np.concatenate(ys), params["l1_ratio"])
        keep = fit["coef"] > 0
        self.assertEqual(sig["n_kept"][k], int(keep.sum()))
        if keep.any():
            now = (abar[:, None] + bbar[:, None] * z[:, k, :])[keep].mean(axis=0)
            np.testing.assert_allclose(sig["signal"][k][eng.eligible[k]], now[eng.eligible[k]], rtol=1e-12)

    def test_elastic_net_training_pairs_are_weeks_k_minus_m_to_k_minus_1(self):
        window = self.params["rolling_window_weeks"]
        sig = self.engine.signals(self.params)
        self.assertGreater(len(sig["training_weeks"]), 5)
        for k, used in sig["training_weeks"].items():
            self.assertEqual(used, list(range(k - window, k)))  # ranks at S_j with the return of week j+1 <= k
            self.assertLessEqual(max(used) + 1, k)  # the latest training return is that of week k, realised at S_k
        k = int(np.flatnonzero(sig["valid"])[4])
        only = self.engine.signals(self.params, only_week=k)
        self.assertEqual(only["training_weeks"][k], list(range(k - window, k)))

    def test_weights_held_monday_to_sunday_and_book_is_balanced(self):
        w = self.engine.daily_weights(self.params)
        first = w.dropna(how="all").index[0]
        self.assertEqual(first.dayofweek, 6)  # decided at a Sunday close
        self.assertTrue(w.loc[:first - pd.Timedelta(1, "D")].isna().all().all())  # NaN before the first full signal
        for sunday in self.engine.weeks[self.engine.weeks > first][:8]:
            block = w.loc[sunday:sunday + pd.Timedelta(6, "D")]
            self.assertEqual(len(block), 7)
            self.assertTrue((block.nunique(dropna=False) == 1).all())  # constant Sunday..Saturday rows
        gross = w.abs().sum(axis=1).dropna()
        net = w.sum(axis=1).dropna()
        trading = gross[gross > 0]
        np.testing.assert_allclose(trading.to_numpy(), 1.0, atol=1e-12)  # 0.5 gross per leg
        np.testing.assert_allclose(net[gross > 0].to_numpy(), 0.0, atol=1e-12)

    def test_book_decided_at_sunday_earns_monday_to_sunday(self):
        w = self.engine.daily_weights(self.params)
        returns = ss.asset_returns(self.data["close"])
        detail = ss.backtest_detail(w, returns, 0.0)
        sunday = w.dropna(how="all").index[0]
        self.assertEqual(detail.index[0], sunday + pd.Timedelta(1, "D"))  # first return earned: the following Monday
        week = w.loc[sunday].fillna(0.0)
        days = returns.loc[sunday + pd.Timedelta(1, "D"):sunday + pd.Timedelta(7, "D")].fillna(0.0)
        np.testing.assert_allclose(detail.loc[days.index, "gross"].to_numpy(), (days * week).sum(axis=1).to_numpy())

    def test_signal_is_predictive_on_planted_data_and_cached_across_quantiles(self):
        sig = self.engine.signals(self.params)
        self.assertGreater(float(sig["n_kept"][sig["valid"]].mean()), 1.0)
        self.assertIs(self.engine.signals({**self.params, "quantiles": 4}), sig)  # quantiles reuse the fit
        w5, _ = self.engine.weekly_weights(self.params)
        w4, _ = self.engine.weekly_weights({**self.params, "quantiles": 4})
        k = int(np.flatnonzero(sig["valid"])[5])
        self.assertGreater(int((w4[k] > 0).sum()), int((w5[k] > 0).sum()) - 1)
        self.assertFalse(np.array_equal(w4[k], w5[k]))
        # next-week return of the long leg exceeds the short leg on average (planted latent factor)
        spreads = []
        for k in np.flatnonzero(sig["valid"])[:-1]:
            r = np.nan_to_num(self.engine.ret_fwd[k])
            spreads.append(float(w5[k] @ r) * 2) if np.abs(w5[k]).sum() > 0 else None
        self.assertGreater(float(np.mean(spreads)), 0.0)

    def test_perturbation_parameters_are_all_arguments(self):
        cfg = json.loads((ROOT / "config" / "strategy_search_v1_round2.json").read_text(encoding="utf-8"))
        spec = next(c for c in cfg["candidates"] if c["id"] == "R2C1_CTREND")
        self.assertEqual(set(spec["perturb"]), set(ctrend.DEFAULT_PARAMS))
        self.assertEqual(ctrend.DEFAULT_PARAMS, {"rolling_window_weeks": 52, "quantiles": 5, "l1_ratio": 0.5,
                                                 "indicator_window_scale": 1.0})
        specs = r2.candidate_specs(cfg)
        variants = ss.perturbation_param_sets(specs[0])
        self.assertEqual(len(variants), 8)
        self.assertIn({**ctrend.DEFAULT_PARAMS, "indicator_window_scale": 0.8}, variants)
        self.assertIn({**ctrend.DEFAULT_PARAMS, "l1_ratio": 0.6}, variants)
        window_variant = {**self.params, "rolling_window_weeks": 8}
        a = self.engine.signals(window_variant)
        b = self.engine.signals({**self.params, "l1_ratio": 0.6})
        self.assertFalse(np.array_equal(np.flatnonzero(a["valid"]), np.flatnonzero(self.engine.signals(self.params)["valid"])))
        self.assertEqual(b["signal"].shape, a["signal"].shape)


class LeakTests(unittest.TestCase):
    """The model at week w uses only what is available by the Sunday close of week w."""

    @classmethod
    def setUpClass(cls):
        cls.data = planted_panel(n_coins=40, days=700, seed=9)
        cls.params = {**ctrend.DEFAULT_PARAMS, **SMALL, "rolling_window_weeks": 8, "_min_cross_section": 10}
        cls.full = ctrend.ctrend_weights(cls.data, cls.params)

    def sundays_with_signal(self):
        idx = self.full.dropna(how="all").index
        return [d for d in idx if d.dayofweek == 6]

    def test_weights_unchanged_when_data_after_sunday_is_removed(self):
        sundays = self.sundays_with_signal()
        self.assertGreater(len(sundays), 10)
        for sunday in (sundays[0], sundays[len(sundays) // 2], sundays[-3]):
            truncated = ss.truncate_data(self.data, sunday)
            row = ctrend.ctrend_weights(truncated, self.params).loc[sunday]
            np.testing.assert_array_equal(row.to_numpy(), self.full.loc[sunday].to_numpy())
            last_only = ctrend.ctrend_weights_last_week(truncated, self.params).loc[sunday]
            np.testing.assert_array_equal(last_only.to_numpy(), self.full.loc[sunday].to_numpy())

    def test_weights_unchanged_when_future_data_is_scrambled(self):
        sunday = self.sundays_with_signal()[len(self.sundays_with_signal()) // 2]
        rng = np.random.default_rng(0)
        scrambled = {k: v.copy() for k, v in self.data.items()}
        for key, frame in scrambled.items():
            future = frame.index > sunday
            frame.loc[future] = frame.loc[future].to_numpy() * rng.uniform(0.2, 5.0, frame.loc[future].shape)
        other = ctrend.ctrend_weights(scrambled, self.params)
        np.testing.assert_array_equal(other.loc[:sunday].to_numpy(), self.full.loc[:sunday].to_numpy())

    def test_g1_truncation_gate_passes_on_the_pipeline(self):
        res = ss.g1_truncation(ctrend.ctrend_weights_last_week, self.data, self.params, self.full, n_dates=6)
        self.assertTrue(res["pass"], res)
        self.assertTrue(res["decision_date_diagnostic"]["pass"], res)

    def test_a_deliberate_leak_is_caught_by_the_same_test(self):
        def leaky(data, params):
            w = ctrend.ctrend_weights(data, params)
            future_mean = data["close"].iloc[-1].mean()  # depends on the last row of the (truncated) data
            return w * (1.0 + 1e-6 * future_mean)

        full = leaky(self.data, self.params)
        busy = [d for d in self.sundays_with_signal() if full.loc[d].abs().sum() > 0][-3:]
        self.assertEqual(len(busy), 3)
        res = ss.truncation_test(leaky, self.data, self.params, busy, full)
        self.assertFalse(res["pass"])


class PortfolioAccountingTests(unittest.TestCase):
    def test_paper_cost_scenarios_charge_each_leg(self):
        idx = pd.date_range("2021-01-03", periods=4, freq="D", tz="UTC")
        w = pd.DataFrame({"A": [0.5, 0.5, 0.5, 0.0], "B": [-0.5, -0.5, -0.5, 0.0]}, index=idx)
        r = pd.DataFrame(0.0, index=idx, columns=["A", "B"])
        out = ctrend.paper_cost_scenarios(w, r, scenarios_bps=((30.0, 40.0),))
        net = out["series"]["30/40"]
        # first held day pays the entry on both legs: 0.5 * 30bp + 0.5 * 40bp
        self.assertAlmostEqual(float(net.iloc[0]), -(0.5 * 30 + 0.5 * 40) / 1e4)
        self.assertAlmostEqual(float(net.iloc[1]), 0.0)

    def test_null_returns_only_offer_coins_eligible_that_week(self):
        idx = pd.date_range("2021-01-03", periods=4, freq="D", tz="UTC")
        returns = pd.DataFrame({"A": [0.01, 0.02, 0.03, 0.04], "B": [0.01, 0.02, 0.03, 0.04]}, index=idx)
        eligible = pd.DataFrame({"A": [True, True, False, False], "B": [True, False, False, False]}, index=idx)
        masked = r2.null_returns_eligible_only(returns, eligible)
        # the book decided at close t earns the return stamped t+1, so eligibility is shifted by one row
        self.assertTrue(np.isnan(masked.loc[idx[0]]).all())
        self.assertEqual(masked.loc[idx[1], "A"], 0.02)
        self.assertEqual(masked.loc[idx[1], "B"], 0.02)
        self.assertTrue(np.isnan(masked.loc[idx[2], "B"]))
        self.assertEqual(masked.loc[idx[2], "A"], 0.03)
        self.assertTrue(np.isnan(masked.loc[idx[3], "A"]))

    def test_registered_costs_and_annualisation(self):
        self.assertEqual(r2.CRYPTO_PERIODS_PER_YEAR, 365)
        self.assertEqual(r2.ETF_PERIODS_PER_YEAR, 252)
        self.assertEqual(r2.CRYPTO_COST_BPS_ROUND_TRIP, 20.0)
        self.assertEqual(r2.ETF_COST_BPS_ROUND_TRIP, 10.0)


class BuyAndHoldAccountingTests(unittest.TestCase):
    """CTREND accounting as published: formed at the Sunday close, buy-and-hold for the week, turnover once a week."""

    A = [100, 110, 110, 110, 110, 110, 110, 121]
    B = [100, 100, 90, 90, 90, 90, 90, 90]

    @staticmethod
    def book(prices_a, prices_b, w_a=0.5, w_b=-0.5, weeks=1):
        idx = pd.date_range("2021-01-03", periods=7 * weeks + 1, freq="D", tz="UTC")  # starts on a Sunday
        close = pd.DataFrame({"A": prices_a, "B": prices_b}, index=idx)
        weights = pd.DataFrame(np.nan, index=idx, columns=["A", "B"])
        for k in range(weeks):
            weights.iloc[7 * k:7 * k + 7] = [w_a, w_b]
        return weights, close

    def test_two_coin_week_differs_from_constant_weights_and_matches_hand_values(self):
        weights, close = self.book(self.A, self.B)
        detail = r2.buy_and_hold_detail(weights, close, 20.0)
        expected = [0.05, 1.10 / 1.05 - 1.0, 0.0, 0.0, 0.0, 0.0, 1.155 / 1.10 - 1.0]
        np.testing.assert_allclose(detail["gross"].to_numpy(), expected, atol=1e-12)
        self.assertEqual(list(detail.index), list(close.index[1:]))
        constant = ss.backtest_detail(weights, ss.asset_returns(close), 0.0)["gross"].to_numpy()
        self.assertGreater(abs(constant[1] - detail["gross"].iloc[1]), 1e-3)  # drift matters: 0.05 vs 0.0476
        self.assertAlmostEqual(float((1 + detail["gross"]).prod() - 1), 0.5 * 0.21 + 0.5 * 0.10)  # compounded week
        # costs: 1.0 turnover at 10 bp per side, on the first day only
        np.testing.assert_allclose((detail["gross"] - detail["net"]).to_numpy(), [0.001, 0, 0, 0, 0, 0, 0], atol=1e-15)
        self.assertEqual(detail["turnover"].tolist(), [1.0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(detail["turnover_long"].iloc[0], 0.5)
        self.assertEqual(detail["turnover_short"].iloc[0], 0.5)

    def test_cost_is_charged_once_per_week_on_target_weight_changes(self):
        a = self.A + [121, 121, 121, 121, 121, 121, 121]
        b = self.B + [90, 90, 90, 90, 90, 90, 90]
        weights, close = self.book(a, b, weeks=2)
        unchanged = r2.buy_and_hold_detail(weights, close, 20.0)
        self.assertEqual(int((unchanged["turnover"] > 0).sum()), 1)  # same book again: no second charge
        weights.iloc[7:14] = [0.25, -0.25]  # week 2 halves the book: turnover 0.5
        detail = r2.buy_and_hold_detail(weights, close, 20.0)
        paid = detail["gross"] - detail["net"]
        self.assertEqual(list(detail.index[paid.abs() > 0]), [close.index[1], close.index[8]])
        self.assertAlmostEqual(float(paid.loc[close.index[8]]), 0.5 * 10 / 1e4)
        self.assertEqual(float(detail["turnover"].sum()), 1.5)

    def test_coin_without_a_bar_keeps_its_last_price(self):
        b = [100, 100, 90, np.nan, np.nan, np.nan, np.nan, np.nan]
        weights, close = self.book(self.A, b)
        detail = r2.buy_and_hold_detail(weights, close, 0.0)
        # B stays at 90 after its last bar: V = 1 + 0.5 (A/100 - 1) + 0.05
        expected = [0.05, 1.10 / 1.05 - 1.0, 0, 0, 0, 0, 1.155 / 1.10 - 1.0]
        np.testing.assert_allclose(detail["gross"].to_numpy(), expected, atol=1e-12)

    def test_null_with_identity_permutation_equals_the_observed_statistic(self):
        rng = np.random.default_rng(3)
        idx = pd.date_range("2021-01-03", periods=7 * 12 + 1, freq="D", tz="UTC")
        n = 12
        close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (len(idx), n)), axis=0)), index=idx,
                             columns=[f"C{i}" for i in range(n)])
        weights = pd.DataFrame(np.nan, index=idx, columns=close.columns)
        for k in range(12):
            w = np.zeros(n)
            order = rng.permutation(n)
            w[order[:3]] = np.array([0.2, 0.2, 0.1])
            w[order[3:6]] = -np.array([0.3, 0.1, 0.1])
            weights.iloc[7 * k:7 * k + 7] = w
        eligible = pd.DataFrame(True, index=idx, columns=close.columns)
        spells = r2.weekly_spells(weights, close, eligible, idx[1], idx[-1])
        self.assertEqual(len(spells), 12)
        observed = r2.spell_statistic(spells)
        self.assertAlmostEqual(r2.spell_statistic(spells, np.random.default_rng(0), identity=True), observed, places=15)
        # the observed statistic is the compounded week returns of the daily table, per spell day
        detail = r2.buy_and_hold_detail(weights, close, 0.0)
        weekly = [(1 + detail["gross"].iloc[7 * k:7 * k + 7]).prod() - 1 for k in range(12)]
        self.assertAlmostEqual(observed, float(sum(weekly)) / 84.0, places=12)
        draws = [r2.spell_statistic(spells, np.random.default_rng(i)) for i in range(20)]
        self.assertGreater(float(np.std(draws)), 0.0)  # random re-allocations differ from the real book
        res = r2.g4_buy_and_hold_allocation_null(weights, close, eligible, idx[1], idx[-1], n_draws=99, seed=1)
        self.assertAlmostEqual(res["observed_mean_daily_gross"], observed, places=15)
        self.assertEqual(res["n_null"], 99)
        self.assertEqual(res["n_spells"], 12)

    def test_null_only_draws_eligible_coins(self):
        idx = pd.date_range("2021-01-03", periods=8, freq="D", tz="UTC")
        close = pd.DataFrame({"A": np.linspace(100, 107, 8), "B": np.linspace(100, 93, 8),
                              "C": np.linspace(100, 150, 8)}, index=idx)
        weights = pd.DataFrame(np.nan, index=idx, columns=close.columns)
        weights.iloc[:7] = [0.5, -0.5, 0.0]
        eligible = pd.DataFrame({"A": True, "B": True, "C": False}, index=idx)  # C, a big winner, is not eligible
        spells = r2.weekly_spells(weights, close, eligible, idx[1], idx[-1])
        stats = {round(r2.spell_statistic(spells, np.random.default_rng(i)), 10) for i in range(30)}
        allowed = {round((0.5 * 0.07 + 0.5 * 0.07) / 7, 10), round(-(0.5 * 0.07 + 0.5 * 0.07) / 7, 10)}
        self.assertTrue(stats <= allowed, stats)
        self.assertEqual(len(stats), 2)

    def test_accounting_hook_is_used_by_the_gate_evaluation(self):
        weights, close = self.book(self.A, self.B)
        spec = {"id": "T", "params": {}, "perturb": {}, "development": ["first full signal", "2021-01-10"],
                "null": "allocation"}
        returns = ss.asset_returns(close)
        calls = []

        def account(w, r, c):
            calls.append(c)
            return r2.buy_and_hold_detail(w, close, c)

        try:
            r2.evaluate_candidate_general(
                spec, {"close": close, "_calendar": close.index}, returns,
                validation_window=["2021-01-11", "2021-01-12"], crypto_reference=None, spy_returns=returns["A"],
                cost_bps=20.0, periods_per_year=365, fn=lambda d, p: weights, detail_fn=account,
                null_fn=lambda *a, **k: {"pass": False}, n_truncation_dates=1)
        except Exception:  # noqa: BLE001 - too little data for the later gates; only the hook matters here
            pass
        self.assertEqual(calls[:1], [20.0])


def _load_round2_script():
    spec = importlib.util.spec_from_file_location("strategy_search_v1_round2", ROOT / "scripts" / "strategy_search_v1_round2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RoundTwoRunnerGuards(unittest.TestCase):
    """The single-look guards fire before any data is fetched or any evaluation runs."""

    def setUp(self):
        boom = mock.Mock(side_effect=AssertionError("guard regressed: reached data loading or evaluation"))
        self.module = _load_round2_script()
        for target, name in ((self.module, "load_crypto_panel"), (self.module, "load_spy_data"),
                             (ss, "crypto_trend_core_reference"), (r2, "evaluate_candidate_general")):
            patcher = mock.patch.object(target, name, boom)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_refuses_when_results_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, ledger = Path(tmp) / "round2_results.json", Path(tmp) / "trials.jsonl"
            results.write_text("{}", encoding="utf-8")
            self.assertEqual(self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)]), 2)
            self.assertFalse(ledger.exists())
            self.assertEqual(results.read_text(encoding="utf-8"), "{}")

    def test_refuses_when_ledger_has_a_round_two_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, ledger = Path(tmp) / "round2_results.json", Path(tmp) / "trials.jsonl"
            ledger.write_text(json.dumps({"id": "X", "round": 1}) + "\n" + json.dumps({"id": "Y", "round": 2}) + "\n",
                              encoding="utf-8")
            before = ledger.read_text(encoding="utf-8")
            self.assertEqual(self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)]), 2)
            self.assertFalse(results.exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)

    def test_round_one_records_alone_do_not_block_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            results, ledger = Path(tmp) / "round2_results.json", Path(tmp) / "trials.jsonl"
            ledger.write_text(json.dumps({"id": "X", "round": 1}) + "\n", encoding="utf-8")
            reached = mock.Mock(side_effect=RuntimeError("reached"))
            with mock.patch.object(ss, "crypto_trend_core_reference", reached):
                with self.assertRaises(RuntimeError):
                    self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])

    def test_overrides_need_test_mode_and_there_is_no_draws_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.module.main(["--results", str(Path(tmp) / "r.json")]), 2)
            self.assertEqual(self.module.main(["--ledger", str(Path(tmp) / "t.jsonl")]), 2)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        with self.assertRaises(SystemExit) as ctx:
            self.module.main(["--draws", "5"])
        self.assertEqual(ctx.exception.code, 2)

    def test_registered_round_two_config(self):
        cfg = json.loads((ROOT / "config" / "strategy_search_v1_round2.json").read_text(encoding="utf-8"))
        specs = r2.candidate_specs(cfg)
        self.assertEqual([s["id"] for s in specs], [r2.CTREND_ID, r2.FOMC_ID])
        self.assertEqual(specs[0]["null"], "allocation")
        self.assertEqual(specs[0]["development"], ["first full signal", "2022-05-31"])
        self.assertEqual(specs[0]["validation"], ["2022-06-01", "2026-09-30"])
        self.assertEqual(len(ss.perturbation_param_sets(specs[0])), 8)


class RoundTwoEndToEnd(unittest.TestCase):
    """The whole runner on synthetic data with few draws: wiring, serialisation and the ledger."""

    def test_synthetic_run_writes_results_and_ledger_once(self):
        module = _load_round2_script()
        crypto = planted_panel(n_coins=40, days=1500, seed=21)
        start = pd.Timestamp("2019-06-01", tz="UTC")
        for frame in crypto.values():
            frame.index = pd.date_range(start, periods=len(frame), freq="D")
        panel = {**crypto, "provenance": {"symbols_listed": 40, "symbols_excluded": {}, "symbols_used": 40, "end": "x",
                                          "per_symbol": {}}}
        idx = pd.bdate_range("1993-06-01", "2026-09-30", tz="UTC")
        rng = np.random.default_rng(2)
        prices = pd.DataFrame({"SPY": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx))))}, index=idx)
        spy_returns = ss.asset_returns(prices)["SPY"]
        spy_bundle = ({"prices": prices, "_calendar": idx}, ss.asset_returns(prices), spy_returns,
                      ss.data_provenance(prices, {}))
        reference = pd.Series(rng.normal(0, 0.02, 1400), index=pd.date_range("2021-01-01", periods=1400, freq="D", tz="UTC"))
        round2_cfg = json.loads((ROOT / "config" / "strategy_search_v1_round2.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            results, ledger = Path(tmp) / "round2_results.json", Path(tmp) / "trials.jsonl"
            ledger.write_text(json.dumps({"id": "P", "round": 1, "status": "tested", "dev": {"sharpe_daily": 0.01}}) + "\n",
                              encoding="utf-8")
            with mock.patch.object(module, "load_crypto_panel", return_value=panel), \
                    mock.patch.object(module, "load_spy_data", return_value=spy_bundle), \
                    mock.patch.object(ss, "crypto_trend_core_reference", return_value=reference), \
                    mock.patch.object(ss, "N_NULL_DRAWS", 99), mock.patch.object(ss, "N_TRUNCATION_DATES", 3):
                code = module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])
                self.assertEqual(code, 0)
                payload = json.loads(results.read_text(encoding="utf-8"))
                self.assertEqual([c["id"] for c in payload["candidates"]], [r2.CTREND_ID, r2.FOMC_ID])
                self.assertEqual(payload["n_trials_cumulative"], 3)  # one prior ledger trial + two candidates
                for cand in payload["candidates"]:
                    self.assertEqual(sorted(cand["gates"]), ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"])
                    self.assertEqual(cand["gates"]["G5"]["n_trials"], 3)
                ctr = payload["candidates"][0]
                self.assertEqual(ctr["periods_per_year"], 365)
                self.assertEqual(ctr["gates"]["G4"]["null_type"], "allocation")
                self.assertEqual(len(ctr["gates"]["G6"]["variants"]), 8)
                self.assertIn("30/40", ctr["descriptive"]["paper_cost_scenarios_one_way_bps_long_short"])
                self.assertEqual(payload["candidates"][1]["gates"]["G4"]["null_type"], "timing")
                self.assertEqual(payload["candidates"][1]["periods_per_year"], 252)
                self.assertFalse(payload["claims"]["strategy_promotion_authorized"])
                records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
                self.assertEqual([r.get("round") for r in records].count(2), 2 + len(round2_cfg["screened_out"]))
                # a second look is refused
                self.assertEqual(module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)]), 2)


if __name__ == "__main__":
    unittest.main()
