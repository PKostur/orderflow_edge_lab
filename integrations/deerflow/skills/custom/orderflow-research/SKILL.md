---
name: orderflow-research
description: Orchestrates the PKostur/orderflow_edge_lab trading-research project using specialist subagents for market-state research, validation, execution safety, reliability, and observability. Use for ENA/BTC order-flow research, DeepCharts/dxFeed integration, regime/indicator research, backtesting, paper execution safety, CI, and project refinement.
---

# Order-Flow Research Orchestrator

Use this skill for work on the `orderflow_edge_lab` automated trading research project.

Read `references/project-context.md` before making research or architecture decisions. Read `references/commands.md` before invoking repository commands. For indicator/market-condition work also read `config/regime_research_v1.json` and `docs/REGIME_RESEARCH.md` from the trading repository.

## Core operating rule

The project is research-first. Engineering correctness, attractive charts, in-sample performance, or a positive discovery batch do not establish a profitable edge.

Never claim profitability without genuine untouched out-of-sample evidence that survives realistic economics and the repository's promotion gates.

Automatic live broker/exchange order transmission remains out of scope. Do not implement or enable it unless the repository has explicit evidence for promotion, reliable paper/shadow operation, reconciliation tests, and the user explicitly approves a future live step.

## Market-state-first research

Indicator research must not start by ranking indicators on strategy profit factor.

First ask whether an indicator family helps predict a future market-state target:

- directionality versus chop;
- volatility expansion versus contraction;
- liquidity stability versus deterioration;
- continuation versus mean reversion.

Then test whether the frozen trading strategy benefits from conditioning on that state after realistic costs.

## Specialist pods

For substantial regime/indicator research, use bounded specialist tasks. Run only the roles relevant to the question and respect DeerFlow concurrency limits.

### Market-state specialists

1. **Trend / structure**: EMA state/slope, ADX, Donchian location, directional efficiency, 15m/1h agreement and transitions.
2. **Volatility**: ATR percentile, Bollinger bandwidth, realized volatility, expansion/contraction, volatility-of-volatility.
3. **Liquidity / microstructure**: spread, displayed depth, microprice, book imbalance, depth-flow, liquidity add/pull, update intensity and book quality.
4. **Aggressive flow**: CVD, signed volume ratio, trade intensity, flow acceleration, large-trade share and price/flow divergence.
5. **Mean reversion**: Bollinger/VWAP displacement, RSI, return z-score, failed breakout and exhaustion.
6. **Cross-asset**: BTC returns/volatility, flow alignment, rolling beta/correlation and lead-lag.
7. **Derivatives positioning**: funding, OI, basis/premium and liquidation context only when legitimately available at zero additional cost.
8. **Session/time**: UTC session, weekday/weekend, funding and session-transition effects.

### Economics specialists

9. **Execution economics**: spread, fees, slippage, latency, staleness, signal half-life and expected move after friction.
10. **Risk path**: MAE/MFE, stop placement, RR path, exposure caps, drawdown and risk-of-ruin diagnostics.

### Validation specialists

11. **Indicator orthogonality**: redundancy/correlation and incremental information after existing regime variables.
12. **Research validity/statistics**: discovery/validation/holdout separation, dependence, multiple testing, trial accounting and OOS claims.
13. **Transfer/generalization**: stability across independent batches, regimes and PnL-independently screened coin pairs.
14. **Data integrity**: causal eligibility, sequence/timestamp correctness, adapters and provenance.
15. **Reliability/observability**: CI, packaging, workflow failures, hashes, manifests, runtime identity and reproducibility.

## Lead-agent responsibility

The lead agent is the adversarial synthesis/release manager.

After specialist results return:

1. Reconcile contradictions using repository evidence, not voting.
2. Challenge unsupported edge claims and indicator proliferation.
3. Prefer one stable representative from highly redundant indicators.
4. Require a new feature to add incremental market-state information or have a pre-specified interaction rationale before combining it with existing variables.
5. Preserve frozen discovery-v1 and regime-research-v1 definitions unless explicitly starting a new protocol version before later evidence is inspected.
6. Keep infrastructure work secondary unless it blocks trustworthy research.
7. If implementation is appropriate, create a branch, make the smallest coherent change, run relevant tests/CI, and merge only after required checks pass.
8. If a step needs something only the user can supply, state the single smallest concrete action needed, then continue all independent work.

## Research validity rules

- Treat independent capture batches as dependence clusters.
- Cross-pair transfer is generalization evidence, not automatically OOS validation.
- Do not choose the cross-pair universe from strategy PnL.
- Do not tune indicator definitions or buckets because one batch looked attractive.
- Do not combine indicators simply because both had high PF.
- Do not weaken fees/spread/slippage assumptions to rescue an indicator.
- Already-inspected historical periods remain development data.

## DeepCharts / dxFeed priority

Prefer the user's existing DeepCharts/dxFeed access where it can provide better order-flow data at zero additional cost. When a real export is unavailable, continue public MEXC research rather than blocking the project.

Never invent dxFeed entitlements, endpoints, or fields. Audit the actual export or legitimate endpoint before using it as research evidence.

## Completion criteria

A refinement cycle is complete when it includes:

- specialist evidence;
- a lead reconciliation;
- one prioritized next action or implemented change;
- test/CI status when code changed;
- explicit research-evidence status;
- no unsupported profitability claim;
- no live-transmission enablement.
