# FX Market-State v1 Status

**Current state:** two historical market-state survivors; no trading edge or candidate.

## Frozen universe and source

- EURUSD, GBPUSD, USDJPY, AUDUSD
- Massive 1-minute quote-derived forex aggregates
- 12:00-16:00 UTC, fixed 15-minute decision grid
- exact-minute fail-closed eligibility
- historical FX BBO/tick data is not entitled on the connected plan, so this lane does not make executable-PnL claims

## D0 — July 6-31, 2026

- **FXS-H1 trend-efficiency continuation:** falsified because only 56 triggers were observed versus the frozen minimum of 80. Its average directional target was positive, but the sample gate controls.
- **FXS-H2 volatility-expansion persistence:** survived D0. 107 triggers; pooled future-volatility ratio effect versus control +0.3261; all four pairs positive; both calendar halves positive.
- **FXS-H3 Bollinger-displacement reversion:** survived D0. 139 triggers; pooled signed reversion target +0.9647 bps; pooled hit rate 55.40%; all four pairs positive; both calendar halves positive in mean target.

## D3 historical holdout — August 3-28, 2026

The original freeze called this D2 non-overlap replication. The taxonomy clarification corrects the label to D3 historical holdout because it is non-overlapping history from the same source.

- **FXS-H2:** replicated. 135 triggers; pooled future-volatility ratio effect +0.6961; all four pairs positive.
- **FXS-H3:** replicated. 140 triggers; pooled signed reversion target +1.2312 bps; pooled hit rate 60.71%; all four pairs positive.
- **FXS-H1:** not inspected after its D0 failure.

## Evidence boundary

These findings support only the statement that the two frozen features identified similar future **market states** in two non-overlapping historical windows from the same data source.

They do **not** establish:

- independent-source replication;
- genuine post-freeze D4 evidence;
- executable profitability after spread/fees/slippage;
- a promoted trading candidate;
- live or leveraged trading eligibility.

Next evidence should remain state-first: independent-source or genuinely future replication and redundancy/incremental-value analysis before any strategy-PnL conditioning.
