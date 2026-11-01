"""Binance USDT-M futures archive loader (offline: listing pages, zips and checksums are mocked)."""

from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_futures_archive as fa
from tests.test_binance_spot_archive import FakeArchive


def hour_row(ts: str, close: float, quote_volume: float = 100.0, micro: bool = False, high: float | None = None,
             low: float | None = None) -> str:
    seconds = int(pd.Timestamp(ts, tz="UTC").timestamp())
    open_time = seconds * (1_000_000 if micro else 1000)
    close_time = open_time + (3_600_000_000 if micro else 3_600_000) - 1
    high = close + 1 if high is None else high
    low = close - 1 if low is None else low
    return (f"{open_time},{close - 0.5:.8f},{high:.8f},{low:.8f},{close:.8f},10.0,{close_time},{quote_volume:.8f},"
            f"100,5.0,50.0,0")


HEADER = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"


def zip_of(rows: list[str], header: bool = False, name: str = "x.csv") -> bytes:
    text = (HEADER + "\n" if header else "") + "\n".join(rows) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def funding_zip(rows: list[tuple[int, int, float]], header: bool = True) -> bytes:
    lines = ["calc_time,funding_interval_hours,last_funding_rate"] if header else []
    lines += [f"{t},{h},{r}" for t, h, r in rows]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("f.csv", "\n".join(lines) + "\n")
    return buffer.getvalue()


def ms(ts: str, extra: int = 0) -> int:
    return int(pd.Timestamp(ts, tz="UTC").timestamp()) * 1000 + extra


def key(dataset: str, sym: str, name: str, kind: str = "monthly") -> str:
    prefix = fa.DATASETS[dataset][0 if kind == "monthly" else 1].format(s=sym)
    return prefix + name


def hours(start: str, n: int) -> list[str]:
    return [str(t) for t in pd.date_range(start, periods=n, freq="1h", tz="UTC")]


class ParsingTests(unittest.TestCase):
    def test_bar_end_index_header_and_ms_us_open_times(self):
        ms_rows = [hour_row("2024-12-31 22:00", 100.0), hour_row("2024-12-31 23:00", 101.0)]
        us_rows = [hour_row("2025-01-01 00:00", 102.0, micro=True), hour_row("2025-01-01 01:00", 103.0, micro=True)]
        frame = pd.concat([fa.parse_hourly_zip(zip_of(ms_rows, header=True)), fa.parse_hourly_zip(zip_of(us_rows))])
        self.assertEqual([str(t) for t in frame.index],
                         ["2024-12-31 23:00:00+00:00", "2025-01-01 00:00:00+00:00", "2025-01-01 01:00:00+00:00",
                          "2025-01-01 02:00:00+00:00"])  # open time + 1h = the time the close is known
        np.testing.assert_allclose(frame["close"], [100.0, 101.0, 102.0, 103.0])
        self.assertEqual(frame.index.name, "bar_end")

    def test_mixed_units_in_one_file(self):
        rows = [hour_row("2024-12-31 23:00", 1.0), hour_row("2025-01-01 00:00", 2.0, micro=True)]
        frame = fa.parse_hourly_csv("\n".join(rows))
        self.assertEqual([str(t) for t in frame.index], ["2025-01-01 00:00:00+00:00", "2025-01-01 01:00:00+00:00"])

    def test_empty_inputs_give_empty_frames(self):
        self.assertTrue(fa.parse_hourly_csv("").empty)
        self.assertTrue(fa.parse_funding_csv("").empty)
        self.assertTrue(fa.empty_frame("funding").empty)

    def test_zip_without_csv_is_an_error(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "x")
        with self.assertRaises(fa.ArchiveError):
            fa.parse_hourly_zip(buffer.getvalue())

    def test_funding_settlements_are_rounded_to_the_minute_and_keep_the_given_interval(self):
        rows = [(ms("2026-08-01 00:00", 1), 8, 0.00004123),  # archive jitter: 00:00:00.001
                (ms("2026-08-01 08:00"), 8, -0.0001),
                (ms("2026-08-01 12:00", 2), 4, 0.0002),  # contract switched to 4h funding
                (ms("2026-08-01 15:59:59") + 999, 4, 0.0003)]  # 15:59:59.999 -> 16:00
        frame = fa.parse_funding_zip(funding_zip(rows))
        self.assertEqual([t.strftime("%H:%M:%S.%f") for t in frame.index],
                         ["00:00:00.000000", "08:00:00.000000", "12:00:00.000000", "16:00:00.000000"])
        np.testing.assert_allclose(frame["rate"], [0.00004123, -0.0001, 0.0002, 0.0003])
        self.assertEqual(list(frame["interval_hours"]), [8.0, 8.0, 4.0, 4.0])
        self.assertEqual(str(frame.index.tz), "UTC")

    def test_funding_without_header_legacy_two_columns_and_microseconds(self):
        no_header = fa.parse_funding_zip(funding_zip([(ms("2020-01-01 00:00"), 8, -0.0001)], header=False))
        self.assertEqual(float(no_header["rate"].iloc[0]), -0.0001)
        legacy = fa.parse_funding_csv(f"{ms('2019-09-10 08:00')},0.0001\n")
        self.assertEqual(float(legacy["rate"].iloc[0]), 0.0001)
        self.assertTrue(np.isnan(legacy["interval_hours"].iloc[0]))
        micro = fa.parse_funding_csv(f"{ms('2026-01-01 08:00') * 1000 + 1000},8,0.0002\n")
        self.assertEqual(str(micro.index[0]), "2026-01-01 08:00:00+00:00")


