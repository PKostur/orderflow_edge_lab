# MEXC Futures order-flow recorder

This path records public MEXC Futures trades and price-level depth for research. It does not use API keys and does not contain live order transmission.

## Why this path

For ENA/USDT and BTC/USDT research, using the venue's own public market-data streams avoids trying to infer MEXC behavior from another market or from an undocumented desktop bridge. The recorder stores the raw exchange messages before deriving any features so future research can be replayed from immutable source data.

MEXC's current Futures API documentation states that public market endpoints do not require authentication, that the Futures REST base URL is `https://api.mexc.com`, and that the native Futures WebSocket endpoint is `wss://contract.mexc.com/edge`. The WebSocket host is configurable because MEXC documents REST and WebSocket endpoints separately.

Official references:

- https://www.mexc.com/api-docs/futures/integration-guide
- https://www.mexc.com/api-docs/futures/websocket-api/native-ws-endpoint
- https://www.mexc.com/api-docs/futures/websocket-api/deal
- https://www.mexc.com/api-docs/futures/websocket-api/order-book-depth
- https://www.mexc.com/api-docs/futures/websocket-api/incremental-order-book-maintenance-mechanism

## Install

```bash
python -m pip install -e .
```

The only added runtime dependency is the `websockets` client library. REST snapshots use Python's standard library.

## Record ENA and BTC

The default symbols are `ENA_USDT` and `BTC_USDT`:

```bash
orderflow-mexc-record
```

Record for one hour:

```bash
orderflow-mexc-record --duration-seconds 3600
```

Choose symbols explicitly:

```bash
orderflow-mexc-record \
  --symbol ENA_USDT \
  --symbol BTC_USDT \
  --duration-seconds 3600
```

Output is written under `data/mexc_orderflow/` by default:

```text
YYYYMMDDTHHMMSSZ_mexc_raw.jsonl
YYYYMMDDTHHMMSSZ_mexc_raw.jsonl.manifest.json
YYYYMMDDTHHMMSSZ_mexc_features.jsonl
YYYYMMDDTHHMMSSZ_mexc_features.jsonl.manifest.json
```

Files are created with exclusive-create mode. Existing recordings are never overwritten. A SHA-256 manifest is written when a file closes cleanly.

## What is recorded

The raw file contains:

- a session record declaring symbols and endpoints;
- full REST depth snapshots;
- every received public WebSocket message;
- depth-gap observations;
- REST depth-commit responses used for recovery;
- reconnect events.

No username, password, API key, token, account data, order, or position data is requested.

The recorder subscribes to MEXC `push.deal` and `push.depth` channels. The deal stream supplies trade price, quantity, exchange side, transaction ID when present, and timestamps. MEXC documents `T=1` as buy and `T=2` as sell. Depth is pushed as price-level updates with monotonically increasing versions.

## Order-book synchronization

The local book follows MEXC's documented maintenance mechanism:

1. fetch a full depth snapshot;
2. save its `version`;
3. subscribe to incremental depth;
4. require each new version to equal `local_version + 1`;
5. if a gap appears, fetch `/depth_commits/{symbol}/1000` and apply only contiguous missing commits;
6. if commits cannot bridge the gap, replace the local book with a fresh full snapshot;
7. stop rather than continue from an uncertain book if continuity still cannot be established.

MEXC depth quantities are absolute values. Quantity `0` deletes a level. The code sorts recovery commits by version before applying them because the maintenance instructions require ascending application even though API examples may display newer versions first.

## Derived features

The feature file currently contains causal, price-level features that can be reconstructed from the raw file:

- exchange-side buy and sell volume;
- rolling CVD;
- rolling trade count and trade velocity;
- best bid and ask;
- spread;
- top-of-book microprice;
- configurable top-N book imbalance;
- bid and ask liquidity added;
- bid and ask liquidity pulled;
- depth-flow imbalance from absolute level changes.

These are measurements, not trading signals. Liquidity reductions cannot by themselves distinguish cancellation from execution, so the recorder deliberately does not label every pull as a fill or every price interaction as absorption.

## Replay

Rebuild features without touching the network:

```bash
orderflow-mexc-replay data/mexc_orderflow/<raw-file>.jsonl
```

If the raw file has a manifest, replay verifies its SHA-256 before processing. Sequence gaps must be resolved by recorded recovery data or replay fails closed.

You can change research feature parameters during replay without changing the raw source:

```bash
orderflow-mexc-replay data/mexc_orderflow/<raw-file>.jsonl \
  --trade-window-seconds 5 \
  --imbalance-levels 20
```

Changing these parameters creates a new feature artifact. It does not alter the immutable raw recording.

## Important limitations

This is price-level depth, not CME-style market-by-order data. The feed shows aggregate quantity at each price level and an order-count field. It does not expose a documented stable identifier for every individual resting order.

Therefore the current implementation can measure CVD, L2 imbalance, liquidity changes, microprice and trade/depth interactions, but true queue-position reconstruction is out of scope. Sweep and absorption classifiers should be added only after enough raw data has been collected to define and validate them causally.

The first useful research objective is to record ENA and BTC continuously, then freeze a feature definition and evaluate it on future data that was not used to design the rule. No positive result from previously inspected data should be treated as independent out-of-sample evidence.
