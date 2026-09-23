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

The recorded metrics are completed-trade compounded return, expectancy, win rate, profit factor, correct-direction rate, correct-direction MFE, and completed-trade sequence drawdown.

## Review rule

No formal pass or fail is permitted until both conditions hold for every strategy:

1. at least 30 calendar days have elapsed since the prospective start;
2. at least 20 completed post-start trades exist for that strategy across the frozen symbol universe.

If either requirement is missing, status remains `ACCUMULATING`.

## Operational note

The GitHub workflow runs at 00:25, 08:25, and 16:25 UTC once the workflow is present on the default branch. While PR #113 remains draft, prospective integrity is still preserved because the source is public historical 8h kline data and the hypothesis definition commit predates all scored entries. The future sample can therefore be reconstructed from MEXC without retroactively changing the frozen rules.

This watch is research-only. It does not authorize a session filter, strategy promotion, leverage, or live trading.
