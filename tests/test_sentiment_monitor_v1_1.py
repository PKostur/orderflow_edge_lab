from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from orderflow_edge_lab.sentiment_monitor import SentimentMonitorError
from orderflow_edge_lab.sentiment_monitor_v1_1 import (
    merge_sentiment_ledgers_v1_1,
    monitor_sentiment_v1_1,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads((ROOT / "config" / "sentiment_monitor_v1_1.json").read_text(encoding="utf-8"))


def _rss(items: list[tuple[str, str, str]]) -> bytes:
    rows = "".join(
        f"<item><title>{title}</title><link>{link}</link><pubDate>{published}</pubDate></item>"
        for title, published, link in items
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>{rows}</channel></rss>'.encode("utf-8")


class SentimentMonitorV11Tests(unittest.TestCase):
    def test_fixed_universe_contains_frozen_strategy_symbols(self):
        universe = PROTOCOL["observation_universe"]
        expected = {"ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "BNB_USDT", "ADA_USDT", "LINK_USDT", "SUI_USDT", "ENA_USDT"}
        self.assertEqual(set(universe["strategy_conditioning_symbols"]), expected)
        self.assertEqual(set(universe["readiness_symbols"]), expected)
        self.assertEqual(universe["context_only_symbols"], ["BTC_USDT"])
        self.assertFalse(universe["strategy_pnl_used_for_universe_selection"])
        self.assertFalse(universe["dynamic_cross_pair_panel_used_for_readiness"])

    def test_btc_context_event_does_not_count_toward_readiness(self):
        event = int(datetime(2026, 9, 13, 22, 10, tzinfo=timezone.utc).timestamp())
        now = int(datetime(2026, 9, 13, 23, 20, tzinfo=timezone.utc).timestamp())
        def series(base: float) -> dict[int, float]:
            return {
                event - 900: base * 0.995,
                event: base,
                event + 300: base * 1.002,
                event + 900: base * 1.003,
                event + 1800: base * 1.004,
                event + 3600: base * 1.005,
            }
        feed_payloads = {
            "coindesk": _rss([
                ("Bitcoin rally accelerates after approval", "Sun, 13 Sep 2026 22:10:00 +0000", "https://example.test/btc"),
                ("Solana upgrade wins approval", "Sun, 13 Sep 2026 22:10:00 +0000", "https://example.test/sol"),
            ]),
            "decrypt": _rss([]),
        }
        report = monitor_sentiment_v1_1(
            PROTOCOL,
            now_epoch_seconds=now,
            feed_payloads=feed_payloads,
            candle_series={"BTC_USDT": series(200.0), "SOL_USDT": series(100.0)},
        )
        self.assertEqual(report["summary"]["event_count"], 2)
        self.assertEqual(report["summary"]["readiness_event_count"], 1)
        self.assertEqual(report["summary"]["distinct_conditioning_symbols"], ["SOL_USDT"])
        self.assertFalse(report["summary"]["state_screen_ready"])
        self.assertIn("BTC_USDT", report["summary"]["current_symbol_state"])
        self.assertIn("SOL_USDT", report["summary"]["current_symbol_state"])

    def test_v1_ledger_cannot_be_merged_into_v1_1(self):
        claims = {
            "research_only": True,
            "observational_only": True,
            "causal_effect_established": False,
            "sentiment_is_strategy_filter": False,
            "eligible_as_strategy_filter": False,
            "v1_evidence_reused": False,
            "profitable_edge_established": False,
            "verified_out_of_sample_evidence": False,
            "live_order_transmission_supported": False,
        }
        current = {"protocol_name": "sentiment-monitor-v1.1", "events": [], "claims": claims}
        prior = {"protocol_name": "sentiment-monitor-v1", "events": [], "claims": claims}
        with self.assertRaises(SentimentMonitorError):
            merge_sentiment_ledgers_v1_1(prior, current, PROTOCOL)


if __name__ == "__main__":
    unittest.main()
