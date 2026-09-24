from __future__ import annotations

import unittest
from unittest.mock import patch

from orderflow_edge_lab.cli.mexc_record import _snapshot_symbol
from orderflow_edge_lab.mexc_orderflow import MexcOrderFlowError


class _Writer:
    def __init__(self) -> None:
        self.rows = []

    def write(self, row):
        self.rows.append(row)


class _Engine:
    def __init__(self) -> None:
        self.calls = 0

    def load_snapshot(self, symbol, payload):
        self.calls += 1
        version = int(payload["data"]["version"])
        if version <= 0:
            raise MexcOrderFlowError("depth.version must be positive")
        return {
            "event_type": "snapshot",
            "symbol": symbol,
            "book_version": version,
        }


class MexcRecordSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_bootstrap_snapshot_is_retried_without_weakening_validation(self):
        raw = _Writer()
        features = _Writer()
        engine = _Engine()
        payloads = [
            {"success": True, "code": 0, "data": {"version": 0}},
            {"success": True, "code": 0, "data": {"version": 42}},
        ]
        with patch(
            "orderflow_edge_lab.cli.mexc_record._fetch_json",
            side_effect=payloads,
        ), patch(
            "orderflow_edge_lab.cli.mexc_record.asyncio.sleep",
            return_value=None,
        ):
            await _snapshot_symbol(
                engine,
                raw,
                features,
                rest_base="https://example.invalid",
                symbol="ETH_USDT",
                snapshot_limit=1000,
            )

        self.assertEqual(engine.calls, 2)
        self.assertEqual(raw.rows[0]["record_type"], "rest_snapshot_rejected")
        self.assertEqual(raw.rows[0]["attempt"], 1)
        self.assertIn("depth.version must be positive", raw.rows[0]["reason"])
        self.assertEqual(raw.rows[1]["record_type"], "rest_snapshot")
        self.assertEqual(raw.rows[1]["attempt"], 2)
        self.assertEqual(features.rows[0]["book_version"], 42)
        self.assertEqual(features.rows[0]["snapshot_attempt"], 2)

    async def test_persistent_invalid_snapshot_fails_with_symbol_context(self):
        raw = _Writer()
        features = _Writer()
        engine = _Engine()
        with patch(
            "orderflow_edge_lab.cli.mexc_record._fetch_json",
            return_value={"success": True, "code": 0, "data": {"version": 0}},
        ), patch(
            "orderflow_edge_lab.cli.mexc_record.asyncio.sleep",
            return_value=None,
        ):
            with self.assertRaisesRegex(
                MexcOrderFlowError,
                "ETH_USDT: unable to obtain a valid depth snapshot after 2 attempts",
            ):
                await _snapshot_symbol(
                    engine,
                    raw,
                    features,
                    rest_base="https://example.invalid",
                    symbol="ETH_USDT",
                    snapshot_limit=1000,
                    max_attempts=2,
                )

        self.assertEqual(len(raw.rows), 2)
        self.assertEqual(features.rows, [])


if __name__ == "__main__":
    unittest.main()
