---
name: orderflow-research
description: Coordinate PKostur/orderflow_edge_lab research with Ruflo memory/swarms while preserving DeerFlow domain context, deterministic evidence gates, and the no-live-transmission boundary.
---

# Orderflow Research with Ruflo

Use this skill for substantial work on the automated trading research project.

## Layering

Ruflo is the meta-harness for memory, swarm/task coordination, routing, hooks, and harness-level review. DeerFlow remains the detailed trading-domain orchestrator. The Python repository remains the executable evidence source.

## Required loop

1. Search Ruflo memory for relevant prior patterns/failures/decisions when Ruflo is available.
2. Read `integrations/deerflow/skills/custom/orderflow-research/references/project-context.md` and `commands.md`.
3. Read `config/regime_research_v1.json` and `docs/REGIME_RESEARCH.md` for indicator/market-condition work.
4. Inspect the latest GitHub/research state before proposing changes.
5. Use the smallest specialized pod that can answer the question. Do not spawn every researcher by default.
6. Execute implementation and testing through the normal repository workflow.
7. Require the deterministic multi-agent release-manager report to be reviewable before merge.
8. Store only a distilled evidence-backed lesson in Ruflo memory after completion.

## Specialized pods

### Market-state pod

- trend-structure researcher: EMA state/slope, ADX, Donchian position, directional efficiency, 15m/1h regime transitions
- volatility-regime researcher: ATR percentile, Bollinger bandwidth, realized volatility, expansion/contraction, volatility-of-volatility
- liquidity-microstructure researcher: spread/depth, microprice, book imbalance, depth-flow, add/pull behavior, update intensity
- aggressive-flow researcher: CVD, signed volume, trade intensity, acceleration, large-trade share, price/flow divergence
- mean-reversion researcher: Bollinger/VWAP displacement, RSI, return z-score, failed breakout/exhaustion
- cross-asset researcher: BTC returns/volatility, flow alignment, rolling correlation/beta and lead-lag
- news-event researcher: public headline timing, conservative symbol attribution, source provenance and subsequent coin/BTC behavior as observational context only
- derivatives-positioning researcher: funding, OI, premium/basis and liquidation context when legitimately available at zero additional cost
- session researcher: UTC session, weekend/weekday, funding/session transition effects

### Economics pod

- execution-economics researcher: spread/fees/slippage/latency/staleness, signal half-life and expected move after friction
- risk-path researcher: MAE/MFE, stops, RR path, exposure caps, drawdown and risk of ruin

### Validation pod

- indicator-orthogonality researcher: redundancy and incremental information among indicator families
- research-validity researcher: dependence, multiple testing, trial accounting, freeze/holdout discipline and OOS claims
- transfer-generalization researcher: stability across independent batches, regimes and other PnL-independently screened pairs
- data-integrity researcher: causality, sequences, adapter correctness, feature eligibility and provenance
- reliability/observability researcher: CI, packaging, workflow failures, hashes, manifests and reproducibility

### Lead

The lead is the adversarial synthesis/release manager. Reconcile evidence rather than votes. Reject indicator proliferation when several features encode the same underlying state.

## Market-state-first rule

Do not begin by asking which indicator has the highest strategy profit factor.

First measure whether a feature predicts a future market-state target such as:

- directionality versus chop;
- volatility expansion versus contraction;
- liquidity stability versus deterioration;
- continuation versus mean reversion.

Only after a feature shows stable state information across independent batches should the strategy be conditioned on that state and evaluated for PF/net expectancy after realistic costs.

## Indicator combination rule

A new indicator should enter a combined regime only if it adds incremental information after already-selected variables or if the interaction was pre-specified for a defensible market-structure reason. Prefer one simple representative from highly redundant indicator clusters.

## Research invariants

Preserve frozen discovery-v1 thresholds, the pre-registered regime-research-v1 families, capture-batch dependence clustering, realistic execution costs, immutable provenance, trial accounting, approval-bound paper execution, and untouched future validation for any candidate promoted from discovery.

Current market-condition work may stratify PF by pre-registered signal-time regimes and transfer the unchanged strategy to PnL-independent screened pairs. A BTC-correlation-diversified panel is permitted only after that compatibility screen and must not use strategy PnL. Do not turn an exploratory bucket into a trading requirement until its readiness gate is satisfied across independent batches.

Public news/event monitoring is an external development context, not a strategy condition. Do not infer causality from headlines, use article outcomes to retune discovery-v1, or make news a trading filter unless a separate specification is frozen before later validation evidence is inspected.

## Safety

Do not claim a profitable edge without genuine untouched OOS evidence. Do not enable automatic live broker or exchange order transmission. Ruflo coordination/memory never substitutes for the repository promotion chain.

Never store secrets or credentials in Ruflo memory.
