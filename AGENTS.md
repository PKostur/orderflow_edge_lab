# Orderflow Edge Lab Agent Contract

This repository uses three cooperating layers. Keep their responsibilities separate.

## Orchestration hierarchy

1. **Ruflo meta-harness** coordinates agent memory, task routing, swarm state, handoffs, and harness-level adversarial checks.
2. **DeerFlow `orderflow-research`** supplies the domain-specific trading-research context and specialist decomposition.
3. **`orderflow_edge_lab`** is the executable source of truth for market data, backtests, statistics, risk, promotion, paper execution, CI, and evidence artifacts.

Ruflo and DeerFlow may coordinate or recommend work. They do not override repository evidence or safety gates.

## Before substantial work

When Ruflo is available:

1. Search Ruflo memory for relevant patterns, experiments, failures, and prior decisions.
2. Read the DeerFlow project context under `integrations/deerflow/skills/custom/orderflow-research/references/`.
3. Read `config/regime_research_v1.json` and `docs/REGIME_RESEARCH.md` for market-condition/indicator work.
4. Inspect current repository state and latest research artifacts.
5. Use the smallest specialist pod that covers the question. Do not spawn every specialist merely because they exist.

If Ruflo is unavailable, continue with the repository and DeerFlow guidance rather than blocking the work.

## Specialized research pods

Multiple specialists may read the same evidence, but never allow two writers to modify the same worktree concurrently.

### Market-state pod

- **trend-structure researcher**: EMA20/50 state and slope, ADX, Donchian position, directional efficiency, 15m/1h alignment, trend/range transitions.
- **volatility-regime researcher**: ATR percentile, Bollinger bandwidth, realized volatility, expansion/contraction, volatility-of-volatility, range versus spread.
- **liquidity-microstructure researcher**: spread, displayed depth, microprice, book imbalance, depth-flow, quote update intensity, add/pull behavior, stale/crossed-book quality.
- **aggressive-flow researcher**: CVD, signed volume ratio, trade intensity, flow acceleration, large-trade share, price/CVD divergence.
- **mean-reversion researcher**: Bollinger/VWAP displacement, RSI, return z-score, failed breakout, exhaustion versus continuation.
- **cross-asset researcher**: BTC returns/volatility, flow alignment, rolling correlation/beta, lead-lag, idiosyncratic versus beta-driven altcoin moves.
- **news-event researcher**: public headline timing, conservative coin attribution, source provenance, and subsequent coin/BTC behavior as observational context only.
- **derivatives-positioning researcher**: funding, OI change, premium/basis and liquidation information only when legitimately available through zero-additional-cost/public or already-owned data.
- **session researcher**: UTC hour/session, weekday/weekend, funding-window proximity and session-transition effects.

### Economics pod

- **execution-economics researcher**: spread/fee/slippage/latency/staleness burden, signal half-life, expected move after friction, market-impact assumptions.
- **risk-path researcher**: MAE/MFE, stop placement, RR path, exposure cap, drawdown, risk-of-ruin and original-versus-reversed comparisons.

### Validation pod

- **indicator-orthogonality researcher**: redundancy/correlation among indicators, incremental information after existing regime variables, interaction justification.
- **research-validity researcher**: discovery/validation/holdout separation, dependence clustering, multiple testing, trial accounting, frozen definitions and OOS claims.
- **transfer-generalization researcher**: stability across independent batches, regimes and PnL-independently screened coin pairs.
- **data-integrity researcher**: adapters, sequence continuity, timestamps, causality, provenance and feature eligibility.
- **reliability/CI tester**: unit/integration tests, packaging, Linux/Windows CI, workflow failure paths and upstream compatibility.
- **observability reviewer**: hashes, logs, manifests, runtime identity and reproducibility.

### Lead / coordinator

The lead is the adversarial synthesis and release manager. It reconciles specialist findings using evidence rather than voting, challenges indicator proliferation, and blocks promotion when the claimed effect is not economically or statistically supported.

## Market-state research principle

Indicator research must separate **prediction of future market state** from **strategy PnL**.

First ask whether a feature helps identify a future state such as directionality, volatility expansion/contraction, liquidity deterioration, or continuation versus mean reversion. Only afterward ask whether the frozen trading strategy improves PF/net expectancy when conditioned on that state.

Do not select an indicator merely because it has the highest in-sample PF.

## Current research rules

- Preserve frozen `discovery-v1` thresholds. Do not retune them batch by batch.
- Treat independent capture batches as the primary dependence clusters.
- Preserve the pre-registered `regime-research-v1` feature families/targets unless explicitly starting a new version before viewing later evidence.
- Market-condition findings are exploratory until they meet the pre-registered readiness gate.
- Cross-pair results are transfer evidence, not untouched OOS evidence for ENA-discovered conditions.
- A BTC-correlation-diversified pair panel may be used only after the existing PnL-independent market-compatibility screen; correlation selection must not inspect strategy PnL.
- Public news/event monitoring is development-only observational context. Do not infer causality from event timing, retune `discovery-v1` from news outcomes, or make news a strategy filter unless a separate specification is frozen before later validation data is inspected.
- The remembered 15m EMA20/50 TradingView result remains an already-inspected development hypothesis, not verified OOS evidence.
- Risk discussions should prefer the stop-based MAE/MFE experiment over raw leverage.
- Realistic spread, fees, slippage, latency/freshness and failure assumptions must not be weakened to improve results.
- Prefer one stable representative from highly redundant indicator clusters.
- Combine indicators only when there is incremental predictive information or a pre-specified interaction rationale.

## Evidence and release gates

A change may merge only after the relevant tests pass and the deterministic `orderflow-multi-agent` report is `reviewable`. Treat the internal release-manager status as a real gate, not merely the GitHub workflow conclusion.

A strategy may not be called profitable without genuine untouched out-of-sample evidence. Promotion must preserve candidate freeze, holdout audit, trial-ledger accounting, economics policy, approval-bound paper/shadow reliability, and reconciliation evidence.

## Live execution boundary

Automatic live broker or exchange order transmission remains disabled. Do not add, enable, or route around this boundary unless explicit promotion criteria are met and the user separately approves a future live-execution step.

## Ruflo memory policy

Store distilled reusable lessons only after evidence exists. Suggested namespaces:

- `orderflow/patterns`
- `orderflow/experiments`
- `orderflow/failures`
- `orderflow/decisions`
- `orderflow/regimes`
- `orderflow/indicators`

Never store API keys, exchange credentials, passwords, account identifiers, secret-bearing `.env` content, or other sensitive values in Ruflo memory.

## Execution rule

Ruflo coordinates. The active coding agent executes the actual repository work, tests, branches, CI inspection, and evidence generation. Never stop after creating a Ruflo task or swarm record and assume the work has been performed.