class ListingTests(unittest.TestCase):
    def test_perpetual_usdt_filter_pagination_and_cache(self):
        fake = FakeArchive(page_size=2)
        for sym in ("AAAUSDT", "BBBUSDT_240628", "CCCUSDC", "DDDUSDT", "EEEBUSD", "FFFUSDT", "GGGUSDT"):
            fake.add_zip(key("perp", sym, f"{sym}-1h-2024-01.zip"), zip_of([hour_row("2024-01-01 00:00", 1.0)]))
        with tempfile.TemporaryDirectory() as tmp:
            symbols = fa.list_perp_symbols(fetch=fake, directory=Path(tmp))
            self.assertEqual(symbols, ["AAAUSDT", "DDDUSDT", "FFFUSDT", "GGGUSDT"])  # delivery / non-USDT dropped
            self.assertGreaterEqual(sum("marker=" in c for c in fake.calls), 2)
            n = len(fake.calls)
            self.assertEqual(fa.list_perp_symbols(fetch=fake, directory=Path(tmp)), symbols)
            self.assertEqual(len(fake.calls), n)  # cached

    def test_base_name_and_perpetual_predicate(self):
        self.assertEqual(fa.base_name("ABCUSDT#2"), "ABCUSDT")
        self.assertEqual(fa.base_name("ABCUSDT"), "ABCUSDT")
        self.assertFalse(fa.is_perpetual_usdt("USDT"))
        self.assertFalse(fa.is_perpetual_usdt("BTCUSDT_210625"))


