from __future__ import annotations

import unittest
from unittest.mock import patch

from orderflow_edge_lab.cli.mexc_record import _parse_symbol_aliases, _snapshot_symbol
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


class MexcRecordAliasTests(unittest.TestCase):
    def test_logical_to_native_alias_preserves_unaliased_symbols(self):
        aliases = _parse_symbol_aliases(
            ["FIL_USDT=FILECOIN_USDT"],
            ("FIL_USDT", "BTC_USDT"),
        )
        self.assertEqual(aliases["FIL_USDT"], "FILECOIN_USDT")
        self.assertEqual(aliases["BTC_USDT"], "BTC_USDT")

    def test_alias_requires_logical_symbol_in_panel(self):
        with self.assertRaisesRegex(ValueError, "not in --symbol panel"):
            _parse_symbol_aliases(
                ["FIL_USDT=FILECOIN_USDT"],
                ("BTC_USDT",),
            )


class MexcRecordSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_uses_native_alias_but_preserves_logical_symbol(self):
        raw = _Writer()
        features = _Writer()
        engine = _Engine()
        seen_urls = []

        def fetch(url):
            seen_urls.append(url)
            return {"success": True, "code": 0, "data": {"version": 42}}

        with patch(
            "orderflow_edge_lab.cli.mexc_record._fetch_json",
            side_effect=fetch,
        ):
            await _snapshot_symbol(
                engine,
                raw,
                features,
                rest_base="https://example.invalid",
                symbol="FIL_USDT",
                venue_symbol="FILECOIN_USDT",
                snapshot_limit=1000,
            )

        self.assertIn("/depth/FILECOIN_USDT?limit=1000", seen_urls[0])
        self.assertEqual(raw.rows[0]["symbol"], "FIL_USDT")
        self.assertEqual(raw.rows[0]["venue_symbol"], "FILECOIN_USDT")
        self.assertEqual(features.rows[0]["symbol"], "FIL_USDT")

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

    async def test_retry_budget_can_recover_after_three_invalid_snapshots(self):
        raw = _Writer()
        features = _Writer()
        engine = _Engine()
        payloads = [
            {"success": True, "code": 0, "data": {"version": 0}},
            {"success": True, "code": 0, "data": {"version": 0}},
            {"success": True, "code": 0, "data": {"version": 0}},
            {"success": True, "code": 0, "data": {"version": 99}},
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
                symbol="FIL_USDT",
                snapshot_limit=1000,
                max_attempts=5,
            )

        self.assertEqual(engine.calls, 4)
        self.assertEqual(
            [row["record_type"] for row in raw.rows],
            [
                "rest_snapshot_rejected",
                "rest_snapshot_rejected",
                "rest_snapshot_rejected",
                "rest_snapshot",
            ],
        )
        self.assertEqual(features.rows[0]["book_version"], 99)
        self.assertEqual(features.rows[0]["snapshot_attempt"], 4)

    async def test_partial_bootstrap_marks_exhausted_symbol_unavailable(self):
        raw = _Writer()
        features = _Writer()
        engine = _Engine()
        payloads = [
            {"success": True, "code": 0, "data": {"version": 11}},
            {"success": True, "code": 0, "data": {"version": 0}},
            {"success": True, "code": 0, "data": {"version": 0}},
            {"success": True, "code": 0, "data": {"version": 22}},
        ]
        with patch(
            "orderflow_edge_lab.cli.mexc_record._fetch_json",
            side_effect=payloads,
        ), patch(
            "orderflow_edge_lab.cli.mexc_record.asyncio.sleep",
            return_value=None,
        ):
            unavailable = await _bootstrap_snapshots(
                engine,
                raw,
                features,
                rest_base="https://example.invalid",
                symbols=("ETH_USDT", "FIL_USDT", "SOL_USDT"),
                venue_symbols={
                    "ETH_USDT": "ETH_USDT",
                    "FIL_USDT": "FIL_USDT",
                    "SOL_USDT": "SOL_USDT",
                },
                snapshot_limit=1000,
                snapshot_max_attempts=2,
                failure_policy="continue",
            )

        self.assertEqual(unavailable, {"FIL_USDT"})
        self.assertTrue(
            any(
                row.get("record_type") == "snapshot_unavailable"
                and row.get("symbol") == "FIL_USDT"
                for row in raw.rows
            )
        )
        self.assertTrue(
            any(
                row.get("record_type") == "symbol_unavailable"
                and row.get("symbol") == "FIL_USDT"
                for row in features.rows
            )
        )
        snapshot_symbols = [
            row["symbol"]
            for row in features.rows
            if row.get("event_type") == "snapshot"
        ]
        self.assertEqual(snapshot_symbols, ["ETH_USDT", "SOL_USDT"])

    async def test_partial_bootstrap_fail_policy_preserves_fail_fast_default(self):
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
            with self.assertRaises(MexcOrderFlowError):
                await _bootstrap_snapshots(
                    engine,
                    raw,
                    features,
                    rest_base="https://example.invalid",
                    symbols=("FIL_USDT",),
                    venue_symbols={"FIL_USDT": "FIL_USDT"},
                    snapshot_limit=1000,
                    snapshot_max_attempts=2,
                    failure_policy="fail",
                )

        self.assertFalse(
            any(row.get("record_type") == "symbol_unavailable" for row in features.rows)
        )

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
