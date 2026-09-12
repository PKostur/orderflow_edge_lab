# Order-Flow Trading Research Project Context

## Purpose

This project is a research-first automated trading system centered on ENA_USDT and BTC_USDT order flow. The goal is to discover whether short-horizon order-flow information can improve executable expectancy after spread, fees, slippage, and realistic execution constraints. Do not treat engineering success or in-sample backtest results as evidence of profitability.

Primary repository: `PKostur/orderflow_edge_lab`.

## Prior strategy context

The original discretionary edge hypothesis came from 1-minute ENA price behavior around Bollinger Bands. Historical work later added:

- BTC directional/context confirmation;
- 15-minute and 1-hour higher-timeframe bias;
- fixed RR comparisons including 1:1 and roughly 2:1 to 3:1;
- explicit next-bar execution and transaction-cost scenarios;
- MEXC futures data and public order-flow capture;
- DeepCharts/dxFeed as the preferred zero-additional-cost professional data source when available.

The old price/HTF system showed some positive gross behavior in places, but transaction costs materially weakened or erased expectancy. Therefore order flow is being tested primarily as a selective filter and timing signal, not assumed to be a standalone profitable strategy.

## Current order-flow research

The repository contains:

- MEXC public futures incremental depth and trade capture;
- sequence-gap detection and recovery;
- causal feature reconstruction using local observation order;
- rolling aggressive buy/sell flow and CVD;
- top-level and top-N book imbalance;
- microprice;
- liquidity additions/pulls and depth-flow imbalance;
- ENA/BTC joint capture;
- spread-aware event backtesting;
- discovery aggregation by independent capture batch;
- DeepCharts/dxFeed export audit/bundling adapters;
- immutable research/candidate/holdout provenance;
- trial accounting and promotion gates;
- approval-bound paper execution only;
- runtime/journal/session integrity controls;
- a deterministic multi-agent hardening report.

## Frozen discovery-v1 protocol

Do not silently retune this protocol batch by batch.

- CVD / trade-flow ratio threshold: absolute 0.25
- Book imbalance threshold: absolute 0.25
- Microprice normalized edge threshold: absolute 0.20
- Minimum trade prints: 5
- Same-family/same-direction cooldown: 2 seconds
- Forward horizons: 1s, 5s, 15s, 30s
- Extra round-trip cost cases: 0 bps, 4 bps, 8 bps
- Long entry crosses ask and future exit hits bid
- Short entry crosses bid and future exit hits ask

Current discovery treats each fresh capture batch as the primary dependence cluster rather than treating every nearby signal as independent evidence.

## Current empirical status

A short clean pilot showed small positive raw microprice response around the 5 to 15 second horizon in one sample, but the effect did not survive the 4 bps additional cost hurdle. This is exploratory only. No profitable edge has been established.

Continuous discovery captures fresh public ENA/BTC order flow under the frozen protocol. Later candidate creation must freeze a new specification before untouched validation data is examined.

## Safety and promotion boundary

Never claim a profitable edge without genuine untouched out-of-sample evidence.

Automatic live exchange/broker transmission remains disabled. Promotion requires, at minimum:

1. frozen candidate specification;
2. untouched holdout evidence;
3. trial-ledger accounting;
4. realistic economics;
5. promotion-gate pass;
6. approval-bound paper/shadow reliability;
7. reconciliation and failure-recovery evidence;
8. explicit user approval before any future live-transmission work.

High leverage used in earlier discretionary experiments is historical context, not a deployment target.

## Multi-agent roles

Use six specialist subagents and keep the lead agent as the adversarial reviewer/release manager:

1. Data integrity: market-data adapters, timestamps, sequences, provenance, causal eligibility.
2. Research validity/statistics: discovery/validation/holdout separation, trial accounting, pseudo-replication, multiple testing.
3. Strategy/backtest validation: signal definitions, fills, fees, spread/slippage, walk-forward/OOS, overfitting.
4. Execution safety/risk: approval-bound paper path, sizing, stale-data rejection, kill switch, reconciliation.
5. Reliability/CI: tests, packaging, scheduled workflows, cross-platform behavior, failure recovery.
6. Observability/deployment: logs, hashes, manifests, runtime identity, operator diagnostics, reproducibility.
7. Lead adversarial/release manager: reconcile findings, challenge unsupported claims, choose the highest-value non-blocked next step, and block unsafe promotion.

## Research priorities

Prioritize:

- accumulating clean independent MEXC discovery batches;
- validating DeepCharts/dxFeed data adapters when real exports are available;
- testing whether order-flow features improve executable expectancy rather than only direction accuracy;
- checking 5 to 15 second predictive decay without threshold-chasing;
- eventually evaluating order flow as a filter for the 1-minute Bollinger + 15m/1h bias + BTC-context setup;
- preserving immutable provenance and untouched validation windows.

Infrastructure hardening is secondary unless a reliability issue blocks trustworthy research.