class LoadDatasetTests(unittest.TestCase):
    def build(self):
        fake = FakeArchive(page_size=3)
        sym = "AAAUSDT"
        fake.add_zip(key("perp", sym, f"{sym}-1h-2025-01.zip"),
                     zip_of([hour_row(t, 10.0 + i, micro=True) for i, t in enumerate(hours("2025-01-31 22:00", 2))],
                            header=True))
        fake.add_zip(key("perp", sym, f"{sym}-1h-2025-02.zip"),
                     zip_of([hour_row(t, 20.0 + i) for i, t in enumerate(hours("2025-02-01 00:00", 3))]))
        fake.add_zip(key("perp", sym, f"{sym}-1h-2025-03-01.zip", "daily"),
                     zip_of([hour_row(t, 30.0 + i) for i, t in enumerate(hours("2025-03-01 00:00", 2))]))
        fake.add_zip(key("perp", sym, f"{sym}-1h-2025-03-02.zip", "daily"),
                     zip_of([hour_row(t, 40.0 + i) for i, t in enumerate(hours("2025-03-02 00:00", 2))]))
        fake.add_zip(key("perp", sym, f"{sym}-1h-2025-02-03.zip", "daily"),
                     zip_of([hour_row("2025-02-03 00:00", 99.0)]))  # a day of an already-monthly month: ignored
        return fake

    def test_monthly_then_daily_for_the_tail_months(self):
        fake = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            frame = fa.load_dataset("perp", "AAAUSDT", end="2025-03-31", fetch=fake, directory=Path(tmp))
        np.testing.assert_allclose(frame["close"], [10.0, 11.0, 20.0, 21.0, 22.0, 30.0, 31.0, 40.0, 41.0])
        self.assertTrue(frame.index.is_monotonic_increasing)

    def test_end_clips_and_old_gaps_do_not_list_daily(self):
        fake = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            clipped = fa.load_dataset("perp", "AAAUSDT", end="2025-01-31", fetch=fake, directory=Path(tmp))
            self.assertEqual(str(clipped.index[-1]), "2025-02-01 00:00:00+00:00")  # bar ending end + 1 day 00:00 stays
            early = fa.load_dataset("perp", "AAAUSDT", end="2025-01-30", fetch=fake, directory=Path(tmp))
            self.assertTrue(early.empty)  # January zip loaded, but every bar ends after 2025-01-31 00:00
            fake.calls.clear()
            old = fa.load_dataset("perp", "AAAUSDT", end="2026-09-30", fetch=fake, directory=Path(tmp))
            self.assertEqual(float(old["close"].iloc[-1]), 22.0)  # delisted long ago: monthly zips only
            self.assertFalse(any("/daily/" in c for c in fake.calls))

    def test_start_month_limits_downloads(self):
        fake = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            frame = fa.load_dataset("perp", "AAAUSDT", end="2025-03-31", start="2025-02-15", fetch=fake,
                                    directory=Path(tmp))
        self.assertEqual(float(frame["close"].iloc[0]), 20.0)  # February onwards
        self.assertFalse(any("2025-01.zip" in c for c in fake.calls))

    def test_checksum_failure_raises_and_resume_uses_the_cache(self):
        fake = self.build()
        bad_key = key("perp", "AAAUSDT", "AAAUSDT-1h-2025-02.zip")
        good = fake.files[bad_key]
        fake.add_zip(bad_key, good, bad_checksum=True)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(fa.ChecksumError):
                fa.load_dataset("perp", "AAAUSDT", end="2025-03-31", fetch=fake, directory=Path(tmp))
            fake.add_zip(bad_key, good)
            fa.load_dataset("perp", "AAAUSDT", end="2025-03-31", fetch=fake, directory=Path(tmp))
            fake.calls.clear()
            fa.load_dataset("perp", "AAAUSDT", end="2025-03-31", fetch=fake, directory=Path(tmp))  # second run
            self.assertFalse(any(c.startswith(fa.spot.DATA_URL) for c in fake.calls))

    def test_funding_monthly_without_daily_files(self):
        fake = FakeArchive(page_size=2)
        sym = "AAAUSDT"
        fake.add_zip(key("funding", sym, f"{sym}-fundingRate-2026-08.zip"),
                     funding_zip([(ms("2026-08-31 16:00", 1), 8, 0.0001)]))
        fake.add_zip(key("funding", sym, f"{sym}-fundingRate-2026-07.zip"),
                     funding_zip([(ms("2026-07-31 16:00", 1), 8, 0.0002)]))
        with tempfile.TemporaryDirectory() as tmp:
            frame = fa.load_dataset("funding", sym, end="2026-09-30", fetch=fake, directory=Path(tmp))
        self.assertEqual(list(frame["rate"]), [0.0002, 0.0001])
        self.assertEqual(str(frame.index[1]), "2026-08-31 16:00:00+00:00")  # tail looked for, none published: no error

    def test_non_ascii_symbol_is_percent_encoded_everywhere(self):
        sym = "币安人生USDT"
        fake = FakeArchive(page_size=5)
        fake.add_zip(key("perp", sym, f"{sym}-1h-2025-02.zip"), zip_of([hour_row("2025-02-01 00:00", 5.0, micro=True)]))
        fake.add_zip(key("spot", sym, f"{sym}-1h-2025-02.zip"), zip_of([hour_row("2025-02-01 00:00", 5.0, micro=True)]))
        fake.add_zip(key("funding", sym, f"{sym}-fundingRate-2025-02.zip"),
                     funding_zip([(ms("2025-02-01 08:00"), 8, 0.0001)]))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(fa.list_perp_symbols(fetch=fake, directory=Path(tmp)), [sym])
            universe = fa.load_universe(end="2025-02-28", fetch=fake, directory=Path(tmp), workers=1)
            self.assertEqual(list(universe["perp"]), [sym])
            cached = list(Path(tmp).rglob("*.zip"))
            self.assertEqual(len(cached), 3)
            self.assertTrue(all(p.parent.name.isascii() and p.name.isascii() for p in cached))


class SpotMatchTests(unittest.TestCase):
    SPOT = frozenset({"PEPEUSDT", "SHIBUSDT", "1INCHUSDT", "BABYDOGEUSDT", "MOGUSDT", "AAAUSDT"})

    def test_exact_scaled_and_unmatched(self):
        self.assertEqual(fa.match_spot("AAAUSDT", self.SPOT), ("AAAUSDT", 1.0))
        self.assertEqual(fa.match_spot("1INCHUSDT", self.SPOT), ("1INCHUSDT", 1.0))  # real base starting with 1
        self.assertEqual(fa.match_spot("1000PEPEUSDT", self.SPOT), ("PEPEUSDT", 1000.0))
        self.assertEqual(fa.match_spot("10000SHIBUSDT", self.SPOT), ("SHIBUSDT", 10000.0))
        self.assertEqual(fa.match_spot("1000000MOGUSDT", self.SPOT), ("MOGUSDT", 1_000_000.0))
        self.assertEqual(fa.match_spot("1MBABYDOGEUSDT", self.SPOT), ("BABYDOGEUSDT", 1_000_000.0))
        self.assertIsNone(fa.match_spot("1000BONKUSDT", self.SPOT))  # scaled contract without a spot pair stays out
        self.assertIsNone(fa.match_spot("42USDT", self.SPOT))
        self.assertIsNone(fa.match_spot("BBBUSDT", self.SPOT))
        self.assertIsNone(fa.match_spot("1000USDT", self.SPOT))


