import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from orderflow_edge_lab import liquidation_flow as lf

H = 3600 * 1000
D0 = int(datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp() * 1000)
CFG = json.loads(Path("config/liquidation_flow_v1.json").read_text(encoding="utf-8"))


def det(ts, side="sell", pos="long", sz="10", px="100"):
    return {"ts": str(ts), "side": side, "posSide": pos, "sz": sz, "bkPx": px}


def page(*details):
    return {"code": "0", "data": [{"instFamily": "BTC-USDT", "details": list(details)}] if details else []}


def row(ts, fam="BTC-USDT", pos="long", sz=10.0, px=100.0, side=None, notional=None):
    r = {"instFamily": fam, "ts": ts, "side": side or ("sell" if pos == "long" else "buy"), "posSide": pos, "sz": sz, "bkPx": px}
    r["notional_usd"] = sz * px if notional is None else notional
    return r


def poll(ts, **ok):
    return {"ts": ts, "ok": ok, "rows": 0}


class Fetch(unittest.TestCase):
    def test_pagination_stops_on_empty_page(self):
        urls = []
        pages = [page(det(300), det(200)), page(det(100)), page()]

        def getter(url):
            urls.append(url)
            return pages[len(urls) - 1]

        rows = lf.fetch_liquidations("BTC-USDT", getter=getter, pause=0)
        self.assertEqual([r["ts"] for r in rows], [300, 200, 100])
        self.assertEqual(len(urls), 3)
        self.assertNotIn("after=", urls[0])
        self.assertIn("after=200", urls[1])
        self.assertIn("after=100", urls[2])
        self.assertIsInstance(rows[0]["sz"], float)

    def test_retry_then_success(self):
        calls = []

        def getter(url):
            calls.append(url)
            if len(calls) == 1:
                raise OSError("boom")
            return page()

        self.assertEqual(lf.fetch_liquidations("BTC-USDT", getter=getter, pause=0, backoff=0), [])
        self.assertEqual(len(calls), 2)

    def test_ct_vals(self):
        payload = {"code": "0", "data": [
            {"instId": "BTC-USDT-SWAP", "instFamily": "BTC-USDT", "ctVal": "0.01"},
            {"instId": "BTC-USD-SWAP", "instFamily": "BTC-USD", "ctVal": "100"}]}
        self.assertEqual(lf.fetch_ct_vals(getter=lambda u: payload), {"BTC-USDT": 0.01})


class Universe(unittest.TestCase):
    def test_aliases_and_missing(self):
        ct = {"BTC-USDT": 0.01, "FIL-USDT": 1.0, "TRUMP-USDT": 1.0, "PUMP-USDT": 1.0}
        got = lf.universe(["BTC_USDT", "FILECOIN_USDT", "TRUMPOFFICIAL_USDT", "PUMPFUN_USDT", "NOPE_USDT"], ct)
        self.assertEqual(got, ["BTC-USDT", "FIL-USDT", "PUMP-USDT", "TRUMP-USDT"])

    def test_frozen_from_prior_meta(self):
        with tempfile.TemporaryDirectory() as t:
            prior, out = Path(t) / "p", Path(t) / "o"
            prior.mkdir()
            (prior / "meta.json").write_text(json.dumps({"universe": ["BTC-USDT"], "ct_vals": {"BTC-USDT": 0.01},
                                                         "first_run_utc": "x"}), encoding="utf-8")
            seen = []
            lf.run(CFG, ["BTC_USDT", "ETH_USDT"], prior, out, now=datetime(2026, 10, 12, tzinfo=timezone.utc),
                   liq_fetcher=lambda fam: seen.append(fam) or [],
                   ct_fetcher=lambda: self.fail("ct_vals must not be refetched"))
            self.assertEqual(seen, ["BTC-USDT"])
            self.assertEqual(json.loads((out / "meta.json").read_text())["universe"], ["BTC-USDT"])


