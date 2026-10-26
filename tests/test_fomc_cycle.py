"""FOMC-cycle even-week rule (strategy-search-v1 round 2, R2C2): meeting data, cycle-day mapping, weights, gates."""

from __future__ import annotations

from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from orderflow_edge_lab import fomc_cycle as fc
from orderflow_edge_lab import strategy_search as ss
from orderflow_edge_lab import strategy_search_round2 as r2

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "config" / "fomc_scheduled_meetings_1994_2026.json"


def weekday_distance(a: date, b: date) -> int:
    """Independent signed count of weekdays from ``a`` to ``b`` (b - a in weekdays), by walking the calendar."""
    step = 1 if b >= a else -1
    n, d = 0, a
    while d != b:
        d += timedelta(days=step)
        if d.weekday() < 5:
            n += step
    return n


class MeetingDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        cls.meetings = fc.load_scheduled_meetings()

    def test_every_year_has_a_source_url_and_eight_meetings_except_2020(self):
        years = self.payload["years"]
        self.assertEqual(sorted(years), [str(y) for y in range(1994, 2027)])
        for year, info in years.items():
            self.assertTrue(info["source_url"].startswith("https://www.federalreserve.gov/monetarypolicy/"), year)
            expected = 7 if year == "2020" else 8
            self.assertEqual(len(info["meetings"]), expected, year)

    def test_known_dates_decision_day_and_exclusions(self):
        dates = {m.date().isoformat() for m in self.meetings}
        for present in ("1994-02-04", "2008-12-16", "2013-05-01", "2019-05-01", "2023-02-01", "2026-09-16", "2003-09-16"):
            self.assertIn(present, dates)  # second day of two-day meetings; Apr/May and Jan/Feb spans use the later month
        for absent in ("2001-09-17", "2008-10-08", "2013-10-16", "2020-03-15", "2020-03-18", "2025-08-22", "2003-09-15",
                       "2019-10-04"):
            self.assertNotIn(absent, dates)  # calls, unscheduled, cancelled, notation votes, pre-meeting session
        excluded = {e["date"]: e["reason"] for y in self.payload["years"].values() for e in y["excluded"]}
        self.assertEqual(excluded["2020-03-18"], "cancelled")
        self.assertEqual(excluded["2020-03-15"], "unscheduled")
        self.assertIn("pre-meeting session", excluded["2003-09-15"])

    def test_sorted_unique_weekdays(self):
        self.assertEqual(self.meetings, sorted(set(self.meetings)))
        self.assertTrue(all(m.dayofweek < 5 for m in self.meetings))
        self.assertEqual(len(self.meetings), 263)


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_fomc", ROOT / "scripts" / "build_fomc_scheduled_meetings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HeadingParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = _load_builder()

    def test_cross_month_two_day_meetings_use_the_second_day_in_the_later_month(self):
        parse = self.builder.parse_heading_date
        self.assertEqual(parse("January 31-February 1 Meeting", 1995), date(1995, 2, 1))
        self.assertEqual(parse("June 30-July 1 Meeting", 1998), date(1998, 7, 1))
        self.assertEqual(parse("July 31-August 1  Meeting", 2012), date(2012, 8, 1))  # double space as on the page
        self.assertEqual(parse("April/May 30-1 Meeting", 2019), date(2019, 5, 1))
        self.assertEqual(parse("January 28-29 Meeting", 2020), date(2020, 1, 29))
        self.assertEqual(parse("March 31 Meeting", 1998), date(1998, 3, 31))
        self.assertEqual(parse("March 17-18 (cancelled) Meeting", 2020), date(2020, 3, 18))

    def test_historical_page_fixture_with_the_three_real_headings(self):
        html = "".join(f'<h5 class="panel-heading panel-heading--shaded">{h}</h5>' for h in (
            "January 31-February 1 Meeting - 1995", "March 28 Meeting - 1995", "February 28 Conference Call - 1995"))
        meetings, excluded = self.builder.parse_historical_year(html, 1995)
        self.assertEqual(meetings, [date(1995, 2, 1), date(1995, 3, 28)])
        self.assertEqual([e["reason"] for e in excluded], ["conference call"])
        for heading, year, expected in (("June 30-July 1 Meeting - 1998", 1998, date(1998, 7, 1)),
                                        ("July 31-August 1  Meeting - 2012", 2012, date(2012, 8, 1))):
            got, _ = self.builder.parse_historical_year(f"<h5>{heading}</h5>", year)
            self.assertEqual(got, [expected])

    def test_data_file_has_the_decision_day_not_the_first_day(self):
        years = json.loads(DATA_FILE.read_text(encoding="utf-8"))["years"]
        for year, good, bad in (("1995", "1995-02-01", "1995-01-31"), ("1998", "1998-07-01", "1998-06-30"),
                                ("2012", "2012-08-01", "2012-07-31")):
            self.assertIn(good, years[year]["meetings"])
            self.assertNotIn(bad, years[year]["meetings"])


