# Orderflow Edge Lab

Research-first infrastructure for short-horizon order-flow strategy research and paper execution.

**Version 1.0: research and manual paper release.** See the
[release guide](docs/RELEASE_1_0.md) for installation, verification, and operational boundaries.

## Safety boundary

This repository does not contain live broker or exchange order transmission. The execution layer is limited to paper and explicit approval workflows. No strategy is considered to have a profitable edge unless it survives genuine out-of-sample validation after realistic costs on data that was not used for discovery or tuning.

## Current priorities

1. Use MEXC public Futures trades and price-level depth as the primary zero-additional-cost data path for ENA/BTC crypto research.
2. Preserve DeepCharts/dxFeed as an optional path where the entitlement permits supported export or external API access.
3. Keep strict separation between discovery, validation, and final holdout data.
4. Fail closed on stale, malformed, incomplete, duplicated, crossed, sequence-gapped, or low-quality market data.
5. Make research runs reproducible with frozen configuration, immutable raw inputs, hashes, and run manifests.
6. Paper trade and approval-test before any future broker or exchange integration is considered.

## MEXC Futures order flow

The repository can record public MEXC Futures `push.deal` and incremental `push.depth` streams for `ENA_USDT`, `BTC_USDT`, or other Futures symbols without API keys.

```bash
python -m pip install -e .
orderflow-mexc-record --symbol ENA_USDT --symbol BTC_USDT
```

The recorder maintains a synchronized local L2 book using full snapshots, depth versions, commit recovery, and fail-closed snapshot fallback. Raw JSONL is exclusive-create and receives a SHA-256 manifest on clean close. A separate feature stream contains rolling CVD, buy/sell volume, trade velocity, spread, microprice, top-N book imbalance, liquidity adds/pulls, and depth-flow imbalance.

Replay an existing raw capture without touching the network:

```bash
orderflow-mexc-replay data/mexc_orderflow/<raw-file>.jsonl
```

See [MEXC Futures order-flow recorder](docs/MEXC_ORDERFLOW.md).

## dxFeed and DeepCharts

Credentials must remain local. Never commit them or paste them into chat.

The repository supports two paths using existing access:

1. A normalized adapter for DeepCharts or dxFeed trade/BBO exports.
2. An entitlement probe scaffold for external dxFeed access without assuming a DeepCharts login automatically grants API entitlement.

The probe supports HTTPS Basic or bearer authentication when provided by the
existing subscription. A platform-issued username does not determine API rights.
See [data access and quality checks](docs/DXFEED.md).

## Operator tools

- [Manual paper control and checkpoint recovery](docs/DEPLOYMENT.md): inspect,
  submit, approve, reject, close, and halt paper execution.
- [Future-observation audit](docs/RESEARCH_PROTOCOL.md): verify supplied records
  against frozen rules and produce hashed, descriptive reports without certifying
  out-of-sample evidence or deployment eligibility.

Local export validation, MEXC public market-data collection, replay, and engineering tests require no paid API or external service beyond the user's existing network access. Real market-data availability and exchange coverage remain vendor-controlled.

## Research validity

- Previously inspected data is considered spent for independent validation.
- Parameters are frozen before a validation window is opened.
- A final holdout is not exported by an unrevealed research run.
- Transaction costs, spread, slippage assumptions, and ambiguous same-bar outcomes must be explicit.
- Attractive synthetic or in-sample results are engineering evidence only.
- One positive validation window is not enough for deployment.

## Execution lifecycle

```text
signal -> TradeIntent -> data/risk checks -> approval queue -> paper fill -> paper close -> journal
```

The manual submission interface blocks failed data-quality or risk checks.
Direct PaperEngine callers must supply upstream data/signal validation.

## Live trading

Live order transmission is deliberately absent. Any future live adapter should be introduced only after sufficient fresh out-of-sample evidence, paper/shadow reliability evidence, and broker/exchange reconciliation testing exist.
