# Universal session alignment prospective shadow

## Freeze boundary

The research question was frozen in commit `5415416440430bce912123694e8965e671326423` before the prospective start at `2026-09-24T00:00:00Z`.

The watch uses the unchanged DON8, EMA8, and VOL8 strategy definitions, the same ten MEXC futures symbols, canonical accounting version 2, and a 20 bps round-trip cost assumption.

No entry before the prospective boundary can contribute to prospective evidence. A strategy episode still open at the end of a data snapshot is retained only as a terminal snapshot and is excluded from completed-trade scoring.

## Observational labels

Every original strategy trade is retained. The watch only adds these frozen labels at entry:

- exclusive session regime from the existing daylight-saving-aware Asia, London, and New York definitions;
- BTC prior-bar direction alignment;
- own prior-three-bar direction alignment.

The labels do not alter targets, entries, exits, symbols, costs, or position size.

## Frozen comparisons

The prospective report records these comparisons without an early verdict:

- DON8, EMA8, and VOL8: `ASIA+LONDON` versus `LONDON+NEW_YORK` exclusive session regime;
- DON8: BTC prior-bar `ALIGNED` versus `AGAINST`;
- EMA8: own prior-three-bar `ALIGNED` versus `AGAINST`;
- EMA8 secondary diagnostic: BTC prior-bar `ALIGNED` versus `AGAINST`;
- VOL8: own prior-three-bar `ALIGNED` versus `AGAINST`.

The recorded metrics are equal-weight symbol-sleeve completed-trade return, its exit-by-exit equity curve and portfolio-consistent maximum drawdown, median observed-symbol compounded return, positive-symbol fraction, expectancy, win rate, profit factor, correct-direction rate, correct-direction MFE, and a pooled completed-trade sequence drawdown diagnostic. The pooled trade-sequence drawdown remains descriptive and is not treated as the portfolio drawdown.

## Pre-start accounting clarification

Before the prospective boundary, the cumulative-return implementation was corrected so overlapping trades from different symbols are not compounded as if they occurred sequentially in one account. Each frozen symbol receives an equal 10% initial capital sleeve. Completed post-start trades compound only inside their own symbol sleeve, and inactive sleeves remain cash. Factor-state comparisons use per-symbol compounded returns, including their median across observed symbols, rather than constructing a filtered cross-symbol portfolio.

This clarification changes only reporting semantics. It does not change any frozen hypothesis, strategy parameter, signal, entry, exit, session definition, alignment definition, cost assumption, or symbol.

## Review rule

No formal pass or fail is permitted until both conditions hold for every strategy:

1. at least 30 calendar days have elapsed since the prospective start;
2. at least 20 completed post-start trades exist for that strategy across the frozen symbol universe.

If either requirement is missing, status remains `ACCUMULATING`.

## Evidence progress

The report also exposes non-gating accumulation diagnostics so early shadow growth can be inspected without changing the review rule:

- completed post-start trade count and still-open post-start episode count per strategy;
- completed-symbol coverage across the frozen ten-symbol universe;
- first and latest completed post-start entry timestamps;
- calendar-day and completed-trade progress fractions toward the existing review gate;
- aligned and comparison-state trade counts for each frozen hypothesis;
- symbols represented in each state and the count of symbols that have observed both states.

These fields are descriptive only. They do not add a new minimum sample rule and do not permit an early verdict.

## Operational note

The GitHub workflow runs at 00:25, 08:25, and 16:25 UTC once the workflow is present on the default branch. While PR #113 remains draft, prospective integrity is still preserved because the source is public historical 8h kline data and the hypothesis definition commit predates all scored entries. The future sample can therefore be reconstructed from MEXC without retroactively changing the frozen rules.

This watch is research-only. It does not authorize a session filter, strategy promotion, leverage, or live trading.