class CycleDayTests(unittest.TestCase):
    MEETINGS = [pd.Timestamp("2019-01-30"), pd.Timestamp("2019-03-20"), pd.Timestamp("2019-05-01")]

    def test_two_day_meeting_day_zero_is_the_second_day(self):
        dates = pd.DatetimeIndex(["2019-01-28", "2019-01-29", "2019-01-30", "2019-01-31", "2019-02-04", "2019-02-05"])
        cd = fc.cycle_days(dates, self.MEETINGS)
        self.assertTrue(np.isnan(cd[0]))  # before the first cycle starts (day -1 = 2019-01-29)
        np.testing.assert_array_equal(cd[1:], [-1, 0, 1, 3, 4])

    def test_holiday_counts_as_a_day_and_matches_brute_force(self):
        # 2019-02-18 is Presidents' Day (no trading) but day 13: the last day of week 2
        cd = fc.cycle_days(pd.DatetimeIndex(["2019-02-12", "2019-02-15", "2019-02-18", "2019-02-19"]), self.MEETINGS)
        np.testing.assert_array_equal(cd, [9, 12, 13, 14])
        days = pd.bdate_range("2019-01-29", "2019-05-01")
        got = fc.cycle_days(days, self.MEETINGS)
        for d, g in zip(days, got):
            self.assertEqual(g, weekday_distance_cycle(d.date(), self.MEETINGS), d)

    def test_even_weeks_membership_and_week_labels(self):
        cd = np.array([-2, -1, 3, 4, 8, 9, 13, 14, 18, 19, 23, 24, 28, 29, 33, 34, np.nan], dtype=float)
        inside = fc.in_even_week(cd)
        np.testing.assert_array_equal(inside, [0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0])
        self.assertEqual([fc.week_of(x) for x in (-6, -2, -1, 3, 4, 8, 9, 13, 14, 29, 33, 34)],
                         [-1, -1, 0, 0, 1, 1, 2, 2, 3, 6, 6, 7])
        self.assertEqual(fc.EVEN_WEEK_WINDOWS, ((-1, 3), (9, 13), (19, 23), (29, 33)))

    def test_cycle_resets_at_day_minus_one_and_week_seven_days_are_out(self):
        # day 33 of the Jan-30 cycle is 2019-03-18; the next meeting (2019-03-20) resets the clock at 2019-03-19
        cd = fc.cycle_days(pd.DatetimeIndex(["2019-03-18", "2019-03-19", "2019-03-20"]), self.MEETINGS)
        np.testing.assert_array_equal(cd, [33, -1, 0])
        # a cycle longer than 34 weekdays: week 7 and beyond are out of the market until the reset
        long_cycle = [pd.Timestamp("2019-01-30"), pd.Timestamp("2019-04-24")]
        days = pd.bdate_range("2019-01-29", "2019-04-23")
        cds = fc.cycle_days(days, long_cycle)
        inside = fc.in_even_week(cds)
        d33 = days[list(cds).index(33)]
        d34 = days[list(cds).index(34)]
        self.assertEqual(d34, d33 + pd.offsets.BDay(1))
        self.assertTrue(inside[list(cds).index(33)])
        self.assertFalse(inside[list(cds).index(34)])
        after33 = inside[list(cds).index(34):]
        self.assertFalse(after33[:-1].any())  # week 7, 8, ... until the next day -1 (2019-04-23, last element)
        self.assertEqual(float(cds[-1]), -1.0)
        self.assertTrue(after33[-1])

    def test_window_shift_moves_every_window_by_whole_weekdays(self):
        days = pd.bdate_range("2019-01-01", "2019-06-30")
        base = fc.in_even_week(fc.cycle_days(days, self.MEETINGS))
        later = fc.in_even_week(fc.cycle_days(days, self.MEETINGS, shift_days=1))
        earlier = fc.in_even_week(fc.cycle_days(days, self.MEETINGS, shift_days=-1))
        np.testing.assert_array_equal(later[1:], base[:-1])  # windows one weekday later: today's flag = yesterday's base
        np.testing.assert_array_equal(earlier[:-1], base[1:])  # one weekday earlier
        # week 0 with shift -1 is days -2..2 relative to the unshifted meeting (cycle day 3 / 4 here are shifted counts)
        cd = fc.cycle_days(pd.DatetimeIndex(["2019-01-28", "2019-02-01", "2019-02-04"]), self.MEETINGS, shift_days=-1)
        np.testing.assert_array_equal(cd, [-1, 3, 4])
        self.assertEqual(fc.DEFAULT_PARAMS, {"window_shift_days": 0})


