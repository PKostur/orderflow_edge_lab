from __future__ import annotations

from io import BytesIO
import zipfile
import unittest

import pandas as pd

from orderflow_edge_lab.okx_funding_archive import (
    OkxFundingArchiveError,
    merge_okx_funding_archive_records,
    parse_okx_funding_archive_bytes,
    records_to_funding_frames,
)


def _archive(rows: str, header: str = "instrument_name,funding_rate,funding_time") -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("funding.csv", header + "\n" + rows)
    return out.getvalue()


class OkxFundingArchiveTests(unittest.TestCase):
    def test_exact_schema_parses_target_rows(self):
        payload = _archive(
            "BTC-USDT-SWAP,0.0001,1756684800000\n"
            "ETH-USDT-SWAP,-0.0002,1756684800000\n"
        )
        result = parse_okx_funding_archive_bytes(
            payload,
            expected_archive_filename="fixture.zip",
            target_instruments=["BTC-USDT-SWAP"],
            start="2025-09-01T00:00:00Z",
            end="2025-10-01T00:00:00Z",
        )
        self.assertEqual(result["total_data_rows"], 2)
        self.assertEqual(result["target_record_count"], 1)
        self.assertEqual(
            result["records"][0]["instrument_name"],
            "BTC-USDT-SWAP",
        )
        self.assertAlmostEqual(
            result["records"][0]["funding_rate"],
            0.0001,
        )

    def test_header_change_fails_closed(self):
        payload = _archive(
            "BTC-USDT-SWAP,0.0001,1756684800000\n",
            header="instId,rate,time",
        )
        with self.assertRaises(OkxFundingArchiveError):
            parse_okx_funding_archive_bytes(
                payload,
                expected_archive_filename="fixture.zip",
                target_instruments=["BTC-USDT-SWAP"],
                start="2025-09-01T00:00:00Z",
                end="2025-10-01T00:00:00Z",
            )

    def test_conflicting_cross_archive_duplicate_fails_closed(self):
        reports = [
            {
                "records": [
                    {
                        "instrument_name": "BTC-USDT-SWAP",
                        "funding_time": 1,
                        "funding_rate": 0.1,
                    }
                ]
            },
            {
                "records": [
                    {
                        "instrument_name": "BTC-USDT-SWAP",
                        "funding_time": 1,
                        "funding_rate": 0.2,
                    }
                ]
            },
        ]
        with self.assertRaises(OkxFundingArchiveError):
            merge_okx_funding_archive_records(reports)

    def test_records_convert_to_canonical_funding_frames(self):
        frames = records_to_funding_frames(
            [
                {
                    "instrument_name": "BTC-USDT-SWAP",
                    "funding_time": 1756684800000,
                    "funding_rate": 0.0001,
                }
            ],
            {"BTC_USDT": "BTC-USDT-SWAP", "ETH_USDT": "ETH-USDT-SWAP"},
        )
        self.assertEqual(len(frames["BTC_USDT"]), 1)
        self.assertTrue(frames["ETH_USDT"].empty)
        self.assertEqual(
            frames["BTC_USDT"].index.tz,
            pd.Timestamp.now(tz="UTC").tz,
        )


if __name__ == "__main__":
    unittest.main()
