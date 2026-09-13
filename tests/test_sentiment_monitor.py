from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from orderflow_edge_lab.sentiment_monitor import merge_sentiment_ledgers, monitor_sentiment, score_headline


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((ROOT / "config" / "sentiment_monitor_v1.json").read_text(encoding="utf-8"))


def _rss(title: str, published: str, link: str) -> bytes:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>{title}</title><link>{link}</link><pubDate>{published}</pubDate>
</item></channel></rss>'''.encode("utf-8")


class SentimentMonitorTests(unittest.TestCase):
    def test_scoring_is_deterministic_and_longest_phrase_wins(self):
        scoring = PROTOCOL["scoring"]
        bullish = score_headline(
            "Bitcoin ETF sees record inflows after approval",
            scoring["positive_phrase_weights"],
            scoring["negative_phrase_weights"],
            neutral_abs_score_below=scoring["neutral_abs_score_below"],
        )
        self.assertEqual(bullish["label"], "bullish")
        phrases = {row["phrase"] for row in bullish["matched_terms"]}
        self.assertIn("record inflows", phrases)
        self.assertNotIn("inflows", phrases)
        bearish = score_headline(
            "Solana suffers exploit and outage",
            scoring["positive_phrase_weights"],
            scoring["negative_phrase_weights"],
            neutral_abs_score_below=scoring["neutral_abs_score_below"],
        )
        self.assertEqual(bearish["label"], "bearish")
        neutral = score_headline(
            "Solana developers discuss ecosystem metrics",
            scoring["positive_phrase_weights"],
            scoring["negative_phrase_weights"],
            neutral_abs_score_below=scoring["neutral_abs_score_below"],
        )
        self.assertEqual(neutral["label"], "neutral")

    def test_forward_monitor_is_observational_and_excludes_preboundary_news(self):
        event = int(datetime(2026, 9, 13, 19, 0, tzinfo=timezone.utc).timestamp())
        old_event = int(datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc).timestamp())
        now = int(datetime(2026, 9, 13, 20, 15, tzinfo=timezone.utc).timestamp())
        sol = {
            old_event: 99.0,
            event - 900: 99.5,
            event: 100.0,
            event + 300: 101.0,
            event + 900: 101.5,
            event + 1800: 102.0,
            event + 3600: 103.0,
        }
        btc = {
            old_event: 199.0,
            event - 900: 199.5,
            event: 200.0,
            event + 300: 200.2,
            event + 900: 200.4,
            event + 1800: 200.6,
            event + 3600: 200.8,
        }
        report = monitor_sentiment(
            ["SOL_USDT", "BTC_USDT"],
            PROTOCOL,
            now_epoch_seconds=now,
            feed_payloads={
                "coindesk": _rss(
                    "Solana upgrade wins approval from validators",
                    "Sun, 13 Sep 2026 19:00:00 +0000",
                    "https://example.test/new",
                ),
                "cointelegraph": _rss(
                    "Solana upgrade announced before the evidence boundary",
                    "Sun, 13 Sep 2026 18:00:00 +0000",
                    "https://example.test/old",
                ),
            },
            candle_series={"SOL_USDT": sol, "BTC_USDT": btc},
        )
        self.assertEqual(report["summary"]["event_count"], 1)
        self.assertEqual(report["events"][0]["sentiment"]["label"], "bullish")
        self.assertFalse(report["summary"]["state_screen_ready"])
        self.assertFalse(report["claims"]["sentiment_is_strategy_filter"])
        self.assertFalse(report["claims"]["eligible_as_strategy_filter"])
        self.assertFalse(report["claims"]["live_order_transmission_supported"])

    def test_cumulative_ledger_deduplicates_and_prefers_more_complete_event(self):
        base = {
            "event_id": "abc",
            "symbol": "SOL_USDT",
            "source": "coindesk",
            "title": "Solana upgrade wins approval",
            "published_epoch_seconds": int(datetime(2026, 9, 13, 19, 0, tzinfo=timezone.utc).timestamp()),
            "sentiment": {"score": 0.5, "label": "bullish"},
            "behavior": {"horizons": {"5m": {"complete": False}}},
        }
        complete = {
            **base,
            "behavior": {
                "horizons": {
                    "5m": {
                        "complete": True,
                        "coin_minus_btc_return_bps": 20.0,
                        "coin_return_bps": 30.0,
                    }
                }
            },
        }
        claims = {
            "research_only": True,
            "observational_only": True,
            "causal_effect_established": False,
            "sentiment_is_strategy_filter": False,
            "eligible_as_strategy_filter": False,
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
            "live_order_transmission_supported": False,
        }
        prior = {"events": [base], "claims": claims}
        current = {"events": [complete], "claims": claims}
        now = int(datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc).timestamp())
        ledger = merge_sentiment_ledgers(prior, current, PROTOCOL, now_epoch_seconds=now)
        self.assertEqual(len(ledger["events"]), 1)
        self.assertTrue(ledger["events"][0]["behavior"]["horizons"]["5m"]["complete"])
        self.assertFalse(ledger["summary"]["state_screen_ready"])


if __name__ == "__main__":
    unittest.main()