class Ledger(unittest.TestCase):
    def test_dedupe_and_sort(self):
        a, b = row(200), row(100)
        self.assertEqual([r["ts"] for r in lf.merge([a], [b, dict(a)])], [100, 200])

    def test_notional(self):
        got = lf.with_notional([{"instFamily": "BTC-USDT", "ts": 1, "side": "sell", "posSide": "long", "sz": 5.0, "bkPx": 200.0}],
                               {"BTC-USDT": 0.01})
        self.assertAlmostEqual(got[0]["notional_usd"], 10.0)


class Daily(unittest.TestCase):
    def full_polls(self, gap_h=8, start_h=-8, end_h=48):
        return [poll(D0 + h * H, **{"BTC-USDT": True}) for h in range(start_h, end_h, gap_h)]

    def test_long_short_split(self):
        rows = [row(D0 + H, pos="long", notional=30.0), row(D0 + 2 * H, pos="short", notional=7.0),
                row(D0 + 3 * H, pos="long", notional=5.0)]
        d = [x for x in lf.daily(rows, self.full_polls()) if x["day"] == "2026-10-12"][0]
        self.assertEqual((d["long_liq_usd"], d["short_liq_usd"], d["n"]), (35.0, 7.0, 3))
        self.assertTrue(d["complete"])

    def test_gap_over_16h_incomplete(self):
        polls = [poll(D0 + h * H, **{"BTC-USDT": True}) for h in (-2, 1, 18, 26)]
        d = [x for x in lf.daily([], polls) if x["day"] == "2026-10-12"][0]
        self.assertFalse(d["complete"])

    def test_failed_poll_breaks_completeness_and_edges(self):
        polls = self.full_polls()
        for p in polls:
            if D0 + 2 * H <= p["ts"] <= D0 + 16 * H:
                p["ok"]["BTC-USDT"] = False
        d = [x for x in lf.daily([], polls) if x["day"] == "2026-10-12"][0]
        self.assertFalse(d["complete"])
        # no poll before day start -> incomplete
        d2 = [x for x in lf.daily([], self.full_polls(start_h=0)) if x["day"] == "2026-10-12"][0]
        self.assertFalse(d2["complete"])


class Report(unittest.TestCase):
    def test_status_flip_and_no_hypothesis_fields(self):
        meta = {"universe": ["BTC-USDT"], "first_run_utc": "x"}
        pre = lf.build_report(CFG, [], [], [], meta, now=datetime(2026, 10, 11, 23, tzinfo=timezone.utc))
        on = lf.build_report(CFG, [], [], [], meta, now=datetime(2026, 10, 12, tzinfo=timezone.utc))
        self.assertEqual((pre["status"], on["status"]), ("PRE_START", "COLLECTING"))
        self.assertEqual(on["review_after_days"], 180)
        self.assertFalse(any(v for k, v in on["claims"].items() if k.endswith("_authorized")))
        text = json.dumps(on).lower()
        for banned in ("t_stat", "tstat", "coef", "regression", "h1", "h2", "pvalue", "beta", "sharpe"):
            self.assertNotIn(banned, text)

    def test_run_end_to_end_mocked(self):
        now = datetime(2026, 10, 12, 6, tzinfo=timezone.utc)
        raw = [{"instFamily": "BTC-USDT", "ts": D0 + H, "side": "sell", "posSide": "long", "sz": 10.0, "bkPx": 100.0}]
        with tempfile.TemporaryDirectory() as t:
            rep = lf.run(CFG, ["BTC_USDT"], None, Path(t), now=now, liq_fetcher=lambda f: list(raw),
                         ct_fetcher=lambda: {"BTC-USDT": 0.01})
            rows = [json.loads(x) for x in (Path(t) / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(rep["ledger_rows"], 1)
        self.assertAlmostEqual(rows[0]["notional_usd"], 10.0)


if __name__ == "__main__":
    unittest.main()
