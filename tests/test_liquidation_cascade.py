"""Liquidation-cascade reversal (strategy-search-v3 round 2): event detection, OI as-of lookup, position state,
accounting, event null, leverage book and plumbing.  Synthetic data only; no network."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab import leverage_sim as lev
from orderflow_edge_lab import liquidation_cascade as lc
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab.truncation_check import check_truncation

ROOT = Path(__file__).resolve().parents[1]
ROUND_CFG = json.loads((ROOT / "config" / "strategy_search_v3_round2.json").read_text(encoding="utf-8"))
PROTOCOL = json.loads((ROOT / "config" / "strategy_search_v3_leveraged.json").read_text(encoding="utf-8"))
START = "2021-03-01 01:00"


def ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def flat_data(names: list[str], n: int = 200, start: str = START) -> dict[str, pd.DataFrame]:
    idx = pd.date_range(ts(start), periods=n, freq="1h")
    return {"close": pd.DataFrame(100.0, index=idx, columns=names),
            "volume": pd.DataFrame(1e6, index=idx, columns=names),
            "oi": pd.DataFrame(1000.0, index=idx, columns=names),
            "oi_age": pd.DataFrame(5.0, index=idx, columns=names)}


def spike(data: dict[str, pd.DataFrame], name: str, when: str, r: float = -0.06, oi: float = -0.06) -> None:
    """A one-bar excursion: the close and the open interest at ``when`` differ from the flat 100 / 1000 by r / oi."""
    data["close"].loc[ts(when), name] = 100.0 * (1.0 + r)
    data["oi"].loc[ts(when), name] = 1000.0 * (1.0 + oi)


def inputs_for(data, funding=None, max_exit=None, mark=None) -> lc.CascadeInputs:
    cap = None if max_exit is None else ts(max_exit)
    return lc.CascadeInputs(data=data, funding=funding or {}, max_exit=cap, mark=mark or {})


def funding_frame(stamps: list[str], rates: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"rate": rates, "interval_hours": 8.0}, index=pd.DatetimeIndex([ts(s) for s in stamps]))


def entries(weights: pd.DataFrame) -> list[tuple[str, str, float]]:
    out = []
    for t, row in weights.dropna(how="all").iterrows():
        for name, w in row.items():
            if w != 0.0:
                out.append((str(t)[:16], name, float(w)))
    return out


class RandomWorld:
    """Random-walk perps with injected crashes (price and OI fall together) followed by a rebound (a planted reversal)."""

    def __init__(self, n=14, days=75, seed=3, start="2023-04-01 01:00", rebound=0.04, crashes_per_100h=1.0):
        rng = np.random.default_rng(seed)
        ends = pd.date_range(ts(start), periods=days * 24, freq="1h")
        self.perp, self.oi, self.funding, self.mark = {}, {}, {}, {}
        for i in range(n):
            name = f"S{i:02d}USDT"
            steps = rng.normal(0.0, 0.006, len(ends))
            oi_steps = rng.normal(0.0, 0.004, len(ends))
            for k in np.flatnonzero(rng.random(len(ends) - 40) < crashes_per_100h / 100 / n * 3)[:200]:
                steps[k:k + 3] += -0.025
                oi_steps[k:k + 3] += -0.04
                steps[k + 3:k + 15] += rebound / 12
            path = 100.0 * np.exp(np.cumsum(steps))
            oi_path = 1000.0 * np.exp(np.cumsum(oi_steps))
            self.perp[name] = pd.DataFrame({"close": path, "quote_volume": 5e6, "high": path * 1.006,
                                            "low": path * 0.994}, index=ends)
            five = pd.date_range(ends[0] - pd.Timedelta(hours=2), ends[-1], freq="5min")
            hours_from_start = (five - ends[0]).total_seconds() / 3600.0
            interp = np.interp(hours_from_start, np.arange(len(ends)), oi_path)
            self.oi[name] = pd.Series(interp, index=five, name="sum_open_interest")
            stamps = pd.date_range(ends[0].normalize(), ends[-1], freq="8h")
            self.funding[name] = pd.DataFrame({"rate": rng.normal(0.0001, 0.0002, len(stamps)), "interval_hours": 8.0},
                                              index=stamps)
            self.mark[name] = pd.DataFrame({"high": path * 1.004, "low": path * 0.996}, index=ends)
        self.perp_hl = {n: f[["high", "low"]] for n, f in self.perp.items()}
        self.universe = {"perp": {n: f[["close", "quote_volume"]] for n, f in self.perp.items()}, "oi": self.oi,
                         "funding": self.funding, "mark": self.mark, "perp_hl": self.perp_hl}
        self.inputs = lc.make_inputs(self.universe)
        self.params = dict(lc.DEFAULT_PARAMS)


class OpenInterestLookupTests(unittest.TestCase):
    def series(self):
        stamps = ["2021-03-01 11:50", "2021-03-01 11:55", "2021-03-01 12:00", "2021-03-01 12:05"]
        return pd.Series([1.0, 2.0, 3.0, 4.0], index=pd.DatetimeIndex([ts(s) for s in stamps]))

    def test_last_record_known_at_x_never_a_future_one(self):
        grid = pd.DatetimeIndex([ts("2021-03-01 12:00")])
        value, age = lc.asof_values(self.series(), grid, lag_minutes=5)
        self.assertEqual((float(value[0]), float(age[0])), (2.0, 5.0))  # the 12:00 record may describe 12:05
        value0, age0 = lc.asof_values(self.series(), grid, lag_minutes=0)
        self.assertEqual((float(value0[0]), float(age0[0])), (3.0, 0.0))  # literal "stamp at or before x"
        for lag in (0, 5):
            v, _ = lc.asof_values(self.series(), grid, lag_minutes=lag)
            self.assertNotEqual(float(v[0]), 4.0)  # the 12:05 record is never read at 12:00
        self.assertEqual(lc.OI_SNAPSHOT_LAG_MINUTES, 5)

    def test_before_the_first_record_is_nan_and_gaps_keep_the_old_value_with_its_age(self):
        grid = pd.DatetimeIndex([ts("2021-03-01 11:00"), ts("2021-03-01 14:00")])
        value, age = lc.asof_values(self.series(), grid, lag_minutes=5)
        self.assertTrue(np.isnan(value[0]) and np.isnan(age[0]))
        self.assertEqual(float(value[1]), 4.0)
        self.assertEqual(float(age[1]), 115.0)  # stale by almost two hours: visible, not hidden
        v, a = lc.asof_values(pd.Series(dtype=float), grid)
        self.assertTrue(np.isnan(v).all() and np.isnan(a).all())

    def test_unsorted_series_is_refused(self):
        bad = self.series().iloc[::-1]
        with self.assertRaises(lc.CascadeError):
            lc.asof_values(bad, pd.DatetimeIndex([ts("2021-03-01 12:00")]))

    def test_panels_are_truncation_invariant_and_ignore_later_records(self):
        world = RandomWorld(n=3, days=6)
        probes = [ts("2023-04-02 12:00"), ts("2023-04-04 03:00"), ts("2023-04-05 20:00")]
        for key in ("close", "oi"):
            res = check_truncation(lambda d, key=key: lc.build_panels(d["perp"], d["oi"])[key],
                                   {"perp": world.perp, "oi": world.oi}, probes)
            self.assertTrue(res["pass"], (key, res))
        name = "S00USDT"
        altered = {k: v.copy() for k, v in world.oi.items()}
        altered[name].loc[altered[name].index > ts("2023-04-03 12:00")] *= 5.0
        a = lc.build_panels(world.perp, world.oi)["oi"][name]
        b = lc.build_panels(world.perp, altered)["oi"][name]
        pd.testing.assert_series_equal(a.loc[:ts("2023-04-03 12:00")], b.loc[:ts("2023-04-03 12:00")])
        self.assertFalse(a.loc[ts("2023-04-03 14:00")] == b.loc[ts("2023-04-03 14:00")])

    def test_staleness_is_reported_per_contract(self):
        world = RandomWorld(n=2, days=4)
        oi = dict(world.oi)
        oi["S01USDT"] = oi["S01USDT"].loc[oi["S01USDT"].index < ts("2023-04-02 00:00")]  # the OI feed stops
        stats = lc.oi_staleness(world.perp, oi)
        self.assertEqual(stats["S00USDT"]["hours_oi_older_than_60min"], 0)
        self.assertGreater(stats["S01USDT"]["hours_oi_older_than_60min"], 40)
        self.assertGreater(stats["S01USDT"]["max_oi_age_hours"], 40.0)


class EventTests(unittest.TestCase):
    def test_exact_thresholds_are_events_on_both_sides(self):
        data = flat_data(["A", "B", "C", "D", "E", "F"])
        spike(data, "A", "2021-03-02 00:00", r=-0.05, oi=-0.05)    # exactly on both thresholds: long
        spike(data, "B", "2021-03-02 00:00", r=+0.05, oi=-0.05)    # exactly +5% with OI -5%: short
        spike(data, "C", "2021-03-02 00:00", r=-0.0499, oi=-0.05)  # price just inside
        spike(data, "D", "2021-03-02 00:00", r=-0.05, oi=-0.0499)  # OI just inside
        spike(data, "E", "2021-03-02 00:00", r=+0.06, oi=+0.04)    # big move but OI rose: not liquidations
        spike(data, "F", "2021-03-02 00:00", r=-0.06, oi=-0.06)    # a regular long
        weights = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        self.assertEqual(entries(weights), [("2021-03-02 00:00", "A", 0.1), ("2021-03-02 00:00", "B", -0.1),
                                            ("2021-03-02 00:00", "F", 0.1)])
        self.assertEqual(weights.attrs["params"], lc.DEFAULT_PARAMS)

    def test_ratio_never_defined_on_zero_open_interest_or_missing_data(self):
        data = flat_data(["A", "B", "C"])
        data["oi"].loc[ts("2021-03-01 20:00"), "A"] = 0.0     # OI_(t-4h) = 0 -> oi4 undefined at t = 24:00
        spike(data, "A", "2021-03-02 00:00")
        spike(data, "B", "2021-03-02 00:00")
        data["oi"].loc[ts("2021-03-02 00:00"), "C"] = np.nan  # no OI known -> no event
        spike(data, "C", "2021-03-02 00:00", oi=0.0)
        data["oi"].loc[ts("2021-03-02 00:00"), "C"] = np.nan
        self.assertEqual([e[1] for e in entries(lc.cascade_weights(data, lc.DEFAULT_PARAMS))], ["B"])

    def test_perturbed_parameters_change_the_rule(self):
        data = flat_data(["A", "B"])
        spike(data, "A", "2021-03-02 00:00", r=-0.045, oi=-0.045)
        spike(data, "B", "2021-03-02 00:00", r=-0.055, oi=-0.055)
        names = lambda **kw: [e[1] for e in entries(lc.cascade_weights(data, {**lc.DEFAULT_PARAMS, **kw}))]  # noqa: E731
        self.assertEqual(names(), ["B"])
        self.assertEqual(names(price_threshold=0.04, oi_threshold=0.04), ["A", "B"])
        self.assertEqual(names(price_threshold=0.06, oi_threshold=0.06), [])
        self.assertEqual(names(price_threshold=0.04), ["B"])   # A fails the 5% OI condition
        self.assertEqual(names(oi_threshold=0.04, price_threshold=0.06), [])
        self.assertEqual(names(oi_threshold=0.04), ["A", "B"][1:])  # A fails the 5% price condition

    def test_lookback_hours_sets_both_windows(self):
        data = flat_data(["A"])
        t = "2021-03-02 00:00"
        data["close"].loc[ts("2021-03-01 20:00"), "A"] = 100.0   # t-4h
        data["close"].loc[ts("2021-03-01 21:00"), "A"] = 94.5    # t-3h
        data["close"].loc[ts(t), "A"] = 94.0
        data["oi"].loc[ts("2021-03-01 20:00"), "A"] = 1000.0
        data["oi"].loc[ts("2021-03-01 21:00"), "A"] = 940.0
        data["oi"].loc[ts(t), "A"] = 940.0
        ev4 = lc.event_matrices(data, lc.DEFAULT_PARAMS)
        ev3 = lc.event_matrices(data, {**lc.DEFAULT_PARAMS, "lookback_hours": 3})
        ev5 = lc.event_matrices(data, {**lc.DEFAULT_PARAMS, "lookback_hours": 5})
        row = data["close"].index.get_loc(ts(t))
        self.assertAlmostEqual(ev4["r4"][row, 0], 94.0 / 100.0 - 1.0)
        self.assertTrue(ev4["long"][row, 0])
        self.assertFalse(ev3["long"][row, 0])  # r over 3h is only -0.5% and oi4 over 3h is 0
        self.assertAlmostEqual(ev3["r4"][row, 0], 94.0 / 94.5 - 1.0)
        self.assertTrue(ev5["long"][row, 0])   # 5h ago: 100 and 1000 as well
        with self.assertRaises(lc.CascadeError):
            lc.event_matrices(data, {**lc.DEFAULT_PARAMS, "lookback_hours": 0})


class PositionStateTests(unittest.TestCase):
    def test_one_position_per_contract_events_while_in_position_are_ignored(self):
        data = flat_data(["A", "B"], n=120)
        spike(data, "A", "2021-03-02 00:00")
        spike(data, "A", "2021-03-02 10:00")   # inside the 24h hold: ignored
        spike(data, "B", "2021-03-02 10:00")   # another contract is unaffected
        spike(data, "A", "2021-03-03 00:00")   # exactly at the exit close: the contract is free again
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        self.assertEqual(entries(w), [("2021-03-02 00:00", "A", 0.1), ("2021-03-02 10:00", "B", 0.1),
                                      ("2021-03-03 00:00", "A", 0.1)])
        short_hold = lc.cascade_weights(data, {**lc.DEFAULT_PARAMS, "hold_hours": 8})
        self.assertEqual([e[:2] for e in entries(short_hold)],
                         [("2021-03-02 00:00", "A"), ("2021-03-02 10:00", "A"), ("2021-03-02 10:00", "B"),
                          ("2021-03-03 00:00", "A")])  # a 8h hold has expired by 10:00

    def test_concurrency_cap_takes_the_largest_moves_and_ties_by_column_order(self):
        names = [f"C{i:02d}" for i in range(13)]
        data = flat_data(names, n=120)
        t = "2021-03-02 00:00"
        for i, name in enumerate(names[:12]):
            spike(data, name, t, r=-0.07 if i == 11 else -0.06, oi=-0.10)  # C11 is the largest, C00..C10 tie
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        taken = [e[1] for e in entries(w)]
        self.assertEqual(taken, ["C00", "C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C11"])
        spike(data, "C12", "2021-03-02 05:00")                      # 10 positions open: capacity is zero
        spike(data, "C12", "2021-03-03 00:00")                      # the exits free capacity at the same close
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        self.assertEqual([e for e in entries(w) if e[1] == "C12"], [("2021-03-03 00:00", "C12", 0.1)])
        self.assertEqual(lc.MAX_CONCURRENT, 10)

    def test_direction_and_fixed_ten_percent_notional(self):
        data = flat_data(["A", "B"])
        spike(data, "A", "2021-03-02 00:00", r=-0.06)
        spike(data, "B", "2021-03-02 00:00", r=+0.06)
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        self.assertEqual(float(w.loc[ts("2021-03-02 00:00"), "A"]), 0.1)    # the move is faded: long after a drop
        self.assertEqual(float(w.loc[ts("2021-03-02 00:00"), "B"]), -0.1)   # short after a spike
        self.assertTrue(w.drop(index=ts("2021-03-02 00:00")).isna().all().all())  # no decision elsewhere

    def test_rows_without_a_decision_are_nan_so_truncation_checks_probe_real_entries(self):
        data = flat_data(["A", "B"])
        spike(data, "A", "2021-03-02 00:00")
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        self.assertEqual(list(w.dropna(how="all").index), [ts("2021-03-02 00:00")])
        self.assertEqual(float(w.loc[ts("2021-03-02 00:00"), "B"]), 0.0)

    def test_state_machine_is_causal_on_a_random_world(self):
        world = RandomWorld()
        data = world.inputs.data
        full = lc.cascade_weights(data, world.params)
        self.assertGreater(full.dropna(how="all").shape[0], 40)
        g1 = ss.g1_truncation(lc.cascade_weights, data, world.params, full, n_dates=30)
        self.assertTrue(g1["pass"], g1)
        self.assertTrue(g1["decision_date_diagnostic"]["pass"], g1)
        dates = list(full.dropna(how="all").index[::3])
        res = check_truncation(lambda d: lc.cascade_weights(d, world.params), data, dates)
        self.assertTrue(res["pass"], res)
        # data after t never changes the decisions up to and including t
        t = full.dropna(how="all").index[len(dates) // 2]
        altered = {k: v.copy() for k, v in data.items()}
        for frame in altered.values():
            frame.loc[frame.index > t] *= 1.7
        again = lc.cascade_weights(altered, world.params)
        pd.testing.assert_frame_equal(full.loc[:t], again.loc[:t])


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.data = flat_data(["A", "B"], n=160)
        spike(self.data, "A", "2021-03-02 00:00", r=-0.06)   # long, enters at 94, exits at 100 at 03-03 00:00
        spike(self.data, "B", "2021-03-02 00:00", r=+0.06)   # short, enters at 106, exits at 100
        self.funding = {"A": funding_frame(["2021-03-02 00:00", "2021-03-02 08:00", "2021-03-02 16:00",
                                            "2021-03-03 00:00", "2021-03-03 08:00"],
                                           [0.5, 0.001, 0.002, 0.004, 0.9]),
                        "B": funding_frame(["2021-03-02 08:00", "2021-03-03 00:00"], [0.001, 0.002])}
        self.inputs = inputs_for(self.data, self.funding)
        self.weights = lc.cascade_weights(self.data, lc.DEFAULT_PARAMS)

    def trades(self, cost_bps=lc.COST_BPS_ROUND_TRIP):
        return lc.build_trades(self.weights, self.inputs, None, cost_bps)

    def test_price_return_and_funding_sign_over_entry_exclusive_exit_inclusive(self):
        t = self.trades().set_index("symbol")
        a, b = t.loc["A"], t.loc["B"]
        self.assertAlmostEqual(a["price_return"], 100.0 / 94.0 - 1.0)
        self.assertAlmostEqual(a["funding_return"], -(0.001 + 0.002 + 0.004))  # settlement AT the entry and after the exit excluded
        self.assertAlmostEqual(a["unit_return"], a["price_return"] + a["funding_return"])
        self.assertAlmostEqual(a["trade_gross"], a["unit_return"])           # long: longs pay positive funding
        self.assertAlmostEqual(a["funding_pnl"], 0.1 * -(0.007))
        self.assertAlmostEqual(b["price_return"], 100.0 / 106.0 - 1.0)
        self.assertAlmostEqual(b["funding_return"], -(0.001 + 0.002))
        self.assertAlmostEqual(b["trade_gross"], -(b["price_return"] - 0.003))   # short earns the funding
        self.assertAlmostEqual(b["funding_pnl"], 0.1 * 0.003)
        self.assertGreater(b["funding_pnl"], 0.0)
        self.assertAlmostEqual(b["price_pnl"], -0.1 * (100.0 / 106.0 - 1.0))
        self.assertEqual(a["entry_time"], ts("2021-03-02 00:00"))
        self.assertEqual(a["exit_time"], ts("2021-03-03 00:00"))

    def test_fourteen_bps_round_trip_per_trade_on_the_notional(self):
        t = self.trades()
        for _, tr in t.iterrows():
            self.assertAlmostEqual(tr["cost"], 0.1 * 14e-4)
            self.assertAlmostEqual(tr["net"], tr["gross"] - 0.1 * 14e-4)
            self.assertAlmostEqual(tr["turnover"], 0.2)
            self.assertAlmostEqual(tr["cost"], tr["turnover"] * lc.COST_BPS_ROUND_TRIP / 2.0 / 1e4)
        self.assertAlmostEqual(self.trades(cost_bps=20.0)["cost"].iloc[0], 0.1 * 20e-4)
        self.assertAlmostEqual(self.trades(cost_bps=0.0)["net"].iloc[0], self.trades(cost_bps=0.0)["gross"].iloc[0])

    def test_daily_returns_are_stamped_by_the_exit_day_and_zero_filled(self):
        data = flat_data(["A", "B", "C"], n=200)
        spike(data, "A", "2021-03-01 20:00")   # exits 03-02 20:00
        spike(data, "B", "2021-03-02 00:00")   # exits 03-03 00:00 -> belongs to the new day 03-03
        spike(data, "C", "2021-03-04 12:00")   # exits 03-05 12:00; nothing exits on 03-04
        inputs = inputs_for(data)
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        trades = lc.build_trades(w, inputs, None, 14.0)
        daily = lc.daily_detail(trades)
        self.assertEqual([str(d.date()) for d in daily.index], ["2021-03-02", "2021-03-03", "2021-03-04", "2021-03-05"])
        gross_trade = 0.1 * (100.0 / 94.0 - 1.0)
        np.testing.assert_allclose(daily["gross"].to_numpy(), [gross_trade, gross_trade, 0.0, gross_trade])
        np.testing.assert_allclose(daily["turnover"].to_numpy(), [0.2, 0.2, 0.0, 0.2])
        np.testing.assert_allclose(daily["net"].to_numpy(), daily["gross"].to_numpy() - daily["cost"].to_numpy())
        self.assertAlmostEqual(float(daily["cost"].sum()), 3 * 0.1 * 14e-4)
        self.assertEqual(float(daily.loc[ts("2021-03-04"), "gross"]), 0.0)

    def test_hold_hours_perturbation_moves_the_exit(self):
        w = lc.cascade_weights(self.data, {**lc.DEFAULT_PARAMS, "hold_hours": 19})
        t = lc.build_trades(w, self.inputs, None, 14.0).set_index("symbol")
        self.assertEqual(t.loc["A", "exit_time"], ts("2021-03-02 19:00"))
        self.assertAlmostEqual(t.loc["A", "funding_return"], -(0.001 + 0.002))  # the 24:00 settlement is after the exit

    def test_exit_after_max_exit_or_beyond_the_data_is_not_taken(self):
        capped = inputs_for(self.data, self.funding, max_exit="2021-03-02 23:00")
        t = lc.build_trades(self.weights, capped, None, 14.0)
        self.assertTrue(t.empty)
        self.assertEqual(t.attrs["diagnostics"], {"entries": 2, "dropped_unusable_exit": 2})
        data = flat_data(["A"], n=40)
        spike(data, "A", "2021-03-02 08:00")   # only 12h of data left after the entry
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        self.assertTrue(lc.build_trades(w, inputs_for(data), None, 14.0).empty)

    def test_exit_price_falls_back_to_the_last_close_when_the_contract_stops_trading(self):
        data = flat_data(["A", "B"], n=160)
        spike(data, "A", "2021-03-02 00:00")
        data["close"].loc[ts("2021-03-02 10:00"):, "A"] = np.nan  # delisted at 10:00
        data["close"].loc[ts("2021-03-02 09:00"), "A"] = 97.0
        spike(data, "B", "2021-03-02 00:00")
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        t = lc.build_trades(w, inputs_for(data), None, 14.0).set_index("symbol")
        self.assertAlmostEqual(t.loc["A", "exit_price"], 97.0)
        self.assertAlmostEqual(t.loc["A", "price_return"], 97.0 / 94.0 - 1.0)
        self.assertAlmostEqual(t.loc["B", "price_return"], 100.0 / 94.0 - 1.0)

    def test_non_finite_funding_is_an_error_never_zero(self):
        bad = {"A": funding_frame(["2021-03-02 08:00"], [np.nan])}
        with self.assertRaises(lc.CascadeError):
            lc.build_trades(self.weights, inputs_for(self.data, bad), None, 14.0)
        with self.assertRaises(Exception):
            lc.make_inputs({"perp": {"A": pd.DataFrame({"close": [1.0], "quote_volume": [1.0]},
                                                       index=[ts("2021-03-01 01:00")])}, "oi": {}, "funding": bad})

    def test_unknown_columns_or_rows_are_errors(self):
        w = self.weights.copy()
        w["ZZZ"] = 0.0
        with self.assertRaises(lc.CascadeError):
            lc.build_trades(w, self.inputs, None, 14.0)
        shifted = self.weights.copy()
        shifted.index = shifted.index + pd.Timedelta(minutes=7)
        with self.assertRaises(lc.CascadeError):
            lc.build_trades(shifted, self.inputs, None, 14.0)


class NullTests(unittest.TestCase):
    def setUp(self):
        self.world = RandomWorld(n=10, days=90, seed=11)
        self.weights = lc.cascade_weights(self.world.inputs.data, self.world.params)
        self.dev_start, self.dev_end = ts("2023-04-02"), ts("2023-06-15")
        self.groups, self.observed, self.n_trades = lc.event_null_groups(self.weights, self.world.inputs,
                                                                          self.dev_start, self.dev_end)

    def test_observed_statistic_is_the_mean_per_trade_gross_of_the_development_trades(self):
        trades = lc.build_trades(self.weights, self.world.inputs, None, 0.0)
        day = pd.DatetimeIndex(trades["exit_time"]).normalize()
        dev = trades.loc[np.asarray((day >= self.dev_start) & (day <= self.dev_end))]
        self.assertEqual(self.n_trades, len(dev))
        self.assertGreater(self.n_trades, 25)
        self.assertAlmostEqual(self.observed, float((dev["side"] * dev["unit_return"]).mean()))
        self.assertAlmostEqual(self.observed, float(dev["trade_gross"].mean()))  # gross: before the 14 bps cost

    def test_identity_draw_reproduces_the_observed_statistic(self):
        draws = lc.null_draws(self.groups, self.n_trades, n_draws=7, identity=True)
        np.testing.assert_allclose(draws, self.observed, rtol=0, atol=1e-12)
        self.assertEqual(sum(len(g.sides) for g in self.groups), self.n_trades)

    def test_candidates_preserve_contract_direction_and_calendar_month(self):
        trades = lc.build_trades(self.weights, self.world.inputs, None, 0.0)
        idx = self.world.inputs.data["close"].index
        by_group: dict[tuple[int, int], list[float]] = {}
        for _, tr in trades.iterrows():
            month = tr["entry_time"].year * 12 + tr["entry_time"].month - 1
            by_group.setdefault((int(tr["col"]), month), []).append(tr["side"])
        for g in self.groups:
            months = {idx[r].year * 12 + idx[r].month - 1 for r in g.cand_rows}
            self.assertEqual(months, {g.month})                                  # same calendar month
            self.assertTrue(set(g.sides) <= {-1.0, 1.0})
            self.assertEqual(sorted(g.sides), sorted(s for s in by_group[(g.col, g.month)] if s in g.sides)[:len(g.sides)])
            self.assertGreater(len(g.cand_rows), 1)                              # a real alternative exists
            self.assertTrue(np.isfinite(g.cand_unit).all())
            exits = idx[g.cand_rows] + pd.Timedelta(hours=24)
            self.assertTrue((exits.normalize() <= self.dev_end).all())           # nothing after the development end
        rng = np.random.default_rng(0)
        for g in self.groups[:5]:
            pick = rng.integers(0, len(g.cand_rows), size=(3, len(g.sides)))
            self.assertTrue((g.cand_rows[pick] >= 0).all())

    def test_draws_are_reproducible_use_the_registered_seed_and_move_with_it(self):
        a = lc.null_draws(self.groups, self.n_trades, n_draws=50, seed=lc.NULL_SEED)
        b = lc.null_draws(self.groups, self.n_trades, n_draws=50, seed=lc.NULL_SEED)
        c = lc.null_draws(self.groups, self.n_trades, n_draws=50, seed=1)
        np.testing.assert_array_equal(a, b)
        self.assertFalse(np.array_equal(a, c))
        self.assertEqual((lc.NULL_SEED, lc.N_NULL_DRAWS), (20261012, 999))
        fn = lc.make_null_fn(self.world.inputs)
        r1 = fn(self.weights, self.dev_start, self.dev_end, n_draws=lc.N_NULL_DRAWS, seed=ss.SEED)  # seed argument ignored
        r2 = lc.event_null(self.weights, self.world.inputs, self.dev_start, self.dev_end)
        self.assertEqual(r1["p"], r2["p"])
        self.assertEqual(r1["n_null"], 999)

    def test_a_planted_reversal_beats_the_null_and_a_planted_continuation_does_not(self):
        res = lc.event_null(self.weights, self.world.inputs, self.dev_start, self.dev_end)
        self.assertTrue(res["pass"], res)
        self.assertEqual(res["null_type"], "event")
        self.assertLessEqual(res["p"], 0.05)
        wrong = RandomWorld(n=10, days=90, seed=11, rebound=-0.04)  # the crash keeps going instead
        w = lc.cascade_weights(wrong.inputs.data, wrong.params)
        res2 = lc.event_null(w, wrong.inputs, self.dev_start, self.dev_end)
        self.assertFalse(res2["pass"], res2)
        self.assertGreater(res2["p"], 0.5)

    def test_no_development_trades_is_an_error(self):
        with self.assertRaises(lc.CascadeError):
            lc.event_null(self.weights, self.world.inputs, ts("2030-01-01"), ts("2030-02-01"))


class LeverageBookTests(unittest.TestCase):
    def setUp(self):
        self.world = RandomWorld(n=8, days=60, seed=5)
        self.weights = lc.cascade_weights(self.world.inputs.data, self.world.params)
        self.trades = lc.build_trades(self.weights, self.world.inputs, None, lc.COST_BPS_ROUND_TRIP)

    def test_positions_are_selected_by_exit_day_with_costs_stamped_at_the_exit(self):
        lo, hi = ts("2023-04-10"), ts("2023-05-10")
        positions, costs = lc.positions_for_leverage(self.trades, lo, hi)
        day = pd.DatetimeIndex(self.trades["exit_time"]).normalize()
        expected = int(((day >= lo) & (day <= hi)).sum())
        self.assertEqual(len(positions), expected)
        self.assertGreater(expected, 10)
        self.assertEqual(len(costs), expected)
        self.assertTrue((costs.index == pd.DatetimeIndex(positions["exit_time"])).all())
        self.assertTrue(np.allclose(costs.to_numpy(), 0.1 * 14e-4))
        for column in ("entry_time", "exit_time", "mark_key", "weight", "entry_price", "unit_return"):
            self.assertIn(column, positions.columns)

    def test_one_x_daily_returns_equal_the_gate_accounting(self):
        lo, hi = ts("2023-04-10"), ts("2023-05-10")
        positions, costs = lc.positions_for_leverage(self.trades, lo, hi)
        report = lc.assess_trade_book(positions, self.world.mark, costs, levels=(1,),
                                      config=lev.LeverageConfig(paths=200, horizon_days=60))
        self.assertEqual(report["levels"]["1"]["n_liquidations"], 0)
        adverse, _ = lev.position_adverse_excursions(positions, self.world.mark)
        sim = lev.simulate_leverage(positions.assign(entry_time=positions["exit_time"]), adverse, costs, 1)
        detail = lc.daily_detail(self.trades)
        gate = detail["net"].loc[lo:hi]
        both = pd.concat([sim["daily_returns"].rename("sim"), gate.rename("gate")], axis=1).dropna()
        self.assertGreater(len(both), 20)
        # the gate sums trades within a day; the leverage sim compounds period returns: equal to second order
        np.testing.assert_allclose(both["sim"].to_numpy(), both["gate"].to_numpy(), atol=3e-4)

    def test_positions_use_their_own_overlapping_windows_for_liquidation(self):
        data = flat_data(["A", "B"], n=120)
        spike(data, "A", "2021-03-02 00:00")
        spike(data, "B", "2021-03-02 06:00")
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        trades = lc.build_trades(w, inputs_for(data), None, 14.0)
        idx = data["close"].index
        # A's contract has a sharp excursion at 2021-03-02 03:00 only (inside A's window; B has not entered yet)
        mark_a = pd.DataFrame({"high": 100.0, "low": 100.0}, index=idx)
        mark_a.loc[ts("2021-03-02 03:00"), "low"] = 89.0
        mark = {"A": mark_a, "B": pd.DataFrame({"high": 100.0, "low": 100.0}, index=idx)}
        positions, costs = lc.positions_for_leverage(trades, ts("2021-03-01"), ts("2021-03-10"))
        adverse, missing = lev.position_adverse_excursions(positions, mark)
        by_symbol = dict(zip(positions["symbol"], adverse, strict=True))
        self.assertAlmostEqual(by_symbol["A"], (94.0 - 89.0) / 94.0)  # measured from A's entry price over A's window
        self.assertEqual(by_symbol["B"], 0.0)
        self.assertEqual(missing, 0)
        report = lc.assess_trade_book(positions, mark, costs, levels=(1, 10, 20),
                                      config=lev.LeverageConfig(paths=100, horizon_days=30))
        self.assertEqual(report["levels"]["1"]["n_liquidations"], 0)
        self.assertEqual(report["levels"]["10"]["n_liquidations"], 0)
        self.assertEqual(report["levels"]["20"]["n_liquidations"], 1)  # 5.3% adverse vs a 4.5% threshold at 20x (9.5% at 10x)
        self.assertIn("exit", report["stamping"])


class IntegrityAndSpecTests(unittest.TestCase):
    def test_oi_integrity_requires_coverage_from_the_start_and_to_the_end_for_active_contracts(self):
        world = RandomWorld(n=3, days=10)
        kwargs = {"required_first": ts("2023-04-01 01:00"), "required_last": ts("2023-04-10 20:00"),
                  "active_from": ts("2023-04-10 12:00")}
        out = lc.oi_integrity(world.perp, world.oi, **kwargs)
        self.assertEqual(out["symbols"], 3)
        self.assertTrue(all(v["active_at_end"] for v in out["per_symbol"].values()))
        oi = dict(world.oi)
        oi["S00USDT"] = oi["S00USDT"].loc[oi["S00USDT"].index < ts("2023-04-10 00:00")]  # stops early, still trading
        with self.assertRaises(lc.CascadeError) as ctx:
            lc.oi_integrity(world.perp, oi, **kwargs)
        self.assertIn("S00USDT", str(ctx.exception))
        # a contract that stopped trading before the end may have shorter OI
        perp = dict(world.perp)
        perp["S00USDT"] = perp["S00USDT"].iloc[:100]
        out = lc.oi_integrity(perp, oi, **kwargs)
        self.assertFalse(out["per_symbol"]["S00USDT"]["active_at_end"])
        late = dict(world.oi)
        late["S01USDT"] = late["S01USDT"].loc[late["S01USDT"].index > ts("2023-04-03")]  # starts too late
        with self.assertRaises(lc.CascadeError):
            lc.oi_integrity(world.perp, late, **kwargs)
        missing = dict(world.oi)
        del missing["S02USDT"]
        with self.assertRaises(lc.CascadeError):
            lc.oi_integrity(world.perp, missing, **kwargs)
        nan = {k: v.copy() for k, v in world.oi.items()}
        nan["S01USDT"].iloc[5] = np.nan
        with self.assertRaises(lc.CascadeError):
            lc.oi_integrity(world.perp, nan, **kwargs)

    def test_zero_volume_bars_after_a_delisting_do_not_make_a_contract_active(self):
        world = RandomWorld(n=2, days=10)
        perp = dict(world.perp)
        dead = perp["S00USDT"].copy()
        dead.loc[dead.index[100]:, "quote_volume"] = 0.0
        perp["S00USDT"] = dead
        oi = dict(world.oi)
        oi["S00USDT"] = oi["S00USDT"].loc[oi["S00USDT"].index < ts("2023-04-05")]
        out = lc.oi_integrity(perp, oi, required_first=ts("2023-04-01 01:00"), required_last=ts("2023-04-10 20:00"),
                              active_from=ts("2023-04-10 12:00"))
        self.assertFalse(out["per_symbol"]["S00USDT"]["active_at_end"])

    def test_candidate_spec_matches_the_registration(self):
        spec = lc.candidate_spec(ROUND_CFG)
        self.assertEqual(spec["params"], {"price_threshold": 0.05, "oi_threshold": 0.05, "hold_hours": 24,
                                          "lookback_hours": 4, "trade_start": "2021-12-01"})  # entries start there
        self.assertEqual(spec["null"], "event")
        self.assertEqual(spec["development"], ["2021-12-01", "2023-06-30"])  # from the amendment
        self.assertEqual(spec["validation"], ["2023-07-01", "2026-09-30"])
        variants = ss.perturbation_param_sets(spec)
        self.assertEqual(len(variants), 8)
        self.assertTrue(all(v["trade_start"] == "2021-12-01" for v in variants))
        self.assertEqual({(k, v) for var in variants for k, v in var.items() if var[k] != spec["params"][k]},
                         {("price_threshold", 0.04), ("price_threshold", 0.06), ("oi_threshold", 0.04),
                          ("oi_threshold", 0.06), ("hold_hours", 19), ("hold_hours", 29), ("lookback_hours", 3),
                          ("lookback_hours", 5)})
        self.assertEqual(lc.POSITION_FRACTION, 0.10)
        self.assertEqual(lc.COST_BPS_ROUND_TRIP, 14.0)
        self.assertEqual(lc.PERIODS_PER_YEAR, 365)
        plain = json.loads(json.dumps(ROUND_CFG))
        plain.pop("amendments")
        self.assertEqual(lc.candidate_spec(plain)["development"], ["2021-01-01", "2023-06-30"])  # registered text alone
        bad = json.loads(json.dumps(ROUND_CFG))
        bad["candidates"][0]["null"] = "allocation: x"
        with self.assertRaises(lc.CascadeError):
            lc.candidate_spec(bad)
        bad = json.loads(json.dumps(ROUND_CFG))
        bad["candidates"][0]["id"] = "other"
        with self.assertRaises(lc.CascadeError):
            lc.candidate_spec(bad)

    def test_registration_text_matches_the_implemented_constants(self):
        cand = ROUND_CFG["candidates"][0]
        self.assertIn("r4 <= -0.05 and oi4 <= -0.05", cand["signal"])
        self.assertIn("2021-12-01", json.dumps(ROUND_CFG["amendments"]))
        self.assertIn("minutes", ROUND_CFG["amendments"][0]["changes"]["oi_timing"])
        self.assertIn("10% of account equity", cand["trade"])
        self.assertIn("at most 10 concurrent", cand["trade"])
        self.assertIn("14 bps", cand["returns"])
        self.assertIn("20261012", cand["null"])
        self.assertEqual(PROTOCOL["leverage_assessment"]["levels"], list(lev.LEVERAGE_LEVELS))

    def test_full_pipeline_gates_run_on_a_random_world(self):
        from orderflow_edge_lab import strategy_search_round2 as r2
        world = RandomWorld(n=12, days=120, seed=8)
        spec = lc.candidate_spec(ROUND_CFG)
        reference = pd.Series(np.random.default_rng(1).normal(0, 0.01, 400),
                              index=pd.date_range("2023-01-01", periods=400, freq="D", tz="UTC"))
        result = r2.evaluate_candidate_general(
            spec, world.inputs.data, None, validation_window=spec["validation"], crypto_reference=reference,
            spy_returns=None, cost_bps=lc.COST_BPS_ROUND_TRIP, periods_per_year=lc.PERIODS_PER_YEAR,
            fn=lc.cascade_weights, detail_fn=lc.make_detail_fn(world.inputs), null_fn=lc.make_null_fn(world.inputs),
            g8_mode="crypto_only", n_draws=lc.N_NULL_DRAWS, n_truncation_dates=10, seed=ss.SEED)
        lc.apply_cumulative_dsr(result, 11)
        self.assertEqual(set(result["gates"]), {f"G{i}" for i in range(1, 9)})
        self.assertEqual(result["gates"]["G5"]["n_trials"], 11)
        self.assertEqual(result["gates"]["G4"]["n_null"], 999)
        self.assertEqual(len(result["gates"]["G6"]["variants"]), 8)
        self.assertTrue(result["gates"]["G1"]["pass"])


class ReviewFixesTests(unittest.TestCase):
    """Entries start at the development start; dead bars; non-positive OI; staleness report; windows; mark fallback."""

    def test_no_entries_before_the_development_start_and_no_occupied_slot_from_them(self):
        data = flat_data(["A", "B"], n=240)
        spike(data, "A", "2021-03-02 00:00")   # before the start: not traded
        spike(data, "A", "2021-03-02 12:00")   # would have been ignored as 'in position'; now it is a real entry
        spike(data, "B", "2021-03-05 00:00")
        params = {**lc.DEFAULT_PARAMS, "trade_start": "2021-03-02 12:00"}
        w = lc.cascade_weights(data, params)
        self.assertEqual(entries(w), [("2021-03-02 12:00", "A", 0.1), ("2021-03-05 00:00", "B", 0.1)])  # start inclusive
        self.assertEqual([e[:2] for e in entries(lc.cascade_weights(data, lc.DEFAULT_PARAMS))],
                         [("2021-03-02 00:00", "A"), ("2021-03-05 00:00", "B")])  # without a start: the old behaviour
        report = lc.event_report(data, params)
        self.assertEqual(report["dropped_before_start"], 1)
        self.assertEqual(report["tradable_events_long"], 2)

    def test_g4_candidates_never_come_before_the_start_or_on_dead_bars(self):
        world = RandomWorld(n=10, days=90, seed=11)
        data = {k: v.copy() for k, v in world.inputs.data.items()}
        start = ts("2023-04-20")
        dead = data["volume"].index[::7]
        data["volume"].loc[dead, :] = 0.0                       # every 7th bar of every contract is dead
        inputs = lc.CascadeInputs(data=data, funding=world.inputs.funding, max_exit=None, mark={})
        params = {**world.params, "trade_start": str(start)}
        weights = lc.cascade_weights(data, params)
        trades = lc.build_trades(weights, inputs, None, 0.0)
        self.assertGreater(len(trades), 10)
        self.assertTrue((trades["entry_time"] >= start).all())
        self.assertFalse(trades["entry_time"].isin(dead).any())
        groups, observed, n = lc.event_null_groups(weights, inputs, ts("2023-04-02"), ts("2023-06-15"))
        idx = data["close"].index
        for g in groups:
            self.assertTrue((idx[g.cand_rows] >= start).all())
            self.assertTrue((data["volume"].to_numpy()[g.cand_rows, g.col] > 0).all())
        self.assertEqual(sum(len(g.sides) for g in groups), n)
        np.testing.assert_allclose(lc.null_draws(groups, n, n_draws=3, identity=True), observed, atol=1e-12)

    def test_events_on_dead_bars_are_dropped_and_counted(self):
        data = flat_data(["A", "B", "C"])
        for name in "ABC":
            spike(data, name, "2021-03-02 00:00")
        data["volume"].loc[ts("2021-03-02 00:00"), "B"] = 0.0
        data["volume"].loc[ts("2021-03-02 00:00"), "C"] = np.nan
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        self.assertEqual([e[1] for e in entries(w)], ["A"])
        report = lc.event_report(data, lc.DEFAULT_PARAMS)
        self.assertEqual((report["raw_events_long"], report["dropped_dead_bar_long"], report["tradable_events_long"]),
                         (3, 2, 1))
        self.assertEqual(report["dropped_dead_bar_short"], 0)
        del data["volume"]
        with self.assertRaises(lc.CascadeError):
            lc.cascade_weights(data, lc.DEFAULT_PARAMS)

    def test_non_positive_oi_rows_are_missing_for_the_lookup_and_counted_in_integrity(self):
        stamps = ["2021-03-01 11:50", "2021-03-01 11:55", "2021-03-01 12:00"]
        series = pd.Series([7.0, 0.0, -3.0], index=pd.DatetimeIndex([ts(s) for s in stamps]))
        value, age = lc.asof_values(series, pd.DatetimeIndex([ts("2021-03-01 12:05")]), lag_minutes=5)
        self.assertEqual((float(value[0]), float(age[0])), (7.0, 15.0))   # skips the 0 and the negative record
        nothing, _ = lc.asof_values(series.iloc[1:], pd.DatetimeIndex([ts("2021-03-01 12:05")]), lag_minutes=5)
        self.assertTrue(np.isnan(nothing[0]))
        world = RandomWorld(n=2, days=6)
        oi = {k: v.copy() for k, v in world.oi.items()}
        oi["S00USDT"].iloc[10:13] = 0.0
        out = lc.oi_integrity(world.perp, oi, required_first=ts("2023-04-01 01:00"),
                              required_last=ts("2023-04-06 20:00"), active_from=ts("2023-04-06 12:00"))
        self.assertEqual(out["per_symbol"]["S00USDT"]["nonpositive_rows_treated_as_missing"], 3)
        self.assertEqual(out["nonpositive_rows_total"], 3)
        zero_only = {k: v.copy() for k, v in world.oi.items()}
        zero_only["S01USDT"][:] = 0.0
        with self.assertRaises(lc.CascadeError):
            lc.oi_integrity(world.perp, zero_only, required_first=ts("2023-04-01 01:00"),
                            required_last=ts("2023-04-06 20:00"), active_from=ts("2023-04-06 12:00"))
        # a zero OI row at t-lookback does not create an event with an undefined or huge ratio: the older value is used
        data = flat_data(["A"])
        panels = lc.build_panels({"A": pd.DataFrame({"close": data["close"]["A"], "quote_volume": 1.0})},
                                 {"A": pd.Series([1000.0, 0.0], index=pd.DatetimeIndex(
                                     [ts("2021-03-01 00:00"), ts("2021-03-01 05:00")]))})
        self.assertEqual(float(panels["oi"].loc[ts("2021-03-01 06:00"), "A"]), 1000.0)

    def test_staleness_and_missing_oi_are_reported_without_changing_the_rule(self):
        data = flat_data(["A", "B", "C"])
        for name in "ABC":
            spike(data, name, "2021-03-02 00:00")
        t = ts("2021-03-02 00:00")
        data["oi_age"].loc[t, "B"] = 45.0                       # stale at t
        data["oi_age"].loc[ts("2021-03-01 20:00"), "C"] = 31.0  # stale at t-4h
        data["oi_age"].loc[t, "A"] = 30.0                       # exactly 30: not older than 30
        data["close"].loc[ts("2021-03-02 03:00"), "A"] = 90.0   # a price trigger whose OI is missing
        data["oi"].loc[ts("2021-03-02 03:00"), "A"] = np.nan
        report = lc.event_report(data, lc.DEFAULT_PARAMS)
        self.assertEqual(report["tradable_with_oi_older_than_30min"], 2)
        # the 03:00 trigger itself (OI missing at t) and the 07:00 rebound (OI missing at t-4h)
        self.assertEqual(report["price_trigger_without_oi"], 2)
        self.assertEqual([e[1] for e in entries(lc.cascade_weights(data, lc.DEFAULT_PARAMS))], ["A", "B", "C"])  # rule unchanged
        del data["oi_age"]
        self.assertIsNone(lc.event_report(data, lc.DEFAULT_PARAMS)["tradable_with_oi_older_than_30min"])

    def test_panels_carry_volume_and_the_oi_age(self):
        world = RandomWorld(n=2, days=4)
        panels = lc.build_panels(world.universe["perp"], world.oi)
        self.assertEqual(set(panels), {"close", "volume", "oi", "oi_age"})
        self.assertTrue((panels["volume"].dropna() == 5e6).all().all())
        self.assertTrue((panels["oi_age"].dropna() >= 5.0).all().all())  # at least the 5-minute causal lag

    def test_daily_detail_is_zero_filled_over_the_full_registered_windows(self):
        data = flat_data(["A"], n=400)
        spike(data, "A", "2021-03-05 12:00")   # exits 03-06 12:00
        inputs = inputs_for(data)
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        trades = lc.build_trades(w, inputs, None, 14.0)
        windows = [(ts("2021-03-01"), ts("2021-03-10")), (ts("2021-03-11"), ts("2021-03-20"))]
        daily = lc.daily_detail(trades, windows)
        self.assertEqual((str(daily.index[0].date()), str(daily.index[-1].date()), len(daily)), ("2021-03-01", "2021-03-20", 20))
        self.assertEqual(float((daily["gross"] != 0).sum()), 1.0)
        self.assertEqual(float(daily.loc[ts("2021-03-01"), "gross"]), 0.0)
        self.assertEqual(len(lc.daily_detail(trades)), 1)   # without windows: just the covered range
        with self.assertRaises(lc.CascadeError):
            lc.daily_detail(trades, [(ts("2021-03-10"), ts("2021-03-20"))])  # the exit day lies outside
        gate = lc.make_detail_fn(inputs, windows)(w, None, 14.0)
        pd.testing.assert_frame_equal(gate, daily)

    def test_positions_without_mark_bars_fall_back_to_perp_high_low_and_are_counted(self):
        data = flat_data(["A", "B"], n=120)
        spike(data, "A", "2021-03-02 00:00")
        spike(data, "B", "2021-03-02 06:00")
        w = lc.cascade_weights(data, lc.DEFAULT_PARAMS)
        trades = lc.build_trades(w, inputs_for(data), None, 14.0)
        idx = data["close"].index
        flat = pd.DataFrame({"high": 100.0, "low": 100.0}, index=idx)
        perp_a = flat.copy()
        perp_a.loc[ts("2021-03-02 03:00"), "low"] = 89.0           # the dip only exists in A's perp bars
        perp_b = flat.copy()
        positions, costs = lc.positions_for_leverage(trades, ts("2021-03-01"), ts("2021-03-10"))
        cfg = lev.LeverageConfig(paths=100, horizon_days=30)
        # A has no mark frame at all; B's mark has a hole covering its window except the final bar
        mark_b = flat.copy()
        mark_b = mark_b.loc[(mark_b.index <= ts("2021-03-02 06:00")) | (mark_b.index >= ts("2021-03-03 06:00"))]
        report = lc.assess_trade_book(positions, {"B": mark_b}, costs, levels=(1, 20), config=cfg,
                                      perp_hl={"A": perp_a, "B": perp_b})
        self.assertEqual(report["levels"]["20"]["n_liquidations"], 1)      # A: 5.3% adverse from the perp low
        self.assertEqual(report["positions_without_mark_bars"], 1)          # A
        self.assertEqual(report["positions_using_perp_fallback_bars"], 2)   # A (all bars) and B (holes)
        self.assertEqual(report["positions_without_any_bars"], 0)
        self.assertEqual(report["perp_fallback_bars_in_windows"], 24 + 23)  # A: 24 bars, B: 23 hole bars
        self.assertEqual(report["mark_bars_in_windows"], 1)
        # without the fallback the same positions cannot liquidate and are counted as unprotected
        bare = lc.assess_trade_book(positions, {"B": mark_b}, costs, levels=(20,), config=cfg)
        self.assertEqual(bare["levels"]["20"]["n_liquidations"], 0)
        self.assertEqual(bare["positions_without_any_bars"], 1)
        merged = lc.mark_with_perp_fallback({"B": mark_b}, {"A": perp_a, "B": perp_b})
        self.assertEqual(set(merged), {"A", "B"})
        self.assertTrue(merged["B"].index.is_monotonic_increasing)
        self.assertEqual(int(merged["B"]["is_mark"].sum()), len(mark_b))


if __name__ == "__main__":
    unittest.main()
