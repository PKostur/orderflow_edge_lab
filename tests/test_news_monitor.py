from __future__ import annotations

from datetime import datetime, timezone
import unittest

from orderflow_edge_lab.news_monitor import NewsMonitorConfig, event_behavior, monitor_news, parse_feed


RSS = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
<title>Solana upgrade draws renewed attention from traders</title>
<link>https://example.test/solana-upgrade</link>
<pubDate>Sat, 12 Sep 2026 12:00:00 +0000</pubDate>
</item>
</channel></rss>'''
EMPTY_RSS = b'''<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel></channel></rss>'''


class NewsMonitorTests(unittest.TestCase):
    def test_feed_parser_keeps_headline_metadata_not_article_body(self):
        rows = parse_feed("coindesk", RSS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "coindesk")
        self.assertIn("Solana", rows[0]["title"])
        self.assertNotIn("body", rows[0])
        self.assertEqual(len(rows[0]["event_id"]), 64)

    def test_event_behavior_reports_coin_btc_relative_move(self):
        event = int(datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc).timestamp())
        coin = {
            event - 900: 99.0,
            event: 100.0,
            event + 300: 101.0,
            event + 900: 102.0,
            event + 1800: 98.0,
            event + 3600: 103.0,
        }
        btc = {
            event - 900: 199.0,
            event: 200.0,
            event + 300: 200.5,
            event + 900: 201.0,
            event + 1800: 200.0,
            event + 3600: 202.0,
        }
        report = event_behavior(coin, btc, event)
        self.assertEqual(report["status"], "ok")
        self.assertAlmostEqual(report["horizons"]["5m"]["coin_return_bps"], 100.0, places=6)
        self.assertAlmostEqual(report["horizons"]["5m"]["btc_return_bps"], 25.0, places=6)
        self.assertAlmostEqual(report["horizons"]["5m"]["coin_minus_btc_return_bps"], 75.0, places=6)

    def test_monitor_is_observational_and_matches_conservative_aliases(self):
        event = int(datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc).timestamp())
        now = int(datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc).timestamp())
        sol = {
            event - 900: 99.0,
            event: 100.0,
            event + 300: 101.0,
            event + 900: 102.0,
            event + 1800: 103.0,
            event + 3600: 104.0,
        }
        btc = {
            event - 900: 199.0,
            event: 200.0,
            event + 300: 200.2,
            event + 900: 200.4,
            event + 1800: 200.6,
            event + 3600: 200.8,
        }
        report = monitor_news(
            ["SOL_USDT", "BTC_USDT", "ENA_USDT"],
            NewsMonitorConfig(),
            now_epoch_seconds=now,
            feed_payloads={"coindesk": RSS, "cointelegraph": EMPTY_RSS},
            candle_series={"SOL_USDT": sol, "BTC_USDT": btc},
        )
        self.assertEqual(report["event_count"], 1)
        self.assertEqual(report["events"][0]["symbol"], "SOL_USDT")
        self.assertFalse(report["claims"]["news_is_strategy_filter"])
        self.assertFalse(report["claims"]["profitable_edge_established"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])


if __name__ == "__main__":
    unittest.main()
