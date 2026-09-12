# Specialized Market-Regime Research

The project now separates **market-state prediction** from **strategy profitability**.

This is intentional. If the same metric is used both to discover a condition and to judge whether the strategy profits from it, indicator research can quietly become PnL mining. The deeper research loop therefore asks two questions in order:

1. Does an indicator or feature family help identify a future market state?
2. Conditional on that state, does the frozen strategy improve net executable expectancy after spread, fees and other stated costs?

The pre-registered feature/target catalog is `config/regime_research_v1.json`.

## Research pods

### Market-state pod

These specialists describe the environment before judging strategy returns.

- **Trend / structure specialist**: EMA state and slope, ADX, Donchian location, directional efficiency, multi-timeframe agreement.
- **Volatility specialist**: ATR percentile, Bollinger bandwidth, realized volatility, expansion/contraction, volatility-of-volatility.
- **Liquidity specialist**: spread, displayed depth, update intensity, depth-flow, add/pull behavior, stale/crossed-book quality.
- **Aggressive-flow specialist**: CVD, signed volume, trade intensity, acceleration, large-trade share, price/flow divergence.
- **Mean-reversion specialist**: Bollinger/VWAP displacement, RSI, return z-score, failed-breakout/exhaustion behavior.
- **Cross-asset specialist**: BTC returns, volatility, beta/correlation, lead-lag, BTC order-flow agreement.
- **Derivatives-positioning specialist**: funding, OI change, premium/basis and liquidation information only when legitimately available at zero additional cost.
- **Session specialist**: hour/session, weekday/weekend, funding-window proximity and session-transition effects.

### Economics pod

- **Execution-economics specialist**: determines whether predictive information is large enough to survive spread, fees, slippage, latency and staleness.
- **Risk-path specialist**: MAE/MFE, stop placement, target path, exposure caps, drawdown and risk-of-ruin diagnostics.

### Validation pod

- **Indicator-orthogonality specialist**: detects redundant indicator families and asks whether a new feature adds incremental information after existing conditions.
- **Statistical-validity specialist**: dependence clustering, multiple testing, freeze/holdout/trial accounting and OOS claim control.
- **Transfer/generalization specialist**: checks stability across independent batches, market regimes and other PnL-independently screened coin pairs.
- **Adversarial synthesis lead**: reconciles the pods and can block promotion even when a headline PF looks attractive.

## Market-state targets

The initial targets are deliberately strategy-independent:

- **Directionality**: future directional efficiency and signed move.
- **Volatility**: future realized range/volatility versus a causal trailing baseline.
- **Liquidity**: future spread/depth quality and deterioration.
- **Continuation vs reversion**: whether an existing displacement persists or mean-reverts.

A feature should first demonstrate stable information about one of these states. Only then should we ask whether the trading strategy benefits from conditioning on it.

## Indicator families

The v1 catalog covers:

- multi-timeframe EMA / trend strength / directional efficiency;
- ATR and Bollinger-width volatility state;
- spread/depth/microprice/depth-flow liquidity state;
- CVD and aggressive-flow acceleration;
- Bollinger/VWAP/RSI-style mean-reversion state;
- BTC return, flow, beta, correlation and lead-lag context;
- derivatives positioning where the data is legitimately available;
- time/session effects;
- execution economics.

The purpose is not to maximize the number of indicators. The purpose is to test distinct explanatory families and remove redundant ones.

## Combination policy

Do not combine indicators because two individually had high PF.

A combination is justified only when at least one of the following holds:

1. the second feature adds measurable incremental information about the future market-state target after conditioning on the first;
2. the interaction was pre-specified for a microstructure reason;
3. the feature belongs to a clearly different causal family, for example trend state plus liquidity quality rather than two moving-average variants.

When two indicators are highly redundant, prefer the simpler and more stable one.

## Evidence progression

```text
feature family
    -> future market-state prediction
    -> independent-batch stability
    -> incremental value / redundancy check
    -> frozen condition hypothesis
    -> strategy conditional-PF/net-expectancy test
    -> cross-pair transfer
    -> candidate freeze
    -> later untouched validation
```

Cross-pair transfer is useful for generalization but is not automatically OOS validation of a condition discovered on ENA.

## Current economic gate

For a condition to influence pair/strategy selection it must currently have, at minimum:

- 20 observations;
- 3 independent capture batches;
- positive net expectancy after the stated costs;
- net PF above 1;
- positive net expectancy in at least two thirds of contributing batches.

Those minimums are screening gates, not proof of an edge.

## Research priorities

The initial deeper-research order is:

1. liquidity/microstructure state versus short-horizon directionality;
2. volatility expansion versus signal half-life and cost hurdle;
3. trend/range classification using HTF structure without unfinished candles;
4. BTC beta/lead-lag versus idiosyncratic altcoin behavior;
5. order-flow continuation/exhaustion versus mean-reversion indicators;
6. derivatives-positioning context if the public/existing data source is reliable;
7. interactions only after the individual families are understood.

This ordering keeps the project focused on explanatory market state instead of uncontrolled indicator search.