def weekday_distance_cycle(t: date, meetings: list[pd.Timestamp]) -> float:
    """Independent brute-force cycle day by walking weekdays (nan before the first cycle)."""
    best = None
    for m in meetings:
        reset = m.date()
        reset -= timedelta(days=1)
        while reset.weekday() >= 5:
            reset -= timedelta(days=1)
        if reset <= t:
            best = m.date()
    return float("nan") if best is None else float(weekday_distance(best, t))


class WeightTests(unittest.TestCase):
    def data_for(self, start, end, holidays=()):
        idx = pd.bdate_range(start, end, tz="UTC").difference(pd.DatetimeIndex(holidays, tz="UTC"))
        prices = pd.DataFrame({"SPY": np.linspace(100, 120, len(idx))}, index=idx)
        return {"prices": prices, "_calendar": idx}

    def test_position_for_day_d_is_set_at_close_of_d_minus_1(self):
        data = self.data_for("2019-01-22", "2019-02-28", holidays=["2019-02-18"])
        w = fc.weights_R2C2_fomc_cycle(data, {})["SPY"]
        t = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
        self.assertEqual(w[t("2019-01-25")], 0.0)  # next day 01-28 is day 28 of the December cycle (week 5)
        self.assertEqual(w[t("2019-01-28")], 1.0)  # next day 01-29 = day -1 (week 0 starts)
        self.assertEqual(w[t("2019-02-04")], 0.0)  # next day 02-05 is day 4 (week 1)
        self.assertEqual(w[t("2019-02-11")], 1.0)  # next day 02-12 is day 9
        self.assertEqual(w[t("2019-02-14")], 1.0)  # next trading day 02-15 is day 12
        self.assertEqual(w[t("2019-02-15")], 0.0)  # 02-18 is a holiday; next trading day 02-19 is day 14 (out)
        self.assertEqual(w[t("2019-02-25")], 1.0)  # 02-26 is day 19

    def test_weights_have_no_signal_before_the_first_meeting_cycle(self):
        data = self.data_for("1994-01-03", "1994-02-10")
        w = fc.weights_R2C2_fomc_cycle(data, {})["SPY"]
        self.assertTrue(w.loc[:"1994-02-01"].isna().all())
        self.assertEqual(w[pd.Timestamp("1994-02-02", tz="UTC")], 1.0)  # next day 02-03 is day -1 of the 02-04 meeting
        self.assertEqual(w[pd.Timestamp("1994-02-10", tz="UTC")], 0.0)  # last row: next weekday 02-11 is day 5

    def test_truncation_g1_passes(self):
        data = self.data_for("2018-01-02", "2019-12-31")
        w = fc.weights_R2C2_fomc_cycle(data, {})
        res = ss.g1_truncation(fc.weights_R2C2_fomc_cycle, data, {}, w, n_dates=20)
        self.assertTrue(res["pass"], res)

    def test_registered_perturbations(self):
        cfg = json.loads((ROOT / "config" / "strategy_search_v1_round2.json").read_text(encoding="utf-8"))
        specs = {s["id"]: s for s in r2.candidate_specs(cfg)}
        spec = specs[r2.FOMC_ID]
        self.assertEqual(spec["perturb"], {"window_shift_days": [-1, 1]})
        self.assertEqual(spec["null"], "timing")  # parsed from the registered text
        self.assertTrue(spec["null_registered_text"].startswith("timing (run-length shuffle, 999 draws"))
        self.assertEqual(spec["development"], ["1994-01-01", "2013-12-31"])
        self.assertEqual(spec["validation"], ["2020-01-01", "2026-09-30"])
        self.assertEqual([p["window_shift_days"] for p in ss.perturbation_param_sets(spec)], [-1, 1])


