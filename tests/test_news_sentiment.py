from __future__ import annotations

from datetime import datetime, timezone
import unittest

from orderflow_edge_lab.news_sentiment import Scorer, collect, daily_aggregates, enrich, load_config, merge, parse_feed

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Bitcoin surges to record high as ETF inflows jump</title><link>https://x.test/a</link>
<description>&lt;p&gt;Solana also rallied.&lt;/p&gt;</description><pubDate>Wed, 30 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>Exchange hacked, $ETH dumped after exploit</title><link>https://x.test/b</link><pubDate>Wed, 30 Sep 2026 12:00:00 +0000</pubDate></item>
</channel></rss>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Is XRP not bullish anymore?</title><link href="https://reddit.test/c"/><updated>2026-10-01T01:00:00+00:00</updated>
<content type="html">thoughts</content></entry></feed>"""


class NewsSentimentTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        self.scorer = Scorer(self.cfg)

    def test_frozen_before_collection_and_no_x(self):
        self.assertEqual(self.cfg["status"], "FROZEN_BEFORE_COLLECTION")
        urls = list(self.cfg["sources"]["news_rss"].values()) + list(self.cfg["sources"]["social_rss"].values())
        self.assertFalse(any("twitter.com" in u or "x.com" in u for u in urls))
        self.assertEqual(self.cfg["strategies"]["prospective_start_utc"], "2026-11-01T00:00:00Z")

    def test_parse_rss_and_atom(self):
        a = parse_feed(RSS, "demo", "news", "2026-10-01T00:00:00+00:00")
        self.assertEqual(len(a), 2)
        self.assertEqual(a[0]["published_utc"], "2026-09-30T10:00:00+00:00")
        self.assertEqual(a[0]["summary"], "Solana also rallied.")
        b = parse_feed(ATOM, "reddit", "social", "2026-10-01T02:00:00+00:00")
        self.assertEqual(b[0]["link"], "https://reddit.test/c")
        self.assertEqual(b[0]["published_utc"], "2026-10-01T01:00:00+00:00")

    def test_scoring_signs_and_negation(self):
        self.assertGreater(self.scorer.score("Bitcoin surges to record high as ETF inflows jump")[0], 0.5)
        self.assertLess(self.scorer.score("Exchange hacked, ETH dumped after exploit")[0], -0.5)
        self.assertLess(self.scorer.score("XRP is not bullish anymore")[0], 0)
        self.assertEqual(self.scorer.score("Weekly market recap")[0], 0.0)

    def test_coin_tagging_avoids_ambiguous_tickers(self):
        self.assertEqual(self.scorer.coins("Bitcoin and Solana rally; $ETH lags"), ["BTC", "ETH", "SOL"])
        self.assertEqual(self.scorer.coins("An OP ed about the ONE thing AR analysts say"), [])
        self.assertEqual(self.scorer.coins("Optimism upgrade and AVAX news"), ["AVAX", "OP"])

    def test_merge_dedupes_and_aggregates(self):
        items = enrich(parse_feed(RSS, "demo", "news", "2026-10-01T00:00:00+00:00"), self.scorer)
        ledger = merge(items, items + enrich(parse_feed(ATOM, "reddit", "social", "t"), self.scorer))
        self.assertEqual(len(ledger), 3)
        agg = daily_aggregates(ledger)
        self.assertEqual(agg["market"]["2026-09-30"]["items"], 2)
        self.assertEqual(agg["market"]["2026-10-01"]["social_items"], 1)
        self.assertEqual(agg["coins"]["BTC"]["2026-09-30"]["mentions"], 1)

    def test_collect_records_failures_without_raising(self):
        def fake(url, ua):
            if "reddit" in url:
                raise OSError("blocked")
            return RSS
        items, status = collect(self.cfg, now=datetime(2026, 10, 1, tzinfo=timezone.utc), fetcher=fake, pause=0)
        self.assertFalse(status["reddit_cryptocurrency"]["ok"])
        self.assertTrue(status["coindesk"]["ok"])
        self.assertEqual(len(items), 2 * len(self.cfg["sources"]["news_rss"]))


if __name__ == "__main__":
    unittest.main()
