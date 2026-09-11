# MEXC Futures order-flow recorder

This path records public MEXC Futures trades and price-level depth for research. It does not use API keys and does not contain live order transmission.

## Why this path

For ENA/USDT and BTC/USDT research, using the venue's own public market-data streams avoids trying to infer MEXC behavior from another market or from an undocumented desktop bridge. The recorder stores raw exchange messages before deriving features so research can be replayed from immutable source data.

Official MEXC Futures documentation:

- https://mexcdevelop.github.io/apidocs/contract_v1_en/
- https://www.mexc.com/api-docs/futures/integration-guide
- https://www.mexc.com/api-docs/futures/websocket-api/native-ws-endpoint
- https://www.mexc.com/api-docs/futures/websocket-api/deal
- https://www.mexc.com/api-docs/futures/websocket-api/order-book-depth

The current native Futures WebSocket endpoint is `wss://contract.mexc.com/edge`. Public market endpoints do not require authentication.

## Install

```bash
python -m pip install -e .
```

## Record ENA and BTC

The default symbols are `ENA_USDT` and `BTC_USDT`:

```bash
orderflow-mexc-record
```

A short validation capture:

```bash
orderflow-mexc-record --duration-seconds 120
```

Output is written under `data/mexc_orderflow/` by default:

```text
YYYYMMDDTHHMMSSZ_mexc_raw.jsonl
YYYYMMDDTHHMMSSZ_mexc_raw.jsonl.manifest.json
YYYYMMDDTHHMMSSZ_mexc_features.jsonl
YYYYMMDDTHHMMSSZ_mexc_features.jsonl.manifest.json
```

Files are exclusive-create and never overwritten. A SHA-256 sidecar is written when each file closes cleanly.

## Correct MEXC depth schema

MEXC depth levels are interpreted as:

```text
[price, contract volume, order count]
```

For example, `[77318.5, 210251, 4]` means price `77318.5`, contract volume `210251`, and order count `4`.

The recorder uses contract volume for:

- best bid/ask volume;
- top-N book imbalance;
- microprice weighting;
- liquidity added/pulled;
- depth-flow imbalance.

The feature file keeps `best_bid_qty` and `best_ask_qty` as backward-compatible aliases, but the canonical fields are `best_bid_contract_volume` and `best_ask_contract_volume`.

## Depth synchronization

MEXC enables merged incremental depth by default unless `compress` is explicitly disabled. Recorder schema v2 sends:

```json
{
  "method": "sub.depth",
  "param": {
    "symbol": "BTC_USDT",
    "compress": false
  }
}
```

The book engine is still range-aware so old captures and any merged messages remain replayable. For a ranged update:

```text
begin <= local_version + 1 <= end
version == end
```

is treated as continuous. A real gap exists only when `begin > local_version + 1`.

The connection sequence is also hardened:

1. connect the WebSocket;
2. subscribe to deals and depth;
3. fetch REST snapshots while WebSocket updates buffer;
4. process the queued updates against the snapshot;
5. ignore stale updates whose `end <= snapshot_version`;
6. apply continuous single-version or merged-range updates;
7. recover only genuine gaps using depth commits;
8. fall back to a fresh snapshot if commits cannot bridge the gap;
9. stop rather than continue from an uncertain book.

This removes the snapshot-before-subscription blind window.

## Depth continuity counters

Every depth feature carries cumulative counters for its symbol:

- `depth_messages_seen`
- `compressed_depth_ranges_seen`
- `true_depth_gaps_seen`
- `stale_depth_messages_seen`

The recorder also writes a `session_summary` with these counters. Merged ranges are not counted as packet loss.

## Trade fields

`T=1` is treated as aggressive buy and `T=2` as aggressive sell for CVD and buy/sell volume.

MEXC documentation currently uses inconsistent wording for the `M` field between REST and WebSocket sections. The recorder therefore preserves it neutrally as:

```text
exchange_m_flag
```

and does not infer self-trade or auto-transaction semantics from it.

## Derived features

The feature stream includes:

- exchange-side buy and sell volume;
- rolling CVD;
- rolling trade count and velocity;
- best bid and ask;
- best bid/ask contract volume;
- spread;
- top-of-book microprice;
- configurable top-N book imbalance;
- bid/ask liquidity added;
- bid/ask liquidity pulled;
- depth-flow imbalance;
- depth range metadata and continuity counters.

These are measurements, not trading signals. A reduction in resting volume cannot by itself distinguish cancellation from execution.

## Replay

Rebuild features without touching the network:

```bash
orderflow-mexc-replay data/mexc_orderflow/<raw-file>.jsonl
```

Replay verifies the raw SHA-256 when a manifest exists.

Recorder schema v2 uses the corrected depth schema and continuity model. Replay also supports recorder schema v1. In v1 files, recovery commits and fallback snapshots created only because the old implementation misclassified valid merged ranges are ignored unless a genuine range-aware gap is pending.

This means the first ENA/BTC sample can be reprocessed from its original immutable raw payloads instead of being discarded.

A replay summary reports the final depth continuity counters.

## Important limitations

This is price-level depth, not CME-style market-by-order data. It exposes aggregate contract volume at each price and an order-count field, but not a documented stable identifier for every individual resting order.

Therefore this path can support CVD, L2 imbalance, liquidity changes, microprice, sweeps/absorption proxies, and BTC/ENA cross-market research, but not true queue-position reconstruction.

No positive result from previously inspected data should be treated as independent out-of-sample evidence.
