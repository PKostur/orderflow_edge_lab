import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab import review_methods as rm


class NullPTests(unittest.TestCase):
    def test_greater_less_two_sided(self):
        draws = np.arange(100, dtype=float)
        g = rm.action_matched_null_p(99.5, draws)
        self.assertAlmostEqual(g["p"], 1 / 101)
        self.assertEqual(g["n_null"], 100)
        self.assertAlmostEqual(g["null_mean"], 49.5)
        self.assertAlmostEqual(g["null_p95"], float(np.percentile(draws, 95)))
        lo = rm.action_matched_null_p(99.5, draws, alternative="less")
        self.assertAlmostEqual(lo["p"], 1.0)
        two = rm.action_matched_null_p(99.5, draws, alternative="two-sided")
        self.assertAlmostEqual(two["p"], 2 / 101)
        mid = rm.action_matched_null_p(49.5, draws, alternative="two-sided")
        self.assertLessEqual(mid["p"], 1.0)

    def test_too_few(self):
        with self.assertRaises(ValueError):
            rm.action_matched_null_p(1.0, [0.0] * 98)
        with self.assertRaises(ValueError):
            rm.action_matched_null_p(1.0, [0.0] * 98 + [float("nan")] * 5)


class MatchedSelectionTests(unittest.TestCase):
    def setUp(self):
        idx = pd.date_range("2026-01-01", periods=4)
        self.ret = pd.DataFrame(
            np.random.default_rng(0).normal(size=(4, 6)), index=idx, columns=list("ABCDEF")
        )
        self.sel = pd.DataFrame(0.0, index=idx, columns=self.ret.columns)
        self.sel.loc[:, "A"] = 0.5
        self.sel.loc[:, "B"] = -0.25
        self.sel.loc[:, "C"] = -0.25

    def test_reproducible(self):
        a = rm.matched_random_selection_returns(self.ret, self.sel, np.random.default_rng(1))
        b = rm.matched_random_selection_returns(self.ret, self.sel, np.random.default_rng(1))
        pd.testing.assert_series_equal(a, b)
        self.assertEqual(len(a), 4)

    def test_counts_and_net_preserved(self):
        ret = self.ret.copy()
        ret[:] = 1.0
        ret.loc[ret.index[1], ["E", "F"]] = np.nan
        out = rm.matched_random_selection_returns(ret, self.sel, np.random.default_rng(2))
        # unit returns: portfolio return equals net weight = 0.5 - 0.5 = 0
        self.assertTrue(np.allclose(out.to_numpy(), 0.0))

    def test_never_picks_nan_asset(self):
        ret = pd.DataFrame([[np.nan, np.nan, 1.0, 2.0]], columns=list("ABCD"))
        sel = pd.DataFrame([[1.0, 0.0, 0.0, -1.0]], columns=list("ABCD"))
        seen = set()
        for s in range(30):
            out = rm.matched_random_selection_returns(ret, sel, np.random.default_rng(s))
            self.assertFalse(out.isna().any())
            seen.add(round(float(out.iloc[0]), 6))
        self.assertEqual(seen, {-1.0, 1.0})

    def test_infeasible_date_nan(self):
        ret = pd.DataFrame([[1.0, np.nan]], columns=["A", "B"])
        sel = pd.DataFrame([[1.0, -1.0]], columns=["A", "B"])
        out = rm.matched_random_selection_returns(ret, sel, np.random.default_rng(0))
        self.assertTrue(out.isna().all())


class EventNullTests(unittest.TestCase):
    def test_plain(self):
        v = pd.Series(np.arange(10, dtype=float))
        self.assertAlmostEqual(rm.random_event_null(v, 10, np.random.default_rng(0)), 4.5)
        with self.assertRaises(ValueError):
            rm.random_event_null(v, 11, np.random.default_rng(0))

    def test_block_counts(self):
        v = pd.Series([0.0] * 5 + [100.0] * 5)
        lab = pd.Series(["a"] * 5 + ["b"] * 5)
        m = rm.random_event_null(
            v, rng=np.random.default_rng(0), block=lab, block_counts={"a": 2, "b": 2}
        )
        self.assertAlmostEqual(m, 50.0)
        m2 = rm.random_event_null(
            v, 99, rng=np.random.default_rng(0), block=lab, block_counts={"b": 3}
        )
        self.assertAlmostEqual(m2, 100.0)
        with self.assertRaises(ValueError):
            rm.random_event_null(v, rng=np.random.default_rng(0), block=lab, block_counts={"a": 6})


