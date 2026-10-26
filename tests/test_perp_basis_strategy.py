"""Perp log-basis quintile sort (strategy-search-v3 round 1): signal timing, eligibility, quintiles, funding sign,
costs on overlapping books, entry delay, null and plumbing.  Synthetic data only; no network."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab import perp_basis_strategy as pbs
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2
from orderflow_edge_lab.truncation_check import check_truncation

ROOT = Path(__file__).resolve().parents[1]
ROUND_CFG = json.loads((ROOT / "config" / "strategy_search_v3_round1.json").read_text(encoding="utf-8"))
PROTOCOL = json.loads((ROOT / "config" / "strategy_search_v3_leveraged.json").read_text(encoding="utf-8"))


def ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def bar_ends(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(ts(start), ts(end), freq="1h")


def perp_frame(ends: pd.DatetimeIndex, close, volume=1e6) -> pd.DataFrame:
    close = np.broadcast_to(np.asarray(close, dtype=float), len(ends)).copy()
    vol = np.broadcast_to(np.asarray(volume, dtype=float), len(ends)).copy()
    return pd.DataFrame({"close": close, "quote_volume": vol}, index=ends)


def spot_frame(ends: pd.DatetimeIndex, close) -> pd.DataFrame:
    return pd.DataFrame({"close": np.broadcast_to(np.asarray(close, dtype=float), len(ends)).copy()}, index=ends)


def funding_frame(stamps: list[str], rates: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"rate": rates, "interval_hours": 8.0}, index=pd.DatetimeIndex([ts(s) for s in stamps]))


def inputs_for(perp, spot, funding, max_exit=None) -> pbs.BasisInputs:
    cap = None if max_exit is None else ts(max_exit)
    return pbs.BasisInputs(data=pbs.build_event_panels(perp, spot), perp=perp, funding=funding, max_exit=cap)


def weights_frame(rows: dict[str, dict[str, float]], columns: list[str], **params) -> pd.DataFrame:
    frame = pd.DataFrame({c: [rows[t].get(c, 0.0) for t in rows] for c in columns},
                         index=pd.DatetimeIndex([ts(t) for t in rows]))
    frame.attrs["params"] = {**pbs.DEFAULT_PARAMS, **params}
    return frame


def panels(index: list[str], perp: dict[str, list[float]], spot: dict[str, list[float]],
           dv: dict[str, list[float]]) -> dict[str, pd.DataFrame]:
    idx = pd.DatetimeIndex([ts(t) for t in index])
    return {"perp_close": pd.DataFrame(perp, index=idx), "spot_close": pd.DataFrame(spot, index=idx),
            "perp_dv24": pd.DataFrame(dv, index=idx)}


class PanelTests(unittest.TestCase):
    def test_trailing_volume_needs_a_full_day_and_is_the_sum_of_the_last_24_bars(self):
        ends = bar_ends("2021-03-01 01:00", "2021-03-03 00:00")
        vol = np.arange(1.0, len(ends) + 1)
        out = pbs.trailing_volume(pd.Series(vol, index=ends))
        self.assertTrue(out.iloc[:23].isna().all())
        self.assertEqual(out.index[23], ts("2021-03-02 00:00"))  # first bar end + 23h: listed for 24h
        self.assertEqual(float(out.iloc[23]), vol[:24].sum())
        self.assertEqual(float(out.iloc[30]), vol[7:31].sum())

    def test_missing_hours_inside_the_span_count_as_zero_volume(self):
        ends = bar_ends("2021-03-01 01:00", "2021-03-03 00:00").delete(30)
        out = pbs.trailing_volume(pd.Series(1.0, index=ends))
        self.assertEqual(float(out.loc[ts("2021-03-02 08:00")]), 23.0)  # 23 bars + one empty hour

    def test_event_panels_hours_and_spot_alignment(self):
        ends = bar_ends("2021-03-01 01:00", "2021-03-03 00:00")
        perp = {"AUSDT": perp_frame(ends, 10.0), "AUSDT#2": perp_frame(ends[24:], 11.0)}
        spot = {"AUSDT": spot_frame(ends, 9.0)}
        data = pbs.build_event_panels(perp, spot)
        hours = sorted(set(data["perp_close"].index.hour))
        self.assertEqual(hours, [0, 1, 8, 9, 16, 17])
        self.assertEqual(list(data["spot_close"].columns), ["AUSDT", "AUSDT#2"])
        self.assertEqual(float(data["spot_close"].loc[ts("2021-03-02 08:00"), "AUSDT#2"]), 9.0)  # spot of the base symbol
        self.assertTrue(np.isnan(data["perp_close"].loc[ts("2021-03-01 08:00"), "AUSDT#2"]))

    def test_scaled_contract_basis_uses_the_multiplier(self):
        ends = bar_ends("2021-03-01 01:00", "2021-03-03 00:00")
        perp = {"1000PEPEUSDT": perp_frame(ends, 12.0, 5e6), "AUSDT": perp_frame(ends, 10.0, 5e6),
                "BUSDT": perp_frame(ends, 10.0, 5e6), "1000NOSPOTUSDT": perp_frame(ends, 3.0, 5e6)}
        spot = {"1000PEPEUSDT": spot_frame(ends, 0.0123),  # the spot pair PEPEUSDT, stored under the perp symbol
                "AUSDT": spot_frame(ends, 10.1), "BUSDT": spot_frame(ends, 9.9)}
        scale = {"1000PEPEUSDT": 1000.0, "AUSDT": 1.0, "BUSDT": 1.0}
        data = pbs.build_event_panels(perp, spot, spot_scale=scale)
        t = ts("2021-03-02 08:00")
        self.assertAlmostEqual(float(data["spot_close"].loc[t, "1000PEPEUSDT"]), 12.3)
        self.assertEqual(float(data["perp_close"].loc[t, "1000PEPEUSDT"]), 12.0)  # perp price is never rescaled
        w = pbs.basis_quintile_weights(data, {"quantiles": 3, "volume_filter_usd": 1e6}).loc[t]
        # y = ln(F/k) - ln(S): PEPE ln(12/1000)-ln(0.0123) = ln(12/12.3) = -0.0247 (lowest) < A -0.0099 < B +0.0100
        self.assertEqual(w["1000PEPEUSDT"], 0.5)
        self.assertEqual(w["AUSDT"], 0.0)
        self.assertEqual(w["BUSDT"], -0.5)
        self.assertTrue(np.isnan(w["1000NOSPOTUSDT"]))  # a scaled contract without a spot pair stays excluded
        unscaled = pbs.build_event_panels(perp, spot)
        y_bad = np.log(12.0) - np.log(0.0123)
        self.assertGreater(y_bad, 6.0)  # without k the basis would be ln(1000) too large
        self.assertAlmostEqual(float(np.log(unscaled["perp_close"].loc[t, "1000PEPEUSDT"])
                                     - np.log(unscaled["spot_close"].loc[t, "1000PEPEUSDT"])), y_bad)

    def test_panels_are_causal(self):
        rng = np.random.default_rng(3)
        ends = bar_ends("2021-03-01 01:00", "2021-03-08 00:00")
        perp = {n: perp_frame(ends, 10 + rng.random(len(ends)), rng.random(len(ends)) * 1e5) for n in ("AUSDT", "BUSDT")}
        spot = {n: spot_frame(ends, 10 + rng.random(len(ends))) for n in ("AUSDT", "BUSDT")}
        probes = [ts("2021-03-02 08:00"), ts("2021-03-04 16:00"), ts("2021-03-07 00:00")]
        for key in ("perp_close", "spot_close", "perp_dv24"):
            result = check_truncation(lambda d, key=key: pbs.build_event_panels(d["perp"], d["spot"])[key],
                                      {"perp": perp, "spot": spot}, probes)
            self.assertTrue(result["pass"], (key, result))


class SignalTests(unittest.TestCase):
    NAMES = ["A", "B", "C", "D", "E", "F", "G"]

    def setUp(self):
        self.t = "2021-03-05 08:00"

    def build(self, basis, dv=None, spot_nan=(), perp_nan=()):
        spot = {n: [100.0] for n in self.NAMES}
        perp = {n: [100.0 * np.exp(b)] for n, b in zip(self.NAMES, basis, strict=True)}
        volume = {n: [5e6] for n in self.NAMES}
        for n, v in (dv or {}).items():
            volume[n] = [v]
        for n in spot_nan:
            spot[n] = [np.nan]
        for n in perp_nan:
            perp[n] = [np.nan]
        return panels([self.t], perp, spot, volume)

    def test_quintile_assignment_and_weights(self):
        basis = [0.03, -0.02, 0.01, 0.05, -0.01, 0.0, 0.02]  # sorted: B E F C G A D
        w = pbs.basis_quintile_weights(self.build(basis), {"quantiles": 5, "volume_filter_usd": 1e6}).iloc[0]
        # n = 7, bucket = floor(i * 5 / 7) -> i=0,1 in bucket 0 (long), i=6 in bucket 4 (short)
        self.assertEqual({k: v for k, v in w.items() if v > 0}, {"B": 0.25, "E": 0.25})
        self.assertEqual({k: v for k, v in w.items() if v < 0}, {"D": -0.5})
        self.assertEqual(w[["A", "C", "F", "G"]].tolist(), [0.0, 0.0, 0.0, 0.0])
        self.assertAlmostEqual(float(w[w > 0].sum()), 0.5)
        self.assertAlmostEqual(float(w[w < 0].sum()), -0.5)

    def test_quantile_perturbations_and_too_few_names(self):
        basis = [0.03, -0.02, 0.01, 0.05, -0.01, 0.0, 0.02]
        data = self.build(basis)
        four = pbs.basis_quintile_weights(data, {"quantiles": 4, "volume_filter_usd": 1e6}).iloc[0]
        self.assertEqual(sorted(four[four > 0].index), ["B", "E"])  # i=0,1 -> floor(i*4/7)=0
        self.assertEqual(sorted(four[four < 0].index), ["D"])  # i=6 -> floor(6*4/7)=3; i=5 -> 2
        six = pbs.basis_quintile_weights(data, {"quantiles": 6, "volume_filter_usd": 1e6}).iloc[0]
        self.assertEqual(list(six[six > 0].index), ["B", "E"])  # i=1 -> floor(6/7)=0
        self.assertEqual(list(six[six < 0].index), ["D"])
        self.assertAlmostEqual(float(six[six > 0].sum()), 0.5)
        sparse = pbs.basis_quintile_weights(self.build(basis, dv={n: 0.0 for n in self.NAMES[3:]}),
                                            {"quantiles": 5, "volume_filter_usd": 1e6})
        self.assertTrue(sparse.iloc[0].isna().all())  # 3 eligible < 5 buckets: no signal

    def test_eligibility_volume_is_strict_and_missing_spot_or_perp_bar_excludes(self):
        basis = [0.03, -0.02, 0.01, 0.05, -0.01, 0.0, 0.02]
        data = self.build(basis, dv={"A": 1e6, "B": 999_999.0, "C": np.nan}, spot_nan=("D",), perp_nan=("E",))
        w = pbs.basis_quintile_weights(data, {"quantiles": 2, "volume_filter_usd": 1e6}).iloc[0]
        self.assertEqual(sorted(w.dropna().index), ["F", "G"])
        for name in ("A", "B", "C", "D", "E"):  # A: exactly at threshold, B: below, C: listed < 1 day (NaN), D/E no bar
            self.assertTrue(np.isnan(w[name]), name)
        lower = pbs.basis_quintile_weights(data, {"quantiles": 2, "volume_filter_usd": 999_999.0}).iloc[0]
        self.assertEqual(sorted(lower.dropna().index), ["A", "F", "G"])  # threshold is a perturbed parameter

    def test_only_settlement_rows_and_parameters_travel_with_the_weights(self):
        idx = ["2021-03-05 00:00", "2021-03-05 01:00", "2021-03-05 08:00", "2021-03-05 09:00", "2021-03-05 16:00"]
        data = panels(idx, {"A": [1.0] * 5, "B": [1.0] * 5}, {"A": [1.0] * 5, "B": [1.0] * 5},
                      {"A": [2e6] * 5, "B": [2e6] * 5})
        params = {**pbs.DEFAULT_PARAMS, "quantiles": 2, "entry_delay_hours": 1}
        w = pbs.basis_quintile_weights(data, params)
        self.assertEqual([t.hour for t in w.index], [0, 8, 16])
        self.assertEqual(w.attrs["params"]["entry_delay_hours"], 1)

    def test_signal_uses_only_data_up_to_t(self):
        rng = np.random.default_rng(11)
        ends = bar_ends("2021-03-01 01:00", "2021-03-12 00:00")
        names = [f"S{i}USDT" for i in range(9)]
        perp = {n: perp_frame(ends, 100 * np.exp(np.cumsum(rng.normal(0, 0.003, len(ends)))), 4e5) for n in names}
        spot = {n: spot_frame(ends, perp[n]["close"].to_numpy() * np.exp(rng.normal(0, 0.002, len(ends))))
                for n in names}
        data = pbs.build_event_panels(perp, spot)
        params = {**pbs.DEFAULT_PARAMS, "volume_filter_usd": 1e6, "quantiles": 4}
        full = pbs.basis_quintile_weights(data, params)
        self.assertGreater(full.notna().any(axis=1).sum(), 10)
        dates = list(full.dropna(how="all").index[::4])
        res = check_truncation(lambda d: pbs.basis_quintile_weights(d, params), data, dates)
        self.assertTrue(res["pass"], res)
        # a registered-gate style check as well, and a change after t never alters row t
        g1 = ss.g1_truncation(pbs.basis_quintile_weights, data, params, full, n_dates=8)
        self.assertTrue(g1["pass"], g1)
        t = full.dropna(how="all").index[10]
        altered = {k: v.copy() for k, v in data.items()}
        for v in altered.values():
            v.loc[v.index > t] = v.loc[v.index > t] * 1.7
        pd.testing.assert_series_equal(pbs.basis_quintile_weights(altered, params).loc[t], full.loc[t])


class AccountingTests(unittest.TestCase):
    ENDS = bar_ends("2021-03-01 01:00", "2021-03-03 00:00")

    def base_world(self):
        ends = self.ENDS
        perp = {"A": perp_frame(ends, 100.0), "B": perp_frame(ends, 50.0), "C": perp_frame(ends, 20.0)}
        spot = {n: spot_frame(ends, 1.0) for n in perp}
        stamps = [f"2021-03-0{d} {h:02d}:00" for d in (1, 2, 3) for h in (0, 8, 16)]
        funding = {"A": funding_frame(stamps, [0.001] * len(stamps)), "B": funding_frame(stamps, [0.002] * len(stamps)),
                   "C": funding_frame(stamps, [0.0] * len(stamps))}
        return perp, spot, funding

    @staticmethod
    def set_price(frame: pd.DataFrame, when: str, price: float):
        frame.loc[ts(when), "close"] = price

    def test_price_return_funding_sign_and_cost_of_one_period(self):
        perp, spot, funding = self.base_world()
        self.set_price(perp["A"], "2021-03-01 16:00", 102.0)
        self.set_price(perp["B"], "2021-03-01 16:00", 49.5)
        inputs = inputs_for(perp, spot, funding)
        w = weights_frame({"2021-03-01 08:00": {"A": 0.5, "B": -0.5}}, ["A", "B", "C"])
        book = pbs.build_book(w, inputs, None, 14.0)
        per = book.periods.iloc[0]
        self.assertAlmostEqual(per["price_pnl"], 0.5 * 0.02 + 0.5 * 0.01)
        # settlements in (08:00, 16:00]: only 16:00.  Long A pays 0.001, short B receives 0.002 (on 0.5 notional each)
        self.assertAlmostEqual(per["funding_pnl"], -0.5 * 0.001 + 0.5 * 0.002)
        self.assertAlmostEqual(per["gross"], 0.015 + 0.0005)
        self.assertAlmostEqual(per["turnover"], 1.0)
        self.assertAlmostEqual(per["cost"], 7e-4)  # 14 bps round trip = 7 bps per unit traded
        self.assertAlmostEqual(per["net"], 0.0155 - 7e-4)
        pos = book.positions.set_index("symbol")
        self.assertAlmostEqual(pos.loc["A", "funding_return"], -0.001)  # long pays when the rate is positive
        self.assertAlmostEqual(pos.loc["B", "funding_return"], -0.002)  # per unit LONG notional; the short earns +0.002
        self.assertAlmostEqual(pos.loc["B", "unit_return"], -0.01 - 0.002)
        self.assertEqual(pos.loc["A", "entry_time"], ts("2021-03-01 08:00"))
        self.assertEqual(pos.loc["A", "exit_time"], ts("2021-03-01 16:00"))

    def test_negative_rate_pays_longs_and_charges_shorts(self):
        perp, spot, funding = self.base_world()
        funding["A"] = funding_frame(["2021-03-01 16:00"], [-0.003])
        inputs = inputs_for(perp, spot, funding)
        long_book = pbs.build_book(weights_frame({"2021-03-01 08:00": {"A": 0.5}}, ["A"]), inputs, None, 0.0)
        short_book = pbs.build_book(weights_frame({"2021-03-01 08:00": {"A": -0.5}}, ["A"]), inputs, None, 0.0)
        self.assertAlmostEqual(long_book.periods["funding_pnl"].iloc[0], 0.5 * 0.003)
        self.assertAlmostEqual(short_book.periods["funding_pnl"].iloc[0], -0.5 * 0.003)

    def test_four_hour_funding_settlements_are_all_counted_and_boundaries_are_half_open(self):
        perp, spot, funding = self.base_world()
        funding["A"] = funding_frame(["2021-03-01 08:00", "2021-03-01 12:00", "2021-03-01 16:00", "2021-03-01 20:00"],
                                     [0.01, 0.001, 0.002, 0.5])
        panel = pbs.unit_return_panel(inputs_for(perp, spot, funding), pd.DatetimeIndex([ts("2021-03-01 08:00")]),
                                      dict(pbs.DEFAULT_PARAMS))
        j = panel["columns"].index("A")
        self.assertAlmostEqual(panel["funding_sum"][0, j], 0.003)  # 12:00 and 16:00; not 08:00 (entry) nor 20:00
        self.assertEqual(panel["funding_records"][0, j], 2)

    def test_overlapping_books_charge_turnover_on_the_difference_only(self):
        perp, spot, funding = self.base_world()
        inputs = inputs_for(perp, spot, funding)
        w = weights_frame({"2021-03-01 08:00": {"A": 0.5, "B": -0.5},
                           "2021-03-01 16:00": {"A": 0.5, "C": -0.5},  # A is rolled, B replaced by C
                           "2021-03-02 00:00": {}}, ["A", "B", "C"])
        book = pbs.build_book(w, inputs, None, 14.0)
        np.testing.assert_allclose(book.periods["turnover"], [1.0, 1.0, 1.0])
        np.testing.assert_allclose(book.periods["cost"], [7e-4] * 3)
        full_turn = weights_frame({"2021-03-01 08:00": {"A": 0.5, "B": -0.5}, "2021-03-01 16:00": {"C": 0.5, "A": -0.5}},
                                  ["A", "B", "C"])
        np.testing.assert_allclose(pbs.build_book(full_turn, inputs, None, 14.0).periods["turnover"], [1.0, 2.0])
        # a complete replacement of a 1.0-gross book costs one round trip: 2.0 turnover * 7 bps = 14 bps
        self.assertAlmostEqual(float(pbs.build_book(full_turn, inputs, None, 14.0).periods["cost"].iloc[1]), 14e-4)

    def test_entry_delay_variant_shifts_entry_exit_and_the_funding_window(self):
        perp, spot, funding = self.base_world()
        self.set_price(perp["A"], "2021-03-01 08:00", 90.0)  # signal-time close: not the entry price with a delay
        self.set_price(perp["A"], "2021-03-01 09:00", 100.0)
        self.set_price(perp["A"], "2021-03-01 17:00", 103.0)
        self.set_price(perp["A"], "2021-03-01 16:00", 111.0)
        funding["A"] = funding_frame(["2021-03-01 08:00", "2021-03-01 16:00", "2021-03-01 17:00"], [0.5, 0.001, 0.004])
        inputs = inputs_for(perp, spot, funding)
        w0 = weights_frame({"2021-03-01 08:00": {"A": 0.5}}, ["A"])
        w1 = weights_frame({"2021-03-01 08:00": {"A": 0.5}}, ["A"], entry_delay_hours=1)
        base = pbs.build_book(w0, inputs, None, 0.0)
        delayed = pbs.build_book(w1, inputs, None, 0.0)
        self.assertAlmostEqual(base.periods["price_pnl"].iloc[0], 0.5 * (111.0 / 90.0 - 1))
        self.assertAlmostEqual(base.periods["funding_pnl"].iloc[0], -0.5 * 0.001)  # (08:00, 16:00]
        self.assertAlmostEqual(delayed.periods["price_pnl"].iloc[0], 0.5 * 0.03)  # 09:00 -> 17:00
        self.assertAlmostEqual(delayed.periods["funding_pnl"].iloc[0], -0.5 * (0.001 + 0.004))  # (09:00, 17:00]
        self.assertEqual(delayed.positions["entry_time"].iloc[0], ts("2021-03-01 09:00"))
        self.assertEqual(delayed.positions["exit_time"].iloc[0], ts("2021-03-01 17:00"))
        # the weights themselves do not depend on the delay
        np.testing.assert_array_equal(w0.to_numpy(), w1.to_numpy())

    def test_delisted_contract_exits_at_its_last_close_and_flat_without_any_bar(self):
        perp, spot, funding = self.base_world()
        perp["D"] = perp_frame(self.ENDS[:12], 4.0)  # last bar ends 2021-03-01 12:00
        self.set_price(perp["D"], "2021-03-01 12:00", 5.0)
        perp["E"] = perp_frame(self.ENDS[:8], 7.0)  # last bar ends 08:00: no bar in (08:00, 16:00]
        spot["D"] = spot_frame(self.ENDS, 1.0)
        spot["E"] = spot_frame(self.ENDS, 1.0)
        inputs = inputs_for(perp, spot, funding)
        w = weights_frame({"2021-03-01 08:00": {"D": 0.25, "E": 0.25}}, ["D", "E"])
        book = pbs.build_book(w, inputs, None, 0.0)
        pos = book.positions.set_index("symbol")
        self.assertAlmostEqual(pos.loc["D", "price_return"], 0.25)
        self.assertAlmostEqual(pos.loc["E", "price_return"], 0.0)
        self.assertEqual(book.diagnostics["fallback_exit_prices"], 2)

    def test_position_without_entry_price_is_not_taken_and_not_charged(self):
        perp, spot, funding = self.base_world()
        inputs = inputs_for(perp, spot, funding)
        w = weights_frame({"2021-03-01 08:00": {"A": 0.25, "B": 0.25, "C": -0.5}}, ["A", "B", "C"], entry_delay_hours=1)
        inputs.data["perp_close"].loc[ts("2021-03-01 09:00"), "B"] = np.nan
        book = pbs.build_book(w, inputs, None, 14.0)
        self.assertEqual(book.diagnostics["skipped_no_entry_price"], 1)
        self.assertAlmostEqual(book.periods["turnover"].iloc[0], 0.75)
        self.assertEqual(sorted(book.positions["symbol"]), ["A", "C"])

    def test_daily_series_are_stamped_by_entry_day_and_incomplete_periods_are_dropped(self):
        perp, spot, funding = self.base_world()
        self.set_price(perp["A"], "2021-03-01 16:00", 102.0)
        self.set_price(perp["A"], "2021-03-02 00:00", 102.0)
        self.set_price(perp["A"], "2021-03-02 08:00", 102.0)
        inputs = inputs_for(perp, spot, funding, max_exit="2021-03-02 23:59:59")
        w = weights_frame({"2021-03-01 08:00": {"A": 0.5}, "2021-03-01 16:00": {"A": 0.5},
                           "2021-03-02 00:00": {"A": 0.5}, "2021-03-02 08:00": {"A": 0.5},
                           "2021-03-02 16:00": {"A": 0.5}, "2021-03-03 00:00": {"A": 0.5}}, ["A"])
        book = pbs.build_book(w, inputs, None, 14.0)
        self.assertEqual(len(book.periods), 4)  # 03-02 16:00 exits after max_exit; 03-03 00:00 has no exit bar
        detail = pbs.daily_detail(book)
        self.assertEqual([str(d.date()) for d in detail.index], ["2021-03-01", "2021-03-02"])
        self.assertAlmostEqual(detail["turnover"].iloc[0], 0.5)  # entered once on day 1, then rolled
        self.assertAlmostEqual(detail["turnover"].iloc[1], 0.0)
        self.assertAlmostEqual(detail["cost"].sum(), 0.5 * 7e-4)
        per = book.periods
        self.assertAlmostEqual(detail["gross"].iloc[0], float(per["gross"].iloc[:2].sum()))
        self.assertAlmostEqual(detail["gross"].iloc[1], float(per["gross"].iloc[2:].sum()))
        self.assertAlmostEqual(detail["net"].sum(), float(per["net"].sum()))
        # the account function used by evaluate_candidate_general is the same table
        pd.testing.assert_frame_equal(pbs.make_detail_fn(inputs)(w, None, 14.0), detail)

    def test_first_nonzero_book_starts_the_series(self):
        perp, spot, funding = self.base_world()
        inputs = inputs_for(perp, spot, funding)
        w = weights_frame({"2021-03-01 00:00": {}, "2021-03-01 08:00": {"A": 0.5}}, ["A"])
        w.iloc[0] = np.nan
        detail = pbs.daily_detail(pbs.build_book(w, inputs, None, 14.0))
        self.assertEqual(str(detail.index[0].date()), "2021-03-01")
        empty = pbs.daily_detail(pbs.build_book(weights_frame({"2021-03-01 08:00": {}}, ["A"]), inputs, None, 14.0))
        self.assertTrue(empty.empty)


class SyntheticWorld:
    """A universe whose low-basis contracts drift up and high-basis contracts drift down (planted edge)."""

    def __init__(self, n=14, days=70, edge=0.0, seed=5, start="2021-03-01 01:00"):
        rng = np.random.default_rng(seed)
        ends = pd.date_range(ts(start), periods=days * 24, freq="1h")
        self.perp, self.spot, self.funding = {}, {}, {}
        for i in range(n):
            name = f"S{i:02d}USDT"
            basis = (i - n / 2) * 0.002
            drift = -edge * basis
            steps = rng.normal(0.0, 0.004, len(ends)) + drift
            path = 100 * np.exp(np.cumsum(steps))
            self.perp[name] = perp_frame(ends, path, 5e5)
            self.spot[name] = spot_frame(ends, path * np.exp(-basis))
            stamps = [str(t) for t in pd.date_range(ends[0].normalize(), ends[-1], freq="8h")]
            self.funding[name] = funding_frame(stamps, list(rng.normal(0.0001, 0.0002, len(stamps))))
        self.inputs = pbs.BasisInputs(data=pbs.build_event_panels(self.perp, self.spot), perp=self.perp,
                                      funding=self.funding, max_exit=None)
        self.params = {**pbs.DEFAULT_PARAMS, "volume_filter_usd": 1e6}


class IntegrityAndDescriptiveTests(unittest.TestCase):
    def test_funding_integrity_requires_a_settlement_for_every_active_contract(self):
        ends = bar_ends("2021-03-01 01:00", "2021-03-08 00:00")
        perp = {"AUSDT": perp_frame(ends, 1.0), "BUSDT": perp_frame(ends, 1.0), "CUSDT": perp_frame(ends[:100], 1.0),
                "BUSDT#2": perp_frame(ends[50:], 1.0)}
        stamps = [str(t) for t in pd.date_range("2021-03-01", "2021-03-08", freq="8h", tz="UTC")]
        funding = {n: funding_frame(stamps, [0.0001] * len(stamps)) for n in ("AUSDT", "BUSDT", "CUSDT")}
        kwargs = {"required_last": ts("2021-03-08 00:00"), "window_start": ts("2021-03-01 00:00")}
        out = pbs.funding_integrity(perp, funding, **kwargs)
        self.assertEqual(out["active_symbols"], 3)  # A, B and the relisted B#2 (base BUSDT)
        self.assertEqual(out["last_settlement"]["AUSDT"], "2021-03-08 00:00:00+00:00")
        self.assertIn("CUSDT", out["ended_in_final_week"])  # ended earlier: listed, not failed
        funding["BUSDT"] = funding["BUSDT"].iloc[:-1]
        with self.assertRaises(pbs.PerpBasisError) as ctx:
            pbs.funding_integrity(perp, funding, **kwargs)
        self.assertIn("BUSDT", str(ctx.exception))
        del funding["AUSDT"]
        with self.assertRaises(pbs.PerpBasisError):
            pbs.funding_integrity(perp, funding, **kwargs)

    def test_zero_volume_bars_after_delisting_do_not_count_as_trading(self):
        ends = bar_ends("2021-03-01 01:00", "2021-03-08 00:00")
        dead = perp_frame(ends, 1.0)
        dead.loc[dead.index[100]:, "quote_volume"] = 0.0  # archive keeps flat zero-volume bars after a delisting
        stamps = [str(t) for t in pd.date_range("2021-03-01", "2021-03-03", freq="8h", tz="UTC")]
        funding = {"DUSDT": funding_frame(stamps, [0.0001] * len(stamps))}  # funding stopped with trading
        kwargs = {"required_last": ts("2021-03-08 00:00"), "window_start": ts("2021-03-01 00:00")}
        out = pbs.funding_integrity({"DUSDT": dead}, funding, **kwargs)
        self.assertEqual(out["active_symbols"], 0)
        self.assertIn("DUSDT", out["ended_in_final_week"])

    def test_non_finite_funding_is_an_error_never_zero(self):
        bad = funding_frame(["2021-03-01 16:00"], [np.nan])
        with self.assertRaises(pbs.PerpBasisError):
            pbs.validate_funding({"A": bad})
        ends = bar_ends("2021-03-01 01:00", "2021-03-03 00:00")
        perp, spot = {"A": perp_frame(ends, 1.0)}, {"A": spot_frame(ends, 1.0)}
        inputs = inputs_for(perp, spot, {"A": bad})
        with self.assertRaises(pbs.PerpBasisError):
            pbs.unit_return_panel(inputs, pd.DatetimeIndex([ts("2021-03-01 08:00")]), dict(pbs.DEFAULT_PARAMS))
        with self.assertRaises(pbs.PerpBasisError):
            pbs.make_inputs({"perp": perp, "spot": spot, "funding": {"A": bad}})

    def test_extreme_basis_counts_and_ranking(self):
        idx = ["2021-03-05 00:00", "2021-03-05 08:00", "2021-03-05 16:00", "2021-03-06 00:00"]
        spot = {n: [100.0] * 4 for n in ("A", "B", "C")}
        perp = {"A": [100.0, 120.0, 100.0, 80.0],   # ln(1.2) = 0.18 and ln(0.8) = -0.22: 2 of 4 beyond 10%
                "B": [100.0, 100.0, 111.0, np.nan],  # ln(1.11) = 0.104: 1 of 3 finite
                "C": [100.0, 100.0, 100.0, 100.0]}
        vol = {"A": [2e6, 2e6, 2e6, 0.0], "B": [2e6] * 4, "C": [2e6] * 4}
        data = panels(idx, perp, spot, vol)
        stats = pbs.basis_extreme_stats(data, {"volume_filter_usd": 1e6})
        by = {r["symbol"]: r for r in stats["per_symbol"]}
        self.assertEqual((by["A"]["n_extreme"], by["A"]["n_settlements"]), (2, 4))
        self.assertEqual(by["A"]["n_extreme_eligible"], 1)  # the 80/100 event has no eligible volume
        self.assertEqual((by["B"]["n_extreme"], by["B"]["n_settlements"]), (1, 3))
        self.assertEqual(by["C"]["n_extreme"], 0)
        self.assertEqual([r["symbol"] for r in stats["top_by_share"]], ["A", "B", "C"])
        self.assertAlmostEqual(by["A"]["share_extreme"], 0.5)
        self.assertEqual(stats["n_extreme_total"], 3)
        self.assertEqual(len(pbs.basis_extreme_stats(data, {"volume_filter_usd": 1e6}, top=2)["top_by_share"]), 2)


class NullAndPlumbingTests(unittest.TestCase):
    def test_null_is_reproducible_and_observed_matches_the_account(self):
        world = SyntheticWorld(edge=0.0)
        weights = pbs.basis_quintile_weights(world.inputs.data, world.params)
        detail = pbs.daily_detail(pbs.build_book(weights, world.inputs, None, 14.0))
        lo, hi = detail.index[0], detail.index[-1]
        null_fn = pbs.make_null_fn(world.inputs)
        a = null_fn(weights, lo, hi, n_draws=120, seed=1)
        b = null_fn(weights, lo, hi, n_draws=120, seed=999)  # the registered seed 20261012 is fixed, the argument unused
        c = pbs.allocation_null(weights, world.inputs, lo, hi, n_draws=120, seed=pbs.NULL_SEED)
        self.assertEqual(a["p"], c["p"])
        self.assertEqual(a["p"], b["p"])
        self.assertEqual(a["null_mean"], b["null_mean"])
        self.assertAlmostEqual(a["observed_mean_daily_gross"], float(detail["gross"].mean()), places=12)
        self.assertEqual(a["null_type"], "allocation")
        self.assertEqual(a["n_null"], 120)

    def test_planted_edge_is_detected_and_random_books_are_not(self):
        edge_world = SyntheticWorld(edge=0.9)
        w = pbs.basis_quintile_weights(edge_world.inputs.data, edge_world.params)
        d = pbs.daily_detail(pbs.build_book(w, edge_world.inputs, None, 14.0))
        res = pbs.allocation_null(w, edge_world.inputs, d.index[0], d.index[-1], n_draws=199)
        self.assertEqual(res["p"], 1 / 200)
        self.assertTrue(res["pass"])
        flat = SyntheticWorld(edge=0.0, seed=9)
        w0 = pbs.basis_quintile_weights(flat.inputs.data, flat.params)
        d0 = pbs.daily_detail(pbs.build_book(w0, flat.inputs, None, 14.0))
        res0 = pbs.allocation_null(w0, flat.inputs, d0.index[0], d0.index[-1], n_draws=199)
        self.assertGreater(res0["p"], 0.05)

    def test_null_draws_have_the_real_leg_sizes(self):
        world = SyntheticWorld(edge=0.0)
        weights = pbs.basis_quintile_weights(world.inputs.data, world.params)
        row = weights.dropna(how="all").iloc[5]
        self.assertAlmostEqual(float(row[row > 0].sum()), 0.5)
        self.assertAlmostEqual(float(row[row < 0].sum()), -0.5)

    def test_candidate_spec_matches_the_registration(self):
        spec = pbs.candidate_spec(ROUND_CFG)
        self.assertEqual(spec["id"], pbs.CANDIDATE_ID)
        self.assertEqual(spec["null"], "allocation")
        self.assertEqual(spec["perturb"], {"quantiles": [4, 6], "volume_filter_usd": [800000, 1200000],
                                           "entry_delay_hours": [1]})
        variants = ss.perturbation_param_sets(spec)
        self.assertEqual(len(variants), 5)
        self.assertEqual([v["entry_delay_hours"] for v in variants], [0, 0, 0, 0, 1])
        self.assertEqual(spec["params"]["quantiles"], 5)
        self.assertEqual(spec["params"]["volume_filter_usd"], 1_000_000)
        self.assertEqual(spec["params"]["hold_hours"], 8)
        self.assertEqual(spec["development"], ["2020-01-01", "2023-07-01"])
        self.assertEqual(spec["validation"], ["2023-07-02", "2026-09-30"])
        self.assertEqual(pbs.SETTLEMENT_HOURS, (0, 8, 16))
        self.assertEqual(pbs.NULL_SEED, 20261012)
        self.assertEqual(pbs.N_NULL_DRAWS, 999)
        self.assertEqual(pbs.COST_BPS_ROUND_TRIP, 14.0)  # protocol: 5 bps fee + 2 bps slippage per side
        self.assertIn("14 bps", PROTOCOL["costs"]["fees"])

    def test_cumulative_dsr_uses_null_consistent_rule_and_n(self):
        rng = np.random.default_rng(0)
        net = pd.Series(rng.normal(0.002, 0.01, 800))
        res = pbs.apply_cumulative_dsr({"gates": {}, "_dev_net": net}, 10)["gates"]["G5"]
        self.assertEqual(res["n_trials"], 10)
        more = pbs.apply_cumulative_dsr({"gates": {}, "_dev_net": net}, 40)["gates"]["G5"]
        self.assertGreater(more["sr0_daily"], res["sr0_daily"])
        flat = pbs.apply_cumulative_dsr({"gates": {}, "_dev_net": pd.Series([0.0] * 10)}, 10)["gates"]["G5"]
        self.assertFalse(flat["pass"])

    def test_end_to_end_through_the_shared_gate_harness(self):
        world = SyntheticWorld(edge=0.9, days=90)
        spec = pbs.candidate_spec(ROUND_CFG)
        reference = pd.Series(np.random.default_rng(2).normal(0, 0.01, 200),
                              index=pd.date_range("2021-03-01", periods=200, freq="D", tz="UTC"))
        result = r2.evaluate_candidate_general(
            spec, world.inputs.data, None, validation_window=["2021-04-15", "2021-06-30"], crypto_reference=reference,
            spy_returns=None, cost_bps=pbs.COST_BPS_ROUND_TRIP, periods_per_year=pbs.PERIODS_PER_YEAR,
            fn=pbs.basis_quintile_weights, detail_fn=pbs.make_detail_fn(world.inputs),
            null_fn=pbs.make_null_fn(world.inputs), g8_mode="crypto_only", n_draws=99, n_truncation_dates=5,
            seed=ss.SEED)
        self.assertEqual(result["periods_per_year"], 365)
        self.assertTrue(result["gates"]["G1"]["pass"])
        variants = result["gates"]["G6"]["variants"]
        self.assertEqual(len(variants), 5)
        self.assertTrue(all(v["days"] > 0 for v in variants))
        self.assertIsNotNone(variants[-1]["sharpe"])  # the 1h entry-delay variant ran through the same account
        self.assertEqual(result["gates"]["G4"]["null_type"], "allocation")
        pbs.apply_cumulative_dsr(result, 10)
        passed, first_fail = ss.verdict(result)
        self.assertEqual(passed, first_fail is None)
        rec = ss.ledger_record(result, 1)
        self.assertEqual(rec["round"], 1)
        self.assertEqual(rec["id"], pbs.CANDIDATE_ID)


if __name__ == "__main__":
    unittest.main()
