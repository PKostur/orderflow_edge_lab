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

A user recollection says an earlier TradingView indicator comparison may have favored a 15-minute EMA20/EMA50 crossover/regime. That exact historical result has not been independently recovered from saved artifacts. Preserved project templates more commonly reference EMA9/EMA21, while the preserved August HTF Python test used completed-candle SMA20 price/slope variants on 15m and 1h. Therefore EMA20/EMA50 must be treated as a new hypothesis until directly supported by preserved evidence.

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
- original-versus-reversed paired execution controls;
- effective-exposure stress testing;
- stop-based percent-equity risk testing with executable-path MAE/MFE;
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

## Risk research

When percent equity risk is requested, prefer the stop-based experiment rather than equating leverage with risk. The current exploratory stop model uses recent causally observed BBO structure, a minimum stop distance expressed in current spreads, executable bid/ask path traversal, a 30-second time stop, RR targets 1R/2R/3R, and requested equity-risk levels 0.25% through 5%.

Position exposure must be sized from both the technical stop distance and the stated round-trip transaction-cost hurdle. Do not size from stop distance alone when costs are material relative to the stop. Apply an explicit exposure cap. The experiment reports MAE/MFE and realized drawdown, but does not model liquidation price, maintenance margin, funding, or market impact, so it is not a deployable leverage model.

## Current empirical status

Short clean order-flow pilots have shown small directional asymmetry, especially where original book/microprice signals outperform fully reversed controls, but the effects have not established positive executable expectancy after realistic costs. This is exploratory only. No profitable edge has been established.

A development-only historical test on the already-inspected August ENA/BTC minute data is being used to compare the preserved Bollinger/BTC baseline with a completed-candle 15-minute EMA20/EMA50 direction filter. Because the period has already been inspected in prior work, any favorable result is development evidence only, never OOS.

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
- measuring stop-based MAE/MFE and cost-aware position sizing rather than raw leverage alone;
- evaluating the 15m EMA20/EMA50 idea as a separately labeled development hypothesis;
- eventually evaluating order flow as a filter for the 1-minute Bollinger + HTF bias + BTC-context setup;
- preserving immutable provenance and untouched validation windows.

Infrastructure hardening is secondary unless a reliability issue blocks trustworthy research.
