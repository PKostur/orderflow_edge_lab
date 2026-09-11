# MEXC capture validation

MEXC Futures incremental depth can be merged by the server. The official contract WebSocket documentation states that incremental depth merging is enabled by default and that `compress: false` disables it.

For research that treats `version` as a contiguous price-level book sequence, record with the strict command:

```bash
orderflow-mexc-record --symbol ENA_USDT --symbol BTC_USDT --duration-seconds 120
```

The strict recorder requests `compress: false` and records `depth_merge_requested: false` in session provenance.

After every capture, run:

```bash
orderflow-mexc-audit \
  data/mexc_orderflow/<stamp>_mexc_raw.jsonl \
  data/mexc_orderflow/<stamp>_mexc_features.jsonl
```

The audit verifies both SHA-256 manifests and fails closed on excessive sequence gaps, low depth-apply coverage, crossed books, insufficient duration, or missing trades. A passing result establishes transport and reconstruction quality only. It does not establish a profitable strategy or independent out-of-sample evidence.

## September 11, 2026 sample finding

The first two-minute ENA/BTC capture was useful as an engineering test but failed the depth-integrity standard. It contained 195 sequence-gap recoveries. Only about 33% of ENA depth messages and about 7.8% of BTC depth messages were directly applied. Trade prints remain useful for exploratory aggressive-flow statistics, but liquidity add/pull, depth-flow imbalance, and related order-book features from that capture must not be used as research evidence.

The likely cause is that the initial recorder subscribed without explicitly disabling MEXC's default incremental-depth merging. The strict recorder corrects that subscription setting. Re-collect and audit before using depth-derived features.
