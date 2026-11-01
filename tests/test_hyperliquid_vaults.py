import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from orderflow_edge_lab import hyperliquid_vaults as hv


def item(addr="0x1", closed=False, pnls=None, apr=0.5):
    if pnls is None:
        pnls = [["day", [1, 2.5]], ["week", [3.0]], ["month", [4.0, 5.0]], ["allTime", [6, 7, 8]]]
    return {
        "apr": apr,
        "pnls": pnls,
        "summary": {
            "name": "n",
            "vaultAddress": addr,
            "leader": "0xL",
            "tvl": "12.5",
            "isClosed": closed,
            "relationship": {"type": "normal"},
            "createTimeMillis": 123,
        },
    }


def at(day):
    return datetime(2026, 10, day, 3, 0, tzinfo=timezone.utc)


class HyperliquidVaultsTests(unittest.TestCase):
    def test_compact_fields_and_types(self):
        rows = hv.compact([item()], "2026-10-12T03:00:00Z")
        self.assertEqual(tuple(rows[0]), hv.FIELDS)
        r = rows[0]
        self.assertIsInstance(r["tvl"], float)
        self.assertIsInstance(r["apr"], float)
        self.assertEqual(r["relationship_type"], "normal")
        self.assertEqual(
            (r["pnl_day_last"], r["pnl_week_last"], r["pnl_month_last"], r["pnl_alltime_last"]),
            (2.5, 3.0, 5.0, 8.0),
        )
        self.assertTrue(all(isinstance(r[k], float) for k in r if k.startswith("pnl_")))

    def test_missing_pnl_series_is_none(self):
        r = hv.compact([item(pnls=[["day", []], ["week", [1]]])], "t")[0]
        self.assertIsNone(r["pnl_day_last"])
        self.assertEqual(r["pnl_week_last"], 1.0)
        self.assertIsNone(r["pnl_month_last"])
        self.assertIsNone(r["pnl_alltime_last"])
        r2 = hv.compact([item(pnls=None) | {"pnls": None}], "t")[0]
        self.assertIsNone(r2["pnl_day_last"])

    def test_gzip_round_trip(self):
        rows = hv.compact([item("0xa"), item("0xb", closed=True)], "t")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl.gz"
            hv.write_rows(p, rows)
            with gzip.open(p, "rt") as f:
                self.assertEqual(len(f.read().strip().splitlines()), 2)
            self.assertEqual(hv.read_rows(p), rows)

    def test_carry_forward_keeps_prior_dates(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            hv.run(None, a, at(10), snapshot=[item("0x1")])
            rep = hv.run(a, b, at(11), snapshot=[item("0x2", closed=True)])
            self.assertEqual(rep["n_dates"], 2)
            self.assertEqual(rep["vaults_seen_ever"], 2)
            self.assertEqual(rep["latest_closed_count"], 1)
            self.assertEqual(rep["latest_open_count"], 0)
            idx = json.loads((b / "index.json").read_text())
            self.assertEqual(idx["dates"], ["2026-10-10", "2026-10-11"])
            self.assertEqual(len(idx["files"]["2026-10-10"]["sha256"]), 64)

    def test_shrink_guard_raises(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            hv.run(None, a, at(10), snapshot=[item()])
            real = hv._dates
            calls = {"n": 0}

            def fake(p):
                calls["n"] += 1
                return real(p) if calls["n"] == 1 else []

            with mock.patch.object(hv, "_dates", fake):
                with self.assertRaises(RuntimeError):
                    hv.run(a, b, at(11), snapshot=[item()])

    def test_same_day_rerun_keeps_earlier_unless_missing_rows(self):
        with tempfile.TemporaryDirectory() as d:
            a, b, c = Path(d) / "a", Path(d) / "b", Path(d) / "c"
            hv.run(None, a, at(10), snapshot=[item("0x1"), item("0x2")])
            hv.run(a, b, at(10), snapshot=[item("0x1")])
            self.assertEqual(len(hv.read_rows(b / "snapshots" / "2026-10-10.jsonl.gz")), 2)
            hv.run(b, c, at(10), snapshot=[item("0x1"), item("0x2"), item("0x3")])
            self.assertEqual(len(hv.read_rows(c / "snapshots" / "2026-10-10.jsonl.gz")), 3)

    def test_report_has_no_statistics(self):
        with tempfile.TemporaryDirectory() as d:
            rep = hv.run(None, Path(d), at(10), snapshot=[item()])
            banned = ("mean", "sharpe", "rank", "persist", "return", "corr", "median", "std")
            for k in rep:
                self.assertFalse(any(b in k.lower() for b in banned), k)
            self.assertFalse(any(rep["claims"].values()))

    def test_fetch_retries_then_raises(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")) as m:
            with self.assertRaises(RuntimeError):
                hv.fetch_snapshot(retries=3, sleep=lambda s: None)
            self.assertEqual(m.call_count, 3)


if __name__ == "__main__":
    unittest.main()
