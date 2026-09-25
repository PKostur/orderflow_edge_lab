from __future__ import annotations

from io import BytesIO
import zipfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from orderflow_edge_lab.okx_funding_archive_schema import (
    ArchiveLimits,
    OkxFundingArchiveSchemaError,
    build_okx_funding_archive_schema_probe,
    _download,
    inspect_okx_funding_archive,
)


def _zip_bytes(name: str = "funding.csv", rows: str | None = None) -> bytes:
    rows = rows or (
        "ts,instId,fundingRate\n"
        "1756684800000,BTC-USDT-SWAP,0.0001\n"
        "1756713600000,BTC-USDT-SWAP,-0.0002\n"
    )
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, rows)
    return out.getvalue()


class _FakeResponse:
    def __init__(self, payload: bytes):
        self.status = 200
        self.headers = {}
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self._payload if size < 0 else self._payload[:size]


class OkxFundingArchiveSchemaTests(unittest.TestCase):
    def test_fixed_archive_schema_is_reported_without_pnl(self):
        with patch(
            "orderflow_edge_lab.okx_funding_archive_schema._download",
            return_value=_zip_bytes(),
        ):
            result = inspect_okx_funding_archive(
                "https://example.invalid/funding.zip",
                expected_filename="funding.zip",
                limits=ArchiveLimits(max_sample_rows=1),
            )
        self.assertEqual(result["csv_member_count"], 1)
        csv_report = result["csv_reports"][0]
        self.assertEqual(csv_report["header"], ["ts", "instId", "fundingRate"])
        self.assertEqual(csv_report["data_row_count"], 2)
        self.assertEqual(len(csv_report["sample_rows"]), 1)

    def test_path_traversal_member_fails_closed(self):
        with patch(
            "orderflow_edge_lab.okx_funding_archive_schema._download",
            return_value=_zip_bytes("../funding.csv"),
        ):
            with self.assertRaises(OkxFundingArchiveSchemaError):
                inspect_okx_funding_archive(
                    "https://example.invalid/funding.zip",
                    expected_filename="funding.zip",
                )


    def test_download_retries_http_429(self):
        payload = _zip_bytes()
        error = HTTPError(
            "https://example.invalid/funding.zip",
            429,
            "Too Many Requests",
            {},
            None,
        )
        with patch(
            "orderflow_edge_lab.okx_funding_archive_schema.urlopen",
            side_effect=[error, _FakeResponse(payload)],
        ), patch(
            "orderflow_edge_lab.okx_funding_archive_schema.time.sleep"
        ) as sleeper:
            result = _download(
                "https://example.invalid/funding.zip",
                max_bytes=1_000_000,
                max_attempts=2,
                backoff_seconds=0.01,
            )
        self.assertEqual(result, payload)
        sleeper.assert_called_once()

    def test_probe_is_engineering_only(self):
        config = {
            "probe_id": "fixture",
            "samples": [
                {
                    "sample_id": "monthly",
                    "archive_kind": "monthly_single_instrument",
                    "filename": "funding.zip",
                    "url": "https://example.invalid/funding.zip",
                }
            ],
        }
        with patch(
            "orderflow_edge_lab.okx_funding_archive_schema._download",
            return_value=_zip_bytes(),
        ):
            result = build_okx_funding_archive_schema_probe(config)
        self.assertEqual(
            result["evidence_use"],
            "engineering_schema_discovery_only",
        )
        claims = result["claims"]
        self.assertFalse(claims["candidate_pnl_computed"])
        self.assertFalse(claims["candidate_retested"])
        self.assertFalse(claims["historical_result_repaired"])
        self.assertFalse(claims["candidate_promoted"])
        self.assertFalse(claims["live_trading_authorized"])
        self.assertFalse(claims["leverage_authorized"])


if __name__ == "__main__":
    unittest.main()
