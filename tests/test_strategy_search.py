"""Synthetic-data tests for strategy-search-v1 (no network, never touches the real ledger)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab.discovery_v2_evaluation import deflated_sharpe_probability

ROOT = Path(__file__).resolve().parents[1]
ROUND1 = json.loads((ROOT / "config" / "strategy_search_v1_round1.json").read_text(encoding="utf-8"))


def bdays(start: str, end: str | None = None, periods: int | None = None) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end, periods=periods, tz="UTC")


def step_prices(index: pd.DatetimeIndex, growth: dict[str, float]) -> pd.DataFrame:
    """Price = 100 * (1+g)^(month number): constant within a month, so month-end momentum is closed-form."""
    month_no = (index.year - index[0].year) * 12 + (index.month - index[0].month)
    return pd.DataFrame({a: 100.0 * (1.0 + g) ** month_no for a, g in growth.items()}, index=index)


def last_row(w: pd.DataFrame, date: str) -> pd.Series:
    return w.loc[pd.Timestamp(date, tz="UTC")]


class BacktestArithmetic(unittest.TestCase):
    def test_cost_turnover_and_timing(self):
        idx = bdays("2021-03-01", periods=5)
        weights = pd.DataFrame({"X": [1.0, 1.0, 0.0, 0.5, 0.5]}, index=idx)
        returns = pd.DataFrame({"X": [np.nan, 0.01, 0.02, -0.01, 0.03]}, index=idx)
        net, turnover = ss.backtest(weights, returns, 10.0)
        # weight decided at close t-1 earns day t: first earning day is idx[1]
        self.assertEqual(list(net.index), list(idx[1:]))
        np.testing.assert_allclose(turnover.to_numpy(), [1.0, 0.0, 1.0, 0.5])
        # 10 bps round trip = 5 bps per unit traded weight
        np.testing.assert_allclose(net.to_numpy(), [0.01 - 0.0005, 0.02, 0.0 - 0.0005, 0.015 - 0.00025])
        detail = ss.backtest_detail(weights, returns, 10.0)
        np.testing.assert_allclose(detail["gross"].to_numpy(), [0.01, 0.02, 0.0, 0.015])

    def test_nan_weights_are_cash_and_start_is_first_signal(self):
        idx = bdays("2021-03-01", periods=4)
        weights = pd.DataFrame({"X": [np.nan, np.nan, 1.0, 1.0]}, index=idx)
        returns = pd.DataFrame({"X": [0.0, 0.01, 0.02, 0.03]}, index=idx)
        net, turnover = ss.backtest(weights, returns, 0.0)
        self.assertEqual(list(net.index), list(idx[3:]))
        self.assertAlmostEqual(float(net.iloc[0]), 0.03)

    def test_short_leg_and_two_assets(self):
        idx = bdays("2021-03-01", periods=3)
        weights = pd.DataFrame({"A": [0.5, 0.5, 0.5], "B": [-0.5, -0.5, -0.5]}, index=idx)
        returns = pd.DataFrame({"A": [0.0, 0.02, 0.0], "B": [0.0, 0.04, 0.0]}, index=idx)
        net, turnover = ss.backtest(weights, returns, 10.0)
        self.assertAlmostEqual(float(turnover.iloc[0]), 1.0)
        self.assertAlmostEqual(float(net.iloc[0]), 0.5 * 0.02 - 0.5 * 0.04 - 1.0 * 0.0005)


class Calendar(unittest.TestCase):
    def test_month_end_and_first_day_with_holiday(self):
        cal = bdays("2021-03-22", "2021-04-08").drop(pd.Timestamp("2021-03-31", tz="UTC"))
        ends = [d.date().isoformat() for d in ss.month_end_dates(cal)]
        self.assertEqual(ends[0], "2021-03-30")
        firsts = [d.date().isoformat() for d in ss.first_trading_days(cal)]
        self.assertEqual(firsts, ["2021-04-01"])

    def test_final_date_month_end_rule(self):
        mid = bdays("2021-03-01", "2021-03-24")
        self.assertEqual(len(ss.month_end_dates(mid)), 0)
        full = bdays("2021-03-01", "2021-03-31")
        self.assertEqual(ss.month_end_dates(full)[-1], full[-1])

    def test_fred_lag_one_business_day(self):
        s = pd.Series([1.0, 2.0, np.nan, 4.0], index=bdays("2021-03-01", periods=4))  # Mon..Thu
        idx = bdays("2021-03-01", periods=6)
        avail = ss.fred_available(s, idx)
        self.assertTrue(np.isnan(avail.iloc[0]))
        self.assertEqual(list(avail.iloc[1:6]), [1.0, 2.0, 2.0, 4.0, 4.0])

    def test_parse_fred_csv_dot_is_nan(self):
        text = "observation_date,DTB3\n2021-03-01,0.04\n2021-03-02,.\n2021-03-03,0.05\n"
        s = ss.parse_fred_csv(text, "DTB3")
        self.assertEqual(len(s), 3)
        self.assertTrue(np.isnan(s.iloc[1]))
        self.assertEqual(s.index.tz.__str__(), "UTC")


class G1Truncation(unittest.TestCase):
    def setUp(self):
        idx = bdays("2020-01-01", periods=400)
        rng = np.random.default_rng(7)
        prices = pd.DataFrame({"A": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))}, index=idx)
        self.data = {"prices": prices}

    @staticmethod
    def honest(data, params):
        p = data["prices"]["A"]
        ma = p.rolling(5, min_periods=5).mean()
        w = (p > ma).astype(float).where(ma.notna())
        return pd.DataFrame({"A": w})

    @staticmethod
    def leaky(data, params):
        p = data["prices"]["A"]
        return pd.DataFrame({"A": (p.shift(-1) > p).astype(float)})

    def test_honest_passes_and_leaky_fails(self):
        for fn, expected in ((self.honest, True), (self.leaky, False)):
            w = fn(self.data, {})
            res = ss.g1_truncation(fn, self.data, {}, w)
            self.assertEqual(res["pass"], expected, msg=fn.__name__)
            self.assertEqual(res["dates_checked"], 50)

    def test_random_dates_are_seeded(self):
        w = self.honest(self.data, {})
        a = ss.g1_truncation(self.leaky, self.data, {}, self.leaky(self.data, {}))
        b = ss.g1_truncation(self.leaky, self.data, {}, self.leaky(self.data, {}))
        self.assertEqual(a["mismatches"], b["mismatches"])
        self.assertTrue(ss.g1_truncation(self.honest, self.data, {}, w)["pass"])

    def test_calendar_survives_truncation(self):
        data = {**self.data, "_calendar": self.data["prices"].index}
        cut = ss.truncate_data(data, self.data["prices"].index[100])
        self.assertEqual(len(cut["prices"]), 101)
        self.assertEqual(len(cut["_calendar"]), 400)

    def test_all_registered_candidates_are_causal_on_synthetic_data(self):
        data = _full_synthetic_data()
        for spec in ROUND1["candidates"]:
            fn = ss.CANDIDATE_FUNCS[spec["id"]]
            w = fn(data, spec["params"])
            res = ss.truncation_test(fn, data, spec["params"], list(w.dropna(how="all").index[::25]), w)
            self.assertTrue(res["pass"], msg=f"{spec['id']}: {res}")


def _full_synthetic_data() -> dict:
    idx = bdays("2012-01-02", "2016-12-30")
    rng = np.random.default_rng(11)
    tickers = sorted(set(ss.VAA_RISKY + ss.VAA_CASH + ss.PAA_RISKY + [ss.PAA_SAFE, "EFA", "AGG", "SVXY"] + ss.STYLE_UNIVERSE))
    prices = pd.DataFrame({t: 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))) for t in tickers}, index=idx)
    vix3m = pd.Series(18 + np.cumsum(rng.normal(0, 0.1, len(idx))), index=idx)
    prices["^VIX3M"] = vix3m
    prices["^VIX"] = vix3m * (1 + rng.normal(0, 0.08, len(idx)))
    dtb3 = pd.Series(1.0 + np.abs(np.cumsum(rng.normal(0, 0.02, len(idx)))), index=idx)
    wti = pd.Series(60 * np.exp(np.cumsum(rng.normal(0, 0.02, len(idx)))), index=idx)
    return {"prices": prices, "DTB3": dtb3, "DCOILWTICO": wti, "_calendar": idx}


class VaaCandidate(unittest.TestCase):
    RISKY = ss.VAA_RISKY

    def mom(self, negatives=(), order=None):
        base = {a: 0.1 - 0.01 * i for i, a in enumerate(self.RISKY)}  # SPY highest, then IWM, ...
        for a in negatives:
            base[a] = -0.05
        return base

    def test_slot_logic_all_b_cases(self):
        cash = {"SHY": 0.001, "IEF": 0.003, "LQD": 0.002}
        # b = 0: n = 2 -> top two risky, no cash
        self.assertEqual(ss.vaa_allocation(self.mom(), cash, 4, 2), {"SPY": 0.5, "IWM": 0.5})
        # b = 1: CF = .25, (1-CF)*T = 1.5 rounds half up to 2
        self.assertEqual(ss.vaa_allocation(self.mom(["HYG"]), cash, 4, 2), {"SPY": 0.5, "IWM": 0.5})
        # b = 2: CF = .5 -> n = 1: one risky slot and half in the best cash asset
        self.assertEqual(ss.vaa_allocation(self.mom(["HYG", "TLT"]), cash, 4, 2), {"SPY": 0.5, "IEF": 0.5})
        # b = 3: CF = .75 -> .5 rounds half up to 1
        self.assertEqual(ss.vaa_allocation(self.mom(["HYG", "TLT", "GLD"]), cash, 4, 2), {"SPY": 0.5, "IEF": 0.5})
        # b = B = 4: CF = 1 -> all cash; b > B behaves the same
        self.assertEqual(ss.vaa_allocation(self.mom(["HYG", "TLT", "GLD", "GSG"]), cash, 4, 2), {"IEF": 1.0})
        self.assertEqual(ss.vaa_allocation(self.mom(["HYG", "TLT", "GLD", "GSG", "VNQ"]), cash, 4, 2), {"IEF": 1.0})

    def test_best_cash_asset_and_lqd_overlap(self):
        cash = {"SHY": 0.001, "IEF": 0.003, "LQD": 0.02}
        self.assertEqual(ss.vaa_allocation(self.mom(["HYG", "TLT", "GLD", "GSG"]), cash, 4, 2), {"LQD": 1.0})
        m = self.mom(["HYG", "TLT"])
        m["LQD"] = 0.2  # LQD is also the top risky asset and the best cash asset: weights add
        self.assertEqual(ss.vaa_allocation(m, cash, 4, 2), {"LQD": 1.0})

    def test_T_and_B_perturbations(self):
        cash = {"SHY": 0.001, "IEF": 0.003, "LQD": 0.002}
        w = ss.vaa_allocation(self.mom(["HYG", "TLT"]), cash, 5, 3)  # CF=.4, n = round(1.8) = 2
        self.assertAlmostEqual(w["SPY"], 1 / 3)
        self.assertAlmostEqual(w["IWM"], 1 / 3)
        self.assertAlmostEqual(w["IEF"], 1 / 3)
        w1 = ss.vaa_allocation(self.mom(["HYG"]), cash, 3, 1)  # CF=1/3 -> n = round(.667) = 1
        self.assertEqual(w1, {"SPY": 1.0})

    def test_end_to_end_month_end_weights(self):
        idx = bdays("2019-01-01", "2021-06-30")
        growth = {a: 0.001 + 0.002 * (len(self.RISKY) - i) for i, a in enumerate(self.RISKY)}  # SPY fastest
        growth.update({"SHY": 0.0005, "IEF": 0.001})
        growth["LQD"] = 0.0001
        data = {"prices": step_prices(idx, growth)}
        w = ss.weights_R1C1_VAA_G12(data, {"B": 4, "T": 2})
        # rows before the first full 12-month momentum are NaN; first signal is month number 12 (2020-01-31)
        self.assertTrue(w.loc[:"2020-01-30"].isna().all().all())
        row = last_row(w, "2020-01-31")
        self.assertEqual(row["SPY"], 0.5)
        self.assertEqual(row["IWM"], 0.5)
        self.assertEqual(row.drop(["SPY", "IWM"]).abs().sum(), 0.0)
        # held through the month, decided again at the next month end
        np.testing.assert_array_equal(last_row(w, "2020-02-14").to_numpy(), row.to_numpy())

        neg = dict(growth)
        for a in ["SPY", "IWM", "QQQ", "VGK", "EWJ"]:  # b = 5 >= B
            neg[a] = -0.01
        w2 = ss.weights_R1C1_VAA_G12({"prices": step_prices(idx, neg)}, {"B": 4, "T": 2})
        row2 = last_row(w2, "2020-01-31")
        self.assertEqual(row2["IEF"], 1.0)
        self.assertEqual(row2.drop("IEF").abs().sum(), 0.0)


class PaaCandidate(unittest.TestCase):
    def mom(self, negatives=0, zeros=0):
        m = {a: 0.20 - 0.01 * i for i, a in enumerate(ss.PAA_RISKY)}
        names = list(ss.PAA_RISKY)
        for a in names[len(names) - negatives:]:
            m[a] = -0.02
        for a in names[len(names) - negatives - zeros: len(names) - negatives]:
            m[a] = 0.0
        return m

    def test_safe_share_and_split(self):
        w = ss.paa_allocation(self.mom(negatives=3), 6, 6)  # n0=3 -> safe .5; 9 positive, top 6 each .5/6
        for a in ss.PAA_RISKY[:6]:
            self.assertAlmostEqual(w[a], 0.5 / 6)
        self.assertAlmostEqual(w["IEF"], 0.5)
        self.assertAlmostEqual(sum(w.values()), 1.0)
        self.assertEqual(set(w) - {"IEF"}, set(ss.PAA_RISKY[:6]))

    def test_zero_momentum_counts_as_non_positive(self):
        w = ss.paa_allocation(self.mom(negatives=1, zeros=2), 6, 6)  # n0 = 3 (1 negative + 2 zero)
        self.assertAlmostEqual(w["IEF"], 0.5)
        self.assertNotIn(ss.PAA_RISKY[-2], w)

    def test_no_protection_and_full_protection(self):
        w0 = ss.paa_allocation(self.mom(), 6, 6)
        self.assertAlmostEqual(w0["IEF"], 0.0)
        self.assertAlmostEqual(sum(w0[a] for a in ss.PAA_RISKY[:6]), 1.0)
        w1 = ss.paa_allocation(self.mom(negatives=10), 6, 6)  # n0/6 > 1 -> safe = 1
        self.assertEqual(w1, {ss.PAA_RISKY[0]: 0.0, ss.PAA_RISKY[1]: 0.0, "IEF": 1.0})

    def test_unfilled_slots_go_to_ief(self):
        w = ss.paa_allocation(self.mom(negatives=8), 12, 6)  # safe = 8/12; 4 positives fill 4 of 6 slots
        slot = (1 - 8 / 12) / 6
        for a in ss.PAA_RISKY[:4]:
            self.assertAlmostEqual(w[a], slot)
        self.assertAlmostEqual(w["IEF"], 8 / 12 + 2 * slot)
        self.assertAlmostEqual(sum(w.values()), 1.0)

    def test_end_to_end_sma_momentum(self):
        idx = bdays("2019-01-01", "2021-06-30")
        growth = {a: 0.002 * (12 - i) for i, a in enumerate(ss.PAA_RISKY)}  # SPY fastest ... TLT 0.002
        for a in ss.PAA_RISKY[-4:]:
            growth[a] = -0.01
        growth["IEF"] = 0.001
        w = ss.weights_R1C2_PAA2({"prices": step_prices(idx, growth)}, {"lookback_months": 12, "protection_divisor": 6, "top_n": 6})
        self.assertTrue(w.loc[:"2019-11-28"].isna().all().all())  # 12 month-ends are needed
        row = last_row(w, "2019-12-31")
        self.assertAlmostEqual(row["IEF"], 4 / 6)
        for a in ss.PAA_RISKY[:6]:
            self.assertAlmostEqual(row[a], (1 - 4 / 6) / 6)
        self.assertAlmostEqual(row.sum(), 1.0)


class GemCandidate(unittest.TestCase):
    def build(self, g_spy, g_efa, g_agg, tbill):
        idx = bdays("2019-01-01", "2021-06-30")
        data = {"prices": step_prices(idx, {"SPY": g_spy, "EFA": g_efa, "AGG": g_agg})}
        data["DTB3"] = pd.Series(tbill, index=bdays("2017-01-02", "2021-06-30"))
        return data

    def test_picks_higher_of_us_and_exus_when_spy_beats_tbill(self):
        data = self.build(0.01, 0.015, 0.002, 4.0)  # SPY R12 = 12.7% > 4%
        w = ss.weights_R1C3_GEM(data, {"lookback_months": 12})
        row = last_row(w, "2020-01-31")
        self.assertEqual((row["EFA"], row["SPY"], row["AGG"]), (1.0, 0.0, 0.0))
        w2 = ss.weights_R1C3_GEM(self.build(0.015, 0.01, 0.002, 4.0), {"lookback_months": 12})
        self.assertEqual(last_row(w2, "2020-01-31")["SPY"], 1.0)

    def test_bond_fallback_and_tbill_units(self):
        # SPY R12 = (1.005)^12 - 1 = 6.2%: above a 4% bill, below an 8% bill (percent -> /100)
        hold = ss.weights_R1C3_GEM(self.build(0.005, 0.001, 0.002, 4.0), {"lookback_months": 12})
        self.assertEqual(last_row(hold, "2020-01-31")["SPY"], 1.0)
        bonds = ss.weights_R1C3_GEM(self.build(0.005, 0.001, 0.002, 8.0), {"lookback_months": 12})
        self.assertEqual(last_row(bonds, "2020-01-31")["AGG"], 1.0)
        neg = ss.weights_R1C3_GEM(self.build(-0.01, 0.01, 0.002, 0.5), {"lookback_months": 12})
        self.assertEqual(last_row(neg, "2020-01-31")["AGG"], 1.0)  # SPY negative: bonds even though EFA is strong

    def test_tbill_window_is_trailing_months_only(self):
        data = self.build(0.005, 0.001, 0.002, 1.0)
        old = data["DTB3"].index <= pd.Timestamp("2020-01-27", tz="UTC")  # before the window (2020-01-29, 2021-01-29]
        data["DTB3"] = data["DTB3"].mask(old, 50.0)  # huge bill rate before the window must not count
        w = ss.weights_R1C3_GEM(data, {"lookback_months": 12})
        self.assertEqual(last_row(w, "2021-01-29")["SPY"], 1.0)


class GemLookbackScaling(unittest.TestCase):
    def test_tbill_is_scaled_to_the_lookback_length(self):
        # 10-month return (1.005364)^10 - 1 = 5.5%; the 10-month bill return is 6%/100 * 10/12 = 5.0% (unscaled: 6.0%)
        g = 1.055 ** 0.1 - 1.0
        idx = bdays("2019-01-01", "2021-06-30")
        base = {"prices": step_prices(idx, {"SPY": g, "EFA": g / 2, "AGG": 0.001})}
        base["DTB3"] = pd.Series(6.0, index=bdays("2017-01-02", "2021-06-30"))
        hold = ss.weights_R1C3_GEM(base, {"lookback_months": 10})
        self.assertEqual(last_row(hold, "2020-01-31")["SPY"], 1.0)
        base["DTB3"] = pd.Series(7.0, index=bdays("2017-01-02", "2021-06-30"))  # 5.83% > 5.5%
        bonds = ss.weights_R1C3_GEM(base, {"lookback_months": 10})
        self.assertEqual(last_row(bonds, "2020-01-31")["AGG"], 1.0)

    def test_twelve_months_is_the_registered_rule(self):
        self.assertEqual(12 / 12.0, 1.0)
        self.assertIn("L/12", ss.GEM_TBILL_SCALING_NOTE)


class TurnOfMonth(unittest.TestCase):
    def weights(self, cal, before=1, after=3):
        data = {"prices": pd.DataFrame({"SPY": 100.0}, index=cal), "_calendar": cal}
        return ss.weights_R1C4_turn_of_month(data, {"days_before": before, "days_after": after})["SPY"]

    def invested(self, w):
        return [d.date().isoformat() for d in w.index[w == 1.0]]

    def test_days_minus1_plus1_to_plus3(self):
        cal = bdays("2021-01-18", "2021-04-09")
        got = self.invested(self.weights(cal))
        # weight at close t is 1 when the next trading day is day -1, +1, +2 or +3; entry = close of day -2
        self.assertEqual(got, ["2021-01-28", "2021-01-29", "2021-02-01", "2021-02-02",
                               "2021-02-25", "2021-02-26", "2021-03-01", "2021-03-02",
                               "2021-03-30", "2021-03-31", "2021-04-01", "2021-04-02"])

    def test_holiday_gap_moves_the_month_end(self):
        cal = bdays("2021-03-22", "2021-04-09").drop(pd.Timestamp("2021-03-31", tz="UTC"))
        got = self.invested(self.weights(cal))
        self.assertEqual(got, ["2021-03-29", "2021-03-30", "2021-04-01", "2021-04-02"])

    def test_year_boundary_and_perturbed_window(self):
        cal = bdays("2021-12-20", "2022-01-14")
        got = self.invested(self.weights(cal, before=2, after=2))
        # days -2,-1 (Dec 30, 31) and +1,+2 (Jan 3, 4): weights on the close before each
        self.assertEqual(got, ["2021-12-29", "2021-12-30", "2021-12-31", "2022-01-03"])

    def test_incomplete_last_month_is_not_a_month_end(self):
        cal = bdays("2021-03-15", "2021-03-24")
        self.assertEqual(self.invested(self.weights(cal)), [])

    def test_never_nan(self):
        cal = bdays("2021-01-18", "2021-02-26")
        self.assertFalse(self.weights(cal).isna().any())


class VixRatio(unittest.TestCase):
    def prices(self, vix):
        idx = bdays("2021-03-01", periods=len(vix))
        return pd.DataFrame({"^VIX": vix, "^VIX3M": 100.0, "SVXY": 50.0}, index=idx)

    VIX = [120.0, 110.0, 90.0, 80.0, 95.0, 105.0, 100.0, 70.0, 80.0, 90.0]

    def test_two_day_lag(self):
        data = {"prices": self.prices(self.VIX)}
        w = ss.weights_R1C5_vix_ratio_short_vol(data, {"threshold": 1.0, "sma_days": 3, "lag_days": 2})["SVXY"]
        # signal(i) = ratio<1 and ratio<SMA3: i2..i9 = 1,1,0,0,0,1,1,0 ; position held on day t uses signal(t-2),
        # i.e. the weight row decided at close d is signal(d-1)
        expected = [np.nan, np.nan, np.nan, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0]
        np.testing.assert_array_equal(w.to_numpy(), np.array(expected))

    def test_lag_one_uses_same_day_signal(self):
        data = {"prices": self.prices(self.VIX)}
        w = ss.weights_R1C5_vix_ratio_short_vol(data, {"threshold": 1.0, "sma_days": 3, "lag_days": 1})["SVXY"]
        expected = [np.nan, np.nan, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0]
        np.testing.assert_array_equal(w.to_numpy(), np.array(expected))

    def test_return_on_day_t_uses_ratio_two_days_back(self):
        data = {"prices": self.prices(self.VIX)}
        w = ss.weights_R1C5_vix_ratio_short_vol(data, {"threshold": 1.0, "sma_days": 3, "lag_days": 2})
        returns = pd.DataFrame({"SVXY": [0.0] * 10}, index=w.index)
        returns.iloc[7, 0] = 0.1  # day 7 return should be earned iff signal(5) = 0 -> not invested
        returns.iloc[5, 0] = 0.2  # day 5 return earned iff signal(3) = 1 -> invested
        net, _ = ss.backtest(w, returns, 0.0)
        self.assertAlmostEqual(float(net.loc[w.index[5]]), 0.2)
        self.assertAlmostEqual(float(net.loc[w.index[7]]), 0.0)

    def test_strict_inequality_and_no_signal_before_instrument(self):
        data = {"prices": self.prices(self.VIX)}
        data["prices"].loc[data["prices"].index[:5], "SVXY"] = np.nan
        w = ss.weights_R1C5_vix_ratio_short_vol(data, {"threshold": 1.0, "sma_days": 3, "lag_days": 2})["SVXY"]
        self.assertTrue(w.iloc[:5].isna().all())
        self.assertEqual(w.iloc[6], 0.0)  # ratio exactly 1.0 is not < 1.0


class OilRegression(unittest.TestCase):
    def build(self, noise=None, window=5, tbill=6.0):
        idx = bdays("2019-01-01", "2020-12-31")
        months = pd.period_range("2019-01", "2020-12", freq="M")
        x_ret = np.array([0.0, 0.05, -0.04, 0.03, 0.06, -0.05, 0.02, -0.03, 0.04, 0.01, -0.06, 0.05,
                          0.03, -0.02, 0.07, -0.04, 0.02, -0.05, 0.06, 0.01, -0.03, 0.04, -0.02, 0.05])
        wti_level = 50.0 * np.cumprod(1.0 + x_ret)  # month 0 has return 0
        y_ret = np.zeros(len(months))
        for j in range(1, len(months)):
            y_ret[j] = 0.01 + 0.5 * x_ret[j - 1] + (0.0 if noise is None else noise[j])
        spy_level = 100.0 * np.cumprod(1.0 + y_ret)
        month_no = (idx.year - 2019) * 12 + (idx.month - 1)
        prices = pd.DataFrame({"SPY": spy_level[month_no]}, index=idx)
        wti = pd.Series(wti_level[month_no], index=idx)
        dtb3 = pd.Series(tbill, index=bdays("2018-06-01", "2020-12-31"))
        return {"prices": prices, "DCOILWTICO": wti, "DTB3": dtb3}, x_ret, y_ret, idx

    def month_end(self, idx, k):
        m = pd.Period("2019-01", freq="M") + k
        return idx[(idx.year == m.year) & (idx.month == m.month)][-1]

    def test_exact_relation_forecast_vs_rf(self):
        data, x_ret, _, idx = self.build()
        w = ss.weights_R1C6_oil_spy(data, {"window_months": 5})["SPY"]
        # forecast_k = 0.01 + 0.5*x_k ; rf = 6/100/12 = 0.005 -> invested iff x_k > -0.01
        first_valid = 6
        self.assertTrue(w.loc[: self.month_end(idx, first_valid - 1)].isna().all())
        for k in range(first_valid, 22):
            t = self.month_end(idx, k)
            self.assertEqual(w.loc[t], 1.0 if x_ret[k] > -0.01 else 0.0, msg=f"month {k}")
        # held until the next month end
        k = 8
        self.assertEqual(w.loc[self.month_end(idx, k) + pd.offsets.BDay(1)], w.loc[self.month_end(idx, k)])

    def test_rf_threshold_changes_decision(self):
        data, x_ret, _, idx = self.build(tbill=24.0)  # rf = 2%/month > forecast 0.01 + 0.5 x unless x > 0.02
        w = ss.weights_R1C6_oil_spy(data, {"window_months": 5})["SPY"]
        for k in range(6, 22):
            self.assertEqual(w.loc[self.month_end(idx, k)], 1.0 if x_ret[k] > 0.02 else 0.0, msg=f"month {k}")

    def test_window_uses_last_n_pairs_with_noise(self):
        rng = np.random.default_rng(3)
        noise = rng.normal(0, 0.02, 24)
        data, x_ret, y_ret, idx = self.build(noise=noise)
        for window in (5, 8):
            w = ss.weights_R1C6_oil_spy(data, {"window_months": window})["SPY"]
            k = 15
            xs = x_ret[k - window: k]  # oil returns of months k-window .. k-1
            ys = y_ret[k - window + 1: k + 1]  # SPY returns of months k-window+1 .. k
            slope, intercept = np.polyfit(xs, ys, 1)
            forecast = intercept + slope * x_ret[k]
            self.assertEqual(w.loc[self.month_end(idx, k)], 1.0 if forecast > 0.005 else 0.0)

    def test_no_decision_without_enough_pairs(self):
        data, _, _, idx = self.build()
        w = ss.weights_R1C6_oil_spy(data, {"window_months": 24})["SPY"]
        self.assertTrue(w.isna().all())


class StyleMomentum(unittest.TestCase):
    def test_long_top_short_bottom_first_trading_day(self):
        idx = bdays("2021-01-04", "2021-04-30")
        slopes_a = {"IJJ": 0.001, "IJK": 0.003, "IJS": -0.002, "IJT": 0.0005, "IVE": 0.002, "IVW": -0.001}
        slopes_b = {**slopes_a, "IJT": 0.004, "IJJ": -0.004}
        switch = idx >= pd.Timestamp("2021-02-15", tz="UTC")
        rets = pd.DataFrame({a: np.where(switch, slopes_b[a], slopes_a[a]) for a in slopes_a}, index=idx)
        prices = 100.0 * (1.0 + rets).cumprod()
        w = ss.weights_R1C7_style_momentum({"prices": prices}, {"lookback_days": 3})
        self.assertEqual(list(w.columns), ss.STYLE_UNIVERSE)
        self.assertTrue(w.loc[:"2021-01-29"].isna().all().all())
        feb = last_row(w, "2021-02-01")
        self.assertEqual((feb["IJK"], feb["IJS"]), (0.5, -0.5))
        self.assertEqual(feb.drop(["IJK", "IJS"]).abs().sum(), 0.0)
        np.testing.assert_array_equal(last_row(w, "2021-02-26").to_numpy(), feb.to_numpy())  # held all month
        mar = last_row(w, "2021-03-01")
        self.assertEqual((mar["IJT"], mar["IJJ"]), (0.5, -0.5))
        self.assertEqual(mar.sum(), 0.0)  # dollar neutral
        self.assertEqual(mar.abs().sum(), 1.0)

    def test_decision_uses_trading_day_lookback_not_months(self):
        idx = bdays("2021-01-04", "2021-03-31")
        base = {a: 100.0 for a in ss.STYLE_UNIVERSE}
        prices = pd.DataFrame(base, index=idx)
        # IVW rallies only over the 240-day-style window ending Feb 1 (lookback 2): last two days
        prices.loc[idx[idx >= pd.Timestamp("2021-01-29", tz="UTC")], "IVW"] = 110.0
        w = ss.weights_R1C7_style_momentum({"prices": prices}, {"lookback_days": 2})
        self.assertEqual(last_row(w, "2021-02-01")["IVW"], 0.5)


class Nulls(unittest.TestCase):
    def test_timing_null_preserves_days_and_spell_lengths(self):
        pos = np.array([0, 0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0], dtype=float)

        def runs(a):
            state = a != 0
            cuts = np.flatnonzero(state[1:] != state[:-1]) + 1
            blocks = np.split(state, cuts)
            return sorted(len(b) for b in blocks if b[0]), sorted(len(b) for b in blocks if not b[0])

        rng = np.random.default_rng(1)
        seen = set()
        for _ in range(50):
            shuffled = ss.run_length_shuffle(pos, rng)
            self.assertEqual(shuffled.sum(), pos.sum())
            self.assertEqual(len(shuffled), len(pos))
            self.assertEqual(shuffled[0] != 0, pos[0] != 0)
            self.assertEqual(runs(shuffled), runs(pos))
            seen.add(tuple(shuffled))
        self.assertGreater(len(seen), 1)

    def test_timing_null_draws_are_seeded_and_mean_matches_exposure(self):
        idx = bdays("2021-01-04", periods=200)
        pos = pd.Series(([1.0] * 5 + [0.0] * 15) * 10, index=idx)
        ret = pd.Series(0.001, index=idx)  # constant return: every matched book earns exposure * 0.001
        d1 = ss.timing_null_draws(pos, ret, n_draws=120, seed=5)
        d2 = ss.timing_null_draws(pos, ret, n_draws=120, seed=5)
        np.testing.assert_array_equal(d1, d2)
        np.testing.assert_allclose(d1, 0.25 * 0.001)

    def test_allocation_null_preserves_gross_long_short_counts(self):
        n = 5
        idx = bdays("2021-01-04", periods=3)
        returns = pd.DataFrame({f"a{i}": [10.0**i] * 3 for i in range(n)}, index=idx)
        weights = pd.DataFrame(0.0, index=idx, columns=returns.columns)
        weights.iloc[:, 0] = 0.5
        weights.iloc[:, 1] = 0.3
        weights.iloc[:, 2] = -0.4  # two longs, one short
        valid = set()
        import itertools
        for a, b, c in itertools.permutations(range(n), 3):
            valid.add(round(0.5 * 10.0**a + 0.3 * 10.0**b - 0.4 * 10.0**c, 6))
        draws = []
        rng = np.random.default_rng(2)
        for _ in range(300):
            s = ss.matched_random_selection_returns(returns, weights, rng)
            for v in s:
                self.assertIn(round(float(v), 6), valid)  # distinct assets, same weight vector
                draws.append(round(float(v), 6))
        self.assertGreater(len(set(draws)), 20)

    def test_g4_gate_structure_on_synthetic_books(self):
        idx = bdays("2020-01-01", periods=300)
        rng = np.random.default_rng(4)
        returns = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), index=idx, columns=list("ABC"))
        weights = pd.DataFrame(0.0, index=idx, columns=list("ABC"))
        weights["A"] = 1.0
        res = ss.g4_matched_null("allocation", weights, returns, idx[1], idx[-1], n_draws=199, seed=ss.SEED)
        self.assertEqual(res["n_null"], 199)
        self.assertIn("p", res)
        res_t = ss.g4_matched_null("timing", weights[["A"]], returns[["A"]], idx[1], idx[-1], n_draws=199, seed=ss.SEED)
        self.assertEqual(res_t["n_null"], 199)


class SpellNull(unittest.TestCase):
    def test_spell_frames_collapse_between_weight_changes(self):
        idx = bdays("2021-01-04", periods=7)
        pos = pd.DataFrame({"A": [1, 1, 1, 0, 0, 1, 1], "B": [0, 0, 0, 1, 1, 0, 0]}, index=idx, dtype=float)
        rets = pd.DataFrame({"A": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07], "B": [0.1] * 7}, index=idx)
        spell_ret, spell_pos, days = ss.spell_frames(pos, rets)
        self.assertEqual(list(days), [3.0, 2.0, 2.0])
        np.testing.assert_allclose(spell_ret["A"].to_numpy(), [0.06, 0.09, 0.13])  # sums of daily returns
        np.testing.assert_allclose(spell_ret["B"].to_numpy(), [0.3, 0.2, 0.2])
        self.assertEqual(spell_pos.to_numpy().tolist(), [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])

    def test_asset_unavailable_on_any_spell_day_is_excluded(self):
        idx = bdays("2021-01-04", periods=4)
        pos = pd.DataFrame({"A": [1.0] * 4, "B": [0.0] * 4}, index=idx)
        rets = pd.DataFrame({"A": [0.01] * 4, "B": [np.nan, 0.1, 0.1, 0.1]}, index=idx)
        spell_ret, _, _ = ss.spell_frames(pos, rets)
        self.assertTrue(np.isnan(spell_ret["B"].iloc[0]))
        self.assertAlmostEqual(spell_ret["A"].iloc[0], 0.04)

    def test_one_permutation_per_spell_not_per_day(self):
        import itertools

        n = 5
        idx = bdays("2021-01-04", periods=20)
        returns = pd.DataFrame({f"a{i}": [10.0**i] * 20 for i in range(n)}, index=idx)
        pos = pd.DataFrame(0.0, index=idx, columns=returns.columns)
        pos.iloc[:10, 0], pos.iloc[:10, 1], pos.iloc[:10, 2] = 0.5, 0.3, -0.4  # spell 1
        pos.iloc[10:, 3], pos.iloc[10:, 4] = 0.6, -0.6  # spell 2
        spell_ret, spell_pos, days = ss.spell_frames(pos, returns)
        self.assertEqual(list(days), [10.0, 10.0])
        draws = ss.allocation_null_draws(spell_ret, spell_pos, days, n_draws=400, seed=3)
        v1 = {0.5 * 10.0**a + 0.3 * 10.0**b - 0.4 * 10.0**c for a, b, c in itertools.permutations(range(n), 3)}
        v2 = {0.6 * 10.0**a - 0.6 * 10.0**b for a, b in itertools.permutations(range(n), 2)}
        # constant assets within a spell: draw = (10*v1 + 10*v2) / 20 with ONE v1 and ONE v2.  A per-day redraw would
        # average ~20 different values and almost never land on such a pair.
        allowed = np.array([(x + y) / 2.0 for x in v1 for y in v2])
        for d in draws:
            self.assertTrue(np.isclose(allowed, d, rtol=0, atol=1e-6).any(), msg=str(d))
        self.assertGreater(len(set(np.round(draws, 6))), 20)

    def test_single_spell_draws_are_a_single_permutation(self):
        import itertools

        n = 5
        idx = bdays("2021-01-04", periods=20)
        returns = pd.DataFrame({f"a{i}": [10.0**i] * 20 for i in range(n)}, index=idx)
        pos = pd.DataFrame(0.0, index=idx, columns=returns.columns)
        pos.iloc[:, 0], pos.iloc[:, 1], pos.iloc[:, 2] = 0.5, 0.3, -0.4
        spell_ret, spell_pos, days = ss.spell_frames(pos, returns)
        self.assertEqual(len(days), 1)
        valid = {round(0.5 * 10.0**a + 0.3 * 10.0**b - 0.4 * 10.0**c, 6) for a, b, c in itertools.permutations(range(n), 3)}
        for d in ss.allocation_null_draws(spell_ret, spell_pos, days, n_draws=200, seed=1):
            self.assertIn(round(float(d), 6), valid)

    def test_observed_statistic_matches_daily_gross_mean(self):
        idx = bdays("2020-01-01", periods=300)
        rng = np.random.default_rng(14)
        returns = pd.DataFrame(rng.normal(0.0003, 0.01, (300, 3)), index=idx, columns=list("ABC"))
        weights = pd.DataFrame(0.0, index=idx, columns=list("ABC"))
        weights.iloc[:100, 0] = 1.0
        weights.iloc[100:200, 1] = 1.0
        weights.iloc[200:, 2] = 1.0
        res = ss.g4_matched_null("allocation", weights, returns, idx[1], idx[-1], n_draws=199, seed=ss.SEED)
        pos = weights.shift(1).fillna(0.0).loc[idx[1]:]
        expected = float((pos * returns.loc[idx[1]:]).sum(axis=1).mean())
        self.assertAlmostEqual(res["observed_mean_daily_gross"], expected, places=12)


class PriceCalendarAndProvenance(unittest.TestCase):
    def test_build_prices_uses_spy_calendar_only(self):
        spy_idx = bdays("2021-03-01", periods=12)
        spy = pd.Series(100.0, index=spy_idx)
        vix_idx = spy_idx.delete([3, 4, 5, 6, 7, 8, 9]).append(pd.DatetimeIndex([pd.Timestamp("2021-03-06", tz="UTC")]))
        vix = pd.Series(20.0, index=vix_idx.sort_values())
        frame = ss.build_prices({"SPY": spy, "^VIX": vix}, ffill_limit=5)
        self.assertTrue(frame.index.equals(spy_idx))
        self.assertNotIn(pd.Timestamp("2021-03-06", tz="UTC"), frame.index)  # extra (weekend) date dropped
        self.assertEqual(int(frame["^VIX"].notna().sum()), 3 + 5 + 2)  # 5 rows filled, the rest of the gap stays NaN
        self.assertTrue(frame["^VIX"].iloc[9:10].isna().all())

    def test_data_provenance_fields(self):
        idx = bdays("2021-03-01", periods=10)
        prices = pd.DataFrame({"SPY": np.arange(10.0) + 100, "X": [np.nan] * 3 + list(np.arange(7.0) + 50)}, index=idx)
        fred = {"DTB3": pd.Series(np.arange(5.0), index=idx[:5])}
        prov = ss.data_provenance(prices, fred)
        self.assertEqual(prov["tickers"]["X"]["rows"], 7)
        self.assertEqual(prov["tickers"]["X"]["first_date"], "2021-03-04")
        self.assertEqual(prov["tickers"]["SPY"]["last_date"], "2021-03-12")
        self.assertEqual(prov["fred"]["DTB3"]["rows"], 5)
        self.assertEqual(len(prov["price_frame_sha256"]), 64)
        changed = prices.copy()
        changed.iloc[4, 0] += 1e-6
        self.assertNotEqual(prov["price_frame_sha256"], ss.data_provenance(changed, fred)["price_frame_sha256"])

    def test_reference_cache_key_tracks_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg, pkl = Path(tmp) / "c.json", Path(tmp) / "d.pkl"
            cfg.write_text("{}", encoding="utf-8")
            pkl.write_bytes(b"abc")
            k0 = ss.crypto_reference_cache_key(cfg, pkl)
            self.assertEqual(k0, ss.crypto_reference_cache_key(cfg, pkl))
            cfg.write_text('{"a": 1}', encoding="utf-8")
            k1 = ss.crypto_reference_cache_key(cfg, pkl)
            pkl.write_bytes(b"abcd")
            k2 = ss.crypto_reference_cache_key(cfg, pkl)
            self.assertEqual(len({k0, k1, k2}), 3)

    def test_reference_provenance_is_truthful(self):
        self.assertIn("Binance funding", ss.CRYPTO_REFERENCE_PROVENANCE)
        self.assertIn("MEXC 8h prices", ss.CRYPTO_REFERENCE_PROVENANCE)
        self.assertIn("MEXC funding history starts 2025-04", ss.CRYPTO_REFERENCE_PROVENANCE)


class DsrGate(unittest.TestCase):
    def test_trial_count_is_cumulative(self):
        rng = np.random.default_rng(9)
        dev = pd.Series(rng.normal(0.001, 0.01, 800))
        own = float(dev.mean() / dev.std(ddof=1))
        prior = [0.01, -0.02, 0.03]
        this_round = [own, 0.005]
        res = ss.dsr_gate(dev, prior, this_round)
        self.assertEqual(res["n_trials"], 5)
        direct = deflated_sharpe_probability(dev.to_numpy(), prior + this_round)
        self.assertAlmostEqual(res["probability"], direct["probability"])
        many_prior = list(np.linspace(-0.05, 0.08, 33))
        res_many = ss.dsr_gate(dev, many_prior, this_round)
        self.assertEqual(res_many["n_trials"], 35)
        self.assertLess(res_many["probability"], res["probability"])  # more, wider trials deflate harder

    def test_ledger_sharpes_feed_the_next_round(self):
        records = [{"dev": {"sharpe_daily": 0.02}}, {"dev": {"sharpe_daily": None}}, {"dev": {"sharpe_daily": -0.01}}]
        self.assertEqual(ss.ledger_trial_sharpes(records), [0.02, -0.01])

    def test_apply_dsr_uses_whole_round(self):
        rng = np.random.default_rng(10)
        results = []
        for i in range(3):
            r = pd.Series(rng.normal(0.0005 * (i + 1), 0.01, 500))
            results.append({"dev": {"sharpe_daily": float(r.mean() / r.std(ddof=1))}, "_dev_net": r, "gates": {}})
        ss.apply_dsr(results, [0.01, 0.0])
        self.assertTrue(all(r["gates"]["G5"]["n_trials"] == 5 for r in results))


class Gates(unittest.TestCase):
    def test_g2_g3_thresholds(self):
        rng = np.random.default_rng(1)
        strong = pd.Series(rng.normal(0.0012, 0.008, 1500))
        g2 = ss.g2_development(strong)
        self.assertTrue(g2["pass"])
        self.assertAlmostEqual(g2["sharpe"], g2["sharpe_daily"] * np.sqrt(252))
        weak = pd.Series(rng.normal(0.00005, 0.01, 1500))
        self.assertFalse(ss.g2_development(weak)["pass"])
        self.assertTrue(ss.g3_validation(g2, pd.Series(rng.normal(0.0012, 0.008, 800)))["pass"])
        self.assertFalse(ss.g3_validation(g2, pd.Series(rng.normal(-0.0005, 0.008, 800)))["pass"])

    def test_g3_relative_bar(self):
        val = pd.Series(np.tile([0.012, -0.006], 500))  # Sharpe well above 0.4
        stats = ss.perf_stats(val)
        self.assertFalse(ss.g3_validation({"sharpe": stats["sharpe"] / 0.3}, val)["pass"])  # val = 30% of dev
        self.assertTrue(ss.g3_validation({"sharpe": stats["sharpe"] / 0.5}, val)["pass"])  # val = 50% of dev

    def test_g6_rules(self):
        dev = pd.Series([0.001] * 100)
        ok = ss.g6_robustness({"sharpe": 1.0}, dev, [{"sharpe": 0.6}, {"sharpe": 1.2}])
        self.assertTrue(ok["pass"])
        bad = ss.g6_robustness({"sharpe": 1.0}, dev, [{"sharpe": 0.4}, {"sharpe": 1.2}])
        self.assertFalse(bad["pass"])
        neg_half = ss.g6_robustness({"sharpe": 1.0}, pd.Series([0.002] * 50 + [-0.001] * 50), [{"sharpe": 0.9}])
        self.assertFalse(neg_half["pass"])

    def test_g7_cost_wall(self):
        gross = pd.Series([0.001] * 100)
        turnover = pd.Series([0.1] * 100)  # wall = 0.001 / (0.1/2/1e4) = 200 bps
        res = ss.g7_costs(gross, turnover, 10.0)
        self.assertAlmostEqual(res["cost_wall_bps"], 200.0)
        self.assertTrue(res["pass"])
        self.assertFalse(ss.g7_costs(gross * 0.1, turnover, 10.0)["pass"])  # wall 20 < 30

    def test_g8_independence(self):
        idx = bdays("2021-01-04", periods=200)
        rng = np.random.default_rng(6)
        cand = pd.Series(rng.normal(0, 0.01, 200), index=idx)
        spy = pd.Series(rng.normal(0, 0.01, 200), index=idx)
        ref = pd.Series(rng.normal(0, 0.01, 200), index=idx + pd.Timedelta("1D"))  # stamped d+1 covers d
        res = ss.g8_independence(cand, ref, spy)
        self.assertTrue(res["pass"])
        self.assertGreater(res["crypto_core"]["overlap_days"], 100)
        self.assertFalse(ss.g8_independence(cand, ref, cand)["pass"])  # corr with SPY = 1
        ref_same = cand.copy()
        ref_same.index = ref_same.index + pd.Timedelta("1D")
        self.assertFalse(ss.g8_independence(cand, ref_same, spy)["pass"])  # restamped: perfect correlation with crypto
        self.assertFalse(ss.g8_independence(cand, None, spy)["pass"])


class RegistrationConsistency(unittest.TestCase):
    def test_universes_match_config(self):
        by_id = {c["id"]: c for c in ROUND1["candidates"]}
        self.assertEqual(ss.VAA_RISKY, by_id["R1C1_VAA_G12"]["universe"]["risky"])
        self.assertEqual(ss.VAA_CASH, by_id["R1C1_VAA_G12"]["universe"]["cash"])
        self.assertEqual(ss.PAA_RISKY, by_id["R1C2_PAA2"]["universe"]["risky"])
        self.assertEqual([ss.PAA_SAFE], by_id["R1C2_PAA2"]["universe"]["safe"])
        gem = by_id["R1C3_GEM"]["universe"]
        self.assertEqual((ss.GEM_US, ss.GEM_EXUS, ss.GEM_BONDS), (gem["us"], gem["ex_us"], gem["bonds"]))
        self.assertEqual(ss.STYLE_UNIVERSE, by_id["R1C7_style_momentum"]["universe"])
        self.assertEqual(set(ss.CANDIDATE_FUNCS), set(by_id))
        self.assertEqual([c["id"] for c in ROUND1["candidates"]], list(ss.CANDIDATE_FUNCS))

    def test_perturbation_sets_follow_registration(self):
        counts = {c["id"]: len(ss.perturbation_param_sets(c)) for c in ROUND1["candidates"]}
        self.assertEqual(counts, {"R1C1_VAA_G12": 4, "R1C2_PAA2": 6, "R1C3_GEM": 2, "R1C4_turn_of_month": 2,
                                  "R1C5_vix_ratio_short_vol": 4, "R1C6_oil_spy": 2, "R1C7_style_momentum": 2})
        tom = [c for c in ROUND1["candidates"] if c["id"] == "R1C4_turn_of_month"][0]
        got = [(p["days_before"], p["days_after"]) for p in ss.perturbation_param_sets(tom)]
        self.assertEqual(got, [(1, 2), (2, 3)])
        vix = [c for c in ROUND1["candidates"] if c["id"] == "R1C5_vix_ratio_short_vol"][0]
        first = ss.perturbation_param_sets(vix)[0]
        self.assertEqual((first["threshold"], first["sma_days"], first["lag_days"]), (0.8, 60, 2))

    def test_protocol_constants(self):
        self.assertEqual(ss.SEED, 20261011)
        self.assertEqual(ss.N_NULL_DRAWS, 999)
        self.assertEqual(ss.N_TRUNCATION_DATES, 50)
        self.assertEqual(ss.TRADING_DAYS, 252)
        self.assertEqual(ss.NW_LAGS, 5)


class EvaluateAndLedger(unittest.TestCase):
    @staticmethod
    def momentum(data, params):
        p = data["prices"][["A", "B"]]
        look = int(params["n"])
        mom = p / p.shift(look) - 1.0
        top = mom.eq(mom.max(axis=1), axis=0).astype(float).where(mom.notna())
        return top

    def test_end_to_end_with_temp_ledger(self):
        idx = bdays("2018-01-01", "2021-12-31")
        rng = np.random.default_rng(12)
        prices = pd.DataFrame({k: 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx)))) for k in "AB"}, index=idx)
        data = {"prices": prices, "_calendar": idx}
        returns = ss.asset_returns(prices)
        spec = {"id": "SYNTH", "params": {"n": 20}, "perturb": {"n": [16, 24]},
                "development": ["first full signal", "2019-12-31"], "null": "allocation"}
        ref = pd.Series(rng.normal(0, 0.01, 800), index=bdays("2019-06-01", periods=800))
        res = ss.evaluate_candidate(spec, data, returns, validation_window=["2020-01-01", "2021-09-30"],
                                    crypto_reference=ref, spy_returns=returns["A"], n_draws=199, fn=self.momentum)
        ss.apply_dsr([res], [0.0, 0.01])
        self.assertEqual(set(res["gates"]), set(ss.GATE_ORDER))
        self.assertEqual(res["gates"]["G5"]["n_trials"], 3)
        self.assertEqual(len(res["gates"]["G6"]["variants"]), 2)
        self.assertTrue(res["gates"]["G1"]["pass"])
        passed, first_fail = ss.verdict(res)
        self.assertEqual(passed, first_fail is None)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "trials.jsonl"
            ss.append_trial(ledger, ss.ledger_record(res, 1))
            ss.append_trial(ledger, ss.ledger_record(res, 1))
            lines = ledger.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            rec = json.loads(lines[0])
            self.assertEqual(rec["id"], "SYNTH")
            self.assertEqual(rec["round"], 1)
            self.assertEqual(len(rec["return_series_sha256"]), 64)
            self.assertEqual(len(ss.read_trials(ledger)), 2)
            self.assertIn("timestamp_utc", rec)

    def test_screened_out_are_logged_with_reasons_and_are_not_trials(self):
        records = ss.screened_out_records(ROUND1, 1)
        self.assertEqual(len(records), len(ROUND1["screened_out"]))
        self.assertTrue(all(r["status"] == "ineligible" and r["reason"] for r in records))
        self.assertEqual(ss.ledger_trial_sharpes(records), [])

    def test_series_hash_is_stable_and_sensitive(self):
        s = pd.Series([0.1, 0.2], index=bdays("2021-01-04", periods=2))
        self.assertEqual(ss.series_sha256(s), ss.series_sha256(s.copy()))
        self.assertNotEqual(ss.series_sha256(s), ss.series_sha256(s * 1.0000001))


def _load_script():
    spec = importlib.util.spec_from_file_location("strategy_search_v1_round1", ROOT / "scripts" / "strategy_search_v1_round1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunScript(unittest.TestCase):
    """Every guard test stubs the network and the evaluation to raise, so a regressed guard fails loudly offline."""

    def setUp(self):
        boom = mock.Mock(side_effect=AssertionError("guard regressed: reached fetch/evaluation"))
        self.patches = [mock.patch.object(ss, "fetch_close", boom), mock.patch.object(ss, "fetch_fred", boom),
                        mock.patch.object(ss, "crypto_trend_core_reference", boom),
                        mock.patch.object(ss, "evaluate_candidate", boom)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.module = _load_script()

    def test_refuses_second_run_when_results_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "round1_results.json"
            ledger = Path(tmp) / "trials.jsonl"
            results.write_text("{}", encoding="utf-8")
            code = self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            self.assertFalse(ledger.exists())
            self.assertEqual(results.read_text(encoding="utf-8"), "{}")

    def test_refuses_when_ledger_has_round_one_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "round1_results.json"
            ledger = Path(tmp) / "trials.jsonl"
            ledger.write_text(json.dumps({"id": "X", "round": 1}) + "\n", encoding="utf-8")
            before = ledger.read_text(encoding="utf-8")
            code = self.module.main(["--test-mode", "--results", str(results), "--ledger", str(ledger)])
            self.assertEqual(code, 2)
            self.assertFalse(results.exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)

    def test_path_overrides_need_test_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = self.module.main(["--results", str(Path(tmp) / "r.json")])
            self.assertEqual(code, 2)
            code = self.module.main(["--ledger", str(Path(tmp) / "t.jsonl")])
            self.assertEqual(code, 2)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_draws_option_is_gone(self):
        with self.assertRaises(SystemExit) as ctx:
            self.module.main(["--draws", "5"])
        self.assertEqual(ctx.exception.code, 2)

    def test_ticker_list_covers_registration(self):
        tickers = self.module.all_tickers(ROUND1)
        for needed in ["SPY", "SVXY", "^VIX", "^VIX3M", "EFA", "AGG", "IEF", "IJJ", "IVW", "GSG", "EEM", "IYR"]:
            self.assertIn(needed, tickers)
        self.assertFalse([t for t in tickers if t.startswith("FRED")])
        self.assertEqual(len(tickers), len(set(tickers)))


if __name__ == "__main__":
    unittest.main()
