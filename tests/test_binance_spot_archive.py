"""Binance spot archive loader (offline: listing pages, zips and checksums are mocked)."""

from __future__ import annotations

from hashlib import sha256
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit
import zipfile

import numpy as np
import pandas as pd

from orderflow_edge_lab import binance_spot_archive as ba

NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def listing_xml(prefixes=(), keys=(), truncated=False, next_marker=None) -> bytes:
    parts = [f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult {NS}><Name>data.binance.vision</Name>']
    parts.append(f"<IsTruncated>{'true' if truncated else 'false'}</IsTruncated>")
    if next_marker is not None:
        parts.append(f"<NextMarker>{next_marker}</NextMarker>")
    parts += [f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>" for p in prefixes]
    parts += [f"<Contents><Key>{k}</Key><Size>1</Size></Contents>" for k in keys]
    parts.append("</ListBucketResult>")
    return "".join(parts).encode()


def kline_row(day: str, close: float, quote_volume: float, micro: bool = False) -> str:
    ts = int(pd.Timestamp(day, tz="UTC").timestamp())
    open_time = ts * 1_000_000 if micro else ts * 1000
    close_time = open_time + (86_400_000_000 if micro else 86_400_000) - 1
    return (f"{open_time},{close - 1:.8f},{close + 1:.8f},{close - 2:.8f},{close:.8f},10.0,{close_time},"
            f"{quote_volume:.8f},100,5.0,50.0,0")


def make_zip(rows: list[str], name: str = "X-1d.csv", header: bool = False) -> bytes:
    text = ("open_time,open,high,low,close,volume,close_time,quote_volume,count,tbb,tbq,ignore\n" if header else "")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text + "\n".join(rows) + "\n")
    return buffer.getvalue()


def checksum_text(data: bytes, name: str) -> bytes:
    return f"{sha256(data).hexdigest()}  {name}".encode()


class FakeArchive:
    """Maps URLs to bytes and serves S3 listings of the registered keys (page size configurable)."""

    def __init__(self, page_size=2):
        self.files: dict[str, bytes] = {}
        self.page_size = page_size
        self.calls: list[str] = []

    def add_zip(self, key: str, data: bytes, bad_checksum: bool = False):
        self.files[key] = data
        text = checksum_text(data, Path(key).name)
        if bad_checksum:
            text = checksum_text(b"other", Path(key).name)
        self.files[key + ".CHECKSUM"] = text

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url.startswith(ba.LIST_URL):
            q = parse_qs(urlsplit(url).query)
            prefix, marker = q["prefix"][0], q.get("marker", [None])[0]
            delimiter = q.get("delimiter", [None])[0]
            keys = sorted(k for k in self.files if k.startswith(prefix))
            entries: list[tuple[str, str]] = []
            seen = set()
            for k in keys:
                rest = k[len(prefix):]
                if delimiter and delimiter in rest:
                    p = prefix + rest.split(delimiter)[0] + delimiter
                    if p not in seen:
                        seen.add(p)
                        entries.append(("p", p))
                else:
                    entries.append(("k", k))
            if marker:
                entries = [e for e in entries if e[1] > marker]
            page = entries[: self.page_size]
            truncated = len(entries) > self.page_size
            return listing_xml(prefixes=[e[1] for e in page if e[0] == "p"], keys=[e[1] for e in page if e[0] == "k"],
                               truncated=truncated, next_marker=page[-1][1] if truncated else None)
        url.encode("ascii")  # http.client can only send ASCII request lines: every URL must be percent-encoded
        key = unquote(url[len(ba.DATA_URL):])
        if key not in self.files:
            raise ba.ArchiveHTTPError(url, 404)
        return self.files[key]


class ListingTests(unittest.TestCase):
    def test_parse_listing_with_next_marker_and_namespace(self):
        page = ba.parse_listing_xml(listing_xml(prefixes=["data/spot/monthly/klines/AAAUSDT/"], truncated=True,
                                                next_marker="data/spot/monthly/klines/AAAUSDT/"))
        self.assertEqual(page.prefixes, ("data/spot/monthly/klines/AAAUSDT/",))
        self.assertTrue(page.truncated)
        self.assertEqual(page.next_marker, "data/spot/monthly/klines/AAAUSDT/")

    def test_truncated_page_without_next_marker_continues_from_last_entry(self):
        page = ba.parse_listing_xml(listing_xml(keys=["a/1", "a/2"], truncated=True))
        self.assertEqual(page.next_marker, "a/2")

    def test_pagination_collects_every_symbol_across_pages(self):
        fake = FakeArchive(page_size=2)
        for sym in ("AAAUSDT", "BBBUSDT", "CCCBTC", "DDDUSDT", "EEEUSDT"):
            fake.add_zip(f"{ba.MONTHLY_PREFIX}{sym}/1d/{sym}-1d-2020-01.zip", make_zip([kline_row("2020-01-01", 5, 5)]))
        prefixes, keys = ba.list_all(ba.MONTHLY_PREFIX, fetch=fake)
        self.assertEqual(keys, [])
        self.assertEqual([p[len(ba.MONTHLY_PREFIX):] for p in prefixes],
                         ["AAAUSDT/", "BBBUSDT/", "CCCBTC/", "DDDUSDT/", "EEEUSDT/"])
        self.assertGreaterEqual(sum("marker=" in c for c in fake.calls), 2)  # really paginated
        with tempfile.TemporaryDirectory() as tmp:
            usdt = ba.list_usdt_symbols(fetch=fake, directory=Path(tmp))
            self.assertEqual(usdt, ["AAAUSDT", "BBBUSDT", "DDDUSDT", "EEEUSDT"])  # CCCBTC dropped
            before = len(fake.calls)
            self.assertEqual(ba.list_usdt_symbols(fetch=fake, directory=Path(tmp)), usdt)  # cached
            self.assertEqual(len(fake.calls), before)

    def test_marker_that_does_not_advance_is_an_error(self):
        def stuck(url):
            return listing_xml(keys=["a"], truncated=True, next_marker="a")

        with self.assertRaises(ba.ArchiveError):
            ba.list_all("x/", fetch=stuck)


class ExclusionTests(unittest.TestCase):
    def test_stablecoins_fiat_and_leveraged_tokens_are_excluded(self):
        symbols = ["BTCUSDT", "ETHUSDT", "BTCUPUSDT", "BTCDOWNUSDT", "ETHBULLUSDT", "ETHBEARUSDT", "USDCUSDT", "BUSDUSDT",
                   "TUSDUSDT", "DAIUSDT", "FDUSDUSDT", "EURUSDT", "GBPUSDT", "TRYUSDT", "BRLUSDT", "AUDUSDT", "JUPUSDT",
                   "SUPUSDT", "PAXGUSDT"]
        kept, excluded = ba.filter_symbols(symbols)
        self.assertEqual(kept, ["BTCUSDT", "ETHUSDT", "JUPUSDT", "PAXGUSDT", "SUPUSDT"])
        self.assertEqual(excluded["BTCUPUSDT"], "leveraged token (UP/DOWN/BULL/BEAR)")
        self.assertEqual(excluded["USDCUSDT"], "stablecoin or fiat base")
        self.assertEqual(len(excluded), 14)

    def test_suffix_match_needs_a_listed_prefix(self):
        self.assertTrue(ba.is_leveraged_token("BNBUP", {"BNB", "BNBUP"}))
        self.assertFalse(ba.is_leveraged_token("JUP", {"J", "JUP"} - {"J"}))  # "J" is not a listed base
        self.assertFalse(ba.is_leveraged_token("UP", {"UP"}))

    def test_base_asset_requires_usdt(self):
        self.assertEqual(ba.base_asset("BTCUSDT"), "BTC")
        with self.assertRaises(ba.ArchiveError):
            ba.base_asset("BTCBUSD")


class ChecksumTests(unittest.TestCase):
    def test_checksum_formats_and_mismatch(self):
        data = b"hello"
        digest = sha256(data).hexdigest()
        self.assertEqual(ba.parse_checksum(f"{digest}  file.zip"), digest)
        self.assertEqual(ba.parse_checksum(f"{digest.upper()} *file.zip\n"), digest)
        self.assertEqual(ba.verify_checksum(data, f"{digest}  f"), digest)
        with self.assertRaises(ba.ChecksumError):
            ba.verify_checksum(b"hellO", f"{digest}  f")
        with self.assertRaises(ba.ChecksumError):
            ba.parse_checksum("not a checksum")

    def test_download_verifies_caches_and_replaces_corrupt_cache(self):
        fake = FakeArchive()
        data = make_zip([kline_row("2020-01-01", 5, 5)])
        key = "data/spot/monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2020-01.zip"
        fake.add_zip(key, data)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "AAAUSDT-1d-2020-01.zip"
            self.assertEqual(ba.download_verified(ba.data_url(key), target, fetch=fake), data)
            n = len(fake.calls)
            self.assertEqual(ba.download_verified(ba.data_url(key), target, fetch=fake), data)
            self.assertEqual(len(fake.calls), n)  # served from the verified cache
            target.write_bytes(b"corrupt")
            self.assertEqual(ba.download_verified(ba.data_url(key), target, fetch=fake), data)
            self.assertGreater(len(fake.calls), n)  # corrupt cache detected and re-fetched

    def test_bad_checksum_on_the_server_raises_and_nothing_is_cached(self):
        fake = FakeArchive()
        key = "data/spot/monthly/klines/AAAUSDT/1d/AAAUSDT-1d-2020-01.zip"
        fake.add_zip(key, make_zip([kline_row("2020-01-01", 5, 5)]), bad_checksum=True)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "AAAUSDT-1d-2020-01.zip"
            with self.assertRaises(ba.ChecksumError):
                ba.download_verified(ba.data_url(key), target, fetch=fake)
            self.assertFalse(target.exists())


class ParsingTests(unittest.TestCase):
    def test_millisecond_and_microsecond_open_times_give_the_same_dates(self):
        ms = ba.parse_kline_csv("\n".join([kline_row("2024-12-30", 100.0, 7.0), kline_row("2024-12-31", 101.0, 8.0)]))
        us = ba.parse_kline_csv("\n".join([kline_row("2025-01-01", 102.0, 9.0, micro=True),
                                            kline_row("2025-01-02", 103.0, 10.0, micro=True)]))
        both = pd.concat([ms, us])
        self.assertEqual([str(d.date()) for d in both.index], ["2024-12-30", "2024-12-31", "2025-01-01", "2025-01-02"])
        self.assertTrue(all(d.tz is not None and d.hour == 0 for d in both.index))
        np.testing.assert_allclose(both["close"], [100.0, 101.0, 102.0, 103.0])
        np.testing.assert_allclose(both["quote_volume"], [7.0, 8.0, 9.0, 10.0])  # dollar volume column

    def test_mixed_units_in_one_file_and_header_rows(self):
        rows = [kline_row("2024-12-31", 100.0, 5.0), kline_row("2025-01-01", 101.0, 6.0, micro=True)]
        frame = ba.parse_kline_zip(make_zip(rows, header=True))
        self.assertEqual([str(d.date()) for d in frame.index], ["2024-12-31", "2025-01-01"])

    def test_zip_without_csv_is_an_error(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "x")
        with self.assertRaises(ba.ArchiveError):
            ba.parse_kline_zip(buffer.getvalue())


class SymbolLoadingTests(unittest.TestCase):
    def build(self):
        fake = FakeArchive(page_size=3)
        sym = "AAAUSDT"
        base = f"{ba.MONTHLY_PREFIX}{sym}/1d/{sym}-1d-"
        fake.add_zip(base + "2024-12.zip", make_zip([kline_row("2024-12-30", 10.0, 1.0), kline_row("2024-12-31", 11.0, 2.0)]))
        fake.add_zip(base + "2025-01.zip", make_zip([kline_row("2025-01-01", 12.0, 3.0, micro=True),
                                                      kline_row("2025-01-02", 13.0, 4.0, micro=True)]))
        daily = f"{ba.DAILY_PREFIX}{sym}/1d/{sym}-1d-"
        fake.add_zip(daily + "2025-02-01.zip", make_zip([kline_row("2025-02-01", 14.0, 5.0, micro=True)]))
        fake.add_zip(daily + "2025-02-02.zip", make_zip([kline_row("2025-02-02", 15.0, 6.0, micro=True)]))
        fake.add_zip(daily + "2025-01-02.zip", make_zip([kline_row("2025-01-02", 99.0, 99.0, micro=True)]))  # in a monthly month
        return fake

    def test_monthly_zips_then_daily_zips_for_months_after_the_last_monthly(self):
        fake = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            frame = ba.load_symbol_daily("AAAUSDT", end="2025-02-28", fetch=fake, directory=Path(tmp))
        self.assertEqual([str(d.date()) for d in frame.index],
                         ["2024-12-30", "2024-12-31", "2025-01-01", "2025-01-02", "2025-02-01", "2025-02-02"])
        np.testing.assert_allclose(frame["close"], [10.0, 11.0, 12.0, 13.0, 14.0, 15.0])  # the 99.0 daily dup is ignored
        np.testing.assert_allclose(frame["quote_volume"], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    def test_end_date_clips_and_old_gaps_do_not_trigger_daily_listing(self):
        fake = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            clipped = ba.load_symbol_daily("AAAUSDT", end="2025-01-01", fetch=fake, directory=Path(tmp))
            self.assertEqual(str(clipped.index[-1].date()), "2025-01-01")
            fake.calls.clear()
            old = ba.load_symbol_daily("AAAUSDT", end="2026-09-30", fetch=fake, directory=Path(tmp))
            self.assertEqual(str(old.index[-1].date()), "2025-01-02")  # delisted long before the end: monthly data only
            self.assertFalse(any(ba.DAILY_PREFIX in c for c in fake.calls))

    def test_load_universe_builds_aligned_panels_with_provenance(self):
        fake = self.build()
        other = "ZZZUSDT"
        fake.add_zip(f"{ba.MONTHLY_PREFIX}{other}/1d/{other}-1d-2025-01.zip",
                     make_zip([kline_row("2025-01-02", 7.0, 70.0, micro=True)]))
        fake.add_zip(f"{ba.MONTHLY_PREFIX}USDCUSDT/1d/USDCUSDT-1d-2025-01.zip",
                     make_zip([kline_row("2025-01-02", 1.0, 1.0, micro=True)]))
        with tempfile.TemporaryDirectory() as tmp:
            panel = ba.load_universe(end="2025-01-31", fetch=fake, directory=Path(tmp), workers=2,
                                     symbols=["AAAUSDT", "ZZZUSDT", "USDCUSDT"])
        self.assertEqual(list(panel["close"].columns), ["AAAUSDT", "ZZZUSDT"])
        self.assertEqual(panel["provenance"]["symbols_used"], 2)
        self.assertIn("USDCUSDT", panel["provenance"]["symbols_excluded"])
        self.assertEqual(panel["provenance"]["per_symbol"]["ZZZUSDT"]["first_date"], "2025-01-02")
        self.assertTrue(np.isnan(panel["close"].loc[pd.Timestamp("2024-12-30", tz="UTC"), "ZZZUSDT"]))
        self.assertEqual(panel["quote_volume"].loc[pd.Timestamp("2025-01-02", tz="UTC"), "ZZZUSDT"], 70.0)
        self.assertEqual(sorted(panel["close"].index), list(panel["close"].index))


class NonAsciiAndGapTests(unittest.TestCase):
    SYMBOL = "币安人生USDT"

    def test_non_ascii_symbol_urls_are_percent_encoded_and_cache_names_are_safe(self):
        fake = FakeArchive(page_size=5)
        key = f"{ba.MONTHLY_PREFIX}{self.SYMBOL}/1d/{self.SYMBOL}-1d-2025-01.zip"
        fake.add_zip(key, make_zip([kline_row("2025-01-02", 7.0, 70.0, micro=True)]))
        url = ba.data_url(key)
        url.encode("ascii")
        self.assertIn("%E5%B8%81", url)
        self.assertEqual(ba.safe_name("BTCUSDT-1d-2020-01.zip"), "BTCUSDT-1d-2020-01.zip")  # old cache names unchanged
        self.assertTrue(ba.safe_name(self.SYMBOL).isascii())
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ba.list_usdt_symbols(fetch=fake, directory=Path(tmp)), [self.SYMBOL])
            frame = ba.load_symbol_daily(self.SYMBOL, end="2025-01-31", fetch=fake, directory=Path(tmp))
            self.assertEqual(float(frame["close"].iloc[0]), 7.0)
            cached = [p for p in Path(tmp).rglob("*.zip")]
            self.assertEqual(len(cached), 1)
            self.assertTrue(cached[0].parent.name.isascii() and cached[0].name.isascii())
            n = len(fake.calls)
            ba.load_symbol_daily(self.SYMBOL, end="2025-01-31", fetch=fake, directory=Path(tmp))
            self.assertFalse(any(c.endswith(".zip") or c.endswith(".CHECKSUM") for c in fake.calls[n:]))  # resumed from cache
            panel = ba.load_universe(end="2025-01-31", fetch=fake, directory=Path(tmp), workers=1, symbols=[self.SYMBOL])
            self.assertEqual(list(panel["close"].columns), [self.SYMBOL])  # real listed pair stays in the universe

    def test_http_fetch_never_sends_raw_non_ascii(self):
        sent = []

        class Response:
            status = 200

            def read(self):
                return b"ok"

        class Conn:
            def request(self, method, target, headers=None):
                target.encode("ascii")
                sent.append(target)

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with mock.patch.object(ba, "_connection", return_value=Conn()):
            self.assertEqual(ba.http_fetch(f"{ba.DATA_URL}data/spot/{self.SYMBOL}/x.zip"), b"ok")
            self.assertEqual(ba.http_fetch(ba.data_url(f"data/spot/{self.SYMBOL}/x.zip")), b"ok")
        self.assertEqual(sent[0], sent[1])  # encoded once, not twice

    def test_relisted_ticker_becomes_a_new_coin_after_a_gap_of_more_than_30_days(self):
        days = list(pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC"))
        days += list(pd.date_range("2024-03-01", periods=5, freq="D", tz="UTC"))  # 51 days after the last bar
        frame = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": np.arange(15.0) + 1, "volume": 1.0,
                              "quote_volume": 5.0, "trades": 1.0}, index=pd.DatetimeIndex(days))
        parts = ba.split_on_gaps(frame)
        self.assertEqual([len(p) for p in parts], [10, 5])
        self.assertEqual(len(ba.split_on_gaps(frame.iloc[[0, 1, 2]])), 1)
        edge = frame.iloc[[0, 5]].set_axis(pd.DatetimeIndex(["2024-01-01", "2024-01-31"], tz="UTC"))
        self.assertEqual(len(ba.split_on_gaps(edge)), 1)  # exactly 30 days is not a relisting
        self.assertEqual(len(ba.split_on_gaps(pd.concat([frame.iloc[:10], frame.iloc[:10].set_axis(
            frame.index[:10] + pd.Timedelta(40, "D"))]))), 2)
        fake = FakeArchive(page_size=5)
        sym = "ZZZUSDT"
        rows1 = [kline_row(d.strftime("%Y-%m-%d"), 10.0 + i, 5.0, micro=True) for i, d in enumerate(days[:10])]
        rows2 = [kline_row(d.strftime("%Y-%m-%d"), 50.0 + i, 5.0, micro=True) for i, d in enumerate(days[10:])]
        fake.add_zip(f"{ba.MONTHLY_PREFIX}{sym}/1d/{sym}-1d-2024-01.zip", make_zip(rows1))
        fake.add_zip(f"{ba.MONTHLY_PREFIX}{sym}/1d/{sym}-1d-2024-03.zip", make_zip(rows2))
        with tempfile.TemporaryDirectory() as tmp:
            panel = ba.load_universe(end="2024-03-31", fetch=fake, directory=Path(tmp), workers=1, symbols=[sym])
        self.assertEqual(list(panel["close"].columns), [sym, f"{sym}#2"])
        close = panel["close"]
        self.assertEqual(int(close[sym].notna().sum()), 10)
        self.assertEqual(int(close[f"{sym}#2"].notna().sum()), 5)
        returns = close.pct_change(fill_method=None)
        self.assertEqual(int(returns[sym].notna().sum()), 9)  # no return across the gap
        self.assertEqual(int(returns[f"{sym}#2"].notna().sum()), 4)
        self.assertIn(f"{sym}#2", panel["provenance"]["per_symbol"])


if __name__ == "__main__":
    unittest.main()