class UniverseTests(unittest.TestCase):
    def build(self):
        fake = FakeArchive(page_size=4)
        # AAA: perp + spot; BBB: perp, no spot; USDC: stablecoin base; 1000ZZZ: scaled contract, spot ZZZUSDT
        for sym in ("AAAUSDT", "BBBUSDT", "USDCUSDT", "1000ZZZUSDT"):
            fake.add_zip(key("perp", sym, f"{sym}-1h-2024-01.zip"),
                         zip_of([hour_row(t, 10.0 + i, quote_volume=50.0) for i, t in enumerate(hours("2024-01-10 00:00", 4))]))
        # AAA relists after a >30 day hole
        fake.add_zip(key("perp", "AAAUSDT", "AAAUSDT-1h-2024-03.zip"),
                     zip_of([hour_row(t, 70.0 + i) for i, t in enumerate(hours("2024-03-10 00:00", 3))]))
        for sym in ("AAAUSDT", "USDCUSDT", "ZZZUSDT"):
            months = ["2023-11", "2024-01", "2024-03"] if sym == "AAAUSDT" else ["2024-01"]
            for m in months:
                start = {"2023-11": "2023-11-05 00:00", "2024-01": "2024-01-10 00:00", "2024-03": "2024-03-10 00:00"}[m]
                fake.add_zip(key("spot", sym, f"{sym}-1h-{m}.zip"),
                             zip_of([hour_row(t, 5.0, micro=True) for t in hours(start, 4)]))
        for sym in ("AAAUSDT", "BBBUSDT"):
            fake.add_zip(key("funding", sym, f"{sym}-fundingRate-2024-01.zip"),
                         funding_zip([(ms("2024-01-10 08:00", 1), 8, 0.0001)]))
            fake.add_zip(key("mark", sym, f"{sym}-1h-2024-01.zip"),
                         zip_of([hour_row(t, 10.0) for t in hours("2024-01-10 00:00", 4)]))
        return fake

    def test_exact_spot_match_exclusions_relisting_split_and_provenance(self):
        fake = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            u = fa.load_universe(end="2024-03-31", fetch=fake, directory=Path(tmp), workers=2,
                                 symbols=["AAAUSDT", "BBBUSDT", "USDCUSDT", "1000ZZZUSDT", "BTCUSDT_240628"],
                                 include_mark=True)
        prov = u["provenance"]
        self.assertEqual(list(u["perp"]), ["1000ZZZUSDT", "AAAUSDT", "AAAUSDT#2"])  # BBB: no spot pair at all
        self.assertEqual(prov["perps_without_spot"], ["BBBUSDT"])
        self.assertEqual(prov["spot_mapping"], {"1000ZZZUSDT": {"spot": "ZZZUSDT", "k": 1000.0}})
        self.assertEqual(u["spot_scale"], {"1000ZZZUSDT": 1.0 * 1000.0, "AAAUSDT": 1.0})
        self.assertEqual(prov["symbols_excluded"], {"USDCUSDT": "stablecoin or fiat base"})
        self.assertEqual(len(u["perp"]["AAAUSDT"]), 4)
        self.assertEqual(len(u["perp"]["AAAUSDT#2"]), 3)
        self.assertEqual(list(u["perp"]["AAAUSDT"].columns), ["close", "quote_volume"])
        self.assertEqual(list(u["spot"]), ["1000ZZZUSDT", "AAAUSDT"])  # keyed by perp symbol, frame of its spot pair
        self.assertEqual(list(u["mark"]["AAAUSDT"].columns), ["high", "low"])
        self.assertEqual(len(u["funding"]["AAAUSDT"]), 1)
        self.assertIn("AAAUSDT#2", prov["per_instrument"])

    def test_spot_download_starts_at_the_perp_listing_month(self):
        fake = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            u = fa.load_universe(end="2024-03-31", fetch=fake, directory=Path(tmp), workers=1, symbols=["AAAUSDT"])
        self.assertFalse(any("AAAUSDT-1h-2023-11.zip" in c for c in fake.calls))  # older than the perp: not fetched
        self.assertEqual(str(u["spot"]["AAAUSDT"].index[0]), "2024-01-10 01:00:00+00:00")
        self.assertEqual(u["mark"], {})  # not requested


if __name__ == "__main__":
    unittest.main()
