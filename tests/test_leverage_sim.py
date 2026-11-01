"""Isolated-margin leverage simulation: liquidation trigger, P&L scaling, ruin, bootstrap (synthetic, offline)."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab import leverage_sim as lev


def ts(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


def position(entry: str, exit_: str, weight: float, unit_return: float, price: float = 100.0,
             key: str = "X") -> dict:
    return {"entry_time": ts(entry), "exit_time": ts(exit_), "mark_key": key, "symbol": key, "weight": weight,
            "entry_price": price, "unit_return": unit_return}


def book(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def mark_frame(rows: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """bar END time -> (high, low)."""
    return pd.DataFrame({"high": [v[0] for v in rows.values()], "low": [v[1] for v in rows.values()]},
                        index=pd.DatetimeIndex([ts(t) for t in rows]))


def costs(entries: list[str], value: float = 0.0) -> pd.Series:
    return pd.Series(value, index=pd.DatetimeIndex([ts(t) for t in entries]), dtype=float)


class ThresholdTests(unittest.TestCase):
    def test_threshold_is_inverse_leverage_minus_maintenance_margin(self):
        self.assertAlmostEqual(lev.liquidation_threshold(10), 0.095)
        self.assertAlmostEqual(lev.liquidation_threshold(20), 0.045)
        self.assertAlmostEqual(lev.liquidation_threshold(1), 0.995)
        self.assertAlmostEqual(lev.liquidation_threshold(2, 0.01), 0.49)
        with self.assertRaises(lev.LeverageError):
            lev.liquidation_threshold(0)

    def test_long_liquidation_triggers_exactly_at_the_threshold(self):
        # 10x long from 100: liquidated when the mark low reaches 90.5 (9.5% adverse), not at 90.51
        at = lev.adverse_excursion(1.0, 100.0, 90.5, 120.0)
        above = lev.adverse_excursion(1.0, 100.0, 90.51, 120.0)
        self.assertTrue(bool(lev.is_liquidated(at, 10)))
        self.assertFalse(bool(lev.is_liquidated(above, 10)))
        self.assertTrue(bool(lev.is_liquidated(lev.adverse_excursion(1.0, 100.0, 90.0, 120.0), 10)))

    def test_short_liquidation_triggers_exactly_at_the_threshold(self):
        at = lev.adverse_excursion(-1.0, 100.0, 80.0, 109.5)
        below = lev.adverse_excursion(-1.0, 100.0, 80.0, 109.49)
        self.assertTrue(bool(lev.is_liquidated(at, 10)))
        self.assertFalse(bool(lev.is_liquidated(below, 10)))
        # only the adverse side counts: a short does not care about the low, a long does not care about the high
        self.assertEqual(lev.adverse_excursion(-1.0, 100.0, 1.0, 100.0), 0.0)
        self.assertEqual(lev.adverse_excursion(1.0, 100.0, 100.0, 1e6), 0.0)

    def test_window_covers_bars_ending_after_entry_up_to_and_including_exit(self):
        mark = {"X": mark_frame({"2021-03-01 08:00": (100.0, 50.0),   # bar ending AT entry: before the fill
                                 "2021-03-01 09:00": (101.0, 99.0),
                                 "2021-03-01 16:00": (102.0, 95.0),   # bar ending at exit: counts
                                 "2021-03-01 17:00": (103.0, 10.0)})}  # after exit
        pos = book([position("2021-03-01 08:00", "2021-03-01 16:00", 0.5, 0.0)])
        adverse, missing = lev.position_adverse_excursions(pos, mark)
        self.assertAlmostEqual(adverse[0], 0.05)
        self.assertEqual(missing, 0)
        none, missing = lev.position_adverse_excursions(pos, {"X": mark["X"].iloc[:1]})
        self.assertEqual((none[0], missing), (0.0, 1))


class SimulationTests(unittest.TestCase):
    def test_pnl_scales_with_leverage_and_costs_scale_too(self):
        pos = book([position("2021-03-01 08:00", "2021-03-01 16:00", 0.5, 0.01),
                    position("2021-03-01 08:00", "2021-03-01 16:00", -0.5, -0.02, key="Y")])
        adverse = np.zeros(2)
        pc = costs(["2021-03-01 08:00"], 7e-4)
        one = lev.simulate_leverage(pos, adverse, pc, 1)
        three = lev.simulate_leverage(pos, adverse, pc, 3)
        self.assertAlmostEqual(float(one["period_returns"].iloc[0]), 0.5 * 0.01 + 0.5 * 0.02 - 7e-4)
        self.assertAlmostEqual(float(three["period_returns"].iloc[0]), 3 * (0.015) - 3 * 7e-4)
        self.assertEqual(three["n_liquidations"], 0)

    def test_liquidated_position_loses_margin_plus_fee_on_notional(self):
        pos = book([position("2021-03-01 08:00", "2021-03-01 16:00", -0.5, -0.30)])
        sim = lev.simulate_leverage(pos, np.array([0.2]), costs(["2021-03-01 08:00"]), 10)
        self.assertEqual(sim["n_liquidations"], 1)
        self.assertAlmostEqual(float(sim["period_returns"].iloc[0]), -0.5 * (1 + 0.005 * 10))
        safe = lev.simulate_leverage(pos, np.array([0.2]), costs(["2021-03-01 08:00"]), 2)
        self.assertEqual(safe["n_liquidations"], 0)  # threshold at 2x is 49.5%
        self.assertAlmostEqual(float(safe["period_returns"].iloc[0]), 2 * -0.5 * -0.30)

    def test_losses_are_floored_at_the_whole_account(self):
        pos = book([position("2021-03-01 08:00", "2021-03-01 16:00", 1.0, -0.9)])
        sim = lev.simulate_leverage(pos, np.array([0.0]), costs(["2021-03-01 08:00"]), 20)  # no mark hit: pure scaling
        self.assertEqual(float(sim["period_returns"].iloc[0]), -1.0)
        self.assertEqual(sim["final_equity"], 0.0)

    def test_ruin_is_equity_below_half_at_any_period_end(self):
        rows = [position(f"2021-03-0{d} 08:00", f"2021-03-0{d} 16:00", 1.0, r)
                for d, r in zip((1, 2, 3, 4), (-0.3, -0.3, 0.9, 0.0), strict=True)]
        sim = lev.simulate_leverage(book(rows), np.zeros(4), costs([f"2021-03-0{d} 08:00" for d in (1, 2, 3, 4)]), 1)
        np.testing.assert_allclose(sim["equity"].to_numpy(), [0.7, 0.49, 0.49 * 1.9, 0.49 * 1.9])
        self.assertTrue(sim["historical_ruin"])  # 0.49 < 0.5 although it later recovered
        self.assertAlmostEqual(sim["min_equity"], 0.49)
        mild = lev.simulate_leverage(book(rows[:1]), np.zeros(1), costs(["2021-03-01 08:00"]), 1)
        self.assertFalse(mild["historical_ruin"])

    def test_daily_returns_compound_the_periods_of_a_day_and_fill_flat_days(self):
        rows = [position("2021-03-01 00:00", "2021-03-01 08:00", 1.0, 0.10),
                position("2021-03-01 08:00", "2021-03-01 16:00", 1.0, 0.10),
                position("2021-03-03 00:00", "2021-03-03 08:00", 1.0, -0.05)]
        sim = lev.simulate_leverage(book(rows), np.zeros(3), costs([r["entry_time"].isoformat() for r in rows]), 1)
        daily = sim["daily_returns"]
        self.assertEqual([str(d.date()) for d in daily.index], ["2021-03-01", "2021-03-02", "2021-03-03"])
        np.testing.assert_allclose(daily.to_numpy(), [1.1 * 1.1 - 1.0, 0.0, -0.05])

    def test_cost_only_period_is_still_charged(self):
        pos = book([position("2021-03-01 08:00", "2021-03-01 16:00", 1.0, 0.0)])
        pc = costs(["2021-03-01 08:00", "2021-03-01 16:00"], 7e-4)  # the second rebalance closes the book
        sim = lev.simulate_leverage(pos, np.zeros(1), pc, 5)
        np.testing.assert_allclose(sim["period_returns"].to_numpy(), [-5 * 7e-4, -5 * 7e-4])


class BootstrapTests(unittest.TestCase):
    def test_indices_are_reproducible_in_range_and_have_the_requested_block_length(self):
        a = lev.stationary_bootstrap_indices(500, 2000, 365, 10, seed=20261012)
        b = lev.stationary_bootstrap_indices(500, 2000, 365, 10, seed=20261012)
        c = lev.stationary_bootstrap_indices(500, 2000, 365, 10, seed=1)
        np.testing.assert_array_equal(a, b)
        self.assertFalse(np.array_equal(a, c))
        self.assertEqual(a.shape, (2000, 365))
        self.assertTrue(a.min() >= 0 and a.max() < 500)
        continued = (np.diff(a, axis=1) % 500 == 1)
        # a step continues the block with probability 0.9 (a fresh start can also land on the next index: ~1/500)
        self.assertAlmostEqual(continued.mean(), 0.9 + 0.1 / 500, delta=0.01)

    def test_ruin_probability_extremes_and_common_random_numbers(self):
        cfg = lev.LeverageConfig(paths=500, horizon_days=365)
        losing = lev.bootstrap_ruin_probability(np.full(100, -0.01), config=cfg)
        self.assertEqual(losing["ruin_probability"], 1.0)  # 0.99^365 < 0.5
        winning = lev.bootstrap_ruin_probability(np.full(100, 0.001), config=cfg)
        self.assertEqual(winning["ruin_probability"], 0.0)
        rng = np.random.default_rng(4)
        noisy = rng.normal(0.0, 0.03, 400)
        first = lev.bootstrap_ruin_probability(noisy, config=cfg)
        again = lev.bootstrap_ruin_probability(noisy, config=cfg)
        self.assertEqual(first, again)
        other = lev.bootstrap_ruin_probability(noisy, config=lev.LeverageConfig(paths=500, seed=7))
        self.assertNotEqual(first["ruin_probability"], other["ruin_probability"])
        with self.assertRaises(lev.LeverageError):
            lev.bootstrap_ruin_probability([], config=cfg)

    def test_registered_constants(self):
        cfg = lev.LeverageConfig()
        self.assertEqual(cfg.levels, (1, 2, 3, 5, 10, 20))
        self.assertEqual((cfg.paths, cfg.mean_block_days, cfg.horizon_days, cfg.seed), (5000, 10, 365, 20261012))
        self.assertEqual((cfg.maintenance_margin_rate, cfg.liquidation_fee_rate, cfg.ruin_fraction), (0.005, 0.005, 0.5))


class AssessmentTests(unittest.TestCase):
    def world(self):
        rng = np.random.default_rng(8)
        days = pd.date_range("2021-03-01", periods=120, freq="D", tz="UTC")
        rows, mark_rows = [], {}
        for d in days:
            entry, exit_ = d + pd.Timedelta("8h"), d + pd.Timedelta("16h")
            unit = float(rng.normal(0.0008, 0.004))
            rows.append({"entry_time": entry, "exit_time": exit_, "mark_key": "X", "symbol": "X", "weight": 1.0,
                         "entry_price": 100.0, "unit_return": unit})
            low = 99.0
            if d == days[60]:
                low = 94.0  # one 6% adverse excursion against the long: kills 20x (threshold 4.5%), not 10x (9.5%)
            mark_rows[exit_] = (101.0, low)
        pos = pd.DataFrame(rows)
        pc = pd.Series(7e-4, index=pd.DatetimeIndex([r["entry_time"] for r in rows]))
        return pos, {"X": pd.DataFrame({"high": [v[0] for v in mark_rows.values()],
                                        "low": [v[1] for v in mark_rows.values()]},
                                       index=pd.DatetimeIndex(list(mark_rows)))}, pc

    def test_report_structure_and_liquidation_rule(self):
        pos, mark, pc = self.world()
        report = lev.assess_leverage(pos, mark, pc, config=lev.LeverageConfig(paths=300))
        self.assertEqual(list(report["levels"]), ["1", "2", "3", "5", "10", "20"])
        self.assertEqual(report["levels"]["20"]["n_liquidations"], 1)
        for level in ("1", "2", "3", "5", "10"):
            self.assertEqual(report["levels"][level]["n_liquidations"], 0, level)
        self.assertAlmostEqual(report["max_adverse_excursion"], 0.06)
        self.assertEqual(report["positions_without_mark_bars"], 0)
        ruin = [report["levels"][k]["ruin_probability"] for k in report["levels"]]
        self.assertEqual(ruin, sorted(ruin))  # more leverage never lowers the bootstrap ruin probability here
        self.assertLessEqual(report["max_safe_leverage"] or 0, 10)  # 20x has a historical liquidation
        again = lev.assess_leverage(pos, mark, pc, config=lev.LeverageConfig(paths=300))
        self.assertEqual(report["levels"], again["levels"])

    def test_max_safe_leverage_needs_low_ruin_and_no_liquidation(self):
        report = {"1": {"ruin_probability": 0.0, "n_liquidations": 0},
                  "2": {"ruin_probability": 0.04, "n_liquidations": 0},
                  "3": {"ruin_probability": 0.05, "n_liquidations": 1},   # a liquidation disqualifies
                  "5": {"ruin_probability": 0.051, "n_liquidations": 0},  # just above 5%
                  "10": {"ruin_probability": 0.9, "n_liquidations": 0}}
        self.assertEqual(lev.max_safe_leverage(report), 2)
        self.assertIsNone(lev.max_safe_leverage({"1": {"ruin_probability": 0.2, "n_liquidations": 0}}))
        self.assertEqual(lev.max_safe_leverage({"1": {"ruin_probability": 0.05, "n_liquidations": 0}}), 1)  # <= 5%


if __name__ == "__main__":
    unittest.main()
