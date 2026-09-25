# Payoff Geometry Forward v1

This is a new prospective structural-replication watch generated from the historical non-gating Payoff Geometry v1 diagnostic.

It does not modify the existing universal session/alignment shadow.

## Prospective boundary

The hypotheses were frozen before the new boundary:

`2026-09-25T16:00:00Z`

Historical results before that boundary do not count toward this watch.

## Primary question

For each unchanged strategy—DON8, EMA8 and VOL8—does the median MFE of completed trades entered in a causal HIGH pre-entry volatility state exceed the median MFE of completed trades entered in a LOW state?

The question concerns payoff travel, not strategy profitability.

## Volatility state

The label is observational only:

- 20-bar close-to-close realized volatility;
- calculated at the final completed bar before canonical entry;
- ranked against the preceding 90-bar realized-volatility history;
- LOW / MID / HIGH terciles;
- UNKNOWN retained when history is insufficient.

No trade is filtered or skipped because of the label.

## Review gate

Formal review remains withheld until, for every strategy:

- at least 30 calendar days have elapsed;
- at least 20 completed post-start trades exist;
- at least 8 HIGH-state completed trades exist;
- at least 8 LOW-state completed trades exist.

Even when the gate is met, the watcher reports `READY_FOR_REVIEW`, not an automatic pass/fail.

## Secondary diagnostics

The watcher records MFE/MAE/capture/time-to-MFE distributions, correct-direction rate and expectancy to explain the primary magnitude comparison.

They remain secondary diagnostics and do not authorize a volatility filter.

## Evidence boundary

The watch cannot authorize:

- strategy promotion;
- a volatility filter;
- live trading;
- leverage.

Any later trading rule based on volatility would require its own frozen candidate and independent validation.