class BhTests(unittest.TestCase):
    def test_bh(self):
        res = rm.bh_family({"x": 0.001, "y": 0.04, "z": 0.9}, q=0.10)
        self.assertTrue(res["x"]["reject"])
        self.assertFalse(res["z"]["reject"])
        self.assertLessEqual(res["x"]["q_value"], res["y"]["q_value"])
        self.assertLessEqual(res["y"]["q_value"], res["z"]["q_value"])
        self.assertEqual(res["y"]["p"], 0.04)


class MaskTests(unittest.TestCase):
    def test_masks(self):
        t = rm.mask_headline("$BTC and Bitcoin rally; eth dips", ["BTC", "ETH"])
        self.assertEqual(t, "<ASSET> and <ASSET> rally; <ASSET> dips")
        self.assertEqual(rm.mask_headline("On 2026-10-09 it moved", []), "On <DATE> it moved")
        self.assertEqual(rm.mask_headline("Oct 9 close", []), "<DATE> close")
        self.assertEqual(rm.mask_headline("October 9, 2026 close", []), "<DATE> close")
        self.assertEqual(rm.mask_headline("9 October close", []), "<DATE> close")
        self.assertEqual(rm.mask_headline("Friday selloff", []), "<DATE> selloff")
        self.assertEqual(rm.mask_headline("Outlook for 2027", []), "Outlook for <YEAR>")

    def test_whole_word_and_deterministic(self):
        s = "BTCUSD and SOLID"
        self.assertEqual(rm.mask_headline(s, ["BTC", "SOL"]), s)
        self.assertEqual(rm.mask_headline(s, ["BTC"]), rm.mask_headline(s, ["BTC"]))

    def test_custom_alias(self):
        self.assertEqual(
            rm.mask_headline("Foo Coin up", ["FOO"], {"FOO": "Foo Coin"}), "<ASSET> up"
        )


class SingleLookTests(unittest.TestCase):
    def test_locked_and_open(self):
        with self.assertRaises(PermissionError) as cm:
            rm.assert_single_look("2026-11-01", pd.Timestamp("2026-10-09", tz="UTC"))
        self.assertIn("locked until 2026-11-01", str(cm.exception))
        rm.assert_single_look("2026-11-01", pd.Timestamp("2026-11-01", tz="UTC"))
        rm.assert_single_look("2026-11-01", pd.Timestamp("2026-12-01"))


class AntiGamingTests(unittest.TestCase):
    def test_scale(self):
        a = pd.Series(np.random.default_rng(0).normal(size=50))
        self.assertTrue(rm.scale_invariance_flag(a, a * 2.5)["flag"])
        self.assertFalse(rm.scale_invariance_flag(a, -a * 2.5)["flag"])
        b = a + pd.Series(np.random.default_rng(1).normal(size=50))
        self.assertFalse(rm.scale_invariance_flag(a, b)["flag"])

    def test_concentration(self):
        self.assertTrue(rm.concentration_flag(pd.Series([10.0, 1, 1, 1]))["flag"])
        self.assertFalse(rm.concentration_flag(pd.Series([1.0, 1, 1, 1]))["flag"])
        self.assertFalse(rm.concentration_flag(pd.Series([5.0, -10.0]))["flag"])

    def test_boundary(self):
        grid = {"a": [1, 2, 3], "b": [10, 20, 30]}
        self.assertTrue(rm.boundary_flag({"a": 3, "b": 20}, grid)["flag"])
        self.assertTrue(rm.boundary_flag({"a": 2, "b": 10}, grid)["flag"])
        self.assertFalse(rm.boundary_flag({"a": 2, "b": 20}, grid)["flag"])

    def test_cost_wall(self):
        g = pd.Series([0.001, 0.001])
        t = pd.Series([2.0, 2.0])
        self.assertAlmostEqual(rm.cost_wall_bps(g, t), 10.0)
        self.assertIsNone(rm.cost_wall_bps(-g, t))
        self.assertIsNone(rm.cost_wall_bps(g, t * 0))


if __name__ == "__main__":
    unittest.main()