class GeneralEvaluationTests(unittest.TestCase):
    def test_general_evaluation_reproduces_evaluate_candidate_for_etf_settings(self):
        idx = pd.bdate_range("1993-06-01", "2026-09-30", tz="UTC")
        rng = np.random.default_rng(5)
        px = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx))))
        prices = pd.DataFrame({"SPY": px}, index=idx)
        data = {"prices": prices, "_calendar": idx}
        returns = ss.asset_returns(prices)
        reference = pd.Series(rng.normal(0, 0.02, 1500), index=pd.date_range("2022-01-01", periods=1500, freq="D", tz="UTC"))
        spec = {"id": r2.FOMC_ID, "params": {"window_shift_days": 0}, "perturb": {"window_shift_days": [-1, 1]},
                "development": ["1994-01-01", "2013-12-31"], "null": "timing"}
        window = ["2020-01-01", "2026-09-30"]
        old = ss.evaluate_candidate(spec, data, returns, validation_window=window, crypto_reference=reference,
                                    spy_returns=returns["SPY"], n_draws=99, fn=fc.weights_R2C2_fomc_cycle)
        new = r2.evaluate_candidate_general(
            spec, data, returns, validation_window=window, crypto_reference=reference, spy_returns=returns["SPY"],
            cost_bps=ss.COST_BPS_ROUND_TRIP, periods_per_year=252, fn=fc.weights_R2C2_fomc_cycle, g8_mode="both",
            n_draws=99)
        self.assertEqual(old["return_series_sha256"], new["return_series_sha256"])
        self.assertEqual(old["windows"], new["windows"])
        for gate in ("G1", "G2", "G3", "G4", "G7", "G8"):
            self.assertEqual(ss.json_clean(old["gates"][gate]), ss.json_clean(new["gates"][gate]), gate)
        self.assertEqual([v["sharpe"] for v in old["gates"]["G6"]["variants"]],
                         [v["sharpe"] for v in new["gates"]["G6"]["variants"]])
        self.assertEqual(old["gates"]["G6"]["pass"], new["gates"]["G6"]["pass"])
        # the annualisation argument really changes the Sharpe
        crypto = r2.evaluate_candidate_general(
            spec, data, returns, validation_window=window, crypto_reference=reference, spy_returns=returns["SPY"],
            cost_bps=ss.COST_BPS_ROUND_TRIP, periods_per_year=365, fn=fc.weights_R2C2_fomc_cycle,
            g8_mode="crypto_only", n_draws=99)
        self.assertAlmostEqual(crypto["dev"]["sharpe"] / new["dev"]["sharpe"], (365 / 252) ** 0.5, places=9)
        self.assertEqual(crypto["dev"]["sharpe_daily"], new["dev"]["sharpe_daily"])


if __name__ == "__main__":
    unittest.main()
