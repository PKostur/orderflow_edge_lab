# Payoff Geometry v1

## Question

Win rate is not enough to describe a strategy whose payoff distribution may be positively skewed.

This diagnostic asks:

- when direction is correct, how far does price travel?
- when direction is wrong, how adverse is the path?
- how much of available MFE is captured?
- how long does the trade take to reach MFE?
- do those distributions change across session, alignment, side, outcome, or causal pre-entry volatility state?

The diagnostic is historical, same-period, and non-gating.

## Frozen cells

The cell set is preregistered in `config/payoff_geometry_v1.json`.

Every cell is emitted even when it has zero trades. No cells may be silently removed after results are seen.

Cell families include:

- ALL;
- correct and incorrect direction;
- long and short;
- all fixed exclusive session regimes;
- BTC prior-bar alignment;
- own prior-three-bar alignment;
- session × alignment interactions;
- causal pre-entry volatility LOW/MID/HIGH/UNKNOWN.

The volatility amendment was recorded before the first payoff-geometry diagnostic run and before any payoff-geometry result was inspected.

## Distribution reporting

For every cell the report includes p10, p25, p50, p75 and p90 for:

- net bps;
- gross bps;
- MFE;
- absolute MAE;
- gross-to-MFE capture ratio;
- winner gross-to-MFE capture ratio;
- time to MFE;
- time to MAE;
- trade duration;
- MFE / absolute-MAE ratio.

This is intended to expose payoff asymmetry even when hit rate is stable or low.

## Volatility conditioning

Pre-entry volatility is causal.

The state is based on 20-bar realized close-to-close volatility at the final completed bar before entry. It is compared with the prior 90-bar realized-volatility history and classified into terciles:

- LOW;
- MID;
- HIGH;
- UNKNOWN when history is insufficient.

No future move is used to assign the volatility cell.

## Block bootstrap

The uncertainty layer resamples 30-day non-overlapping calendar blocks.

The same bootstrap block resamples are shared across strategies and cells within each cost case. Trades across symbols and strategies that occur in the same block therefore remain grouped instead of being treated as independent draws.

Intervals are descriptive. They do not create a promotion gate.

## Multiple testing

This diagnostic does not select the best cell.

Any later claim that changes filtering, candidate selection, promotion or deployment requires a new frozen protocol and should use appropriate data-snooping controls. The preregistered reserved methods are:

- White's Reality Check;
- Hansen SPA;
- Deflated Sharpe Ratio;
- Probability of Backtest Overfitting.

They are not used here to rescue a strategy after looking at the diagnostic.

## Interpretation

A low win rate is not rejected on hit rate alone when payoff geometry is asymmetric. Of particular interest are cells where:

- win rate is similar;
- MFE distribution shifts materially upward;
- MAE does not worsen proportionally;
- capture remains stable or improves;
- the cumulative economic path remains realistic.

Crypto/session backtests remain weak same-period evidence and are treated as hypothesis-generating only.

No result from this report authorizes a strategy filter, live trading or leverage.
