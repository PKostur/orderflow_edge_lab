"""Binance futures metrics loader and the round-2 universe builder (offline: listings, zips and checksums mocked)."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as fa
from orderflow_edge_lab import binance_futures_metrics as bfm
from tests.test_binance_futures_archive import hour_row, zip_of
from tests.test_binance_spot_archive import FakeArchive

HEADER = ("create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,"
          "sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio")


def metrics_row(stamp: str, oi: float, symbol: str = "AAAUSDT") -> str:
    return f"{stamp},{symbol},{oi:.8f},{oi * 100:.8f},1.5,1.2,1.6,0.4"


def metrics_csv(rows: list[str], header: str = HEADER) -> str:
    return header + "\n" + "\n".join(rows) + "\n"


def metrics_zip(rows: list[str], header: str = HEADER) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("m.csv", metrics_csv(rows, header))
    return buffer.getvalue()


def day_rows(day: str, symbol: str = "AAAUSDT", base: float = 1000.0, n: int = 288) -> list[str]:
    stamps = pd.date_range(pd.Timestamp(day), periods=n, freq="5min")
    return [metrics_row(str(s), base + i, symbol) for i, s in enumerate(stamps)]


def add_metrics(fake: FakeArchive, symbol: str, day: str, rows: list[str] | None = None, **kwargs):
    fake.add_zip(bfm.metrics_key(symbol, day), metrics_zip(rows if rows is not None else day_rows(day, symbol)),
                 **kwargs)


class ParsingTests(unittest.TestCase):
    def test_real_columns_oi_field_utc_index_and_float_values(self):
        series, dropped = bfm.parse_metrics_csv(metrics_csv([metrics_row("2021-01-01 00:05:00", 34935.881),
                                                             metrics_row("2021-01-01 00:00:00", 34900.5)]),
                                                symbol="AAAUSDT")
        self.assertEqual(dropped, 0)
        self.assertEqual(bfm.OI_COLUMN, "sum_open_interest")
        self.assertEqual(series.name, "sum_open_interest")
        self.assertEqual(series.index.name, "create_time")
        self.assertEqual(str(series.index.tz), "UTC")
        self.assertEqual([str(t) for t in series.index], ["2021-01-01 00:00:00+00:00", "2021-01-01 00:05:00+00:00"])
        np.testing.assert_allclose(series.to_numpy(), [34900.5, 34935.881])  # base units, not the USDT value column
        self.assertEqual(set(bfm.EXPECTED_COLUMNS), set(HEADER.split(",")))

    def test_unsorted_file_is_sorted(self):
        rows = [metrics_row("2026-09-30 02:30:00", 3.0), metrics_row("2026-09-30 00:00:00", 1.0),
                metrics_row("2026-09-30 01:15:00", 2.0)]
        series, _ = bfm.parse_metrics_csv(metrics_csv(rows))
        self.assertTrue(series.index.is_monotonic_increasing)
        self.assertEqual(list(series), [1.0, 2.0, 3.0])

    def test_exact_duplicate_rows_are_dropped_and_counted_conflicts_raise(self):
        rows = [metrics_row("2021-01-01 00:00:00", 5.0), metrics_row("2021-01-01 00:05:00", 6.0)] * 2
        series, dropped = bfm.parse_metrics_csv(metrics_csv(rows))
        self.assertEqual((len(series), dropped), (2, 2))
        with self.assertRaises(bfm.MetricsError):
            bfm.parse_metrics_csv(metrics_csv([metrics_row("2021-01-01 00:00:00", 5.0),
                                               metrics_row("2021-01-01 00:00:00", 5.5)]))

    def test_bad_inputs_fail_loudly(self):
        with self.assertRaises(bfm.MetricsError):  # the OI column is missing
            bfm.parse_metrics_csv("create_time,symbol,sum_open_interest_value\n2021-01-01 00:00:00,A,1\n")
        with self.assertRaises(bfm.MetricsError):  # NaN open interest is never read as zero
            bfm.parse_metrics_csv(metrics_csv([metrics_row("2021-01-01 00:00:00", float("nan"))]))
        with self.assertRaises(bfm.MetricsError):  # empty field
            bfm.parse_metrics_csv(metrics_csv(["2021-01-01 00:00:00,AAAUSDT,,1,1,1,1,1"]))
        with self.assertRaises(bfm.MetricsError):  # unparseable timestamp
            bfm.parse_metrics_csv(metrics_csv([metrics_row("yesterday", 1.0)]))
        with self.assertRaises(bfm.MetricsError):  # wrong symbol in the file
            bfm.parse_metrics_csv(metrics_csv([metrics_row("2021-01-01 00:00:00", 1.0, "BBBUSDT")]), symbol="AAAUSDT")
        with self.assertRaises(bfm.MetricsError):  # ragged row
            bfm.parse_metrics_csv(metrics_csv(["2021-01-01 00:00:00,AAAUSDT,1.0"]))
        empty, dropped = bfm.parse_metrics_csv(HEADER + "\n")
        self.assertEqual((len(empty), dropped), (0, 0))

    def test_zip_parsing(self):
        series, _ = bfm.parse_metrics_zip(metrics_zip(day_rows("2022-06-15", n=12)), symbol="AAAUSDT")
        self.assertEqual(len(series), 12)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeArchive(page_size=3)
        for day in ("2021-01-01", "2021-01-02", "2021-01-03"):
            add_metrics(self.fake, "AAAUSDT", day)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def downloads(self) -> list[str]:
        """File downloads (zip and checksum) as opposed to listing requests."""
        return [c for c in self.fake.calls if c.startswith("https://data.binance.vision/")]

    def load(self, **kwargs):
        kwargs.setdefault("start", "2021-01-01")  # the fixtures are dated early January 2021, not the sample start
        return bfm.load_metrics_universe(["AAAUSDT"], fetch=self.fake, directory=self.dir, workers=3, **kwargs)

    def test_listing_range_series_and_provenance(self):
        out = self.load(start="2021-01-02", end="2021-01-03")
        series = out["oi"]["AAAUSDT"]
        self.assertEqual(len(series), 576)
        self.assertEqual(str(series.index[0]), "2021-01-02 00:00:00+00:00")
        self.assertEqual(str(series.index[-1]), "2021-01-03 23:55:00+00:00")
        prov = out["provenance"]["AAAUSDT"]
        self.assertEqual((prov["days_loaded"], prov["days_missing_within_span"], prov["max_gap_minutes"]), (2, 0, 5.0))
        self.assertEqual(prov["first_listed_day"], "2021-01-01")
        self.assertEqual(bfm.list_metrics_days("AAAUSDT", fetch=self.fake), ["2021-01-01", "2021-01-02", "2021-01-03"])

    def test_missing_day_and_partial_day_are_reported_not_hidden(self):
        fake = FakeArchive(page_size=3)
        add_metrics(fake, "AAAUSDT", "2021-06-21")
        add_metrics(fake, "AAAUSDT", "2021-06-23", day_rows("2021-06-23", n=126))
        out = bfm.load_metrics_universe(["AAAUSDT"], start="2021-06-01", end="2021-06-30", fetch=fake,
                                        directory=self.dir / "gap", workers=2)
        prov = out["provenance"]["AAAUSDT"]
        self.assertEqual(prov["days_missing_within_span"], 1)
        self.assertEqual(prov["rows"], 288 + 126)
        self.assertEqual(prov["partial_days"], {"2021-06-23": 126})   # days with fewer than 288 rows, with their counts
        self.assertEqual(prov["n_partial_days"], 1)
        self.assertGreater(prov["max_gap_minutes"], 24 * 60)

    def test_provenance_counts_non_positive_rows_and_complete_days_have_no_partials(self):
        fake = FakeArchive(page_size=3)
        rows = day_rows("2021-06-21")
        rows[3] = metrics_row("2021-06-21 00:15:00", 0.0)
        add_metrics(fake, "AAAUSDT", "2021-06-21", rows)
        add_metrics(fake, "AAAUSDT", "2021-06-22")
        out = bfm.load_metrics_universe(["AAAUSDT"], start="2021-06-01", end="2021-06-30", fetch=fake,
                                        directory=self.dir / "zeros", workers=2)
        prov = out["provenance"]["AAAUSDT"]
        self.assertEqual((prov["zero_or_negative_rows"], prov["partial_days"], prov["n_partial_days"]), (1, {}, 0))

    def test_symbol_without_files_gives_an_empty_series(self):
        out = bfm.load_metrics_universe(["ZZZUSDT"], fetch=self.fake, directory=self.dir)
        self.assertEqual(len(out["oi"]["ZZZUSDT"]), 0)
        self.assertEqual(out["provenance"]["ZZZUSDT"]["rows"], 0)

    def test_checksum_failure_raises_and_is_not_cached(self):
        fake = FakeArchive()
        add_metrics(fake, "AAAUSDT", "2021-01-01", bad_checksum=True)
        with self.assertRaises(fa.ChecksumError):
            bfm.load_metrics_universe(["AAAUSDT"], start="2021-01-01", fetch=fake, directory=self.dir / "bad")
        self.assertFalse(any((self.dir / "bad").rglob("*.zip")))

    def test_cache_is_reused_and_resumes_after_a_partial_download(self):
        self.load()
        first_calls = len(self.downloads())
        self.assertEqual(first_calls, 6)  # three zips and three checksums
        self.fake.calls.clear()
        self.load()
        self.assertEqual(self.downloads(), [])
        victim = next(self.dir.rglob("*2021-01-02.zip"))
        victim.unlink()  # a missing file is fetched again, the others are not
        corrupt = next(self.dir.rglob("*2021-01-03.zip"))
        corrupt.write_bytes(b"garbage")  # a corrupt file fails its checksum and is replaced
        self.fake.calls.clear()
        out = self.load()
        fetched = sorted(Path(c).name for c in self.downloads() if c.endswith(".zip"))
        self.assertEqual(fetched, ["AAAUSDT-metrics-2021-01-02.zip", "AAAUSDT-metrics-2021-01-03.zip"])
        self.assertEqual(len(out["oi"]["AAAUSDT"]), 3 * 288)

    def test_load_oi_series_returns_the_series(self):
        series = bfm.load_oi_series("AAAUSDT", start="2021-01-01", end="2021-01-01", fetch=self.fake,
                                    directory=self.dir)
        self.assertEqual(len(series), 288)
        self.assertEqual(str(series.index.tz), "UTC")

    def test_cross_file_conflict_raises(self):
        fake = FakeArchive()
        add_metrics(fake, "AAAUSDT", "2021-01-01", [metrics_row("2021-01-01 23:55:00", 5.0)])
        add_metrics(fake, "AAAUSDT", "2021-01-02", [metrics_row("2021-01-01 23:55:00", 6.0)])
        with self.assertRaises(bfm.MetricsError):
            bfm.load_metrics_universe(["AAAUSDT"], start="2021-01-01", fetch=fake, directory=self.dir / "x")


def kline_zip(sym: str, rows: list[tuple[str, float]]) -> bytes:
    return zip_of([hour_row(ts, 1.0, quote_volume=q) for ts, q in rows])


class UniverseTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeArchive(page_size=50)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def add_klines(self, sym: str, month: str, rows: list[tuple[str, float]]):
        self.fake.add_zip(fa.DATASETS["perp"][0].format(s=sym) + f"{sym}-1h-{month}.zip", kline_zip(sym, rows))

    def build(self, symbols, lister, size=2):
        return bfm.build_universe(symbols, size=size, fetch=self.fake, directory=self.dir, workers=2,
                                  metrics_lister=lister)

    def test_ranking_uses_only_pre_2021_bars_and_total_over_calendar_days(self):
        # AAA: 100 per hour for one day in Dec 2020; BBB: 50 per hour for 3 days; CCC: only 2021 volume (huge)
        self.add_klines("AAAUSDT", "2020-12", [(f"2020-12-01 {h:02d}:00", 100.0) for h in range(24)])
        self.add_klines("BBBUSDT", "2020-11", [(f"2020-11-0{d} {h:02d}:00", 50.0) for d in (1, 2, 3) for h in range(24)])
        self.add_klines("CCCUSDT", "2021-01", [("2021-01-01 00:00", 1e12)])
        # an extra bar OPENED at 2021-01-01 00:00 inside a December file must not count either
        self.add_klines("DDDUSDT", "2020-12", [("2020-12-31 23:00", 10.0), ("2021-01-01 00:00", 1e12)])
        listers = {s: ["2020-09-01", "2021-12-01"] for s in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT")}
        out = self.build(list(listers), lambda s: listers[s], size=4)
        self.assertEqual(out["symbols"], ["BBBUSDT", "AAAUSDT", "DDDUSDT"])  # 3600 > 2400 > 10; CCC has no pre-2021 bar
        rank = {r["symbol"]: r["mean_daily_quote_volume"] for r in out["ranking"]}
        self.assertAlmostEqual(rank["AAAUSDT"], 2400.0 / 92)  # total / calendar days of the window
        self.assertAlmostEqual(rank["BBBUSDT"], 3600.0 / 92)
        self.assertAlmostEqual(rank["DDDUSDT"], 10.0 / 92)
        self.assertEqual(out["candidates_without_pre_period_volume"], 1)
        direct = bfm.pre_period_volume("DDDUSDT", fetch=self.fake, directory=self.dir)
        self.assertEqual(direct["total_quote_volume"], 10.0)

    def test_keeps_top_n_with_a_metrics_file_from_2021_12_01_and_records_the_skipped(self):
        vols = {"AAAUSDT": 400.0, "BBBUSDT": 300.0, "CCCUSDT": 200.0, "DDDUSDT": 100.0}
        for sym, v in vols.items():
            self.add_klines(sym, "2020-10", [("2020-10-05 00:00", v)])
        days = {"AAAUSDT": ["2021-12-01"], "BBBUSDT": ["2022-02-01"],  # BBB starts too late
                "CCCUSDT": ["2020-09-01", "2021-12-01"], "DDDUSDT": ["2021-12-01"]}
        out = self.build(list(vols), lambda s: days[s], size=2)
        self.assertEqual(out["symbols"], ["AAAUSDT", "CCCUSDT"])
        self.assertEqual([s["symbol"] for s in out["skipped_no_metrics"]], ["BBBUSDT"])
        self.assertEqual(out["skipped_no_metrics"][0]["first_metrics_day"], "2022-02-01")

    def test_default_lister_checks_the_2021_12_01_file_by_listing_it(self):
        for sym, v in (("AAAUSDT", 400.0), ("BBBUSDT", 300.0), ("CCCUSDT", 200.0)):
            self.add_klines(sym, "2020-10", [("2020-10-05 00:00", v)])
        add_metrics(self.fake, "AAAUSDT", "2021-12-01", day_rows("2021-12-01", n=2))
        add_metrics(self.fake, "BBBUSDT", "2022-02-01", day_rows("2022-02-01", "BBBUSDT", n=2))  # starts too late
        add_metrics(self.fake, "CCCUSDT", "2020-12-31", day_rows("2020-12-31", "CCCUSDT", n=2))
        add_metrics(self.fake, "CCCUSDT", "2021-12-01", day_rows("2021-12-01", "CCCUSDT", n=2))
        out = bfm.build_universe(["AAAUSDT", "BBBUSDT", "CCCUSDT"], size=5, fetch=self.fake, directory=self.dir,
                                 workers=2)
        self.assertEqual(out["symbols"], ["AAAUSDT", "CCCUSDT"])
        self.assertEqual(out["skipped_no_metrics"], [{"symbol": "BBBUSDT", "rank": 2, "first_metrics_day": "2022-02-01",
                                                      "metrics_days": 1}])
        self.assertEqual(bfm.list_metrics_days("CCCUSDT", fetch=self.fake, day="2021-12-01"), ["2021-12-01"])
        self.assertEqual(bfm.list_metrics_days("BBBUSDT", fetch=self.fake, day="2021-12-01"), [])

    def test_ties_by_symbol_and_registered_exclusions(self):
        for sym in ("BBBUSDT", "AAAUSDT", "USDCUSDT", "BTCUPUSDT", "BTCUSDT", "XXX_240628"):
            self.add_klines(sym, "2020-10", [("2020-10-05 00:00", 10.0)])
        days = ["2021-12-01"]
        out = self.build(["BBBUSDT", "AAAUSDT", "USDCUSDT", "BTCUPUSDT", "BTCUSDT", "XXX_240628"], lambda s: days,
                         size=10)
        self.assertEqual(out["symbols"], ["AAAUSDT", "BBBUSDT", "BTCUSDT"])  # stablecoin, leveraged token, delivery out
        self.assertEqual(out["metrics_day"], "2021-12-01")  # the amended registered criterion is recorded in the file
        self.assertIn("2021-12-01", out["rule"])
        self.assertEqual((bfm.DATA_START, bfm.OI_LOAD_START), ("2021-12-01", "2021-11-30"))
        self.assertIn("USDCUSDT", out["symbols_excluded_by_filter"])
        self.assertTrue(bfm.universe_matches(out, {"symbols": ["AAAUSDT", "BBBUSDT", "BTCUSDT"]}))
        self.assertFalse(bfm.universe_matches(out, {"symbols": ["AAAUSDT", "BBBUSDT", "BTCUSDT"],
                                                    "metrics_day": "2021-01-01"}))
        base = {"symbols": ["AAAUSDT", "BBBUSDT", "BTCUSDT"], "metrics_day": "2021-12-01", "size": 10,
                "rank_window": ["2020-10-01", "2020-12-31"]}
        self.assertTrue(bfm.universe_matches(out, base))
        self.assertFalse(bfm.universe_matches(out, {**base, "size": 30}))
        self.assertFalse(bfm.universe_matches(out, {**base, "rank_window": ["2020-09-01", "2020-12-31"]}))
        self.assertFalse(bfm.universe_matches(out, {"symbols": ["BBBUSDT", "AAAUSDT", "BTCUSDT"]}))

    def test_missing_rank_months_count_as_no_volume_not_an_error(self):
        out = bfm.pre_period_volume("NOPEUSDT", fetch=self.fake, directory=self.dir)
        self.assertEqual(out["total_quote_volume"], 0.0)


if __name__ == "__main__":
    unittest.main()
