# Cross-Market Regime Atlas v1.1

## Scope

This is the first implementation of the discovery-only Cross-Market Regime Atlas plan.

It does not modify any frozen prospective watch and does not use strategy PnL to define or rank regimes.

The first reference run uses MEXC 8h perpetual-futures bars over the already designated historical development window. The engine itself accepts generic OHLCV frames so later ETF, gold and futures adapters can use the same state vocabulary.

## State clock

A state is evaluated using information available by the close of the labeled bar. Future behavior begins after that bar close.

All instrument-relative rank states use only strictly earlier feature observations to establish their tercile boundaries.

The prefix-causality test verifies that appending later bars cannot change previously assigned state labels.

## Common states

The frozen v1.1 Phase A state map contains:

- UTC time block;
- trend efficiency state;
- realized-volatility state;
- signed three-bar displacement state;
- relative bar-activity state;
- rolling BTC-correlation state for the crypto reference track;
- current three-bar direction;
- liquidity-efficiency state.

Liquidity is explicitly `UNKNOWN` for the bar-only reference implementation. Spread or depth is never inferred from OHLCV bars.

Trend, volatility, displacement and activity states are instrument-relative causal terciles. BTC correlation uses predeclared correlation bands rather than strategy-PnL-derived thresholds.

## Raw future behavior

The atlas measures raw 1, 3 and 6 bar future behavior:

- signed return;
- absolute return;
- future high/low range;
- direction match when the current state direction is UP or DOWN.

No strategy overlay is permitted in v1.1.

## Cells

One-dimensional cells are emitted for every common state dimension.

Three interactions are predeclared before the first result:

- trend × volatility;
- displacement × volatility;
- BTC correlation × volatility.

A descriptive cell is marked sufficiently populated only with at least 30 observations and 10 distinct UTC dates.

Sparse cells are retained.

## Interpretation boundary

This atlas is a map, not a candidate selector.

It can identify where raw market behavior differs across causal states, but it cannot:

- promote a strategy;
- authorize a filter;
- claim future OOS evidence;
- authorize live trading or leverage.

Any atlas observation used for a trading rule must receive a new candidate/protocol and a later validation boundary.
