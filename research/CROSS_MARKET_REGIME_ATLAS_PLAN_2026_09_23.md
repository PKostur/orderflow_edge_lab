# Cross-market regime atlas - execution plan

Protocol: `config/cross_market_regime_atlas_v1.json`

This lane is discovery-only and runs in parallel with the frozen prospective validation watches. It does not alter DON8, W1/W2, W3 or ETF H2.

## Phase A - common state map

Build a common regime table for each supported instrument using only causal information available at the observation time:

* session/time block;
* trend versus range state;
* realized volatility;
* local displacement;
* relative volume/activity where available;
* liquidity/spread efficiency where available;
* direction and timeframe.

Raw forward market behavior is measured before strategy PnL is overlaid.

## Phase B - market-specific extensions

Crypto adds BTC return/flow alignment, funding and cross-sectional state.

US ETFs add overnight gap, opening range, VWAP distance, relative volume and cash-session phase.

Gold adds cross-session transmission and source-labelled relative-value state.

ES/NQ/GC/CL add regular/extended-session state, overnight behavior, opening range and bar-based volatility/volume. Tick-order-flow claims remain blocked unless the required entitlement becomes available.

## Phase C - strategy overlay

Existing strategy families are mapped onto the frozen state cells. No strategy parameters are changed.

Primary reporting is cumulative after-cost path plus drawdown and temporal breadth. WR, EV, PF and MFE/MAE explain the path rather than replace it.

Every result retains instrument, source, timeframe and cost provenance.

## Phase D - correlation structure

For crypto, compute rolling BTC correlation from returns and report behavior by correlation quantile/group. Correlation grouping is defined from market data, not strategy PnL.

This is specifically intended to test whether the same mechanism behaves differently in BTC-following versus relatively independent coins.

## Promotion boundary

The atlas itself cannot promote anything.

A cell can only generate a hypothesis. Any later candidate must receive a new ID, fixed rule, cost model and future boundary before validation evidence is collected.

## Parallel validation

While the atlas is built:

* DON8 continues its 30-day prospective session watch.
* W1/W2 continue accumulating Asia-opening ENA microstructure evidence.
* W3 continues accumulating the frozen CVD London/New-York state.
* ETF H2 remains isolated under its existing prospective freeze.

No live or leverage authorization follows from atlas results.
